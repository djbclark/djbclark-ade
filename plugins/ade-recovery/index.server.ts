// ade-recovery: passive recovery evidence for interrupted agents (issue 278).
//
// Registers EXACTLY five notification hooks. It never registers `agent.open.before`:
// declaring that hook makes Paseo reload every idle agent whenever this plugin starts or
// reloads (critique finding 11). Structural types only; no @getpaseo/* import, so Node's
// type stripping runs it with no npm install.

import fs from "node:fs";
import path from "node:path";
import type { HookAgent, PaseoLike, TurnOutcome } from "./server/types.ts";
import { Capture, type CaptureDeps } from "./server/capture.ts";
import { canonicalJson, sha256Hex } from "./server/canonical.ts";
import { gitEvidence } from "./server/git-evidence.ts";
import { daemonIdentity, hostIdentity, processStart } from "./server/host-identity.ts";
import { ensureRoot, safeComponent, stateRoot } from "./server/state-root.ts";
import { listAgents, loadRecord, sweepTmp, writeGeneration } from "./server/store.ts";
import { lookupPaseoAgentRecord, paseoHome } from "./server/paseo-home.ts";
import { acquireLock, selfWriterInfo } from "./server/writer-lock.ts";

/** The hooks this plugin registers, in order. */
export const HOOK_NAMES = [
  "agent.create.after",
  "agent.turn.before",
  "agent.turn.after",
  "agent.close.after",
  "agent.archive.after",
] as const;

export interface HookContextLike {
  paseo: PaseoLike;
  signal?: AbortSignal;
}

/** The slice of upstream PluginServerContext this plugin uses. */
export interface ServerLike {
  addHook(name: string, handler: (payload: never, context: HookContextLike) => Promise<void>): () => void;
}

/** The slice of `process` the disconnect handler needs (injectable for tests). */
export interface ProcessLike {
  on(event: "disconnect", listener: () => void): unknown;
  off(event: "disconnect", listener: () => void): unknown;
}

export interface PluginOptions {
  deps?: Partial<CaptureDeps>;
  env?: NodeJS.ProcessEnv;
  process?: ProcessLike;
  exit?: (code: number) => void;
}

/** `$PASEO_HOME`, resolved as the daemon resolves it (server/paseo-home.ts, shared with the CLI). */
export { paseoHome };

/**
 * The daemon deletes `$PASEO_HOME/local-credential` first when it stops (bootstrap.ts
 * stop()), before it closes agents and drains plugin events.
 */
export function shuttingDownFromCredential(env: NodeJS.ProcessEnv = process.env): () => boolean {
  const credential = path.join(paseoHome(env), "local-credential");
  return () => !fs.existsSync(credential);
}

function stderrLog(message: string, extra?: Record<string, unknown>): void {
  let tail = "";
  if (extra && Object.keys(extra).length > 0) {
    try {
      tail = ` ${JSON.stringify(extra)}`;
    } catch {
      tail = "";
    }
  }
  console.error(`[ade-recovery] ${message}${tail}`);
}

export function productionDeps(env: NodeJS.ProcessEnv = process.env): CaptureDeps {
  const home = paseoHome(env);
  return {
    store: {
      stateRoot: (serverId) => stateRoot(serverId, env),
      ensureRoot,
      acquireLock,
      writeGeneration: (dir, agentId, body) => writeGeneration(dir, agentId, body),
      loadRecord,
      listAgents,
      sweepTmp: (dir) => sweepTmp(dir),
    },
    gitEvidence: (cwd, signal) => gitEvidence(cwd, signal),
    host: { hostIdentity, daemonIdentity, processStart, writerInfo: selfWriterInfo },
    now: () => Date.now(),
    shuttingDown: shuttingDownFromCredential(env),
    log: stderrLog,
    hashJson: (value) => sha256Hex(canonicalJson(value)),
    safeComponent,
    realpath: (p) => fs.promises.realpath(p),
    paseoHome: home,
    // Read only, the same reader the CLI uses.
    paseoUpdatedAt: (agentId) => {
      const r = lookupPaseoAgentRecord(home, agentId);
      return r.status === "found" ? r.record.updatedAt : null;
    },
  };
}

/** Wire the capture into a server context; returns the plugin cleanup. */
export function createRecoveryPlugin(
  server: ServerLike,
  options: PluginOptions = {},
): { capture: Capture; cleanup: () => Promise<void> } {
  const deps: CaptureDeps = { ...productionDeps(options.env ?? process.env), ...(options.deps ?? {}) };
  const capture = new Capture(deps);
  const proc: ProcessLike = options.process ?? process;
  const exit = options.exit ?? ((code: number) => process.exit(code));

  // Handlers return at once: capture applies or buffers the event synchronously and runs
  // the rest detached. A bad payload is logged by capture, never thrown into the daemon.
  const offs: Array<() => void> = [
    server.addHook("agent.create.after", async (payload: { agent: HookAgent }, ctx) => {
      capture.onCreate(payload?.agent, ctx?.paseo);
    }),
    server.addHook(
      "agent.turn.before",
      async (payload: { agent: HookAgent; turnId: string | null }, ctx) => {
        capture.onTurnBefore(payload?.agent, payload?.turnId ?? null, ctx?.paseo);
      },
    ),
    server.addHook(
      "agent.turn.after",
      async (payload: { agent: HookAgent; turnId: string | null; outcome: TurnOutcome }, ctx) => {
        capture.onTurnAfter(payload?.agent, payload?.turnId ?? null, payload?.outcome, ctx?.paseo);
      },
    ),
    server.addHook("agent.close.after", async (payload: { agent: HookAgent }, ctx) => {
      capture.onClose(payload?.agent, ctx?.paseo);
    }),
    server.addHook(
      "agent.archive.after",
      async (payload: { agent: HookAgent; archivedAt: string }, ctx) => {
        capture.onArchive(payload?.agent, payload?.archivedAt, ctx?.paseo);
      },
    ),
  ];

  // An orphan left by a daemon SIGKILL keeps its pid alive; without this the next daemon's
  // plugin would find a live lock holder and stay read-only (critique finding 9).
  let exiting = false;
  const onDisconnect = (): void => {
    if (exiting) return;
    exiting = true;
    void capture.close().finally(() => exit(0));
  };
  proc.on("disconnect", onDisconnect);

  let cleaned = false;
  const cleanup = async (): Promise<void> => {
    if (cleaned) return;
    cleaned = true;
    proc.off("disconnect", onDisconnect);
    for (const off of offs) {
      try {
        off();
      } catch {
        // the host is tearing down anyway
      }
    }
    await capture.close();
  };
  return { capture, cleanup };
}

export default function contribute(server: ServerLike): () => Promise<void> {
  return createRecoveryPlugin(server).cleanup;
}
