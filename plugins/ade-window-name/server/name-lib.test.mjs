import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import {
  handleAgentEvent,
  isDefaultTitle,
  isDryRun,
  isFirstAgent,
  registerAdeWindowNameHooks,
  resolveDecisionScript,
  resolvePluginRoot,
  runDecision,
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
