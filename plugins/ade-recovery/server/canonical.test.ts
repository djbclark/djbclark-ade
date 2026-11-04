import { test } from "node:test";
import assert from "node:assert/strict";
import { canonicalJson, sha256Hex } from "./canonical.ts";

test("sorted keys, no whitespace, nested", () => {
  assert.equal(canonicalJson({ b: 1, a: { d: [3, { z: 1, y: 2 }], c: "x" } }), '{"a":{"c":"x","d":[3,{"y":2,"z":1}]},"b":1}');
  assert.equal(canonicalJson([]), "[]");
  assert.equal(canonicalJson({}), "{}");
  assert.equal(canonicalJson("é\n\"q\""), JSON.stringify("é\n\"q\""));
});

test("matches a JSON round trip (undefined, NaN, -0, toJSON)", () => {
  const v = { u: undefined, n: NaN, i: Infinity, z: -0, arr: [undefined, () => 1], d: new Date(0), s: Symbol("x") };
  assert.equal(canonicalJson(v), canonicalJson(JSON.parse(JSON.stringify(v))));
  assert.equal(canonicalJson(v), '{"arr":[null,null],"d":"1970-01-01T00:00:00.000Z","i":null,"n":null,"z":0}');
});

test("rejects what JSON cannot express", () => {
  assert.throws(() => canonicalJson(undefined), TypeError);
  assert.throws(() => canonicalJson(10n), TypeError);
  const cyc: Record<string, unknown> = {};
  cyc.self = cyc;
  assert.throws(() => canonicalJson(cyc), /cyclic/);
  const shared = { a: 1 };
  assert.equal(canonicalJson({ x: shared, y: shared }), '{"x":{"a":1},"y":{"a":1}}', "shared refs are not cycles");
});

test("sha256Hex of string and Buffer", () => {
  const e3b = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
  assert.equal(sha256Hex(""), e3b);
  assert.equal(sha256Hex(Buffer.alloc(0)), e3b);
  assert.equal(sha256Hex("abc"), sha256Hex(Buffer.from("abc")));
});
