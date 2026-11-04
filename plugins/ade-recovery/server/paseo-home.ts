// Paseo's own on-disk state, read only: where $PASEO_HOME is, the daemon's server id, and the
// stored agent record. Resolution copies upstream packages/server/src/server/paseo-home.ts
// (resolvePaseoHome): `PASEO_HOME ?? "~/.paseo"`, a leading `~/` (or a bare `~`) expands to the
// home directory, then path.resolve() makes a relative value absolute against the cwd. Note `??`:
// an EMPTY PASEO_HOME resolves to the cwd upstream, and so it does here.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export interface PaseoHomeOptions {
  /** Defaults to os.homedir(), as upstream. */
  homedir?: string;
  /** Defaults to process.cwd() (what upstream's path.resolve uses). */
  cwd?: string;
}

/** `$PASEO_HOME` resolved exactly as the Paseo daemon resolves it. */
export function paseoHome(env: NodeJS.ProcessEnv = process.env, opts: PaseoHomeOptions = {}): string {
  const raw = env.PASEO_HOME ?? "~/.paseo";
  const home = opts.homedir ?? os.homedir();
  let expanded = raw;
  if (raw.startsWith("~/")) expanded = path.join(home, raw.slice(2));
  else if (raw === "~") expanded = home;
  return opts.cwd === undefined ? path.resolve(expanded) : path.resolve(opts.cwd, expanded);
}

const SERVER_ID_FILE = "server-id";
const SAFE_ID = /^[A-Za-z0-9_-]{1,128}$/;
const MAX_AGENT_RECORD_BYTES = 8 * 1024 * 1024;

/**
 * The daemon's server id as upstream server-id.ts getOrCreateServerId() reads it: a non-empty
 * trimmed `PASEO_SERVER_ID` wins, else `<home>/server-id` trimmed. null when neither yields a
 * safe id (never generated here: this reader writes nothing).
 */
export function paseoServerId(home: string, env: NodeJS.ProcessEnv = process.env): string | null {
  const override = typeof env.PASEO_SERVER_ID === "string" ? env.PASEO_SERVER_ID.trim() : "";
  if (override.length > 0) return SAFE_ID.test(override) ? override : null;
  const raw = readSmallFile(path.join(home, SERVER_ID_FILE), 4096);
  if (raw === null) return null;
  const id = raw.trim();
  return SAFE_ID.test(id) ? id : null;
}

/** What the CLI takes from Paseo's stored agent record (docs/data-model.md, "Agent Record"). */
export interface PaseoAgentRecordEvidence {
  archivedAt: string | null;
  /** The record's `updatedAt` (a required string upstream), else the file mtime when it does not parse. */
  updatedAt: string | null;
  updatedAtSource: "updatedAt" | "mtime";
}

/**
 * found: a valid record. missing: `<home>/agents` is readable and holds no valid `<id>.json`
 * (upstream remove() unlinks it; upstream also skips a file that fails its schema, so Paseo does
 * not know the agent either). unavailable: no agents directory, an unreadable one, or an unsafe id.
 */
export type PaseoAgentLookup =
  | { status: "found"; record: PaseoAgentRecordEvidence }
  | { status: "missing" }
  | { status: "unavailable" };

/**
 * A regular file's text, or null (missing, not a regular file, too large, unreadable). Opened with
 * O_NONBLOCK, so a FIFO never blocks; fstat then refuses anything but a regular file of at most
 * `maxBytes`. `noFollow` adds O_NOFOLLOW: a symlink is refused.
 */
export function readSmallFile(file: string, maxBytes: number, opts: { noFollow?: boolean } = {}): string | null {
  let fd: number;
  try {
    const flags =
      fs.constants.O_RDONLY | (fs.constants.O_NONBLOCK ?? 0) | (opts.noFollow ? (fs.constants.O_NOFOLLOW ?? 0) : 0);
    fd = fs.openSync(file, flags);
  } catch {
    return null;
  }
  try {
    const st = fs.fstatSync(fd);
    if (!st.isFile() || st.size > maxBytes) return null;
    return fs.readFileSync(fd, "utf8");
  } catch {
    return null;
  } finally {
    try {
      fs.closeSync(fd);
    } catch {
      // ignore
    }
  }
}

/**
 * One candidate file, as upstream scanDisk would load it: a regular file (Dirent.isFile(), so a
 * symlink is skipped; lstat here, O_NOFOLLOW on open) that parses and passes a minimal slice of
 * upstream's STORED_AGENT_SCHEMA (`id` and `updatedAt` strings, `archivedAt` string|null|absent),
 * with `id` equal to the agent id. null otherwise.
 */
function readAgentFile(file: string, agentId: string): PaseoAgentRecordEvidence | null {
  let st: fs.Stats;
  try {
    st = fs.lstatSync(file);
  } catch {
    return null;
  }
  if (!st.isFile()) return null;
  const raw = readSmallFile(file, MAX_AGENT_RECORD_BYTES, { noFollow: true });
  if (raw === null) return null;
  let v: unknown;
  try {
    v = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!v || typeof v !== "object" || Array.isArray(v)) return null;
  const r = v as Record<string, unknown>;
  if (typeof r.id !== "string" || r.id !== agentId) return null; // upstream keys the record by its id field
  if (typeof r.updatedAt !== "string") return null; // required upstream: the record is skipped without it
  if (r.archivedAt !== undefined && r.archivedAt !== null && typeof r.archivedAt !== "string") return null;
  const archivedAt = typeof r.archivedAt === "string" && r.archivedAt !== "" ? r.archivedAt : null;
  if (Number.isFinite(Date.parse(r.updatedAt))) {
    return { archivedAt, updatedAt: r.updatedAt, updatedAtSource: "updatedAt" };
  }
  return { archivedAt, updatedAt: st.mtime.toISOString(), updatedAtSource: "mtime" };
}

/**
 * Paseo's stored record for `agentId`, read only: `<home>/agents/<project-dir>/<id>.json` (one
 * level, as upstream AgentStorage.scanDisk) and the legacy `<home>/agents/<id>.json`. Several
 * copies: the latest updatedAt wins, and any archived copy marks it archived (fail closed).
 */
export function lookupPaseoAgentRecord(home: string, agentId: string): PaseoAgentLookup {
  if (!SAFE_ID.test(agentId)) return { status: "unavailable" };
  const base = path.join(home, "agents");
  const files = [path.join(base, `${agentId}.json`)];
  try {
    for (const d of fs.readdirSync(base, { withFileTypes: true })) {
      if (d.isDirectory()) files.push(path.join(base, d.name, `${agentId}.json`));
    }
  } catch {
    return { status: "unavailable" };
  }
  let best: PaseoAgentRecordEvidence | null = null;
  let archivedAt: string | null = null;
  for (const f of files) {
    const e = readAgentFile(f, agentId);
    if (!e) continue;
    if (e.archivedAt && !archivedAt) archivedAt = e.archivedAt;
    const t = e.updatedAt === null ? Number.NaN : Date.parse(e.updatedAt);
    const bt = best?.updatedAt ? Date.parse(best.updatedAt) : Number.NaN;
    if (best === null || (Number.isFinite(t) && (!Number.isFinite(bt) || t > bt))) best = e;
  }
  if (best === null) return { status: "missing" };
  return { status: "found", record: { ...best, archivedAt: best.archivedAt ?? archivedAt } };
}

/** The found record of lookupPaseoAgentRecord, else null (missing and unavailable alike). */
export function readPaseoAgentRecord(home: string, agentId: string): PaseoAgentRecordEvidence | null {
  const r = lookupPaseoAgentRecord(home, agentId);
  return r.status === "found" ? r.record : null;
}

/** A recorded `paseoHome` the CLI may use: a string, absolute, no NUL, bounded; else null. */
export function validRecordedPaseoHome(v: unknown): string | null {
  if (typeof v !== "string" || v === "" || v.length > 4096 || v.includes("\0")) return null;
  if (!path.isAbsolute(v)) return null;
  return path.resolve(v);
}
