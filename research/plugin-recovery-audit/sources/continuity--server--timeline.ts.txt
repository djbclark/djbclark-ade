import type { AgentTimelineItem } from "@getpaseo/protocol/agent-types";

/** Items after the last user message: the latest turn's output. */
export function latestTurnItems(timeline: readonly AgentTimelineItem[]): readonly AgentTimelineItem[] {
  for (let index = timeline.length - 1; index >= 0; index -= 1) {
    if (timeline[index]!.type === "user_message") {
      return timeline.slice(index + 1);
    }
  }
  return timeline;
}

export function userMessages(timeline: readonly AgentTimelineItem[]): string[] {
  const texts: string[] = [];
  for (const item of timeline) {
    if (item.type === "user_message") {
      texts.push(item.text);
    }
  }
  return texts;
}

/** Assistant text may stream across several items; join consecutive chunks. */
export function lastAssistantText(items: readonly AgentTimelineItem[]): string {
  let text = "";
  let collecting = false;
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index]!;
    if (item.type === "assistant_message") {
      text = item.text + text;
      collecting = true;
    } else if (collecting && item.type !== "reasoning") {
      break;
    }
  }
  return text.trim();
}
