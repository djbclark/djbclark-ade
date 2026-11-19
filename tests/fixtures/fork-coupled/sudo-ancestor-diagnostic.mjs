// Host-only read-only diagnostic. Not invoked automatically before source review.
import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { readRegular, sha256 } from './retained-daemon.mjs';

const execute = promisify(execFile);
const directory = fileURLToPath(new URL('.', import.meta.url));
const sourceRoot = path.resolve(directory, '../../..');
const sudo = (args) => execute('/usr/bin/sudo', ['-k', '-n', ...args],
  {timeout: 30000, maxBuffer: 16384, env: {PATH: '/usr/bin:/bin'}});
assert.equal(process.platform, 'linux');
assert.equal(process.env.GITHUB_ACTIONS, 'true', 'disposable CI only');
assert.notEqual(process.getuid(), 0);
assert.equal(process.argv.length, 3);
const staged = path.resolve(process.argv[2], 'qualified-daemon');
const helper = path.join(staged, 'system-closure/namespace-bootstrap.py');
const bytes = await readRegular(helper, 65536);
assert.equal(bytes.length, 52756);
assert.equal(sha256(bytes), '605fe0f54cd43ed9614d7c4517919c9867e48a6da719bc33dac55b95ded6a8d7');
const diagnostic = path.join(directory, 'sudo-ancestor-diagnostic.py');
const diagnosticBytes = await readRegular(diagnostic, 65536);
const revision = (await execute('git', ['rev-parse', 'HEAD'], {cwd: sourceRoot})).stdout.trim();
assert.match(revision, /^[a-f0-9]{40}$/);
const recorded = (await execute('git', ['show', `${revision}:tests/fixtures/fork-coupled/sudo-ancestor-diagnostic.py`],
  {cwd: sourceRoot, encoding: 'buffer', maxBuffer: 65536})).stdout;
assert.ok(recorded.equals(diagnosticBytes));
const root = `/fork-coupled-diagnostic-${randomUUID()}`;
let created = false, closed = false;
try {
  await sudo(['/bin/mkdir', '-m', '0755', root]); created = true;
  await sudo(['/usr/bin/install', '-D', '-o', '0', '-g', '0', '-m', '0444', helper,
    path.join(root, 'system-closure/namespace-bootstrap.py')]);
  await sudo(['/usr/bin/install', '-o', '0', '-g', '0', '-m', '0444', diagnostic,
    path.join(root, 'sudo-ancestor-diagnostic.py')]);
  assert.equal(sha256(await readRegular(path.join(root, 'sudo-ancestor-diagnostic.py'), 65536)), sha256(diagnosticBytes));
  const result = await sudo(['/usr/bin/python3', '-I', path.join(root, 'sudo-ancestor-diagnostic.py'),
    root, String(process.pid)]);
  closed = true; // execFile callback follows actual close, not a timer or protocol ACK.
  const data = JSON.parse(result.stdout);
  assert.equal(data.qualification, false);
  assert.equal(data.diagnosticOnly, true);
  assert.equal(data.snapshotStable, true);
  assert.equal(data.caller.pid, process.pid);
  console.log(JSON.stringify({sourceSha: revision, diagnosticSha256: sha256(diagnosticBytes), ...data}));
} finally {
  if (created && closed) await sudo(['/bin/rm', '-rf', root]);
  else if (created) console.error(`Diagnostic closure unproved; retained read-only files: ${root}`);
}
