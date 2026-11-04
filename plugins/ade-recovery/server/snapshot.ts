// Normalise what the SDK's `agents.ref(id).refresh()` returns into AgentSnapshot.
// The SDK (getpaseo/paseo 5d1a2c1, packages/client/src/index.ts:279,376) resolves to
// `{agent: PaseoAgent, project} | null`, where the active turn is `agent.activeTurn.turnId`
// (protocol AgentSnapshotPayloadSchema). A flat snapshot is accepted too (tests, older SDKs).
import type { AgentSnapshot } from "./types.ts";

function str(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}

export function normalizeSnapshot(result: unknown): AgentSnapshot | null {
  if (!result || typeof result !== "object") return null;
  const outer = result as Record<string, unknown>;
  const a = (outer.agent && typeof outer.agent === "object" ? outer.agent : outer) as Record<string, unknown>;
  const id = str(a.id);
  if (!id) return null;
  const snap: AgentSnapshot = { id };
  const status = str(a.status);
  if (status !== undefined) snap.status = status;
  const active = a.activeTurn;
  if (active && typeof active === "object") {
    snap.activeTurnId = str((active as Record<string, unknown>).turnId) ?? null;
  } else if ("activeTurnId" in a) {
    snap.activeTurnId = str(a.activeTurnId) ?? null;
  } else if (active === null) {
    snap.activeTurnId = null;
  }
  if ("archivedAt" in a) snap.archivedAt = str(a.archivedAt) ?? null;
  if (a.labels && typeof a.labels === "object") snap.labels = a.labels as Record<string, string>;
  if ("persistence" in a) {
    const p = a.persistence;
    snap.persistence = p && typeof p === "object" ? (p as AgentSnapshot["persistence"]) : null;
  }
  return snap;
}
