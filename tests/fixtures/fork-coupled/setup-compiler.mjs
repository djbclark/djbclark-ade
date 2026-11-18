// Expected bytes from ordinary retained compiler setup ONLY. No native owner,
// compiler.runs receipt, plugin evaluation, qualification or activation authority.
import assert from 'node:assert/strict';
import childProcess, { fork } from 'node:child_process';
import { createHash } from 'node:crypto';
import { constants } from 'node:fs';
import filesystem from 'node:fs/promises';
import { lstat, mkdir, readdir, realpath, writeFile } from 'node:fs/promises';
import { performance } from 'node:perf_hooks';
import { createRequire, syncBuiltinESMExports } from 'node:module';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { isMainThread, MessageChannel, parentPort, threadId, Worker, workerData } from 'node:worker_threads';
import { ownDisposableGroup } from './owned-cleanup.mjs';

const SELF = fileURLToPath(import.meta.url);
const MAX_BUNDLE = 16 * 1024 * 1024;
const MAX_DIAGNOSTIC = 4096;
const CHILD_ROLE = '__setup-compiler-child-v1';
const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
const inside = (root, file) => file === root || file.startsWith(root + path.sep);

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  // A Worker may fail before the coordinator reaches this particular wait.
  promise.catch(() => {});
  return { promise, resolve, reject };
}

async function canonicalDirectory(value) {
  assert.equal(typeof value, 'string');
  assert.ok(path.isAbsolute(value), 'absolute setup directory required');
  const resolved = path.resolve(value);
  assert.equal(await realpath(resolved), resolved, 'canonical setup directory required');
  assert.ok((await lstat(resolved)).isDirectory(), 'setup directory missing');
  return resolved;
}

async function regular(file, limit = 256 * 1024 * 1024) {
  const handle = await filesystem.open(file, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const before = await handle.stat({ bigint: true });
    assert.ok(before.isFile() && before.size <= BigInt(limit), 'bounded regular retained input required');
    const bytes = await handle.readFile();
    const after = await handle.stat({ bigint: true });
    for (const key of ['dev', 'ino', 'mode', 'size', 'mtimeNs', 'ctimeNs'])
      assert.equal(after[key], before[key], 'retained input changed while reading');
    assert.equal(BigInt(bytes.length), before.size);
    return bytes;
  } finally { await handle.close(); }
}

async function inputs(root) {
  // Acquisition authenticates this external manifest. Setup independently binds
  // every retained byte before use, without enforcing unrelated host libraries.
  const manifestBytes = await regular(root + '.manifest.json', 16 * 1024 * 1024);
  const manifest = JSON.parse(manifestBytes.toString('utf8'));
  assert.equal(manifest.schemaVersion, 2);
  assert.equal(manifest.profile, 'enclosing-daemon-v2');
  assert.ok(Array.isArray(manifest.files) && manifest.files.length > 0 && manifest.files.length <= 10000);
  const names = ['runtime/node', 'runtime/esbuild', 'compiler-code.mjs', 'package.json', 'node_modules/esbuild/package.json'];
  const selected = new Map(), expected = new Set();
  let total = 0;
  for (const row of manifest.files) {
    assert.ok(typeof row.path === 'string' && row.path.length > 0 && !row.path.includes('\\') &&
      !path.isAbsolute(row.path) && row.path.split('/').every((part) => part && part !== '.' && part !== '..'));
    assert.ok(!expected.has(row.path), 'duplicate retained manifest member');
    expected.add(row.path);
    assert.ok(Number.isSafeInteger(row.size) && row.size >= 0 && /^[a-f0-9]{64}$/.test(row.sha256));
    total += row.size; assert.ok(total <= 512 * 1024 * 1024);
    const bytes = await regular(path.join(root, row.path));
    assert.equal(bytes.length, row.size, 'retained manifest size mismatch');
    assert.equal(sha256(bytes), row.sha256, 'retained manifest digest mismatch');
    assert.equal((await lstat(path.join(root, row.path))).mode & 0o777, row.mode);
    if (names.includes(row.path)) selected.set(row.path, bytes);
  }
  let count = 0;
  async function inventory(directory) {
    for (const name of await readdir(directory)) {
      assert.ok(++count <= 20000, 'retained inventory exceeds setup bound');
      const file = path.join(directory, name), stat = await lstat(file);
      if (stat.isDirectory()) await inventory(file);
      else assert.ok(stat.isFile() && expected.has(path.relative(root, file)), 'unexpected retained member');
    }
  }
  await inventory(root);
  assert.ok(names.every((name) => selected.has(name)), 'retained compiler closure missing');
  const metadata = JSON.parse(selected.get('package.json').toString('utf8'));
  const esbuild = JSON.parse(selected.get('node_modules/esbuild/package.json').toString('utf8'));
  assert.ok(typeof metadata.version === 'string' && metadata.version.length > 0 && metadata.version.length <= 128,
    'actual retained daemon version missing');
  assert.ok(typeof esbuild.version === 'string' && /^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$/.test(esbuild.version),
    'actual retained esbuild metadata missing');
  return { version: metadata.version, esbuildVersion: esbuild.version,
    manifestSha256: sha256(manifestBytes),
    sha256: Object.fromEntries(names.map((name) => [name, sha256(selected.get(name))])) };
}

function bundle(value) {
  assert.ok(value === null || typeof value === 'string', 'unexpected compiler bundle');
  if (value === null) return null;
  assert.ok(Buffer.byteLength(value, 'utf8') <= MAX_BUNDLE, 'compiler bundle exceeds setup bound');
  return Buffer.from(value, 'utf8');
}

// This observes setup-owned handles only. It does not install/import the native
// private compiler owner or certify its settlement protocol.
async function setupThread() {
  const { nativeRoot: root, control } = workerData;
  const require = createRequire(pathToFileURL(path.join(root, 'compiler-code.mjs')));
  const metadata = JSON.parse((await regular(path.join(root, 'node_modules/esbuild/package.json'), 65536)).toString('utf8'));
  const executable = path.join(root, 'runtime/esbuild');
  const originalSpawn = childProcess.spawn;
  const children = [];
  let sealed = false, failed = false, retiring = false, activeStop = null;
  let helperFailure;
  childProcess.spawn = (command, args, options) => {
    if (sealed || command !== executable || !Array.isArray(args) ||
        args[0] !== `--service=${metadata.version}` || args.length > 2 ||
        (args.length === 2 && args[1] !== '--ping')) {
      failed = true;
      throw new Error('unexpected setup compiler helper');
    }
    const child = originalSpawn(command, args, { ...options, detached: false,
      cwd: root, env: { PATH: '/usr/bin:/bin' } });
    const record = { child, closed: deferred(), observation: null, exited: false, stopKill: null };
    children.push(record); // Keep the real ChildProcess, not a PID-only proxy.
    const originalKill = child.kill;
    child.kill = function (...signals) {
      // The retained CJS stopService synchronously calls THIS exact handle's
      // default kill(). A retiring flag or a later signal alone is not provenance.
      const token = activeStop;
      const eligible = token !== null && this === child && signals.length === 0 &&
        !record.exited && child.exitCode === null && child.signalCode === null;
      const accepted = Reflect.apply(originalKill, this, signals);
      if (eligible && accepted === true) record.stopKill = token;
      return accepted; // Preserve the actual ChildProcess method/event semantics.
    };
    function acceptOutcome(code, signal) {
      return (code === 0 && signal === null) ||
        (code === null && signal === 'SIGTERM' && record.stopKill !== null);
    }
    function observeFailure(code, signal) {
      if (!acceptOutcome(code, signal)) {
        failed = true;
        helperFailure ??= `setup helper exit code=${code} signal=${signal}`;
      }
    }
    child.once('error', () => { failed = true; helperFailure ??= 'setup helper process error'; });
    child.once('exit', (code, signal) => {
      record.exited = true;
      // Latch premature failure even if stdio close arrives during stop later.
      observeFailure(code, signal);
    });
    child.once('close', (code, signal) => {
      record.observation = { pid: child.pid, code, signal };
      observeFailure(code, signal);
      // Resolve only on actual close, including failed outcomes; all handles
      // remain awaited before the combined failure can be reported as retired.
      record.closed.resolve(record.observation);
    });
    return child;
  };
  syncBuiltinESMExports();
  const compiler = await import(pathToFileURL(path.join(root, 'compiler-code.mjs')).href);
  assert.equal(typeof compiler.retireQualifiedCompilerTasks, 'function', 'actual task retirement export missing');
  control.on('message', (message) => {
    if (message?.type !== 'retire' || retiring) return;
    retiring = true;
    void (async () => {
      // Retirement closes real compiler task ingress synchronously, then drains
      // every admitted task (including a failed task's still-running sibling).
      await compiler.retireQualifiedCompilerTasks();
      sealed = true;
      // compiler-esbuild.ts also uses createRequire(import.meta.url)("esbuild").
      // Producer externalizes that CJS package: this is its SAME cached namespace.
      const esbuild = require('esbuild');
      assert.equal(typeof esbuild.stop, 'function');
      const stop = esbuild.stop;
      const token = Object.freeze({ stop, namespace: esbuild });
      let stopFailure;
      activeStop = token;
      try {
        // No await inside this window: only the exact retained stop invocation
        // may account for a synchronous default helper.kill() that returned true.
        const stopped = Reflect.apply(stop, esbuild, []);
        activeStop = null;
        await stopped;
      } catch (error) { stopFailure = error; }
      finally { activeStop = null; }
      await Promise.all(children.map((record) => record.closed.promise));
      if (stopFailure) throw stopFailure;
      assert.equal(failed, false, helperFailure ?? 'setup helper failure is not settlement');
      assert.ok(children.every((record) => record.observation !== null));
      control.postMessage({ type: 'retired', threadId,
        helpers: children.map((record) => record.observation) });
      parentPort.close();
      control.close(); // Natural Worker exit, never terminate()/process.exit().
    })().catch((error) => {
      control.postMessage({ type: 'retirement-error', message: String(error.message).slice(0, MAX_DIAGNOSTIC) });
      parentPort.close(); control.close();
    });
  });
  control.postMessage({ type: 'ready', threadId });
}

async function setupChild(request) {
  const { nativeRoot: root, directory, version } = request;
  assert.equal(await realpath(process.execPath), path.join(root, 'runtime/node'), 'retained runtime required');
  assert.equal(process.env.ESBUILD_BINARY_PATH, path.join(root, 'runtime/esbuild'));
  const channel = new MessageChannel();
  const ready = deferred(), reply = deferred(), retired = deferred(), exited = deferred();
  let count = 0, observedThread;
  const worker = new Worker(new URL(import.meta.url), {
    workerData: { role: 'setup-compiler-worker-v1', nativeRoot: root, control: channel.port2 },
    transferList: [channel.port2], execArgv: [],
  });
  worker.once('error', (error) => {
    ready.reject(error); reply.reject(error); retired.reject(error); exited.reject(error);
  });
  worker.once('exit', (code) => {
    exited.resolve(code);
    if (code !== 0) {
      const error = new Error(`setup Worker exited ${code}`);
      ready.reject(error); reply.reject(error); retired.reject(error);
    }
  });
  worker.on('message', (message) => {
    if (message?.kind === 'log') return;
    if (++count !== 1) { reply.reject(new Error('ambiguous compiler reply')); return; }
    if (message?.kind === 'result') reply.resolve(message.value);
    else if (message?.kind === 'error') reply.reject(new Error('directory compiler refused setup input: ' + String(message.error?.message ?? 'unknown').slice(0, 1024)));
    else reply.reject(new Error('unexpected directory compiler reply'));
  });
  channel.port1.on('message', (message) => {
    if (message?.type === 'ready') { observedThread = message.threadId; ready.resolve(); }
    else if (message?.type === 'retired') retired.resolve(message);
    else retired.reject(new Error('actual compiler retirement failed: ' + String(message?.message ?? 'unknown').slice(0, 1024)));
  });
  await ready.promise;
  assert.ok(Number.isInteger(observedThread) && observedThread > 0);
  worker.postMessage({ kind: 'directory', directory, version });
  let value, refusal;
  try { value = await reply.promise; } catch (error) { refusal = error; }
  channel.port1.postMessage({ type: 'retire' });
  const [settlement, code] = await Promise.all([retired.promise, exited.promise]);
  channel.port1.close();
  assert.equal(code, 0, 'setup Worker did not exit normally');
  assert.equal(settlement.threadId, observedThread);
  if (refusal) throw refusal;
  assert.equal(count, 1, 'ambiguous compiler reply');
  assert.ok(value && typeof value === 'object' && value.manifest && typeof value.manifest === 'object');
  const server = bundle(value.serverBundle), client = bundle(value.clientBundle);
  assert.ok(server !== null || client !== null, 'compiler returned no bundles');
  return { server, client, manifest: value.manifest,
    settlement: { workerExitCode: code, setupWorkerThreadId: observedThread, helpers: settlement.helpers } };
}

/** Setup expected bytes only. All paths are explicit trusted in-process inputs;
 * none are a policy override, native owner claim, compiler measurement or grant.
 * timeoutMs bounds process admission through final inventory and byte verification.
 * Initial input validation precedes this phase. Publication I/O starts only after
 * the final synchronous latch/deadline guard; it is outside that timeout budget. */
export async function setupWorker({ nativeRoot, snapshotRoot, directory, outputDirectory, timeoutMs = 60_000 }) {
  assert.equal(process.platform, 'linux', 'Linux-only disposable setup');
  assert.ok(Number.isSafeInteger(timeoutMs) && timeoutMs >= 100 && timeoutMs <= 300_000);
  const root = await canonicalDirectory(nativeRoot);
  const snapshot = await canonicalDirectory(snapshotRoot);
  const source = await canonicalDirectory(directory);
  assert.ok(inside(snapshot, source), 'plugin must be inside the supplied immutable snapshot');
  assert.ok(typeof outputDirectory === 'string' && path.isAbsolute(outputDirectory));
  const output = path.resolve(outputDirectory);
  assert.equal(path.join(await canonicalDirectory(path.dirname(output)), path.basename(output)), output);
  assert.ok(!inside(snapshot, output) && !inside(root, output), 'expected outputs must be outside source snapshot and retained root');
  try { await lstat(output); throw new Error('fresh expected output directory required'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  const before = await inputs(root);
  const verificationDeadline = performance.now() + timeoutMs;
  const child = fork(SELF, [CHILD_ROLE], {
    execPath: path.join(root, 'runtime/node'), execArgv: [], detached: true,
    stdio: ['ignore', 'pipe', 'pipe', 'ipc'], serialization: 'json',
    env: { PATH: '/usr/bin:/bin', ESBUILD_BINARY_PATH: path.join(root, 'runtime/esbuild') },
  });
  const result = deferred(), failure = deferred();
  let diagnosticBytes = 0, messages = 0, timer, failed;
  const fail = (error) => { failed ??= error; result.reject(error); failure.reject(error); };
  child.once('error', fail);
  child.once('close', (code) => { if (messages === 0) fail(new Error(`setup runner closed without result (${code})`)); });
  for (const stream of [child.stdout, child.stderr]) stream.on('data', (chunk) => {
    diagnosticBytes += chunk.length;
    if (diagnosticBytes > MAX_DIAGNOSTIC) fail(new Error('setup compiler diagnostics overflow'));
  });
  child.on('message', (message) => {
    if (++messages !== 1 || message?.type !== 'setup-result') { fail(new Error('setup runner refused input: ' + String(message?.reason ?? 'unexpected reply').slice(0, 1024))); return; }
    result.resolve(message.value);
  });
  // Error without an acquired process has no group to dispose.
  if (!Number.isSafeInteger(child.pid)) {
    await result.promise;
    throw new Error('setup runner has no process');
  }
  const owner = ownDisposableGroup(child, { gracefulMs: 1500, forcedMs: 5000 });
  function assertVerifiedPhaseCurrent() {
    if (failed) throw failed;
    if (performance.now() >= verificationDeadline) {
      const error = new Error('setup compiler timed out; verification deadline exceeded');
      fail(error);
      throw error;
    }
  }
  timer = setTimeout(() => fail(new Error('setup compiler timed out; settlement unknown')),
    Math.max(0, verificationDeadline - performance.now()));
  child.send({ nativeRoot: root, directory: source, version: before.version });
  let observed;
  try {
    observed = await Promise.race([
      Promise.all([result.promise, owner.closed]).then(([value, exit]) => {
        assert.equal(exit.code, 0); assert.equal(exit.signal, null); return value;
      }),
      failure.promise,
    ]);
    await owner.dispose(); // Already closed: validates no surviving group members; no signal on success.
    assertVerifiedPhaseCurrent();
    assert.deepEqual(await inputs(root), before, 'retained compiler inputs changed');
    assertVerifiedPhaseCurrent(); // A timeout during the actual inventory await wins.
    function decoded(value) {
      if (value === null) return null;
      assert.ok(typeof value === 'string' && value.length <= Math.ceil(MAX_BUNDLE / 3) * 4);
      const bytes = Buffer.from(value, 'base64');
      assert.equal(bytes.toString('base64'), value, 'noncanonical setup byte transport');
      return bytes;
    }
    const server = decoded(observed.server), client = decoded(observed.client);
    for (const bytes of [server, client]) if (bytes !== null) assert.ok(bytes.length <= MAX_BUNDLE);
    const receipt = { status: 'setup-expected-bytes', qualification: false,
      nativeRoot: root, snapshotRoot: snapshot, directory: source, daemonVersion: before.version,
      inputSha256: before.sha256, inputManifestSha256: before.manifestSha256, manifest: observed.manifest,
      serverBundleSha256: server === null ? null : sha256(server),
      clientBundleSha256: client === null ? null : sha256(client),
      serverBytes: server?.length ?? 0, clientBytes: client?.length ?? 0,
      settlement: { ...observed.settlement, setupProcessId: child.pid, processGroupClosed: true },
      files: { server: server === null ? null : path.join(output, 'server.js'),
        client: client === null ? null : path.join(output, 'client.js'), receipt: path.join(output, 'setup.json') } };
    // Explicit verification/publication cutoff. A delayed timer callback cannot
    // evade this absolute monotonic check, and any already observed failure wins.
    assertVerifiedPhaseCurrent();
    clearTimeout(timer);
    await mkdir(output, { mode: 0o700 });
    if (server !== null) await writeFile(receipt.files.server, server, { flag: 'wx', mode: 0o600 });
    if (client !== null) await writeFile(receipt.files.client, client, { flag: 'wx', mode: 0o600 });
    await writeFile(receipt.files.receipt, JSON.stringify(receipt, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
    return { ...receipt, serverBundle: server, clientBundle: client };
  } catch (original) {
    // Killing this disposable group is failure cleanup only, never a quiet proof.
    try { await owner.dispose(); } catch (cleanup) { original.cleanup = cleanup.message; }
    throw original;
  } finally { clearTimeout(timer); }
}

if (!isMainThread && workerData?.role === 'setup-compiler-worker-v1') {
  await setupThread();
} else if (process.argv[1] && path.resolve(process.argv[1]) === SELF) {
  if (process.argv[2] === CHILD_ROLE) {
    process.once('message', (request) => {
      void setupChild(request).then((value) => {
        process.send({ type: 'setup-result', value: { ...value,
          server: value.server?.toString('base64') ?? null, client: value.client?.toString('base64') ?? null } }, () => process.disconnect());
      }).catch((error) => {
        process.exitCode = 1;
        if (process.connected) process.send({ type: 'setup-failed', reason: String(error.message).slice(0, 1024) }, () => process.disconnect());
      });
    });
  } else {
    try {
      assert.equal(process.argv.length, 6, 'nativeRoot snapshotRoot directory outputDirectory required');
      const [nativeRoot, snapshotRoot, directory, outputDirectory] = process.argv.slice(2);
      const { serverBundle, clientBundle, ...receipt } = await setupWorker({ nativeRoot, snapshotRoot, directory, outputDirectory });
      process.stdout.write(JSON.stringify(receipt) + '\n');
    } catch (error) {
      process.stderr.write(JSON.stringify({ status: 'setup-failed', qualification: false, reason: error.message }) + '\n');
      process.exitCode = 1;
    }
  }
}
