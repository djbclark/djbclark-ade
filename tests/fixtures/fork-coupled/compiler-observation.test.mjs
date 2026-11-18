import assert from 'node:assert/strict';
import test from 'node:test';
import { verifyOwnedColdPair } from './compiler-observation.mjs';
import { sha256 } from './retained-daemon.mjs';

function fixture() {
  const bytes = Buffer.from('actual bytes represented by this synthetic boundary case');
  const closure = {runtimeClosureSha256: '1'.repeat(64), helperClosureSha256: '2'.repeat(64),
    qualificationSha256: '3'.repeat(64)};
  const trigger = {generation: 7, transactionId: 'original-held-transaction', operation: 'verify',
    pluginId: 'ade-yolo', expectedGeneration: 3};
  const expected = {daemonPid: 100, daemonIncarnation: 'actual-owner-incarnation', closure,
    sourceDirectory: '/snapshots/target/plugins/ade-yolo', snapshotRoot: '/snapshots/target',
    snapshotSha256: '4'.repeat(64), serverBundleSha256: sha256(bytes), clientBundleSha256: null, trigger};
  const run = {threadId: 1, incarnation: 'compiler-one', sourceDirectory: expected.sourceDirectory,
    snapshotRoot: expected.snapshotRoot, snapshotSha256: expected.snapshotSha256,
    serverBundleBase64: bytes.toString('base64'), serverBundleSha256: sha256(bytes),
    serverBundleByteLength: bytes.length, clientBundleBase64: null, clientBundleSha256: null,
    closure, settled: true, trigger};
  const observation = {schemaVersion: 2, status: 'observed', daemon: {pid: expected.daemonPid,
    incarnation: expected.daemonIncarnation, closure}, runtime: {version: 2, observationEpoch: 6,
    compiler: {runs: [run, {...run, threadId: 2, incarnation: 'compiler-two'}], coldPair: [0, 1]}}};
  return structuredClone({bytes, observation, expected});
}

test('synthetic boundary returns both verified byte strings, never a runtime qualification', () => {
  const {bytes, observation, expected} = fixture();
  const result = verifyOwnedColdPair(observation, expected);
  assert.deepEqual(result.workerThreadIds, [1, 2]);
  assert.deepEqual(result.workerIncarnations, ['compiler-one', 'compiler-two']);
  assert.ok(result.outputs.every((value) => value.server.equals(Buffer.from(bytes)) && value.client === null));
  assert.equal(Object.hasOwn(result, 'qualified'), false);
});

const substitutions = {
  'prior source': (value) => { value.sourceDirectory = '/snapshots/old/plugins/ade-yolo'; },
  'prior tree': (value) => { value.snapshotSha256 = 'a'.repeat(64); },
  'other plugin': (value) => { value.trigger = {...value.trigger, pluginId: 'different'}; },
  'other native generation': (value) => { value.trigger = {...value.trigger, generation: 8}; },
  'other transaction': (value) => { value.trigger = {...value.trigger, transactionId: 'old'}; },
  'stale plugin CAS': (value) => { value.trigger = {...value.trigger, expectedGeneration: 2}; },
  'wrong operation': (value) => { value.trigger = {...value.trigger, operation: 'replace'}; },
  'unsettled lifetime': (value) => { value.settled = false; },
  'different closure': (value) => { value.closure = {...value.closure, qualificationSha256: 'b'.repeat(64)}; },
  'changed bytes': (value) => { value.serverBundleBase64 = Buffer.from('substituted bytes').toString('base64'); },
  'noncanonical base64': (value) => { value.serverBundleBase64 += '\n'; },
  'changed length': (value) => { value.serverBundleByteLength += 1; },
  'unbound client bytes': (value) => { value.clientBundleBase64 = 'YQ=='; },
};
for (const [name, alter] of Object.entries(substitutions)) {
  test(`matching hash in the other run cannot hide ${name}`, () => {
    const {observation, expected} = fixture();
    alter(observation.runtime.compiler.runs[1]);
    assert.throws(() => verifyOwnedColdPair(observation, expected));
  });
}

for (const name of ['same-thread', 'same-incarnation', 'same-index', 'unrelated-pair', 'hold', 'v1', 'other-daemon']) {
  test(`cold pair refuses ${name}`, () => {
    const {observation, expected} = fixture();
    const compiler = observation.runtime.compiler;
    if (name === 'same-thread') compiler.runs[1].threadId = compiler.runs[0].threadId;
    if (name === 'same-incarnation') compiler.runs[1].incarnation = compiler.runs[0].incarnation;
    if (name === 'same-index') compiler.coldPair = [0, 0];
    if (name === 'unrelated-pair') {
      compiler.runs.push({...compiler.runs[0], threadId: 3, incarnation: 'unrelated',
        trigger: {...compiler.runs[0].trigger, transactionId: 'other-transaction'}});
      compiler.coldPair = [1, 2];
    }
    if (name === 'hold') observation.status = 'hold';
    if (name === 'v1') observation.schemaVersion = 1;
    if (name === 'other-daemon') observation.daemon.incarnation = 'other-owner';
    assert.throws(() => verifyOwnedColdPair(observation, expected));
  });
}
