"""Tests for bin/verifycmd: register argv, run under deadline, exit table 0/1/2/4/75/124.

Hermetic: VERIFYCMD_STATE_DIR temp dir, stub DEADLINE_BIN / VERIFYCMD_BG, no real daemon.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "verifycmd"
DROP = ("VERIFYCMD_STATE_DIR", "VERIFYCMD_BG", "VERIFYCMD_NO_BG", "DEADLINE_BIN",
        "DEADLINE_NAME", "PASEO_AGENT_ID")


class World:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.state = tmp / "verifycmd-state"
        self.ws = tmp / "workspace"
        self.ws.mkdir()
        self.log = tmp / "calls.log"
        # passthrough deadline: run the command after --, optionally force an rc via marker file
        (tmp / "deadline").write_text(
            "#!/bin/sh\n"
            'echo "DEADLINE $@" >> "$VC_LOG"\n'
            'while [ $# -gt 0 ]; do\n'
            '  if [ "$1" = "--" ]; then shift; break; fi\n'
            '  shift\n'
            'done\n'
            'if [ -f "$VC_DEADLINE_RC" ]; then rc=$(cat "$VC_DEADLINE_RC"); "$@" >/dev/null 2>&1 || true; exit "$rc"; fi\n'
            'exec "$@"\n'
        )
        (tmp / "deadline").chmod(0o755)
        # bg that can refuse with 75
        (tmp / "bg").write_text(
            "#!/bin/sh\n"
            'echo "BG $@" >> "$VC_LOG"\n'
            'if [ -f "$VC_BG_RC" ]; then exit "$(cat "$VC_BG_RC")"; fi\n'
            'exec "$@"\n'
        )
        (tmp / "bg").chmod(0o755)
        self.env = {k: v for k, v in os.environ.items() if k not in DROP}
        self.env.update(
            VERIFYCMD_STATE_DIR=str(self.state),
            DEADLINE_BIN=str(tmp / "deadline"),
            VERIFYCMD_BG=str(tmp / "bg"),
            VC_LOG=str(self.log),
            VC_DEADLINE_RC=str(tmp / "deadline-rc"),
            VC_BG_RC=str(tmp / "bg-rc"),
            PASEO_AGENT_ID="agent-1",
            PATH=f"{tmp}{os.pathsep}{os.environ.get('PATH', '')}",
        )

    def run(self, *args: str, **extra) -> subprocess.CompletedProcess:
        env = {**self.env, **{k: str(v) for k, v in extra.items()}}
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True, text=True, env=env, timeout=30,
        )

    def record(self, agent_id: str = "agent-1") -> dict:
        return json.loads((self.state / f"{agent_id}.json").read_text())

    def set_deadline_rc(self, rc: int | None) -> None:
        p = self.tmp / "deadline-rc"
        if rc is None:
            p.unlink(missing_ok=True)
        else:
            p.write_text(str(rc))

    def set_bg_rc(self, rc: int | None) -> None:
        p = self.tmp / "bg-rc"
        if rc is None:
            p.unlink(missing_ok=True)
        else:
            p.write_text(str(rc))


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_register_status_clear(world: World) -> None:
    r = world.run("register", "--workspace", str(world.ws), "--", "true")
    assert r.returncode == 0, r.stderr
    body = json.loads(r.stdout)
    assert body["state"] == "armed"
    assert body["argv"] == ["true"]
    rec = world.record()
    assert rec.get("version") == 1
    assert rec.get("attempt") == 0
    assert rec.get("max_attempts") == 3

    s = world.run("status", "--json")
    assert s.returncode == 0
    assert json.loads(s.stdout)["agent_id"] == "agent-1"

    c = world.run("clear")
    assert c.returncode == 0
    assert world.run("status").returncode == 2


def test_register_refuses_cwd_outside_workspace(world: World) -> None:
    outside = world.tmp / "outside"
    outside.mkdir()
    r = world.run("register", "--workspace", str(world.ws), "--cwd", str(outside), "--", "true")
    assert r.returncode == 2
    assert "outside workspace" in r.stderr


def test_register_refuses_empty_argv(world: World) -> None:
    r = world.run("register", "--workspace", str(world.ws), "--")
    assert r.returncode == 2
    assert "non-empty argv" in r.stderr


def test_register_clamps_max_attempts(world: World) -> None:
    r = world.run("register", "--workspace", str(world.ws), "--max-attempts", "99", "--", "true")
    assert r.returncode == 0
    assert world.record()["max_attempts"] == 3


def test_run_once_pass_exit_0(world: World) -> None:
    assert world.run("register", "--workspace", str(world.ws), "--", "true").returncode == 0
    r = world.run("run-once")
    assert r.returncode == 0, (r.stdout, r.stderr)
    out = json.loads(r.stdout)
    assert out["runner_rc"] == 0
    assert out["state"] == "passed"
    assert world.record()["attempt"] == 1
    # wrapped under stub deadline + bg
    calls = world.log.read_text()
    assert "DEADLINE" in calls
    assert "BG" in calls


def test_run_once_fail_exit_1_then_exhausted_4(world: World) -> None:
    assert world.run("register", "--workspace", str(world.ws), "--max-attempts", "2",
                     "--", "false").returncode == 0
    r1 = world.run("run-once")
    assert r1.returncode == 1, (r1.stdout, r1.stderr)
    assert world.record()["state"] == "armed"
    assert world.record()["attempt"] == 1

    r2 = world.run("run-once")
    assert r2.returncode == 4, (r2.stdout, r2.stderr)
    assert world.record()["state"] == "failed"
    assert world.record()["attempt"] == 2

    # terminal without re-arm
    r3 = world.run("run-once")
    assert r3.returncode == 2
    assert "failed" in r3.stderr


def test_run_once_deadline_124_consumes_attempt(world: World) -> None:
    assert world.run("register", "--workspace", str(world.ws), "--max-attempts", "3",
                     "--", "true").returncode == 0
    world.set_deadline_rc(124)
    r = world.run("run-once")
    assert r.returncode == 124, (r.stdout, r.stderr)
    rec = world.record()
    assert rec["attempt"] == 1
    assert rec["state"] == "armed"
    assert rec["last_rc"] == 124


def test_run_once_bg_75_does_not_consume_attempt(world: World) -> None:
    assert world.run("register", "--workspace", str(world.ws), "--", "true").returncode == 0
    world.set_bg_rc(75)
    # bg exits 75 before exec; stub deadline still runs bg and returns its rc
    r = world.run("run-once")
    assert r.returncode == 75, (r.stdout, r.stderr)
    rec = world.record()
    assert rec["attempt"] == 0
    assert rec["state"] == "armed"
    assert rec["last_rc"] == 75


def test_run_once_refuses_without_record(world: World) -> None:
    r = world.run("run-once")
    assert r.returncode == 2


def test_rearm_after_passed(world: World) -> None:
    assert world.run("register", "--workspace", str(world.ws), "--", "true").returncode == 0
    assert world.run("run-once").returncode == 0
    assert world.record()["state"] == "passed"
    r = world.run("rearm", "--reset-attempts")
    assert r.returncode == 0
    assert world.record()["state"] == "armed"
    assert world.record()["attempt"] == 0


def test_run_until_pass_succeeds_on_retry(world: World) -> None:
    # argv: fail once then pass — use a counter file in the workspace
    counter = world.ws / "n"
    counter.write_text("0")
    script = world.ws / "flip.sh"
    script.write_text(
        "#!/bin/sh\n"
        f'n=$(cat "{counter}")\n'
        f'echo $((n+1)) > "{counter}"\n'
        'if [ "$n" -eq 0 ]; then exit 1; fi\n'
        "exit 0\n"
    )
    script.chmod(0o755)
    assert world.run("register", "--workspace", str(world.ws), "--", str(script)).returncode == 0
    r = world.run("run-until-pass")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert world.record()["state"] == "passed"
    assert world.record()["attempt"] == 2
    assert "nudge stub" in r.stderr


def test_run_until_pass_exhausted(world: World) -> None:
    assert world.run("register", "--workspace", str(world.ws), "--max-attempts", "2",
                     "--", "false").returncode == 0
    r = world.run("run-until-pass")
    assert r.returncode == 4, (r.stdout, r.stderr)
    assert world.record()["state"] == "failed"


def test_handoff_rekey_preserves_attempt(world: World) -> None:
    assert world.run("register", "--workspace", str(world.ws), "--max-attempts", "3",
                     "--", "false").returncode == 0
    assert world.run("run-once").returncode == 1
    assert world.record()["attempt"] == 1
    r = world.run("handoff", "--from", "agent-1", "--to", "agent-2")
    assert r.returncode == 0, r.stderr
    assert not (world.state / "agent-1.json").exists()
    rec = world.record("agent-2")
    assert rec["agent_id"] == "agent-2"
    assert rec["attempt"] == 1
    assert rec["handoff_from"] == "agent-1"


def test_handoff_clear(world: World) -> None:
    assert world.run("register", "--workspace", str(world.ws), "--", "true").returncode == 0
    r = world.run("handoff", "--from", "agent-1", "--clear")
    assert r.returncode == 0
    assert not (world.state / "agent-1.json").exists()


def test_nested_short_budget_skips_second_deadline(world: World) -> None:
    assert world.run(
        "register", "--workspace", str(world.ws), "--budget", "30s", "--", "true"
    ).returncode == 0
    r = world.run("run-once", DEADLINE_NAME="outer-deadline")
    assert r.returncode == 0, (r.stdout, r.stderr)
    calls = world.log.read_text() if world.log.exists() else ""
    # nested + short budget: beat the outer record, no second `deadline run`
    assert "DEADLINE beat outer-deadline" in calls
    assert "DEADLINE run" not in calls
    assert "BG" in calls
