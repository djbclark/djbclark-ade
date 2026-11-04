// Host and process identity that survives PID reuse (pid + start token) and reboots (boot id).
// Linux reads /proc; macOS and other platforms use `ps -o lstart=` and `sysctl kern.bootsessionuuid`.
// The machine id (Linux /etc/machine-id, macOS IOPlatformUUID) is the stable host key; the
// hostname is display text and is compared only when either side has no machine id.
// Anything that cannot be read is null; callers record it as missing telemetry.

import fs from "node:fs";
import os from "node:os";
import { execFileSync } from "node:child_process";
import type { HostIdentity, ProcessIdentity } from "./types.ts";

const SUBPROCESS_TIMEOUT_MS = 2000;
/** Total budget for one identity probe across all its candidate binaries (not per binary). */
export const PROBE_BUDGET_MS = 2000;

export type ProbeRunner = (bin: string, args: string[], timeoutMs: number) => string;

const defaultRunner: ProbeRunner = (bin, args, timeoutMs) =>
  execFileSync(bin, args, {
    env: minimalEnv(),
    timeout: timeoutMs,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"],
    maxBuffer: 1024 * 1024,
  });

/**
 * The first candidate binary whose output `parse` accepts, under ONE deadline of `budgetMs` for
 * all of them: each run gets only the time left, and none starts once it is spent. The callers
 * cache the result, so a probe runs at most once per process (macOS ioreg, sysctl).
 */
export function probeFirst(
  bins: readonly string[],
  args: string[],
  parse: (out: string) => string | null,
  budgetMs: number = PROBE_BUDGET_MS,
  run: ProbeRunner = defaultRunner,
  now: () => number = Date.now,
): string | null {
  const deadline = now() + budgetMs;
  for (const bin of bins) {
    const left = deadline - now();
    if (left <= 0) break;
    try {
      const v = parse(run(bin, args, left));
      if (v) return v;
    } catch {
      // timeout, ENOENT or a non-zero exit: try the next location while time is left
    }
  }
  return null;
}

function validPid(pid: unknown): pid is number {
  return typeof pid === "number" && Number.isSafeInteger(pid) && pid >= 1;
}

function minimalEnv(): NodeJS.ProcessEnv {
  return { PATH: process.env.PATH || "/usr/bin:/bin:/usr/sbin:/sbin", LC_ALL: "C" };
}

/** Field 22 (starttime, clock ticks since boot) of a /proc/<pid>/stat line; parsed after the LAST ')'. */
export function parseProcStatStart(stat: string): string | null {
  const close = stat.lastIndexOf(")");
  if (close < 0) return null;
  const fields = stat.slice(close + 1).trim().split(/\s+/);
  // fields[0] is field 3 (state), so field 22 is fields[19].
  const start = fields[19];
  return start !== undefined && /^\d+$/.test(start) ? start : null;
}

/** The `ps -o lstart= -p PID` token (macOS path; also works with Linux procps). */
export function processStartViaPs(pid: number): string | null {
  if (!validPid(pid)) return null;
  try {
    const out = execFileSync("ps", ["-o", "lstart=", "-p", String(pid)], {
      env: minimalEnv(),
      timeout: SUBPROCESS_TIMEOUT_MS,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
      maxBuffer: 64 * 1024,
    });
    const tok = out.trim().replace(/\s+/g, " ");
    return tok === "" ? null : tok;
  } catch {
    return null; // ps exits 1 for a missing pid; timeout or ENOENT also land here
  }
}

let procUsable: boolean | null = null;
function procAvailable(): boolean {
  if (procUsable === null) {
    try {
      procUsable = parseProcStatStart(fs.readFileSync("/proc/self/stat", "utf8")) !== null;
    } catch {
      procUsable = false;
    }
  }
  return procUsable;
}

/** Start token of a process, or null when it does not exist or cannot be read. */
export function processStart(pid: number): string | null {
  if (!validPid(pid)) return null;
  if (process.platform === "linux" && procAvailable()) {
    try {
      return parseProcStatStart(fs.readFileSync(`/proc/${pid}/stat`, "utf8"));
    } catch {
      return null;
    }
  }
  return processStartViaPs(pid);
}

/**
 * Is this exact process (pid AND start token) alive?
 * false: no such pid (ESRCH), or the pid now belongs to a process with a different start token.
 * null: the pid exists but identity cannot be confirmed (start unknown on either side).
 */
export function processAlive(id: ProcessIdentity): boolean | null {
  if (!id || !validPid(id.pid)) return false;
  try {
    process.kill(id.pid, 0);
  } catch (e) {
    const code = (e as NodeJS.ErrnoException).code;
    if (code === "ESRCH") return false;
    if (code !== "EPERM") return null; // EPERM: exists, owned by someone else
  }
  if (id.start === null || id.start === undefined) return null;
  const now = processStart(id.pid);
  if (now === null) return null;
  return now === id.start;
}

let bootCache: { value: string | null } | null = null;

export function bootId(): string | null {
  if (bootCache) return bootCache.value;
  let value: string | null = null;
  if (process.platform === "linux") {
    try {
      value = fs.readFileSync("/proc/sys/kernel/random/boot_id", "utf8").trim() || null;
    } catch {
      value = null;
    }
  } else if (process.platform === "darwin") {
    value = probeFirst(["/usr/sbin/sysctl", "sysctl"], ["-n", "kern.bootsessionuuid"], (out) => out.trim() || null);
  }
  bootCache = { value };
  return value;
}

const MACHINE_ID = /^[A-Za-z0-9-]{8,128}$/;
export const LINUX_MACHINE_ID_FILES = ["/etc/machine-id", "/var/lib/dbus/machine-id"] as const;

/** First valid machine id in `files` (systemd writes "uninitialized" before first boot completes). */
export function machineIdFromFiles(files: readonly string[]): string | null {
  for (const f of files) {
    try {
      const v = fs.readFileSync(f, "utf8").trim();
      if (v !== "uninitialized" && MACHINE_ID.test(v)) return v.toLowerCase();
    } catch {
      // try the next file
    }
  }
  return null;
}

/** IOPlatformUUID from `ioreg -rd1 -c IOPlatformExpertDevice` output, or null. */
export function parseIoregPlatformUuid(out: string): string | null {
  const m = /"IOPlatformUUID"\s*=\s*"([^"]+)"/.exec(out);
  if (!m) return null;
  const v = m[1]!.trim();
  return MACHINE_ID.test(v) ? v.toUpperCase() : null;
}

let machineCache: { value: string | null } | null = null;

export function machineId(): string | null {
  if (machineCache) return machineCache.value;
  let value: string | null = null;
  if (process.platform === "linux") {
    value = machineIdFromFiles(LINUX_MACHINE_ID_FILES);
  } else if (process.platform === "darwin") {
    // One 2 s budget for both locations (it was 2 s each), run once and cached.
    value = probeFirst(["/usr/sbin/ioreg", "ioreg"], ["-rd1", "-c", "IOPlatformExpertDevice"], parseIoregPlatformUuid);
  }
  machineCache = { value };
  return value;
}

export function hostIdentity(): HostIdentity {
  return { host: os.hostname(), bootId: bootId(), platform: process.platform, machineId: machineId() };
}

/**
 * Same machine? Machine ids decide when both sides have one; the hostname is the fallback only
 * when either is missing (an old record or lock, or a host with no readable id).
 */
export function sameHost(
  a: { host?: unknown; machineId?: unknown } | null | undefined,
  b: { host?: unknown; machineId?: unknown } | null | undefined,
): boolean {
  if (!a || !b) return false;
  const ma = typeof a.machineId === "string" && a.machineId !== "" ? a.machineId.toLowerCase() : null;
  const mb = typeof b.machineId === "string" && b.machineId !== "" ? b.machineId.toLowerCase() : null;
  if (ma !== null && mb !== null) return ma === mb;
  return typeof a.host === "string" && a.host !== "" && a.host === b.host;
}

/** This process (the plugin child). */
export function selfIdentity(): ProcessIdentity {
  return { pid: process.pid, start: processStart(process.pid) };
}

/** The Paseo daemon forks plugin children, so the daemon is process.ppid. */
export function daemonIdentity(): ProcessIdentity {
  return { pid: process.ppid, start: processStart(process.ppid) };
}
