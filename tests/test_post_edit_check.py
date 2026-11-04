"""bin/post-edit-check: narrow syntax check after an edit; silent on success, exit 2 on problems."""
import ast
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "post-edit-check"
HAS_RUFF = shutil.which("ruff") is not None
HAS_JQ = shutil.which("jq") is not None
HAS_BASH = shutil.which("bash") is not None


def run(args=(), stdin=None, env=None, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], input=stdin, capture_output=True,
                          text=True, timeout=30, env=env, cwd=cwd)


def hook(payload, **kw):
    return run(["--hook"], stdin=payload if isinstance(payload, str) else json.dumps(payload), **kw)


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def stub_env(tmp_path, tools=()):
    """PATH holding only symlinks to the named tools (python is run by absolute path)."""
    d = tmp_path / "stubbin"
    d.mkdir(exist_ok=True)
    for t in tools:
        src = shutil.which(t)
        if src and not (d / t).exists():
            (d / t).symlink_to(src)
    return dict(os.environ, PATH=str(d))


def test_script_is_py39_syntax():
    ast.parse(SCRIPT.read_text(), feature_version=(3, 9))


def test_executable():
    assert os.access(SCRIPT, os.X_OK)


@pytest.mark.parametrize("name,good,bad", [
    ("a.py", "x = 1\nprint(x)\n", "def f(:\n  pass\n"),
    ("a.sh", "echo hi\n", "if then fi (\n"),
    ("a.json", '{"a": 1}\n', '{"a": }\n'),
    ("a.toml", 'a = 1\n', 'a = = 1\n'),
])
def test_good_and_bad(tmp_path, name, good, bad):
    if name.endswith(".sh") and not HAS_BASH:
        pytest.skip("no bash")
    if name.endswith(".toml") and sys.version_info < (3, 11):
        pytest.skip("no tomllib")
    ok = run([write(tmp_path, "ok_" + name, good)])
    assert (ok.returncode, ok.stdout, ok.stderr) == (0, "", "")
    r = run([write(tmp_path, "bad_" + name, bad)])
    assert r.returncode == 2 and r.stderr.strip() and r.stdout == ""


@pytest.mark.skipif(not HAS_RUFF, reason="no ruff")
def test_ruff_undefined_name_and_no_style_nag(tmp_path):
    assert run([write(tmp_path, "u.py", "print(undefined_name)\n")]).returncode == 2
    # style problems (unused import, long line) are outside the narrow select list
    assert run([write(tmp_path, "s.py", "import os\nx=1;y=2\n")]).returncode == 0


def test_shebangs_and_tmpl(tmp_path):
    p = write(tmp_path, "tool", "#!/usr/bin/env python3\ndef f(:\n")
    assert run([p]).returncode == 2
    if HAS_BASH:
        assert run([write(tmp_path, "sh1", "#!/bin/bash\nif then (\n")]).returncode == 2
    assert run([write(tmp_path, "x.py.tmpl", "def f(:\n")]).returncode == 0
    assert run([write(tmp_path, "notes.txt", "def f(:\n")]).returncode == 0


def test_missing_and_large_skipped(tmp_path):
    assert run([str(tmp_path / "gone.py")]).returncode == 0
    big = write(tmp_path, "big.py", "def f(:\n" + "#" * (2 * 1024 * 1024 + 10))
    assert run([big]).returncode == 0


def test_py_fallback_without_ruff(tmp_path):
    if sys.version_info < (3, 10):
        pytest.skip("compile() fallback is skipped on python < 3.10")
    env = stub_env(tmp_path)  # empty PATH: no ruff
    bad = write(tmp_path, "b.py", "def f(:\n")
    r = run([bad], env=env)
    assert r.returncode == 2 and "SyntaxError" in r.stderr
    assert not (tmp_path / "__pycache__").exists()
    assert run([write(tmp_path, "g.py", "x = 1\n")], env=env).returncode == 0


def test_json_fallback_without_jq(tmp_path):
    env = stub_env(tmp_path)
    assert run([write(tmp_path, "b.json", "{")], env=env).returncode == 2
    assert run([write(tmp_path, "g.json", "{}")], env=env).returncode == 0


@pytest.mark.parametrize("rel", ["tsconfig.json", "tsconfig.build.json", "jsconfig.json", "a.jsonc",
                                 ".vscode/settings.json", "devcontainer.json", ".devcontainer.json"])
@pytest.mark.parametrize("nojq", [False, True])
def test_jsonc_files_are_skipped(tmp_path, rel, nojq):
    (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
    f = write(tmp_path, rel, '{\n // c\n "a": {"b": 1,},\n}\n')
    r = run([f], env=stub_env(tmp_path) if nojq else None)
    assert r.returncode == 0 and r.stderr == ""


def test_sh_skipped_without_bash(tmp_path):
    assert run([write(tmp_path, "b.sh", "if then (\n")], env=stub_env(tmp_path)).returncode == 0


def test_budget_exhaustion_is_silent_and_fast(tmp_path):
    d = tmp_path / "slow"
    d.mkdir()
    ruff = d / "ruff"
    ruff.write_text("#!/bin/sh\nexec sleep 30\n")
    ruff.chmod(0o755)
    sleep = shutil.which("sleep")
    (d / "sleep").symlink_to(sleep)
    env = dict(os.environ, PATH=str(d))
    f = write(tmp_path, "s.py", "def f(:\n")
    t0 = time.monotonic()
    r = run(["--budget", "0.5", f], env=env)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")
    assert time.monotonic() - t0 < 10


def test_hook_claude_payload_and_cwd(tmp_path):
    write(tmp_path, "rel.py", "def f(:\n")
    r = hook({"cwd": str(tmp_path), "tool_name": "Write", "tool_input": {"file_path": "rel.py"}})
    assert r.returncode == 2 and "rel.py" in r.stderr
    ok = write(tmp_path, "ok.py", "x = 1\n")
    r = hook({"tool_input": {"file_path": ok}})
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


def test_hook_codex_patch(tmp_path):
    write(tmp_path, "new.py", "def f(:\n")
    write(tmp_path, "fine.py", "x = 1\n")
    patch = ("*** Begin Patch\n*** Update File: fine.py\n@@\n-x\n+x = 1\n"
             "*** Add File: new.py\n+def f(:\n*** Delete File: gone.py\n*** End Patch\n")
    r = hook({"cwd": str(tmp_path), "tool_input": {"command": ["apply_patch", patch]}})
    assert r.returncode == 2 and "new.py" in r.stderr and "fine.py" not in r.stderr
    r = hook({"cwd": str(tmp_path), "tool_input": {"input": patch.replace("Add File: new.py", "Move to: fine.py")}})
    assert r.returncode == 0


@pytest.mark.parametrize("stdin", ["", "not json", "[1,2]", '{"tool_input": 5}', '{"tool_input": {"file_path": 7}}'])
def test_hook_malformed_stdin_exits_0(stdin):
    r = hook(stdin)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


def test_usage_errors():
    assert run([]).returncode == 64
    assert run(["--bogus", "x"]).returncode == 64
    assert run(["--budget", "abc", "x"]).returncode == 64
    assert hook({"tool_input": {}}).returncode == 0


def test_output_capped(tmp_path):
    env = stub_env(tmp_path)
    files = [write(tmp_path, "b%d.py" % i, "def f(:\n") for i in range(60)]
    r = run(files, env=env)
    assert r.returncode == 2 and len(r.stderr.splitlines()) <= 41
