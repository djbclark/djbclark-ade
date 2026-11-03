import { LABEL, providerIdOf } from "../shared/labels";
import type { ChainEntry, ContinuitySettings } from "../shared/settings";

export interface ChainPosition {
  chainId: string;
  sequence: number;
  consecutive: number;
}

/** Reads chain position from the failed agent's labels; an unlabeled agent starts a new chain. */
export function chainPositionFromLabels(
  agentId: string,
  labels: Readonly<Record<string, string>> | null | undefined,
): ChainPosition {
  const chainId = labels?.[LABEL.chainId];
  if (!chainId) {
    return { chainId: agentId, sequence: 0, consecutive: 0 };
  }
  return {
    chainId,
    sequence: toCount(labels[LABEL.sequence]),
    consecutive: toCount(labels[LABEL.consecutive]),
  };
}

function toCount(value: string | undefined): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : 0;
}

export type BreakerVerdict = { ok: true } | { ok: false; reason: string };

export const GLOBAL_WINDOW_MS = 10 * 60_000;
export const GLOBAL_MAX_FAILOVERS = 5;

export function checkBreaker(input: {
  position: ChainPosition;
  /** Whether the failed agent did useful work after its own handoff prompt. */
  madeProgress: boolean;
  settings: Pick<ContinuitySettings, "maxSwitchesPerChain" | "maxConsecutiveFailovers"> & {
    chainLength?: number;
  };
  recentFailovers: number;
}): BreakerVerdict {
  const { position, madeProgress, settings, recentFailovers } = input;
  if (position.sequence >= settings.maxSwitchesPerChain) {
    return {
      ok: false,
      reason: `Chain already switched ${position.sequence} times (limit ${settings.maxSwitchesPerChain}).`,
    };
  }
  const consecutive = madeProgress ? 0 : position.consecutive;
  const consecutiveLimit =
    settings.chainLength !== undefined && settings.chainLength > 0
      ? Math.min(settings.maxConsecutiveFailovers, settings.chainLength)
      : settings.maxConsecutiveFailovers;
  if (consecutive >= consecutiveLimit) {
    return {
      ok: false,
      reason: `${consecutive} consecutive failovers without progress (limit ${consecutiveLimit}).`,
    };
  }
  if (recentFailovers >= GLOBAL_MAX_FAILOVERS) {
    return {
      ok: false,
      reason: `${recentFailovers} failovers on this host in the last 10 minutes (limit ${GLOBAL_MAX_FAILOVERS}).`,
    };
  }
  return { ok: true };
}

export function nextConsecutive(position: ChainPosition, madeProgress: boolean): number {
  return (madeProgress ? 0 : position.consecutive) + 1;
}

/**
 * Picks the first eligible chain entry after the current provider, wrapping around.
 * The current provider itself is never picked.
 */
export function pickNextEntry(input: {
  currentProvider: string;
  chain: readonly ChainEntry[];
  isCoolingDown: (provider: string) => boolean;
  isAvailable: (provider: string) => boolean;
}): ChainEntry | null {
  const current = providerIdOf(input.currentProvider);
  const { chain } = input;
  if (chain.length === 0) {
    return null;
  }
  const position = chain.findIndex((entry) => providerIdOf(entry.provider) === current);
  const start = position === -1 ? 0 : position + 1;
  for (let offset = 0; offset < chain.length; offset += 1) {
    const entry = chain[(start + offset) % chain.length]!;
    const provider = providerIdOf(entry.provider);
    if (provider === current) continue;
    if (input.isCoolingDown(provider)) continue;
    if (!input.isAvailable(provider)) continue;
    return entry;
  }
  return null;
}
