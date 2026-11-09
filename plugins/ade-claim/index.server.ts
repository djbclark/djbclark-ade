import type { PluginServerContext } from "@getpaseo/plugin/server";
import { registerAdeClaimHooks } from "./server/hook.mjs";

/**
 * Paseo server entry:
 * - W2: claim the worktree when git worktree add completes; run trusted ade-git-guard install
 * - W2 follow-up: release the claim on workspace.archive.after
 * - W3: export ADE_CLAIM_ID on agent.open.before; bind owner on agent.create.after
 * - W4: prepend libexec/agent-bin to PATH on agent.open.before
 */
export default function contribute(server: PluginServerContext) {
  return registerAdeClaimHooks(server);
}
