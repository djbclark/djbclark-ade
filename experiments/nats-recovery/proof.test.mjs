import { test } from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, writeFile, rm, readFile, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { Coordination, LocalState, Delivery, Artifacts, streamConfig } from "../../lib/ade-coord/index.js";
const require = createRequire(new URL("../../lib/ade-coord/package.json", import.meta.url));
const { connect } = await import(require.resolve("@nats-io/transport-node"));
const { jetstreamManager } = await import(require.resolve("@nats-io/jetstream"));
const { Objm } = await import(require.resolve("@nats-io/obj"));
const tool = fileURLToPath(new URL("../../bin/ade-coord-backup", import.meta.url));
const token = "public-ci-fixture-not-a-secret-0123456789";
const generation = "recovery-proof-generation";

function command(args, env) {
  return new Promise((resolve, reject) => {
    const p = spawn("python3", [tool, ...args], { env: { ...process.env, ...env } });
    let out = "", err = "";
    p.stdout.on("data", b => out += b); p.stderr.on("data", b => err += b);
    p.on("error", reject); p.on("exit", code => resolve({ code, out, err }));
    p.stdin.end();
  });
}

async function broker(directory) {
  const config = join(directory, "server.conf");
  await writeFile(config, `host: 127.0.0.1\nport: -1\nauthorization { token: "${token}" }\njetstream { store_dir: "${directory}/store", sync_interval: always }\n`);
  const p = spawn(process.env.NATS_SERVER, ["-c", config]);
  const url = await new Promise((resolve, reject) => {
    let logs = "";
    const timer = setTimeout(() => { p.kill(); reject(new Error("broker readiness timeout")); }, 10000);
    p.on("error", e => { clearTimeout(timer); reject(e); });
    p.on("exit", code => { clearTimeout(timer); reject(new Error(`broker exited ${code}`)); });
    p.stderr.on("data", b => {
      logs += b;
      const m = logs.match(/Listening for client connections on (127\.0\.0\.1:\d+)/);
      if (m && logs.includes("Server is ready")) { clearTimeout(timer); resolve("nats://" + m[1]); }
    });
  });
  return { p, url };
}

test("network snapshots restore roles, reports, receipts and real artifacts in isolated broker", async () => {
  assert.equal(process.platform, "linux", "CI proof only; no Mac servers");
  const directory = await mkdtemp(join(tmpdir(), "ade-recovery-"));
  let source, target, nc, restored, state;
  try {
    const { mkdir } = await import("node:fs/promises");
    await mkdir(join(directory, "source")); await mkdir(join(directory, "target"));
    source = await broker(join(directory, "source")); target = await broker(join(directory, "target"));
    nc = await connect({ servers: source.url, token });
    await (await jetstreamManager(nc)).streams.add(streamConfig());
    await new Objm(nc).create("ADE_ARTIFACTS_V1", { storage: "file", ttl: 0 });
    const core = await Coordination.connect(nc, { generation });
    const snapshot = await core.createRole({ role_id: "lead", owner: { host: "host-a", server: "paseo-a", agent: "agent-a" },
      ownership_epoch: 1, generation, state: "active", bindings: [] });
    state = new LocalState(join(directory, "producer"));
    const delivery = new Delivery(core, state, new Artifacts(nc));
    await delivery.publish({ role_id: "lead", message_id: "recoverable", payload: { text: "durable report" } },
      { artifacts: [{ bytes: Buffer.from("artifact bytes across restore"), media_type: "text/plain" }] });
    await delivery.intake(snapshot, { message_id: "recoverable", authority: { owner: snapshot.record.owner,
      ownership_epoch: 1, generation, revision: snapshot.revision } });
    const original = await core.reportStatus("lead", "recoverable");
    const backup = join(directory, "offhost-backup");
    let result = await command(["create", backup, "--generation", generation], { ADE_NATS_URL: source.url, ADE_NATS_TOKEN: token });
    assert.equal(result.code, 0, result.out + result.err);
    assert.equal((await stat(backup)).mode & 0o777, 0o700);
    assert.ok(!(await readFile(join(backup, "ade-manifest.json"), "utf8")).includes(token));
    result = await command(["restore-isolated", backup, "--generation", generation, "--isolated-url", target.url],
      { ADE_NATS_URL: source.url, ADE_NATS_TOKEN: "wrong-production-token-must-not-be-used", ADE_NATS_RECOVERY_TOKEN: token });
    assert.equal(result.code, 0, result.out + result.err);
    assert.equal(JSON.parse(result.out).result.production_authority, false);
    restored = await connect({ servers: target.url, token });
    const recovered = await Coordination.connect(restored, { generation });
    assert.deepEqual(await recovered.getRole("lead"), snapshot);
    const report = await recovered.reportStatus("lead", "recoverable");
    assert.deepEqual(report, original);
    assert.ok(await recovered.receiptStatus("lead", "recoverable", "ADE-inbox-recorded"));
    assert.deepEqual(Buffer.from(await new Artifacts(restored).readArtifact(report.record.report.artifacts[0])), Buffer.from("artifact bytes across restore"));
    result = await command(["restore-isolated", backup, "--generation", generation, "--isolated-url", "nats://100.64.0.1:4222"], { ADE_NATS_RECOVERY_TOKEN: token });
    assert.equal(result.code, 1, "production/tailnet restore must be refused");
    result = await command(["verify", backup, "--generation", "older-generation"], {});
    assert.equal(result.code, 1, "independent generation mismatch must be refused");
    const manifest = JSON.parse(await readFile(join(backup, "ade-manifest.json"), "utf8"));
    const victim = Object.keys(manifest.files)[0];
    await writeFile(join(backup, victim), "tampered");
    result = await command(["verify", backup, "--generation", generation], {});
    assert.equal(result.code, 1, "snapshot corruption must be refused");
  } finally {
    state?.close(); await nc?.close(); await restored?.close();
    for (const server of [source, target]) if (server?.p.exitCode === null) {
      const exited = new Promise(resolve => server.p.once("exit", resolve)); server.p.kill("SIGTERM"); await exited;
    }
    await rm(directory, { recursive: true, force: true });
  }
});
