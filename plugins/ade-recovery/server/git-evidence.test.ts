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

// Adversary round 1, finding 1: changes the fingerprint used to miss.

test("staged rename then restoring the old path changes the fingerprint", async () => {
  const d = mkrepo();
  fs.writeFileSync(path.join(d, "a.txt"), "hello world content\n".repeat(20));
  git(d, "add", "a.txt"); git(d, "commit", "-q", "-m", "big");
  git(d, "mv", "a.txt", "r.txt");
  const e1 = await gitEvidence(d);
  assert.deepEqual(e1.trackedPaths, ["a.txt", "r.txt"]);
  git(d, "checkout", "HEAD", "--", "a.txt");
  const e2 = await gitEvidence(d);
  assert.deepEqual(e2.trackedPaths, ["r.txt"]);
  assert.ok(e1.trackedFingerprint && e2.trackedFingerprint);
  assert.notEqual(e1.trackedFingerprint, e2.trackedFingerprint);
  // The reverse: an identical staged copy, then the original deleted.
  const d2 = mkrepo();
  fs.copyFileSync(path.join(d2, "a.txt"), path.join(d2, "c.txt"));
  git(d2, "add", "c.txt");
  const f1 = await gitEvidence(d2);
  fs.rmSync(path.join(d2, "a.txt"));
  const f2 = await gitEvidence(d2);
  assert.deepEqual(f2.trackedPaths, ["a.txt", "c.txt"]);
  assert.notEqual(f1.trackedFingerprint, f2.trackedFingerprint);
});

test("a commit inside a submodule changes the fingerprint", async () => {
  const sub = mkrepo();
  const d = mkrepo();
  git(d, "-c", "protocol.file.allow=always", "submodule", "add", "-q", sub, "s");
  git(d, "commit", "-q", "-m", "add submodule");
  const e0 = await gitEvidence(d);
  assert.equal(e0.trackedChanged, 0);
  fs.writeFileSync(path.join(d, "s", "a.txt"), "sub change\n");
  const dirty = await gitEvidence(d);
  assert.deepEqual(dirty.trackedPaths, ["s"], "a dirty submodule worktree is a changed path");
  assert.notEqual(dirty.trackedFingerprint, e0.trackedFingerprint);
  git(path.join(d, "s"), "commit", "-q", "-am", "inner");
  const e1 = await gitEvidence(d);
  assert.deepEqual(e1.trackedPaths, ["s"]);
  assert.ok(e1.trackedFingerprint);
  assert.notEqual(e1.trackedFingerprint, e0.trackedFingerprint);
  assert.deepEqual(e1.errors, []);
  fs.writeFileSync(path.join(d, "s", "a.txt"), "second\n");
  git(path.join(d, "s"), "commit", "-q", "-am", "inner 2");
  const e2 = await gitEvidence(d);
  assert.deepEqual(e2.trackedPaths, ["s"]);
  assert.notEqual(e2.trackedFingerprint, e1.trackedFingerprint, "a second submodule commit moves it again");
  assert.equal((await gitEvidence(d)).trackedFingerprint, e2.trackedFingerprint);
});

test("chmod +x changes the fingerprint", async () => {
  const d = mkrepo();
  fs.writeFileSync(path.join(d, "a.txt"), "edited\n");
  const e1 = await gitEvidence(d);
  fs.chmodSync(path.join(d, "a.txt"), 0o755);
  const e2 = await gitEvidence(d);
  assert.notEqual(e1.trackedFingerprint, e2.trackedFingerprint);
  // core.fileMode=false hides the mode from git; the exec bit is still recorded.
  git(d, "config", "core.fileMode", "false");
  const e3 = await gitEvidence(d);
  fs.chmodSync(path.join(d, "a.txt"), 0o644);
  const e4 = await gitEvidence(d);
  assert.notEqual(e3.trackedFingerprint, e4.trackedFingerprint);
});

test("symlink retarget changes the fingerprint; a file<->symlink swap with the same bytes too", async () => {
  const d = mkrepo();
  fs.symlinkSync("a.txt", path.join(d, "l"));
  git(d, "add", "l"); git(d, "commit", "-q", "-m", "link");
  fs.rmSync(path.join(d, "l")); fs.symlinkSync("x-target", path.join(d, "l"));
  const e1 = await gitEvidence(d);
  fs.rmSync(path.join(d, "l")); fs.symlinkSync("y-target", path.join(d, "l"));
  const e2 = await gitEvidence(d);
  assert.deepEqual(e2.trackedPaths, ["l"]);
  assert.notEqual(e1.trackedFingerprint, e2.trackedFingerprint);
  fs.rmSync(path.join(d, "l")); fs.symlinkSync("x-target", path.join(d, "l"));
  assert.equal((await gitEvidence(d)).trackedFingerprint, e1.trackedFingerprint);
  fs.rmSync(path.join(d, "l")); fs.writeFileSync(path.join(d, "l"), "x-target");
  const e3 = await gitEvidence(d);
  assert.ok(e3.trackedFingerprint);
  assert.notEqual(e3.trackedFingerprint, e1.trackedFingerprint);
});

test("a symlink to /dev/zero, to a directory, or a fifo neither hangs nor nulls the fingerprint", async () => {
  const d = mkrepo();
  const elsewhere = tmp();
  const cases: Array<[string, () => void]> = [
    ["dev-zero", () => fs.symlinkSync("/dev/zero", path.join(d, "a.txt"))],
    ["directory", () => fs.symlinkSync(elsewhere, path.join(d, "a.txt"))],
    ["fifo", () => execFileSync("mkfifo", [path.join(d, "a.txt")])],
  ];
  const prints = new Set<string>();
  for (const [name, make] of cases) {
    fs.rmSync(path.join(d, "a.txt"), { force: true });
    make();
    const t0 = Date.now();
    const ev = await gitEvidence(d);
    assert.ok(Date.now() - t0 < 5000, `${name}: took ${Date.now() - t0} ms`);
    assert.ok(ev.trackedFingerprint, `${name}: fingerprint nulled (${ev.errors.join(",")})`);
    assert.deepEqual(ev.errors, [], name);
    assert.ok(ev.trackedPaths.includes("a.txt"), name);
    prints.add(ev.trackedFingerprint!);
  }
  assert.equal(prints.size, cases.length);
});

test("a tracked path below a symlinked directory is not followed", async () => {
  const d = mkrepo();
  fs.mkdirSync(path.join(d, "dir"));
  fs.writeFileSync(path.join(d, "dir", "zero"), "z\n");
  git(d, "add", "dir"); git(d, "commit", "-q", "-m", "dir");
  fs.rmSync(path.join(d, "dir"), { recursive: true });
  fs.symlinkSync("/dev", path.join(d, "dir"));
  const t0 = Date.now();
  const ev = await gitEvidence(d);
  assert.ok(Date.now() - t0 < 5000);
  assert.ok(ev.trackedFingerprint);
  assert.deepEqual(ev.errors, []);
});

// Adversary round 2, N1: names `--stdin-paths` cannot carry (a newline; a leading quote, which it
// C-unquotes; a trailing CR, which it drops) must still have their content hashed.

test("a content edit to a path with a newline, a leading quote or a trailing CR changes the fingerprint", async () => {
  for (const name of ["we\nird", '"a.txt"', "b.txt\r"]) {
    const d = mkrepo();
    const p = path.join(d, name);
    fs.writeFileSync(p, "1\n");
    git(d, "add", "--", name); git(d, "commit", "-q", "-m", "odd name");
    fs.writeFileSync(p, "agent edit\n");
    const a = await gitEvidence(d);
    assert.ok(a.trackedFingerprint, `${JSON.stringify(name)}: fingerprint nulled (${a.errors.join(",")})`);
    assert.deepEqual(a.errors, [], JSON.stringify(name));
    assert.equal(a.truncated, false);
    assert.equal(a.trackedChanged, 1, JSON.stringify(name));
    assert.equal((await gitEvidence(d)).trackedFingerprint, a.trackedFingerprint, `${JSON.stringify(name)}: stable`);
    fs.writeFileSync(p, "someone else's edit\n");
    const b = await gitEvidence(d);
    assert.ok(b.trackedFingerprint);
    assert.notEqual(b.trackedFingerprint, a.trackedFingerprint, `${JSON.stringify(name)}: edit invisible`);
  }
});

// Adversary round 2, N2: edits inside a submodule's own worktree.

function mksuper(): { d: string; s: string } {
  const sub = mkrepo();
  const d = mkrepo();
  git(d, "-c", "protocol.file.allow=always", "submodule", "add", "-q", sub, "s");
  git(d, "commit", "-q", "-m", "add submodule");
  return { d, s: path.join(d, "s") };
}

test("a submodule worktree edit changes the fingerprint, a second edit changes it again, and it is stable", async () => {
  const { d, s } = mksuper();
  const e0 = await gitEvidence(d);
  assert.equal(e0.trackedChanged, 0);
  fs.writeFileSync(path.join(s, "a.txt"), "agent edit\n");
  const e1 = await gitEvidence(d);
  assert.ok(e1.trackedFingerprint, e1.errors.join(","));
  assert.deepEqual(e1.errors, []);
  assert.deepEqual(e1.trackedPaths, ["s"]);
  assert.notEqual(e1.trackedFingerprint, e0.trackedFingerprint);
  // Same tree twice: same fingerprint, also after a touch that leaves the content alone.
  assert.equal((await gitEvidence(d)).trackedFingerprint, e1.trackedFingerprint);
  const t = new Date(Date.now() + 5000);
  fs.utimesSync(path.join(s, "a.txt"), t, t);
  assert.equal((await gitEvidence(d)).trackedFingerprint, e1.trackedFingerprint, "touch moved it");
  fs.writeFileSync(path.join(s, "a.txt"), "someone else\n");
  const e2 = await gitEvidence(d);
  assert.ok(e2.trackedFingerprint);
  assert.notEqual(e2.trackedFingerprint, e1.trackedFingerprint, "second edit invisible");
  assert.equal((await gitEvidence(d)).trackedFingerprint, e2.trackedFingerprint);
  // A new untracked file inside the submodule moves it too.
  fs.writeFileSync(path.join(s, "new.txt"), "n\n");
  const e3 = await gitEvidence(d);
  assert.notEqual(e3.trackedFingerprint, e2.trackedFingerprint);
  assert.equal((await gitEvidence(d)).trackedFingerprint, e3.trackedFingerprint);
  // Restoring the submodule restores the clean fingerprint.
  fs.rmSync(path.join(s, "new.txt"));
  git(s, "checkout", "-q", "--", "a.txt");
  assert.equal((await gitEvidence(d)).trackedFingerprint, e0.trackedFingerprint);
});

test("the submodule scan runs none of the submodule's filter drivers and writes nothing there", async () => {
  const { d, s } = mksuper();
  const marker = path.join(tmp(), "sub-filter-ran");
  const script = path.join(tmp(), "filter.sh");
  fs.writeFileSync(script, `#!/bin/sh\ntouch '${marker}'\ncat\n`, { mode: 0o755 });
  git(s, "config", "filter.subonly.clean", script);
  git(s, "config", "filter.subonly.process", script);
  fs.writeFileSync(path.join(s, ".gitattributes"), "*.txt filter=subonly\n");
  fs.writeFileSync(path.join(s, "a.txt"), "dirty in submodule\n");
  const gitDir = git(s, "rev-parse", "--absolute-git-dir").trim();
  const idx = path.join(gitDir, "index");
  const before = fs.statSync(idx);
  await new Promise((r) => setTimeout(r, 20));
  const ev = await gitEvidence(d);
  assert.ok(!fs.existsSync(marker), "submodule filter driver ran");
  assert.ok(ev.trackedFingerprint, ev.errors.join(","));
  assert.deepEqual(ev.trackedPaths, ["s"]);
  const after = fs.statSync(idx);
  assert.equal(after.mtimeMs, before.mtimeMs);
  assert.ok(!fs.existsSync(idx + ".lock"));
});

test("an uninitialised submodule is not scanned and does not null the fingerprint", async () => {
  const { d } = mksuper();
  const clone = path.join(tmp(), "clone");
  git(d, "clone", "-q", d, clone);
  const ev = await gitEvidence(clone);
  assert.ok(ev.trackedFingerprint, ev.errors.join(","));
  assert.deepEqual(ev.errors, []);
  assert.equal(ev.trackedChanged, 0);
});

// Adversary round 3, B3: only initialised gitlinks count against the 16-scan budget.
function addGitlinks(d: string, n: number, init: boolean): void {
  const sha = git(d, "rev-parse", "HEAD").trim();
  for (let i = 0; i < n; i++) {
    const name = `g${String(i).padStart(2, "0")}`;
    fs.mkdirSync(path.join(d, name));
    if (init) {
      git(path.join(d, name), "init", "-q", "-b", "main");
      git(path.join(d, name), "commit", "-q", "--allow-empty", "-m", "x");
    }
    git(d, "update-index", "--add", "--cacheinfo", `160000,${sha},${name}`);
  }
}
test("17 uninitialised gitlinks do not exhaust the scan budget", async () => {
  const d = mkrepo();
  addGitlinks(d, 17, false);
  const ev = await gitEvidence(d);
  assert.ok(!ev.errors.includes("submodule-dirty:limit"), ev.errors.join(","));
  assert.equal(ev.truncated, false);
});
test("17 initialised gitlinks exceed the scan budget", async () => {
  const d = mkrepo();
  addGitlinks(d, 17, true);
  const ev = await gitEvidence(d);
  assert.equal(ev.truncated, true);
  assert.ok(ev.errors.includes("submodule-dirty:limit"), ev.errors.join(","));
});

// Adversary round 3, B4: a filter driver named with `=` cannot be blanked, so nothing may run it.
test("a clean filter driver whose name contains '=' must not run", async () => {
  const d = mkrepo();
  const marker = path.join(d, "..", `marker-eq-${path.basename(d)}`);
  const script = path.join(tmp(), "filter.sh");
  fs.writeFileSync(script, `#!/bin/sh\ntouch '${marker}'\ncat\n`, { mode: 0o755 });
  git(d, "config", "filter.a=b.clean", script);
  git(d, "config", "filter.a=b.process", script);
  fs.writeFileSync(path.join(d, ".gitattributes"), "*.txt filter=a=b\n");
  fs.writeFileSync(path.join(d, "a.txt"), "dirty with filter\n");
  const ev = await gitEvidence(d);
  assert.ok(!fs.existsSync(marker), "filter driver ran");
  assert.equal(ev.trackedFingerprint, null);
  assert.ok(ev.errors.includes("filter-name:unsafe"));
});
