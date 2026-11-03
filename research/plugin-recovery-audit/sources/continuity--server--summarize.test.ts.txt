import { describe, expect, it, vi } from "vitest";
import { DEFAULT_SETTINGS } from "../shared/settings";
import { summarizeTimeline } from "./summarize";

const agent = { id: "a1", workspaceId: "w1", cwd: "/tmp/p" };
const meta = { fromAgentId: "a1", fromProvider: "codex", cwd: "/tmp/p", reason: "manual" as const, evidence: "" };
const timeline = [{ type: "user_message", text: "fix the bug" }] as never;
const enabled = {
  ...DEFAULT_SETTINGS,
  summary: { ...DEFAULT_SETTINGS.summary, enabled: true, provider: "ollama", model: "qwen" },
};

function fakePaseo(result: object, archive = vi.fn(async () => ({}))) {
  const create = vi.fn(async () => ({ waitForFinish: async () => result, archive }));
  return { paseo: { workspaces: { ref: () => ({ agents: { create } }) } } as never, create, archive };
}

describe("summarizeTimeline", () => {
  it("is skipped when disabled or without a provider", async () => {
    const { paseo, create } = fakePaseo({});
    expect(await summarizeTimeline(paseo, DEFAULT_SETTINGS, agent, timeline, meta)).toBeNull();
    expect(create).not.toHaveBeenCalled();
  });

  it("returns the redacted summary and archives the helper agent", async () => {
    const { paseo, create, archive } = fakePaseo({
      status: "idle",
      lastMessage: "Done: key sk-abcdefghijklmnop1234 removed",
    });
    const result = await summarizeTimeline(paseo, enabled, agent, timeline, meta);
    expect(result?.by).toBe("ollama/qwen");
    expect(result?.text).not.toContain("sk-abcdefghijklmnop1234");
    expect(create).toHaveBeenCalledOnce();
    expect(archive).toHaveBeenCalledOnce();
  });

  it("falls back to null on timeout", async () => {
    const { paseo } = fakePaseo({ status: "timeout", lastMessage: null, error: null });
    expect(await summarizeTimeline(paseo, enabled, agent, timeline, meta)).toBeNull();
  });
});
