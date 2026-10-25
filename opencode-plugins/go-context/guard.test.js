import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import plugin, { createGuard, loadPolicy } from "./index.js";

async function fixture() {
  let tick = 1_000_000;
  const calls = [], saved = new Map(), models = new Map();
  const ctx = {
    location: { directory: "/repo" },
    permission: { list: async () => [] },
    storage: { get: async (key) => saved.get(key), set: async (key, value) => saved.set(key, structuredClone(value)) },
    session: {
      get: async ({ sessionID }) => ({ data: { id: sessionID, model: models.get(sessionID) } }),
      compact: async ({ sessionID }) => { calls.push(sessionID); },
    },
  };
  const policy = loadPolicy();
  const guard = await createGuard(ctx, policy, () => tick);
  const context = async (sid = "ses_one", providerID = "opencode-go", id = "deepseek-v4.1-flash") => {
    const event = { sessionID: sid, model: { id, providerID }, system: [], tools: { ade_compact: {} } };
    models.set(sid, event.model);
    await guard.onContext(event);
    return event;
  };
  const step = async (total, extra = {}, sid = "ses_one") => {
    tick += 1000;
    await guard.onEvent({ type: "session.step.ended", created: tick,
      data: { sessionID: sid, tokens: { input: 1000, output: 9000000, reasoning: 8000000,
        cache: { read: total - 1000, write: 0 } } }, ...extra });
  };
  const end = async (sid = "ses_one") => {
    tick += 1000;
    await guard.onEvent({ type: "session.compaction.ended", created: tick, data: { sessionID: sid } });
  };
  return { ctx, guard, policy, calls, saved, models, context, step, end,
    get time() { return tick; }, advance: (ms) => { tick += ms; } };
}

test("fresh per-request cached input triggers compaction; lifetime/output usage does not", async () => {
  const f = await fixture();
  await f.context();
  await f.guard.onEvent({ type: "session.usage.updated", created: f.time, data: {
    sessionID: "ses_one", tokens: { input: 999999999, cache: { read: 999999999, write: 0 } },
  } });
  assert.equal(f.calls.length, 0);
  await f.step(50000);
  await f.step(64000);
  assert.equal(f.calls.length, 0);
  assert.match((await f.context()).system[0].text, /including cache/);
  assert.equal((await f.context()).system.length, 0);
  await f.step(96000);
  assert.deepEqual(f.calls, ["ses_one"]);
  await f.step(150000);
  assert.equal(f.calls.length, 1, "acceptance must not reset pending state");
});

test("a successful completion resets the floor and cooldown, not an acceptance", async () => {
  const f = await fixture(); await f.context();
  await f.step(50000); await f.step(96000); await f.end();
  await f.step(50000);
  await f.step(96000);
  assert.equal(f.calls.length, 1, "five-minute cooldown still applies");
  f.advance(300000);
  await f.step(97000);
  assert.equal(f.calls.length, 2);
});

test("an irreducible instruction baseline compacts once and cannot loop", async () => {
  const f = await fixture(); await f.context();
  await f.step(150000); await f.end(); await f.step(145000);
  f.advance(300000); await f.step(180000);
  assert.equal(f.calls.length, 1);
  assert.match((await f.context()).system[0].text, /ineffective or unconfirmed/);
});

test("expensive models use the tighter profile while economical Luna remains routine", async () => {
  const f = await fixture(); await f.context("ses_one", "opencode-go", "kimi-k3");
  await f.step(32000); await f.step(64000);
  assert.equal(f.calls.length, 1);
  await f.context("ses_two", "opencode-go", "gpt-6-luna");
  await f.step(32000, {}, "ses_two"); await f.step(64000, {}, "ses_two");
  assert.equal(f.calls.length, 1);
});

test("stale, duplicate and out-of-order samples cannot trigger writes", async () => {
  const f = await fixture(); await f.context(); await f.step(50000);
  const last = f.time;
  await f.step(150000, { created: last });
  await f.step(150000, { created: last - 200000 });
  await f.step(150000, { created: last - 1 });
  assert.equal(f.calls.length, 0);
});

test("non-Go and a provider switch are never compacted by an old Go sample", async () => {
  const f = await fixture(); await f.context("ses_one", "anthropic", "claude-sonnet");
  await f.step(200000); assert.equal(f.calls.length, 0);
  await f.context(); await f.step(50000);
  f.models.set("ses_one", { id: "deepseek-v4.1-flash", providerID: "opencode" });
  await f.step(150000); assert.equal(f.calls.length, 0);
});

test("pending state survives a plugin reload and sessions remain independent", async () => {
  const f = await fixture(); await f.context(); await f.step(150000);
  const reloaded = await createGuard(f.ctx, f.policy, () => f.time);
  await reloaded.onContext({ sessionID: "ses_one", model: f.models.get("ses_one"), system: [], tools: {} });
  f.advance(1000);
  await reloaded.onEvent({ type: "session.step.ended", created: f.time, data: { sessionID: "ses_one",
    tokens: { input: 1000, cache: { read: 200000, write: 0 } } } });
  assert.equal(f.calls.length, 1);
  await f.context("ses_two"); await f.step(150000, {}, "ses_two");
  assert.deepEqual(f.calls, ["ses_one", "ses_two"]);
});

test("uncertain requests and unusable storage never cause blind retries", async () => {
  const f = await fixture(); await f.context();
  f.ctx.session.compact = async () => { f.calls.push("timeout"); throw new Error("timeout"); };
  await f.step(150000); f.advance(600000); await f.step(200000);
  assert.deepEqual(f.calls, ["timeout"]);
  const g = await fixture(); await g.context();
  g.ctx.storage.set = async () => { throw new Error("unavailable"); };
  await g.step(150000); assert.equal(g.calls.length, 0);
});

test("tool environment scope is per native tool call and never global or inferred", async () => {
  const f = await fixture(); await f.context(); await f.context("ses_two");
  const before = process.env.ADE_OPENCODE_SESSION_ID;
  const one = { tool: "bash", sessionID: "ses_one", input: { command: "pwd" } };
  const two = { tool: "shell", sessionID: "ses_two", input: { command: "pwd" } };
  await f.guard.onTool(one); await f.guard.onTool(two);
  assert.match(one.input.command, /'ses_one'/); assert.match(two.input.command, /'ses_two'/);
  const js = { tool: "execute", sessionID: "ses_one", input: { code: "return 1" } };
  await f.guard.onTool(js); assert.equal(js.input.code, "return 1");
  assert.equal(process.env.ADE_OPENCODE_SESSION_ID, before);
});

test("native V2 adapter registers real hooks and a session-scoped compact tool", async () => {
  const f = await fixture(); const hooks = [], tools = [];
  f.ctx.session.hook = async (name, callback) => { hooks.push([name, callback]); return { dispose() {} }; };
  f.ctx.tool = { hook: async (name, callback) => { hooks.push([name, callback]); return { dispose() {} }; },
    transform: async (callback) => { callback({ add: (tool) => tools.push(tool) }); return { dispose() {} }; } };
  f.ctx.event = { async *subscribe() {} };
  let rpc;
  f.ctx.rpc = { register: async (definition, handlers) => { rpc = { definition, handlers }; return { dispose() {} }; } };
  const cleanup = await plugin.setup(f.ctx);
  assert.deepEqual(hooks.map(([name]) => name), ["context", "execute.before"]);
  assert.equal(tools[0].name, "ade_compact");
  f.models.set("ses_one", { id: "deepseek-v4.1-flash", providerID: "opencode-go" });
  assert.match((await tools[0].execute({}, { sessionID: "ses_one" })).content, /accepted/);
  assert.deepEqual(await rpc.handlers.compact({ sessionID: "ses_one" }), { accepted: false }, "RPC and tool share pending admission");
  assert.equal(f.calls.length, 1);
  const status = await rpc.handlers.status({ sessionID: "ses_one" });
  assert.equal(status.known, true);
  assert.equal(status.pending, true);
  assert.equal(f.calls.length, 1, "status must never request compaction");
  await cleanup();
});


test("unreadable prior state and stopped event streams fail closed", async () => {
  const f = await fixture();
  f.ctx.storage.get = async () => { throw new Error("unreadable"); };
  const guard = await createGuard(f.ctx, f.policy, () => f.time);
  assert.equal(await guard.manual("ses_one"), false);
  await f.context();
  await guard.onContext({ sessionID: "ses_one", model: f.models.get("ses_one"), system: [], tools: {} });
  assert.equal(await guard.manual("ses_one"), false);
  assert.equal(f.calls.length, 0);
  const g = await fixture(); await g.context(); await g.step(50000);
  g.guard.streamStopped(); await g.step(150000);
  assert.equal(g.calls.length, 0);
  assert.match((await g.context()).system[0].text, /unconfirmed/);
});


test("a failed lookup never becomes an uncertain write or permanent pending state", async () => {
  const f = await fixture(); await f.context();
  const original = f.ctx.session.get;
  f.ctx.session.get = async () => { throw new Error("temporary read failure"); };
  await f.step(150000);
  assert.equal(await f.guard.manual("ses_one"), false);
  assert.equal(f.calls.length, 0);
  f.ctx.session.get = original;
  f.advance(300000); await f.step(160000);
  assert.equal(f.calls.length, 1);
});

test("manual calls share automatic cooldown and ineffective-baseline protection", async () => {
  const f = await fixture(); await f.context(); await f.step(150000); await f.end();
  assert.equal(await f.guard.manual("ses_one"), false);
  await f.step(145000); f.advance(300000);
  assert.equal(await f.guard.manual("ses_one"), false);
  assert.equal(f.calls.length, 1);
});


test("native directory scope is literal shell data, including quotes and substitutions", async () => {
  const f = await fixture(); await f.context();
  f.ctx.location.directory = "/repo's dir $(false)\nline";
  const event = { tool: "shell", sessionID: "ses_one", input: { command: "printf '%s' \"$ADE_OPENCODE_DIRECTORY\"" } };
  await f.guard.onTool(event);
  const result = spawnSync("/bin/sh", ["-c", event.input.command], { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, f.ctx.location.directory);
});

// A prefix before native permission matching must not evade the original resource.
for (const rules of [
  [{ action: "shell", resource: "git push*", effect: "deny" }],
  { rules: [{ action: "shell", resource: "git push*", effect: "ask" }] },
  [{ action: "*", resource: "*", effect: "deny" }],
  [{ action: "read", resource: "*", effect: "ask" }],
  null, {}, [null], [{}], [{ effect: "unknown" }], { rules: [], error: "unavailable" },
]) {
  test(`native restricted or unreadable rules preserve shell permission resource: ${JSON.stringify(rules)}`, async () => {
    const f = await fixture(); await f.context();
    f.ctx.permission.list = async () => rules;
    const command = "git push origin master";
    const event = { tool: "shell", sessionID: "ses_one", input: { command } };
    await f.guard.onTool(event);
    assert.equal(event.input.command, command);
    assert.ok(event.input.command.startsWith("git push"), "native git push* rules still match");
    assert.equal(await f.guard.manual("ses_one"), true, "native compaction remains available");
  });
}

test("shell scope fails closed on permission API errors or absence and refreshes rules per call", async () => {
  const f = await fixture(); await f.context();
  const event = () => ({ tool: "shell", sessionID: "ses_one", input: { command: "git push origin master" } });
  const first = event();
  f.ctx.permission.list = async () => ({ rules: [{ effect: "allow", action: "shell", resource: "*" }] });
  await f.guard.onTool(first); assert.match(first.input.command, /^export ADE_OPENCODE_DIRECTORY=/);
  f.ctx.permission.list = async () => [{ effect: "deny", action: "shell", resource: "git push*" }];
  const second = event(); await f.guard.onTool(second); assert.equal(second.input.command, "git push origin master");
  f.ctx.permission.list = async () => { throw new Error("unavailable"); };
  const third = event(); await f.guard.onTool(third); assert.equal(third.input.command, "git push origin master");
  delete f.ctx.permission;
  const fourth = event(); await f.guard.onTool(fourth); assert.equal(fourth.input.command, "git push origin master");
});
