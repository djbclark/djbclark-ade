import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { appendFile, chmod, copyFile, link, lstat, mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { setupWorker } from './setup-compiler.mjs';

const digest = (value) => createHash('sha256').update(value).digest('hex');
const fixtureVersion = '0.8.123-synthetic';

async function manifest(root) {
  const files = [];
  async function visit(dir) {
    for (const name of (await readdir(dir)).sort()) {
      const file = path.join(dir, name), stat = await lstat(file);
      if (stat.isDirectory()) await visit(file);
      else files.push({ path: path.relative(root, file), mode: stat.mode & 0o777,
        size: stat.size, sha256: digest(await readFile(file)) });
    }
  }
  await visit(root);
  await writeFile(root + '.manifest.json', JSON.stringify({ schemaVersion: 2,
    profile: 'enclosing-daemon-v2', files }));
}

// SYNTHETIC protocol/lifecycle fixtures, not native ownership or real compiler proof.
async function fixture(t, mode = 'normal') {
  const dir = await mkdtemp(path.join(tmpdir(), 'setup-compiler-unit-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const root = path.join(dir, 'retained'), snapshot = path.join(dir, 'snapshot');
  const plugin = path.join(snapshot, 'plugin'), output = path.join(dir, 'expected');
  await mkdir(path.join(root, 'runtime'), { recursive: true });
  await mkdir(path.join(root, 'node_modules/esbuild/lib'), { recursive: true });
  await mkdir(plugin, { recursive: true });
  try { await link(process.execPath, path.join(root, 'runtime/node')); }
  catch { await copyFile(process.execPath, path.join(root, 'runtime/node')); }
  await writeFile(path.join(root, 'package.json'), JSON.stringify({ type: 'module', version: fixtureVersion }));
  await writeFile(path.join(root, 'node_modules/esbuild/package.json'), JSON.stringify({ name: 'esbuild', version: '1.2.3', main: 'lib/main.cjs' }));
  const service = `#!${process.execPath}
process.stdin.resume();
process.stdin.on('end', () => setTimeout(() => process.stdin.pause(), 120));
`;
  await writeFile(path.join(root, 'runtime/esbuild'), service, { mode: 0o755 });
  await writeFile(path.join(root, 'node_modules/esbuild/lib/main.cjs'), `
const cp = require('node:child_process');
let child;
exports.admittedSettled = false;
exports.start = () => {
  child = cp.spawn(process.env.ESBUILD_BINARY_PATH, ['--service=1.2.3', '--ping'], {stdio:['pipe','pipe','pipe']});
  child.stdout.resume(); child.stderr.resume();
};
exports.stop = () => {
  if (!exports.admittedSettled) throw new Error('stop before actual admitted settlement');
  if (${JSON.stringify(mode)} === 'stop-fails') throw new Error('synthetic close rejected');
  child.stdin.end();
};
`);
  const compiler = `
import { parentPort } from 'node:worker_threads';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
const esbuild = createRequire(import.meta.url)('esbuild');
let admitted, accepting = true;
export function retireQualifiedCompilerTasks() {
  accepting = false;
  return admitted;
}
parentPort.on('message', (task) => {
  if (!accepting) throw new Error('already retiring');
  if (JSON.stringify(Object.keys(task).sort()) !== JSON.stringify(['directory','kind','version'])) throw new Error('unexpected task fields');
  if (task.kind !== 'directory' || task.version !== ${JSON.stringify(fixtureVersion)}) throw new Error('wrong actual metadata/task');
  if (process.env.NODE_OPTIONS || process.env.PASEO_MANAGED_PLUGIN_POLICY) throw new Error('ambient authority leaked');
  admitted = (async () => {
    esbuild.start();
    if (${JSON.stringify(mode)} === 'hang') return await new Promise(() => {});
    const server = await readFile(path.join(task.directory, 'server.txt'), 'utf8');
    const client = ${JSON.stringify(mode)} === 'server-only' ? null : await readFile(path.join(task.directory, 'client.txt'), 'utf8');
    if (${JSON.stringify(mode)} === 'compile-error') parentPort.postMessage({kind:'error',error:new Error('synthetic compiler refusal'),properties:{}});
    else parentPort.postMessage({ kind: 'result', value: { manifest: {id:'synthetic-only'},
      serverBundle: 'server:' + task.version + ':' + server, clientBundle: client } });
    // The reply is deliberately earlier than admitted settlement: setup must
    // await this actual export, not infer drain from receiving bytes.
    await new Promise((resolve) => setTimeout(resolve, 80));
    esbuild.admittedSettled = true;
  })();
});
`;
  await writeFile(path.join(root, 'compiler-code.mjs'), compiler);
  await writeFile(path.join(plugin, 'server.txt'), '中文 café 😀\nserver');
  await writeFile(path.join(plugin, 'client.txt'), 'client Ω\n');
  await manifest(root);
  return { nativeRoot: root, snapshotRoot: snapshot, directory: plugin,
    outputDirectory: output, timeoutMs: 10_000, dir };
}

async function absent(file) {
  await assert.rejects(lstat(file), { code: 'ENOENT' });
}

for (const mode of ['normal', 'server-only']) test(`synthetic ${mode}: real handle drain, CJS stop, natural Worker0 and group closure`, async (t) => {
  const args = await fixture(t, mode);
  const before = await readFile(path.join(args.directory, 'server.txt'));
  const result = await setupWorker(args);
  const server = Buffer.from(`server:${fixtureVersion}:中文 café 😀\nserver`, 'utf8');
  assert.deepEqual(result.serverBundle, server);
  assert.equal(result.serverBundleSha256, digest(server));
  assert.equal(result.qualification, false);
  assert.equal(result.daemonVersion, fixtureVersion);
  assert.equal(result.settlement.workerExitCode, 0);
  assert.equal(result.settlement.processGroupClosed, true);
  assert.ok(result.settlement.setupWorkerThreadId > 0);
  assert.equal(result.settlement.helpers.length, 1);
  assert.equal(result.settlement.helpers[0].code, 0);
  assert.equal(result.settlement.helpers[0].signal, null);
  assert.deepEqual(await readFile(result.files.server), server);
  assert.deepEqual(await readFile(path.join(args.directory, 'server.txt')), before);
  const receipt = JSON.parse(await readFile(result.files.receipt, 'utf8'));
  assert.equal(receipt.qualification, false);
  assert.equal(receipt.serverBundleSha256, digest(server));
  assert.ok(!('serverBundle' in receipt));
  if (mode === 'server-only') {
    assert.equal(result.clientBundle, null); assert.equal(result.clientBundleSha256, null);
  } else {
    assert.deepEqual(result.clientBundle, Buffer.from('client Ω\n'));
    assert.equal(result.clientBundleSha256, digest(result.clientBundle));
  }
  await assert.rejects(setupWorker(args), /fresh expected output/);
});

test('synthetic compiler refusal drains but emits no expected files or false success', async (t) => {
  const args = await fixture(t, 'compile-error');
  await assert.rejects(setupWorker(args), /setup runner refused input/);
  await absent(args.outputDirectory);
});

test('synthetic retirement failure never becomes Worker/group success', async (t) => {
  const args = await fixture(t, 'stop-fails');
  await assert.rejects(setupWorker(args), /setup runner refused input/);
  await absent(args.outputDirectory);
});

test('synthetic timeout fails even when forced owned-group cleanup settles', async (t) => {
  const args = await fixture(t, 'hang');
  await assert.rejects(setupWorker({ ...args, timeoutMs: 250 }), /timed out/);
  await absent(args.outputDirectory);
});

for (const file of ['runtime/node', 'runtime/esbuild', 'compiler-code.mjs', 'package.json', 'node_modules/esbuild/lib/main.cjs'])
  test(`manifest substitution refused before use: ${file}`, async (t) => {
    const args = await fixture(t);
    // Do not modify the hardlinked CI runner Node; replace its directory entry.
    if (file === 'runtime/node') {
      await rm(path.join(args.nativeRoot, file));
      await writeFile(path.join(args.nativeRoot, file), 'substitute');
    } else await appendFile(path.join(args.nativeRoot, file), 'substitute');
    await assert.rejects(setupWorker(args), /manifest (size|digest) mismatch/);
    await absent(args.outputDirectory);
  });

test('extra retained code is refused rather than resolved from an unmeasured dependency', async (t) => {
  const args = await fixture(t);
  await writeFile(path.join(args.nativeRoot, 'unexpected.cjs'), 'module.exports = 1');
  await assert.rejects(setupWorker(args), /unexpected retained member/);
  await absent(args.outputDirectory);
});

test('expected output cannot pollute the hashed snapshot or retained compiler closure', async (t) => {
  const args = await fixture(t);
  for (const outputDirectory of [path.join(args.snapshotRoot, 'expected'), path.join(args.nativeRoot, 'expected')])
    await assert.rejects(setupWorker({ ...args, outputDirectory }), /outside source snapshot/);
});

test('directory/version are derived from canonical input and retained metadata only', async (t) => {
  const args = await fixture(t);
  await assert.rejects(setupWorker({ ...args, directory: args.dir }), /inside the supplied/);
  for (const timeoutMs of [0, 99, 300001, NaN, '1000'])
    await assert.rejects(setupWorker({ ...args, timeoutMs }));
});

test('actual retained BASE60a setup compiles checkout ade-yolo twice; expected bytes only', {
  skip: !process.env.SETUP_COMPILER_NATIVE_ROOT,
}, async (t) => {
  const nativeRoot = process.env.SETUP_COMPILER_NATIVE_ROOT;
  const checkout = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
  const directory = path.join(checkout, 'plugins/ade-yolo');
  const output = process.env.SETUP_COMPILER_OUTPUT_ROOT;
  assert.ok(output && path.isAbsolute(output));
  await mkdir(output, { recursive: true });
  const first = await setupWorker({ nativeRoot, snapshotRoot: checkout, directory,
    outputDirectory: path.join(output, 'first'), timeoutMs: 120_000 });
  const second = await setupWorker({ nativeRoot, snapshotRoot: checkout, directory,
    outputDirectory: path.join(output, 'second'), timeoutMs: 120_000 });
  assert.equal(first.qualification, false); assert.equal(second.qualification, false);
  assert.deepEqual(first.serverBundle, second.serverBundle);
  assert.deepEqual(first.clientBundle, second.clientBundle);
  assert.ok(first.serverBundle?.length > 0);
  assert.equal(first.serverBundleSha256, digest(first.serverBundle));
  assert.equal(first.serverBundleSha256, second.serverBundleSha256);
  assert.notEqual(first.settlement.setupProcessId, second.settlement.setupProcessId);
  assert.equal(first.settlement.workerExitCode, 0); assert.equal(second.settlement.workerExitCode, 0);
  assert.ok(first.settlement.helpers.length > 0 && second.settlement.helpers.length > 0);
  const metadata = JSON.parse(await readFile(path.join(nativeRoot, 'package.json'), 'utf8'));
  assert.equal(first.daemonVersion, metadata.version);
  assert.equal(first.settlement.processGroupClosed, true);
  assert.equal(second.settlement.processGroupClosed, true);
  t.diagnostic(JSON.stringify({ status: 'actual-setup-expected-bytes-only', qualification: false,
    serverBundleSha256: first.serverBundleSha256, clientBundleSha256: first.clientBundleSha256,
    version: first.daemonVersion, nodeSha256: first.inputSha256['runtime/node'],
    compilerSha256: first.inputSha256['compiler-code.mjs'], helperSha256: first.inputSha256['runtime/esbuild'] }));
});
