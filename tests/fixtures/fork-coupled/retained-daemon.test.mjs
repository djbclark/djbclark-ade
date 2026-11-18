import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, mkdir, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { readRegular } from './retained-daemon.mjs';

test('bounded descriptor reader accepts exact data and refuses oversized and special leaves', async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'fork-coupled-read-'));
  try {
    await writeFile(path.join(root, 'data'), 'payload');
    assert.equal((await readRegular(path.join(root, 'data'), 7)).toString(), 'payload');
    await assert.rejects(readRegular(path.join(root, 'data'), 6));
    await mkdir(path.join(root, 'directory'));
    await assert.rejects(readRegular(path.join(root, 'directory')));
    await symlink('data', path.join(root, 'alias'));
    await assert.rejects(readRegular(path.join(root, 'alias')));
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('no-writer FIFO rejects in a bounded subprocess', { timeout: 10_000 }, async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'fork-coupled-fifo-'));
  const childResult = (child) => new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('close', (code, signal) => resolve({ code, signal }));
  });
  try {
    const fifo = path.join(root, 'fifo');
    const created = await childResult(spawn('mkfifo', [fifo]));
    assert.equal(created.code, 0);
    const module = fileURLToPath(new URL('./retained-daemon.mjs', import.meta.url));
    const source = `import {readRegular} from ${JSON.stringify(new URL('./retained-daemon.mjs', import.meta.url).href)}; try { await readRegular(process.argv[1]); process.exitCode=2; } catch { process.exitCode=0; }`;
    assert.ok(path.isAbsolute(module));
    const child = spawn(process.execPath, ['--input-type=module', '-e', source, fifo], { stdio: 'ignore' });
    let timedOut = false;
    const watchdog = setTimeout(() => { timedOut = true; child.kill('SIGKILL'); }, 2500);
    try {
      const result = await childResult(child);
      assert.equal(timedOut, false, 'FIFO must reject without watchdog intervention');
      assert.equal(result.code, 0);
    } finally { clearTimeout(watchdog); }
  } finally { await rm(root, { recursive: true, force: true }); }
});
