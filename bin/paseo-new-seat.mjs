// paseo-new-seat.mjs: the node half of bin/paseo-new-seat. Runs inside Paseo's bundled Electron node
// (ELECTRON_RUN_AS_NODE=1) and creates an agent through the daemon's own client, with
// config.featureValues.auto_accept = true so the seat never prompts on its first tool call.
//
// Why the config and not a follow-up `setAgentFeature`: Paseo's resolveACPCreateConfig only defaults
// auto_accept for an UNATTENDED create, and `paseo agent run` has no --unattended flag, so a
// run-then-set sequence leaves a window in which the agent's first tool call prompts. On 2026-10-25
// that window fired for real (a seat was told to read its brief at once and prompted before the
// feature could be set afterwards).
//
// Exit: 0 created and the shield verified; 1 error; 2 usage; 4 created but the shield stayed off.
import { pathToFileURL } from "node:url";
import path from "node:path";
import fs from "node:fs";
import os from "node:os";

const DIST = process.env.PASEO_NEW_SEAT_CLI_DIST;
if (!DIST) { console.error("error: PASEO_NEW_SEAT_CLI_DIST is not set"); process.exit(1); }
const load = (rel) => import(pathToFileURL(path.join(DIST, rel)).href);

const argv = process.argv.slice(2);
const opt = (name, dflt = undefined) => {
  const i = argv.indexOf(name);
  return i === -1 ? dflt : argv[i + 1];
};
const has = (name) => argv.includes(name);

if (argv.length === 0 || has("--help") || has("-h")) {
  console.error("usage: paseo-new-seat.mjs create --title T --provider P --model M --cwd D "
    + "[--prompt TEXT] [--workspace ID] [--auto-accept] [--dry-run]");
  process.exit(argv.length ? 0 : 2);
}
if (argv[0] !== "create") {
  console.error(`unknown command ${argv[0]}`);
  process.exit(2);
}

const title = opt("--title");
const provider = opt("--provider");
const model = opt("--model");
const cwd = opt("--cwd");
const prompt = opt("--prompt");
const workspaceId = opt("--workspace");
const allowNewWorkspace = has("--allow-new-workspace");
const autoAccept = has("--auto-accept");
const dryRun = has("--dry-run");

if (!title || !provider || !cwd) {
  console.error("create needs --title, --provider and --cwd");
  process.exit(2);
}

// REFUSE to create a workspace implicitly. `paseo agent run` (and this call) creates a NEW workspace
// named from the prompt when no workspaceId is given — which silently littered four empty `main`
// workspaces on 2026-10-25, and a workspace name is derived the same fragile way a tab name is. A
// seat almost always belongs in an existing workspace, so making the implicit path a hard error is
// the fix; --allow-new-workspace is the deliberate opt-in for the rare case it is wanted.
if (!workspaceId && !allowNewWorkspace) {
  console.error("refusing to create a workspace implicitly (that is how four empty `main` "
    + "workspaces appeared on 2026-10-25). Pass --workspace <id> to join an existing one, or "
    + "--allow-new-workspace if a new one is really wanted.");
  process.exit(2);
}

const config = {
  ...(model ? { model } : {}),
  // The whole point: the feature rides along WITH the create, so there is no grey window.
  ...(autoAccept ? { featureValues: { auto_accept: true } } : {}),
};

if (dryRun) {
  console.log(JSON.stringify({ title, provider, cwd, workspaceId: workspaceId ?? null,
    prompt: prompt ?? null, config }, null, 1));
  process.exit(0);
}

let client;
let code = 1;
async function work() {
  const { connectToDaemon } = await load("utils/client.js");
  const { selectDaemonTarget } = await load("utils/daemon-target.js");
  client = await connectToDaemon({ target: selectDaemonTarget({}) });
  const created = await client.createAgent({
    provider, cwd, title, config,
    ...(workspaceId ? { workspaceId } : {}),
    ...(prompt ? { initialPrompt: prompt } : {}),
  });
  const id = created?.id ?? created?.agent?.id;
  if (!id) { console.error("created, but the daemon returned no agent id"); return 1; }
  console.log(`created ${id.slice(0, 8)} title=${title}`);

  if (!autoAccept) return 0;

  // Verify the shield from the agent's own state file, which is what the UI icon reflects.
  const slug = String(cwd).replace(/\//g, "-").replace(/^-/, "");
  const stateFile = path.join(os.homedir(), ".paseo", "agents", slug, `${id}.json`);
  const readFeature = () => {
    try {
      const d = JSON.parse(fs.readFileSync(stateFile, "utf8"));
      const f = (d.features ?? []).find((x) => x?.id === "auto_accept");
      return f ? f.value === true : undefined;
    } catch { return undefined; }
  };
  let on = readFeature();
  for (let i = 0; i < 20 && on !== true; i++) {
    await new Promise((r) => setTimeout(r, 250));
    on = readFeature();
  }
  console.log(on === true ? "auto_accept: on (verified)"
    : "auto_accept: NOT verified - the shield may be grey; run paseo-set-model autoaccept " + id.slice(0, 8));
  return on === true ? 0 : 4;
}

try {
  code = await work();
} catch (e) {
  console.error(`error: ${e?.message ?? e}`);
  code = 1;
} finally {
  if (client) await client.close().catch(() => {});
}
await new Promise((resolve) => process.stdout.write("", resolve));
await new Promise((resolve) => process.stderr.write("", resolve));
process.exit(code);
