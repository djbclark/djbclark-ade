import type { PaseoApi } from "@getpaseo/client";
import type { AgentTimelineItem } from "@getpaseo/protocol/agent-types";
import {
  TRANSITION_KIND,
  TRANSITION_ROW_ID,
  TRANSITION_VERSION,
  type FailureClass,
  type TransitionCard,
} from "../shared/contracts";
import { LABEL, buildSuccessorTitle, providerIdOf } from "../shared/labels";
import type { ChainEntry, ContinuitySettings } from "../shared/settings";
import { checkBreaker, chainPositionFromLabels, nextConsecutive, pickNextEntry } from "./chain";
import { summarizeTimeline } from "./summarize";
import { writeHandoffFile } from "./handoff-file";
import { buildHandoffPrompt } from "./serialize";
import type { ContinuityState } from "./state";
import { userMessages } from "./timeline";

export interface FailedAgent {
  id: string;
  workspaceId: string | null;
  provider: string;
  cwd: string;
  title: string | null;
}

export interface FailoverRequest {
  agent: FailedAgent;
  turnId: string | null;
  timeline: readonly AgentTimelineItem[];
  reason: FailureClass;
  evidence: string;
  resetAt?: number;
  /** Continue on this provider even if the chain would pick another or it is cooling down. */
  targetProvider?: string;
  handoff?: "inline" | "file";
}

export type FailoverResult =
  | { status: "created"; newAgentId: string; message: string }
  | { status: "failed" | "exhausted" | "halted" | "skipped"; newAgentId: null; message: string };

interface ResolvedTarget {
  entry: ChainEntry;
  provider: string;
  model: string;
  modeId: string | undefined;
  thinkingOptionId: string | undefined;
}

const TAIL_BUDGET_WITH_SUMMARY = 15_000;

const log = (...args: unknown[]) => console.log("[continuity]", ...args);

export async function runFailover(
  paseo: PaseoApi,
  settings: ContinuitySettings,
  state: ContinuityState,
  request: FailoverRequest,
): Promise<FailoverResult> {
  const { agent, reason } = request;
  const fromProvider = providerIdOf(agent.provider);
  const card = cardWriter(paseo, agent.id, {
    reason,
    evidence: request.evidence,
    fromProvider,
  });

  if (reason !== "manual") {
    const minutes =
      reason === "quota" ? settings.cooldownMinutes.quota : settings.cooldownMinutes.rateLimit;
    state.coolDown(fromProvider, request.resetAt ?? Date.now() + minutes * 60_000);
  }

  const oldHandle = paseo.agents.ref(agent.id);
  const refreshed = await oldHandle.refresh().catch((error: unknown) => {
    log("could not refresh failed agent", agent.id, errorText(error));
    return null;
  });
  const labels = refreshed?.agent.labels ?? {};
  const position = chainPositionFromLabels(agent.id, labels);
  const isSuccessor = Boolean(labels[LABEL.chainId]);
  const madeProgress = !isSuccessor || userMessages(request.timeline).length > 1;

  // Manual attempts clear the exhausted state so the user can retry after changing settings.
  if (reason === "manual") {
    state.clearExhaustedChains();
  } else if (state.isChainExhausted(position.chainId)) {
    log("chain already exhausted, skipping auto-failover", position.chainId);
    return {
      status: "exhausted",
      newAgentId: null,
      message: "All providers in the chain have been tried. Add a new provider to your Fallback chain and use /continuity or the composer pill to retry.",
    };
  }

  const breaker = checkBreaker({
    position,
    madeProgress,
    settings: {
      ...settings,
      chainLength: settings.chain.length,
    },
    recentFailovers: state.recentFailovers(),
  });
  if (!breaker.ok) {
    state.markChainExhausted(position.chainId);
    await card({ status: "halted", detail: breaker.reason });
    return { status: "halted", newAgentId: null, message: breaker.reason };
  }

  const target = await resolveTarget(paseo, settings, state, agent, request.targetProvider);
  if (!target) {
    state.markChainExhausted(position.chainId);
    const message = "No fallback provider is available (all are cooling down, unavailable, or unconfigured).";
    await card({ status: "exhausted", detail: message });
    return { status: "exhausted", newAgentId: null, message };
  }

  await card({ status: "creating", toProvider: target.provider });

  const budget =
    settings.contextMode === "full" ? settings.budgets.fullChars : settings.budgets.automaticChars;
  const meta = {
    fromAgentId: agent.id,
    fromProvider: refreshed?.agent.model ? `${fromProvider}/${refreshed.agent.model}` : fromProvider,
    cwd: agent.cwd,
    reason,
    evidence: request.evidence,
  };
  const summary = await summarizeTimeline(paseo, settings, agent, request.timeline, meta);
  // With a summary, keep only a short verbatim tail as ground truth next to it.
  const handoffBody = buildHandoffPrompt(
    request.timeline,
    meta,
    summary ? Math.min(budget, TAIL_BUDGET_WITH_SUMMARY) : budget,
  );
  const handoffText = summary
    ? `## Summary of the work so far (written by ${summary.by})\n\n${summary.text}\n\n${handoffBody}`
    : handoffBody;
  let prompt = handoffText;
  if (request.handoff === "file") {
    try {
      prompt = await writeHandoffFile(agent.cwd, agent.id, handoffText);
    } catch (error) {
      log("could not write handoff file, sending inline", errorText(error));
    }
  }
  const title = buildSuccessorTitle({
    provider: target.provider,
    model: target.model,
    previousTitle: agent.title,
    fallbackText: userMessages(request.timeline)[0] ?? "",
    badges: settings.titleBadges,
  });
  const sequence = position.sequence + 1;

  try {
    const workspace = agent.workspaceId
      ? paseo.workspaces.ref(agent.workspaceId)
      : await paseo.workspaces.open(agent.cwd);
    const created = await workspace.agents.create({
      idempotencyKey: `continuity:${agent.id}:${request.turnId ?? "manual"}`,
      config: {
        provider: `${target.provider}/${target.model}`,
        ...(target.modeId ? { modeId: target.modeId } : {}),
        ...(target.thinkingOptionId ? { thinkingOptionId: target.thinkingOptionId } : {}),
      },
      title,
      prompt,
      labels: {
        [LABEL.chainId]: position.chainId,
        [LABEL.previousAgentId]: agent.id,
        [LABEL.provider]: target.provider,
        [LABEL.sequence]: String(sequence),
        [LABEL.consecutive]: String(nextConsecutive(position, madeProgress)),
        [LABEL.reason]: reason,
      },
    });
    state.recordFailover();
    await card({
      status: "created",
      toProvider: target.provider,
      toAgentId: created.id,
      toTitle: title,
    });
    log("created successor", { from: agent.id, to: created.id, provider: target.provider, reason });
    return {
      status: "created",
      newAgentId: created.id,
      message: `Continued in ${title} (${created.id.slice(0, 8)}).`,
    };
  } catch (error) {
    const message = `Could not create the ${target.provider} agent: ${errorText(error)}`;
    log(message);
    await card({ status: "failed", toProvider: target.provider, detail: message });
    return { status: "failed", newAgentId: null, message };
  }
}

async function resolveTarget(
  paseo: PaseoApi,
  settings: ContinuitySettings,
  state: ContinuityState,
  agent: FailedAgent,
  forcedProvider?: string,
): Promise<ResolvedTarget | null> {
  const snapshot = await paseo.providers.snapshot({ cwd: agent.cwd }).catch((error: unknown) => {
    log("provider snapshot failed", errorText(error));
    return null;
  });
  const entries = new Map((snapshot?.entries ?? []).map((entry) => [entry.provider, entry]));
  const rejected = new Set<string>();

  for (;;) {
    const forcedId = forcedProvider ? providerIdOf(forcedProvider) : null;
    const entry = pickNextEntry({
      currentProvider: agent.provider,
      chain: forcedId
        ? [
            settings.chain.find((candidate) => providerIdOf(candidate.provider) === forcedId) ?? {
              provider: forcedId,
              model: null,
              modeId: null,
              thinkingOptionId: null,
            },
          ]
        : settings.chain,
      isCoolingDown: (provider) => !forcedId && state.isCoolingDown(provider),
      isAvailable: (provider) => {
        if (rejected.has(provider)) return false;
        const info = entries.get(provider);
        // Without a snapshot we cannot tell; let creation fail visibly instead.
        return snapshot === null || (info !== undefined && info.enabled !== false && info.status === "ready");
      },
    });
    if (!entry) {
      return null;
    }
    const provider = providerIdOf(entry.provider);
    const info = entries.get(provider);
    const models = info?.models?.filter((model) => model.isSelectable !== false) ?? [];
    const model =
      entry.model ?? models.find((candidate) => candidate.isDefault)?.id ?? models[0]?.id ?? null;
    if (!model) {
      log("no model for fallback provider", provider);
      rejected.add(provider);
      continue;
    }
    const modes = info?.modes ?? [];
    const modeId =
      entry.modeId && (modes.length === 0 || modes.some((mode) => mode.id === entry.modeId))
        ? entry.modeId
        : (info?.defaultModeId ?? undefined);
    return {
      entry,
      provider,
      model,
      modeId: modeId ?? undefined,
      thinkingOptionId: entry.thinkingOptionId ?? undefined,
    };
  }
}

function cardWriter(
  paseo: PaseoApi,
  agentId: string,
  base: Pick<TransitionCard, "reason" | "evidence" | "fromProvider">,
) {
  return async (patch: Partial<TransitionCard> & Pick<TransitionCard, "status">) => {
    const data: TransitionCard = {
      toProvider: null,
      toAgentId: null,
      toTitle: null,
      detail: null,
      ...base,
      ...patch,
      at: new Date().toISOString(),
    };
    try {
      await paseo.agents.ref(agentId).timeline.append({
        type: "plugin",
        id: TRANSITION_ROW_ID,
        kind: TRANSITION_KIND,
        version: TRANSITION_VERSION,
        data,
      });
    } catch (error) {
      log("could not append transition card", agentId, errorText(error));
    }
  };
}

/** Loads the full canonical timeline for the manual failover path. */
export async function loadTimeline(paseo: PaseoApi, agentId: string): Promise<AgentTimelineItem[]> {
  const page = await paseo.agents
    .ref(agentId)
    .timeline.refetch({ direction: "tail", limit: 0, projection: "canonical" });
  return page.entries.map((entry) => entry.item as AgentTimelineItem);
}

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
