import { test } from "node:test";
import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { execFileSync, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import type { RecoveryRecord, TurnRecord } from "./types.ts";
import { sealRecord } from "./record.ts";
import { hostIdentity } from "./host-identity.ts";
import { gitEvidence } from "./git-evidence.ts";

const CLI = path.join(path.dirname(fileURLToPath(import.meta.url)), "cli.ts");
const GITENV = { PATH: process.env.PATH ?? "", HOME: "/nonexistent-home", GIT_AUTHOR_NAME: "t", GIT_AUTHOR_EMAIL: "t@t", GIT_COMMITTER_NAME: "t", GIT_COMMITTER_EMAIL: "t@t" };
const git = (cwd: string, ...a: string[]) => execFileSync("git", a, { cwd, env: GITENV, encoding: "utf8" });
const tmp = () => fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "ade-cli-")));

interface World { base: string; paseo: string; dir: string; env: NodeJS.ProcessEnv }
function world(serverId = "srv1"): World {
  const base = tmp();
  const paseo = path.join(base, "paseo");
  const dir = path.join(base, "ade", serverId, "ade-recovery", "recovery", "v1");
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  fs.mkdirSync(paseo);
  return { base, paseo, dir, env: { PATH: process.env.PATH, HOME: base, ADE_STATE_ROOT: base, PASEO_HOME: paseo } };
}

const T0 = "2026-11-01T00:00:00.000Z";
function turn(over: Partial<TurnRecord> = {}): TurnRecord {
  return { turnKey: "d1:1", turnId: "t1", startedAt: T0, endedAt: "2026-11-01T00:01:00.000Z", outcome: { kind: "completed" }, duringShutdown: false, ...over };
}
function record(id: string, over: Partial<RecoveryRecord> = {}): Omit<RecoveryRecord, "integrity"> {
  const h = hostIdentity();
  const me = { pid: 2_000_000_000, start: "1" }; // no such process
  const { integrity: _i, ...rest } = {
    schema: "ade.recovery.passive/v1",
    generation: 1,
    writtenAt: new Date().toISOString(),
    integrity: { alg: "sha256", digest: "" },
    writer: { ...me, plugin: "ade-recovery", pluginVersion: "0.1.0", daemon: me, host: h.host, bootId: h.bootId },
    serverId: "srv1",
    paseoAgentId: id,
    provider: "claude",
    cwd: "/nonexistent",
    host: h.host,
    bootId: h.bootId,
    platform: h.platform,
    persistence: { provider: "claude", sessionId: "sess-" + id },
    state: "idle",
    daemonInstance: "d1",
    turns: [turn()],
    interruptions: [],
    ...over,
  } as RecoveryRecord;
  return rest;
}
function put(w: World, id: string, over: Partial<RecoveryRecord> = {}) {
  fs.writeFileSync(path.join(w.dir, `${id}.json`), JSON.stringify(sealRecord(record(id, over))), { mode: 0o600 });
}
function cli(w: World, ...args: string[]) {
  const r = spawnSync(process.execPath, ["--disable-warning=ExperimentalWarning", CLI, ...args], { env: w.env, encoding: "utf8", timeout: 60000 });
  return { code: r.status, out: r.stdout, err: r.stderr };
}
const listing = (d: string) => fs.readdirSync(d).sort().map((n) => `${n}:${fs.statSync(path.join(d, n)).mtimeMs}`);

test("help, usage errors", () => {
  const w = world();
  assert.equal(cli(w, "--help").code, 0);
  assert.match(cli(w, "-h").out, /usage: paseo-checkpoint/);
  assert.equal(cli(w).code, 64);
  assert.equal(cli(w, "bogus").code, 64);
  assert.equal(cli(w, "show").code, 64);
  assert.equal(cli(w, "show", "a", "b").code, 64);
  assert.equal(cli(w, "list", "--nope").code, 64);
  assert.equal(cli(w, "list", "--server-id", "../x").code, 64);
});

test("not found is exit 3", () => {
  const w = world();
  assert.equal(cli(w, "show", "ghost", "--no-live").code, 3);
});

test("archived record is do-not-resume (exit 2)", () => {
  const w = world();
  put(w, "a1", { state: "archived", archivedAt: T0 });
  const r = cli(w, "show", "a1", "--json", "--no-live");
  assert.equal(r.code, 2, r.err);
  assert.equal(JSON.parse(r.out).verdict, "do-not-resume");
});

test("clean turn without live git needs review (exit 1)", () => {
  const w = world();
  put(w, "a2");
  const r = cli(w, "show", "a2", "--json", "--no-live");
  assert.equal(r.code, 1, r.err);
  const j = JSON.parse(r.out);
  assert.equal(j.verdict, "needs-review");
  assert.ok(j.reasons.includes("git-evidence-missing"));
  assert.equal(j.agentId, "a2");
});

test("live git: matching tree is resumable-native, a changed tree needs review", async () => {
  const w = world();
  const repo = tmp();
  git(repo, "init", "-q", "-b", "main");
  fs.writeFileSync(path.join(repo, "a.txt"), "1\n");
  git(repo, "add", "."); git(repo, "commit", "-q", "-m", "i");
  const ev = await gitEvidence(repo);
  put(w, "a3", { cwd: repo, git: { latest: ev } });
  const ok = cli(w, "show", "a3", "--json");
  assert.equal(ok.code, 0, ok.out + ok.err);
  assert.equal(JSON.parse(ok.out).verdict, "resumable-native");
  fs.writeFileSync(path.join(repo, "a.txt"), "2\n");
  const bad = cli(w, "show", "a3", "--json");
  assert.equal(bad.code, 1);
  assert.ok(JSON.parse(bad.out).reasons.includes("dirty-tree-changed"));
});

test("turn in flight with a dead writer reports writer-dead (computed, not written)", () => {
  const w = world();
  put(w, "a4", { state: "turn-in-flight", turns: [turn({ endedAt: null, outcome: null })] });
  const before = listing(w.dir);
  const r = cli(w, "show", "a4", "--json", "--no-live");
  assert.equal(r.code, 1, r.err);
  const j = JSON.parse(r.out);
  assert.ok(j.interruptions.some((i: { evidence: string }) => i.evidence === "writer-dead"));
  assert.ok(j.reasons.includes("interrupted:writer-dead"), JSON.stringify(j.reasons));
  assert.deepEqual(listing(w.dir), before);
  const stored = JSON.parse(fs.readFileSync(path.join(w.dir, "a4.json"), "utf8"));
  assert.deepEqual(stored.interruptions, []);
});

test("session-recovery open record is reported read-only", () => {
  const w = world();
  put(w, "a5");
  const sr = path.join(w.paseo, "plugin-data", "session-recovery");
  fs.mkdirSync(sr, { recursive: true });
  const state = { version: 1, serverId: "srv1", lastBoot: "", records: { a5: { id: "a5", phase: "scheduled" } }, excluded: [], history: [] };
  fs.writeFileSync(path.join(sr, "state.json"), JSON.stringify(state));
  const r = cli(w, "show", "a5", "--json", "--no-live");
  assert.equal(JSON.parse(r.out).recoveryScheduledElsewhere, true);
  assert.ok(JSON.parse(r.out).reasons.includes("recovery-scheduled-elsewhere"));
  state.records.a5.phase = "done";
  fs.writeFileSync(path.join(sr, "state.json"), JSON.stringify(state));
  assert.equal(JSON.parse(cli(w, "show", "a5", "--json", "--no-live").out).recoveryScheduledElsewhere, false);
  fs.writeFileSync(path.join(sr, "state.json"), "{not json");
  assert.equal(JSON.parse(cli(w, "show", "a5", "--json", "--no-live").out).recoveryScheduledElsewhere, null);
});

test("list reads every server, --server-id narrows, human output works", () => {
  const w = world("srv1");
  put(w, "l1", { state: "archived", archivedAt: T0 });
  const dir2 = path.join(w.base, "ade", "srv2", "ade-recovery", "recovery", "v1");
  fs.mkdirSync(dir2, { recursive: true, mode: 0o700 });
  fs.writeFileSync(path.join(dir2, "l2.json"), JSON.stringify(sealRecord(record("l2", { serverId: "srv2" }))), { mode: 0o600 });
  const all = JSON.parse(cli(w, "list", "--json", "--no-live").out);
  assert.deepEqual(all.map((x: { agentId: string }) => x.agentId).sort(), ["l1", "l2"]);
  const one = JSON.parse(cli(w, "list", "--json", "--no-live", "--server-id", "srv2").out);
  assert.deepEqual(one.map((x: { agentId: string }) => x.agentId), ["l2"]);
  const human = cli(w, "list", "--no-live");
  assert.equal(human.code, 0);
  assert.match(human.out, /do-not-resume\s.*l1/);
  assert.equal(cli(world(), "list").code, 0);
});

test("a corrupt record is reported, never repaired", () => {
  const w = world();
  put(w, "c1");
  fs.writeFileSync(path.join(w.dir, "c1.json"), "{ truncated");
  const before = listing(w.dir);
  const r = cli(w, "show", "c1", "--json", "--no-live");
  assert.equal(r.code, 1, r.err);
  assert.ok(JSON.parse(r.out).reasons.some((x: string) => x.startsWith("corrupt-")));
  assert.deepEqual(listing(w.dir), before);
});
