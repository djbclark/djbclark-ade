import { Objm } from "@nats-io/obj";
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
import { Coordination, SharedOperations, safeToken, digest, subject, streamConfig } from "../index.js";
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
  await new Objm(nc).create("ADE_ARTIFACTS_V1", { storage: "file", ttl: 0 });
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

test("shared operation UNKNOWN is durable across clients and blocks quiescence until endpoint evidence", async () => {
  const initial=await role("sharedOps"), operations=new SharedOperations(c);
  await operations.intent(initial,"effect",{endpoint:"fake",key:"stable"});
  const independent=await Coordination.connect(nc,{generation:"gen1"});
  assert.equal((await new SharedOperations(independent).inspect("sharedOps","effect")).record.state,"UNKNOWN");
  await assert.rejects(operations.intent(initial,"effect",{endpoint:"changed"}),{code:"IMMUTABLE"});
  const draining=await c.transitionRole(initial,{state:"draining"});
  await assert.rejects(operations.intent(initial,"another",{}),{code:"STALE"});
  await assert.rejects(c.transitionRole(draining,{state:"quiescent",quiescence:quiescenceFor(draining)}),{code:"UNKNOWN"});
  await operations.reconcile(draining,"effect",{state:"NOT_APPLIED",result:null,evidence:{endpoint:"verified absence"}});
  const q=await c.transitionRole(draining,{state:"quiescent",quiescence:quiescenceFor(draining)});
  const ready=await c.transitionRole(q,{state:"checkpointed",checkpoint_digest:"a".repeat(64)});
  const successor=await c.transferRole(ready,{priorOwner:initial.record.owner,priorEpoch:1,nextOwner:owner("new"),quiescence:ready.record.quiescence});
  assert.equal((await new SharedOperations(independent).inspect("sharedOps","effect")).record.state,"NOT_APPLIED");
  assert.equal(successor.record.ownership_epoch,2);
});

test("real broker Python adapters persist completion, suppress prompt ack and follow successor role", async () => {
  const resource=join(dir,"adapter-resource"); await (await import("node:fs/promises")).mkdir(resource);
  const initial=await c.createRole({role_id:"adapter",owner:owner("old"),ownership_epoch:1,generation:"gen1",state:"active",bindings:[resource]});
  const cfgPath=join(dir,"adapter-config.json"), manifest=join(dir,"generation.json"), done=join(dir,"adapter.done"), reportPath=join(dir,"adapter-report.md");
  await writeFile(manifest,JSON.stringify({generation:"gen1",reconciled:true})); await writeFile(done,""); await writeFile(reportPath,"durable report bytes");
  const cfg={generation:"gen1",generation_manifest:manifest,state_dir:join(dir,"adapter-state"),identity:{host:"host1",server:"paseo1"},roles:{adapter:{controller:true}},claims:{claim:{role_id:"adapter",resources:[resource]}},aliases:{recipient:"adapter",old:"adapter",new:"adapter"},assignments:{worker:{id:"assignment",message_id:"stable",recipient_role:"adapter"}}}; await writeFile(cfgPath,JSON.stringify(cfg));
  const bin=new URL("../../../bin/",import.meta.url).pathname;
  const env={...process.env,ADE_COORD_CONFIG:cfgPath,ADE_COORD_NODE:process.execPath,ADE_NATS_URL:"nats://"+nc.getServer(),ADE_COORD_ENROLLMENT_MARKER:join(dir,"adapter-enrollment.json"),ADE_STATE_DIR:join(dir,"adapter-claims"),ADE_COORD_METRICS:join(dir,"adapter-metrics.jsonl")};
  const python=(args,input,extra={})=>new Promise((resolve,reject)=>{const child=spawn("python3",args,{env:{...env,...extra}});let out="",err="";child.stdout.on("data",d=>out+=d);child.stderr.on("data",d=>err+=d);child.on("error",reject);child.on("exit",code=>resolve({code,out,err}));child.stdin.end(input?JSON.stringify(input):"");});
  const enrolled=await python([bin+"ade_coord_controller.py","--enroll"]);assert.equal(enrolled.code,0,enrolled.out+enrolled.err);
  const provisioned=await python([bin+"ade-coord","broker","provision"],{confirm:"ADE_COORD_V1"});assert.equal(provisioned.code,0,provisioned.out+provisioned.err);assert.equal(JSON.parse(provisioned.out).result.object_store,"ADE_ARTIFACTS_V1");
  const sent=await python([bin+"completion-notice","--send","--requester","recipient","--sender","worker","--title","unit","--status","DONE","--report",reportPath]);assert.equal(sent.code,0,sent.out+sent.err);assert.equal(JSON.parse(sent.out).status,"broker-accepted");
  const repeated=await python([bin+"completion-notice","--send","--requester","recipient","--sender","worker","--title","unit","--status","DONE","--report",reportPath]);assert.equal(JSON.parse(repeated.out).revision,JSON.parse(sent.out).revision);
  const successor=await handoff(c,initial,owner("new"));
  const ack=await python([bin+"completion-notice","--lead-ack","--worker","worker","--msg-id","stable","--done",done,"--paseo","/missing-paseo-must-not-be-called"],null,{PASEO_AGENT_ID:"new"});assert.equal(ack.code,0,ack.out+ack.err);assert.deepEqual(JSON.parse(ack.out).routes,["ADE-inbox","disk"]);assert.equal(JSON.parse(ack.out).processed,false);
  const telemetry=(await (await import("node:fs/promises")).readFile(join(dir,"adapter-metrics.jsonl"),"utf8")).trim().split("\n").map(JSON.parse);assert.ok(telemetry.some(e=>e.request_bytes>0&&e.response_bytes>0&&e.elapsed_ms>=0));assert.ok(telemetry.some(e=>e.prompt_ack_suppressed===1));assert.ok(!JSON.stringify(telemetry).includes("durable report bytes"));
  assert.equal((await c.listInbox("adapter")).length,1);assert.equal((await c.receiptStatus("adapter","stable","ADE-inbox-recorded")).record.ownership_epoch,successor.record.ownership_epoch);
  const claimScript=`import sys,json;sys.path.insert(0,${JSON.stringify(bin)});from ade_claims import make_claim,create_claim,read_claim; c=make_claim(id='claim',path=${JSON.stringify(resource)},branch='pilot',base_sha='a'*40,owner_agent='new',owner_record='new');create_claim(c);print(json.dumps(read_claim('claim')))`;
  const created=await python(["-c",claimScript]);assert.equal(created.code,0,created.out+created.err);assert.equal(JSON.parse(created.out).coordination.role_id,"adapter");
  const job=await python([bin+"ade-coord","job","run"],{claim:"claim",job_id:"managed",argv:["python3","-c","print('managed-effect')"]},{PASEO_AGENT_ID:"new"});assert.equal(job.code,0,job.out+job.err);assert.equal(JSON.parse(job.out).result.exit_code,0);assert.ok(!job.out.includes("managed-effect"));
  const jobStatus=await python([bin+"ade-coord","job","inspect"],{job_id:"managed"});assert.equal(JSON.parse(jobStatus.out).result.state,"QUIESCENT");
  const check=`import sys,json;sys.path.insert(0,${JSON.stringify(bin)});from ade_claims import read_claim;from ade_coord import authorize_claim;authorize_claim(read_claim('claim'),'old')`;
  const stale=await python(["-c",check]);assert.notEqual(stale.code,0);
  const offline=await python([bin+"completion-notice","--send","--requester","recipient","--sender","worker","--title","offline","--status","DONE","--report",reportPath,"--msg-id","offline"],null,{ADE_NATS_URL:"nats://127.0.0.1:1"});assert.equal(offline.code,5,offline.out+offline.err);assert.equal(JSON.parse(offline.out).status,"local-buffered");
  const missingConfig=await python(["-c",check],null,{ADE_COORD_CONFIG:"",ADE_COORD_ENROLLMENT_MARKER:join(dir,"no-marker")});assert.notEqual(missingConfig.code,0,"persisted enrolled claim must not fall back");
  const received=await c.reportStatus("adapter","stable");const independent=await python([bin+"ade-coord","artifact","read"],{artifact:received.record.report.artifacts[0]});assert.equal(independent.code,0,independent.out+independent.err);assert.equal(Buffer.from(JSON.parse(independent.out).result.base64,"base64").toString(),"durable report bytes");
  const materialized=await python([bin+"ade-coord","artifact","materialize"],{artifact:received.record.report.artifacts[0]});assert.equal(materialized.code,0,materialized.out+materialized.err);assert.equal((await (await import("node:fs/promises")).readFile(JSON.parse(materialized.out).result.path)).toString(),"durable report bytes");

});

test("external handoff gate uses actual jobs, provider-child exit, workspace census and broker reconciliation", async () => {
  const fs=await import("node:fs/promises"), root=join(dir,"gate"), resource=join(root,"workspace");await fs.mkdir(resource,{recursive:true});
  const provider=spawn("python3",["-c","import time;time.sleep(60)"],{cwd:dir}); const exited=new Promise(resolve=>provider.once("exit",resolve));
  const bin=new URL("../../../bin/",import.meta.url).pathname, probe=new URL("../../../tests/coord_adapter_gate_probe.py",import.meta.url).pathname;
  const cfgPath=join(root,"config.json"), manifest=join(root,"generation.json"), checkpointPath=join(root,"checkpoint.md");
  await writeFile(manifest,JSON.stringify({generation:"gen1",reconciled:true}));await writeFile(checkpointPath,"checkpoint bytes");
  const next=owner("gateNext"), initial=await c.createRole({role_id:"gate",owner:owner("old"),ownership_epoch:1,generation:"gen1",state:"active",bindings:[resource]});
  const cfg={generation:"gen1",generation_manifest:manifest,state_dir:join(root,"state"),identity:{host:"host1",server:"paseo1"},roles:{gate:{controlled_pilot:true,successors:[next]}},claims:{gateClaim:{role_id:"gate",resources:[resource]}},aliases:{old:"gate",gateNext:"gate"},assignments:{}};await writeFile(cfgPath,JSON.stringify(cfg));
  const env={...process.env,ADE_COORD_CONFIG:cfgPath,ADE_COORD_NODE:process.execPath,ADE_NATS_URL:"nats://"+nc.getServer(),ADE_STATE_DIR:join(root,"claims"),ADE_COORD_ENROLLMENT_MARKER:join(root,"enrollment")};
  const python=(args,input)=>new Promise((resolve,reject)=>{const child=spawn("python3",args,{env});let out="",err="";child.stdout.on("data",d=>out+=d);child.stderr.on("data",d=>err+=d);child.on("error",reject);child.on("exit",code=>resolve({code,out,err}));child.stdin.end(input?JSON.stringify(input):"");});
  const bootstrap=`import sys,json;from pathlib import Path;sys.path.insert(0,${JSON.stringify(bin)});from ade_coord_resources import process_identity,Resources;from ade_claims import make_claim,create_claim;from ade_coord import remember_enrollment;remember_enrollment(); p=Path(${JSON.stringify(cfgPath)});cfg=json.loads(p.read_text());cfg['roles']['gate']['runtime']={'owner':${JSON.stringify(initial.record.owner)},'ownership_epoch':1,'processes':[process_identity(${provider.pid})]};p.write_text(json.dumps(cfg));create_claim(make_claim(id='gateClaim',path=${JSON.stringify(resource)},branch='pilot',base_sha='a'*40,owner_agent='old',owner_record='old'));r=Resources(Path(cfg['state_dir'])/'jobs');r.intent('job','gateClaim',{'owner':'prior'});r.close()`;
  try {
    const boot=await python(["-c",bootstrap]);assert.equal(boot.code,0,boot.out+boot.err);
    const request={role_id:"gate",next_owner:next,checkpoint_path:checkpointPath,attempt_id:"stableAttempt"};
    const blocked=await python([probe],request);assert.equal(blocked.code,1,blocked.out+blocked.err);assert.equal(JSON.parse(blocked.out).error,"TRACKED_JOBS_NOT_QUIESCENT");assert.equal((await c.getRole("gate")).record.owner.agent,"old");
    const reconcile=`import sys,json;from pathlib import Path;sys.path.insert(0,${JSON.stringify(bin)});from ade_coord_resources import Resources;r=Resources(Path(${JSON.stringify(cfg.state_dir)})/'jobs');r.reconcile_not_started('job',{'source':'fixture verified no launch'});r.close()`;
    const resolved=await python(["-c",reconcile]);assert.equal(resolved.code,0,resolved.out+resolved.err);
    const results=await Promise.all([python([probe],request),python([probe],request)]);
    for(const result of results)assert.equal(result.code,0,result.out+result.err);
    assert.equal((await c.getRole("gate")).record.ownership_epoch,2);assert.deepEqual(JSON.parse(results[0].out).result.role,JSON.parse(results[1].out).result.role);
    const transferred=await c.getRole("gate");assert.ok(transferred.record.handoff.quiescence.resource_manifest_digest);
    await exited;
  } finally {if(provider.exitCode===null)provider.kill("SIGTERM");}
});
