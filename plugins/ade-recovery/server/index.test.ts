// End to end: index.server.ts wired to the REAL store, lock, host identity, state root and
// git evidence, driven through a fake Paseo server context into a temp state root.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { EventEmitter } from "node:events";
import type { AgentSnapshot, GitEvidence, HookAgent, LiveEvidence, PaseoLike, TurnOutcome } from "./types.ts";
import contribute, { HOOK_NAMES, createRecoveryPlugin, productionDeps, type HookContextLike, type ServerLike } from "../index.server.ts";
import { loadRecord, listAgents } from "./store.ts";
import { stateRoot } from "./state-root.ts";
import { lockHolderAlive, readLock } from "./writer-lock.ts";
import { gitEvidence } from "./git-evidence.ts";
import { hostIdentity } from "./host-identity.ts";
import { judge } from "./verdict.ts";

const SERVER_ID = "srv_e2e-1";

type Handler = (payload: unknown, ctx: HookContextLike) => Promise<void>;

function fakeServer(): ServerLike & { names: string[]; handlers: Map<string, Handler>; removed: string[] } {
  const names: string[] = [];
  const removed: string[] = [];
  const handlers = new Map<string, Handler>();
  return {
    names,
    removed,
    handlers,
    addHook(name: string, handler: never) {
      names.push(name);
      handlers.set(name, handler as Handler);
      return () => {
        removed.push(name);
      };
    },
  };
}

/** A Paseo SDK fake: hosts.list and agents.ref(id).refresh only; anything else throws. */
function strictPaseo(opts: { serverId?: string | null; refresh?: (id: string) => Promise<AgentSnapshot | null> } = {}) {
  const used: string[] = [];
  const forbidden: string[] = [];
  const trap = <T extends object>(label: string, target: T): T =>
    new Proxy(target, {
      get(t, prop) {
        if (typeof prop === "symbol" || prop === "then") return (t as Record<PropertyKey, unknown>)[prop];
        if (prop in t) return (t as Record<string, unknown>)[prop];
        forbidden.push(`${label}.${prop}`);
        throw new Error(`forbidden SDK access ${label}.${prop}`);
      },
    });
  const paseo = trap("paseo", {
    hosts: trap("hosts", {
      list: async () => {
        used.push("hosts.list");
        return { self: opts.serverId === null ? null : { serverId: opts.serverId ?? SERVER_ID } };
      },
    }),
    agents: trap("agents", {
      ref: (id: string) =>
        trap(`agents.ref(${id})`, {
          refresh: async () => {
            used.push(`refresh:${id}`);
            if (opts.refresh) return opts.refresh(id);
            return {
              id,
              status: "idle",
              persistence: { provider: "claude", sessionId: `sess-${id}`, nativeHandle: { path: "/n/h" } },
            } satisfies AgentSnapshot;
          },
        }),
    }),
  }) as unknown as PaseoLike;
  return { paseo, used, forbidden };
}

function tempEnv(t: { after(fn: () => void): void }) {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), "ade-recovery-index-"));
  t.after(() => fs.rmSync(base, { recursive: true, force: true }));
  const state = path.join(base, "state");
  const paseoHome = path.join(base, "paseo");
  const repo = path.join(base, "repo");
  fs.mkdirSync(paseoHome, { mode: 0o700 });
  fs.writeFileSync(path.join(paseoHome, "local-credential"), "x", { mode: 0o600 });
  fs.mkdirSync(repo);
  const gitEnv = { ...process.env, GIT_CONFIG_NOSYSTEM: "1", GIT_CONFIG_GLOBAL: "/dev/null", HOME: base };
  const g = (...args: string[]) => execFileSync("git", args, { cwd: repo, env: gitEnv, stdio: "pipe", timeout: 10_000 });
  g("init", "-q", "-b", "main");
  g("config", "user.email", "t@example.invalid");
  g("config", "user.name", "t");
  fs.writeFileSync(path.join(repo, "a.txt"), "one\n");
  g("add", "a.txt");
  g("commit", "-q", "-m", "init");
  const env: NodeJS.ProcessEnv = { ...process.env, ADE_STATE_ROOT: state, PASEO_HOME: paseoHome };
  delete env.XDG_STATE_HOME;
  return { base, state, paseoHome, repo, env, dir: stateRoot(SERVER_ID, env) };
}

function hookAgent(id: string, cwd: string): HookAgent {
  return { id, workspaceId: "ws", parentAgentId: null, provider: "claude", cwd, title: "secret title TOKEN=abc" };
}

async function fire(server: ReturnType<typeof fakeServer>, name: string, payload: unknown, paseo: PaseoLike) {
  const h = server.handlers.get(name);
  assert.ok(h, `no handler for ${name}`);
  const t0 = performance.now();
  await h(payload, { paseo, signal: new AbortController().signal });
  assert.ok(performance.now() - t0 < 1000, `${name} returned within 1 s`);
}

async function live(repo: string, dir: string): Promise<LiveEvidence> {
  const git: GitEvidence = await gitEvidence(repo);
  return {
    now: Date.now(),
    host: hostIdentity(),
    git,
    writerAlive: lockHolderAlive(dir),
    recordWriterAlive: null,
    recoveryScheduledElsewhere: null,
    serverId: SERVER_ID,
  };
}

test("registers exactly the five notification hooks and never agent.open.before", async () => {
  const server = fakeServer();
  const proc = new EventEmitter();
  const { cleanup } = createRecoveryPlugin(server, { process: proc, env: { HOME: os.tmpdir() } });
  assert.deepEqual(server.names, [...HOOK_NAMES]);
  assert.deepEqual(server.names, [
    "agent.create.after",
    "agent.turn.before",
    "agent.turn.after",
    "agent.close.after",
    "agent.archive.after",
  ]);
  assert.equal((server.names as string[]).includes("agent.open.before"), false);
  assert.equal(proc.listenerCount("disconnect"), 1);
  await cleanup();
  assert.deepEqual(server.removed.sort(), [...HOOK_NAMES].sort());
  assert.equal(proc.listenerCount("disconnect"), 0);
});

test("default export: contribute returns a cleanup function and registers the same hooks", async (t) => {
  const e = tempEnv(t);
  const saved = { ADE_STATE_ROOT: process.env.ADE_STATE_ROOT, PASEO_HOME: process.env.PASEO_HOME };
  process.env.ADE_STATE_ROOT = e.state;
  process.env.PASEO_HOME = e.paseoHome;
  t.after(() => {
    for (const [k, v] of Object.entries(saved)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  });
  const server = fakeServer();
  const before = process.listenerCount("disconnect");
  const cleanup = contribute(server);
  assert.equal(typeof cleanup, "function");
  assert.deepEqual(server.names, [...HOOK_NAMES]);
  const { paseo, forbidden } = strictPaseo();
  await fire(server, "agent.create.after", { agent: hookAgent("dflt", e.repo) }, paseo);
  await fire(server, "agent.close.after", { agent: hookAgent("dflt", e.repo) }, paseo);
  for (let i = 0; i < 200 && listAgents(e.dir).length === 0; i += 1) await new Promise((r) => setTimeout(r, 10));
  await cleanup();
  assert.equal(process.listenerCount("disconnect"), before);
  assert.deepEqual(forbidden, []);
  const load = loadRecord(e.dir, "dflt");
  assert.equal(load.source, "current");
  assert.equal(load.record?.state, "closed");
});

test("create -> turn -> close end to end into a temp root: valid generations, resumable after a clean turn", async (t) => {
  const e = tempEnv(t);
  const server = fakeServer();
  const proc = new EventEmitter();
  let gitCalls = 0;
  const { capture, cleanup } = createRecoveryPlugin(server, {
    env: e.env,
    process: proc,
    deps: {
      gitEvidence: (cwd, signal) => {
        gitCalls += 1;
        return gitEvidence(cwd, signal);
      },
    },
  });
  t.after(() => cleanup());
  const { paseo, used, forbidden } = strictPaseo();
  const a = hookAgent("agent-e2e", e.repo);

  await fire(server, "agent.create.after", { agent: a }, paseo);
  await capture.idle();
  assert.equal(capture.mode, "active");
  assert.ok(fs.existsSync(path.join(e.dir, "writer.lock")), "writer lock held while active");
  assert.equal(readLock(e.dir)?.pid, process.pid);
  assert.equal(fs.statSync(e.dir).mode & 0o777, 0o700);
  let load = loadRecord(e.dir, a.id);
  assert.equal(load.source, "current");
  assert.deepEqual(load.problems, []);
  assert.equal(load.record?.state, "idle");
  assert.equal(load.record?.serverId, SERVER_ID);
  assert.ok(load.record?.git?.baseAtCreate?.head, "baseAtCreate captured");
  assert.equal(load.record?.persistence?.sessionId, "sess-agent-e2e");
  assert.match(load.record?.persistence?.nativeHandleSha256 ?? "", /^[0-9a-f]{64}$/);
  const raw = fs.readFileSync(path.join(e.dir, `${a.id}.json`), "utf8");
  assert.equal(raw.includes("TOKEN=abc"), false, "the agent title is never stored");
  assert.equal(fs.statSync(path.join(e.dir, `${a.id}.json`)).mode & 0o777, 0o600);

  await fire(server, "agent.turn.before", { agent: a, turnId: "turn-1" }, paseo);
  await capture.idle();
  load = loadRecord(e.dir, a.id);
  assert.equal(load.record?.state, "turn-in-flight");
  assert.equal(judge(load, await live(e.repo, e.dir)).verdict, "needs-review", "a live turn is never resumable");

  fs.writeFileSync(path.join(e.repo, "a.txt"), "two\n"); // the turn edits a file
  await fire(server, "agent.turn.after", { agent: a, turnId: "turn-1", outcome: { kind: "completed" }, timeline: [] }, paseo);
  await capture.idle();
  load = loadRecord(e.dir, a.id);
  assert.equal(load.record?.state, "idle");
  assert.deepEqual(load.record?.turns?.at(-1)?.outcome, { kind: "completed" });
  assert.equal(load.record?.git?.latest?.trackedChanged, 1);
  const v1 = judge(load, await live(e.repo, e.dir));
  assert.equal(v1.verdict, "resumable-native", JSON.stringify(v1));

  // The tree moves on after the record: the verdict notices.
  fs.writeFileSync(path.join(e.repo, "a.txt"), "three\n");
  assert.ok(judge(load, await live(e.repo, e.dir)).reasons.includes("dirty-tree-changed"));
  fs.writeFileSync(path.join(e.repo, "a.txt"), "two\n");

  await fire(server, "agent.close.after", { agent: a }, paseo);
  await capture.idle();
  load = loadRecord(e.dir, a.id);
  assert.equal(load.record?.state, "closed");
  assert.ok((load.record?.generation ?? 0) >= 4);
  assert.equal(gitCalls, 3, "git at create, turn.before and turn.after; none at close");

  assert.deepEqual(forbidden, [], "no mutating SDK call");
  assert.ok(used.every((u) => u === "hosts.list" || u.startsWith("refresh:")));
  await cleanup();
  assert.equal(fs.existsSync(path.join(e.dir, "writer.lock")), false, "cleanup releases the lock");
});

test("shutdown: a canceled turn is recorded as an interruption with no git and no SDK", async (t) => {
  const e = tempEnv(t);
  const server = fakeServer();
  let gitCalls = 0;
  const { capture, cleanup } = createRecoveryPlugin(server, {
    env: e.env,
    process: new EventEmitter(),
    deps: {
      gitEvidence: (cwd, signal) => {
        gitCalls += 1;
        return gitEvidence(cwd, signal);
      },
    },
  });
  t.after(() => cleanup());
  const { paseo, used, forbidden } = strictPaseo();
  const a = hookAgent("agent-sd", e.repo);
  await fire(server, "agent.create.after", { agent: a }, paseo);
  await fire(server, "agent.turn.before", { agent: a, turnId: "t1" }, paseo);
  await capture.idle();
  const gitBefore = gitCalls;
  const sdkBefore = used.length;

  fs.rmSync(path.join(e.paseoHome, "local-credential")); // the daemon's first stop step
  const canceled: TurnOutcome = { kind: "canceled", reason: "shutdown" };
  await fire(server, "agent.turn.after", { agent: a, turnId: "t1", outcome: canceled, timeline: [] }, paseo);
  await fire(server, "agent.close.after", { agent: a }, paseo);
  await capture.idle();

  const load = loadRecord(e.dir, a.id);
  const r = load.record!;
  assert.equal(r.state, "closed");
  assert.equal(r.turns?.at(-1)?.duringShutdown, true);
  assert.deepEqual(r.interruptions?.map((i) => i.evidence), ["canceled-during-shutdown"]);
  assert.equal(gitCalls, gitBefore, "no git after shutdown began");
  assert.equal(used.length, sdkBefore, "no SDK call after shutdown began");
  assert.deepEqual(forbidden, []);
  const v = judge(load, await live(e.repo, e.dir));
  assert.equal(v.verdict, "needs-review");
  assert.ok(v.reasons.includes("interrupted:canceled-during-shutdown"));
  assert.ok(v.reasons.includes("tools-unobserved"));
  assert.equal(v.reasons.includes("canceled-outside-shutdown"), false, "a shutdown cancel is not canceled-outside-shutdown");
});

test("a user cancel outside shutdown reads as do-not-resume", async (t) => {
  const e = tempEnv(t);
  const server = fakeServer();
  const { capture, cleanup } = createRecoveryPlugin(server, { env: e.env, process: new EventEmitter() });
  t.after(() => cleanup());
  const { paseo } = strictPaseo();
  const a = hookAgent("agent-uc", e.repo);
  await fire(server, "agent.turn.before", { agent: a, turnId: "t1" }, paseo);
  await fire(server, "agent.turn.after", { agent: a, turnId: "t1", outcome: { kind: "canceled", reason: "user" }, timeline: [] }, paseo);
  await capture.idle();
  const v = judge(loadRecord(e.dir, a.id), await live(e.repo, e.dir));
  assert.equal(v.verdict, "do-not-resume");
  assert.ok(v.reasons.includes("canceled-outside-shutdown"));
});

test("null turnId: before(null) and after(null) are not paired", async (t) => {
  const e = tempEnv(t);
  const server = fakeServer();
  const { capture, cleanup } = createRecoveryPlugin(server, { env: e.env, process: new EventEmitter() });
  t.after(() => cleanup());
  const { paseo } = strictPaseo();
  const a = hookAgent("agent-null", e.repo);
  await fire(server, "agent.turn.before", { agent: a, turnId: null }, paseo);
  await fire(server, "agent.turn.after", { agent: a, turnId: null, outcome: { kind: "completed" }, timeline: [] }, paseo);
  await capture.idle();
  const r = loadRecord(e.dir, a.id).record!;
  assert.equal(r.turns?.length, 2);
  assert.deepEqual(r.turns?.[0]?.outcome, { kind: "unknown", code: "null-turn-id" });
  assert.deepEqual(r.turns?.[1]?.outcome, { kind: "completed" });
  assert.ok(r.missingTelemetry?.some((m) => m.field === "turnId"));
});

test("no server id: inert, nothing created under the state root", async (t) => {
  const e = tempEnv(t);
  const server = fakeServer();
  const logs: string[] = [];
  const { capture, cleanup } = createRecoveryPlugin(server, {
    env: e.env,
    process: new EventEmitter(),
    deps: { log: (m) => logs.push(m) },
  });
  t.after(() => cleanup());
  const { paseo } = strictPaseo({ serverId: null });
  await fire(server, "agent.create.after", { agent: hookAgent("x", e.repo) }, paseo);
  await fire(server, "agent.turn.before", { agent: hookAgent("x", e.repo), turnId: "t" }, paseo);
  await capture.idle();
  assert.equal(capture.mode, "inert");
  assert.equal(fs.existsSync(e.state), false);
  assert.equal(logs.filter((l) => l.startsWith("inert")).length, 1, "logged once");
});

test("restart: a second plugin instance (new daemon) marks the left-over turn interrupted", async (t) => {
  const e = tempEnv(t);
  const a = hookAgent("agent-rs", e.repo);
  const s1 = fakeServer();
  const p1 = createRecoveryPlugin(s1, {
    env: e.env,
    process: new EventEmitter(),
    deps: { host: { hostIdentity, daemonIdentity: () => ({ pid: 11111, start: "old-daemon" }) } },
  });
  const { paseo } = strictPaseo();
  await fire(s1, "agent.turn.before", { agent: a, turnId: "t1" }, paseo);
  await p1.capture.idle();
  await p1.cleanup(); // the old plugin child goes away mid-turn

  const s2 = fakeServer();
  const p2 = createRecoveryPlugin(s2, { env: e.env, process: new EventEmitter() });
  t.after(() => p2.cleanup());
  const other = hookAgent("agent-other", e.repo);
  await fire(s2, "agent.create.after", { agent: other }, paseo); // first hook runs lazy init + reconcile
  await p2.capture.idle();
  const r = loadRecord(e.dir, a.id).record!;
  assert.equal(r.state, "interrupted");
  assert.deepEqual(r.interruptions?.map((i) => i.evidence), ["daemon-restart"]);

  // A later turn (a continuation) does not clear the history.
  await fire(s2, "agent.turn.before", { agent: a, turnId: "t2" }, paseo);
  await fire(s2, "agent.turn.after", { agent: a, turnId: "t2", outcome: { kind: "completed" }, timeline: [] }, paseo);
  await p2.capture.idle();
  const r2 = loadRecord(e.dir, a.id).record!;
  assert.deepEqual(r2.interruptions?.map((i) => i.evidence), ["daemon-restart"]);
  assert.equal(r2.state, "idle");
});

test("a second live writer runs read-only and writes nothing", async (t) => {
  const e = tempEnv(t);
  const s1 = fakeServer();
  const p1 = createRecoveryPlugin(s1, { env: e.env, process: new EventEmitter() });
  t.after(() => p1.cleanup());
  const { paseo } = strictPaseo();
  await fire(s1, "agent.create.after", { agent: hookAgent("one", e.repo) }, paseo);
  await p1.capture.idle();
  const s2 = fakeServer();
  const p2 = createRecoveryPlugin(s2, { env: e.env, process: new EventEmitter(), deps: { log: () => undefined } });
  t.after(() => p2.cleanup());
  await fire(s2, "agent.create.after", { agent: hookAgent("two", e.repo) }, paseo);
  await p2.capture.idle();
  assert.equal(p2.capture.mode, "read-only");
  assert.equal(loadRecord(e.dir, "two").source, "none");
  await p2.cleanup();
  assert.ok(fs.existsSync(path.join(e.dir, "writer.lock")), "the read-only instance does not remove the holder's lock");
});

test("disconnect (daemon gone): flush, release the lock, exit 0", async (t) => {
  const e = tempEnv(t);
  const server = fakeServer();
  const proc = new EventEmitter();
  let exitCode: number | null = null;
  let exited!: () => void;
  const exitedP = new Promise<void>((r) => (exited = r));
  const { capture } = createRecoveryPlugin(server, {
    env: e.env,
    process: proc,
    exit: (code) => {
      exitCode = code;
      exited();
    },
  });
  const { paseo } = strictPaseo();
  await fire(server, "agent.turn.before", { agent: hookAgent("dc", e.repo), turnId: "t1" }, paseo);
  await capture.idle();
  assert.ok(fs.existsSync(path.join(e.dir, "writer.lock")));
  proc.emit("disconnect");
  proc.emit("disconnect"); // a repeat is ignored
  await exitedP;
  assert.equal(exitCode, 0);
  assert.equal(fs.existsSync(path.join(e.dir, "writer.lock")), false);
  assert.equal(loadRecord(e.dir, "dc").record?.state, "turn-in-flight");
});

test("production Paseo reader: lastActivityAt from the daemon's store, one agents-dir listing per pass (B2, B5)", (t) => {
  const e = tempEnv(t);
  const d = path.join(e.paseoHome, "agents", "proj");
  fs.mkdirSync(d, { recursive: true });
  const rec = { id: "a1", provider: "claude", cwd: e.repo, updatedAt: "2026-11-04T12:00:00.000Z", lastActivityAt: "2026-11-04T10:00:00.000Z" };
  fs.writeFileSync(path.join(d, "a1.json"), JSON.stringify(rec));
  const read = productionDeps(e.env).paseoActivityReader!();
  assert.equal(read("a1"), "2026-11-04T10:00:00.000Z", "a store-only updatedAt bump is not activity");
  assert.equal(read("nobody"), null);
});
