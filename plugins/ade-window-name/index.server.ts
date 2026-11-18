import type { PluginServerContext } from "@getpaseo/plugin/server";
import { registerAdeWindowNameHooks } from "./server/name-lib.mjs";

/**
 * Paseo server entry: name a new window `<KIND> <repo> (<work>)` (docs/workspace-layout.md) on `agent.create.after`, retried on
 * `agent.turn.after` while the agent has no title yet. The decision is bin/ade_ws_autoname.py; this plugin only gathers facts
 * from the daemon, runs it, and calls `workspaces.ref(id).setTitle`.
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
  return registerAdeWindowNameHooks(server, server.sourceDirectory === undefined ? {} : { pluginRoot: server.sourceDirectory, managed: server.managedSource === true });
}
