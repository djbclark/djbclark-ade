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

// Adversary finding 4: Paseo's own store is checked, read only.
function paseoAgent(w: World, id: string, body: Record<string, unknown>) {
  const d = path.join(w.paseo, "agents", "nonexistent");
  fs.mkdirSync(d, { recursive: true });
  fs.writeFileSync(path.join(d, `${id}.json`), JSON.stringify({ id, provider: "claude", cwd: "/nonexistent", ...body }));
}

async function cleanRepoRecord(w: World, id: string, over: Partial<RecoveryRecord> = {}) {
  const repo = tmp();
  git(repo, "init", "-q", "-b", "main");
  fs.writeFileSync(path.join(repo, "a.txt"), "1\n");
  git(repo, "add", "."); git(repo, "commit", "-q", "-m", "i");
  put(w, id, { cwd: repo, git: { latest: await gitEvidence(repo) }, ...over });
}

test("Paseo's stored record: archived there is do-not-resume (paseo-archived); newer is paseo-record-newer", async () => {
  const w = world();
  await cleanRepoRecord(w, "p1");
  const before = cli(w, "show", "p1", "--json");
  assert.equal(before.code, 0, before.out + before.err);
  assert.ok(JSON.parse(before.out).info.includes("paseo-record-unavailable"), "absent store: info only");
  const now = new Date().toISOString();
  paseoAgent(w, "p1", { updatedAt: now, archivedAt: now });
  const archived = cli(w, "show", "p1", "--json");
  assert.equal(archived.code, 2, archived.out + archived.err);
  const a = JSON.parse(archived.out);
  assert.ok(a.reasons.includes("paseo-archived"), a.reasons.join(","));
  assert.equal(a.paseoRecord.archivedAt, now);
  paseoAgent(w, "p1", { updatedAt: new Date(Date.now() + 60_000).toISOString(), archivedAt: null });
  const newer = cli(w, "show", "p1", "--json");
  assert.equal(newer.code, 1, newer.out);
  assert.deepEqual(JSON.parse(newer.out).reasons.sort(), ["interrupted:unobserved-activity", "paseo-record-newer", "tools-unobserved"]);
  assert.ok(JSON.parse(newer.out).interruptions.some((i: { evidence: string }) => i.evidence === "unobserved-activity"));
  // B2: a store-only change (attention clear, unread, rename, label, unarchive) moves updatedAt
  // but not lastActivityAt: not unobserved activity.
  paseoAgent(w, "p1", { updatedAt: new Date(Date.now() + 60_000).toISOString(), lastActivityAt: "2020-01-01T00:00:00.000Z", archivedAt: null });
  const storeOnly = cli(w, "show", "p1", "--json");
  assert.equal(storeOnly.code, 0, storeOnly.out);
  assert.equal(JSON.parse(storeOnly.out).paseoRecord.activitySource, "lastActivityAt");
  paseoAgent(w, "p1", { updatedAt: "2020-01-01T00:00:00.000Z", lastActivityAt: new Date(Date.now() + 60_000).toISOString(), archivedAt: null });
  const active = cli(w, "show", "p1", "--json");
  assert.equal(active.code, 1, active.out);
  assert.ok(JSON.parse(active.out).reasons.includes("paseo-record-newer"));
  paseoAgent(w, "p1", { updatedAt: "2020-01-01T00:00:00.000Z", archivedAt: null });
  const older = cli(w, "show", "p1", "--json");
  assert.equal(older.code, 0, older.out);
  assert.equal(JSON.parse(older.out).info.includes("paseo-record-unavailable"), false);
  fs.writeFileSync(path.join(w.paseo, "agents", "nonexistent", "p1.json"), "{corrupt");
  const corrupt = cli(w, "show", "p1", "--json");
  assert.equal(corrupt.code, 1, "upstream skips a corrupt record too: Paseo does not know the agent");
  assert.deepEqual(JSON.parse(corrupt.out).reasons, ["paseo-record-missing"]);
});

test("the daemon's server-id file: a mismatch is other-server, a match passes", async () => {
  const w = world();
  await cleanRepoRecord(w, "s1");
  fs.writeFileSync(path.join(w.paseo, "server-id"), "srv1\n");
  const ok = cli(w, "show", "s1", "--json");
  assert.equal(ok.code, 0, ok.out + ok.err);
  assert.equal(JSON.parse(ok.out).paseoServerId, "srv1");
  fs.writeFileSync(path.join(w.paseo, "server-id"), "srv_elsewhere\n");
  const bad = cli(w, "show", "s1", "--json");
  assert.equal(bad.code, 1);
  assert.deepEqual(JSON.parse(bad.out).reasons, ["other-server"]);
});

// Adversary finding 7: PASEO_HOME=~/... resolves as upstream does (the session-recovery state too).
test("PASEO_HOME with a leading ~ resolves against HOME, for the agents dir and session-recovery state", () => {
  const w = world();
  put(w, "t1");
  const env = { ...w.env, PASEO_HOME: "~/paseo" }; // HOME is w.base, and w.paseo is <base>/paseo
  paseoAgent(w, "t1", { updatedAt: new Date().toISOString(), archivedAt: new Date().toISOString() });
  const sr = path.join(w.paseo, "plugin-data", "session-recovery");
  fs.mkdirSync(sr, { recursive: true });
  fs.writeFileSync(path.join(sr, "state.json"), JSON.stringify({ records: { t1: { id: "t1", phase: "scheduled" } } }));
  const r = spawnSync(process.execPath, ["--disable-warning=ExperimentalWarning", CLI, "show", "t1", "--json", "--no-live"], { env, encoding: "utf8", timeout: 60000 });
  assert.equal(r.status, 2, r.stdout + r.stderr);
  const j = JSON.parse(r.stdout);
  assert.ok(j.reasons.includes("paseo-archived"));
  assert.equal(j.recoveryScheduledElsewhere, true);
});

// Adversary round 2, N3b: a readable agents dir without the agent's record blocks.
test("Paseo's agents dir readable but no <id>.json: needs-review, paseo-record-missing", async () => {
  const w = world();
  await cleanRepoRecord(w, "m1");
  fs.mkdirSync(path.join(w.paseo, "agents", "proj"), { recursive: true });
  const r = cli(w, "show", "m1", "--json");
  assert.equal(r.code, 1, r.out + r.err);
  const j = JSON.parse(r.out);
  assert.deepEqual(j.reasons, ["paseo-record-missing"]);
  assert.equal(j.paseoRecordMissing, true);
  assert.equal(j.info.includes("paseo-record-unavailable"), false);
  assert.match(cli(w, "show", "m1").out, /stored record missing/);
});

test("the record's own paseoHome wins over the shell's PASEO_HOME; a relative one is ignored", () => {
  const w = world();
  put(w, "h1", { paseoHome: w.paseo });
  paseoAgent(w, "h1", { updatedAt: new Date().toISOString(), archivedAt: new Date().toISOString() });
  const env = { ...w.env, PASEO_HOME: path.join(w.base, "some-other-home") };
  const run = () => spawnSync(process.execPath, ["--disable-warning=ExperimentalWarning", CLI, "show", "h1", "--json", "--no-live"], { env, encoding: "utf8", timeout: 60000 });
  const r = run();
  assert.equal(r.status, 2, r.stdout + r.stderr);
  const j = JSON.parse(r.stdout);
  assert.ok(j.reasons.includes("paseo-archived"));
  assert.equal(j.paseoHome, w.paseo);
  assert.equal(j.paseoHomeSource, "record");
  put(w, "h1", { paseoHome: "paseo" }); // relative: not trusted, the env's is used
  const r2 = run();
  const j2 = JSON.parse(r2.stdout);
  assert.equal(j2.paseoHomeSource, "env");
  assert.equal(j2.paseoHome, path.join(w.base, "some-other-home"));
  assert.equal(j2.reasons.includes("paseo-archived"), false);
});

// Adversary round 2, N4: session-recovery state is read through the bounded reader.
test("a FIFO as session-recovery state.json does not hang the CLI", () => {
  const w = world();
  put(w, "f1");
  const sr = path.join(w.paseo, "plugin-data", "session-recovery");
  fs.mkdirSync(sr, { recursive: true });
  execFileSync("mkfifo", [path.join(sr, "state.json")]);
  const r = spawnSync(process.execPath, ["--disable-warning=ExperimentalWarning", CLI, "show", "f1", "--json", "--no-live"], { env: w.env, encoding: "utf8", timeout: 15000 });
  assert.notEqual(r.status, null, "the CLI finished (no blocking read of a FIFO)");
  assert.equal(JSON.parse(r.stdout).recoveryScheduledElsewhere, null);
});
