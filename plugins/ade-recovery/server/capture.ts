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
  openTurn,
  reconcile,
  type RecordBody,
} from "./reconcile.ts";

export type { RecordBody } from "./reconcile.ts";

export type LockResult =
  | { held: true; release(): void }
  | { held: false; holder: WriterInfo | null; reason: string };

/** The durability layer (Slice A), injected so tests can replace it. */
export interface CaptureStore {
  stateRoot(serverId: string): string;
  ensureRoot(dir: string): unknown;
  acquireLock(dir: string, info: WriterInfo): LockResult;
  /** Seals and atomically writes the next generation for `agentId`. */
  writeGeneration(dir: string, agentId: string, body: RecordBody): Promise<unknown>;
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

interface Buffered {
  seq: number;
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

  private agents: Map<string, AgentEntry>;
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
    this.agents = new Map();
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
    this.accept(paseo, (seq, p) => this.applyCreate(agent, seq, p));
  }

  onTurnBefore(agent: HookAgent, turnId: string | null, paseo: PaseoLike): void {
    this.accept(paseo, (seq, p) => this.applyTurnBefore(agent, turnId ?? null, seq, p));
  }

  onTurnAfter(agent: HookAgent, turnId: string | null, outcome: TurnOutcome, paseo: PaseoLike): void {
    this.accept(paseo, (seq, p) => this.applyTurnAfter(agent, turnId ?? null, outcome, seq, p));
  }

  onClose(agent: HookAgent, paseo: PaseoLike): void {
    this.accept(paseo, (seq) => this.applyClose(agent, seq));
  }

  onArchive(agent: HookAgent, archivedAt: string, paseo: PaseoLike): void {
    this.accept(paseo, (seq) => this.applyArchive(agent, archivedAt, seq));
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
   */
  async close(flushMs: number = this.timeouts.closeFlushMs): Promise<void> {
    if (this.modeValue === "closed") return;
    this.closing = true;
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
      ).catch(() => this.log("flush did not finish before close"));
    } catch {
      // never throw from cleanup
    }
    try {
      this.lock?.release();
    } catch (error) {
      this.log("lock release failed", { error: errorName(error) });
    }
    this.lock = null;
    this.modeValue = "closed";
    this.agents.clear();
  }

  // ---------------------------------------------------------------- dispatch

  private accept(paseo: PaseoLike, apply: (seq: number, paseo: PaseoLike) => void): void {
    try {
      this.seq += 1;
      const seq = this.seq;
      if (this.closing || this.modeValue === "closed") return;
      if (this.modeValue === "active" || this.modeValue === "read-only") {
        this.safeApply(apply, seq, paseo);
        return;
      }
      if (this.modeValue === "inert") {
        if (this.deps.now() - this.initFailedAt < this.timeouts.initRetryMs) return;
      }
      if (this.buffer.length >= MAX_BUFFERED_EVENTS) {
        this.dropped += 1;
      } else {
        this.buffer.push({ seq, paseo, apply });
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
        } else if (buffered.length > 0 || this.dropped > 0) {
          this.log("dropped events while inert", { count: buffered.length + this.dropped });
        }
        if (this.dropped > 0 && this.modeValue === "active") {
          this.log("dropped events beyond the init buffer", { count: this.dropped });
        }
        this.dropped = 0;
      });
  }

  private failInit(reason: string): void {
    try {
      this.lock?.release();
    } catch {
      // ignore
    }
    this.lock = null;
    this.modeValue = this.closing ? "closed" : "inert";
    this.initFailedAt = this.deps.now();
    this.logOnce(`inert:${reason}`, "inert: recording nothing", { reason });
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
    if (this.isShuttingDown()) {
      // Either the daemon is already stopping, or this daemon keeps no local-credential
      // (then every capture reads as shutdown-time: no git, never resumable). Say which.
      this.logOnce("shutdown-at-init", "local-credential absent at init: shutdown assumed; git and SDK capture off");
    }

    // 3. load every record.
    const loaded: RecordBody[] = [];
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
    this.modeValue = "active";
  }

  // ---------------------------------------------------------------- event application

  private applyCreate(agent: HookAgent, seq: number, paseo: PaseoLike): void {
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
    const prefix = `${this.daemonInstance}:`;
    if (
      turnId !== null &&
      turns.some((t) => t.turnId === turnId && t.turnKey.startsWith(prefix) && t.endedAt !== null)
    ) {
      // turn.after for this turn already arrived (hook order is not guaranteed).
      this.scheduleWrite(agent.id);
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
    body.daemonInstance = this.daemonInstance;
    // agent.title is deliberately not stored (it can carry a command line).
    addMissing(body, "toolCalls", TOOL_CALLS_REASON, at);
    addMissing(body, "providerVersion", PROVIDER_VERSION_REASON, at);
    return entry;
  }

  // ---------------------------------------------------------------- writes and detached work

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
    if (!entry || entry.foreign || !entry.body || !this.dir) return Promise.resolve();
    const dir = this.dir;
    return this.writes.run(`w:${agentId}`, async () => {
      const current = this.agents.get(agentId)?.body;
      if (!current) return;
      const body = structuredClone(current);
      try {
        await this.deps.store.writeGeneration(dir, agentId, body);
      } catch (error) {
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
        try {
          await this.deps.store.writeGeneration(dir, agentId, body);
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
