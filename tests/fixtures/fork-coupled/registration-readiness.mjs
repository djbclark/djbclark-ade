// Fixture scheduling DATA only. A candidate never authorizes execution, selects
// an endpoint, proves readiness or replaces the actual retained CLI checks.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { ChildProcess } from 'node:child_process';
import path from 'node:path';

const {open, lstat, readFile} = fs.promises;
const LIMIT = 65536;
const keys = new Set(['pid', 'startedAt', 'hostname', 'uid', 'listen',
  'serverId', 'desktopManaged', 'heartbeat', 'bootId']);
const sameFile = (a, b) => a.dev === b.dev && a.ino === b.ino;
const sameRead = (a, b) => sameFile(a, b) && a.size === b.size &&
  a.mode === b.mode && a.uid === b.uid && a.nlink === b.nlink &&
  a.mtimeNs === b.mtimeNs && a.ctimeNs === b.ctimeNs;
const nonempty = (value) => typeof value === 'string' && value.length > 0 && !value.includes('\0');

function parseRecord(bytes) {
  let row;
  try { row = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes)); }
  catch { throw new Error('Malformed nonempty daemon PID JSON'); }
  const valid = row && typeof row === 'object' && !Array.isArray(row) &&
    Object.keys(row).every((key) => keys.has(key)) &&
    Number.isSafeInteger(row.pid) && row.pid > 0 &&
    Number.isSafeInteger(row.uid) && row.uid >= 0 &&
    nonempty(row.startedAt) && nonempty(row.hostname) &&
    (row.listen === null || nonempty(row.listen)) &&
    (row.serverId === undefined || row.serverId === null || nonempty(row.serverId)) &&
    (row.desktopManaged === undefined || typeof row.desktopManaged === 'boolean') &&
    (row.heartbeat === undefined || row.heartbeat === true) &&
    (row.bootId === undefined || nonempty(row.bootId));
  if (!valid) throw new Error('Malformed daemon PID metadata shape');
  return row;
}

export function createRegistrationReadinessObserver(home, child, deadline) {
  assert.ok(child instanceof ChildProcess && Number.isSafeInteger(child.pid) && child.pid > 0,
    'Original spawned daemon handle required');
  assert.ok(Number.isFinite(deadline));
  const originalPid = child.pid;
  const originalUid = process.getuid();
  const file = path.join(home, 'paseo.pid');
  // This is the ORIGINAL registration-smoke config layout, never metadata input.
  const socket = path.join(path.dirname(home), 'daemon.sock');
  let failure, retired = false, incarnation = null, readyPair = null;
  const lose = () => { failure ??= new Error('Original daemon handle lost during readiness wait'); };
  const childError = (error) => { failure ??= error; };
  child.on('error', childError);
  for (const event of ['exit', 'close', 'disconnect']) child.on(event, lose);

  const check = (startup) => {
    if (failure) throw failure;
    if (retired || child.pid !== originalPid || !child.connected ||
        child.exitCode !== null || child.signalCode !== null) {
      throw new Error('Original daemon handle unavailable');
    }
    if (startup) assert.ok(performance.now() < deadline, 'Original startup deadline exceeded');
  };
  const pending = (reason) => {
    if (readyPair) throw new Error('Previously ready daemon metadata became unavailable');
    return Object.freeze({ready: false, reason});
  };
  const safeFile = (record) => assert.ok(record.isFile() && record.nlink === 1n &&
    record.uid === BigInt(originalUid) && (record.mode & 0o7077n) === 0n &&
    record.size <= BigInt(LIMIT), 'Unsafe daemon PID metadata file');

  async function readObservation(startup) {
    check(startup);
    let fd;
    try { fd = await open(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK); }
    catch (error) {
      if (error.code !== 'ENOENT' || incarnation) throw error;
      check(startup);
      return pending('absent');
    }
    let result, primary;
    try {
      check(startup);
      const before = await fd.stat({bigint: true});
      check(startup);
      safeFile(before);
      if (incarnation && !sameFile(before, incarnation.file)) throw new Error('Daemon PID metadata file replaced');
      const buffer = Buffer.alloc(LIMIT + 1);
      let total = 0;
      while (total < buffer.length) {
        const read = await fd.read(buffer, total, buffer.length - total, total);
        check(startup);
        total += read.bytesRead;
        if (!read.bytesRead) break;
      }
      assert.ok(total <= LIMIT, 'Daemon PID metadata exceeded bound');
      const after = await fd.stat({bigint: true});
      check(startup);
      const current = await lstat(file, {bigint: true});
      check(startup);
      safeFile(after);
      safeFile(current);
      if (incarnation && !sameFile(current, incarnation.file)) throw new Error('Daemon PID metadata path replaced');
      if (!sameRead(before, after) || !sameRead(after, current)) result = pending('changing');
      else {
        assert.equal(total, Number(after.size), 'Incomplete stable daemon PID read');
        result = total ? {bytes: buffer.subarray(0, total), file: after} : pending('empty');
      }
    } catch (error) { primary = error; }
    finally {
      try { await fd.close(); }
      catch (error) {
        primary = primary ? new AggregateError([primary, error], 'PID observation and close failed',
          {cause: error}) : error;
      }
    }
    if (primary) throw primary;
    check(startup);
    if (!result.bytes) return result;
    const row = parseRecord(result.bytes);
    assert.equal(row.pid, originalPid, 'Foreign daemon PID metadata');
    assert.equal(row.uid, originalUid, 'Foreign daemon UID metadata');
    if (row.bootId !== undefined) {
      const boot = await readFile('/proc/sys/kernel/random/boot_id', 'utf8');
      check(startup);
      assert.ok(boot.length <= 64 && row.bootId === boot.trim(), 'Foreign daemon boot metadata');
    }
    const tuple = {pid: row.pid, uid: row.uid, startedAt: row.startedAt,
      hostname: row.hostname, bootId: row.bootId};
    if (incarnation) {
      assert.ok(Object.keys(tuple).every((key) => tuple[key] === incarnation.tuple[key]),
        'Daemon PID metadata incarnation changed');
    } else incarnation = {tuple, file: result.file};
    if (row.listen === null) {
      assert.ok(row.serverId === undefined || row.serverId === null, 'Incomplete daemon ready pair');
      return pending('unpublished');
    }
    assert.ok(nonempty(row.serverId) && row.listen === socket, 'Unexpected daemon ready endpoint or ID');
    const pair = {listen: row.listen, serverId: row.serverId};
    if (readyPair) assert.ok(pair.listen === readyPair.listen && pair.serverId === readyPair.serverId,
      'Daemon ready pair changed');
    readyPair = pair;
    return Object.freeze({ready: true, reason: 'published'});
  }

  async function observe(startup) {
    try { return await readObservation(startup); }
    catch (error) {
      if (!failure) failure = error;
      else if (error !== failure) failure = new AggregateError([failure, error],
        'Original daemon and metadata observation failed', {cause: error});
      throw failure;
    }
  }
  return Object.freeze({
    poll: () => observe(true),
    async assertReady() {
      const result = await observe(false);
      if (!result.ready) {
        failure ??= new Error('Original daemon ready metadata unavailable before CLI');
        throw failure;
      }
    },
    dispose() {
      retired = true;
      child.removeListener('error', childError);
      for (const event of ['exit', 'close', 'disconnect']) child.removeListener(event, lose);
    },
  });
}
