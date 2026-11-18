const { test } = require('node:test');
const assert = require('node:assert/strict');
const { TestWorkflowEnvironment } = require('@temporalio/testing');
const { Worker } = require('@temporalio/worker');
const { DatabaseSync } = require('node:sqlite');
const { mkdtemp, rm } = require('node:fs/promises');
const { tmpdir } = require('node:os');
const { join } = require('node:path');

test('task-like start, lost activity result, durable approval wait and worker restart', { timeout: 180000 }, async () => {
  const directory = await mkdtemp(join(tmpdir(), 'ade-temporal-small-'));
  const endpoint = new DatabaseSync(join(directory, 'fake-endpoint.sqlite3'));
  endpoint.exec('PRAGMA synchronous=FULL; CREATE TABLE effects(id TEXT PRIMARY KEY, result TEXT NOT NULL);');
  let attempts = 0;
  const activities = { async fakeEffect(id) {
    attempts++;
    const prior = endpoint.prepare('SELECT result FROM effects WHERE id=?').get(id);
    if (prior) return prior.result;
    endpoint.prepare('INSERT INTO effects VALUES (?,?)').run(id, 'fake-endpoint-receipt');
    throw new Error('fake response lost AFTER committed effect; retry must reuse endpoint id');
  } };
  let env, worker, run, stopped = false;
  try {
    // Downloads a disposable local dev server. No Cloud namespace, account,
    // model call, credit card, production credential or external effect.
    env = await TestWorkflowEnvironment.createLocal();
    const options = { connection: env.nativeConnection, taskQueue: 'ade-small-experiment',
      workflowsPath: require.resolve('./workflows.cjs'), activities };
    worker = await Worker.create(options);
    run = worker.run();
    const handle = await env.client.workflow.start('messageLikeTask', {
      taskQueue: options.taskQueue, workflowId: 'bounded-experiment', args: ['stable-operation-id'] });
    const deadline = Date.now() + 30000;
    while (await handle.query('phase') !== 'waiting-for-human') {
      assert.ok(Date.now() < deadline, 'workflow did not reach durable approval wait');
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.equal(attempts, 2, 'lost response caused one retry with same endpoint id');
    assert.equal(endpoint.prepare('SELECT count(*) AS n FROM effects').get().n, 1);
    worker.shutdown(); await run; stopped = true;
    const successor = await Worker.create(options);
    const receipt = await successor.runUntil(async () => {
      await handle.signal('approve');
      return handle.result();
    });
    assert.equal(receipt, 'fake-endpoint-receipt');
    assert.equal(endpoint.prepare('SELECT count(*) AS n FROM effects').get().n, 1);
    assert.equal(attempts, 2, 'workflow replay did not repeat successful activity');
    console.log(JSON.stringify({ local_only: true, cloud_enrolled: false,
      activity_attempts: attempts, external_effects: 1, worker_restart: true, approval_signal: true }));
  } finally {
    if (worker && !stopped) { worker.shutdown(); await run?.catch(() => {}); }
    await env?.teardown(); endpoint.close(); await rm(directory, { recursive: true, force: true });
  }
});
