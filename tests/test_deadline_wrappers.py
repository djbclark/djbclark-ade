"""The long waiters register their own deadline (docs/deadline.md, "Waiters register themselves"): `bin/pr-wait`, `bin/load-watch admit --wait`
and `bin/acp-dispatch-wait`. Hermetic: every run gets its own DEADLINE_STATE_DIR (never ~/.local/state/deadlines), the real `bin/deadline`,
stub relay / hermes-ping, a fake `gh` that always fails (pr-wait just keeps polling until its own timeout), a fake load (LW_FAKE_LOAD1) and a stub
acp-dispatch. The expiry test advances the clock of an explicit `deadline sweep` (DEADLINE_NOW); nothing touches the installed launchd sweep."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DEADLINE = ROOT / "bin" / "deadline"
LW = ROOT / "bin" / "load-watch"
PR_WAIT = ROOT / "bin" / "pr-wait"
DWAIT = ROOT / "bin" / "acp-dispatch-wait"
OWNER = "agent-test-1"
PR = 4242
KINDS = ["admit", "pr-wait", "dispatch"]
DROP = ("DEADLINE_NAME", "DEADLINE_WAIT_NAME", "DEADLINE_WAIT_MARK", "DEADLINE_BIN", "PASEO_AGENT_ID")


def wait_until(pred, timeout: float = 20.0, step: float = 0.05):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        got = pred()
        if got:
            return got
        time.sleep(step)
    raise AssertionError("condition not met in time")


class World:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.state = tmp / "deadlines"
        self.procs: list[subprocess.Popen] = []
        for name, body in {"ping": "#!/bin/sh\nexit 0\n", "relay": "#!/bin/sh\ncat > /dev/null\nexit 0\n",
                           "gh": "#!/bin/sh\nexit 1\n", "broken-deadline": "#!/bin/sh\necho boom >&2\nexit 1\n",
                           "dispatch": ('#!/bin/sh\ncase "$1" in\n  wait) if [ -e "$STUB_DIR/ok" ]; then exit 0; fi; exit 75 ;;\n'
                                        '  check) echo checked; exit 0 ;;\nesac\n')}.items():
            p = tmp / name
            p.write_text(body)
            p.chmod(0o755)
        (tmp / "record.json").write_text(json.dumps({"wait_timeout": 600, "finished": None}))
        self.env = {k: v for k, v in os.environ.items() if k not in DROP}
        self.env.update(
            DEADLINE_STATE_DIR=str(self.state), DEADLINE_HERMES_PING=str(tmp / "ping"), DEADLINE_RELAY=str(tmp / "relay"),
            DEADLINE_INLINE_WORKER="1", DEADLINE_SETTLE_S="0.3", DEADLINE_RUN_POLL="0.1", DEADLINE_WAIT_BEAT_EVERY="0.2",
            PASEO_AGENT_ID=OWNER, PATH=f"{tmp}{os.pathsep}{os.environ['PATH']}",
            LW_STATE_DIR=str(tmp / "lw"), LW_REGISTRY=str(tmp / "ci-only.tsv"), LW_ADMIT_POLL_S="1", LW_ADMIT_STAGGER_S="0,0",
            LW_BOOST_CALM_S="0", LW_RESERVE_S="0", LW_FAKE_LOAD1="1000", PR_WAIT_STATE_DIR=str(tmp / "prw"),
            ACP_DISPATCH_BIN=str(tmp / "dispatch"), ACP_DISPATCH_WAIT_TICK="1", ACP_DISPATCH_WAIT_PASS="1", STUB_DIR=str(tmp))

    def start(self, kind: str, *flags: str, **env) -> tuple[subprocess.Popen, str]:
        """(process, the deadline name it must register). The wait is short (4 s): admit and pr-wait end by their own timeout, the dispatch
        waiter when the test creates STUB_DIR/ok. `flags` are extra tool options."""
        argv = {"admit": [sys.executable, str(LW), "admit", "--wait", "4", "--json", *flags],
                "pr-wait": [sys.executable, "-I", str(PR_WAIT), str(PR), "--head", "a" * 40, "--timeout", "4", "--interval", "0.3",
                            "--out", str(self.tmp / "out" / "w"), *flags],
                "dispatch": [str(DWAIT), *flags, str(self.tmp / "record.json"), str(self.tmp / "marker")]}[kind]
        p = subprocess.Popen(argv, env={**self.env, **{k: str(v) for k, v in env.items()}}, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, start_new_session=True)
        self.procs.append(p)
        return p, {"admit": f"admit-wait-{p.pid}", "pr-wait": f"pr-wait-{PR}", "dispatch": "dispatch-wait-record"}[kind]

    def finish_dispatch(self) -> None:
        (self.tmp / "ok").write_text("")

    def record(self, name: str) -> dict:
        return json.loads((self.state / f"{name}.json").read_text())

    def live(self, name: str) -> dict | None:
        """The record once `deadline run` has persisted the running command (not the `starting` placeholder)."""
        try:
            rec = self.record(name)
        except (OSError, ValueError):
            return None
        return rec if rec.get("state") == "running" and rec.get("pgid") else None

    def records(self) -> list[str]:
        return sorted(p.name for p in self.state.glob("*.json")) if self.state.exists() else []

    def sweep(self, now: float) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(DEADLINE), "sweep", "--no-agents"], capture_output=True, text=True, timeout=60,
                              env={**self.env, "DEADLINE_NOW": str(now)})

    def cleanup(self) -> None:
        for p in self.procs:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            p.wait()
        if self.state.exists():   # the supervised copy lives in its own session: find stragglers by their record
            for f in self.state.glob("*.json"):
                try:
                    rec = json.loads(f.read_text())
                    if rec.get("pgid"):
                        os.killpg(rec["pgid"], signal.SIGKILL)
                except (OSError, ValueError):
                    pass


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.cleanup()


def natural_rc(kind: str) -> int:
    return {"admit": 75, "pr-wait": 6, "dispatch": 0}[kind]


def end_naturally(w: World, kind: str, p: subprocess.Popen) -> tuple[int, str, str]:
    if kind == "dispatch":
        time.sleep(0.7)
        w.finish_dispatch()
    out, err = p.communicate(timeout=60)
    return p.returncode, out, err


@pytest.mark.parametrize("kind", KINDS)
def test_wait_registers_beats_and_deregisters_on_a_normal_end(world, kind):
    p, name = world.start(kind)
    rec = wait_until(lambda: world.live(name))
    assert rec["state"] == "running" and rec["kind"] == "run" and rec["on_expire"] == "kill"
    assert rec["owner"] == OWNER
    assert rec["budget_s"] == (660 if kind == "dispatch" else 64), "class budget or the waiter's own timeout (4 s), plus 60 s"
    assert rec["heartbeat_s"] >= 300 and rec["pgid"], "a heartbeat timeout and the waiter's own process group"
    assert rec["pgid"] != os.getpgid(0) and rec["pgid"] != p.pid, "never the caller's group, never the supervisor's"
    first = rec["last_beat"]
    wait_until(lambda: world.record(name)["last_beat"] > first, timeout=10)   # the poll loop heartbeats
    rc, out, err = end_naturally(world, kind, p)
    assert rc == natural_rc(kind), (out, err)
    final = world.record(name)
    assert final["state"] == "done" and final["rc"] == natural_rc(kind), "deregistered with the wait's own exit code"
    assert "warning" not in err


@pytest.mark.parametrize("kind", KINDS)
def test_sigterm_deregisters_and_stops_the_waiter(world, kind):
    p, name = world.start(kind)
    pgid = wait_until(lambda: world.live(name))["pgid"]
    p.send_signal(signal.SIGTERM)
    p.communicate(timeout=30)
    assert p.returncode == 143
    final = world.record(name)
    assert final["state"] not in ("running", "stopping"), final["state"]
    wait_until(lambda: not subprocess.run(["pgrep", "-g", str(pgid)], capture_output=True).stdout, timeout=10)


@pytest.mark.parametrize("kind", KINDS)
def test_expiry_kills_the_waiters_own_group_and_exits_124(world, kind):
    p, name = world.start(kind)
    rec = wait_until(lambda: world.live(name))
    r = world.sweep(rec["started"] + rec["budget_s"] + 5)
    assert r.returncode == 0, (r.stdout, r.stderr)
    p.communicate(timeout=60)
    assert p.returncode == 124
    assert world.record(name)["state"] == "expired"
    wait_until(lambda: not subprocess.run(["pgrep", "-g", str(rec["pgid"])], capture_output=True).stdout, timeout=10)


@pytest.mark.parametrize("kind", KINDS)
def test_no_deadline_flag_registers_nothing(world, kind):
    p, _ = world.start(kind, "--no-deadline")
    time.sleep(1.5)
    assert world.records() == [], "opted out: no record while it waits"
    rc, _, err = end_naturally(world, kind, p)
    assert rc == natural_rc(kind) and world.records() == [] and "warning" not in err


@pytest.mark.parametrize("kind", KINDS)
def test_a_waiter_under_a_deadline_run_does_not_register_again(world, kind):
    p, _ = world.start(kind, DEADLINE_NAME="caller-run")
    time.sleep(1.5)
    assert world.records() == [], "DEADLINE_NAME is set: the caller's own `deadline run` owns the deadline"
    rc, _, err = end_naturally(world, kind, p)
    assert rc == natural_rc(kind) and world.records() == [] and "warning" not in err


@pytest.mark.parametrize("kind", KINDS)
def test_a_missing_deadline_tool_only_warns(world, kind):
    p, _ = world.start(kind, DEADLINE_BIN=str(world.tmp / "no-such-tool"))
    rc, out, err = end_naturally(world, kind, p)
    assert rc == natural_rc(kind), (out, err)
    assert err.count("warning") == 1 and "deadline" in err and world.records() == []


@pytest.mark.parametrize("kind", KINDS)
def test_a_failing_deadline_tool_only_warns_and_the_wait_goes_on(world, kind):
    p, _ = world.start(kind, DEADLINE_BIN=str(world.tmp / "broken-deadline"))
    rc, out, err = end_naturally(world, kind, p)
    assert rc == natural_rc(kind), (out, err)
    assert err.count("warning") == 1, err


@pytest.mark.parametrize("kind", ["pr-wait", "dispatch"])
def test_a_name_already_live_does_not_cost_the_wait(world, kind):
    name = {"pr-wait": f"pr-wait-{PR}", "dispatch": "dispatch-wait-record"}[kind]
    r = subprocess.run([sys.executable, str(DEADLINE), "start", name, "--owner", "someone", "--budget", "600", "--on-expire", "notify"],
                       capture_output=True, text=True, env=world.env, timeout=30)
    assert r.returncode == 0, r.stderr
    p, _ = world.start(kind)
    rc, out, err = end_naturally(world, kind, p)
    assert rc == natural_rc(kind), (out, err)
    assert err.count("warning") == 1 and world.record(name)["owner"] == "someone" and world.record(name)["state"] == "running"


def test_no_owner_when_the_caller_has_no_paseo_agent_id(world):
    del world.env["PASEO_AGENT_ID"]
    p, name = world.start("admit")
    rec = wait_until(lambda: world.live(name))
    assert rec["owner"] == "-", "no owner: the sweep tells Hermes"
    p.communicate(timeout=60)
