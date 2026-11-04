// Per-key serialized, coalescing work queue (issue 278, Slice B).
//
// One chain per key. A task for a key never overlaps another task for the same key.
// While a task runs, later requests for that key coalesce into ONE trailing run: the
// newest function wins, because every task re-reads the in-memory state when it starts.
// The returned promise never rejects; failures go to `onError`, so a caller that drops
// the promise cannot cause an unhandled rejection in the plugin process.

interface Deferred {
  promise: Promise<void>;
  resolve(): void;
}

function deferred(): Deferred {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

interface KeyState {
  running: boolean;
  next: { fn: () => Promise<void> | void; done: Deferred } | null;
}

export class CoalescingQueue {
  private keys: Map<string, KeyState>;
  private idleWaiters: Array<() => void>;
  private onError: (key: string, error: unknown) => void;

  constructor(options?: { onError?: (key: string, error: unknown) => void }) {
    this.keys = new Map();
    this.idleWaiters = [];
    this.onError = options?.onError ?? (() => undefined);
  }

  /**
   * Run `fn` for `key` after any task already running for it. Resolves when a run that
   * started after this call has finished (successfully or not).
   */
  run(key: string, fn: () => Promise<void> | void): Promise<void> {
    let state = this.keys.get(key);
    if (!state) {
      state = { running: false, next: null };
      this.keys.set(key, state);
    }
    if (state.next) {
      state.next.fn = fn;
      return state.next.done.promise;
    }
    const done = deferred();
    if (state.running) {
      state.next = { fn, done };
      return done.promise;
    }
    this.start(key, state, fn, done);
    return done.promise;
  }

  /** True while a task for `key` is running or waiting. */
  busy(key: string): boolean {
    return this.keys.has(key);
  }

  /** Number of keys with work running or waiting. */
  size(): number {
    return this.keys.size;
  }

  /** Resolves once no key has work running or waiting. */
  idle(): Promise<void> {
    if (this.keys.size === 0) return Promise.resolve();
    return new Promise<void>((resolve) => this.idleWaiters.push(resolve));
  }

  private start(key: string, state: KeyState, fn: () => Promise<void> | void, done: Deferred): void {
    state.running = true;
    Promise.resolve()
      .then(fn)
      .catch((error: unknown) => {
        try {
          this.onError(key, error);
        } catch {
          // onError must not break the chain.
        }
      })
      .finally(() => {
        state.running = false;
        done.resolve();
        const next = state.next;
        if (next) {
          state.next = null;
          this.start(key, state, next.fn, next.done);
          return;
        }
        this.keys.delete(key);
        if (this.keys.size === 0) {
          const waiters = this.idleWaiters;
          this.idleWaiters = [];
          for (const w of waiters) w();
        }
      });
  }
}

/** Counting semaphore: at most `limit` holders at once, FIFO. */
export class Semaphore {
  private limit: number;
  private held: number;
  private waiting: Array<() => void>;

  constructor(limit: number) {
    if (!Number.isInteger(limit) || limit < 1) throw new Error(`bad semaphore limit: ${limit}`);
    this.limit = limit;
    this.held = 0;
    this.waiting = [];
  }

  /** Resolves with a release function; release is idempotent. */
  async acquire(): Promise<() => void> {
    if (this.held < this.limit) {
      this.held += 1;
    } else {
      await new Promise<void>((resolve) => this.waiting.push(resolve));
      // The releaser handed its slot straight to us; `held` is unchanged.
    }
    let released = false;
    return () => {
      if (released) return;
      released = true;
      const next = this.waiting.shift();
      if (next) next();
      else this.held -= 1;
    };
  }

  /** Holders right now (for tests). */
  inUse(): number {
    return this.held;
  }
}

/** Reject with `TimeoutError` (name) after `ms`; the timer never keeps the process alive. */
export function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      const error = new Error(`${label} timed out after ${ms} ms`);
      error.name = "TimeoutError";
      reject(error);
    }, ms);
    timer.unref?.();
  });
  return Promise.race([promise, timeout]).finally(() => {
    if (timer) clearTimeout(timer);
  });
}

/** Run `fn` over `items` with at most `limit` in flight; results keep input order. */
export async function mapLimit<T, R>(
  items: readonly T[],
  limit: number,
  fn: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results = new Array<R>(items.length);
  let next = 0;
  const workers: Promise<void>[] = [];
  const width = Math.max(1, Math.min(limit, items.length));
  for (let w = 0; w < width; w += 1) {
    workers.push(
      (async () => {
        while (next < items.length) {
          const index = next;
          next += 1;
          results[index] = await fn(items[index] as T, index);
        }
      })(),
    );
  }
  await Promise.all(workers);
  return results;
}
