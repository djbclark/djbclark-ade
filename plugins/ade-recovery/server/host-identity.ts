// Host and process identity that survives PID reuse (pid + start token) and reboots (boot id).
// Linux reads /proc; macOS and other platforms use `ps -o lstart=` and `sysctl kern.bootsessionuuid`.
// Anything that cannot be read is null; callers record it as missing telemetry.

import fs from "node:fs";
import os from "node:os";
import { execFileSync } from "node:child_process";
import type { HostIdentity, ProcessIdentity } from "./types.ts";

const SUBPROCESS_TIMEOUT_MS = 2000;

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
    for (const bin of ["/usr/sbin/sysctl", "sysctl"]) {
      try {
        const out = execFileSync(bin, ["-n", "kern.bootsessionuuid"], {
          env: minimalEnv(),
          timeout: SUBPROCESS_TIMEOUT_MS,
          encoding: "utf8",
          stdio: ["ignore", "pipe", "ignore"],
          maxBuffer: 64 * 1024,
        }).trim();
        if (out) {
          value = out;
          break;
        }
      } catch {
        // try the next location
      }
    }
  }
  bootCache = { value };
  return value;
}

export function hostIdentity(): HostIdentity {
  return { host: os.hostname(), bootId: bootId(), platform: process.platform };
}

/** This process (the plugin child). */
export function selfIdentity(): ProcessIdentity {
  return { pid: process.pid, start: processStart(process.pid) };
}

/** The Paseo daemon forks plugin children, so the daemon is process.ppid. */
export function daemonIdentity(): ProcessIdentity {
  return { pid: process.ppid, start: processStart(process.ppid) };
}
