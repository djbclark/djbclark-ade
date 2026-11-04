// paseo-checkpoint: read-only recovery verdicts from ade-recovery records.
// Never writes, sweeps, locks, or calls Paseo. Live git goes through the same hardened exec as the plugin.
import * as fs from "node:fs";
import * as path from "node:path";
import type { GitEvidence, Interruption, LiveEvidence, LoadResult, RecoveryRecord, Verdict, VerdictResult } from "./types.ts";
import { loadRecord, listAgents } from "./store.ts";
import { stateBase, stateRoot } from "./state-root.ts";
import { lockHolderAlive } from "./writer-lock.ts";
import { hostIdentity, processAlive, sameHost } from "./host-identity.ts";
import { paseoHome, paseoServerId, readPaseoAgentRecord, type PaseoAgentRecordEvidence } from "./paseo-home.ts";
import { judge } from "./verdict.ts";
import { gitEvidence } from "./git-evidence.ts";

const USAGE = `usage: paseo-checkpoint <command> [options]

Read-only recovery verdicts from the ade-recovery plugin's records (issue 278).

commands:
  list [--json] [--server-id S] [--no-live]
        one line per recorded agent: verdict, state, generation, age
  show AGENT_ID [--json] [--server-id S] [--no-live]
        full verdict, reason codes and evidence for one agent
  -h, --help
        this text

options:
  --json         machine-readable output
  --server-id S  only read the records of Paseo server S
  --no-live      do not run live git against the record's cwd (the verdict then needs review)

exit codes (show): 0 resumable-native, 1 needs-review, 2 do-not-resume, 3 not found, 64 usage error
exit codes (list): 0 ok, 64 usage error

Paseo's own store is read too, read only: <PASEO_HOME>/agents/*/<id>.json (archivedAt set:
do-not-resume, paseo-archived; updatedAt more than 2 s after the record: needs-review,
paseo-record-newer) and the daemon's server id (PASEO_SERVER_ID, else <PASEO_HOME>/server-id;
a mismatch: other-server). Unreadable evidence never blocks by itself (info only).

environment: ADE_STATE_ROOT / XDG_STATE_HOME (state base), PASEO_HOME (default ~/.paseo; a
leading ~ expands and a relative value resolves against the cwd, as Paseo does), PASEO_SERVER_ID
`;

const EXIT: Record<Verdict, number> = { "resumable-native": 0, "needs-review": 1, "do-not-resume": 2 };
const OPEN_PHASES = new Set(["watching", "waiting", "interrupted", "scheduled", "review", "sending", "resumed"]);
const SAFE = /^[A-Za-z0-9_-]{1,128}$/;

interface Opts {
  json: boolean;
  noLive: boolean;
  serverId: string | null;
  positional: string[];
}

class UsageError extends Error {}

function parse(args: string[]): Opts {
  const o: Opts = { json: false, noLive: false, serverId: null, positional: [] };
  for (let i = 0; i < args.length; i++) {
    const a = args[i]!;
    if (a === "--json") o.json = true;
    else if (a === "--no-live") o.noLive = true;
    else if (a === "--server-id") {
      const v = args[++i];
      if (v === undefined || !SAFE.test(v)) throw new UsageError("--server-id needs a value of [A-Za-z0-9_-]{1,128}");
      o.serverId = v;
    } else if (a.startsWith("--server-id=")) {
      const v = a.slice("--server-id=".length);
      if (!SAFE.test(v)) throw new UsageError("--server-id needs a value of [A-Za-z0-9_-]{1,128}");
      o.serverId = v;
    } else if (a.startsWith("-")) throw new UsageError(`unknown option: ${a}`);
    else o.positional.push(a);
  }
  return o;
}

interface Entry {
  serverId: string;
  dir: string;
  name: string;
  load: LoadResult;
}

function serverIds(env: NodeJS.ProcessEnv, only: string | null): string[] {
  if (only) return [only];
  try {
    return fs
      .readdirSync(path.join(stateBase(env), "ade"), { withFileTypes: true })
      .filter((d) => d.isDirectory() && SAFE.test(d.name))
      .map((d) => d.name)
      .sort();
  } catch {
    return [];
  }
}

async function collect(env: NodeJS.ProcessEnv, only: string | null): Promise<Entry[]> {
  const out: Entry[] = [];
  for (const serverId of serverIds(env, only)) {
    const dir = stateRoot(serverId, env);
    let names: string[] = [];
    try {
      names = await listAgents(dir);
    } catch {
      continue;
    }
    for (const name of names) {
      try {
        out.push({ serverId, dir, name, load: await loadRecord(dir, name) });
      } catch (e) {
        out.push({ serverId, dir, name, load: { record: null, source: "none", problems: [`unreadable:${(e as Error).message}`], maxGenerationSeen: 0 } });
      }
    }
  }
  return out;
}

/** Read-only look at session-recovery's state: true when it holds an open record for this agent. */
function recoveryScheduledElsewhere(home: string, agentId: string, sessionId: string | undefined): boolean | null {
  let state: unknown;
  try {
    state = JSON.parse(fs.readFileSync(path.join(home, "plugin-data", "session-recovery", "state.json"), "utf8"));
  } catch {
    return null;
  }
  const records = (state as { records?: unknown } | null)?.records;
  if (!records || typeof records !== "object" || Array.isArray(records)) return null;
  for (const [key, val] of Object.entries(records as Record<string, unknown>)) {
    if (!val || typeof val !== "object") continue;
    const r = val as { id?: unknown; phase?: unknown };
    const id = typeof r.id === "string" ? r.id : key;
    if (id !== agentId && !(sessionId && id === sessionId)) continue;
    if (typeof r.phase === "string" && OPEN_PHASES.has(r.phase)) return true;
  }
  return false;
}

interface Judged {
  entry: Entry;
  result: VerdictResult;
  live: LiveEvidence;
  computed: Interruption | null;
  paseo: PaseoAgentRecordEvidence | null;
}

async function evaluate(entry: Entry, opts: Opts, env: NodeJS.ProcessEnv): Promise<Judged> {
  const rec = entry.load.record;
  const host = hostIdentity();
  const home = paseoHome(env);
  let paseo: PaseoAgentRecordEvidence | null = null;
  let git: GitEvidence | null = null;
  if (rec && !opts.noLive && rec.cwd) git = await gitEvidence(rec.cwd, AbortSignal.timeout(25_000));
  let recordWriterAlive: boolean | null = null;
  if (rec && sameHost(rec, host)) recordWriterAlive = (await processAlive(rec.writer)) ?? null;
  const live: LiveEvidence = {
    now: Date.now(),
    host,
    git,
    writerAlive: await lockHolderAlive(entry.dir),
    recordWriterAlive,
    recoveryScheduledElsewhere: rec ? recoveryScheduledElsewhere(home, rec.paseoAgentId, rec.persistence?.sessionId) : null,
    serverId: entry.serverId,
  };
  if (rec) {
    const stored = readPaseoAgentRecord(home, rec.paseoAgentId);
    live.paseoArchived = stored === null ? null : stored.archivedAt !== null;
    live.paseoUpdatedAt = stored === null ? null : stored.updatedAt;
    live.paseoServerId = paseoServerId(home, env);
    paseo = stored;
  }
  let load = entry.load;
  let computed: Interruption | null = null;
  if (rec && rec.state === "turn-in-flight" && recordWriterAlive === false) {
    const last = rec.turns?.[rec.turns.length - 1];
    computed = {
      detectedAt: new Date(live.now).toISOString(),
      evidence: "writer-dead",
      turnKey: last?.turnKey ?? null,
      detail: `record writer pid ${rec.writer.pid} is not alive`,
    };
    const patched: RecoveryRecord = { ...rec, interruptions: [...(rec.interruptions ?? []), computed] };
    load = { ...load, record: patched };
  }
  const result = await judge(load, live);
  return { entry, result, live, computed, paseo };
}

function summary(j: Judged) {
  const rec = j.entry.load.record;
  const last = rec?.turns?.[rec.turns.length - 1] ?? null;
  return {
    serverId: j.entry.serverId,
    agentId: rec?.paseoAgentId ?? j.entry.name,
    verdict: j.result.verdict,
    reasons: j.result.reasons,
    info: j.result.info,
    generation: rec?.generation ?? null,
    source: j.entry.load.source,
    problems: j.entry.load.problems,
    state: rec?.state ?? null,
    writtenAt: rec?.writtenAt ?? null,
    provider: rec?.provider ?? null,
    cwd: rec?.cwd ?? null,
    lastTurn: last,
    interruptions: [...(rec?.interruptions ?? []), ...(j.computed ? [j.computed] : [])],
    liveGit: j.live.git ? { head: j.live.git.head, branch: j.live.git.branch, errors: j.live.git.errors } : null,
    writerAlive: j.live.writerAlive,
    recordWriterAlive: j.live.recordWriterAlive,
    recoveryScheduledElsewhere: j.live.recoveryScheduledElsewhere,
    paseoRecord: j.paseo,
    paseoServerId: j.live.paseoServerId ?? null,
  };
}

function age(rec: RecoveryRecord | null, now: number): string {
  if (!rec) return "-";
  const t = Date.parse(rec.writtenAt);
  if (Number.isNaN(t)) return "?";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 90) return `${s}s`;
  if (s < 5400) return `${Math.round(s / 60)}m`;
  if (s < 129600) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}

async function cmdList(opts: Opts, env: NodeJS.ProcessEnv): Promise<number> {
  if (opts.positional.length) throw new UsageError("list takes no arguments");
  const entries = await collect(env, opts.serverId);
  const judged: Judged[] = [];
  for (const e of entries) judged.push(await evaluate(e, opts, env));
  if (opts.json) {
    process.stdout.write(JSON.stringify(judged.map(summary), null, 2) + "\n");
    return 0;
  }
  if (judged.length === 0) {
    process.stdout.write("no ade-recovery records found\n");
    return 0;
  }
  for (const j of judged) {
    const s = summary(j);
    const why = j.result.reasons.length ? ` [${j.result.reasons.join(",")}]` : "";
    process.stdout.write(
      `${s.verdict.padEnd(16)} ${String(s.state ?? "-").padEnd(14)} gen ${String(s.generation ?? "-").padEnd(4)} ${age(j.entry.load.record, j.live.now).padEnd(5)} ${s.serverId} ${s.agentId}${why}\n`,
    );
  }
  return 0;
}

async function cmdShow(opts: Opts, env: NodeJS.ProcessEnv): Promise<number> {
  if (opts.positional.length !== 1) throw new UsageError("show needs exactly one AGENT_ID");
  const id = opts.positional[0]!;
  const entries = await collect(env, opts.serverId);
  const hit = entries.find((e) => e.load.record?.paseoAgentId === id) ?? entries.find((e) => e.name === id);
  if (!hit) {
    process.stderr.write(`paseo-checkpoint: no record for agent ${id}\n`);
    return 3;
  }
  const j = await evaluate(hit, opts, env);
  const s = summary(j);
  if (opts.json) {
    process.stdout.write(JSON.stringify(s, null, 2) + "\n");
  } else {
    const lines = [
      `agent      ${s.agentId}`,
      `server     ${s.serverId}`,
      `verdict    ${s.verdict}`,
      `reasons    ${s.reasons.join(", ") || "-"}`,
      `info       ${s.info.join(", ") || "-"}`,
      `state      ${s.state ?? "-"}  generation ${s.generation ?? "-"}  source ${s.source}`,
      `provider   ${s.provider ?? "-"}  cwd ${s.cwd ?? "-"}`,
      `written    ${s.writtenAt ?? "-"} (${age(hit.load.record, j.live.now)} ago)`,
      `problems   ${s.problems.join(", ") || "-"}`,
      `live git   ${s.liveGit ? `head ${s.liveGit.head ?? "-"} branch ${s.liveGit.branch ?? "-"} errors ${s.liveGit.errors.join(",") || "-"}` : "not captured"}`,
      `writer     lock holder alive ${s.writerAlive}, record writer alive ${s.recordWriterAlive}`,
      `recovery   scheduled elsewhere ${s.recoveryScheduledElsewhere}`,
      `paseo      ${s.paseoRecord ? `archivedAt ${s.paseoRecord.archivedAt ?? "-"} updatedAt ${s.paseoRecord.updatedAt ?? "-"} (${s.paseoRecord.updatedAtSource})` : "stored record unavailable"}, server id ${s.paseoServerId ?? "unavailable"}`,
      `interrupts ${s.interruptions.map((i) => i.evidence).join(", ") || "-"}`,
    ];
    process.stdout.write(lines.join("\n") + "\n");
  }
  return EXIT[j.result.verdict];
}

async function main(argv: string[], env: NodeJS.ProcessEnv): Promise<number> {
  const [cmd, ...rest] = argv;
  if (cmd === undefined || cmd === "-h" || cmd === "--help" || cmd === "help") {
    (cmd === undefined ? process.stderr : process.stdout).write(USAGE);
    return cmd === undefined ? 64 : 0;
  }
  if (rest.includes("-h") || rest.includes("--help")) {
    process.stdout.write(USAGE);
    return 0;
  }
  try {
    if (cmd === "list") return await cmdList(parse(rest), env);
    if (cmd === "show") return await cmdShow(parse(rest), env);
    throw new UsageError(`unknown command: ${cmd}`);
  } catch (e) {
    if (e instanceof UsageError) {
      process.stderr.write(`paseo-checkpoint: ${e.message}\n\n${USAGE}`);
      return 64;
    }
    process.stderr.write(`paseo-checkpoint: ${(e as Error).message}\n`);
    return 70;
  }
}

process.exitCode = await main(process.argv.slice(2), process.env);
