import type { PluginServerContext } from "@getpaseo/plugin/server";
import { registerAdeYoloHooks } from "./server/hook.mjs";

/**
 * Paseo server entry: force unattended (YOLO / Bypass) modeId on agent.create.before.
 */
export default function contribute(server: PluginServerContext) {
  return registerAdeYoloHooks(server);
}
