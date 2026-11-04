import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { agentFileName, ensureRoot, safeComponent, stateBase, stateRoot } from "./state-root.ts";

test("stateRoot: ADE_STATE_ROOT > XDG_STATE_HOME > ~/.local/state", () => {
  const tail = path.join("ade", "srv_1", "ade-recovery", "recovery", "v1");
  assert.equal(stateRoot("srv_1", { ADE_STATE_ROOT: "/r", XDG_STATE_HOME: "/x", HOME: "/h" }), path.join("/r", tail));
  assert.equal(stateRoot("srv_1", { XDG_STATE_HOME: "/x", HOME: "/h" }), path.join("/x", tail));
  assert.equal(stateRoot("srv_1", { HOME: "/h" }), path.join("/h", ".local", "state", tail));
  assert.equal(stateRoot("srv_1", { XDG_STATE_HOME: "relative/x", HOME: "/h" }), path.join("/h", ".local", "state", tail), "relative XDG ignored");
  assert.equal(stateBase({ ADE_STATE_ROOT: "rel" }), path.resolve("rel"));
});

test("safeComponent accepts only [A-Za-z0-9_-]{1,128}", () => {
  for (const ok of ["a", "A-b_9", "x".repeat(128), "550e8400-e29b-41d4-a716-446655440000"]) assert.equal(safeComponent(ok), ok);
  for (const bad of ["", ".", "..", "a/b", "a.b", "x".repeat(129), "a b", "é", "a\0b"]) {
    assert.throws(() => safeComponent(bad), /unsafe path component/, JSON.stringify(bad));
    assert.throws(() => stateRoot(bad, { HOME: "/h" }), /unsafe path component/);
  }
});

test("agentFileName: safe ids as is, others h-<sha256>", () => {
  assert.equal(agentFileName("agent-1"), "agent-1");
  const h = agentFileName("a/b");
  assert.match(h, /^h-[0-9a-f]{64}$/);
  assert.equal(agentFileName(h), h, "a hashed key maps to itself");
  assert.notEqual(agentFileName("a/b"), agentFileName("a/c"));
});

test("ensureRoot creates every missing level with 0700 and is idempotent", () => {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), "ade-recovery-sr-"));
  const dir = stateRoot("srv", { ADE_STATE_ROOT: base });
  const old = process.umask(0o000);
  try {
    assert.equal(ensureRoot(dir), dir);
  } finally {
    process.umask(old);
  }
  for (let d = dir; d !== base; d = path.dirname(d)) assert.equal(fs.statSync(d).mode & 0o777, 0o700, d);
  assert.equal(ensureRoot(dir), dir);
});
