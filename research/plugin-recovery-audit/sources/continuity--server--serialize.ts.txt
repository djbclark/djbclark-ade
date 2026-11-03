import type { AgentTimelineItem, ToolCallDetail } from "@getpaseo/protocol/agent-types";
import type { FailureClass } from "../shared/contracts";
import { userMessages } from "./timeline";

export interface HandoffMeta {
  fromAgentId: string;
  fromProvider: string;
  cwd: string;
  reason: FailureClass;
  evidence: string;
}

const TASK_CAP = 8_000;
const MESSAGE_CAP = 4_000;
const TOOL_OUTPUT_TAIL = 800;
const TOOL_ERROR_CAP = 300;
const NOTE_CAP = 500;

const REASON_TEXT: Record<FailureClass, string> = {
  quota: "usage quota exhausted",
  rate_limit: "rate limited",
  overloaded: "provider overloaded",
  manual: "manual failover requested by the user",
};

/**
 * Builds the first prompt for the successor agent from the failed agent's timeline.
 * The result never exceeds `budgetChars` (plus a small fixed header).
 */
export function buildHandoffPrompt(
  timeline: readonly AgentTimelineItem[],
  meta: HandoffMeta,
  budgetChars: number,
): string {
  const users = userMessages(timeline);
  const firstTask = users[0] ?? "";
  const latestRequest = users.length > 1 ? users[users.length - 1]! : "";
  const todo = lastTodo(timeline);

  const header = [
    "# Paseo Continuity handoff",
    "",
    `The previous agent (provider \`${meta.fromProvider}\`, agent id \`${meta.fromAgentId}\`) stopped: ${REASON_TEXT[meta.reason]}${meta.evidence ? ` — "${meta.evidence}"` : ""}.`,
    `You are continuing the same task in the same working directory \`${meta.cwd}\`.`,
    "Any file changes the previous agent made are already on disk. Inspect the current state (for example `git status` and `git diff`) before acting.",
    "Do not redo work that is already complete. Continue from the latest user request; if the transcript ends mid-step, finish that step.",
    "The transcript below was captured by Paseo from the previous agent's timeline; it may be truncated.",
  ].join("\n");

  const fixed: string[] = [header];
  fixed.push(section("Original task", cap(firstTask, TASK_CAP)));
  if (latestRequest && latestRequest !== firstTask) {
    fixed.push(section("Latest user request", cap(latestRequest, TASK_CAP)));
  }
  if (todo) {
    fixed.push(section("Latest task list", todo));
  }

  const fixedText = fixed.join("\n\n");
  const transcriptBudget = Math.max(0, budgetChars - fixedText.length - 64);
  const transcript = renderTranscript(timeline, transcriptBudget);

  return redact([fixedText, section("Transcript (oldest first)", transcript || "(empty)")].join("\n\n"));
}

function section(title: string, body: string): string {
  return `## ${title}\n\n${body}`;
}

/** Renders items newest-first until the budget is spent, then restores chronological order. */
export function renderTranscript(timeline: readonly AgentTimelineItem[], budget: number): string {
  const rendered = mergeAssistantChunks(timeline)
    .map(renderItem)
    .filter((line): line is string => line !== null);

  const kept: string[] = [];
  let used = 0;
  let index = rendered.length - 1;
  for (; index >= 0; index -= 1) {
    const line = rendered[index]!;
    if (used + line.length + 2 > budget) {
      break;
    }
    kept.push(line);
    used += line.length + 2;
  }
  kept.reverse();
  const omitted = index + 1;
  if (omitted > 0) {
    kept.unshift(`[… ${omitted} earlier item${omitted === 1 ? "" : "s"} omitted …]`);
  }
  return kept.join("\n\n");
}

function mergeAssistantChunks(timeline: readonly AgentTimelineItem[]): AgentTimelineItem[] {
  const merged: AgentTimelineItem[] = [];
  for (const item of timeline) {
    const previous = merged[merged.length - 1];
    if (item.type === "assistant_message" && previous?.type === "assistant_message") {
      merged[merged.length - 1] = { ...previous, text: previous.text + item.text };
    } else {
      merged.push(item);
    }
  }
  return merged;
}

function renderItem(item: AgentTimelineItem): string | null {
  switch (item.type) {
    case "user_message":
      return `USER: ${cap(item.text, MESSAGE_CAP)}`;
    case "assistant_message":
      return item.text.trim() ? `ASSISTANT: ${cap(item.text, MESSAGE_CAP)}` : null;
    case "tool_call": {
      const detail = renderToolDetail(item.detail);
      const error =
        item.status === "failed" && item.error != null
          ? ` — error: ${cap(stringify(item.error), TOOL_ERROR_CAP)}`
          : "";
      return `TOOL ${item.name} [${item.status}]${detail ? `: ${detail}` : ""}${error}`;
    }
    case "error":
      return `ERROR: ${cap(item.message, NOTE_CAP)}`;
    case "notification":
      return `NOTE (${item.level}): ${cap(item.message, NOTE_CAP)}`;
    case "compaction":
      return "[context was compacted by the previous provider here]";
    case "reasoning":
    case "todo":
    case "plugin":
      return null;
  }
}

function renderToolDetail(detail: ToolCallDetail): string {
  switch (detail.type) {
    case "shell": {
      const exit = detail.exitCode == null ? "" : ` (exit ${detail.exitCode})`;
      const output = detail.output ? `\n${tail(detail.output, TOOL_OUTPUT_TAIL)}` : "";
      return `$ ${cap(detail.command, 500)}${exit}${output}`;
    }
    case "read":
      return `read ${detail.filePath}`;
    case "edit":
      return `edited ${detail.filePath}`;
    case "write":
      return `wrote ${detail.filePath}`;
    case "search":
      return `search ${cap(detail.query, 200)}${detail.numFiles != null ? ` (${detail.numFiles} files)` : ""}`;
    case "fetch":
      return `fetch ${detail.url}${detail.code != null ? ` (${detail.code})` : ""}`;
    case "worktree_setup":
      return `worktree ${detail.worktreePath} on ${detail.branchName}`;
    case "sub_agent":
      return `sub-agent ${detail.subAgentType ?? ""} ${cap(detail.description ?? "", 200)}`.trim();
    case "plain_text":
      return cap([detail.label, detail.text].filter(Boolean).join(": "), 500);
    case "plan":
      return `plan:\n${cap(detail.text, 2_000)}`;
    case "unknown":
      return cap(stringify(detail.input), 300);
  }
}

function lastTodo(timeline: readonly AgentTimelineItem[]): string | null {
  for (let index = timeline.length - 1; index >= 0; index -= 1) {
    const item = timeline[index]!;
    if (item.type === "todo") {
      return item.items.map((task) => `- [${task.completed ? "x" : " "}] ${task.text}`).join("\n");
    }
  }
  return null;
}

function cap(text: string, max: number): string {
  const trimmed = text.trim();
  return trimmed.length <= max ? trimmed : `${trimmed.slice(0, max)}… [truncated ${trimmed.length - max} chars]`;
}

function tail(text: string, max: number): string {
  const trimmed = text.trimEnd();
  return trimmed.length <= max ? trimmed : `[…] ${trimmed.slice(trimmed.length - max)}`;
}

function stringify(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}

const SECRET_PATTERNS: RegExp[] = [
  /\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{16,}/g,
  /\bgh[pousr]_[A-Za-z0-9]{20,}/g,
  /\bgithub_pat_[A-Za-z0-9_]{20,}/g,
  /\bAKIA[0-9A-Z]{16}\b/g,
  /\bAIza[0-9A-Za-z_-]{30,}/g,
  /\bxox[abprs]-[A-Za-z0-9-]{10,}/g,
  /(Bearer\s+)[A-Za-z0-9._~+/-]{16,}=*/g,
];

export function redact(text: string): string {
  let result = text;
  for (const pattern of SECRET_PATTERNS) {
    result = result.replace(pattern, (match, prefix: unknown) =>
      typeof prefix === "string" && match.startsWith(prefix) ? `${prefix}[REDACTED]` : "[REDACTED]",
    );
  }
  return result;
}
