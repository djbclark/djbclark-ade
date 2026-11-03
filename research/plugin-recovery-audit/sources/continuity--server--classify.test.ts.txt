import type { AgentTimelineItem } from "@getpaseo/protocol/agent-types";
import { describe, expect, it } from "vitest";
import { classifyTurn, parseResetAt } from "./classify";

const ALL = { quota: true, rateLimit: true, overloaded: false };
const user = (text: string): AgentTimelineItem => ({ type: "user_message", text });
const assistant = (text: string): AgentTimelineItem => ({ type: "assistant_message", text });
const failed = (message: string, code?: string) =>
  ({ kind: "failed", error: code ? { message, code } : { message } }) as const;
const completed = { kind: "completed" } as const;

describe("classifyTurn", () => {
  it("detects insufficient_quota on a failed outcome", () => {
    const result = classifyTurn(failed("429 insufficient_quota: You exceeded your current quota"), [user("fix it")], ALL);
    expect(result?.class).toBe("quota");
  });

  it("detects a Claude usage-limit status line on a completed turn and parses the epoch", () => {
    const now = 1_759_000_000_000;
    const result = classifyTurn(
      completed,
      [user("fix it"), assistant("Claude AI usage limit reached|1759300000")],
      ALL,
      now,
    );
    expect(result?.class).toBe("quota");
    expect(result?.resetAt).toBe(1_759_300_000_000);
  });

  it("detects rate limits from an error item in the latest turn", () => {
    const result = classifyTurn(failed("turn failed"), [user("go"), { type: "error", message: "rate_limit_error: Too many requests" }], ALL);
    expect(result?.class).toBe("rate_limit");
  });

  it("ignores long assistant text that merely discusses rate limits", () => {
    const essay = `Implemented the rate limit handler. ${"It returns 429 when the quota is exceeded. ".repeat(20)}`;
    expect(classifyTurn(completed, [user("add rate limiting"), assistant(essay)], ALL)).toBeNull();
  });

  it("ignores rate-limit text that only appears in tool output", () => {
    const tool: AgentTimelineItem = {
      type: "tool_call",
      callId: "1",
      name: "shell",
      status: "completed",
      error: null,
      detail: { type: "shell", command: "grep -r 429 .", output: "HTTP 429 Too Many Requests" },
    };
    expect(classifyTurn(completed, [user("search"), tool, assistant("Done.")], ALL)).toBeNull();
  });

  it("ignores errors from earlier turns", () => {
    const timeline: AgentTimelineItem[] = [
      user("first"),
      { type: "error", message: "429 Too Many Requests" },
      user("second"),
      assistant("All good now."),
    ];
    expect(classifyTurn(completed, timeline, ALL)).toBeNull();
  });

  it("never fires on canceled turns", () => {
    expect(classifyTurn({ kind: "canceled", reason: "usage limit reached" }, [user("x")], ALL)).toBeNull();
  });

  it("respects disabled triggers", () => {
    expect(classifyTurn(failed("rate limited"), [user("x")], { ...ALL, rateLimit: false })).toBeNull();
    expect(classifyTurn(failed("overloaded_error"), [user("x")], ALL)).toBeNull();
    expect(classifyTurn(failed("overloaded_error"), [user("x")], { ...ALL, overloaded: true })?.class).toBe("overloaded");
  });

  it("ignores plain failures unrelated to limits", () => {
    expect(classifyTurn(failed("ENOENT: no such file"), [user("x")], ALL)).toBeNull();
  });
});

describe("parseResetAt", () => {
  const now = new Date(2026, 8, 30, 10, 0, 0).getTime();
  it("parses relative durations", () => {
    expect(parseResetAt("Please try again in 20 minutes", now)).toBe(now + 20 * 60_000);
  });
  it("parses clock times, rolling to tomorrow when already past", () => {
    expect(parseResetAt("limit resets at 3pm", now)).toBe(new Date(2026, 8, 30, 15, 0, 0).getTime());
    expect(parseResetAt("resets 9am", now)).toBe(new Date(2026, 9, 1, 9, 0, 0).getTime());
  });
});
