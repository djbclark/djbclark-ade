// Synthetic boundary checks only. No provider, native agent or qualification proof.
import assert from 'node:assert/strict';
import test from 'node:test';
import { observeMetadataAuthority, requireMetadataClientEntry } from './native-agent-metadata.mjs';

const enclosing = {serverId: 'expected-server', incarnation: 'expected-incarnation'};
const healthy = () => ({authority: {qualified: true, serverId: enclosing.serverId,
  daemonIncarnation: enclosing.incarnation,
  features: {maintenanceReservationV1: true, maintenancePluginOperationV1: true}},
ready: true, state: 'idle', recoveryRequired: false, reservationGeneration: 4});

test('new executable entry must be in the already verified manifest', () => {
  assert.throws(() => requireMetadataClientEntry({files: [{path: 'daemon.mjs'}]}), /Verified client entry absent/);
  assert.throws(() => requireMetadataClientEntry({files: [{path: 'other/client-code.mjs'}]}), /Verified client entry absent/);
  requireMetadataClientEntry({files: [{path: 'client-code.mjs'}]});
});

test('same-client status uses actual result/error envelope and original identity', async () => {
  let reads = 0;
  const client = {maintenanceStatus: async () => { reads += 1; return {result: healthy()}; }};
  assert.equal((await observeMetadataAuthority(client, enclosing)).reservationGeneration, 4);
  assert.equal(reads, 1);
  for (const payload of [{error: 'refused', result: healthy()}, {}, {result: null}]) {
    await assert.rejects(observeMetadataAuthority({maintenanceStatus: async () => payload}, enclosing));
  }
});

for (const [name, alter] of [
  ['other server', (s) => { s.authority.serverId = 'different-server'; }],
  ['other incarnation', (s) => { s.authority.daemonIncarnation = 'different-incarnation'; }],
  ['unqualified', (s) => { s.authority.qualified = false; }],
  ['unready', (s) => { s.ready = false; }],
  ['missing reservation feature', (s) => { delete s.authority.features.maintenanceReservationV1; }],
  ['missing mutation feature', (s) => { delete s.authority.features.maintenancePluginOperationV1; }],
  ['held', (s) => { s.state = 'held'; }],
  ['recovery', (s) => { s.recoveryRequired = true; }],
  ['missing baseline', (s) => { delete s.reservationGeneration; }],
]) {
  test(`mutation-channel authority rejects ${name}`, async () => {
    const status = healthy(); alter(status);
    await assert.rejects(observeMetadataAuthority({maintenanceStatus: async () => ({result: status})}, enclosing));
  });
}
