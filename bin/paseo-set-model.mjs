// paseo-set-model.mjs: the node half of bin/paseo-set-model. Runs inside Paseo's bundled Electron
// node (ELECTRON_RUN_AS_NODE=1) and talks to the daemon through the bundled CLI's own client:
//   set <agent-id-or-prefix> <[provider/]model> [--dry-run]   switch a live agent's model in place
//   list                                                     print every agent the daemon knows, as JSON
// The daemon's set_agent_model_request is what the Paseo UI's model picker sends; the CLI has no
// command for it (docs/upstream-issues.md section 17). Exit codes: 0 ok, 1 error, 2 usage,
// 3 no such agent, 4 the re-fetch shows another model.
// PASEO_SET_MODEL_CLI_DIST: the bundled CLI's dist directory (set by the launcher).
import { pathToFileURL } from "node:url";
import path from "node:path";

const DIST = process.env.PASEO_SET_MODEL_CLI_DIST;
if (!DIST) { console.error("error: PASEO_SET_MODEL_CLI_DIST is not set"); process.exit(1); }
const load = (rel) => import(pathToFileURL(path.join(DIST, rel)).href);

// A leading `provider/` on a model names a provider; only these are treated as one, because an
// omp model id is itself `anthropic/claude-…` and must pass through whole.
const PROVIDERS = new Set(["claude", "codex", "opencode", "omp", "pi", "copilot", "gemini", "cursor", "grok", "zai"]);

const modelOf = (a) => a.model ?? a.config?.model ?? a.runtimeInfo?.model ?? "?";
const summary = (a) => ({
  id: a.id,
  name: a.title ?? null,
  provider: a.provider,
  model: modelOf(a),
  status: a.status,
  archived: Boolean(a.archivedAt),
  ...(a.parentAgentId ? { parentAgentId: a.parentAgentId } : {}),
});

const [cmd, ...rest] = process.argv.slice(2);
if (cmd !== "set" && cmd !== "list") {
  console.error("usage: paseo-set-model.mjs set <agent> <[provider/]model> [--dry-run] | list");
  process.exit(2);
}
const flags = rest.filter((x) => x.startsWith("--"));
const pos = rest.filter((x) => !x.startsWith("--"));
if (flags.some((f) => f !== "--dry-run" || cmd !== "set") || (cmd === "set" && pos.length !== 2) || (cmd === "list" && pos.length)) {
  console.error("usage: paseo-set-model.mjs set <agent> <[provider/]model> [--dry-run] | list");
  process.exit(2);
}

let client;
let code = 1;

// every exit goes through here: `process.exit` inside the work would skip the `finally` that closes the client and could
// cut off a large `list` JSON still queued in the stdout pipe (Codex pass 1 on PR 31, P1)
async function work() {
  const { connectToDaemon } = await load("utils/client.js");
  const { selectDaemonTarget } = await load("utils/daemon-target.js");
  client = await connectToDaemon({ target: selectDaemonTarget({}) });
  if (cmd === "list") {
    const { fetchAllAgents } = await load("utils/agent-directory.js");
    const agents = await fetchAllAgents(client, { filter: { includeArchived: true, includeBackground: true } });
    console.log(JSON.stringify(agents.map(summary), null, 1));
    return 0;
  }
  const [id, requested] = pos;
  const got = await client.fetchAgent({ agentId: id });
  if (!got) { console.error(`no agent ${id}`); return 3; }
  const a = got.agent;
  let model = requested;
  const slash = requested.indexOf("/");
  if (slash > 0) {
    const prefix = requested.slice(0, slash);
    if (prefix === a.provider) model = requested.slice(slash + 1);
    else if (PROVIDERS.has(prefix)) {
      console.error(`refusing ${requested}: agent ${a.id.slice(0, 7)} runs on provider ${a.provider}, setModel is per provider`);
      return 1;
    }
  }
  const before = modelOf(a);
  console.log(`agent ${a.id.slice(0, 7)} provider=${a.provider} status=${a.status} model=${before}`);
  if (flags.includes("--dry-run")) return 0;
  await client.setAgentModel(a.id, model);
  const after = (await client.fetchAgent({ agentId: a.id })).agent;
  const now = modelOf(after);
  console.log(`set: ${before} -> ${now}`);
  return now === model ? 0 : 4;
}

try {
  code = await work();
} catch (e) {
  console.error(`error: ${e?.message ?? e}`);
  code = 1;
} finally {
  if (client) await client.close().catch(() => {});
}
// let both pipes drain before the process ends: a large `list` JSON must reach the governor whole
await new Promise((resolve) => process.stdout.write("", resolve));
await new Promise((resolve) => process.stderr.write("", resolve));
process.exit(code);
