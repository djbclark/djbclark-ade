import { describe, expect, it } from "vitest";
import { buildSuccessorTitle, providerIdOf, stripBadgePrefix } from "../shared/labels";
import { parseChain } from "../shared/chain-format";
import { checkBreaker, chainPositionFromLabels, nextConsecutive, pickNextEntry } from "./chain";
import { ContinuityState } from "./state";

const entry = (provider: string) => ({ provider, model: null, modeId: null, thinkingOptionId: null });
const chain = [entry("codex"), entry("claude"), entry("opencode")];
const always = () => true;
const never = () => false;

describe("pickNextEntry", () => {
  it("picks the entry after the current provider", () => {
    expect(pickNextEntry({ currentProvider: "codex", chain, isCoolingDown: never, isAvailable: always })?.provider).toBe("claude");
  });
  it("wraps around and skips cooling-down providers", () => {
    const cooling = (provider: string) => provider === "codex";
    expect(pickNextEntry({ currentProvider: "opencode", chain, isCoolingDown: cooling, isAvailable: always })?.provider).toBe("claude");
  });
  it("starts from the top when the current provider is not in the chain", () => {
    expect(pickNextEntry({ currentProvider: "pi/some-model", chain, isCoolingDown: never, isAvailable: always })?.provider).toBe("codex");
  });
  it("returns null when everything else is exhausted or unavailable", () => {
    const cooling = (provider: string) => provider === "claude";
    const available = (provider: string) => provider !== "opencode";
    expect(pickNextEntry({ currentProvider: "codex", chain, isCoolingDown: cooling, isAvailable: available })).toBeNull();
  });
  it("never picks the current provider", () => {
    expect(pickNextEntry({ currentProvider: "codex", chain: [entry("codex")], isCoolingDown: never, isAvailable: always })).toBeNull();
  });
});

describe("circuit breaker", () => {
  const settings = { maxSwitchesPerChain: 3, maxConsecutiveFailovers: 2 };
  const position = (sequence: number, consecutive: number) => ({ chainId: "c", sequence, consecutive });

  it("allows a fresh chain", () => {
    expect(checkBreaker({ position: position(0, 0), madeProgress: true, settings, recentFailovers: 0 }).ok).toBe(true);
  });
  it("halts at the per-chain switch limit", () => {
    expect(checkBreaker({ position: position(3, 0), madeProgress: true, settings, recentFailovers: 0 }).ok).toBe(false);
  });
  it("halts after consecutive switches without progress, but progress resets the counter", () => {
    expect(checkBreaker({ position: position(2, 2), madeProgress: false, settings, recentFailovers: 0 }).ok).toBe(false);
    expect(checkBreaker({ position: position(2, 2), madeProgress: true, settings, recentFailovers: 0 }).ok).toBe(true);
    expect(nextConsecutive(position(2, 2), true)).toBe(1);
    expect(nextConsecutive(position(1, 1), false)).toBe(2);
  });
  it("halts at the host-wide rate limit", () => {
    expect(checkBreaker({ position: position(0, 0), madeProgress: true, settings, recentFailovers: 5 }).ok).toBe(false);
  });
  it("caps consecutive limit by chainLength", () => {
    const customSettings = { maxSwitchesPerChain: 5, maxConsecutiveFailovers: 4, chainLength: 2 };
    expect(checkBreaker({ position: position(1, 1), madeProgress: false, settings: customSettings, recentFailovers: 0 }).ok).toBe(true);
    expect(checkBreaker({ position: position(2, 2), madeProgress: false, settings: customSettings, recentFailovers: 0 }).ok).toBe(false);
  });
  it("reads chain position from labels", () => {
    expect(chainPositionFromLabels("a1", {})).toEqual({ chainId: "a1", sequence: 0, consecutive: 0 });
    expect(
      chainPositionFromLabels("a2", { "continuity.chainId": "a1", "continuity.sequence": "2", "continuity.consecutive": "1" }),
    ).toEqual({ chainId: "a1", sequence: 2, consecutive: 1 });
  });
});

describe("ContinuityState", () => {
  it("claims an agent once and tracks cooldowns and the rate window", () => {
    let now = 1_000_000;
    const state = new ContinuityState(() => now);
    expect(state.claim("a")).toBe(true);
    expect(state.claim("a")).toBe(false);
    state.coolDown("claude/sonnet", now + 60_000);
    expect(state.isCoolingDown("claude")).toBe(true);
    now += 61_000;
    expect(state.isCoolingDown("claude")).toBe(false);
    state.recordFailover();
    expect(state.recentFailovers()).toBe(1);
    now += 11 * 60_000;
    expect(state.recentFailovers()).toBe(0);
  });

  it("handles inFlight concurrency lock correctly", () => {
    const state = new ContinuityState();
    expect(state.isInFlight("agent-1")).toBe(false);
    expect(state.startInFlight("agent-1")).toBe(true);
    expect(state.isInFlight("agent-1")).toBe(true);
    expect(state.startInFlight("agent-1")).toBe(false);
    state.finishInFlight("agent-1");
    expect(state.isInFlight("agent-1")).toBe(false);
    expect(state.startInFlight("agent-1")).toBe(true);
  });

  it("tracks and clears exhausted chains and handled agents", () => {
    const state = new ContinuityState();
    expect(state.isChainExhausted("chain-1")).toBe(false);
    state.markChainExhausted("chain-1");
    expect(state.isChainExhausted("chain-1")).toBe(true);
    state.clearExhaustedChains();
    expect(state.isChainExhausted("chain-1")).toBe(false);

    expect(state.claim("agent-x")).toBe(true);
    expect(state.isHandled("agent-x")).toBe(true);
    state.clearHandled();
    expect(state.isHandled("agent-x")).toBe(false);
    expect(state.claim("agent-x")).toBe(true);
  });
});

describe("titles", () => {
  it("prefixes the provider badge and does not stack prefixes", () => {
    const first = buildSuccessorTitle({ provider: "claude", previousTitle: "Fix authentication", fallbackText: "", badges: true });
    expect(first).toBe("◆ Claude · Fix authentication");
    const second = buildSuccessorTitle({ provider: "codex", previousTitle: first, fallbackText: "", badges: true });
    expect(second).toBe("● Codex · Fix authentication");
    expect(stripBadgePrefix("✦ Gemini · Fix authentication")).toBe("Fix authentication");
  });
  it("labels Gemini models behind other providers as Gemini", () => {
    expect(
      buildSuccessorTitle({ provider: "opencode", model: "google/gemini-2.5-pro", previousTitle: "X", fallbackText: "", badges: true }),
    ).toBe("✦ Gemini · X");
  });
  it("falls back to the first user message when there is no title", () => {
    expect(buildSuccessorTitle({ provider: "claude", previousTitle: null, fallbackText: "fix   the login bug", badges: false })).toBe("fix the login bug");
  });
  it("normalizes provider IDs with lowercasing and trimming", () => {
    expect(providerIdOf("Claude/sonnet")).toBe("claude");
    expect(providerIdOf("  OpenCode  ")).toBe("opencode");
    expect(providerIdOf("codex")).toBe("codex");
  });
});

describe("parseChain", () => {
  it("parses provider/model:mode lists", () => {
    expect(parseChain("codex:auto, opencode/google/gemini-2.5-pro:build")).toEqual([
      { provider: "codex", model: null, modeId: "auto", thinkingOptionId: null },
      { provider: "opencode", model: "google/gemini-2.5-pro", modeId: "build", thinkingOptionId: null },
    ]);
  });
  it("rejects single-entry chains and garbage", () => {
    expect(typeof parseChain("codex")).toBe("string");
    expect(typeof parseChain("codex, ???")).toBe("string");
  });
});
