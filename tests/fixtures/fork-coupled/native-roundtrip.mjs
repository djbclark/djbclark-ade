// Real native FD transaction phase for a disposable, already provisioned CI
// daemon. No mock ports, owner mint, policy writes or automatic failure recovery.
// This phase alone is not the evaluator or complete feature qualification.
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { cli, requireOwnerToken } from './retained-cli.mjs';
import { validateRetainedDistribution } from './retained-daemon.mjs';
import { verifyOwnedColdPair } from './compiler-observation.mjs';

const target = 'ade-yolo';
const catalog = [
  // Runtime manifest IDs, distinct from ADE installer catalog aliases.
  'ade-claim', 'ade-window-name', target, 'baton', 'pr-radar', 'session-recovery',
  'antigravity-provider', 'claude-usage-source', 'codex-usage-source',
  'copilot-usage-source', 'cursor-usage-source', 'fx-provider',
  'grok-usage-source', 'hoplite-provider', 'kimi-usage-source',
  'minimax-usage-source', 'muse-provider', 'opencode-go-usage-source',
  'worktree-include', 'zai-usage-source',
].sort();
const digest = /^[a-f0-9]{64}$/;
function keys(value, names) {
  assert.ok(value && typeof value === 'object' && !Array.isArray(value));
  assert.deepEqual(Object.keys(value).sort(), [...names].sort());
}
function staticHost(row) {
  assert.equal(row.enabled, true);
  assert.ok(row.registration && row.loaded && row.execution, 'complete executing cohort required');
  if (row.kind === 'directory') {
    keys(row, ['kind', 'pluginId', 'registration', 'enabled', 'journal', 'loaded', 'execution']);
    assert.equal(row.loaded.kind, 'plugin-child');
    const receipt = row.loaded.receipt;
    assert.deepEqual(row.journal?.currentReceipt, receipt, 'loaded receipt must be the current native journal receipt');
    assert.ok(Number.isSafeInteger(row.journal.generation) && row.journal.generation > 0);
    assert.equal(row.execution.kind, 'plugin-child');
    assert.equal(row.execution.contract, 'native-passive-contract-1');
    assert.equal(row.execution.incarnation, receipt.processStartToken);
    assert.ok(Number.isSafeInteger(receipt.pid) && receipt.pid > 0 && receipt.startedAt);
    return {kind: row.kind, registration: row.registration, enabled: true,
      loaded: {sourcePath: receipt.sourcePath, snapshotRoot: receipt.snapshotRoot,
        snapshotSha256: receipt.snapshotSha256, serverBundleSha256: receipt.serverBundleSha256},
      execution: {contract: row.execution.contract, distributionBuildId: row.execution.distributionBuildId,
        closure: row.execution.closure}};
  }
  assert.equal(row.kind, 'builtin-in-process');
  keys(row, ['kind', 'pluginId', 'registration', 'enabled', 'loaded', 'execution']);
  assert.equal(row.loaded.kind, row.kind);
  assert.equal(row.execution.kind, row.kind);
  assert.equal(row.loaded.pluginId, row.pluginId);
  assert.equal(row.execution.pluginId, row.pluginId);
  assert.ok(typeof row.loaded.instanceId === 'string' && row.loaded.instanceId.length > 0);
  assert.equal(row.loaded.instanceId, row.execution.instanceId);
  assert.equal(row.execution.contract, 'builtin-in-process-v1');
  for (const key of ['sourcePath', 'sourceSha256', 'serverBundleSha256', 'moduleTableSha256',
    'profileSha256', 'closure', 'enclosingIncarnation']) {
    assert.deepEqual(row.loaded[key], row.execution[key]);
  }
  for (const key of ['sourceSha256', 'serverBundleSha256', 'moduleTableSha256', 'profileSha256']) {
    assert.match(row.loaded[key], digest);
  }
  return {kind: row.kind, registration: row.registration, enabled: true,
    loaded: {sourcePath: row.loaded.sourcePath, sourceSha256: row.loaded.sourceSha256,
      serverBundleSha256: row.loaded.serverBundleSha256, moduleTableSha256: row.loaded.moduleTableSha256,
      profileSha256: row.loaded.profileSha256, closure: row.loaded.closure},
    execution: {contract: row.execution.contract, distributionBuildId: row.execution.distributionBuildId,
      closure: row.execution.closure}};
}

export async function runNativeRoundTrip({root, home, manifestSha256, daemon, enclosing, hosts, baseline, replacement}) {
  assert.equal(process.platform, 'linux');
  assert.notEqual(process.getuid(), 0);
  await validateRetainedDistribution(root, manifestSha256);
  assert.deepEqual(Object.keys(hosts).sort(), catalog, 'protected full catalog required');
  assert.deepEqual(hosts[target], baseline.host);
  assert.notEqual(baseline.host.loaded.sourcePath, replacement.host.loaded.sourcePath);
  assert.notEqual(baseline.host.loaded.snapshotSha256, replacement.host.loaded.snapshotSha256);
  keys(enclosing, ['serverId', 'incarnation', 'distributionBuildId', 'closure']);
  assert.equal(enclosing.closure.runtimeClosureSha256, manifestSha256);
  assert.ok(daemon.child.pid > 0 && daemon.child.connected && daemon.child.exitCode === null);
  const identity = ['--expected-server-id', enclosing.serverId,
    '--expected-daemon-incarnation', enclosing.incarnation];
  let token = null, nativeGeneration, transactionId, pluginGeneration;
  const call = async (args, privateOwner = false) => {
    if (privateOwner) requireOwnerToken(token);
    const response = await cli(root, home, args, {token: privateOwner ? token : null, timeoutMs: 30000});
    // Never include raw BEGIN/operation stdout in an assertion or diagnostic.
    assert.equal(response.code, 0, 'retained native CLI refused the requested phase');
    try { return JSON.parse(response.stdout); }
    catch { throw new Error('retained native CLI returned invalid JSON'); }
  };
  const status = async () => {
    const value = await call(['daemon', 'maintenance', 'status']);
    assert.equal(value.authority?.qualified, true);
    assert.equal(value.authority.serverId, enclosing.serverId);
    assert.equal(value.authority.daemonIncarnation, enclosing.incarnation);
    assert.equal(value.authority.features?.maintenanceReservationV1, true);
    assert.equal(value.authority.features?.maintenancePluginOperationV1, true);
    assert.equal(value.ready, true);
    assert.equal(value.recoveryRequired, false);
    return value;
  };
  let untouched;
  const cohort = async (selected) => {
    const value = await call(['plugin', 'cohort-v2-status']);
    assert.equal(value.version, 2);
    assert.equal(value.consistency, 'coherent');
    assert.deepEqual(value.enclosing, enclosing);
    assert.deepEqual(value.entries.map((row) => row.pluginId).sort(), catalog);
    const rows = new Map();
    for (const row of value.entries) {
      assert.ok(!rows.has(row.pluginId));
      const expected = row.pluginId === target ? selected.host : hosts[row.pluginId];
      assert.deepEqual(staticHost(row), expected, `protected host mismatch: ${row.pluginId}`);
      assert.equal(row.execution.distributionBuildId, enclosing.distributionBuildId);
      assert.deepEqual(row.execution.closure, enclosing.closure);
      if (row.kind === 'builtin-in-process') assert.equal(row.loaded.enclosingIncarnation, enclosing.incarnation);
      rows.set(row.pluginId, row);
    }
    const others = value.entries.filter((row) => row.pluginId !== target).sort((a, b) => a.pluginId.localeCompare(b.pluginId));
    if (untouched) assert.deepEqual(others, untouched, 'another host changed during target replacement');
    else untouched = structuredClone(others);
    return rows.get(target);
  };
  const original = await cohort(baseline);
  assert.equal(original.journal.generation, 1, 'fresh public enrollment must establish the actual first receipt');
  pluginGeneration = original.journal.generation;
  const initialStatus = await status();
  assert.equal(initialStatus.state, 'idle');
  assert.ok(Number.isSafeInteger(initialStatus.reservationGeneration) && initialStatus.reservationGeneration >= 0);
  nativeGeneration = initialStatus.reservationGeneration + 1;
  assert.ok(Number.isSafeInteger(nativeGeneration));
  transactionId = randomUUID();
  const reservation = ['--generation', String(nativeGeneration), '--transaction-id', transactionId, ...identity];
  const begin = await call(['daemon', 'maintenance', 'begin', ...reservation]);
  token = begin.ownerToken;
  delete begin.ownerToken;
  requireOwnerToken(token);
  assert.equal(begin.state, 'held');
  assert.equal(begin.recoveryRequired, false);
  assert.equal(begin.generation, nativeGeneration);
  assert.equal(begin.transactionId, transactionId);
  const heldStatus = async () => {
    const value = await status();
    assert.equal(value.state, 'held');
    assert.equal(value.generation, nativeGeneration);
    assert.equal(value.reservationGeneration, nativeGeneration);
    assert.equal(value.transactionId, transactionId);
  };
  const operation = async (kind, from, to) => {
    await heldStatus();
    const expectedGeneration = pluginGeneration;
    const loaded = to.host.loaded;
    const value = await call(['daemon', 'maintenance', 'plugin-operation', '--operation', kind,
      ...reservation, '--plugin-id', target, '--path', loaded.sourcePath,
      '--expected-path', from.host.loaded.sourcePath, '--expected-generation', String(expectedGeneration),
      '--snapshot-sha256', loaded.snapshotSha256, '--server-bundle-sha256', loaded.serverBundleSha256,
      '--owner-token-fd', '0'], true);
    assert.equal(value.outcome, undefined, 'normal roundtrip cannot relabel a failed-held outcome as success');
    assert.equal(value.serverId, enclosing.serverId);
    assert.equal(value.daemonIncarnation, enclosing.incarnation);
    assert.equal(value.plugin?.id, target);
    assert.equal(value.plugin.status, 'running');
    assert.equal(value.plugin.enabled, true);
    const nextGeneration = expectedGeneration + (kind === 'verify' ? 0 : 1);
    assert.equal(value.nativeGeneration, nextGeneration, 'plugin journal CAS is independent of native reservation');
    pluginGeneration = nextGeneration;
    const actual = await cohort(to);
    assert.equal(actual.journal.generation, pluginGeneration);
    assert.deepEqual(actual.loaded.receipt, value.plugin.loaded);
    await heldStatus();
    return {receipt: actual.loaded.receipt, expectedGeneration};
  };
  // Any refusal/exception exits with the reservation still held. No fallback
  // BEGIN, automatic recover, blind replay or END occurs in a failure handler.
  const changed = await operation('replace', baseline, replacement);
  assert.notEqual(changed.receipt.processStartToken, original.loaded.receipt.processStartToken);
  const checkedB = await operation('verify', replacement, replacement);
  assert.deepEqual(checkedB.receipt, changed.receipt, 'verify must not restart or replace the loaded child');
  const recovered = await operation('recover', replacement, baseline);
  assert.notEqual(recovered.receipt.processStartToken, original.loaded.receipt.processStartToken);
  assert.notEqual(recovered.receipt.processStartToken, changed.receipt.processStartToken);
  const checkedA = await operation('verify', baseline, baseline);
  assert.deepEqual(checkedA.receipt, recovered.receipt);
  const observed = await daemon.observation();
  const bytes = verifyOwnedColdPair(observed, {daemonPid: daemon.child.pid,
    daemonIncarnation: enclosing.incarnation, closure: enclosing.closure,
    sourceDirectory: baseline.host.loaded.sourcePath, snapshotRoot: baseline.host.loaded.snapshotRoot,
    snapshotSha256: baseline.host.loaded.snapshotSha256,
    serverBundleSha256: baseline.host.loaded.serverBundleSha256,
    clientBundleSha256: baseline.clientBundleSha256,
    trigger: {generation: nativeGeneration, transactionId, operation: 'verify', pluginId: target,
      expectedGeneration: checkedA.expectedGeneration}});
  assert.deepEqual(observed.runtime.plugins, await call(['plugin', 'cohort-v2-status']),
    'full compiler observation must match a fresh coherent cohort');
  const end = await call(['daemon', 'maintenance', 'end', ...reservation, '--owner-token-fd', '0'], true);
  assert.equal(end.state, 'idle');
  assert.equal(end.recoveryRequired, false);
  assert.equal(end.reservationGeneration, nativeGeneration);
  assert.equal(end.transactionId, transactionId);
  token = null;
  const final = await status();
  assert.equal(final.state, 'idle');
  assert.equal(final.reservationGeneration, nativeGeneration);
  await cohort(baseline);
  return {qualification: false, phase: 'native-roundtrip-passed', nativeGeneration, transactionId,
    pluginGeneration, original: original.loaded.receipt, replacement: changed.receipt,
    recovered: recovered.receipt, compiler: bytes};
}
