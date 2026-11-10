import { applyYoloToCreateRequest } from "./yolo-lib.mjs";

/**
 * Force unattended modeId on every agent create (MCP children, UI seats, CLI),
 * unless restrictive or metadata ade-yolo.skip.
 *
 * @param {{ addHook: (name: string, handler: Function) => () => void }} server
 */
export function registerAdeYoloHooks(server) {
  return server.addHook("agent.create.before", async ({ request }) => {
    return applyYoloToCreateRequest(request);
  });
}
