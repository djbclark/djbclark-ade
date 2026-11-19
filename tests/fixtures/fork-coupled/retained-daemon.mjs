import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { constants } from 'node:fs';
import { lstat, open, realpath } from 'node:fs/promises';
import { createHash, randomBytes } from 'node:crypto';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { ownDisposableGroup } from './owned-cleanup.mjs';

const MAX_FILE = 512 * 1024 * 1024;
const MAX_REPLY = 16 * 1024 * 1024;
const hex = /^[a-f0-9]{64}$/;
export const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');

function stable(a, b) {
  return ['dev', 'ino', 'uid', 'gid', 'mode', 'size', 'mtimeNs', 'ctimeNs']
    .every((key) => a[key] === b[key]);
}

export async function readRegular(file, limit = MAX_FILE) {
  const descriptor = await open(file, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const before = await descriptor.stat({ bigint: true });
    assert.ok(before.isFile() && before.nlink === 1n && before.size <= BigInt(limit), 'regular bounded leaf required');
    const chunks = [];
    let count = 0;
    for (;;) {
      const buffer = Buffer.alloc(Math.min(65536, limit + 1 - count));
      const { bytesRead } = await descriptor.read(buffer, 0, buffer.length, null);
      if (!bytesRead) break;
      count += bytesRead;
      assert.ok(count <= limit && count <= Number(before.size), 'leaf grew during read');
      chunks.push(buffer.subarray(0, bytesRead));
    }
    const after = await descriptor.stat({ bigint: true });
    const named = await lstat(file, { bigint: true });
    assert.ok(stable(before, after) && stable(after, named), 'leaf replaced during read');
    assert.equal(count, Number(before.size), 'leaf truncated during read');
    return Buffer.concat(chunks);
  } finally {
    await descriptor.close();
  }
}

async function rootOwned(file, directory) {
  const metadata = await lstat(file);
  assert.ok(directory ? metadata.isDirectory() : metadata.isFile(), 'unexpected retained node');
  assert.equal(metadata.uid, 0, 'retained closure must be root owned');
  assert.equal(metadata.mode & (directory ? 0o022 : 0o222), 0, 'retained closure is writable');
  assert.ok(!metadata.isSymbolicLink(), 'retained closure cannot contain symlinks');
  return metadata;
}

export function validateDaemonObservation(raw, nonce, childPid, parentPid, version = 1) {
  assert.ok(version === 1 || version === 2, 'explicit supported measurement version required');
  assert.equal(raw.type, 'qualified.measurement.response');
  assert.equal(raw.nonce, nonce);
  assert.ok(Buffer.byteLength(JSON.stringify(raw)) <= MAX_REPLY);
  assert.equal(raw.schemaVersion, version, 'measurement version must match the actual request');
  assert.equal(raw.parentPid, parentPid, 'observation must bind the actual parent');
  assert.ok(raw.status === 'hold' || raw.status === 'observed');
  if (raw.status === 'observed' || raw.daemon !== null) {
    assert.equal(raw.daemon?.pid, childPid, 'observation must identify the owned child');
  }
  return raw;
}

// This independent pre-exec check protects importing the retained launcher itself.
// Its successful result is never an execution capability; the real producer still
// checks protected enrollment and actual executing process/module ownership.
export async function validateRetainedPayload(root, expectedManifest) {
  assert.equal(process.platform, 'linux', 'finite Linux acceptance only');
  assert.notEqual(process.getuid(), 0, 'runtime account must be unprivileged');
  assert.ok(path.isAbsolute(root) && root !== '/' && hex.test(expectedManifest));
  assert.equal(await realpath(root), root, 'canonical retained root required');
  for (let current = root;; current = path.dirname(current)) {
    await rootOwned(current, true);
    if (current === '/') break;
  }
  await rootOwned(`${root}.manifest.json`, false);
  const bytes = await readRegular(`${root}.manifest.json`, 4 * 1024 * 1024);
  assert.equal(sha256(bytes), expectedManifest, 'protected final manifest mismatch');
  const manifest = JSON.parse(bytes);
  assert.equal(manifest.schemaVersion, 2);
  assert.equal(manifest.profile, 'enclosing-daemon-v2');
  assert.ok(Array.isArray(manifest.files) && manifest.files.length);
  const names = new Set();
  for (const member of manifest.files) {
    assert.ok(typeof member.path === 'string' && member.path && !path.isAbsolute(member.path));
    assert.ok(!member.path.split('/').some((part) => !part || part === '.' || part === '..'));
    assert.ok(!names.has(member.path) && hex.test(member.sha256));
    names.add(member.path);
    const file = path.join(root, member.path);
    for (let parent = path.dirname(file); parent !== root; parent = path.dirname(parent)) {
      await rootOwned(parent, true);
    }
    const metadata = await rootOwned(file, false);
    assert.equal(metadata.size, member.size);
    assert.equal(metadata.mode & 0o777, member.mode & 0o777);
    assert.equal(sha256(await readRegular(file)), member.sha256, 'retained member integrity mismatch');
  }
  for (const name of ['runtime/node', 'role.cjs', 'daemon-launcher.mjs', 'daemon.mjs', 'compiler-code.mjs']) {
    assert.ok(names.has(name), 'finite distribution entry absent');
  }
  assert.equal(manifest.systemClosure?.schemaVersion, 1, 'retained system closure required; old inputs cannot launch');
  assert.equal(manifest.systemClosure.profile, 'linux-retained-system-closure-v1');
  assert.equal(manifest.systemClosure.loaderResolution?.policy, 'glibc-pinned-cache-existing-layout-v1');
  assert.ok(Array.isArray(manifest.externalLibraries) && manifest.externalLibraries.length > 0 &&
    manifest.externalLibraries.length <= 128);
  assert.equal(manifest.systemClosure?.schemaVersion, 1, 'retained system closure required');
  assert.equal(manifest.systemClosure.profile, 'linux-retained-system-closure-v1');
  for (const member of manifest.externalLibraries) {
    assert.ok(typeof member.path === 'string' && path.isAbsolute(member.path));
    assert.equal(member.retainedPath, `system-closure/elf/${member.path.slice(1)}`);
    assert.ok(member.mode === 0o444 || member.mode === 0o555);
    const retained = manifest.files.find((row) => row.path === member.retainedPath);
    assert.ok(retained && retained.mode === member.mode && retained.size === member.size &&
      retained.sha256 === member.sha256, 'external payload must match the retained inventory');
  }
  assert.ok(names.has('system-closure/namespace-bootstrap.py'), 'packaged namespace bootstrap absent');
  return manifest;
}

// Call this only INSIDE the private namespace. Host preparation checks retained
// payload bytes independently; the host libraries are allowed to differ.
export async function validateRetainedDistribution(root, expectedManifest) {
  const manifest = await validateRetainedPayload(root, expectedManifest);
  const cache = manifest.systemClosure.loaderResolution.cache;
  assert.equal(cache.path, '/etc/ld.so.cache');
  assert.equal(cache.retainedPath, 'system-closure/loader/ld.so.cache');
  for (const member of [...manifest.externalLibraries, cache]) {
    assert.ok(path.isAbsolute(member.path) && hex.test(member.sha256));
    assert.equal(await realpath(member.path), member.path, 'canonical system library required');
    for (let current = path.dirname(member.path);; current = path.dirname(current)) {
      await rootOwned(current, true);
      if (current === '/') break;
    }
    const metadata = await lstat(member.path);
    assert.ok(metadata.isFile() && metadata.uid === 0 && (metadata.mode & 0o222) === 0);
    const retained = await lstat(path.join(root, member.retainedPath));
    assert.ok(metadata.dev === retained.dev && metadata.ino === retained.ino,
      'runtime external target must use the actual retained backing inode');
    assert.equal(metadata.size, member.size, `external library size mismatch: ${member.path}`);
    assert.equal(metadata.mode & 0o777, member.mode);
    assert.equal(sha256(await readRegular(member.path)), member.sha256,
      `external library bytes mismatch: ${member.path}`);
  }
  return manifest;
}

export async function launchObservedDaemon(root, home, expectedManifest, measurementVersion = 1, diagnostics = null) {
  assert.ok(measurementVersion === 1 || measurementVersion === 2);
  diagnostics?.record('distribution-validation-start');
  await validateRetainedDistribution(root, expectedManifest);
  diagnostics?.record('distribution-validation-end');
  const launcher = await import(pathToFileURL(path.join(root, 'daemon-launcher.mjs')).href);
  diagnostics?.record('qualified-invocation-start');
  const invocation = await launcher.createQualifiedDaemonInvocation(root, home);
  diagnostics?.record('qualified-invocation-end');
  assert.equal(invocation.command, path.join(root, 'runtime/node'));
  assert.deepEqual(invocation.args, [path.join(root, 'role.cjs')]);
  assert.equal(invocation.closure.runtimeClosureSha256, expectedManifest);
  const child = spawn(invocation.command, invocation.args, {
    env: invocation.env, stdio: ['ignore', 'pipe', 'pipe', 'ipc'], detached: true,
  });
  let childError = null;
  child.on('error', (error) => { childError = error; diagnostics?.record('daemon-error', {name: error.name, code: error.code}); });
  diagnostics?.record('daemon-spawned', {pid: child.pid});
  child.once('exit', (code, signal) => diagnostics?.record('daemon-exit', {code, signal}));
  child.once('close', (code, signal) => diagnostics?.record('daemon-close', {code, signal}));
  const owner = ownDisposableGroup(child);
  const dispose = async () => {
    diagnostics?.record('daemon-disposal-start', {exitCode: child.exitCode, signalCode: child.signalCode});
    try {
      const result = await owner.dispose();
      diagnostics?.record('daemon-disposal-end', result);
      return result;
    } catch (error) {
      diagnostics?.record('daemon-disposal-failed', {name: error.name, message: error.message,
        exitCode: child.exitCode, signalCode: child.signalCode});
      throw error;
    }
  };
  let outputBytes = 0;
  let overflow = false;
  let outputTail = '';
  for (const [name, stream] of [['stdout', child.stdout], ['stderr', child.stderr]]) {
    stream.on('data', (chunk) => {
      diagnostics?.capture(name, chunk);
      outputBytes += chunk.length;
      if (outputBytes > MAX_REPLY) overflow = true;
      outputTail = (outputTail + chunk.toString('utf8')).slice(-8192);
    });
  }
  const observation = async () => {
    assert.ok(child.connected && child.exitCode === null && child.signalCode === null && !childError);
    assert.ok(!overflow, 'daemon output exceeded bound');
    const nonce = randomBytes(32).toString('hex');
    const reply = await new Promise((resolve, reject) => {
      const finish = (error, value) => {
        clearTimeout(timer);
        child.off('message', receive);
        child.off('close', lost);
        error ? reject(error) : resolve(value);
      };
      const lost = () => finish(new Error('owned daemon exited before observation'));
      const receive = (raw) => {
        if (raw?.type !== 'qualified.measurement.response' || raw.nonce !== nonce) return;
        try {
          finish(null, validateDaemonObservation(raw, nonce, child.pid, process.pid, measurementVersion));
        } catch (error) { finish(error); }
      };
      const timer = setTimeout(() => finish(new Error('owned observation timed out')), 30_000);
      child.on('message', receive);
      child.once('close', lost);
      child.send({ type: 'qualified.measurement.request', schemaVersion: measurementVersion, nonce }, (error) => {
        if (error) finish(error);
      });
    });
    assert.ok(!overflow && !childError && child.exitCode === null && child.connected);
    return reply;
  };
  return Object.freeze({ child, observation, dispose, diagnostics: () => outputTail });
}
