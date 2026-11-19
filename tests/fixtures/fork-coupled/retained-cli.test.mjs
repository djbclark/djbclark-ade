// Actual disposable CLI processes with synthetic protocol bytes; no native
// namespace, daemon ownership or transaction qualification follows.
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir, userInfo } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { EventEmitter } from 'node:events';
import { PassThrough } from 'node:stream';
import { inspect } from 'node:util';
import { cli, collectCliResponse, getCliFailureStderr, requireOwnerToken } from './retained-cli.mjs';

async function fixture() {
  const root = await mkdtemp(path.join(tmpdir(), 'coupled-cli-'));
  await mkdir(path.join(root, 'runtime'));
  await symlink(process.execPath, path.join(root, 'runtime/node'));
  await writeFile(path.join(root, 'cli-entry.mjs'), `
    import {readFileSync,writeFileSync} from 'node:fs';
    writeFileSync(new URL('./executed',import.meta.url),'yes');
    const mode=process.argv[2];
    if(mode==='owner'){
      const bearer=readFileSync(0,'utf8');
      if(process.argv.some(value=>value.includes(bearer.trim()))||
         Object.values(process.env).some(value=>value.includes(bearer.trim())))process.exit(9);
      console.log(JSON.stringify({bytes:bearer.length,home:process.env.HOME,
        daemonHome:process.env.PASEO_HOME,args:process.argv.slice(3)}));
    }else if(mode==='refuse') {process.stderr.write('refused');process.exitCode=7;}
    else if(mode==='partial') {
      process.stdout.write('private-stdout-sentinel');
      process.stderr.write('partial startup marker');
      setInterval(()=>{},1000);
    }
    else if(mode==='wait') setInterval(()=>{},1000);
    else if(mode==='overflow') {process.stdout.write(Buffer.alloc(2*1024*1024));setInterval(()=>{},1000);}
    else if(mode==='stderr-overflow') {process.stderr.write(Buffer.alloc(32768,120));setInterval(()=>{},1000);}
    else console.log('{}');
  `);
  return root;
}

test('real anonymous pipe carries synthetic bearer without argv/environment exposure', {timeout: 10000}, async () => {
  const root = await fixture();
  try {
    const reply = await cli(root, '/tmp/disposable-home', ['owner', '--owner-token-fd', '0'],
      {token: 'a'.repeat(43), timeoutMs: 5000});
    assert.equal(reply.code, 0);
    const seen = JSON.parse(reply.stdout);
    assert.equal(seen.bytes, 44);
    assert.equal(seen.home, userInfo().homedir);
    assert.equal(seen.daemonHome, '/tmp/disposable-home');
    assert.deepEqual(seen.args, ['--owner-token-fd', '0', '--home', '/tmp/disposable-home', '--json']);
  } finally { await rm(root, {recursive: true, force: true}); }
});

test('malformed bearer refuses before launching any process', async () => {
  const root = await fixture();
  try {
    for (const token of ['private-sentinel-invalid', 'S'.repeat(43) + '\n', {secret: 'object-private-sentinel'}]) {
      const check = (error) => {
        assert.equal(error.constructor, Error);
        assert.equal(error.message, 'Invalid private owner token');
        const diagnostics = [error.message, error.stack, inspect(error, {showHidden: true}),
          JSON.stringify(error), JSON.stringify(Object.entries(error))].join('\n');
        const sentinel = typeof token === 'string' ? token.trim() : token.secret;
        assert.equal(diagnostics.includes(sentinel), false);
        assert.equal('actual' in error, false);
        assert.equal('expected' in error, false);
        assert.equal('cause' in error, false);
        return true;
      };
      assert.throws(() => requireOwnerToken(token), check);
      await assert.rejects(cli(root, '/tmp/home', ['owner'], {token}), check);
    }
    await assert.rejects(readFile(path.join(root, 'executed')), {code: 'ENOENT'});
  } finally { await rm(root, {recursive: true, force: true}); }
});

test('natural CLI refusal is returned only after its actual group disposal', async () => {
  const root = await fixture();
  try {
    const reply = await cli(root, '/tmp/home', ['refuse']);
    assert.equal(reply.code, 7);
    assert.equal(reply.stdout, '');
    assert.equal(reply.stderr, 'refused');
  } finally { await rm(root, {recursive: true, force: true}); }
});

for (const mode of ['wait', 'overflow']) {
  test(`${mode} cannot publish a completed CLI response`, {timeout: 10000}, async () => {
    const root = await fixture();
    try { await assert.rejects(cli(root, '/tmp/home', [mode], {timeoutMs: 300})); }
    finally { await rm(root, {recursive: true, force: true}); }
  });
}

// Synthetic missing-close failure branch; this does not simulate successful
// child settlement or establish that a daemon operation has stopped.
test('missing actual close returns bounded disposal failure with cleanup handoff', {timeout: 1500}, async () => {
  const child = new EventEmitter();
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  let disposals = 0;
  const cleanupError = Object.assign(new Error('Synthetic disposal deadline'), {cleanupPid: 424242});
  const owner = {
    closed: new Promise(() => {}),
    dispose: async () => {
      disposals += 1;
      await new Promise((resolve) => setTimeout(resolve, 20));
      throw cleanupError;
    },
  };
  const started = performance.now();
  await assert.rejects(collectCliResponse(child, owner, {timeoutMs: 20}), (error) => {
    assert.ok(error instanceof AggregateError);
    assert.equal(error.errors[0].message, 'CLI timed out');
    assert.equal(error.errors[1], cleanupError);
    assert.equal(error.errors[1].cleanupPid, 424242);
    return true;
  });
  assert.equal(disposals, 1);
  assert.ok(performance.now() - started < 1000);
});

// Actual disposable processes retain failed observational stderr, never stdout
// or owner-bearing call evidence, without accepting forced disposal as success.
for (const token of [null, 'a'.repeat(43)]) {
  test('partial stderr on timeout is ' + (token === null ? 'retained' : 'suppressed for owner calls'),
    {timeout: 10000}, async () => {
      const root = await fixture();
      try {
        await assert.rejects(cli(root, '/tmp/home', ['partial'], {token, timeoutMs: 1000}), (error) => {
          assert.ok(error instanceof AggregateError);
          assert.equal(error.errors[0].message, 'CLI timed out');
          assert.match(error.errors[1].message, /signal=SIGTERM/);
          const evidence = getCliFailureStderr(error);
          if (token !== null) assert.equal(evidence, null);
          else {
            assert.deepEqual(evidence, {stderr: 'partial startup marker',
              stderrBytes: Buffer.byteLength('partial startup marker'), stderrTruncated: false});
            assert.ok(Object.isFrozen(evidence));
            assert.ok(!JSON.stringify(evidence).includes('private-stdout-sentinel'));
          }
          assert.equal(getCliFailureStderr(new Error('same message')), null);
          return true;
        });
      } finally { await rm(root, {recursive: true, force: true}); }
    });
}

test('stderr overflow evidence stays within original cap and preserves the failed outcome',
  {timeout: 10000}, async () => {
    const root = await fixture();
    try {
      await assert.rejects(cli(root, '/tmp/home', ['stderr-overflow']), (error) => {
        assert.ok(error instanceof AggregateError);
        assert.equal(error.errors[0].message, 'CLI stderr overflow');
        const evidence = getCliFailureStderr(error);
        assert.ok(evidence.stderrBytes > 16384);
        assert.equal(evidence.stderrTruncated, true);
        assert.ok(Buffer.byteLength(evidence.stderr) <= 16384);
        return true;
      });
    } finally { await rm(root, {recursive: true, force: true}); }
  });
