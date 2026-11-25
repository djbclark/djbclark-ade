// ade-pin-workspaces.mjs: the node half of bin/ade-pin-workspaces. Runs inside Paseo's bundled
// Electron node (ELECTRON_RUN_AS_NODE=1) and talks to the daemon through the bundled CLI's own
// client, the same way bin/paseo-set-model.mjs does.
//
//   pin [--check]     pin every non-worker window (LEAD, OTHER, and any window not a WORKER box),
//                     so leads and operator-started agents sort to the top of the sidebar.
//                     --check prints what would be pinned and pins nothing.
//
// The daemon's workspace.pin.set_request is what the Paseo UI's sidebar pin sends; the `paseo` CLI
// has no command for it (docs/upstream-issues.md draft 23). setWorkspacePinned is the CLI client's
// method for it.
//
// Classification is by the WINDOW name, which the ADE window scheme makes unambiguous
// (docs/workspace-layout.md): a window titled `WORKER <repo> (<work>)` is a worker box and is never
// pinned, and any window titled `RETIRED …` is skipped (2026-11-23); `LEAD …`, `OTHER …`, and any
// other active window (operator-started or a lead with a custom name) are pinned. Background and
// archived workspaces are skipped. Already-pinned windows are a no-op.
//
// Exit codes: 0 pinned (or nothing to do), 1 error, 2 usage, 69 macOS only (the launcher reports
// helper-missing before we run).
import { pathToFileURL } from "node:url";
import { readdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import path from "node:path";

const DIST = process.env.PASEO_SET_MODEL_CLI_DIST;
if (!DIST) { console.error("error: PASEO_SET_MODEL_CLI_DIST is not set"); process.exit(1); }
const load = (rel) => import(pathToFileURL(path.join(DIST, rel)).href);

const [cmd, ...rest] = process.argv.slice(2);
if (cmd !== "pin" || rest.some((x) => x !== "--check")) {
  console.error("usage: ade-pin-workspaces.mjs pin [--check]");
  process.exit(2);
}
const check = rest.includes("--check");

function loadRegisteredBoxes() {
  const dir = process.env.ADE_WORKER_RUN_STATE || path.join(homedir(), ".local", "state", "ade", "worker-run");
  const out = new Map();
  let files = [];
  try {
    files = readdirSync(dir).filter((f) => f.endsWith(".windows.json")).sort();
  } catch {
    return out;
  }
  for (const f of files) {
    try {
      const data = JSON.parse(readFileSync(path.join(dir, f), "utf8"));
      const entries = data && typeof data.entries === "object" ? data.entries : {};
      for (const [wid, entry] of Object.entries(entries || {})) {
        if (entry && typeof entry.box === "string" && !out.has(wid)) {
          out.set(wid, entry.box.toUpperCase());
        }
      }
    } catch {
      // skip unreadable registry files
    }
  }
  return out;
}

const effectiveName = (w) => w.title ?? w.name ?? "";
const isExcluded = (w, boxes) => {
  const box = boxes.get(w.id ?? w.workspaceId ?? "");
  if (box === "WORKER") return true;
  if (box === "LEAD" || box === "OTHER") return false;
  const n = String(effectiveName(w));
  return n.startsWith("WORKER ") || n.startsWith("WORKERS ") || n.startsWith("RETIRED ");
};

let client;
let code = 1;

async function work() {
  const { connectToDaemon } = await load("utils/client.js");
  const { selectDaemonTarget } = await load("utils/daemon-target.js");
  client = await connectToDaemon({ target: selectDaemonTarget({}) });
  if (typeof client.setWorkspacePinned !== "function") {
    console.error("error: the daemon client exposes no setWorkspacePinned; pinning is not available in this Paseo build");
    return 1;
  }
  const boxes = loadRegisteredBoxes();
  const ws = await client.fetchWorkspaces({});
  const entries = Array.isArray(ws?.entries) ? ws.entries : [];
  const targets = entries.filter((w) =>
    !w.background && !w.archivingAt && !w.archivedAt && !isExcluded(w, boxes));
  const todo = targets.filter((w) => !w.pinnedAt);
  if (check) {
    for (const w of targets) {
      console.log(`${w.pinnedAt ? "already-pinned" : "would-pin"} ${w.id}  ${effectiveName(w).slice(0, 50)}`);
    }
    console.log(`${todo.length}/${targets.length} window(s) to pin`);
    return 0;
  }
  let pinned = 0;
  for (const w of todo) {
    try {
      await client.setWorkspacePinned(w.id, true);
      console.log(`pinned ${w.id}  ${effectiveName(w).slice(0, 50)}`);
      pinned += 1;
    } catch (e) {
      console.error(`pin failed ${w.id}: ${e?.message ?? e}`);
    }
  }
  console.log(`pinned ${pinned}/${todo.length} window(s)`);
  return pinned === todo.length ? 0 : 1;
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
