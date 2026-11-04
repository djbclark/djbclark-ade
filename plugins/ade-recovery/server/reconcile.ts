// Startup reconcile for records left in `turn-in-flight` (issue 278, Slice B).
//
// Runs once, after lazy init has taken the writer lock and loaded every record. It only
// READS through the SDK (`agents.ref(id).refresh()`), and only for a record written by
// this same daemon instance (a plugin reload): a record from another daemon or boot is
// decided from the record alone. It never sends, reloads, archives, interrupts or
// creates. A later turn never clears an interruption: `interruptions[]` is history.

import type {
  AgentSnapshot,
  Interruption,
  InterruptionEvidence,
  MissingTelemetry,
  RecoveryRecord,
  TurnRecord,
} from "./types.ts";
import { MAX_INTERRUPTIONS } from "./constants.ts";
import { mapLimit, withTimeout } from "./queue.ts";

/** A record without the fields the store assigns when it writes a generation. */
export type RecordBody = Omit<RecoveryRecord, "integrity" | "generation" | "writtenAt">;

export interface ReconcileContext {
  /** "<daemon pid>:<daemon start>:<bootId>" of the daemon running this plugin now. */
  daemonInstance: string;
  bootId: string | null;
  /** Read-only snapshot; null (or a not-found error) means the agent is gone. */
  refresh(agentId: string): Promise<AgentSnapshot | null>;
  now?: () => number;
  /** Concurrent refreshes (default 4). */
  concurrency?: number;
  /** Per-refresh deadline in ms (default 10 000). */
  timeoutMs?: number;
}

export interface ReconcileWrite<R extends RecordBody = RecordBody> {
  agentId: string;
  record: R;
  /** What changed, for the log: interruption evidence or "turn-outcome-unknown", ... */
  changes: string[];
}

/** The turn still open: no end observed and no outcome assigned. */
export function openTurn(record: Pick<RecordBody, "turns">): TurnRecord | null {
  const turns = record.turns ?? [];
  for (let i = turns.length - 1; i >= 0; i -= 1) {
    const turn = turns[i] as TurnRecord;
    if (turn.endedAt === null && turn.outcome === null) return turn;
  }
  return null;
}

export function addInterruption(
  record: Pick<RecordBody, "interruptions">,
  interruption: Interruption,
  max: number = MAX_INTERRUPTIONS,
): void {
  const list = record.interruptions ? [...record.interruptions] : [];
  list.push(interruption);
  record.interruptions = list.length > max ? list.slice(list.length - max) : list;
}

/** Add a missing-telemetry entry once per field. */
export function addMissing(
  record: Pick<RecordBody, "missingTelemetry">,
  field: string,
  reason: string,
  at: string,
): void {
  const list = record.missingTelemetry ? [...record.missingTelemetry] : [];
  if (list.some((m: MissingTelemetry) => m.field === field)) return;
  list.push({ field, reason, at });
  record.missingTelemetry = list;
}

/** Evidence for a record written by another daemon (or boot), or null for this one. */
export function staleDaemonEvidence(
  record: Pick<RecordBody, "daemonInstance" | "bootId">,
  ctx: { daemonInstance: string; bootId: string | null },
): InterruptionEvidence | null {
  if (record.daemonInstance === ctx.daemonInstance) return null;
  // A record with no daemonInstance cannot prove it belongs to this daemon: treat it as
  // another daemon's (the conservative reading).
  if (record.daemonInstance === undefined) return "daemon-restart";
  if (record.bootId && ctx.bootId && record.bootId !== ctx.bootId) return "boot-id-changed";
  return "daemon-restart";
}

/**
 * Mark a turn-in-flight record from another daemon (or boot) as interrupted, in place.
 * Returns the evidence it recorded, or null when the record is not stale.
 */
export function interruptIfStaleDaemon(
  record: RecordBody,
  ctx: { daemonInstance: string; bootId: string | null },
  at: string,
): InterruptionEvidence | null {
  if (record.state !== "turn-in-flight") return null;
  const evidence = staleDaemonEvidence(record, ctx);
  if (!evidence) return null;
  const turn = openTurn(record);
  addInterruption(record, {
    detectedAt: at,
    evidence,
    turnKey: turn ? turn.turnKey : null,
    detail:
      evidence === "boot-id-changed"
        ? "turn in flight when the machine rebooted"
        : record.daemonInstance === undefined
          ? "turn in flight in a record with no daemon instance"
          : "turn in flight when the daemon that ran it stopped",
  });
  record.state = "interrupted";
  return evidence;
}

function isNotFound(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const e = error as { code?: unknown; message?: unknown; name?: unknown };
  const text = `${String(e.code ?? "")} ${String(e.name ?? "")} ${String(e.message ?? "")}`;
  return /not[ _-]?found|unknown agent|no such agent|ENOENT/i.test(text);
}

type RefreshResult =
  | { kind: "snapshot"; snapshot: AgentSnapshot }
  | { kind: "missing" }
  | { kind: "error"; detail: string };

function setTurnUnknown(turn: TurnRecord, code: string): void {
  turn.outcome = { kind: "unknown", code };
}

/**
 * Decide every `turn-in-flight` record. Returns the generations to write (deep copies;
 * the input records are not mutated). A record that is still running the same non-null
 * turn in this same daemon is kept and not returned.
 */
export async function reconcile<R extends RecordBody>(
  records: readonly R[],
  ctx: ReconcileContext,
): Promise<ReconcileWrite<R>[]> {
  const now = ctx.now ?? Date.now;
  const timeoutMs = ctx.timeoutMs ?? 10_000;
  const concurrency = ctx.concurrency ?? 4;
  const writes: ReconcileWrite<R>[] = [];
  const sameDaemon: R[] = [];

  for (const original of records) {
    if (!original || original.state !== "turn-in-flight") continue;
    if (staleDaemonEvidence(original, ctx) === null) {
      sameDaemon.push(original);
      continue;
    }
    const record = structuredClone(original);
    const evidence = interruptIfStaleDaemon(record, ctx, new Date(now()).toISOString());
    if (evidence) writes.push({ agentId: record.paseoAgentId, record, changes: [evidence] });
  }

  const results = await mapLimit(sameDaemon, concurrency, async (record): Promise<RefreshResult> => {
    try {
      const snapshot = await withTimeout(
        Promise.resolve().then(() => ctx.refresh(record.paseoAgentId)),
        timeoutMs,
        "refresh",
      );
      if (snapshot === null || snapshot === undefined) return { kind: "missing" };
      return { kind: "snapshot", snapshot };
    } catch (error) {
      if (isNotFound(error)) return { kind: "missing" };
      const name = error instanceof Error ? error.name : "error";
      return { kind: "error", detail: name === "TimeoutError" ? "refresh-timeout" : "refresh-failed" };
    }
  });

  sameDaemon.forEach((original, index) => {
    const result = results[index] as RefreshResult;
    const at = new Date(now()).toISOString();
    const record = structuredClone(original);
    const turn = openTurn(record);
    const changes: string[] = [];

    if (result.kind === "error") {
      // Cannot tell; keep the state, say why it was not reconciled.
      addMissing(record, "reconcile", `${result.detail}: state left as recorded`, at);
      writes.push({ agentId: record.paseoAgentId, record, changes: [result.detail] });
      return;
    }

    if (result.kind === "missing") {
      addInterruption(record, {
        detectedAt: at,
        evidence: "agent-missing",
        turnKey: turn ? turn.turnKey : null,
        detail: "agent no longer known to the daemon while a turn was in flight",
      });
      record.state = "interrupted";
      writes.push({ agentId: record.paseoAgentId, record, changes: ["agent-missing"] });
      return;
    }

    const snap = result.snapshot;
    const status = typeof snap.status === "string" ? snap.status : "";
    const active = typeof snap.activeTurnId === "string" ? snap.activeTurnId : null;
    if (status === "running" && active !== null && turn && turn.turnId !== null && turn.turnId === active) {
      return; // Same daemon, same turn still running: keep tracking.
    }

    if (status === "closed") {
      addInterruption(record, {
        detectedAt: at,
        evidence: "closed-without-turn-end",
        turnKey: turn ? turn.turnKey : null,
        detail: "agent closed while the plugin was not observing; turn end not seen",
      });
      record.state = "closed";
      changes.push("closed-without-turn-end");
    } else {
      // Idle, error, a different or null running turn: the tracked turn's end was missed
      // (plugin reload in the same daemon). Its outcome is unknown; it was not interrupted.
      if (turn) setTurnUnknown(turn, "turn-end-not-observed");
      record.state = status === "running" ? "turn-in-flight" : "idle";
      if (status === "running") {
        addMissing(record, "turnStart", "a running turn started while the plugin was not observing", at);
      }
      changes.push("turn-outcome-unknown");
    }
    if (typeof snap.archivedAt === "string" && snap.archivedAt && !record.archivedAt) {
      record.archivedAt = snap.archivedAt;
      record.state = "archived";
      changes.push("archived");
    }
    writes.push({ agentId: record.paseoAgentId, record, changes });
  });

  return writes;
}
