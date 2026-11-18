// Runs only after the reviewed bootstrap has sealed the private namespace,
// dropped to the actual original caller, and freshly execed the retained Node.
// This checks registration and refusal only; it cannot qualify any snapshot.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { readFile, readlink, stat } from 'node:fs/promises';
import { setTimeout as pause } from 'node:timers/promises';
import path from 'node:path';
import { launchObservedDaemon } from './retained-daemon.mjs';
import { ownDisposableGroup } from './owned-cleanup.mjs';

const builtins = [
  'antigravity-provider', 'claude-usage-source', 'codex-usage-source',
  'copilot-usage-source', 'cursor-usage-source', 'fx-provider',
  'grok-usage-source', 'hoplite-provider', 'kimi-usage-source',
  'minimax-usage-source', 'muse-provider', 'opencode-go-usage-source',
  'worktree-include', 'zai-usage-source',
];

async function cli(root, home, args) {
  const child = spawn(path.join(root, 'runtime/node'),
    [path.join(root, 'cli-entry.mjs'), ...args, '--home', home, '--json'], {
      detached: true, stdio: ['ignore', 'pipe', 'pipe'],
      env: {PATH: '/usr/bin:/bin', PASEO_HOME: home},
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
  const timer = setTimeout(() => stop('CLI timed out'), 15_000);
  try {
    const result = await owner.closed;
    if (failure) throw failure;
    return {code: result.code, stdout: Buffer.concat(output).toString('utf8'),
      stderr: Buffer.concat(errors).toString('utf8')};
  } finally {
    clearTimeout(timer);
    await owner.dispose();
  }
}


assert.equal(process.platform, 'linux');
assert.equal(process.env.GITHUB_ACTIONS, 'true');
assert.notEqual(process.getuid(), 0);
assert.notEqual(process.getgid(), 0);
assert.equal(process.argv.length, 7);
const [root, home, expectedManifest, hostNamespace, sourceSha] = process.argv.slice(2);
assert.match(expectedManifest, /^[a-f0-9]{64}$/);
assert.match(sourceSha, /^[a-f0-9]{40}$/);
const namespace = await readlink('/proc/self/ns/mnt');
assert.notEqual(namespace, hostNamespace, 'fresh private mount namespace required');
const credentials = await readFile('/proc/self/status', 'utf8');
assert.match(credentials, /^NoNewPrivs:\s+1$/m);
for (const name of ['CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb']) {
  assert.match(credentials, new RegExp(`^${name}:\\s+0+$`, 'm'), 'capabilities must be empty');
}
const actualNode = await stat('/proc/self/exe');
const retainedNode = await stat(path.join(root, 'runtime/node'));
assert.ok(actualNode.dev === retainedNode.dev && actualNode.ino === retainedNode.ino,
  'probe must freshly execute the retained Node');
let daemon, failure, result;
try {
  daemon = await launchObservedDaemon(root, home, expectedManifest);
  let plugins;
  const deadline = performance.now() + 180_000;
  while (performance.now() < deadline) {
    assert.equal(daemon.child.exitCode, null, 'owned daemon exited during startup');
    assert.equal(daemon.child.signalCode, null, 'owned daemon stopped during startup');
    const reply = await cli(root, home, ['plugin', 'ls']);
    if (reply.code === 0) { plugins = JSON.parse(reply.stdout); break; }
    await pause(500);
  }
  assert.ok(Array.isArray(plugins), 'actual plugin listing did not become available');
  assert.deepEqual(plugins.map((plugin) => plugin.id).sort(), [...builtins].sort(),
    'default builtin inventory changed');
  assert.ok(plugins.every((plugin) => plugin.enabled === true && plugin.status === 'running'),
    'all actual default registrations must initialize');
  const status = await cli(root, home, ['daemon', 'maintenance', 'status']);
  assert.equal(status.code, 0, 'actual maintenance status unavailable');
  const reservation = JSON.parse(status.stdout);
  assert.equal(reservation.authority?.features?.maintenanceReservationV1, false,
    'missing builtin profiles cannot enable maintenance');
  assert.ok(Number.isSafeInteger(reservation.reservationGeneration));
  const begin = await cli(root, home, ['daemon', 'maintenance', 'begin',
    '--generation', String(reservation.reservationGeneration + 1), '--transaction-id', randomUUID()]);
  assert.ok(begin.code !== 0 && begin.stdout.trim() === '', 'unqualified BEGIN must refuse without token');
  const observed = await daemon.observation();
  assert.equal(observed.status, 'hold', 'missing full executing profiles cannot qualify');
  result = {status: 'registration-negative-passed', qualification: false,
    builtinCount: plugins.length, manifestSha256: expectedManifest, sourceSha,
    daemonPid: daemon.child.pid, probePid: process.pid, hostNamespace, namespace};
} catch (error) {
  failure = error;
  if (daemon) process.stderr.write(`Disposable daemon diagnostics:\n${daemon.diagnostics()}\n`);
} finally {
  try { if (daemon) await daemon.dispose(); }
  catch (error) { failure = failure ? new AggregateError([failure, error], 'probe and teardown failed') : error; }
}
if (failure) throw failure;
// Publication follows actual daemon/CLI group disposal, never a timer or signal.
console.log(JSON.stringify({...result, ownedWorkSettled: true}));
