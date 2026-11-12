// Read-only git evidence: head, branch, base, tracked-change fingerprint, untracked fingerprint.
// Never stages, commits, stashes, writes objects or takes the index lock; never runs a clean filter.
// The tracked fingerprint covers, per changed path, the worktree content (regular files via
// hash-object, symlinks by target, gitlinks by submodule HEAD, other types by a marker), the raw
// HEAD/index diffs (modes, index and gitlink ids, status letters) and, for each initialised
// submodule whose own worktree is dirty, its status and the content of its changed files.
import { createHash } from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import type { GitEvidence } from "./types.ts";
import { run } from "./exec.ts";
import { redactPath } from "./redact.ts";

const TOTAL_DEADLINE_MS = 20_000;
const CALL_TIMEOUT_MS = 10_000;
const MERGE_BASE_TIMEOUT_MS = 5_000;
const MAX_PATHS = 200;
const MAX_HASHED = 5000;
const MAX_STDOUT = 8 * 1024 * 1024;
const MAX_SUBMODULE_PROBES = 64;
const SUBMODULE_TIMEOUT_MS = 5_000;
/** Initialised submodules whose own worktree is scanned for dirt (status + changed-file content). */
const MAX_SUBMODULE_SCANS = 16;
/** rev-parse probes of gitlinks that turn out not to be initialised; a separate, larger budget. */
const MAX_SUBMODULE_UNINIT_PROBES = 256;
/** `ls-files --stage` lists every index entry; room for roughly 700k paths. */
const GITLINK_SCAN_MAX_STDOUT = 64 * 1024 * 1024;
/** hash-object takes its paths by argv in chunks of at most this many bytes or paths. */
const HASH_ARGV_BYTES = 64 * 1024;
const HASH_ARGV_PATHS = 1000;

/** Filter driver names in `git config --get-regexp -z ^filter\.` output. */
function filterNames(out: string): string[] {
  const names = new Set<string>();
  for (const entry of out.split("\0")) {
    const key = entry.split("\n")[0] ?? "";
    const m = /^filter\.(.+)\.(clean|smudge|process|required)$/i.exec(key);
    if (m) names.add(m[1]!);
  }
  return [...names];
}

function blankFilters(names: Iterable<string>): string[] {
  const out: string[] = [];
  for (const n of names) {
    out.push("-c", `filter.${n}.clean=`, "-c", `filter.${n}.process=`, "-c", `filter.${n}.smudge=`, "-c", `filter.${n}.required=false`);
  }
  return out;
}

/** A path below a symlinked (or otherwise non-directory) parent, relative to `root`; cached per directory. */
function makeBeyondSymlink(root: string): (rel: string) => boolean {
  const parentIsLink = new Map<string, boolean>();
  return (rel: string): boolean => {
    const segs = rel.split("/");
    let acc = "";
    for (let i = 0; i < segs.length - 1; i++) {
      acc = acc ? `${acc}/${segs[i]}` : segs[i]!;
      let bad = parentIsLink.get(acc);
      if (bad === undefined) {
        try {
          bad = !fs.lstatSync(path.join(root, acc)).isDirectory();
        } catch {
          bad = false; // missing parent: the lstat of the path itself reports it deleted
        }
        parentIsLink.set(acc, bad);
      }
      if (bad) return true;
    }
    return false;
  };
}

interface GitResult {
  ok: boolean;
  out: string;
  raw: Buffer;
  /** Why the call failed (null on success): timeout, deadline, overflow or exit-N. */
  why: string | null;
}

function emptyEvidence(): GitEvidence {
  return {
    capturedAt: new Date().toISOString(),
    repoTop: null,
    isLinkedWorktree: null,
    branch: null,
    head: null,
    base: null,
    trackedFingerprint: null,
    trackedChanged: null,
    trackedPaths: [],
    untrackedCount: null,
    untrackedPaths: [],
    untrackedFingerprint: null,
    truncated: false,
    errors: [],
  };
}

export async function gitEvidence(cwd: string, signal?: AbortSignal): Promise<GitEvidence> {
  const ev = emptyEvidence();
  const deadline = AbortSignal.timeout(TOTAL_DEADLINE_MS);
  const sig = signal ? AbortSignal.any([signal, deadline]) : deadline;
  // Clean/process filter drivers configured in the repo are blanked per call, so a stat-dirty file
  // never makes git spawn a driver (`--no-filters` covers hash-object only).
  let filterOverrides: string[] = [];

  const git = async (
    label: string,
    root: string,
    args: string[],
    opts: { timeoutMs?: number; input?: string; quietFail?: boolean; extraConfig?: string[]; maxBuffer?: number } = {},
  ): Promise<GitResult> => {
    const argv = [
      "--no-optional-locks",
      "-c", "core.fsmonitor=false",
      "-c", "core.untrackedCache=false",
      "-c", "core.hooksPath=/dev/null",
      ...filterOverrides,
      ...(opts.extraConfig ?? []),
      "-C", root,
      ...args,
    ];
    const r = await run("git", argv, {
      cwd: root,
      timeoutMs: opts.timeoutMs ?? CALL_TIMEOUT_MS,
      signal: sig,
      maxBuffer: opts.maxBuffer ?? MAX_STDOUT,
      input: opts.input,
    });
    const why = r.code === 0 ? null : r.timedOut ? "timeout" : r.aborted ? "deadline" : r.overflow ? "overflow" : `exit-${r.code}`;
    if (why && !opts.quietFail) ev.errors.push(`${label}:${why}`);
    return { ok: r.code === 0, out: r.stdout.toString("utf8"), raw: r.stdout, why };
  };

  // Blob ids of regular files under `root`, in order; null (with an error recorded) when any one
  // could not be hashed. Paths go by argv after `--`, never through `--stdin-paths`: that reads one
  // path per line, C-unquotes a line starting with `"` and drops a trailing CR, so a name holding a
  // newline, a leading quote or a trailing CR would be hashed as some other file, or not at all.
  const hashFiles = async (label: string, root: string, paths: string[], extraConfig: string[] = [], timeoutMs?: number): Promise<string[] | null> => {
    const ids: string[] = [];
    let i = 0;
    while (i < paths.length) {
      const chunk: string[] = [];
      let bytes = 0;
      while (i < paths.length && chunk.length < HASH_ARGV_PATHS && (chunk.length === 0 || bytes + Buffer.byteLength(paths[i]!) + 1 <= HASH_ARGV_BYTES)) {
        bytes += Buffer.byteLength(paths[i]!) + 1;
        chunk.push(paths[i]!);
        i++;
      }
      const h = await git(label, root, ["hash-object", "--no-filters", "--", ...chunk], { extraConfig, timeoutMs });
      if (!h.ok) return null;
      const lines = h.out.split("\n").filter((l) => l.length > 0);
      if (lines.length !== chunk.length || !lines.every((l) => /^[0-9a-f]{40}([0-9a-f]{24})?$/.test(l))) {
        ev.errors.push(`${label}:unparsed`);
        return null;
      }
      ids.push(...lines);
    }
    return ids;
  };

  // 1. toplevel (separate: must survive an unborn HEAD)
  const top = await git("show-toplevel", cwd, ["rev-parse", "--show-toplevel"], { quietFail: true });
  if (!top.ok) {
    ev.errors.push("not-a-repo");
    return ev;
  }
  const toplevel = top.out.trim();
  ev.repoTop = toplevel;

  // 2. linked worktree?
  const gd = await git("git-dir", toplevel, ["rev-parse", "--git-dir", "--git-common-dir"]);
  if (gd.ok) {
    const [gitDir, common] = gd.out.split("\n");
    if (gitDir && common) {
      try {
        const a = fs.realpathSync(path.resolve(toplevel, gitDir));
        const b = fs.realpathSync(path.resolve(toplevel, common));
        ev.isLinkedWorktree = a !== b;
      } catch {
        ev.errors.push("git-dir:realpath");
      }
    }
  }

  // 3. head (unborn -> null, not an error)
  const head = await git("head", toplevel, ["rev-parse", "--verify", "-q", "HEAD"], { quietFail: true });
  if (head.ok) ev.head = head.out.trim() || null;

  // 4. branch (detached -> null)
  const br = await git("branch", toplevel, ["symbolic-ref", "-q", "--short", "HEAD"], { quietFail: true });
  if (br.ok) ev.branch = br.out.trim() || null;

  // 5. base via origin/HEAD
  if (ev.head) {
    const oh = await git("origin-head", toplevel, ["symbolic-ref", "-q", "refs/remotes/origin/HEAD"], { quietFail: true });
    const ref = oh.ok ? oh.out.trim() : "";
    if (ref) {
      const mb = await git("merge-base", toplevel, ["merge-base", "HEAD", ref], { timeoutMs: MERGE_BASE_TIMEOUT_MS });
      const sha = mb.ok ? mb.out.trim() : "";
      if (sha) ev.base = { ref: ref.replace(/^refs\/remotes\//, ""), sha, method: "merge-base-origin-head" };
    }
  }

  // Blank configured filter drivers (read config only; runs nothing).
  const topFilters = new Set<string>();
  // Names only (`--name-only`): a huge dummy `filter.*` value cannot push real driver names past
  // the stdout cap. Only exit 0 (parsed) or exit 1 with empty output (no matches) is success; any
  // other result fails closed below (null fingerprint, no diff, no hash-object).
  const discoverFilters = async (label: string, root: string, timeoutMs?: number): Promise<string[] | null> => {
    const r = await git(label, root, ["config", "--name-only", "--get-regexp", "-z", "^filter\\."], { quietFail: true, timeoutMs });
    if (r.ok) return filterNames(r.out);
    if (r.why === "exit-1" && r.raw.length === 0) return [];
    ev.errors.push(`${label}:failed`);
    return null;
  };
  const topDiscovered = await discoverFilters("filter-discovery", toplevel);
  for (const n of topDiscovered ?? []) topFilters.add(n);
  // A driver name containing `=` cannot be blanked through `-c` argv (git splits at the first `=`),
  // and exec.ts offers no env option: fail closed, run no diff that could spawn the driver.
  const unsafeName = (n: string) => n.includes("=") || /[\0\n\r]/.test(n);
  const unsafeTop = [...topFilters].some(unsafeName);
  if (unsafeTop) ev.errors.push("filter-name:unsafe");
  filterOverrides = blankFilters(topFilters);

  // 6. tracked changes: union of (worktree vs HEAD) and (index vs HEAD).
  // `--no-renames`: rename detection would list only the new side of a staged rename, so restoring
  // the old path would leave the list and the fingerprint unchanged. `--ignore-submodules=dirty`:
  // a gitlink whose submodule HEAD moved is listed; edits inside a submodule's own tree are found
  // by step 6b instead, because `=none` would make git run `status` inside each submodule with
  // that submodule's own filter drivers, which are not blanked here.
  const changed = new Set<string>();
  let trackedOk = !unsafeTop && topDiscovered !== null;
  const splitZ = (s: string) => s.split("\0").filter((x) => x.length > 0);
  const common = ["-z", "--no-renames", "--ignore-submodules=dirty", "--no-ext-diff", "--no-textconv"];
  if (trackedOk && ev.head) {
    const d = await git("diff", toplevel, ["diff", "--name-only", ...common, "HEAD"]);
    if (d.ok) for (const p of splitZ(d.out)) changed.add(p);
    else trackedOk = false;
  }
  if (trackedOk) {
    const dc = await git("diff-cached", toplevel, ["diff", "--cached", "--name-only", ...common]);
    if (dc.ok) for (const p of splitZ(dc.out)) changed.add(p);
    else trackedOk = false;
  }

  // Raw diffs carry modes (chmod, file<->symlink, gitlink) and the HEAD and index object ids
  // (staged content, gitlink commits). `--no-abbrev`: an abbreviated id grows with the object
  // count, which would move the fingerprint with no change to the tree.
  const rawLines: string[] = [];
  const foldRaw = (tag: string, out: string, dropNewSha: boolean) => {
    const parts = out.split("\0");
    for (let i = 0; i + 1 < parts.length; i += 2) {
      const meta = parts[i]!;
      const p = parts[i + 1]!;
      if (!meta.startsWith(":")) {
        trackedOk = false;
        ev.errors.push(`${tag}:unparsed`);
        return;
      }
      const f = meta.slice(1).split(" ");
      // The worktree side's id is 0{40} or the index id depending on stat state; the worktree
      // content itself is hashed below, so that id is left out.
      if (dropNewSha && f.length >= 5) f[3] = "-";
      rawLines.push(`${tag}\0${f.join(" ")}\0${p}`);
    }
  };
  if (trackedOk && ev.head) {
    const r = await git("diff-raw", toplevel, ["diff", "--raw", "--no-abbrev", ...common, "HEAD"]);
    if (r.ok) foldRaw("W", r.out, true);
    else trackedOk = false;
  }
  if (trackedOk) {
    const r = await git("diff-cached-raw", toplevel, ["diff", "--cached", "--raw", "--no-abbrev", ...common]);
    if (r.ok) foldRaw("I", r.out, false);
    else trackedOk = false;
  }

  const beyondSymlink = makeBeyondSymlink(toplevel);

  // 6b. Dirty submodule worktrees (adversary round 2, N2). Every gitlink in the index whose
  // directory is an initialised repository of its own gets a hardened `status` there, with that
  // submodule's filter drivers blanked too. A dirty one joins the changed paths, and its status plus
  // the content of its changed files (untracked ones by stat, as in step 7) are folded in. A nested
  // submodule (depth 2) is not scanned: one whose commit moved sets `truncated`. Any failure nulls
  // the tracked fingerprint.
  const subDigests = new Map<string, string>();
  if (trackedOk) {
    const ls = await git("gitlinks", toplevel, ["ls-files", "-z", "--stage"], { maxBuffer: GITLINK_SCAN_MAX_STDOUT });
    if (!ls.ok) trackedOk = false;
    const links = new Set<string>();
    if (ls.ok) {
      for (const e of splitZ(ls.out)) {
        const tab = e.indexOf("\t");
        if (tab > 0 && e.startsWith("160000 ")) links.add(e.slice(tab + 1));
      }
    }
    let scans = 0;
    let uninit = 0;
    for (const link of [...links].sort()) {
      if (!trackedOk) break;
      const abs = path.join(toplevel, link);
      if (beyondSymlink(link)) continue; // listed by the diffs as deleted
      let st: fs.Stats;
      try {
        st = fs.lstatSync(abs);
      } catch {
        continue; // deleted: listed by the diffs
      }
      if (!st.isDirectory()) continue; // replaced by a file or symlink: listed by the diffs
      if (uninit >= MAX_SUBMODULE_UNINIT_PROBES) {
        ev.truncated = true;
        ev.errors.push("submodule-uninit:limit");
        break;
      }
      const tl = await git("submodule-dirty", abs, ["rev-parse", "--show-toplevel"], { timeoutMs: SUBMODULE_TIMEOUT_MS });
      if (!tl.ok) {
        trackedOk = false; // a broken gitfile: its worktree cannot be read as a repository
        break;
      }
      let own = false;
      try {
        own = fs.realpathSync(tl.out.trim()) === fs.realpathSync(abs);
      } catch {
        own = false;
      }
      if (!own) {
        uninit++; // uninitialised: an empty directory of this repo, covered by step 7
        continue;
      }
      if (scans >= MAX_SUBMODULE_SCANS) {
        ev.truncated = true;
        ev.errors.push("submodule-dirty:limit");
        break;
      }
      scans++;
      // The submodule's own filter drivers (its config may define ones this repo does not).
      const sc = await discoverFilters("submodule-filter-discovery", abs, SUBMODULE_TIMEOUT_MS);
      if (sc === null) {
        trackedOk = false;
        break;
      }
      const subNames = sc.filter((n) => !topFilters.has(n));
      if (subNames.some(unsafeName)) {
        ev.errors.push("filter-name:unsafe");
        trackedOk = false;
        break;
      }
      const extra = blankFilters(subNames);
      const s = await git(
        "submodule-status",
        abs,
        ["status", "--porcelain=v2", "-z", "--untracked-files=all", "--ignore-submodules=dirty", "--no-renames"],
        { timeoutMs: SUBMODULE_TIMEOUT_MS, extraConfig: extra },
      );
      if (!s.ok) {
        trackedOk = false;
        break;
      }
      if (s.raw.length === 0) continue; // clean
      const entries = splitZ(s.out);
      const parsed: Array<{ tracked: boolean; p: string }> = [];
      for (const e of entries) {
        let m: RegExpExecArray | null;
        if ((m = /^1 (\S\S) (\S{4}) (?:\S+ ){5}(.+)$/s.exec(e))) {
          if (m[2]!.startsWith("S")) {
            ev.truncated = true; // a nested submodule's commit moved; its own worktree is not scanned
            if (!ev.errors.includes("submodule-dirty:nested")) ev.errors.push("submodule-dirty:nested");
            continue;
          }
          parsed.push({ tracked: true, p: m[3]! });
        } else if ((m = /^u (\S\S) (\S{4}) (?:\S+ ){7}(.+)$/s.exec(e))) {
          parsed.push({ tracked: true, p: m[3]! });
        } else if (e.startsWith("? ") && e.length > 2) {
          parsed.push({ tracked: false, p: e.slice(2) });
        } else {
          ev.errors.push("submodule-status:unparsed");
          trackedOk = false;
          break;
        }
      }
      if (!trackedOk) break;
      let limited = parsed;
      if (limited.length > MAX_HASHED) {
        limited = limited.slice(0, MAX_HASHED);
        ev.truncated = true;
      }
      const subBeyond = makeBeyondSymlink(abs);
      const detail = new Map<string, string>();
      const toHashSub: string[] = [];
      for (const { tracked, p } of limited) {
        const pAbs = path.join(abs, p);
        if (subBeyond(p)) {
          detail.set(p, "beyond-symlink");
          continue;
        }
        let pst: fs.Stats;
        try {
          pst = fs.lstatSync(pAbs);
        } catch {
          detail.set(p, "deleted");
          continue;
        }
        if (!tracked) detail.set(p, `u:${pst.size}:${pst.mtimeMs}`); // untracked: stat only, never content
        else if (pst.isSymbolicLink()) {
          try {
            detail.set(p, `l:${createHash("sha256").update(fs.readlinkSync(pAbs, { encoding: "buffer" })).digest("hex")}`);
          } catch {
            detail.set(p, "l:unreadable");
          }
        } else if (pst.isFile()) {
          detail.set(p, pst.mode & 0o111 ? "fx" : "f-");
          toHashSub.push(p);
        } else {
          detail.set(p, pst.isDirectory() ? "dir" : "type:other");
        }
      }
      if (toHashSub.length > 0) {
        const ids = await hashFiles("submodule-hash-object", abs, toHashSub, extra, SUBMODULE_TIMEOUT_MS);
        if (!ids) {
          trackedOk = false;
          break;
        }
        toHashSub.forEach((p, k) => detail.set(p, `${detail.get(p)}:${ids[k]}`));
      }
      const h = createHash("sha256").update(s.raw);
      for (const { p } of limited) h.update(`\0${p}\0${detail.get(p)}`);
      subDigests.set(link, h.digest("hex"));
      changed.add(link);
    }
  }

  if (trackedOk) {
    const sorted = [...changed].sort();
    ev.trackedChanged = sorted.length;
    ev.trackedPaths = sorted.slice(0, MAX_PATHS).map(redactPath);
    if (sorted.length > MAX_PATHS) ev.truncated = true;
    let hashed = sorted;
    if (hashed.length > MAX_HASHED) {
      hashed = hashed.slice(0, MAX_HASHED);
      ev.truncated = true;
    }
    // A path below a symlinked directory is not in the worktree as git sees it; lstat on it would
    // follow the parent link, so the parents are checked first (beyondSymlink, cached per directory).
    // Only regular files reach hash-object (`--no-filters`, never `-w`). A symlink is hashed by its
    // target string (lstat, never followed: a link to /dev/zero or to a directory is just a string).
    // A directory is probed as a gitlink; fifos, sockets and devices get a type marker.
    const blob = new Map<string, string>();
    const toHash: string[] = [];
    let subProbes = 0;
    for (const p of hashed) {
      const abs = path.join(toplevel, p);
      if (beyondSymlink(p)) {
        blob.set(p, "beyond-symlink");
        continue;
      }
      let st: fs.Stats;
      try {
        st = fs.lstatSync(abs);
      } catch {
        blob.set(p, "deleted");
        continue;
      }
      if (st.isSymbolicLink()) {
        try {
          const target = fs.readlinkSync(abs, { encoding: "buffer" });
          blob.set(p, `l:${createHash("sha256").update(target).digest("hex")}`);
        } catch {
          blob.set(p, "l:unreadable");
        }
      } else if (st.isFile()) {
        blob.set(p, st.mode & 0o111 ? "fx" : "f-"); // the exec bit, also when core.fileMode is false
        toHash.push(p);
      } else if (st.isDirectory()) {
        if (subProbes >= MAX_SUBMODULE_PROBES) {
          blob.set(p, "dir:unprobed");
          ev.truncated = true;
          if (subProbes === MAX_SUBMODULE_PROBES) ev.errors.push("submodule-head:limit");
          subProbes++;
          continue;
        }
        subProbes++;
        const r = await git("submodule-head", abs, ["rev-parse", "--show-toplevel", "--verify", "-q", "HEAD"], {
          timeoutMs: SUBMODULE_TIMEOUT_MS,
          quietFail: true,
        });
        if (r.why === "timeout" || r.why === "deadline" || r.why === "overflow") {
          ev.errors.push(`submodule-head:${r.why}`);
          trackedOk = false;
          break;
        }
        const [subTop, subHead] = r.out.split("\n");
        let own = false;
        try {
          own = !!subTop && fs.realpathSync(subTop) === fs.realpathSync(abs);
        } catch {
          own = false;
        }
        if (!r.ok || (own && !subHead)) {
          // A broken gitfile, an unborn nested HEAD: recorded, and reported.
          blob.set(p, "gitlink:unresolved");
          ev.errors.push(`submodule-head:${r.why ?? "no-head"}`);
        } else if (!own) blob.set(p, "dir"); // a plain directory (or an uninitialised submodule) of this repo
        else blob.set(p, `gitlink:${subHead!.trim()}`);
      } else {
        const kind = st.isFIFO() ? "fifo" : st.isSocket() ? "socket" : st.isCharacterDevice() ? "chardev" : st.isBlockDevice() ? "blockdev" : "other";
        blob.set(p, `type:${kind}`);
      }
    }
    if (trackedOk && toHash.length > 0) {
      const ids = await hashFiles("hash-object", toplevel, toHash);
      if (ids) toHash.forEach((p, i) => blob.set(p, `${blob.get(p)}:${ids[i]}`));
      else trackedOk = false;
    }
    if (trackedOk) {
      const hash = createHash("sha256");
      for (const p of hashed) hash.update(`${p}\0${blob.get(p)}\n`);
      for (const l of rawLines) hash.update(`raw\0${l}\n`);
      for (const [p, d] of [...subDigests].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))) hash.update(`sub\0${p}\0${d}\n`);
      ev.trackedFingerprint = hash.digest("hex");
    } else {
      ev.trackedChanged = null;
    }
  } else {
    ev.trackedChanged = null;
  }

  // 7. untracked: stat only, never content
  const ut = await git("ls-files-others", toplevel, ["ls-files", "-o", "--exclude-standard", "-z"]);
  if (ut.ok) {
    const files = splitZ(ut.out).sort();
    ev.untrackedCount = files.length;
    ev.untrackedPaths = files.slice(0, MAX_PATHS).map(redactPath);
    if (files.length > MAX_PATHS) ev.truncated = true;
    const limited = files.length > MAX_HASHED ? files.slice(0, MAX_HASHED) : files;
    if (limited.length < files.length) ev.truncated = true;
    const hash = createHash("sha256");
    for (const p of limited) {
      try {
        const st = fs.lstatSync(path.join(toplevel, p));
        hash.update(`${p}\0${st.size}\0${st.mtimeMs}\n`);
      } catch {
        hash.update(`${p}\0gone\n`);
      }
    }
    ev.untrackedFingerprint = hash.digest("hex");
  }

  if (sig.aborted && !ev.errors.some((e) => e.endsWith(":deadline") || e.endsWith(":timeout"))) ev.errors.push("deadline");
  ev.capturedAt = new Date().toISOString();
  return ev;
}

