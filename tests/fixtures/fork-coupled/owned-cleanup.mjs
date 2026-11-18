import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { setTimeout as pause } from 'node:timers/promises';

async function deadline(promise, milliseconds, message) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(message)), milliseconds); }),
    ]);
  } finally { clearTimeout(timer); }
}

async function liveGroup(group, signal) {
  const members = (await readdir('/proc')).filter((name) => /^[0-9]+$/.test(name));
  assert.ok(members.length <= 65_536, 'fixture process inventory exceeds bound');
  for (const member of members) {
    signal?.throwIfAborted();
    let raw;
    try { raw = await readFile(`/proc/${member}/stat`, { encoding: 'utf8', signal }); }
    catch (error) { if (error.code === 'ENOENT') continue; throw error; }
    const fields = raw.slice(raw.lastIndexOf(') ') + 2).split(' ');
    // The detached fixture starts its own session and group. Exited zombies
    // have already released execution/resources; the system reaper owns them.
    if (Number(fields[2]) === group && Number(fields[3]) === group && fields[0] !== 'Z') return true;
  }
  return false;
}

async function groupExited(group, signal) {
  while (await liveGroup(group, signal)) await pause(25, undefined, { signal });
}

// Fixture teardown only. The caller creates this detached process group itself;
// it never accepts a PID from a request, policy, observation or running daemon.
// Forced teardown fails acceptance and is never used to obtain maintenance quiet.
export function ownDisposableGroup(child, { gracefulMs = 30_000, forcedMs = 5000 } = {}) {
  assert.equal(process.platform, 'linux', 'finite Linux fixture cleanup only');
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
        if (result.code !== 0) throw new Error(`owned fixture exited code=${result.code} signal=${result.signal}`);
        assert.equal(await liveGroup(child.pid), false, 'owned helpers survived fixture leader');
      } catch (original) {
        // Every member of this group descends from our detached fixture child.
        // Even if the leader exits during escalation, remaining owned helpers
        // must not survive an unsuccessful disposable acceptance run.
        try { process.kill(-child.pid, 'SIGKILL'); }
        catch (error) { if (error.code !== 'ESRCH') original.cause = error; }
        const abort = new AbortController();
        try {
          await deadline(Promise.all([closed, groupExited(child.pid, abort.signal)]), forcedMs, 'owned fixture group did not close');
        }
        catch (error) {
          original.cause = error;
          original.cleanupPid = child.pid;
          if (child.connected) child.disconnect();
          child.stdout?.destroy();
          child.stderr?.destroy();
          child.unref();
        } finally { abort.abort(); }
        throw original;
      }
      assert.equal(result.code, 0, 'owned fixture must stop successfully');
      return result;
    })();
    return cleanup;
  };
  return Object.freeze({ closed, dispose });
}
