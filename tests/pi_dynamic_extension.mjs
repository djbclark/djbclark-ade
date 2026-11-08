import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { PassThrough, Writable } from "node:stream";
import { createDynamicDefaults, runHelper } from "../pi-extensions/dynamic-defaults/index.mjs";

const STATE = "pi.virtual-model-state";
const first = { provider: "cursor", id: "composer-2.5", api: "test" };
const second = { provider: "zai", id: "glm-5", api: "test" };
const auto = { provider: "ade", id: "auto", api: "pi-virtual" };
const answer = (model = first, service = model.provider, kind = "code") => ({
  schema_version: 1, kind, service, provider: model.provider, model: model.id,
  model_id: `${model.provider}/${model.id}`, thinking: "high", reason: "test", quota_age_seconds: 0,
});

// Fake only the process boundary: production argv, stdin, stream limits and exit handling run unchanged.
function fakeProcess(responses) {
  const calls = [];
  const spawnImpl = (command, args, options) => {
    const child = new EventEmitter();
    child.stdout = new PassThrough();
    child.stderr = new PassThrough();
    let input = "";
    let closed = false;
    const close = (code) => { if (!closed) { closed = true; child.emit("close", code); } };
    child.kill = (signal) => { calls.at(-1).killed = signal; queueMicrotask(() => close(null)); return true; };
    child.stdin = new Writable({
      write(chunk, _encoding, callback) { input += chunk.toString(); callback(); },
      final(callback) {
        calls.at(-1).input = input;
        const response = responses.shift();
        queueMicrotask(() => {
          if (!response) { child.stderr.write("unexpected helper call"); close(2); return; }
          if (response.hang) return;
          child.stdout.write(response.raw ?? JSON.stringify(response.json ?? {}));
          if (response.stderr) child.stderr.write(response.stderr);
          close(response.code ?? 0);
        });
        callback();
      },
    });
    calls.push({ command, args, options, input });
    return child;
  };
  return { calls, spawnImpl };
}

function harness(responses = [], entries = [], routingOptions = {}) {
  const process = fakeProcess(responses);
  const commands = new Map();
  const notices = [];
  let descriptor;
  let nextEpoch = 0;
  const ctx = {
    model: auto, idle: true, pending: false,
    isIdle() { return this.idle; }, hasPendingMessages() { return this.pending; },
    sessionManager: { getBranch: () => entries },
    modelRegistry: {
      models: [first, second, auto],
      getAvailable() { return this.models; },
      find(provider, id) { return this.models.find((m) => m.provider === provider && m.id === id); },
    },
    ui: { notify: (message) => notices.push(message) },
  };
  const pi = {
    registerVirtualModel: (value) => { descriptor = value; },
    registerCommand: (name, value) => commands.set(name, value),
    appendEntry: (customType, data) => entries.push({ type: "custom", customType, data }),
  };
  const install = () => createDynamicDefaults({ stateEntryType: STATE, helperCommand: ["fake-helper"],
    spawnImpl: process.spawnImpl, epoch: () => `task-${++nextEpoch}`,
    isServiceBlocked: async () => false, ...routingOptions })(pi);
  install();
  const currentState = () => entries.findLast((e) => e.customType === STATE)?.data.state;
  const route = async (overrides = {}) => {
    const request = { reason: "user", state: currentState(), messages: [], thinkingLevel: "high", ...overrides };
    const result = await descriptor.route(request, ctx);
    if (result.state !== undefined && result.state !== request.state) pi.appendEntry(STATE, { provider: "ade", modelId: "auto", state: result.state });
    return result;
  };
  return { ctx, calls: process.calls, entries, notices, descriptor: () => descriptor, install, route,
    task: (args = "") => commands.get("ade-task").handler(args, ctx), currentState };
}

test("registers the native descriptor with zero startup helper calls", () => {
  const h = harness();
  assert.equal(h.descriptor().provider, "ade");
  assert.equal(h.descriptor().id, "auto");
  assert.equal(h.descriptor().name, "ADE Auto");
  assert.equal(h.calls.length, 0);
});

test("a confirmed failure is latched even when a new task epoch is pending", async () => {
  const h = harness([{ json: answer() }, { json: { blocked: true } }, { json: answer(second) }]);
  await h.route();
  await h.task("code");
  const result = await h.route({ failed: { model: first, message: { errorMessage: "insufficient_quota" } } });
  assert.equal(result.model, second);
  assert.deepEqual(h.calls[1].args, ["--block-service", "cursor", "--reason", "quota"]);
});

test("another session's confirmed pool failure invalidates the latched choice", async () => {
  let blocked = false;
  const h = harness([{ json: answer() }, { json: answer(second) }], [], {
    isServiceBlocked: async (service) => blocked && service === "cursor",
  });
  await h.route();
  blocked = true;
  const result = await h.route({ reason: "continuation" });
  assert.equal(result.model, second);
  assert.ok(h.calls[1].args.includes("--exclude-service"));
});

test("production latch reader validates helper output before replacing a choice", async () => {
  const h = harness([{ json: answer() },
    { json: { schema_version: 1, service: "cursor", blocked: true } }, { json: answer(second) }], [],
    { isServiceBlocked: undefined });
  await h.route();
  assert.equal((await h.route({ reason: "continuation" })).model, second);
  assert.deepEqual(h.calls[1].args, ["--check-service", "cursor"]);
  assert.equal(h.calls[1].input, "");
});

test("malformed latch response fails closed instead of spending another pool", async () => {
  const h = harness([{ json: answer() }, { json: { schema_version: 1, service: "cursor", blocked: "false" } }], [],
    { isServiceBlocked: undefined });
  await h.route();
  await assert.rejects(h.route(), /ADE Auto could not select/);
  assert.equal(h.calls.length, 2);
});

test("physical choice and effort persist across user followups, steer, continuation and retries", async () => {
  const h = harness([{ json: answer() }]);
  const initial = await h.route();
  for (const overrides of [{ reason: "user" }, { reason: "user", messages: [{ role: "user", content: "steer" }] },
    { reason: "continuation" }, { reason: "retry" }]) {
    const next = await h.route(overrides);
    assert.equal(next.model, first);
    assert.equal(next.thinkingLevel, "high");
    assert.equal(next.state, initial.state);
  }
  assert.equal(h.calls.length, 1);
  assert.deepEqual(JSON.parse(h.calls[0].input), ["cursor/composer-2.5", "zai/glm-5"]);
  assert.equal(h.calls[0].options.shell, undefined);
});

test("restored branch state survives extension reload/resume and fork", async () => {
  const h = harness([{ json: answer() }]);
  const initial = await h.route();
  h.install();
  assert.equal((await h.route()).state, initial.state);
  const fork = harness([], [...h.entries]);
  assert.equal((await fork.route()).model, first);
  assert.equal(fork.calls.length, 0);
});

test("explicit task epoch switches once without changing ordinary task text", async () => {
  const h = harness([{ json: answer() }, { json: answer(second, "zai", "review") }]);
  await h.route();
  await h.task("review --native-tools");
  assert.equal(h.calls.length, 1);
  const messages = [{ role: "user", content: "the unchanged task" }];
  const result = await h.route({ messages });
  assert.equal(result.model, second);
  assert.equal(result.state.kind, "review");
  assert.equal(result.state.epoch, "task-1");
  assert.ok(h.calls[1].args.includes("--native-tools"));
  assert.deepEqual(messages, [{ role: "user", content: "the unchanged task" }]);
  await h.route();
  assert.equal(h.calls.length, 2);
});

test("physical manual pin refuses task reset and does no helper work", async () => {
  const h = harness();
  h.ctx.model = first;
  await h.task("code");
  assert.equal(h.entries.length, 0);
  assert.equal(h.ctx.model, first);
  assert.equal(h.calls.length, 0);
  assert.match(h.notices[0], /Select ade\/auto/);
});

test("busy, compacting or queued sessions refuse explicit task boundary", async () => {
  const h = harness();
  h.ctx.idle = false;
  await h.task();
  h.ctx.idle = true; h.ctx.pending = true;
  await h.task();
  assert.equal(h.entries.length, 0);
  assert.equal(h.calls.length, 0);
});

test("invalid command arguments do not create a boundary", async () => {
  const h = harness();
  for (const args of ["--unknown", "code review", "code --native-tools --native-tools"]) await h.task(args);
  assert.equal(h.entries.length, 0);
});

test("direct summary reads stored physical choice without consuming pending epoch", async () => {
  const h = harness([{ json: answer() }, { json: answer(second, "zai", "review") }]);
  const initial = await h.route();
  await h.task("review");
  const before = h.entries.length;
  const summary = await h.route({ reason: "direct", state: undefined });
  assert.equal(summary.model, first);
  assert.equal(summary.state, undefined);
  assert.equal(h.entries.length, before);
  assert.equal(h.currentState(), initial.state);
  assert.equal(h.calls.length, 1);
  assert.equal((await h.route()).model, second);
});

test("direct summary with no choice resolves conservative default without persisting or consuming boundary", async () => {
  const h = harness([{ json: answer() }, { json: answer(second, "zai", "review") }]);
  await h.task("review --native-tools");
  const summary = await h.route({ reason: "direct", state: undefined });
  assert.equal(summary.state, undefined);
  assert.equal(h.currentState(), undefined);
  assert.ok(h.calls[0].args.includes("code"));
  assert.ok(!h.calls[0].args.includes("--native-tools"));
  assert.equal((await h.route()).state.kind, "review");
});

test("no eligible result fails closed without exposing helper diagnostics", async () => {
  const h = harness([{ code: 1, json: { reason: "secret diagnostic" }, stderr: "credential-like-data" }]);
  await assert.rejects(h.route(), (error) => error.message === "ADE Auto could not select an available model.");
  assert.equal(h.currentState(), undefined);
  assert.equal(h.calls.length, 1);
});

test("confirmed matched quota failure blocks service before excluding it and selecting replacement", async () => {
  const h = harness([{ json: answer() }, { json: { blocked: true } }, { json: answer(second) }]);
  await h.route();
  const result = await h.route({ reason: "retry", failed: { model: first, message: { errorMessage: "quota exceeded" } } });
  assert.equal(result.model, second);
  assert.deepEqual(h.calls[1].args, ["--block-service", "cursor", "--reason", "quota"]);
  assert.equal(h.calls[1].input, "");
  assert.deepEqual(h.calls[2].args.slice(-2), ["--exclude-service", "cursor"]);
  await h.route();
  assert.equal(h.calls.length, 3);
});

test("confirmed billing failure uses fixed billing reason without forwarding runtime text", async () => {
  const h = harness([{ json: answer() }, { json: {} }, { json: answer(second) }]);
  await h.route();
  await h.route({ reason: "retry", failed: { model: first, message: { errorMessage: "Insufficient credits: sensitive account detail" } } });
  assert.deepEqual(h.calls[1].args, ["--block-service", "cursor", "--reason", "billing"]);
});

test("failed block write fails closed and never spends another pool", async () => {
  const h = harness([{ json: answer() }, { code: 2 }]);
  await h.route();
  await assert.rejects(h.route({ reason: "retry", failed: { model: first, message: { errorMessage: "quota exhausted" } } }));
  assert.equal(h.calls.length, 2);
});

test("unknown errors, unmatched failures, and quota words in user/tool text do not fail over", async () => {
  const h = harness([{ json: answer() }]);
  const initial = await h.route();
  const failures = [
    { model: first, message: { errorMessage: "429 too many requests" } },
    { model: first, message: { errorMessage: "temporary transport error" } },
    { model: second, message: { errorMessage: "quota exceeded" } },
  ];
  for (const failed of failures) {
    const result = await h.route({ reason: "retry", failed,
      messages: [{ role: "user", content: "quota exceeded" }, { role: "toolResult", content: "insufficient credits" }] });
    assert.equal(result.state, initial.state);
    assert.equal(result.model, first);
  }
  assert.equal(h.calls.length, 1);
});

test("unavailable latched model permits reselection excluding its service", async () => {
  const h = harness([{ json: answer() }, { json: answer(second) }]);
  await h.route(); h.ctx.modelRegistry.models = [second, auto];
  assert.equal((await h.route()).model, second);
  assert.deepEqual(h.calls[1].args.slice(-2), ["--exclude-service", "cursor"]);
});

test("malformed or unavailable helper choices never reach dispatch", async () => {
  for (const result of [{ ...answer(), model_id: "wrong/model" }, { ...answer(), model: "missing", model_id: "cursor/missing" }, { ...answer(), thinking: "extreme" }]) {
    const h = harness([{ json: result }]);
    await assert.rejects(h.route());
    assert.equal(h.currentState(), undefined);
  }
});

test("aborted subprocess and excessive output fail closed with bounded child cleanup", async () => {
  const process = fakeProcess([{ hang: true }]);
  const controller = new AbortController();
  const pending = runHelper(["fake"], [], [], { signal: controller.signal, spawnImpl: process.spawnImpl });
  controller.abort();
  await assert.rejects(pending);
  assert.equal(process.calls[0].killed, "SIGTERM");
  const large = fakeProcess([{ raw: "x".repeat(20_000) }]);
  await assert.rejects(runHelper(["fake"], [], [], { spawnImpl: large.spawnImpl }));
  assert.equal(large.calls[0].killed, "SIGTERM");
});
