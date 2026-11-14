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
const SETTLED_MAX = 1000;

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
export function isDryRun(env = process.env) {
  const v = String(env.ADE_WINDOW_NAME_DRY_RUN ?? "").trim().toLowerCase();
  return v !== "" && !["0", "false", "no", "off"].includes(v);
}

/** Run the decision script: JSON on stdin, JSON on stdout. Resolves to the parsed object; rejects on a non-zero exit or bad JSON. */
export function runDecision({ python = "python3", script, info, timeoutMs = SCRIPT_TIMEOUT_MS, exec = execFile }) {
  return new Promise((resolve, reject) => {
    const child = exec(python, ["-I", script], { encoding: "utf8", timeout: timeoutMs, maxBuffer: 1 << 20 }, (err, stdout, stderr) => {
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

const blank = (v) => typeof v !== "string" || v.trim() === "";
const entryAgent = (entry) => entry?.agent ?? entry;
const createdMs = (a) => {
  const t = Date.parse(a?.createdAt ?? "");
  return Number.isFinite(t) ? t : null;
};

/**
 * True when `self` is the window's first agent: no other (non-archived, non-background) agent in the window was created earlier
 * by `createdAt`, ties broken by id. When a time is missing on either side, a window holding no other agent decides.
 */
export function isFirstAgent(self, entries) {
  const others = entries.map(entryAgent).filter((a) => a && a.id !== self.id);
  const mine = createdMs(self);
  return others.every((o) => {
    const theirs = createdMs(o);
    if (mine === null || theirs === null) return false;
    return theirs > mine || (theirs === mine && String(o.id) > String(self.id));
  });
}

/**
 * Paseo gives a window created with a first prompt (the app's new-workspace screen, a plain create) the prompt's first line as
 * its title at once, and later replaces a title equal to that line with a generated one (workspace-auto-name.ts, rule K4). So a
 * title equal to the first agent's own title is still Paseo's default, not a name given on purpose.
 */
export function isDefaultTitle(windowTitle, agentTitle) {
  if (blank(windowTitle)) return true;
  if (SCHEME_NAME.test(windowTitle.trim())) return false; // already `<KIND> <repo> (<work>)`: never re-wrapped, whatever the tab is called
  return !blank(agentTitle) && windowTitle.trim() === agentTitle.trim();
}
const SCHEME_NAME = /^(?:MAIN|WORKERS|USER) \S+ \(.+\)$/;

/**
 * Handle one agent event. Returns a short outcome record (also the log line) and never throws.
 *
 * @param {{ id: string, workspaceId: string|null, parentAgentId?: string|null, cwd: string, title?: string|null, background?: boolean }} agent
 * @param {{ paseo: any }} context
 * @param {{ env?: object, pluginRoot?: string, run?: typeof runDecision, log?: (line: string) => void, settled?: Set<string>, python?: string }} [deps]
 */
export async function handleAgentEvent(agent, context, deps = {}) {
  const env = deps.env ?? process.env;
  const log = deps.log ?? ((line) => console.error(line));
  const settled = deps.settled ?? new Set();
  const out = (outcome, extra = {}) => {
    const rec = { hook: "window-name", agent: agent?.id, workspace: agent?.workspaceId ?? null, outcome, ...extra };
    log(`ade-window-name ${JSON.stringify(rec)}`);
    return rec;
  };
  try {
    const wid = agent?.workspaceId;
    if (!wid) return out("skip", { reason: "agent has no window" });
    if (agent.background) return out("skip", { reason: "background agent" });
    if (settled.has(wid)) return out("skip", { reason: "window settled" });
    const { paseo } = context;
    const handle = paseo.workspaces.ref(wid);
    const ws = await handle.refresh();
    if (!ws) return out("skip", { reason: "window not found" });
    if (ws.background) {
      remember(settled, wid);
      return out("skip", { reason: "background window" });
    }
    const self = (await paseo.agents.ref(agent.id).refresh())?.agent ?? {};
    const title = self.title ?? agent.title ?? null;
    // First-agent check before the title check: a joiner's event must not settle a prompt-titled window its first agent has yet to name.
    const listed = await paseo.agents.list({});
    const inWindow = (listed?.entries ?? []).filter((e) => entryAgent(e)?.workspaceId === wid);
    if (!isFirstAgent({ ...self, id: agent.id }, inWindow)) return out("skip", { reason: "not the window's first agent" });
    if (!isDefaultTitle(ws.title, title)) {
      remember(settled, wid);
      return out("skip", { reason: "window already has a title" });
    }
    const info = {
      cwd: agent.cwd,
      windowTitle: null, // default by the check above; the script's own title rule stays for a direct call
      firstAgent: true,
      background: false,
      agent: { title, parentAgentId: agent.parentAgentId ?? null, labels: self.labels ?? {} },
    };
    const script = resolveDecisionScript({ env, pluginRoot: deps.pluginRoot });
    const run = deps.run ?? runDecision;
    const decision = await run({ python: deps.python ?? env.ADE_PYTHON ?? "python3", script, info });
    if (decision?.action !== "rename") {
      if (decision?.retry !== true) remember(settled, wid);
      return out("skip", { reason: decision?.reason ?? "no decision" });
    }
    if (isDryRun(env)) return out("would-rename", { name: decision.name, kind: decision.kind });
    // A last read right before the write; Paseo has no compare-and-set, so a name given in the few milliseconds after this read
    // can still be overwritten (bin/ade-worker-run's own launches are skipped by the script for that reason).
    const again = await handle.refresh();
    if (!again || (!blank(again.title) && again.title !== ws.title)) {
      remember(settled, wid);
      return out("skip", { reason: "window was named while deciding" });
    }
    await handle.setTitle(decision.name);
    remember(settled, wid);
    return out("renamed", { name: decision.name, kind: decision.kind });
  } catch (err) {
    return out("error", { error: errText(err) });
  }
}

function remember(settled, wid) {
  if (settled.size >= SETTLED_MAX) settled.delete(settled.values().next().value);
  settled.add(wid);
}

/**
 * Register both hooks. Handlers run one at a time per window (`create.after` and a quick `turn.after` must not both rename),
 * and a decided window is remembered so later turns cost nothing.
 *
 * @param {{ addHook: (name: string, handler: Function) => () => void }} server
 * @param {Parameters<typeof handleAgentEvent>[2]} [deps]
 */
export function registerAdeWindowNameHooks(server, deps = {}) {
  const settled = deps.settled ?? new Set();
  const pluginRoot = deps.pluginRoot ?? resolvePluginRoot({ metaUrl: import.meta?.url });
  const chains = new Map();
  const handler = async ({ agent }, context) => {
    const key = agent?.workspaceId ?? "";
    const prev = chains.get(key) ?? Promise.resolve();
    const next = prev.then(() => handleAgentEvent(agent, context, { ...deps, pluginRoot, settled }));
    chains.set(key, next);
    try {
      await next;
    } finally {
      if (chains.get(key) === next) chains.delete(key);
    }
  };
  const offs = ["agent.create.after", "agent.turn.after"].map((name) => server.addHook(name, handler));
  return () => offs.forEach((off) => off());
}
