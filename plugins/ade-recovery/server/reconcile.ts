// Startup reconcile for records left in `turn-in-flight` (issue 278, Slice B).
//
// Runs once, after lazy init has taken the writer lock and loaded every record. It only
// READS through the SDK (`agents.ref(id).refresh()`), and only for a record written by
// this same daemon instance (a plugin reload), or by an instance that cannot be told apart
// from it (same pid and boot, a start token unknown): a record from another daemon or boot is
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
  if (list.length <= max) {
    record.interruptions = list;
    return;
  }
  // The cap never drops the sticky unobserved-activity entry: keep the oldest one in front.
  let kept = list.slice(list.length - max);
  const sticky = list.find((i) => i?.evidence === "unobserved-activity");
  if (sticky && !kept.some((i) => i?.evidence === "unobserved-activity")) kept = [sticky, ...kept.slice(1)];
  record.interruptions = kept;
}

/**
 * Paseo's stored agent record says the agent changed after `writtenAt` (beyond `toleranceMs`) and
 * before `before` (the time the plugin first buffered an event for it, which may itself have bumped
 * it). The time compared is Paseo's activity time (`lastActivityAt`, else `updatedAt`; see
 * paseo-home.ts). Appends the sticky `unobserved-activity` interruption, once; true when added.
 */
export function noteUnobservedActivity(
  record: RecordBody,
  writtenAt: string | null | undefined,
  paseoActivityAt: string | null | undefined,
  before: number,
  toleranceMs: number,
  at: string,
): boolean {
  const w = typeof writtenAt === "string" ? Date.parse(writtenAt) : Number.NaN;
  const u = typeof paseoActivityAt === "string" ? Date.parse(paseoActivityAt) : Number.NaN;
  if (!Number.isFinite(w) || !Number.isFinite(u)) return false;
  if (u - w <= toleranceMs) return false;
  if (Number.isFinite(before) && u >= before - toleranceMs) return false;
  if ((record.interruptions ?? []).some((i) => i?.evidence === "unobserved-activity")) return false;
  addInterruption(record, {
    detectedAt: at,
    evidence: "unobserved-activity",
    turnKey: null,
    detail: "Paseo's agent record changed after the last generation while the plugin was not observing",
  });
  return true;
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

/** A "<pid>:<start>:<bootId>" daemon instance split up; the start token (ps lstart) may hold colons. */
export function parseDaemonInstance(s: unknown): { pid: string; start: string | null; boot: string | null } | null {
  if (typeof s !== "string") return null;
  const first = s.indexOf(":");
  const last = s.lastIndexOf(":");
  if (first <= 0 || last <= first) return null;
  const pid = s.slice(0, first);
  if (!/^\d+$/.test(pid)) return null;
  const start = s.slice(first + 1, last);
  const boot = s.slice(last + 1);
  return { pid, start: start === "" || start === "null" ? null : start, boot: boot === "" || boot === "null" ? null : boot };
}

/**
 * The same daemon pid on the same boot, but a start token is unknown on either side (a slow
 * `ps` on a loaded macOS host reads null): the instance cannot be told apart, so it is
 * "unknown", not "another daemon" (adversary finding 2). The caller then asks the SDK.
 */
export function daemonInstanceUnknown(recorded: unknown, current: string): boolean {
  const a = parseDaemonInstance(recorded);
  const b = parseDaemonInstance(current);
  if (!a || !b) return false;
  if (a.pid !== b.pid || a.boot === null || b.boot === null || a.boot !== b.boot) return false;
  return a.start === null || b.start === null;
}

/**
 * Evidence for a record written by another daemon (or boot), or null for this one. An unknown
 * instance (daemonInstanceUnknown) is null too: reconcile takes the refresh path for it.
 */
export function staleDaemonEvidence(
  record: Pick<RecordBody, "daemonInstance" | "bootId">,
  ctx: { daemonInstance: string; bootId: string | null },
): InterruptionEvidence | null {
  if (record.daemonInstance === ctx.daemonInstance) return null;
  // A record with no daemonInstance cannot prove it belongs to this daemon: treat it as
  // another daemon's (the conservative reading).
  if (record.daemonInstance === undefined) return "daemon-restart";
  if (record.bootId && ctx.bootId && record.bootId !== ctx.bootId) return "boot-id-changed";
  if (daemonInstanceUnknown(record.daemonInstance, ctx.daemonInstance)) return null;
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
