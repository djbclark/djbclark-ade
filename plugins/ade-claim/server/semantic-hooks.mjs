/** Business callbacks for the finite SDK seam. No process/import fallback.
 * runOperation is supplied by the fixed committed SDK route, never native IPC
 * input. Tests inject descriptive business results, not native capabilities.
 */
import { readFileSync } from "node:fs";
import { isAbsolute, join, resolve } from "node:path";
import { bindSnapshot } from "./snapshot-binding.mjs";
import {
  appendObserveLog, buildObserveEntry, claimAllowsAgent, deriveClaimId,
  formatObserveLine, mergeOpenBeforeEnv, parseAgentCreateAfterAgent,
  parseAgentOpenBeforeRequest, parseClaimPointer, parseWorktreePayload,
  parseWorkspaceArchivePayload, resolveClaimForCwd, resolveClaimMode,
  resolveClaimTtlHours,
} from "./claim-lib.mjs";

export function createSemanticClaimHandlers(deps) {
  const { runOperation, pluginRoot } = deps;
  if (typeof runOperation !== "function") throw new Error("ADE directory SDK operation unavailable");
  const env = deps.env ?? process.env;
  const { root } = bindSnapshot(pluginRoot, "ade-claim", [
    "bin/ade_directory_operations.py", "bin/ade_claims.py", "bin/ade_ws_autoname.py", "bin/ade_ws_names.py",
    "bin/ade-git-guard", "libexec/agent-bin/git",
    "libexec/git-hooks/pre-push", "libexec/git-hooks/reference-transaction",
  ], env);
  const agentBinDir = join(root, "libexec/agent-bin");
  const log = deps.log ?? ((line) => console.error(line));
  const mode = () => resolveClaimMode({ env, stateDir: deps.stateDir });
  const record = (m, hook, planned, ids, error) => {
    const entry = buildObserveEntry({ hook, mode: m.mode, reason: m.reason, planned, ids, error,
      now: deps.now?.() ?? new Date() });
    log(formatObserveLine(entry));
    appendObserveLog(entry, { stateDir: deps.stateDir });
  };
  const perform = (operation, cwd, fields = {}) => runOperation({ version: 1, operation, cwd, ...fields });
  const fact = async (cwd, selection) => {
    const result = await perform("repository-facts", cwd, { selection });
    if (result.version !== 1 || result.selection !== selection || typeof result.stdout !== "string"
      || (result.status !== 0 && !(selection === "origin" && result.status === 1))) {
      throw new Error(`ADE repository ${selection} unavailable`);
    }
    return result.status === 1 ? "" : result.stdout.trim();
  };
  const lookup = async (cwd) => {
    const gitdir = await fact(cwd, "git-dir");
    let pointer = null;
    try {
      pointer = parseClaimPointer(readFileSync(join(isAbsolute(gitdir) ? gitdir : resolve(cwd, gitdir), "ade-claim"), "utf8"));
    } catch { /* Optional/stale pointer never hides the actual complete registry. */ }
    const result = await perform("claim-list", cwd);
    if (result.status !== 0 || !Array.isArray(result.output)) throw new Error("ADE claim registry unavailable");
    return resolveClaimForCwd(result.output, cwd, pointer);
  };

  return {
    "worktree.create.after": async ({ worktree }) => {
      const m = mode();
      const wt = parseWorktreePayload(worktree);
      const ids = { worktree: wt.path, branch: wt.branch };
      // Observe retains the old real read/planning behavior, with no mutation.
      const head = await fact(wt.path, "head");
      const origin = await fact(wt.path, "origin");
      const fields = { branch: wt.branch, claimId: deriveClaimId(wt), ttlHours: resolveClaimTtlHours(env),
        ownerAgent: "", ownerRecord: null };
      const planned = { operation: "claim-new", ...fields, head, origin, then: "claim-install-hooks" };
      if (m.mode === "observe") { record(m, "worktree.create.after", planned, ids); return; }
      const created = await perform("claim-new", wt.path, fields);
      if (created.status !== 0) {
        record(m, "worktree.create.after", planned, ids, `claim-new refused (${created.status})`);
        throw new Error(`ADE claim-new refused (${created.status})`);
      }
      // No rollback/retry if install refuses or fails after a real claim write.
      const install = await perform("claim-install-hooks", wt.path);
      record(m, "worktree.create.after", { ...planned, install }, ids,
        install.status === 0 ? undefined : `hook install refused (${install.status})`);
    },
    "workspace.archive.after": async ({ workspace }) => {
      const m = mode();
      const parsed = parseWorkspaceArchivePayload(workspace);
      const ids = { workspace: parsed.id, cwd: parsed.cwd };
      const claim = await lookup(parsed.cwd);
      if (!claim) { record(m, "workspace.archive.after", { action: "none", why: "no active claim for cwd" }, ids); return; }
      const planned = { operation: "claim-release", claimId: claim.id };
      if (m.mode === "observe") { record(m, "workspace.archive.after", planned, { ...ids, claim: claim.id }); return; }
      const result = await perform("claim-release", parsed.cwd, { claimId: claim.id });
      record(m, "workspace.archive.after", planned, { ...ids, claim: claim.id },
        result.status === 0 ? undefined : `release refused (${result.status})`);
    },
    "agent.open.before": async ({ request }) => {
      const m = mode();
      const parsed = parseAgentOpenBeforeRequest(request);
      // A thrown SDK/proof/transport error propagates; never PATH-only fallback
      // from an uncertain registry or a second raw lookup.
      const claim = await lookup(parsed.cwd);
      const claimId = claim && claimAllowsAgent(claim, parsed.agentId) ? claim.id : null;
      const changed = mergeOpenBeforeEnv(parsed.env, { claimId, agentBinDir, fallbackPath: env.PATH });
      record(m, "agent.open.before", {
        wouldChange: Boolean(changed), ADE_CLAIM_ID: claimId ? { set: claimId }
          : (Object.hasOwn(parsed.env, "ADE_CLAIM_ID") ? "clear" : "unchanged"),
        PATH: { prepend: agentBinDir },
      }, { agent: parsed.agentId, cwd: parsed.cwd, ...(claimId ? { claim: claimId } : {}) });
      if (m.mode === "observe" || !changed) return undefined;
      return { ...request, env: changed };
    },
    "agent.create.after": async ({ agent }) => {
      const m = mode();
      const parsed = parseAgentCreateAfterAgent(agent);
      const ids = { agent: parsed.id, cwd: parsed.cwd };
      const claim = await lookup(parsed.cwd);
      if (!claim || !claimAllowsAgent(claim, parsed.id)) {
        record(m, "agent.create.after", { action: "none", why: claim ? "claim owned by another agent" : "no active claim for cwd" }, ids);
        return;
      }
      const planned = { operation: "claim-bind-owner", claimId: claim.id, agentId: parsed.id };
      if (m.mode === "observe") { record(m, "agent.create.after", planned, ids); return; }
      const result = await perform("claim-bind-owner", parsed.cwd, { claimId: claim.id, agentId: parsed.id });
      record(m, "agent.create.after", planned, { ...ids, claim: claim.id },
        result.status === 0 ? undefined : `bind-owner refused (${result.status})`);
    },
  };
}
