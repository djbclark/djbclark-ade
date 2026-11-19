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
  const boundary=join(dir,"managed-boundary");
  await writeFile(boundary,"#!/usr/bin/env python3\nimport os,sys\nargs=sys.argv[sys.argv.index('--')+1:]\nenv={**os.environ,'ADE_NATS_TOKEN':'fixture-current-token','UNRELATED_MANAGED_SECRET':'must-not-reach-consumer'}\nos.execvpe(args[0],args,env)\n",{mode:0o700});
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
  const cfg={credential_boundary:join(dir,"managed-boundary"),generation:"gen1",generation_manifest:manifest,state_dir:join(dir,"adapter-state"),identity:{host:"host1",server:"paseo1"},roles:{adapter:{controller:true}},claims:{claim:{role_id:"adapter",resources:[resource]}},aliases:{recipient:"adapter",old:"adapter",new:"adapter"},assignments:{worker:{id:"assignment",message_id:"stable",recipient_role:"adapter"}}}; await writeFile(cfgPath,JSON.stringify(cfg));
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
  const job=await python([bin+"ade-coord","job","run"],{claim:"claim",job_id:"managed",argv:["python3","-c","import os;print('managed-effect');print(os.environ['PATH'].split(os.pathsep)[0])"]},{PASEO_AGENT_ID:"new"});assert.equal(job.code,0,job.out+job.err);assert.equal(JSON.parse(job.out).result.exit_code,0);assert.ok(!job.out.includes("managed-effect"));assert.match((await (await import("node:fs/promises")).readFile(JSON.parse(job.out).result.output,"utf8")).trim().split("\n")[1],/libexec\/agent-bin$/);
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
  let launch,gating;
  const provider=spawn("python3",["-c","import time;time.sleep(60)"],{cwd:dir}); const exited=new Promise(resolve=>provider.once("exit",resolve));
  const bin=new URL("../../../bin/",import.meta.url).pathname, probe=new URL("../../../tests/coord_adapter_gate_probe.py",import.meta.url).pathname;
  const cfgPath=join(root,"config.json"), manifest=join(root,"generation.json"), checkpointPath=join(root,"checkpoint.md");
  await writeFile(manifest,JSON.stringify({generation:"gen1",reconciled:true}));await writeFile(checkpointPath,"checkpoint bytes");
  const next=owner("gateNext"), initial=await c.createRole({role_id:"gate",owner:owner("old"),ownership_epoch:1,generation:"gen1",state:"active",bindings:[resource]});
  const cfg={credential_boundary:join(dir,"managed-boundary"),generation:"gen1",generation_manifest:manifest,state_dir:join(root,"state"),identity:{host:"host1",server:"paseo1"},roles:{gate:{controlled_pilot:true,successors:[next]}},claims:{gateClaim:{role_id:"gate",resources:[resource]}},aliases:{old:"gate",gateNext:"gate"},assignments:{}};await writeFile(cfgPath,JSON.stringify(cfg));
  const env={...process.env,ADE_COORD_CONFIG:cfgPath,ADE_COORD_NODE:process.execPath,ADE_NATS_URL:"nats://"+nc.getServer(),ADE_STATE_DIR:join(root,"claims"),ADE_COORD_ENROLLMENT_MARKER:join(root,"enrollment")};
  const python=(args,input,extra={})=>new Promise((resolve,reject)=>{const child=spawn("python3",args,{env:{...env,...extra}});let out="",err="";child.stdout.on("data",d=>out+=d);child.stderr.on("data",d=>err+=d);child.on("error",reject);child.on("exit",code=>resolve({code,out,err}));child.stdin.end(input?JSON.stringify(input):"");});
  const bootstrap=`import sys,json;from pathlib import Path;sys.path.insert(0,${JSON.stringify(bin)});from ade_coord_resources import process_identity,Resources;from ade_claims import make_claim,create_claim;from ade_coord import remember_enrollment;remember_enrollment(); p=Path(${JSON.stringify(cfgPath)});cfg=json.loads(p.read_text());cfg['roles']['gate']['runtime']={'owner':${JSON.stringify(initial.record.owner)},'ownership_epoch':1,'processes':[process_identity(${provider.pid})]};p.write_text(json.dumps(cfg));create_claim(make_claim(id='gateClaim',path=${JSON.stringify(resource)},branch='pilot',base_sha='a'*40,owner_agent='old',owner_record='old'));r=Resources(Path(cfg['state_dir'])/'jobs');r.intent('job','gateClaim',{'owner':'prior'});r.close()`;
  try {
    const boot=await python(["-c",bootstrap]);assert.equal(boot.code,0,boot.out+boot.err);
    const request={role_id:"gate",next_owner:next,checkpoint_path:checkpointPath,attempt_id:"stableAttempt"};
    const admissionProbe=new URL("../../../tests/coord_admission_probe.py",import.meta.url).pathname;
    launch=spawn("python3",[admissionProbe],{env});let launchErr="";launch.stderr.on("data",d=>launchErr+=d);const launchExit=new Promise(resolve=>launch.once("exit",resolve));
    const authorized=new Promise((resolve,reject)=>{launch.stdout.on("data",d=>{if(d.toString().includes("AUTHORIZED"))resolve();});launch.once("exit",()=>reject(new Error(launchErr)));});
    await authorized;
    gating=spawn("python3",[probe],{env:{...env,ADE_TEST_ADMISSION_READY:"1"}});let gateOut="",gateErr="";gating.stdout.on("data",d=>gateOut+=d);
    const waiting=new Promise((resolve,reject)=>{gating.stderr.on("data",d=>{gateErr+=d;if(gateErr.includes("WAITING_ADMISSION"))resolve();});gating.once("exit",()=>reject(new Error(gateErr)));});
    const gated=new Promise(resolve=>gating.once("exit",code=>resolve({code,out:gateOut,err:gateErr})));gating.stdin.end(JSON.stringify(request));await waiting;
    assert.equal((await c.getRole("gate")).record.state,"active","paused admitted grant holds drain barrier before registration");launch.stdin.end("GO\n");
    const blocked=await gated;assert.equal(blocked.code,1,blocked.out+blocked.err);assert.equal(JSON.parse(blocked.out).error,"TRACKED_JOBS_NOT_QUIESCENT");assert.equal((await c.getRole("gate")).record.owner.agent,"old");
    await writeFile(join(cfg.state_dir,"finish-admitted-job"),"finish");assert.equal(await launchExit,0,launchErr);
    const reconcile=`import sys,json;from pathlib import Path;sys.path.insert(0,${JSON.stringify(bin)});from ade_coord_resources import Resources;r=Resources(Path(${JSON.stringify(cfg.state_dir)})/'jobs');r.reconcile_not_started('job',{'source':'fixture verified no launch'});r.close()`;
    const resolved=await python(["-c",reconcile]);assert.equal(resolved.code,0,resolved.out+resolved.err);
    const phaseCrash=await python([probe],request,{ADE_TEST_PHASE_CRASH:"quiescent"});assert.equal(phaseCrash.code,1,phaseCrash.out+phaseCrash.err);assert.equal(JSON.parse(phaseCrash.out).error,"INJECTED_PHASE_CRASH");
    const lateJob=`import sys;from pathlib import Path;sys.path.insert(0,${JSON.stringify(bin)});from ade_coord_resources import Resources;r=Resources(Path(${JSON.stringify(cfg.state_dir)})/'jobs');r.intent('resumed-unknown','gateClaim',{'owner':'prior'});r.close()`;assert.equal((await python(["-c",lateJob])).code,0);
    const resumeBlocked=await python([probe],request);assert.equal(JSON.parse(resumeBlocked.out).error,"TRACKED_JOBS_NOT_QUIESCENT");
    assert.equal((await python(["-c",reconcile.replace("'job'","'resumed-unknown'")])).code,0);
    const results=await Promise.all([python([probe],request),python([probe],request)]);
    for(const result of results)assert.equal(result.code,0,result.out+result.err);
    assert.equal((await c.getRole("gate")).record.ownership_epoch,2);assert.deepEqual(JSON.parse(results[0].out).result.role,JSON.parse(results[1].out).result.role);
    const transferred=await c.getRole("gate");assert.ok(transferred.record.handoff.quiescence.resource_manifest_digest);
    await exited;
    const nextProvider=spawn("python3",["-c","import time;time.sleep(60)"],{cwd:dir});const nextExited=new Promise(resolve=>nextProvider.once("exit",resolve));
    try {
      const third=owner("gateThird"),fourth=owner("gateFourth");
      const advance=`import sys,json;from pathlib import Path;sys.path.insert(0,${JSON.stringify(bin)});from ade_coord_resources import process_identity;p=Path(${JSON.stringify(cfgPath)});cfg=json.loads(p.read_text());cfg['roles']['gate']['successors']=[${JSON.stringify(third)},${JSON.stringify(fourth)}];cfg['aliases']['gateThird']='gate';cfg['aliases']['gateFourth']='gate';cfg['roles']['gate']['runtime']={'owner':${JSON.stringify(next)},'ownership_epoch':2,'processes':[process_identity(${nextProvider.pid})]};p.write_text(json.dumps(cfg))`;
      const advanced=await python(["-c",advance]);assert.equal(advanced.code,0,advanced.out+advanced.err);
      await writeFile(checkpointPath,"second checkpoint bytes");
      const secondRequest={...request,next_owner:third,attempt_id:"secondAttempt"};
      const checkpointCrash=await python([probe],secondRequest,{ADE_TEST_PHASE_CRASH:"checkpointed"});assert.equal(checkpointCrash.code,1,checkpointCrash.out+checkpointCrash.err);assert.equal(JSON.parse(checkpointCrash.out).error,"INJECTED_PHASE_CRASH");
      assert.equal((await python(["-c",lateJob.replace("'resumed-unknown'","'checkpoint-unknown'")])).code,0);
      const checkpointBlocked=await python([probe],secondRequest);assert.equal(JSON.parse(checkpointBlocked.out).error,"TRACKED_JOBS_NOT_QUIESCENT");
      assert.equal((await python(["-c",reconcile.replace("'job'","'checkpoint-unknown'")])).code,0);
      const crashed=await python([probe],secondRequest,{ADE_TEST_PROJECTION_CRASH:"secondAttempt"});assert.equal(crashed.code,1,crashed.out+crashed.err);assert.equal(JSON.parse(crashed.out).error,"INJECTED_PROJECTION_CRASH");assert.equal((await c.getRole("gate")).record.ownership_epoch,3);
      const competing=await python([probe],{...request,next_owner:fourth,attempt_id:"competingAttempt"});assert.equal(competing.code,1);assert.equal(JSON.parse(competing.out).error,"UNFINISHED_HANDOFF_MUST_RECONCILE_FIRST");
      const recovered=await python([probe],secondRequest);assert.equal(recovered.code,0,recovered.out+recovered.err);
      const old=await python([probe],request);assert.equal(old.code,0,old.out+old.err);assert.equal(JSON.parse(old.out).result.role.record.owner.agent,"gateThird");assert.equal(JSON.parse(old.out).result.historical,true);
      const projection=await python(["-c",`import sys,json;sys.path.insert(0,${JSON.stringify(bin)});from ade_claims import read_claim;print(json.dumps(read_claim('gateClaim')))`]);assert.equal(JSON.parse(projection.out).owner.agent,"gateThird");assert.equal((await c.getRole("gate")).record.ownership_epoch,3);
      await nextExited;
    } finally {if(nextProvider.exitCode===null)nextProvider.kill("SIGTERM");}
  } finally {
    try{await fs.writeFile(join(cfg.state_dir,"finish-admitted-job"),"finish");}catch{}
    if(launch?.exitCode===null){if(!launch.stdin.destroyed)launch.stdin.end("GO\n");launch.kill("SIGTERM");}
    if(gating?.exitCode===null)gating.kill("SIGTERM");
    if(provider.exitCode===null)provider.kill("SIGTERM");
  }
});

test("resource-free role transfers across independent host/server state while local resources cannot migrate",async()=>{
  const fs=await import("node:fs/promises"),root=join(dir,"free-hosts");await fs.mkdir(root,{recursive:true});
  const provider=spawn("python3",["-c","import time;time.sleep(60)"],{cwd:dir});const exited=new Promise(resolve=>provider.once("exit",resolve));
  const bin=new URL("../../../bin/",import.meta.url).pathname,probe=new URL("../../../tests/coord_adapter_gate_probe.py",import.meta.url).pathname;
  const old=owner("freeOld"),remote={host:"independentHost",server:"independentServer",agent:"freeRemote"};
  const initial=await c.createRole({role_id:"free",owner:old,ownership_epoch:1,generation:"gen1",state:"active",bindings:[]});
  const manifestA=join(root,"manifest-a"),manifestB=join(root,"manifest-b"),cfgA=join(root,"config-a"),cfgB=join(root,"config-b"),checkpointPath=join(root,"checkpoint"),reportPath=join(root,"report"),done=join(root,"done");
  for(const path of [manifestA,manifestB])await writeFile(path,JSON.stringify({generation:"gen1",reconciled:true}));await writeFile(checkpointPath,"free checkpoint");await writeFile(reportPath,"cross-host artifact");await writeFile(done,"");
  const config={credential_boundary:join(dir,"managed-boundary"),generation:"gen1",generation_manifest:manifestA,state_dir:join(root,"state-a"),identity:{host:old.host,server:old.server},roles:{free:{controlled_pilot:true,resource_free:true,controller:true,successors:[remote]}},claims:{},aliases:{freeOld:"free",freeRemote:"free",recipient:"free"},assignments:{worker:{id:"free-assignment",recipient_role:"free",message_id:"pre"}}};await writeFile(cfgA,JSON.stringify(config));
  await writeFile(cfgB,JSON.stringify({...config,generation_manifest:manifestB,state_dir:join(root,"state-b"),identity:{host:remote.host,server:remote.server}}));
  const envFor=host=>({...process.env,ADE_COORD_CONFIG:host==="a"?cfgA:cfgB,ADE_COORD_NODE:process.execPath,ADE_NATS_URL:"nats://"+nc.getServer(),ADE_COORD_ENROLLMENT_MARKER:join(root,"enrolled-"+host),ADE_STATE_DIR:join(root,"claims-"+host)});
  const python=(host,args,input,extra={})=>new Promise((resolve,reject)=>{const child=spawn("python3",args,{env:{...envFor(host),...extra}});let out="",err="";child.stdout.on("data",d=>out+=d);child.stderr.on("data",d=>err+=d);child.on("error",reject);child.on("exit",code=>resolve({code,out,err}));child.stdin.end(input?JSON.stringify(input):"");});
  try{
    for(const host of ["a","b"]){const e=await python(host,[bin+"ade_coord_controller.py","--enroll"]);assert.equal(e.code,0,e.out+e.err);}
    const boot=await python("a",["-c",`import sys,json;from pathlib import Path;sys.path.insert(0,${JSON.stringify(bin)});from ade_coord_resources import process_identity;p=Path(${JSON.stringify(cfgA)});cfg=json.loads(p.read_text());cfg['roles']['free']['runtime']={'owner':${JSON.stringify(old)},'ownership_epoch':1,'processes':[process_identity(${provider.pid})]};p.write_text(json.dumps(cfg))`]);assert.equal(boot.code,0,boot.out+boot.err);
    const send=id=>python("a",[bin+"completion-notice","--send","--requester","recipient","--sender","worker","--title","free","--status","DONE","--report",reportPath,"--msg-id",id]);
    const pre=await send("pre");assert.equal(pre.code,0,pre.out+pre.err);
    const oldIntake=await python("a",[bin+"completion-notice","--lead-ack","--worker","worker","--msg-id","pre","--done",done],null,{PASEO_AGENT_ID:"freeOld"});assert.equal(oldIntake.code,0,oldIntake.out+oldIntake.err);
    const operations=new SharedOperations(c);await operations.intent(initial,"unknown-effect",{endpoint:"requires-reconcile"});
    const request={role_id:"free",next_owner:remote,attempt_id:"freeAttempt",checkpoint_path:checkpointPath};
    const blocked=await python("a",[probe],request);assert.equal(blocked.code,1,blocked.out+blocked.err);assert.equal(JSON.parse(blocked.out).error,"SHARED_OPERATION_UNKNOWN");
    const draining=await c.getRole("free");await operations.reconcile(draining,"unknown-effect",{state:"NOT_APPLIED",result:null,evidence:{endpoint:"verified absent"}});
    const moved=await python("a",[probe],request);assert.equal(moved.code,0,moved.out+moved.err);assert.deepEqual((await c.getRole("free")).record.owner,remote);assert.match(JSON.parse(moved.out).result.scope,/no local projections/);
    const post=await send("post");assert.equal(post.code,0,post.out+post.err);
    const pump=await python("b",[bin+"ade_coord_controller.py","--role","free"]);assert.equal(pump.code,0,pump.out+pump.err);assert.equal(JSON.parse(pump.out).result.ADE_inbox_recorded,2);
    const current=await c.getRole("free"),auth={owner:remote,ownership_epoch:2,generation:"gen1",revision:current.revision};
    for(const id of ["pre","post"]){
      const record=await c.reportStatus("free",id);const material=await python("b",[bin+"ade-coord","artifact","materialize"],{artifact:record.record.report.artifacts[0]});assert.equal(material.code,0,material.out+material.err);assert.equal((await fs.readFile(JSON.parse(material.out).result.path)).toString(),"cross-host artifact");
      const disposed=await python("b",[bin+"ade-coord","inbox","dispose"],{snapshot:current,authority:auth,message_id:id,disposition:"remote-processed"});assert.equal(disposed.code,0,disposed.out+disposed.err);
    }
    assert.deepEqual((await c.receiptStatus("free","pre","ADE-inbox-recorded")).record.owner,old);assert.deepEqual((await c.receiptStatus("free","pre","processed")).record.owner,remote);
    await assert.rejects(c.commitReceipt(initial,{message_id:"post",stage:"processed",disposition:"stale"}),{code:"STALE"});
    const resource=join(root,"nonempty-workspace");await fs.mkdir(resource);await c.createRole({role_id:"migration",owner:old,ownership_epoch:1,generation:"gen1",state:"active",bindings:[resource]});
    const changed=JSON.parse(await fs.readFile(cfgA,"utf8"));changed.roles.migration={controlled_pilot:true,successors:[remote]};await writeFile(cfgA,JSON.stringify(changed));
    const refused=await python("a",[bin+"ade-coord","handoff","transfer"],{...request,role_id:"migration",attempt_id:"migrationAttempt"});assert.equal(refused.code,1,refused.out+refused.err);assert.equal(JSON.parse(refused.out).error.code,"REMOTE_RESOURCE_ADAPTER_REQUIRED");assert.equal((await c.getRole("migration")).record.ownership_epoch,1);
    await exited;
  }finally{if(provider.exitCode===null)provider.kill("SIGTERM");}
});

test("real broker wake intents coalesce across reopen and UNKNOWN blocks transfer without receipt inference",async()=>{
  const fs=await import("node:fs/promises"),root=join(dir,"wake-controller");await fs.mkdir(root);
  const role=await c.createRole({role_id:"pulse",owner:owner("pulseAgent"),ownership_epoch:1,generation:"gen1",state:"active",bindings:[]});
  const cfgPath=join(root,"config"),manifest=join(root,"manifest"),state=join(root,"state");await writeFile(manifest,JSON.stringify({generation:"gen1",reconciled:true}));
  await writeFile(cfgPath,JSON.stringify({credential_boundary:join(dir,"managed-boundary"),generation:"gen1",generation_manifest:manifest,state_dir:state,identity:{host:"host1",server:"paseo1"},roles:{pulse:{controller:true,wake:true}},claims:{},aliases:{pulseAgent:"pulse"},assignments:{}}));
  const bin=new URL("../../../bin/",import.meta.url).pathname,probe=new URL("../../../tests/coord_wake_probe.py",import.meta.url).pathname;
  const env={...process.env,ADE_COORD_CONFIG:cfgPath,ADE_COORD_NODE:process.execPath,ADE_NATS_URL:"nats://"+nc.getServer(),ADE_COORD_ENROLLMENT_MARKER:join(root,"enrolled"),ADE_STATE_DIR:join(root,"claims")};
  const python=(args,input)=>new Promise((resolve,reject)=>{const child=spawn("python3",args,{env});let out="",err="";child.stdout.on("data",d=>out+=d);child.stderr.on("data",d=>err+=d);child.on("error",reject);child.on("exit",code=>resolve({code,out,err}));child.stdin.end(input?JSON.stringify(input):"");});
  const enrolled=await python([bin+"ade_coord_controller.py","--enroll"]);assert.equal(enrolled.code,0,enrolled.out+enrolled.err);
  await c.publishReport({role_id:"pulse",message_id:"one",payload:"pending",artifacts:[]});
  const busy=await python([probe],{role_id:"pulse",mode:"busy"});assert.equal(JSON.parse(busy.out).result.status,"deferred-busy");
  const first=await python([probe],{role_id:"pulse",mode:"idle"});assert.equal(first.code,0,first.out+first.err);assert.equal(JSON.parse(first.out).result.native_status,"queued");
  const repeated=await python([probe],{role_id:"pulse",mode:"idle"});assert.equal(JSON.parse(repeated.out).result.status,"coalesced");
  assert.equal(await c.receiptStatus("pulse","one","processed"),null);assert.equal(await c.receiptStatus("pulse","one","ADE-inbox-recorded"),null);
  await c.publishReport({role_id:"pulse",message_id:"two",payload:"new pending",artifacts:[]});
  const uncertain=await python([probe],{role_id:"pulse",mode:"unknown"});assert.equal(uncertain.code,0,uncertain.out+uncertain.err);const wake=JSON.parse(uncertain.out).result;assert.equal(wake.status,"unknown-no-retry");
  const noRetry=await python([probe],{role_id:"pulse",mode:"idle"});assert.equal(JSON.parse(noRetry.out).result.status,"coalesced");
  assert.equal((await fs.readFile(join(state,"synthetic-wake-calls"),"utf8")).trim().split("\n").length,2);
  const draining=await c.transitionRole(role,{state:"draining"});await assert.rejects(c.transitionRole(draining,{state:"quiescent",quiescence:quiescenceFor(draining)}),{code:"UNKNOWN"});
  const resolved=await python([probe],{command:"reconcile",wake_id:wake.wake_id,state:"NOT_APPLIED",result:null,evidence:{endpoint:"fixture verified no enqueue"}});assert.equal(resolved.code,0,resolved.out+resolved.err);
  await c.transitionRole(draining,{state:"quiescent",quiescence:quiescenceFor(draining)});
});
