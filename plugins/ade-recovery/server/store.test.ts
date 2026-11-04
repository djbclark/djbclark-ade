import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { listAgents, loadRecord, resetStoreCache, sweepTmp, writeGeneration } from "./store.ts";
import type { RecordDraft } from "./store.ts";
import { ensureRoot, agentFileName } from "./state-root.ts";
import { acquireLock, selfWriterInfo } from "./writer-lock.ts";
import { hostIdentity } from "./host-identity.ts";
import { validateRecord, sealRecord } from "./record.ts";
import { CRASH_POINTS, MAX_RECORD_BYTES, SCHEMA } from "./constants.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const WRITE_ONCE = path.join(here, "fixtures", "write-once.ts");

function tmpRoot(): string {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), "ade-recovery-store-"));
  return ensureRoot(path.join(base, "ade", "srv-test", "ade-recovery", "recovery", "v1"));
}

function draft(agentId: string, extra: Partial<RecordDraft> = {}): RecordDraft {
  const h = hostIdentity();
  return {
    schema: SCHEMA,
    writer: selfWriterInfo(),
    serverId: "srv-test",
    paseoAgentId: agentId,
    provider: "claude",
    cwd: "/tmp/work",
    host: h.host,
    bootId: h.bootId,
    platform: h.platform,
    state: "idle",
    ...extra,
  };
}

interface ChildResult {
  code: number | null;
  signal: NodeJS.Signals | null;
  acks: number[];
  stderr: string;
}

function runChild(dir: string, agentId: string, count: number, crashAt?: string): Promise<ChildResult> {
  return new Promise((resolve, reject) => {
    const env: NodeJS.ProcessEnv = { ...process.env };
    delete env.ADE_RECOVERY_CRASH_AT;
    delete env.ADE_RECOVERY_TEST;
    if (crashAt) {
      env.ADE_RECOVERY_TEST = "1";
      env.ADE_RECOVERY_CRASH_AT = crashAt;
    }
    const child = spawn(
      process.execPath,
      ["--disable-warning=ExperimentalWarning", WRITE_ONCE, dir, agentId, String(count)],
      { env, stdio: ["ignore", "pipe", "pipe"] },
    );
    let out = "";
    let err = "";
    child.stdout.on("data", (b) => (out += b));
    child.stderr.on("data", (b) => (err += b));
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      reject(new Error(`write-once timed out: ${err}`));
    }, 30000);
    child.on("error", reject);
    child.on("close", (code, signal) => {
      clearTimeout(timer);
      const acks = [...out.matchAll(/^ack (\d+)$/gm)].map((m) => Number(m[1]));
      resolve({ code, signal, acks, stderr: err });
    });
  });
}

function tmpNames(dir: string): string[] {
  return fs.readdirSync(dir).filter((n) => n.startsWith(".tmp-")).sort();
}

test("writes generations atomically with prev, modes 0600 files / 0700 dirs", async () => {
  const dir = tmpRoot();
  assert.equal(fs.statSync(dir).mode & 0o777, 0o700);
  assert.equal(fs.statSync(path.dirname(dir)).mode & 0o777, 0o700, "created parents are 0700 too");
  const a = await writeGeneration(dir, "agent-1", draft("agent-1"));
  assert.equal(a.generation, 1);
  assert.equal(validateRecord(a).ok, true);
  const b = await writeGeneration(dir, "agent-1", draft("agent-1", { state: "closed" }));
  assert.equal(b.generation, 2);
  const load = loadRecord(dir, "agent-1");
  assert.equal(load.source, "current");
  assert.deepEqual(load.problems, []);
  assert.equal(load.record?.generation, 2);
  assert.equal(load.record?.state, "closed");
  assert.equal(load.maxGenerationSeen, 2);
  const prev = validateRecord(fs.readFileSync(path.join(dir, "agent-1.prev.json")));
  assert.ok(prev.ok && prev.record.generation === 1);
  for (const f of ["agent-1.json", "agent-1.prev.json"]) {
    assert.equal(fs.statSync(path.join(dir, f)).mode & 0o777, 0o600, f);
  }
  assert.deepEqual(tmpNames(dir), [], "no temp files left after clean writes");
  assert.deepEqual(listAgents(dir), ["agent-1"]);
});

test("every crash point: reader returns a valid generation >= the last acknowledged one", async () => {
  for (const point of CRASH_POINTS) {
    const dir = tmpRoot();
    const id = "agent-crash";
    const base = await runChild(dir, id, 2);
    assert.equal(base.code, 0, base.stderr);
    assert.deepEqual(base.acks, [1, 2]);
    let lastAck = 2;
    let lastSeen = 2;
    // Crash twice in a row at the same point: leftover temp files must not break the next write.
    for (let round = 0; round < 2; round++) {
      const crashed = await runChild(dir, id, 1, point);
      assert.equal(crashed.signal, "SIGKILL", `${point}: child must die by SIGKILL (stderr: ${crashed.stderr})`);
      assert.deepEqual(crashed.acks, [], `${point}: no ack from a crashed write`);
      const load = loadRecord(dir, id);
      assert.equal(load.source, "current", `${point}: current stays readable`);
      assert.deepEqual(load.problems, [], point);
      assert.ok(load.record && validateRecord(load.record).ok, point);
      assert.ok(load.record!.generation >= lastAck, `${point}: generation ${load.record!.generation} < ack ${lastAck}`);
      assert.ok(load.record!.generation >= lastSeen, `${point}: generation went backwards`);
      lastSeen = load.record!.generation;
      const prev = validateRecord(fs.readFileSync(path.join(dir, `${id}.prev.json`)));
      assert.ok(prev.ok, `${point}: prev stays valid`);
    }
    const after = await runChild(dir, id, 1);
    assert.equal(after.code, 0, `${point}: write after crash: ${after.stderr}`);
    assert.equal(after.acks.length, 1);
    assert.ok(after.acks[0] > lastSeen, `${point}: next generation ${after.acks[0]} must exceed ${lastSeen}`);
    lastAck = after.acks[0];
    const final = loadRecord(dir, id);
    assert.equal(final.record?.generation, lastAck, point);
    // Temp files from the crashes have distinct random names; the lock holder sweeps them once old.
    // Exact counts prove where each crash landed: tmp only, tmp + prev temp, or nothing (renamed).
    const expected: Record<string, number> = {
      "after-tmp-write": 2,
      "after-tmp-sync": 2,
      "after-prev-link": 4,
      "after-prev-rename": 2,
      "after-rename": 0,
    };
    const leftovers = tmpNames(dir);
    assert.equal(leftovers.length, expected[point], `${point}: leftovers ${leftovers}`);
    if (point === "after-prev-link") assert.equal(leftovers.filter((n) => n.startsWith(".tmp-prev-")).length, 2);
    assert.equal(new Set(leftovers).size, leftovers.length);
    const lock = acquireLock(dir, selfWriterInfo());
    assert.equal(lock.held, true);
    const old = (Date.now() - 11 * 60 * 1000) / 1000;
    for (const n of leftovers) fs.utimesSync(path.join(dir, n), old, old);
    const swept = sweepTmp(dir);
    assert.equal(swept.skipped, null);
    assert.deepEqual(swept.removed, leftovers);
    if (lock.held) lock.release();
    assert.deepEqual(tmpNames(dir), []);
    assert.equal(loadRecord(dir, id).record?.generation, lastAck);
  }
});

test("a crash during the very first write leaves either nothing or generation 1", async () => {
  for (const point of ["after-tmp-write", "after-tmp-sync", "after-rename"]) {
    const dir = tmpRoot();
    const crashed = await runChild(dir, "first", 1, point);
    assert.equal(crashed.signal, "SIGKILL", point);
    const load = loadRecord(dir, "first");
    if (point === "after-rename") {
      assert.equal(load.record?.generation, 1, point);
    } else {
      assert.equal(load.record, null, point);
      assert.equal(load.source, "none");
      assert.deepEqual(load.problems, []);
    }
    const next = await runChild(dir, "first", 1);
    assert.equal(next.code, 0, next.stderr);
    assert.equal(loadRecord(dir, "first").record?.generation, next.acks[0]);
  }
});

test("crash points are ignored without ADE_RECOVERY_TEST=1", async () => {
  const dir = tmpRoot();
  const r = await new Promise<ChildResult>((resolve) => {
    const env = { ...process.env, ADE_RECOVERY_CRASH_AT: "after-tmp-write" };
    delete env.ADE_RECOVERY_TEST;
    const c = spawn(process.execPath, ["--disable-warning=ExperimentalWarning", WRITE_ONCE, dir, "x", "1"], { env });
    let out = "";
    c.stdout.on("data", (b) => (out += b));
    c.on("close", (code, signal) => resolve({ code, signal, acks: [...out.matchAll(/^ack (\d+)$/gm)].map((m) => Number(m[1])), stderr: "" }));
  });
  assert.equal(r.code, 0);
  assert.deepEqual(r.acks, [1]);
});

test("truncated current falls back to prev; next generation skips the corrupt number; good prev is kept", async () => {
  const dir = tmpRoot();
  await writeGeneration(dir, "t", draft("t"));
  await writeGeneration(dir, "t", draft("t"));
  const cur = path.join(dir, "t.json");
  const raw = fs.readFileSync(cur);
  fs.writeFileSync(cur, raw.subarray(0, Math.floor(raw.length / 2)));
  const load = loadRecord(dir, "t");
  assert.equal(load.source, "prev");
  assert.equal(load.record?.generation, 1);
  assert.ok(load.problems.includes("corrupt-fell-back-to-prev"));
  assert.ok(load.problems.includes("current:not-json"));
  assert.equal(load.maxGenerationSeen, 2, "generation read from the truncated text");
  resetStoreCache(); // as a fresh process would
  const next = await writeGeneration(dir, "t", draft("t"));
  assert.equal(next.generation, 3, "must not reuse the corrupt generation 2");
  const prev = validateRecord(fs.readFileSync(path.join(dir, "t.prev.json")));
  assert.ok(prev.ok && prev.record.generation === 1, "a corrupt current never overwrites a good prev");
});

test("bad integrity in current falls back to prev", async () => {
  const dir = tmpRoot();
  await writeGeneration(dir, "bi", draft("bi"));
  await writeGeneration(dir, "bi", draft("bi"));
  const cur = path.join(dir, "bi.json");
  const j = JSON.parse(fs.readFileSync(cur, "utf8"));
  j.cwd = "/elsewhere";
  fs.writeFileSync(cur, JSON.stringify(j));
  const load = loadRecord(dir, "bi");
  assert.equal(load.source, "prev");
  assert.deepEqual(load.problems, ["current:bad-integrity", "corrupt-fell-back-to-prev"]);
});

test("both generations corrupt -> corrupt-no-valid-generation; nothing on disk -> none", async () => {
  const dir = tmpRoot();
  await writeGeneration(dir, "bc", draft("bc"));
  await writeGeneration(dir, "bc", draft("bc"));
  fs.writeFileSync(path.join(dir, "bc.json"), "{\"generation\":2,");
  fs.writeFileSync(path.join(dir, "bc.prev.json"), "");
  const load = loadRecord(dir, "bc");
  assert.equal(load.record, null);
  assert.equal(load.source, "none");
  assert.ok(load.problems.includes("corrupt-no-valid-generation"));
  assert.equal(load.maxGenerationSeen, 2);
  const none = loadRecord(dir, "never-written");
  assert.deepEqual(none, { record: null, source: "none", problems: [], maxGenerationSeen: 0 });
});

test("unknown schema in current: no record, and the writer refuses to overwrite it", async () => {
  const dir = tmpRoot();
  const future = sealRecord({ ...(draft("u") as object), schema: "ade.recovery.passive/v2", generation: 7, writtenAt: new Date().toISOString() } as never);
  fs.writeFileSync(path.join(dir, "u.json"), JSON.stringify(future));
  const load = loadRecord(dir, "u");
  assert.equal(load.record, null);
  assert.deepEqual(load.problems, ["unknown-schema"]);
  assert.equal(load.maxGenerationSeen, 7);
  await assert.rejects(writeGeneration(dir, "u", draft("u")), { code: "EUNKNOWNSCHEMA" });
});

test("fixed-name prev temp files cannot collide; temp names are random", async () => {
  const dir = tmpRoot();
  await writeGeneration(dir, "c", draft("c"));
  // Names an older design used, left behind by a crash: they must not block the next write.
  for (const n of ["prev.tmp", "c.prev.tmp", ".tmp-prev"]) fs.writeFileSync(path.join(dir, n), "junk");
  fs.mkdirSync(path.join(dir, `.tmp-prev-${process.pid}`));
  const seen = new Set<string>();
  const realLink = fs.promises.link;
  const io = {
    link: async (a: string, b: string) => {
      seen.add(path.basename(b));
      await realLink(a, b);
    },
  };
  for (let i = 0; i < 5; i++) await writeGeneration(dir, "c", draft("c"), { io });
  assert.equal(seen.size, 5, "each write uses a fresh random prev temp name");
  assert.equal(loadRecord(dir, "c").record?.generation, 6);
});

test("filesystem without hard links: prev is copied, fsynced and 0600", async () => {
  const dir = tmpRoot();
  await writeGeneration(dir, "nl", draft("nl"));
  const io = {
    link: async () => {
      throw Object.assign(new Error("operation not permitted"), { code: "EPERM" });
    },
  };
  await writeGeneration(dir, "nl", draft("nl"), { io });
  const prevPath = path.join(dir, "nl.prev.json");
  const prev = validateRecord(fs.readFileSync(prevPath));
  assert.ok(prev.ok && prev.record.generation === 1);
  assert.equal(fs.statSync(prevPath).mode & 0o777, 0o600);
  assert.notEqual(fs.statSync(prevPath).ino, fs.statSync(path.join(dir, "nl.json")).ino);
  await assert.rejects(
    writeGeneration(dir, "nl", draft("nl"), { io: { link: async () => { throw Object.assign(new Error("io"), { code: "EIO" }); } } }),
    { code: "EIO" },
  );
  assert.equal(loadRecord(dir, "nl").record?.generation, 2, "an unexpected link error keeps the previous generation");
  assert.deepEqual(tmpNames(dir), []);
});

test("ENOSPC mid-write: rejects, previous generation intact, no temp left, generation not reused", async () => {
  const dir = tmpRoot();
  await writeGeneration(dir, "e", draft("e"));
  await writeGeneration(dir, "e", draft("e"));
  const before = fs.readFileSync(path.join(dir, "e.json"));
  const beforePrev = fs.readFileSync(path.join(dir, "e.prev.json"));
  const io = {
    write: async (fh: fs.promises.FileHandle, data: Buffer) => {
      await fh.write(data, 0, Math.floor(data.length / 2));
      throw Object.assign(new Error("no space left on device"), { code: "ENOSPC" });
    },
  };
  await assert.rejects(writeGeneration(dir, "e", draft("e"), { io }), { code: "ENOSPC" });
  assert.deepEqual(fs.readFileSync(path.join(dir, "e.json")), before);
  assert.deepEqual(fs.readFileSync(path.join(dir, "e.prev.json")), beforePrev);
  assert.deepEqual(tmpNames(dir), []);
  assert.equal(loadRecord(dir, "e").record?.generation, 2);
  const next = await writeGeneration(dir, "e", draft("e"));
  assert.equal(next.generation, 4, "the failed write spent generation 3");
  assert.equal(loadRecord(dir, "e").record?.generation, next.generation);
});

test("record over the size cap is refused and the previous generation kept", async () => {
  const dir = tmpRoot();
  await writeGeneration(dir, "big", draft("big"));
  const huge = draft("big", { missingTelemetry: [{ field: "x", reason: "y".repeat(MAX_RECORD_BYTES), at: "now" }] });
  await assert.rejects(writeGeneration(dir, "big", huge), { code: "ERECORDTOOLARGE" });
  assert.equal(loadRecord(dir, "big").record?.generation, 1);
  assert.deepEqual(tmpNames(dir), []);
  // An oversized file on disk is rejected by the reader without being read whole.
  fs.writeFileSync(path.join(dir, "big.json"), "{\"generation\":5," + " ".repeat(MAX_RECORD_BYTES) + "}");
  const load = loadRecord(dir, "big");
  assert.ok(load.problems.includes("current:too-large"));
  assert.equal(load.maxGenerationSeen, 5);
});

test("agent id must match the record, unsafe ids hash to h-<sha256>", async () => {
  const dir = tmpRoot();
  await assert.rejects(writeGeneration(dir, "a", draft("b")), /does not match/);
  const odd = "../../etc/passwd";
  await writeGeneration(dir, odd, draft(odd));
  const key = agentFileName(odd);
  assert.match(key, /^h-[0-9a-f]{64}$/);
  assert.ok(fs.existsSync(path.join(dir, `${key}.json`)));
  assert.deepEqual(listAgents(dir), [key]);
  assert.equal(loadRecord(dir, odd).record?.paseoAgentId, odd);
  assert.equal(loadRecord(dir, key).record?.paseoAgentId, odd, "listAgents keys load directly");
});

test("concurrent writes for one agent are serialized with unique generations", async () => {
  const dir = tmpRoot();
  const out = await Promise.all(Array.from({ length: 10 }, () => writeGeneration(dir, "par", draft("par"))));
  assert.deepEqual(out.map((r) => r.generation).sort((a, b) => a - b), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  assert.equal(loadRecord(dir, "par").record?.generation, 10);
  assert.deepEqual(tmpNames(dir), []);
});

test("sweepTmp: only the lock holder sweeps, only .tmp-* older than 10 minutes", () => {
  const dir = tmpRoot();
  const old = (Date.now() - 11 * 60 * 1000) / 1000;
  for (const n of [".tmp-a-1-x", ".tmp-prev-1-y", "keep.json"]) {
    fs.writeFileSync(path.join(dir, n), "x");
    fs.utimesSync(path.join(dir, n), old, old);
  }
  fs.writeFileSync(path.join(dir, ".tmp-young-1-z"), "x");
  assert.deepEqual(sweepTmp(dir), { removed: [], skipped: "not-lock-holder" });
  assert.equal(tmpNames(dir).length, 3);
  const lock = acquireLock(dir, selfWriterInfo());
  assert.equal(lock.held, true);
  assert.deepEqual(sweepTmp(dir).removed, [".tmp-a-1-x", ".tmp-prev-1-y"]);
  assert.deepEqual(tmpNames(dir), [".tmp-young-1-z"]);
  assert.ok(fs.existsSync(path.join(dir, "keep.json")));
  if (lock.held) lock.release();
  assert.equal(sweepTmp(dir).skipped, "not-lock-holder");
});

test("listAgents: current and prev-only keys, ignores lock and temp files, missing dir is empty", async () => {
  const dir = tmpRoot();
  await writeGeneration(dir, "one", draft("one"));
  fs.writeFileSync(path.join(dir, "two.prev.json"), "{}");
  fs.writeFileSync(path.join(dir, "writer.lock"), "{}");
  fs.writeFileSync(path.join(dir, ".tmp-one-1-abc"), "{}");
  fs.writeFileSync(path.join(dir, "bad.name.json"), "{}");
  assert.deepEqual(listAgents(dir), ["one", "two"]);
  assert.deepEqual(listAgents(path.join(dir, "nope")), []);
  const two = loadRecord(dir, "two");
  assert.equal(two.record, null);
  assert.deepEqual(two.problems, ["current:missing", "unknown-schema"], "{} has no schema");
});

test("ensureRoot refuses a group- or world-writable root and one owned by another uid", () => {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), "ade-recovery-root-"));
  const gw = path.join(base, "gw");
  fs.mkdirSync(gw);
  fs.chmodSync(gw, 0o770);
  assert.throws(() => ensureRoot(gw), /group- or world-writable/);
  fs.chmodSync(gw, 0o702);
  assert.throws(() => ensureRoot(gw), /group- or world-writable/);
  fs.chmodSync(gw, 0o755);
  assert.equal(ensureRoot(gw), gw, "a pre-existing 0755 dir is accepted and left unchanged");
  assert.equal(fs.statSync(gw).mode & 0o777, 0o755);
  const file = path.join(base, "f");
  fs.writeFileSync(file, "");
  assert.throws(() => ensureRoot(file), /not a directory/);
  if (typeof process.getuid === "function" && process.getuid() === 0) {
    const other = path.join(base, "other");
    fs.mkdirSync(other, { mode: 0o700 });
    fs.chownSync(other, 12345, 12345);
    assert.throws(() => ensureRoot(other), /owned by uid 12345/);
  }
});
