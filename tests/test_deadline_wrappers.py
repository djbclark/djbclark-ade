"""The long waiter registers its own deadline (docs/deadline.md, "Waiters register themselves"): `bin/load-watch admit --wait`
(the Python supervisor, bin/deadline_wait.py). The PR waiter that shared the Python supervisor was removed by slim-down E8 (2026-11-06) and
`bin/acp-dispatch-wait` (bash) went with the dispatch shim (Wave 6 deletion, 2026-11-14). Every wait that a test must interrupt is LONG
(120 s real time, the sweep's clock is faked), so a slow runner can never let it end by itself first (PR 257 adversary A1). Hermetic: every
run gets its own DEADLINE_STATE_DIR (never ~/.local/state/deadlines), the real `bin/deadline`, stub relay / hermes-ping and a fake load
(LW_FAKE_LOAD1). The expiry test advances the clock of an explicit `deadline sweep` (DEADLINE_NOW); nothing touches the installed launchd sweep."""
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
OWNER = "agent-test-1"
QUICK, SEEN, LONG = 3, 8, 120     # a wait that ends by itself and is never inspected live / one a test inspects while it runs / one that must outlive the test
# Wall time matters: pytest-linux's 30 min cap was crossed at PR 257 head 4aaee173 (the suite was at 29:53 before this file grew), so a natural end is 3 s.
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
        self.tmpd = tmp / "tmpd"   # TMPDIR of every waiter: the start marks must be private and removed
        self.tmpd.mkdir()
        self.procs: list[subprocess.Popen] = []
        for name, body in {"ping": "#!/bin/sh\nexit 0\n", "relay": "#!/bin/sh\ncat > /dev/null\nexit 0\n",
                           "broken-deadline": "#!/bin/sh\necho boom >&2\nexit 1\n"}.items():
            p = tmp / name
            p.write_text(body)
            p.chmod(0o755)
        self.env = {k: v for k, v in os.environ.items() if k not in DROP}
        self.env.update(
            DEADLINE_STATE_DIR=str(self.state), DEADLINE_HERMES_PING=str(tmp / "ping"), DEADLINE_RELAY=str(tmp / "relay"),
            DEADLINE_INLINE_WORKER="1", DEADLINE_SETTLE_S="0.3", DEADLINE_RUN_POLL="0.1", DEADLINE_WAIT_BEAT_EVERY="0.2",
            PASEO_AGENT_ID=OWNER, PATH=f"{tmp}{os.pathsep}{os.environ['PATH']}", TMPDIR=str(self.tmpd),
            LW_STATE_DIR=str(tmp / "lw"), LW_REGISTRY=str(tmp / "ci-only.tsv"), LW_ADMIT_POLL_S="1", LW_ADMIT_STAGGER_S="0,0",
            LW_BOOST_CALM_S="0", LW_RESERVE_S="0", LW_FAKE_LOAD1="1000", STUB_DIR=str(tmp))

    def start(self, *flags: str, secs: int = QUICK, **env) -> tuple[subprocess.Popen, str]:
        """(process, the deadline name it must register). `admit --wait` ends by its own `secs` timeout. `flags` are extra tool options."""
        argv = [sys.executable, str(LW), "admit", "--wait", str(secs), "--json", *flags]
        p = subprocess.Popen(argv, env={**self.env, **{k: str(v) for k, v in env.items()}}, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, start_new_session=True)
        self.procs.append(p)
        return p, f"admit-wait-{p.pid}"

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

    def started_marks(self) -> int:
        return sum(1 for d in self.tmpd.iterdir() if (d / "started").exists())

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


NATURAL_RC = 75   # admit's own timeout end: its callers fail OPEN on an unknown exit


def group_gone(pgid: int) -> bool:
    return not subprocess.run(["pgrep", "-g", str(pgid)], capture_output=True).stdout


def test_wait_registers_beats_and_deregisters_on_a_normal_end(world):
    p, name = world.start(secs=SEEN)
    rec = wait_until(lambda: world.live(name))
    assert rec["state"] == "running" and rec["kind"] == "run" and rec["on_expire"] == "kill"
    assert rec["owner"] == OWNER
    assert rec["budget_s"] == SEEN + 60, "the waiter's own timeout, plus 60 s"
    assert rec["heartbeat_s"] >= 300 and rec["pgid"], "a heartbeat timeout and the waiter's own process group"
    assert rec["pgid"] != os.getpgid(0) and rec["pgid"] != p.pid, "never the caller's group, never the supervisor's"
    marks = list(world.tmpd.iterdir())
    assert len(marks) == 1 and marks[0].stat().st_mode & 0o777 == 0o700, "the start mark lives in a private directory"
    first = rec["last_beat"]
    wait_until(lambda: world.record(name)["last_beat"] > first, timeout=30)   # the poll loop heartbeats
    out, err = p.communicate(timeout=90)
    assert p.returncode == NATURAL_RC, (out, err)
    final = world.record(name)
    assert final["state"] == "done" and final["rc"] == NATURAL_RC, "deregistered with the wait's own exit code"
    assert "warning" not in err and list(world.tmpd.iterdir()) == [], "the private mark directory is removed"


def test_sigterm_deregisters_and_stops_the_waiter(world):
    p, name = world.start(secs=LONG)
    pgid = wait_until(lambda: world.live(name))["pgid"]
    p.send_signal(signal.SIGTERM)
    p.communicate(timeout=60)
    assert p.returncode == 143
    final = world.record(name)
    assert final["state"] not in ("running", "stopping"), final["state"]
    wait_until(lambda: group_gone(pgid), timeout=15)
    assert list(world.tmpd.iterdir()) == []


def test_expiry_kills_the_waiters_own_group_with_its_own_exit_code(world):
    p, name = world.start(secs=LONG)
    rec = wait_until(lambda: world.live(name))
    wait_until(lambda: world.started_marks() == 1)
    # a sweep skips a record another enforcer holds the lock of (the run loop, a beat): like the real 60 s sweep, simply sweep again
    for _ in range(40):
        r = world.sweep(rec["started"] + rec["budget_s"] + 5)
        assert r.returncode == 0, (r.stdout, r.stderr)
        if world.record(name)["state"] != "running":
            break
        time.sleep(0.25)
    assert world.record(name)["state"] != "running", "sweep never acquired the record lock to expire it"
    out, err = p.communicate(timeout=90)
    assert p.returncode == NATURAL_RC, (out, err)   # admit answers 75: its callers fail OPEN on an unknown exit
    assert world.record(name)["state"] == "expired", "the DEADLINE stopped it, not the wait's own end"
    assert "deadline expired" in err
    wait_until(lambda: group_gone(rec["pgid"]), timeout=15)


def test_expiry_before_start_mark_still_honors_deadline(world):
    """If the enforcer expires `deadline run` (exit 124) before the inner copy touches its start mark,
    the supervisor must honor exit 124 rather than falling back to an unregistered wait."""
    early_expire = world.tmp / "early-expire-deadline"
    early_expire.write_text("#!/bin/sh\nexit 124\n")
    early_expire.chmod(0o755)
    p, _ = world.start(secs=LONG, DEADLINE_BIN=str(early_expire))
    out, err = p.communicate(timeout=30)
    assert p.returncode == NATURAL_RC, (out, err)
    assert "deadline expired" in err
    assert "waiting without a deadline" not in err
    assert list(world.tmpd.iterdir()) == []


def test_no_deadline_flag_registers_nothing(world):
    p, _ = world.start("--no-deadline")
    time.sleep(1.5)
    assert world.records() == [], "opted out: no record while it waits"
    out, err = p.communicate(timeout=90)
    assert p.returncode == NATURAL_RC and world.records() == [] and "warning" not in err


def test_a_waiter_under_a_deadline_run_does_not_register_again(world):
    p, _ = world.start(DEADLINE_NAME="caller-run")
    time.sleep(1.5)
    assert world.records() == [], "DEADLINE_NAME is set: the caller's own `deadline run` owns the deadline"
    out, err = p.communicate(timeout=90)
    assert p.returncode == NATURAL_RC and world.records() == [] and "warning" not in err


def test_a_missing_deadline_tool_only_warns(world):
    p, _ = world.start(DEADLINE_BIN=str(world.tmp / "no-such-tool"))
    out, err = p.communicate(timeout=90)
    assert p.returncode == NATURAL_RC, (out, err)
    assert err.count("warning") == 1 and "deadline" in err and world.records() == []


def test_a_failing_deadline_tool_only_warns_and_the_wait_goes_on(world):
    p, _ = world.start(DEADLINE_BIN=str(world.tmp / "broken-deadline"))
    out, err = p.communicate(timeout=90)
    assert p.returncode == NATURAL_RC, (out, err)
    assert err.count("warning") == 1, err
    assert list(world.tmpd.iterdir()) == []


def test_two_admission_waits_never_refuse_each_other(world):
    """Names carry the supervisor's pid (PR 257 adversary A6): two admission waits both register."""
    p1, n1 = world.start(secs=LONG)
    p2, n2 = world.start(secs=LONG)
    for n in (n1, n2):
        wait_until(lambda n=n: world.live(n))
    assert n1 != n2 and len(world.records()) == 2
    for q in (p1, p2):
        q.send_signal(signal.SIGTERM)
        q.communicate(timeout=60)


def test_a_killed_supervisor_leaves_no_orphaned_wait(world):
    """SIGKILL cannot be caught: the supervised copy notices the supervisor is gone and ends (PR 257 adversary A4)."""
    p, name = world.start(secs=LONG)
    rec = wait_until(lambda: world.live(name))
    p.kill()
    p.wait()
    wait_until(lambda: group_gone(rec["pgid"]), timeout=40)
    final = wait_until(lambda: world.record(name) if world.record(name)["state"] == "done" else None, timeout=20)
    assert final["rc"] == 143


def test_no_owner_when_the_caller_has_no_paseo_agent_id(world):
    del world.env["PASEO_AGENT_ID"]
    p, name = world.start(secs=SEEN)
    rec = wait_until(lambda: world.live(name))
    assert rec["owner"] == "-", "no owner: the sweep tells Hermes"
    p.communicate(timeout=90)


def test_a_name_already_live_does_not_cost_the_wait(world):
    """The real tool refuses a registration whose name is live (exit 2, the command never runs): the waiter warns once and waits unregistered.
    Names carry the pid, so the clash is made by a `deadline` wrapper that registers the name it is asked to run under first."""
    wrapper = world.tmp / "clashing-deadline"
    wrapper.write_text(f'#!/bin/sh\n# $1=run $2=--name $3=NAME\n"{sys.executable}" "{DEADLINE}" start "$3" --owner someone --budget 600 --on-expire notify >/dev/null || exit 9\n'
                       f'exec "{sys.executable}" "{DEADLINE}" "$@"\n')
    wrapper.chmod(0o755)
    p, name = world.start(DEADLINE_BIN=str(wrapper))
    out, err = p.communicate(timeout=90)
    assert p.returncode == NATURAL_RC, (out, err)
    assert err.count("warning") == 1 and "already registered and live" in err
    assert world.record(name)["owner"] == "someone" and world.record(name)["state"] == "running", "the other registration is untouched"
