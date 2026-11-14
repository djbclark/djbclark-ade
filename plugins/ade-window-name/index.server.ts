import type { PluginServerContext } from "@getpaseo/plugin/server";
import { registerAdeWindowNameHooks } from "./server/name-lib.mjs";

/**
 * Paseo server entry: name a new window `<KIND> <repo> (<work>)` (docs/workspace-layout.md) on `agent.create.after`, retried on
 * `agent.turn.after` while the agent has no title yet. The decision is bin/ade_ws_autoname.py; this plugin only gathers facts
 * from the daemon, runs it, and calls `workspaces.ref(id).setTitle`.
 */
export default function contribute(server: PluginServerContext) {
  return registerAdeWindowNameHooks(server);
}
