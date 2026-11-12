"""First-run diagnostics must work without touching live installation state."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "bin/ade-install"


def run_isolated(tmp_path, code, *args):
    return subprocess.run(
        [sys.executable, "-I", "-B", "-c", code, str(CLI), *args],
        cwd=tmp_path, capture_output=True, text=True, timeout=15,
    )


@pytest.mark.parametrize("version", [(3, 8), (3, 9), (3, 10)])
def test_old_python_fails_before_catalog_import(tmp_path, version):
    # Simulate version detection in a fresh interpreter; deliberately forbid
    # the import that would otherwise fail on old Python's missing tomllib.
    code = '''
import builtins, runpy, sys
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name == "ade_install":
        raise AssertionError("catalog implementation imported before version check")
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
path = sys.argv[1]
sys.argv = [path, *sys.argv[2:]]
sys.version_info = VERSION
runpy.run_path(path, run_name="__main__")
'''.replace("VERSION", repr(version))
    result = run_isolated(tmp_path, code, "check")
    assert result.returncode == 2
    assert "requires Python 3.11+" in result.stderr
    assert f"running {version[0]}.{version[1]}" in result.stderr
    assert "No installation was attempted" in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""


def test_no_arguments_only_print_guidance(tmp_path):
    # Execute the real shebang on a cold tree, without -B or preimported modules.
    # A tripwire implementation would write a marker (and normally __pycache__)
    # before any possible catalog reads, probes or downloads if it were imported.
    bindir = tmp_path / "bin"
    bindir.mkdir()
    executable = bindir / "ade-install"
    executable.write_bytes(CLI.read_bytes())
    executable.chmod(0o755)
    (bindir / "ade_install.py").write_text(
        "from pathlib import Path\n"
        "Path(__file__).with_name('unexpected-import').touch()\n"
        "raise AssertionError('first-run guidance imported installation code')\n"
    )
    home = tmp_path / "home"
    home.mkdir()
    def snapshot():
        return {str(p.relative_to(tmp_path)): p.read_bytes() if p.is_file() else None
                for p in tmp_path.rglob("*")}
    before = snapshot()
    result = subprocess.run(
        [str(executable)], cwd=tmp_path, env={**os.environ, "HOME": str(home)},
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert "guidance only; no changes made" in result.stdout
    assert "./bin/ade-install apply --dry-run" in result.stdout
    assert "./bin/ade-install apply --yes --id just" in result.stdout
    assert "Nothing runs automatically" in result.stdout
    assert "bin/ade-bootstrap" in result.stdout
    assert snapshot() == before


def test_explicit_commands_keep_parser_and_validation_behavior(tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config/install.schema.json").write_bytes((REPO / "config/install.schema.json").read_bytes())
    (root / "config/install.toml").write_bytes(
        (REPO / "tests/fixtures/install_catalog/minimal.toml").read_bytes()
    )
    code = '''
import runpy, sys
path = sys.argv[1]
sys.argv = [path, *sys.argv[2:]]
runpy.run_path(path, run_name="__main__")
'''
    result = run_isolated(tmp_path, code, "check", "--root", str(root), "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ok"] is True
    invalid = run_isolated(tmp_path, code, "unknown-command")
    assert invalid.returncode == 2
    assert "invalid choice" in invalid.stderr
    assert "first-run checklist" not in invalid.stdout
