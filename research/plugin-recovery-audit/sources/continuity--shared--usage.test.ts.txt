import { describe, expect, it } from "vitest";
import { isLowQuota, summarizeQuota, type UsageProvider } from "./usage";

const providers: UsageProvider[] = [
  {
    providerId: "codex",
    status: "available",
    windows: [
      { label: "5h", usedPct: 90 },
      { label: "Weekly", remainingPct: 60, resetsAt: "2026-10-05T00:00:00Z" },
    ],
  },
  { providerId: "claude", status: "error", windows: [{ label: "5h", remainingPct: 1 }] },
];

describe("summarizeQuota", () => {
  it("picks the tightest window and derives remaining from used", () => {
    expect(summarizeQuota(providers, "codex/gpt-5")).toEqual({
      remainingPct: 10,
      windowLabel: "5h",
      resetsAt: null,
    });
  });

  it("returns null for unavailable or unknown providers", () => {
    expect(summarizeQuota(providers, "claude")).toBeNull();
    expect(summarizeQuota(providers, "gemini")).toBeNull();
  });
});

describe("isLowQuota", () => {
  it("compares against the threshold and ignores unknown usage", () => {
    expect(isLowQuota({ remainingPct: 15, windowLabel: "5h", resetsAt: null }, 15)).toBe(true);
    expect(isLowQuota({ remainingPct: 16, windowLabel: "5h", resetsAt: null }, 15)).toBe(false);
    expect(isLowQuota(null, 15)).toBe(false);
  });
});
