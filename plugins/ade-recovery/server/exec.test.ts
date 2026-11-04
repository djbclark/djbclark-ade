import { test } from "node:test";
import assert from "node:assert/strict";
import { cleanEnv, run } from "./exec.ts";

test("cleanEnv is built from scratch", () => {
  const e = cleanEnv({ PATH: "/bin", HOME: "/h", GIT_DIR: "/x", GIT_INDEX_FILE: "/y", GIT_CONFIG_PARAMETERS: "z", SECRET: "s" });
  assert.deepEqual(Object.keys(e).sort(), ["GIT_CONFIG_NOSYSTEM", "GIT_OPTIONAL_LOCKS", "GIT_PAGER", "GIT_TERMINAL_PROMPT", "HOME", "LC_ALL", "PATH"]);
  assert.equal(e.LC_ALL, "C");
});

test("run returns stdout, code and does not leak parent env", async () => {
  process.env.ADE_TEST_LEAK = "leaked";
  process.env.GIT_DIR = "/nonexistent";
  try {
    const r = await run(process.execPath, ["-e", "process.stdout.write(String(process.env.ADE_TEST_LEAK)+'|'+String(process.env.GIT_DIR)+'|'+process.env.GIT_OPTIONAL_LOCKS)"], { timeoutMs: 10000 });
    assert.equal(r.code, 0);
    assert.equal(r.stdout.toString(), "undefined|undefined|0");
  } finally {
    delete process.env.ADE_TEST_LEAK;
    delete process.env.GIT_DIR;
  }
});

test("non-zero exit and stdin input", async () => {
  const r = await run(process.execPath, ["-e", "process.stdin.pipe(process.stdout);process.stdin.on('end',()=>process.exitCode=3)"], { timeoutMs: 10000, input: "hi" });
  assert.equal(r.code, 3);
  assert.equal(r.stdout.toString(), "hi");
});

test("timeout kills the child", async () => {
  const r = await run(process.execPath, ["-e", "setTimeout(()=>{},60000)"], { timeoutMs: 200 });
  assert.equal(r.code, -1);
  assert.equal(r.timedOut, true);
});

test("abort signal kills the child; pre-aborted never spawns", async () => {
  const ac = new AbortController();
  const p = run(process.execPath, ["-e", "setTimeout(()=>{},60000)"], { timeoutMs: 30000, signal: ac.signal });
  setTimeout(() => ac.abort(), 100);
  const r = await p;
  assert.equal(r.aborted, true);
  assert.equal(r.code, -1);
  const r2 = await run(process.execPath, ["-e", "1"], { timeoutMs: 1000, signal: AbortSignal.abort() });
  assert.equal(r2.aborted, true);
});

test("maxBuffer overflow is reported", async () => {
  const r = await run(process.execPath, ["-e", "process.stdout.write('x'.repeat(100000))"], { timeoutMs: 10000, maxBuffer: 1000 });
  assert.equal(r.overflow, true);
  assert.equal(r.code, -1);
});

test("missing binary and missing cwd give code -1, not a throw", async () => {
  const r = await run("definitely-not-a-binary-xyz", [], { timeoutMs: 1000 });
  assert.equal(r.code, -1);
  const r2 = await run(process.execPath, ["-e", "1"], { timeoutMs: 1000, cwd: "/nonexistent-dir-xyz" });
  assert.equal(r2.code, -1);
});

test("no shell: metacharacters are literal argv", async () => {
  const r = await run(process.execPath, ["-e", "process.stdout.write(process.argv[1])", "$(echo hi);ls"], { timeoutMs: 5000 });
  assert.equal(r.stdout.toString(), "$(echo hi);ls");
});
