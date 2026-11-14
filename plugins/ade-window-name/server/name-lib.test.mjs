import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import {
  handleAgentEvent,
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

/** One fake daemon: a window record, its agents, and a record of every setTitle. */
function fakeDaemon({ windowTitle = null, windowBackground = false, agents }) {
  const state = { ws: { id: "wks_0000000000000001", title: windowTitle, background: windowBackground }, agents, titles: [] };
  const paseo = {
    workspaces: {
      ref: () => ({
        refresh: async () => ({ ...state.ws }),
        setTitle: async (t) => {
          state.titles.push(t);
          state.ws.title = t;
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
  const rec = await handleAgentEvent(hookAgent(second), { paseo: d.paseo }, baseDeps());
  assert.equal(rec.outcome, "skip");
  assert.deepEqual(d.state.titles, []);
  await handleAgentEvent(hookAgent(first), { paseo: d.paseo }, baseDeps());
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
    d.state.ws.title = "named by ade-worker-run meanwhile";
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
