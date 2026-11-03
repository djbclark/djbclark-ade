// Native Pi bridge, NOT an OMP extension. See pi-native-controls.md.
// Deliberately uses only JS syntax so CI can exercise the exact module without
// loading Pi or a provider. JSDoc imports describe Pi's public API.
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { randomUUID } from "node:crypto";

function writeJson(file, data) {
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data), { mode: 0o600 });
  fs.renameSync(tmp, file);
}

/** @param {import('@earendil-works/pi-coding-agent').ExtensionAPI} pi */
export default function (pi) {
  const root = path.join(process.env.AUTORENAME_STATE_DIR || path.join(os.homedir(), ".local/state/autorename"), "pi");
  const instance = randomUUID().replaceAll("-", "");
  const directory = path.join(root, instance);
  const registry = path.join(root, `${process.pid}.json`);
  let current;
  let timer;
  let pending;
  let running = false;
  let promptOpen = false;
  let compactStatus = null;
  let active = false;

  function nameState() {
    const entries = current.sessionManager.getEntries();
    const info = entries.filter(e => e.type === "session_info").at(-1);
    const marker = entries.filter(e => e.type === "custom" && e.customType === "ade.pi.autorename").at(-1);
    const title = pi.getSessionName() || null;
    // Pi has no OMP titleSource. Pin any unknown name, including a /name with
    // the same text as a prior automatic name (different session_info ID).
    const source = title && marker?.data?.entryId === info?.id && marker?.data?.title === title
      ? marker.data.source : title ? "user" : null;
    return { title, source };
  }

  function publish() {
    if (!active) return;
    writeJson(registry, {
      version: 1, pid: process.pid, instance,
      session_id: current.sessionManager.getSessionId(),
      session_file: current.sessionManager.getSessionFile() || null,
      provider: current.model?.provider || null, model: current.model?.id || null,
      thinking: current.thinkingLevel, ...nameState(), compact_status: compactStatus,
    });
  }

  function identity(body) {
    if (!active || body.instance !== instance || body.session_id !== current.sessionManager.getSessionId()
        || body.session_file !== (current.sessionManager.getSessionFile() || null)) {
      throw new Error("Pi session changed");
    }
  }

  function modelIdentity(body) {
    if (!body.provider || !body.model || !body.thinking || body.provider !== current.model?.provider
        || body.model !== current.model?.id || body.thinking !== current.thinkingLevel) {
      throw new Error("Pi selected model/reasoning changed");
    }
  }

  function safeUI() {
    // RPC getEditorText is a stub: only a TUI can prove the draft is empty.
    if (current.mode !== "tui") throw new Error("native compaction requires Pi TUI mode");
    if (promptOpen || current.ui.getEditorText() !== "") throw new Error("draft or dialog present; nothing changed");
  }

  function finish(status, error = null) {
    compactStatus = { nonce: compactStatus?.nonce, status, error };
    running = false;
    publish();
    if (active && error) current.ui.notify(`self-slash: ${error}`, "warning");
  }

  function drain() {
    if (!active || !pending || running) return;
    try {
      identity(pending);
      modelIdentity(pending);
      safeUI();
      if (Date.now() > pending.deadline) throw new Error("queued compaction expired");
      if (!current.isIdle() || current.hasPendingMessages()) return;
      const focus = pending.focus;
      pending = undefined;
      running = true;
      compactStatus.status = "running";
      publish();
      current.compact({
        customInstructions: focus || undefined,
        onComplete: () => finish("completed"),
        onError: error => finish("failed", String(error.message || error)),
      });
    } catch (error) {
      pending = undefined;
      finish("refused", String(error.message || error));
    }
  }

  function serve() {
    if (!active) return;
    for (const file of fs.readdirSync(directory)) {
      const match = /^([a-f0-9]{32})\.request\.json$/.exec(file);
      if (!match) continue;
      const nonce = match[1];
      const result = { nonce, instance, accepted: false, status: "refused", error: null };
      const request = path.join(directory, file);
      try {
        const body = JSON.parse(fs.readFileSync(request, "utf8"));
        fs.unlinkSync(request);
        if (body.nonce !== nonce || !Number.isFinite(body.expires) || body.expires < Date.now()) throw new Error("invalid or expired request");
        identity(body);
        if (body.action === "rename") {
          if (typeof body.title !== "string" || !body.title.trim() || body.title.length > 80 || /[\x00-\x1f\x7f]/.test(body.title)) throw new Error("invalid title");
          if (body.auto === true && nameState().source === "user") {
            result.status = "skipped: operator-set title kept";
          } else {
            pi.setSessionName(body.title);
            const info = current.sessionManager.getEntries().filter(e => e.type === "session_info").at(-1);
            pi.appendEntry("ade.pi.autorename", { title: body.title, entryId: info?.id, source: body.auto === true ? "auto" : "user" });
            result.status = "renamed";
          }
        } else if (body.action === "compact") {
          if (process.env.ACP_RUN_AGENT === "1") throw new Error("dispatched slice cannot compact");
          modelIdentity(body);
          safeUI();
          if (typeof body.focus !== "string" || body.focus.length > 4000) throw new Error("invalid compaction focus");
          if (pending || running) throw new Error("compaction already queued/running");
          const last = current.sessionManager.getEntries().filter(e => e.type === "compaction").at(-1);
          if (last && Date.now() - Date.parse(last.timestamp) < 1800000) throw new Error("compacted within 30 minutes");
          pending = { ...body, deadline: Date.now() + 900000 };
          compactStatus = { nonce, status: "queued", error: null };
          result.status = "queued (not completed)";
        } else throw new Error("unsupported native action");
        result.accepted = true;
        publish();
      } catch (error) {
        fs.rmSync(request, { force: true });
        result.error = String(error.message || error);
      }
      writeJson(path.join(directory, `${nonce}.result.json`), result);
    }
    drain();
  }

  pi.on("session_start", (_event, ctx) => {
    current = ctx;
    active = true;
    fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
    publish();
    // Pi has no OMP ctx.setInterval; own and dispose a Node timer instead.
    timer = setInterval(() => {
      try { serve(); } catch { /* Retry I/O next tick; never affect the agent. */ }
    }, 250);
    timer.unref();
  });
  for (const event of ["model_select", "thinking_level_select", "session_info_changed", "session_tree", "agent_settled"]) {
    pi.on(event, (_event, ctx) => { current = ctx; publish(); });
  }
  pi.on("ui_prompt_start", () => { promptOpen = true; });
  pi.on("ui_prompt_end", () => { promptOpen = false; });
  pi.on("session_before_compact", () => {
    // A built-in/automatic compaction supersedes a queued request.
    if (pending) { pending = undefined; finish("refused", "another compaction started"); }
  });
  pi.on("session_shutdown", () => {
    active = false;
    clearInterval(timer);
    pending = undefined;
    // Runtime replacement loads a fresh instance; never carry requests forward.
    fs.rmSync(registry, { force: true });
    fs.rmSync(directory, { recursive: true, force: true });
  });
}
