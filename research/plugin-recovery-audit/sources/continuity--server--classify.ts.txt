import type { AgentTimelineItem } from "@getpaseo/protocol/agent-types";
import type { PluginTurnOutcome } from "@getpaseo/plugin/server";
import type { FailureClass } from "../shared/contracts";
import type { ContinuitySettings } from "../shared/settings";
import { lastAssistantText, latestTurnItems } from "./timeline";

export interface Classification {
  class: Exclude<FailureClass, "manual">;
  evidence: string;
  /** Epoch milliseconds when the provider said the limit resets, if stated. */
  resetAt?: number;
}

const QUOTA = [
  /insufficient[_ ]quota/i,
  /usage limit (?:reached|exceeded)/i,
  /you(?:'|’)?ve (?:hit|reached) your (?:usage |weekly |daily |monthly |session )?limit/i,
  /out of credits/i,
  /credit balance is too low/i,
  /quota (?:exceeded|exhausted)/i,
  /exceeded your current quota/i,
  /resource[_ ]exhausted/i,
  /usage_limit/i,
];

const RATE_LIMIT = [/\b429\b/, /rate[_ ]limit(?:ed|_error|_exceeded)?\b/i, /too many requests/i];

const OVERLOADED = [/overloaded(?:_error)?/i, /\b529\b/, /over capacity/i, /at capacity/i];

/** Final assistant text is only trusted when it is a short status line, not a discussion. */
const MAX_ASSISTANT_EVIDENCE_CHARS = 400;

export function classifyTurn(
  outcome: PluginTurnOutcome,
  timeline: readonly AgentTimelineItem[],
  triggers: ContinuitySettings["triggers"],
  now: number = Date.now(),
): Classification | null {
  if (outcome.kind === "canceled") {
    return null;
  }

  const evidence: string[] = [];
  if (outcome.kind === "failed") {
    evidence.push([outcome.error.code, outcome.error.message].filter(Boolean).join(": "));
  }

  const turn = latestTurnItems(timeline);
  for (const item of turn) {
    if (item.type === "error") {
      evidence.push(item.message);
    } else if (item.type === "notification" && item.level !== "info") {
      evidence.push(item.message);
    }
  }

  const assistant = lastAssistantText(turn);
  if (assistant && assistant.length <= MAX_ASSISTANT_EVIDENCE_CHARS) {
    evidence.push(assistant);
  }

  const ordered: Array<[Classification["class"], RegExp[], boolean]> = [
    ["quota", QUOTA, triggers.quota],
    ["rate_limit", RATE_LIMIT, triggers.rateLimit],
    ["overloaded", OVERLOADED, triggers.overloaded],
  ];

  for (const text of evidence) {
    for (const [failureClass, patterns, enabled] of ordered) {
      if (!enabled || !patterns.some((pattern) => pattern.test(text))) {
        continue;
      }
      const resetAt = parseResetAt(text, now);
      return {
        class: failureClass,
        evidence: compact(text, 300),
        ...(resetAt === undefined ? {} : { resetAt }),
      };
    }
  }
  return null;
}

/** Best-effort parse of "resets at 3pm", "|1759300000", or "try again in 20 minutes". */
export function parseResetAt(text: string, now: number): number | undefined {
  const epoch = text.match(/\|(\d{10,13})\b/);
  if (epoch) {
    const value = Number(epoch[1]);
    const millis = value < 1e12 ? value * 1000 : value;
    if (millis > now) {
      return millis;
    }
  }

  const relative = text.match(
    /(?:try again|retry|resets?) in (\d+(?:\.\d+)?)\s*(s|sec|seconds?|m|min|minutes?|h|hr|hours?)\b/i,
  );
  if (relative) {
    const amount = Number(relative[1]);
    const unit = relative[2]!.toLowerCase();
    const factor = unit.startsWith("h") ? 3_600_000 : unit.startsWith("m") ? 60_000 : 1000;
    return now + amount * factor;
  }

  const clock = text.match(/resets?(?: at)? (\d{1,2})(?::(\d{2}))?\s*(am|pm)?/i);
  if (clock) {
    let hours = Number(clock[1]);
    const minutes = clock[2] ? Number(clock[2]) : 0;
    const meridiem = clock[3]?.toLowerCase();
    if (meridiem === "pm" && hours < 12) hours += 12;
    if (meridiem === "am" && hours === 12) hours = 0;
    if (hours > 23 || minutes > 59) {
      return undefined;
    }
    const reset = new Date(now);
    reset.setHours(hours, minutes, 0, 0);
    if (reset.getTime() <= now) {
      reset.setDate(reset.getDate() + 1);
    }
    return reset.getTime();
  }
  return undefined;
}

function compact(text: string, max: number): string {
  const single = text.replace(/\s+/g, " ").trim();
  return single.length <= max ? single : single.slice(0, max - 1) + "…";
}
