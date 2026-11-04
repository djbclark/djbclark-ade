import { test } from "node:test";
import assert from "node:assert/strict";
import os from "node:os";
import fs from "node:fs";
import path from "node:path";
import { spawn, execFileSync } from "node:child_process";
import {
  bootId,
  daemonIdentity,
  hostIdentity,
  machineId,
  machineIdFromFiles,
  parseIoregPlatformUuid,
  parseProcStatStart,
  processAlive,
  processStart,
  processStartViaPs,
  sameHost,
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

// Adversary finding 3: hostnames drift; the machine id is the host key.
test("machineIdFromFiles: first valid id; uninitialized, empty and missing files are skipped", () => {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "ade-mid-"));
  const f = (n: string, v: string) => {
    fs.writeFileSync(path.join(d, n), v);
    return path.join(d, n);
  };
  const missing = path.join(d, "missing");
  assert.equal(machineIdFromFiles([missing, f("a", "uninitialized\n"), f("b", "\n"), f("c", "D165C2D88D894A4787BE219662B439AD\n")]), "d165c2d88d894a4787be219662b439ad");
  assert.equal(machineIdFromFiles([missing, f("e", "bad id with spaces")]), null);
});

test("parseIoregPlatformUuid reads IOPlatformUUID from ioreg output", () => {
  const out = `+-o J316sAP  <class IOPlatformExpertDevice, id 0x100000215, registered>
    {
      "IOPlatformSerialNumber" = "XXXXXXXXXX"
      "IOPlatformUUID" = "0A1B2C3D-4E5F-6071-8293-A4B5C6D7E8F9"
    }`;
  assert.equal(parseIoregPlatformUuid(out), "0A1B2C3D-4E5F-6071-8293-A4B5C6D7E8F9");
  assert.equal(parseIoregPlatformUuid("nothing here"), null);
});

test("hostIdentity carries the machine id (Linux: /etc/machine-id when present)", () => {
  const h = hostIdentity();
  assert.equal(h.machineId, machineId());
  if (process.platform === "linux" && fs.existsSync("/etc/machine-id")) {
    assert.equal(h.machineId, fs.readFileSync("/etc/machine-id", "utf8").trim().toLowerCase());
  }
});

test("sameHost: machine ids decide when both are known; hostname only as the fallback", () => {
  const mid = "d165c2d88d894a4787be219662b439ad";
  assert.equal(sameHost({ host: "old-name.local", machineId: mid }, { host: "new-name.local", machineId: mid.toUpperCase() }), true, "rename, same machine");
  assert.equal(sameHost({ host: "same", machineId: mid }, { host: "same", machineId: "ffffffffffffffffffffffffffffffff" }), false, "same name, another machine");
  assert.equal(sameHost({ host: "h" }, { host: "h", machineId: mid }), true, "old record without machineId: hostname");
  assert.equal(sameHost({ host: "h", machineId: null }, { host: "other", machineId: mid }), false);
  assert.equal(sameHost({ host: "" }, { host: "" }), false);
  assert.equal(sameHost(null, { host: "h" }), false);
});

// Adversary round 2, N6b: one 2 s budget across all candidate binaries, never 2 s each.
test("probeFirst: one total budget; the next binary gets only the time left, none once it is spent", async () => {
  const { probeFirst, PROBE_BUDGET_MS } = await import("./host-identity.ts");
  assert.equal(PROBE_BUDGET_MS, 2000);
  let clock = 0;
  const now = () => clock;
  const seen: Array<[string, number]> = [];
  const hang = (bin: string, _a: string[], t: number): string => {
    seen.push([bin, t]);
    clock += t; // a run that hangs until its timeout
    throw new Error("ETIMEDOUT");
  };
  assert.equal(probeFirst(["/usr/sbin/ioreg", "ioreg"], [], (o) => o || null, 2000, hang, now), null);
  assert.deepEqual(seen, [["/usr/sbin/ioreg", 2000]], "the second binary is not started once the budget is spent");
  seen.length = 0;
  clock = 0;
  const slowThenOk = (bin: string, _a: string[], t: number): string => {
    seen.push([bin, t]);
    if (bin === "a") {
      clock += 1500;
      throw new Error("ENOENT");
    }
    return "VALUE";
  };
  assert.equal(probeFirst(["a", "b"], [], (o) => o || null, 2000, slowThenOk, now), "VALUE");
  assert.deepEqual(seen, [["a", 2000], ["b", 500]]);
  assert.equal(probeFirst(["x"], [], () => null, 2000, () => "out", now), null, "unparsed output is null");
});
