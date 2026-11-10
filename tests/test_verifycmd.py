"""Tests for bin/verifycmd: register argv, run under deadline, exit table 0/1/2/4/75/124.

Hermetic: VERIFYCMD_STATE_DIR + ADE_STATE_DIR temp dirs, stub DEADLINE_BIN / VERIFYCMD_BG,
linked claimed worktree via ade_claims (order 9), no real daemon.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "verifycmd"
sys.path.insert(0, str(ROOT / "bin"))
import ade_claims  # noqa: E402


def _load_verifycmd():
    # bin/verifycmd has no .py suffix; SourceFileLoader still loads it.
    loader = importlib.machinery.SourceFileLoader("verifycmd_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vc = _load_verifycmd()

DROP = ("VERIFYCMD_STATE_DIR", "VERIFYCMD_BG", "VERIFYCMD_NO_BG", "DEADLINE_BIN",
        "DEADLINE_NAME", "PASEO_AGENT_ID", "ADE_STATE_DIR", "ADE_CLAIM_ID", "ACP_RUN_AGENT",
        "CLAUDE_CODE_SESSION_ID")


def _git_env(state: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("GIT_", "ADE_", "ACP_", "CLAUDE_CODE", "PASEO", "PRE_COMMIT"))}
    env.update({
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
        "ADE_STATE_DIR": str(state),
    })
    return env


def _git(state: Path, args: list[str], cwd: Path) -> None:
    r = subprocess.run(["git", *args], cwd=cwd, env=_git_env(state),
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, (args, r.stderr)


def _mk_linked_claimed(tmp: Path, ade_state: Path, claim_id: str = "agent-1") -> tuple[Path, Path]:
    """Primary (shared) checkout + linked worktree claimed by claim_id. Returns (primary, wt)."""
    primary = tmp / "primary"
    primary.mkdir()
    _git(ade_state, ["init", "-q", "-b", "main"], primary)
    (primary / "f").write_text("base\n")
    _git(ade_state, ["add", "f"], primary)
    _git(ade_state, ["commit", "-qm", "init"], primary)
    wt = tmp / "workspace"
    _git(ade_state, ["worktree", "add", "-q", "-b", "wtb", str(wt)], primary)
    c = ade_claims.make_claim(
        id=claim_id, path=wt, branch="wtb", base_sha="deadbeef",
        owner_record=claim_id, owner_agent="verify-agent",
    )
    # ADE_STATE_DIR must already point at ade_state (fixture sets it).
    assert os.environ.get("ADE_STATE_DIR") == str(ade_state)
    ade_claims.create_claim(c, pointer_for=wt)
    return primary, wt


class World:
    def __init__(self, tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp = tmp
        self.state = tmp / "verifycmd-state"
        self.ade_state = tmp / "ade-state"
        self.ade_state.mkdir()
        monkeypatch.setenv("ADE_STATE_DIR", str(self.ade_state))
        self.primary, self.ws = _mk_linked_claimed(tmp, self.ade_state, "agent-1")
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
            ADE_STATE_DIR=str(self.ade_state),
            ADE_CLAIM_ID="agent-1",
            ACP_RUN_AGENT="1",
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
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return World(tmp_path, monkeypatch)


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


def test_register_refuses_shared_checkout(world: World) -> None:
    r = world.run("register", "--workspace", str(world.primary), "--", "true")
    assert r.returncode == 2, r.stderr
    assert "shared/primary" in r.stderr


def test_register_refuses_foreign_claim(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    # Claim owned by other-agent; caller is still agent-1
    foreign_wt = world.tmp / "foreign-wt"
    _git(world.ade_state, ["worktree", "add", "-q", "-b", "foreign-br", str(foreign_wt)],
         world.primary)
    monkeypatch.setenv("ADE_STATE_DIR", str(world.ade_state))
    c = ade_claims.make_claim(
        id="other-agent", path=foreign_wt, branch="foreign-br", base_sha="deadbeef",
        owner_record="other-agent", owner_agent="other",
    )
    ade_claims.create_claim(c, pointer_for=foreign_wt)
    r = world.run("register", "--workspace", str(foreign_wt), "--", "true")
    assert r.returncode == 2, r.stderr
    assert "belongs to" in r.stderr or "claim" in r.stderr.lower()


def test_register_refuses_non_git(world: World) -> None:
    plain = world.tmp / "plain"
    plain.mkdir()
    r = world.run("register", "--workspace", str(plain), "--", "true")
    assert r.returncode == 2
    assert "not a git worktree" in r.stderr


def test_run_once_refuses_after_claim_released(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    assert world.run("register", "--workspace", str(world.ws), "--", "true").returncode == 0
    monkeypatch.setenv("ADE_STATE_DIR", str(world.ade_state))
    ade_claims.set_state("agent-1", "released")
    r = world.run("run-once")
    assert r.returncode == 2, r.stderr
    assert "no active claim" in r.stderr


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
    # collision-resistant name includes digest + attempt
    assert "verifycmd-" in calls
    assert "-1" in calls  # attempt suffix


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


def test_deadline_name_distinguishes_sanitize_collisions() -> None:
    a = vc.deadline_name("agent:a", 1)
    b = vc.deadline_name("agent@a", 1)
    assert a != b
    assert a.endswith("-1") and b.endswith("-1")
    assert len(a) <= 100 and len(b) <= 100
    assert a.startswith("verifycmd-") and b.startswith("verifycmd-")


def test_deadline_name_keeps_attempt_under_long_id() -> None:
    long_id = "agent-" + ("x" * 200) + ":tail"
    name = vc.deadline_name(long_id, 12)
    assert name.endswith("-12")
    assert len(name) <= 100
    # digest still present
    digest = __import__("hashlib").sha256(long_id.encode()).hexdigest()[:12]
    assert digest in name
