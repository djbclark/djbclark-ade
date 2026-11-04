// Sealing and validating recovery records: integrity is sha256 over the canonical JSON of every
// field except `integrity` itself (unknown keys included, so they cannot be altered unnoticed).

import type { RecoveryRecord } from "./types.ts";
import { SCHEMA, MAX_RECORD_BYTES } from "./constants.ts";
import { canonicalJson, sha256Hex } from "./canonical.ts";

export type ValidateResult = { ok: true; record: RecoveryRecord } | { ok: false; problem: string };

function digestOf(r: Record<string, unknown>): string {
  const { integrity: _ignored, ...rest } = r;
  return sha256Hex(canonicalJson(rest));
}

export function sealRecord(r: Omit<RecoveryRecord, "integrity">): RecoveryRecord {
  const digest = digestOf(r as Record<string, unknown>);
  return { ...(r as RecoveryRecord), integrity: { alg: "sha256", digest } };
}

const REQUIRED_STRINGS = ["serverId", "paseoAgentId", "provider", "cwd", "host", "platform"] as const;

/** First missing or ill-typed required field, or null. Shared with the verdict's identity check. */
export function missingIdentityField(r: Record<string, unknown>): string | null {
  const gen = r.generation;
  if (typeof gen !== "number" || !Number.isSafeInteger(gen) || gen < 0) return "generation";
  if (typeof r.writtenAt !== "string" || r.writtenAt === "") return "writtenAt";
  const w = r.writer as Record<string, unknown> | null | undefined;
  if (w === null || typeof w !== "object" || Array.isArray(w)) return "writer";
  if (typeof w.pid !== "number" || !Number.isSafeInteger(w.pid) || w.pid < 1) return "writer.pid";
  for (const f of REQUIRED_STRINGS) {
    if (typeof r[f] !== "string" || r[f] === "") return f;
  }
  if (!("bootId" in r) || (r.bootId !== null && typeof r.bootId !== "string")) return "bootId";
  return null;
}

/**
 * Validate a record given as its raw file content (string or Buffer) or as a parsed value.
 * Problems, checked in this order: not-json, too-large, unknown-schema, bad-integrity,
 * missing-identity:<field>. Unknown keys are tolerated; missing optional fields load as unknown.
 */
export function validateRecord(x: unknown): ValidateResult {
  let value: unknown = x;
  if (typeof x === "string" || Buffer.isBuffer(x)) {
    const bytes = typeof x === "string" ? Buffer.byteLength(x, "utf8") : x.length;
    if (bytes > MAX_RECORD_BYTES) return { ok: false, problem: "too-large" };
    try {
      value = JSON.parse(typeof x === "string" ? x : x.toString("utf8"));
    } catch {
      return { ok: false, problem: "not-json" };
    }
  }
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return { ok: false, problem: "not-json" };
  }
  const r = value as Record<string, unknown>;
  if (!(typeof x === "string" || Buffer.isBuffer(x))) {
    let size: number;
    try {
      size = Buffer.byteLength(canonicalJson(r), "utf8");
    } catch {
      return { ok: false, problem: "not-json" };
    }
    if (size > MAX_RECORD_BYTES) return { ok: false, problem: "too-large" };
  }
  if (r.schema !== SCHEMA) return { ok: false, problem: "unknown-schema" };
  const integ = r.integrity as Record<string, unknown> | null | undefined;
  if (
    integ === null ||
    typeof integ !== "object" ||
    integ.alg !== "sha256" ||
    typeof integ.digest !== "string" ||
    integ.digest !== digestOf(r)
  ) {
    return { ok: false, problem: "bad-integrity" };
  }
  const missing = missingIdentityField(r);
  if (missing !== null) return { ok: false, problem: `missing-identity:${missing}` };
  return { ok: true, record: r as unknown as RecoveryRecord };
}

/**
 * Best-effort generation number from a file that failed validation (finding 8d: the next write must
 * not reuse a corrupt generation's number). Reads it from parsed JSON, or from the raw text of a
 * truncated file. Returns 0 when none can be found.
 */
export function generationHint(raw: string): number {
  try {
    const v = JSON.parse(raw) as { generation?: unknown };
    if (v && typeof v === "object" && typeof v.generation === "number" && Number.isSafeInteger(v.generation)) {
      return Math.max(0, v.generation);
    }
  } catch {
    // fall through to the text scan
  }
  let best = 0;
  for (const m of raw.matchAll(/"generation"\s*:\s*(\d{1,15})/g)) {
    const n = Number(m[1]);
    if (Number.isSafeInteger(n) && n > best) best = n;
  }
  return best;
}
