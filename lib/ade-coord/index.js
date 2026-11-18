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
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
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
  async transferRole(snapshot, { priorOwner, priorEpoch, nextOwner, quiescence }) {
    const r = snapshot.record; revision(snapshot.revision); owner(priorOwner); owner(nextOwner);
    if (r.generation !== this.generation) throw new CoordError("GENERATION", "Stale generation");
    if (digest(r.owner) !== digest(priorOwner) || r.ownership_epoch !== priorEpoch) throw new CoordError("STALE", "Prior owner/epoch mismatch");
    if (!quiescence || quiescence.prior_revision !== snapshot.revision || quiescence.prior_epoch !== priorEpoch || digest(quiescence.prior_owner) !== digest(priorOwner) || quiescence.processes_stopped !== true || quiescence.jobs_stopped !== true || quiescence.operations_reconciled !== true || !quiescence.checkpoint_digest?.match(/^[a-f0-9]{64}$/)) throw new CoordError("INVALID", "Explicit prior-owner quiescence and checkpoint evidence required");
    const record = { ...r, owner: nextOwner, ownership_epoch: priorEpoch + 1, state: "active", quiescence };
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
