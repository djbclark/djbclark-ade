import assert from "node:assert/strict";
import { test } from "node:test";
import { registerLazyHooks } from "./lazy-hooks.mjs";

function server(managedSource) {
  const hooks = new Map();
  let removed = 0;
  return { hooks, get removed() { return removed; }, managedSource, sourceDirectory: "/snapshot/plugin",
    addHook(name, fn) { hooks.set(name, fn); return () => { hooks.delete(name); removed++; }; } };
}
for (const flag of [undefined, false, true]) test(`synchronous registration and awaited ${flag} route`, async () => {
  const s = server(flag);
  let ordinary = 0, selected = 0, release;
  const pending = new Promise((resolve) => { release = resolve; });
  const callbacks = { event: async (input, context) => { await pending; return { input, context }; } };
  const stop = registerLazyHooks(s, ["event"], {
    ordinary: async () => { ordinary++; return callbacks; },
    selected: async () => { selected++; return callbacks; },
  });
  assert.equal(typeof stop, "function");
  assert.equal(ordinary + selected, 0);
  let completed = false;
  const input = {}, context = {};
  const result = s.hooks.get("event")(input, context).then((value) => { completed = true; return value; });
  await Promise.resolve(); await Promise.resolve();
  assert.equal(completed, false);
  release();
  assert.deepEqual(await result, { input, context });
  assert.equal(ordinary, flag === true ? 0 : 1);
  assert.equal(selected, flag === true ? 1 : 0);
  stop(); stop();
  assert.equal(s.removed, 1);
});
test("selected error is sticky with no ordinary fallback or rerun", async () => {
  const s = server(true); let attempts = 0;
  registerLazyHooks(s, ["event"], { ordinary: () => assert.fail("raw fallback"), selected: async () => {
    attempts++; throw new Error("proof refused");
  } });
  const invoke = s.hooks.get("event");
  await assert.rejects(invoke({}, {}), /proof refused/);
  await assert.rejects(invoke({}, {}), /proof refused/);
  assert.equal(attempts, 1);
});
test("cleanup during module wait prevents callback effects", async () => {
  const s = server(true); let finish, effects = 0;
  const pending = new Promise((resolve) => { finish = resolve; });
  const stop = registerLazyHooks(s, ["event"], { selected: () => pending });
  const invoke = s.hooks.get("event"); const running = invoke({}, {});
  await Promise.resolve(); stop();
  finish({ event: () => { effects++; } });
  await running; await invoke({}, {});
  assert.equal(effects, 0);
});
for (const value of [null, "true", 1, {}]) test(`malformed route refuses ${JSON.stringify(value)}`, () => {
  const s = server(value);
  assert.throws(() => registerLazyHooks(s, ["event"], {}), /classification/);
  assert.equal(s.hooks.size, 0);
});
test("missing selected source refuses before registration", () => {
  const s = server(true); delete s.sourceDirectory;
  assert.throws(() => registerLazyHooks(s, ["event"], {}), /directory/);
  assert.equal(s.hooks.size, 0);
});
test("partial registration failure disposes already registered hook", () => {
  const s = server(false); const original = s.addHook;
  s.addHook = (name, fn) => { if (name === "second") throw new Error("registration refused"); return original(name, fn); };
  assert.throws(() => registerLazyHooks(s, ["event", "second"], {}), /registration refused/);
  assert.equal(s.removed, 1); assert.equal(s.hooks.size, 0);
});
