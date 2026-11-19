import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { createRegistrationDiagnostics, redactDiagnosticText } from './registration-diagnostics.mjs';

test('retains early output, split secrets, UTF-8 and actual teardown chronology beyond the old tail', async () => {
  const home = await mkdtemp(path.join(tmpdir(), 'registration-evidence-'));
  try {
    const diagnostic = await createRegistrationDiagnostics(home);
    diagnostic.capture('stdout', Buffer.from('FIRST PHASE\n' + 'x'.repeat(9000)));
    const bytes = Buffer.from('\nBearer abcdefghijklmnop\n{"token":"private-value","message":"UTF-8 café"}\n');
    for (const byte of bytes) diagnostic.capture('stderr', Buffer.from([byte]));
    diagnostic.record('cli-end', {ordinal: 1, code: 1, stderr: 'authorization: Bearer private-cli-token'});
    diagnostic.record('cli-failed', {ordinal: 2, name: 'AggregateError', message: 'CLI and cleanup failed',
      stderr: 'partial startup marker secret=private-failed-cli-token',
      stderrBytes: 57, stderrTruncated: false});
    diagnostic.record('daemon-disposal-start');
    diagnostic.record('daemon-exit', {code: 0, signal: null});
    diagnostic.record('daemon-close', {code: 0, signal: null});
    await diagnostic.finish();
    await diagnostic.finish();
    const directory = path.join(home, 'registration-diagnostics');
    const stdout = await readFile(path.join(directory, 'daemon.stdout.log'), 'utf8');
    const stderr = await readFile(path.join(directory, 'daemon.stderr.log'), 'utf8');
    const events = (await readFile(path.join(directory, 'registration-events.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse);
    assert.ok(stdout.startsWith('FIRST PHASE\n'));
    assert.match(stderr, /UTF-8 café/);
    for (const secret of ['abcdefghijklmnop', 'private-value', 'private-cli-token', 'private-failed-cli-token']) {
      assert.ok(!(stdout + stderr + JSON.stringify(events)).includes(secret));
    }
    assert.ok(events.some((entry) => entry.phase === 'cli-failed' &&
      entry.stderr.startsWith('partial startup marker') && entry.stderr.includes('[REDACTED]')));
    assert.deepEqual(events.slice(-4).map((entry) => entry.phase),
      ['daemon-disposal-start', 'daemon-exit', 'daemon-close', 'diagnostics-finished']);
    assert.ok(events.every((entry, index) => !index || entry.elapsedMs >= events[index - 1].elapsedMs));
    for (const file of ['daemon.stdout.log', 'daemon.stderr.log', 'registration-events.jsonl']) {
      assert.equal((await stat(path.join(directory, file))).mode & 0o777, 0o600);
    }
  } finally { await rm(home, {recursive: true, force: true}); }
});

test('overflow is explicit and refuses completion rather than presenting a tail as full evidence', async () => {
  const home = await mkdtemp(path.join(tmpdir(), 'registration-overflow-'));
  try {
    const diagnostic = await createRegistrationDiagnostics(home);
    diagnostic.capture('stdout', Buffer.alloc(16 * 1024 * 1024 + 1, 120));
    assert.throws(() => diagnostic.assertWithinBounds(), /exceeded bound/);
    await assert.rejects(diagnostic.finish(), /exceeded bound/);
    await assert.rejects(diagnostic.finish(), /exceeded bound/);
    const events = await readFile(path.join(home, 'registration-diagnostics/registration-events.jsonl'), 'utf8');
    assert.equal(JSON.parse(events.trim().split('\n').at(-1)).overflow, true);
    assert.equal((await stat(path.join(home, 'registration-diagnostics/daemon.stdout.log'))).size, 16 * 1024 * 1024);
  } finally { await rm(home, {recursive: true, force: true}); }
});

test('diagnostic redaction covers labelled credentials while retaining failure and timing details', () => {
  const text = redactDiagnosticText('exit=1 password=hello {"apiKey":"short", "elapsedMs":15000} Bearer abc.def');
  assert.ok(!text.includes('hello') && !text.includes('short') && !text.includes('abc.def'));
  assert.match(text, /exit=1/);
  assert.match(text, /15000/);
});
