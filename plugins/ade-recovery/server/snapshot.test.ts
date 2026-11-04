import { test } from "node:test";
import assert from "node:assert/strict";
import { normalizeSnapshot } from "./snapshot.ts";

test("real SDK shape {agent, project} with activeTurn.turnId", () => {
  const s = normalizeSnapshot({
    agent: { id: "a1", status: "running", activeTurn: { turnId: "t9", startedAt: "x" }, archivedAt: null,
      persistence: { provider: "claude", sessionId: "s1", nativeHandle: { k: 1 } } },
    project: null,
  });
  assert.deepEqual(s, { id: "a1", status: "running", activeTurnId: "t9", archivedAt: null,
    persistence: { provider: "claude", sessionId: "s1", nativeHandle: { k: 1 } } });
});

test("flat snapshot is accepted", () => {
  assert.deepEqual(normalizeSnapshot({ id: "a2", status: "idle", activeTurnId: null }),
    { id: "a2", status: "idle", activeTurnId: null });
});

test("null, non-objects and id-less results give null", () => {
  assert.equal(normalizeSnapshot(null), null);
  assert.equal(normalizeSnapshot("x"), null);
  assert.equal(normalizeSnapshot({ agent: { status: "idle" } }), null);
});

test("idle agent with no active turn", () => {
  assert.equal(normalizeSnapshot({ agent: { id: "a3", status: "idle", activeTurn: null } })!.activeTurnId, null);
});
