import { test } from "node:test";
import assert from "node:assert/strict";
import { CoalescingQueue, Semaphore, mapLimit, withTimeout } from "./queue.ts";

function gate(): { promise: Promise<void>; open(): void } {
  let open!: () => void;
  const promise = new Promise<void>((r) => {
    open = r;
  });
  return { promise, open };
}

test("tasks for one key never overlap and run in order", async () => {
  const q = new CoalescingQueue();
  const log: string[] = [];
  let active = 0;
  const g = gate();
  const first = q.run("a", async () => {
    active += 1;
    assert.equal(active, 1);
    log.push("first-start");
    await g.promise;
    log.push("first-end");
    active -= 1;
  });
  const second = q.run("a", async () => {
    active += 1;
    assert.equal(active, 1);
    log.push("second");
    active -= 1;
  });
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(log, ["first-start"]);
  g.open();
  await Promise.all([first, second]);
  assert.deepEqual(log, ["first-start", "first-end", "second"]);
});

test("requests made while a task runs coalesce into one trailing run, newest function wins", async () => {
  const q = new CoalescingQueue();
  const ran: number[] = [];
  const g = gate();
  const p0 = q.run("k", async () => {
    await g.promise;
    ran.push(0);
  });
  const p1 = q.run("k", () => {
    ran.push(1);
  });
  const p2 = q.run("k", () => {
    ran.push(2);
  });
  const p3 = q.run("k", () => {
    ran.push(3);
  });
  g.open();
  await Promise.all([p0, p1, p2, p3]);
  assert.deepEqual(ran, [0, 3]);
});

test("different keys run concurrently", async () => {
  const q = new CoalescingQueue();
  const g = gate();
  let bRan = false;
  const a = q.run("a", () => g.promise);
  const b = q.run("b", () => {
    bRan = true;
  });
  await b;
  assert.equal(bRan, true);
  assert.equal(q.busy("a"), true);
  g.open();
  await a;
  assert.equal(q.busy("a"), false);
});

test("a failing task never rejects the caller; onError sees it and the chain continues", async () => {
  const errors: string[] = [];
  const q = new CoalescingQueue({ onError: (key, e) => errors.push(`${key}:${(e as Error).message}`) });
  await q.run("x", () => {
    throw new Error("sync boom");
  });
  await q.run("x", async () => {
    throw new Error("async boom");
  });
  let after = false;
  await q.run("x", () => {
    after = true;
  });
  assert.deepEqual(errors, ["x:sync boom", "x:async boom"]);
  assert.equal(after, true);
});

test("a throwing onError does not break the queue", async () => {
  const q = new CoalescingQueue({
    onError: () => {
      throw new Error("bad handler");
    },
  });
  await q.run("x", () => {
    throw new Error("boom");
  });
  let ok = false;
  await q.run("x", () => {
    ok = true;
  });
  assert.equal(ok, true);
});

test("idle resolves only when every key has drained, including trailing runs", async () => {
  const q = new CoalescingQueue();
  await q.idle(); // empty: immediate
  const g = gate();
  const done: string[] = [];
  void q.run("a", async () => {
    await g.promise;
    done.push("a1");
  });
  void q.run("a", () => {
    done.push("a2");
  });
  void q.run("b", () => {
    done.push("b");
  });
  const idle = q.idle();
  setTimeout(() => g.open(), 5);
  await idle;
  assert.deepEqual(done.sort(), ["a1", "a2", "b"]);
  assert.equal(q.size(), 0);
});

test("semaphore limits holders and hands slots over FIFO", async () => {
  const s = new Semaphore(2);
  const r1 = await s.acquire();
  const r2 = await s.acquire();
  assert.equal(s.inUse(), 2);
  const order: number[] = [];
  const w3 = s.acquire().then((r) => {
    order.push(3);
    return r;
  });
  const w4 = s.acquire().then((r) => {
    order.push(4);
    return r;
  });
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(order, []);
  r1();
  r1(); // idempotent: must not free a second slot
  const r3 = await w3;
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(order, [3]);
  assert.equal(s.inUse(), 2);
  r2();
  const r4 = await w4;
  assert.deepEqual(order, [3, 4]);
  r3();
  r4();
  assert.equal(s.inUse(), 0);
  assert.throws(() => new Semaphore(0));
});

test("withTimeout rejects with TimeoutError and passes results through", async (t) => {
  assert.equal(await withTimeout(Promise.resolve(7), 50, "x"), 7);
  // withTimeout's own timer is unref'd (it must not hold the plugin process open), so keep
  // the loop alive here while the never-settling promise times out.
  const keepAlive = setTimeout(() => undefined, 1000);
  t.after(() => clearTimeout(keepAlive));
  await assert.rejects(withTimeout(new Promise(() => undefined), 10, "slow"), (e: Error) => {
    assert.equal(e.name, "TimeoutError");
    assert.match(e.message, /slow timed out/);
    return true;
  });
});

test("mapLimit keeps order and never exceeds the limit", async () => {
  let active = 0;
  let peak = 0;
  const out = await mapLimit([5, 1, 4, 2, 3, 0], 2, async (n) => {
    active += 1;
    peak = Math.max(peak, active);
    await new Promise((r) => setTimeout(r, n));
    active -= 1;
    return n * 10;
  });
  assert.deepEqual(out, [50, 10, 40, 20, 30, 0]);
  assert.ok(peak <= 2);
  assert.deepEqual(await mapLimit([], 4, async () => 1), []);
});
