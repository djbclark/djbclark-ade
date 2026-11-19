// Fixed retained CLI transport for disposable CI. Bearers use an anonymous
// stdin pipe only; do not log or serialize raw BEGIN output. No owner is minted.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { userInfo } from 'node:os';
import path from 'node:path';
import { ownDisposableGroup } from './owned-cleanup.mjs';

// Failure evidence is bounded stderr DATA, never stdout, a bearer or settlement.
const failureStderr = new WeakMap();
export function getCliFailureStderr(error) {
  return failureStderr.get(error) ?? null;
}

function failureStderrSnapshot(errors, stderrBytes) {
  const decoded = Buffer.from(Buffer.concat(errors).toString('utf8'), 'utf8');
  let end = Math.min(decoded.length, 16384);
  // Decoding invalid input can expand it; cut only at a UTF-8 boundary.
  while (end < decoded.length && end > 0 && (decoded[end] & 0xc0) === 0x80) end -= 1;
  return Object.freeze({
    stderr: decoded.subarray(0, end).toString('utf8'), stderrBytes,
    stderrTruncated: stderrBytes > 16384 || end < decoded.length,
  });
}

export function requireOwnerToken(value) {
  if (typeof value !== 'string' || value.length !== 43 || /[^A-Za-z0-9_-]/u.test(value)) {
    throw new Error('Invalid private owner token');
  }
}

export async function cli(root, home, args, {token = null, timeoutMs = 15000} = {}) {
  assert.ok(Number.isSafeInteger(timeoutMs) && timeoutMs > 0 && timeoutMs <= 120000);
  if (token !== null) requireOwnerToken(token);
  const child = spawn(path.join(root, 'runtime/node'),
    [path.join(root, 'cli-entry.mjs'), ...args, '--home', home, '--json'], {
      detached: true, stdio: [token === null ? 'ignore' : 'pipe', 'pipe', 'pipe'],
      env: {PATH: '/usr/bin:/bin', PASEO_HOME: home, HOME: userInfo().homedir},
    });
  const owner = ownDisposableGroup(child, {gracefulMs: 1500, forcedMs: 3000, allowNonzeroExit: true});
  return collectCliResponse(child, owner, {token, timeoutMs});
}

// Data transport only. The actual CLI path above always supplies its real child
// and group owner; controlled tests of bounded failure confer no native authority.
export async function collectCliResponse(child, owner, {token = null, timeoutMs}) {
  const output = [], errors = [];
  let stdoutBytes = 0, stderrBytes = 0;
  let failure;
  let fail;
  const failed = new Promise((resolve) => { fail = resolve; });
  const stop = (reason) => {
    if (!failure) { failure = new Error(reason); fail({failure}); }
  };
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
    const settled = await Promise.race([owner.closed.then((result) => ({result})), failed]);
    if (settled.failure) throw settled.failure;
    if (failure) throw failure;
    const result = settled.result;
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
  try {
    if (failure) throw failure;
    assert.ok(performance.now() < deadline, 'CLI deadline exceeded after actual disposal');
  } catch (error) {
    if (token === null && typeof error === 'object' && error !== null) {
      failureStderr.set(error, failureStderrSnapshot(errors, stderrBytes));
    }
    throw error;
  }
  return response;
}
