/**
 * Pure helpers for the ade-claim Paseo plugin (unit-tested without a daemon).
 *
 * @typedef {{ path: string, branch: string, sourceCheckout: string }} WorktreeHookPayload
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
 * Locate a trusted bin/ade_claims.py.
 *
 * Never uses worktree.sourceCheckout: an untrusted repo could plant a hostile
 * bin/ade_claims.py that the daemon would exec. Prefer ADE_CLAIMS_PY, else walk
 * parents of the plugin install path (reviewed code) for bin/ade_claims.py.
 *
 * @param {WorktreeHookPayload} worktree
 * @param {NodeJS.ProcessEnv} [env]
 * @param {{ pluginRoot?: string }} [opts]
 */
export function resolveAdeClaimsScript(worktree, env = process.env, opts = {}) {
  parseWorktreePayload(worktree);
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
