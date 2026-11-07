"""The long waiters register their own deadline (docs/deadline.md, "Waiters register themselves"): `bin/load-watch admit --wait`
(the Python supervisor, bin/deadline_wait.py) and `bin/acp-dispatch-wait` (bash). The PR waiter that shared the Python supervisor was removed by
slim-down E8 (2026-11-06); its cases here now run through `admit`, which exercises the same code. Every wait that a test must interrupt is LONG (120 s real time, the sweep's clock is faked), so a slow runner can never let it end by itself first (PR 257 adversary A1). Hermetic: every run gets its own DEADLINE_STATE_DIR (never ~/.local/state/deadlines), the real `bin/deadline`,
stub relay / hermes-ping, a fake load (LW_FAKE_LOAD1) and a stub
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
DWAIT = ROOT / "bin" / "acp-dispatch-wait"
OWNER = "agent-test-1"
KINDS = ["admit", "dispatch"]
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
        envdump = 'env | grep "^DEADLINE_" | sort > "$STUB_DIR/$STUB_NAME-env"\n'
        for name, body in {"ping": "#!/bin/sh\nexit 0\n", "relay": "#!/bin/sh\ncat > /dev/null\nexit 0\n",
                           "broken-deadline": "#!/bin/sh\necho boom >&2\nexit 1\n",
                           "dispatch": ('#!/bin/sh\ncase "$1" in\n  wait) STUB_NAME=dispatch\n' + envdump +
                                        '    if [ -e "$STUB_DIR/ok" ]; then exit 0; fi; if [ -e "$STUB_DIR/timeout" ]; then exit 124; fi; exit 75 ;;\n'
                                        '  check) echo checked; exit 0 ;;\nesac\n')}.items():
            p = tmp / name
            p.write_text(body)
            p.chmod(0o755)
        (tmp / "record.json").write_text(json.dumps({"wait_timeout": 600, "finished": None}))
        self.env = {k: v for k, v in os.environ.items() if k not in DROP}
        self.env.update(
            DEADLINE_STATE_DIR=str(self.state), DEADLINE_HERMES_PING=str(tmp / "ping"), DEADLINE_RELAY=str(tmp / "relay"),
            DEADLINE_INLINE_WORKER="1", DEADLINE_SETTLE_S="0.3", DEADLINE_RUN_POLL="0.1", DEADLINE_WAIT_BEAT_EVERY="0.2",
            PASEO_AGENT_ID=OWNER, PATH=f"{tmp}{os.pathsep}{os.environ['PATH']}", TMPDIR=str(self.tmpd),
            LW_STATE_DIR=str(tmp / "lw"), LW_REGISTRY=str(tmp / "ci-only.tsv"), LW_ADMIT_POLL_S="1", LW_ADMIT_STAGGER_S="0,0",
            LW_BOOST_CALM_S="0", LW_RESERVE_S="0", LW_FAKE_LOAD1="1000",
            ACP_DISPATCH_BIN=str(tmp / "dispatch"), ACP_DISPATCH_WAIT_TICK="1", ACP_DISPATCH_WAIT_PASS="1", STUB_DIR=str(tmp))

    def start(self, kind: str, *flags: str, secs: int = QUICK, **env) -> tuple[subprocess.Popen, str]:
        """(process, the deadline name it must register). admit ends by its own `secs` timeout, the dispatch waiter when the
        test creates STUB_DIR/ok (or `timeout`). `flags` are extra tool options."""
        argv = {"admit": [sys.executable, str(LW), "admit", "--wait", str(secs), "--json", *flags],
                "dispatch": [str(DWAIT), *flags, str(self.tmp / "record.json"), str(self.tmp / "marker")]}[kind]
        p = subprocess.Popen(argv, env={**self.env, **{k: str(v) for k, v in env.items()}}, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, start_new_session=True)
        self.procs.append(p)
        return p, {"admit": f"admit-wait-{p.pid}", "dispatch": f"dispatch-wait-record-{p.pid}"}[kind]

    def stub(self, name: str) -> None:
        (self.tmp / name).write_text("")

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
    return {"admit": 75, "dispatch": 0}[kind]


def end_naturally(w: World, kind: str, p: subprocess.Popen) -> tuple[int, str, str]:
    if kind == "dispatch":
        time.sleep(0.7)
        w.stub("ok")
    out, err = p.communicate(timeout=90)
    return p.returncode, out, err


def group_gone(pgid: int) -> bool:
    return not subprocess.run(["pgrep", "-g", str(pgid)], capture_output=True).stdout


@pytest.mark.parametrize("kind", KINDS)
def test_wait_registers_beats_and_deregisters_on_a_normal_end(world, kind):
    p, name = world.start(kind, secs=SEEN)
    rec = wait_until(lambda: world.live(name))
    assert rec["state"] == "running" and rec["kind"] == "run" and rec["on_expire"] == "kill"
    assert rec["owner"] == OWNER
    assert rec["budget_s"] == (660 if kind == "dispatch" else SEEN + 60), "class budget or the waiter's own timeout, plus 60 s"
    assert rec["heartbeat_s"] >= 300 and rec["pgid"], "a heartbeat timeout and the waiter's own process group"
    assert rec["pgid"] != os.getpgid(0) and rec["pgid"] != p.pid, "never the caller's group, never the supervisor's"
    marks = list(world.tmpd.iterdir())
    assert len(marks) == 1 and marks[0].stat().st_mode & 0o777 == 0o700, "the start mark lives in a private directory"
    first = rec["last_beat"]
    wait_until(lambda: world.record(name)["last_beat"] > first, timeout=30)   # the poll loop heartbeats
    rc, out, err = end_naturally(world, kind, p)
    assert rc == natural_rc(kind), (out, err)
    final = world.record(name)
    assert final["state"] == "done" and final["rc"] == natural_rc(kind), "deregistered with the wait's own exit code"
    assert "warning" not in err and list(world.tmpd.iterdir()) == [], "the private mark directory is removed"


@pytest.mark.parametrize("kind", KINDS)
def test_sigterm_deregisters_and_stops_the_waiter(world, kind):
    p, name = world.start(kind, secs=LONG)
    pgid = wait_until(lambda: world.live(name))["pgid"]
    p.send_signal(signal.SIGTERM)
    p.communicate(timeout=60)
    assert p.returncode == 143
    final = world.record(name)
    assert final["state"] not in ("running", "stopping"), final["state"]
    wait_until(lambda: group_gone(pgid), timeout=15)
    assert list(world.tmpd.iterdir()) == []


@pytest.mark.parametrize("kind", KINDS)
def test_expiry_kills_the_waiters_own_group_with_its_own_exit_code(world, kind):
    p, name = world.start(kind, secs=LONG)
    rec = wait_until(lambda: world.live(name))
    # a sweep skips a record another enforcer holds the lock of (the run loop, a beat): like the real 60 s sweep, simply sweep again
    for _ in range(40):
        r = world.sweep(rec["started"] + rec["budget_s"] + 5)
        assert r.returncode == 0, (r.stdout, r.stderr)
        if world.record(name)["state"] != "running":
            break
        time.sleep(0.25)
    out, err = p.communicate(timeout=90)
    # admit answers 75 (its callers fail OPEN on an unknown exit); acp-dispatch-wait 76 (NOT 124, the slice timeout)
    assert p.returncode == {"admit": 75, "dispatch": 76}[kind], (out, err)
    assert world.record(name)["state"] == "expired", "the DEADLINE stopped it, not the wait's own end"
    if kind == "admit":
        assert "deadline expired" in err
    if kind == "dispatch":
        assert "slice is still running" in err
    wait_until(lambda: group_gone(rec["pgid"]), timeout=15)


def test_a_slice_timeout_124_passes_through_the_dispatch_waiter(world):
    """124 keeps its meaning (the record's wait_timeout passed): only an expired DEADLINE record turns it into 76."""
    world.stub("timeout")
    p, name = world.start("dispatch")
    out, err = p.communicate(timeout=60)
    assert p.returncode == 124 and world.record(name)["state"] == "done", (out, err)


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
    assert list(world.tmpd.iterdir()) == []


def test_waiters_for_the_same_pr_or_record_never_refuse_each_other(world):
    """Names carry the supervisor's pid (PR 257 adversary A6): two admission waits, or a re-arm of one record, all register."""
    p1, n1 = world.start("admit", secs=LONG)
    p2, n2 = world.start("admit", secs=LONG)
    d1, m1 = world.start("dispatch", secs=LONG)
    d2, m2 = world.start("dispatch", secs=LONG)
    for n in (n1, n2, m1, m2):
        wait_until(lambda n=n: world.live(n))
    assert len({n1, n2, m1, m2}) == 4 and len(world.records()) == 4
    for q in (p1, p2, d1, d2):
        q.send_signal(signal.SIGTERM)
        q.communicate(timeout=60)


@pytest.mark.parametrize("kind", KINDS)
def test_a_killed_supervisor_leaves_no_orphaned_wait(world, kind):
    """SIGKILL cannot be caught: the supervised copy notices the supervisor is gone and ends (PR 257 adversary A4)."""
    p, name = world.start(kind, secs=LONG)
    rec = wait_until(lambda: world.live(name))
    p.kill()
    p.wait()
    wait_until(lambda: group_gone(rec["pgid"]), timeout=40)
    final = wait_until(lambda: world.record(name) if world.record(name)["state"] == "done" else None, timeout=20)
    assert final["rc"] == 143


def test_the_bash_supervisor_runs_deadline_run_in_its_own_group(world):
    """A signal sent to the whole caller group must reach `deadline run` once (via the trap), not twice (PR 257 adversary A3)."""
    p, name = world.start("dispatch", secs=LONG)
    rec = wait_until(lambda: world.live(name))
    assert os.getpgid(rec["registrar_pid"]) != os.getpgid(p.pid), "`deadline run` shares the caller's process group"
    os.killpg(os.getpgid(p.pid), signal.SIGTERM)
    p.communicate(timeout=60)
    assert p.returncode == 143
    final = world.record(name)
    assert final["state"] != "running" and final.get("cancelled") is True
    wait_until(lambda: group_gone(rec["pgid"]), timeout=15)


@pytest.mark.parametrize("kind", ["dispatch"])
def test_what_a_waiter_starts_inherits_no_registration_variables(world, kind):
    """Only DEADLINE_NAME (so ITS waiters skip registering); never the pair that would let it beat this record (PR 257 adversary A5)."""
    p, name = world.start(kind, secs=SEEN)
    wait_until(lambda: world.live(name))
    dump = world.tmp / {"dispatch": "dispatch-env"}[kind]
    wait_until(dump.exists, timeout=30)
    lines = wait_until(lambda: dump.read_text().splitlines(), timeout=10)
    assert f"DEADLINE_NAME={name}" in lines
    assert not [ln for ln in lines if ln.split("=")[0] in ("DEADLINE_WAIT_NAME", "DEADLINE_WAIT_MARK", "DEADLINE_WAIT_SUPERVISOR")], lines
    end_naturally(world, kind, p)


def test_no_owner_when_the_caller_has_no_paseo_agent_id(world):
    del world.env["PASEO_AGENT_ID"]
    p, name = world.start("admit", secs=SEEN)
    rec = wait_until(lambda: world.live(name))
    assert rec["owner"] == "-", "no owner: the sweep tells Hermes"
    p.communicate(timeout=90)


@pytest.mark.parametrize("kind", ["admit", "dispatch"])
def test_a_name_already_live_does_not_cost_the_wait(world, kind):
    """The real tool refuses a registration whose name is live (exit 2, the command never runs): the waiter warns once and waits unregistered.
    Names carry the pid, so the clash is made by a `deadline` wrapper that registers the name it is asked to run under first."""
    wrapper = world.tmp / "clashing-deadline"
    wrapper.write_text(f'#!/bin/sh\n# $1=run $2=--name $3=NAME\n"{sys.executable}" "{DEADLINE}" start "$3" --owner someone --budget 600 --on-expire notify >/dev/null || exit 9\n'
                       f'exec "{sys.executable}" "{DEADLINE}" "$@"\n')
    wrapper.chmod(0o755)
    p, name = world.start(kind, DEADLINE_BIN=str(wrapper))
    rc, out, err = end_naturally(world, kind, p)
    assert rc == natural_rc(kind), (out, err)
    assert err.count("warning") == 1 and "already registered and live" in err
    assert world.record(name)["owner"] == "someone" and world.record(name)["state"] == "running", "the other registration is untouched"
