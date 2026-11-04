import { test } from "node:test";
import assert from "node:assert/strict";
import type { AgentSnapshot, TurnRecord } from "./types.ts";
import {
  addInterruption,
  addMissing,
  interruptIfStaleDaemon,
  daemonInstanceUnknown,
  openTurn,
  parseDaemonInstance,
  reconcile,
  staleDaemonEvidence,
  type RecordBody,
} from "./reconcile.ts";

const DI = "100:5000:boot-A";
const NOW = Date.parse("2026-11-04T12:00:00.000Z");

function turn(turnId: string | null, extra: Partial<TurnRecord> = {}): TurnRecord {
  return {
    turnKey: `${DI}:3`,
    turnId,
    startedAt: "2026-11-04T11:00:00.000Z",
    endedAt: null,
    outcome: null,
    duringShutdown: false,
    ...extra,
  };
}

function rec(id: string, extra: Partial<RecordBody> = {}): RecordBody {
  return {
    schema: "ade.recovery.passive/v1",
    writer: {
      plugin: "ade-recovery",
      pluginVersion: "0.1.0",
      pid: 7,
      start: "70",
      daemon: { pid: 100, start: "5000" },
      host: "h",
      bootId: "boot-A",
    },
    serverId: "srv",
    paseoAgentId: id,
    provider: "claude",
    cwd: "/w",
    host: "h",
    bootId: "boot-A",
    platform: "linux",
    state: "turn-in-flight",
    daemonInstance: DI,
    turns: [turn("t1")],
    interruptions: [],
    missingTelemetry: [],
    ...extra,
  };
}

/** A refresh fake that records calls; any other SDK use would have to go through it. */
function refresher(map: Record<string, AgentSnapshot | null | Error | "hang">) {
  const calls: string[] = [];
  let active = 0;
  let peak = 0;
  const refresh = async (id: string): Promise<AgentSnapshot | null> => {
    calls.push(id);
    active += 1;
    peak = Math.max(peak, active);
    try {
      await new Promise((r) => setTimeout(r, 3));
      const v = map[id];
      if (v === "hang") return await new Promise<never>(() => undefined);
      if (v instanceof Error) throw v;
      return v === undefined ? null : v;
    } finally {
      active -= 1;
    }
  };
  return { refresh, calls, peak: () => peak };
}

const ctx = (refresh: (id: string) => Promise<AgentSnapshot | null>, extra = {}) => ({
  daemonInstance: DI,
  bootId: "boot-A",
  refresh,
  now: () => NOW,
  ...extra,
});

test("another daemon instance: daemon-restart, decided without any SDK call", async () => {
  const r = refresher({});
  const input = [rec("a", { daemonInstance: "99:4000:boot-A" })];
  const out = await reconcile(input, ctx(r.refresh));
  assert.deepEqual(r.calls, []);
  assert.equal(out.length, 1);
  const w = out[0]!;
  assert.equal(w.agentId, "a");
  assert.equal(w.record.state, "interrupted");
  assert.deepEqual(w.record.interruptions!.map((i) => [i.evidence, i.turnKey, i.detectedAt]), [
    ["daemon-restart", `${DI}:3`, "2026-11-04T12:00:00.000Z"],
  ]);
  assert.deepEqual(w.changes, ["daemon-restart"]);
  assert.equal(input[0]!.state, "turn-in-flight", "the input record is not mutated");
  assert.equal(input[0]!.interruptions!.length, 0);
});

test("a different boot id: boot-id-changed", async () => {
  const r = refresher({});
  const out = await reconcile([rec("a", { daemonInstance: "100:5000:boot-OLD", bootId: "boot-OLD" })], ctx(r.refresh));
  assert.equal(out[0]!.record.interruptions![0]!.evidence, "boot-id-changed");
  assert.deepEqual(r.calls, []);
});

test("a record with no daemonInstance is treated as another daemon's", async () => {
  const r = refresher({});
  const out = await reconcile([rec("a", { daemonInstance: undefined })], ctx(r.refresh));
  assert.equal(out[0]!.record.interruptions![0]!.evidence, "daemon-restart");
});

test("same daemon, still running the same non-null turn: kept, nothing written", async () => {
  const r = refresher({ a: { id: "a", status: "running", activeTurnId: "t1" } });
  const out = await reconcile([rec("a")], ctx(r.refresh));
  assert.deepEqual(r.calls, ["a"]);
  assert.deepEqual(out, []);
});

test("same daemon, running with a null turn id and a null tracked turn: NOT kept (unknown)", async () => {
  const r = refresher({ a: { id: "a", status: "running", activeTurnId: null } });
  const out = await reconcile([rec("a", { turns: [turn(null)] })], ctx(r.refresh));
  assert.equal(out.length, 1);
  const w = out[0]!;
  assert.deepEqual(w.record.turns![0]!.outcome, { kind: "unknown", code: "turn-end-not-observed" });
  assert.equal(w.record.state, "turn-in-flight");
  assert.deepEqual(w.record.interruptions, [], "a missed end is not an interruption");
  assert.ok(w.record.missingTelemetry!.some((m) => m.field === "turnStart"));
  assert.deepEqual(w.changes, ["turn-outcome-unknown"]);
});

test("same daemon, running a different turn: the tracked turn's outcome is unknown", async () => {
  const r = refresher({ a: { id: "a", status: "running", activeTurnId: "t2" } });
  const out = await reconcile([rec("a")], ctx(r.refresh));
  assert.deepEqual(out[0]!.record.turns![0]!.outcome, { kind: "unknown", code: "turn-end-not-observed" });
});

test("same daemon, agent idle (plugin reload missed turn.after): turn-outcome-unknown, not interrupted", async () => {
  const r = refresher({ a: { id: "a", status: "idle", activeTurnId: null } });
  const out = await reconcile([rec("a")], ctx(r.refresh));
  const w = out[0]!;
  assert.equal(w.record.state, "idle");
  assert.deepEqual(w.record.turns![0]!.outcome, { kind: "unknown", code: "turn-end-not-observed" });
  assert.equal(w.record.turns![0]!.endedAt, null, "the end was not observed");
  assert.deepEqual(w.record.interruptions, []);
  assert.deepEqual(w.changes, ["turn-outcome-unknown"]);
});

test("same daemon, agent missing (null, or a not-found error): agent-missing", async () => {
  const notFound = Object.assign(new Error("Agent not found: b"), { code: "NOT_FOUND" });
  const r = refresher({ a: null, b: notFound });
  const out = await reconcile([rec("a"), rec("b")], ctx(r.refresh));
  assert.deepEqual(
    out.map((w) => [w.agentId, w.record.state, w.record.interruptions![0]!.evidence]),
    [
      ["a", "interrupted", "agent-missing"],
      ["b", "interrupted", "agent-missing"],
    ],
  );
});

test("same daemon, agent closed meanwhile: closed-without-turn-end", async () => {
  const r = refresher({ a: { id: "a", status: "closed" } });
  const out = await reconcile([rec("a")], ctx(r.refresh));
  assert.equal(out[0]!.record.state, "closed");
  assert.equal(out[0]!.record.interruptions![0]!.evidence, "closed-without-turn-end");
});

test("same daemon, archived meanwhile: archived state carried over", async () => {
  const r = refresher({ a: { id: "a", status: "idle", archivedAt: "2026-11-04T11:30:00.000Z" } });
  const out = await reconcile([rec("a")], ctx(r.refresh));
  assert.equal(out[0]!.record.state, "archived");
  assert.equal(out[0]!.record.archivedAt, "2026-11-04T11:30:00.000Z");
});

test("refresh errors and timeouts leave the state as recorded, with a reason", async () => {
  const r = refresher({ a: new Error("socket hang up"), b: "hang" });
  const keepAlive = setTimeout(() => undefined, 2000);
  const out = await reconcile([rec("a"), rec("b")], ctx(r.refresh, { timeoutMs: 30 }));
  clearTimeout(keepAlive);
  assert.deepEqual(out.map((w) => [w.agentId, w.record.state, w.changes[0]]), [
    ["a", "turn-in-flight", "refresh-failed"],
    ["b", "turn-in-flight", "refresh-timeout"],
  ]);
  for (const w of out) {
    assert.deepEqual(w.record.interruptions, []);
    assert.ok(w.record.missingTelemetry!.some((m) => m.field === "reconcile"));
  }
});

test("only turn-in-flight records are considered; at most 4 refreshes at once", async () => {
  const map: Record<string, AgentSnapshot | null> = {};
  const records: RecordBody[] = [];
  for (let i = 0; i < 10; i += 1) {
    map[`a${i}`] = { id: `a${i}`, status: "idle" };
    records.push(rec(`a${i}`));
  }
  records.push(rec("idle-one", { state: "idle" }), rec("closed-one", { state: "closed" }), rec("int", { state: "interrupted" }));
  const r = refresher(map);
  const out = await reconcile(records, ctx(r.refresh));
  assert.equal(out.length, 10);
  assert.equal(r.calls.length, 10);
  assert.ok(r.peak() <= 4, `peak ${r.peak()}`);
  assert.ok(!r.calls.includes("idle-one"));
});

test("interruption history is kept (capped at 20, newest last); a new one is appended", async () => {
  const old = Array.from({ length: 20 }, (_, i) => ({
    detectedAt: "2026-11-01T00:00:00.000Z",
    evidence: "daemon-restart" as const,
    turnKey: `x:${i}`,
    detail: "old",
  }));
  const r = refresher({});
  const out = await reconcile([rec("a", { daemonInstance: "1:1:boot-A", interruptions: old })], ctx(r.refresh));
  const list = out[0]!.record.interruptions!;
  assert.equal(list.length, 20);
  assert.equal(list[0]!.turnKey, "x:1");
  assert.equal(list[19]!.turnKey, `${DI}:3`);
});

test("helpers: openTurn, addMissing once per field, staleDaemonEvidence, interruptIfStaleDaemon", () => {
  assert.equal(openTurn({ turns: [] }), null);
  assert.equal(openTurn({ turns: [turn("a", { outcome: { kind: "unknown" } })] }), null);
  const t = turn("b");
  assert.equal(openTurn({ turns: [turn("a", { endedAt: "x", outcome: { kind: "completed" } }), t] }), t);

  const r: Pick<RecordBody, "missingTelemetry"> = {};
  addMissing(r, "f", "one", "t0");
  addMissing(r, "f", "two", "t1");
  assert.deepEqual(r.missingTelemetry, [{ field: "f", reason: "one", at: "t0" }]);

  const i: Pick<RecordBody, "interruptions"> = {};
  addInterruption(i, { detectedAt: "t", evidence: "writer-dead", turnKey: null, detail: "d" }, 2);
  addInterruption(i, { detectedAt: "t", evidence: "agent-missing", turnKey: null, detail: "d" }, 2);
  addInterruption(i, { detectedAt: "t", evidence: "daemon-restart", turnKey: null, detail: "d" }, 2);
  assert.deepEqual(i.interruptions!.map((x) => x.evidence), ["agent-missing", "daemon-restart"]);

  assert.equal(staleDaemonEvidence({ daemonInstance: DI, bootId: "boot-A" }, { daemonInstance: DI, bootId: "boot-A" }), null);
  assert.equal(staleDaemonEvidence({ daemonInstance: "x", bootId: null }, { daemonInstance: DI, bootId: "boot-A" }), "daemon-restart");

  const idle = rec("z", { state: "idle", daemonInstance: "old" });
  assert.equal(interruptIfStaleDaemon(idle, { daemonInstance: DI, bootId: "boot-A" }, "t"), null);
  assert.equal(idle.state, "idle");
});

// Adversary finding 2: a slow `ps` reads the daemon start as null on one plugin load.
test("parseDaemonInstance keeps colons in a ps lstart token and reads null parts", () => {
  assert.deepEqual(parseDaemonInstance("100:Wed Nov 4 22:37:01 2026:boot-A"), { pid: "100", start: "Wed Nov 4 22:37:01 2026", boot: "boot-A" });
  assert.deepEqual(parseDaemonInstance("100:null:boot-A"), { pid: "100", start: null, boot: "boot-A" });
  assert.deepEqual(parseDaemonInstance("100:5000:null"), { pid: "100", start: "5000", boot: null });
  for (const bad of ["d1", "x:1:b", ":1:b", "100:b", undefined, 7]) assert.equal(parseDaemonInstance(bad), null, String(bad));
});

test("daemonInstanceUnknown: same pid and boot with a null start on either side only", () => {
  assert.equal(daemonInstanceUnknown("100:null:boot-A", DI), true);
  assert.equal(daemonInstanceUnknown(DI, "100:null:boot-A"), true);
  assert.equal(daemonInstanceUnknown("100:null:boot-A", "100:null:boot-A"), true);
  assert.equal(daemonInstanceUnknown("101:null:boot-A", DI), false, "another pid");
  assert.equal(daemonInstanceUnknown("100:null:boot-B", DI), false, "another boot");
  assert.equal(daemonInstanceUnknown("100:null:null", "100:5000:null"), false, "boot unknown: no proof of the same boot");
  assert.equal(daemonInstanceUnknown("100:4999:boot-A", DI), false, "two known, different starts: another daemon");
});

test("a null daemon start token is unknown: the refresh path, never daemon-restart", async () => {
  assert.equal(staleDaemonEvidence({ daemonInstance: "100:null:boot-A", bootId: "boot-A" }, { daemonInstance: DI, bootId: "boot-A" }), null);
  // Still running the same turn: kept, nothing written.
  const running = refresher({ a: { id: "a", status: "running", activeTurnId: "t1" } });
  assert.deepEqual(await reconcile([rec("a", { daemonInstance: "100:null:boot-A" })], ctx(running.refresh)), []);
  assert.deepEqual(running.calls, ["a"], "asked the SDK");
  // The current read is the null one; the record has the real start.
  const flipped = refresher({ a: { id: "a", status: "running", activeTurnId: "t1" } });
  assert.deepEqual(await reconcile([rec("a")], ctx(flipped.refresh, { daemonInstance: "100:null:boot-A" })), []);
  assert.deepEqual(flipped.calls, ["a"]);
  // Idle now: the turn end was missed (outcome unknown), not an interruption.
  const idle = refresher({ a: { id: "a", status: "idle", activeTurnId: null } });
  const out = await reconcile([rec("a", { daemonInstance: "100:null:boot-A" })], ctx(idle.refresh));
  assert.equal(out.length, 1);
  assert.equal(out[0]!.record.state, "idle");
  assert.deepEqual(out[0]!.record.interruptions, []);
  assert.deepEqual(out[0]!.changes, ["turn-outcome-unknown"]);
  // upsert's stale check agrees: no interruption is added for the unknown instance.
  const live = rec("b", { daemonInstance: "100:null:boot-A" });
  assert.equal(interruptIfStaleDaemon(live, { daemonInstance: DI, bootId: "boot-A" }, "t"), null);
  assert.equal(live.state, "turn-in-flight");
});

test("a null start with another pid or boot is still another daemon", async () => {
  const r = refresher({});
  const out = await reconcile(
    [rec("a", { daemonInstance: "99:null:boot-A" }), rec("b", { daemonInstance: "100:null:boot-OLD", bootId: "boot-OLD" })],
    ctx(r.refresh),
  );
  assert.deepEqual(r.calls, []);
  assert.deepEqual(out.map((w) => w.changes[0]), ["daemon-restart", "boot-id-changed"]);
});

// Adversary round 2, N3a: the sticky interruption survives the history cap and is added once.
test("addInterruption keeps unobserved-activity past the cap; noteUnobservedActivity bounds", async () => {
  const { addInterruption: add, noteUnobservedActivity } = await import("./reconcile.ts");
  const rec: { interruptions?: import("./types.ts").Interruption[] } = { interruptions: [] };
  add(rec, { detectedAt: "2026-11-04T00:00:00.000Z", evidence: "unobserved-activity", turnKey: null, detail: "" }, 3);
  for (let i = 0; i < 10; i++) add(rec, { detectedAt: "2026-11-04T01:00:00.000Z", evidence: "daemon-restart", turnKey: `k${i}`, detail: "" }, 3);
  assert.equal(rec.interruptions!.length, 3);
  assert.equal(rec.interruptions![0]!.evidence, "unobserved-activity");
  assert.deepEqual(rec.interruptions!.slice(1).map((i) => i.turnKey), ["k8", "k9"]);

  const body = { interruptions: [] } as unknown as import("./reconcile.ts").RecordBody;
  const W = "2026-11-04T11:00:00.000Z";
  const at = "2026-11-04T12:00:00.000Z";
  const before = Date.parse("2026-11-04T12:00:00.000Z");
  assert.equal(noteUnobservedActivity(body, W, "2026-11-04T11:00:02.000Z", before, 2000, at), false, "within tolerance");
  assert.equal(noteUnobservedActivity(body, W, "2026-11-04T11:59:59.000Z", before, 2000, at), false, "at the waking event");
  assert.equal(noteUnobservedActivity(body, W, null, before, 2000, at), false);
  assert.equal(noteUnobservedActivity(body, "bad", "2026-11-04T11:30:00.000Z", before, 2000, at), false);
  assert.equal(noteUnobservedActivity(body, W, "2026-11-04T11:30:00.000Z", before, 2000, at), true);
  assert.equal(noteUnobservedActivity(body, W, "2026-11-04T11:40:00.000Z", Number.POSITIVE_INFINITY, 2000, at), false, "added once");
  assert.equal(body.interruptions!.length, 1);
});
