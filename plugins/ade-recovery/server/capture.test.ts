// Capture state machine, driven with injected fakes (no real store, git or SDK).
import { test } from "node:test";
import assert from "node:assert/strict";
import type {
  AgentSnapshot,
  GitEvidence,
  HookAgent,
  LoadResult,
  PaseoLike,
  RecoveryRecord,
  WriterInfo,
} from "./types.ts";
import { Capture, MAX_BUFFERED_EVENTS, type CaptureDeps, type LockResult, type RecordBody } from "./capture.ts";

const DAEMON = { pid: 4242, start: "777" };
const BOOT = "boot-1";
const DI = `${DAEMON.pid}:${DAEMON.start}:${BOOT}`;
const SERVER = "srv_test-1";

function agent(id = "agent-1", extra: Partial<HookAgent> = {}): HookAgent {
  return {
    id,
    workspaceId: "ws-1",
    parentAgentId: null,
    provider: "claude",
    cwd: "/work/repo",
    title: "curl -H 'Authorization: Bearer SECRET-TITLE'",
    ...extra,
  };
}

function git(head: string, extra: Partial<GitEvidence> = {}): GitEvidence {
  return {
    capturedAt: "2026-11-04T00:00:00.000Z",
    repoTop: "/work/repo",
    isLinkedWorktree: false,
    branch: "main",
    head,
    base: null,
    trackedFingerprint: `tf-${head}`,
    trackedChanged: 0,
    trackedPaths: [],
    untrackedCount: 0,
    untrackedPaths: [],
    untrackedFingerprint: `uf-${head}`,
    truncated: false,
    errors: [],
    ...extra,
  };
}

const MUTATING = ["send", "reload", "archive", "interrupt", "create", "close", "timeline", "prompt", "delete"];

interface FakePaseo extends PaseoLike {
  calls: string[];
}

function fakePaseo(opts: {
  serverId?: unknown;
  hostsList?: () => Promise<unknown>;
  refresh?: (id: string) => Promise<AgentSnapshot | null>;
} = {}): FakePaseo {
  const calls: string[] = [];
  const refresh =
    opts.refresh ??
    (async (id: string): Promise<AgentSnapshot | null> => ({
      id,
      status: "idle",
      persistence: { provider: "claude", sessionId: `sess-${id}`, nativeHandle: { file: "/x/y.jsonl" } },
    }));
  const ref = (id: string) =>
    new Proxy(
      {
        refresh: () => {
          calls.push(`refresh:${id}`);
          return refresh(id);
        },
      } as Record<string, unknown>,
      {
        get(target, prop) {
          if (prop in target) return target[prop as string];
          if (typeof prop === "string" && MUTATING.some((m) => prop.toLowerCase().includes(m))) {
            calls.push(`FORBIDDEN:${prop}`);
            throw new Error(`forbidden SDK call ${prop}`);
          }
          return undefined;
        },
      },
    );
  return {
    calls,
    hosts: {
      list: () => {
        calls.push("hosts.list");
        if (opts.hostsList) return opts.hostsList() as never;
        return Promise.resolve({ self: { serverId: opts.serverId === undefined ? SERVER : opts.serverId } }) as never;
      },
    },
    agents: {
      ref: (id: string) => ref(id) as never,
    },
  };
}

interface Harness {
  capture: Capture;
  deps: CaptureDeps;
  writes: Array<{ agentId: string; body: RecordBody }>;
  logs: string[];
  gitCalls: string[];
  disk: Map<string, LoadResult>;
  lockReleased: () => boolean;
  setShutdown(v: boolean): void;
  advance(ms: number): void;
  lastWrite(agentId: string): RecordBody;
}

function harness(opts: {
  lockHeld?: boolean;
  disk?: Map<string, LoadResult>;
  gitEvidence?: (cwd: string, signal: AbortSignal) => Promise<GitEvidence>;
  writeGeneration?: (dir: string, agentId: string, body: RecordBody) => Promise<unknown>;
  timeouts?: CaptureDeps["timeouts"];
} = {}): Harness {
  const writes: Array<{ agentId: string; body: RecordBody }> = [];
  const logs: string[] = [];
  const gitCalls: string[] = [];
  const disk = opts.disk ?? new Map<string, LoadResult>();
  let released = false;
  let shutting = false;
  let clock = Date.parse("2026-11-04T12:00:00.000Z");
  const writer: WriterInfo = {
    plugin: "ade-recovery",
    pluginVersion: "0.1.0-test",
    pid: 99,
    start: "123",
    daemon: DAEMON,
    host: "testhost",
    bootId: BOOT,
  };
  let headN = 0;
  const deps: CaptureDeps = {
    store: {
      stateRoot: (id) => `/state/${id}`,
      ensureRoot: () => undefined,
      acquireLock: (): LockResult =>
        opts.lockHeld === false
          ? { held: false, holder: { ...writer, pid: 1 }, reason: "held-by-live-writer" }
          : {
              held: true,
              release() {
                released = true;
              },
            },
      writeGeneration:
        opts.writeGeneration ??
        (async (_dir, agentId, body) => {
          writes.push({ agentId, body: structuredClone(body) });
          return body;
        }),
      loadRecord: (_dir, name) => disk.get(name) ?? { record: null, source: "none", problems: [], maxGenerationSeen: 0 },
      listAgents: () => [...disk.keys()],
      sweepTmp: () => undefined,
    },
    gitEvidence:
      opts.gitEvidence ??
      (async (cwd) => {
        gitCalls.push(cwd);
        headN += 1;
        return git(`h${headN}`);
      }),
    host: {
      hostIdentity: () => ({ host: "testhost", bootId: BOOT, platform: "linux" }),
      daemonIdentity: () => DAEMON,
      writerInfo: () => writer,
    },
    now: () => clock,
    shuttingDown: () => shutting,
    log: (m, extra) => logs.push(extra ? `${m} ${JSON.stringify(extra)}` : m),
    hashJson: (v) => `hash(${JSON.stringify(v)})`,
    timeouts: { hostsListMs: 200, refreshMs: 200, gitMs: 500, initRetryMs: 1000, ...(opts.timeouts ?? {}) },
  };
  const capture = new Capture(deps);
  return {
    capture,
    deps,
    writes,
    logs,
    gitCalls,
    disk,
    lockReleased: () => released,
    setShutdown: (v) => {
      shutting = v;
    },
    advance: (ms) => {
      clock += ms;
    },
    lastWrite(agentId) {
      const w = [...writes].reverse().find((x) => x.agentId === agentId);
      assert.ok(w, `no write for ${agentId}`);
      return w.body;
    },
  };
}

function sealedFrom(body: RecordBody, generation = 1): RecoveryRecord {
  return {
    ...structuredClone(body),
    generation,
    writtenAt: "2026-11-04T11:00:00.000Z",
    integrity: { alg: "sha256", digest: "x" },
  } as RecoveryRecord;
}

function baseBody(id: string, extra: Partial<RecordBody> = {}): RecordBody {
  return {
    schema: "ade.recovery.passive/v1",
    writer: {
      plugin: "ade-recovery",
      pluginVersion: "0.0.9",
      pid: 1,
      start: "1",
      daemon: { pid: 1, start: "1" },
      host: "testhost",
      bootId: BOOT,
    },
    serverId: SERVER,
    paseoAgentId: id,
    provider: "claude",
    cwd: "/work/repo",
    host: "testhost",
    bootId: BOOT,
    platform: "linux",
    state: "idle",
    daemonInstance: DI,
    turns: [],
    interruptions: [],
    missingTelemetry: [],
    ...extra,
  };
}

test("create: identity write lands before git, then git fills baseAtCreate and latest", async () => {
  let releaseGit!: () => void;
  const gitGate = new Promise<void>((r) => {
    releaseGit = r;
  });
  const h = harness({
    gitEvidence: async () => {
      await gitGate;
      return git("abc");
    },
  });
  const p = fakePaseo();
  h.capture.onCreate(agent(), p);
  // Wait for init and the first write; git is still blocked.
  for (let i = 0; i < 50 && h.writes.length === 0; i += 1) await new Promise((r) => setTimeout(r, 2));
  assert.equal(h.capture.mode, "active");
  const first = h.writes[0]?.body;
  assert.ok(first);
  assert.equal(first.paseoAgentId, "agent-1");
  assert.equal(first.serverId, SERVER);
  assert.equal(first.state, "idle");
  assert.equal(first.daemonInstance, DI);
  assert.equal(first.git?.latest, null, "first generation is written before git");
  assert.equal(JSON.stringify(first).includes("SECRET-TITLE"), false, "title is never stored");
  assert.equal("title" in first, false);
  releaseGit();
  await h.capture.idle();
  const last = h.lastWrite("agent-1");
  assert.equal(last.git?.baseAtCreate?.head, "abc");
  assert.equal(last.git?.latest?.head, "abc");
  assert.deepEqual(last.persistence, {
    sessionId: "sess-agent-1",
    provider: "claude",
    nativeHandleSha256: 'hash({"file":"/x/y.jsonl"})',
  });
  const fields = (last.missingTelemetry ?? []).map((m) => m.field).sort();
  assert.deepEqual(fields, ["providerVersion", "toolCalls"]);
  assert.match((last.missingTelemetry ?? []).find((m) => m.field === "toolCalls")!.reason, /no tool calls/);
  assert.deepEqual(
    p.calls.filter((c) => c.startsWith("FORBIDDEN")),
    [],
  );
});

test("turn lifecycle: before opens a keyed turn, after closes it; git per boundary", async () => {
  const h = harness();
  const p = fakePaseo();
  h.capture.onCreate(agent(), p);
  h.capture.onTurnBefore(agent(), "t1", p);
  await h.capture.idle();
  let rec = h.lastWrite("agent-1");
  assert.equal(rec.state, "turn-in-flight");
  assert.equal(rec.turns?.length, 1);
  const turn = rec.turns![0]!;
  assert.equal(turn.turnId, "t1");
  assert.equal(turn.turnKey, `${DI}:2`, "turnKey is daemonInstance:seq");
  assert.equal(turn.endedAt, null);
  assert.ok(rec.git?.atTurnStart);
  h.capture.onTurnAfter(agent(), "t1", { kind: "completed" }, p);
  await h.capture.idle();
  rec = h.lastWrite("agent-1");
  assert.equal(rec.state, "idle");
  assert.deepEqual(rec.turns![0]!.outcome, { kind: "completed" });
  assert.ok(rec.turns![0]!.endedAt);
  assert.equal(rec.turns![0]!.duringShutdown, false);
  assert.equal(rec.interruptions?.length, 0);
  assert.equal(h.gitCalls.length, 3, "create, turn.before, turn.after");
  assert.ok(rec.git?.latest && rec.git.latest.head !== rec.git.baseAtCreate?.head);
});

test("a failed turn stores its code, never its message", async () => {
  const h = harness();
  const p = fakePaseo();
  h.capture.onTurnBefore(agent(), "t1", p);
  h.capture.onTurnAfter(
    agent(),
    "t1",
    { kind: "failed", error: { message: "curl -H token=SECRETMSG failed", code: "E_TOOL" } },
    p,
  );
  await h.capture.idle();
  const rec = h.lastWrite("agent-1");
  assert.deepEqual(rec.turns![0]!.outcome, { kind: "failed", code: "E_TOOL" });
  assert.equal(JSON.stringify(rec).includes("SECRETMSG"), false);
});

test("a user cancel (no shutdown) is recorded as canceled, not as an interruption", async () => {
  const h = harness();
  const p = fakePaseo();
  h.capture.onTurnBefore(agent(), "t1", p);
  h.capture.onTurnAfter(agent(), "t1", { kind: "canceled", reason: "user" }, p);
  await h.capture.idle();
  const rec = h.lastWrite("agent-1");
  assert.equal(rec.state, "idle");
  assert.deepEqual(rec.turns![0]!.outcome, { kind: "canceled", code: "user" });
  assert.equal(rec.turns![0]!.duringShutdown, false);
  assert.deepEqual(rec.interruptions, []);
});

test("shutdown: a canceled turn is an interruption, written with no git and no SDK", async () => {
  const h = harness();
  const p = fakePaseo();
  h.capture.onCreate(agent(), p);
  h.capture.onTurnBefore(agent(), "t1", p);
  await h.capture.idle();
  const gitBefore = h.gitCalls.length;
  const sdkBefore = p.calls.length;
  h.setShutdown(true);
  h.capture.onTurnAfter(agent(), "t1", { kind: "canceled", reason: "shutdown" }, p);
  h.capture.onClose(agent(), p);
  await h.capture.idle();
  const rec = h.lastWrite("agent-1");
  assert.equal(rec.state, "closed");
  assert.ok(rec.closedAt);
  assert.equal(rec.turns![0]!.duringShutdown, true);
  assert.deepEqual(rec.turns![0]!.outcome, { kind: "canceled", code: "shutdown" });
  assert.deepEqual(
    rec.interruptions!.map((i) => [i.evidence, i.turnKey]),
    [["canceled-during-shutdown", rec.turns![0]!.turnKey]],
  );
  assert.equal(h.gitCalls.length, gitBefore, "no git during shutdown");
  assert.equal(p.calls.length, sdkBefore, "no SDK call during shutdown");
});

test("shutdown: turn.after canceled alone leaves the state interrupted", async () => {
  const h = harness();
  const p = fakePaseo();
  h.capture.onTurnBefore(agent(), "t1", p);
  await h.capture.idle();
  h.setShutdown(true);
  h.capture.onTurnAfter(agent(), "t1", { kind: "canceled", reason: "x" }, p);
  await h.capture.idle();
  assert.equal(h.lastWrite("agent-1").state, "interrupted");
});

test("close with a turn in flight records closed-without-turn-end; a late canceled turn.after keeps closed", async () => {
  const h = harness();
  const p = fakePaseo();
  h.capture.onTurnBefore(agent(), "t1", p);
  await h.capture.idle();
  h.setShutdown(true);
  h.capture.onClose(agent(), p);
  await h.capture.idle();
  let rec = h.lastWrite("agent-1");
  assert.equal(rec.state, "closed");
  assert.equal(rec.turns![0]!.endedAt, null);
  assert.equal(rec.turns![0]!.duringShutdown, true);
  assert.deepEqual(rec.interruptions!.map((i) => i.evidence), ["closed-without-turn-end"]);
  // Events overlap: the drain can deliver turn.after after close.after.
  h.capture.onTurnAfter(agent(), "t1", { kind: "canceled", reason: "shutdown" }, p);
  await h.capture.idle();
  rec = h.lastWrite("agent-1");
  assert.equal(rec.state, "closed");
  assert.deepEqual(rec.interruptions!.map((i) => i.evidence), ["closed-without-turn-end", "canceled-during-shutdown"]);
  assert.equal(rec.turns!.length, 1, "the late turn.after paired with the open turn");
});

test("close without a turn in flight: no interruption, and no git or SDK even outside shutdown", async () => {
  const h = harness();
  const p = fakePaseo();
  h.capture.onCreate(agent(), p);
  await h.capture.idle();
  const gitBefore = h.gitCalls.length;
  const sdkBefore = p.calls.length;
  h.capture.onClose(agent(), p);
  await h.capture.idle();
  const rec = h.lastWrite("agent-1");
  assert.equal(rec.state, "closed");
  assert.deepEqual(rec.interruptions, []);
  assert.equal(h.gitCalls.length, gitBefore);
  assert.equal(p.calls.length, sdkBefore);
});

test("a null turnId never matches another null", async () => {
  const h = harness();
  const p = fakePaseo();
  h.capture.onTurnBefore(agent(), null, p);
  h.capture.onTurnAfter(agent(), null, { kind: "completed" }, p);
  await h.capture.idle();
  const rec = h.lastWrite("agent-1");
  assert.equal(rec.turns!.length, 2);
  assert.deepEqual(rec.turns![0]!.outcome, { kind: "unknown", code: "null-turn-id" });
  assert.equal(rec.turns![0]!.endedAt, null);
  assert.deepEqual(rec.turns![1]!.outcome, { kind: "completed" });
  assert.notEqual(rec.turns![0]!.turnKey, rec.turns![1]!.turnKey);
  assert.equal(rec.state, "idle");
  assert.ok(rec.missingTelemetry!.some((m) => m.field === "turnId"));
});

test("a missed turn.after is closed as unknown when the next turn starts", async () => {
  const h = harness();
  const p = fakePaseo();
  h.capture.onTurnBefore(agent(), "t1", p);
  h.capture.onTurnBefore(agent(), "t2", p);
  await h.capture.idle();
  const rec = h.lastWrite("agent-1");
  assert.deepEqual(rec.turns![0]!.outcome, { kind: "unknown", code: "turn-end-not-observed" });
  assert.equal(rec.turns![1]!.turnId, "t2");
  assert.equal(rec.state, "turn-in-flight");
});

test("a turn.before arriving after its own turn.after does not reopen the turn", async () => {
  const h = harness();
  const p = fakePaseo();
  h.capture.onTurnAfter(agent(), "t9", { kind: "completed" }, p);
  h.capture.onTurnBefore(agent(), "t9", p);
  await h.capture.idle();
  const rec = h.lastWrite("agent-1");
  assert.equal(rec.turns!.length, 1);
  assert.equal(rec.state, "idle");
  assert.ok(rec.missingTelemetry!.some((m) => m.field === "turnStart"));
});

test("archive sets archived state and the payload's archivedAt", async () => {
  const h = harness();
  const p = fakePaseo();
  h.capture.onCreate(agent(), p);
  h.capture.onArchive(agent(), "2026-11-04T12:30:00.000Z", p);
  await h.capture.idle();
  const rec = h.lastWrite("agent-1");
  assert.equal(rec.state, "archived");
  assert.equal(rec.archivedAt, "2026-11-04T12:30:00.000Z");
});

test("an agent restored from storage (no create.after) gets its identity on its first hook", async () => {
  const h = harness();
  const p = fakePaseo();
  h.capture.onTurnBefore(agent("restored", { cwd: "/w/r2", provider: "codex", workspaceId: null }), "t1", p);
  await h.capture.idle();
  const rec = h.lastWrite("restored");
  assert.equal(rec.paseoAgentId, "restored");
  assert.equal(rec.cwd, "/w/r2");
  assert.equal(rec.provider, "codex");
  assert.equal(rec.host, "testhost");
  assert.equal(rec.platform, "linux");
  assert.equal(rec.bootId, BOOT);
  assert.equal(rec.git?.baseAtCreate ?? null, null, "no base is invented for a restored agent");
});

test("no server id: inert, writes nothing, retries init only after the retry interval", async () => {
  const h = harness();
  const p = fakePaseo({ serverId: null });
  h.capture.onCreate(agent(), p);
  h.capture.onTurnBefore(agent(), "t1", p);
  await h.capture.idle();
  assert.equal(h.capture.mode, "inert");
  assert.equal(h.writes.length, 0);
  assert.equal(h.gitCalls.length, 0);
  assert.ok(h.logs.some((l) => l.startsWith("inert")));
  assert.equal(p.calls.filter((c) => c === "hosts.list").length, 1);
  h.capture.onTurnAfter(agent(), "t1", { kind: "completed" }, p);
  await h.capture.idle();
  assert.equal(p.calls.filter((c) => c === "hosts.list").length, 1, "no retry inside the interval");
  h.advance(1001);
  const p2 = fakePaseo();
  h.capture.onTurnBefore(agent(), "t2", p2);
  await h.capture.idle();
  assert.equal(h.capture.mode, "active");
  assert.ok(h.writes.length > 0);
});

test("an unsafe server id is refused (inert)", async () => {
  const h = harness();
  h.capture.onCreate(agent(), fakePaseo({ serverId: "../../etc" }));
  await h.capture.idle();
  assert.equal(h.capture.mode, "inert");
  assert.equal(h.writes.length, 0);
});

test("hosts.list that hangs: the hook returns at once; init times out to inert", async () => {
  const h = harness({ timeouts: { hostsListMs: 30 } });
  const p = fakePaseo({ hostsList: () => new Promise(() => undefined) });
  const keepAlive = setTimeout(() => undefined, 2000);
  const t0 = performance.now();
  h.capture.onCreate(agent(), p);
  h.capture.onTurnBefore(agent(), "t1", p);
  assert.ok(performance.now() - t0 < 50, "hook handlers do not wait for init");
  await h.capture.idle();
  clearTimeout(keepAlive);
  assert.equal(h.capture.mode, "inert");
  assert.equal(h.writes.length, 0);
});

test("events that arrive while init runs are buffered and applied in order", async () => {
  let resolveHosts!: (v: unknown) => void;
  const h = harness();
  const p = fakePaseo({ hostsList: () => new Promise((r) => (resolveHosts = r)) });
  h.capture.onCreate(agent(), p);
  h.capture.onTurnBefore(agent(), "t1", p);
  h.capture.onTurnAfter(agent(), "t1", { kind: "completed" }, p);
  assert.equal(h.capture.mode, "initializing");
  await new Promise((r) => setImmediate(r)); // hosts.list is called on the next tick
  resolveHosts({ self: { serverId: SERVER } });
  await h.capture.idle();
  const rec = h.lastWrite("agent-1");
  assert.equal(rec.state, "idle");
  assert.equal(rec.turns!.length, 1);
  assert.equal(rec.turns![0]!.turnKey, `${DI}:2`);
  assert.deepEqual(rec.turns![0]!.outcome, { kind: "completed" });
});

test("the init buffer holds at most 500 events; the rest are dropped and logged", async () => {
  let resolveHosts!: (v: unknown) => void;
  const h = harness();
  const p = fakePaseo({ hostsList: () => new Promise((r) => (resolveHosts = r)) });
  for (let i = 0; i < MAX_BUFFERED_EVENTS + 7; i += 1) h.capture.onCreate(agent(`a${i}`), p);
  await new Promise((r) => setImmediate(r));
  resolveHosts({ self: { serverId: SERVER } });
  await h.capture.idle();
  const agentsWritten = new Set(h.writes.map((w) => w.agentId));
  assert.equal(agentsWritten.size, MAX_BUFFERED_EVENTS);
  assert.ok(h.logs.some((l) => l.includes("dropped events beyond the init buffer") && l.includes('"count":7')));
});

test("lock held by another writer: read-only, nothing written, no git, no refresh", async () => {
  const h = harness({ lockHeld: false });
  const p = fakePaseo();
  h.capture.onCreate(agent(), p);
  h.capture.onTurnBefore(agent(), "t1", p);
  await h.capture.idle();
  assert.equal(h.capture.mode, "read-only");
  assert.equal(h.writes.length, 0);
  assert.equal(h.gitCalls.length, 0);
  assert.deepEqual(p.calls, ["hosts.list"]);
  assert.equal(h.capture.record("agent-1")?.state, "turn-in-flight", "state is still kept in memory");
  assert.ok(h.logs.some((l) => l.startsWith("read-only")));
});

test("git failure is missing telemetry, never a crash; an older capture never overwrites a newer one", async () => {
  let n = 0;
  const gates: Array<() => void> = [];
  const h = harness({
    gitEvidence: async () => {
      n += 1;
      const mine = n;
      if (mine === 1) throw new Error("boom");
      if (mine === 2) {
        // turn.after for t1: held back until after t2's capture lands
        await new Promise<void>((r) => gates.push(r));
        return git("old");
      }
      return git(`new${mine}`);
    },
  });
  const p = fakePaseo();
  h.capture.onCreate(agent(), p); // git #1 throws
  await h.capture.idle();
  assert.ok(h.lastWrite("agent-1").missingTelemetry!.some((m) => m.field === "git" && /git capture failed/.test(m.reason)));
  h.capture.onTurnBefore(agent(), "t1", p);
  await new Promise((r) => setTimeout(r, 5));
  // #2 is the atTurnStart capture for t1 (held); then t1 ends and t2's after captures latest.
  h.capture.onTurnAfter(agent(), "t1", { kind: "completed" }, p); // latest #3
  await new Promise((r) => setTimeout(r, 5));
  gates.forEach((g) => g());
  await h.capture.idle();
  const rec = h.lastWrite("agent-1");
  assert.equal(rec.git?.latest?.head, "new3");
  assert.equal(rec.git?.atTurnStart?.head, "old");
});

test("seq ordering: a slower capture for an older event does not replace the newer slot value", async () => {
  const releases: Array<() => void> = [];
  let n = 0;
  const h = harness({
    gitEvidence: async () => {
      n += 1;
      const mine = n;
      if (mine === 1) await new Promise<void>((r) => releases.push(r));
      return git(`g${mine}`);
    },
  });
  const p = fakePaseo();
  h.capture.onCreate(agent(), p); // g1 (slow) -> baseAtCreate + latest, seq 1
  await new Promise((r) => setTimeout(r, 5));
  h.capture.onTurnBefore(agent(), "t1", p); // g2 -> atTurnStart, seq 2
  h.capture.onTurnAfter(agent(), "t1", { kind: "completed" }, p); // g3 -> latest, seq 3
  for (let i = 0; i < 50 && h.lastWrite("agent-1").git?.latest?.head !== "g3"; i += 1) {
    await new Promise((r) => setTimeout(r, 2));
  }
  assert.equal(h.lastWrite("agent-1").git?.latest?.head, "g3");
  releases.forEach((r) => r());
  await h.capture.idle();
  const rec = h.lastWrite("agent-1");
  assert.equal(rec.git?.baseAtCreate?.head, "g1");
  assert.equal(rec.git?.latest?.head, "g3", "the create-time capture landed last but is older");
});

test("recorded-at-create base fills a later capture that found no origin/HEAD", async () => {
  const h = harness();
  const p = fakePaseo();
  h.capture.onCreate(agent(), p);
  await h.capture.idle();
  h.capture.onTurnBefore(agent(), "t1", p);
  await h.capture.idle();
  const rec = h.lastWrite("agent-1");
  assert.deepEqual(rec.git?.atTurnStart?.base, { ref: "HEAD@create", sha: "h1", method: "recorded-at-create" });
  assert.equal(rec.git?.baseAtCreate?.base, null);
});

test("refresh without a persistence handle, or failing, is missing telemetry", async () => {
  const h = harness();
  const p = fakePaseo({ refresh: async () => { throw new Error("nope"); } });
  h.capture.onCreate(agent(), p);
  await h.capture.idle();
  const rec = h.lastWrite("agent-1");
  assert.equal(rec.persistence, null);
  assert.ok(rec.missingTelemetry!.some((m) => m.field === "persistence" && /refresh failed/.test(m.reason)));
});

test("init: loads records, reconciles a turn left by another daemon, keeps foreign records untouched", async () => {
  const disk = new Map<string, LoadResult>();
  const stale = baseBody("old-agent", {
    state: "turn-in-flight",
    daemonInstance: "1:1:boot-1",
    turns: [{ turnKey: "1:1:boot-1:5", turnId: "tx", startedAt: "2026-11-04T10:00:00.000Z", endedAt: null, outcome: null, duringShutdown: false }],
  });
  disk.set("old-agent", { record: sealedFrom(stale), source: "current", problems: [], maxGenerationSeen: 1 });
  disk.set("future", { record: null, source: "none", problems: ["unknown-schema"], maxGenerationSeen: 3 });
  const fellBack = baseBody("fb", {
    turns: [{ turnKey: `${DI}:1`, turnId: "t", startedAt: "2026-11-04T10:00:00.000Z", endedAt: "2026-11-04T10:01:00.000Z", outcome: { kind: "completed" }, duringShutdown: false }],
  });
  disk.set("fb", { record: sealedFrom(fellBack, 4), source: "prev", problems: ["current:bad-integrity", "corrupt-fell-back-to-prev"], maxGenerationSeen: 5 });
  const h = harness({ disk });
  const p = fakePaseo();
  h.capture.onCreate(agent("future"), p);
  await h.capture.idle();
  const old = h.lastWrite("old-agent");
  assert.equal(old.state, "interrupted");
  assert.deepEqual(old.interruptions!.map((i) => [i.evidence, i.turnKey]), [["daemon-restart", "1:1:boot-1:5"]]);
  assert.equal("integrity" in old, false);
  assert.equal("generation" in old, false);
  const fb = h.lastWrite("fb");
  assert.deepEqual(fb.turns![0]!.outcome, { kind: "unknown", code: "record-fell-back-to-prev" });
  assert.ok(fb.missingTelemetry!.some((m) => m.field === "generation"));
  assert.equal(h.writes.some((w) => w.agentId === "future"), false, "a newer schema's record is never overwritten");
  assert.equal(p.calls.filter((c) => c.startsWith("refresh:old-agent")).length, 0, "another daemon's record needs no SDK");
});

test("too large: retried once without path lists; other write errors keep memory and retry next event", async () => {
  let calls = 0;
  const bodies: RecordBody[] = [];
  const h = harness({
    gitEvidence: async () => git("p", { trackedPaths: ["a", "b"], untrackedPaths: ["c"], trackedChanged: 2, untrackedCount: 1 }),
    writeGeneration: async (_d, _id, body) => {
      calls += 1;
      if (calls === 1) {
        const e = new Error("disk full") as NodeJS.ErrnoException;
        e.code = "ENOSPC";
        throw e;
      }
      if (body.git?.latest && body.git.latest.trackedPaths.length > 0) {
        const e = new Error("record too large") as NodeJS.ErrnoException;
        e.code = "ERECORDTOOLARGE";
        throw e;
      }
      bodies.push(structuredClone(body));
      return body;
    },
  });
  const p = fakePaseo();
  h.capture.onCreate(agent(), p);
  await h.capture.idle();
  assert.ok(h.logs.some((l) => l.includes("previous generation kept") && l.includes("error")));
  const last = bodies[bodies.length - 1]!;
  assert.equal(last.git?.latest?.trackedPaths.length, 0);
  assert.equal(last.git?.latest?.trackedChanged, 2);
  assert.equal(last.git?.latest?.truncated, true);
});

test("close: releases the lock, drops later events, never throws, is idempotent", async () => {
  const h = harness();
  const p = fakePaseo();
  h.capture.onCreate(agent(), p);
  await h.capture.idle();
  await h.capture.close();
  await h.capture.close();
  assert.equal(h.lockReleased(), true);
  assert.equal(h.capture.mode, "closed");
  const before = h.writes.length;
  h.capture.onTurnBefore(agent(), "t1", p);
  await h.capture.idle();
  assert.equal(h.writes.length, before);
});

test("bad payloads never throw out of a hook", async () => {
  const h = harness();
  const p = fakePaseo();
  assert.doesNotThrow(() => h.capture.onCreate(undefined as never, p));
  assert.doesNotThrow(() => h.capture.onTurnAfter(agent(), "t", undefined as never, p));
  assert.doesNotThrow(() => h.capture.onClose(agent(), undefined as never));
  await h.capture.idle();
  assert.doesNotThrow(() => h.capture.onTurnBefore({} as never, "t", p));
  await h.capture.idle();
  const rec = h.lastWrite("agent-1");
  assert.deepEqual(rec.turns![0]!.outcome, { kind: "unknown", code: "no-outcome" });
});

test("shuttingDown that throws is read as shutting down (no git)", async () => {
  const h = harness();
  h.deps.shuttingDown = () => {
    throw new Error("stat failed");
  };
  const p = fakePaseo();
  h.capture.onCreate(agent(), p);
  await h.capture.idle();
  assert.equal(h.gitCalls.length, 0);
  assert.ok(h.writes.length > 0);
});

// Adversary finding 8 (partial): an init failure logs a code or name, never the raw message.
test("init failure logs the error code and name only, never a message carrying a path", async () => {
  const h = harness();
  h.deps.store.ensureRoot = () => {
    const e = new Error("EACCES: permission denied, mkdir '/Users/secret-user/.local/state/ade'") as NodeJS.ErrnoException;
    e.code = "EACCES";
    throw e;
  };
  h.capture.onCreate(agent(), fakePaseo());
  await h.capture.idle();
  assert.equal(h.capture.mode, "inert");
  const inert = h.logs.filter((l) => l.startsWith("inert"));
  assert.equal(inert.length, 1, h.logs.join("\n"));
  assert.match(inert[0]!, /"reason":"error:EACCES"/);
  assert.equal(h.logs.some((l) => l.includes("secret-user") || l.includes("/Users/")), false, h.logs.join("\n"));
});

test("init failure with our own reason code keeps the code (no-server-id)", async () => {
  const h = harness();
  h.capture.onCreate(agent(), fakePaseo({ serverId: null }));
  await h.capture.idle();
  assert.ok(h.logs.some((l) => l.includes('"reason":"no-server-id:invalid"')), h.logs.join("\n"));
});

// Adversary finding 2: the previous load read the daemon start as null (slow ps); same pid, same boot.
test("init: a record from the same daemon pid and boot with a null start takes the refresh path", async () => {
  const disk = new Map<string, LoadResult>();
  const nullDI = `${DAEMON.pid}:null:${BOOT}`;
  const body = baseBody("agent-1", {
    state: "turn-in-flight",
    daemonInstance: nullDI,
    turns: [{ turnKey: `${nullDI}:1`, turnId: "t1", startedAt: "2026-11-04T10:00:00.000Z", endedAt: null, outcome: null, duringShutdown: false }],
  });
  disk.set("agent-1", { record: sealedFrom(body), source: "current", problems: [], maxGenerationSeen: 1 });
  const h = harness({ disk });
  const p = fakePaseo({ refresh: async (id) => ({ id, status: "running", activeTurnId: "t1" }) });
  h.capture.onTurnBefore(agent("other"), "x", p);
  await h.capture.idle();
  assert.ok(p.calls.includes("refresh:agent-1"), `asked the SDK: ${p.calls.join(",")}`);
  assert.equal(h.writes.some((w) => w.agentId === "agent-1"), false, "still running the same turn: kept, nothing written");
  // The turn then ends under the current (known) start: no daemon-restart interruption appears.
  h.capture.onTurnAfter(agent("agent-1"), "t1", { kind: "completed" }, p);
  await h.capture.idle();
  const rec = h.lastWrite("agent-1");
  assert.deepEqual(rec.interruptions, []);
  assert.equal(rec.state, "idle");
  assert.equal(rec.daemonInstance, DI);
});

test("records carry the machine id from the host identity", async () => {
  const h = harness();
  h.deps.host.hostIdentity = () => ({ host: "testhost", bootId: BOOT, platform: "linux", machineId: "d165c2d88d894a4787be219662b439ad" });
  h.capture.onCreate(agent(), fakePaseo());
  await h.capture.idle();
  assert.equal(h.lastWrite("agent-1").machineId, "d165c2d88d894a4787be219662b439ad");
});
