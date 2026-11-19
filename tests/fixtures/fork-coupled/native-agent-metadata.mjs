// Genuine public-client create/read/archive component for disposable Linux CI.
// No injected clients, provider definitions, hook results or model responses.
// This does not prove catalogue discovery, resume, claim enforcement or full20.
import assert from 'node:assert/strict';
import { realpath } from 'node:fs/promises';
import { userInfo } from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { cli } from './retained-cli.mjs';
import { validateRetainedDistribution } from './retained-daemon.mjs';

export async function runNativeAgentMetadata({root, home, manifestSha256, enclosing,
  workspaceId, cwd, agentTitle, expectedWindowName}) {
  assert.equal(process.platform, 'linux');
  assert.notEqual(process.getuid(), 0);
  assert.equal(home, path.join(userInfo().homedir, '.paseo'));
  assert.equal(await realpath(cwd), cwd);
  for (const value of [workspaceId, agentTitle, expectedWindowName]) {
    assert.ok(typeof value === 'string' && value.length > 0 && Buffer.byteLength(value) <= 1024);
  }
  await validateRetainedDistribution(root, manifestSha256);
  // Full sealed inventory and current namespace checks precede any import.
  const transport = await import(pathToFileURL(path.join(root, 'client-code.mjs')).href);
  assert.deepEqual(Object.keys(transport), ['connectToDaemon']);
  assert.equal(typeof transport.connectToDaemon, 'function');
  const deadline = performance.now() + 60000;
  const bounded = async (operation, label, limit = deadline - performance.now()) => {
    if (limit <= 0) throw new Error('Native metadata phase deadline exceeded');
    let timer;
    try {
      return await Promise.race([operation(), new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(label)), limit);
      })]);
    } finally { clearTimeout(timer); }
  };
  const observeAuthority = async () => {
    const result = await cli(root, home, ['daemon', 'maintenance', 'status'], {timeoutMs: 15000});
    assert.equal(result.code, 0);
    let status;
    try { status = JSON.parse(result.stdout); }
    catch { throw new Error('Native metadata authority response is invalid'); }
    assert.equal(status.authority?.qualified, true);
    assert.equal(status.authority.serverId, enclosing.serverId);
    assert.equal(status.authority.daemonIncarnation, enclosing.incarnation);
    assert.equal(status.ready, true);
    assert.equal(status.authority.features?.maintenanceReservationV1, true);
    assert.equal(status.authority.features?.maintenancePluginOperationV1, true);
    assert.equal(status.state, 'idle');
    assert.equal(status.recoveryRequired, false);
    return status;
  };
  const before = await observeAuthority();
  // Use the actual client's own connect timeout/cleanup, rather than racing
  // away and losing a connection handle that might be returned later.
  assert.equal(Object.hasOwn(process.env, 'PASEO_PASSWORD'), false);
  const client = await transport.connectToDaemon({
    target: {kind: 'instance', home}, timeout: 10000,
  });
  let failed;
  let result;
  try {
    const workspace = await bounded(() => client.findWorkspace(workspaceId), 'Workspace read timed out');
    assert.equal(workspace?.id, workspaceId);
    assert.equal(workspace.workspaceDirectory, cwd);
    assert.notEqual(workspace.name, expectedWindowName, 'naming positive must observe an actual change');
    const providers = await bounded(() => client.getProvidersSnapshot({cwd}), 'Real catalogue read timed out');
    const rows = providers.entries.filter((row) => row.provider === 'claude');
    assert.equal(rows.length, 1);
    assert.equal(rows[0].enabled, true);
    assert.equal(rows[0].status, 'ready');
    assert.ok(rows[0].modes.some((mode) => mode.id === 'default'));
    assert.ok(rows[0].modes.some((mode) => mode.id === 'bypassPermissions'));
    // No prompt/images/attachments, output schema, fake session or mode-control call.
    // A real catalogue's prior discovery helpers are a separate required proof.
    const created = await bounded(() => client.createAgent({provider: 'claude', cwd,
      workspaceId, title: agentTitle, modeId: 'default'}), 'Actual agent create timed out');
    assert.ok(typeof created.id === 'string' && created.id.length > 0);
    const fetched = await bounded(() => client.fetchAgent({agentId: created.id}), 'Agent read timed out');
    assert.equal(fetched.agent?.id, created.id);
    assert.equal(fetched.agent.provider, 'claude');
    assert.equal(fetched.agent.workspaceId, workspaceId);
    assert.equal(fetched.agent.cwd, cwd);
    assert.equal(fetched.agent.title, agentTitle);
    assert.equal(fetched.agent.currentModeId, 'bypassPermissions');
    assert.equal(fetched.agent.metadata?.['ade-yolo.applied'], '1');
    let renamed;
    do {
      renamed = await bounded(() => client.findWorkspace(workspaceId), 'Naming readback timed out');
      assert.equal(renamed?.id, workspaceId);
      assert.equal(renamed.workspaceDirectory, cwd);
      if (renamed.name === expectedWindowName) break;
      await bounded(() => new Promise((resolve) => setTimeout(resolve, 50)), 'Naming observation timed out');
    } while (performance.now() < deadline);
    assert.equal(renamed.name, expectedWindowName);
    await bounded(() => client.archiveAgent(created.id), 'Actual agent archive timed out');
    const archived = await bounded(() => client.fetchAgent({agentId: created.id}), 'Archive readback timed out');
    assert.equal(archived.agent?.id, created.id);
    assert.ok(typeof archived.agent.archivedAt === 'string' && archived.agent.archivedAt.length > 0);
    const after = await observeAuthority();
    assert.equal(after.reservationGeneration, before.reservationGeneration);
    result = {qualification: false, phase: 'native-agent-metadata-passed',
      agentId: created.id, workspaceId, mode: fetched.agent.currentModeId,
      title: renamed.name, archivedAt: archived.agent.archivedAt};
  } catch (error) { failed = error; }
  finally {
    // Closing this public connection is not daemon/helper settlement. Failure
    // never replays create/archive, starts BEGIN, repairs state or releases END.
    try { await bounded(() => client.close(), 'Public client close timed out', 5000); }
    catch (error) { failed = failed ? new AggregateError([failed, error], 'Metadata phase and connection close failed') : error; }
  }
  if (failed) throw failed;
  assert.ok(performance.now() < deadline, 'Native metadata phase deadline exceeded');
  return result;
}
