import { bindSnapshot } from "./snapshot-binding.mjs";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { userInfo } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  appendObserveLog,
  buildAdeClaimsBindOwnerArgv,
  buildAdeClaimsRebindOwnerArgv,
  classifyOwnerAgent,
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

/**
 * Reviewed plugin directory (never the agent's worktree), and where it came from.
 *
 * Paseo bundles `index.server.ts` to CommonJS and `eval`s it (daemon `compiler-build.js` format "cjs",
 * `bundle-evaluator.js`), and never tells the plugin its own directory; so in the daemon `import.meta.url`
 * is undefined and `fileURLToPath(undefined)` threw at load ("The "path" argument must be of type string
 * or an instance of URL. Received undefined", #638 D2). Order: (1) a real `file:` URL (plain Node ESM, the
 * tests); (2) Paseo's own install record, `<home>/.paseo/config.json` `plugins["ade-claim"].path` (the
 * directory the code was compiled from; absolute, own-user file); (3) the shared checkout
 * `<home>/src/djbclark-ade/plugins/ade-claim`. `<home>` is the account's home directory, never `$HOME`
 * (an env value must not redirect where trusted helpers are looked up; same rule as the mode file).
 * `ADE_CLAIMS_PY`, `ADE_GIT_GUARD` and `ADE_AGENT_BIN` still override each tool.
 *
 * @param {{ metaUrl?: unknown, home?: string }} [opts]
 * @returns {{ root: string, source: "file-url" | "paseo-install-record" | "home-fallback" }}
 */
export function resolvePluginRoot({ metaUrl, home = userInfo().homedir } = {}) {
  if (typeof metaUrl === "string" && metaUrl.startsWith("file:")) {
    return { root: join(dirname(fileURLToPath(metaUrl)), ".."), source: "file-url" };
  }
  try {
    const raw = readFileSync(join(home, ".paseo", "config.json"), "utf8");
    const path = JSON.parse(raw)?.plugins?.["ade-claim"]?.path;
    if (typeof path === "string" && path.startsWith("/")) {
      return { root: path, source: "paseo-install-record" };
    }
  } catch {
    // no readable install record: fall through to the shared checkout
  }
  return { root: join(home, "src", "djbclark-ade", "plugins", "ade-claim"), source: "home-fallback" };
}

// Legacy resolution is lazy; module evaluation never reads registration.

/** Install soft-fail codes (do not abort worktree.create.after). */
const INSTALL_SOFT_FAIL = new Set([73, 78]);

/**
 * Everything a hook touches outside its own arguments, so tests run offline: the daemon env, the state
 * dir (mode flag + observe JSONL), the process spawner and the clock. Production uses the defaults.
 *
 * @typedef {{
 *   managed?: boolean,
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
  let env = deps.env ?? process.env;
  let pluginRoot = deps.pluginRoot;
  if (deps.managed) {
    const { root } = bindSnapshot(pluginRoot, "ade-claim", [
      "bin/ade_claims.py", "bin/ade-git-guard", "libexec/agent-bin/git",
      "libexec/git-hooks/pre-push", "libexec/git-hooks/reference-transaction",
    ], env);
    // Internal exact bindings, constructed only after rejecting caller overrides.
    env = { ...env, ADE_CLAIMS_PY: join(root, "bin/ade_claims.py"),
      ADE_GIT_GUARD: join(root, "bin/ade-git-guard"), ADE_AGENT_BIN: join(root, "libexec/agent-bin") };
  } else pluginRoot ??= resolvePluginRoot({ metaUrl: import.meta?.url }).root;
  return {
    env,
    stateDir: deps.stateDir,
    spawn: deps.spawn ?? spawnSync,
    now: deps.now ?? (() => new Date()),
    pluginRoot,
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
 * Q4 (operator ruling 2026-11-20): an active claim whose owner agent is archived (or gone) passes to the next
 * agent created in its workspace, so a reused workspace whose every agent was archived does not leave the new agent
 * without a write identity (agent.open.before ran before the rebind, so a Claude-provider agent has no ADE_CLAIM_ID on its first launch; ade_claims.is_mine accepts its PASEO_AGENT_ID as owner.record of this claim shape instead, M1). Fails closed: the owner must be PROVEN archived or gone by one
 * SDK lookup (`classifyOwnerAgent`); a live owner, a failed lookup and any odd answer leave the claim
 * alone. The swap is `ade_claims.py rebind-owner`, a compare-and-swap on the exact owner that was inspected, on an
 * ACTIVE claim only (a released or expired claim is never revived). No handoff record is read, so nothing stale
 * can be replayed (queue Carried 58 a). One log line per call: observe logs the planned argv, enforce the argv and
 * the outcome.
 *
 * @param {ReturnType<typeof hookContext>} ctx
 * @param {{ mode: string, reason?: string }} m
 * @param {string} hook
 * @param {import("@getpaseo/plugin/server").PluginHookContext | undefined} context
 * @param {{ claim: { id: string, owner?: Record<string, unknown> }, parsed: { id: string, cwd: string },
 *           script: string, ids: Record<string, unknown> }} a
 */
async function rebindArchivedOwner(ctx, m, hook, context, { claim, parsed, script, ids }) {
  const owner = claim.owner && typeof claim.owner === "object" ? claim.owner : {};
  const oldOwner = typeof owner.agent === "string" ? owner.agent.trim() : "";
  const baseIds = { ...ids, claim: claim.id, workspace: parsed.cwd };
  // Only the shape `bind-owner` writes for a Paseo agent is ours to take: owner.agent === owner.record and no
  // owner.session. A harness label (`codex`, `pi`, ... with the real identity in owner.session) is never a Paseo
  // agent id: Paseo answers AGENT_NOT_FOUND for it while the owner may be live (adversary H1).
  const ownerRecord = typeof owner.record === "string" ? owner.record.trim() : "";
  const ownerSession = typeof owner.session === "string" ? owner.session.trim() : "";
  if (!oldOwner || ownerRecord !== oldOwner || ownerSession) {
    record(ctx, m, hook, { action: "none", why: "claim owned by another agent" }, baseIds);
    return;
  }
  let state = "unknown";
  try {
    if (!context?.signal?.aborted) {
      const result = await context?.paseo?.agents.ref(oldOwner).refresh();
      if (!context?.signal?.aborted) state = classifyOwnerAgent(oldOwner, result);
    }
  } catch {
    // SDK errors (including denied and ambiguous lookups) prove nothing about the owner.
  }
  if (state === "live") {
    record(ctx, m, hook, { action: "none", why: "claim owned by another agent" }, baseIds);
    return;
  }
  if (state === "unknown") {
    record(ctx, m, hook, { action: "none", why: "owner state unknown, not rebinding" }, baseIds,
      `owner lookup failed for ${oldOwner}: no rebind`);
    return;
  }
  let built;
  try {
    built = buildAdeClaimsRebindOwnerArgv({
      adeClaimsScript: script, claimId: claim.id, fromAgent: oldOwner, ownerAgent: parsed.id, ownerState: state,
    });
  } catch (err) {
    record(ctx, m, hook, null, baseIds, `rebind-owner argv: ${errText(err)}`);
    return;
  }
  const planned = {
    action: "rebind-owner",
    owner_state: state,
    from: oldOwner,
    to: parsed.id,
    claim: claim.id,
    workspace: parsed.cwd,
    argv: [built.python, built.script, ...built.argv],
  };
  const idsRebind = { ...baseIds, from: oldOwner };
  if (m.mode === "observe") {
    record(ctx, m, hook, planned, idsRebind);
    return;
  }
  const run = ctx.spawn(built.python, [built.script, ...built.argv], { encoding: "utf8" });
  if (run.status !== 0) {
    const detail = (run.stderr || run.stdout || "").trim();
    record(ctx, m, hook, planned, idsRebind, `rebind-owner failed (exit ${run.status})${detail ? `: ${detail}` : ""}`);
    return;
  }
  record(ctx, m, hook, planned, idsRebind);
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
  return server.addHook(hook, async ({ agent }, context) => {
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
    if (!claim) {
      record(ctx, m, hook, { action: "none", why: "no active claim for cwd" }, ids);
      return;
    }
    if (!claimAllowsAgent(claim, parsed.id)) {
      // Another agent owns it: never overwrite a live owner; an archived or gone owner is rebound (Q4).
      await rebindArchivedOwner(ctx, m, hook, context, { claim, parsed, script, ids });
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
  // Validate explicit context before registering even notification/observe hooks.
  hookContext(deps);
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
