import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import type { ChildProcess } from "node:child_process";
import { pathToFileURL } from "node:url";
import { acquireLock, heldByThisProcess, lockHolderAlive, readLock, selfWriterInfo } from "./writer-lock.ts";
import { bootId, hostIdentity, processStart } from "./host-identity.ts";
import { LOCK_FILE } from "./constants.ts";
import type { WriterInfo } from "./types.ts";

function tmpDir(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), "ade-recovery-lock-"));
}

function fakeLock(dir: string, over: Partial<WriterInfo> & { nonce?: string }): void {
  const h = hostIdentity();
  const content = {
    plugin: "ade-recovery",
    pluginVersion: "0.0.0",
    pid: 1,
    start: null,
    daemon: { pid: 1, start: null },
    host: h.host,
    bootId: h.bootId,
    nonce: "theirs",
    acquiredAt: new Date().toISOString(),
    ...over,
  };
  fs.writeFileSync(path.join(dir, LOCK_FILE), JSON.stringify(content), { mode: 0o600 });
}

function sleeper(): Promise<ChildProcess> {
  return new Promise((resolve, reject) => {
    const c = spawn(process.execPath, ["-e", "setTimeout(() => {}, 60000); console.log('up')"], { stdio: ["ignore", "pipe", "ignore"] });
    c.on("error", reject);
    c.stdout!.once("data", () => resolve(c));
  });
}

function stop(c: ChildProcess): Promise<void> {
  return new Promise((resolve) => {
    if (c.exitCode !== null || c.signalCode !== null) return resolve();
    c.once("exit", () => resolve());
    c.kill("SIGKILL");
  });
}

function tmpLeft(dir: string): string[] {
  return fs.readdirSync(dir).filter((n) => n.startsWith(".tmp-"));
}

test("acquire, re-acquire refused, release; file is 0600 and complete", () => {
  const dir = tmpDir();
  assert.equal(lockHolderAlive(dir), false, "no lock: nobody holds it");
  const info = selfWriterInfo();
  const a = acquireLock(dir, info);
  assert.equal(a.held, true);
  if (!a.held) return;
  assert.equal(fs.statSync(path.join(dir, LOCK_FILE)).mode & 0o777, 0o600);
  const content = readLock(dir);
  assert.equal(content?.nonce, a.nonce);
  assert.equal(content?.pid, process.pid);
  assert.equal(content?.start, processStart(process.pid));
  assert.equal(content?.plugin, "ade-recovery");
  assert.equal(lockHolderAlive(dir), true);
  assert.equal(heldByThisProcess(dir), true);
  const b = acquireLock(dir, info);
  assert.equal(b.held, false);
  if (!b.held) {
    assert.equal(b.reason, "held-by-live-writer");
    assert.equal(b.holder?.pid, process.pid);
    assert.equal((b.holder as Record<string, unknown>).nonce, undefined, "the holder view hides the nonce");
  }
  assert.equal(a.stillHeld(), true);
  a.release();
  a.release();
  assert.equal(fs.existsSync(path.join(dir, LOCK_FILE)), false);
  assert.equal(a.stillHeld(), false);
  assert.equal(lockHolderAlive(dir), false);
  assert.deepEqual(tmpLeft(dir), []);
});

test("a live holder in another process blocks; once it dies the lock is taken over", async () => {
  const dir = tmpDir();
  const c = await sleeper();
  try {
    fakeLock(dir, { pid: c.pid!, start: processStart(c.pid!) });
    const r = acquireLock(dir, selfWriterInfo());
    assert.equal(r.held, false);
    if (!r.held) {
      assert.equal(r.reason, "held-by-live-writer");
      assert.equal(r.holder?.pid, c.pid);
    }
    assert.equal(lockHolderAlive(dir), true);
  } finally {
    await stop(c);
  }
  assert.equal(lockHolderAlive(dir), false);
  const r2 = acquireLock(dir, selfWriterInfo());
  assert.equal(r2.held, true);
  assert.equal(readLock(dir)?.pid, process.pid);
  assert.deepEqual(tmpLeft(dir), []);
});

test("dead pid is stale", async () => {
  const dir = tmpDir();
  const c = await sleeper();
  const pid = c.pid!;
  const start = processStart(pid);
  await stop(c);
  fakeLock(dir, { pid, start });
  assert.equal(lockHolderAlive(dir), false);
  assert.equal(acquireLock(dir, selfWriterInfo()).held, true);
});

test("PID reuse: same live pid with a different start token is stale", async () => {
  const dir = tmpDir();
  const c = await sleeper();
  try {
    fakeLock(dir, { pid: c.pid!, start: "999999999-not-its-start" });
    assert.equal(lockHolderAlive(dir), false);
    const r = acquireLock(dir, selfWriterInfo());
    assert.equal(r.held, true);
  } finally {
    await stop(c);
  }
});

test("boot id change is stale even when pid and start match", { skip: bootId() === null && "no boot id here" }, () => {
  const dir = tmpDir();
  fakeLock(dir, { pid: process.pid, start: processStart(process.pid), bootId: "00000000-0000-0000-0000-000000000000" });
  assert.equal(lockHolderAlive(dir), false);
  assert.equal(acquireLock(dir, selfWriterInfo()).held, true);
});

test("other host and unknown start are never taken over", () => {
  const dir = tmpDir();
  fakeLock(dir, { pid: process.pid, start: processStart(process.pid), host: "some-other-host" });
  const r = acquireLock(dir, selfWriterInfo());
  assert.equal(r.held, false);
  if (!r.held) assert.equal(r.reason, "held-by-other-host");
  assert.equal(lockHolderAlive(dir), null);
  fakeLock(dir, { pid: process.pid, start: null });
  const r2 = acquireLock(dir, selfWriterInfo());
  assert.equal(r2.held, false);
  if (!r2.held) assert.equal(r2.reason, "holder-liveness-unknown");
  assert.equal(lockHolderAlive(dir), null);
  assert.deepEqual(tmpLeft(dir), []);
});

test("a malformed lock is stale for acquire and unknown for lockHolderAlive", () => {
  const dir = tmpDir();
  fs.writeFileSync(path.join(dir, LOCK_FILE), "{not json");
  assert.equal(lockHolderAlive(dir), null);
  assert.equal(readLock(dir), null);
  assert.equal(acquireLock(dir, selfWriterInfo()).held, true);
});

test("nonce race: a lock replaced right after our link is detected and left alone", () => {
  const dir = tmpDir();
  const r = acquireLock(dir, selfWriterInfo(), {
    afterLink: () => {
      fs.rmSync(path.join(dir, LOCK_FILE));
      fakeLock(dir, { pid: process.pid, start: processStart(process.pid), nonce: "racer" });
    },
  });
  assert.equal(r.held, false);
  if (!r.held) assert.equal(r.reason, "nonce-mismatch");
  assert.equal(readLock(dir)?.nonce, "racer", "the racer's lock is untouched");
  assert.deepEqual(tmpLeft(dir), []);
});

test("takeover guard: one left by a dead taker is taken over; one held by a live taker blocks", async () => {
  const dir = tmpDir();
  const dead = await sleeper();
  const deadPid = dead.pid!;
  const deadStart = processStart(deadPid);
  await stop(dead);
  fakeLock(dir, { pid: deadPid, start: deadStart, nonce: "aaaaaaaa00000001" });
  const guard = path.join(dir, ".tmp-takeover-aaaaaaaa00000001");
  fs.writeFileSync(guard, JSON.stringify({ ...JSON.parse(fs.readFileSync(path.join(dir, LOCK_FILE), "utf8")), nonce: "bbbbbbbb00000002" }));
  const r = acquireLock(dir, selfWriterInfo());
  assert.equal(r.held, true, "a guard whose taker died does not wedge the lock");
  assert.deepEqual(tmpLeft(dir), []);
  if (r.held) r.release();

  const live = await sleeper();
  try {
    fakeLock(dir, { pid: deadPid, start: deadStart, nonce: "cccccccc00000003" });
    const liveGuard = path.join(dir, ".tmp-takeover-cccccccc00000003");
    fs.writeFileSync(liveGuard, JSON.stringify({ ...readLock(dir), pid: live.pid, start: processStart(live.pid!), nonce: "dddddddd00000004" }));
    const r2 = acquireLock(dir, selfWriterInfo());
    assert.equal(r2.held, false);
    if (!r2.held) assert.equal(r2.reason, "lost-race");
    assert.equal(readLock(dir)?.nonce, "cccccccc00000003", "the stale lock is left for the live taker");
    assert.ok(fs.existsSync(liveGuard));
  } finally {
    await stop(live);
  }
});

test("release never removes a lock someone else now holds", () => {
  const dir = tmpDir();
  const a = acquireLock(dir, selfWriterInfo());
  assert.equal(a.held, true);
  if (!a.held) return;
  fakeLock(dir, { pid: process.pid, start: processStart(process.pid), nonce: "taken-over" });
  assert.equal(a.stillHeld(), false);
  a.release();
  assert.equal(readLock(dir)?.nonce, "taken-over");
});

const LOCK_URL = pathToFileURL(path.join(path.dirname(new URL(import.meta.url).pathname), "writer-lock.ts")).href;
const CHILD = `
import { acquireLock, selfWriterInfo } from ${JSON.stringify(LOCK_URL)};
const dir = process.argv[1];
let r = null;
process.stdout.write("ready\\n");
let buf = "";
process.stdin.on("data", (d) => {
  buf += d;
  if (r === null && buf.includes("go\\n")) {
    r = acquireLock(dir, selfWriterInfo());
    process.stdout.write(JSON.stringify({ held: r.held, reason: r.held ? null : r.reason }) + "\\n");
  }
});
process.stdin.on("end", () => {
  process.stdout.write(JSON.stringify({ still: !!(r && r.held && r.stillHeld()) }) + "\\n");
  process.exit(0);
});
`;

interface Racer {
  child: ChildProcess;
  lines: string[];
  waitLines(n: number): Promise<void>;
}

function racer(dir: string): Racer {
  const child = spawn(process.execPath, ["--disable-warning=ExperimentalWarning", "--input-type=module", "-e", CHILD, dir], {
    stdio: ["pipe", "pipe", "inherit"],
  });
  const lines: string[] = [];
  let buf = "";
  const waiters: Array<() => void> = [];
  child.stdout!.on("data", (d) => {
    buf += d;
    let i: number;
    while ((i = buf.indexOf("\n")) >= 0) {
      lines.push(buf.slice(0, i));
      buf = buf.slice(i + 1);
      waiters.splice(0).forEach((w) => w());
    }
  });
  return {
    child,
    lines,
    waitLines(n) {
      return new Promise((resolve, reject) => {
        const t = setTimeout(() => reject(new Error(`racer timed out with ${JSON.stringify(lines)}`)), 20000);
        const check = () => {
          if (lines.length >= n) {
            clearTimeout(t);
            resolve();
          } else waiters.push(check);
        };
        check();
      });
    },
  };
}

test("real race: 8 processes contend for a stale lock; exactly one wins and keeps it", async () => {
  for (let round = 0; round < 4; round++) {
    const dir = tmpDir();
    const dead = await sleeper();
    const pid = dead.pid!;
    const start = processStart(pid);
    await stop(dead);
    fakeLock(dir, { pid, start });
    const rs = Array.from({ length: 8 }, () => racer(dir));
    try {
      await Promise.all(rs.map((r) => r.waitLines(1)));
      for (const r of rs) r.child.stdin!.write("go\n");
      await Promise.all(rs.map((r) => r.waitLines(2)));
      const results = rs.map((r) => JSON.parse(r.lines[1]) as { held: boolean; reason: string | null });
      const winners = results.filter((x) => x.held).length;
      assert.equal(winners, 1, `round ${round}: ${JSON.stringify(results)}`);
      for (const x of results) if (!x.held) assert.ok(x.reason, "a loser always says why");
      for (const r of rs) r.child.stdin!.end();
      await Promise.all(rs.map((r) => r.waitLines(3)));
      const still = rs.map((r) => (JSON.parse(r.lines[2]) as { still: boolean }).still).filter(Boolean).length;
      assert.equal(still, 1, `round ${round}: exactly one holder at the end`);
      assert.deepEqual(tmpLeft(dir), [], "no temp or graveyard files left behind");
    } finally {
      await Promise.all(rs.map((r) => stop(r.child)));
    }
  }
});

// Adversary finding 3: a hostname rename must not leave capture read-only forever.
const MID = "d165c2d88d894a4787be219662b439ad";
const renamed = () => ({ ...hostIdentity(), host: "renamed-host.local", machineId: MID });

test("hostname renamed, same machine id: a dead holder is stale and taken over, not held-by-other-host", async () => {
  const dir = tmpDir();
  const c = await sleeper();
  const pid = c.pid!;
  const start = processStart(pid);
  await stop(c);
  fakeLock(dir, { pid, start, host: "old-host.local", machineId: MID });
  assert.equal(lockHolderAlive(dir, renamed), false);
  const r = acquireLock(dir, { ...selfWriterInfo(), host: "renamed-host.local", machineId: MID }, { host: renamed });
  assert.equal(r.held, true, JSON.stringify(r));
  assert.equal(readLock(dir)?.machineId, MID);
  if (r.held) r.release();
});

test("hostname renamed, same machine id: a live holder is held-by-live-writer, and an unknown start stays unknown", () => {
  const dir = tmpDir();
  fakeLock(dir, { pid: process.pid, start: processStart(process.pid), host: "old-host.local", machineId: MID });
  const r = acquireLock(dir, selfWriterInfo(), { host: renamed });
  assert.equal(r.held, false);
  if (!r.held) assert.equal(r.reason, "held-by-live-writer");
  assert.equal(lockHolderAlive(dir, renamed), true);
  fakeLock(dir, { pid: process.pid, start: null, host: "old-host.local", machineId: MID });
  const r2 = acquireLock(dir, selfWriterInfo(), { host: renamed });
  if (!r2.held) assert.equal(r2.reason, "holder-liveness-unknown");
  assert.equal(r2.held, false);
});

test("same hostname, another machine id: held-by-other-host; an old lock without machineId falls back to the hostname", () => {
  const dir = tmpDir();
  const me = { ...hostIdentity(), machineId: MID };
  fakeLock(dir, { pid: 1, start: null, machineId: "ffffffffffffffffffffffffffffffff" });
  const r = acquireLock(dir, selfWriterInfo(), { host: () => me });
  assert.equal(r.held, false);
  if (!r.held) assert.equal(r.reason, "held-by-other-host");
  fakeLock(dir, { pid: 1, start: null, host: "old-host.local" }); // no machineId field at all
  const r2 = acquireLock(dir, selfWriterInfo(), { host: () => me });
  assert.equal(r2.held, false);
  if (!r2.held) assert.equal(r2.reason, "held-by-other-host");
});

test("selfWriterInfo records the machine id", () => {
  assert.equal(selfWriterInfo().machineId, hostIdentity().machineId ?? null);
});

// Adversary round 2, N6a: cloned machine ids (cloned VMs) with another hostname AND boot id are
// another host for takeover; a rename on the same boot, or a reboot under the same name, is not.
test("same machine id, hostname and boot id both differ: held-by-other-host (cloned-VM guard)", async () => {
  const { clonedMachineSuspect } = await import("./writer-lock.ts");
  const dir = tmpDir();
  const c = await sleeper();
  const pid = c.pid!;
  const start = processStart(pid);
  await stop(c); // dead here, but on a clone it could be alive: never taken over
  fakeLock(dir, { pid, start, host: "clone-a.local", machineId: MID, bootId: "other-boot-0000" });
  const me = () => ({ ...hostIdentity(), host: "clone-b.local", machineId: MID, bootId: "this-boot-1111" });
  assert.equal(lockHolderAlive(dir, me), null, "liveness on another host is unknown");
  const r = acquireLock(dir, { ...selfWriterInfo(), host: "clone-b.local", machineId: MID }, { host: me });
  assert.equal(r.held, false, JSON.stringify(r));
  assert.match(JSON.stringify(r), /held-by-other-host/);
  // A reboot under the same name is still a takeover.
  const sameName = () => ({ ...hostIdentity(), host: "clone-a.local", machineId: MID, bootId: "this-boot-1111" });
  assert.equal(lockHolderAlive(dir, sameName), false);
  assert.equal(clonedMachineSuspect({ host: "a", bootId: "b1", machineId: MID }, { host: "b", bootId: "b1", machineId: MID }), false, "rename, same boot");
  assert.equal(clonedMachineSuspect({ host: "a", bootId: "b1", machineId: MID }, { host: "b", bootId: "b2", machineId: MID, platform: "darwin" }), false, "macOS rename + reboot is the same Mac");
  assert.equal(clonedMachineSuspect({ host: "a", bootId: "b1", machineId: MID }, { host: "b", bootId: "b2", machineId: MID, platform: "linux" }), true, "linux clone");
  assert.equal(clonedMachineSuspect({ host: "a", bootId: "b1", machineId: MID }, { host: "a", bootId: "b2", machineId: MID }), false, "reboot, same name");
  assert.equal(clonedMachineSuspect({ host: "a", bootId: "b1", machineId: null }, { host: "b", bootId: "b2", machineId: MID }), false, "no machine id: hostname decides");
  assert.equal(clonedMachineSuspect({ host: "a", bootId: null, machineId: MID }, { host: "b", bootId: "b2", machineId: MID }), false, "boot unknown");
  assert.equal(clonedMachineSuspect({ host: "a", bootId: "b1", machineId: MID }, { host: "b", bootId: "b2", machineId: MID.toUpperCase() }), true);
});
