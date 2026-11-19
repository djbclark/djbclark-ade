import assert from "node:assert/strict";
import { test } from "node:test";
import { createSemanticWindowHandlers } from "./semantic-hooks.mjs";
import { fixture } from "./semantic-fixture.mjs";
function setup(t, decision, env = {}) {
  const f = fixture(t, "ade-window-name"); const calls = [], titles = [];
  const agent = { id: "agent-a", cwd: f.cwd, workspaceId: "window-a", title: "Work", labels: {}, createdAt: new Date().toISOString() };
  let title = null;
  const context = { paseo: {
    workspaces: { ref: () => ({ refresh: async () => ({ title }), setTitle: async (value) => { titles.push(value); title = value; } }) },
    agents: { ref: () => ({ refresh: async () => ({ agent }) }), list: async () => ({ entries: [{ agent }] }) },
  } };
  const handlers = createSemanticWindowHandlers({ ...f, env, log() {}, runOperation: async (request) => {
    calls.push(request); return { version: 1, status: 0, output: await decision(request) };
  } });
  return { calls, titles, agent, context, handlers, name(value) { title = value; } };
}
const rename = { action: "rename", name: "LEAD repo (Work)", kind: "LEAD" };
test("actual metadata read produces finite request and awaited title write", async (t) => {
  let release; const pending = new Promise((resolve) => { release = resolve; });
  const f = setup(t, () => pending);
  let done = false;
  const work = f.handlers["agent.create.after"]({ agent: f.agent }, f.context).then(() => { done = true; });
  for (let i = 0; i < 12; i++) await Promise.resolve();
  assert.equal(done, false); assert.deepEqual(f.titles, []);
  release(rename); await work;
  assert.deepEqual(f.titles, [rename.name]);
  assert.deepEqual(Object.keys(f.calls[0]).sort(), ["agent", "background", "cwd", "firstAgent", "operation", "version", "windowTitle"]);
  await f.handlers["agent.turn.after"]({ agent: f.agent }, f.context);
  assert.equal(f.calls.length, 1);
});
test("retry decision permits later real turn without registration helper", async (t) => {
  let count = 0; const f = setup(t, () => ++count === 1 ? { action: "skip", retry: true, reason: "no title" } : rename);
  assert.equal(f.calls.length, 0);
  await f.handlers["agent.create.after"]({ agent: f.agent }, f.context);
  await f.handlers["agent.turn.after"]({ agent: f.agent }, f.context);
  assert.equal(f.calls.length, 2); assert.deepEqual(f.titles, [rename.name]);
});
test("unknown proof throws, no title write or automatic retry", async (t) => {
  const f = setup(t, () => { throw new Error("proof unavailable"); });
  await assert.rejects(f.handlers["agent.create.after"]({ agent: f.agent }, f.context), /proof unavailable/);
  assert.equal(f.calls.length, 1); assert.deepEqual(f.titles, []);
});
test("concurrent explicit naming wins after helper wait", async (t) => {
  const f = setup(t, () => { f.name("Human title"); return rename; });
  await f.handlers["agent.create.after"]({ agent: f.agent }, f.context);
  assert.deepEqual(f.titles, []);
});
test("dry run still measures decision but never changes native title", async (t) => {
  const f = setup(t, () => rename, { ADE_WINDOW_NAME_DRY_RUN: "true" });
  await f.handlers["agent.create.after"]({ agent: f.agent }, f.context);
  assert.equal(f.calls.length, 1); assert.deepEqual(f.titles, []);
});
test("cancelled event cannot write after settled helper", async (t) => {
  const controller = new AbortController();
  const f = setup(t, () => { controller.abort(); return rename; }); f.context.signal = controller.signal;
  await f.handlers["agent.create.after"]({ agent: f.agent }, f.context);
  assert.deepEqual(f.titles, []);
});
