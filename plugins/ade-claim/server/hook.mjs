import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  buildAdeClaimsBindOwnerArgv,
  buildAdeClaimsNewArgv,
  claimAllowsAgent,
  mergeAdeClaimIdEnv,
  parseAgentCreateAfterAgent,
  parseAgentOpenBeforeRequest,
  parseClaimPointer,
  parseWorktreePayload,
  resolveAdeClaimsScript,
  resolveClaimForCwd,
  resolveTrustedAdeClaimsScript,
} from "./claim-lib.mjs";

/** Reviewed plugin directory (never the agent's worktree). */
const PLUGIN_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

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
  });
}

/**
 * W3: export ADE_CLAIM_ID on every open (create's first launch and resumes).
 * agent.create.after cannot change env (Paseo notification); open.before can.
 *
 * @param {{ addHook: (name: string, handler: Function) => () => void }} server
 */
export function registerAgentClaimEnvHook(server) {
  return server.addHook("agent.open.before", async ({ request }) => {
    const parsed = parseAgentOpenBeforeRequest(request);
    let script;
    try {
      script = resolveTrustedAdeClaimsScript(process.env, { pluginRoot: PLUGIN_ROOT });
    } catch {
      return undefined;
    }
    let claim;
    try {
      claim = lookupClaimForCwd(parsed.cwd, script);
    } catch {
      // No claim / unreadable registry: leave the launch alone.
      return undefined;
    }
    if (!claim || !claimAllowsAgent(claim, parsed.agentId)) {
      // Missing claim or foreign owner: never export ADE_CLAIM_ID (is_mine trusts it).
      return undefined;
    }
    const env = mergeAdeClaimIdEnv(parsed.env, claim.id);
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
 * Register W2 + W3 hooks; returns a disposer that removes all of them.
 *
 * @param {{ addHook: (name: string, handler: Function) => () => void }} server
 */
export function registerAdeClaimHooks(server) {
  const removeWt = registerWorktreeClaimHook(server);
  const removeEnv = registerAgentClaimEnvHook(server);
  const removeOwner = registerAgentClaimOwnerHook(server);
  return () => {
    removeWt();
    removeEnv();
    removeOwner();
  };
}
