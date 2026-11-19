import { bindSnapshot } from "./snapshot-binding.mjs";
import { createWindowHandlers } from "./window-workflow.mjs";

/** Fixed SDK business seam; no raw process import or error fallback. */
export function createSemanticWindowHandlers(deps) {
  if (typeof deps.runOperation !== "function") throw new Error("ADE directory SDK operation unavailable");
  bindSnapshot(deps.pluginRoot, "ade-window-name", [
    "bin/ade_directory_operations.py", "bin/ade_claims.py", "bin/ade_ws_autoname.py", "bin/ade_ws_names.py",
  ], deps.env ?? process.env);
  return createWindowHandlers({ ...deps, propagateErrors: true, decide: async (info, signal) => {
    if (signal?.aborted) throw new Error("aborted");
    const result = await deps.runOperation({ version: 1, operation: "window-name-decision", ...info });
    if (signal?.aborted) throw new Error("aborted");
    if (result.status !== 0) throw new Error(`ADE window-name-decision refused (${result.status})`);
    return result.output;
  } });
}
