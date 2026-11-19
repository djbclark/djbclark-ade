import { bindSnapshot } from "./snapshot-binding.mjs";
import { execFile } from "node:child_process";
import { accessSync, constants, readFileSync } from "node:fs";
import { userInfo } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * ade-window-name: name a new Paseo window `<KIND> <repo> (<work>)` (docs/workspace-layout.md) when its first agent is created.
 *
 * The plugin is deliberately thin. Every naming rule (KIND, repo, work text, "is this a default name") lives in
 * bin/ade_ws_autoname.py on top of bin/ade_ws_names.py, the builder `bin/ade-worker-run` and `bin/ade-tidy` use; this file
 * gathers the facts from the daemon, runs that script (argv list, no shell, timeout), and calls `setTitle` on the result.
 *
 * Hooks (Paseo 0.16.0-beta.2 names, read at the tag): `agent.create.after` and `agent.turn.after`; both are notifications
 * (`waits: false`), so a failure here can never block an agent. The turn hook is the retry for an agent whose title was not
 * known at creation (ade_ws_autoname answers `retry: true`).
 */

const SCRIPT_TIMEOUT_MS = 20_000;

const errText = (err) => String(err instanceof Error ? err.message : err);

/**
 * Reviewed plugin directory (never the agent's worktree). Paseo bundles `index.server.ts` to CommonJS and evaluates it, where
 * `import.meta.url` is undefined (the ade-claim #638 D2 lesson): order is (1) a real `file:` URL (plain Node ESM, the tests),
 * (2) Paseo's install record `<home>/.paseo/config.json` `plugins["ade-window-name"].path`, (3) the shared checkout
 * `<home>/src/djbclark-ade/plugins/ade-window-name`. `<home>` is the account's home from the password database, never `$HOME`.
 *
 * @param {{ metaUrl?: unknown, home?: string }} [opts]
 */
export function resolvePluginRoot({ metaUrl, home = userInfo().homedir } = {}) {
  if (typeof metaUrl === "string" && metaUrl.startsWith("file:")) {
    return join(dirname(fileURLToPath(metaUrl)), "..");
  }
  try {
    const raw = readFileSync(join(home, ".paseo", "config.json"), "utf8");
    const path = JSON.parse(raw)?.plugins?.["ade-window-name"]?.path;
    if (typeof path === "string" && path.startsWith("/")) return path;
  } catch {
    // no readable install record: fall through to the shared checkout
  }
  return join(home, "src", "djbclark-ade", "plugins", "ade-window-name");
}

/** The decision script: `ADE_WS_AUTONAME_PY`, else `<plugin root>/../../bin/ade_ws_autoname.py`. Throws when unreadable. */
export function resolveDecisionScript({ env = process.env, pluginRoot, readable = isReadable } = {}) {
  const candidate = env.ADE_WS_AUTONAME_PY || join(pluginRoot, "..", "..", "bin", "ade_ws_autoname.py");
  if (!candidate.startsWith("/") || !readable(candidate)) {
    throw new Error(`ade_ws_autoname.py is not readable at ${candidate}; set ADE_WS_AUTONAME_PY to an absolute path`);
  }
  return candidate;
}

function isReadable(path) {
  try {
    accessSync(path, constants.R_OK);
    return true;
  } catch {
    return false;
  }
}

/** Observe mode: `ADE_WINDOW_NAME_DRY_RUN` set to anything but 0/false/no/off/empty logs the planned name and renames nothing. */


/** Run the decision script: JSON on stdin, JSON on stdout. Resolves to the parsed object; rejects on a non-zero exit or bad JSON. */
export function runDecision({ python = "python3", script, info, timeoutMs = SCRIPT_TIMEOUT_MS, exec = execFile, signal }) {
  return new Promise((resolve, reject) => {
    const child = exec(python, ["-I", script], { encoding: "utf8", timeout: timeoutMs, maxBuffer: 1 << 20, ...(signal ? { signal } : {}) }, (err, stdout, stderr) => {
      if (err) return reject(new Error(`ade_ws_autoname failed: ${errText(err)}${stderr ? `: ${String(stderr).slice(0, 300)}` : ""}`));
      try {
        resolve(JSON.parse(stdout));
      } catch (e) {
        reject(new Error(`ade_ws_autoname printed unreadable output: ${errText(e)}`));
      }
    });
    child.stdin?.on("error", () => {}); // python gone before it read the input: the exit status reports it
    child.stdin?.end(JSON.stringify(info));
  });
}

import { createWindowHandlers, handleAgentEvent as handleWindowEvent } from "./window-workflow.mjs";
export { isDryRun, isFirstAgent, isDefaultTitle, validName, HANDLER_BUDGET_MS } from "./window-workflow.mjs";

function legacyDecision(deps) {
  return (info, signal) => {
    const env = deps.env ?? process.env;
    const script = resolveDecisionScript({ env, pluginRoot: deps.pluginRoot });
    return (deps.run ?? runDecision)({ python: deps.python ?? env.ADE_PYTHON ?? "python3", script, info,
      ...(signal ? { signal } : {}) });
  };
}

export function handleAgentEvent(agent, context, deps = {}) {
  return handleWindowEvent(agent, context, { ...deps, decide: legacyDecision(deps) });
}

export function createLegacyWindowHandlers(deps = {}) {
  if (deps.managed) {
    const { root } = bindSnapshot(deps.pluginRoot, "ade-window-name",
      ["bin/ade_ws_autoname.py", "bin/ade_ws_names.py"], deps.env ?? process.env);
    deps = { ...deps, env: { ...(deps.env ?? process.env), ADE_WS_AUTONAME_PY: join(root, "bin/ade_ws_autoname.py") } };
  }
  const pluginRoot = deps.pluginRoot ?? resolvePluginRoot({ metaUrl: import.meta?.url });
  const context = { ...deps, pluginRoot };
  return createWindowHandlers({ ...context, decide: legacyDecision(context) });
}

export function registerAdeWindowNameHooks(server, deps = {}) {
  const offs = Object.entries(createLegacyWindowHandlers(deps)).map(([name, handler]) => server.addHook(name, handler));
  return () => offs.forEach((off) => off());
}
