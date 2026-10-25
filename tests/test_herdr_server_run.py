"""bin/herdr-server-run: "already running" after a server handoff is a clean exit, everything else passes through
(2026-10-25: dev.herdr.server looped 24 times in 4 minutes). A fake `herdr` stands in; the real server is never run."""
import os
import subprocess
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent / "bin" / "herdr-server-run"


def run(tmp_path, body, *args):
    fake = tmp_path / "herdr"
    fake.write_text("#!/bin/bash\n" + body)
    fake.chmod(0o755)
    env = dict(os.environ, HERDR_BIN=str(fake), TMPDIR=str(tmp_path))
    return subprocess.run([str(RUN), *args], capture_output=True, text=True, env=env, timeout=30)


def test_already_running_exits_zero(tmp_path):
    r = run(tmp_path, 'echo "error: herdr server is already running"; exit 1\n')
    assert r.returncode == 0, r.stderr
    assert "already running" in r.stdout + r.stderr


def test_other_failures_pass_through(tmp_path):
    assert run(tmp_path, 'echo "error: bind failed"; exit 1\n').returncode == 1
    assert run(tmp_path, 'echo "already running"; exit 2\n').returncode == 2  # wrong code: not the handoff case
    assert run(tmp_path, "exit 0\n").returncode == 0


def test_arguments_reach_the_server_and_nothing_else_runs(tmp_path):
    log = tmp_path / "argv"
    r = run(tmp_path, f'printf "%s\\n" "$@" > {log}; exit 0\n', "--handoff-import", "x")
    assert r.returncode == 0
    assert log.read_text().split() == ["server", "--handoff-import", "x"]


def test_no_temp_files_left(tmp_path):
    run(tmp_path, "exit 0\n")
    assert not list(tmp_path.glob("herdr-server-run.*"))
