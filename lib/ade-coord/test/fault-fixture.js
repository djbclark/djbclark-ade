// Linux-only actual subprocess/TCP fault machinery. No production endpoints.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer, createConnection } from "node:net";
import { mkdtemp, writeFile, rm, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { connect } from "@nats-io/transport-node";
import { jetstream, jetstreamManager } from "@nats-io/jetstream";
import { Objm } from "@nats-io/obj";
import { Coordination, streamConfig } from "../index.js";

export const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
export async function until(fn, message, timeout = 8000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await fn()) return; await sleep(30); }
  throw new Error(message);
}
export async function stopChild(child, signal = "SIGTERM") {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  const exit = once(child, "exit"); child.kill(signal);
  let timer;
  try { await Promise.race([exit, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`child ${child.pid} did not stop`)), 4000); })]); }
  catch (error) { child.kill("SIGKILL"); await exit; throw error; }
  finally { clearTimeout(timer); console.log("fault child reaped", child.pid, child.exitCode, child.signalCode); }
}
export class Broker {
  static async create(t, { parent = tmpdir(), provision = true, token } = {}) {
    assert.equal(process.platform, "linux", "fault conformance requires Linux");
    await mkdir(parent, { recursive: true });
    const b = new Broker(); b.dir = await mkdtemp(join(parent, "ade-fault-")); b.store = join(b.dir, "store"); b.token = token; b.clients = new Set(); b.logs = ""; b.port = -1;
    t.after(async () => { await b.closeClients(); await b.stop(); await rm(b.dir, { recursive: true, force: true }); });
    await b.start(); await b.open();
    if (provision) {
      await b.manager.streams.add({ ...streamConfig(), duplicate_window: 100000000 });
      await new Objm(b.nc).create("ADE_ARTIFACTS_V1", { storage: "file", ttl: 0 });
    }
    return b;
  }
  async start() {
    const config = join(this.dir, "server.conf");
    await writeFile(config, `host: 127.0.0.1\nport: ${this.port}\n${this.token ? `authorization { token: ${JSON.stringify(this.token)} }\n` : ""}jetstream { store_dir: "${this.store}", sync_interval: always }\n`);
    const child = spawn(process.env.NATS_SERVER ?? "nats-server", ["-c", config]); this.child = child;
    await new Promise((resolve, reject) => {
      let logs = "";
      const timer = setTimeout(() => reject(new Error(`broker startup timeout: ${logs}`)), 8000);
      const failed = () => { clearTimeout(timer); reject(new Error(`broker exited during startup: ${logs}`)); };
      child.once("error", reject); child.once("exit", failed);
      child.stderr.on("data", data => {
        const text = data.toString(); this.logs = (this.logs + text).slice(-64000); logs += text;
        const m = logs.match(/Listening for client connections on 127\.0\.0\.1:(\d+)/);
        if (m) { this.port = Number(m[1]); this.url = `nats://127.0.0.1:${this.port}`; clearTimeout(timer); child.removeListener("exit", failed); resolve(); }
      });
    });
    console.log("fault broker started", child.pid, this.url);
  }
  async connection(url = this.url) {
    const nc = await connect({ servers: url, token: this.token, timeout: 700, reconnectTimeWait: 50, maxReconnectAttempts: -1 });
    this.clients.add(nc); return nc;
  }
  async open() {
    this.nc = await this.connection(); this.manager = await jetstreamManager(this.nc, { timeout: 700 });
    this.core = await this.coordination(this.nc);
    console.log("fault server/client", this.nc.info.version, process.version);
  }
  async coordination(nc) {
    const core = await Coordination.connect(nc, { generation: "gen1" });
    core.manager = await jetstreamManager(nc, { timeout: 700 }); core.js = jetstream(nc, { timeout: 700 }); return core;
  }
  async closeClients() { await Promise.all([...this.clients].map(nc => nc.close())); this.clients.clear(); }
  async stop(signal) { await stopChild(this.child, signal); }
  async restart(signal = "SIGKILL") { await this.closeClients(); await this.stop(signal); await this.start(); await this.open(); }
}

/** Established actual TCP link; suppress only replies to the armed outbound
 * subject, then destroy both sockets. Other fixture clients bypass the proxy. */
export class FaultProxy {
  static async create(t, broker) {
    const p = new FaultProxy(); p.broker = broker; p.pairs = new Set(); p.available = true;
    p.server = createServer(down => {
      if (!p.available) { down.destroy(); return; }
      const up = createConnection({ host: "127.0.0.1", port: broker.port });
      const pair = { down, up, suppress: false }; p.pairs.add(pair);
      for (const socket of [down, up]) {
        socket.on("error", () => {});
        socket.on("close", () => { down.destroy(); up.destroy(); p.pairs.delete(pair); });
      }
      down.on("data", data => {
        // Subjects and header/payload frames may be split across TCP chunks.
        const scan = (pair.scan ?? "") + data.toString();
        pair.scan = scan.slice(-4096);
        if (p.target && scan.includes(`PUB ${p.target} `)) { pair.suppress = true; p.observed = true; }
        up.write(data);
      });
      up.on("data", data => { if (!pair.suppress) down.write(data); });
    });
    p.server.listen(0, "127.0.0.1"); await once(p.server, "listening"); p.url = `nats://127.0.0.1:${p.server.address().port}`;
    t.after(async () => { p.cut(); await new Promise(resolve => p.server.close(resolve)); }); return p;
  }
  arm(subject) { this.target = subject; this.observed = false; }
  cut() { this.available = false; for (const { down, up } of this.pairs) { down.destroy(); up.destroy(); } }
  restore() { this.target = null; this.available = true; }
}
export async function countSubject(core, subject) {
  const info = await core.manager.streams.info("ADE_COORD_V1"); let count = 0;
  for (let seq = info.state.first_seq; seq <= info.state.last_seq; seq++) {
    const m = await core.manager.streams.getMessage("ADE_COORD_V1", { seq }); if (m?.subject === subject) count++;
  }
  return count;
}
