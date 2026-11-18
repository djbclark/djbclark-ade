import { createHash, randomUUID } from "node:crypto";
import { headers } from "@nats-io/nats-core";
import { jetstream, jetstreamManager } from "@nats-io/jetstream";

export class CoordError extends Error {
  constructor(code, message, cause) { super(message, { cause }); this.name = "CoordError"; this.code = code; }
}
export function safeToken(value) {
  if (typeof value !== "string" || !/^[A-Za-z0-9_-]{1,128}$/.test(value)) throw new CoordError("INVALID", "Expected opaque safe subject token");
  return value;
}
export function subject(kind, role, message, stage) {
  if (!["role", "report", "receipt", "guard"].includes(kind)) throw new CoordError("INVALID", "Unknown subject kind");
  const parts = ["ade", "v1", kind, safeToken(role)];
  if (kind !== "role") parts.push(safeToken(message));
  if (kind === "receipt") parts.push(safeToken(stage));
  return parts.join(".");
}
function canonical(value) {
  if (value === null || typeof value === "boolean" || typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number" && Number.isFinite(value)) return JSON.stringify(value);
  if (Array.isArray(value)) {
    for (let i = 0; i < value.length; i++) if (!Object.hasOwn(value, i)) throw new CoordError("INVALID", "Sparse arrays are not JSON values");
    return "[" + value.map(canonical).join(",") + "]";
  }
  if (value && Object.getPrototypeOf(value) === Object.prototype) return "{" + Object.keys(value).sort().map(k => JSON.stringify(k) + ":" + canonical(value[k])).join(",") + "}";
  throw new CoordError("INVALID", "Only finite JSON values are supported");
}
const encode = value => new TextEncoder().encode(canonical(value));
export const digest = value => createHash("sha256").update(encode(value)).digest("hex");
export const streamConfig = () => ({ name: "ADE_COORD_V1", subjects: ["ade.v1.>"], storage: "file", retention: "limits", discard: "new", max_age: 0, max_msgs: 1000000, max_bytes: 1073741824, max_msgs_per_subject: -1, allow_atomic: true, allow_direct: false, deny_delete: true, deny_purge: true });
const STREAM = "ADE_COORD_V1";
const STAGES = ["ADE-inbox-recorded", "processed"];
function owner(value) { for (const k of ["host", "server", "agent"]) safeToken(value?.[k]); return value; }
function revision(value) { if (!Number.isSafeInteger(value) || value < 1) throw new CoordError("INVALID", "Invalid role revision"); }
function failure(err) {
  if (err instanceof CoordError) return err;
  const code = err?.api_error?.err_code;
  return new CoordError(code === 10071 ? "CONFLICT" : "UNKNOWN", "Coordination publish failed; reconcile stable id before retry", err);
}

/** generation must come from independently retained, reconciled authority evidence.
 * This library cannot detect a restored broker without that external high-water input. */
export class Coordination {
  constructor(nc, manager, generation) { this.nc = nc; this.manager = manager; this.js = jetstream(nc); this.generation = safeToken(generation); }
  static async connect(nc, { generation }) { return new Coordination(nc, await jetstreamManager(nc), generation); }
  async doctor() {
    const { config } = await this.manager.streams.info(STREAM);
    if (config.retention !== "limits" || config.discard !== "new" || config.storage !== "file" || config.max_age !== 0 || !config.allow_atomic || config.max_msgs_per_subject !== -1 || !config.deny_delete || !config.deny_purge) throw new CoordError("UNSUPPORTED", "Unsafe coordination stream configuration");
    return { stream: STREAM, server: this.nc.info?.version, generation: this.generation, persistence: "server sync_interval=always must be verified by deployment" };
  }
  async read(subj) {
    try {
      // STREAM.MSG.GET is served by the leader; never use direct/follower reads.
      const m = await this.manager.streams.getMessage(STREAM, { last_by_subj: subj });
      if (m === null) return null; // Current nats.js returns null for absent subjects.
      return { record: JSON.parse(new TextDecoder().decode(m.data)), revision: m.seq };
    } catch (e) { if (e?.api_error?.err_code === 10037) return null; throw e; }
  }
  async getRole(role) { const s = await this.read(subject("role", role)); if (s && s.record.generation !== this.generation) throw new CoordError("GENERATION", "Role generation differs from reconciled authority"); return s; }
  async createRole(record) {
    safeToken(record.role_id); owner(record.owner);
    if (record.generation !== this.generation || record.ownership_epoch !== 1 || record.state !== "active") throw new CoordError("INVALID", "New role requires current generation, epoch 1, active state");
    try { const ack = await this.js.publish(subject("role", record.role_id), encode(record), { expect: { lastSubjectSequence: 0 } }); return { record, revision: ack.seq }; } catch (e) { throw failure(e); }
  }
  async assertSnapshot(snapshot) {
    revision(snapshot.revision);
    if (snapshot.record.generation !== this.generation) throw new CoordError("GENERATION", "Stale generation");
    const current = await this.getRole(snapshot.record.role_id);
    if (!current || current.revision !== snapshot.revision || digest(current.record) !== digest(snapshot.record)) throw new CoordError("STALE", "Role snapshot differs from current authority");
  }
  async transitionRole(snapshot, { state, quiescence, checkpoint_digest }) {
    await this.assertSnapshot(snapshot);
    const r = snapshot.record;
    const next = { active: "draining", draining: "quiescent", quiescent: "checkpointed" }[r.state];
    if (state !== next || !next) throw new CoordError("INVALID", "Lifecycle transition skipped or reversed");
    const record = { ...r, state };
    if (state === "draining") {
      if (quiescence !== undefined || checkpoint_digest !== undefined) throw new CoordError("INVALID", "Draining does not establish quiescence or checkpoint");
    } else if (state === "quiescent") {
      if (!quiescence || quiescence.prior_revision !== snapshot.revision || quiescence.prior_epoch !== r.ownership_epoch || digest(quiescence.prior_owner) !== digest(r.owner) || quiescence.processes_stopped !== true || quiescence.jobs_stopped !== true || quiescence.operations_reconciled !== true || checkpoint_digest !== undefined) throw new CoordError("INVALID", "Quiescence evidence must bind the draining owner, epoch and revision");
      const { SharedOperations } = await import("./operations.js");
      if ((await new SharedOperations(this).list(r.role_id)).some(op => op.record.state === "UNKNOWN")) throw new CoordError("UNKNOWN", "Shared unresolved operations block quiescence");
      record.quiescence = quiescence;
    } else {
      if (typeof checkpoint_digest !== "string" || !/^[a-f0-9]{64}$/.test(checkpoint_digest) || (quiescence !== undefined && digest(quiescence) !== digest(r.quiescence)) || (r.quiescence.checkpoint_digest !== undefined && r.quiescence.checkpoint_digest !== checkpoint_digest)) throw new CoordError("INVALID", "Durable checkpoint digest and unchanged quiescence required");
      record.checkpoint_digest = checkpoint_digest;
      record.quiescent_revision = snapshot.revision;
    }
    try { const ack = await this.js.publish(subject("role", r.role_id), encode(record), { expect: { lastSubjectSequence: snapshot.revision } }); return { record, revision: ack.seq }; } catch (e) { throw failure(e); }
  }
  async transferRole(snapshot, { priorOwner, priorEpoch, nextOwner, quiescence, checkpoint_digest }) {
    await this.assertSnapshot(snapshot);
    const r = snapshot.record; owner(priorOwner); owner(nextOwner);
    if (digest(r.owner) !== digest(priorOwner) || r.ownership_epoch !== priorEpoch) throw new CoordError("STALE", "Prior owner/epoch mismatch");
    if (r.state !== "checkpointed" || !r.quiescence || typeof r.checkpoint_digest !== "string" || !/^[a-f0-9]{64}$/.test(r.checkpoint_digest) || !Number.isSafeInteger(r.quiescent_revision) || !(r.quiescence.prior_revision < r.quiescent_revision && r.quiescent_revision < snapshot.revision) || digest(quiescence) !== digest(r.quiescence) || (checkpoint_digest !== undefined && checkpoint_digest !== r.checkpoint_digest)) throw new CoordError("INVALID", "Transfer requires persisted checkpointed lifecycle and matching proof");
    if (!Number.isSafeInteger(priorEpoch + 1)) throw new CoordError("INVALID", "Ownership epoch exhausted");
    const record = { ...r, owner: nextOwner, ownership_epoch: priorEpoch + 1, state: "active", handoff: { quiescence: r.quiescence, checkpoint_digest: r.checkpoint_digest, quiescent_revision: r.quiescent_revision, checkpoint_revision: snapshot.revision } };
    delete record.quiescence; delete record.checkpoint_digest; delete record.quiescent_revision;
    try { const ack = await this.js.publish(subject("role", r.role_id), encode(record), { expect: { lastSubjectSequence: snapshot.revision } }); return { record, revision: ack.seq }; } catch (e) { throw failure(e); }
  }
  async reportStatus(role, id) { return this.read(subject("report", role, id)); }
  async publishReport(report) {
    const subj = subject("report", report.role_id, report.message_id);
    const envelope = { report, digest: digest(report) };
    try { const ack = await this.js.publish(subj, encode(envelope), { expect: { lastSubjectSequence: 0 } }); return { record: envelope, revision: ack.seq }; }
    catch (e) {
      // Handles a duplicate, a lost ack, or an uncertain disconnect identically.
      const found = await this.reportStatus(report.role_id, report.message_id);
      if (found) { if (found.record.digest !== envelope.digest) throw new CoordError("IMMUTABLE", "Same report id has different content", e); return found; }
      throw failure(e);
    }
  }
  async receiptStatus(role, id, stage) { return this.read(subject("receipt", role, id, stage)); }
  async commitReceipt(snapshot, { message_id, stage, disposition }) {
    if (!STAGES.includes(stage)) throw new CoordError("INVALID", "Receipt stage must be ADE-inbox-recorded or processed");
    revision(snapshot.revision);
    const r = snapshot.record;
    if (r.generation !== this.generation) throw new CoordError("GENERATION", "Stale generation");
    await this.assertSnapshot(snapshot);
    if (r.state !== "active") throw new CoordError("STALE", "Only active roles can commit receipts");
    const record = { role_id: r.role_id, message_id, stage, disposition, owner: r.owner, ownership_epoch: r.ownership_epoch, generation: r.generation, role_revision: snapshot.revision };
    if (!await this.reportStatus(r.role_id, message_id)) throw new CoordError("INVALID", "Receipt requires retained report");
    try {
      // Guard is a separate subject: do not rewrite the role within this batch.
      const guardHeaders = headers();
      guardHeaders.set("Nats-Expected-Last-Subject-Sequence", String(snapshot.revision));
      guardHeaders.set("Nats-Expected-Last-Subject-Sequence-Subject", subject("role", r.role_id));
      const batch = await this.js.startBatch(subject("guard", r.role_id, randomUUID()), encode(record), { headers: guardHeaders });
      const receiptHeaders = headers();
      receiptHeaders.set("Nats-Expected-Last-Subject-Sequence", "0");
      await batch.commit(subject("receipt", r.role_id, message_id, stage), encode(record), { headers: receiptHeaders });
    } catch (e) {
      const found = await this.receiptStatus(r.role_id, message_id, stage);
      if (found && digest(found.record) === digest(record)) return found;
      if (found) throw new CoordError("IMMUTABLE", "Receipt already committed with different content", e);
      throw failure(e);
    }
    return this.receiptStatus(r.role_id, message_id, stage);
  }
  async listInbox(role) {
    safeToken(role);
    const info = await this.manager.streams.info(STREAM); const result = [];
    // Retained ledger scan; consumer ack state has no correctness role.
    for (let seq = info.state.first_seq; seq <= info.state.last_seq; seq++) {
      const m = await this.manager.streams.getMessage(STREAM, { seq });
      if (m.subject.startsWith(`ade.v1.report.${role}.`)) {
        const value = JSON.parse(new TextDecoder().decode(m.data));
        if (!await this.receiptStatus(role, value.report.message_id, "processed")) result.push({ record: value, revision: m.seq });
      }
    }
    return result;
  }
}

export { canonical as canonicalJSON };
export { LocalState, Delivery, Artifacts, artifactReference } from "./delivery.js";

export { SharedOperations } from "./operations.js";
