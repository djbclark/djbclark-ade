import assert from "node:assert/strict";
import { test } from "node:test";
import { join } from "node:path";
import { createSemanticClaimHandlers } from "./semantic-hooks.mjs";
import { fixture } from "./semantic-fixture.mjs";

function setup(t, extra = {}) {
  const f = fixture(t, "ade-claim"); const calls = [];
  let claims = [], fail = null;
  const runOperation = async (request) => {
    calls.push(request);
    if (fail) throw fail;
    if (request.operation === "repository-facts") return { version: 1, selection: request.selection, status: 0,
      stdout: request.selection === "head" ? "a".repeat(40) : request.selection === "git-dir" ? join(f.cwd, ".git") : "https://example.invalid/ours" };
    if (request.operation === "claim-list") return { version: 1, status: 0, output: claims };
    return { version: 1, status: 0, output: { claimId: request.claimId } };
  };
  const deps = { ...f, env: { PATH: "/usr/bin" }, log() {}, runOperation, ...extra };
  return { ...f, calls, deps, get handlers() { return createSemanticClaimHandlers(deps); },
    set claims(value) { claims = value; }, set fail(value) { fail = value; } };
}
const active = (cwd, agent = "") => ({ id: "claim-a", path: cwd, state: "active", shown_state: "active",
  owner: { agent, record: null, session: null, model: "" } });

test("claim creation awaits actual result then install, no owner-session inference", async (t) => {
  const f = setup(t); let release; const waiting = new Promise((resolve) => { release = resolve; });
  const run = f.deps.runOperation;
  f.deps.runOperation = async (request) => { const result = await run(request); if (request.operation === "claim-new") await waiting; return result; };
  let done = false;
  const result = f.handlers["worktree.create.after"]({ worktree: { path: f.cwd, branch: "feature", sourceCheckout: f.cwd } }).then(() => { done = true; });
  for (let i = 0; i < 8; i++) await Promise.resolve();
  assert.equal(done, false); assert.equal(f.calls.some((r) => r.operation === "claim-install-hooks"), false);
  release(); await result;
  assert.deepEqual(f.calls.map((r) => r.operation), ["repository-facts", "repository-facts", "claim-new", "claim-install-hooks"]);
  const created = f.calls[2]; assert.equal(created.ownerAgent, ""); assert.equal(created.ownerRecord, null);
  assert.equal(created.ttlHours, 72); assert.match(created.claimId, /^wt-/);
});
test("mode reread preserves observe and enforce without replay", async (t) => {
  const f = setup(t); const handlers = f.handlers;
  f.mode("observe"); await handlers["worktree.create.after"]({ worktree: { path: f.cwd, branch: "feature", sourceCheckout: f.cwd } });
  assert.equal(f.calls.length, 2);
  f.mode("enforce"); await handlers["worktree.create.after"]({ worktree: { path: f.cwd, branch: "feature", sourceCheckout: f.cwd } });
  assert.equal(f.calls.filter((r) => r.operation === "claim-new").length, 1);
});
test("bind, env injection and release keep actual path and agent association", async (t) => {
  const f = setup(t); f.claims = [active(f.cwd)]; const h = f.handlers;
  await h["agent.create.after"]({ agent: { id: "agent-a", cwd: f.cwd } });
  assert.deepEqual(f.calls.at(-1), { version: 1, operation: "claim-bind-owner", cwd: f.cwd, claimId: "claim-a", agentId: "agent-a" });
  const request = { agentId: "agent-a", cwd: f.cwd, env: { PATH: "/bin", KEEP: "yes" } };
  const changed = await h["agent.open.before"]({ request });
  assert.equal(changed.env.ADE_CLAIM_ID, "claim-a"); assert.equal(changed.env.KEEP, "yes");
  assert.equal(changed.env.PATH, join(f.root, "libexec/agent-bin") + ":/bin");
  await h["workspace.archive.after"]({ workspace: { id: "window-a", cwd: f.cwd } });
  assert.equal(f.calls.at(-1).operation, "claim-release");
});
test("foreign owner never binds or exports claim identity", async (t) => {
  const f = setup(t); f.claims = [active(f.cwd, "other")]; const h = f.handlers;
  await h["agent.create.after"]({ agent: { id: "agent-a", cwd: f.cwd } });
  assert.equal(f.calls.some((r) => r.operation === "claim-bind-owner"), false);
  const changed = await h["agent.open.before"]({ request: { agentId: "agent-a", cwd: f.cwd, env: { ADE_CLAIM_ID: "stale" } } });
  assert.equal(Object.hasOwn(changed.env, "ADE_CLAIM_ID"), false);
});
test("SDK unknown on lookup propagates without env patch, mutation or retry", async (t) => {
  const f = setup(t); f.fail = new Error("private proof unavailable");
  await assert.rejects(f.handlers["agent.open.before"]({ request: { agentId: "agent-a", cwd: f.cwd, env: {} } }), /private proof/);
  assert.equal(f.calls.length, 1);
});
test("post-publication install unknown does not replay new or compensate", async (t) => {
  const f = setup(t); const run = f.deps.runOperation;
  f.deps.runOperation = async (r) => { if (r.operation === "claim-install-hooks") { f.calls.push(r); throw new Error("unknown IO"); } return run(r); };
  await assert.rejects(f.handlers["worktree.create.after"]({ worktree: { path: f.cwd, branch: "feature", sourceCheckout: f.cwd } }), /unknown IO/);
  assert.equal(f.calls.filter((r) => r.operation === "claim-new").length, 1);
  assert.equal(f.calls.some((r) => r.operation === "claim-release"), false);
});
