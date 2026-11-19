import assert from "node:assert/strict";
import { test } from "node:test";
import { createSemanticWindowHandlers } from "./semantic-hooks.mjs";
import { fixture } from "./semantic-fixture.mjs";
import { createWindowHandlers } from "./window-workflow.mjs";
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
test("selected successful helper after cancellation rejects locally without title or replay", async (t) => {
  const controller = new AbortController();
  const f = setup(t, () => { controller.abort(); return rename; }); f.context.signal = controller.signal;
  await assert.rejects(f.handlers["agent.create.after"]({ agent: f.agent }, f.context), /aborted/);
  assert.equal(f.calls.length, 1);
  assert.deepEqual(f.titles, []);
});

test("abort then real SDK rejection preserves SAME original error, one call and no title", async (t) => {
  const controller = new AbortController();
  let entered, reject;
  const inside = new Promise((resolve) => { entered = resolve; });
  const pending = new Promise((_, no) => { reject = no; });
  const original = new Error("distinct SDK proof rejection");
  const f = setup(t, () => { entered(); return pending; }); f.context.signal = controller.signal;
  const running = f.handlers["agent.create.after"]({ agent: f.agent }, f.context);
  // Attach rejection observer before advancing the controlled failure phase.
  const escaped = assert.rejects(running, (error) => error === original);
  await inside;
  assert.equal(f.calls.length, 1);
  controller.abort(); reject(original);
  await escaped;
  assert.equal(f.calls.length, 1);
  assert.deepEqual(f.titles, []);
});

test("ordinary abort still normalizes raced decision rejection to fulfilled skip", async (t) => {
  const controller = new AbortController();
  let entered, reject, calls = 0;
  const inside = new Promise((resolve) => { entered = resolve; });
  const pending = new Promise((_, no) => { reject = no; });
  const f = setup(t, () => assert.fail("selected operation must not run"));
  f.context.signal = controller.signal;
  const handlers = createWindowHandlers({ env: {}, log() {}, decide: () => { calls++; entered(); return pending; } });
  const running = handlers["agent.create.after"]({ agent: f.agent }, f.context);
  await inside; controller.abort(); reject(new Error("ordinary decision cancelled"));
  assert.equal(await running, undefined);
  assert.equal(calls, 1); assert.equal(f.calls.length, 0);
  assert.deepEqual(f.titles, []);
});
