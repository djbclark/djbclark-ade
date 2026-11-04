import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { judge } from "./verdict.ts";
import { validateRecord } from "./record.ts";
import type { LiveEvidence, LoadResult } from "./types.ts";

const DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "fixtures", "verdicts");

interface Fixture {
  name: string;
  note?: string;
  load: LoadResult;
  live: LiveEvidence | null;
  expect: { verdict: string; reasons: string[]; info?: string[] };
}

const files = fs.readdirSync(DIR).filter((f) => f.endsWith(".json")).sort();

function deepFreeze<T>(v: T): T {
  if (v && typeof v === "object") {
    for (const x of Object.values(v as object)) deepFreeze(x);
    Object.freeze(v);
  }
  return v;
}

test("fixture set is present and names are unique", () => {
  assert.ok(files.length >= 30, `found ${files.length}`);
  const names = files.map((f) => (JSON.parse(fs.readFileSync(path.join(DIR, f), "utf8")) as Fixture).name);
  assert.equal(new Set(names).size, names.length);
  const verdicts = new Set(files.map((f) => (JSON.parse(fs.readFileSync(path.join(DIR, f), "utf8")) as Fixture).expect.verdict));
  assert.deepEqual([...verdicts].sort(), ["do-not-resume", "needs-review", "resumable-native"]);
});

for (const f of files) {
  const fx = JSON.parse(fs.readFileSync(path.join(DIR, f), "utf8")) as Fixture;
  test(`verdict fixture ${f}`, () => {
    const res = judge(deepFreeze(fx.load), deepFreeze(fx.live)); // frozen: judge must not mutate
    assert.equal(res.verdict, fx.expect.verdict, `${fx.name}: reasons ${JSON.stringify(res.reasons)}`);
    assert.deepEqual([...res.reasons].sort(), [...fx.expect.reasons].sort(), fx.name);
    assert.equal(new Set(res.reasons).size, res.reasons.length, "no duplicate reasons");
    for (const i of fx.expect.info ?? []) assert.ok(res.info.includes(i), `${fx.name}: info ${i} missing from ${JSON.stringify(res.info)}`);
    if (res.verdict === "resumable-native") assert.deepEqual(res.reasons, []);
    // Fixture records with complete identity are sealed and valid, so the CLI test can write them as-is.
    if (fx.load.record && !fx.expect.reasons.some((r) => r.startsWith("missing-identity:"))) {
      assert.ok(validateRecord(fx.load.record).ok, `${fx.name}: record must be sealed and valid`);
    }
  });
}

test("an interrupted turn is never resumable-native, whatever else holds", () => {
  for (const f of files) {
    const fx = JSON.parse(fs.readFileSync(path.join(DIR, f), "utf8")) as Fixture;
    const r = fx.load.record;
    if (!r || !r.turns || r.turns.length === 0) continue;
    const last = r.turns[r.turns.length - 1];
    const load = {
      ...fx.load,
      record: {
        ...r,
        interruptions: [...(r.interruptions ?? []), { detectedAt: last.startedAt, evidence: "daemon-restart" as const, turnKey: last.turnKey, detail: "" }],
      },
    };
    const res = judge(load, fx.live);
    assert.notEqual(res.verdict, "resumable-native", fx.name);
    if (res.verdict === "needs-review") assert.ok(res.reasons.includes("tools-unobserved"), fx.name);
  }
});

test("unknown load problems fail closed; detail problems are info", () => {
  const base = JSON.parse(fs.readFileSync(path.join(DIR, files.find((f) => f.includes("clean-completed-turn"))!), "utf8")) as Fixture;
  const r1 = judge({ ...base.load, problems: ["something-new"] }, base.live);
  assert.equal(r1.verdict, "needs-review");
  assert.deepEqual(r1.reasons, ["something-new"]);
  const r2 = judge({ ...base.load, problems: ["prev:not-json"] }, base.live);
  assert.equal(r2.verdict, "resumable-native");
  assert.ok(r2.info.includes("load:prev:not-json"));
  const r3 = judge({ ...base.load, source: "prev", problems: [] }, base.live);
  assert.deepEqual(r3.reasons, ["corrupt-fell-back-to-prev"], "a prev source blocks even without the problem code");
});
