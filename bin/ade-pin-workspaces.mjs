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
import { closeSync, constants as fsConstants, fstatSync, openSync, readdirSync, readSync, realpathSync } from "node:fs";
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

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const WKS_RE = /^wks_[A-Za-z0-9]+$/;
const REPO_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const BOX_OF = Object.freeze({ LEAD: "LEAD", WORKER: "WORKER", OTHER: "OTHER", MAIN: "LEAD", WORKERS: "WORKER", USER: "OTHER" });
const MAX_REGISTRY_BYTES = 1_048_576;
const UTF8_DECODER = new TextDecoder("utf-8", { fatal: true });
const fullMatch = (re, s) => typeof s === "string" && !/[\r\n]/.test(s) && re.test(s);

function readRegularUtf8(filePath, anchorReal) {
  if (realpathSync(path.dirname(filePath)) !== anchorReal) {
    throw new Error("registry path escapes state dir");
  }
  const flags = fsConstants.O_RDONLY | (fsConstants.O_NOFOLLOW || 0) | (fsConstants.O_NONBLOCK || 0);
  const fd = openSync(filePath, flags);
  try {
    const st = fstatSync(fd);
    if (!st.isFile()) throw new Error("not a regular file");
    if (st.size > MAX_REGISTRY_BYTES) throw new Error("registry file too large");
    const chunks = [];
    let total = 0;
    const buf = Buffer.allocUnsafe(65536);
    for (;;) {
      const n = readSync(fd, buf, 0, Math.min(buf.length, MAX_REGISTRY_BYTES - total + 1), null);
      if (n === 0) break;
      total += n;
      if (total > MAX_REGISTRY_BYTES) throw new Error("registry file too large");
      chunks.push(Buffer.from(buf.subarray(0, n)));
    }
    return UTF8_DECODER.decode(Buffer.concat(chunks, total));
  } finally {
    closeSync(fd);
  }
}

function parseRegistryBoxes(text) {
  const data = JSON.parse(text);
  if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("root not object");
  if (!Array.isArray(data.windows) || !data.windows.every((w) => fullMatch(WKS_RE, w))) {
    throw new Error("bad windows list");
  }
  const idSet = new Set(data.windows);
  const parsed = new Map();
  if (!Object.prototype.hasOwnProperty.call(data, "entries")) {
    return parsed;
  }
  if (!data.entries || typeof data.entries !== "object" || Array.isArray(data.entries)) {
    throw new Error("bad entries map");
  }
  for (const [wid, raw] of Object.entries(data.entries)) {
    if (!fullMatch(WKS_RE, wid) || !idSet.has(wid)) throw new Error(`orphan entry ${wid}`);
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error(`bad entry ${wid}`);
    if (Object.prototype.hasOwnProperty.call(raw, "windowId") && raw.windowId !== wid) {
      throw new Error(`mismatched windowId ${wid}`);
    }
    if (Object.prototype.hasOwnProperty.call(raw, "repo")) {
      if (typeof raw.repo !== "string" || /[\r\n]/.test(raw.repo) || !fullMatch(REPO_RE, raw.repo.trim())) {
        throw new Error(`bad repo ${wid}`);
      }
    }
    if (Object.prototype.hasOwnProperty.call(raw, "lead")) {
      if (typeof raw.lead !== "string" || /[\r\n]/.test(raw.lead) || !fullMatch(UUID_RE, raw.lead.trim())) {
        throw new Error(`bad lead ${wid}`);
      }
    }
    for (const k of ["cwd", "work"]) {
      if (Object.prototype.hasOwnProperty.call(raw, k)) {
        if (typeof raw[k] !== "string" || !raw[k].trim()) throw new Error(`bad ${k} ${wid}`);
      }
    }
    if (Object.prototype.hasOwnProperty.call(raw, "box")) {
      if (typeof raw.box !== "string" || /[\r\n]/.test(raw.box)) throw new Error(`bad box ${wid}`);
      const norm = BOX_OF[raw.box.trim().toUpperCase()];
      if (!norm) throw new Error(`unknown box ${wid}`);
      parsed.set(wid, norm);
    }
  }
  return parsed;
}

function loadRegisteredBoxes() {
  const dir = process.env.ADE_WORKER_RUN_STATE || path.join(homedir(), ".local", "state", "ade", "worker-run");
  const out = new Map();
  let anchorReal;
  let files = [];
  try {
    anchorReal = realpathSync(dir);
    files = readdirSync(anchorReal)
      .filter((f) => f.endsWith(".windows.json") && fullMatch(UUID_RE, f.slice(0, -".windows.json".length)))
      .sort();
  } catch {
    return out;
  }
  for (const f of files) {
    try {
      const parsed = parseRegistryBoxes(readRegularUtf8(path.join(anchorReal, f), anchorReal));
      for (const [wid, box] of parsed.entries()) {
        if (!out.has(wid)) out.set(wid, box);
      }
    } catch {
      // skip unreadable or malformed registry files (aligned with Python all_registered_windows)
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
