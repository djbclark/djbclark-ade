// Capture state machine: Paseo hook event -> in-memory record -> generation write
// (issue 278, Slice B).
//
// Every hook handler returns at once. It assigns a sequence number synchronously, then
// either applies the event (mutate the in-memory record, upsert identity, enqueue a
// lifecycle write FIRST) or buffers it while lazy init runs. Git capture and the
// persistence refresh run detached, after the write is enqueued, each under its own
// deadline. During daemon shutdown (local-credential gone) nothing calls git or the SDK.
// Nothing in here sends, reloads, archives, interrupts or creates; no method throws.

import type {
  AgentSnapshot,
  GitEvidence,
  HookAgent,
  HostIdentity,
  LoadResult,
  PaseoLike,
  ProcessIdentity,
  RecoveryRecord,
  TurnOutcome,
  TurnRecord,
  WriterInfo,
} from "./types.ts";
import { MAX_TURNS, PLUGIN_ID, PLUGIN_VERSION, SCHEMA } from "./constants.ts";
import { CoalescingQueue, Semaphore, withTimeout } from "./queue.ts";
import { normalizeSnapshot } from "./snapshot.ts";
import {
  addInterruption,
  addMissing,
  interruptIfStaleDaemon,
  noteUnobservedActivity,
  openTurn,
  reconcile,
  type RecordBody,
} from "./reconcile.ts";
import { PASEO_NEWER_TOLERANCE_MS } from "./verdict.ts";

export type { RecordBody } from "./reconcile.ts";

export type LockResult =
  | { held: true; release(): void; stillHeld?(): boolean }
  | { held: false; holder: WriterInfo | null; reason: string };

/** Passed to every generation write: the store re-checks it right before each rename. */
export interface WriteGuard {
  /** False once this writer may no longer publish (lock released or lost, close deadline passed). */
  owner(): boolean;
}

/** The durability layer (Slice A), injected so tests can replace it. */
export interface CaptureStore {
  stateRoot(serverId: string): string;
  ensureRoot(dir: string): unknown;
  acquireLock(dir: string, info: WriterInfo): LockResult;
  /**
   * Seals and atomically writes the next generation for `agentId`. Must call `guard.owner()`
   * immediately before publishing (each rename) and abandon the write, rejecting, when it is false.
   */
  writeGeneration(dir: string, agentId: string, body: RecordBody, guard?: WriteGuard): Promise<unknown>;
  loadRecord(dir: string, agentId: string): LoadResult;
  listAgents(dir: string): string[];
  sweepTmp(dir: string): unknown;
}

export interface CaptureHost {
  hostIdentity(): HostIdentity;
  daemonIdentity(): ProcessIdentity;
  /** WriterInfo for this process; built from the other two when absent. */
  writerInfo?(): WriterInfo;
  processStart?(pid: number): string | null;
}

export interface CaptureDeps {
  store: CaptureStore;
  gitEvidence(cwd: string, signal: AbortSignal): Promise<GitEvidence>;
  host: CaptureHost;
  now(): number;
  /** True once the daemon has begun stopping ($PASEO_HOME/local-credential absent). */
  shuttingDown(): boolean;
  log(message: string, extra?: Record<string, unknown>): void;
  /** sha256 of canonical JSON, for the native persistence handle. */
  hashJson(value: unknown): string;
  /** Throws unless `s` is a safe path component. */
  safeComponent?(s: string): unknown;
  realpath?(p: string): Promise<string>;
  timeouts?: Partial<CaptureTimeouts>;
  /** The resolved $PASEO_HOME, stored in each record so the CLI reads the daemon's store. */
  paseoHome?: string | null;
  /**
   * Read only, called once per init pass: a reader of the activity time of Paseo's stored record
   * for an agent (`<PASEO_HOME>/agents/<dir>/<id>.json`: `lastActivityAt`, else `updatedAt`; see
   * paseo-home.ts PaseoAgentRecordEvidence.activityAt), null when unavailable. The factory lets the
   * reader list the agents directory once for the pass (adversary round 3, B5). Absent: the init
   * cross-check is skipped.
   */
  paseoActivityReader?(): (agentId: string) => string | null;
}

export interface CaptureTimeouts {
  hostsListMs: number;
  refreshMs: number;
  gitMs: number;
  realpathMs: number;
  initRetryMs: number;
  closeFlushMs: number;
}

const DEFAULT_TIMEOUTS: CaptureTimeouts = {
  hostsListMs: 5_000,
  refreshMs: 10_000,
  gitMs: 20_000,
  realpathMs: 2_000,
  initRetryMs: 30_000,
  closeFlushMs: 1_500,
};

/**
 * A turn.before that matches a turn whose turn.after arrived first (with no start observed) is that
 * same turn's late start only within this window of the end; later, it is a reopen that reuses the
 * id (the hook contract allows a repeat turnId after a session reopens) and opens a new turn.
 */
export const LATE_TURN_START_MS = 10_000;

/** Events held while lazy init settles; later ones are dropped and counted. */
export const MAX_BUFFERED_EVENTS = 500;
/** Concurrent git captures across all agents. */
export const GIT_CONCURRENCY = 2;

export type CaptureMode = "uninitialized" | "initializing" | "active" | "read-only" | "inert" | "closed";

type GitSlot = "baseAtCreate" | "atTurnStart" | "latest";

interface AgentEntry {
  body: RecordBody | null;
  /** On disk under an unknown (newer) schema: never overwritten. */
  foreign: boolean;
  gitSeq: Record<GitSlot, number>;
}

/** One lock acquisition's right to publish generations. */
interface Ownership {
  lock: { release(): void; stillHeld?(): boolean };
  /** Set when this writer must publish nothing more (close deadline passed, or released). */
  stopped: boolean;
}

/** A turn created by a turn.after whose turn.before had not arrived (it may still, late). */
interface UnmatchedEnd {
  turnKey: string;
  turnId: string;
  at: number;
}

interface Buffered {
  seq: number;
  agentId: string | null;
  paseo: PaseoLike;
  apply(seq: number, paseo: PaseoLike): void;
}

const SAFE_COMPONENT = /^[A-Za-z0-9_-]{1,128}$/;
const TOOL_CALLS_REASON = "v1 captures no tool calls; refetch can start a provider";
const PROVIDER_VERSION_REASON = "the hook payload carries no provider or adapter version";

/** Short machine code from an untrusted string; key-shaped runs are redacted. */
function safeCode(value: unknown): string | undefined {
  if (typeof value !== "string" || value.length === 0) return undefined;
  let s = value.replace(/[^A-Za-z0-9_.:-]/g, "_").slice(0, 64);
  if (/[A-Fa-f0-9]{32,}|[A-Za-z0-9+/_-]{40,}|AKIA|ghp_|gho_|github_pat_|sk-|xox.-/.test(s)) s = "[redacted]";
  return s || undefined;
}

function mapOutcome(outcome: TurnOutcome | null | undefined): NonNullable<TurnRecord["outcome"]> {
  if (!outcome || typeof outcome !== "object") return { kind: "unknown", code: "no-outcome" };
  switch (outcome.kind) {
    case "completed":
      return { kind: "completed" };
    case "failed": {
      // The error message can quote command output: store only its code.
      const code = safeCode(outcome.error?.code);
      return code ? { kind: "failed", code } : { kind: "failed" };
    }
    case "canceled": {
      const code = safeCode(outcome.reason);
      return code ? { kind: "canceled", code } : { kind: "canceled" };
    }
    default:
      return { kind: "unknown", code: "unrecognized-outcome" };
  }
}

function errorName(error: unknown): string {
  if (error instanceof Error) return error.name === "Error" ? "error" : error.name;
  return "error";
}

/** Thrown by init with a fixed reason code (no paths, no command output). */
class InitError extends Error {
  constructor(code: string) {
    super(code);
    this.name = "InitError";
  }
}

/**
 * The reason logged when init fails: an InitError's fixed code, else the error's errno code or
 * name only. A raw message can carry filesystem paths (adversary finding 8), so it is never logged.
 */
export function initFailureReason(error: unknown): string {
  if (error instanceof InitError) return error.message;
  const code = (error as { code?: unknown } | null)?.code;
  if (typeof code === "string" && /^[A-Za-z0-9_-]{1,40}$/.test(code)) return `${errorName(error)}:${code}`;
  return errorName(error);
}

function isTooLarge(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const e = error as { code?: unknown; message?: unknown };
  return /too[ _-]?large/i.test(`${String(e.code ?? "")} ${String(e.message ?? "")}`);
}

/** The store refused to publish because the write guard said this writer no longer owns the root. */
function isWriterLost(error: unknown): boolean {
  return !!error && typeof error === "object" && (error as { code?: unknown }).code === "EWRITERLOST";
}

function withoutPaths(ev: GitEvidence | null | undefined): GitEvidence | null | undefined {
  if (!ev) return ev;
  const dropped = ev.trackedPaths.length > 0 || ev.untrackedPaths.length > 0;
  return { ...ev, trackedPaths: [], untrackedPaths: [], truncated: ev.truncated || dropped };
}

/** Strip the fields the store assigns; keep everything else, unknown keys included. */
function toBody(record: RecoveryRecord): RecordBody {
  const copy = structuredClone(record) as Partial<RecoveryRecord>;
  delete copy.integrity;
  delete copy.generation;
  delete copy.writtenAt;
  return copy as RecordBody;
}

export class Capture {
  private deps: CaptureDeps;
  private timeouts: CaptureTimeouts;
  private seq: number;
  private modeValue: CaptureMode;
  private initPromise: Promise<void> | null;
  private initFailedAt: number;
  private buffer: Buffered[];
  private dropped: number;
  private closing: boolean;
  private loggedOnce: Set<string>;

  private hostId: HostIdentity | null;
  private daemonInstance: string;
  private writer: WriterInfo | null;
  private serverId: string | null;
  private dir: string | null;
  private lock: { release(): void } | null;
  /** The current lock's publishing right; captured by each write when it is scheduled. */
  private ownership: Ownership | null;
  /**
   * Per agent, the last turn opened by an unmatched turn.after (no start seen) in this capture. Only
   * that turn may swallow a late turn.before with its id; any later turn.before consumes the entry.
   */
  private unmatchedEnds: Map<string, UnmatchedEnd>;

  private agents: Map<string, AgentEntry>;
  /**
   * When an event for each agent was first BUFFERED before init finished (it may bump Paseo's
   * activity time, and it is applied once init succeeds). Never set for a dropped event, and
   * cleared when init fails (its buffer is then dropped): a dropped event must not excuse the bump
   * it caused (adversary round 3, B1).
   */
  private firstSeen: Map<string, number>;
  /**
   * Agents with at least one hook event that was never applied (inert window, init buffer full,
   * buffer discarded after a failed init). Each gets the sticky unobserved-activity
   * (detail `events-dropped`) at the next successful init, whatever Paseo's store says.
   */
  private droppedFor: Set<string>;
  private foreignNames: Set<string>;
  private lostNames: Set<string>;
  private writes: CoalescingQueue;
  private side: CoalescingQueue;
  private gitSem: Semaphore;
  private controllers: Set<AbortController>;

  constructor(deps: CaptureDeps) {
    this.deps = deps;
    this.timeouts = { ...DEFAULT_TIMEOUTS, ...(deps.timeouts ?? {}) };
    this.seq = 0;
    this.modeValue = "uninitialized";
    this.initPromise = null;
    this.initFailedAt = 0;
    this.buffer = [];
    this.dropped = 0;
    this.closing = false;
    this.loggedOnce = new Set();
    this.hostId = null;
    this.daemonInstance = "unknown";
    this.writer = null;
    this.serverId = null;
    this.dir = null;
    this.lock = null;
    this.ownership = null;
    this.unmatchedEnds = new Map();
    this.agents = new Map();
    this.firstSeen = new Map();
    this.droppedFor = new Set();
    this.foreignNames = new Set();
    this.lostNames = new Set();
    const onError = (key: string, error: unknown): void =>
      this.log("queued work failed", { key: key.split(":")[0], error: errorName(error) });
    this.writes = new CoalescingQueue({ onError });
    this.side = new CoalescingQueue({ onError });
    this.gitSem = new Semaphore(GIT_CONCURRENCY);
    this.controllers = new Set();
  }

  // ---------------------------------------------------------------- hooks

  onCreate(agent: HookAgent, paseo: PaseoLike): void {
    this.accept(paseo, (seq, p) => this.applyCreate(agent, seq, p), agent?.id);
  }

  onTurnBefore(agent: HookAgent, turnId: string | null, paseo: PaseoLike): void {
    this.accept(paseo, (seq, p) => this.applyTurnBefore(agent, turnId ?? null, seq, p), agent?.id);
  }

  onTurnAfter(agent: HookAgent, turnId: string | null, outcome: TurnOutcome, paseo: PaseoLike): void {
    this.accept(paseo, (seq, p) => this.applyTurnAfter(agent, turnId ?? null, outcome, seq, p), agent?.id);
  }

  onClose(agent: HookAgent, paseo: PaseoLike): void {
    this.accept(paseo, (seq) => this.applyClose(agent, seq), agent?.id);
  }

  onArchive(agent: HookAgent, archivedAt: string, paseo: PaseoLike): void {
    this.accept(paseo, (seq) => this.applyArchive(agent, archivedAt, seq), agent?.id);
  }

  // ---------------------------------------------------------------- inspection (tests, cleanup)

  get mode(): CaptureMode {
    return this.modeValue;
  }

  get root(): string | null {
    return this.dir;
  }

  /** A deep copy of the in-memory record for `agentId`, or null. */
  record(agentId: string): RecordBody | null {
    const body = this.agents.get(agentId)?.body;
    return body ? structuredClone(body) : null;
  }

  /** Resolves when init, buffered events, writes and detached work have all settled. */
  async idle(): Promise<void> {
    for (let i = 0; i < 100; i += 1) {
      if (this.initPromise) await this.initPromise;
      await Promise.all([this.writes.idle(), this.side.idle()]);
      if (!this.initPromise && this.writes.size() === 0 && this.side.size() === 0) return;
    }
  }

  /**
   * Stop: accept no more events, abort git, flush pending writes (bounded), release the
   * writer lock, drop in-memory state. Idempotent; never throws.
   *
   * The lock is never released while a generation write may still publish (PR 290, Codex P2): a
   * write that outlasts the flush deadline is told to stop (the store re-checks ownership before
   * each rename and abandons it), and the lock is released only once every write has settled. A
   * write that never settles keeps the lock until this process exits; a stale-holder takeover
   * (dead pid, or a different start token) then frees it, safely, since nothing here runs anymore.
   */
  async close(flushMs: number = this.timeouts.closeFlushMs): Promise<void> {
    if (this.modeValue === "closed") return;
    this.closing = true;
    let flushed = false;
    try {
      for (const c of this.controllers) c.abort();
      this.buffer = [];
      await withTimeout(
        (async () => {
          if (this.initPromise) await this.initPromise;
          await this.side.idle();
          await this.writes.idle();
        })(),
        flushMs,
        "flush",
      ).then(
        () => {
          flushed = true;
        },
        () => this.log("flush did not finish before close"),
      );
    } catch {
      // never throw from cleanup
    }
    this.relinquish(!flushed);
    this.modeValue = "closed";
    this.agents.clear();
    this.unmatchedEnds.clear();
  }

  // ---------------------------------------------------------------- dispatch

  private accept(paseo: PaseoLike, apply: (seq: number, paseo: PaseoLike) => void, agentId?: unknown): void {
    try {
      this.seq += 1;
      const seq = this.seq;
      if (this.closing || this.modeValue === "closed") return;
      if (this.modeValue === "active" || this.modeValue === "read-only") {
        this.safeApply(apply, seq, paseo);
        return;
      }
      const id = typeof agentId === "string" && agentId !== "" ? agentId : null;
      if (this.modeValue === "inert") {
        if (this.deps.now() - this.initFailedAt < this.timeouts.initRetryMs) {
          this.noteDropped(id);
          return;
        }
      }
      if (this.buffer.length >= MAX_BUFFERED_EVENTS) {
        this.dropped += 1;
        this.noteDropped(id);
      } else {
        this.buffer.push({ seq, agentId: id, paseo, apply });
        if (id !== null && !this.firstSeen.has(id)) this.firstSeen.set(id, this.deps.now());
      }
      this.startInit(paseo);
    } catch (error) {
      this.log("hook handling failed", { error: errorName(error) });
    }
  }

  private safeApply(apply: (seq: number, paseo: PaseoLike) => void, seq: number, paseo: PaseoLike): void {
    try {
      apply(seq, paseo);
    } catch (error) {
      this.log("event apply failed", { error: errorName(error) });
    }
  }

  private startInit(paseo: PaseoLike): void {
    if (this.initPromise) return;
    this.modeValue = "initializing";
    this.initPromise = this.init(paseo)
      .catch((error: unknown) => {
        this.failInit(initFailureReason(error));
      })
      .finally(() => {
        this.initPromise = null;
        const buffered = this.buffer;
        this.buffer = [];
        if (this.modeValue === "active" || this.modeValue === "read-only") {
          for (const b of buffered) this.safeApply(b.apply, b.seq, b.paseo);
          if (this.modeValue === "active") this.markDropped();
        } else {
          for (const b of buffered) this.noteDropped(b.agentId);
          if (buffered.length > 0 || this.dropped > 0) {
            this.log("dropped events while inert", { count: buffered.length + this.dropped });
          }
        }
        if (this.dropped > 0 && this.modeValue === "active") {
          this.log("dropped events beyond the init buffer", { count: this.dropped });
        }
        this.dropped = 0;
      });
  }

  private failInit(reason: string): void {
    // Writes already scheduled under this lock (a prev fallback, a reconcile) may still be running:
    // the lock goes only once they have settled. After close() has returned (its deadline passed
    // while init ran) they must publish nothing more.
    this.relinquish(this.modeValue === "closed");
    this.modeValue = this.closing ? "closed" : "inert";
    this.initFailedAt = this.deps.now();
    // The buffer is about to be dropped: its events no longer excuse anything.
    this.firstSeen.clear();
    this.logOnce(`inert:${reason}`, "inert: recording nothing", { reason });
  }

  /**
   * Give up the writer lock without ever releasing it under a write that may still publish. No new
   * write is scheduled under it from now on. `stop`: writes still running must publish nothing more
   * (each abandons at its next ownership check). The lock is released at once when no write is in
   * flight, else when the write queue has settled (never, if a write hangs: see close()).
   */
  private relinquish(stop: boolean): void {
    const own = this.ownership;
    const lock = this.lock;
    this.ownership = null;
    this.lock = null;
    if (!lock) return;
    const release = (): void => {
      if (own) own.stopped = true;
      try {
        lock.release();
      } catch (error) {
        this.log("lock release failed", { error: errorName(error) });
      }
    };
    if (stop && own) own.stopped = true;
    if (this.writes.size() === 0) {
      release();
      return;
    }
    this.log("writer lock kept until in-flight writes settle", { stopped: stop });
    void this.writes.idle().then(release, release);
  }

  private async init(paseo: PaseoLike): Promise<void> {
    const host = this.deps.host;
    this.hostId = host.hostIdentity();
    const daemon = host.daemonIdentity();
    this.daemonInstance = `${daemon.pid}:${daemon.start ?? "null"}:${this.hostId.bootId ?? "null"}`;
    this.writer = host.writerInfo
      ? host.writerInfo()
      : {
          plugin: PLUGIN_ID as "ade-recovery",
          pluginVersion: PLUGIN_VERSION,
          pid: process.pid,
          start: host.processStart ? host.processStart(process.pid) : null,
          daemon,
          host: this.hostId.host,
          bootId: this.hostId.bootId,
          machineId: this.hostId.machineId ?? null,
        };

    // 1. server id: never a shared key; no id means inert.
    let serverId: unknown = null;
    try {
      const hosts = await withTimeout(
        Promise.resolve().then(() => paseo.hosts.list()),
        this.timeouts.hostsListMs,
        "hosts.list",
      );
      serverId = hosts?.self?.serverId ?? null;
    } catch (error) {
      throw new InitError(`no-server-id:${errorName(error)}`);
    }
    if (typeof serverId !== "string" || !this.isSafe(serverId)) throw new InitError("no-server-id:invalid");
    if (this.closing) throw new InitError("closed-during-init");
    this.serverId = serverId;

    // 2. root and lock.
    const store = this.deps.store;
    const dir = store.stateRoot(serverId);
    store.ensureRoot(dir);
    this.dir = dir;
    const lock = store.acquireLock(dir, this.writer);
    if (!lock.held) {
      this.modeValue = "read-only";
      this.logOnce("read-only", "read-only: another writer holds the lock; writing nothing", {
        reason: lock.reason,
        holderPid: lock.holder?.pid ?? null,
      });
      return;
    }
    this.lock = lock;
    this.ownership = { lock, stopped: false };
    if (this.isShuttingDown()) {
      // Either the daemon is already stopping, or this daemon keeps no local-credential
      // (then every capture reads as shutdown-time: no git, never resumable). Say which.
      this.logOnce("shutdown-at-init", "local-credential absent at init: shutdown assumed; git and SDK capture off");
    }

    // 3. load every record.
    const loaded: RecordBody[] = [];
    const writtenAt = new Map<string, string>();
    for (const name of store.listAgents(dir)) {
      let result: LoadResult;
      try {
        result = store.loadRecord(dir, name);
      } catch (error) {
        this.log("record load failed", { error: errorName(error) });
        continue;
      }
      if (!result.record) {
        if (result.problems.includes("unknown-schema")) this.foreignNames.add(name);
        else this.lostNames.add(name);
        continue;
      }
      const body = toBody(result.record);
      const at = this.iso();
      writtenAt.set(body.paseoAgentId, result.record.writtenAt);
      if (result.source === "prev" || result.problems.includes("corrupt-fell-back-to-prev")) {
        // The lost generation may have held an interruption: never let the last turn
        // read as cleanly observed on the strength of an older generation.
        const turns = body.turns ?? [];
        const last = turns[turns.length - 1];
        if (last && last.outcome && last.outcome.kind !== "unknown") {
          last.outcome = { kind: "unknown", code: "record-fell-back-to-prev" };
        }
        addMissing(body, "generation", "current generation was corrupt at load; continued from the previous one", at);
      }
      this.agents.set(body.paseoAgentId, { body, foreign: false, gitSeq: { baseAtCreate: 0, atTurnStart: 0, latest: 0 } });
      loaded.push(body);
      if (result.source === "prev") this.scheduleWrite(body.paseoAgentId, true);
    }

    // 4. tidy and reconcile (lock holder only).
    try {
      store.sweepTmp(dir);
    } catch (error) {
      this.log("tmp sweep failed", { error: errorName(error) });
    }
    const writes = await reconcile(loaded, {
      daemonInstance: this.daemonInstance,
      bootId: this.hostId.bootId,
      refresh: async (id) => normalizeSnapshot(await paseo.agents.ref(id).refresh()),
      now: this.deps.now,
      timeoutMs: this.timeouts.refreshMs,
    });
    if (this.closing) throw new InitError("closed-during-init");
    for (const w of writes) {
      const entry = this.agents.get(w.agentId);
      if (!entry) continue;
      w.record.writer = this.writer;
      entry.body = w.record;
      this.log("reconciled", { changes: w.changes.join(",") });
      this.scheduleWrite(w.agentId, true);
    }

    // 5. Paseo's own store, for EVERY loaded record: activity after our last generation means
    // something happened while the plugin was not observing (a turn and a stop, an archive). The
    // next generation's writtenAt would hide it from the CLI's paseo-record-newer, so it becomes a
    // sticky interruption now. An event already buffered for the agent (and so about to be applied)
    // may have caused the bump itself, so only an update before that event counts for it; a dropped
    // event excuses nothing (droppedFor marks its agent unconditionally once init succeeds).
    this.crossCheckPaseo(writtenAt);
    this.modeValue = "active";
  }

  private crossCheckPaseo(writtenAt: Map<string, string>): void {
    const factory = this.deps.paseoActivityReader;
    let read: ((agentId: string) => string | null) | null = null;
    try {
      read = factory ? factory() : null;
    } catch (error) {
      this.log("paseo store read failed", { error: errorName(error) });
    }
    if (!read) {
      this.firstSeen.clear();
      return;
    }
    for (const [agentId, w] of writtenAt) {
      const entry = this.agents.get(agentId);
      if (!entry?.body) continue;
      let updatedAt: string | null = null;
      try {
        updatedAt = read(agentId);
      } catch (error) {
        this.log("paseo store read failed", { error: errorName(error) });
        continue;
      }
      const before = this.firstSeen.get(agentId) ?? Number.POSITIVE_INFINITY;
      if (noteUnobservedActivity(entry.body, w, updatedAt, before, PASEO_NEWER_TOLERANCE_MS, this.iso())) {
        this.log("unobserved activity", { source: "paseo-store" });
        this.scheduleWrite(agentId, true);
      }
    }
    this.firstSeen.clear();
  }

  /** An event for `agentId` was not (and will not be) applied. */
  private noteDropped(agentId: string | null): void {
    if (agentId !== null) this.droppedFor.add(agentId);
  }

  /**
   * After a successful init (active mode): every agent with a dropped event that has a record gets
   * the sticky unobserved-activity now; one without a record yet gets it in upsert, when its next
   * event creates the record.
   */
  private markDropped(): void {
    for (const agentId of [...this.droppedFor]) {
      const entry = this.agents.get(agentId);
      if (!entry?.body) continue;
      this.droppedFor.delete(agentId);
      if (this.addDroppedInterruption(entry.body)) {
        this.log("unobserved activity", { source: "events-dropped" });
        this.scheduleWrite(agentId);
      }
    }
  }

  private addDroppedInterruption(body: RecordBody): boolean {
    if ((body.interruptions ?? []).some((i) => i?.evidence === "unobserved-activity")) return false;
    addInterruption(body, {
      detectedAt: this.iso(),
      evidence: "unobserved-activity",
      turnKey: null,
      detail: "events-dropped",
    });
    return true;
  }

  // ---------------------------------------------------------------- event application

  private applyCreate(agent: HookAgent, seq: number, paseo: PaseoLike): void {
    this.unmatchedEnds.delete(agent.id); // a create/close/archive between end and start: no late start
    const entry = this.upsert(agent);
    if (!entry) return;
    const body = entry.body as RecordBody;
    if (body.state !== "turn-in-flight" && body.state !== "archived") {
      body.state = "idle";
      body.closedAt = null;
    }
    this.scheduleWrite(agent.id);
    if (this.sideEffectsAllowed()) {
      this.scheduleGit(agent.id, ["baseAtCreate", "latest"], seq);
      this.scheduleRefresh(agent.id, paseo);
    }
  }

  private applyTurnBefore(agent: HookAgent, turnId: string | null, seq: number, paseo: PaseoLike): void {
    const entry = this.upsert(agent);
    if (!entry) return;
    const body = entry.body as RecordBody;
    const turns = body.turns ? [...body.turns] : [];
    if (this.isLateStart(agent.id, turnId, turns)) {
      // turn.after for this very turn already arrived (hook order is not guaranteed): its start.
      // No write: the body is unchanged, and a fresh writtenAt would hide a wrongly swallowed
      // start from the CLI's paseo-record-newer check (adversary round 5, B1).
      return;
    }
    const previous = openTurn({ turns });
    if (previous) previous.outcome = { kind: "unknown", code: "turn-end-not-observed" };
    turns.push({
      turnKey: `${this.daemonInstance}:${seq}`,
      turnId,
      startedAt: this.iso(),
      endedAt: null,
      outcome: null,
      duringShutdown: false,
    });
    body.turns = turns.length > MAX_TURNS ? turns.slice(turns.length - MAX_TURNS) : turns;
    body.state = "turn-in-flight";
    body.closedAt = null;
    this.scheduleWrite(agent.id);
    if (this.sideEffectsAllowed()) {
      this.scheduleGit(agent.id, ["atTurnStart"], seq);
      this.scheduleRefresh(agent.id, paseo);
    }
  }

  /**
   * Is this turn.before the late start of a turn whose turn.after already arrived? Only when the
   * agent's last unmatched end (a turn.after with no start seen, in this capture) has this turnId,
   * is still the newest turn with it, and ended within LATE_TURN_START_MS. Every turn.before
   * consumes the entry: a completed turn's id seen again later is a reopen, and opens a new turn.
   */
  private isLateStart(agentId: string, turnId: string | null, turns: TurnRecord[]): boolean {
    const pending = this.unmatchedEnds.get(agentId);
    this.unmatchedEnds.delete(agentId);
    if (!pending || turnId === null || pending.turnId !== turnId) return false;
    if (this.deps.now() - pending.at > LATE_TURN_START_MS) return false;
    for (let i = turns.length - 1; i >= 0; i -= 1) {
      const t = turns[i] as TurnRecord;
      if (t.turnId === turnId) return t.turnKey === pending.turnKey && t.endedAt !== null;
    }
    return false;
  }

  private applyTurnAfter(
    agent: HookAgent,
    turnId: string | null,
    outcome: TurnOutcome,
    seq: number,
    paseo: PaseoLike,
  ): void {
    const entry = this.upsert(agent);
    if (!entry) return;
    const body = entry.body as RecordBody;
    const shutting = this.isShuttingDown();
    const at = this.iso();
    const turns = body.turns ? [...body.turns] : [];
    let turn: TurnRecord | null = null;
    if (turnId !== null) {
      for (let i = turns.length - 1; i >= 0; i -= 1) {
        const t = turns[i] as TurnRecord;
        if (t.turnId === turnId && t.endedAt === null && t.outcome === null) {
          turn = t;
          break;
        }
      }
    }
    if (!turn) {
      if (turnId === null) {
        // A null turnId never matches another null: the open null turn's end is unknown.
        const open = openTurn({ turns });
        if (open && open.turnId === null) open.outcome = { kind: "unknown", code: "null-turn-id" };
        addMissing(body, "turnId", "provider reported a null turnId; turn start and end cannot be paired", at);
      } else {
        addMissing(body, "turnStart", "turn.after arrived for a turn whose start was not observed", at);
      }
      turn = {
        turnKey: `${this.daemonInstance}:${seq}`,
        turnId,
        startedAt: at,
        endedAt: null,
        outcome: null,
        duringShutdown: false,
      };
      turns.push(turn);
      if (turnId !== null) this.unmatchedEnds.set(agent.id, { turnKey: turn.turnKey, turnId, at: this.deps.now() });
    }
    turn.endedAt = at;
    turn.outcome = mapOutcome(outcome);
    turn.duringShutdown = shutting;
    body.turns = turns.length > MAX_TURNS ? turns.slice(turns.length - MAX_TURNS) : turns;
    const canceledByShutdown = shutting && outcome?.kind === "canceled";
    if (canceledByShutdown) {
      addInterruption(body, {
        detectedAt: at,
        evidence: "canceled-during-shutdown",
        turnKey: turn.turnKey,
        detail: "turn canceled while the daemon was stopping (local-credential gone)",
      });
    }
    if (body.state !== "closed" && body.state !== "archived") {
      if (canceledByShutdown) body.state = "interrupted";
      else body.state = openTurn(body) ? "turn-in-flight" : "idle";
    }
    this.scheduleWrite(agent.id);
    if (this.sideEffectsAllowed()) {
      this.scheduleGit(agent.id, ["latest"], seq);
      this.scheduleRefresh(agent.id, paseo);
    }
  }

  private applyClose(agent: HookAgent, _seq: number): void {
    this.unmatchedEnds.delete(agent.id);
    const entry = this.upsert(agent);
    if (!entry) return;
    const body = entry.body as RecordBody;
    const shutting = this.isShuttingDown();
    const at = this.iso();
    const turn = openTurn(body);
    if (turn) {
      if (shutting) turn.duringShutdown = true;
      addInterruption(body, {
        detectedAt: at,
        evidence: "closed-without-turn-end",
        turnKey: turn.turnKey,
        detail: shutting ? "agent closed by daemon shutdown with a turn in flight" : "agent closed with a turn in flight",
      });
    }
    if (body.state !== "archived") body.state = "closed";
    body.closedAt = at;
    // close.after: write the in-memory state at once; no git, no SDK.
    this.scheduleWrite(agent.id);
  }

  private applyArchive(agent: HookAgent, archivedAt: string, _seq: number): void {
    this.unmatchedEnds.delete(agent.id);
    const entry = this.upsert(agent);
    if (!entry) return;
    const body = entry.body as RecordBody;
    body.state = "archived";
    body.archivedAt = typeof archivedAt === "string" && archivedAt.length <= 64 ? archivedAt : this.iso();
    this.scheduleWrite(agent.id);
  }

  /** Get or create the entry and refresh its identity (restored agents never fire create.after). */
  private upsert(agent: HookAgent): AgentEntry | null {
    if (!agent || typeof agent.id !== "string" || agent.id.length === 0) {
      this.logOnce("bad-agent", "hook payload without an agent id ignored");
      return null;
    }
    const host = this.hostId as HostIdentity;
    const at = this.iso();
    let entry = this.agents.get(agent.id);
    if (!entry) {
      entry = {
        body: null,
        foreign: this.foreignNames.has(agent.id),
        gitSeq: { baseAtCreate: 0, atTurnStart: 0, latest: 0 },
      };
      this.agents.set(agent.id, entry);
    }
    if (!entry.body) {
      entry.body = {
        schema: SCHEMA,
        writer: this.writer as WriterInfo,
        serverId: this.serverId as string,
        paseoAgentId: agent.id,
        provider: agent.provider,
        cwd: agent.cwd,
        host: host.host,
        bootId: host.bootId,
        platform: host.platform,
        machineId: host.machineId ?? null,
        workspaceId: null,
        parentAgentId: null,
        persistence: null,
        state: "idle",
        daemonInstance: this.daemonInstance,
        closedAt: null,
        archivedAt: null,
        turns: [],
        git: { baseAtCreate: null, atTurnStart: null, latest: null },
        interruptions: [],
        missingTelemetry: [],
      };
      if (this.lostNames.has(agent.id)) {
        addMissing(entry.body, "history", "no valid generation on disk at load; earlier history lost", at);
      }
    }
    const body = entry.body;
    if (this.modeValue === "active" && this.droppedFor.delete(agent.id)) {
      // An earlier event for this agent was dropped before its record existed.
      if (this.addDroppedInterruption(body)) this.log("unobserved activity", { source: "events-dropped" });
    }
    // A turn left in flight by another daemon is an interruption, before identity moves on.
    interruptIfStaleDaemon(body, { daemonInstance: this.daemonInstance, bootId: host.bootId }, at);
    body.schema = SCHEMA;
    body.writer = this.writer as WriterInfo;
    body.serverId = this.serverId as string;
    body.paseoAgentId = agent.id;
    if (typeof agent.provider === "string" && agent.provider) body.provider = agent.provider;
    if (typeof agent.cwd === "string" && agent.cwd) body.cwd = agent.cwd;
    body.workspaceId = typeof agent.workspaceId === "string" ? agent.workspaceId : null;
    body.parentAgentId = typeof agent.parentAgentId === "string" ? agent.parentAgentId : null;
    body.host = host.host;
    body.bootId = host.bootId;
    body.platform = host.platform;
    body.machineId = host.machineId ?? null;
    if (typeof this.deps.paseoHome === "string" && this.deps.paseoHome !== "") body.paseoHome = this.deps.paseoHome;
    body.daemonInstance = this.daemonInstance;
    // agent.title is deliberately not stored (it can carry a command line).
    addMissing(body, "toolCalls", TOOL_CALLS_REASON, at);
    addMissing(body, "providerVersion", PROVIDER_VERSION_REASON, at);
    return entry;
  }

  // ---------------------------------------------------------------- writes and detached work

  /** May a write scheduled under `own` still publish? The lock file must still carry our nonce. */
  private owns(own: Ownership): boolean {
    if (own.stopped) return false;
    try {
      return own.lock.stillHeld ? own.lock.stillHeld() === true : true;
    } catch {
      return false;
    }
  }

  private sideEffectsAllowed(): boolean {
    return this.modeValue === "active" && !this.closing && !this.isShuttingDown();
  }

  private isShuttingDown(): boolean {
    try {
      return this.deps.shuttingDown();
    } catch {
      return true; // cannot tell: the conservative reading
    }
  }

  /** Enqueue a generation write of the agent's current in-memory state. */
  private scheduleWrite(agentId: string, duringInit = false): Promise<void> {
    if (!duringInit && this.modeValue !== "active") return Promise.resolve();
    const entry = this.agents.get(agentId);
    const own = this.ownership;
    if (!entry || entry.foreign || !entry.body || !this.dir || !own) return Promise.resolve();
    const dir = this.dir;
    const guard: WriteGuard = { owner: () => this.owns(own) };
    return this.writes.run(`w:${agentId}`, async () => {
      if (!this.owns(own)) return;
      const current = this.agents.get(agentId)?.body;
      if (!current) return;
      const body = structuredClone(current);
      try {
        await this.deps.store.writeGeneration(dir, agentId, body, guard);
      } catch (error) {
        if (isWriterLost(error)) {
          this.log("generation write abandoned: this writer no longer owns the state root");
          if (!own.stopped && this.modeValue === "active") {
            // The lock vanished or changed hands while we live: stop writing, say so once
            // (adversary round 5, B2). The CLI then reads the writer as gone.
            this.modeValue = "read-only";
            this.logOnce("writer-lost", "read-only: writer.lock no longer carries our nonce; writing nothing");
          }
          return;
        }
        if (!isTooLarge(error)) {
          this.log("generation write failed; previous generation kept", { error: errorName(error) });
          return;
        }
        // Too large: keep fingerprints and counts, drop the path lists, try once more.
        const git = body.git ?? {};
        body.git = {
          baseAtCreate: withoutPaths(git.baseAtCreate),
          atTurnStart: withoutPaths(git.atTurnStart),
          latest: withoutPaths(git.latest),
        };
        if (!this.owns(own)) return;
        try {
          await this.deps.store.writeGeneration(dir, agentId, body, guard);
        } catch (again) {
          this.log("generation write failed even without path lists", { error: errorName(again) });
        }
      }
    });
  }

  private scheduleGit(agentId: string, slots: GitSlot[], seq: number): void {
    const key = `g:${agentId}:${slots.join("+")}`;
    void this.side.run(key, async () => {
      if (!this.sideEffectsAllowed()) return;
      const entry = this.agents.get(agentId);
      const cwd = entry?.body?.cwd;
      if (!entry || !cwd) return;
      const release = await this.gitSem.acquire();
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeouts.gitMs);
      timer.unref?.();
      this.controllers.add(controller);
      let evidence: GitEvidence | null = null;
      try {
        if (!this.sideEffectsAllowed()) return;
        evidence = await this.deps.gitEvidence(cwd, controller.signal);
      } catch (error) {
        const body = entry.body;
        if (body) addMissing(body, "git", `git capture failed: ${errorName(error)}`, this.iso());
      } finally {
        clearTimeout(timer);
        this.controllers.delete(controller);
        release();
      }
      const body = entry.body;
      if (!body) return;
      if (evidence) {
        body.git = { ...(body.git ?? {}) };
        const createdHead = body.git.baseAtCreate?.head ?? null;
        for (const slot of slots) {
          if (seq < entry.gitSeq[slot]) continue; // a newer capture already landed
          let ev = evidence;
          if (slot !== "baseAtCreate" && !ev.base && createdHead) {
            ev = { ...ev, base: { ref: "HEAD@create", sha: createdHead, method: "recorded-at-create" } };
          }
          body.git[slot] = ev;
          entry.gitSeq[slot] = seq;
        }
      }
      if (body.cwdRealpath === undefined && this.deps.realpath) {
        try {
          body.cwdRealpath = await withTimeout(this.deps.realpath(cwd), this.timeouts.realpathMs, "realpath");
        } catch {
          body.cwdRealpath = null;
        }
      }
      await this.scheduleWrite(agentId);
    });
  }

  private scheduleRefresh(agentId: string, paseo: PaseoLike): void {
    const entry = this.agents.get(agentId);
    if (!entry?.body || entry.body.persistence?.sessionId) return;
    void this.side.run(`r:${agentId}`, async () => {
      if (!this.sideEffectsAllowed()) return;
      const current = this.agents.get(agentId);
      if (!current?.body || current.body.persistence?.sessionId) return;
      let snapshot: AgentSnapshot | null = null;
      let failure: string | null = null;
      try {
        snapshot = await withTimeout(
          Promise.resolve().then(async () => normalizeSnapshot(await paseo.agents.ref(agentId).refresh())),
          this.timeouts.refreshMs,
          "refresh",
        );
      } catch (error) {
        failure = errorName(error);
      }
      const body = current.body;
      if (!body) return;
      const p = snapshot?.persistence;
      if (p && typeof p === "object" && typeof p.sessionId === "string" && p.sessionId.length > 0) {
        const persistence: NonNullable<RecordBody["persistence"]> = { sessionId: p.sessionId };
        if (typeof p.provider === "string") persistence.provider = p.provider;
        if (p.nativeHandle !== undefined && p.nativeHandle !== null) {
          try {
            persistence.nativeHandleSha256 = this.deps.hashJson(p.nativeHandle);
          } catch {
            // no hash; the session id alone still identifies the session
          }
        }
        body.persistence = persistence;
        if (body.missingTelemetry) body.missingTelemetry = body.missingTelemetry.filter((m) => m.field !== "persistence");
      } else {
        addMissing(
          body,
          "persistence",
          failure ? `refresh failed: ${failure}` : "refresh returned no persistence handle",
          this.iso(),
        );
      }
      await this.scheduleWrite(agentId);
    });
  }

  // ---------------------------------------------------------------- small helpers

  private isSafe(s: string): boolean {
    if (this.deps.safeComponent) {
      try {
        this.deps.safeComponent(s);
        return true;
      } catch {
        return false;
      }
    }
    return SAFE_COMPONENT.test(s);
  }

  private iso(): string {
    return new Date(this.deps.now()).toISOString();
  }

  private log(message: string, extra?: Record<string, unknown>): void {
    try {
      this.deps.log(message, extra);
    } catch {
      // logging must never break capture
    }
  }

  private logOnce(key: string, message: string, extra?: Record<string, unknown>): void {
    if (this.loggedOnce.has(key)) return;
    this.loggedOnce.add(key);
    this.log(message, extra);
  }
}
