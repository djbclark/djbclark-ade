// Read-only git evidence: head, branch, base, tracked-change fingerprint, untracked fingerprint.
// Never stages, commits, stashes, writes objects or takes the index lock; never runs a clean filter.
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


interface GitResult {
  ok: boolean;
  out: string;
  raw: Buffer;
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
    if (r.code !== 0 && !opts.quietFail) {
      const why = r.timedOut ? "timeout" : r.aborted ? "deadline" : r.overflow ? "overflow" : `exit-${r.code}`;
      ev.errors.push(`${label}:${why}`);
    }
    return { ok: r.code === 0, out: r.stdout.toString("utf8"), raw: r.stdout };
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

  // 6. tracked changes: union of (worktree vs HEAD) and (index vs HEAD)
  const changed = new Set<string>();
  let trackedOk = true;
  const splitZ = (s: string) => s.split("\0").filter((x) => x.length > 0);
  const diffFlags = ["--name-only", "-z", "--ignore-submodules=all", "--no-ext-diff", "--no-textconv"];
  if (ev.head) {
    const d = await git("diff", toplevel, ["diff", ...diffFlags, "HEAD"]);
    if (d.ok) for (const p of splitZ(d.out)) changed.add(p);
    else trackedOk = false;
  }
  const dc = await git("diff-cached", toplevel, ["diff", "--cached", "--name-only", "-z", "--ignore-submodules=all", "--no-ext-diff"]);
  if (dc.ok) for (const p of splitZ(dc.out)) changed.add(p);
  else trackedOk = false;

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
    const blob = new Map<string, string>();
    const toHash: string[] = [];
    for (const p of hashed) {
      if (p.includes("\n")) {
        blob.set(p, "unhashable");
        continue;
      }
      try {
        const st = fs.lstatSync(path.join(toplevel, p));
        if (st.isDirectory()) blob.set(p, "dir");
        else toHash.push(p);
      } catch {
        blob.set(p, "deleted");
      }
    }
    if (toHash.length > 0) {
      const h = await git("hash-object", toplevel, ["hash-object", "--no-filters", "--stdin-paths"], {
        input: toHash.join("\n") + "\n",
      });
      const lines = h.ok ? h.out.split("\n").filter((l) => l.length > 0) : [];
      toHash.forEach((p, i) => blob.set(p, lines.length === toHash.length ? lines[i]! : "unhashed"));
      if (!h.ok || lines.length !== toHash.length) trackedOk = false;
    }
    if (trackedOk) {
      const hash = createHash("sha256");
      for (const p of hashed) hash.update(`${p}\0${blob.get(p)}\n`);
      ev.trackedFingerprint = hash.digest("hex");
    } else {
      ev.trackedChanged = null;
    }
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

