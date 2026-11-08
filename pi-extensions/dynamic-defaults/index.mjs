import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";

const PROVIDER = "ade";
const MODEL = "auto";
const TASK_ENTRY = "ade.task";
const ROUTE_ENTRY = "ade.route";
const KINDS = new Set(["code", "mechanical", "bulk", "research", "judgment", "frontier"]);
const INITIAL = Object.freeze({ epoch: "initial", kind: "code", nativeTools: false });
const FIXED_ERROR = "ADE Auto could not select an available model.";
const safeName = (value) => typeof value === "string" && /^[a-z][a-z0-9_-]{0,63}$/.test(value);
const selectedAuto = (model) => model?.provider === PROVIDER && model.id === MODEL;
const physical = (model) => model && model.api !== "pi-virtual" && !selectedAuto(model);

/** Interpret only a matched runtime failure, never prompt or tool content. */
export function confirmedFailure(message) {
  if (typeof message !== "string") return undefined;
  if (/\binsufficient[_ ](?:funds|credits|balance)\b|\bcredit balance (?:is )?too low\b|\bpayment required\b|\bbilling[_ ](?:hard[_ ]limit|quota|limit|error)\b/i.test(message)) return "billing";
  if (/\binsufficient_quota\b|\bquota[_ ](?:exceeded|exhausted)\b|\b(?:usage|weekly|monthly|daily) limit (?:has been )?(?:exceeded|reached|exhausted)\b|\b(?:exceeded|exhausted) (?:your |the )?(?:usage )?quota\b/i.test(message)) return "quota";
  return undefined;
}

/** Bounded argv-only subprocess boundary. Child diagnostics never reach the transcript. */
export function runHelper(command, args, input, { signal, timeoutMs = 70_000, spawnImpl = spawn } = {}) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(new Error(FIXED_ERROR)); return; }
    let child;
    try { child = spawnImpl(command[0], [...command.slice(1), ...args], { stdio: ["pipe", "pipe", "pipe"] }); }
    catch { reject(new Error(FIXED_ERROR)); return; }
    let output = "";
    let size = 0;
    let settled = false;
    let failure = false;
    let timer;
    let killTimer;
    const stop = () => {
      if (settled) return;
      failure = true;
      child.kill("SIGTERM");
      killTimer ??= setTimeout(() => child.kill("SIGKILL"), 250);
    };
    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      clearTimeout(killTimer);
      signal?.removeEventListener("abort", stop);
      if (error) reject(new Error(FIXED_ERROR)); else resolve(value);
    };
    child.on("error", () => finish(true));
    child.stdout.on("data", (chunk) => {
      size += chunk.length;
      if (size > 16_384) stop(); else output += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk) => { size += chunk.length; if (size > 16_384) stop(); });
    child.stdin.on("error", () => stop());
    child.on("close", (code) => finish(failure || code !== 0, output));
    timer = setTimeout(stop, timeoutMs);
    signal?.addEventListener("abort", stop, { once: true });
    if (signal?.aborted) stop();
    const payload = input === undefined ? "" : JSON.stringify(input);
    if (Buffer.byteLength(payload) > 1_048_576) stop();
    child.stdin.end(payload);
  });
}

function choiceValid(choice) {
  return choice?.schema_version === 1 && typeof choice.epoch === "string"
    && safeName(choice.kind) && safeName(choice.service) && safeName(choice.provider)
    && typeof choice.id === "string" && choice.id.length > 0 && choice.id.length <= 512
    && !/[\x00-\x1f]/.test(choice.id) && ["off", "low", "high"].includes(choice.thinking);
}

/** Injectable factory exercises the registered route without loading Pi or credentials in tests. */
export function createDynamicDefaults({
  stateEntryType = ROUTE_ENTRY,
  helperCommand = [fileURLToPath(new URL("../../bin/pi-default", import.meta.url))],
  spawnImpl = spawn,
  timeoutMs = 70_000,
  epoch = randomUUID,
  isServiceBlocked,
} = {}) {
  if (typeof stateEntryType !== "string" || !stateEntryType) throw new Error(FIXED_ERROR);
  const invoke = (args, input, signal) => runHelper(helperCommand, args, input, { signal, timeoutMs, spawnImpl });
  const blocked = isServiceBlocked ?? (async (service, signal) => {
    let result;
    try { result = JSON.parse(await invoke(["--check-service", service], undefined, signal)); }
    catch { throw new Error(FIXED_ERROR); }
    if (result?.schema_version !== 1 || result.service !== service || typeof result.blocked !== "boolean") throw new Error(FIXED_ERROR);
    return result.blocked;
  });
  return function register(pi) {
    const branch = (ctx) => ctx.sessionManager.getBranch();
    const latestTask = (ctx) => {
      const entry = branch(ctx).findLast((item) => item.type === "custom" && item.customType === TASK_ENTRY);
      if (!entry) return INITIAL;
      const value = entry.data;
      if (!value || typeof value.epoch !== "string" || !safeName(value.kind) || typeof value.nativeTools !== "boolean") throw new Error(FIXED_ERROR);
      return value;
    };
    const storedChoice = (ctx) => branch(ctx).findLast((item) => item.type === "custom"
      && item.customType === stateEntryType && item.data?.provider === PROVIDER
      && item.data?.modelId === MODEL)?.data?.state;
    const available = (ctx) => ctx.modelRegistry.getAvailable().filter(physical);
    const lookup = (ctx, choice) => {
      const model = ctx.modelRegistry.find(choice.provider, choice.id);
      return physical(model) && available(ctx).some((entry) => entry.provider === choice.provider && entry.id === choice.id) ? model : undefined;
    };
    const pick = async (ctx, task, excluded, signal) => {
      const ids = available(ctx).map((model) => `${model.provider}/${model.id}`);
      const args = ["--kind", task.kind, "--models-json", "-"];
      if (task.nativeTools) args.push("--native-tools");
      for (const service of excluded) args.push("--exclude-service", service);
      const raw = await invoke(args, ids, signal);
      let result;
      try { result = JSON.parse(raw); } catch { throw new Error(FIXED_ERROR); }
      if (!result || typeof result !== "object" || Array.isArray(result)) throw new Error(FIXED_ERROR);
      const choice = { schema_version: result.schema_version, epoch: task.epoch, kind: result.kind,
        service: result.service, provider: result.provider, id: result.model, thinking: result.thinking };
      if (!choiceValid(choice) || result.kind !== task.kind || result.model_id !== `${choice.provider}/${choice.id}`
        || excluded.has(choice.service) || !lookup(ctx, choice)) throw new Error(FIXED_ERROR);
      return choice;
    };
    pi.registerVirtualModel({
      provider: PROVIDER, id: MODEL, name: "ADE Auto", thinkingLevels: ["off", "low", "high"],
      async route(request, ctx) {
        const direct = request.reason === "direct";
        let choice = direct ? storedChoice(ctx) : request.state;
        if (choice !== undefined && !choiceValid(choice)) throw new Error(FIXED_ERROR);
        const task = direct ? (choice ? { epoch: choice.epoch, kind: choice.kind, nativeTools: false } : INITIAL) : latestTask(ctx);
        const excluded = new Set();
        // Record a known failure before discarding an old epoch; a new task cannot erase it.
        if (choice && request.failed?.model?.provider === choice.provider && request.failed.model.id === choice.id) {
          const reason = confirmedFailure(request.failed.message?.errorMessage);
          if (reason) {
            await invoke(["--block-service", choice.service, "--reason", reason], undefined, request.signal);
            excluded.add(choice.service);
            choice = undefined;
          }
        }
        if (choice && await blocked(choice.service, request.signal)) { excluded.add(choice.service); choice = undefined; }
        // A direct summary keeps the prior task even when a next-task marker is pending.
        if (!direct && choice?.epoch !== task.epoch) choice = undefined;
        if (choice && !lookup(ctx, choice)) { excluded.add(choice.service); choice = undefined; }
        if (!choice) choice = await pick(ctx, task, excluded, request.signal);
        const model = lookup(ctx, choice);
        if (!model) throw new Error(FIXED_ERROR);
        const result = { model, thinkingLevel: choice.thinking };
        if (!direct) {
          // Own public custom entry avoids depending on an internal Pi state-tag or SDK package resolution.
          if (choice !== request.state) pi.appendEntry(stateEntryType, { provider: PROVIDER, modelId: MODEL, state: choice });
          result.state = choice;
        }
        return result;
      },
    });
    pi.registerCommand("ade-task", {
      description: "Begin an explicit automatic-routing task: /ade-task [kind] [--native-tools]",
      async handler(args, ctx) {
        const notify = (message) => ctx.ui?.notify(message, "info");
        if (!ctx.isIdle() || ctx.hasPendingMessages()) { notify("ADE task boundary requires idle with no queued messages."); return; }
        if (!selectedAuto(ctx.model)) { notify("Select ade/auto before starting an automatic task."); return; }
        const words = args.trim() ? args.trim().split(/\s+/) : [];
        const nativeTools = words.includes("--native-tools");
        const kinds = words.filter((word) => word !== "--native-tools");
        if (kinds.length > 1 || words.filter((word) => word === "--native-tools").length > 1 || (kinds[0] && !KINDS.has(kinds[0]))) {
          notify("Use /ade-task [kind] [--native-tools]."); return;
        }
        pi.appendEntry(TASK_ENTRY, { epoch: epoch(), kind: kinds[0] ?? "code", nativeTools });
        notify("ADE task boundary recorded; the next request selects its model.");
      },
    });
  };
}

export default createDynamicDefaults();
