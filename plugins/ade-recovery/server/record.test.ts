import { test } from "node:test";
import assert from "node:assert/strict";
import { generationHint, sealRecord, validateRecord } from "./record.ts";
import { canonicalJson } from "./canonical.ts";
import { MAX_RECORD_BYTES, PLUGIN_VERSION, SCHEMA, MAX_TURNS, MAX_INTERRUPTIONS, MAX_PATHS } from "./constants.ts";
import type { RecoveryRecord } from "./types.ts";

function base(): Omit<RecoveryRecord, "integrity"> {
  return {
    schema: SCHEMA,
    generation: 3,
    writtenAt: "2026-11-04T12:00:00.000Z",
    writer: {
      plugin: "ade-recovery",
      pluginVersion: "0.1.0",
      pid: 4242,
      start: "123456",
      daemon: { pid: 4000, start: "120000" },
      host: "h1",
      bootId: "boot-1",
    },
    serverId: "srv1",
    paseoAgentId: "agent-1",
    provider: "claude",
    cwd: "/work",
    host: "h1",
    bootId: "boot-1",
    platform: "linux",
    state: "idle",
    turns: [],
  };
}

test("constants", () => {
  assert.equal(SCHEMA, "ade.recovery.passive/v1");
  assert.equal(MAX_TURNS, 20);
  assert.equal(MAX_INTERRUPTIONS, 20);
  assert.equal(MAX_PATHS, 200);
  assert.equal(MAX_RECORD_BYTES, 262144);
  assert.match(PLUGIN_VERSION, /^\d+\.\d+\.\d+/);
});

test("seal then validate round-trips through JSON, in any key order", () => {
  const sealed = sealRecord(base());
  assert.equal(sealed.integrity.alg, "sha256");
  assert.match(sealed.integrity.digest, /^[0-9a-f]{64}$/);
  assert.deepEqual(validateRecord(sealed), { ok: true, record: sealed });
  const text = JSON.stringify(sealed, null, 2);
  const v = validateRecord(text);
  assert.ok(v.ok);
  assert.equal(validateRecord(Buffer.from(text)).ok, true);
  // reversed key order: canonical JSON makes it irrelevant
  const parsed = JSON.parse(text) as Record<string, unknown>;
  const reversed = Object.fromEntries(Object.entries(parsed).reverse());
  assert.equal(validateRecord(JSON.stringify(reversed)).ok, true);
  // sealing ignores any stale integrity on the input
  const resealed = sealRecord({ ...sealed, integrity: { alg: "sha256", digest: "0".repeat(64) } } as never);
  assert.equal(resealed.integrity.digest, sealed.integrity.digest);
});

test("unknown keys are tolerated but still covered by the digest", () => {
  const sealed = sealRecord({ ...base(), futureField: { a: 1 } } as never);
  assert.equal(validateRecord(sealed).ok, true);
  const tampered = { ...sealed, futureField: { a: 2 } };
  assert.deepEqual(validateRecord(tampered), { ok: false, problem: "bad-integrity" });
});

test("optional fields may be missing", () => {
  const r = base();
  delete r.state;
  delete r.turns;
  assert.equal(validateRecord(sealRecord(r)).ok, true);
});

test("not-json", () => {
  for (const x of ["", "{", "null", "[]", "42", "\"s\"", null, 7, [], "{\"a\":"]) {
    assert.deepEqual(validateRecord(x), { ok: false, problem: "not-json" }, JSON.stringify(x));
  }
});

test("unknown-schema is reported before integrity", () => {
  const r = sealRecord({ ...base(), schema: "ade.recovery.passive/v2" } as never);
  assert.deepEqual(validateRecord(r), { ok: false, problem: "unknown-schema" });
  const { schema: _s, ...noSchema } = sealRecord(base());
  assert.deepEqual(validateRecord(noSchema), { ok: false, problem: "unknown-schema" });
});

test("bad-integrity: tampered field, wrong alg, missing integrity", () => {
  const sealed = sealRecord(base());
  assert.deepEqual(validateRecord({ ...sealed, cwd: "/other" }), { ok: false, problem: "bad-integrity" });
  assert.deepEqual(validateRecord({ ...sealed, integrity: { alg: "md5", digest: sealed.integrity.digest } }), {
    ok: false,
    problem: "bad-integrity",
  });
  const { integrity: _i, ...bare } = sealed;
  assert.deepEqual(validateRecord(bare), { ok: false, problem: "bad-integrity" });
});

test("missing-identity:<field> for every required field", () => {
  const fields = ["generation", "writtenAt", "writer", "serverId", "paseoAgentId", "provider", "cwd", "host", "platform", "bootId"];
  for (const f of fields) {
    const r = base() as Record<string, unknown>;
    delete r[f];
    assert.deepEqual(validateRecord(sealRecord(r as never)), { ok: false, problem: `missing-identity:${f}` }, f);
  }
  const emptyCwd = sealRecord({ ...base(), cwd: "" });
  assert.deepEqual(validateRecord(emptyCwd), { ok: false, problem: "missing-identity:cwd" });
  const badGen = sealRecord({ ...base(), generation: 1.5 });
  assert.deepEqual(validateRecord(badGen), { ok: false, problem: "missing-identity:generation" });
  const badPid = sealRecord({ ...base(), writer: { ...base().writer, pid: 0 } });
  assert.deepEqual(validateRecord(badPid), { ok: false, problem: "missing-identity:writer.pid" });
  // bootId may be null, but must be present
  assert.equal(validateRecord(sealRecord({ ...base(), bootId: null })).ok, true);
});

test("too-large: raw text and parsed object", () => {
  const big = sealRecord({ ...base(), missingTelemetry: [{ field: "x", reason: "y".repeat(MAX_RECORD_BYTES), at: "t" }] });
  assert.deepEqual(validateRecord(big), { ok: false, problem: "too-large" });
  assert.deepEqual(validateRecord(JSON.stringify(big)), { ok: false, problem: "too-large" });
  assert.deepEqual(validateRecord("x".repeat(MAX_RECORD_BYTES + 1)), { ok: false, problem: "too-large" });
});

test("generationHint reads parsed and truncated files", () => {
  const text = canonicalJson(sealRecord(base()));
  assert.equal(generationHint(text), 3);
  assert.equal(generationHint(text.slice(0, text.indexOf("generation") + 20)), 3);
  assert.equal(generationHint("garbage"), 0);
  assert.equal(generationHint("{\"generation\":-4}"), 0);
});
