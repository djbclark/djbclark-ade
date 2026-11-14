import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import {
  HANDLER_BUDGET_MS,
  handleAgentEvent,
  isDefaultTitle,
  isDryRun,
  isFirstAgent,
  registerAdeWindowNameHooks,
  resolveDecisionScript,
  resolvePluginRoot,
  runDecision,
  validName,
} from "./name-lib.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const PLUGIN_ROOT = join(HERE, "..");
const SCRIPT = join(PLUGIN_ROOT, "..", "..", "bin", "ade_ws_autoname.py");
const LEAD = "8cd86203-d33b-49db-abde-9baba52bcf61";
const T0 = "2026-11-14T10:00:00.000Z";
const T1 = "2026-11-14T10:00:05.000Z";

/**
 * One fake daemon: windows keyed by id (so a call on the wrong id is caught), their agents, and a record of every setTitle as
 * [windowId, title]. `windowTitle` sets the title of the primary window `wks_0000000000000001`.
 */
const WID = "wks_0000000000000001";
function fakeDaemon({ windowTitle = null, windowBackground = false, agents, otherWindows = {} }) {
  const state = {
    windows: { [WID]: { id: WID, title: windowTitle, background: windowBackground }, ...otherWindows },
    agents,
    calls: [],
    get titles() {
      return this.calls.map((c) => c[1]);
    },
  };
  const paseo = {
    workspaces: {
      ref: (id) => ({
        refresh: async () => (state.windows[id] ? { ...state.windows[id] } : null),
        setTitle: async (t) => {
          state.calls.push([id, t]);
          state.windows[id].title = t;
          return { title: t };
        },
      }),
    },
    agents: {
      ref: (id) => ({ refresh: async () => ({ agent: state.agents.find((a) => a.id === id) }) }),
      list: async () => ({ entries: state.agents.map((agent) => ({ agent })) }),
    },
  };
  return { state, paseo };
}

const agentRec = (over = {}) => ({
  id: "agent-1", workspaceId: "wks_0000000000000001", cwd: "/x", title: "Fix the thing", labels: {}, createdAt: T0, ...over,
});
const hookAgent = (a) => ({ id: a.id, workspaceId: a.workspaceId, cwd: a.cwd, title: null, parentAgentId: a.parentAgentId ?? null, background: false });

const gitDir = (() => {
  const base = realpathSync(mkdtempSync(join(tmpdir(), "ade-wn-")));
  const repo = join(base, "my-repo");
  mkdirSync(repo, { recursive: true });
  return { base, repo };
})();

const lines = [];
const baseDeps = (extra = {}) => ({
  env: { ADE_WS_AUTONAME_PY: SCRIPT },
  pluginRoot: PLUGIN_ROOT,
  log: (l) => lines.push(l),
  now: () => Date.parse(T1), // the agents are seconds old
  settled: new Set(),
  ...extra,
});

test("operator-started first agent in a default-named window: MAIN <repo> (<work>), real decision script", async () => {
  const a = agentRec({ cwd: gitDir.repo, title: "Fix the thing" });
  const { state, paseo } = fakeDaemon({ agents: [a] });
  const rec = await handleAgentEvent(hookAgent(a), { paseo }, baseDeps());
  assert.equal(rec.outcome, "renamed");
  assert.deepEqual(state.titles, ["MAIN my-repo (Fix the thing)"]);
});

test("a worker (parent id or ade.lead label) gets WORKERS, and a worker tab title reduces to its slice", async () => {
  const a = agentRec({ cwd: gitDir.repo, title: `worker auto-naming ${LEAD}`, labels: { "ade.lead": LEAD } });
  const d1 = fakeDaemon({ agents: [a] });
  await handleAgentEvent(hookAgent(a), { paseo: d1.paseo }, baseDeps());
  assert.deepEqual(d1.state.titles, ["WORKERS my-repo (auto-naming)"]);
  const b = agentRec({ cwd: gitDir.repo, title: "Review the diff", parentAgentId: "lead-1" });
  const d2 = fakeDaemon({ agents: [b] });
  await handleAgentEvent(hookAgent(b), { paseo: d2.paseo }, baseDeps());
  assert.deepEqual(d2.state.titles, ["WORKERS my-repo (Review the diff)"]);
});

test("a window that already has a title (a human's, ade-worker-run's, or ours) is never renamed", async () => {
  for (const title of ["my own name", "WORKERS my-repo (Wave 7)", "MAIN my-repo (x)", "  x "]) {
    const a = agentRec({ cwd: gitDir.repo });
    const { state, paseo } = fakeDaemon({ windowTitle: title, agents: [a] });
    const rec = await handleAgentEvent(hookAgent(a), { paseo }, baseDeps());
    assert.equal(rec.outcome, "skip", title);
    assert.deepEqual(state.titles, [], title);
  }
});

test("a non-git cwd names the window after the directory", async () => {
  const dir = join(gitDir.base, "plain-dir");
  mkdirSync(dir);
  const a = agentRec({ cwd: dir, title: "Look around" });
  const { state, paseo } = fakeDaemon({ agents: [a] });
  await handleAgentEvent(hookAgent(a), { paseo }, baseDeps());
  assert.deepEqual(state.titles, ["MAIN plain-dir (Look around)"]);
});

test("a second agent joining an unnamed window does not name it; the earlier agent's retry still can", async () => {
  const first = agentRec({ id: "first", cwd: gitDir.repo, title: "First job", createdAt: T0 });
  const second = agentRec({ id: "second", cwd: gitDir.repo, title: "Second job", createdAt: T1 });
  const d = fakeDaemon({ agents: [first, second] });
  const deps = baseDeps();  // one settled set across both events, as in the running plugin
  const rec = await handleAgentEvent(hookAgent(second), { paseo: d.paseo }, deps);
  assert.equal(rec.outcome, "skip");
  assert.deepEqual(d.state.titles, []);
  assert.equal(deps.settled.size, 0);
  await handleAgentEvent(hookAgent(first), { paseo: d.paseo }, deps);
  assert.deepEqual(d.state.titles, ["MAIN my-repo (First job)"]);
});

test("no agent title yet: skip with retry, not settled; the next event names it", async () => {
  const a = agentRec({ cwd: gitDir.repo, title: null });
  const d = fakeDaemon({ agents: [a] });
  const deps = baseDeps();
  const rec = await handleAgentEvent(hookAgent(a), { paseo: d.paseo }, deps);
  assert.equal(rec.outcome, "skip");
  assert.equal(deps.settled.size, 0);
  a.title = "Now titled";
  await handleAgentEvent(hookAgent(a), { paseo: d.paseo }, deps);
  assert.deepEqual(d.state.titles, ["MAIN my-repo (Now titled)"]);
  const again = await handleAgentEvent(hookAgent(a), { paseo: d.paseo }, deps);
  assert.equal(again.reason, "window settled");
});

test("background agent, background window, and an agent without a window are skipped", async () => {
  const a = agentRec({ cwd: gitDir.repo });
  const d = fakeDaemon({ agents: [a] });
  assert.equal((await handleAgentEvent({ ...hookAgent(a), background: true }, { paseo: d.paseo }, baseDeps())).outcome, "skip");
  assert.equal((await handleAgentEvent({ ...hookAgent(a), workspaceId: null }, { paseo: d.paseo }, baseDeps())).outcome, "skip");
  const bg = fakeDaemon({ windowBackground: true, agents: [a] });
  assert.equal((await handleAgentEvent(hookAgent(a), { paseo: bg.paseo }, baseDeps())).outcome, "skip");
  assert.deepEqual([...d.state.titles, ...bg.state.titles], []);
});

test("a name given between the decision and the write wins", async () => {
  const a = agentRec({ cwd: gitDir.repo });
  const d = fakeDaemon({ agents: [a] });
  const run = async (args) => {
    d.state.windows[WID].title = "named by ade-worker-run meanwhile";
    return runDecision(args);
  };
  const rec = await handleAgentEvent(hookAgent(a), { paseo: d.paseo }, baseDeps({ run }));
  assert.equal(rec.reason, "window was named while deciding");
  assert.deepEqual(d.state.titles, []);
});

test("dry run logs the planned name and renames nothing", async () => {
  const a = agentRec({ cwd: gitDir.repo });
  const d = fakeDaemon({ agents: [a] });
  const rec = await handleAgentEvent(hookAgent(a), { paseo: d.paseo }, baseDeps({ env: { ADE_WS_AUTONAME_PY: SCRIPT, ADE_WINDOW_NAME_DRY_RUN: "1" } }));
  assert.equal(rec.outcome, "would-rename");
  assert.equal(rec.name, "MAIN my-repo (Fix the thing)");
  assert.deepEqual(d.state.titles, []);
});

test("a failing decision script or daemon call is logged as an error and never thrown", async () => {
  const a = agentRec({ cwd: gitDir.repo });
  const d = fakeDaemon({ agents: [a] });
  const rec = await handleAgentEvent(hookAgent(a), { paseo: d.paseo }, baseDeps({ env: { ADE_WS_AUTONAME_PY: "/nonexistent/x.py" } }));
  assert.equal(rec.outcome, "error");
  const broken = { workspaces: { ref: () => ({ refresh: async () => { throw new Error("daemon gone"); } }) } };
  assert.equal((await handleAgentEvent(hookAgent(a), { paseo: broken }, baseDeps())).outcome, "error");
});

test("isDryRun and isFirstAgent", () => {
  for (const v of [undefined, "", "0", "false", "No", "off"]) assert.equal(isDryRun({ ADE_WINDOW_NAME_DRY_RUN: v }), false, String(v));
  for (const v of ["1", "true", "yes"]) assert.equal(isDryRun({ ADE_WINDOW_NAME_DRY_RUN: v }), true, v);
  const me = { id: "a", createdAt: T1 };
  assert.equal(isFirstAgent(me, []), true);
  assert.equal(isFirstAgent(me, [{ agent: { id: "b", createdAt: T0 } }]), false);
  assert.equal(isFirstAgent(me, [{ agent: { id: "b", createdAt: "2026-11-14T10:00:09.000Z" } }]), true);
  assert.equal(isFirstAgent({ id: "a" }, [{ id: "b", createdAt: T0 }]), false);
});

test("script and plugin-root resolution", () => {
  assert.equal(resolveDecisionScript({ env: {}, pluginRoot: PLUGIN_ROOT }), join(PLUGIN_ROOT, "..", "..", "bin", "ade_ws_autoname.py"));
  assert.throws(() => resolveDecisionScript({ env: { ADE_WS_AUTONAME_PY: "relative.py" }, pluginRoot: PLUGIN_ROOT }), /not readable/);
  assert.throws(() => resolveDecisionScript({ env: {}, pluginRoot: "/nonexistent/plugin" }), /not readable/);
  assert.equal(resolvePluginRoot({ metaUrl: undefined, home: "/nonexistent-home" }), "/nonexistent-home/src/djbclark-ade/plugins/ade-window-name");
  assert.equal(resolvePluginRoot({ metaUrl: import.meta.url }), PLUGIN_ROOT);
});

test("both hooks register, run one at a time per window, and unregister", async () => {
  const handlers = new Map();
  let offs = 0;
  const server = { addHook: (name, fn) => (handlers.set(name, fn), () => { offs += 1; }) };
  const a = agentRec({ cwd: gitDir.repo });
  const d = fakeDaemon({ agents: [a] });
  const off = registerAdeWindowNameHooks(server, baseDeps());
  assert.deepEqual([...handlers.keys()].sort(), ["agent.create.after", "agent.turn.after"]);
  await Promise.all([
    handlers.get("agent.create.after")({ agent: hookAgent(a) }, { paseo: d.paseo }),
    handlers.get("agent.turn.after")({ agent: hookAgent(a) }, { paseo: d.paseo }),
  ]);
  assert.equal(d.state.titles.length, 1);
  off();
  assert.equal(offs, 2);
});

const OTHER = "wks_0000000000000002";

test("an older agent in ANOTHER window does not stop naming, and setTitle hits the right window", async () => {
  const older = agentRec({ id: "older", workspaceId: OTHER, cwd: gitDir.repo, title: "Elsewhere", createdAt: "2026-11-13T09:00:00.000Z" });
  const mine = agentRec({ id: "mine", cwd: gitDir.repo, title: "Here", createdAt: T1 });
  const d = fakeDaemon({ agents: [older, mine], otherWindows: { [OTHER]: { id: OTHER, title: "kept", background: false } } });
  await handleAgentEvent(hookAgent(mine), { paseo: d.paseo }, baseDeps());
  assert.deepEqual(d.state.calls, [[WID, "MAIN my-repo (Here)"]]);
  assert.equal(d.state.windows[OTHER].title, "kept");
});

test("a window Paseo pre-titled with the agent's first prompt line is still default: named, not settled as titled", async () => {
  const a = agentRec({ cwd: gitDir.repo, title: "Fix the flaky login test" });
  const d = fakeDaemon({ windowTitle: "Fix the flaky login test", agents: [a] });
  await handleAgentEvent(hookAgent(a), { paseo: d.paseo }, baseDeps());
  assert.deepEqual(d.state.titles, ["MAIN my-repo (Fix the flaky login test)"]);
  const b = agentRec({ cwd: gitDir.repo, title: "Fix the flaky login test" });
  const e = fakeDaemon({ windowTitle: "a name somebody typed", agents: [b] });
  await handleAgentEvent(hookAgent(b), { paseo: e.paseo }, baseDeps());
  assert.deepEqual(e.state.titles, []);
});

test("a launch by bin/ade-worker-run (slice + ade.lead labels) is left to ade-worker-run", async () => {
  const a = agentRec({ cwd: gitDir.repo, labels: { "ade.lead": LEAD, slice: "auto-naming" } });
  const d = fakeDaemon({ agents: [a] });
  const rec = await handleAgentEvent(hookAgent(a), { paseo: d.paseo }, baseDeps());
  assert.equal(rec.outcome, "skip");
  assert.deepEqual(d.state.titles, []);
});

test("agents created at the same instant: exactly one is first (ties break by id)", () => {
  const a = { id: "a", createdAt: T0 };
  const b = { id: "b", createdAt: T0 };
  assert.equal(isFirstAgent(a, [{ agent: b }]), true);
  assert.equal(isFirstAgent(b, [{ agent: a }]), false);
});

test("events for one window never overlap, even when the decision is slow", async () => {
  const handlers = new Map();
  const server = { addHook: (name, fn) => (handlers.set(name, fn), () => {}) };
  const a = agentRec({ cwd: gitDir.repo, title: null });
  const d = fakeDaemon({ agents: [a] });
  let running = 0;
  let maxRunning = 0;
  const run = async (args) => {
    running += 1;
    maxRunning = Math.max(maxRunning, running);
    await new Promise((r) => setTimeout(r, 40));
    running -= 1;
    return runDecision(args);
  };
  a.title = "Slow one";
  registerAdeWindowNameHooks(server, baseDeps({ run }));
  await Promise.all([
    handlers.get("agent.create.after")({ agent: hookAgent(a) }, { paseo: d.paseo }),
    handlers.get("agent.turn.after")({ agent: hookAgent(a) }, { paseo: d.paseo }),
    handlers.get("agent.turn.after")({ agent: hookAgent(a) }, { paseo: d.paseo }),
  ]);
  assert.equal(maxRunning, 1);
  assert.equal(d.state.titles.length, 1);
});

test("a joiner's event does not settle a prompt-titled window before its first agent names it", async () => {
  const first = agentRec({ id: "first", cwd: gitDir.repo, title: "Fix the login test", createdAt: T0 });
  const joiner = agentRec({ id: "joiner", cwd: gitDir.repo, title: `worker s ${LEAD}`, createdAt: T1 });
  const d = fakeDaemon({ windowTitle: "Fix the login test", agents: [first, joiner] });
  const deps = baseDeps();
  const rec = await handleAgentEvent(hookAgent(joiner), { paseo: d.paseo }, deps);
  assert.equal(rec.reason, "not the window's first agent");
  assert.equal(deps.settled.size, 0);
  await handleAgentEvent(hookAgent(first), { paseo: d.paseo }, deps);
  assert.deepEqual(d.state.titles, ["MAIN my-repo (Fix the login test)"]);
});

test("a window already named in the scheme is never re-wrapped, even when the tab carries the same text", async () => {
  for (const t of ["MAIN my-repo (x)", "WORKERS my-repo (Wave 7)", "USER r (a (b))"]) {
    assert.equal(isDefaultTitle(t, t), false, t);
    const a = agentRec({ cwd: gitDir.repo, title: t });
    const d = fakeDaemon({ windowTitle: t, agents: [a] });
    await handleAgentEvent(hookAgent(a), { paseo: d.paseo }, baseDeps());
    assert.deepEqual(d.state.titles, [], t);
  }
  assert.equal(isDefaultTitle("Fix it", "Fix it"), true);
  assert.equal(isDefaultTitle("MAIN notes", "MAIN notes"), true); // not the scheme: no parenthesised work
});

test("a daemon call that never settles frees the window's slot and does not block another window", async () => {
  const handlers = new Map();
  const server = { addHook: (name, fn) => (handlers.set(name, fn), () => {}) };
  const a = agentRec({ cwd: gitDir.repo, title: "Stuck then fine" });
  const b = agentRec({ id: "agent-2", workspaceId: OTHER, cwd: gitDir.repo, title: "Other window" });
  const d = fakeDaemon({ agents: [a, b], otherWindows: { [OTHER]: { id: OTHER, title: null, background: false } } });
  let stuck = true;
  const realRef = d.paseo.workspaces.ref;
  d.paseo.workspaces.ref = (id) => {
    const h = realRef(id);
    return id === WID && stuck ? { ...h, refresh: () => new Promise(() => {}) } : h;
  };
  const logged = [];
  registerAdeWindowNameHooks(server, baseDeps({ timeoutMs: 1500, log: (l) => logged.push(l) }));
  const create = handlers.get("agent.create.after");
  const t0 = Date.now();
  await Promise.all([create({ agent: hookAgent(a) }, { paseo: d.paseo }), create({ agent: hookAgent(b) }, { paseo: d.paseo })]);
  assert.ok(Date.now() - t0 < 2000);
  assert.ok(logged.some((l) => l.includes("exceeded")), "the stuck handler is logged as an error");
  assert.deepEqual(d.state.calls, [[OTHER, "MAIN my-repo (Other window)"]]);
  stuck = false; // the daemon recovered: the same window is not parked
  await handlers.get("agent.turn.after")({ agent: hookAgent(a) }, { paseo: d.paseo });
  assert.deepEqual(d.state.calls.at(-1), [WID, "MAIN my-repo (Stuck then fine)"]);
});

test("while one event is in flight for a window, a second for the same window is dropped, not queued", async () => {
  const handlers = new Map();
  const server = { addHook: (name, fn) => (handlers.set(name, fn), () => {}) };
  // No agent title: the script answers retry, so nothing settles and a queued second event WOULD call run again.
  const a = agentRec({ cwd: gitDir.repo, title: null });
  const d = fakeDaemon({ agents: [a] });
  let runs = 0;
  let release;
  const gate = new Promise((r) => (release = r));
  const run = async (args) => {
    runs += 1;
    await gate;
    return runDecision(args);
  };
  registerAdeWindowNameHooks(server, baseDeps({ run }));
  const first = handlers.get("agent.create.after")({ agent: hookAgent(a) }, { paseo: d.paseo });
  await new Promise((r) => setTimeout(r, 30)); // the first run is parked inside `run`
  let secondDone = false;
  const second = handlers.get("agent.turn.after")({ agent: hookAgent(a) }, { paseo: d.paseo }).then(() => (secondDone = true));
  await new Promise((r) => setTimeout(r, 30));
  assert.equal(secondDone, true, "the second event returns at once, it does not wait behind the first");
  release();
  await Promise.all([first, second]);
  assert.equal(runs, 1);
  assert.deepEqual(d.state.titles, []);
  await handlers.get("agent.turn.after")({ agent: hookAgent(a) }, { paseo: d.paseo }); // slot freed: a later event runs again
  assert.equal(runs, 2);
});

test("a run past its budget is aborted: its python child gets the signal and nothing is written afterwards", async () => {
  const handlers = new Map();
  const server = { addHook: (name, fn) => (handlers.set(name, fn), () => {}) };
  const a = agentRec({ cwd: gitDir.repo, title: "Late" });
  const d = fakeDaemon({ agents: [a] });
  let seen;
  const run = (args) =>
    new Promise((resolve) => {
      seen = args.signal;
      setTimeout(() => resolve({ action: "rename", name: "MAIN my-repo (Late)", kind: "MAIN" }), 150); // answers after the budget
    });
  const logged = [];
  registerAdeWindowNameHooks(server, baseDeps({ run, timeoutMs: 40, log: (l) => logged.push(l) }));
  await handlers.get("agent.create.after")({ agent: hookAgent(a) }, { paseo: d.paseo });
  assert.equal(seen?.aborted, true, "the run's signal was aborted by the budget");
  await new Promise((r) => setTimeout(r, 250)); // the abandoned run finishes its decision
  assert.deepEqual(d.state.calls, [], "the abandoned run does not call setTitle");
  assert.ok(logged.some((l) => l.includes("exceeded")));
});

test("Paseo's hook cancel (context.signal) aborts the run the same way", async () => {
  const handlers = new Map();
  const server = { addHook: (name, fn) => (handlers.set(name, fn), () => {}) };
  const a = agentRec({ cwd: gitDir.repo, title: "Cancelled" });
  const d = fakeDaemon({ agents: [a] });
  const cancel = new AbortController();
  let seen;
  const run = (args) =>
    new Promise((resolve) => {
      seen = args.signal;
      setTimeout(() => resolve({ action: "rename", name: "MAIN my-repo (Cancelled)", kind: "MAIN" }), 100);
    });
  registerAdeWindowNameHooks(server, baseDeps({ run }));
  const p = handlers.get("agent.create.after")({ agent: hookAgent(a) }, { paseo: d.paseo, signal: cancel.signal });
  await new Promise((r) => setTimeout(r, 30));
  cancel.abort();
  await p;
  assert.equal(seen.aborted, true);
  assert.deepEqual(d.state.calls, []);
});

test("an abort that lands during the last re-read stops the write", async () => {
  const handlers = new Map();
  const server = { addHook: (name, fn) => (handlers.set(name, fn), () => {}) };
  const a = agentRec({ cwd: gitDir.repo, title: "Race" });
  const d = fakeDaemon({ agents: [a] });
  const cancel = new AbortController();
  const realRef = d.paseo.workspaces.ref;
  let refreshes = 0;
  d.paseo.workspaces.ref = (id) => {
    const h = realRef(id);
    return { ...h, refresh: async () => ((refreshes += 1) === 2 && cancel.abort(), h.refresh()) }; // 1: first look, 2: the re-read just before setTitle
  };
  registerAdeWindowNameHooks(server, baseDeps());
  await handlers.get("agent.create.after")({ agent: hookAgent(a) }, { paseo: d.paseo, signal: cancel.signal });
  assert.equal(refreshes, 2, "the window is read twice (first look, last look)");
  assert.deepEqual(d.state.calls, []);
});

test("runDecision passes the signal to execFile", async () => {
  let opts;
  const exec = (_cmd, _args, o, cb) => {
    opts = o;
    cb(null, '{"action":"skip"}', "");
    return { stdin: { on() {}, end() {} } };
  };
  const ac = new AbortController();
  await runDecision({ script: "/x.py", info: {}, exec, signal: ac.signal });
  assert.equal(opts.signal, ac.signal);
});

test("the default handler budget stays under Paseo's 30 s notification timeout", () => {
  assert.ok(HANDLER_BUDGET_MS < 30_000 && HANDLER_BUDGET_MS > 0);
});

test("equality-as-default holds only while the first agent is young; later only a null title is default", async () => {
  assert.equal(isDefaultTitle("Fix it", "Fix it", false), false);
  assert.equal(isDefaultTitle(null, "Fix it", false), true);
  assert.equal(isDefaultTitle("Fix it", "Fix it", true), true);
  const a = agentRec({ cwd: gitDir.repo, title: "Same text" });
  const old = fakeDaemon({ windowTitle: "Same text", agents: [a] });
  const rec = await handleAgentEvent(hookAgent(a), { paseo: old.paseo }, baseDeps({ now: () => Date.parse(T0) + 3_600_000 }));
  assert.equal(rec.outcome, "skip");
  assert.deepEqual(old.state.titles, [], "a window deliberately titled like its tab is left alone an hour later (backfill)");
  const young = fakeDaemon({ windowTitle: "Same text", agents: [a] });
  await handleAgentEvent(hookAgent(a), { paseo: young.paseo }, baseDeps({ now: () => Date.parse(T0) + 60_000 }));
  assert.deepEqual(young.state.titles, ["MAIN my-repo (Same text)"]);
  const nodate = agentRec({ cwd: gitDir.repo, title: "Same text", createdAt: undefined });
  const nd = fakeDaemon({ windowTitle: "Same text", agents: [nodate] });
  await handleAgentEvent(hookAgent(nodate), { paseo: nd.paseo }, baseDeps());
  assert.deepEqual(nd.state.titles, [], "no createdAt: not provably young, left alone");
  const nulltitle = fakeDaemon({ windowTitle: null, agents: [a] });
  await handleAgentEvent(hookAgent(a), { paseo: nulltitle.paseo }, baseDeps({ now: () => Date.parse(T0) + 3_600_000 }));
  assert.deepEqual(nulltitle.state.titles, ["MAIN my-repo (Same text)"], "a null title is named at any age");
});

test("an invalid name from the decision script is never written", async () => {
  assert.equal(validName("MAIN my-repo (Fix)"), true);
  for (const bad of [undefined, null, 42, "", "my own name", "MAIN my-repo (x)\nMAIN y (z)", "MAIN r (" + "x".repeat(100) + ")"]) {
    assert.equal(validName(bad), false, String(bad));
    const a = agentRec({ cwd: gitDir.repo });
    const d = fakeDaemon({ agents: [a] });
    const rec = await handleAgentEvent(hookAgent(a), { paseo: d.paseo }, baseDeps({ run: async () => ({ action: "rename", name: bad, kind: "MAIN" }) }));
    assert.equal(rec.outcome, "error", String(bad));
    assert.deepEqual(d.state.calls, [], String(bad));
  }
});
