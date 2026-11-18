import { readFileSync, realpathSync, statSync, lstatSync } from "node:fs";
import { userInfo } from "node:os";
import { dirname, join, resolve, isAbsolute, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

function trusted(path, directory = false) {
  const stat = statSync(path), uid = process.getuid?.();
  if ((directory ? !stat.isDirectory() : !stat.isFile()) || (stat.mode & 0o022) ||
      (uid !== undefined && stat.uid !== uid && stat.uid !== 0)) throw new Error("ADE runtime path is not trusted");
}
function inside(root, path) {
  const actual = realpathSync(path), suffix = relative(root, actual);
  if (suffix === ".." || suffix.startsWith(".." + sep) || isAbsolute(suffix)) throw new Error("ADE runtime path escapes installed root");
  return actual;
}
function installRecord(env, home) {
  // Exact beta.2 paseo-home.ts supports PASEO_HOME; require an absolute path
  // (or an explicit home expansion), never resolve a plugin from an agent cwd.
  let paseoHome = env.PASEO_HOME ?? join(home, ".paseo");
  if (paseoHome === "~") paseoHome = home;
  else if (paseoHome.startsWith("~/")) paseoHome = join(home, paseoHome.slice(2));
  if (!isAbsolute(paseoHome)) throw new Error("Absolute Paseo home required");
  const file = join(paseoHome, "config.json"), stat = lstatSync(file);
  if (stat.isSymbolicLink() || stat.size > 1024 * 1024) throw new Error("ADE install record unavailable");
  trusted(file);
  const path = JSON.parse(readFileSync(file, "utf8"))?.plugins?.["ade-coord"]?.path;
  if (typeof path !== "string" || !isAbsolute(path)) throw new Error("ADE install record unavailable");
  return path;
}
/** CJS bundle evaluation has no import.meta.url. Resolve the exact configured
 * plugin directory instead; no shared-checkout or working-directory fallback. */
export function resolveRuntimePaths({ metaUrl, env = process.env, home = userInfo().homedir } = {}) {
  try {
    const source = typeof metaUrl === "string" && metaUrl.startsWith("file:") ? "file-url" : "paseo-install-record";
    const candidate = source === "file-url" ? resolve(dirname(fileURLToPath(metaUrl)), "..") : installRecord(env, home);
    const plugin = realpathSync(candidate), root = realpathSync(join(plugin, "../.."));
    if (plugin !== join(root, "plugins", "ade-coord")) throw new Error("ADE plugin layout mismatch");
    trusted(root, true); trusted(plugin, true);
    const manifest = inside(root, join(plugin, "paseo-plugin.json")); trusted(manifest);
    if (JSON.parse(readFileSync(manifest, "utf8")).id !== "ade-coord") throw new Error("ADE plugin identity mismatch");
    const paths = { root, plugin, source, driver: join(root, "bin/ade-coord"), controller: join(root, "bin/ade_coord_controller.py"), agentBin: join(root, "libexec/agent-bin"), instructions: join(root, "docs/nats-coordination.md") };
    for (const [name, path] of Object.entries(paths)) {
      if (["root", "plugin", "source"].includes(name)) continue;
      inside(root, path); trusted(path, name === "agentBin");
    }
    for (const path of ["plugins/ade-coord/index.server.ts", "plugins/ade-coord/server/hook.mjs", "lib/ade-coord/cli.js", "libexec/agent-bin/git", "libexec/agent-bin/paseo"]) trusted(inside(root, join(root, path)));
    return paths;
  } catch {
    // Never emit config contents, native errors or credential-bearing paths.
    throw new Error("ADE versioned runtime layout or install record unavailable");
  }
}
