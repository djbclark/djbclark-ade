"""Pi controls: isolated files and fake API only; never import/run a live Pi."""
import importlib.util
import json
import os
import re
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
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(tmp_path / "agent"))
    monkeypatch.setattr(mod, "ancestors", lambda: [(22, "bash"), (42, "pi")])
    reg = dict(version=1, pid=42, instance="a" * 32, session_id="custom/id",
               session_file="/session.jsonl", provider="openai", model="test", thinking="high")
    mod.root().mkdir()
    (mod.root() / "42.json").write_text(json.dumps(reg))
    (mod.root() / reg["instance"]).mkdir()
    return mod, reg


def load_autorename(name, monkeypatch, mod):
    """Load autorename AFTER the fixture set AUTORENAME_STATE_DIR: its paths must follow that variable unpatched."""
    spec = importlib.util.spec_from_file_location(name, SKILL / "autorename.py")
    rename = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rename)
    monkeypatch.setattr(rename, "pi_native", mod)
    assert rename.STATE_DIR == mod.root().parent
    assert rename.OMP_DIR == mod.root().parent / "omp"
    return rename


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


@pytest.mark.parametrize("name", ["pi", "node", "bun", "omp", "claude", "codex", "opencode"])
def test_nested_unregistered_runtime_blocks_parent(native, monkeypatch, name):
    mod, _ = native
    monkeypatch.setattr(mod, "ancestors", lambda: [(30, name), (42, "pi")])
    assert mod.selected(), "unverified child must not unlock inherited host routes"
    with pytest.raises(ValueError, match="omp-bridge.ts" if name == "omp" else "no owning"):
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
    scrubbed = {k: v for k, v in os.environ.items() if not k.startswith(("PI_", "ADE_OPENCODE_", "OPENCODE_"))
                and k not in {"AI_AGENT", "OMPCODE"}}
    env = dict(scrubbed, HOME=str(tmp_path / "home"), PI_SESSION_ID="missing", PI_SESSION_FILE="/missing",
               AUTORENAME_STATE_DIR=str(tmp_path), CLAUDE_CODE_SESSION_ID="parent")
    result = subprocess.run([sys.executable, str(SKILL / "autorename.py"), "Title"],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert "nothing else renamed" in result.stderr


def test_autorename_paths_follow_state_env_unpatched(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "AUTORENAME_STATE_DIR"}
    env.update(HOME=str(tmp_path / "home"), AUTORENAME_STATE_DIR=str(tmp_path / "state"))
    code = ("import importlib.util,sys;s=importlib.util.spec_from_file_location('a',sys.argv[1]);m=importlib.util.module_from_spec(s);"
            "s.loader.exec_module(m);print(m.STATE_DIR);print(m.OMP_DIR)")
    out = subprocess.run([sys.executable, "-c", code, str(SKILL / "autorename.py")], env=env,
                         capture_output=True, text=True, timeout=20, check=True).stdout.split()
    assert out == [str(tmp_path / "state"), str(tmp_path / "state/omp")]


def test_unregistered_omp_names_omp_bridge(native, monkeypatch):
    mod, _ = native
    monkeypatch.setattr(mod, "ancestors", lambda: [(22, "bash"), (30, "omp"), (42, "pi")])
    monkeypatch.setenv("OMPCODE", "1")
    with pytest.raises(ValueError, match="omp-bridge.ts"):
        mod.registration()
    monkeypatch.setattr(mod, "ancestors", lambda: [(22, "bash"), (30, "node")])
    monkeypatch.delenv("OMPCODE")
    with pytest.raises(ValueError, match="pi-bridge.ts"):
        mod.registration()


def test_autorename_uses_bridge_without_host_side_effects(native, monkeypatch, capsys):
    mod, reg = native
    rename = load_autorename("autorename_pi_test", monkeypatch, mod)
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


@pytest.mark.parametrize("kind,sid", [("omp", "omp-own"), ("opencode", "ses_child")])
def test_nested_backend_selection_and_rename(native, monkeypatch, tmp_path, kind, sid):
    mod, _ = native
    rename = load_autorename("autorename_child_test", monkeypatch, mod)
    monkeypatch.setattr(mod, "ancestors", lambda: [(22, "bash"), (30, kind), (42, "pi")])
    monkeypatch.setenv("PI_CODING_AGENT", "true")
    monkeypatch.setenv("AI_AGENT", "pi")
    monkeypatch.setenv("PASEO_AGENT_ID", "parent")
    monkeypatch.setattr(rename, "paseo_set_name", lambda *a, **kw: pytest.fail("parent host touched"))
    monkeypatch.setattr(mod, "request", lambda *a, **kw: pytest.fail("parent Pi touched"))
    calls = []
    if kind == "omp":
        monkeypatch.setenv("OMPCODE", "1")
        file = tmp_path / "omp.jsonl"
        file.write_text(json.dumps({"type": "title", "title": "Pinned", "source": "user"}) + "\n")
        assert rename.omp_read(file) == ("Pinned", "user")
        rename.OMP_DIR.mkdir(parents=True)
        (rename.OMP_DIR / "30.json").write_text(json.dumps({"session_id": sid, "session_file": str(file)}))
        monkeypatch.setattr(rename, "_alive", lambda pid: pid == 30)
        monkeypatch.setattr(rename, "omp_set_title", lambda reg, title: calls.append((reg["pid"], title)) or True)
    else:
        monkeypatch.setenv("ADE_OPENCODE_SESSION_ID", sid)
        monkeypatch.setenv("ADE_OPENCODE_DIRECTORY", str(tmp_path))
        monkeypatch.setenv("OPENCODE_SESSION_ID", sid)
        monkeypatch.setattr(rename, "opencode_current_title", lambda sid: "Old")
        monkeypatch.setattr(rename, "opencode_set_title", lambda sid, title: calls.append((sid, title)) or True)
    assert mod.child_backend() == (kind, 30, sid)
    assert not mod.selected()  # actual selection, no selector stub
    assert rename.session_id() == sid
    assert rename.backend_for(sid) == kind
    monkeypatch.setattr(sys, "argv", ["autorename.py", "--session-id", "custom/id", "No"])
    assert rename.main() == 2
    assert not calls
    monkeypatch.setattr(sys, "argv", ["autorename.py", "Child title"])
    assert rename.main() == 0
    assert calls == [(30 if kind == "omp" else sid, "Child title")]
    # A nearer unknown runtime or Pi must never unlock this child/ancestor route.
    for barrier in ("node", "bun", "pi"):
        monkeypatch.setattr(mod, "ancestors", lambda: [(29, barrier), (30, kind), (42, "pi")])
        assert mod.selected()
        assert rename.main() == 2
    assert len(calls) == 1


def test_invalid_child_scope_and_pi_record_fail_closed(native, monkeypatch, tmp_path):
    mod, _ = native
    monkeypatch.setattr(mod, "ancestors", lambda: [(30, "opencode"), (42, "pi")])
    monkeypatch.setenv("ADE_OPENCODE_SESSION_ID", "ses_child")
    monkeypatch.setenv("ADE_OPENCODE_DIRECTORY", "relative")
    assert mod.selected()
    monkeypatch.setenv("ADE_OPENCODE_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_other")
    assert mod.selected()
    monkeypatch.delenv("OPENCODE_SESSION_ID")
    assert not mod.selected()
    (mod.root() / "30.json").write_text("{}")
    assert mod.selected(), "a mismatched Pi record must not fall back to child or host"
    with pytest.raises(ValueError, match="identity mismatch"):
        mod.registration()


def test_no_pi_markers_preserves_legacy_selection(native, monkeypatch):
    mod, _ = native
    for key in ("PI_SESSION_ID", "PI_SESSION_FILE", "PI_CODING_AGENT", "AI_AGENT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(mod, "ancestors", lambda: pytest.fail("legacy path must not probe Pi ancestry"))
    assert not mod.selected()
    assert mod.child_backend() is None


def test_legacy_omp_still_renames_its_host_without_pi_markers(native, monkeypatch):
    mod, _ = native
    for key in ("PI_SESSION_ID", "PI_SESSION_FILE", "PI_CODING_AGENT", "AI_AGENT"):
        monkeypatch.delenv(key, raising=False)
    rename = load_autorename("autorename_legacy_test", monkeypatch, mod)
    monkeypatch.setenv("OMPCODE", "1")
    monkeypatch.setattr(rename, "nearest_agent_proc", lambda: ("omp", 30))
    rename.OMP_DIR.mkdir(parents=True)
    (rename.OMP_DIR / "30.json").write_text(json.dumps({"session_id": "omp-own"}))
    monkeypatch.setattr(rename, "_alive", lambda pid: pid == 30)
    monkeypatch.setattr(rename, "omp_read", lambda file: (None, None))
    calls = []
    monkeypatch.setattr(rename, "omp_set_title", lambda reg, title: calls.append(("omp", reg["pid"])) or True)
    monkeypatch.setattr(rename, "paseo_set_name", lambda title, **kw: calls.append(("host", title)) or "")
    monkeypatch.setattr(sys, "argv", ["autorename.py", "Legacy title"])
    assert rename.main() == 0
    assert calls == [("omp", 30), ("host", "Legacy title")]


@pytest.mark.parametrize("owner,marked,expected", [
    ("opencode", True, 0), ("pi", True, 2), ("node", True, 2),
    ("opencode", False, 0),
])
def test_self_slash_resolves_native_child_before_inherited_pi(tmp_path, owner, marked, expected):
    tools = tmp_path / "tools"
    tools.mkdir()
    ps = tools / "ps"
    ps.write_text(f"#!{sys.executable}\n" + '''
import os, subprocess
# pi_native's ps child -> helper -> tool shell. Only process observation is
# faked; run the real selection and both real self-slash/helper entrypoints.
result = subprocess.run(['/bin/ps', '-p', str(os.getppid()), '-o', 'ppid='],
                        capture_output=True, text=True, check=True)
shell = int(result.stdout.strip())
print(f'{shell} 42000 bash')
print('42000 42001 ' + os.environ['TEST_OWNER'])
print('42001 1 pi')
''')
    ps.chmod(0o755)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("PI_", "SELF_SLASH_")) and k not in {"AI_AGENT", "ACP_RUN_AGENT", "OPENCODE_SESSION_ID"}}
    env.update(PATH=str(tools) + os.pathsep + os.environ["PATH"],
               HOME=str(tmp_path), AUTORENAME_STATE_DIR=str(tmp_path / "state"),
               SELF_SLASH_PATH_AS_IS="1", TEST_OWNER=owner,
               ADE_OPENCODE_SESSION_ID="ses_child", ADE_OPENCODE_DIRECTORY=str(tmp_path),
               PASEO_AGENT_ID="parent", HERDR_ENV="1", HERDR_PANE_ID="parent")
    if marked:
        env.update(PI_CODING_AGENT="true", AI_AGENT="pi", PI_SESSION_ID="parent", PI_SESSION_FILE="/parent")
    result = subprocess.run(["bash", str(ROOT / "bin/self-slash"), "--dry-run", "/compact"],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == expected, result.stderr
    if expected == 0:
        assert "native Go guard to compact ses_child" in result.stdout
    assert not (tmp_path / ".local/state/self-slash.log").exists()
    # Verified nested child must not leak unsupported commands into host fallback.
    if marked and owner == "opencode":
        for command in ("/new", "/model foo", "arbitrary text"):
            result = subprocess.run(["bash", str(ROOT / "bin/self-slash"), "--dry-run", command],
                                    env=env, capture_output=True, text=True, timeout=10)
            assert result.returncode == 2
            assert "no inherited host fallback" in result.stderr


@pytest.mark.parametrize("ch", ["\x85", "\x9f", "\u2028", "\u2029", "\u202a", "\u202e", "\u2066", "\u2069", "\x07", "\x7f",
                                "\u200e", "\u200f", "\u061c", "\u200b", "\u2060", "\ufeff"])
def test_clean_strips_controls_like_the_bridge_rejects(native, monkeypatch, ch):
    # Cc, Cf, Zl and Zp: the invisible bidi marks, zero-width characters and BOM too (2026-11-03, audit A12)
    rename = load_autorename("autorename_clean_test", monkeypatch, native[0])
    assert rename.clean(f"a{ch}b") == "a b"
    assert rename.clean(ch) == ""


JOINED = ["می\u200cخواهم", "👨\u200d👩\u200d👧", "क्\u200dष", "Café résumé 🚀 naïve – 日本語"]


@pytest.mark.parametrize("text", JOINED)
def test_clean_keeps_normal_text_and_zero_width_joiners(native, monkeypatch, text):
    # ZWNJ/ZWJ are text (Persian, Devanagari, emoji sequences), not invisible controls
    rename = load_autorename("autorename_clean_keep_test", monkeypatch, native[0])
    assert rename.clean(text) == text


def test_omp_bridge_rejects_the_same_invisible_set_and_keeps_joiners():
    # omp-bridge.ts is TypeScript (not loadable as .mjs): run its validation regex, as written in the file, in Node
    node = shutil.which("node")
    assert node, "Node required for the bridge regression contract"
    literal = re.search(r"if \((/.+?/u)\.test\(title\)\) throw new Error\(\"invalid title\"\)", (SKILL / "omp-bridge.ts").read_text())
    assert literal, "omp-bridge.ts no longer validates the title"
    script = f"""const bad = {literal.group(1)};
const ok = {json.dumps(JOINED)}, no = {json.dumps(["a\u200eb", "a\u200fb", "a\u061cb", "a\u200bb", "a\u2060b", "a\ufeffb", "a\u2028b", "a\u202eb", "a\x07b", "a\x85b"])};
console.log(JSON.stringify([ok.map(t => bad.test(t)), no.map(t => bad.test(t))]));"""
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30, check=True).stdout
    kept, rejected = json.loads(out)
    assert kept == [False] * len(JOINED) and rejected == [True] * 10


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
for (const bad of ['a\u0085b', 'a\u009fb', 'a\u2028b', 'a\u2029b', 'a\u202eb', 'a\u2066b', 'a\u2069b', 'a\u0007b', 'a\u007fb',
  'a\u200eb', 'a\u200fb', 'a\u061cb', 'a\u200bb', 'a\u2060b', 'a\ufeffb']) {
  assert.equal(request({action:'rename', title:bad, auto:false}).accepted, false, JSON.stringify(bad));
}
for (const good of ['\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645', '\u{1F468}\u200d\u{1F469}\u200d\u{1F467}', '\u0915\u094d\u200d\u0937']) {
  assert.equal(request({action:'rename', title:good, auto:false}).accepted, true, JSON.stringify(good));
  assert.equal(title, good);
}
assert.equal(request({action:'rename', title:'Explicit', auto:false}).status, 'renamed');
assert.equal(title, 'Explicit');
assert.equal(request({action:'rename', title:'Wrong', session_id:'parent'}).accepted, false);
assert.equal(request({action:'rename', title:'Wrong', instance:'stale'}).accepted, false);
assert.equal(request({action:'rename', title:'Wrong', expires:0}).accepted, false);
assert.equal(title, 'Explicit');
assert.equal(compact({model:'wrong'}).accepted, false);
draft = ' '; assert.equal(compact().accepted, false); draft = '';
emit('ui_prompt_start'); assert.equal(compact().accepted, false); emit('ui_prompt_end');
ctx.mode = 'rpc'; assert.equal(compact().accepted, false); ctx.mode = 'tui';
process.env.ACP_RUN_AGENT = '1'; assert.equal(compact().accepted, false); delete process.env.ACP_RUN_AGENT;
// Built-in selectors replace the main editor but emit NO ui_prompt_start.
// Their search text is not getEditorText(): this models the installed contract,
// not an invented public focus API or an extension dialog approximation.
let activeScreen = {kind:'main-editor', search:''};
for (const kind of ['model-selector', 'settings-selector', 'session-selector', 'tree-selector', 'custom-screen']) {
  activeScreen = {kind, search:'operator is typing here'};
  draft = ''; idle = true; queued = false;
  assert.notEqual(activeScreen.kind, 'main-editor');
  assert.notEqual(activeScreen.search, '');
  assert.equal(ctx.ui.getEditorText(), '', 'hidden main editor stays empty');
  const receipt = compact();
  assert.equal(receipt.accepted, false);
  assert.equal(receipt.status, 'refused');
  assert.match(receipt.error, /active main-editor focus cannot be proven/);
  emit('agent_settled'); tick();
  assert.equal(compactCalls.length, 0);
  assert.equal(reg().compact_status, null, 'refusal is not queued or executed');
}
activeScreen = {kind:'main-editor', search:''};
for (const busy of [true, false]) {
  idle = !busy; queued = busy;
  assert.equal(compact().accepted, false, 'even an apparently safe editor cannot prove focus');
}
ctx.model = {provider:'other', id:'test'}; emit('model_select');
assert.match(compact().error, /model\/reasoning changed/);
assert.equal(reg().provider, 'other');
ctx.model = {provider:'openai', id:'test'}; emit('model_select');
assert.equal(request({action:'rename', title:'Still works', auto:false}).status, 'renamed');
const old = reg(); emit('session_shutdown');
assert.equal(cleared, 1); assert.equal(fs.existsSync(path.join(root, old.instance)), false);
tick(); assert.equal(compactCalls.length, 0, 'shutdown cannot execute refused work');
assert.equal(fs.existsSync(path.join(root, `${process.pid}.json`)), false);
// Actual replacement instance: old runtime requests cannot cross a reload.
bridge(pi); emit('session_start');
assert.notEqual(reg().instance, old.instance);
assert.equal(request({action:'rename', title:'Stale', instance:old.instance}).accepted, false);
assert.equal(request({action:'rename', title:'Replacement', auto:false}).status, 'renamed');
assert.equal(compact().accepted, false);
emit('session_shutdown'); assert.equal(cleared, 2);
'''
    result = subprocess.run([node, "--input-type=module", "-e", script, str(bridge), str(tmp_path / "state")],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
