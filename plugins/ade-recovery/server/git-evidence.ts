// Read-only git evidence: head, branch, base, tracked-change fingerprint, untracked fingerprint.
// Never stages, commits, stashes, writes objects or takes the index lock; never runs a clean filter.
// The tracked fingerprint covers, per changed path, the worktree content (regular files via
// hash-object, symlinks by target, gitlinks by submodule HEAD, other types by a marker) and the raw
// HEAD/index diffs (modes, index and gitlink ids, status letters).
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
    opts: { timeoutMs?: number; input?: string; quietFail?: boolean } = {},
  ): Promise<GitResult> => {
    const argv = [
      "--no-optional-locks",
      "-c", "core.fsmonitor=false",
      "-c", "core.untrackedCache=false",
      "-c", "core.hooksPath=/dev/null",
      ...filterOverrides,
      "-C", root,
      ...args,
    ];
    const r = await run("git", argv, {
      cwd: root,
      timeoutMs: opts.timeoutMs ?? CALL_TIMEOUT_MS,
      signal: sig,
      maxBuffer: MAX_STDOUT,
      input: opts.input,
    });
    const why = r.code === 0 ? null : r.timedOut ? "timeout" : r.aborted ? "deadline" : r.overflow ? "overflow" : `exit-${r.code}`;
    if (why && !opts.quietFail) ev.errors.push(`${label}:${why}`);
    return { ok: r.code === 0, out: r.stdout.toString("utf8"), raw: r.stdout, why };
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
  const cfg = await git("filter-config", toplevel, ["config", "--get-regexp", "-z", "^filter\\."], { quietFail: true });
  if (cfg.ok) {
    const names = new Set<string>();
    for (const entry of cfg.out.split("\0")) {
      const key = entry.split("\n")[0] ?? "";
      const m = /^filter\.(.+)\.(clean|smudge|process|required)$/i.exec(key);
      if (m) names.add(m[1]!);
    }
    for (const n of names) {
      filterOverrides.push("-c", `filter.${n}.clean=`, "-c", `filter.${n}.process=`, "-c", `filter.${n}.smudge=`, "-c", `filter.${n}.required=false`);
    }
  }

  // 6. tracked changes: union of (worktree vs HEAD) and (index vs HEAD).
  // `--no-renames`: rename detection would list only the new side of a staged rename, so restoring
  // the old path would leave the list and the fingerprint unchanged. `--ignore-submodules=dirty`:
  // a gitlink whose submodule HEAD moved is listed; edits inside a submodule's own tree are not.
  const changed = new Set<string>();
  let trackedOk = true;
  const splitZ = (s: string) => s.split("\0").filter((x) => x.length > 0);
  const common = ["-z", "--no-renames", "--ignore-submodules=dirty", "--no-ext-diff", "--no-textconv"];
  if (ev.head) {
    const d = await git("diff", toplevel, ["diff", "--name-only", ...common, "HEAD"]);
    if (d.ok) for (const p of splitZ(d.out)) changed.add(p);
    else trackedOk = false;
  }
  const dc = await git("diff-cached", toplevel, ["diff", "--cached", "--name-only", ...common]);
  if (dc.ok) for (const p of splitZ(dc.out)) changed.add(p);
  else trackedOk = false;

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
    // follow the parent link, so the parents are checked first (cached per directory).
    const parentIsLink = new Map<string, boolean>();
    const beyondSymlink = (rel: string): boolean => {
      const segs = rel.split("/");
      let acc = "";
      for (let i = 0; i < segs.length - 1; i++) {
        acc = acc ? `${acc}/${segs[i]}` : segs[i]!;
        let bad = parentIsLink.get(acc);
        if (bad === undefined) {
          try {
            bad = !fs.lstatSync(path.join(toplevel, acc)).isDirectory();
          } catch {
            bad = false; // missing parent: the lstat of the path itself reports it deleted
          }
          parentIsLink.set(acc, bad);
        }
        if (bad) return true;
      }
      return false;
    };
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
        const kind = st.mode & 0o111 ? "fx" : "f-"; // the exec bit, also when core.fileMode is false
        if (p.includes("\n")) blob.set(p, `${kind}:unhashable`);
        else {
          blob.set(p, kind);
          toHash.push(p);
        }
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
      const h = await git("hash-object", toplevel, ["hash-object", "--no-filters", "--stdin-paths"], {
        input: toHash.join("\n") + "\n",
      });
      const lines = h.ok ? h.out.split("\n").filter((l) => l.length > 0) : [];
      toHash.forEach((p, i) => {
        const mark = blob.get(p) ?? "";
        blob.set(p, `${mark}:${lines.length === toHash.length ? lines[i]! : "unhashed"}`);
      });
      if (!h.ok || lines.length !== toHash.length) trackedOk = false;
    }
    if (trackedOk) {
      const hash = createHash("sha256");
      for (const p of hashed) hash.update(`${p}\0${blob.get(p)}\n`);
      for (const l of rawLines) hash.update(`raw\0${l}\n`);
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

