// Actual disposable CLI processes with synthetic protocol bytes; no native
// namespace, daemon ownership or transaction qualification follows.
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir, userInfo } from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { cli } from './retained-cli.mjs';

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
    else if(mode==='wait') setInterval(()=>{},1000);
    else if(mode==='overflow') {process.stdout.write(Buffer.alloc(2*1024*1024));setInterval(()=>{},1000);}
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
    await assert.rejects(cli(root, '/tmp/home', ['owner'], {token: 'invalid'}));
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
