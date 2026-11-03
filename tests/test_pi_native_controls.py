"""Pi controls: isolated files and fake API only; never import/run a live Pi."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/autorename"


@pytest.fixture
def native(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("pi_native_test", SKILL / "pi_native.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setenv("AUTORENAME_STATE_DIR", str(tmp_path))
    for key in list(os.environ):
        if key.startswith("PI_") or key in {"AI_AGENT", "ACP_RUN_AGENT"}:
            monkeypatch.delenv(key)
    monkeypatch.setenv("PI_SESSION_ID", "custom/id")
    monkeypatch.setenv("PI_SESSION_FILE", "/session.jsonl")
    monkeypatch.setattr(mod, "ancestors", lambda: [(22, "bash"), (42, "pi")])
    reg = dict(version=1, pid=42, instance="a" * 32, session_id="custom/id",
               session_file="/session.jsonl", provider="openai", model="test", thinking="high")
    mod.root().mkdir()
    (mod.root() / "42.json").write_text(json.dumps(reg))
    (mod.root() / reg["instance"]).mkdir()
    return mod, reg


def test_identity_and_native_priority(native, monkeypatch):
    mod, reg = native
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent")
    monkeypatch.setenv("OMPCODE", "1")
    assert mod.selected()
    assert mod.registration() == reg
    with pytest.raises(ValueError):
        mod.registration("parent")
    monkeypatch.setenv("PI_SESSION_FILE", "/different.jsonl")
    with pytest.raises(ValueError):
        mod.registration()
    monkeypatch.delenv("PI_SESSION_ID")
    assert mod.selected()
    with pytest.raises(ValueError):
        mod.registration()


@pytest.mark.parametrize("name", ["pi", "node", "bun", "omp", "claude", "codex"])
def test_nested_unregistered_runtime_blocks_parent(native, monkeypatch, name):
    mod, _ = native
    monkeypatch.setattr(mod, "ancestors", lambda: [(30, name), (42, "pi")])
    with pytest.raises(ValueError, match="no owning"):
        mod.registration()


def test_request_receipt_is_bound_to_instance(native, monkeypatch):
    mod, reg = native
    directory = mod.root() / reg["instance"]

    def respond(_seconds):
        for file in directory.glob("*.request.json"):
            body = json.loads(file.read_text())
            assert body["session_id"] == "custom/id"
            assert body["session_file"] == "/session.jsonl"
            assert file.stat().st_mode & 0o777 == 0o600
            file.with_name(file.name.replace("request", "result")).write_text(json.dumps(
                dict(nonce=body["nonce"], instance="wrong", accepted=True)))

    monkeypatch.setattr(mod.time, "sleep", respond)
    with pytest.raises(ValueError, match="receipt identity"):
        mod.request(reg, "rename", title="Title", auto=True)
    assert not list(directory.iterdir())


def test_dry_run_and_model_mismatch(native, monkeypatch, capsys):
    mod, _ = native
    for key, value in {"PI_PROVIDER": "openai", "PI_MODEL": "test", "PI_REASONING_LEVEL": "high"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "argv", ["pi_native.py", "--dry-run", "/compact focus"])
    assert mod.main() == 0
    assert "no request written" in capsys.readouterr().out
    monkeypatch.setenv("PI_MODEL", "changed")
    assert mod.main() == 2
    monkeypatch.setenv("ACP_RUN_AGENT", "1")
    assert mod.main() == 9


@pytest.mark.parametrize("command", ["/new", "/reset", "/quit", "/model foo", "/compact focus"])
def test_self_slash_never_reaches_inherited_host(tmp_path, command):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PI_", "SELF_SLASH_"))}
    env.update(PI_CODING_AGENT="true", PI_SESSION_ID="missing", HOME=str(tmp_path),
               AUTORENAME_STATE_DIR=str(tmp_path / "state"), PASEO_AGENT_ID="parent",
               HERDR_ENV="1", HERDR_PANE_ID="parent", SELF_SLASH_PATH_AS_IS="1")
    env.pop("ACP_RUN_AGENT", None)
    result = subprocess.run(["bash", str(ROOT / "bin/self-slash"), "--dry-run", command],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2, result.stderr
    assert not (tmp_path / ".local/state/self-slash.log").exists()


def test_autorename_missing_pi_never_renames_parent(tmp_path):
    env = dict(os.environ, PI_SESSION_ID="missing", PI_SESSION_FILE="/missing",
               AUTORENAME_STATE_DIR=str(tmp_path), CLAUDE_CODE_SESSION_ID="parent")
    result = subprocess.run([sys.executable, str(SKILL / "autorename.py"), "Title"],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert "nothing else renamed" in result.stderr


def test_autorename_uses_bridge_without_host_side_effects(native, monkeypatch, capsys):
    mod, reg = native
    spec = importlib.util.spec_from_file_location("autorename_pi_test", SKILL / "autorename.py")
    rename = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rename)
    monkeypatch.setattr(rename, "pi_native", mod)
    monkeypatch.setattr(rename, "paseo_set_name", lambda *a, **kw: pytest.fail("inherited host touched"))
    calls = []
    monkeypatch.setattr(mod, "request", lambda reg, action, **kw: calls.append((action, kw)) or {"status": "renamed"})
    monkeypatch.setenv("PASEO_AGENT_ID", "parent")
    monkeypatch.setattr(sys, "argv", ["autorename.py", "--auto", "Title"])
    assert rename.main() == 0
    assert calls == [("rename", {"title": "Title", "auto": True})]
    assert "renamed: Title" in capsys.readouterr().out
    assert rename.session_id() == reg["session_id"]
    assert rename.backend_for(reg["session_id"]) == "pi"


def test_omp_dispatch_and_title_slot_unchanged(native, monkeypatch, tmp_path):
    mod, _ = native
    spec = importlib.util.spec_from_file_location("autorename_omp_test", SKILL / "autorename.py")
    rename = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rename)
    monkeypatch.setattr(rename.pi_native, "selected", lambda: False)
    monkeypatch.setenv("OMPCODE", "1")
    monkeypatch.setattr(rename, "nearest_agent_proc", lambda: ("omp", 42))
    monkeypatch.setattr(rename, "omp_registration", lambda **kw: {"session_id": "omp-own"})
    assert rename.session_id() == "omp-own"
    file = tmp_path / "omp.jsonl"
    file.write_text(json.dumps({"type": "title", "title": "Pinned", "source": "user"}) + "\n")
    assert rename.omp_read(file) == ("Pinned", "user")


def test_native_extension_contract(tmp_path):
    # The bridge is valid JS with JSDoc API types. Copy verbatim to .mjs, NOT a
    # mocked reimplementation or a regex-transpiled approximation of the module.
    node = shutil.which("node")
    assert node, "Node required for the bridge regression contract"
    bridge = tmp_path / "bridge.mjs"
    bridge.write_text((SKILL / "pi-bridge.ts").read_text())
    script = r'''
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const bridge = (await import(pathToFileURL(process.argv[1]))).default;
process.env.AUTORENAME_STATE_DIR = process.argv[2];
delete process.env.ACP_RUN_AGENT;
let tick, cleared = 0;
globalThis.setInterval = fn => { tick = fn; return { unref() {} }; };
globalThis.clearInterval = () => { cleared++; };
const events = new Map();
let entries = [], title, draft = '', idle = false, queued = false, compactCalls = [], notifications = [];
const ctx = {
  mode: 'tui', model: {provider: 'openai', id: 'test'}, thinkingLevel: 'high',
  sessionManager: {getEntries: () => entries, getSessionId: () => 'sid', getSessionFile: () => '/file'},
  isIdle: () => idle, hasPendingMessages: () => queued,
  ui: {getEditorText: () => draft, notify: text => notifications.push(text)},
  compact: options => compactCalls.push(options),
};
const pi = {
  on: (name, fn) => events.set(name, fn),
  getSessionName: () => title,
  setSessionName: value => { title = value; entries.push({type: 'session_info', id: String(entries.length), name: value}); },
  appendEntry: (customType, data) => entries.push({type: 'custom', customType, data}),
};
const emit = name => events.get(name)?.({}, ctx);
bridge(pi);
assert.equal(tick, undefined, 'factory must not start background resources');
emit('session_start');
const root = path.join(process.env.AUTORENAME_STATE_DIR, 'pi');
const reg = () => JSON.parse(fs.readFileSync(path.join(root, `${process.pid}.json`)));
let serial = 0;
function request(fields) {
  const r = reg(), nonce = (++serial).toString(16).padStart(32, '0');
  const dir = path.join(root, r.instance);
  fs.writeFileSync(path.join(dir, `${nonce}.request.json`), JSON.stringify({
    nonce, instance: r.instance, session_id: r.session_id, session_file: r.session_file,
    expires: Date.now() + 15000, ...fields,
  }));
  tick();
  const result = path.join(dir, `${nonce}.result.json`);
  const data = JSON.parse(fs.readFileSync(result)); fs.unlinkSync(result);
  return data;
}
const compact = extra => request({action: 'compact', focus: 'keep constraints', provider: 'openai', model: 'test', thinking: 'high', ...extra});
assert.equal(request({action:'rename', title:'Auto', auto:true}).accepted, true);
assert.equal(reg().source, 'auto');
assert.equal(request({action:'rename', title:'Auto 2', auto:true}).status, 'renamed');
pi.setSessionName('Auto 2'); emit('session_info_changed'); // operator pins SAME text
assert.equal(reg().source, 'user');
assert.match(request({action:'rename', title:'No', auto:true}).status, /skipped/);
assert.equal(title, 'Auto 2');
assert.equal(request({action:'rename', title:'Explicit', auto:false}).status, 'renamed');
assert.equal(reg().source, 'user');
assert.equal(request({action:'rename', title:'Wrong', session_id:'parent'}).accepted, false);
assert.equal(request({action:'rename', title:'Wrong', instance:'stale'}).accepted, false);
assert.equal(request({action:'rename', title:'Wrong', expires:0}).accepted, false);
assert.equal(title, 'Explicit');
assert.equal(compact({model:'wrong'}).accepted, false);
draft = ' '; assert.equal(compact().accepted, false); draft = '';
emit('ui_prompt_start'); assert.equal(compact().accepted, false); emit('ui_prompt_end');
ctx.mode = 'rpc'; assert.equal(compact().accepted, false); ctx.mode = 'tui';
process.env.ACP_RUN_AGENT = '1'; assert.equal(compact().accepted, false); delete process.env.ACP_RUN_AGENT;
assert.match(compact().status, /queued/);
assert.equal(compactCalls.length, 0);
assert.equal(compact().accepted, false, 'no duplicate queued compaction');
emit('agent_end'); tick(); assert.equal(compactCalls.length, 0, 'agent_end is not idle');
idle = true; queued = true; tick(); assert.equal(compactCalls.length, 0);
queued = false; emit('agent_settled'); tick(); assert.equal(compactCalls.length, 1);
assert.equal(compactCalls[0].customInstructions, 'keep constraints');
assert.equal(reg().compact_status.status, 'running');
compactCalls[0].onComplete(); assert.equal(reg().compact_status.status, 'completed');
entries.push({type:'compaction', timestamp:new Date().toISOString()});
assert.equal(compact().accepted, false, '30 minute gap'); entries.pop();
idle = false; compact(); draft = 'new draft'; idle = true; tick();
assert.equal(reg().compact_status.status, 'refused'); assert.equal(compactCalls.length, 1); draft = '';
idle = false; compact(); ctx.model = {provider:'other', id:'test'}; emit('model_select'); idle = true; tick();
assert.equal(reg().compact_status.status, 'refused'); assert.equal(reg().provider, 'other');
ctx.model = {provider:'openai', id:'test'}; emit('model_select');
idle = false; compact(); const old = reg(); emit('session_shutdown');
assert.equal(cleared, 1); assert.equal(fs.existsSync(path.join(root, old.instance)), false);
tick(); assert.equal(compactCalls.length, 1, 'shutdown cancels queued work');
assert.equal(fs.existsSync(path.join(root, `${process.pid}.json`)), false);
'''
    result = subprocess.run([node, "--input-type=module", "-e", script, str(bridge), str(tmp_path / "state")],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
