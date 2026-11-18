import assert from 'node:assert/strict';

async function deadline(promise, milliseconds, message) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(message)), milliseconds); }),
    ]);
  } finally { clearTimeout(timer); }
}

// Fixture teardown only. The caller creates this detached process group itself;
// it never accepts a PID from a request, policy, observation or running daemon.
// Forced teardown fails acceptance and is never used to obtain maintenance quiet.
export function ownDisposableGroup(child, { gracefulMs = 30_000, forcedMs = 5000 } = {}) {
  assert.ok(Number.isSafeInteger(child.pid) && child.pid > 0 && child.pid !== process.pid);
  const closed = new Promise((resolve) => {
    child.once('close', (code, signal) => resolve({ code, signal }));
  });
  let cleanup;
  const dispose = () => {
    if (!cleanup) cleanup = (async () => {
      if (child.exitCode === null && child.signalCode === null) child.kill('SIGTERM');
      let result;
      try {
        result = await deadline(closed, gracefulMs, 'owned fixture graceful stop timed out');
      } catch (original) {
        // Every member of this group descends from our detached fixture child.
        // Even if the leader exits during escalation, remaining owned helpers
        // must not survive an unsuccessful disposable acceptance run.
        try { process.kill(-child.pid, 'SIGKILL'); }
        catch (error) { if (error.code !== 'ESRCH') original.cause = error; }
        try { await deadline(closed, forcedMs, 'owned fixture forced stop did not close'); }
        catch (error) {
          original.cause = error;
          original.cleanupPid = child.pid;
          if (child.connected) child.disconnect();
          child.stdout?.destroy();
          child.stderr?.destroy();
          child.unref();
        }
        throw original;
      }
      assert.equal(result.code, 0, 'owned fixture must stop successfully');
      return result;
    })();
    return cleanup;
  };
  return Object.freeze({ closed, dispose });
}
