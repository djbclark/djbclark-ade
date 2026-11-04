import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { lookupPaseoAgentRecord, paseoHome, paseoServerId, readPaseoAgentRecord, readSmallFile, validRecordedPaseoHome } from "./paseo-home.ts";
import { paseoHome as fromIndex } from "../index.server.ts";

const tmp = () => fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "ade-paseo-home-")));

// Adversary finding 7: one resolver, copying upstream resolvePaseoHome().
test("paseoHome copies upstream: default, ~ expansion, relative against the cwd, absolute as is", () => {
  const o = { homedir: "/home/u", cwd: "/work/dir" };
  assert.equal(paseoHome({}, o), "/home/u/.paseo");
  assert.equal(paseoHome({ PASEO_HOME: "~/.paseo-dev" }, o), "/home/u/.paseo-dev");
  assert.equal(paseoHome({ PASEO_HOME: "~" }, o), "/home/u");
  assert.equal(paseoHome({ PASEO_HOME: "rel/p" }, o), "/work/dir/rel/p");
  assert.equal(paseoHome({ PASEO_HOME: "/abs/p/../q" }, o), "/abs/q");
  assert.equal(paseoHome({ PASEO_HOME: "~user/x" }, o), "/work/dir/~user/x", "only ~ and ~/ expand upstream");
  assert.equal(paseoHome({ PASEO_HOME: "" }, o), "/work/dir", "upstream uses ??: empty resolves to the cwd");
  assert.equal(paseoHome({ PASEO_HOME: "rel" }), path.resolve("rel"));
  assert.equal(paseoHome({}), path.join(os.homedir(), ".paseo"));
});

test("index.server.ts shutdown detection uses the same resolver", () => {
  const env = { PASEO_HOME: "~/.paseo-dev" };
  assert.equal(fromIndex(env), paseoHome(env));
  assert.equal(fromIndex(env), path.join(os.homedir(), ".paseo-dev"));
});

test("paseoServerId: PASEO_SERVER_ID override, else the server-id file; null when absent or unsafe", () => {
  const home = tmp();
  assert.equal(paseoServerId(home, {}), null);
  fs.writeFileSync(path.join(home, "server-id"), "srv_abcDEF123-_\n");
  assert.equal(paseoServerId(home, {}), "srv_abcDEF123-_");
  assert.equal(paseoServerId(home, { PASEO_SERVER_ID: "  srv_override \n" }), "srv_override");
  assert.equal(paseoServerId(home, { PASEO_SERVER_ID: "   " }), "srv_abcDEF123-_", "blank override is ignored, as upstream");
  assert.equal(paseoServerId(home, { PASEO_SERVER_ID: "../x" }), null);
  fs.writeFileSync(path.join(home, "server-id"), "\n");
  assert.equal(paseoServerId(home, {}), null);
  fs.rmSync(path.join(home, "server-id"));
  fs.mkdirSync(path.join(home, "server-id"));
  assert.equal(paseoServerId(home, {}), null, "a directory is not read");
});

function agentFile(home: string, dir: string | null, id: string, body: unknown): string {
  const d = dir === null ? path.join(home, "agents") : path.join(home, "agents", dir);
  fs.mkdirSync(d, { recursive: true });
  const f = path.join(d, `${id}.json`);
  fs.writeFileSync(f, typeof body === "string" ? body : JSON.stringify(body));
  return f;
}

test("readPaseoAgentRecord: archivedAt and updatedAt from <home>/agents/*/<id>.json", () => {
  const home = tmp();
  assert.equal(readPaseoAgentRecord(home, "a1"), null, "no agents dir");
  agentFile(home, "work-repo", "a1", { id: "a1", updatedAt: "2026-11-04T10:00:00.000Z", archivedAt: null });
  assert.deepEqual(readPaseoAgentRecord(home, "a1"), { archivedAt: null, updatedAt: "2026-11-04T10:00:00.000Z", updatedAtSource: "updatedAt" });
  agentFile(home, "work-repo", "a1", { id: "a1", updatedAt: "2026-11-04T11:00:00.000Z", archivedAt: "2026-11-04T11:00:00.000Z" });
  assert.equal(readPaseoAgentRecord(home, "a1")?.archivedAt, "2026-11-04T11:00:00.000Z");
  assert.equal(readPaseoAgentRecord(home, "nobody"), null);
  assert.equal(readPaseoAgentRecord(home, "../a1"), null, "an unsafe id is never a path");
});

test("readPaseoAgentRecord tolerates corruption, a wrong id, an unparseable updatedAt (mtime) and a FIFO", () => {
  const home = tmp();
  agentFile(home, "p", "bad", "{not json");
  assert.equal(readPaseoAgentRecord(home, "bad"), null);
  agentFile(home, "p", "other", { id: "someone-else", updatedAt: "2026-11-04T10:00:00.000Z" });
  assert.equal(readPaseoAgentRecord(home, "other"), null);
  const f = agentFile(home, "p", "nots", { id: "nots", updatedAt: "yesterday-ish" });
  const r = readPaseoAgentRecord(home, "nots");
  assert.equal(r?.updatedAtSource, "mtime");
  assert.equal(r?.updatedAt, fs.statSync(f).mtime.toISOString());
  if (process.platform !== "win32") {
    fs.mkdirSync(path.join(home, "agents", "q"), { recursive: true });
    execFileSync("mkfifo", [path.join(home, "agents", "q", "fifo.json")]);
    assert.equal(readPaseoAgentRecord(home, "fifo"), null, "a FIFO is not opened for a blocking read");
  }
});

test("readPaseoAgentRecord: legacy root record, and several copies (newest wins, any archive counts)", () => {
  const home = tmp();
  agentFile(home, null, "a1", { id: "a1", updatedAt: "2026-11-04T09:00:00.000Z", archivedAt: "2026-11-04T09:00:00.000Z" });
  assert.equal(readPaseoAgentRecord(home, "a1")?.archivedAt, "2026-11-04T09:00:00.000Z");
  agentFile(home, "moved", "a1", { id: "a1", updatedAt: "2026-11-04T12:00:00.000Z" });
  const r = readPaseoAgentRecord(home, "a1");
  assert.equal(r?.updatedAt, "2026-11-04T12:00:00.000Z");
  assert.equal(r?.archivedAt, "2026-11-04T09:00:00.000Z", "fail closed: an archived copy marks it archived");
});

// Adversary round 2, N6c: skip what upstream scanDisk skips (a symlinked .json, a record failing
// the schema); N3b: missing is told apart from unavailable.
test("readPaseoAgentRecord skips a symlinked .json and records failing the minimal shape check", () => {
  const home = tmp();
  const real = path.join(home, "elsewhere.json");
  fs.writeFileSync(real, JSON.stringify({ id: "s1", updatedAt: "2026-11-04T10:00:00.000Z" }));
  fs.mkdirSync(path.join(home, "agents", "p"), { recursive: true });
  fs.symlinkSync(real, path.join(home, "agents", "p", "s1.json"));
  assert.equal(readPaseoAgentRecord(home, "s1"), null, "a symlink is not a regular file to upstream");
  assert.deepEqual(lookupPaseoAgentRecord(home, "s1"), { status: "missing" });
  agentFile(home, "p", "noupd", { id: "noupd" });
  assert.deepEqual(lookupPaseoAgentRecord(home, "noupd"), { status: "missing" }, "updatedAt is required upstream");
  agentFile(home, "p", "numid", { id: 7, updatedAt: "2026-11-04T10:00:00.000Z" });
  assert.equal(readPaseoAgentRecord(home, "numid"), null);
  agentFile(home, "p", "badarch", { id: "badarch", updatedAt: "2026-11-04T10:00:00.000Z", archivedAt: 5 });
  assert.equal(readPaseoAgentRecord(home, "badarch"), null, "an ill-typed archivedAt fails upstream's schema");
  // A valid copy elsewhere still wins over the skipped ones.
  agentFile(home, "q", "s1", { id: "s1", updatedAt: "2026-11-04T11:00:00.000Z" });
  assert.equal(readPaseoAgentRecord(home, "s1")?.updatedAt, "2026-11-04T11:00:00.000Z");
});

test("lookupPaseoAgentRecord: unavailable without a readable agents dir, missing when the dir has no record", () => {
  const home = tmp();
  assert.deepEqual(lookupPaseoAgentRecord(home, "a1"), { status: "unavailable" });
  assert.deepEqual(lookupPaseoAgentRecord(home, "../a1"), { status: "unavailable" });
  fs.mkdirSync(path.join(home, "agents", "proj"), { recursive: true });
  assert.deepEqual(lookupPaseoAgentRecord(home, "a1"), { status: "missing" });
  agentFile(home, "proj", "a1", { id: "a1", updatedAt: "2026-11-04T10:00:00.000Z" });
  assert.equal(lookupPaseoAgentRecord(home, "a1").status, "found");
  fs.rmSync(path.join(home, "agents", "proj", "a1.json")); // upstream remove() unlinks it
  assert.deepEqual(lookupPaseoAgentRecord(home, "a1"), { status: "missing" });
  fs.rmSync(path.join(home, "agents"), { recursive: true });
  fs.writeFileSync(path.join(home, "agents"), "not a dir");
  assert.deepEqual(lookupPaseoAgentRecord(home, "a1"), { status: "unavailable" });
});

test("validRecordedPaseoHome accepts only an absolute path; readSmallFile refuses FIFOs and caps size", () => {
  assert.equal(validRecordedPaseoHome("/home/u/.paseo"), "/home/u/.paseo");
  assert.equal(validRecordedPaseoHome("/home/u/../v/.paseo"), "/home/v/.paseo");
  for (const bad of ["rel/p", "~/.paseo", "", 7, null, undefined, "/a\0b", "/" + "x".repeat(5000)]) {
    assert.equal(validRecordedPaseoHome(bad), null, String(bad));
  }
  const d = tmp();
  fs.writeFileSync(path.join(d, "big"), "x".repeat(100));
  assert.equal(readSmallFile(path.join(d, "big"), 99), null);
  assert.equal(readSmallFile(path.join(d, "big"), 100)?.length, 100);
  if (process.platform !== "win32") {
    execFileSync("mkfifo", [path.join(d, "fifo")]);
    assert.equal(readSmallFile(path.join(d, "fifo"), 100), null);
    fs.symlinkSync(path.join(d, "big"), path.join(d, "link"));
    assert.equal(readSmallFile(path.join(d, "link"), 100, { noFollow: true }), null);
    assert.equal(readSmallFile(path.join(d, "link"), 100)?.length, 100);
  }
});
