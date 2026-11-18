import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { JetStreamApiError, JetStreamApiCodes } from "@nats-io/jetstream";
import { Objm } from "@nats-io/obj";
import { streamConfig } from "../index.js";
import { Broker, stopChild } from "./fault-fixture.js";
const cli = fileURLToPath(new URL("../cli.js", import.meta.url));
async function provision(t, b, { confirm = "ADE_COORD_V1", token = b.token } = {}) {
  const child = spawn(process.execPath, [cli, "broker", "provision", "--state-dir", join(b.dir, "cli-state")], {
    env: { ...process.env, ADE_NATS_URL: b.url, ADE_NATS_TOKEN: token ?? "" },
  });
  t.after(() => stopChild(child));
  let out = "", err = "";
  child.stdout.on("data", d => out += d); child.stderr.on("data", d => err += d);
  const result = new Promise((resolve, reject) => { child.on("error", reject); child.on("exit", code => resolve({ code, out, err })); });
  child.stdin.end(JSON.stringify({ generation: "gen1", confirm }));
  const r = await result; assert.equal(r.out.trim().split("\n").length, 1); return { ...r, json: JSON.parse(r.out) };
}
const streams = async b => (await b.manager.streams.list().next()).map(s => s.config.name).sort();

test("actual authenticated empty-broker CLI provision recognizes typed absence and repeats without mutation", { timeout: 20000 }, async t => {
  const b = await Broker.create(t, { provision: false, token: "synthetic-test-token" });
  assert.deepEqual(await streams(b), []);
  await assert.rejects(b.manager.streams.info("ADE_COORD_V1"), error => error instanceof JetStreamApiError && error.code === JetStreamApiCodes.StreamNotFound);
  const denied = await provision(t, b, { token: "wrong-synthetic-token" }); assert.equal(denied.json.ok, false); assert.deepEqual(await streams(b), []);
  const unconfirmed = await provision(t, b, { confirm: "wrong" }); assert.equal(unconfirmed.json.error.code, "INVALID"); assert.deepEqual(await streams(b), []);
  const first = await provision(t, b); assert.equal(first.code, 0, first.out + first.err); assert.equal(first.json.result.object_store, "ADE_ARTIFACTS_V1");
  assert.deepEqual(await streams(b), ["ADE_COORD_V1", "OBJ_ADE_ARTIFACTS_V1"]);
  const before = await Promise.all(["ADE_COORD_V1", "OBJ_ADE_ARTIFACTS_V1"].map(n => b.manager.streams.info(n)));
  const second = await provision(t, b); assert.equal(second.code, 0, second.out + second.err);
  const after = await Promise.all(["ADE_COORD_V1", "OBJ_ADE_ARTIFACTS_V1"].map(n => b.manager.streams.info(n)));
  for (let i = 0; i < before.length; i++) {
    assert.deepEqual(after[i].config, before[i].config); assert.equal(after[i].created, before[i].created); assert.equal(after[i].state.messages, 0);
  }
});

test("provision refuses existing unsafe coordination stream before creating artifact bucket", { timeout: 20000 }, async t => {
  const b = await Broker.create(t, { provision: false });
  await b.manager.streams.add({ ...streamConfig(), discard: "old" });
  const before = await b.manager.streams.info("ADE_COORD_V1");
  const result = await provision(t, b); assert.equal(result.code, 1); assert.equal(result.json.error.code, "UNSUPPORTED");
  assert.deepEqual(await streams(b), ["ADE_COORD_V1"]); assert.deepEqual((await b.manager.streams.info("ADE_COORD_V1")).config, before.config);
});

test("provision refuses unsafe existing artifact storage/retention without changing its configuration", { timeout: 20000 }, async t => {
  for (const options of [{ storage: "memory", ttl: 0 }, { storage: "file", ttl: 60000000000 }]) {
    const b = await Broker.create(t, { provision: false }); await b.manager.streams.add(streamConfig());
    await new Objm(b.nc).create("ADE_ARTIFACTS_V1", options);
    const before = await b.manager.streams.info("OBJ_ADE_ARTIFACTS_V1");
    const result = await provision(t, b); assert.equal(result.code, 1); assert.equal(result.json.error.code, "UNSUPPORTED");
    assert.deepEqual((await b.manager.streams.info("OBJ_ADE_ARTIFACTS_V1")).config, before.config);
  }
});
