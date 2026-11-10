"""Only explicit Just acquisition may precede an explicit installation preview."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))
import ade_install as ai


@pytest.fixture
def layout(tmp_path):
    root = tmp_path / "repo with spaces"
    (root / "bin").mkdir(parents=True)
    (root / "justfile").write_text("# fixture\n")
    (root / "bin/ade-user-install").write_text("# fixture helper, never executed\n")
    return root, tmp_path / "user bin"


def result(rc=0, out=""):
    return subprocess.CompletedProcess([], rc, out, "")


@pytest.mark.parametrize("present", [False, True])
def test_default_only_plans_metadata(layout, monkeypatch, present):
    root, prefix = layout
    forbidden = Mock(side_effect=AssertionError("dry run executed a command"))
    monkeypatch.setattr(ai.subprocess, "run", forbidden)
    found = str(root / "existing just") if present else None
    report, rc = ai.bootstrap_just(root=root, prefix=prefix, find_just=lambda: found)
    assert rc == 0
    assert report["mode"] == "dry-run"
    assert report["just_status"] == ("present-unverified" if present else "missing")
    assert report["setup_complete"] is False
    assert report["preview_argv"][-2:] == ["install", "--dry-run"]
    assert ("install_argv" in report) is not present
    assert not prefix.exists()
    forbidden.assert_not_called()


def test_missing_just_acquires_verifies_then_previews_with_exact_argv(layout):
    root, prefix = layout
    calls = []
    original_path = os.environ.get("PATH")
    def runner(argv, cwd, env):
        calls.append((argv, cwd, env.get("PATH")))
        if len(calls) == 2:
            return result(out="just 1.99.0\n")
        return result(out="fixture installation preview\n")
    report, rc = ai.bootstrap_just(root=root, prefix=prefix, yes=True,
                                   find_just=lambda: None, runner=runner)
    assert rc == 0
    assert [c[0] for c in calls] == [
        [sys.executable, "-I", str(root / "bin/ade-user-install"), "just", "--prefix", str(prefix)],
        [str(prefix / "just"), "--version"],
        [str(prefix / "just"), "--justfile", str(root / "justfile"), "install", "--dry-run"],
    ]
    assert all(c[1] == root for c in calls)
    assert calls[-1][2].split(os.pathsep)[0] == str(prefix)
    assert os.environ.get("PATH") == original_path
    assert report["status"] == "preview-complete"
    assert report["just_status"] == "ready"
    assert report["setup_complete"] is False
    assert "--yes" not in report["preview_argv"]


@pytest.mark.parametrize("outcome", [result(7), OSError("missing helper"), subprocess.TimeoutExpired([], 300)])
def test_failed_acquisition_never_falls_through(layout, outcome):
    root, prefix = layout
    runner = Mock(side_effect=[outcome])
    report, rc = ai.bootstrap_just(root=root, prefix=prefix, yes=True,
                                   find_just=lambda: None, runner=runner)
    assert rc == 1 and report["status"] == "acquisition-failed"
    assert report["just_status"] == "unknown"  # failed acquisition may have left partial output
    assert runner.call_count == 1
    assert report["setup_complete"] is False


@pytest.mark.parametrize("outcome,status", [
    (result(1), "broken"), (result(out="not Just"), "unknown"),
    (OSError("not executable"), "unknown"), (subprocess.TimeoutExpired([], 300), "unknown"),
])
def test_existing_broken_or_unknown_just_is_not_replaced(layout, outcome, status):
    root, prefix = layout
    prefix.mkdir()
    executable = prefix / "just"
    executable.write_text("existing binary placeholder")
    runner = Mock(side_effect=[outcome])
    report, rc = ai.bootstrap_just(root=root, prefix=prefix, yes=True,
                                   find_just=lambda: None, runner=runner)
    assert rc == 1 and report["just_status"] == status
    assert "install_argv" not in report
    assert runner.call_args.args[:2] == ([str(executable), "--version"], root)
    assert runner.call_count == 1
    assert executable.read_text() == "existing binary placeholder"


def test_missing_after_acquisition_and_preview_failure_stop(layout):
    root, prefix = layout
    runner = Mock(side_effect=[result(), OSError("Just still absent")])
    report, rc = ai.bootstrap_just(root=root, prefix=prefix, yes=True,
                                   find_just=lambda: None, runner=runner)
    assert rc == 1 and report["just_status"] == "unknown"
    assert runner.call_count == 2
    runner = Mock(side_effect=[result(out="just 1.99.0"), result(9)])
    report, rc = ai.bootstrap_just(root=root, prefix=prefix, yes=True,
                                   find_just=lambda: str(root / "existing just"), runner=runner)
    assert rc == 1 and report["status"] == "preview-failed"
    assert report["setup_complete"] is False


def test_invalid_root_stops_before_discovery(tmp_path):
    finder = Mock(side_effect=AssertionError("invalid root queried PATH"))
    report, rc = ai.bootstrap_just(root=tmp_path, find_just=finder, yes=True)
    assert rc == 1 and report["status"] == "invalid-root"
    finder.assert_not_called()


def snapshot(root):
    return {str(p.relative_to(root)): (os.readlink(p) if p.is_symlink()
            else p.read_bytes() if p.is_file() else None) for p in root.rglob("*")}


@pytest.mark.parametrize("args", [[], ["--dry-run"], ["--yes", "--dry-run"]])
def test_cold_cli_preview_has_no_writes_or_process_effects(layout, tmp_path, args):
    root, prefix = layout
    for name in ("ade-install", "ade_install.py", "ade_install_catalog.py", "ade_config.py", "model_tiers.py"):
        shutil.copyfile(REPO / "bin" / name, root / "bin" / name)
    cli = root / "bin/ade-install"
    cli.chmod(0o755)
    # PATH can start the real shebang, but contains no Just/provider/network tools.
    path = tmp_path / "path"
    path.mkdir()
    (path / "python3").symlink_to(sys.executable)
    home = tmp_path / "home"
    home.mkdir()
    before = snapshot(tmp_path)
    run = subprocess.run([str(cli), "--roo=" + str(root), "bootstrap", "--prefix", str(prefix), "--json", *args],
                         cwd=tmp_path, env={**os.environ, "HOME": str(home), "PATH": str(path)},
                         capture_output=True, text=True, timeout=15)
    assert run.returncode == (2 if "--yes" in args else 0), run.stderr
    if run.returncode == 0:
        payload = json.loads(run.stdout)
        assert payload["just_status"] == "missing"
        assert payload["status"] == "dry-run"
        assert payload["preview_argv"][-1] == "--dry-run"
    assert snapshot(tmp_path) == before


@pytest.mark.skipif(shutil.which("just") is None, reason="Just development dependency unavailable")
def test_real_just_forwards_explicit_install_preview(layout, tmp_path):
    root, prefix = layout
    recipe = (REPO / "justfile").read_text().split("\ninstall *args:\n", 1)[1].split("\nupdate ", 1)[0]
    (root / "justfile").write_text('root := justfile_directory()\ninstall *args:\n' + recipe)
    capture = tmp_path / "argv.json"
    cli = root / "bin/ade-install"
    cli.write_text("#!" + sys.executable + "\nimport json,sys\nfrom pathlib import Path\n"
                   + "Path(" + repr(str(capture)) + ").write_text(json.dumps(sys.argv[1:]))\n")
    cli.chmod(0o755)
    just = shutil.which("just")
    def runner(argv, cwd, env):
        return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=15)
    report, rc = ai.bootstrap_just(root=root, prefix=prefix, yes=True, find_just=lambda: just, runner=runner)
    assert rc == 0, report
    assert json.loads(capture.read_text()) == ["apply", "--root", str(root), "--dry-run"]
    assert report["setup_complete"] is False
