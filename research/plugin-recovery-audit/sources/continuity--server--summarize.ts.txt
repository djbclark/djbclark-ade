import type { PaseoApi } from "@getpaseo/client";
import type { AgentTimelineItem } from "@getpaseo/protocol/agent-types";
import type { ContinuitySettings } from "../shared/settings";
import { LABEL } from "../shared/labels";
import { buildHandoffPrompt, redact, type HandoffMeta } from "./serialize";

interface SummarySource {
  id: string;
  workspaceId: string | null;
  cwd: string;
}

const SYSTEM_PROMPT =
  "You condense agent transcripts. Do not use any tools and do not touch files. Reply with the summary only.";

const INSTRUCTIONS = [
  "Summarize the transcript below so another coding agent can continue the work without reading it.",
  "Cover: the goal; what is done (files changed, decisions made and why); what is in progress or failing; open questions; the next concrete steps.",
  "Be concrete (file paths, commands, error messages). Skip pleasantries. Under 800 words.",
].join("\n");

/**
 * Condenses the timeline with the configured summarizer model. Returns null when
 * disabled or on any failure, so the caller falls back to the plain transcript.
 */
export async function summarizeTimeline(
  paseo: PaseoApi,
  settings: ContinuitySettings,
  agent: SummarySource,
  timeline: readonly AgentTimelineItem[],
  meta: HandoffMeta,
): Promise<{ text: string; by: string } | null> {
  const { summary } = settings;
  if (!summary.enabled || !summary.provider) return null;
  const by = summary.model ? `${summary.provider}/${summary.model}` : summary.provider;
  try {
    const source = buildHandoffPrompt(timeline, meta, summary.inputChars);
    const workspace = agent.workspaceId
      ? paseo.workspaces.ref(agent.workspaceId)
      : await paseo.workspaces.open(agent.cwd);
    const handle = await workspace.agents.create({
      config: { provider: by, systemPrompt: SYSTEM_PROMPT },
      title: "Continuity summary",
      prompt: `${INSTRUCTIONS}\n\n${source}`,
      labels: { [LABEL.provider]: summary.provider, [LABEL.reason]: "summary" },
    });
    try {
      const result = await handle.waitForFinish(summary.timeoutSeconds * 1000);
      const text = result.lastMessage?.trim();
      if (result.status !== "idle" || !text) {
        console.log("[continuity] summary unusable", { status: result.status, error: result.error });
        return null;
      }
      return { text: redact(text), by };
    } finally {
      await handle.archive().catch(() => {});
    }
  } catch (error) {
    console.log("[continuity] summary failed, using plain transcript", error);
    return null;
  }
}
