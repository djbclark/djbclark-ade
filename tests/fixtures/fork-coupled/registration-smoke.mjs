// Administrative host wrapper only. The unprivileged probe runs in a fresh
// private namespace through the reviewed, packaged Python bootstrap.
import assert from 'node:assert/strict';
import { spawn, execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { randomUUID } from 'node:crypto';
import { userInfo } from 'node:os';
import { access, lstat, mkdir, mkdtemp, readlink, rm, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { readRegular, sha256, validateRetainedPayload } from './retained-daemon.mjs';
import { ownDisposableGroup } from './owned-cleanup.mjs';

const execute = promisify(execFile);
const fixtureDirectory = fileURLToPath(new URL('.', import.meta.url));
const sourceRoot = path.resolve(fixtureDirectory, '../../..');
const members = ['registration-probe.mjs', 'retained-daemon.mjs', 'owned-cleanup.mjs',
  'registration-smoke-contract.json', 'namespace-bootstrap-input.json'];

async function sudo(arguments_) {
  await execute('/usr/bin/sudo', ['-k', '-n', ...arguments_], {
    timeout: 30_000, maxBuffer: 65536, env: {PATH: '/usr/bin:/bin'},
  });
}

async function absent(file) {
  try { await access(file); return false; }
  catch (error) { if (error.code === 'ENOENT') return true; throw error; }
}

// The protected harness closure comes from the exact checked-out Git blobs,
// never from an ignored/untracked/generated file or a caller-supplied module.
async function sourceClosure() {
  const git = async (args) => (await execute('git', args,
    {cwd: sourceRoot, encoding: 'buffer', maxBuffer: 1024 * 1024})).stdout;
  const sourceSha = (await git(['rev-parse', 'HEAD'])).toString('ascii').trim();
  assert.match(sourceSha, /^[a-f0-9]{40}$/);
  const files = [];
  for (const name of members) {
    const file = path.join(fixtureDirectory, name);
    const bytes = await readRegular(file, 1024 * 1024);
    const relative = path.relative(sourceRoot, file).split(path.sep).join('/');
    const recorded = await git(['show', `${sourceSha}:${relative}`]);
    assert.ok(recorded.equals(bytes), `fixture differs from exact committed Git blob: ${name}`);
    files.push({name, file, bytes});
  }
  return {sourceSha, files};
}

async function hostLibraryView(manifest) {
  const entries = [];
  const paths = [...manifest.externalLibraries.map((member) => member.path),
    manifest.systemClosure.loaderResolution.cache.path];
  for (const file of paths) {
    const metadata = await lstat(file, {bigint: true});
    assert.ok(metadata.isFile() && metadata.uid === 0n);
    entries.push({path: file, dev: String(metadata.dev), ino: String(metadata.ino),
      mode: Number(metadata.mode), sha256: sha256(await readRegular(file))});
  }
  return {namespace: await readlink('/proc/self/ns/mnt'), entries};
}

async function namespaceProbe(arguments_) {
  const child = spawn('/usr/bin/sudo', ['-k', '-n', '/usr/bin/python3', '-I', ...arguments_], {
    env: {PATH: '/usr/bin:/bin'}, detached: true, stdio: ['ignore', 'pipe', 'pipe'],
  });
  const owner = ownDisposableGroup(child, {gracefulMs: 3000, forcedMs: 5000, allowNonzeroExit: true});
  let failure, stdoutBytes = 0, stderrBytes = 0;
  const output = [], errors = [];
  const fail = (reason) => { failure ??= new Error(reason); void owner.dispose().catch(() => {}); };
  child.stdout.on('data', (bytes) => {
    stdoutBytes += bytes.length;
    if (stdoutBytes > 65536) fail('namespace probe output overflow'); else output.push(bytes);
  });
  child.stderr.on('data', (bytes) => {
    stderrBytes += bytes.length;
    if (stderrBytes > 65536) fail('namespace probe diagnostics overflow'); else errors.push(bytes);
  });
  child.once('error', () => fail('namespace bootstrap launch failed'));
  const deadline = performance.now() + 300_000;
  const timer = setTimeout(() => fail('namespace probe deadline'), 300_000);
  let outcome;
  try {
    const closed = await owner.closed;
    assert.ok(performance.now() < deadline, 'namespace probe deadline');
    if (failure) throw failure;
    assert.equal(closed.code, 0, `namespace bootstrap/probe failed: ${Buffer.concat(errors).toString('utf8')}`);
    outcome = JSON.parse(Buffer.concat(output).toString('utf8'));
    assert.equal(outcome.status, 'registration-negative-passed');
    assert.equal(outcome.qualification, false);
    assert.equal(outcome.ownedWorkSettled, true, 'no backing cleanup before actual owned settlement');
    // sudo may retain a real monitor process. The bootstrap authenticates its
    // actual ancestor chain before exec; a sudo PID is not a Node PID alias.
    assert.ok(Number.isSafeInteger(outcome.probePid) && outcome.probePid > 1);
  } finally {
    clearTimeout(timer);
    await owner.dispose();
  }
  assert.ok(performance.now() < deadline, 'namespace probe deadline after disposal');
  return outcome;
}

assert.equal(process.platform, 'linux');
assert.equal(process.env.GITHUB_ACTIONS, 'true', 'disposable CI only');
assert.notEqual(process.getuid(), 0);
assert.equal(process.argv.length, 3, 'one authenticated staging directory required');
const staged = path.resolve(process.argv[2], 'qualified-daemon');
const manifestBytes = await readRegular(`${staged}.manifest.json`, 4 * 1024 * 1024);
const manifest = JSON.parse(manifestBytes);
assert.equal(manifest.systemClosure?.profile, 'linux-retained-system-closure-v1',
  'old build inputs lacking retained library bytes cannot launch');
const expectedManifest = sha256(manifestBytes);
const {sourceSha, files} = await sourceClosure();
const contract = files.find((entry) => entry.name === 'registration-smoke-contract.json').bytes;
assert.equal(JSON.parse(contract).qualification, false);
const policyDirectory = path.join(userInfo().homedir, '.local/state/djbclark-ade/forks');
const hostPolicy = path.join(policyDirectory, 'paseo-qualified-host-policy.json');
const managedPolicy = path.join(policyDirectory, 'paseo-managed-plugins.json');
assert.ok(await absent(hostPolicy) && await absent(managedPolicy), 'fresh CI account policies required');
const root = `/fork-coupled-native-${randomUUID()}`;
const protectedFixture = `/fork-coupled-fixture-${randomUUID()}`;
const work = await mkdtemp('/tmp/fcs-');
const home = path.join(work, 'home');
let installed = false, fixtureInstalled = false, hostWritten = false, managedWritten = false;
let launchAttempted = false, settled = false, failure, result, before;
try {
  await mkdir(home, {mode: 0o700});
  const config = {version: 1, pluginsEnabled: true,
    daemon: {listen: `unix://${work}/daemon.sock`, relay: {enabled: false},
      mcp: {enabled: false, injectIntoAgents: false}, usage: {enabled: false},
      browserTools: {enabled: false}, enableTerminalAgentHooks: false},
    features: {dictation: {enabled: false}, voiceMode: {enabled: false}, webUi: {enabled: false}},
    agents: {resumeOnStartup: false}};
  await writeFile(path.join(home, 'config.json'), JSON.stringify(config), {mode: 0o600, flag: 'wx'});
  await sudo(['/bin/cp', '-a', staged, root]); installed = true;
  await sudo(['/bin/cp', `${staged}.manifest.json`, `${root}.manifest.json`]);
  await sudo(['/bin/chown', '-R', 'root:root', root, `${root}.manifest.json`]);
  await sudo(['/bin/chmod', '0444', `${root}.manifest.json`]);
  // No executing library check on the host; nothing retained is imported here.
  await validateRetainedPayload(root, expectedManifest);
  await sudo(['/bin/mkdir', '-m', '0755', protectedFixture]); fixtureInstalled = true;
  for (const entry of files) {
    await sudo(['/usr/bin/install', '-o', '0', '-g', '0', '-m', '0444', entry.file,
      path.join(protectedFixture, entry.name)]);
    assert.equal(sha256(await readRegular(path.join(protectedFixture, entry.name))), sha256(entry.bytes));
  }
  before = await hostLibraryView(manifest);
  await mkdir(policyDirectory, {recursive: true, mode: 0o700});
  await writeFile(hostPolicy, JSON.stringify({schemaVersion: 1, qualifications: [{
    immutableRoot: root, immutabilityAdapter: 'linux-root-owned-retained-v1',
    distributionBuildId: manifest.distributionBuildId, manifestSha256: expectedManifest,
    qualificationSha256: sha256(contract),
  }]}), {mode: 0o600, flag: 'wx'}); hostWritten = true;
  await writeFile(managedPolicy, JSON.stringify({version: 1, plugins: {}}),
    {mode: 0o600, flag: 'wx'}); managedWritten = true;
  const bootstrap = path.join(root, 'system-closure/namespace-bootstrap.py');
  const bootstrapRow = manifest.files.find((entry) => entry.path === 'system-closure/namespace-bootstrap.py');
  assert.ok(bootstrapRow);
  const approvedBootstrap = JSON.parse(files.find((entry) => entry.name === 'namespace-bootstrap-input.json').bytes);
  assert.equal(approvedBootstrap.schemaVersion, 1);
  assert.equal(approvedBootstrap.qualification, false);
  assert.equal(bootstrapRow.sha256, approvedBootstrap.sha256, 'bootstrap must match the independently reviewed source');
  assert.equal(bootstrapRow.size, approvedBootstrap.size);
  const harness = path.join(protectedFixture, 'registration-probe.mjs');
  const harnessBytes = files.find((entry) => entry.name === 'registration-probe.mjs').bytes;
  const recipe = {schemaVersion: 1, profile: 'linux-ci-qualified-system-namespace-v1',
    distributionRoot: root, manifestSha256: expectedManifest,
    bootstrap: {path: bootstrap, sha256: bootstrapRow.sha256, size: bootstrapRow.size},
    harness: {path: harness, sha256: sha256(harnessBytes), size: harnessBytes.length},
    arguments: [root, home, expectedManifest, before.namespace, sourceSha],
    environment: {PATH: '/usr/bin:/bin', PASEO_HOME: home, GITHUB_ACTIONS: 'true', CI: 'true',
      LANG: 'C.UTF-8', LC_ALL: 'C.UTF-8'}};
  const recipeSource = path.join(work, 'launch-recipe.json');
  await writeFile(recipeSource, JSON.stringify(recipe), {mode: 0o600, flag: 'wx'});
  const recipeFile = path.join(protectedFixture, 'launch-recipe.json');
  await sudo(['/usr/bin/install', '-o', '0', '-g', '0', '-m', '0444', recipeSource, recipeFile]);
  assert.equal(sha256(await readRegular(recipeFile)), sha256(Buffer.from(JSON.stringify(recipe))));
  await sudo(['/bin/chmod', '0555', protectedFixture]);
  launchAttempted = true;
  result = await namespaceProbe([bootstrap, '--distribution', root,
    '--expected-manifest', `${root}.manifest.json`, '--expected-manifest-sha256', expectedManifest,
    '--launch-recipe', recipeFile, '--caller-pid', String(process.pid)]);
  assert.equal(result.manifestSha256, expectedManifest);
  assert.equal(result.sourceSha, sourceSha);
  assert.equal(result.hostNamespace, before.namespace);
  assert.notEqual(result.namespace, before.namespace);
  assert.equal(result.builtinCount, 14);
  settled = true;
} catch (error) { failure = error; }
finally {
  try { if (before) assert.deepEqual(await hostLibraryView(manifest), before, 'host library view changed'); }
  catch (error) { failure = failure ? new AggregateError([failure, error], 'probe and host invariance failed') : error; }
  if (!launchAttempted || settled) {
    try {
      if (hostWritten) await rm(hostPolicy);
      if (managedWritten) await rm(managedPolicy);
      if (installed) await sudo(['/bin/rm', '-rf', root, `${root}.manifest.json`]);
      if (fixtureInstalled) await sudo(['/bin/rm', '-rf', protectedFixture]);
      await rm(work, {recursive: true, force: true});
    } catch (error) { failure = failure ? new AggregateError([failure, error], 'fixture cleanup failed') : error; }
  } else {
    process.stderr.write(`Settlement unproved; retained backing and policies preserved: ${root}, ${protectedFixture}, ${work}\n`);
  }
}
if (failure) throw failure;
console.log(JSON.stringify({...result, hostViewUnchanged: true}));
