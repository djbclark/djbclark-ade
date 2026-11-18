// This is an actual retained-daemon missing-profile negative and ordinary
// registration check. It cannot emit qualified artifacts or complete A-B-A.
import assert from 'node:assert/strict';
import { spawn, execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { randomUUID } from 'node:crypto';
import { userInfo } from 'node:os';
import { access, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { setTimeout as pause } from 'node:timers/promises';
import path from 'node:path';
import { launchObservedDaemon, readRegular, sha256, validateRetainedDistribution } from './retained-daemon.mjs';
import { ownDisposableGroup } from './owned-cleanup.mjs';

const execute = promisify(execFile);
const builtins = [
  'antigravity-provider', 'claude-usage-source', 'codex-usage-source',
  'copilot-usage-source', 'cursor-usage-source', 'fx-provider',
  'grok-usage-source', 'hoplite-provider', 'kimi-usage-source',
  'minimax-usage-source', 'muse-provider', 'opencode-go-usage-source',
  'worktree-include', 'zai-usage-source',
];

async function sudo(arguments_) {
  await execute('sudo', ['-k', '-n', ...arguments_], {
    timeout: 30_000, maxBuffer: 65536, env: {PATH: '/usr/bin:/bin'},
  });
}

async function absent(file) {
  try { await access(file); return false; }
  catch (error) { if (error.code === 'ENOENT') return true; throw error; }
}

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
assert.equal(process.env.GITHUB_ACTIONS, 'true', 'disposable CI only');
assert.notEqual(process.getuid(), 0);
assert.equal(process.argv.length, 3, 'one authenticated staging directory required');
const staged = path.resolve(process.argv[2], 'qualified-daemon');
const manifestBytes = await readRegular(`${staged}.manifest.json`);
const manifest = JSON.parse(manifestBytes);
assert.deepEqual(manifest.builtinPlugins, builtins);
const expectedManifest = sha256(manifestBytes);
const contract = await readFile(new URL('./registration-smoke-contract.json', import.meta.url));
assert.equal(JSON.parse(contract).qualification, false);
const policyDirectory = path.join(userInfo().homedir, '.local/state/djbclark-ade/forks');
const hostPolicy = path.join(policyDirectory, 'paseo-qualified-host-policy.json');
const managedPolicy = path.join(policyDirectory, 'paseo-managed-plugins.json');
assert.ok(await absent(hostPolicy) && await absent(managedPolicy), 'fresh CI account policies required');
const root = `/fork-coupled-native-${randomUUID()}`;
const work = await mkdtemp('/tmp/fcs-');
const home = path.join(work, 'home');
let daemon;
let installed = false, hostWritten = false, managedWritten = false;
let failure, result;
try {
  await mkdir(home, {mode: 0o700});
  const config = {version: 1, pluginsEnabled: true,
    daemon: {listen: `unix://${work}/daemon.sock`, relay: {enabled: false},
      mcp: {enabled: false, injectIntoAgents: false}, usage: {enabled: false},
      browserTools: {enabled: false}, enableTerminalAgentHooks: false},
    features: {dictation: {enabled: false}, voiceMode: {enabled: false}, webUi: {enabled: false}},
    agents: {resumeOnStartup: false}};
  await writeFile(path.join(home, 'config.json'), JSON.stringify(config), {mode: 0o600, flag: 'wx'});
  await sudo(['/bin/cp', '-a', staged, root]); installed = true;
  await sudo(['/bin/cp', `${staged}.manifest.json`, `${root}.manifest.json`]);
  await sudo(['/bin/chown', '-R', 'root:root', root, `${root}.manifest.json`]);
  await sudo(['/bin/chmod', '0444', `${root}.manifest.json`]);
  await validateRetainedDistribution(root, expectedManifest);
  await mkdir(policyDirectory, {recursive: true, mode: 0o700});
  // Test authority binds this exact negative recipe, not a claimed successful
  // qualification. No builtinProfiles are granted, so maintenance must refuse.
  await writeFile(hostPolicy, JSON.stringify({schemaVersion: 1, qualifications: [{
    immutableRoot: root, immutabilityAdapter: 'linux-root-owned-retained-v1',
    distributionBuildId: manifest.distributionBuildId, manifestSha256: expectedManifest,
    qualificationSha256: sha256(contract),
  }]}), {mode: 0o600, flag: 'wx'}); hostWritten = true;
  await writeFile(managedPolicy, JSON.stringify({version: 1, plugins: {}}),
    {mode: 0o600, flag: 'wx'}); managedWritten = true;
  daemon = await launchObservedDaemon(root, home, expectedManifest);
  let plugins;
  const deadline = Date.now() + 180_000;
  while (Date.now() < deadline) {
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
    '--generation', String(reservation.reservationGeneration + 1),
    '--transaction-id', randomUUID()]);
  assert.ok(begin.code !== 0 && begin.stdout.trim() === '', 'unqualified BEGIN must refuse without token');
  const observed = await daemon.observation();
  assert.equal(observed.status, 'hold', 'missing full executing profiles cannot qualify');
  result = {status: 'registration-negative-passed', qualification: false,
    builtinCount: plugins.length, manifestSha256: expectedManifest, daemonPid: daemon.child.pid};
} catch (error) {
  failure = error;
  // Only this fresh disposable account's sanitized daemon output is retained.
  if (daemon) process.stderr.write(`Disposable daemon startup diagnostics:\n${daemon.diagnostics()}\n`);
} finally {
  try { if (daemon) await daemon.dispose(); }
  catch (error) { failure = failure ? new AggregateError([failure, error], 'startup and teardown failed') : error; }
  try {
    if (hostWritten) await rm(hostPolicy);
    if (managedWritten) await rm(managedPolicy);
    if (installed) await sudo(['/bin/rm', '-rf', root, `${root}.manifest.json`]);
    await rm(work, {recursive: true, force: true});
  }
  catch (error) { failure = failure ? new AggregateError([failure, error], 'fixture and cleanup failed') : error; }
}
if (failure) throw failure;
console.log(JSON.stringify(result));
