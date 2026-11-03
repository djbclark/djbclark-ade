import { providerIdOf } from "../shared/labels";
import { GLOBAL_WINDOW_MS } from "./chain";

/**
 * In-memory failover state for one plugin process. Lost on reload or daemon
 * restart; durable chain counters live in agent labels instead.
 */
export class ContinuityState {
  private readonly handled = new Set<string>();
  private readonly inFlight = new Set<string>();
  private readonly cooldowns = new Map<string, number>();
  private failoverTimes: number[] = [];
  /** Chains where all providers are cooling down or unavailable. */
  private readonly exhaustedChains = new Set<string>();

  constructor(private readonly now: () => number = Date.now) {}

  /** Claims an agent for failover. Returns false if it was already claimed. */
  claim(agentId: string): boolean {
    if (this.handled.has(agentId)) {
      return false;
    }
    this.handled.add(agentId);
    return true;
  }

  release(agentId: string): void {
    this.handled.delete(agentId);
  }

  isHandled(agentId: string): boolean {
    return this.handled.has(agentId);
  }

  /** Marks an agent as having started an active failover attempt. */
  startInFlight(agentId: string): boolean {
    if (this.inFlight.has(agentId)) {
      return false;
    }
    this.inFlight.add(agentId);
    return true;
  }

  finishInFlight(agentId: string): void {
    this.inFlight.delete(agentId);
  }

  isInFlight(agentId: string): boolean {
    return this.inFlight.has(agentId);
  }

  coolDown(provider: string, until: number): void {
    const id = providerIdOf(provider);
    this.cooldowns.set(id, Math.max(until, this.cooldowns.get(id) ?? 0));
  }

  isCoolingDown(provider: string): boolean {
    const until = this.cooldowns.get(providerIdOf(provider));
    return until !== undefined && until > this.now();
  }

  recordFailover(): void {
    this.failoverTimes.push(this.now());
  }

  recentFailovers(): number {
    const cutoff = this.now() - GLOBAL_WINDOW_MS;
    this.failoverTimes = this.failoverTimes.filter((time) => time > cutoff);
    return this.failoverTimes.length;
  }

  /** Mark a chain as exhausted so auto-failover stops retrying it. */
  markChainExhausted(chainId: string): void {
    this.exhaustedChains.add(chainId);
  }

  isChainExhausted(chainId: string): boolean {
    return this.exhaustedChains.has(chainId);
  }

  /** Clear exhausted state and handled set — called when settings change. */
  clearExhaustedChains(): void {
    this.exhaustedChains.clear();
  }

  clearHandled(): void {
    this.handled.clear();
  }
}

