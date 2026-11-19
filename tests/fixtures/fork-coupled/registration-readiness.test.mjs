// Real disposable children and controlled metadata/FD faults test scheduling
// DATA only. They establish no native daemon, owner or settlement authority.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {spawn, execFile} from 'node:child_process';
import {once} from 'node:events';
import {promisify} from 'node:util';
import {mkdtemp, mkdir, readFile, writeFile, rm, rename, symlink, link, chmod} from 'node:fs/promises';
import {tmpdir, hostname} from 'node:os';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import test from 'node:test';
import {createRegistrationReadinessObserver} from './registration-readiness.mjs';
import {cli} from './retained-cli.mjs';

async function fixture() {
  const work = await mkdtemp(path.join(tmpdir(), 'registration-ready-'));
  const home = path.join(work, 'home');
  await mkdir(home, {mode: 0o700});
  const child = spawn(process.execPath, ['-e',
    "process.on('message',m=>{if(m==='stop')process.disconnect()});process.send('started')"],
  {stdio: ['ignore', 'ignore', 'ignore', 'ipc']});
  const closed = new Promise((resolve) => child.once('close', (code, signal) => resolve({code, signal})));
  await once(child, 'message');
  const file = path.join(home, 'paseo.pid');
  const row = {pid: child.pid, uid: process.getuid(), hostname: hostname(),
    startedAt: '2026-11-19T00:00:00.000Z', listen: null,
    bootId: (await readFile('/proc/sys/kernel/random/boot_id', 'utf8')).trim()};
  const ready = {...row, listen: path.join(work, 'daemon.sock'), serverId: 'fixed-test-home-id'};
  const observers = [];
  const observer = (create = createRegistrationReadinessObserver, deadline = performance.now() + 10000) => {
    const value = create(home, child, deadline); observers.push(value); return value;
  };
  return {work, home, child, file, row, ready, closed, observer,
    write: (value) => writeFile(file, JSON.stringify(value), {mode: 0o600}),
    async dispose() {
      for (const value of observers) value.dispose();
      if (child.connected) child.send('stop');
      const result = await closed;
      assert.deepEqual(result, {code: 0, signal: null}, 'synthetic child must close naturally');
      await rm(work, {recursive: true, force: true});
    }};
}

test('absent, empty and unpublished metadata delay the actual CLI transport; ready invokes it once',
  {timeout: 10000}, async () => {
    const f = await fixture();
    try {
      const observer = f.observer();
      await mkdir(path.join(f.work, 'runtime'));
      await symlink(process.execPath, path.join(f.work, 'runtime/node'));
      await writeFile(path.join(f.work, 'cli-entry.mjs'),
        "import{appendFileSync}from'node:fs';appendFileSync(new URL('./invocations',import.meta.url),'1');console.log('[]')");
      let calls = 0;
      const invokeWhenReady = async () => {
        const result = await observer.poll();
        if (!result.ready) return result;
        await observer.assertReady();
        calls += 1;
        const reply = await cli(f.work, f.home, ['plugin', 'ls']);
        assert.equal(reply.code, 0); assert.equal(reply.stdout.trim(), '[]');
        return result;
      };
      assert.equal((await invokeWhenReady()).reason, 'absent');
      await writeFile(f.file, '', {mode: 0o600});
      assert.equal((await invokeWhenReady()).reason, 'empty');
      await f.write(f.row);
      assert.equal((await invokeWhenReady()).reason, 'unpublished');
      await writeFile(f.file, '');
      assert.equal((await invokeWhenReady()).reason, 'empty');
      assert.equal(calls, 0);
      await f.write(f.ready);
      assert.equal((await invokeWhenReady()).ready, true);
      assert.equal(calls, 1);
      assert.equal(await readFile(path.join(f.work, 'invocations'), 'utf8'), '1');
    } finally { await f.dispose(); }
  });

test('first complete observation may already be ready but remains bound to the original handle',
  {timeout: 5000}, async () => {
    const f = await fixture();
    try { await f.write(f.ready); assert.equal((await f.observer().poll()).ready, true); }
    finally { await f.dispose(); }
  });

for (const field of ['pid', 'uid', 'bootId']) {
  test('foreign initial metadata refuses: ' + field, {timeout: 5000}, async () => {
    const f = await fixture();
    try {
      const row = {...f.ready, [field]: field === 'bootId' ? 'not-current-linux-boot' : f.row[field] + 1};
      await f.write(row);
      const observer = f.observer();
      let failure;
      await assert.rejects(observer.poll(), (error) => { failure = error; return true; });
      await f.write(f.ready);
      await assert.rejects(observer.poll(), (error) => error === failure);
    } finally { await f.dispose(); }
  });
}

for (const field of ['startedAt', 'hostname', 'bootId']) {
  test('latched metadata incarnation cannot change: ' + field, {timeout: 5000}, async () => {
    const f = await fixture();
    try {
      const observer = f.observer(); await f.write(f.row); await observer.poll();
      const changed = {...f.row};
      if (field === 'bootId') delete changed.bootId;
      else changed[field] += '-changed';
      await f.write(changed);
      await assert.rejects(observer.poll(), /incarnation changed/);
      await f.write(f.ready);
      await assert.rejects(observer.poll(), /incarnation changed/);
    } finally { await f.dispose(); }
  });
}

for (const mode of ['replacement', 'disappearance', 'withdrawal', 'endpoint', 'incomplete-pair', 'server-id']) {
  test('normal metadata continuity refuses ' + mode, {timeout: 5000}, async () => {
    const f = await fixture();
    try {
      const observer = f.observer();
      await f.write(mode === 'withdrawal' || mode === 'server-id' ? f.ready : f.row);
      await observer.poll();
      if (mode === 'replacement') {
        await writeFile(f.file + '.replacement', JSON.stringify(f.ready), {mode: 0o600});
        await rename(f.file + '.replacement', f.file);
      } else if (mode === 'disappearance') await rm(f.file);
      else if (mode === 'withdrawal') await f.write(f.row);
      else if (mode === 'endpoint') await f.write({...f.ready, listen: '/tmp/foreign-daemon.sock'});
      else if (mode === 'incomplete-pair') await f.write({...f.ready, serverId: null});
      else await f.write({...f.ready, serverId: 'different-home-id'});
      let failure;
      await assert.rejects(observer.poll(), (error) => { failure = error; return true; });
      await f.write(f.ready);
      await assert.rejects(observer.assertReady(), (error) => error === failure);
    } finally { await f.dispose(); }
  });
}

for (const mode of ['json', 'schema', 'utf8', 'oversize', 'symlink', 'hardlink', 'fifo', 'mode', 'open-permission']) {
  test('stable malformed or unsafe metadata refuses: ' + mode, {timeout: 5000}, async () => {
    const f = await fixture();
    try {
      if (mode === 'json') await writeFile(f.file, 'private-malformed-sentinel', {mode: 0o600});
      else if (mode === 'schema') await f.write({...f.ready, unexpected: 'private-malformed-sentinel'});
      else if (mode === 'utf8') await writeFile(f.file, Buffer.from([255]), {mode: 0o600});
      else if (mode === 'oversize') await writeFile(f.file, Buffer.alloc(65537), {mode: 0o600});
      else if (mode === 'fifo') await promisify(execFile)('/usr/bin/mkfifo', [f.file]);
      else if (mode === 'mode') { await f.write(f.ready); await chmod(f.file, 0o644); }
      else if (mode === 'open-permission') { await f.write(f.ready); await chmod(f.file, 0o000); }
      else {
        await writeFile(f.file + '.target', JSON.stringify(f.ready), {mode: 0o600});
        await (mode === 'symlink' ? symlink : link)(f.file + '.target', f.file);
      }
      const observer = f.observer();
      await assert.rejects(observer.poll(), (error) => {
        assert.ok(!String(error.stack).includes('private-malformed-sentinel')); return true;
      });
    } finally { await f.dispose(); }
  });
}

test('original child exit during pending wait is sticky and cannot follow later ready metadata',
  {timeout: 5000}, async () => {
    const f = await fixture();
    try {
      const observer = f.observer(); await f.write(f.row); await observer.poll();
      f.child.send('stop'); await f.closed; await f.write(f.ready);
      await assert.rejects(observer.poll(), /Original daemon handle/);
    } finally { await f.dispose(); }
  });

test('the same startup deadline expires despite later ready metadata; no new window is created',
  {timeout: 5000}, async () => {
    const f = await fixture();
    try {
      const deadline = performance.now() + 250;
      const observer = f.observer(createRegistrationReadinessObserver, deadline);
      assert.equal((await observer.poll()).ready, false);
      await new Promise((resolve) => setTimeout(resolve, 300)); await f.write(f.ready);
      await assert.rejects(observer.poll(), /Original startup deadline exceeded/);
      await assert.rejects(observer.assertReady(), /Original startup deadline exceeded/);
    } finally { await f.dispose(); }
  });

// Fault modules capture a temporarily replaced FS primitive at import. These
// finite DATA controls are not public injection ports or native IO attestations.
async function faultModule(wrap) {
  const original = fs.promises.open;
  fs.promises.open = async (...args) => wrap(await original(...args), args[0]);
  try { return await import('./registration-readiness.mjs?data-fault=' + randomUUID()); }
  finally { fs.promises.open = original; }
}

for (const mode of ['read', 'stat', 'close', 'read-and-close', 'opened-enoent', 'child-and-read']) {
  test('actual opened descriptor faults remain observable and sticky: ' + mode,
    {timeout: 5000}, async () => {
      const f = await fixture();
      let opened, closes = 0;
      const primary = new Error('controlled original FD ' + mode);
      if (mode === 'opened-enoent') primary.code = 'ENOENT';
      const childFailure = new Error('controlled original child error');
      const closeError = new Error('controlled post-close failure');
      try {
        await f.write(f.ready);
        const module = await faultModule((fd, file) => {
          if (file !== f.file) return fd;
          opened = fd;
          return {stat: async (...args) => {
            if (mode === 'stat') throw primary; return fd.stat(...args);
          }, read: async (...args) => {
            if (mode === 'child-and-read') { f.child.emit('error', childFailure); throw primary; }
            if (mode.startsWith('read') || mode === 'opened-enoent') throw primary;
            return fd.read(...args);
          }, close: async () => {
            closes += 1; await fd.close();
            if (mode.includes('close')) throw closeError;
          }};
        });
        const observer = f.observer(module.createRegistrationReadinessObserver);
        let failure;
        await assert.rejects(observer.poll(), (error) => {
          failure = error;
          if (mode === 'read-and-close') {
            assert.ok(error instanceof AggregateError);
            assert.deepEqual(error.errors, [primary, closeError]); assert.equal(error.cause, closeError);
          } else if (mode === 'child-and-read') {
            assert.ok(error instanceof AggregateError);
            assert.deepEqual(error.errors, [childFailure, primary]); assert.equal(error.cause, primary);
          } else assert.equal(error, mode === 'close' ? closeError : primary);
          return true;
        });
        assert.equal(opened.fd, -1); assert.equal(closes, 1);
        await assert.rejects(observer.poll(), (error) => error === failure);
        assert.equal(closes, 1);
      } finally { await f.dispose(); }
    });
}

test('a genuine in-place changing read stays pending and cannot invoke early',
  {timeout: 5000}, async () => {
    const f = await fixture();
    try {
      await f.write(f.row);
      let changed = false;
      const module = await faultModule((fd, file) => {
        if (file !== f.file) return fd;
        return {stat: async (...args) => {
          const before = await fd.stat(...args);
          if (!changed) { changed = true; await f.write(f.ready); }
          return before;
        }, read: fd.read.bind(fd), close: fd.close.bind(fd)};
      });
      const observer = f.observer(module.createRegistrationReadinessObserver);
      assert.deepEqual(await observer.poll(), {ready: false, reason: 'changing'});
      assert.equal((await observer.poll()).ready, true);
    } finally { await f.dispose(); }
  });
