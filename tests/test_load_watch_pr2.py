"""bin/load-watch admit, retune PR 2 of 3 (2026-11-14): the swap-ins gate, the RAM-scaled free floor, the starvation valve and the
admit tuning log. Subprocess tests use the LW_FAKE_* hooks; the valve tests run cmd_admit in-process with an injected clock (no sleeping)."""
import argparse
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

LW = Path(__file__).resolve().parent.parent / "bin" / "load-watch"
CORES = os.cpu_count() or 1
FAKES = ("LW_FAKE_LOAD1", "LW_FAKE_CHURN", "LW_FAKE_FREE_MB", "LW_FAKE_PAGEINS", "LW_FAKE_SWAPINS", "LW_FAKE_AGENTS")
LIMITS = ("LW_MIN_FREE_MB", "LW_MAX_COMPRESSOR_S", "LW_MAX_COMPRESSOR_HARD_S", "LW_CHURN_THRASH_PER_CORE", "LW_MAX_PAGEINS_S",
          "LW_MAX_PAGEINS_CORROBORATED_S", "LW_MAX_SWAPINS_S", "LW_SWAPINS_CORROBORATED_S", "LW_MAX_AGENTS", "LW_STARVE_SOFT_S",
          "LW_STARVE_MIN_GAP_S", "LW_RESERVE_S", "LW_BOOST_CALM_S", "LW_ADMIT_CALLER")


def admit(tmp_path, *args, **env):
    e = dict(os.environ, LW_STATE_DIR=str(tmp_path / "state"), LW_REGISTRY=str(tmp_path / "ci-only.tsv"), LW_ADMIT_POLL_S="1",
             LW_ADMIT_STAGGER_S="0,0", LW_BOOST_CALM_S="0", LW_RESERVE_S="0")
    for k in FAKES + LIMITS:
        e.pop(k, None)
    if "LW_MIN_FREE_MB" not in env and "default_floor" not in env:
        e["LW_MIN_FREE_MB"] = "1000"   # the default floor scales with the host's RAM: pin it unless the test is about that
    env.pop("default_floor", None)
    e.update(env)
    return subprocess.run([sys.executable, str(LW), "admit", *args], capture_output=True, text=True, env=e, timeout=30)


def load_module(monkeypatch, state):
    """The module, with the limit and fake variables unset at import and LW_STATE_DIR = `state`."""
    for k in FAKES + LIMITS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LW_STATE_DIR", str(state))
    loader = importlib.machinery.SourceFileLoader("load_watch_pr2", str(LW))
    spec = importlib.util.spec_from_loader("load_watch_pr2", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


# --- 1. the swap-ins gate ----------------------------------------------------------------------------------------------------------------

def test_swapins_over_the_limit_refuse_on_their_own(tmp_path):
    ok = admit(tmp_path, "--json", LW_FAKE_LOAD1="0.1", LW_FAKE_SWAPINS="250")
    assert ok.returncode == 0, ok.stderr
    assert json.loads(ok.stdout)["swapins_s"] == 250 and json.loads(ok.stdout)["max_swapins_s"] == 300
    r = admit(tmp_path, "--json", LW_FAKE_LOAD1="0.1", LW_FAKE_SWAPINS="301")
    assert r.returncode == 75
    rec = json.loads(r.stdout)
    assert rec["refused"] == ["swapins"] and rec["swapins_s"] == 301
    line = admit(tmp_path, LW_FAKE_LOAD1="0.1", LW_FAKE_SWAPINS="301").stdout
    assert "swapins=301" in line and "refused=swapins" in line and "max_swapins=300" in line


def test_swapins_limit_flag_and_env(tmp_path):
    assert admit(tmp_path, "--max-swapins", "10", LW_FAKE_LOAD1="0.1", LW_FAKE_SWAPINS="50").returncode == 75
    assert admit(tmp_path, LW_FAKE_LOAD1="0.1", LW_FAKE_SWAPINS="500", LW_MAX_SWAPINS_S="1000").returncode == 0
    assert admit(tmp_path, "--max-swapins", "0", LW_FAKE_LOAD1="0.1").returncode == 2
    assert admit(tmp_path, "--max-swapins", "nan", LW_FAKE_LOAD1="0.1").returncode == 2


def test_swapins_corroborate_the_lower_pageins_line(tmp_path):
    # pageins 1500/s: over the corroborated 1000 line, under the 4000 limit, no memory pressure
    base = dict(LW_FAKE_LOAD1="0.1", LW_FAKE_PAGEINS="1500")
    assert admit(tmp_path, **base, LW_FAKE_SWAPINS="0").returncode == 0
    assert admit(tmp_path, **base, LW_FAKE_SWAPINS="20").returncode == 0           # at the line, not above it
    r = admit(tmp_path, "--json", **base, LW_FAKE_SWAPINS="25")
    assert r.returncode == 75 and json.loads(r.stdout)["refused"] == ["pageins"]
    assert json.loads(r.stdout)["max_pageins_s"] == 1000                             # the corroborated line decided
    assert admit(tmp_path, LW_FAKE_LOAD1="0.1", LW_FAKE_PAGEINS="500", LW_FAKE_SWAPINS="25").returncode == 0   # pageins low
    assert admit(tmp_path, **base, LW_FAKE_SWAPINS="25", LW_SWAPINS_CORROBORATED_S="50").returncode == 0


def test_a_missing_swapins_counter_leaves_the_gate_off(tmp_path, monkeypatch):
    lw = load_module(monkeypatch, tmp_path / "state")
    lim = {"churn": 30000.0, "min_free_mb": 980.0, "max_pageins": 4000.0, "max_agents": 0}
    m = {"churn": 0.0, "free_mb": 8000.0, "pageins_s": 1500.0, "swapins_s": None, "agents": None, "failed": set()}
    assert lw.admit_refusals(0.1, 2.0, m, lim) == []
    m.pop("swapins_s")   # a record built before this key existed
    assert lw.admit_refusals(0.1, 2.0, m, lim) == []


def test_vm_stat_swapins_parse_and_missing_counter(monkeypatch, tmp_path):
    lw = load_module(monkeypatch, tmp_path / "state")
    text = ("Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free: 4831.\nPages speculative: 1417.\n"
            "File-backed pages: 233559.\nPages purgeable: 1910.\nPageins: 417724020.\nPageouts: 102253.\nSwapins: 1745544.\n"
            "Decompressions: 1562927802.\nCompressions: 1656696892.\n")

    def fake(out):
        return lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=out, stderr="")
    monkeypatch.setattr(lw.subprocess, "run", fake(text))
    assert lw._vm_stat_snapshot()["swapins"] == 1745544
    monkeypatch.setattr(lw.subprocess, "run", fake(text.replace("Swapins: 1745544.\n", "")))
    assert lw._vm_stat_snapshot()["swapins"] is None   # parses; the gate is off, nothing raises


def test_proc_snapshot_reads_pswpin_as_swapins(monkeypatch, tmp_path):
    lw = load_module(monkeypatch, tmp_path / "state")
    (tmp_path / "meminfo").write_text("MemTotal: 16000000 kB\nMemAvailable: 8000000 kB\n")
    (tmp_path / "vmstat").write_text("pswpin 40\npswpout 5\npgmajfault 900\n")
    monkeypatch.setattr(lw, "Path", lambda p: tmp_path / Path(p).name)
    s = lw._proc_snapshot()
    assert s["swapins"] == 40 and s["compress"] == 45 and s["pageins"] == 900


def test_admit_memory_swapins_rate_from_two_samples(monkeypatch, tmp_path):
    lw = load_module(monkeypatch, tmp_path / "state")
    snaps = iter([{"free_mb": 5000.0, "compress": 0, "pageins": 0, "swapins": 100},
                  {"free_mb": 5000.0, "compress": 0, "pageins": 0, "swapins": 700}])
    clock = [0.0]
    monkeypatch.setattr(lw, "vm_snapshot", lambda: next(snaps))
    monkeypatch.setattr(lw, "mono", lambda: clock[0])
    monkeypatch.setattr(lw, "nap", lambda s: clock.__setitem__(0, clock[0] + s))
    assert lw.admit_memory([], [], {k: [] for k in ("free_mb", "pageins_s", "swapins_s", "agents")}, 0)["swapins_s"] == 300.0   # 600 / 2 s
    # a counter that went backwards (or is missing) reads as no swap-ins reading
    for a, b in ((700, 100), (None, 5), (5, None)):
        snaps = iter([{"free_mb": 1.0, "compress": 0, "pageins": 0, "swapins": a}, {"free_mb": 1.0, "compress": 0, "pageins": 0, "swapins": b}])
        assert lw.admit_memory([], [], {k: [] for k in ("free_mb", "pageins_s", "swapins_s", "agents")}, 0)["swapins_s"] is None


# --- 2. the RAM-scaled free floor --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("gb,floor", [(4, 300), (8, 300), (16, 420), (32, 980), (64, 1000), (128, 1000), (2, 300)])
def test_scaled_free_floor(gb, floor, monkeypatch, tmp_path):
    lw = load_module(monkeypatch, tmp_path / "state")
    assert lw.scaled_min_free_mb(gb * 1024) == pytest.approx(floor)


@pytest.mark.parametrize("bad", [None, 0, -5, float("nan"), float("inf"), True, "32768"])
def test_a_failing_ram_probe_falls_back_to_1000(bad, monkeypatch, tmp_path):
    lw = load_module(monkeypatch, tmp_path / "state")
    assert lw.scaled_min_free_mb(bad) == 1000.0


def test_every_ram_probe_failing_gives_none_and_1000(monkeypatch, tmp_path):
    lw = load_module(monkeypatch, tmp_path / "state")
    monkeypatch.setattr(lw.os, "sysconf", lambda name: (_ for _ in ()).throw(OSError("no sysconf")))
    monkeypatch.setattr(lw, "Path", lambda p: tmp_path / "does-not-exist")
    monkeypatch.setattr(lw.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("no sysctl")))
    assert lw.physical_ram_mb() is None
    assert lw.scaled_min_free_mb(lw.physical_ram_mb()) == 1000.0


def test_the_default_floor_follows_the_ram_and_the_override_wins(tmp_path, monkeypatch):
    lw = load_module(monkeypatch, tmp_path / "state")
    ram = lw.physical_ram_mb()
    assert lw.ADMIT_MIN_FREE_MB == lw.scaled_min_free_mb(ram)
    r = admit(tmp_path, "--json", LW_FAKE_LOAD1="0.1", default_floor=1)
    assert json.loads(r.stdout)["min_free_mb"] == lw.scaled_min_free_mb(ram)
    assert json.loads(admit(tmp_path, "--json", LW_FAKE_LOAD1="0.1", LW_MIN_FREE_MB="123").stdout)["min_free_mb"] == 123
    assert json.loads(admit(tmp_path, "--json", "--min-free-mb", "77", LW_FAKE_LOAD1="0.1").stdout)["min_free_mb"] == 77


# --- 3. the starvation valve (in-process, injected clock) ---------------------------------------------------------------------------------

class Run:
    """cmd_admit in-process: monotonic clock and sleep replaced (a nap advances the clock), wall clock = wall0 + clock."""

    def __init__(self, monkeypatch, tmp_path, wall0=1000.0, **env):
        self.state = tmp_path / "state"
        self.lw = load_module(monkeypatch, self.state)
        self.log = tmp_path / "admit.jsonl"
        for k, v in dict(LW_ADMIT_POLL_S="15", LW_ADMIT_STAGGER_S="0,0", LW_ADMIT_LOG=str(self.log), **env).items():
            monkeypatch.setenv(k, str(v))
        self.clock = [0.0]
        monkeypatch.setattr(self.lw, "mono", lambda: self.clock[0])
        monkeypatch.setattr(self.lw, "nap", lambda s: self.clock.__setitem__(0, self.clock[0] + s))
        monkeypatch.setattr(self.lw, "now", lambda: wall0 + self.clock[0])
        monkeypatch.setattr(self.lw, "admit_caller", lambda: "pytest")
        monkeypatch.setattr(self.lw, "ADMIT_RESERVE_S", 0.0)
        monkeypatch.setattr(self.lw, "ADMIT_MIN_FREE_MB", 1000.0)   # not the host's RAM-scaled default
        self.wall0 = wall0

    def __call__(self, capsys, wait=600.0, **ns):
        self.clock[0] = 0.0
        setattr(self.lw, "now", lambda: self.wall0 + self.clock[0])
        rc = self.lw.cmd_admit(argparse.Namespace(wait=wait, max_per_core=2.0, json=True, **ns))
        out = capsys.readouterr()
        return rc, json.loads(out.out), out.err


SOFT = dict(LW_FAKE_LOAD1=CORES * 3.0, LW_FAKE_CHURN=40000)   # load over the explicit 2.0 base but under the 5.0 boost line, churn 30-60k: soft refusals


def test_starved_soft_refusal_gets_through_after_five_minutes(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, **SOFT)
    rc, rec, _ = run(capsys, wait=600.0)
    assert rc == 0 and rec["status"] == "ok" and rec["forced"] == "starved"
    assert rec["overrode"] == ["load", "compressor"] and rec["waited_s"] == 300
    assert "refused" not in rec
    # the human line starts with the documented words
    assert run.lw.admit_line(rec).startswith("admit ok forced=starved waited_s=300 overrode=load,compressor load1=")


def test_not_before_five_minutes_and_not_on_a_bare_check(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, **SOFT)
    rc, rec, _ = run(capsys, wait=290.0)
    assert rc == 75 and rec["status"] == "hot" and "forced" not in rec
    # a pure check reports the truth however long ago the clock says it started: the valve is a property of --wait
    ticks = iter(range(0, 10 ** 6, 1000))
    monkeypatch.setattr(run.lw, "mono", lambda: float(next(ticks)))
    rc, rec, _ = run(capsys, wait=0.0)
    assert rc == 75 and rec["status"] == "hot" and "forced" not in rec


def test_the_soft_threshold_is_an_env_knob_and_zero_turns_the_valve_off(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, **SOFT)
    monkeypatch.setattr(run.lw, "STARVE_SOFT_S", 60.0)
    rc, rec, _ = run(capsys, wait=600.0)
    assert rc == 0 and rec["waited_s"] == 60
    monkeypatch.setattr(run.lw, "STARVE_SOFT_S", 0.0)
    rc, rec, _ = run(capsys, wait=600.0)
    assert rc == 75 and rec["status"] == "hot"


@pytest.mark.parametrize("env", [
    dict(LW_FAKE_LOAD1=0.1, LW_FAKE_CHURN=70000),                       # churn over the hard line 60000
    dict(LW_FAKE_LOAD1=0.1, LW_FAKE_SWAPINS=500),                       # swap-ins over their limit
    dict(LW_FAKE_LOAD1=0.1, LW_FAKE_FREE_MB=200),                       # free memory under 300 MB
    dict(LW_FAKE_LOAD1=CORES * 6.0, LW_FAKE_CHURN=40000),               # load over the 5.0 boost line
    dict(LW_FAKE_LOAD1=CORES * 3.0, LW_FAKE_CHURN=40000, LW_FAKE_SWAPINS=500),   # a hard one among soft ones
], ids=["churn-hard", "swapins", "free-300", "load-boost", "mixed"])
def test_hard_gates_never_yield(env, monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, **env)
    rc, rec, _ = run(capsys, wait=900.0)
    assert rc == 75 and rec["status"] == "hot" and "forced" not in rec
    assert not (run.state / "starve.json").exists()   # nothing was claimed


def test_free_memory_between_300_and_the_floor_is_soft(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, LW_FAKE_LOAD1=0.1, LW_FAKE_FREE_MB=500)
    rc, rec, _ = run(capsys, wait=600.0)
    assert rc == 0 and rec["overrode"] == ["free_mem"]


def test_soft_pageins_and_the_agent_cap_yield(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, LW_FAKE_LOAD1=0.1, LW_FAKE_PAGEINS=9000, LW_FAKE_AGENTS=30)
    rc, rec, _ = run(capsys, wait=600.0, max_agents=20)
    assert rc == 0 and rec["overrode"] == ["pageins", "agents"]


def test_at_most_one_forced_admit_per_two_minutes_machine_wide(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, wall0=1000.0, **SOFT)
    rc, rec, _ = run(capsys, wait=600.0)
    assert rc == 0 and rec["forced"] == "starved"
    assert json.loads((run.state / "starve.json").read_text())["last_forced_t"] == pytest.approx(1300.0)
    # a second waiter starves at wall 1330, 30 s after the first forced admit (inside the 120 s gap): it keeps waiting and ends hot
    run.wall0 = 1030.0
    rc, rec, _ = run(capsys, wait=330.0)
    assert rc == 75 and rec["status"] == "hot" and "forced" not in rec
    assert json.loads((run.state / "starve.json").read_text())["last_forced_t"] == pytest.approx(1300.0)   # a refused claim changes nothing
    # the same waiter, given time, passes the moment the gap has elapsed (wall 1420 = 1300 + 120)
    assert run(capsys, wait=400.0)[1]["forced"] == "starved"
    assert json.loads((run.state / "starve.json").read_text())["last_forced_t"] == pytest.approx(1420.0)
    # one that starves at wall 1600, long after the gap, passes
    run.wall0 = 1300.0
    rc, rec, _ = run(capsys, wait=600.0)
    assert rc == 0 and rec["forced"] == "starved"
    assert json.loads((run.state / "starve.json").read_text())["last_forced_t"] == pytest.approx(1600.0)


def test_the_gap_is_an_env_knob(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, wall0=1000.0, **SOFT)
    monkeypatch.setattr(run.lw, "STARVE_MIN_GAP_S", 1.0)
    assert run(capsys, wait=600.0)[0] == 0
    run.wall0 = 1030.0
    assert run(capsys, wait=600.0)[0] == 0   # 1.0 s gap long gone


def test_starve_claim_is_atomic_under_concurrent_callers(monkeypatch, tmp_path):
    lw = load_module(monkeypatch, tmp_path / "state")
    wins, barrier = [], threading.Barrier(8)

    def go():
        barrier.wait()
        wins.append(lw.starve_claim(120.0, t=5000.0))
    threads = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert wins.count(True) == 1 and wins.count(False) == 7
    assert not list((tmp_path / "state").glob("starve.json.tmp*"))   # temp files replaced, none left
    assert lw.starve_claim(120.0, t=5000.0 + 119.0) is False and lw.starve_claim(120.0, t=5000.0 + 121.0) is True
    # a clock that stepped back by more than the gap (last_forced_t far in the future) never blocks forever
    assert lw.starve_claim(120.0, t=10.0) is True


def test_an_earlier_time_cannot_slip_past_a_later_claim(monkeypatch, tmp_path):
    """F1 (lead adversary 2026-11-14): a waiter that read its clock before waiting for the flock holds an earlier time than the claim
    that won; it must be refused, and the stored claim must not move backwards."""
    lw = load_module(monkeypatch, tmp_path / "state")
    assert lw.starve_claim(120.0, t=5000.0) is True
    assert lw.starve_claim(120.0, t=4999.5) is False
    assert json.loads((tmp_path / "state" / "starve.json").read_text())["last_forced_t"] == 5000.0
    assert lw.starve_claim(120.0, t=4880.5) is False and lw.starve_claim(120.0, t=5119.5) is False   # |t - last| < gap on both sides
    assert lw.starve_claim(120.0, t=4879.0) is True   # a clock stepped back by more than the gap unblocks


def test_the_claim_reads_the_clock_after_taking_the_lock(monkeypatch, tmp_path):
    lw = load_module(monkeypatch, tmp_path / "state")
    seen = []
    monkeypatch.setattr(lw, "now", lambda: seen.append("now") or 7000.0)
    assert lw.starve_claim(120.0) is True and seen == ["now"]
    assert lw.starve_claim(120.0) is False   # the same clock again is inside the gap


def test_concurrent_claims_with_staggered_times_pick_one_winner(monkeypatch, tmp_path):
    lw = load_module(monkeypatch, tmp_path / "state")
    wins, barrier = [], threading.Barrier(8)

    def go(i):
        barrier.wait()
        wins.append(lw.starve_claim(120.0, t=5000.0 - i * 0.01))   # a later lock holder may carry an earlier time
    threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert wins.count(True) == 1 and wins.count(False) == 7


def test_starve_claim_survives_a_corrupt_state_and_an_unwritable_dir(monkeypatch, tmp_path):
    lw = load_module(monkeypatch, tmp_path / "state")
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "starve.json").write_text("{not json")
    assert lw.starve_claim(120.0, t=1.0) is True
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(lw, "STATE_DIR", blocker / "sub")   # cannot be created: fail toward waiting
    assert lw.starve_claim(120.0, t=1.0) is False


def test_a_forced_admit_under_the_agent_cap_records_its_reservation(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, LW_FAKE_LOAD1=0.1, LW_FAKE_AGENTS=30)
    monkeypatch.setattr(run.lw, "ADMIT_RESERVE_S", 1200.0)
    rc, rec, _ = run(capsys, wait=600.0, max_agents=20)
    assert rc == 0 and rec["forced"] == "starved" and rec["overrode"] == ["agents"] and rec.get("reservation")
    rows = json.loads((run.state / "agent-reservations.json").read_text())["r"]
    assert [r["id"] for r in rows] == [rec["reservation"]]


# --- 4. the admit tuning log ------------------------------------------------------------------------------------------------------------

def test_every_admit_call_appends_one_json_line(tmp_path):
    log = tmp_path / "log" / "admit-log.jsonl"
    env = dict(LW_ADMIT_LOG=str(log), LW_ADMIT_CALLER="bg")
    assert admit(tmp_path, LW_FAKE_LOAD1="0.1", LW_FAKE_SWAPINS="7", **env).returncode == 0
    assert admit(tmp_path, "--wait", "0", LW_FAKE_LOAD1=str(CORES * 9), LW_FAKE_FREE_MB="500", **env).returncode == 75
    lines = log.read_text().splitlines()
    assert len(lines) == 2
    ok, hot = (json.loads(x) for x in lines)
    assert ok["verdict"] == "ok" and ok["refused"] == [] and ok["swapins"] == 7 and ok["caller"] == "bg"
    assert ok["t"].endswith("Z") and ok["load1"] == 0.1 and ok["cores"] == CORES
    assert hot["verdict"] == "hot" and "load" in hot["refused"] and "free_mem" in hot["refused"] and hot["free_mb"] == 500
    for k in ("per_core", "churn", "pageins", "waited_s", "limits"):
        assert k in hot
    assert set(hot["limits"]) >= {"per_core", "churn", "free_mb", "pageins", "swapins", "agents"} and hot["limits"]["swapins"] == 300


def test_a_forced_admit_is_logged_as_forced(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, **SOFT)
    assert run(capsys, wait=600.0)[0] == 0
    lines = [json.loads(x) for x in run.log.read_text().splitlines()]
    assert len(lines) == 1 and lines[0]["verdict"] == "forced" and lines[0]["refused"] == ["load", "compressor"]
    assert lines[0]["waited_s"] == 300 and lines[0]["caller"] == "pytest"


def test_log_off_writes_nothing(tmp_path):
    for off in ("off", "OFF"):
        r = admit(tmp_path, LW_FAKE_LOAD1="0.1", LW_ADMIT_LOG=off)
        assert r.returncode == 0
    assert not list((tmp_path / "state").glob("admit-log*"))


def test_a_log_failure_never_changes_the_verdict_or_the_exit_code(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    (tmp_path / "d" / "dir").mkdir(parents=True)
    for bad in (str(blocker / "sub" / "log.jsonl"), str(tmp_path / "d" / "dir")):   # a path under a file; a directory
        ok = admit(tmp_path, "--json", LW_FAKE_LOAD1="0.1", LW_ADMIT_LOG=bad)
        assert ok.returncode == 0 and json.loads(ok.stdout)["status"] == "ok", (bad, ok.stderr)
        hot = admit(tmp_path, "--json", LW_FAKE_LOAD1=str(CORES * 9), LW_ADMIT_LOG=bad)
        assert hot.returncode == 75 and json.loads(hot.stdout)["status"] == "hot", (bad, hot.stderr)
        assert ok.stderr == "" and hot.stderr == ""


def test_the_log_rotates_at_the_cap_keeping_one_old_file(monkeypatch, tmp_path):
    lw = load_module(monkeypatch, tmp_path / "state")
    log = tmp_path / "admit.jsonl"
    monkeypatch.setenv("LW_ADMIT_LOG", str(log))
    monkeypatch.setattr(lw, "ADMIT_LOG_MAX_BYTES", 400)
    for i in range(30):
        lw.admit_log_append({"i": i, "pad": "x" * 40})
    old = log.with_name("admit.jsonl.1")
    assert old.exists() and log.stat().st_size < 400 + 100
    rows = [json.loads(x)["i"] for f in (old, log) for x in f.read_text().splitlines()]
    assert rows == sorted(rows) and rows[-1] == 29 and len(set(rows)) == len(rows)   # newest kept in order; older ones dropped
    assert not log.with_name("admit.jsonl.2").exists()


def test_the_default_log_is_in_the_state_dir(tmp_path):
    e = dict(os.environ, LW_STATE_DIR=str(tmp_path / "s"), LW_FAKE_LOAD1="0.1", LW_RESERVE_S="0", LW_ADMIT_CALLER="x")
    e.pop("LW_ADMIT_LOG", None)
    assert subprocess.run([sys.executable, str(LW), "admit"], capture_output=True, text=True, env=e, timeout=30).returncode == 0
    assert len((tmp_path / "s" / "admit-log.jsonl").read_text().splitlines()) == 1


def test_admit_log_summary(tmp_path):
    log = tmp_path / "log.jsonl"

    def row(days_ago, verdict, refused, free, pageins, swapins):
        t = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days_ago * 86400))
        return json.dumps({"t": t, "verdict": verdict, "refused": refused, "free_mb": free, "pageins": pageins, "swapins": swapins})
    rows = [row(0.1, "ok", [], 1000, 100, 0), row(0.2, "ok", [], 2000, 200, 10), row(0.3, "hot", ["load", "pageins"], 3000, 300, 20),
            row(0.4, "forced", ["load"], 4000, 400, 30), row(30, "hot", ["swapins"], 1, 1, 1000), "not json", '{"t": "garbage"}']
    log.write_text("\n".join(rows) + "\n")
    e = dict(os.environ, LW_STATE_DIR=str(tmp_path / "s"), LW_ADMIT_LOG=str(log))
    r = subprocess.run([sys.executable, str(LW), "admit-log", "summary", "--days", "2"], capture_output=True, text=True, env=e, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "4 calls" in r.stdout and "ok=2" in r.stdout and "hot=1" in r.stdout and "forced=1" in r.stdout
    assert "load=2" in r.stdout and "pageins=1" in r.stdout and "swapins" not in r.stdout.split("reasons:")[1].splitlines()[0]
    assert "free_mb: n=4 p50=3000 p90=4000" in r.stdout and "swapins: n=4 p50=20 p90=30" in r.stdout
    wide = subprocess.run([sys.executable, str(LW), "admit-log", "summary", "--days", "60"], capture_output=True, text=True, env=e, timeout=30)
    assert "5 calls" in wide.stdout and "swapins=1" in wide.stdout
    bad = subprocess.run([sys.executable, str(LW), "admit-log", "summary", "--days", "0"], capture_output=True, text=True, env=e, timeout=30)
    assert bad.returncode == 2
    e["LW_ADMIT_LOG"] = str(tmp_path / "empty.jsonl")
    assert subprocess.run([sys.executable, str(LW), "admit-log", "summary"], capture_output=True, text=True, env=e, timeout=30).returncode == 1


# --- adversary round 1 (2026-11-14) --------------------------------------------------------------------------------------------------------

def test_a_forced_admit_whose_reservation_fails_is_refused_and_spends_no_claim(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, LW_FAKE_LOAD1=0.1, LW_FAKE_AGENTS=30)
    monkeypatch.setattr(run.lw, "ADMIT_RESERVE_S", 1200.0)
    monkeypatch.setattr(run.lw, "_res_locked", lambda fn: None)   # the reservation lock cannot be taken
    rc, rec, _ = run(capsys, wait=600.0, max_agents=20)
    assert rc == 75 and rec["status"] == "hot" and "forced" not in rec and "agents_reserve_failed" in rec["refused"]
    assert not (run.state / "starve.json").exists()
    monkeypatch.undo()   # nothing is left claimed: with the reservation working the very same wait is forced
    run2 = Run(monkeypatch, tmp_path / "again", LW_FAKE_LOAD1=0.1, LW_FAKE_AGENTS=30)
    monkeypatch.setattr(run2.lw, "ADMIT_RESERVE_S", 1200.0)
    assert run2(capsys, wait=600.0, max_agents=20)[1]["forced"] == "starved"


def test_a_clean_reading_breaks_the_unbroken_run_of_refusals(monkeypatch, tmp_path, capsys):
    hot, cool = CORES * 3.0, 0.1
    loads = ",".join([str(hot)] * 10 + [str(cool)] + [str(hot)])   # hot until 150 s, one clean read, then hot again
    run = Run(monkeypatch, tmp_path, LW_FAKE_LOAD1=loads, LW_FAKE_CHURN=40000)
    rc, rec, _ = run(capsys, wait=900.0)
    assert rc == 0 and rec["forced"] == "starved" and rec["waited_s"] == 450   # 150 s + a fresh 300 s, not 300 s from the start


def test_the_caller_is_a_plain_program_name_never_a_secret(monkeypatch, tmp_path):
    lw = load_module(monkeypatch, tmp_path / "state")
    monkeypatch.setattr(lw.os, "getppid", lambda: 4194000)   # no /proc entry: the `ps` path

    def ps(out):
        monkeypatch.setattr(lw.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=out, stderr=""))
        return lw.admit_caller()
    assert ps("/bin/bash /opt/x/bg --flag\n") == "bg"
    assert ps("/usr/bin/python3 -u /x/dispatch.py run\n") == "dispatch.py"
    assert ps("/usr/local/bin/acp-dispatch run\n") == "acp-dispatch"
    assert ps("sh -c GH_TOKEN=ghp_secret load-watch admit && make\n") == "sh"
    assert ps("sh /x/GH_TOKEN=ghp_secret\n") == "sh"
    for inline in ("bash -lc GH_TOKEN=ghp_secret make", "sh -ec ghp_barewordsecret", "bash --norc --noprofile -c ghp_barewordsecret",
                   "perl -e ghp_barewordsecret", "/usr/bin/env bash -c ghp_barewordsecret"):
        assert ps(inline + "\n") in ("bash", "sh", "perl", "env"), inline
    assert ps("/weird/na=me arg\n") == ""
    assert ps("") == ""
    monkeypatch.setenv("LW_ADMIT_CALLER", "bg")
    assert lw.admit_caller() == "bg"
    monkeypatch.setenv("LW_ADMIT_CALLER", "GH_TOKEN=ghp_secret")
    assert lw.admit_caller() == ""


def test_a_relative_log_path_is_the_state_dirs_not_the_cwd_and_zero_means_off(tmp_path):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    e = dict(os.environ, LW_STATE_DIR=str(tmp_path / "s"), LW_FAKE_LOAD1="0.1", LW_RESERVE_S="0", LW_ADMIT_LOG="mylog.jsonl")
    assert subprocess.run([sys.executable, str(LW), "admit"], capture_output=True, text=True, env=e, cwd=cwd, timeout=30).returncode == 0
    assert (tmp_path / "s" / "mylog.jsonl").exists() and not list(cwd.iterdir())
    for off in ("0", "false", "no"):
        e["LW_ADMIT_LOG"] = off
        assert subprocess.run([sys.executable, str(LW), "admit"], capture_output=True, text=True, env=e, cwd=cwd, timeout=30).returncode == 0
    assert not list(cwd.iterdir()) and not (tmp_path / "s" / "0").exists()


def test_a_log_fifo_with_no_reader_never_hangs_admit(tmp_path):
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    r = admit(tmp_path, LW_FAKE_LOAD1="0.1", LW_ADMIT_LOG=str(fifo))   # the helper's 30 s timeout is the hang detector
    assert r.returncode == 0 and r.stdout.startswith("admit ok")


def test_the_verdict_is_printed_even_if_the_entry_builder_raises(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, LW_FAKE_LOAD1="0.1")
    monkeypatch.setattr(run.lw, "admit_log_entry", lambda *a, **k: 1 / 0)
    assert run(capsys, wait=0.0)[1]["status"] == "ok"


def test_admit_log_summary_survives_a_corrupt_log(tmp_path):
    log = tmp_path / "log.jsonl"
    t = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    good = json.dumps({"t": t, "verdict": "ok", "refused": [], "free_mb": 5, "wait_s": 0})
    bad = [json.dumps({"t": t, "verdict": "hot", "refused": 5}), json.dumps({"t": t, "verdict": ["x"], "refused": []}),
           json.dumps({"t": t, "verdict": "hot", "refused": [["y"]]}), "[1, 2]", "null"]
    log.write_bytes(("\n".join([good] + bad) + "\n").encode() + b"\xff\xfe not utf-8\n")
    e = dict(os.environ, LW_STATE_DIR=str(tmp_path / "s"), LW_ADMIT_LOG=str(log))
    r = subprocess.run([sys.executable, str(LW), "admit-log", "summary"], capture_output=True, text=True, env=e, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "1 calls" in r.stdout and "ok=1" in r.stdout and "--wait 0" in r.stdout


def test_a_claim_that_cannot_be_written_drops_its_forced_reservation(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, LW_FAKE_LOAD1=0.1, LW_FAKE_AGENTS=30)
    monkeypatch.setattr(run.lw, "ADMIT_RESERVE_S", 1200.0)
    (run.state).mkdir(parents=True)
    (run.state / "starve.json").mkdir()   # the claim's os.replace fails (a directory in the way)
    rc, rec, _ = run(capsys, wait=600.0, max_agents=20)
    assert rc == 75 and rec["status"] == "hot" and "forced" not in rec
    rows = json.loads((run.state / "agent-reservations.json").read_text())["r"]
    assert [r for r in rows if r["until"] > run.wall0] == []   # about 20 polls tried; none left a reservation behind
    assert not list(run.state.glob("starve.json.tmp*"))


# --- lead adversary round 1 (2026-11-14) ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["memory_unreadable", "agents_unreadable", "agents_reserve_failed", "some_future_gate"])
def test_unreadable_and_unknown_refusals_are_always_hard(monkeypatch, tmp_path, name):
    lw = load_module(monkeypatch, tmp_path / "state")
    m = {"churn": None, "free_mb": None}
    lim = {"churn": 30000.0}
    assert lw.hard_refusals([name], 0.1, m, lim, 4.0) == [name]
    assert lw.hard_refusals(["agents", name], 0.1, m, lim, 4.0) == [name]   # one hard name among soft ones holds the valve
    assert lw.hard_refusals(["pageins", "agents"], 0.1, m, lim, 4.0) == []   # the plain soft gates yield


def test_the_valve_never_forces_past_an_unreadable_memory_reading(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, LW_FAKE_LOAD1=0.1, LW_FAKE_AGENTS=30)
    real = run.lw.admit_refusals
    monkeypatch.setattr(run.lw, "admit_refusals", lambda *a, **k: real(*a, **k) + ["memory_unreadable"])
    rc, rec, _ = run(capsys, wait=600.0, max_agents=20)
    assert rc == 75 and "forced" not in rec and "memory_unreadable" in rec["refused"]
    assert not (run.state / "starve.json").exists()
