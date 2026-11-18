import { DatabaseSync } from "node:sqlite";
import { mkdirSync, chmodSync, lstatSync, existsSync, openSync, closeSync } from "node:fs";
import { join, resolve } from "node:path";
import { homedir } from "node:os";
import { createHash } from "node:crypto";
import { Objm } from "@nats-io/obj";
import { CoordError, canonicalJSON, digest, safeToken } from "./index.js";
const BUCKET = "ADE_ARTIFACTS_V1";
const hashBytes = bytes => createHash("sha256").update(bytes).digest("hex");
export function artifactReference(bytes, media_type = "application/octet-stream") {
  if (!(bytes instanceof Uint8Array) || typeof media_type !== "string" || !media_type || media_type.length > 256) throw new CoordError("INVALID", "Invalid artifact bytes or media type");
  const sha256 = hashBytes(bytes);
  return { sha256, size: bytes.length, media_type, reference: { kind: "nats-object", bucket: BUCKET, name: sha256 } };
}
function privatePath(path, directory = false) {
  const stat = lstatSync(path);
  if (stat.isSymbolicLink() || (directory ? !stat.isDirectory() : !stat.isFile())) throw new CoordError("INVALID", "State path must be a real private file or directory");
  chmodSync(path, directory ? 0o700 : 0o600);
}
/** Synchronous short transactions; never hold a SQLite writer lock across await. */
export class LocalState {
  constructor(stateDir = join(homedir(), ".local", "state", "ade-coord")) {
    this.dir = resolve(stateDir); mkdirSync(this.dir, { recursive: true, mode: 0o700 }); privatePath(this.dir, true);
    const file = join(this.dir, "coord.sqlite");
    if (!existsSync(file)) { try { const fd = openSync(file, "wx", 0o600); closeSync(fd); } catch (e) { if (e.code !== "EEXIST") throw e; } }
    privatePath(file);
    for (const suffix of ["-wal", "-shm"]) if (existsSync(file + suffix)) privatePath(file + suffix);
    this.db = new DatabaseSync(file);
    this.db.exec(`PRAGMA busy_timeout=10000; PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
      CREATE TABLE IF NOT EXISTS outbox(role TEXT, id TEXT, intent TEXT NOT NULL, digest TEXT NOT NULL, stage TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, error TEXT, PRIMARY KEY(role,id));
      CREATE TABLE IF NOT EXISTS blobs(digest TEXT PRIMARY KEY, bytes BLOB NOT NULL);
      CREATE TABLE IF NOT EXISTS intake(role TEXT, id TEXT, stage TEXT, record TEXT NOT NULL, PRIMARY KEY(role,id,stage));
      CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY, intent TEXT NOT NULL, digest TEXT NOT NULL, state TEXT NOT NULL, result TEXT);
      CREATE TABLE IF NOT EXISTS disposition_intents(role TEXT, id TEXT, authority TEXT, disposition TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY(role,id,authority));`);
    // Parent versions labelled uncommitted local intent processed. Preserve it as
    // abandoned evidence; only an actual broker receipt can confirm processing.
    this.transaction(() => {
      const version = this.db.prepare("PRAGMA user_version").get().user_version;
      if (version === 0) {
        this.db.exec(`INSERT OR IGNORE INTO disposition_intents SELECT role,id,'legacy-unconfirmed',record,'abandoned' FROM intake WHERE stage='processed'; DELETE FROM intake WHERE stage='processed'; PRAGMA user_version=1;`);
      } else if (version !== 1) throw new CoordError("UNSUPPORTED", "Unsupported local state schema");
    });
  }
  transaction(fn) { this.db.exec("BEGIN IMMEDIATE"); try { const value = fn(); this.db.exec("COMMIT"); return value; } catch (e) { this.db.exec("ROLLBACK"); throw e; } }
  enqueue(report, artifacts = []) {
    safeToken(report.role_id); safeToken(report.message_id);
    if (report.artifacts?.length) throw new CoordError("INVALID", "Provide artifact bytes, not unverified artifact references");
    const refs = artifacts.map(a => artifactReference(a.bytes, a.media_type));
    const intent = { ...report, artifacts: refs }; const text = canonicalJSON(intent), sha = digest(intent);
    return this.transaction(() => {
      const old = this.reportStatus(report.role_id, report.message_id);
      if (old && old.digest !== sha) throw new CoordError("IMMUTABLE", "Message ID already has different intent");
      for (let i = 0; i < refs.length; i++) this.db.prepare("INSERT OR IGNORE INTO blobs VALUES (?,?)").run(refs[i].sha256, artifacts[i].bytes);
      this.db.prepare("INSERT OR IGNORE INTO outbox(role,id,intent,digest,stage) VALUES (?,?,?,?,?)").run(report.role_id, report.message_id, text, sha, "local-buffered");
      return this.reportStatus(report.role_id, report.message_id);
    });
  }
  reportStatus(role, id) { return this.db.prepare("SELECT * FROM outbox WHERE role=? AND id=?").get(safeToken(role), safeToken(id)) ?? null; }
  outbox() { return this.db.prepare("SELECT * FROM outbox ORDER BY role,id").all(); }
  attempt(role, id) { this.db.prepare("UPDATE outbox SET attempts=attempts+1 WHERE role=? AND id=?").run(role, id); }
  accepted(role, id) { this.db.prepare("UPDATE outbox SET stage='broker-accepted',error=NULL WHERE role=? AND id=?").run(role, id); }
  failed(role, id, code) { this.db.prepare("UPDATE outbox SET error=? WHERE role=? AND id=?").run(code, role, id); }
  blob(sha) { const row = this.db.prepare("SELECT bytes FROM blobs WHERE digest=?").get(sha); if (!row) throw new CoordError("UNKNOWN", "Persisted artifact unavailable"); return new Uint8Array(row.bytes); }
  recordIntake(role, id, stage, record) {
    return this.transaction(() => {
      const text = canonicalJSON(record);
      const old = this.db.prepare("SELECT record FROM intake WHERE role=? AND id=? AND stage=?").get(role, id, stage);
      if (old && old.record !== text) throw new CoordError("IMMUTABLE", "Disposition already recorded differently");
      this.db.prepare("INSERT OR IGNORE INTO intake VALUES (?,?,?,?)").run(role, id, stage, text);
      return JSON.parse(old?.record ?? text);
    });
  }
  beginDisposition(snapshot, id, disposition) {
    const role = snapshot.record.role_id;
    const authority = canonicalJSON({ owner: snapshot.record.owner, epoch: snapshot.record.ownership_epoch, generation: snapshot.record.generation, revision: snapshot.revision });
    const text = canonicalJSON(disposition);
    return this.transaction(() => {
      const old = this.db.prepare("SELECT disposition FROM disposition_intents WHERE role=? AND id=? AND authority=?").get(role, id, authority);
      if (old && old.disposition !== text) throw new CoordError("IMMUTABLE", "Authority already has different pending disposition");
      this.db.prepare("UPDATE disposition_intents SET status='abandoned' WHERE role=? AND id=? AND authority!=? AND status='pending'").run(role, id, authority);
      this.db.prepare("INSERT OR IGNORE INTO disposition_intents VALUES (?,?,?,?,'pending')").run(role, id, authority, text);
    });
  }
  confirmDisposition(role, id, receipt) {
    return this.transaction(() => {
      const authority = canonicalJSON({ owner: receipt.record.owner, epoch: receipt.record.ownership_epoch, generation: receipt.record.generation, revision: receipt.record.role_revision });
      this.db.prepare("UPDATE disposition_intents SET status=CASE WHEN disposition=? AND authority=? THEN 'confirmed' ELSE 'abandoned' END WHERE role=? AND id=?").run(canonicalJSON(receipt.record.disposition), authority, role, id);
      const text = canonicalJSON(receipt);
      const old = this.db.prepare("SELECT record FROM intake WHERE role=? AND id=? AND stage='processed'").get(role, id);
      if (old && old.record !== text) throw new CoordError("IMMUTABLE", "Confirmed local receipt conflicts with broker");
      this.db.prepare("INSERT OR IGNORE INTO intake VALUES (?,?,'processed',?)").run(role, id, text);
      return receipt;
    });
  }
  dispositions(role, id) { return this.db.prepare("SELECT * FROM disposition_intents WHERE role=? AND id=? ORDER BY authority").all(safeToken(role), safeToken(id)); }
  readInbox(role, id) { return this.db.prepare("SELECT stage,record FROM intake WHERE role=? AND id=? ORDER BY stage").all(safeToken(role), safeToken(id)).map(r => ({ stage: r.stage, record: JSON.parse(r.record) })); }
  operationIntent(id, intent) {
    safeToken(id); const text = canonicalJSON(intent), sha = digest(intent);
    return this.transaction(() => {
      const old = this.operationInspect(id);
      if (old && old.digest !== sha) throw new CoordError("IMMUTABLE", "Operation ID already has different intent");
      // UNKNOWN from the instant an intent can escape: never infer safe retry from age.
      this.db.prepare("INSERT OR IGNORE INTO operations VALUES (?,?,?,'UNKNOWN',NULL)").run(id, text, sha);
      return this.operationInspect(id);
    });
  }
  operationInspect(id) { return this.db.prepare("SELECT * FROM operations WHERE id=?").get(safeToken(id)) ?? null; }
  operationReconcile(id, { state, result, evidence }) {
    if (!["SUCCEEDED", "NOT_APPLIED"].includes(state) || !evidence) throw new CoordError("INVALID", "Endpoint reconciliation evidence required");
    return this.transaction(() => {
      const old = this.operationInspect(id); if (!old) throw new CoordError("INVALID", "Operation intent missing");
      const text = canonicalJSON({ result, evidence });
      if (old.state !== "UNKNOWN" && (old.state !== state || old.result !== text)) throw new CoordError("IMMUTABLE", "Operation already reconciled differently");
      this.db.prepare("UPDATE operations SET state=?,result=? WHERE id=?").run(state, text, id);
      return this.operationInspect(id);
    });
  }
  close() { this.db.close(); }
}
export class Artifacts {
  constructor(nc) { this.manager = new Objm(nc); }
  async store() { return this.manager.open(BUCKET); } // Provisioning is an explicit deployment action.
  async upload(bytes, media_type) {
    const ref = artifactReference(bytes, media_type), store = await this.store();
    const old = await store.getBlob(ref.reference.name);
    if (!old) await store.putBlob({ name: ref.reference.name }, bytes);
    await this.readArtifact(ref); // Do not publish before actual retrievability + digest proof.
    return ref;
  }
  async readArtifact(ref) {
    if (ref?.reference?.kind !== "nats-object" || ref.reference.bucket !== BUCKET || ref.reference.name !== ref.sha256 || !/^[a-f0-9]{64}$/.test(ref.sha256) || !Number.isSafeInteger(ref.size) || ref.size < 0) throw new CoordError("INVALID", "Invalid retrievable artifact reference");
    const bytes = await (await this.store()).getBlob(ref.reference.name);
    if (!bytes || bytes.length !== ref.size || hashBytes(bytes) !== ref.sha256) throw new CoordError("UNKNOWN", "Artifact missing or digest mismatch");
    return bytes;
  }
}
export class Delivery {
  constructor(core, state, artifacts) { this.core = core; this.state = state; this.artifacts = artifacts; }
  async publish(report, { artifacts = [] } = {}) {
    const row = this.state.enqueue(report, artifacts); // Durable transaction before *any* network call.
    return this.flush(row);
  }
  async flush(row) {
    const report = JSON.parse(row.intent); this.state.attempt(row.role, row.id);
    try {
      const found = await this.core.reportStatus(row.role, row.id);
      if (found) {
        if (found.record.digest !== row.digest) throw new CoordError("IMMUTABLE", "Broker report conflicts with persisted intent");
        await this.ensureArtifacts(report);
        this.state.accepted(row.role, row.id); return found;
      }
      await this.ensureArtifacts(report);
      const result = await this.core.publishReport(report);
      this.state.accepted(row.role, row.id); return result;
    } catch (err) { this.state.failed(row.role, row.id, err instanceof CoordError ? err.code : "UNKNOWN"); throw err; }
  }
  async ensureArtifacts(report) {
    for (const ref of report.artifacts) {
      const bytes = this.state.blob(ref.sha256);
      if (hashBytes(bytes) !== ref.sha256) throw new CoordError("IMMUTABLE", "Local artifact digest mismatch");
      // upload repairs only absent objects; existing corrupt content is surfaced
      // by read-back verification, never overwritten silently.
      await this.artifacts.upload(bytes, ref.media_type);
    }
  }
  async reconcile() {
    const results = [];
    for (const row of this.state.outbox()) {
      if (row.stage === "broker-accepted") continue;
      try { await this.flush(row); results.push({ role_id: row.role, message_id: row.id, stage: "broker-accepted" }); }
      catch (e) { results.push({ role_id: row.role, message_id: row.id, error: e instanceof CoordError ? e.code : "UNKNOWN" }); }
    }
    return results;
  }
  async authority(snapshot, authority) {
    if (snapshot.record.state !== "active") throw new CoordError("STALE", "Intake and disposition require active authority");
    const expected = { owner: snapshot.record.owner, ownership_epoch: snapshot.record.ownership_epoch, generation: snapshot.record.generation, revision: snapshot.revision };
    if (digest(authority) !== digest(expected)) throw new CoordError("STALE", "Current authority token required");
    const current = await this.core.getRole(snapshot.record.role_id);
    if (!current || current.revision !== snapshot.revision || digest(current.record) !== digest(snapshot.record)) throw new CoordError("STALE", "Authority changed");
  }
  async intake(snapshot, { message_id, authority }) {
    await this.authority(snapshot, authority);
    const report = await this.core.reportStatus(snapshot.record.role_id, message_id);
    if (!report) throw new CoordError("INVALID", "Report not found");
    for (const ref of report.record.report.artifacts ?? []) await this.artifacts.readArtifact(ref);
    this.state.recordIntake(snapshot.record.role_id, message_id, "ADE-inbox-recorded", report);
    const previous = await this.core.receiptStatus(snapshot.record.role_id, message_id, "ADE-inbox-recorded");
    return previous ?? this.core.commitReceipt(snapshot, { message_id, stage: "ADE-inbox-recorded", disposition: "recorded" });
  }
  async dispose(snapshot, { message_id, authority, disposition }) {
    await this.intake(snapshot, { message_id, authority });
    const role = snapshot.record.role_id;
    const previous = await this.core.receiptStatus(role, message_id, "processed");
    if (previous) {
      this.state.confirmDisposition(role, message_id, previous);
      if (digest(previous.record.disposition) !== digest(disposition)) throw new CoordError("IMMUTABLE", "Disposition already committed differently");
      return previous;
    }
    this.state.beginDisposition(snapshot, message_id, disposition);
    try {
      const receipt = await this.core.commitReceipt(snapshot, { message_id, stage: "processed", disposition });
      return this.state.confirmDisposition(role, message_id, receipt);
    } catch (error) {
      const committed = await this.core.receiptStatus(role, message_id, "processed");
      if (committed) {
        this.state.confirmDisposition(role, message_id, committed);
        if (digest(committed.record.disposition) === digest(disposition)) return committed;
      }
      throw error;
    }
  }
  readInbox(role, id) { return this.state.readInbox(role, id); }
}
