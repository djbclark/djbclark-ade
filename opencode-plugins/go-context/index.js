// Native OpenCode V2 plugin. No V1 hook adapter or SDK runtime dependency.
import { readFileSync, realpathSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";

const SID = /^ses_[A-Za-z0-9]+$/;
const MAX_SESSIONS = 256;
export const policyPath = resolve(dirname(realpathSync(fileURLToPath(import.meta.url))), "../../config/go-model-policy.json");
export const loadPolicy = () => JSON.parse(readFileSync(policyPath, "utf8"));
const inputTokens = (tokens) => {
  const parts = [tokens?.input, tokens?.cache?.read, tokens?.cache?.write];
  return parts.every((n) => typeof n === "number" && Number.isFinite(n) && n >= 0)
    ? parts.reduce((a, b) => a + b, 0) : null;
};

export async function createGuard(ctx, policy = loadPolicy(), now = Date.now) {
  const scope = JSON.stringify([ctx.location?.directory, ctx.location?.workspaceID]);
  const storageKey = `go-context-v1:${createHash("sha256").update(scope).digest("hex").slice(0, 24)}`;
  const states = new Map();
  let saveQueue = Promise.resolve();
  let storageReadable = true;
  let streamAvailable = true;
  try {
    const saved = await ctx.storage.get(storageKey);
    if (saved != null && (typeof saved !== "object" || Array.isArray(saved))) throw new Error("invalid state");
    for (const [sid, state] of Object.entries(saved ?? {}).slice(-MAX_SESSIONS)) {
      if (!SID.test(sid) || !state || typeof state.model !== "string" ||
          ![state.sampleAt, state.attemptAt].every((n) => Number.isFinite(n) && n >= 0) ||
          typeof state.pending !== "boolean") throw new Error("invalid state");
      states.set(sid, state);
    }
  } catch { storageReadable = false; }
  const save = () => {
    if (!storageReadable) return Promise.reject(new Error("prior Go state unreadable"));
    const snapshot = JSON.parse(JSON.stringify(Object.fromEntries(states)));
    saveQueue = saveQueue.catch(() => {}).then(() => ctx.storage.set(storageKey, snapshot));
    return saveQueue;
  };
  const remember = (sid, model) => {
    if (!SID.test(sid) || model?.providerID !== "opencode-go") return null;
    let state = states.get(sid);
    if (!state) {
      if (!states.has(sid) && states.size >= MAX_SESSIONS) {
        const victim = [...states].find(([, value]) => !value.pending);
        if (!victim) return null;
        states.delete(victim[0]);
      }
      state = { model: model.id, baseline: null, total: null, sampleAt: 0,
        attemptAt: 0, pending: false, blocked: false, failures: 0, notice: "",
        compactions: 0, handoffAt: 0, handoffTries: 0 };
      states.set(sid, state);
    } else if (state.model !== model.id || state.active === false) {
      // Model measurements may change; admission belongs to the conversation.
      // Preserve pending, cooldown, completion evidence and retry blocks.
      state.model = model.id;
      state.baseline = null;
      state.total = null;
      state.notice = "";
    }
    state.active = true;
    return state;
  };
  const profile = (state) => policy.routine_models.includes(state.model)
    ? policy.routine_context : policy.advisory_context;

  async function request(sid, state) {
    const cooling = () => state.attemptAt && now() - state.attemptAt < policy.compact_cooldown_seconds * 1000;
    if (!storageReadable || state.pending || state.blocked || cooling()) return false;
    // A failed read cannot be an uncertain write. Retry it after the cooldown.
    try {
      const response = await ctx.session.get({ sessionID: sid }, { signal: AbortSignal.timeout(10000) });
      const current = response?.data ?? response;
      if (current?.id !== sid || current.model?.providerID !== "opencode-go" || current.model.id !== state.model) {
        // A model switch must not discard session-level admission protection.
        return false;
      }
    } catch {
      state.attemptAt = now();
      await save().catch(() => {});
      return false;
    }
    // Another caller may have completed its lookup while this one awaited it.
    if (state.pending || state.blocked || cooling()) return false;
    state.pending = true;
    state.attemptAt = now();
    state.before = state.total;
    try { await save(); }
    catch { state.pending = false; state.blocked = true; return false; }
    try {
      await ctx.session.compact({ sessionID: sid }, { signal: AbortSignal.timeout(10000) });
      return true; // Acceptance only. Native completion releases pending state.
    } catch {
      // An uncertain write requires native completion evidence, never a blind retry.
      state.blocked = true;
      await save().catch(() => {});
      return false;
    }
  }

  const handoffText = (state, limits, tries) => {
    const byTokens = typeof state.total === "number" && state.total >= limits.handoff;
    const basis = byTokens
      ? `measured input context ${state.total} tokens (handoff ceiling ${limits.handoff})`
      : `${state.compactions ?? 0} automatic compactions (budget ${policy.handoff_after_compactions})`;
    const action = tries <= 1
      ? "At this task boundary, run the handoff skill and start a fresh session; do not continue this task in the current session."
      : `Overdue (fired ${tries} times): stop current work, write the owned handoff document, and start a fresh session through the handoff skill now.`;
    return `Automatic handoff required: ${basis}. ${action}`;
  };

  async function maybeHandoff(sid, state) {
    const limits = profile(state);
    const due = (typeof state.total === "number" && state.total >= limits.handoff) ||
      (state.compactions ?? 0) >= policy.handoff_after_compactions;
    if (!due) return;
    const cooldown = policy.handoff_cooldown_seconds * 1000;
    if (state.handoffAt && now() - state.handoffAt < cooldown) return;
    state.handoffAt = now();
    state.handoffTries = (state.handoffTries ?? 0) + 1;
    await save().catch(() => {});
    // The directive wakes the model into a fresh step; onContext escalates the
    // same wording into event.system via its own dedup if the model ignores it.
    try {
      await ctx.session.prompt(
        { sessionID: sid, prompt: { text: handoffText(state, limits, state.handoffTries) }, delivery: "steer" },
        { signal: AbortSignal.timeout(10000) },
      );
    } catch { /* the wake may fail; onContext still escalates the directive */ }
  }

  async function onContext(event) {
    if (event.model?.providerID !== "opencode-go") {
      const prior = states.get(event.sessionID);
      if (prior) prior.active = false;
      if (event.tools) delete event.tools.ade_compact;
      await save().catch(() => {});
      return;
    }
    const state = remember(event.sessionID, event.model);
    if (!state) return;
    const limits = profile(state);
    const handoffDue = (typeof state.total === "number" && state.total >= limits.handoff) ||
      (state.compactions ?? 0) >= policy.handoff_after_compactions;
    const warnDue = typeof state.total === "number" && now() - state.sampleAt < 15 * 60 * 1000 && state.total >= limits.warn;
    if (handoffDue || warnDue) {
      const level = !storageReadable || !streamAvailable || state.blocked || (state.pending && now() - state.attemptAt > 120000) ? "blocked" : (handoffDue ? "handoff" : "warn");
      if (state.notice !== level) {
        event.system.push({ type: "text", text: level === "handoff"
          ? handoffText(state, limits, Math.max(1, state.handoffTries ?? 0))
          : `Go cost check: last measured input context ${state.total} tokens, including cache reads/writes. ` +
            (level === "blocked" ? "Compaction is ineffective or unconfirmed. Reduce fixed instructions/tools and checkpoint at the next safe task boundary; do not loop compactions. " : "Keep the task brief and delegate separable work. Native compaction is queued automatically when its growth threshold is crossed. ") +
            "At a completed task, write the owned handoff before a supported new-session/baton cycle. Never clear a parent session. Use ade_compact for manual compaction of this session." });
        state.notice = level;
      }
    }
    await save().catch(() => {});
  }

  async function onEvent(event) {
    const sid = event.data?.sessionID;
    if (!SID.test(sid ?? "") || !states.has(sid)) return;
    if (event.location?.directory && ctx.location?.directory && event.location.directory !== ctx.location.directory) return;
    const state = states.get(sid);
    // session.idle is the task-boundary signal. It may carry no `created`, so it
    // must be handled before the staleness guard below.
    if (event.type === "session.idle") {
      if (state.active !== false) await maybeHandoff(sid, state);
      return;
    }
    const stamp = event.created;
    if (typeof stamp !== "number" || !Number.isFinite(stamp) || now() - stamp > 120000 || stamp > now() + 60000) return;
    if (event.type === "session.model.selected") {
      if (event.data.model?.providerID === "opencode-go") remember(sid, event.data.model);
      else state.active = false; // Unknown or non-Go selection: no automatic writes.
      await save().catch(() => {});
      return;
    }
    if (event.type === "session.compaction.ended") {
      if (stamp <= (state.compactedAt ?? 0)) return;
      state.compactedAt = stamp;
      state.pending = false;
      state.afterCompaction = true;
      state.notice = "";
      state.total = null;
      state.sampleAt = stamp;
      state.compactions = (state.compactions ?? 0) + 1;
      await save().catch(() => {});
      return;
    }
    if (event.type === "session.compaction.failed") {
      state.pending = false;
      state.failures = (state.failures ?? 0) + 1;
      state.blocked = true;
      await save().catch(() => {});
      return;
    }
    // usage.updated is a lifetime accumulator; title/summary usage is auxiliary.
    // Only a fresh primary step completion measures the active input context.
    if (state.active === false || event.type !== "session.step.ended" || stamp <= (state.sampleAt ?? 0)) return;
    const total = inputTokens(event.data.tokens);
    if (total === null || total === 0) return;
    state.sampleAt = stamp;
    state.total = total;
    if (state.afterCompaction) {
      state.afterCompaction = false;
      state.blocked = total >= profile(state).hard || (typeof state.before === "number" && total >= state.before * 0.9);
      state.baseline = total;
      state.failures = 0;
    }
    if (typeof state.baseline !== "number") state.baseline = total;
    const limits = profile(state);
    const due = total >= limits.hard || (total >= limits.compact && total - state.baseline >= policy.minimum_growth_tokens);
    if (due && streamAvailable && !state.pending && !state.blocked) await request(sid, state);
    await save().catch(() => {});
  }

  async function manual(sid) {
    if (!SID.test(sid ?? "")) return false;
    let response;
    try { response = await ctx.session.get({ sessionID: sid }, { signal: AbortSignal.timeout(10000) }); }
    catch { return false; }
    const info = response?.data ?? response;
    if (info?.id !== sid || info.model?.providerID !== "opencode-go") return false;
    const state = remember(sid, info.model);
    if (!state) return false;
    return request(sid, state);
  }
  const status = (sid) => ({ ready: storageReadable && streamAvailable,
    known: states.has(sid), pending: states.get(sid)?.pending ?? false,
    blocked: states.get(sid)?.blocked ?? false, attemptAt: states.get(sid)?.attemptAt ?? 0 });
  return { onContext, onEvent, manual, status, streamStopped: () => { streamAvailable = false; } };
}

export default {
  id: "ade.go-context",
  async setup(ctx) {
    const guard = await createGuard(ctx);
    const registrations = [
      await ctx.rpc.register({
        id: "ade.go-context", events: {}, methods: { compact: {
          input: { type: "object", properties: { sessionID: { type: "string" } }, required: ["sessionID"], additionalProperties: false },
          output: { type: "object", properties: { accepted: { type: "boolean" } }, required: ["accepted"], additionalProperties: false },
        }, status: {
          input: { type: "object", properties: { sessionID: { type: "string" } }, required: ["sessionID"], additionalProperties: false },
          output: { type: "object", properties: { ready: { type: "boolean" }, known: { type: "boolean" }, pending: { type: "boolean" }, blocked: { type: "boolean" }, attemptAt: { type: "number" } }, required: ["ready", "known", "pending", "blocked", "attemptAt"], additionalProperties: false },
        } },
      }, { compact: async ({ sessionID }) => ({ accepted: await guard.manual(sessionID) }),
           status: async ({ sessionID }) => guard.status(sessionID) }),
      await ctx.session.hook("context", guard.onContext),
      await ctx.tool.transform((editor) => editor.add({
        name: "ade_compact", description: "Queue safe native compaction for this OpenCode Go session; acceptance is not completion.",
        input: { type: "object", properties: {}, additionalProperties: false },
        execute: async (_input, context) => ({ content: await guard.manual(context.sessionID)
          ? "Native compaction accepted for this session; wait for completion."
          : "Compaction was not queued: verify Go session, durable state, pending request and cooldown. Do not loop." }),
      })),
    ];
    const controller = new AbortController();
    void (async () => {
      try {
        for await (const event of ctx.event.subscribe({ signal: controller.signal })) await guard.onEvent(event);
        if (!controller.signal.aborted) guard.streamStopped();
      } catch (error) {
        guard.streamStopped();
        if (!controller.signal.aborted) console.error("ade.go-context: event stream stopped; automatic compaction is unavailable");
      }
    })();
    return async () => {
      controller.abort();
      for (const registration of registrations) await registration.dispose();
    };
  },
};
