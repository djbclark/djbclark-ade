// Single-writer lock for one state root: `writer.lock`, created by link(tmp, lock) so it is never
// seen empty (finding 9). Stale iff the holder's pid is dead, its start token differs (PID reuse),
// or its boot id differs. A stale lock is removed only under a takeover guard named after its
// nonce (see claim()); after linking, the winner re-reads the lock and compares its nonce.
// Host: the machine id decides (hostname drifts on macOS), the hostname only when either side has
// no machine id (an older lock). Residual: a holder on another machine (shared home) is never
// judged; it is reported, not taken over. Cloned-VM guard: machine ids that match while BOTH the
// hostname and the boot id differ read as another host (a cloned /etc/machine-id), not as a
// reboot. Residual of that guard: one machine that was renamed AND rebooted keeps its stale lock
// (read-only) until the operator removes writer.lock.

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import type { HostIdentity, WriterInfo } from "./types.ts";
import { LOCK_FILE, PLUGIN_ID, PLUGIN_VERSION, TMP_PREFIX } from "./constants.ts";
import { canonicalJson, sha256Hex } from "./canonical.ts";
import { bootId, daemonIdentity, hostIdentity, processAlive, sameHost, selfIdentity } from "./host-identity.ts";

export type LockContent = WriterInfo & { nonce: string; acquiredAt: string };

export interface HeldLock {
  held: true;
  nonce: string;
  /** True while writer.lock still carries this holder's nonce. */
  stillHeld(): boolean;
  /** Removes writer.lock only if it still carries this holder's nonce. Idempotent. */
  release(): void;
}

export type LockRefusal =
  | "held-by-live-writer"
  | "holder-liveness-unknown"
  | "held-by-other-host"
  | "lost-race"
  | "nonce-mismatch"
  | `error:${string}`;

export interface NotHeld {
  held: false;
  holder: WriterInfo | null;
  reason: LockRefusal;
}

export interface AcquireOptions {
  /** Test hook: runs right after a successful link, before the nonce re-read. */
  afterLink?: () => void;
  /** Test hook: this host's identity (default hostIdentity()). */
  host?: () => HostIdentity;
}

/** WriterInfo for this process. */
export function selfWriterInfo(): WriterInfo {
  const me = selfIdentity();
  const h = hostIdentity();
  return {
    plugin: PLUGIN_ID,
    pluginVersion: PLUGIN_VERSION,
    pid: me.pid,
    start: me.start,
    daemon: daemonIdentity(),
    host: h.host,
    bootId: h.bootId,
    machineId: h.machineId ?? null,
  };
}

function lockPath(dir: string): string {
  return path.join(dir, LOCK_FILE);
}

function rand(): string {
  return crypto.randomBytes(6).toString("hex");
}

function parseLock(raw: string): LockContent | null {
  try {
    const v = JSON.parse(raw) as Record<string, unknown>;
    if (!v || typeof v !== "object" || Array.isArray(v)) return null;
    if (typeof v.pid !== "number" || !Number.isSafeInteger(v.pid) || v.pid < 1) return null;
    if (v.start !== null && typeof v.start !== "string") return null;
    if (typeof v.host !== "string") return null;
    if (v.bootId !== null && typeof v.bootId !== "string") return null;
    // machineId is optional (locks written before it existed); an ill-typed one reads as absent.
    if (v.machineId !== undefined && v.machineId !== null && typeof v.machineId !== "string") v.machineId = null;
    if (typeof v.nonce !== "string" || v.nonce === "") return null;
    return v as unknown as LockContent;
  } catch {
    return null;
  }
}

function readRaw(dir: string): string | null {
  try {
    return fs.readFileSync(lockPath(dir), "utf8");
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw e;
  }
}

/** The current lock content, or null when there is no lock or it cannot be parsed. */
export function readLock(dir: string): LockContent | null {
  let raw: string | null;
  try {
    raw = readRaw(dir);
  } catch {
    return null;
  }
  return raw === null ? null : parseLock(raw);
}

type HolderState =
  | { stale: true; why: "malformed" | "boot-id-changed" | "holder-dead" }
  | { stale: false; why: "held-by-live-writer" | "holder-liveness-unknown" | "held-by-other-host" };

/**
 * Machine ids match, yet the hostname AND the boot id both differ: likely a cloned VM, not a reboot.
 * Not applied on macOS: IOPlatformUUID is bound to the hardware (a cloned /etc/machine-id is the
 * Linux case), while a renamed-and-rebooted Mac is common and would otherwise stay read-only.
 */
export function clonedMachineSuspect(
  h: { host?: unknown; bootId?: unknown; machineId?: unknown },
  me: { host?: unknown; bootId?: unknown; machineId?: unknown; platform?: unknown },
): boolean {
  if (me.platform === "darwin") return false;
  const hm = typeof h.machineId === "string" && h.machineId !== "";
  const mm = typeof me.machineId === "string" && me.machineId !== "";
  if (!hm || !mm) return false; // the hostname already decided sameHost
  const hostDiffers = typeof h.host === "string" && typeof me.host === "string" && h.host !== me.host;
  const bootDiffers = typeof h.bootId === "string" && typeof me.bootId === "string" && h.bootId !== me.bootId;
  return hostDiffers && bootDiffers;
}

function judgeHolder(h: LockContent | null, me: HostIdentity): HolderState {
  if (h === null) return { stale: true, why: "malformed" };
  if (!sameHost(h, me) || clonedMachineSuspect(h, me)) return { stale: false, why: "held-by-other-host" };
  if (h.bootId !== null && me.bootId !== null && h.bootId !== me.bootId) return { stale: true, why: "boot-id-changed" };
  const alive = processAlive({ pid: h.pid, start: h.start });
  if (alive === false) return { stale: true, why: "holder-dead" };
  if (alive === null) return { stale: false, why: "holder-liveness-unknown" };
  return { stale: false, why: "held-by-live-writer" };
}

function stripLock(h: LockContent | null): WriterInfo | null {
  if (!h) return null;
  const { nonce: _n, acquiredAt: _a, ...info } = h;
  return info as WriterInfo;
}

/** Is the holder named in writer.lock alive? false: no lock or a dead/stale holder; null: unknown. */
export function lockHolderAlive(dir: string, host: () => HostIdentity = hostIdentity): boolean | null {
  let raw: string | null;
  try {
    raw = readRaw(dir);
  } catch {
    return null;
  }
  if (raw === null) return false;
  const h = parseLock(raw);
  if (h === null) return null;
  const s = judgeHolder(h, host());
  if (s.stale) return false;
  return s.why === "held-by-live-writer" ? true : null;
}

function readFileOrNull(file: string): string | null {
  try {
    return fs.readFileSync(file, "utf8");
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw e;
  }
}

function tryLink(tmp: string, target: string): "linked" | "exists" {
  try {
    fs.linkSync(tmp, target);
    return "linked";
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "EEXIST") return "exists";
    throw e;
  }
}

function releaseIfOurs(file: string, nonce: string): void {
  try {
    const cur = parseLock(readFileOrNull(file) ?? "");
    if (cur !== null && cur.nonce === nonce) fs.rmSync(file, { force: true });
  } catch {
    // best effort: a guard left behind is a stale `.tmp-*` file the holder sweeps
  }
}

const MAX_TAKEOVER_DEPTH = 3;

type ClaimResult = { ok: true; nonce: string } | { ok: false; holder: LockContent | null; reason: LockRefusal };

/**
 * Create `file` (writer.lock, or a takeover guard) holding a fresh nonce, via link(tmp, file).
 *
 * Takeover rule: a stale `file` may be unlinked only by the process that first creates the guard
 * `.tmp-takeover-<stale nonce>` (itself claimed by this function, so a guard left by a dead taker
 * is taken over one level down), and only after re-reading `file` under that guard and finding the
 * same stale content. Nothing else but the owner's release() unlinks writer.lock, so a live
 * holder's lock is never removed by a contender: at most one winner, and a winner never loses
 * its lock to a slow contender that judged an older lock stale.
 */
function claim(
  dir: string,
  file: string,
  info: WriterInfo,
  depth: number,
  me: HostIdentity,
  afterLink?: () => void,
): ClaimResult {
  const nonce = crypto.randomBytes(16).toString("hex");
  const content: LockContent = { ...info, nonce, acquiredAt: new Date().toISOString() };
  const tmp = path.join(dir, `${TMP_PREFIX}lock-${process.pid}-${rand()}`);
  const fd = fs.openSync(tmp, "wx", 0o600);
  try {
    try {
      fs.writeFileSync(fd, canonicalJson(content) + "\n");
      fs.fsyncSync(fd);
    } finally {
      fs.closeSync(fd);
    }
    for (let attempt = 0; attempt < 3; attempt++) {
      if (tryLink(tmp, file) === "linked") {
        if (afterLink) afterLink();
        const now = parseLock(readFileOrNull(file) ?? "");
        if (now === null || now.nonce !== nonce) return { ok: false, holder: now, reason: "nonce-mismatch" };
        return { ok: true, nonce };
      }
      const raw = readFileOrNull(file);
      if (raw === null) continue; // released or taken over meanwhile: link again
      const holder = parseLock(raw);
      const state = judgeHolder(holder, me);
      if (!state.stale) return { ok: false, holder, reason: depth === 0 ? state.why : "lost-race" };
      if (depth >= MAX_TAKEOVER_DEPTH) return { ok: false, holder, reason: "lost-race" };
      const staleKey =
        holder !== null && /^[0-9a-f]{8,64}$/.test(holder.nonce) ? holder.nonce : sha256Hex(raw).slice(0, 32);
      const guardFile = path.join(dir, `${TMP_PREFIX}takeover-${staleKey}`);
      const guard = claim(dir, guardFile, info, depth + 1, me);
      if (!guard.ok) return { ok: false, holder: depth === 0 ? holder : guard.holder, reason: "lost-race" };
      try {
        if (readFileOrNull(file) === raw) fs.rmSync(file, { force: true });
      } finally {
        releaseIfOurs(guardFile, guard.nonce);
      }
    }
    return { ok: false, holder: parseLock(readFileOrNull(file) ?? ""), reason: "lost-race" };
  } finally {
    fs.rmSync(tmp, { force: true });
  }
}

export function acquireLock(dir: string, info: WriterInfo, opts: AcquireOptions = {}): HeldLock | NotHeld {
  const lock = lockPath(dir);
  let r: ClaimResult;
  try {
    r = claim(dir, lock, info, 0, (opts.host ?? hostIdentity)(), opts.afterLink);
  } catch (e) {
    return { held: false, holder: null, reason: `error:${(e as NodeJS.ErrnoException).code ?? "unknown"}` };
  }
  if (!r.ok) return { held: false, holder: stripLock(r.holder), reason: r.reason };
  const nonce = r.nonce;
  let released = false;
  return {
    held: true,
    nonce,
    stillHeld(): boolean {
      if (released) return false;
      const cur = readLock(dir);
      return cur !== null && cur.nonce === nonce;
    },
    release(): void {
      if (released) return;
      released = true;
      releaseIfOurs(lock, nonce);
    },
  };
}

/** True when writer.lock names this process (same pid, start token and boot id). */
export function heldByThisProcess(dir: string): boolean {
  const cur = readLock(dir);
  if (!cur) return false;
  const me = selfIdentity();
  return cur.pid === me.pid && cur.start === me.start && cur.bootId === bootId();
}
