"""bin/load-watch install through bin/ade_sched.py (Linux systemd + Mac launchd templates)."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LW = ROOT / "bin" / "load-watch"


def run(tmp_path, *args, path=None):
    env = dict(
        os.environ,
        LW_STATE_DIR=str(tmp_path / "state"),
        LW_REGISTRY=str(tmp_path / "ci-only.tsv"),
        ADE_SCHED_UNIT_DIR=str(tmp_path / "units"),
        ADE_SCHED_LAUNCH_AGENTS=str(tmp_path / "agents"),
        HOME=str(tmp_path / "home"),
    )
    if path is not None:
        env["PATH"] = path
    return subprocess.run(
        [sys.executable, str(LW), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_install_systemd_dry_run(tmp_path):
    r = run(tmp_path, "install", "--backend", "systemd", "--dry-run", "--ade", str(ROOT))
    assert r.returncode == 0, r.stderr
    assert "OnUnitActiveSec=20s" in r.stdout and "AccuracySec=1s" in r.stdout
    assert f"{ROOT}/bin/load-watch" in r.stdout and "__ADE__" not in r.stdout and "__HOME__" not in r.stdout
    assert not (tmp_path / "units").exists()


def test_install_launchd_dry_run_fills_paths(tmp_path):
    r = run(tmp_path, "install", "--backend", "launchd", "--dry-run", "--ade", str(ROOT))
    assert r.returncode == 0, r.stderr
    assert f"<string>{ROOT}/bin/load-watch</string>" in r.stdout
    assert f"{tmp_path}/home/.local/state/load-watch/launchd.out" in r.stdout


def test_install_cron_refused_69(tmp_path):
    r = run(tmp_path, "install", "--backend", "cron", "--dry-run", "--ade", str(ROOT))
    assert r.returncode == 69
    assert "systemd" in r.stderr and "Traceback" not in r.stderr


def test_guard_reset_without_launchctl(tmp_path):
    empty = tmp_path / "nobin"
    empty.mkdir()
    r = run(tmp_path, "guard", "reset", "com.example.x", path=str(empty))
    assert r.returncode == 69
    assert "the launchd job guard is macOS only" in r.stderr and "Traceback" not in r.stderr
