import { checkpoint, handoff, quiescenceFor } from "./lifecycle.js";
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { connect } from "@nats-io/transport-node";
import { headers } from "@nats-io/nats-core";
import { jetstreamManager } from "@nats-io/jetstream";
import { Coordination, safeToken, digest, subject, streamConfig } from "../index.js";
let server, dir, nc, c, manager;
const owner = agent => ({ host: "host1", server: "paseo1", agent });
const evidence = s => ({ prior_revision: s.revision, prior_epoch: s.record.ownership_epoch, prior_owner: s.record.owner, processes_stopped: true, jobs_stopped: true, operations_reconciled: true, checkpoint_digest: "a".repeat(64) });
const role = id => c.createRole({ role_id: id, owner: owner("old"), ownership_epoch: 1, generation: "gen1", state: "active", bindings: [] });
const transfer = s => handoff(c, s, owner("new"));
const report = (r, m) => c.publishReport({ role_id: r, message_id: m, payload: { text: "retained" } });
const receipt = (s, m) => c.commitReceipt(s, { message_id: m, stage: "processed", disposition: "done" });
before(async () => {
  assert.equal(process.platform, "linux", "Integration server runs only in Linux CI");
  dir = await mkdtemp(join(tmpdir(), "ade-coord-"));
  const config = join(dir, "nats.conf");
  await writeFile(config, `host: 127.0.0.1\nport: -1\njetstream { store_dir: "${dir}/store", sync_interval: always }\n`);
  server = spawn(process.env.NATS_SERVER ?? "nats-server", ["-c", config]);
  const url = await new Promise((resolve, reject) => {
    let log = "";
    const timer = setTimeout(() => reject(new Error("server startup timed out: " + log)), 10000);
    server.on("error", e => { clearTimeout(timer); reject(e); });
    server.on("exit", code => { clearTimeout(timer); reject(new Error(`server exited ${code}: ${log}`)); });
    server.stderr.on("data", data => { log += data; const match = log.match(/Listening for client connections on (127\.0\.0\.1:\d+)/); if (match) { clearTimeout(timer); resolve("nats://" + match[1]); } });
  });
  nc = await connect({ servers: url }); manager = await jetstreamManager(nc);
  await manager.streams.add({ ...streamConfig(), duplicate_window: 100000000 });
  c = await Coordination.connect(nc, { generation: "gen1" });
  console.log("server version", nc.info.version, "PID", server.pid);
  await c.doctor();
});
after(async () => { await nc?.close(); if (server && server.exitCode === null) { const exited = new Promise(resolve => server.once("exit", resolve)); server.kill("SIGTERM"); await exited; } if (dir) await rm(dir, { recursive: true, force: true }); });
test("safe identifiers and canonical digests", () => {
  for (const value of ["a.b", "*", ">", "", "a b", null]) assert.throws(() => safeToken(value), { code: "INVALID" });
  assert.equal(digest({ b: 1, a: 2 }), digest({ a: 2, b: 1 }));
  assert.throws(() => digest({ a: undefined }), { code: "INVALID" });
  assert.throws(() => digest(Array(2)), { code: "INVALID" });
});
test("concurrent role CAS has exactly one winner", async () => {
  const s = await role("cas"); const results = await Promise.allSettled([transfer(s), transfer(s)]);
  assert.equal(results.filter(x => x.status === "fulfilled").length, 1);
  assert.equal((await c.getRole("cas")).record.ownership_epoch, 2);
});
test("transfer requires explicit matching quiescence and external generation", async () => {
  const s = await role("validation");
  await assert.rejects(c.transferRole(s, { priorOwner: s.record.owner, priorEpoch: 1, nextOwner: owner("new"), quiescence: {} }), { code: "INVALID" });
  const restored = await Coordination.connect(nc, { generation: "gen2" });
  await assert.rejects(restored.getRole("validation"), { code: "GENERATION" });
  await assert.rejects(restored.commitReceipt(s, { message_id: "m", stage: "processed", disposition: "done" }), { code: "GENERATION" });
});
test("guard staged before transfer must reject stale receipt at commit", async () => {
  const s = await role("staged"); await report("staged", "m");
  const h = headers(); h.set("Nats-Expected-Last-Subject-Sequence", String(s.revision)); h.set("Nats-Expected-Last-Subject-Sequence-Subject", subject("role", "staged"));
  const guard = subject("guard", "staged", "race");
  const batch = await c.js.startBatch(guard, new Uint8Array(), { headers: h });
  await transfer(s);
  const last = headers(); last.set("Nats-Expected-Last-Subject-Sequence", "0");
  await assert.rejects(batch.commit(subject("receipt", "staged", "m", "processed"), new Uint8Array(), { headers: last }), "INVARIANT: commit must recheck guard against role revision after intervening transfer");
  assert.equal(await c.receiptStatus("staged", "m", "processed"), null);
  assert.equal(await c.read(guard), null, "failed batch must leave no guard");
});
test("transfer versus receipt race never accepts receipt after transfer", async () => {
  for (let i = 0; i < 12; i++) {
    const id = "race" + i, s = await role(id); await report(id, "m");
    await Promise.allSettled([transfer(s), receipt(s, "m")]);
    const r = await c.receiptStatus(id, "m", "processed"), current = await c.getRole(id);
    if (r) assert.ok(r.revision < current.revision, "receipt must precede successful transfer");
    await report(id, "later");
    await assert.rejects(receipt(s, "later"));
  }
});
test("report uniqueness survives dedup expiry and recipient handoff", async () => {
  const s = await role("inbox"); const first = await report("inbox", "stable");
  await transfer(s); await new Promise(resolve => setTimeout(resolve, 250));
  const second = await report("inbox", "stable"); assert.equal(second.revision, first.revision);
  await assert.rejects(c.publishReport({ role_id: "inbox", message_id: "stable", payload: "changed" }), { code: "IMMUTABLE" });
  assert.equal((await c.listInbox("inbox")).length, 1);
  const current = await c.getRole("inbox"); await receipt(current, "stable");
  assert.equal((await c.listInbox("inbox")).length, 0);
  assert.ok(await c.reportStatus("inbox", "stable"), "processed report retained");
});
test("ambiguous response reconciles actual committed report by stable id", async () => {
  const real = c.js, ambiguous = await Coordination.connect(nc, { generation: "gen1" });
  ambiguous.js = { publish: async (...args) => { await real.publish(...args); throw new Error("injected ack loss after actual broker commit"); } };
  const result = await ambiguous.publishReport({ role_id: "ambiguous", message_id: "stable", payload: "value" });
  assert.equal(result.revision, (await c.reportStatus("ambiguous", "stable")).revision);
});
test("receipt uniqueness is immutable and failed duplicate batch leaves no guard", async () => {
  const s = await role("unique"); await report("unique", "m");
  const first = await receipt(s, "m"); const count = (await manager.streams.info("ADE_COORD_V1")).state.messages;
  const second = await receipt(s, "m"); assert.equal(first.revision, second.revision);
  assert.equal((await manager.streams.info("ADE_COORD_V1")).state.messages, count);
  await assert.rejects(c.commitReceipt(s, { message_id: "m", stage: "processed", disposition: "different" }), { code: "IMMUTABLE" });
});

test("persist lifecycle across independent client and CLI process; prohibit bypass and stale proofs", async () => {
  const initial = await role("lifecycle");
  await assert.rejects(c.transferRole(initial, { priorOwner: initial.record.owner, priorEpoch: 1, nextOwner: owner("new"), quiescence: evidence(initial) }), { code: "INVALID" });
  await assert.rejects(c.transitionRole(initial, { state: "checkpointed", checkpoint_digest: "a".repeat(64) }), { code: "INVALID" });
  const draining = await c.transitionRole(initial, { state: "draining" });
  await report("lifecycle", "pending");
  await assert.rejects(receipt(draining, "pending"), { code: "STALE" });
  await assert.rejects(receipt(initial, "pending"), { code: "STALE" });
  await assert.rejects(c.transitionRole(draining, { state: "active" }), { code: "INVALID" });
  await assert.rejects(c.transitionRole(draining, { state: "quiescent", quiescence: { ...quiescenceFor(draining), prior_revision: initial.revision } }), { code: "INVALID" });
  for (const change of [{ owner: owner("forged") }, { ownership_epoch: 2 }, { generation: "other" }]) {
    await assert.rejects(c.transitionRole({ ...draining, record: { ...draining.record, ...change } }, { state: "quiescent", quiescence: quiescenceFor(draining) }));
  }
  const nextConnection = await connect({ servers: nc.getServer() });
  try {
    const independent = await Coordination.connect(nextConnection, { generation: "gen1" });
    const persisted = await independent.getRole("lifecycle"); assert.deepEqual(persisted, draining);
    const quiescent = await independent.transitionRole(persisted, { state: "quiescent", quiescence: quiescenceFor(persisted) });
    await assert.rejects(c.transitionRole(draining, { state: "quiescent", quiescence: quiescenceFor(draining) }), { code: "STALE" });
    await assert.rejects(c.transitionRole(quiescent, { state: "checkpointed" }), { code: "INVALID" });
    await assert.rejects(c.transitionRole(quiescent, { state: "checkpointed", checkpoint_digest: "a".repeat(64), quiescence: { ...quiescenceFor(draining), jobs_stopped: false } }), { code: "INVALID" });
    const checkpointed = await c.transitionRole(quiescent, { state: "checkpointed", checkpoint_digest: "a".repeat(64) });
    assert.deepEqual(checkpointed.record.quiescence, quiescenceFor(draining));
    assert.equal(checkpointed.record.ownership_epoch, initial.record.ownership_epoch);
    assert.deepEqual(checkpointed.record.bindings, initial.record.bindings);
    await assert.rejects(c.transferRole(checkpointed, { priorOwner: owner("wrong"), priorEpoch: 1, nextOwner: owner("new"), quiescence: checkpointed.record.quiescence }), { code: "STALE" });
    await assert.rejects(c.transferRole(checkpointed, { priorOwner: initial.record.owner, priorEpoch: 0, nextOwner: owner("new"), quiescence: checkpointed.record.quiescence }), { code: "STALE" });
    await assert.rejects(c.transferRole(checkpointed, { priorOwner: initial.record.owner, priorEpoch: 1, nextOwner: owner("new"), quiescence: checkpointed.record.quiescence, checkpoint_digest: "b".repeat(64) }), { code: "INVALID" });
    const successor = await c.transferRole(checkpointed, { priorOwner: initial.record.owner, priorEpoch: 1, nextOwner: owner("new"), quiescence: checkpointed.record.quiescence });
    assert.equal(successor.record.state, "active"); assert.equal(successor.record.ownership_epoch, 2);
    assert.equal(successor.record.handoff.quiescence.prior_revision, draining.revision);
    assert.equal((await independent.listInbox("lifecycle")).length, 1);
    await receipt(successor, "pending"); assert.equal((await c.listInbox("lifecycle")).length, 0);
    const subprocess = await new Promise((resolve, reject) => {
      const child = spawn(process.execPath, [new URL("../cli.js", import.meta.url).pathname, "role", "get", "--state-dir", join(dir, "lifecycle-client")], { env: { ...process.env, ADE_NATS_URL: "nats://" + nc.getServer() } });
      let out = ""; child.stdout.on("data", d => out += d); child.on("error", reject); child.on("exit", code => resolve({ code, out })); child.stdin.end(JSON.stringify({ generation: "gen1", role_id: "lifecycle" }));
    });
    assert.equal(subprocess.code, 0, subprocess.out); assert.deepEqual(JSON.parse(subprocess.out).result, successor);
  } finally { await nextConnection.close(); }
});
test("concurrent lifecycle CAS has one winner and persists its exact record", async () => {
  const initial = await role("lifecycleRace");
  const results = await Promise.allSettled([c.transitionRole(initial, { state: "draining" }), c.transitionRole(initial, { state: "draining" })]);
  const wins = results.filter(r => r.status === "fulfilled"); assert.equal(wins.length, 1); assert.deepEqual(await c.getRole("lifecycleRace"), wins[0].value);
});
