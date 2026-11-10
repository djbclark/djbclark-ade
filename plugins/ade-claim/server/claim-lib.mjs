/**
 * Pure helpers for the ade-claim Paseo plugin (unit-tested without a daemon).
 *
 * W2: worktree.create.after → ade_claims.py new
 * W3: agent.open.before exports ADE_CLAIM_ID; agent.create.after binds owner
 *     (Paseo's agent.create.after is a notification and cannot change env).
 * W4: agent.open.before prepends trusted libexec/agent-bin to PATH.
 *
 * @typedef {{ path: string, branch: string, sourceCheckout: string }} WorktreeHookPayload
 * @typedef {{ agentId: string, cwd: string, env: Record<string, string> }} AgentOpenBeforePayload
 * @typedef {{ id: string, cwd: string }} AgentCreateAfterPayload
 */

import { randomBytes } from "node:crypto";
import { accessSync, constants } from "node:fs";
import { dirname, join } from "node:path";

const ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

/** @param {unknown} worktree */
export function parseWorktreePayload(worktree) {
  if (!worktree || typeof worktree !== "object" || Array.isArray(worktree)) {
    throw new Error("worktree.create.after: expected { worktree } object");
  }
  const { path, branch, sourceCheckout } = /** @type {Record<string, unknown>} */ (worktree);
  for (const [key, val] of [["path", path], ["branch", branch], ["sourceCheckout", sourceCheckout]]) {
    if (typeof val !== "string" || !val.trim()) {
      throw new Error(`worktree.create.after: worktree.${key} must be a non-empty string`);
    }
  }
  return /** @type {WorktreeHookPayload} */ ({ path, branch, sourceCheckout });
}

/**
 * agent.open.before request (Paseo ≥0.14): cwd + agentId + launch env overrides.
 * @param {unknown} request
 */
export function parseAgentOpenBeforeRequest(request) {
  if (!request || typeof request !== "object" || Array.isArray(request)) {
    throw new Error("agent.open.before: expected { request } object");
  }
  const { agentId, cwd, env } = /** @type {Record<string, unknown>} */ (request);
  if (typeof agentId !== "string" || !agentId.trim()) {
    throw new Error("agent.open.before: request.agentId must be a non-empty string");
  }
  if (typeof cwd !== "string" || !cwd.trim()) {
    throw new Error("agent.open.before: request.cwd must be a non-empty string");
  }
  /** @type {Record<string, string>} */
  const envMap = {};
  if (env != null) {
    if (typeof env !== "object" || Array.isArray(env)) {
      throw new Error("agent.open.before: request.env must be an object when present");
    }
    for (const [k, v] of Object.entries(/** @type {Record<string, unknown>} */ (env))) {
      if (typeof v === "string") envMap[k] = v;
    }
  }
  return /** @type {AgentOpenBeforePayload} */ ({ agentId, cwd, env: envMap });
}

/**
 * agent.create.after payload: { agent: { id, cwd, … } }.
 * @param {unknown} agent
 */
export function parseAgentCreateAfterAgent(agent) {
  if (!agent || typeof agent !== "object" || Array.isArray(agent)) {
    throw new Error("agent.create.after: expected { agent } object");
  }
  const { id, cwd } = /** @type {Record<string, unknown>} */ (agent);
  if (typeof id !== "string" || !id.trim()) {
    throw new Error("agent.create.after: agent.id must be a non-empty string");
  }
  if (typeof cwd !== "string" || !cwd.trim()) {
    throw new Error("agent.create.after: agent.cwd must be a non-empty string");
  }
  return /** @type {AgentCreateAfterPayload} */ ({ id, cwd });
}

/** @param {string} path */
function normalizePath(path) {
  return path.replace(/\/+$/, "") || "/";
}

/**
 * Normalize a list --json claim into the shape hooks use, or null if unusable.
 * @param {unknown} raw
 * @returns {{ id: string, path: string, shown: string, owner?: Record<string, unknown> } | null}
 */
export function normalizeClaimRecord(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const c = /** @type {Record<string, unknown>} */ (raw);
  if (typeof c.id !== "string" || !ID_RE.test(c.id)) return null;
  if (typeof c.path !== "string" || !c.path.trim()) return null;
  const shown = typeof c.shown_state === "string" ? c.shown_state
    : (typeof c.state === "string" ? c.state : "");
  return {
    id: c.id,
    path: c.path,
    shown,
    owner: c.owner && typeof c.owner === "object" && !Array.isArray(c.owner)
      ? /** @type {Record<string, unknown>} */ (c.owner)
      : undefined,
  };
}

/**
 * Pick the active claim whose path matches cwd (string equality after trailing-slash trim).
 * Live hooks may also resolve via the worktree pointer; this is the list --json path.
 *
 * @param {unknown} claims
 * @param {string} cwd
 * @returns {{ id: string, path: string, owner?: Record<string, unknown> } | null}
 */
export function activeClaimForPath(claims, cwd) {
  if (!Array.isArray(claims)) {
    throw new Error("activeClaimForPath: claims must be an array");
  }
  if (typeof cwd !== "string" || !cwd.trim()) {
    throw new Error("activeClaimForPath: cwd must be a non-empty string");
  }
  const want = normalizePath(cwd);
  for (const raw of claims) {
    const c = normalizeClaimRecord(raw);
    if (!c || c.shown !== "active") continue;
    if (normalizePath(c.path) !== want) continue;
    return { id: c.id, path: c.path, owner: c.owner };
  }
  return null;
}

/**
 * Prefer a pointer id only when the registry shows that claim active on cwd;
 * otherwise fall back to activeClaimForPath.
 *
 * @param {unknown} claims
 * @param {string} cwd
 * @param {string | null | undefined} pointerId
 * @returns {{ id: string, path: string, owner?: Record<string, unknown> } | null}
 */
export function resolveClaimForCwd(claims, cwd, pointerId) {
  if (!Array.isArray(claims)) {
    throw new Error("resolveClaimForCwd: claims must be an array");
  }
  if (typeof cwd !== "string" || !cwd.trim()) {
    throw new Error("resolveClaimForCwd: cwd must be a non-empty string");
  }
  const want = normalizePath(cwd);
  if (typeof pointerId === "string" && pointerId) {
    for (const raw of claims) {
      const c = normalizeClaimRecord(raw);
      if (!c || c.id !== pointerId) continue;
      if (c.shown === "active" && normalizePath(c.path) === want) {
        return { id: c.id, path: c.path, owner: c.owner };
      }
      break;
    }
  }
  return activeClaimForPath(claims, cwd);
}

/**
 * Whether this agent may receive ADE_CLAIM_ID / bind as owner for the claim.
 * Unowned claims (no agent/record/session) are open to the first binder.
 * A claim already owned by another agent must not be exported or overwritten.
 *
 * @param {{ owner?: Record<string, unknown> } | null | undefined} claim
 * @param {string} agentId
 */
export function claimAllowsAgent(claim, agentId) {
  if (!claim) return false;
  if (typeof agentId !== "string" || !agentId.trim()) {
    throw new Error("claimAllowsAgent: agentId must be a non-empty string");
  }
  const owner = claim.owner && typeof claim.owner === "object" ? claim.owner : {};
  const agent = typeof owner.agent === "string" ? owner.agent : "";
  const record = typeof owner.record === "string" ? owner.record : "";
  const session = typeof owner.session === "string" ? owner.session : "";
  if (!agent && !record && !session) return true;
  return agent === agentId || record === agentId || session === agentId;
}

/**
 * Contents of `<git-dir>/ade-claim` (claim id), or null when empty/missing text.
 * @param {unknown} text
 */
export function parseClaimPointer(text) {
  if (text == null) return null;
  if (typeof text !== "string") {
    throw new Error("ade-claim pointer must be a string");
  }
  const id = text.trim();
  if (!id) return null;
  if (!ID_RE.test(id)) {
    throw new Error(`ade-claim pointer is not a valid claim id: ${id}`);
  }
  return id;
}

/**
 * Merge ADE_CLAIM_ID into a launch env override map.
 * Returns undefined when there is nothing to change (caller should leave the request alone).
 *
 * @param {Record<string, string> | null | undefined} env
 * @param {string | null | undefined} claimId
 * @returns {Record<string, string> | undefined}
 */
export function mergeAdeClaimIdEnv(env, claimId) {
  if (!claimId) return undefined;
  if (typeof claimId !== "string" || !ID_RE.test(claimId)) {
    throw new Error(`ADE_CLAIM_ID must be a valid claim id, got ${JSON.stringify(claimId)}`);
  }
  const base = env && typeof env === "object" ? { ...env } : {};
  if (base.ADE_CLAIM_ID === claimId) return undefined;
  return { ...base, ADE_CLAIM_ID: claimId };
}

/**
 * Prepend a trusted libexec/agent-bin directory to PATH (W4).
 * Returns undefined when PATH already starts with that directory and was already
 * present on the override map (or when agentBinDir is empty).
 *
 * @param {Record<string, string> | null | undefined} env
 * @param {string | null | undefined} agentBinDir
 * @param {{ fallbackPath?: string }} [opts]
 * @returns {Record<string, string> | undefined}
 */
export function mergeAgentBinPath(env, agentBinDir, opts = {}) {
  if (!agentBinDir) return undefined;
  if (typeof agentBinDir !== "string" || !agentBinDir.trim()) {
    throw new Error("agentBinDir must be a non-empty string when set");
  }
  const dir = agentBinDir.replace(/\/+$/, "") || "/";
  const base = env && typeof env === "object" ? { ...env } : {};
  const current = Object.prototype.hasOwnProperty.call(base, "PATH")
    ? base.PATH
    : (opts.fallbackPath ?? "");
  if (typeof current !== "string") {
    throw new Error("PATH must be a string");
  }
  const parts = current.split(":").filter((p) => p.length > 0);
  const rest = parts.filter((p) => p !== dir);
  const next = [dir, ...rest].join(":");
  if (base.PATH === next) return undefined;
  return { ...base, PATH: next };
}

/**
 * Compose W3 ADE_CLAIM_ID + W4 agent-bin PATH into one open.before env map.
 * Returns undefined when nothing changes.
 *
 * @param {Record<string, string> | null | undefined} env
 * @param {{
 *   claimId?: string | null,
 *   agentBinDir?: string | null,
 *   fallbackPath?: string,
 * }} opts
 * @returns {Record<string, string> | undefined}
 */
export function mergeOpenBeforeEnv(env, opts = {}) {
  const { claimId = null, agentBinDir = null, fallbackPath } = opts;
  let cur = env && typeof env === "object" ? { ...env } : {};
  let changed = false;
  const withClaim = mergeAdeClaimIdEnv(cur, claimId);
  if (withClaim) {
    cur = withClaim;
    changed = true;
  }
  const withPath = mergeAgentBinPath(cur, agentBinDir, { fallbackPath });
  if (withPath) {
    cur = withPath;
    changed = true;
  }
  return changed ? cur : undefined;
}

/**
 * @param {{
 *   adeClaimsScript: string,
 *   claimId: string,
 *   ownerAgent: string,
 *   ownerRecord?: string,
 * }} opts
 */
export function buildAdeClaimsBindOwnerArgv(opts) {
  const { adeClaimsScript, claimId, ownerAgent, ownerRecord } = opts;
  if (typeof adeClaimsScript !== "string" || !adeClaimsScript) {
    throw new Error("adeClaimsScript is required");
  }
  if (typeof claimId !== "string" || !ID_RE.test(claimId)) {
    throw new Error(`claimId must be a valid claim id, got ${JSON.stringify(claimId)}`);
  }
  if (typeof ownerAgent !== "string" || !ownerAgent.trim()) {
    throw new Error("ownerAgent must be a non-empty string");
  }
  const argv = ["bind-owner", "--id", claimId, "--owner-agent", ownerAgent];
  if (ownerRecord) {
    if (typeof ownerRecord !== "string" || !ownerRecord.trim()) {
      throw new Error("ownerRecord must be a non-empty string when set");
    }
    argv.push("--owner-record", ownerRecord);
  }
  return { python: "python3", script: adeClaimsScript, argv };
}

/**
 * Per-creation claim id (branch + path basename + random suffix).
 * Must be unique: ade_claims.py new rejects any existing id (exit 3), even if
 * released/expired, and a throw on worktree.create.after removes the worktree.
 *
 * @param {WorktreeHookPayload} worktree
 * @param {{ randomHex?: () => string }} [opts]
 */
export function deriveClaimId(worktree, opts = {}) {
  const base = worktree.path.split("/").pop() || "worktree";
  const branchPart = worktree.branch.replace(/\//g, "-").replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "");
  const pathPart = base.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "");
  const suffix = (opts.randomHex || (() => randomBytes(4).toString("hex")))();
  const raw = `wt-${branchPart || "branch"}-${pathPart || "dir"}-${suffix}`;
  const id = raw.length <= 128 ? raw : `wt-${raw.slice(0, 120)}`;
  if (!ID_RE.test(id)) {
    throw new Error(`derived claim id is invalid: ${id}`);
  }
  return id;
}

/**
 * @param {WorktreeHookPayload} worktree
 * @param {{
 *   adeClaimsScript: string,
 *   baseSha: string,
 *   repoOrigin?: string,
 *   ttlHours?: number,
 *   ownerRecord?: string,
 *   ownerAgent?: string,
 * }} opts
 */
export function buildAdeClaimsNewArgv(worktree, opts) {
  parseWorktreePayload(worktree);
  const { adeClaimsScript, baseSha, repoOrigin = "", ttlHours, ownerRecord, ownerAgent } = opts;
  if (typeof adeClaimsScript !== "string" || !adeClaimsScript) {
    throw new Error("adeClaimsScript is required");
  }
  if (typeof baseSha !== "string" || !/^[0-9a-f]{4,40}$/i.test(baseSha)) {
    throw new Error("baseSha must look like a git object id");
  }
  const argv = [
    "new",
    "--id", deriveClaimId(worktree),
    "--path", worktree.path,
    "--branch", worktree.branch,
    "--base-sha", baseSha,
    "--created-by", "paseo-ade-claim-plugin",
  ];
  if (repoOrigin) argv.push("--repo-origin", repoOrigin);
  if (ownerRecord) argv.push("--owner-record", ownerRecord);
  if (ownerAgent) argv.push("--owner-agent", ownerAgent);
  if (ttlHours !== undefined) argv.push("--ttl", String(ttlHours));
  return { python: "python3", script: adeClaimsScript, argv };
}

function readable(path) {
  try {
    accessSync(path, constants.R_OK);
    return true;
  } catch {
    return false;
  }
}

/**
 * Locate a trusted bin/ade_claims.py (no checkout path consulted).
 *
 * Prefer ADE_CLAIMS_PY, else walk parents of the plugin install path (reviewed
 * code) for bin/ade_claims.py. Never uses a worktree or sourceCheckout path:
 * an untrusted repo could plant a hostile helper the daemon would exec.
 *
 * @param {NodeJS.ProcessEnv} [env]
 * @param {{ pluginRoot?: string }} [opts]
 */
export function resolveTrustedAdeClaimsScript(env = process.env, opts = {}) {
  if (env.ADE_CLAIMS_PY) {
    if (!readable(env.ADE_CLAIMS_PY)) {
      throw new Error(`ADE_CLAIMS_PY is not readable: ${env.ADE_CLAIMS_PY}`);
    }
    return env.ADE_CLAIMS_PY;
  }
  const start = opts.pluginRoot;
  if (typeof start !== "string" || !start.trim()) {
    throw new Error(
      "ade_claims.py not found: set ADE_CLAIMS_PY to a trusted absolute path (checkout-local helpers are refused)",
    );
  }
  let dir = start;
  for (let i = 0; i < 10 && dir && dir !== "/"; i++) {
    const candidate = join(dir, "bin", "ade_claims.py");
    if (readable(candidate)) return candidate;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  throw new Error(
    "ade_claims.py not found beside the plugin install; set ADE_CLAIMS_PY to a trusted absolute path",
  );
}

function isDir(path) {
  try {
    accessSync(path, constants.R_OK);
    // access alone is not enough for "is directory"; use a cheap readdir probe via join+git shim
    accessSync(join(path, "git"), constants.R_OK);
    return true;
  } catch {
    return false;
  }
}

/**
 * Locate a trusted libexec/agent-bin (W4 PATH shim directory).
 *
 * Prefer ADE_AGENT_BIN, else walk parents of the plugin install for
 * libexec/agent-bin containing the git shim. Never uses a worktree path.
 *
 * @param {NodeJS.ProcessEnv} [env]
 * @param {{ pluginRoot?: string }} [opts]
 */
export function resolveTrustedAgentBinDir(env = process.env, opts = {}) {
  if (env.ADE_AGENT_BIN) {
    if (!isDir(env.ADE_AGENT_BIN)) {
      throw new Error(`ADE_AGENT_BIN is not a usable agent-bin dir: ${env.ADE_AGENT_BIN}`);
    }
    return env.ADE_AGENT_BIN.replace(/\/+$/, "") || "/";
  }
  const start = opts.pluginRoot;
  if (typeof start !== "string" || !start.trim()) {
    throw new Error(
      "libexec/agent-bin not found: set ADE_AGENT_BIN to a trusted absolute path (checkout-local shims are refused)",
    );
  }
  let dir = start;
  for (let i = 0; i < 10 && dir && dir !== "/"; i++) {
    const candidate = join(dir, "libexec", "agent-bin");
    if (isDir(candidate)) return candidate;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  throw new Error(
    "libexec/agent-bin not found beside the plugin install; set ADE_AGENT_BIN to a trusted absolute path",
  );
}

/**
 * W2 helper: validate the worktree payload, then resolve a trusted script.
 *
 * @param {WorktreeHookPayload} worktree
 * @param {NodeJS.ProcessEnv} [env]
 * @param {{ pluginRoot?: string }} [opts]
 */
export function resolveAdeClaimsScript(worktree, env = process.env, opts = {}) {
  parseWorktreePayload(worktree);
  return resolveTrustedAdeClaimsScript(env, opts);
}
