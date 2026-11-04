// Shared contract for the ade-recovery plugin (issue 278, docs/checkpoint.md section G).
// Type-only module: every other module imports from here with `import type`, so Node's
// type stripping runs the code and tests with no npm install.

export const SCHEMA = "ade.recovery.passive/v1";

/** Minimal structural view of the Paseo hook payload agent (upstream PluginHookAgent). */
export interface HookAgent {
  id: string;
  workspaceId: string | null;
  parentAgentId: string | null;
  provider: string;
  cwd: string;
  title: string | null;
}

export type TurnOutcome =
  | { kind: "completed" }
  | { kind: "failed"; error: { message: string; code?: string } }
  | { kind: "canceled"; reason: string };

/** The slice of the Paseo SDK this plugin calls (read-only calls only). */
export interface PaseoLike {
  hosts: { list(): Promise<{ self?: { serverId?: string } | null } & Record<string, unknown>> };
  agents: {
    // The real SDK resolves to `{agent, project} | null`; server/snapshot.ts normalises it.
    ref(id: string): { refresh(): Promise<unknown> };
  };
}

export interface AgentSnapshot {
  id: string;
  status?: string; // e.g. initializing|idle|running|error|closed
  activeTurnId?: string | null;
  archivedAt?: string | null;
  labels?: Record<string, string>;
  persistence?: { provider?: string; sessionId?: string; nativeHandle?: unknown } | null;
}

export interface HostIdentity {
  host: string;
  bootId: string | null; // Linux /proc/sys/kernel/random/boot_id, macOS kern.bootsessionuuid
  platform: string; // process.platform
}

/** A process identity that survives PID reuse: pid plus its start token. */
export interface ProcessIdentity {
  pid: number;
  start: string | null; // Linux /proc/<pid>/stat field 22; macOS `ps -o lstart=`
}

export interface WriterInfo extends ProcessIdentity {
  plugin: "ade-recovery";
  pluginVersion: string;
  daemon: ProcessIdentity; // process.ppid and its start token
  host: string;
  bootId: string | null;
}

export interface GitEvidence {
  capturedAt: string;
  repoTop: string | null;
  isLinkedWorktree: boolean | null;
  branch: string | null;
  head: string | null;
  base: { ref: string; sha: string; method: "merge-base-origin-head" | "recorded-at-create" } | null;
  /** sha256 over (path, blob id from `hash-object --no-filters`) of tracked changes vs HEAD. */
  trackedFingerprint: string | null;
  trackedChanged: number | null;
  trackedPaths: string[]; // capped, redacted names
  untrackedCount: number | null;
  untrackedPaths: string[]; // capped, redacted names
  /** sha256 over (path, size, mtimeMs) of untracked files; contents are never read. */
  untrackedFingerprint: string | null;
  truncated: boolean;
  errors: string[];
}

export type InterruptionEvidence =
  | "daemon-restart"
  | "boot-id-changed"
  | "closed-without-turn-end"
  | "canceled-during-shutdown"
  | "writer-dead"
  | "agent-missing";

export interface Interruption {
  detectedAt: string;
  evidence: InterruptionEvidence;
  turnKey: string | null;
  detail: string;
}

export interface TurnRecord {
  turnKey: string; // "<daemonInstance>:<seq>": turnId may be null or repeat after reopen
  turnId: string | null;
  startedAt: string;
  endedAt: string | null;
  outcome: { kind: "completed" | "failed" | "canceled" | "unknown"; code?: string; message?: string } | null;
  duringShutdown: boolean;
}

export type LifecycleState = "idle" | "turn-in-flight" | "closed" | "archived" | "interrupted";

export interface MissingTelemetry {
  field: string;
  reason: string;
  at: string;
}

export interface RecoveryRecord {
  schema: typeof SCHEMA;
  generation: number;
  writtenAt: string;
  integrity: { alg: "sha256"; digest: string }; // over canonical JSON of all other fields
  writer: WriterInfo;
  // identity (required)
  serverId: string;
  paseoAgentId: string;
  provider: string;
  cwd: string;
  host: string;
  bootId: string | null;
  platform: string;
  // identity (optional)
  cwdRealpath?: string | null;
  workspaceId?: string | null;
  parentAgentId?: string | null;
  persistence?: { provider?: string; sessionId?: string; nativeHandleSha256?: string } | null;
  // lifecycle
  state?: LifecycleState;
  daemonInstance?: string; // "<daemon pid>:<daemon start>:<bootId>"
  closedAt?: string | null;
  archivedAt?: string | null;
  turns?: TurnRecord[]; // last 20
  git?: { baseAtCreate?: GitEvidence | null; atTurnStart?: GitEvidence | null; latest?: GitEvidence | null };
  interruptions?: Interruption[]; // history, last 20; a later turn never clears it
  missingTelemetry?: MissingTelemetry[];
}

export type Verdict = "resumable-native" | "needs-review" | "do-not-resume";

export interface VerdictResult {
  verdict: Verdict;
  reasons: string[]; // blocking reason codes
  info: string[]; // informational codes (boot-id-changed, record-age:<s>, ...)
}

/** Live evidence the reader may add when judging a record (CLI computes it). */
export interface LiveEvidence {
  now: number; // ms epoch
  host: HostIdentity;
  git: GitEvidence | null;
  writerAlive: boolean | null; // the lock holder named in writer.lock is alive (pid+start)
  recordWriterAlive: boolean | null; // the writer named in the record is alive
  recoveryScheduledElsewhere: boolean | null; // session-recovery has an open record for the agent
  serverId?: string | null; // expected server id, when the caller knows it
}

export interface LoadResult {
  record: RecoveryRecord | null;
  source: "current" | "prev" | "none";
  problems: string[]; // e.g. corrupt-fell-back-to-prev, corrupt-no-valid-generation, unknown-schema
  maxGenerationSeen: number;
}
