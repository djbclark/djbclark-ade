import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import plugin, { createGuard, loadPolicy, validHandoffPolicy } from "./index.js";

const storageKey = "go-context-v1:" +
  createHash("sha256").update(JSON.stringify(["/repo", undefined])).digest("hex").slice(0, 24);

// The suite must pass both on a bare machine and inside an acp-dispatched slice,
// where ACP_RUN_AGENT=1 is inherited. Isolate the env per test so the four
// positive wake tests are not silenced by the ambient dispatch marker.
let savedACP;
beforeEach(() => {
  savedACP = process.env.ACP_RUN_AGENT;
  delete process.env.ACP_RUN_AGENT;
});
afterEach(() => {
  if (savedACP === undefined) delete process.env.ACP_RUN_AGENT;
  else process.env.ACP_RUN_AGENT = savedACP;
});

async function fixture(policyOverride, seed = {}) {
  let tick = 1_000_000;
  const calls = [], saved = new Map(Object.entries(seed)), models = new Map(), prompts = [], parents = new Map();
  const ctx = {
    location: { directory: "/repo" },
    storage: { get: async (key) => saved.get(key), set: async (key, value) => saved.set(key, structuredClone(value)) },
    session: {
      get: async ({ sessionID }) => ({ data: { id: sessionID, model: models.get(sessionID), parentID: parents.get(sessionID) } }),
      compact: async ({ sessionID }) => { calls.push(sessionID); },
      prompt: async ({ sessionID, prompt, delivery }) => { prompts.push({ sessionID, text: prompt?.text, delivery }); },
    },
  };
  const policy = policyOverride ?? loadPolicy();
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
  const idle = async (sid = "ses_one") => {
    await guard.onEvent({ type: "session.idle", data: { sessionID: sid } });
  };
  return { ctx, guard, policy, calls, saved, models, prompts, parents, context, step, end, idle,
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
  await f.step(50000); await f.step(96000); await f.end(); await f.step(95000);
  f.advance(300000); await f.step(97000);
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

test("native V2 adapter registers real hooks and a session-scoped compact tool", async () => {
  const f = await fixture(); const hooks = [], tools = [];
  f.ctx.session.hook = async (name, callback) => { hooks.push([name, callback]); return { dispose() {} }; };
  f.ctx.tool = { hook: async (name, callback) => { hooks.push([name, callback]); return { dispose() {} }; },
    transform: async (callback) => { callback({ add: (tool) => tools.push(tool) }); return { dispose() {} }; } };
  f.ctx.event = { async *subscribe() {} };
  let rpc;
  f.ctx.rpc = { register: async (definition, handlers) => { rpc = { definition, handlers }; return { dispose() {} }; } };
  const cleanup = await plugin.setup(f.ctx);
  assert.deepEqual(hooks.map(([name]) => name), ["context"], "shell commands must never be rewritten before native permission matching");
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
  g.guard.streamStopped(); await g.step(100000);
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


// Native permission APIs expose requests, not effective rules. Never hook or rewrite shell input.
test("empty and pending permission lists cannot enable a shell rewrite", async () => {
  for (const requests of [[], [{ id: "per_pending", permission: "shell", patterns: ["git push*"] }]]) {
    const f = await fixture();
    let lookups = 0;
    f.ctx.permission = { list: async () => { lookups++; return requests; } };
    f.ctx.session.hook = async () => ({ dispose() {} });
    f.ctx.tool = { hook: () => assert.fail("no execute.before shell hook"), transform: async () => ({ dispose() {} }) };
    f.ctx.rpc = { register: async () => ({ dispose() {} }) };
    f.ctx.event = { async *subscribe() {} };
    const cleanup = await plugin.setup(f.ctx);
    assert.equal(typeof f.guard.onTool, "undefined");
    assert.equal(lookups, 0, "permission request APIs cannot authorize a shell rewrite");
    await cleanup();
  }
});

for (const change of ["context", "selection", "provider-roundtrip", "manual"]) {
  test(`model switch via ${change} preserves pending, cooldown and ineffective-compaction blocks`, async () => {
    const f = await fixture(); await f.context(); await f.step(150000);
    const model = { providerID: "opencode-go", id: "gpt-6-luna" };
    const switchModel = async () => {
      f.models.set("ses_one", model);
      if (change === "selection") {
        f.advance(1);
        await f.guard.onEvent({ type: "session.model.selected", created: f.time, data: { sessionID: "ses_one", model } });
      } else if (change === "provider-roundtrip") {
        await f.context("ses_one", "anthropic", "claude-sonnet");
        await f.context("ses_one", model.providerID, model.id);
      } else if (change === "manual") {
        assert.equal(await f.guard.manual("ses_one"), false);
      } else await f.context("ses_one", model.providerID, model.id);
    };
    await switchModel();
    assert.equal(f.guard.status("ses_one").pending, true);
    assert.equal(await f.guard.manual("ses_one"), false);
    await f.step(200000); assert.equal(f.calls.length, 1, "switch cannot duplicate an accepted request");
    await f.end();
    assert.equal(await f.guard.manual("ses_one"), false, "cooldown persists after completion");
    await f.step(195000); // A poor reduction must still be compared with the pre-switch input.
    assert.equal(f.guard.status("ses_one").blocked, true);
    f.advance(300000);
    await f.context("ses_one", "opencode-go", "deepseek-v4.1-flash");
    assert.equal(await f.guard.manual("ses_one"), false, "switch cannot clear an ineffective-compaction block");
    await f.step(220000); assert.equal(f.calls.length, 1);
    const reloaded = await createGuard(f.ctx, f.policy, () => f.time);
    assert.equal(await reloaded.manual("ses_one"), false, "protection persists after reload");
  });
}

test("session.idle at or above the handoff ceiling wakes the model once", async () => {
  const f = await fixture(); await f.context();
  await f.step(112000); // routine handoff ceiling
  await f.idle();
  assert.equal(f.prompts.length, 1);
  assert.equal(f.prompts[0].sessionID, "ses_one");
  assert.equal(f.prompts[0].delivery, "steer");
  assert.match(f.prompts[0].text, /Automatic handoff required/);
  assert.match(f.prompts[0].text, /handoff ceiling 112000/);
});

test("session.idle below the handoff ceiling and compaction budget is a no-op", async () => {
  const f = await fixture(); await f.context();
  await f.step(100000); // below the 112000 routine ceiling
  await f.idle();
  assert.equal(f.prompts.length, 0);
});

test("session.idle is ignored for a non-Go session", async () => {
  const f = await fixture(); await f.context("ses_one", "anthropic", "claude-sonnet");
  await f.idle();
  assert.equal(f.prompts.length, 0);
});

test("session.idle does not wake a session that switched away from Go", async () => {
  const f = await fixture(); await f.context();
  await f.step(112000); // crosses the routine handoff ceiling as a Go session
  await f.context("ses_one", "anthropic", "claude-sonnet"); // switch away
  await f.idle();
  assert.equal(f.prompts.length, 0, "a non-Go session must not be woken by a stale Go measurement");
});

test("two compactions exhaust the handoff budget and wake the model on idle", async () => {
  const f = await fixture(); await f.context();
  await f.end(); await f.end(); // two native compaction completions
  await f.idle();
  assert.equal(f.prompts.length, 1);
  assert.match(f.prompts[0].text, /2 compactions/);
});

test("the handoff wake respects its cooldown and escalates on retry", async () => {
  const f = await fixture(); await f.context();
  await f.step(112000);
  await f.idle();
  assert.equal(f.prompts.length, 1);
  assert.match(f.prompts[0].text, /At this task boundary/);
  await f.idle(); // within cooldown → no second wake
  assert.equal(f.prompts.length, 1);
  f.advance(3600000); // handoff_cooldown_seconds
  await f.idle(); // cooldown elapsed → escalate
  assert.equal(f.prompts.length, 2);
  assert.match(f.prompts[1].text, /Overdue \(fired 2 times\)/);
});

test("the context hook delivers the full directive once an idle has confirmed a primary", async () => {
  const f = await fixture(); await f.context();
  await f.step(112000);
  await f.idle(); // live get confirms a primary (no parentID) → state.child === false
  const event = await f.context();
  assert.equal(event.system.length, 1);
  assert.match(event.system[0].text, /Automatic handoff required/);
  assert.match(event.system[0].text, /handoff ceiling 112000/);
});

test("a primary crossing the ceiling before its first idle is softened, then re-surfaces the full directive after a dropped wake", async () => {
  const f = await fixture(); await f.context();
  await f.step(112000);
  // Request before the first idle: state.child is still null, so the notice is
  // neutral — it must not assert a child role or carry the lifecycle directive.
  const softened = await f.context();
  assert.equal(softened.system.length, 1);
  assert.doesNotMatch(softened.system[0].text, /start a fresh session/);
  assert.doesNotMatch(softened.system[0].text, /Automatic handoff required/);
  // The wake is dropped, but the idle still confirms a primary (child === false).
  f.ctx.session.prompt = async () => { throw new Error("wake dropped"); };
  await f.idle();
  assert.equal(f.prompts.length, 0, "the wake was dropped");
  // The next request re-surfaces the full directive: the dedup key now
  // distinguishes the softened wording from the full one.
  const full = await f.context();
  assert.equal(full.system.length, 1);
  assert.match(full.system[0].text, /Automatic handoff required/);
  assert.match(full.system[0].text, /handoff ceiling 112000/);
});

test("validHandoffPolicy accepts a valid policy and rejects each malformed field", () => {
  const base = loadPolicy();
  assert.equal(validHandoffPolicy(base), true);
  const bad = (patch) => ({ ...base, ...patch });
  assert.equal(validHandoffPolicy(bad({ handoff_cooldown_seconds: 299 })), false, "cooldown below the 300 s floor");
  assert.equal(validHandoffPolicy(bad({ handoff_cooldown_seconds: 0 })), false);
  assert.equal(validHandoffPolicy(bad({ handoff_cooldown_seconds: null })), false);
  assert.equal(validHandoffPolicy(bad({ handoff_after_compactions: 0 })), false);
  assert.equal(validHandoffPolicy(bad({ handoff_after_compactions: "2" })), false);
  assert.equal(validHandoffPolicy(bad({ handoff_max_wakes: 0 })), false);
  assert.equal(validHandoffPolicy(bad({ handoff_max_wakes: undefined })), false, "a missing cap fails closed");
  assert.equal(validHandoffPolicy(bad({ handoff_max_wakes: NaN })), false);
  assert.equal(validHandoffPolicy(bad({ routine_context: { ...base.routine_context, handoff: -1 } })), false);
  assert.equal(validHandoffPolicy(bad({ routine_context: { ...base.routine_context, handoff: "x" } })), false);
  assert.equal(validHandoffPolicy(bad({ routine_context: { ...base.routine_context, handoff: 0 } })), false, "a zero ceiling fails closed");
  assert.equal(validHandoffPolicy(bad({ advisory_context: { ...base.advisory_context, handoff: -1 } })), false);
  assert.equal(validHandoffPolicy(bad({ advisory_context: { ...base.advisory_context, handoff: 0 } })), false, "a zero ceiling fails closed");
});

test("a malformed handoff policy disables the automatic wake", async () => {
  const base = loadPolicy();
  const f = await fixture({ ...base, handoff_cooldown_seconds: 0 });
  await f.context();
  await f.step(112000);
  await f.idle();
  assert.equal(f.prompts.length, 0, "a bad cooldown must not open a self-sustaining wake loop");
});

test("the handoff wake is capped at handoff_max_wakes per session", async () => {
  const base = loadPolicy();
  const f = await fixture({ ...base, handoff_max_wakes: 1 });
  await f.context();
  await f.step(112000);
  await f.idle();
  assert.equal(f.prompts.length, 1);
  f.advance(3600000); // past handoff_cooldown_seconds
  await f.idle();
  assert.equal(f.prompts.length, 1, "the retry cap stops further paid wakes");
});

test("a child (subagent) session is never woken to hand off", async () => {
  const f = await fixture();
  f.parents.set("ses_one", "ses_parent");
  await f.context();
  await f.step(112000);
  await f.idle();
  assert.equal(f.prompts.length, 0, "a child session must not be steered to run /handoff or /new");
});

test("a child session's context notice never says to start a fresh session", async () => {
  const f = await fixture();
  f.parents.set("ses_one", "ses_parent");
  await f.context();
  await f.step(112000);
  await f.idle(); // wake refused, but caches state.child === true
  assert.equal(f.prompts.length, 0);
  const event = await f.context();
  assert.equal(event.system.length, 1);
  assert.doesNotMatch(event.system[0].text, /start a fresh session/);
  assert.doesNotMatch(event.system[0].text, /Automatic handoff required/);
  assert.match(event.system[0].text, /report back to your parent/);
});

test("a child session's context notice is softened even before its first idle", async () => {
  const f = await fixture();
  f.parents.set("ses_one", "ses_parent");
  await f.context();
  await f.step(112000);
  const event = await f.context(); // no idle: state.child is still null
  assert.equal(event.system.length, 1);
  assert.doesNotMatch(event.system[0].text, /start a fresh session/);
  assert.doesNotMatch(event.system[0].text, /Automatic handoff required/);
});

test("the wake refuses a session whose live model no longer matches", async () => {
  const f = await fixture(); await f.context();
  await f.step(112000);
  f.models.set("ses_one", { id: "gpt-6-luna", providerID: "opencode-go" }); // live model diverges from the recorded one
  await f.idle();
  assert.equal(f.prompts.length, 0, "a switched-away model must not be woken by a stale Go measurement");
});

test("a dispatched slice (ACP_RUN_AGENT=1) is never woken", async () => {
  const f = await fixture(); await f.context();
  await f.step(112000);
  process.env.ACP_RUN_AGENT = "1"; // afterEach restores the ambient value
  await f.idle();
  assert.equal(f.prompts.length, 0, "an ACP-launched slice must not be steered into a fresh paid turn");
});

test("a dispatched slice's context notice never says to start a fresh session", async () => {
  const f = await fixture(); await f.context();
  await f.step(112000);
  process.env.ACP_RUN_AGENT = "1"; // afterEach restores the ambient value
  const event = await f.context();
  assert.equal(event.system.length, 1);
  assert.doesNotMatch(event.system[0].text, /start a fresh session/);
  assert.doesNotMatch(event.system[0].text, /Automatic handoff required/);
  assert.match(event.system[0].text, /report back to your parent/);
});

test("a malformed persisted record (negative handoffTries) fails closed", async () => {
  const seed = { [storageKey]: { ses_one: { model: "deepseek-v4.1-flash", pending: false, sampleAt: 0, attemptAt: 0, handoffTries: -1 } } };
  const f = await fixture(null, seed);
  await f.context();
  await f.step(112000);
  await f.idle();
  assert.equal(f.prompts.length, 0, "untrusted prior state must not be re-admitted or acted on");
});

test("a far-future persisted handoffAt is clamped per record, not a whole-store rejection", async () => {
  const seed = { [storageKey]: { ses_one: { model: "deepseek-v4.1-flash", pending: false, sampleAt: 0, attemptAt: 0, handoffAt: 2_000_000, handoffTries: 0, compactions: 0, child: null, notice: "", active: true, blocked: false } } };
  const f = await fixture(null, seed);
  await f.context();
  await f.step(150000);
  assert.deepEqual(f.calls, ["ses_one"], "one stale timestamp must not disable automatic compaction for the location");
});

test("a far-future persisted handoffAt is clamped so the handoff wake can still fire after the cooldown", async () => {
  const seed = { [storageKey]: { ses_one: { model: "deepseek-v4.1-flash", pending: false, sampleAt: 0, attemptAt: 0, total: 150000, handoffAt: 2_000_000, handoffTries: 0, compactions: 0, child: null, notice: "", active: true, blocked: false } } };
  const f = await fixture(null, seed);
  await f.context(); // re-admits the record; the clamp sets handoffAt = now()
  await f.idle(); // within the clamped cooldown → no wake
  assert.equal(f.prompts.length, 0, "the clamp suppresses the wake for one cooldown");
  f.advance(f.policy.handoff_cooldown_seconds * 1000);
  await f.idle(); // cooldown elapsed → the wake fires (it would not without the clamp)
  assert.equal(f.prompts.length, 1);
  assert.match(f.prompts[0].text, /Automatic handoff required/);
});

test("concurrent idle events claim the wake once after the awaited read", async () => {
  const f = await fixture(); await f.context();
  await f.step(112000);
  const originalGet = f.ctx.session.get;
  f.ctx.session.get = async (arg) => { await new Promise((r) => setTimeout(r, 20)); return originalGet(arg); };
  await Promise.all([f.idle(), f.idle()]);
  assert.equal(f.prompts.length, 1, "the cap/cooldown re-check after the live read prevents a double wake");
});
