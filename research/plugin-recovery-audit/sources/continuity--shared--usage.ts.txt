import { providerIdOf } from "./labels";

/** The subset of a provider usage report that the pill needs. */
export interface UsageProvider {
  providerId: string;
  status: "available" | "unavailable" | "error";
  windows: ReadonlyArray<{
    label: string;
    usedPct?: number | null;
    remainingPct?: number | null;
    resetsAt?: string | null;
  }>;
}

export interface QuotaSummary {
  /** Remaining share of the tightest quota window, 0–100. */
  remainingPct: number;
  windowLabel: string;
  resetsAt: string | null;
}

/** Returns the tightest quota window for a provider, or null when usage is unknown. */
export function summarizeQuota(
  providers: readonly UsageProvider[],
  provider: string,
): QuotaSummary | null {
  const id = providerIdOf(provider);
  const report = providers.find((candidate) => providerIdOf(candidate.providerId) === id);
  if (!report || report.status !== "available") return null;
  let tightest: QuotaSummary | null = null;
  for (const window of report.windows) {
    const remaining =
      window.remainingPct ?? (window.usedPct == null ? null : 100 - window.usedPct);
    if (remaining == null) continue;
    const clamped = Math.min(100, Math.max(0, remaining));
    if (!tightest || clamped < tightest.remainingPct) {
      tightest = { remainingPct: clamped, windowLabel: window.label, resetsAt: window.resetsAt ?? null };
    }
  }
  return tightest;
}

export function isLowQuota(summary: QuotaSummary | null, warnAtRemainingPct: number): boolean {
  return summary !== null && summary.remainingPct <= warnAtRemainingPct;
}

export function formatPct(pct: number): string {
  return `${Math.round(pct)}%`;
}
