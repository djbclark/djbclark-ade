"""Account isolation, native transport retention and actual Pi failures (no external inference)."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "pi-extensions/go-accounts/index.mjs"
ACCOUNTS = {"djbclark": "OPENCODE_GO_API_KEY_DJBCLARK", "dclark": "OPENCODE_GO_API_KEY_DCLARKUS",
            "t-e": "OPENCODE_GO_API_KEY_TECHNOEUPHORA"}


def test_account_identity_auth_isolation_and_native_transport():
    script = """
import assert from 'node:assert/strict';
import {accountProviders} from './pi-extensions/go-accounts/providers.mjs';
const calls=[];
const stream=()=>{};
const native={id:'opencode-go',auth:{apiKey:{resolve:()=>{throw Error('ambient fallback')}}},
 getModels:()=>[{id:'deepseek',provider:'opencode-go',api:'openai-completions',baseUrl:'https://opencode.ai/inference/go/openai/v1',compat:{maxTokensField:'max_tokens'}}],stream,streamSimple:stream};
const providers=accountProviders(native,async (command,args,options)=>{
 calls.push({command,args,options}); return {stdout:args[1]+'-fixture'};
});
assert.equal(providers.length,3);
assert.equal(new Set(providers.map(p=>p.id)).size,3);
for(const p of providers){
 assert.equal(p.stream,native.stream);assert.equal(p.streamSimple,native.streamSimple);
 assert.equal(p.getModels()[0].provider,p.id);
 assert.equal(p.getModels()[0].baseUrl,native.getModels()[0].baseUrl);
 assert.deepEqual(p.getModels()[0].compat,native.getModels()[0].compat);
 await p.auth.apiKey.check({});
}
assert.equal(calls.length,0);
const results=await Promise.all(providers.map(p=>p.auth.apiKey.resolve({signal:new AbortController().signal,credential:{key:'ignored-global-key'}})));
assert.equal(new Set(results.map(r=>r.auth.apiKey)).size,3);
assert.deepEqual(calls.map(c=>c.args[1]),['OPENCODE_GO_API_KEY_DJBCLARK','OPENCODE_GO_API_KEY_DCLARKUS','OPENCODE_GO_API_KEY_TECHNOEUPHORA']);
assert(calls.every(c=>c.command==='sudo-secretspec'&&c.args[0]==='get'&&c.options.timeout===10000));
for(const stdout of ['', '  ']){
 const p=accountProviders(native,async()=>({stdout}))[0];
 await assert.rejects(p.auth.apiKey.resolve({}),/^Error: Managed Go credential unavailable \(djbclark\)$/);
}
const failing=accountProviders(native,async()=>{throw Error('PRIVATE_STDERR_KEY')})[0];
await assert.rejects(failing.auth.apiKey.resolve({}),/^Error: Managed Go credential unavailable \(djbclark\)$/);
"""
    subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, check=True)


@pytest.mark.parametrize("label", ACCOUNTS)
@pytest.mark.parametrize("failure", ["missing", 401, 402])
def test_real_pi_uses_only_selected_account_and_surfaces_failure(tmp_path, label, failure):
    pi = shutil.which("pi")
    if not pi:
        pytest.skip("Pi installed by provider CI")
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(self.headers.get("Authorization"))
            self.send_response(failure if isinstance(failure, int) else 500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": {"message": "fixture auth failed" if failure == 401
                                                 else "fixture Go usage limit exceeded"}}).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    record = tmp_path / "broker-names.txt"
    broker = bindir / "sudo-secretspec"
    broker.write_text('#!/bin/sh\nprintf "%s\\n" "$2" >> "' + str(record) + '"\n' +
                      ("exit 1\n" if failure == "missing" else "printf fixture-key\n"))
    broker.chmod(0o700)
    wrapper = tmp_path / "provider.mjs"
    wrapper.write_text(f"import register from {json.dumps(EXTENSION.as_uri())};\n"
                       "export default pi => register({registerProvider:p=>pi.registerProvider({...p,"
                       f"getModels:()=>p.getModels().map(m=>({{...m,baseUrl:'http://127.0.0.1:{server.server_port}/v1'}})),"
                       f"getAllModels:()=>p.getModels().map(m=>({{...m,baseUrl:'http://127.0.0.1:{server.server_port}/v1'}}))"
                       "})});\n")
    agent = tmp_path / "agent"
    agent.mkdir()
    settings = agent / "settings.json"
    before = '{"defaultProvider":"retain","extensions":[],"customSetting":"retain"}\n'
    settings.write_text(before)
    env = {**os.environ, "PI_CODING_AGENT_DIR": str(agent), "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
           "OPENCODE_API_KEY": "ambient-must-not-win"}
    try:
        result = subprocess.run([pi, "--no-extensions", "-e", str(wrapper), "--no-skills", "--no-context-files",
                                 "--no-mcp", "--no-tools", "--no-session", "--provider", "opencode-go-" + label,
                                 "--model", "deepseek-v4.1-flash", "--mode", "json", "-p", "Reply OK"],
                                cwd=tmp_path, env=env, capture_output=True, text=True, timeout=45)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    output = result.stdout + result.stderr
    assert "fixture-key" not in output and "ambient-must-not-win" not in output
    assert record.exists(), output
    assert set(record.read_text().splitlines()) == {ACCOUNTS[label]}
    if failure == "missing":
        assert not calls
        assert "Managed Go credential unavailable" in output
    else:
        assert calls and all(key == "Bearer fixture-key" for key in calls)
        assert ("fixture auth failed" if failure == 401 else "fixture Go usage limit exceeded") in output
    assert settings.read_text() == before
