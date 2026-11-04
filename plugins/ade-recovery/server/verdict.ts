// Pure verdict over a loaded record plus live evidence (no I/O, no clock: `live.now` is the time).
// Precedence: do-not-resume > needs-review > resumable-native. resumable-native needs every check
// to pass; an interrupted turn is never resumable-native (critique finding 2).

import type { GitEvidence, Interruption, LiveEvidence, LoadResult, RecoveryRecord, TurnRecord, VerdictResult } from "./types.ts";
import { missingIdentityField } from "./record.ts";
import { sameHost } from "./host-identity.ts";

/** Paseo's stored record may trail ours by this much (clock and flush order) before it counts as newer. */
export const PASEO_NEWER_TOLERANCE_MS = 2_000;

/** Load problems that block on their own (everything else from the loader is detail, or unknown). */
const LOAD_BLOCKING = new Set(["unknown-schema", "corrupt-fell-back-to-prev", "corrupt-no-valid-generation"]);

function ms(s: unknown): number | null {
  if (typeof s !== "string") return null;
  const t = Date.parse(s);
  return Number.isFinite(t) ? t : null;
}

/** Interruptions recorded after turn T started (or tied to T). Unparseable times count (fail closed). */
function interruptionsAfter(ints: Interruption[], t: TurnRecord | null): Interruption[] {
  if (!t) return ints;
  const start = ms(t.startedAt);
  return ints.filter((i) => {
    if (i && i.turnKey !== null && i.turnKey !== undefined && i.turnKey === t.turnKey) return true;
    const at = ms(i?.detectedAt);
    if (at === null || start === null) return true;
    return at >= start;
  });
}

function gitComparable(g: GitEvidence | null | undefined): g is GitEvidence {
  return (
    !!g &&
    typeof g.head === "string" &&
    g.head !== "" &&
    typeof g.trackedFingerprint === "string" &&
    typeof g.untrackedFingerprint === "string"
  );
}

export function judge(load: LoadResult, live: LiveEvidence | null): VerdictResult {
  const stop: string[] = []; // do-not-resume codes
  const reasons: string[] = []; // needs-review codes
  const info: string[] = [];
  const add = (list: string[], code: string) => {
    if (!list.includes(code)) list.push(code);
  };

  for (const p of load?.problems ?? []) {
    if (LOAD_BLOCKING.has(p) || p.startsWith("missing-identity:")) add(reasons, p);
    else if (p.startsWith("current:") || p.startsWith("prev:")) add(info, `load:${p}`);
    else add(reasons, p); // unknown problem: fail closed
  }

  const r: RecoveryRecord | null = load?.record ?? null;
  if (!r) {
    if (reasons.length === 0) add(reasons, "no-record");
    return { verdict: "needs-review", reasons, info };
  }
  if (load.source !== "current") add(reasons, "corrupt-fell-back-to-prev");
  if (typeof r.generation === "number") info.push(`generation:${r.generation}`);
  if (live) {
    const w = ms(r.writtenAt);
    if (w !== null && Number.isFinite(live.now)) info.push(`record-age:${Math.max(0, Math.floor((live.now - w) / 1000))}`);
  }

  // Identity.
  const missing = missingIdentityField(r as unknown as Record<string, unknown>);
  if (missing !== null) add(reasons, `missing-identity:${missing}`);

  // do-not-resume: archived, or any cancel outside shutdown with nothing interrupting it later. The
  // upstream cancel reason is generic, so a reload interrupt or a provider-side cancel reads the same
  // as a user stop: the safe direction.
  const turns: TurnRecord[] = Array.isArray(r.turns) ? r.turns : [];
  const last: TurnRecord | null = turns.length > 0 ? turns[turns.length - 1] : null;
  const ints: Interruption[] = Array.isArray(r.interruptions) ? r.interruptions : [];
  const later = interruptionsAfter(ints, last);
  const prior = ints.length - later.length;
  if (prior > 0) info.push(`prior-interruptions:${prior}`);
  if (r.state === "archived" || (r.archivedAt !== null && r.archivedAt !== undefined)) add(stop, "archived");
  const outcome = last?.outcome?.kind ?? null;
  if (last && outcome === "canceled" && !last.duringShutdown && later.length === 0) add(stop, "canceled-outside-shutdown");

  // Host and server.
  if (!live) {
    add(reasons, "no-live-evidence");
  } else {
    if (live.serverId !== null && live.serverId !== undefined && live.serverId !== r.serverId) add(reasons, "other-server");
    // Machine id when both sides have one; hostname only when either lacks it (older records).
    if (!live.host || !sameHost(live.host, r)) add(reasons, "other-host");
    // Paseo's own store (read only by the CLI): hooks are best-effort, so what the plugin did not
    // observe (an archive, a new turn, a stop while it was down) shows up here. Unavailable
    // evidence never blocks by itself.
    if (live.paseoServerId === null) info.push("paseo-server-id-unavailable");
    else if (typeof live.paseoServerId === "string" && live.paseoServerId !== r.serverId) add(reasons, "other-server");
    if (live.paseoArchived === true) add(stop, "paseo-archived");
    if (live.paseoArchived === null || live.paseoUpdatedAt === null) info.push("paseo-record-unavailable");
    const pu = ms(live.paseoUpdatedAt);
    const wa = ms(r.writtenAt);
    if (pu !== null && wa !== null && pu - wa > PASEO_NEWER_TOLERANCE_MS) add(reasons, "paseo-record-newer");
    if (live.host && typeof live.host.bootId === "string" && typeof r.bootId === "string" && live.host.bootId !== r.bootId) {
      info.push("boot-id-changed");
    }
  }

  if (!r.persistence || typeof r.persistence.sessionId !== "string" || r.persistence.sessionId === "") {
    add(reasons, "no-persistence-handle");
  }

  // Interruptions after the last turn started: never resumable; tool calls are not captured in v1.
  for (const i of later) add(reasons, `interrupted:${typeof i?.evidence === "string" ? i.evidence : "unknown"}`);
  if (later.length > 0) add(reasons, "tools-unobserved");

  // Live turn: a turn is open, nothing has interrupted it, and a writer that could still be
  // recording it is alive. (A recorded interruption wins: a live writer then is a new daemon's.)
  const openState = r.state === "turn-in-flight" || r.state === "idle" || r.state === undefined;
  const unended = r.state === "turn-in-flight" || (openState && last !== null && !last.endedAt);
  const writerLive = !!live && (live.writerAlive === true || live.recordWriterAlive === true);
  const liveTurn = unended && writerLive && later.length === 0;
  if (liveTurn) add(reasons, "live-turn-active");

  // The last turn must have ended cleanly and been observed.
  if (!last) {
    add(reasons, "no-turns");
  } else {
    const clean = !!last.endedAt && (outcome === "completed" || outcome === "failed") && !last.duringShutdown;
    if (!clean && !stop.includes("canceled-outside-shutdown") && later.length === 0 && !liveTurn) {
      if (last.endedAt && last.duringShutdown) add(reasons, "turn-ended-during-shutdown");
      else add(reasons, "turn-outcome-unknown");
    }
  }

  // State must be idle or closed.
  const st = r.state;
  if (st === "turn-in-flight") {
    if (!liveTurn && later.length === 0) add(reasons, "turn-outcome-unknown");
  } else if (st === "interrupted") {
    if (later.length === 0) add(reasons, "interrupted:unrecorded");
  } else if (st !== "idle" && st !== "closed" && st !== "archived") {
    add(reasons, "state-unknown");
  }

  // Git: the live tree must equal the last capture.
  if (live) {
    const latest = r.git?.latest ?? null;
    const now = live.git;
    if (!gitComparable(latest) || !gitComparable(now)) {
      add(reasons, "git-evidence-missing");
    } else {
      if (latest.truncated || now.truncated) {
        add(reasons, "git-evidence-missing");
        info.push("git-evidence-truncated");
      }
      const cap = ms(latest.capturedAt);
      const ended = ms(last?.endedAt);
      if (ended !== null && (cap === null || cap < ended)) {
        add(reasons, "git-evidence-missing");
        info.push("git-latest-predates-turn-end");
      }
      if (latest.head !== now.head) add(reasons, "head-diverged");
      if (latest.trackedFingerprint !== now.trackedFingerprint) add(reasons, "dirty-tree-changed");
      if (latest.untrackedFingerprint !== now.untrackedFingerprint) add(reasons, "untracked-changed");
    }
    if (live.recoveryScheduledElsewhere === true) add(reasons, "recovery-scheduled-elsewhere");
  }

  if (stop.length > 0) return { verdict: "do-not-resume", reasons: [...stop, ...reasons], info };
  if (reasons.length > 0) return { verdict: "needs-review", reasons, info };
  return { verdict: "resumable-native", reasons: [], info };
}
