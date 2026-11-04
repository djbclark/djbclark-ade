import { test } from "node:test";
import assert from "node:assert/strict";
import os from "node:os";
import { spawn, execFileSync } from "node:child_process";
import {
  bootId,
  daemonIdentity,
  hostIdentity,
  parseProcStatStart,
  processAlive,
  processStart,
  processStartViaPs,
  selfIdentity,
} from "./host-identity.ts";

function deadPid(): Promise<number> {
  return new Promise((resolve, reject) => {
    const c = spawn(process.execPath, ["-e", "0"], { stdio: "ignore" });
    c.on("error", reject);
    c.on("exit", () => resolve(c.pid!)); // reaped by libuv: not a zombie
  });
}

function hasPs(): boolean {
  try {
    execFileSync("ps", ["-o", "lstart=", "-p", String(process.pid)], { stdio: "ignore", timeout: 2000 });
    return true;
  } catch {
    return false;
  }
}

test("parseProcStatStart takes field 22 after the last ')'", () => {
  // comm may hold spaces and parentheses: "(a) (b)"
  const rest = ["S", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "17", "18", "987654", "21"];
  assert.equal(parseProcStatStart(`42 (a) (b) ${rest.join(" ")}`), "987654");
  assert.equal(parseProcStatStart("42 (x) S 1 2"), null);
  assert.equal(parseProcStatStart("garbage"), null);
});

test("hostIdentity and bootId", () => {
  const h = hostIdentity();
  assert.equal(h.host, os.hostname());
  assert.equal(h.platform, process.platform);
  assert.equal(h.bootId, bootId());
  if (process.platform === "linux") assert.match(String(h.bootId), /^[0-9a-f-]{36}$/);
  if (process.platform === "darwin") assert.match(String(h.bootId), /^[0-9A-F-]{36}$/i);
});

test("processStart: stable for a live pid, null for dead or invalid", async () => {
  const a = processStart(process.pid);
  assert.ok(a !== null && a !== "", "own start token is readable");
  assert.equal(processStart(process.pid), a);
  assert.equal(processStart(await deadPid()), null);
  for (const bad of [0, -1, 1.5, Number.NaN]) assert.equal(processStart(bad), null);
  assert.deepEqual(selfIdentity(), { pid: process.pid, start: a });
  assert.equal(daemonIdentity().pid, process.ppid);
  assert.equal(daemonIdentity().start, processStart(process.ppid));
});

test("processStartViaPs (the macOS path) where ps is available", { skip: !hasPs() && "no ps" }, async () => {
  const tok = processStartViaPs(process.pid);
  assert.ok(tok && /\d{4}$/.test(tok), `lstart token ends in a year: ${tok}`);
  assert.equal(processStartViaPs(await deadPid()), null);
  assert.equal(processStartViaPs(0), null);
});

test("processAlive: same pid+start true, PID reuse false, dead false, unknown start null", async () => {
  const me = selfIdentity();
  assert.equal(processAlive(me), true);
  assert.equal(processAlive({ pid: me.pid, start: "not-the-start" }), false, "PID reuse: same pid, different start");
  assert.equal(processAlive({ pid: me.pid, start: null }), null);
  assert.equal(processAlive({ pid: await deadPid(), start: "1" }), false);
  assert.equal(processAlive({ pid: 0, start: "1" }), false, "pid 0 would signal the process group");
  assert.equal(processAlive({ pid: -1, start: "1" }), false);
  if (process.getuid?.() !== 0 && processStart(1) !== null) {
    assert.equal(processAlive({ pid: 1, start: processStart(1) }), true, "EPERM still means alive");
  }
});
