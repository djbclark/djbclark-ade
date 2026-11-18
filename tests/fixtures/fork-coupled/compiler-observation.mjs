// Data validation for an observation already received on the actual owned
// daemon IPC channel. This creates no execution capability or qualification.
import assert from 'node:assert/strict';
import path from 'node:path';
import { sha256 } from './retained-daemon.mjs';

const hex = /^[a-f0-9]{64}$/;
const closureKeys = ['runtimeClosureSha256', 'helperClosureSha256', 'qualificationSha256'];
const triggerKeys = ['generation', 'transactionId', 'operation', 'pluginId', 'expectedGeneration'];
function exact(object, keys) {
  assert.ok(object && typeof object === 'object' && !Array.isArray(object));
  assert.deepEqual(Object.keys(object).sort(), [...keys].sort());
}
function closure(value) {
  exact(value, closureKeys);
  for (const key of closureKeys) assert.match(value[key], hex);
}
function trigger(value) {
  exact(value, triggerKeys);
  for (const key of ['generation', 'expectedGeneration']) {
    assert.ok(Number.isSafeInteger(value[key]) && value[key] >= 0);
  }
  assert.ok(['replace', 'recover', 'verify'].includes(value.operation));
  for (const key of ['transactionId', 'pluginId']) {
    assert.ok(typeof value[key] === 'string' && value[key].length > 0 && value[key].length <= 256);
  }
}
function canonicalDirectory(value) {
  assert.ok(typeof value === 'string' && !value.includes('\0') && path.isAbsolute(value) &&
    path.normalize(value) === value);
}
function bundle(encoded, digest, length) {
  assert.ok(typeof encoded === 'string' && encoded.length <= 8388608);
  assert.match(digest, hex);
  const bytes = Buffer.from(encoded, 'base64');
  assert.equal(bytes.toString('base64'), encoded, 'compiler bytes must use canonical base64');
  assert.ok(bytes.length <= 6291456);
  if (length !== undefined) {
    assert.ok(Number.isSafeInteger(length) && length > 0);
    assert.equal(bytes.length, length, 'actual compiler byte length mismatch');
  }
  assert.equal(sha256(bytes), digest, 'actual compiler bytes do not match their digest');
  return bytes;
}

export function verifyOwnedColdPair(observation, expected) {
  // expected must come from the protected target and the SAME authenticated held
  // operation, not by copying the observation's latest unrelated coldPair.
  exact(expected, ['daemonPid', 'daemonIncarnation', 'closure', 'sourceDirectory',
    'snapshotRoot', 'snapshotSha256', 'serverBundleSha256', 'clientBundleSha256', 'trigger']);
  closure(expected.closure);
  trigger(expected.trigger);
  canonicalDirectory(expected.sourceDirectory);
  canonicalDirectory(expected.snapshotRoot);
  assert.match(expected.snapshotSha256, hex);
  assert.match(expected.serverBundleSha256, hex);
  if (expected.clientBundleSha256 !== null) assert.match(expected.clientBundleSha256, hex);
  assert.ok(Number.isSafeInteger(expected.daemonPid) && expected.daemonPid > 0);
  assert.ok(typeof expected.daemonIncarnation === 'string' && expected.daemonIncarnation.length > 0);
  assert.equal(observation.schemaVersion, 2);
  assert.equal(observation.status, 'observed', 'HOLD is not compiler execution evidence');
  assert.equal(observation.daemon?.pid, expected.daemonPid);
  assert.equal(observation.daemon.incarnation, expected.daemonIncarnation);
  assert.deepEqual(observation.daemon.closure, expected.closure);
  assert.equal(observation.runtime?.version, 2);
  assert.ok(Number.isSafeInteger(observation.runtime.observationEpoch) &&
    observation.runtime.observationEpoch >= 0);
  const compiler = observation.runtime.compiler;
  assert.ok(compiler && Array.isArray(compiler.runs) && compiler.runs.length <= 8);
  const pair = compiler.coldPair;
  assert.ok(Array.isArray(pair) && pair.length === 2 && pair[0] !== pair[1]);
  assert.ok(pair.every((index) => Number.isSafeInteger(index) && index >= 0 && index < compiler.runs.length));
  const runs = pair.map((index) => compiler.runs[index]);
  const outputs = runs.map((run) => {
    exact(run, ['threadId', 'incarnation', 'sourceDirectory', 'snapshotRoot', 'snapshotSha256',
      'serverBundleBase64', 'serverBundleSha256', 'serverBundleByteLength',
      'clientBundleBase64', 'clientBundleSha256', 'closure', 'settled', 'trigger']);
    assert.equal(run.settled, true, 'unsettled compiler work cannot qualify');
    assert.ok(Number.isSafeInteger(run.threadId) && run.threadId > 0);
    assert.ok(typeof run.incarnation === 'string' && run.incarnation.length > 0 && run.incarnation.length <= 512);
    assert.deepEqual(run.closure, expected.closure);
    assert.deepEqual(run.trigger, expected.trigger, 'cold pair belongs to a different native operation/CAS');
    for (const key of ['sourceDirectory', 'snapshotRoot', 'snapshotSha256',
      'serverBundleSha256', 'clientBundleSha256']) {
      assert.equal(run[key], expected[key], `cold pair target substitution: ${key}`);
    }
    const server = bundle(run.serverBundleBase64, run.serverBundleSha256, run.serverBundleByteLength);
    let client = null;
    if (run.clientBundleBase64 === null) assert.equal(run.clientBundleSha256, null);
    else client = bundle(run.clientBundleBase64, run.clientBundleSha256);
    return {server, client};
  });
  assert.notEqual(runs[0].threadId, runs[1].threadId, 'two distinct actual Worker threads required');
  assert.notEqual(runs[0].incarnation, runs[1].incarnation, 'two distinct actual Worker incarnations required');
  assert.ok(outputs[0].server.equals(outputs[1].server));
  assert.equal(outputs[0].client === null, outputs[1].client === null);
  if (outputs[0].client) assert.ok(outputs[0].client.equals(outputs[1].client));
  return {outputs, workerThreadIds: runs.map((run) => run.threadId),
    workerIncarnations: runs.map((run) => run.incarnation)};
}
