// Explicit native candidate context only. No config, cwd, env or ancestor fallback.
import { lstatSync, realpathSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

export function bindSnapshot(sourceDirectory, id, helpers, env = process.env) {
  if (typeof sourceDirectory !== "string" || !sourceDirectory.startsWith("/") ||
      resolve(sourceDirectory) !== sourceDirectory || realpathSync(sourceDirectory) !== sourceDirectory ||
      !sourceDirectory.endsWith(`/plugins/${id}`)) throw new Error("Invalid snapshot sourceDirectory");
  const root = dirname(dirname(sourceDirectory));
  const forbidden = ["ADE_CLAIMS_PY", "ADE_GIT_GUARD", "ADE_AGENT_BIN", "ADE_WS_AUTONAME_PY", "ADE_PYTHON", "ADE_REAL_GIT"];
  for (const key of forbidden) {
    if (Object.prototype.hasOwnProperty.call(env, key)) throw new Error(`Unbound managed helper override: ${key}`);
  }
  function check(file, directory) {
    if (realpathSync(file) !== file) throw new Error("Snapshot links are refused");
    const st = lstatSync(file);
    if ((directory ? !st.isDirectory() : !st.isFile()) || (st.mode & 0o222))
      throw new Error("Snapshot entry must be sealed and regular");
  }
  for (const relative of [...helpers, `plugins/${id}/index.server.ts`]) {
    const file = join(root, relative);
    check(file, false);
    for (let dir = dirname(file); ; dir = dirname(dir)) {
      check(dir, true);
      if (dir === root) break;
      if (!dir.startsWith(root + "/")) throw new Error("Helper escapes snapshot root");
    }
  }
  return { root, pluginRoot: sourceDirectory };
}
