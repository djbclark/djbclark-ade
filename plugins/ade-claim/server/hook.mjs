import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  appendObserveLog,
  buildAdeClaimsBindOwnerArgv,
  buildObserveEntry,
  buildAdeClaimsReleaseArgv,
  buildAdeGitGuardInstallArgv,
  claimAllowsAgent,
  formatObserveLine,
  mergeOpenBeforeEnv,
  parseAgentCreateAfterAgent,
  parseAgentOpenBeforeRequest,
  parseClaimPointer,
  parseWorkspaceArchivePayload,
  parseWorktreePayload,
  planWorktreeClaimCreate,
  resolveAdeClaimsScript,
  resolveClaimForCwd,
  resolveClaimMode,
  resolveTrustedAdeClaimsScript,
  resolveTrustedAdeGitGuard,
  resolveTrustedAgentBinDir,
} from "./claim-lib.mjs";

/** Reviewed plugin directory (never the agent's worktree). */
const PLUGIN_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

/** Install soft-fail codes (do not abort worktree.create.after). */
const INSTALL_SOFT_FAIL = new Set([73, 78]);

/**
 * Everything a hook touches outside its own arguments, so tests run offline: the daemon env, the state
 * dir (mode flag + observe JSONL), the process spawner and the clock. Production uses the defaults.
 *
 * @typedef {{
 *   env?: NodeJS.ProcessEnv | Record<string, string | undefined>,
 *   stateDir?: string,
 *   spawn?: typeof spawnSync,
 *   now?: () => Date,
 *   pluginRoot?: string,
 *   log?: (line: string) => void,
 * }} HookDeps
 */

/** @param {HookDeps} [deps] */
function hookContext(deps = {}) {
  return {
    env: deps.env ?? process.env,
    stateDir: deps.stateDir,
    spawn: deps.spawn ?? spawnSync,
    now: deps.now ?? (() => new Date()),
    pluginRoot: deps.pluginRoot ?? PLUGIN_ROOT,
    log: deps.log ?? ((line) => console.error(line)),
  };
}

/** Mode for THIS call: env flag and state file are re-read every time (no daemon restart). */
function callMode(ctx) {
  return resolveClaimMode({ env: ctx.env, stateDir: ctx.stateDir });
}

/**
 * One line per hook call: stderr (plugin logs) plus the append-only JSONL for the D3 soak.
 * Never throws; `planned` is argv or an env delta, never the launch env or a secret.
 */
function record(ctx, m, hook, planned, ids, error) {
  const entry = buildObserveEntry({ hook, mode: m.mode, reason: m.reason, planned, ids, error, now: ctx.now() });
  ctx.log(formatObserveLine(entry));
  appendObserveLog(entry, { stateDir: ctx.stateDir });
}

const errText = (err) => String(err instanceof Error ? err.message : err);

/** @param {string} cwd */
export function gitRevParseHead(cwd, spawn = spawnSync) {
  const r = spawn("git", ["-C", cwd, "rev-parse", "HEAD"], { encoding: "utf8" });
  if (r.status !== 0 || !r.stdout?.trim()) {
    throw new Error(`git rev-parse HEAD failed in ${cwd}: ${r.stderr?.trim() || r.status}`);
  }
  return r.stdout.trim();
}

/** @param {string} cwd */
export function gitRemoteOriginUrl(cwd, spawn = spawnSync) {
  const r = spawn(
    "git",
    ["-C", cwd, "config", "--get", "remote.origin.url"],
    { encoding: "utf8" },
  );
  if (r.status !== 0) return "";
  return (r.stdout || "").trim();
}

/** @param {string} cwd */
export function gitRevParseGitDir(cwd, spawn = spawnSync) {
  const r = spawn("git", ["-C", cwd, "rev-parse", "--git-dir"], { encoding: "utf8" });
  if (r.status !== 0 || !r.stdout?.trim()) {
    throw new Error(`git rev-parse --git-dir failed in ${cwd}: ${r.stderr?.trim() || r.status}`);
  }
  const raw = r.stdout.trim();
  return raw.startsWith("/") ? raw : join(cwd, raw);
}

/**
 * Resolve the active claim for a workspace cwd.
 * Prefer the per-worktree pointer only when the registry confirms it is active
 * on this path; otherwise fall back to path match. Always reads the registry.
 *
 * @param {string} cwd
 * @param {string} script
 * @param {typeof spawnSync} [spawn]
 * @returns {{ id: string, path: string, owner?: Record<string, unknown> } | null}
 */
export function lookupClaimForCwd(cwd, script, spawn = spawnSync) {
  let pointer = null;
  try {
    const gitDir = gitRevParseGitDir(cwd, spawn);
    pointer = parseClaimPointer(readFileSync(join(gitDir, "ade-claim"), "utf8"));
  } catch {
    // Missing git dir / pointer / unreadable: registry-only.
  }
  const run = spawn("python3", [script, "list", "--json", "--state", "active"], {
    encoding: "utf8",
  });
  if (run.status !== 0) {
    const detail = (run.stderr || run.stdout || "").trim();
    throw new Error(`ade_claims.py list failed (exit ${run.status})${detail ? `: ${detail}` : ""}`);
  }
  let claims;
  try {
    claims = JSON.parse(run.stdout || "[]");
  } catch (err) {
    throw new Error(`ade_claims.py list --json was not JSON: ${err}`);
  }
  return resolveClaimForCwd(claims, cwd, pointer);
}

/**
 * Run trusted ade-git-guard install on a new worktree. Soft-fails (logs) on
 * missing binary, 73/78, or other non-zero so a claim create is never rolled back.
 *
 * @param {string} worktreePath
 * @param {HookDeps} [deps]
 * @returns {string} outcome for the log: "ok" | "skipped: …" | "failed (exit N)"
 */
export function runTrustedAdeGitGuardInstall(worktreePath, deps = {}) {
  const ctx = hookContext(deps);
  let guard;
  try {
    guard = resolveTrustedAdeGitGuard(ctx.env, { pluginRoot: ctx.pluginRoot });
  } catch (err) {
    ctx.log(`ade-claim: skipping ade-git-guard install: ${err}`);
    return "skipped: no trusted ade-git-guard";
  }
  const { argv } = buildAdeGitGuardInstallArgv({ adeGitGuard: guard, worktreePath });
  const run = ctx.spawn(guard, argv, { encoding: "utf8" });
  if (run.status === 0) return "ok";
  const detail = (run.stderr || run.stdout || "").trim();
  const soft = INSTALL_SOFT_FAIL.has(run.status ?? -1);
  ctx.log(
    `ade-claim: ade-git-guard install failed (exit ${run.status})${soft ? " (soft)" : ""}${detail ? `: ${detail}` : ""}`,
  );
  return `failed (exit ${run.status})${soft ? " (soft)" : ""}`;
}

/**
 * W2: claim the worktree (`ade_claims.py new --ttl`), then install ref hooks via trusted
 * ade-git-guard. In observe mode (see resolveClaimMode) it logs the planned argv and does nothing else,
 * and never throws: observing must not abort a worktree creation.
 *
 * @param {{ addHook: (name: string, handler: Function) => () => void }} server
 * @param {HookDeps} [deps]
 */
export function registerWorktreeClaimHook(server, deps = {}) {
  const ctx = hookContext(deps);
  return server.addHook("worktree.create.after", async ({ worktree }) => {
    const m = callMode(ctx);
    const observing = m.mode === "observe";
    /** @type {Record<string, unknown>} */
    let ids = {};
    try {
      const wt = parseWorktreePayload(worktree);
      ids = { worktree: wt.path, branch: wt.branch };
      const script = resolveAdeClaimsScript(wt, ctx.env, { pluginRoot: ctx.pluginRoot });
      const baseSha = gitRevParseHead(wt.path, ctx.spawn);
      const repoOrigin = gitRemoteOriginUrl(wt.path, ctx.spawn);
      const plan = planWorktreeClaimCreate(wt, {
        adeClaimsScript: script,
        baseSha,
        repoOrigin,
        env: ctx.env,
      });
      let guard = null;
      try {
        guard = resolveTrustedAdeGitGuard(ctx.env, { pluginRoot: ctx.pluginRoot });
      } catch { /* install is soft-skipped without a trusted guard */ }
      const planned = {
        argv: [plan.python, script, ...plan.argv],
        ttlHours: plan.ttlHours,
        then: guard ? [guard, "install", wt.path] : null,
      };
      if (observing) {
        record(ctx, m, "worktree.create.after", planned, ids);
        return;
      }
      const run = ctx.spawn(plan.python, [script, ...plan.argv], { encoding: "utf8" });
      if (run.status !== 0) {
        const detail = (run.stderr || run.stdout || "").trim();
        throw new Error(`ade_claims.py new failed (exit ${run.status})${detail ? `: ${detail}` : ""}`);
      }
      const install = runTrustedAdeGitGuardInstall(wt.path, deps);
      record(ctx, m, "worktree.create.after", { ...planned, install }, ids);
    } catch (err) {
      record(ctx, m, "worktree.create.after", null, ids, errText(err));
      if (observing) return;
      throw err;
    }
  });
}

/**
 * W2 follow-up: mark the workspace claim released on archive (teardown follows).
 * Notification hook: never throw.
 *
 * @param {{ addHook: (name: string, handler: Function) => () => void }} server
 * @param {HookDeps} [deps]
 */
export function registerWorkspaceArchiveReleaseHook(server, deps = {}) {
  const ctx = hookContext(deps);
  const hook = "workspace.archive.after";
  return server.addHook(hook, async ({ workspace }) => {
    const m = callMode(ctx);
    /** @type {Record<string, unknown>} */
    let ids = {};
    let parsed;
    try {
      parsed = parseWorkspaceArchivePayload(workspace);
      ids = { workspace: parsed.id, cwd: parsed.cwd };
    } catch (err) {
      record(ctx, m, hook, null, ids, errText(err));
      return;
    }
    let script;
    try {
      script = resolveTrustedAdeClaimsScript(ctx.env, { pluginRoot: ctx.pluginRoot });
    } catch (err) {
      record(ctx, m, hook, null, ids, `skipping release: ${errText(err)}`);
      return;
    }
    let claim;
    try {
      claim = lookupClaimForCwd(parsed.cwd, script, ctx.spawn);
    } catch (err) {
      record(ctx, m, hook, null, ids, `claim lookup failed: ${errText(err)}`);
      return;
    }
    if (!claim) {
      record(ctx, m, hook, { action: "none", why: "no active claim for cwd" }, ids);
      return;
    }
    const { python, argv } = buildAdeClaimsReleaseArgv({ adeClaimsScript: script, claimId: claim.id });
    const planned = { argv: [python, script, ...argv] };
    ids = { ...ids, claim: claim.id };
    if (m.mode === "observe") {
      record(ctx, m, hook, planned, ids);
      return;
    }
    const run = ctx.spawn(python, [script, ...argv], { encoding: "utf8" });
    if (run.status !== 0) {
      const detail = (run.stderr || run.stdout || "").trim();
      record(ctx, m, hook, planned, ids,
        `release failed (exit ${run.status})${detail ? `: ${detail}` : ""}`);
      return;
    }
    record(ctx, m, hook, planned, ids);
  });
}

/**
 * W3+W4: on every open (create's first launch and resumes):
 * - export ADE_CLAIM_ID when a claim exists for cwd
 * - put trusted libexec/agent-bin first on PATH (git → ade-git-guard)
 * agent.create.after cannot change env (Paseo notification); open.before can.
 * Observe mode: lookups still run (read-only), the planned env delta is logged, and the request is
 * returned untouched (undefined) — no ADE_CLAIM_ID, no PATH change, never throws.
 *
 * @param {{ addHook: (name: string, handler: Function) => () => void }} server
 * @param {HookDeps} [deps]
 */
export function registerAgentClaimEnvHook(server, deps = {}) {
  const ctx = hookContext(deps);
  const hook = "agent.open.before";
  return server.addHook(hook, async ({ request }) => {
    const m = callMode(ctx);
    const observing = m.mode === "observe";
    /** @type {Record<string, unknown>} */
    let ids = {};
    let parsed;
    try {
      parsed = parseAgentOpenBeforeRequest(request);
      ids = { agent: parsed.agentId, cwd: parsed.cwd };
    } catch (err) {
      record(ctx, m, hook, null, ids, errText(err));
      if (observing) return undefined;
      throw err;
    }
    let agentBinDir = null;
    try {
      agentBinDir = resolveTrustedAgentBinDir(ctx.env, { pluginRoot: ctx.pluginRoot });
    } catch {
      // PATH shim optional when ADE_AGENT_BIN unset and plugin is not beside a checkout.
    }
    let claimId = null;
    try {
      const script = resolveTrustedAdeClaimsScript(ctx.env, { pluginRoot: ctx.pluginRoot });
      const claim = lookupClaimForCwd(parsed.cwd, script, ctx.spawn);
      if (claim && claimAllowsAgent(claim, parsed.agentId)) {
        claimId = claim.id;
      }
      // Foreign/missing claim: still may prepend PATH; never export ADE_CLAIM_ID.
    } catch {
      // No claim / unreadable registry: still may prepend PATH.
    }
    const env = mergeOpenBeforeEnv(parsed.env, {
      claimId,
      agentBinDir,
      fallbackPath: ctx.env.PATH,
    });
    // Env delta only: names, plus the two values this plugin itself sets. Never the launch env.
    const planned = {
      wouldChange: Boolean(env),
      ADE_CLAIM_ID: claimId ? { set: claimId }
        : (Object.prototype.hasOwnProperty.call(parsed.env, "ADE_CLAIM_ID") ? "clear" : "unchanged"),
      PATH: agentBinDir ? { prepend: agentBinDir } : "unchanged",
    };
    record(ctx, m, hook, planned, claimId ? { ...ids, claim: claimId } : ids);
    if (observing || !env) return undefined;
    return { ...request, env };
  });
}

/**
 * W3: bind owner.agent (and owner.record) once the agent id exists.
 * Observe mode logs the planned bind-owner argv and does not write the registry.
 *
 * @param {{ addHook: (name: string, handler: Function) => () => void }} server
 * @param {HookDeps} [deps]
 */
export function registerAgentClaimOwnerHook(server, deps = {}) {
  const ctx = hookContext(deps);
  const hook = "agent.create.after";
  return server.addHook(hook, async ({ agent }) => {
    const m = callMode(ctx);
    /** @type {Record<string, unknown>} */
    let ids = {};
    let parsed;
    try {
      parsed = parseAgentCreateAfterAgent(agent);
      ids = { agent: parsed.id, cwd: parsed.cwd };
    } catch (err) {
      record(ctx, m, hook, null, ids, errText(err));
      if (m.mode === "observe") return;
      throw err;
    }
    let script;
    try {
      script = resolveTrustedAdeClaimsScript(ctx.env, { pluginRoot: ctx.pluginRoot });
    } catch (err) {
      record(ctx, m, hook, null, ids, `no trusted ade_claims.py: ${errText(err)}`);
      return;
    }
    let claim;
    try {
      claim = lookupClaimForCwd(parsed.cwd, script, ctx.spawn);
    } catch (err) {
      record(ctx, m, hook, null, ids, `claim lookup failed: ${errText(err)}`);
      return;
    }
    if (!claim || !claimAllowsAgent(claim, parsed.id)) {
      // No claim, or another agent already owns it: do not overwrite.
      record(ctx, m, hook, { action: "none", why: claim ? "claim owned by another agent" : "no active claim for cwd" }, ids);
      return;
    }
    const { python, argv } = buildAdeClaimsBindOwnerArgv({
      adeClaimsScript: script,
      claimId: claim.id,
      ownerAgent: parsed.id,
      ownerRecord: parsed.id,
    });
    const planned = { argv: [python, script, ...argv] };
    ids = { ...ids, claim: claim.id };
    if (m.mode === "observe") {
      record(ctx, m, hook, planned, ids);
      return;
    }
    const run = ctx.spawn(python, [script, ...argv], { encoding: "utf8" });
    if (run.status !== 0) {
      const detail = (run.stderr || run.stdout || "").trim();
      // Notification hook: log only so a bind miss never aborts creation (already finished).
      record(ctx, m, hook, planned, ids,
        `bind-owner failed (exit ${run.status})${detail ? `: ${detail}` : ""}`);
      return;
    }
    record(ctx, m, hook, planned, ids);
  });
}

/**
 * Register W2 + W2-follow-up + W3 + W4 hooks; returns a disposer that removes all of them.
 *
 * @param {{ addHook: (name: string, handler: Function) => () => void }} server
 * @param {HookDeps} [deps]
 */
export function registerAdeClaimHooks(server, deps = {}) {
  const removeWt = registerWorktreeClaimHook(server, deps);
  const removeArchive = registerWorkspaceArchiveReleaseHook(server, deps);
  const removeEnv = registerAgentClaimEnvHook(server, deps);
  const removeOwner = registerAgentClaimOwnerHook(server, deps);
  return () => {
    removeWt();
    removeArchive();
    removeEnv();
    removeOwner();
  };
}
