import type { PluginServerContext } from "@getpaseo/plugin/server";
import { registerAdeClaimHooks } from "./server/hook.mjs";

/**
 * Paseo server entry:
 * - W2: claim the worktree when git worktree add completes
 * - W3: export ADE_CLAIM_ID on agent.open.before; bind owner on agent.create.after
 */
export default function contribute(server: PluginServerContext) {
  return registerAdeClaimHooks(server);
}
