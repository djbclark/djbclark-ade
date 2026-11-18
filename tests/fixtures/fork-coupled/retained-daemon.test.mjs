import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtemp, mkdir, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import fs from 'node:fs/promises';
import { setTimeout as pause } from 'node:timers/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { once } from 'node:events';
import { readRegular } from './retained-daemon.mjs';
import { ownDisposableGroup } from './owned-cleanup.mjs';

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

test('owned fixture cleanup waits for actual graceful close and is idempotent', { timeout: 5000 }, async () => {
  const child = spawn(process.execPath, ['-e', "process.on('SIGTERM',()=>process.exit(0));setInterval(()=>{},1000);process.send('ready');"], {
    detached: true, stdio: ['ignore', 'ignore', 'ignore', 'ipc'],
  });
  const owner = ownDisposableGroup(child, { gracefulMs: 500, forcedMs: 2000 });
  try {
    await once(child, 'message');
    const first = owner.dispose();
    assert.equal(first, owner.dispose());
    assert.deepEqual(await first, { code: 0, signal: null });
    assert.equal(child.connected, false);
  } finally { await owner.dispose(); }
});

test('unresponsive owned fixture is killed and closed before original timeout is returned', { timeout: 5000 }, async () => {
  const child = spawn(process.execPath, ['-e', "process.on('SIGTERM',()=>{});setInterval(()=>{},1000);process.send('ready');"], {
    detached: true, stdio: ['ignore', 'ignore', 'ignore', 'ipc'],
  });
  const owner = ownDisposableGroup(child, { gracefulMs: 100, forcedMs: 2000 });
  try {
    await once(child, 'message');
    const first = owner.dispose();
    assert.equal(first, owner.dispose());
    await assert.rejects(first, /graceful stop timed out/);
    assert.deepEqual(await owner.closed, { code: null, signal: 'SIGKILL' });
    assert.equal(child.connected, false);
    assert.equal(child.signalCode, 'SIGKILL');
    await assert.rejects(owner.dispose(), /graceful stop timed out/);
  } finally { await owner.dispose().catch(() => {}); }
});

for (const mode of ['nonzero', 'signal', 'zero-with-live-helper']) {
  test(`early ${mode} fixture leader cannot abandon its owned helper`, { timeout: 7000 }, async () => {
    const source = `
      const {spawn}=require('node:child_process');
      const helper=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore'});
      process.send({pid:helper.pid});
      process.once('message',()=>{
        if(process.argv[1]==='signal') process.kill(process.pid,'SIGKILL');
        else process.exit(process.argv[1]==='nonzero'?7:0);
      });
    `;
    const child = spawn(process.execPath, ['-e', source, mode], {
      detached: true, stdio: ['ignore', 'ignore', 'ignore', 'ipc'],
    });
    const owner = ownDisposableGroup(child, { gracefulMs: 1000, forcedMs: 3000 });
    try {
      const [ready] = await once(child, 'message');
      assert.ok(Number.isInteger(ready.pid) && ready.pid > 0);
      child.send('exit');
      const leader = await owner.closed;
      if (mode === 'nonzero') assert.equal(leader.code, 7);
      if (mode === 'signal') assert.equal(leader.signal, 'SIGKILL');
      await assert.rejects(owner.dispose(), /owned (fixture exited|helpers survived)/);
      try {
        const raw = await readFile(`/proc/${ready.pid}/stat`, 'utf8');
        assert.equal(raw.slice(raw.lastIndexOf(') ') + 2).split(' ')[0], 'Z', 'owned helper must have exited');
      } catch (error) { if (error.code !== 'ENOENT') throw error; }
    } finally { await owner.dispose().catch(() => {}); }
  });
}

test('delayed initial group scan expires and cannot continue after failed teardown', { timeout: 8000 }, async () => {
  const source = "const{spawn}=require('node:child_process');const h=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore'});process.send(h.pid);process.once('message',()=>process.exit(0));";
  const child = spawn(process.execPath, ['-e', source], {
    detached: true, stdio: ['ignore', 'ignore', 'ignore', 'ipc'],
  });
  const owner = ownDisposableGroup(child, { gracefulMs: 50, forcedMs: 2000 });
  const nativeReaddir = fs.readdir;
  const nativeReadFile = fs.readFile;
  let release;
  let deadlineFallback;
  let lateReads = 0;
  let finished = false;
  try {
    await once(child, 'message');
    child.send('exit');
    assert.equal((await owner.closed).code, 0);
    let first = true;
    fs.readdir = async (...args) => {
      if (args[0] !== '/proc' || !first) return nativeReaddir(...args);
      first = false;
      await new Promise((resolve) => { release = resolve; deadlineFallback = setTimeout(resolve, 4000); });
      return nativeReaddir(...args);
    };
    fs.readFile = (...args) => {
      if (finished && String(args[0]).startsWith('/proc/')) lateReads += 1;
      return nativeReadFile(...args);
    };
    await assert.rejects(owner.dispose(), /graceful stop timed out/);
    finished = true;
    clearTimeout(deadlineFallback);
    release();
    await pause(30);
    assert.equal(lateReads, 0, 'expired initial inventory must not continue reading processes');
  } finally {
    clearTimeout(deadlineFallback);
    release?.();
    fs.readdir = nativeReaddir;
    fs.readFile = nativeReadFile;
    await owner.dispose().catch(() => {});
  }
});
