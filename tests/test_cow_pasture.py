"""bin/cow-pasture: the retired --orca flag is a usage error and never reaches cow or orca."""
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "cow-pasture"


def run(tmp_path, *args):
    # Stubs that record any call; the script puts /opt/homebrew/bin first, so a stub only
    # proves "not called" for names that are not installed there (orca never is).
    calls = tmp_path / "calls"
    for name in ("orca", "cow"):
        stub = tmp_path / name
        stub.write_text(f"#!/bin/sh\necho {name} >> {calls}\nexit 0\n")
        stub.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "HOME": str(tmp_path)}
    r = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=30)
    return r, (calls.read_text() if calls.exists() else "")


def test_orca_flag_is_a_usage_error(tmp_path):
    r, calls = run(tmp_path, "create", "x", "--source", str(tmp_path), "--orca")
    assert r.returncode == 2
    assert "usage: cow-pasture create" in r.stdout + r.stderr
    assert "orca" not in calls and "cow" not in calls


def test_usage_does_not_advertise_orca(tmp_path):
    r, _ = run(tmp_path)
    assert r.returncode == 2
    assert "orca" not in (r.stdout + r.stderr).lower()
