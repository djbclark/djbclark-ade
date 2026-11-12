// Where records live, and the checks that make the directory safe to write.
// <base>/ade/<serverId>/ade-recovery/recovery/v1, base = ADE_STATE_ROOT || XDG_STATE_HOME || ~/.local/state.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { sha256Hex } from "./canonical.ts";

const SAFE = /^[A-Za-z0-9_-]{1,128}$/;

export function isSafeComponent(s: unknown): s is string {
  return typeof s === "string" && SAFE.test(s);
}

/** Returns s when it is a safe path component (`^[A-Za-z0-9_-]{1,128}$`), else throws. */
export function safeComponent(s: string): string {
  if (!isSafeComponent(s)) throw new Error(`unsafe path component: ${JSON.stringify(String(s).slice(0, 40))}`);
  return s;
}

/** File key for an agent id: the id itself when safe, else `h-<sha256(id)>` (itself a safe key). */
export function agentFileName(agentId: string): string {
  return isSafeComponent(agentId) ? agentId : `h-${sha256Hex(String(agentId))}`;
}

/** The base directory that holds `ade/<serverId>/...` (exported for readers that glob server ids). */
export function stateBase(env: NodeJS.ProcessEnv = process.env): string {
  if (env.ADE_STATE_ROOT) return path.resolve(env.ADE_STATE_ROOT);
  // XDG: a relative XDG_STATE_HOME is invalid and must be ignored.
  if (env.XDG_STATE_HOME && path.isAbsolute(env.XDG_STATE_HOME)) return env.XDG_STATE_HOME;
  return path.join(env.HOME || os.homedir(), ".local", "state");
}

export function stateRoot(serverId: string, env: NodeJS.ProcessEnv = process.env): string {
  return path.join(stateBase(env), "ade", safeComponent(serverId), "ade-recovery", "recovery", "v1");
}

/**
 * mkdir -p, mode 0700 for every directory this call creates (pre-existing ones are not chmodded).
 * Throws when the final directory is not a directory, is not owned by this uid, or is group- or
 * world-writable. Returns the directory.
 */
export function ensureRoot(dir: string): string {
  const abs = path.resolve(dir);
  const missing: string[] = [];
  let cur = abs;
  for (;;) {
    try {
      fs.statSync(cur);
      break;
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code !== "ENOENT") throw e;
      missing.push(cur);
      const up = path.dirname(cur);
      if (up === cur) break;
      cur = up;
    }
  }
  for (const d of missing.reverse()) {
    try {
      fs.mkdirSync(d, { mode: 0o700 });
      fs.chmodSync(d, 0o700); // umask cannot widen, but be explicit
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code !== "EEXIST") throw e;
    }
  }
  const st = fs.statSync(abs);
  if (!st.isDirectory()) throw new Error(`state root is not a directory: ${abs}`);
  const uid = typeof process.getuid === "function" ? process.getuid() : null;
  if (uid !== null && st.uid !== uid) {
    throw new Error(`state root ${abs} is owned by uid ${st.uid}, not ${uid}; refusing`);
  }
  if ((st.mode & 0o022) !== 0) {
    throw new Error(`state root ${abs} is group- or world-writable (mode ${(st.mode & 0o777).toString(8)}); refusing`);
  }
  return abs;
}
