import assert from "node:assert/strict";
import { test } from "node:test";
import {
  applyYoloToCreateRequest,
  planYoloPatch,
  providerId,
  shouldSkip,
} from "./yolo-lib.mjs";

test("providerId strips model suffix", () => {
  assert.equal(providerId("claude/sonnet"), "claude");
  assert.equal(providerId("codex"), "codex");
});

test("shouldSkip reads ade-yolo.skip metadata", () => {
  assert.equal(shouldSkip({ "ade-yolo.skip": true }), true);
  assert.equal(shouldSkip({ "ade-yolo.skip": "yes" }), true);
  assert.equal(shouldSkip({}), false);
});

test("planYoloPatch forces bypass on Always Ask / auto / missing", () => {
  assert.deepEqual(planYoloPatch({ provider: "claude", modeId: "default" }), {
    modeId: "bypassPermissions",
  });
  assert.deepEqual(planYoloPatch({ provider: "claude", modeId: "auto" }), {
    modeId: "bypassPermissions",
  });
  assert.deepEqual(planYoloPatch({ provider: "claude" }), {
    modeId: "bypassPermissions",
  });
  assert.deepEqual(planYoloPatch({ provider: "codex", modeId: "auto-review" }), {
    modeId: "full-access",
  });
});

test("planYoloPatch keeps plan / read-only and skip metadata", () => {
  assert.equal(planYoloPatch({ provider: "claude", modeId: "plan" }), null);
  assert.equal(planYoloPatch({ provider: "claude", modeId: "read-only" }), null);
  assert.equal(
    planYoloPatch({ provider: "claude", modeId: "default" }, { "ade-yolo.skip": true }),
    null,
  );
});

test("planYoloPatch sets OpenCode build + auto_accept", () => {
  assert.deepEqual(planYoloPatch({ provider: "opencode" }), {
    modeId: "build",
    featureValues: { auto_accept: true },
  });
  assert.deepEqual(
    planYoloPatch({ provider: "opencode", modeId: "build", featureValues: {} }),
    { modeId: "build", featureValues: { auto_accept: true } },
  );
});

test("planYoloPatch leaves unknown providers alone", () => {
  assert.equal(planYoloPatch({ provider: "cursor", modeId: "default" }), null);
  assert.equal(planYoloPatch({ provider: "pi" }), null);
});

test("applyYoloToCreateRequest rewrites config.modeId", () => {
  const out = applyYoloToCreateRequest({
    config: { provider: "claude/sonnet", modeId: "default", title: "t" },
    metadata: {},
  });
  assert.equal(out.config.modeId, "bypassPermissions");
  assert.equal(out.config.title, "t");
  assert.equal(out.config.provider, "claude/sonnet");
  assert.equal(applyYoloToCreateRequest({ config: { provider: "claude", modeId: "plan" } }), undefined);
});
