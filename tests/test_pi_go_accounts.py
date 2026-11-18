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
    script = r"""
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
assert(calls.every(c=>c.command==='sudo-secretspec'&&c.args[0]==='get'&&c.options.signal instanceof AbortSignal));
for(const stdout of ['', '  ']){
 const p=accountProviders(native,async()=>({stdout}))[0];
 await assert.rejects(p.auth.apiKey.resolve({}),/^Error: Managed Go credential unavailable \(djbclark\): empty broker stdout$/);
}
const failing=accountProviders(native,async()=>{throw Error('PRIVATE_STDERR_KEY')})[0];
await assert.rejects(failing.auth.apiKey.resolve({}),/^Error: Managed Go credential unavailable \(djbclark\): broker execution failed$/);
const sentinel='PRIVATE_STDOUT_STDERR_KEY';
for (const [fields, expected] of [
 [{code:'ENOENT'}, 'sudo-secretspec executable missing'],
 [{code:'EACCES'}, 'sudo-secretspec execution denied'],
 [{code:'ABORT_ERR'}, 'request aborted'],
 [{name:'AbortError'}, 'request aborted'],
 [{code:'ETIMEDOUT'}, 'broker timed out after 10000ms'],
 [{code:'ERR_CHILD_PROCESS_STDIO_MAXBUFFER'}, 'broker output exceeded limit'],
 [{code:2,stderr:'broker: audit attempt failed: audit denied: '+sentinel}, 'broker denied credential access'],
 [{code:7}, 'broker exited with code 7'],
 [{code:'7'}, 'broker execution failed'],
 [{code:7.5}, 'broker execution failed'],
 [{code:Infinity}, 'broker execution failed'],
 [{code:256}, 'broker execution failed'],
 [{code:-1}, 'broker execution failed'],
 [{signal:'SIGTERM',killed:true}, 'broker process terminated'],
 [{code:2,stderr:sentinel+' denied'}, 'broker exited with code 2'],
]) {
 const error=Object.assign(new Error(sentinel),{stdout:sentinel,stderr:sentinel,...fields});
 const p=accountProviders(native,async()=>{throw error})[0];
 await assert.rejects(p.auth.apiKey.resolve({}),e=>{
   assert.equal(e.message,`Managed Go credential unavailable (djbclark): ${expected}`);
   assert.equal(e.cause,undefined);
   assert.equal(e.stdout,undefined); assert.equal(e.stderr,undefined);
   assert(!String(e.stack).includes(sentinel)); return true;
 });
}
const aborted=new AbortController(); aborted.abort(sentinel);
let ran=false;
await assert.rejects(accountProviders(native,async()=>{ran=true})[0].auth.apiKey.resolve({signal:aborted.signal}),/request aborted$/);
assert.equal(ran,false);
// Inject the platform deadline without waiting or making a broker call.
const timeout=AbortSignal.timeout;
try {
 AbortSignal.timeout=()=>AbortSignal.abort(new DOMException(sentinel,'TimeoutError'));
 await assert.rejects(accountProviders(native,async()=>{ran=true})[0].auth.apiKey.resolve({}),/broker timed out after 10000ms$/);
 assert.equal(ran,false);
} finally { AbortSignal.timeout=timeout; }

"""
    subprocess.run(["node", "--input-type=module", "-e", script], cwd=ROOT, check=True)


@pytest.mark.parametrize("label", ACCOUNTS)
@pytest.mark.parametrize("failure", ["missing", "empty", "denied", 401, 402])
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
                      ({"missing": "exit 1\n", "empty": "exit 0\n",
                        "denied": "echo 'broker: audit attempt failed: audit denied: PRIVATE_STDERR_KEY' >&2\nexit 2\n"}
                       .get(failure, "printf fixture-key\n")))
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
    if isinstance(failure, str):
        assert not calls
        assert {"missing": "broker exited with code 1", "empty": "empty broker stdout",
                "denied": "broker denied credential access"}[failure] in output
        assert "PRIVATE_STDERR_KEY" not in output
    else:
        assert calls and all(key == "Bearer fixture-key" for key in calls)
        assert ("fixture auth failed" if failure == 401 else "fixture Go usage limit exceeded") in output
    assert settings.read_text() == before
