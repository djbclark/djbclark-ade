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
             LW_ADMIT_POLL_S="1", LW_ADMIT_STAGGER_S="0,0", LW_BOOST_CALM_S="0")  # 0: the hysteresis has its own tests
    for k in ("LW_FAKE_LOAD1", "LW_FAKE_CHURN", "LW_FAKE_FREE_MB", "LW_FAKE_PAGEINS", "LW_FAKE_AGENTS", "LW_MIN_FREE_MB",
              "LW_MAX_COMPRESSOR_S", "LW_MAX_PAGEINS_S", "LW_MAX_AGENTS"):
        e.pop(k, None)
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
    # the base alone, not the watcher's blame step: a faked load without a measured churn never boosts
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


def test_admit_hot_on_compressor_churn_even_when_load_is_low(tmp_path):
    r = admit(tmp_path, "--wait", "0", "--json", load1=0.1, LW_FAKE_CHURN="90000")
    assert r.returncode == 75, r.stderr
    rec = json.loads(r.stdout)
    assert rec["status"] == "hot" and rec["mem_churn_pages_s"] == 90000 and rec["max_mem_churn_pages_s"] == 20000
    assert rec["refused"] == ["compressor"]


def test_admit_ok_when_churn_is_under_the_limit(tmp_path):
    r = admit(tmp_path, "--wait", "0", load1=0.1, LW_FAKE_CHURN="5000")
    assert r.returncode == 0, r.stderr
    assert "mem_churn=5000" in r.stdout


def test_admit_max_mem_churn_override(tmp_path):
    assert admit(tmp_path, "--wait", "0", "--max-mem-churn", "120000", load1=0.1, LW_FAKE_CHURN="90000").returncode == 0
    assert admit(tmp_path, "--wait", "0", "--max-mem-churn", "0", load1=0.1).returncode == 2


def test_admit_faked_load_alone_reads_zero_churn(tmp_path):
    r = admit(tmp_path, "--wait", "0", "--json", load1=0.1)
    assert json.loads(r.stdout)["mem_churn_pages_s"] == 0


def test_admit_waits_out_a_churn_spike(tmp_path):
    r = admit(tmp_path, "--wait", "20", load1=0.1, LW_FAKE_CHURN="90000,90000,1000")
    assert r.returncode == 0, r.stderr


def test_calm_boost_raises_the_limit_while_churn_is_low(tmp_path):
    """2026-11-01: load up to 4.0 per core (was 2.0 since 2026-10-25) is admitted while the compressor is calm; the default base stays 1.5."""
    calm = {"LW_FAKE_CHURN": "10000"}
    assert admit(tmp_path, load1=CORES * 1.9, **calm).returncode == 0
    rec = json.loads(admit(tmp_path, "--json", load1=CORES * 1.9, **calm).stdout)
    assert rec["status"] == "ok" and rec["max_per_core"] == 4.0
    assert admit(tmp_path, load1=CORES * 4.1, **calm).returncode == 75  # still above the boosted limit
    # a caller that passes the base explicitly (bg does, 2.5 since 2026-11-01) still gets the boost
    assert admit(tmp_path, "--max-per-core", "2.5", load1=CORES * 3.9, **calm).returncode == 0


def test_admit_allows_3_9_per_core_at_low_churn_and_refuses_it_at_high_churn(tmp_path):
    """2026-11-01: 3.9 per core is fine for this machine while the compressor is calm, not once it churns."""
    assert admit(tmp_path, load1=CORES * 3.9, LW_FAKE_CHURN="10000").returncode == 0
    assert admit(tmp_path, load1=CORES * 3.9, LW_FAKE_CHURN="20001").returncode == 75   # above the 20000 line (boost and limit)
    assert admit(tmp_path, load1=CORES * 3.9, LW_FAKE_CHURN="70000").returncode == 75   # far above it


def test_calm_boost_off_when_churn_is_high_unreadable_or_disabled(tmp_path):
    busy = {"LW_FAKE_CHURN": "30000"}  # above the 20000 line: refused outright, and no boost
    assert admit(tmp_path, load1=CORES * 1.9, **busy).returncode == 75
    assert json.loads(admit(tmp_path, "--json", "--wait", "0", load1=CORES * 1.9, **busy).stdout)["max_per_core"] == 1.5
    assert admit(tmp_path, "--boost-per-core", "0", load1=CORES * 1.9, LW_FAKE_CHURN="1000").returncode == 75
    # a faked load without a faked churn reads churn 0 but is not a measurement: no boost
    assert admit(tmp_path, load1=CORES * 1.9).returncode == 75
    assert admit(tmp_path, "--boost-per-core", "nan", load1=1, LW_FAKE_CHURN="1").returncode == 2


def test_admit_limit_unit():
    lw = load_module()
    assert lw.admit_limit(1.5, 20000) == 4.0 and lw.admit_limit(1.5, 20001) == 1.5
    assert lw.admit_limit(1.5, None) == 1.5
    assert lw.admit_limit(1.5, 0, boost=0) == 1.5 and lw.admit_limit(5.0, 0, boost=4.0) == 5.0


# ---- 2026-11-01 memory gates: free floor, compressor, pageins, agent cap, boost hysteresis -------------------------

def refused(r):
    """The `refused` list of a --json admit result."""
    return json.loads(r.stdout).get("refused", [])


def test_free_memory_floor_refuses_below_and_passes_at_the_boundary(tmp_path):
    low = admit(tmp_path, "--wait", "0", "--json", load1=0.1, LW_FAKE_FREE_MB="599.9")
    assert low.returncode == 75, low.stderr
    rec = json.loads(low.stdout)
    assert rec["refused"] == ["free_mem"] and rec["free_mb"] == 599 and rec["min_free_mb"] == 600
    assert "refused=free_mem" in admit(tmp_path, "--wait", "0", load1=0.1, LW_FAKE_FREE_MB="64").stdout
    assert admit(tmp_path, "--wait", "0", load1=0.1, LW_FAKE_FREE_MB="600").returncode == 0
    # tunable by flag and env
    assert admit(tmp_path, "--wait", "0", "--min-free-mb", "300", load1=0.1, LW_FAKE_FREE_MB="400").returncode == 0
    assert admit(tmp_path, "--wait", "0", load1=0.1, LW_FAKE_FREE_MB="1500", LW_MIN_FREE_MB="2000").returncode == 75


def test_compressor_limit_is_20000_per_second(tmp_path):
    assert admit(tmp_path, "--wait", "0", load1=0.1, LW_FAKE_CHURN="20000").returncode == 0
    r = admit(tmp_path, "--wait", "0", "--json", load1=0.1, LW_FAKE_CHURN="20001")
    assert r.returncode == 75 and refused(r) == ["compressor"]
    assert admit(tmp_path, "--wait", "0", load1=0.1, LW_FAKE_CHURN="25000", LW_MAX_COMPRESSOR_S="30000").returncode == 0


def test_pageins_limit_is_1000_per_second(tmp_path):
    assert admit(tmp_path, "--wait", "0", load1=0.1, LW_FAKE_PAGEINS="1000").returncode == 0
    r = admit(tmp_path, "--wait", "0", "--json", load1=0.1, LW_FAKE_PAGEINS="1001")
    rec = json.loads(r.stdout)
    assert r.returncode == 75 and rec["refused"] == ["pageins"] and rec["pageins_s"] == 1001 and rec["max_pageins_s"] == 1000
    assert admit(tmp_path, "--wait", "0", "--max-pageins", "2000", load1=0.1, LW_FAKE_PAGEINS="1760").returncode == 0
    assert admit(tmp_path, "--wait", "0", load1=0.1, LW_FAKE_PAGEINS="1760", LW_MAX_PAGEINS_S="1500").returncode == 75


def test_agent_cap_refuses_at_the_cap_and_zero_turns_it_off(tmp_path):
    assert admit(tmp_path, "--wait", "0", load1=0.1, LW_FAKE_AGENTS="13").returncode == 0
    r = admit(tmp_path, "--wait", "0", "--json", load1=0.1, LW_FAKE_AGENTS="14")
    rec = json.loads(r.stdout)
    assert r.returncode == 75 and rec["refused"] == ["agents"] and rec["agents"] == 14 and rec["max_agents"] == 14
    assert "refused=agents" in admit(tmp_path, "--wait", "0", load1=0.1, LW_FAKE_AGENTS="31").stdout
    assert admit(tmp_path, "--wait", "0", "--max-agents", "20", load1=0.1, LW_FAKE_AGENTS="19").returncode == 0
    assert admit(tmp_path, "--wait", "0", load1=0.1, LW_FAKE_AGENTS="20", LW_MAX_AGENTS="20").returncode == 75
    assert admit(tmp_path, "--wait", "0", load1=0.1, LW_FAKE_AGENTS="99", LW_MAX_AGENTS="0").returncode == 0
    assert admit(tmp_path, "--wait", "0", "--max-agents", "-1", load1=0.1).returncode == 2


def test_every_gate_is_reported_together_and_each_alone_decides(tmp_path):
    r = admit(tmp_path, "--wait", "0", "--json", load1=CORES * 9, LW_FAKE_CHURN="50000", LW_FAKE_FREE_MB="64",
              LW_FAKE_PAGEINS="1760", LW_FAKE_AGENTS="31")
    assert refused(r) == ["load", "compressor", "free_mem", "pageins", "agents"]
    line = admit(tmp_path, "--wait", "0", load1=CORES * 9, LW_FAKE_CHURN="50000", LW_FAKE_FREE_MB="64",
                 LW_FAKE_PAGEINS="1760", LW_FAKE_AGENTS="31").stdout
    for part in ("mem_churn=50000", "free_mb=64", "pageins=1760", "agents=31", "max_mem_churn=20000", "min_free_mb=600",
                 "max_pageins=1000", "max_agents=14"):
        assert part in line, line


def test_admit_waits_out_a_memory_dip(tmp_path):
    r = admit(tmp_path, "--wait", "20", "--json", load1=0.1, LW_FAKE_FREE_MB="64,64,2000")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["status"] == "ok"


def test_a_bad_memory_hook_value_exits_2(tmp_path):
    for k in ("LW_FAKE_FREE_MB", "LW_FAKE_PAGEINS", "LW_FAKE_AGENTS"):
        assert admit(tmp_path, load1=0.1, **{k: "nan"}).returncode == 2, k
        assert admit(tmp_path, load1=0.1, **{k: "abc"}).returncode == 2, k


def calm_file(tmp_path, calm_for, last_age=5):
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    t = time.time()
    (state / "calm.json").write_text(json.dumps({"calm_since": t - calm_for, "last_t": t - last_age}))
    return state / "calm.json"


def boost_env(**kw):
    return dict(LW_BOOST_CALM_S="600", LW_FAKE_CHURN="10000", **kw)


def test_the_boost_waits_out_the_hysteresis(tmp_path):
    heavy = CORES * 3.5  # above the 2.5 base, below the 4.0 boost
    # no history: this reading starts the clock, the base limit holds
    r = admit(tmp_path, "--max-per-core", "2.5", "--json", load1=heavy, **boost_env())
    assert r.returncode == 75, r.stderr
    assert json.loads(r.stdout)["max_per_core"] == 2.5
    calm_file(tmp_path, 570)
    assert admit(tmp_path, "--max-per-core", "2.5", load1=heavy, **boost_env()).returncode == 75
    calm_file(tmp_path, 650)
    r = admit(tmp_path, "--max-per-core", "2.5", "--json", load1=heavy, **boost_env())
    rec = json.loads(r.stdout)
    assert r.returncode == 0, r.stderr
    assert rec["max_per_core"] == 4.0 and rec["calm_for_s"] >= 650


def test_a_hot_reading_resets_the_calm_clock(tmp_path):
    heavy = CORES * 3.5
    f = calm_file(tmp_path, 3600)
    # a compressor spike, even one that admit then refuses, restarts the run
    assert admit(tmp_path, "--wait", "0", load1=0.1, LW_BOOST_CALM_S="600", LW_FAKE_CHURN="30000").returncode == 75
    assert json.loads(f.read_text())["calm_since"] is None
    # the next calm reading starts a NEW run: 10 minutes are still owed
    assert admit(tmp_path, "--max-per-core", "2.5", load1=heavy, **boost_env()).returncode == 75
    since = json.loads(f.read_text())["calm_since"]
    assert since is not None and time.time() - since < 60
    # low free memory and high pageins are hot readings too
    for hot in ({"LW_FAKE_FREE_MB": "100"}, {"LW_FAKE_PAGEINS": "5000"}):
        calm_file(tmp_path, 3600)
        admit(tmp_path, "--wait", "0", load1=0.1, LW_BOOST_CALM_S="600", LW_FAKE_CHURN="10000", **hot)
        assert json.loads(f.read_text())["calm_since"] is None, hot


def test_a_gap_in_the_readings_is_not_calm(tmp_path):
    f = calm_file(tmp_path, 3600, last_age=600)  # nobody looked for ten minutes
    r = admit(tmp_path, "--max-per-core", "2.5", load1=CORES * 3.5, **boost_env())
    assert r.returncode == 75
    assert time.time() - json.loads(f.read_text())["calm_since"] < 60


def test_a_corrupt_calm_file_is_no_history(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    for body in ("[]", "{not json", '{"calm_since": "x", "last_t": 5}', '{"calm_since": 1e300, "last_t": 1e300}'):
        (state / "calm.json").write_text(body)
        assert admit(tmp_path, "--max-per-core", "2.5", load1=CORES * 3.5, **boost_env()).returncode == 75, body


def test_sampler_feeds_the_calm_clock(tmp_path, monkeypatch):
    monkeypatch.setenv("LW_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("LW_FAKE_COMPRESSOR", "0")  # tests: no vm_stat
    lw = load_module()
    st = {}
    lw.sample_calm(st, 1000.0, 5000, False)
    lw.sample_calm(st, 1020.0, 5000, False)
    assert json.loads((tmp_path / "calm.json").read_text()) == {"calm_since": 1000.0, "last_t": 1020.0}
    lw.sample_calm(st, 1040.0, 21000, False)  # churn over the line: hot
    assert json.loads((tmp_path / "calm.json").read_text())["calm_since"] is None
    lw.sample_calm(st, 1060.0, 5000, False)
    lw.sample_calm(st, 1080.0, None, False)   # an unreadable reading is not calm
    assert json.loads((tmp_path / "calm.json").read_text())["calm_since"] is None
    before = (tmp_path / "calm.json").read_text()
    lw.sample_calm(st, 1100.0, 5000, True)    # --dry-run records nothing
    assert (tmp_path / "calm.json").read_text() == before


PS_OUT = """\
  101 /Users/x/.cache/uv/environments-v2/acp-run-80e1/bin/python3.14 /Users/x/.local/bin/acp-run omp -C /w --model m
  102 uv run --quiet --script /Users/x/.local/bin/acp-run omp -C /w --model m
  103 /Users/x/.local/bin/acp-run copilot -C /w
  104 python3 -u /Users/x/src/djbclark-ade/tools/acp-run/acp-run claude -C /w
  105 python3 /Users/x/src/djbclark-ade/bin/acp-dispatch --name acp-run-slice -C /w
  106 vim /Users/x/notes/acp-run.md
  107 grep -n acp-run /tmp/x
  108 /bin/zsh -c acp-run omp -C /w
  109 python3 /Users/x/bin/not-acp-run omp
  110 /Users/x/.cache/uv/environments-v2/acp-run-80e1/bin/python /Users/x/.local/bin/acp-run agy -C /w
"""


def test_agent_count_counts_only_acp_run_processes(monkeypatch):
    lw = load_module()
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=PS_OUT, stderr="")

    monkeypatch.setattr(lw.subprocess, "run", fake_run)
    assert lw.count_agents() == 4  # 101, 103, 104, 110: not the uv wrapper, not a mention, not a lookalike
    assert calls == [["ps", "-axo", "pid=,args="]]
    monkeypatch.setattr(lw.os, "getpid", lambda: 103)  # this process never counts itself
    assert lw.count_agents() == 3
    monkeypatch.setattr(lw.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 1, stdout="", stderr="x"))
    assert lw.count_agents() is None

    def boom(argv, **kw):
        raise OSError("no ps")

    monkeypatch.setattr(lw.subprocess, "run", boom)
    assert lw.count_agents() is None


VM_STAT = """\
Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                                3969.
Pages active:                            300000.
Pages speculative:                        1000.
Pageins:                                 50000.
Compressions:                           700000.
Decompressions:                         300000.
"""


def test_vm_stat_snapshot_parses_free_plus_speculative(monkeypatch):
    lw = load_module()
    monkeypatch.setattr(lw.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout=VM_STAT, stderr=""))
    s = lw.vm_snapshot()
    assert s == {"free_mb": (3969 + 1000) * 16384 / 1048576, "compress": 1000000, "pageins": 50000}
    monkeypatch.setattr(lw.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout="junk", stderr=""))
    monkeypatch.setattr(lw, "_proc_snapshot", lambda: None)
    assert lw.vm_snapshot() is None


def test_linux_proc_equivalents(monkeypatch):
    lw = load_module()
    files = {"/proc/meminfo": "MemTotal: 16000000 kB\nMemFree: 100 kB\nMemAvailable: 2048000 kB\n",
             "/proc/vmstat": "pgmajfault 7\npswpin 30\npswpout 12\n"}
    def read_text(self, *a, **k):
        if str(self) not in files:
            raise FileNotFoundError(str(self))
        return files[str(self)]

    monkeypatch.setattr(lw.Path, "read_text", read_text)
    assert lw._proc_snapshot() == {"free_mb": 2000.0, "compress": 42, "pageins": 7}
    files["/proc/meminfo"] = "MemFree: 512 kB\n"
    assert lw._proc_snapshot()["free_mb"] == 0.5  # no MemAvailable: MemFree
    del files["/proc/vmstat"]
    assert lw._proc_snapshot() is None


def real_admit(lw, monkeypatch, capsys, snaps, agents, tmp_path):
    """cmd_admit on the real (non-faked) path: vm_snapshot returns `snaps` in order, ps says `agents`."""
    for k in ("LW_FAKE_LOAD1", "LW_FAKE_CHURN", "LW_FAKE_FREE_MB", "LW_FAKE_PAGEINS", "LW_FAKE_AGENTS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LW_STATE_DIR", str(tmp_path))
    lw.STATE_DIR = tmp_path
    seq = iter(snaps)
    sleeps = []
    monkeypatch.setattr(lw, "vm_snapshot", lambda: next(seq))
    monkeypatch.setattr(lw, "count_agents", lambda: agents)
    monkeypatch.setattr(lw.os, "getloadavg", lambda: (0.1, 0.1, 0.1))
    monkeypatch.setattr(lw.time, "sleep", sleeps.append)
    ticks = iter(range(0, 1000, 2))  # monotonic advances 2 s per call: the sample window
    monkeypatch.setattr(lw.time, "monotonic", lambda: float(next(ticks)))
    rc = lw.cmd_admit(argparse.Namespace(wait=0.0, max_per_core=1.5, json=True))
    return rc, json.loads(capsys.readouterr().out), sleeps


def test_real_path_computes_rates_over_the_two_second_sample(tmp_path, monkeypatch, capsys):
    lw = load_module()
    a = {"free_mb": 900.0, "compress": 1000, "pageins": 100}
    b = {"free_mb": 700.0, "compress": 1000 + 2 * 20000, "pageins": 100 + 2 * 1000}  # exactly the limits, over 2 s
    rc, rec, sleeps = real_admit(lw, monkeypatch, capsys, [a, b], 13, tmp_path)
    assert rc == 0, rec
    assert rec["mem_churn_pages_s"] == 20000 and rec["pageins_s"] == 1000 and rec["free_mb"] == 700 and rec["agents"] == 13
    assert sleeps == [lw.ADMIT_MEM_WINDOW_S] and lw.ADMIT_MEM_WINDOW_S == 2.0
    over = {"free_mb": 599.0, "compress": 1000 + 2 * 20002, "pageins": 100 + 2 * 1002}
    rc, rec, _ = real_admit(lw, monkeypatch, capsys, [a, over], 14, tmp_path)
    assert rc == 75 and rec["refused"] == ["compressor", "free_mem", "pageins", "agents"]


def test_unreadable_memory_fails_open_and_says_so(tmp_path, monkeypatch, capsys):
    lw = load_module()
    rc, rec, _ = real_admit(lw, monkeypatch, capsys, [None], None, tmp_path)
    assert rc == 0 and rec["status"] == "ok" and rec["unreadable"] == ["memory", "agents"]
    assert "mem_churn_pages_s" not in rec and "free_mb" not in rec
    assert "unreadable=memory,agents" in lw.admit_line(rec)
