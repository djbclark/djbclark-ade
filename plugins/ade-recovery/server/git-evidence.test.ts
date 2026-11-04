import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { execFileSync } from "node:child_process";
import { gitEvidence } from "./git-evidence.ts";

const ENV = {
  PATH: process.env.PATH ?? "",
  HOME: "/nonexistent-home",
  GIT_CONFIG_NOSYSTEM: "1",
  GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@t", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@t",
};
function git(cwd: string, ...args: string[]): string {
  return execFileSync("git", args, { cwd, env: ENV, encoding: "utf8" });
}
function tmp(): string {
  return fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "ade-gitev-")));
}
function mkrepo(): string {
  const d = tmp();
  git(d, "init", "-q", "-b", "main");
  fs.writeFileSync(path.join(d, "a.txt"), "one\n");
  fs.writeFileSync(path.join(d, "b.txt"), "two\n");
  git(d, "add", "."); git(d, "commit", "-q", "-m", "init");
  return d;
}

test("clean repo", async () => {
  const d = mkrepo();
  const ev = await gitEvidence(d);
  assert.equal(ev.repoTop, d);
  assert.equal(ev.head, git(d, "rev-parse", "HEAD").trim());
  assert.equal(ev.branch, "main");
  assert.equal(ev.isLinkedWorktree, false);
  assert.equal(ev.trackedChanged, 0);
  assert.equal(ev.untrackedCount, 0);
  assert.ok(ev.trackedFingerprint && ev.untrackedFingerprint);
  assert.equal(ev.base, null); // no origin
  assert.deepEqual(ev.errors, []);
});

test("dirty tracked changes the fingerprint; same content is stable", async () => {
  const d = mkrepo();
  const clean = await gitEvidence(d);
  fs.writeFileSync(path.join(d, "a.txt"), "changed\n");
  const e1 = await gitEvidence(d);
  const e2 = await gitEvidence(d);
  assert.equal(e1.trackedChanged, 1);
  assert.deepEqual(e1.trackedPaths, ["a.txt"]);
  assert.notEqual(e1.trackedFingerprint, clean.trackedFingerprint);
  assert.equal(e1.trackedFingerprint, e2.trackedFingerprint);
  fs.writeFileSync(path.join(d, "a.txt"), "changed again\n");
  assert.notEqual((await gitEvidence(d)).trackedFingerprint, e1.trackedFingerprint);
  fs.rmSync(path.join(d, "b.txt"));
  const e3 = await gitEvidence(d);
  assert.equal(e3.trackedChanged, 2);
});

test("staged change is seen", async () => {
  const d = mkrepo();
  fs.writeFileSync(path.join(d, "n.txt"), "new\n");
  git(d, "add", "n.txt");
  const ev = await gitEvidence(d);
  assert.equal(ev.trackedChanged, 1);
  assert.deepEqual(ev.trackedPaths, ["n.txt"]);
  assert.equal(ev.untrackedCount, 0);
});

test("untracked files: counted, redacted names, content never read", async () => {
  const d = mkrepo();
  const before = await gitEvidence(d);
  fs.writeFileSync(path.join(d, "u.txt"), "x");
  fs.writeFileSync(path.join(d, ".env"), "KEY=1");
  const ev = await gitEvidence(d);
  assert.equal(ev.untrackedCount, 2);
  assert.ok(ev.untrackedPaths.includes("u.txt"));
  assert.ok(ev.untrackedPaths.includes("[redacted-name]"));
  assert.ok(!ev.untrackedPaths.includes(".env"));
  assert.notEqual(ev.untrackedFingerprint, before.untrackedFingerprint);
});

test("unborn HEAD keeps the toplevel", async () => {
  const d = tmp();
  git(d, "init", "-q", "-b", "main");
  fs.writeFileSync(path.join(d, "x.txt"), "1");
  const ev = await gitEvidence(d);
  assert.equal(ev.repoTop, d);
  assert.equal(ev.head, null);
  assert.equal(ev.untrackedCount, 1);
  assert.ok(ev.untrackedFingerprint);
});

test("detached HEAD has no branch", async () => {
  const d = mkrepo();
  git(d, "checkout", "-q", "--detach");
  const ev = await gitEvidence(d);
  assert.equal(ev.branch, null);
  assert.ok(ev.head);
});

test("linked worktree is detected", async () => {
  const d = mkrepo();
  const wt = path.join(tmp(), "wt");
  git(d, "worktree", "add", "-q", "-b", "side", wt);
  const ev = await gitEvidence(wt);
  assert.equal(ev.isLinkedWorktree, true);
  assert.equal(ev.branch, "side");
  assert.equal(ev.repoTop, fs.realpathSync(wt));
});

test("non-repo and missing directory give nulls and errors", async () => {
  const d = tmp();
  const ev = await gitEvidence(d);
  assert.equal(ev.repoTop, null);
  assert.equal(ev.head, null);
  assert.equal(ev.trackedFingerprint, null);
  assert.ok(ev.errors.includes("not-a-repo"));
  const ev2 = await gitEvidence(path.join(d, "nope"));
  assert.ok(ev2.errors.includes("not-a-repo"));
});

test("base from origin/HEAD merge-base", async () => {
  const d = mkrepo();
  const sha = git(d, "rev-parse", "HEAD").trim();
  git(d, "update-ref", "refs/remotes/origin/main", sha);
  git(d, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main");
  fs.writeFileSync(path.join(d, "c.txt"), "c");
  git(d, "add", "."); git(d, "commit", "-q", "-m", "two");
  const ev = await gitEvidence(d);
  assert.deepEqual(ev.base, { ref: "origin/main", sha, method: "merge-base-origin-head" });
});

test("read-only: index mtime unchanged, no index.lock, no new objects", async () => {
  const d = mkrepo();
  fs.writeFileSync(path.join(d, "a.txt"), "dirty\n");
  fs.writeFileSync(path.join(d, "u.txt"), "u\n");
  const idx = path.join(d, ".git", "index");
  const before = fs.statSync(idx);
  const objs = git(d, "count-objects", "-v");
  await new Promise((r) => setTimeout(r, 20));
  await gitEvidence(d);
  const after = fs.statSync(idx);
  assert.equal(after.mtimeMs, before.mtimeMs);
  assert.equal(after.ino, before.ino);
  assert.ok(!fs.existsSync(idx + ".lock"));
  assert.equal(git(d, "count-objects", "-v"), objs);
});

test("a clean filter driver must not run", async () => {
  const d = mkrepo();
  const marker = path.join(d, "..", `marker-${path.basename(d)}`);
  const script = path.join(tmp(), "filter.sh");
  fs.writeFileSync(script, `#!/bin/sh\ntouch '${marker}'\ncat\n`, { mode: 0o755 });
  git(d, "config", "filter.x.clean", script);
  git(d, "config", "filter.x.smudge", "cat");
  git(d, "config", "filter.x.process", script);
  fs.writeFileSync(path.join(d, ".gitattributes"), "*.txt filter=x\n");
  fs.writeFileSync(path.join(d, "a.txt"), "dirty with filter\n");
  const ev = await gitEvidence(d);
  assert.ok(!fs.existsSync(marker), "filter driver ran");
  assert.ok(ev.trackedChanged !== null && ev.trackedChanged >= 1);
  assert.ok(ev.trackedPaths.includes("a.txt"));
});

test("a core.fsmonitor hook must not run (config is overridden)", async () => {
  const d = mkrepo();
  const marker = path.join(tmp(), "fsmonitor-ran");
  const hook = path.join(tmp(), "fsm.sh");
  fs.writeFileSync(hook, `#!/bin/sh\ntouch '${marker}'\n`, { mode: 0o755 });
  git(d, "config", "core.fsmonitor", hook);
  git(d, "config", "core.hooksPath", path.dirname(hook));
  fs.writeFileSync(path.join(d, "a.txt"), "dirty\n");
  await gitEvidence(d);
  assert.ok(!fs.existsSync(marker), "fsmonitor hook ran");
});

test("GIT_DIR / GIT_INDEX_FILE in the parent env are ignored", async () => {
  const d = mkrepo();
  const other = mkrepo();
  fs.writeFileSync(path.join(other, "zzz.txt"), "z");
  git(other, "add", "zzz.txt");
  const saved = { GIT_DIR: process.env.GIT_DIR, GIT_INDEX_FILE: process.env.GIT_INDEX_FILE, GIT_WORK_TREE: process.env.GIT_WORK_TREE };
  process.env.GIT_DIR = path.join(other, ".git");
  process.env.GIT_INDEX_FILE = path.join(other, ".git", "index");
  process.env.GIT_WORK_TREE = other;
  try {
    const ev = await gitEvidence(d);
    assert.equal(ev.repoTop, d);
    assert.equal(ev.trackedChanged, 0);
  } finally {
    for (const [k, v] of Object.entries(saved)) {
      if (v === undefined) delete process.env[k]; else process.env[k] = v;
    }
  }
});

test("an aborted signal yields errors, not a throw", async () => {
  const d = mkrepo();
  const ev = await gitEvidence(d, AbortSignal.abort());
  assert.ok(ev.errors.length > 0);
});
