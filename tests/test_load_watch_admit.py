"""bin/load-watch admit: the dispatcher-facing "may new work start now?" predicate (operator 2026-10-19).
No launchd, no ps; the load comes from LW_FAKE_LOAD1 so a busy host cannot change the answer."""
import argparse
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

LW = Path(__file__).resolve().parent.parent / "bin" / "load-watch"
CORES = os.cpu_count() or 1


def admit(tmp_path, *args, load1=None, **env):
    e = dict(os.environ, LW_STATE_DIR=str(tmp_path / "state"), LW_REGISTRY=str(tmp_path / "ci-only.tsv"),
             LW_ADMIT_POLL_S="1", LW_ADMIT_STAGGER_S="0,0")
    e.pop("LW_FAKE_LOAD1", None)
    if load1 is not None:
        e["LW_FAKE_LOAD1"] = str(load1)
    e.update(env)
    return subprocess.run([sys.executable, str(LW), "admit", *args], capture_output=True, text=True, env=e,
                          timeout=30)


def load_module():
    loader = importlib.machinery.SourceFileLoader("load_watch", str(LW))
    spec = importlib.util.spec_from_loader("load_watch", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_admit_ok_under_the_threshold(tmp_path):
    r = admit(tmp_path, load1=0.1)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("admit ok load1=0.1 per_core=")
    assert f"cores={CORES}" in r.stdout
    assert len(r.stdout.strip().splitlines()) == 1


def test_admit_hot_with_wait_zero_is_a_pure_check(tmp_path):
    t0 = time.monotonic()
    r = admit(tmp_path, "--wait", "0", load1=CORES * 4)
    assert r.returncode == 75, r.stderr
    assert r.stdout.startswith("admit hot load1=")
    assert f"cores={CORES}" in r.stdout
    assert time.monotonic() - t0 < 10  # no waiting at --wait 0


def test_admit_default_limit_is_one_and_a_half_per_core(tmp_path):
    assert admit(tmp_path, load1=CORES * 1.4).returncode == 0
    assert admit(tmp_path, load1=CORES * 1.6).returncode == 75
    # bg's number, not the blame step's 2.0: a load that the blame step ignores is still too hot to start in
    assert admit(tmp_path, load1=CORES * 1.9).returncode == 75


def test_admit_max_per_core_override(tmp_path):
    assert admit(tmp_path, "--max-per-core", "0.5", load1=CORES * 1.0).returncode == 75
    assert admit(tmp_path, "--max-per-core", "3", load1=CORES * 2.5).returncode == 0


def test_admit_json_fields(tmp_path):
    r = admit(tmp_path, "--json", load1=0.25)
    assert r.returncode == 0, r.stderr
    rec = json.loads(r.stdout)
    assert rec["status"] == "ok" and rec["load1"] == 0.25 and rec["cores"] == CORES
    assert rec["per_core"] == round(0.25 / CORES, 2) and rec["max_per_core"] == 1.5 and rec["waited_s"] == 0
    hot = admit(tmp_path, "--json", "--wait", "0", load1=CORES * 5)
    assert hot.returncode == 75
    assert json.loads(hot.stdout)["status"] == "hot"


def test_admit_reports_a_sustained_hot_machine_from_fresh_state(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    t = time.time()
    (state / "state.json").write_text(json.dumps({"t": t, "hot_since": t - 400, "streak": 20, "samples": []}))
    r = admit(tmp_path, "--json", load1=CORES * 4)
    rec = json.loads(r.stdout)
    assert rec["streak"] == 20 and 399 <= rec["hot_for_s"] <= 420
    assert "streak=20 hot_for_s=" in admit(tmp_path, load1=CORES * 4).stdout
    # a stale state.json says nothing about the machine now
    (state / "state.json").write_text(json.dumps({"t": t - 3600, "hot_since": t - 7200, "streak": 99}))
    assert "streak" not in json.loads(admit(tmp_path, "--json", load1=CORES * 4).stdout)


def test_admit_waits_until_the_load_drops(tmp_path):
    # two hot reads, then cool: waits, staggers (0 s here), re-checks, admits
    r = admit(tmp_path, "--json", "--wait", "20", load1=f"{CORES * 9},{CORES * 9},0.1")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["status"] == "ok"


def test_admit_stagger_never_runs_past_the_wait_budget(tmp_path):
    # a hot read, then cool: the 5-30 s stagger would have reported waited_s >= 6 for a --wait of 3
    for wait in ("1", "3"):
        t0 = time.monotonic()
        r = admit(tmp_path, "--json", "--wait", wait, load1=f"{CORES * 9},0.1", LW_ADMIT_STAGGER_S="5,30")
        assert r.returncode == 0, r.stderr
        rec = json.loads(r.stdout)
        assert rec["status"] == "ok" and rec["waited_s"] <= int(wait), (wait, rec)
        assert time.monotonic() - t0 < int(wait) + 5  # and it really did not sleep the stagger


def test_admit_gives_up_after_the_wait_budget(tmp_path):
    r = admit(tmp_path, "--json", "--wait", "1", load1=CORES * 9)
    assert r.returncode == 75
    assert json.loads(r.stdout)["status"] == "hot"


def test_admit_usage_errors_exit_2(tmp_path):
    assert admit(tmp_path, "--wait", "-1", load1=0.1).returncode == 2
    assert admit(tmp_path, "--max-per-core", "0", load1=0.1).returncode == 2
    assert admit(tmp_path, "--bogus", load1=0.1).returncode == 2
    assert admit(tmp_path, load1="abc").returncode == 2


def test_admit_prints_one_progress_line_per_waited_minute(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LW_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LW_FAKE_LOAD1", str(CORES * 9))
    monkeypatch.setenv("LW_ADMIT_POLL_S", "15")
    lw = load_module()
    clock = [0.0]
    monkeypatch.setattr(lw.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(lw.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    rc = lw.cmd_admit(argparse.Namespace(wait=130.0, max_per_core=1.5, json=False))
    out = capsys.readouterr()
    assert rc == 75
    assert out.out.startswith("admit hot ")
    assert out.err.count("waiting,") == 2  # at 60 s and 120 s


def test_admit_survives_a_corrupt_state_file(tmp_path):
    # adversary review of e6c538c, finding 2: a crash here ended a wait that had measured a hot machine
    state = tmp_path / "state"
    state.mkdir()
    t = time.time()
    for body in ("[]", '"x"', "null", "{not json", '{"t": 1e12, "hot_since": "x"}', '{"t": "x", "hot_since": 5}',
                 json.dumps({"t": t, "hot_since": True}), json.dumps({"t": t, "hot_since": None}),
                 json.dumps({"t": t, "hot_since": t - 50, "streak": "many"})):
        (state / "state.json").write_text(body)
        hot = admit(tmp_path, "--json", "--wait", "0", load1=CORES * 5)
        assert hot.returncode == 75, (body, hot.stderr)
        assert json.loads(hot.stdout)["status"] == "hot"
        ok = admit(tmp_path, "--json", load1=0.1)
        assert ok.returncode == 0, (body, ok.stderr)
    # the last body has good times and a non-numeric streak: read as 0, not an error
    assert json.loads(hot.stdout)["streak"] == 0


def test_admit_rejects_non_finite_numbers(tmp_path):
    for flag, value in (("--wait", "nan"), ("--wait", "inf"), ("--wait", "-inf"),
                        ("--max-per-core", "nan"), ("--max-per-core", "inf")):
        r = admit(tmp_path, flag, value, load1=0.1)
        assert r.returncode == 2, (flag, value, r.stdout, r.stderr)


def test_admit_rejects_bad_hook_values(tmp_path):
    for env in ({"LW_ADMIT_POLL_S": "nan"}, {"LW_ADMIT_STAGGER_S": "5,99999"}, {"LW_ADMIT_STAGGER_S": "-1,3"},
                {"LW_ADMIT_STAGGER_S": "9,3"}, {"LW_ADMIT_STAGGER_S": "nan,3"}):
        assert admit(tmp_path, load1=0.1, **env).returncode == 2, env


def test_admit_never_busy_loops(tmp_path, monkeypatch):
    monkeypatch.setenv("LW_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LW_FAKE_LOAD1", str(CORES * 9))
    monkeypatch.setenv("LW_ADMIT_POLL_S", "0")
    lw = load_module()
    clock, sleeps = [0.0], []
    monkeypatch.setattr(lw.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(lw.time, "sleep", lambda s: (sleeps.append(s), clock.__setitem__(0, clock[0] + s)))
    assert lw.cmd_admit(argparse.Namespace(wait=10.0, max_per_core=1.5, json=False)) == 75
    assert sleeps and min(sleeps) >= 1.0 and len(sleeps) <= 10
