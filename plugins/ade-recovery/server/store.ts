// Atomic generation store: <key>.json (current) and <key>.prev.json (the previous valid generation).
// Write: tmp (wx, 0600) -> write -> fsync -> [current known valid: link current to a random
// .tmp-prev-* name (copy+fsync where links are refused) -> rename to prev] -> rename tmp to current
// -> fsync dir. A corrupt current never overwrites a good prev; no fixed temp name can collide
// (finding 8). fsync ordering is not verified by the tests (it needs dm-flakey or LazyFS), and
// macOS fsync does not flush the drive cache (no F_FULLFSYNC from Node). With WriteOptions.owner,
// each rename is preceded by the caller's ownership check; a failed check publishes nothing.

import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import type { LoadResult, RecoveryRecord } from "./types.ts";
import { MAX_RECORD_BYTES, SCHEMA, TMP_PREFIX, TMP_SWEEP_AGE_MS } from "./constants.ts";
import type { CrashPoint } from "./constants.ts";
import { canonicalJson } from "./canonical.ts";
import { generationHint, sealRecord, validateRecord } from "./record.ts";
import { agentFileName, isSafeComponent } from "./state-root.ts";
import { heldByThisProcess } from "./writer-lock.ts";

/** What a caller hands writeGeneration: the store assigns generation, writtenAt (if absent) and integrity. */
export type RecordDraft = Omit<RecoveryRecord, "integrity" | "generation" | "writtenAt"> & {
  generation?: number;
  writtenAt?: string;
  integrity?: unknown;
};

export interface StoreIo {
  /** Writes the whole buffer to an open file (injectable to simulate ENOSPC). */
  write(fh: fsp.FileHandle, data: Buffer): Promise<void>;
  /** Hard-links current to the prev temp name (injectable to simulate a filesystem without links). */
  link(existing: string, newPath: string): Promise<void>;
}

export interface WriteOptions {
  io?: Partial<StoreIo>;
  /**
   * Ownership check, called before the write starts and again immediately before each rename (prev,
   * then current). False (or a throw) abandons the write with code EWRITERLOST: the temp files are
   * removed and nothing is published. A writer that lost writer.lock, or that is closing past its
   * deadline, must never rename a stale generation over a newer writer's record (PR 290, Codex P2).
   */
  owner?: () => boolean;
}

const defaultIo: StoreIo = {
  async write(fh, data) {
    await fh.writeFile(data);
  },
  link: (existing, newPath) => fsp.link(existing, newPath),
};

const LINK_FALLBACK = new Set(["EPERM", "ENOTSUP", "EOPNOTSUPP", "EXDEV", "ENOSYS", "EMLINK"]);
const DIR_FSYNC_IGNORED = new Set(["EISDIR", "EINVAL", "EBADF", "EPERM", "ENOTSUP"]);

function crash(point: CrashPoint): void {
  if (process.env.ADE_RECOVERY_TEST === "1" && process.env.ADE_RECOVERY_CRASH_AT === point) {
    process.kill(process.pid, "SIGKILL");
    // SIGKILL to self is delivered before user code continues; block in case delivery lags.
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 10000);
  }
}

function rand(): string {
  return crypto.randomBytes(6).toString("hex");
}

function paths(dir: string, agentId: string): { key: string; current: string; prev: string } {
  const key = agentFileName(agentId);
  return { key, current: path.join(dir, `${key}.json`), prev: path.join(dir, `${key}.prev.json`) };
}

type Slot =
  | { status: "missing"; generation: 0 }
  | { status: "valid"; record: RecoveryRecord; generation: number }
  | { status: "invalid"; problem: string; generation: number };

function readSlot(file: string): Slot {
  let fd: number;
  try {
    fd = fs.openSync(file, "r");
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") return { status: "missing", generation: 0 };
    return { status: "invalid", problem: `unreadable:${(e as NodeJS.ErrnoException).code ?? "unknown"}`, generation: 0 };
  }
  try {
    const st = fs.fstatSync(fd);
    if (!st.isFile()) return { status: "invalid", problem: "not-a-file", generation: 0 };
    // Read at most cap+1 bytes: enough to tell too-large, and to recover a generation hint.
    const buf = Buffer.alloc(Math.min(st.size, MAX_RECORD_BYTES + 1));
    let off = 0;
    while (off < buf.length) {
      const n = fs.readSync(fd, buf, off, buf.length - off, off);
      if (n === 0) break;
      off += n;
    }
    const raw = buf.subarray(0, off);
    if (st.size > MAX_RECORD_BYTES) {
      return { status: "invalid", problem: "too-large", generation: generationHint(raw.toString("utf8")) };
    }
    const v = validateRecord(raw);
    if (v.ok) return { status: "valid", record: v.record, generation: v.record.generation };
    return { status: "invalid", problem: v.problem, generation: generationHint(raw.toString("utf8")) };
  } catch (e) {
    return { status: "invalid", problem: `unreadable:${(e as NodeJS.ErrnoException).code ?? "unknown"}`, generation: 0 };
  } finally {
    fs.closeSync(fd);
  }
}

/**
 * Load an agent's record. current valid -> source current; else prev valid -> source prev with
 * `corrupt-fell-back-to-prev`; else `corrupt-no-valid-generation`. An unknown schema in current
 * gives `unknown-schema` and no record (a newer writer owns it; its prev would mislead). Detail
 * entries `current:<problem>` / `prev:<problem>` say why a file was rejected. Nothing on disk:
 * record null, source none, no problems.
 */
export function loadRecord(dir: string, agentId: string): LoadResult {
  const p = paths(dir, agentId);
  const cur = readSlot(p.current);
  const prev = readSlot(p.prev);
  const maxGenerationSeen = Math.max(cur.generation, prev.generation);
  if (cur.status === "valid") return { record: cur.record, source: "current", problems: [], maxGenerationSeen };
  const problems: string[] = [];
  if (cur.status === "invalid") {
    if (cur.problem === "unknown-schema") {
      return { record: null, source: "none", problems: ["unknown-schema"], maxGenerationSeen };
    }
    problems.push(`current:${cur.problem}`);
  } else if (prev.status !== "missing") {
    problems.push("current:missing");
  }
  if (prev.status === "valid") {
    problems.push("corrupt-fell-back-to-prev");
    return { record: prev.record, source: "prev", problems, maxGenerationSeen };
  }
  if (prev.status === "invalid") {
    problems.push(prev.problem === "unknown-schema" ? "unknown-schema" : `prev:${prev.problem}`);
  }
  if (cur.status === "missing" && prev.status === "missing") {
    return { record: null, source: "none", problems: [], maxGenerationSeen };
  }
  if (!problems.includes("unknown-schema")) problems.push("corrupt-no-valid-generation");
  return { record: null, source: "none", problems, maxGenerationSeen };
}

/** File keys of every agent with a current or prev file (usable as loadRecord's agentId). */
export function listAgents(dir: string): string[] {
  let names: string[];
  try {
    names = fs.readdirSync(dir);
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw e;
  }
  const keys = new Set<string>();
  for (const n of names) {
    const m = /^(.+?)(\.prev)?\.json$/.exec(n);
    if (m && isSafeComponent(m[1])) keys.add(m[1]);
  }
  return [...keys].sort();
}

/**
 * Remove `.tmp-*` files older than TMP_SWEEP_AGE_MS. Only the writer-lock holder sweeps (the CLI
 * never does): when this process does not hold writer.lock it removes nothing.
 */
export function sweepTmp(
  dir: string,
  opts: { now?: number; maxAgeMs?: number } = {},
): { removed: string[]; skipped: "not-lock-holder" | null } {
  if (!heldByThisProcess(dir)) return { removed: [], skipped: "not-lock-holder" };
  const now = opts.now ?? Date.now();
  const maxAge = opts.maxAgeMs ?? TMP_SWEEP_AGE_MS;
  const removed: string[] = [];
  let names: string[];
  try {
    names = fs.readdirSync(dir);
  } catch {
    return { removed, skipped: null };
  }
  for (const n of names) {
    if (!n.startsWith(TMP_PREFIX)) continue;
    const f = path.join(dir, n);
    try {
      const st = fs.lstatSync(f);
      if (!st.isFile() && !st.isSymbolicLink()) continue;
      if (now - st.mtimeMs <= maxAge) continue;
      fs.unlinkSync(f);
      removed.push(n);
    } catch {
      // raced with another removal; ignore
    }
  }
  return { removed: removed.sort(), skipped: null };
}

interface CacheEntry {
  maxGen: number;
  currentValid: boolean | null; // null: unknown, re-inspect on the next write
}
const cache = new Map<string, CacheEntry>();
const chains = new Map<string, Promise<unknown>>();

/** Forget cached write state (tests; or after another process may have written). */
export function resetStoreCache(): void {
  cache.clear();
}

async function fsyncDir(dir: string): Promise<void> {
  let fh: fsp.FileHandle | null = null;
  try {
    fh = await fsp.open(dir, "r");
    await fh.sync();
  } catch (e) {
    if (!DIR_FSYNC_IGNORED.has((e as NodeJS.ErrnoException).code ?? "")) throw e;
  } finally {
    if (fh) await fh.close().catch(() => {});
  }
}

async function copyToPrevTmp(io: StoreIo, current: string, tmpPrev: string): Promise<void> {
  try {
    await io.link(current, tmpPrev);
    return;
  } catch (e) {
    if (!LINK_FALLBACK.has((e as NodeJS.ErrnoException).code ?? "")) throw e;
  }
  await fsp.copyFile(current, tmpPrev, fs.constants.COPYFILE_EXCL);
  const fh = await fsp.open(tmpPrev, "r+");
  try {
    await fh.chmod(0o600);
    await fh.sync();
  } finally {
    await fh.close();
  }
}

function writerLost(): Error {
  const err = new Error("this writer no longer owns the state root; generation not published");
  (err as NodeJS.ErrnoException).code = "EWRITERLOST";
  return err;
}

function checkOwner(opts: WriteOptions): void {
  if (!opts.owner) return;
  let ok = false;
  try {
    ok = opts.owner() === true;
  } catch {
    ok = false;
  }
  if (!ok) throw writerLost();
}

function tooLarge(bytes: number): Error {
  const err = new Error(`record is ${bytes} bytes, over the ${MAX_RECORD_BYTES}-byte cap; previous generation kept`);
  (err as NodeJS.ErrnoException).code = "ERECORDTOOLARGE";
  return err;
}

async function writeOnce(dir: string, agentId: string, draft: RecordDraft, opts: WriteOptions): Promise<RecoveryRecord> {
  const io: StoreIo = { ...defaultIo, ...(opts.io ?? {}) };
  if (draft.paseoAgentId !== agentId) {
    throw new Error(`record paseoAgentId ${JSON.stringify(draft.paseoAgentId)} does not match ${JSON.stringify(agentId)}`);
  }
  checkOwner(opts);
  const p = paths(dir, agentId);
  const ck = path.resolve(dir) + "\0" + p.key;
  let entry = cache.get(ck);
  if (!entry || entry.currentValid === null) {
    const cur = readSlot(p.current);
    if (cur.status === "invalid" && cur.problem === "unknown-schema") {
      const err = new Error(`${p.current} holds an unknown schema (a newer writer?); refusing to overwrite`);
      (err as NodeJS.ErrnoException).code = "EUNKNOWNSCHEMA";
      throw err;
    }
    const prev = readSlot(p.prev);
    entry = {
      maxGen: Math.max(entry?.maxGen ?? 0, cur.generation, prev.generation),
      currentValid: cur.status === "valid",
    };
    cache.set(ck, entry);
  }
  const generation = entry.maxGen + 1;
  const { integrity: _i, generation: _g, ...rest } = draft;
  const sealed = sealRecord({
    ...rest,
    schema: SCHEMA,
    generation,
    writtenAt: typeof draft.writtenAt === "string" && draft.writtenAt ? draft.writtenAt : new Date().toISOString(),
  } as Omit<RecoveryRecord, "integrity">);
  const data = Buffer.from(canonicalJson(sealed) + "\n", "utf8");
  if (data.length > MAX_RECORD_BYTES) throw tooLarge(data.length);

  const tmp = path.join(dir, `${TMP_PREFIX}${p.key}-${process.pid}-${rand()}`);
  const tmpPrev = path.join(dir, `${TMP_PREFIX}prev-${process.pid}-${rand()}`);
  let renamed = false;
  // From here on the generation number is spent, whether or not the write lands.
  entry.maxGen = generation;
  try {
    const fh = await fsp.open(tmp, "wx", 0o600);
    try {
      await fh.chmod(0o600);
      await io.write(fh, data);
      crash("after-tmp-write");
      await fh.sync();
      crash("after-tmp-sync");
    } finally {
      await fh.close();
    }
    checkOwner(opts);
    if (entry.currentValid) {
      let copied = true;
      try {
        await copyToPrevTmp(io, p.current, tmpPrev);
      } catch (e) {
        if ((e as NodeJS.ErrnoException).code !== "ENOENT") throw e;
        copied = false; // current vanished: nothing to preserve
      }
      if (copied) {
        crash("after-prev-link");
        checkOwner(opts);
        await fsp.rename(tmpPrev, p.prev);
        // POSIX rename() does nothing when both names already link the same inode (prev and
        // current share one after a crash at after-prev-rename), leaving tmpPrev behind.
        await fsp.rm(tmpPrev, { force: true });
        crash("after-prev-rename");
      }
    }
    checkOwner(opts);
    await fsp.rename(tmp, p.current);
    renamed = true;
    entry.currentValid = true;
    crash("after-rename");
    await fsyncDir(dir);
    return sealed;
  } catch (e) {
    if (!renamed) {
      entry.currentValid = null; // unknown: re-inspect before the next write
      await fsp.rm(tmp, { force: true }).catch(() => {});
    }
    await fsp.rm(tmpPrev, { force: true }).catch(() => {});
    throw e;
  }
}

/**
 * Write the next generation of an agent's record. Generation = max(readable generation, highest
 * generation seen, including corrupt files and failed writes) + 1. Over MAX_RECORD_BYTES: rejects
 * with code ERECORDTOOLARGE. ENOSPC and other I/O errors reject; the previous generation stays
 * intact. Calls for the same agent in this process are serialized. With `opts.owner`, a write whose
 * owner check fails before a rename rejects with code EWRITERLOST and publishes nothing.
 */
export function writeGeneration(
  dir: string,
  agentId: string,
  rec: RecordDraft | RecoveryRecord,
  opts: WriteOptions = {},
): Promise<RecoveryRecord> {
  const ck = path.resolve(dir) + "\0" + agentFileName(agentId);
  const prior = chains.get(ck) ?? Promise.resolve();
  const run = prior.then(
    () => writeOnce(dir, agentId, rec as RecordDraft, opts),
    () => writeOnce(dir, agentId, rec as RecordDraft, opts),
  );
  const settled = run.catch(() => {});
  chains.set(ck, settled);
  void settled.then(() => {
    if (chains.get(ck) === settled) chains.delete(ck);
  });
  return run;
}
