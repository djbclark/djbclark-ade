import type { PluginServerContext } from "@getpaseo/plugin/server";
import { registerAdeClaimHooks } from "./server/hook.mjs";

/**
 * Paseo server entry:
 * - W2: claim the worktree when git worktree add completes; run trusted ade-git-guard install
 * - W2 follow-up: release the claim on workspace.archive.after
 * - W3: export ADE_CLAIM_ID on agent.open.before; bind owner on agent.create.after
 * - W4: prepend libexec/agent-bin to PATH on agent.open.before
 */
type SourceContext = PluginServerContext & {
  readonly sourceDirectory?: string;
  readonly managedSource?: boolean;
};

export default function contribute(server: SourceContext) {
  if (server.managedSource !== undefined && typeof server.managedSource !== "boolean") {
    throw new Error("Invalid native managedSource classification");
  }
  if (server.managedSource === true && server.sourceDirectory === undefined) {
    throw new Error("Managed source directory is required");
  }
  return registerAdeClaimHooks(server, server.sourceDirectory === undefined ? {} : { pluginRoot: server.sourceDirectory, managed: server.managedSource === true });
}
