// Disposable CI evidence only. These records cannot grant execution or quiet.
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

export const diagnosticFiles = Object.freeze([
  'daemon.stdout.log', 'daemon.stderr.log', 'registration-events.jsonl',
]);
const MAX_LOG = 16 * 1024 * 1024;
const MAX_EVENTS = 1024 * 1024;

export function redactDiagnosticText(value) {
  return String(value)
    .replace(/Bearer\s+[A-Za-z0-9._~+/-]+/gi, 'Bearer [REDACTED]')
    .replace(/(["']?(?:authorization|accessToken|refreshToken|token|password|secret|apiKey)["']?\s*[:=]\s*)("(?:\\.|[^"\\])*"|'[^']*'|[^\s,;}]+)/gi,
      '$1"[REDACTED]"');
}

export async function createRegistrationDiagnostics(home) {
  const directory = path.join(home, 'registration-diagnostics');
  await mkdir(directory, { mode: 0o700 });
  const start = performance.now();
  const logs = { stdout: [], stderr: [] };
  const events = [];
  let logBytes = 0, eventBytes = 0, overflow = false, finished = false;
  let completion;
  const record = (phase, data = {}) => {
    if (finished) return;
    const safe = Object.fromEntries(Object.entries(data).map(([key, value]) =>
      [key, typeof value === 'string' ? redactDiagnosticText(value) : value]));
    const line = JSON.stringify({ elapsedMs: performance.now() - start, phase, ...safe }) + '\n';
    const bytes = Buffer.byteLength(line);
    if (events.length >= 2048 || eventBytes + bytes > MAX_EVENTS) { overflow = true; return; }
    events.push(line); eventBytes += bytes;
  };
  const capture = (stream, chunk) => {
    assert.ok(stream === 'stdout' || stream === 'stderr');
    if (finished) return;
    const remaining = MAX_LOG - logBytes;
    if (chunk.length > remaining) overflow = true;
    if (remaining > 0) logs[stream].push(Buffer.from(chunk.subarray(0, remaining)));
    logBytes += Math.min(chunk.length, remaining);
  };
  const assertWithinBounds = () => assert.equal(overflow, false, 'registration diagnostics exceeded bound');
  const finish = () => {
    if (completion) return completion;
    completion = (async () => {
    record('diagnostics-finished', { overflow, logBytes, eventBytes });
    finished = true;
    const contents = [redactDiagnosticText(Buffer.concat(logs.stdout).toString('utf8')),
      redactDiagnosticText(Buffer.concat(logs.stderr).toString('utf8')), events.join('')];
    for (let index = 0; index < diagnosticFiles.length; index += 1) {
      // Redaction may expand short sensitive values. Refuse rather than truncate.
      assert.ok(Buffer.byteLength(contents[index]) <= (index === 2 ? MAX_EVENTS : MAX_LOG));
      await writeFile(path.join(directory, diagnosticFiles[index]), contents[index], { mode: 0o600, flag: 'wx' });
    }
    assertWithinBounds();
    })();
    return completion;
  };
  record('probe-started', { probePid: process.pid });
  return Object.freeze({ record, capture, assertWithinBounds, finish });
}
