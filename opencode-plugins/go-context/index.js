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

// The automatic-handoff policy is validated once, up front: a bad value must
// fail closed (no automatic wake) rather than open a paid, self-sustaining loop.
export const validHandoffPolicy = (policy) => {
  const n = (v) => typeof v === "number" && Number.isFinite(v);
  return n(policy?.handoff_cooldown_seconds) && policy.handoff_cooldown_seconds >= 300 &&
    n(policy?.handoff_after_compactions) && policy.handoff_after_compactions >= 1 &&
    n(policy?.handoff_max_wakes) && policy.handoff_max_wakes >= 1 &&
    n(policy?.routine_context?.handoff) && policy.routine_context.handoff > 0 &&
    n(policy?.advisory_context?.handoff) && policy.advisory_context.handoff > 0;
};

// A persisted record is trusted only when every field the guard later reads has a
// sane shape. A malformed record (e.g. a negative `handoffTries` that would skip
// the retry cap, or a string `compactions` that concatenates) fails the whole load
// closed rather than half-admitting it. A far-future `handoffAt` is not a shape
// failure: createGuard clamps it to now at load so one stale record cannot switch
// off the whole guard after a backward clock step.
const validPersistedState = (state) => {
  if (!state || typeof state !== "object" || Array.isArray(state)) return false;
  if (typeof state.model !== "string" || typeof state.pending !== "boolean") return false;
  const req = [state.sampleAt, state.attemptAt];
  const opt = [state.baseline, state.total, state.failures, state.compactions,
    state.handoffTries, state.before, state.compactedAt];
  const flags = [state.blocked, state.active, state.afterCompaction, state.child];
  const handoffAtOk = state.handoffAt == null ||
    (Number.isFinite(state.handoffAt) && state.handoffAt >= 0);
  return req.every((v) => Number.isFinite(v) && v >= 0) &&
    opt.every((v) => v == null || (Number.isFinite(v) && v >= 0)) &&
    flags.every((v) => v == null || typeof v === "boolean") &&
    handoffAtOk;
};

export async function createGuard(ctx, policy = loadPolicy(), now = Date.now) {
  const scope = JSON.stringify([ctx.location?.directory, ctx.location?.workspaceID]);
  const storageKey = `go-context-v1:${createHash("sha256").update(scope).digest("hex").slice(0, 24)}`;
  const states = new Map();
  let saveQueue = Promise.resolve();
  let storageReadable = true;
  let streamAvailable = true;
  const handoffEnabled = validHandoffPolicy(policy);
  try {
    const saved = await ctx.storage.get(storageKey);
    if (saved != null && (typeof saved !== "object" || Array.isArray(saved))) throw new Error("invalid state");
    for (const [sid, state] of Object.entries(saved ?? {}).slice(-MAX_SESSIONS)) {
      if (!SID.test(sid) || !validPersistedState(state)) throw new Error("invalid state");
      // A backward clock step (NTP correction after sleep) can leave a far-future
      // handoffAt; clamp it to now so one stale record cannot disable the guard.
      if (typeof state.handoffAt === "number" && state.handoffAt > now() + 60000) state.handoffAt = now();
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
        compactions: 0, handoffAt: 0, handoffTries: 0, child: null };
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
      : `${state.compactions ?? 0} compactions (budget ${policy.handoff_after_compactions})`;
    const action = tries <= 1
      ? "At this task boundary, run the handoff skill and start a fresh session; do not continue this task in the current session."
      : `Overdue (fired ${tries} times): stop current work, write the owned handoff document, and start a fresh session through the handoff skill now.`;
    return `Automatic handoff required: ${basis}. ${action} Never clear a parent session.`;
  };

  // A child or dispatched session must never be told to abandon its delegated
  // task and start a fresh session: it cannot take /handoff or /new. Soften the
  // notice to a report-back wording that carries no lifecycle command.
  const childHandoffText = (state, limits) => {
    const byTokens = typeof state.total === "number" && state.total >= limits.handoff;
    const basis = byTokens
      ? `measured input context ${state.total} tokens (handoff ceiling ${limits.handoff})`
      : `${state.compactions ?? 0} compactions (budget ${policy.handoff_after_compactions})`;
    return `Go cost check: ${basis}. This is a child or dispatched session: finish and report back to your parent. Never run a lifecycle command or hand off yourself.`;
  };

  async function maybeHandoff(sid, state) {
    if (!handoffEnabled || !storageReadable) return; // a malformed policy or unreadable prior state disables the wake (fail closed)
    if (process.env.ACP_RUN_AGENT === "1") return; // a dispatched slice cannot take /handoff or /new
    const limits = profile(state);
    const due = (typeof state.total === "number" && state.total >= limits.handoff) ||
      (state.compactions ?? 0) >= policy.handoff_after_compactions;
    if (!due) return;
    if ((state.handoffTries ?? 0) >= policy.handoff_max_wakes) return; // cap the paid wakes
    const cooldown = policy.handoff_cooldown_seconds * 1000;
    if (state.handoffAt && now() - state.handoffAt < cooldown) return;
    // A child session, a switched-away model or a vanished session must never be
    // woken to run a lifecycle: re-read live and require this exact Go model with
    // no parent, so a cached `active` flag cannot leak a wake into a fork. Cache
    // `state.child` from the same read so onContext can soften the directive for
    // a child until a primary is confirmed.
    let current;
    try {
      const response = await ctx.session.get({ sessionID: sid }, { signal: AbortSignal.timeout(10000) });
      current = response?.data ?? response;
    } catch { return; }
    if (!current || current.id !== sid || current.model?.providerID !== "opencode-go" || current.model.id !== state.model) return;
    state.child = Boolean(current.parentID);
    if (state.child) return;
    // Re-check the cap and cooldown after the awaited read, as request() does:
    // another idle may have claimed while this one was awaiting the live lookup.
    if ((state.handoffTries ?? 0) >= policy.handoff_max_wakes) return;
    if (state.handoffAt && now() - state.handoffAt < cooldown) return;
    state.handoffAt = now();
    state.handoffTries = (state.handoffTries ?? 0) + 1;
    await save().catch(() => {});
    // The wake starts a fresh paid step carrying the directive. Separately,
    // onContext surfaces a handoff-level notice into the next request's system
    // messages, so the session still sees the directive if the wake was dropped.
    try {
      await ctx.session.prompt(
        { sessionID: sid, prompt: { text: handoffText(state, limits, state.handoffTries) }, delivery: "steer" },
        { signal: AbortSignal.timeout(10000) },
      );
    } catch { /* the wake may fail; onContext still surfaces the directive */ }
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
    const handoffDue = handoffEnabled && ((typeof state.total === "number" && state.total >= limits.handoff) ||
      (state.compactions ?? 0) >= policy.handoff_after_compactions);
    const warnDue = typeof state.total === "number" && now() - state.sampleAt < 15 * 60 * 1000 && state.total >= limits.warn;
    if (handoffDue || warnDue) {
      // A handoff outranks a blocked/ineffective-compaction state: that is exactly
      // the session that must hand off rather than loop compactions.
      const level = handoffDue ? "handoff" : (!storageReadable || !streamAvailable || state.blocked || (state.pending && now() - state.attemptAt > 120000) ? "blocked" : "warn");
      if (state.notice !== level) {
        event.system.push({ type: "text", text: level === "handoff"
          ? (process.env.ACP_RUN_AGENT === "1" || state.child !== false
              ? childHandoffText(state, limits)
              : handoffText(state, limits, Math.max(1, state.handoffTries ?? 0)))
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
