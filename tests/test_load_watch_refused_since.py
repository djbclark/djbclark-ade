"""bin/load-watch follow-ups phase 1 (2026-11-14): `release` exit codes and `admit --refused-since EPOCH` (env LW_REFUSED_SINCE).
The valve tests run cmd_admit in-process with the injected clock of tests/test_load_watch_pr2.py (no sleeping)."""
import json
import os
import subprocess
import sys

import pytest

from test_load_watch_pr2 import CORES, LW, SOFT, Run, load_module

WALL0 = 1_000_000.0
HARD = dict(LW_FAKE_LOAD1=0.1, LW_FAKE_SWAPINS=500)   # swap-ins over their limit: a hard gate


def last_log(run):
    return json.loads(run.log.read_text().strip().splitlines()[-1])


def ignored(err):
    """The 'ignoring --refused-since' stderr lines (admit also prints one progress line per waited minute)."""
    return [x for x in err.splitlines() if "ignoring --refused-since" in x]


# --- F1: release exit codes ---------------------------------------------------------------------------------------------------------------

def release(state, rid):
    return subprocess.run([sys.executable, str(LW), "release", rid], capture_output=True, text=True, timeout=30,
                          env=dict(os.environ, LW_STATE_DIR=str(state)))


def test_release_of_an_unknown_reservation_exits_66_and_of_a_known_one_0(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "agent-reservations.json").write_text(json.dumps({"r": [{"id": "r1", "until": 2 ** 40}]}))
    ok = release(state, "r1")
    assert ok.returncode == 0 and "released r1" in ok.stdout, ok
    gone = release(state, "r-nope")
    assert gone.returncode == 66 and "no reservation r-nope" in gone.stdout, gone
    # releasing twice within the 30 s grace finds the grace entry again (0); an expired row not yet pruned is "no such reservation"
    assert release(state, "r1").returncode == 0
    (state / "agent-reservations.json").write_text(json.dumps({"r": [{"id": "old", "until": 1}, {"id": "live", "until": 2 ** 40}]}))
    assert release(state, "old").returncode == 66
    assert [x["id"] for x in json.loads((state / "agent-reservations.json").read_text())["r"]] == ["live"]   # and it was pruned


def test_release_exits_1_when_the_reservations_cannot_be_locked_or_written(tmp_path, monkeypatch):
    blocked = tmp_path / "state"
    blocked.write_text("a file where the state directory should be")   # mkdir fails: no lock
    r = release(blocked, "r1")
    assert r.returncode == 1 and "could not lock or write" in r.stderr, r
    # a write failure on a reservation that exists changes nothing and is 1, not 66
    lw = load_module(monkeypatch, tmp_path / "state2")
    (tmp_path / "state2").mkdir()
    (tmp_path / "state2" / "agent-reservations.json").write_text(json.dumps({"r": [{"id": "r1", "until": 2 ** 40}]}))
    monkeypatch.setattr(lw, "_res_write", lambda rows: (_ for _ in ()).throw(OSError("disk full")))
    assert lw.release_reservation_status("r1") is None
    assert lw.cmd_release(type("A", (), {"id": "r1"})()) == 1
    assert json.loads((tmp_path / "state2" / "agent-reservations.json").read_text())["r"][0]["until"] == 2 ** 40


# --- F2: parse_refused_since --------------------------------------------------------------------------------------------------------------

def test_parse_refused_since_unit(monkeypatch, tmp_path):
    lw = load_module(monkeypatch, tmp_path / "state")
    t, cap = 5000.0, 3600.0
    assert lw.parse_refused_since("4900", t, cap) == (4900, None)
    assert lw.parse_refused_since(" 4900 ", t, cap) == (4900, None)
    assert lw.parse_refused_since("5000", t, cap) == (5000, None)                      # now: zero credit, not the future
    assert lw.parse_refused_since("100", t, cap) == (1400.0, None)                     # capped at now - cap
    assert lw.parse_refused_since("0", t, 0.0) == (5000.0, None)                       # cap 0: never any credit
    for bad in ("5001", "abc", "", "-5", "12.5", "1e9", "0x10", "٣٣", "9" * 5000):     # future, garbage, a unicode digit, absurd length
        got, note = lw.parse_refused_since(bad, t, cap)
        assert got is None and note and "ignoring --refused-since" in note and "\n" not in note, bad


# --- F2: the valve clock ------------------------------------------------------------------------------------------------------------------

def test_without_the_flag_the_clock_is_per_call(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, wall0=WALL0, **SOFT)
    rc, rec, err = run(capsys, wait=600.0)
    assert rc == 0 and rec["waited_s"] == 300 and "refused_since" not in rec and not ignored(err)
    assert "refused_since" not in last_log(run)


def test_a_hold_that_began_earlier_is_admitted_sooner(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, wall0=WALL0, **SOFT)
    rc, rec, err = run(capsys, wait=600.0, refused_since=str(int(WALL0) - 120))
    assert rc == 0 and rec["forced"] == "starved" and rec["waited_s"] == 180 and rec["refused_since"] == int(WALL0) - 120, rec
    assert not ignored(err)
    assert "refused_since=999880" in run.lw.admit_line(rec)
    assert last_log(run)["refused_since"] == int(WALL0) - 120 and last_log(run)["verdict"] == "forced"
    # a hold of 300 s or more is admitted on the first reading; a shorter wait budget still ends hot when the credit is not enough
    run2 = Run(monkeypatch, tmp_path / "b", wall0=WALL0, **SOFT)
    assert run2(capsys, wait=600.0, refused_since=str(int(WALL0) - 300))[1]["waited_s"] == 0
    run3 = Run(monkeypatch, tmp_path / "c", wall0=WALL0, **SOFT)   # its own state: no forced admit 0 s ago holding the gap
    rc, rec, _ = run3(capsys, wait=100.0, refused_since=str(int(WALL0) - 100))
    assert rc == 75 and rec["status"] == "hot" and "forced" not in rec and rec["refused_since"] == int(WALL0) - 100


def test_the_credit_is_capped(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, wall0=WALL0, **SOFT)
    monkeypatch.setattr(run.lw, "STARVE_MIN_GAP_S", 0.0)                         # several forced admits in one test
    assert run.lw.STARVE_REFUSED_SINCE_MAX_S == 3600.0                           # the default cap is an hour
    rc, rec, _ = run(capsys, wait=600.0, refused_since="1")
    assert rc == 0 and rec["waited_s"] == 0 and rec["refused_since"] == int(WALL0) - 3600   # 3600 s of credit is more than the valve needs
    monkeypatch.setattr(run.lw, "STARVE_REFUSED_SINCE_MAX_S", 105.0)
    rc, rec, _ = run(capsys, wait=600.0, refused_since="1")                     # the epoch 1: decades of "hold"
    assert rc == 0 and rec["waited_s"] == 195 and rec["refused_since"] == int(WALL0) - 105   # 105 s of credit, 195 s still to wait
    monkeypatch.setattr(run.lw, "STARVE_REFUSED_SINCE_MAX_S", 0.0)
    rc, rec, _ = run(capsys, wait=600.0, refused_since="1")
    assert rc == 0 and rec["waited_s"] == 300                                   # cap 0: the flag buys nothing


@pytest.mark.parametrize("bad", ["future", "abc", "-5", "12.5", ""])
def test_a_future_or_unparsable_value_is_ignored_with_a_note(bad, monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, wall0=WALL0, **SOFT)
    value = str(int(WALL0) + 500) if bad == "future" else bad
    rc, rec, err = run(capsys, wait=600.0, refused_since=value)
    assert rc == 0 and rec["waited_s"] == 300 and "refused_since" not in rec     # behaves as if the flag was absent: not an error
    assert len(ignored(err)) == 1, err
    assert "refused_since" not in last_log(run)


def test_wait_zero_accepts_and_ignores_it(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, wall0=WALL0, **SOFT)
    rc, rec, err = run(capsys, wait=0.0, refused_since=str(int(WALL0) - 3000))
    assert rc == 75 and rec["status"] == "hot" and "forced" not in rec and "refused_since" not in rec and not ignored(err)
    rc, rec, err = run(capsys, wait=0.0, refused_since="garbage")               # not even a note: nothing waits, nothing to credit
    assert rc == 75 and not ignored(err)


def test_the_flag_beats_the_environment(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, wall0=WALL0, LW_REFUSED_SINCE=str(int(WALL0) - 240), **SOFT)
    monkeypatch.setattr(run.lw, "STARVE_MIN_GAP_S", 0.0)                         # several forced admits in one test
    assert run(capsys, wait=600.0)[1]["waited_s"] == 60                          # the env alone: 240 s of credit, 60 s to go
    rc, rec, _ = run(capsys, wait=600.0, refused_since=str(int(WALL0) - 105))
    assert rec["waited_s"] == 195 and rec["refused_since"] == int(WALL0) - 105   # the flag wins, even when it credits less
    rc, rec, err = run(capsys, wait=600.0, refused_since="junk")                 # a bad flag is not replaced by the env
    assert rec["waited_s"] == 300 and len(ignored(err)) == 1
    assert run(capsys, wait=600.0, refused_since=None)[1]["waited_s"] == 60      # no flag: the env is the fallback
    monkeypatch.setenv("LW_REFUSED_SINCE", "junk")
    rc, rec, err = run(capsys, wait=600.0)
    assert rec["waited_s"] == 300 and len(ignored(err)) == 1


def test_hard_gates_never_yield_to_a_refused_since(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, wall0=WALL0, **HARD)
    rc, rec, _ = run(capsys, wait=900.0, refused_since="1")
    assert rc == 75 and rec["status"] == "hot" and "forced" not in rec and rec["refused_since"] == int(WALL0) - 3600
    assert not (run.state / "starve.json").exists()


def test_the_machine_wide_gap_still_holds(monkeypatch, tmp_path, capsys):
    run = Run(monkeypatch, tmp_path, wall0=WALL0, **SOFT)
    run.state.mkdir(parents=True)
    (run.state / "starve.json").write_text(json.dumps({"last_forced_t": WALL0 - 30}))       # someone was forced 30 s ago
    rc, rec, _ = run(capsys, wait=60.0, refused_since="1")                       # a hold of an hour, but the gap has 90 s to run
    assert rc == 75 and rec["status"] == "hot" and "forced" not in rec
    assert json.loads((run.state / "starve.json").read_text())["last_forced_t"] == WALL0 - 30   # a refused claim changes nothing
    rc, rec, _ = run(capsys, wait=600.0, refused_since="1")                      # given time it passes the moment the gap elapses
    assert rc == 0 and rec["forced"] == "starved" and rec["waited_s"] == 90
    assert json.loads((run.state / "starve.json").read_text())["last_forced_t"] == pytest.approx(WALL0 + 90)


def test_a_clean_reading_spends_the_credit(monkeypatch, tmp_path, capsys):
    """The hold the caller reports is the first unbroken run only: once the machine is calm for a reading the next refusal starts a new run."""
    run = Run(monkeypatch, tmp_path, wall0=WALL0, LW_FAKE_LOAD1=f"{CORES * 3.0},0.1,{CORES * 3.0}", LW_FAKE_CHURN=40000)
    rc, rec, _ = run(capsys, wait=900.0, refused_since=str(int(WALL0) - 100))
    assert rc == 0 and rec["forced"] == "starved" and rec["waited_s"] == 315, rec   # refused at 0, clean at 15, refused again from 15: 15 + 300 (not 195), and the record does not claim the spent credit: no refused_since
    assert "refused_since" not in rec and "refused_since" not in last_log(run)


def test_the_flag_parses_on_the_command_line(tmp_path):
    e = dict(os.environ, LW_STATE_DIR=str(tmp_path / "state"), LW_FAKE_LOAD1="0.1", LW_ADMIT_LOG="off", LW_RESERVE_S="0")
    for args in (["--wait", "0", "--refused-since", "1700000000"], ["--wait", "0", "--refused-since", "garbage"],
                 ["--wait", "0", "--refused-since", "-5"], ["--wait", "0", "--refused-since="]):
        r = subprocess.run([sys.executable, str(LW), "admit", *args], capture_output=True, text=True, env=e, timeout=30)
        assert r.returncode == 0 and r.stdout.startswith("admit ok"), (args, r)
    r = subprocess.run([sys.executable, str(LW), "admit", "--wait", "0"], capture_output=True, text=True, timeout=30,
                       env=dict(e, LW_REFUSED_SINCE="garbage"))
    assert r.returncode == 0
