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
  /** The record's `updatedAt` (a required ISO string upstream), else the file mtime. */
  updatedAt: string | null;
  updatedAtSource: "updatedAt" | "mtime";
}

/** A regular file's text, or null (missing, not a regular file, too large, unreadable). A FIFO never blocks. */
function readSmallFile(file: string, maxBytes: number): string | null {
  let fd: number;
  try {
    fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NONBLOCK ?? 0));
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

function readAgentFile(file: string, agentId: string): PaseoAgentRecordEvidence | null {
  const raw = readSmallFile(file, MAX_AGENT_RECORD_BYTES);
  if (raw === null) return null;
  let v: unknown;
  try {
    v = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!v || typeof v !== "object" || Array.isArray(v)) return null;
  const r = v as Record<string, unknown>;
  if (r.id !== agentId) return null; // upstream keys the record by its id field
  const archivedAt = typeof r.archivedAt === "string" && r.archivedAt !== "" ? r.archivedAt : null;
  if (typeof r.updatedAt === "string" && Number.isFinite(Date.parse(r.updatedAt))) {
    return { archivedAt, updatedAt: r.updatedAt, updatedAtSource: "updatedAt" };
  }
  let mtime: string | null = null;
  try {
    mtime = fs.statSync(file).mtime.toISOString();
  } catch {
    mtime = null;
  }
  return { archivedAt, updatedAt: mtime, updatedAtSource: "mtime" };
}

/**
 * Paseo's stored record for `agentId`, read only: `<home>/agents/<project-dir>/<id>.json` (one
 * level, as upstream AgentStorage.scanDisk) and the legacy `<home>/agents/<id>.json`. null when
 * absent, unreadable or corrupt. Several copies: the latest updatedAt wins, and any archived copy
 * marks it archived (fail closed).
 */
export function readPaseoAgentRecord(home: string, agentId: string): PaseoAgentRecordEvidence | null {
  if (!SAFE_ID.test(agentId)) return null;
  const base = path.join(home, "agents");
  const files = [path.join(base, `${agentId}.json`)];
  try {
    for (const d of fs.readdirSync(base, { withFileTypes: true })) {
      if (d.isDirectory()) files.push(path.join(base, d.name, `${agentId}.json`));
    }
  } catch {
    return null;
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
  if (best === null) return null;
  return { ...best, archivedAt: best.archivedAt ?? archivedAt };
}
