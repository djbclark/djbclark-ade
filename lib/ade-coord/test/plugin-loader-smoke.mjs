// Real released Paseo compiler/evaluator; hook transport/controller are synthetic.
// No daemon, provider/model, broker, install or credentials are used here.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdtemp, mkdir, cp, writeFile, readFile, rm, symlink } from "node:fs/promises";
import { dirname, join, delimiter } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath, pathToFileURL } from "node:url";
const prefix = process.env.ADE_PASEO_LOADER_PREFIX;
assert.ok(prefix, "explicit isolated Paseo dependency prefix required");
const require = createRequire(join(prefix, "package.json"));
const serverDir = dirname(require.resolve("@getpaseo/server"));
const { version } = JSON.parse(await readFile(join(prefix, "node_modules/@getpaseo/server/package.json"), "utf8"));
console.log("actual released Paseo compiler/evaluator", { version, node: process.version });
const { compileDirectoryPlugin } = await import(pathToFileURL(join(serverDir, "plugins/compiler-build.js")));
const { evaluateBundle } = await import(pathToFileURL(join(serverDir, "plugins/bundle-evaluator.js")));
assert.equal(typeof compileDirectoryPlugin, "function"); assert.equal(typeof evaluateBundle, "function");
const source = fileURLToPath(new URL("../../../", import.meta.url));
const dir = await mkdtemp(join(tmpdir(), "ade-native-loader-"));
const original = { ...process.env };
try {
  const runtime = join(dir, "versions/fixture"), home = join(dir, "daemon-home"), log = join(dir, "synthetic-controller.jsonl");
  await mkdir(runtime, { recursive: true }); await mkdir(home, { recursive: true });
  for (const path of ["plugins/ade-coord", "bin/ade-coord", "bin/ade_coord_controller.py", "bin/ade-git-guard", "bin/ade-paseo-guard", "lib/ade-coord/cli.js", "libexec/agent-bin", "docs/nats-coordination.md"]) {
    await mkdir(dirname(join(runtime, path)), { recursive: true });
    await cp(join(source, path), join(runtime, path), { recursive: true, verbatimSymlinks: true });
  }
  await symlink(runtime, join(dir, "current"));
  const installed = join(dir, "current/plugins/ade-coord");
  await writeFile(join(home, "config.json"), JSON.stringify({ plugins: { "ade-coord": { path: installed, enabled: true } } }), { mode: 0o600 });
  const cfg = join(dir, "enrolled.json"), stateDir = join(dir, "state"); await mkdir(stateDir);
  await writeFile(cfg, JSON.stringify({ state_dir: stateDir, identity: { host: "h", server: "s" }, roles: { r: { controller: true } }, aliases: { a: "r" } }), { mode: 0o600 });
  const boundary = join(dir, "synthetic-python");
  await writeFile(boundary, `#!/usr/bin/env python3\nimport json,sys\nrequest=json.load(sys.stdin)\nwith open(${JSON.stringify(log)},'a') as f:f.write(json.dumps({'argv':sys.argv[1:]})+'\\n')\nresult={'record':{'state':'active','generation':'g','ownership_epoch':1,'owner':{'host':'h','server':'s','agent':'a'}}} if request.get('role_id') else {}\nprint(json.dumps({'ok':True,'result':result}))\n`, { mode: 0o700 });
  process.env.PASEO_HOME = home; process.env.ADE_COORD_CONFIG = cfg; process.env.ADE_COORD_PYTHON = boundary;
  const compiled = await compileDirectoryPlugin(installed, version);
  assert.ok(compiled.serverBundle); assert.equal(compiled.manifest.id, "ade-coord");
  let registered = 0, removed = 0;
  for (let round = 0; round < 2; round++) {
    // Actual CJS bundle evaluation has erased import.meta.url. This exercises
    // install-record lookup through the current symlink, not ESM test metadata.
    const setup = evaluateBundle(compiled.serverBundle);
    let open;
    const cleanup = await setup({ addHook(name, handler) { assert.equal(name, "agent.open.before"); registered++; open = handler; return () => removed++; } });
    try {
      assert.equal(await open({ request: { agentId: "legacy", labels: {}, env: {} } }), undefined);
      const output = await open({ request: { agentId: "a", labels: {}, env: { PATH: "/usr/bin" }, purpose: "interactive" } });
      assert.equal(output.env.PATH.split(delimiter)[0], join(runtime, "libexec/agent-bin"));
      assert.equal(output.env.ADE_COORD_INSTRUCTIONS, join(runtime, "docs/nats-coordination.md"));
      assert.equal(output.env.ADE_COORD_ROLE, "r");
      await assert.rejects(open({ request: { agentId: "stale", labels: { "ade.coord.role": "r" }, env: {}, purpose: "interactive" } }));
      const end = Date.now() + 5000;
      while (true) {
        const rows = (await readFile(log, "utf8")).trim().split("\n").map(JSON.parse);
        if (rows.filter(r => r.argv[0] === join(runtime, "bin/ade_coord_controller.py")).length >= round + 1) break;
        assert.ok(Date.now() < end, "actual spawned synthetic controller did not run");
        await new Promise(resolve => setTimeout(resolve, 30));
      }
    } finally { await cleanup(); }
    console.log("actual compiled contribution load/dispose", round + 1);
  }
  assert.equal(registered, 2); assert.equal(removed, 2);
  const rows = (await readFile(log, "utf8")).trim().split("\n").map(JSON.parse);
  assert.ok(rows.some(r => r.argv[0] === join(runtime, "bin/ade-coord") && r.argv.slice(1).join(" ") === "role get"));
  assert.ok(rows.every(r => r.argv[0].startsWith(runtime + "/bin/")));
  await rm(join(home, "config.json"));
  assert.throws(() => evaluateBundle(compiled.serverBundle)({ addHook() { throw new Error("must not register without trusted install record"); } }), /ADE versioned runtime layout or install record unavailable/);
  console.log("compiler/evaluator smoke passed; native daemon install/reload and synthetic controller authority are NOT claimed");
} finally {
  for (const key of Object.keys(process.env)) if (!(key in original)) delete process.env[key];
  Object.assign(process.env, original);
  await rm(dir, { recursive: true, force: true });
}
