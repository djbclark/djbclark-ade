// Fixed retained CLI transport for disposable CI. Bearers use an anonymous
// stdin pipe only; do not log or serialize raw BEGIN output. No owner is minted.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { userInfo } from 'node:os';
import path from 'node:path';
import { ownDisposableGroup } from './owned-cleanup.mjs';

export async function cli(root, home, args, {token = null, timeoutMs = 15000} = {}) {
  assert.ok(Number.isSafeInteger(timeoutMs) && timeoutMs > 0 && timeoutMs <= 120000);
  if (token !== null) assert.match(token, /^[A-Za-z0-9_-]{43}$/);
  const child = spawn(path.join(root, 'runtime/node'),
    [path.join(root, 'cli-entry.mjs'), ...args, '--home', home, '--json'], {
      detached: true, stdio: [token === null ? 'ignore' : 'pipe', 'pipe', 'pipe'],
      env: {PATH: '/usr/bin:/bin', PASEO_HOME: home, HOME: userInfo().homedir},
    });
  const owner = ownDisposableGroup(child, {gracefulMs: 1500, forcedMs: 3000, allowNonzeroExit: true});
  const output = [], errors = [];
  let stdoutBytes = 0, stderrBytes = 0;
  let failure;
  const stop = (reason) => { failure ??= new Error(reason); void owner.dispose().catch(() => {}); };
  child.stdout.on('data', (chunk) => {
    stdoutBytes += chunk.length;
    if (stdoutBytes > 1024 * 1024) stop('CLI stdout overflow');
    else output.push(chunk);
  });
  child.stderr.on('data', (chunk) => {
    stderrBytes += chunk.length;
    if (stderrBytes > 16384) stop('CLI stderr overflow');
    else errors.push(chunk);
  });
  child.once('error', () => stop('CLI failed to launch'));
  const timer = setTimeout(() => stop('CLI timed out'), timeoutMs);
  const deadline = performance.now() + timeoutMs;
  let response;
  try {
    if (token !== null) {
      child.stdin.on('error', () => stop('CLI owner pipe failed'));
      child.stdin.end(token + '\n');
    }
    const result = await owner.closed;
    if (failure) throw failure;
    assert.ok(performance.now() < deadline, 'CLI deadline exceeded');
    response = {code: result.code, stdout: Buffer.concat(output).toString('utf8'),
      stderr: Buffer.concat(errors).toString('utf8')};
  } catch (error) {
    failure ??= error;
  } finally {
    clearTimeout(timer);
    try { await owner.dispose(); }
    catch (error) { failure = failure ? new AggregateError([failure, error], 'CLI and cleanup failed') : error; }
  }
  if (failure) throw failure;
  assert.ok(performance.now() < deadline, 'CLI deadline exceeded after actual disposal');
  return response;
}
