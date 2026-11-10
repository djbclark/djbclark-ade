import type { PluginServerContext } from "@getpaseo/plugin/server";
import { registerWorktreeClaimHook } from "./server/hook.mjs";

/** Paseo server entry: claim the worktree when git worktree add completes. */
export default function contribute(server: PluginServerContext) {
  return registerWorktreeClaimHook(server);
}
