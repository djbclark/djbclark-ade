import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  buildAdeClaimsBindOwnerArgv,
  buildAdeClaimsNewArgv,
  buildAdeClaimsReleaseArgv,
  buildAdeGitGuardInstallArgv,
  claimAllowsAgent,
  mergeOpenBeforeEnv,
  parseAgentCreateAfterAgent,
  parseAgentOpenBeforeRequest,
  parseClaimPointer,
  parseWorkspaceArchivePayload,
  parseWorktreePayload,
  resolveAdeClaimsScript,
  resolveClaimForCwd,
  resolveTrustedAdeClaimsScript,
  resolveTrustedAdeGitGuard,
  resolveTrustedAgentBinDir,
} from "./claim-lib.mjs";

/** Reviewed plugin directory (never the agent's worktree). */
const PLUGIN_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

/** Install soft-fail codes (do not abort worktree.create.after). */
const INSTALL_SOFT_FAIL = new Set([73, 78]);

/** @param {string} cwd */
export function gitRevParseHead(cwd) {
  const r = spawnSync("git", ["-C", cwd, "rev-parse", "HEAD"], { encoding: "utf8" });
  if (r.status !== 0 || !r.stdout?.trim()) {
    throw new Error(`git rev-parse HEAD failed in ${cwd}: ${r.stderr?.trim() || r.status}`);
  }
  return r.stdout.trim();
}

/** @param {string} cwd */
export function gitRemoteOriginUrl(cwd) {
  const r = spawnSync(
    "git",
    ["-C", cwd, "config", "--get", "remote.origin.url"],
    { encoding: "utf8" },
  );
  if (r.status !== 0) return "";
  return (r.stdout || "").trim();
}

/** @param {string} cwd */
export function gitRevParseGitDir(cwd) {
  const r = spawnSync("git", ["-C", cwd, "rev-parse", "--git-dir"], { encoding: "utf8" });
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
 * @returns {{ id: string, path: string, owner?: Record<string, unknown> } | null}
 */
export function lookupClaimForCwd(cwd, script) {
  let pointer = null;
  try {
    const gitDir = gitRevParseGitDir(cwd);
    pointer = parseClaimPointer(readFileSync(join(gitDir, "ade-claim"), "utf8"));
  } catch {
    // Missing git dir / pointer / unreadable: registry-only.
  }
  const run = spawnSync("python3", [script, "list", "--json", "--state", "active"], {
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
 */
export function runTrustedAdeGitGuardInstall(worktreePath) {
  let guard;
  try {
    guard = resolveTrustedAdeGitGuard(process.env, { pluginRoot: PLUGIN_ROOT });
  } catch (err) {
    console.error(`ade-claim: skipping ade-git-guard install: ${err}`);
    return;
  }
  const { argv } = buildAdeGitGuardInstallArgv({ adeGitGuard: guard, worktreePath });
  const run = spawnSync(guard, argv, { encoding: "utf8" });
  if (run.status === 0) return;
  const detail = (run.stderr || run.stdout || "").trim();
  const soft = INSTALL_SOFT_FAIL.has(run.status ?? -1);
  console.error(
    `ade-claim: ade-git-guard install failed (exit ${run.status})${soft ? " (soft)" : ""}${detail ? `: ${detail}` : ""}`,
  );
}

/**
 * W2: claim the worktree, then install ref hooks via trusted ade-git-guard.
 *
 * @param {{ addHook: (name: string, handler: Function) => () => void }} server
 */
export function registerWorktreeClaimHook(server) {
  return server.addHook("worktree.create.after", async ({ worktree }) => {
    const wt = parseWorktreePayload(worktree);
    const script = resolveAdeClaimsScript(wt, process.env, { pluginRoot: PLUGIN_ROOT });
    const baseSha = gitRevParseHead(wt.path);
    const repoOrigin = gitRemoteOriginUrl(wt.path);
    const { python, argv } = buildAdeClaimsNewArgv(wt, {
      adeClaimsScript: script,
      baseSha,
      repoOrigin,
    });
    const run = spawnSync(python, [script, ...argv], { encoding: "utf8" });
    if (run.status !== 0) {
      const detail = (run.stderr || run.stdout || "").trim();
      throw new Error(`ade_claims.py new failed (exit ${run.status})${detail ? `: ${detail}` : ""}`);
    }
    runTrustedAdeGitGuardInstall(wt.path);
  });
}

/**
 * W2 follow-up: mark the workspace claim released on archive (teardown follows).
 * Notification hook: never throw.
 *
 * @param {{ addHook: (name: string, handler: Function) => () => void }} server
 */
export function registerWorkspaceArchiveReleaseHook(server) {
  return server.addHook("workspace.archive.after", async ({ workspace }) => {
    let parsed;
    try {
      parsed = parseWorkspaceArchivePayload(workspace);
    } catch (err) {
      console.error(`ade-claim: workspace.archive.after payload: ${err}`);
      return;
    }
    let script;
    try {
      script = resolveTrustedAdeClaimsScript(process.env, { pluginRoot: PLUGIN_ROOT });
    } catch (err) {
      console.error(`ade-claim: skipping release: ${err}`);
      return;
    }
    let claim;
    try {
      claim = lookupClaimForCwd(parsed.cwd, script);
    } catch (err) {
      console.error(`ade-claim: claim lookup on archive failed: ${err}`);
      return;
    }
    if (!claim) return;
    const { python, argv } = buildAdeClaimsReleaseArgv({
      adeClaimsScript: script,
      claimId: claim.id,
    });
    const run = spawnSync(python, [script, ...argv], { encoding: "utf8" });
    if (run.status !== 0) {
      const detail = (run.stderr || run.stdout || "").trim();
      console.error(
        `ade-claim: ade_claims.py release failed (exit ${run.status})${detail ? `: ${detail}` : ""}`,
      );
    }
  });
}

/**
 * W3+W4: on every open (create's first launch and resumes):
 * - export ADE_CLAIM_ID when a claim exists for cwd
 * - put trusted libexec/agent-bin first on PATH (git → ade-git-guard)
 * agent.create.after cannot change env (Paseo notification); open.before can.
 *
 * @param {{ addHook: (name: string, handler: Function) => () => void }} server
 */
export function registerAgentClaimEnvHook(server) {
  return server.addHook("agent.open.before", async ({ request }) => {
    const parsed = parseAgentOpenBeforeRequest(request);
    let agentBinDir = null;
    try {
      agentBinDir = resolveTrustedAgentBinDir(process.env, { pluginRoot: PLUGIN_ROOT });
    } catch {
      // PATH shim optional when ADE_AGENT_BIN unset and plugin is not beside a checkout.
    }
    let claimId = null;
    try {
      const script = resolveTrustedAdeClaimsScript(process.env, { pluginRoot: PLUGIN_ROOT });
      const claim = lookupClaimForCwd(parsed.cwd, script);
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
      fallbackPath: process.env.PATH,
    });
    if (!env) return undefined;
    return { ...request, env };
  });
}

/**
 * W3: bind owner.agent (and owner.record) once the agent id exists.
 *
 * @param {{ addHook: (name: string, handler: Function) => () => void }} server
 */
export function registerAgentClaimOwnerHook(server) {
  return server.addHook("agent.create.after", async ({ agent }) => {
    const parsed = parseAgentCreateAfterAgent(agent);
    let script;
    try {
      script = resolveTrustedAdeClaimsScript(process.env, { pluginRoot: PLUGIN_ROOT });
    } catch {
      return;
    }
    let claim;
    try {
      claim = lookupClaimForCwd(parsed.cwd, script);
    } catch {
      return;
    }
    if (!claim || !claimAllowsAgent(claim, parsed.id)) {
      // No claim, or another agent already owns it: do not overwrite.
      return;
    }
    const { python, argv } = buildAdeClaimsBindOwnerArgv({
      adeClaimsScript: script,
      claimId: claim.id,
      ownerAgent: parsed.id,
      ownerRecord: parsed.id,
    });
    const run = spawnSync(python, [script, ...argv], { encoding: "utf8" });
    if (run.status !== 0) {
      const detail = (run.stderr || run.stdout || "").trim();
      // Notification hook: log via throw only if we want Paseo to record it;
      // prefer stderr so a bind miss never aborts creation (already finished).
      console.error(
        `ade-claim: ade_claims.py bind-owner failed (exit ${run.status})${detail ? `: ${detail}` : ""}`,
      );
    }
  });
}

/**
 * Register W2 + W2-follow-up + W3 + W4 hooks; returns a disposer that removes all of them.
 *
 * @param {{ addHook: (name: string, handler: Function) => () => void }} server
 */
export function registerAdeClaimHooks(server) {
  const removeWt = registerWorktreeClaimHook(server);
  const removeArchive = registerWorkspaceArchiveReleaseHook(server);
  const removeEnv = registerAgentClaimEnvHook(server);
  const removeOwner = registerAgentClaimOwnerHook(server);
  return () => {
    removeWt();
    removeArchive();
    removeEnv();
    removeOwner();
  };
}
