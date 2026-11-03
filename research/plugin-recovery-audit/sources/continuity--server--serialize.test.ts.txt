import type { AgentTimelineItem } from "@getpaseo/protocol/agent-types";
import { describe, expect, it } from "vitest";
import { buildHandoffPrompt, redact } from "./serialize";

const meta = {
  fromAgentId: "agent-1",
  fromProvider: "codex/gpt-5.5",
  cwd: "/repo",
  reason: "quota" as const,
  evidence: "usage limit reached",
};

function longTimeline(turns: number): AgentTimelineItem[] {
  const items: AgentTimelineItem[] = [{ type: "user_message", text: "ORIGINAL: fix the authentication flow" }];
  for (let index = 0; index < turns; index += 1) {
    items.push({ type: "reasoning", text: `secret thinking ${index}` });
    items.push({ type: "assistant_message", text: `step ${index} part A ` });
    items.push({ type: "assistant_message", text: `part B ${"x".repeat(500)}` });
    items.push({
      type: "tool_call",
      callId: String(index),
      name: "shell",
      status: "completed",
      error: null,
      detail: { type: "shell", command: `npm test -- ${index}`, output: "ok\n".repeat(1000), exitCode: 0 },
    });
  }
  items.push({ type: "user_message", text: "LATEST: also update the docs" });
  items.push({ type: "todo", items: [{ text: "write docs", completed: false }, { text: "fix auth", completed: true }] });
  items.push({ type: "assistant_message", text: "Working on docs…" });
  return items;
}

describe("buildHandoffPrompt", () => {
  it("stays within budget and keeps the first and latest user messages", () => {
    const budget = 20_000;
    const prompt = buildHandoffPrompt(longTimeline(200), meta, budget);
    expect(prompt.length).toBeLessThanOrEqual(budget + 200);
    expect(prompt).toContain("ORIGINAL: fix the authentication flow");
    expect(prompt).toContain("LATEST: also update the docs");
    expect(prompt).toMatch(/earlier items? omitted/);
    expect(prompt).toContain("- [ ] write docs");
    expect(prompt).toContain("Working on docs…");
  });

  it("drops reasoning, merges assistant chunks and tails tool output", () => {
    const prompt = buildHandoffPrompt(longTimeline(2), meta, 60_000);
    expect(prompt).not.toContain("secret thinking");
    expect(prompt).toContain("ASSISTANT: step 1 part A part B");
    expect(prompt).toContain("$ npm test -- 1 (exit 0)");
    expect(prompt).toContain("[…]");
  });

  it("mentions the reason, source agent and working directory", () => {
    const prompt = buildHandoffPrompt(longTimeline(1), meta, 60_000);
    expect(prompt).toContain("codex/gpt-5.5");
    expect(prompt).toContain("agent-1");
    expect(prompt).toContain("`/repo`");
    expect(prompt).toContain("usage quota exhausted");
  });

  it("redacts secrets in the transcript", () => {
    const timeline: AgentTimelineItem[] = [
      { type: "user_message", text: "use key sk-proj-abcdefghijklmnopqrstuvwxyz123456 please" },
    ];
    const prompt = buildHandoffPrompt(timeline, meta, 60_000);
    expect(prompt).not.toContain("abcdefghijklmnopqrstuvwxyz123456");
    expect(prompt).toContain("[REDACTED]");
  });
});

describe("redact", () => {
  it("masks common token shapes but keeps the Bearer prefix", () => {
    expect(redact("Authorization: Bearer abcdefghijklmnopqrstuvwxyz")).toBe("Authorization: Bearer [REDACTED]");
    expect(redact("ghp_abcdefghijklmnopqrstuvwxyz0123")).toBe("[REDACTED]");
    expect(redact("AKIAABCDEFGHIJKLMNOP")).toBe("[REDACTED]");
  });
});
