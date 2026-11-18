import { handoff } from "./lifecycle.js";
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, writeFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { connect } from "@nats-io/transport-node";
import { jetstreamManager } from "@nats-io/jetstream";
import { Objm } from "@nats-io/obj";
import { Coordination, LocalState, Delivery, Artifacts, streamConfig, artifactReference } from "../index.js";
let dir, server, nc, core, url;
const pkg = fileURLToPath(new URL("../index.js", import.meta.url));
const cli = fileURLToPath(new URL("../cli.js", import.meta.url));
function child(args, input, extraEnv = {}) {
  return new Promise((resolve, reject) => {
    const p = spawn(process.execPath, args, { env: { ...process.env, ADE_NATS_URL: url, ...extraEnv } });
    let out = "", err = "";
    p.stdout.on("data", d => out += d); p.stderr.on("data", d => err += d);
    p.on("error", reject); p.on("exit", (code, signal) => resolve({ code, signal, out, err }));
    p.stdin.end(input ? JSON.stringify(input) : "");
  });
}
const run = (state, command, input, env) => child([cli, ...command.split(" "), "--state-dir", state], { generation: "gen1", ...input }, env);
const report = (role, id) => ({ role_id: role, message_id: id, payload: "durable" });
const makeRole = role_id => core.createRole({ role_id, owner: { host: "h", server: "s", agent: "a" }, ownership_epoch: 1, generation: "gen1", state: "active", bindings: [] });
const authority = s => ({ owner: s.record.owner, ownership_epoch: s.record.ownership_epoch, generation: s.record.generation, revision: s.revision });
before(async () => {
  assert.equal(process.platform, "linux"); dir = await mkdtemp(join(tmpdir(), "ade-delivery-"));
  const conf = join(dir, "nats.conf"); await writeFile(conf, `host: 127.0.0.1\nport: -1\njetstream { store_dir: "${dir}/broker", sync_interval: always }\n`);
  server = spawn(process.env.NATS_SERVER ?? "nats-server", ["-c", conf]);
  url = await new Promise((resolve, reject) => {
    let logs = ""; const timer = setTimeout(() => reject(new Error(logs)), 10000);
    server.on("error", reject); server.on("exit", () => { clearTimeout(timer); reject(new Error(logs)); });
    server.stderr.on("data", d => { logs += d; const m = logs.match(/Listening for client connections on (127\.0\.0\.1:\d+)/); if (m) { clearTimeout(timer); resolve("nats://" + m[1]); } });
  });
  nc = await connect({ servers: url }); const manager = await jetstreamManager(nc);
  await manager.streams.add({ ...streamConfig(), duplicate_window: 100000000 });
  await new Objm(nc).create("ADE_ARTIFACTS_V1", { storage: "file", ttl: 0 });
  core = await Coordination.connect(nc, { generation: "gen1" });
  console.log("delivery server", nc.info.version, "PID", server.pid);
});
after(async () => { await nc?.close(); if (server && server.exitCode === null) { const exited = new Promise(resolve => server.once("exit", resolve)); server.kill("SIGTERM"); await exited; console.log("delivery server terminated", server.pid); } if (dir) await rm(dir, { recursive: true, force: true }); });
test("SIGKILL after SQLite commit preserves intent and artifact bytes for fresh CLI reconciliation", async () => {
  const state = join(dir, "crashed");
  const script = `import {LocalState} from ${JSON.stringify(new URL("../index.js", import.meta.url).href)}; const s=new LocalState(process.argv[1]); s.enqueue({role_id:'crash',message_id:'stable',payload:'x'},[{bytes:new Uint8Array([1,2,3]),media_type:'text/plain'}]); process.kill(process.pid,'SIGKILL');`;
  const died = await child(["--input-type=module", "-e", script, state]); assert.equal(died.signal, "SIGKILL");
  const local = new LocalState(state); assert.equal(local.reportStatus("crash", "stable").stage, "local-buffered"); local.close();
  const result = await run(state, "outbox reconcile", {}); assert.equal(result.code, 0, result.out + result.err);
  assert.equal(JSON.parse(result.out).result[0].stage, "broker-accepted");
  assert.ok(await core.reportStatus("crash", "stable"));
  assert.equal((await stat(state)).mode & 0o777, 0o700);
  for (const suffix of ["", "-wal", "-shm"]) { try { assert.equal((await stat(join(state, "coord.sqlite" + suffix))).mode & 0o777, 0o600); } catch (e) { if (e.code !== "ENOENT") throw e; } }
});
test("concurrent CLI publishers serialize immutable IDs beyond duplicate window", async () => {
  const state = join(dir, "concurrent"), request = { report: report("concurrent", "same") };
  const results = await Promise.all(Array.from({ length: 5 }, () => run(state, "report publish", request)));
  for (const r of results) assert.equal(r.code, 0, r.out + r.err);
  const revisions = results.map(r => JSON.parse(r.out).result.revision); assert.equal(new Set(revisions).size, 1);
  await new Promise(resolve => setTimeout(resolve, 250));
  const retry = await run(state, "report publish", request); assert.equal(JSON.parse(retry.out).result.revision, revisions[0]);
  const conflict = await run(state, "report publish", { report: { ...request.report, payload: "changed" } }); assert.equal(JSON.parse(conflict.out).error.code, "IMMUTABLE");
});
test("lost publish response followed by DB reopen reconciles broker instead of republish", async () => {
  const path = join(dir, "lost"); let state = new LocalState(path);
  const lost = Object.create(core); lost.publishReport = async value => { await core.publishReport(value); throw new Error("injected lost reply"); };
  const delivery = new Delivery(lost, state, new Artifacts(nc));
  await assert.rejects(delivery.publish(report("lost", "same")));
  assert.equal(state.reportStatus("lost", "same").stage, "local-buffered"); state.close();
  const found = await core.reportStatus("lost", "same");
  state = new LocalState(path); const noPublish = Object.create(core); noPublish.publishReport = () => { throw new Error("must not republish"); };
  await new Delivery(noPublish, state, new Artifacts(nc)).reconcile();
  assert.equal(state.reportStatus("lost", "same").stage, "broker-accepted"); assert.equal((await core.reportStatus("lost", "same")).revision, found.revision); state.close();
});
test("partial actual Object Store upload leaves buffered intent; independent client retrieves recovered bytes", async () => {
  const path = join(dir, "partial"), state = new LocalState(path), artifacts = new Artifacts(nc);
  const bytes = new Uint8Array(200000).fill(91), ref = artifactReference(bytes, "application/test");
  const partial = Object.create(artifacts); partial.upload = async () => {
    let count = 0;
    const stream = new ReadableStream({ pull(controller) { if (count++ === 0) controller.enqueue(bytes.slice(0, 120000)); else controller.error(new Error("injected partial source")); } });
    await (await artifacts.store()).put({ name: ref.reference.name }, stream);
  };
  await assert.rejects(new Delivery(core, state, partial).publish(report("partial", "same"), { artifacts: [{ bytes, media_type: ref.media_type }] }));
  assert.equal(state.reportStatus("partial", "same").stage, "local-buffered"); assert.equal(await core.reportStatus("partial", "same"), null); state.close();
  const recovered = await run(path, "outbox reconcile", {}); assert.equal(JSON.parse(recovered.out).result[0].stage, "broker-accepted");
  const other = await run(join(dir, "independent"), "artifact read", { artifact: ref }); assert.equal(other.code, 0, other.out + other.err); assert.deepEqual(Buffer.from(JSON.parse(other.out).result.base64, "base64"), Buffer.from(bytes));
});
test("durable intake plus late consumer ack leaves retained report replayable until explicit disposition", async () => {
  const s = await makeRole("intake"), state = new LocalState(join(dir, "intake")), delivery = new Delivery(core, state, new Artifacts(nc));
  await delivery.publish(report("intake", "m"));
  await core.manager.consumers.add("ADE_COORD_V1", { durable_name: "late", filter_subject: "ade.v1.report.intake.m", ack_policy: "explicit", deliver_policy: "all" });
  const consumer = await core.js.consumers.get("ADE_COORD_V1", "late"), message = await consumer.next({ expires: 1000 }); assert.ok(message);
  await delivery.intake(s, { message_id: "m", authority: authority(s) }); message.ack(); await nc.flush();
  assert.equal((await core.listInbox("intake")).length, 1); assert.equal(delivery.readInbox("intake", "m").length, 1);
  const results = await Promise.all([delivery.dispose(s, { message_id: "m", authority: authority(s), disposition: "done" }), delivery.dispose(s, { message_id: "m", authority: authority(s), disposition: "done" })]);
  assert.equal(results[0].revision, results[1].revision); assert.equal((await core.listInbox("intake")).length, 0); assert.ok(await core.reportStatus("intake", "m"));
  await assert.rejects(delivery.dispose(s, { message_id: "m", authority: { ...authority(s), ownership_epoch: 0 }, disposition: "done" }), { code: "STALE" }); state.close();
});
test("operation UNKNOWN survives subprocess restart and cannot trigger automatic external retry", async () => {
  const state = join(dir, "operations");
  const first = await run(state, "operation intent", { id: "op", intent: { endpoint: "effect", value: 1 } }); assert.equal(JSON.parse(first.out).result.state, "UNKNOWN");
  const second = await run(state, "operation inspect", { id: "op" }); assert.equal(JSON.parse(second.out).result.state, "UNKNOWN");
  const bad = await run(state, "operation reconcile", { id: "op", state: "SUCCEEDED", result: 1 }); assert.equal(bad.code, 2);
  const reconciled = await run(state, "operation reconcile", { id: "op", state: "SUCCEEDED", result: 1, evidence: { endpoint_result: "verified" } }); assert.equal(JSON.parse(reconciled.out).result.state, "SUCCEEDED");
});
test("CLI rejects auth-bearing URLs without leaking input or token; persists publish before connection", async () => {
  const secret = "DO_NOT_EMIT_779", state = join(dir, "secret");
  const bad = await run(state, "report publish", { report: report("secret", "m") }, { ADE_NATS_URL: `nats://user:${secret}@127.0.0.1:1`, ADE_NATS_TOKEN: secret });
  assert.equal(bad.code, 2); assert.equal(JSON.parse(bad.out).error.code, "INVALID"); assert.ok(!(bad.out + bad.err).includes(secret));
  const local = new LocalState(state); assert.equal(local.reportStatus("secret", "m").stage, "local-buffered"); local.close();
});

test("handoff after intake preserves old receipt provenance and successor processes with independent DB", async () => {
  const old = await makeRole("handoff"), state = new LocalState(join(dir, "handoff-old"));
  const delivery = new Delivery(core, state, new Artifacts(nc)); await delivery.publish(report("handoff", "m"));
  const original = await delivery.intake(old, { message_id: "m", authority: authority(old) }); state.close();
  const successor = await handoff(core, old, { host: "h2", server: "s2", agent: "a2" });
  const nextState = new LocalState(join(dir, "handoff-new")), next = new Delivery(core, nextState, new Artifacts(nc));
  const replay = await next.intake(successor, { message_id: "m", authority: authority(successor) }); assert.equal(replay.revision, original.revision); assert.deepEqual(replay.record.owner, old.record.owner);
  const processed = await next.dispose(successor, { message_id: "m", authority: authority(successor), disposition: "successor-done" }); assert.deepEqual(processed.record.owner, successor.record.owner);
  assert.equal(next.readInbox("handoff", "m").length, 2); nextState.close();
});

test("SIGKILL before broker disposition does not poison same-host successor", async () => {
  const old = await makeRole("pendingCrash"), path = join(dir, "pendingCrash");
  await core.publishReport({ ...report("pendingCrash", "m"), artifacts: [] });
  const script = `import {connect} from '@nats-io/transport-node'; import {Coordination,LocalState,Delivery,Artifacts} from ${JSON.stringify(new URL('../index.js',import.meta.url).href)}; const nc=await connect({servers:process.env.ADE_NATS_URL}); const core=await Coordination.connect(nc,{generation:'gen1'}); const original=core.commitReceipt.bind(core); core.commitReceipt=async(s,o)=>{if(o.stage==='processed')process.kill(process.pid,'SIGKILL');return original(s,o);};const state=new LocalState(process.argv[1]);const snapshot=JSON.parse(process.argv[2]);await new Delivery(core,state,new Artifacts(nc)).dispose(snapshot,{message_id:'m',authority:JSON.parse(process.argv[3]),disposition:'X'});`;
  const crashed = await child(["--input-type=module", "-e", script, path, JSON.stringify(old), JSON.stringify(authority(old))]); assert.equal(crashed.signal, "SIGKILL", crashed.out + crashed.err);
  let state = new LocalState(path); assert.equal(state.readInbox("pendingCrash", "m").filter(r => r.stage === "processed").length, 0); assert.equal(state.dispositions("pendingCrash", "m")[0].status, "pending"); state.close();
  const successor = await handoff(core, old, { host: "h2", server: "s2", agent: "b" });
  state = new LocalState(path); const delivery = new Delivery(core, state, new Artifacts(nc));
  const done = await delivery.dispose(successor, { message_id: "m", authority: authority(successor), disposition: "Y" }); assert.equal(done.record.disposition, "Y");
  const intents = state.dispositions("pendingCrash", "m"); assert.equal(intents.find(i => i.disposition === '"X"').status, "abandoned"); assert.equal(intents.find(i => i.disposition === '"Y"').status, "confirmed");
  assert.equal(state.readInbox("pendingCrash", "m").find(r => r.stage === "processed").record.record.disposition, "Y"); state.close();
});
test("authoritative remote Y replaces pending local X without freezing false processed", async () => {
  const snapshot = await makeRole("remoteY"), local = new LocalState(join(dir, "remote-local")), remote = new LocalState(join(dir, "remote-remote"));
  const normal = new Delivery(core, local, new Artifacts(nc)); await normal.publish(report("remoteY", "m"));
  const failed = Object.create(core); failed.commitReceipt = async (s, o) => { if (o.stage === "processed") throw new Error("before broker"); return core.commitReceipt(s,o); };
  await assert.rejects(new Delivery(failed, local, new Artifacts(nc)).dispose(snapshot, { message_id: "m", authority: authority(snapshot), disposition: "X" }));
  assert.equal(local.readInbox("remoteY", "m").filter(r => r.stage === "processed").length, 0);
  await new Delivery(core, remote, new Artifacts(nc)).dispose(snapshot, { message_id: "m", authority: authority(snapshot), disposition: "Y" });
  const adopted = await normal.dispose(snapshot, { message_id: "m", authority: authority(snapshot), disposition: "Y" }); assert.equal(adopted.record.disposition, "Y");
  assert.equal(local.dispositions("remoteY", "m")[0].status, "abandoned"); assert.equal(local.readInbox("remoteY", "m").find(r => r.stage === "processed").record.record.disposition, "Y"); local.close(); remote.close();
});
test("lost report ack plus missing actual object repairs from reopened intent without report republish", async () => {
  const path = join(dir, "repairArtifact"), bytes = new Uint8Array([5,6,7,8]), artifacts = new Artifacts(nc), ref = artifactReference(bytes);
  let state = new LocalState(path); const lost = Object.create(core); lost.publishReport = async r => { await core.publishReport(r); throw new Error("ack lost"); };
  await assert.rejects(new Delivery(lost,state,artifacts).publish(report("repairArtifact","m"), { artifacts:[{bytes}] })); state.close();
  const stored = await core.reportStatus("repairArtifact","m"); await (await artifacts.store()).delete(ref.reference.name);
  state = new LocalState(path); const noPublish = Object.create(core); noPublish.publishReport = () => { throw new Error("must not republish"); };
  await new Delivery(noPublish,state,artifacts).reconcile(); assert.equal(state.reportStatus("repairArtifact","m").stage,"broker-accepted"); state.close();
  assert.equal((await core.reportStatus("repairArtifact","m")).revision,stored.revision);
  const independent = await run(join(dir,"repair-reader"), "artifact read", {artifact:ref}); assert.equal(independent.code,0,independent.out+independent.err); assert.deepEqual(Buffer.from(JSON.parse(independent.out).result.base64,"base64"),Buffer.from(bytes));
});
test("matching report with corrupt object stays buffered and does not silently overwrite", async () => {
  const state = new LocalState(join(dir,"corrupt")), bytes = new Uint8Array([10,11]), artifacts = new Artifacts(nc), ref = artifactReference(bytes);
  const lost = Object.create(core); lost.publishReport = async r => { await core.publishReport(r); throw new Error("ack lost"); };
  await assert.rejects(new Delivery(lost,state,artifacts).publish(report("corrupt","m"),{artifacts:[{bytes}]}));
  const store = await artifacts.store(); await store.putBlob({name:ref.reference.name},new Uint8Array([99]));
  const results = await new Delivery(core,state,artifacts).reconcile(); assert.equal(results[0].error,"UNKNOWN"); assert.equal(state.reportStatus("corrupt","m").stage,"local-buffered"); assert.deepEqual(Buffer.from(await store.getBlob(ref.reference.name)),Buffer.from([99])); state.close();
});
