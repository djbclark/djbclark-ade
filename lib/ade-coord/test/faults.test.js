import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { openSync, writeSync, closeSync } from "node:fs";
import { readFile, writeFile, rm, cp, statfs } from "node:fs/promises";
import { join } from "node:path";
import { connect } from "@nats-io/transport-node";
import { Coordination, LocalState, Delivery, Artifacts, artifactReference, subject } from "../index.js";
import { Broker, FaultProxy, until, sleep, countSubject, stopChild } from "./fault-fixture.js";
import { handoff } from "./lifecycle.js";

const role = role_id => ({ role_id, owner: { host: "h", server: "s", agent: "a" }, ownership_epoch: 1, generation: "gen1", state: "active", bindings: [] });
const authority = s => ({ owner: s.record.owner, ownership_epoch: s.record.ownership_epoch, generation: s.record.generation, revision: s.revision });
const report = (message_id, payload = "retained") => ({ role_id: "pilot", message_id, payload });
function state(t, path) { const s = new LocalState(path); t.after(() => s.close()); return s; }
async function seed(t, b, path) {
  const s = state(t, path), d = new Delivery(b.core, s, new Artifacts(b.nc));
  const owner = await b.core.createRole(role("pilot"));
  const bytes = new Uint8Array(8192).fill(77), artifact = artifactReference(bytes);
  const accepted = await d.publish(report("accepted"), { artifacts: [{ bytes }] });
  const intake = await d.intake(owner, { message_id: "accepted", authority: authority(owner) });
  const processed = await d.dispose(owner, { message_id: "accepted", authority: authority(owner), disposition: "done" });
  return { owner, accepted, intake, processed, bytes, artifact, s, d };
}
async function retained(b, x) {
  assert.deepEqual(await b.core.getRole("pilot"), x.owner);
  assert.deepEqual(await b.core.reportStatus("pilot", "accepted"), x.accepted);
  assert.deepEqual(await b.core.receiptStatus("pilot", "accepted", "ADE-inbox-recorded"), x.intake);
  assert.deepEqual(await b.core.receiptStatus("pilot", "accepted", "processed"), x.processed);
  const independent = await b.connection();
  try { assert.deepEqual(Buffer.from(await new Artifacts(independent).readArtifact(x.artifact)), Buffer.from(x.bytes)); }
  finally { await independent.close(); }
}

test("actual stream DiscardNew capacity keeps old ledger and stable buffered ID until capacity is restored", { timeout: 25000 }, async t => {
  const b = await Broker.create(t), x = await seed(t, b, join(b.dir, "local"));
  const before = await b.manager.streams.info("ADE_COORD_V1");
  await b.manager.streams.update("ADE_COORD_V1", { max_bytes: before.state.bytes + 64 });
  await assert.rejects(x.d.publish(report("pressure", "x".repeat(4096))));
  assert.equal(x.s.reportStatus("pilot", "pressure").stage, "local-buffered");
  assert.equal(await b.core.reportStatus("pilot", "pressure"), null);
  assert.equal((await b.manager.streams.info("ADE_COORD_V1")).state.messages, before.state.messages);
  await retained(b, x);
  await b.manager.streams.update("ADE_COORD_V1", { max_bytes: before.config.max_bytes });
  assert.equal((await x.d.reconcile())[0].stage, "broker-accepted");
  await sleep(150); await x.d.publish(report("pressure", "x".repeat(4096)));
  assert.equal(await countSubject(b.core, subject("report", "pilot", "pressure")), 1);
  await retained(b, x);
});

test("actual Object Store DiscardNew pressure preserves old bytes and prevents report acceptance until repair", { timeout: 25000 }, async t => {
  const b = await Broker.create(t), x = await seed(t, b, join(b.dir, "local"));
  const stream = "OBJ_ADE_ARTIFACTS_V1", before = await b.manager.streams.info(stream);
  assert.equal(before.config.discard, "new");
  await b.manager.streams.update(stream, { max_bytes: before.state.bytes + 1024 });
  const bytes = new Uint8Array(200000).fill(51), artifact = artifactReference(bytes);
  await assert.rejects(x.d.publish(report("blobPressure"), { artifacts: [{ bytes }] }));
  assert.equal(x.s.reportStatus("pilot", "blobPressure").stage, "local-buffered");
  assert.equal(await b.core.reportStatus("pilot", "blobPressure"), null);
  await retained(b, x);
  await b.manager.streams.update(stream, { max_bytes: before.config.max_bytes });
  assert.equal((await x.d.reconcile())[0].stage, "broker-accepted");
  const independent = await b.connection();
  assert.deepEqual(Buffer.from(await new Artifacts(independent).readArtifact(artifact)), Buffer.from(bytes));
  await independent.close(); await retained(b, x);
});

test("real bounded tmpfs ENOSPC rejects broker writes, then space recovery and restart reconcile retained coordination", { timeout: 45000 }, async t => {
  const mount = process.env.ADE_FAULT_TMPFS;
  assert.ok(mount, "ADE_FAULT_TMPFS must name the CI-owned disposable tmpfs; unsupported environments must fail");
  const fs = await statfs(mount); assert.equal(Number(fs.type), 0x01021994, "require actual Linux tmpfs");
  assert.ok(fs.blocks * fs.bsize <= 64 * 1024 * 1024, "refuse to fill an unbounded/general filesystem");
  const b = await Broker.create(t, { parent: mount });
  // Local SQLite is deliberately on a different filesystem, so broker ENOSPC
  // cannot erase the durable publish intent or make its error update impossible.
  const localDir = join(process.env.RUNNER_TEMP ?? "/tmp", `ade-enospc-local-${b.child.pid}`);
  t.after(() => rm(localDir, { recursive: true, force: true }));
  const x = await seed(t, b, localDir);
  const filler = join(b.dir, "bounded-filler"), fd = openSync(filler, "wx", 0o600);
  let observed = false, allocated = 0;
  try {
    const chunk = Buffer.alloc(4096, 0x5a);
    for (let i = 0; i < 16384; i++) {
      try { allocated += writeSync(fd, chunk); }
      catch (error) { assert.equal(error.code, "ENOSPC"); observed = true; break; }
    }
  } finally { closeSync(fd); }
  assert.equal(observed, true, "must observe real ENOSPC, not stream max_bytes");
  console.log("actual tmpfs ENOSPC", { allocated, size: fs.blocks * fs.bsize });
  await assert.rejects(x.d.publish(report("diskPending", "p".repeat(512000))));
  assert.equal(x.s.reportStatus("pilot", "diskPending").stage, "local-buffered");
  // Server's own write path must observe disk pressure too, not only the filler.
  await until(() => /no space left|ENOSPC/i.test(b.logs), "broker did not report actual filesystem ENOSPC");
  await rm(filler); await b.restart();
  await retained(b, x);
  const reopened = state(t, localDir), d = new Delivery(b.core, reopened, new Artifacts(b.nc));
  const results = await d.reconcile(); assert.equal(results.find(r => r.message_id === "diskPending").stage, "broker-accepted");
  assert.equal(await countSubject(b.core, subject("report", "pilot", "diskPending")), 1);
  await retained(b, x);
});

test("established TCP partition loses actual publish and atomic receipt replies; reconnect adopts one stable result", { timeout: 35000 }, async t => {
  const b = await Broker.create(t), x = await seed(t, b, join(b.dir, "seed"));
  const proxy = await FaultProxy.create(t, b), nc = await b.connection(proxy.url), core = await b.coordination(nc);
  let disconnected = 0, reconnected = 0;
  const watching = (async () => { for await (const event of nc.status()) { if (event.type === "disconnect") disconnected++; if (event.type === "reconnect") reconnected++; } })();
  t.after(async () => { await nc.close(); await watching; });
  const localDir = join(b.dir, "partition"), first = new LocalState(localDir);
  const d = new Delivery(core, first, new Artifacts(nc));
  proxy.arm(subject("report", "pilot", "inflight"));
  const pending = d.publish(report("inflight")).then(value => ({ value }), error => ({ error }));
  await until(() => proxy.observed, "actual report publish frame not observed");
  await until(async () => !!await b.core.reportStatus("pilot", "inflight"), "publish did not reach actual broker");
  proxy.cut(); const ambiguous = await pending; assert.ok(ambiguous.error, "reply must remain ambiguous while partitioned");
  assert.equal(first.reportStatus("pilot", "inflight").stage, "local-buffered"); first.close();
  proxy.restore(); await until(() => reconnected > 0, "established client failed to reconnect");
  const reopened = state(t, localDir), next = new Delivery(core, reopened, new Artifacts(nc));
  assert.equal((await next.reconcile())[0].stage, "broker-accepted");
  assert.equal(await countSubject(b.core, subject("report", "pilot", "inflight")), 1);
  await next.intake(x.owner, { message_id: "inflight", authority: authority(x.owner) });
  proxy.arm(subject("receipt", "pilot", "inflight", "processed"));
  const disposition = next.dispose(x.owner, { message_id: "inflight", authority: authority(x.owner), disposition: "done" }).then(value => ({ value }), error => ({ error }));
  await until(() => proxy.observed, "actual atomic receipt frame not observed");
  await until(async () => !!await b.core.receiptStatus("pilot", "inflight", "processed"), "atomic receipt did not commit");
  proxy.cut(); await disposition;
  const previousReconnects = reconnected; proxy.restore(); await until(() => reconnected > previousReconnects, "receipt client failed to reconnect");
  const confirmed = await next.dispose(x.owner, { message_id: "inflight", authority: authority(x.owner), disposition: "done" });
  assert.equal(confirmed.record.disposition, "done");
  assert.equal(await countSubject(b.core, subject("receipt", "pilot", "inflight", "processed")), 1);
  assert.equal(reopened.readInbox("pilot", "inflight").filter(r => r.stage === "processed").length, 1);
  assert.ok(disconnected >= 2); await retained(b, x);
});

test("SIGKILL actual broker and publisher then reopen preserves ledger, inbox and pending same-ID bytes", { timeout: 30000 }, async t => {
  const b = await Broker.create(t), x = await seed(t, b, join(b.dir, "local"));
  await x.d.publish(report("intakePending")); await x.d.intake(x.owner, { message_id: "intakePending", authority: authority(x.owner) });
  // A real child commits SQLite intent+bytes and dies before network I/O.
  const script = `import {LocalState} from ${JSON.stringify(new URL("../index.js", import.meta.url).href)}; const s=new LocalState(process.argv[1]);s.enqueue({role_id:'pilot',message_id:'restartPending',payload:'stable'},[{bytes:new Uint8Array([8,9,10])}]);process.kill(process.pid,'SIGKILL');`;
  const child = spawn(process.execPath, ["--input-type=module", "-e", script, join(b.dir, "publisher")]);
  let stderr = ""; child.stderr.on("data", d => stderr += d); t.after(() => stopChild(child));
  const [code, signal] = await once(child, "exit"); assert.equal(signal, "SIGKILL", `${code} ${stderr}`);
  await b.restart("SIGKILL"); await retained(b, x);
  const publisher = state(t, join(b.dir, "publisher")), inbox = state(t, join(b.dir, "local"));
  assert.equal(inbox.readInbox("pilot", "intakePending").length, 1);
  assert.equal((await new Delivery(b.core, publisher, new Artifacts(b.nc)).reconcile())[0].stage, "broker-accepted");
  const bytes = new Uint8Array([8,9,10]); assert.deepEqual(Buffer.from(await new Artifacts(b.nc).readArtifact(artifactReference(bytes))), Buffer.from(bytes));
  const next = new Delivery(b.core, inbox, new Artifacts(b.nc));
  await next.dispose(x.owner, { message_id: "intakePending", authority: authority(x.owner), disposition: "after-restart" });
  assert.equal(await countSubject(b.core, subject("receipt", "pilot", "intakePending", "processed")), 1);
});

test("report publication races handoff and late real consumer ack cannot remove successor intake", { timeout: 25000 }, async t => {
  const b = await Broker.create(t), owner = await b.core.createRole(role("pilot"));
  await b.core.publishReport({ ...report("delayed"), artifacts: [] });
  await b.manager.consumers.add("ADE_COORD_V1", { durable_name: "handoff_late", filter_subject: subject("report", "pilot", "delayed"), ack_policy: "explicit", deliver_policy: "all" });
  const consumer = await b.core.js.consumers.get("ADE_COORD_V1", "handoff_late"), message = await consumer.next({ expires: 1000 }); assert.ok(message);
  const [next] = await Promise.all([handoff(b.core, owner, { host: "h2", server: "s2", agent: "b" }), b.core.publishReport({ ...report("concurrent"), artifacts: [] })]);
  message.ack(); await b.nc.flush();
  const d = new Delivery(b.core, state(t, join(b.dir, "successor")), new Artifacts(b.nc));
  for (const id of ["delayed", "concurrent"]) {
    await d.intake(next, { message_id: id, authority: authority(next) });
    await d.dispose(next, { message_id: id, authority: authority(next), disposition: "successor" });
    assert.ok(await b.core.reportStatus("pilot", id));
    assert.equal(await countSubject(b.core, subject("receipt", "pilot", id, "processed")), 1);
  }
  await assert.rejects(b.core.commitReceipt(owner, { message_id: "concurrent", stage: "processed", disposition: "stale" }), { code: "STALE" });
});

test("actual older cold-store snapshot restore rejects restored authority against independent advanced generation", { timeout: 35000 }, async t => {
  const b = await Broker.create(t), x = await seed(t, b, join(b.dir, "local"));
  const backup = join(b.dir, "older-store"), highwater = join(b.dir, "independent-generation");
  await writeFile(highwater, "gen1", { flush: true });
  // Cold snapshot is copied only after actual broker shutdown; it is not an
  // online snapshot API or a power-loss durability claim.
  await b.closeClients(); await b.stop("SIGTERM"); await cp(b.store, backup, { recursive: true });
  await b.start(); await b.open();
  const advanced = await handoff(b.core, x.owner, { host: "h2", server: "s2", agent: "b" });
  await b.core.publishReport({ ...report("afterSnapshot"), artifacts: [] });
  await writeFile(highwater, "gen2", { flush: true });
  await b.closeClients(); await b.stop("SIGKILL"); await rm(b.store, { recursive: true }); await cp(backup, b.store, { recursive: true });
  await b.start(); await b.open();
  assert.equal(await b.core.reportStatus("pilot", "afterSnapshot"), null);
  assert.deepEqual(await b.core.getRole("pilot"), x.owner); assert.ok(advanced.record.ownership_epoch > x.owner.record.ownership_epoch);
  const generation = await readFile(highwater, "utf8"); assert.equal(generation, "gen2");
  const fenced = await Coordination.connect(b.nc, { generation });
  await assert.rejects(fenced.getRole("pilot"), { code: "GENERATION" });
  await assert.rejects(fenced.commitReceipt(x.owner, { message_id: "accepted", stage: "processed", disposition: "restored-stale" }), { code: "GENERATION" });
  await retained(b, x);
});
