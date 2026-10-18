"""bin/load-watch: the ci-only registry `bg` reads, the sample window, and incident acks. No launchd, no relay."""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

LW = Path(__file__).resolve().parent.parent / "bin" / "load-watch"


def run(tmp_path, *args):
    env = dict(os.environ, LW_STATE_DIR=str(tmp_path / "state"), LW_REGISTRY=str(tmp_path / "ci-only.tsv"))
    return subprocess.run([sys.executable, str(LW), *args], capture_output=True, text=True, env=env, timeout=30)


def load_module():
    loader = importlib.machinery.SourceFileLoader("load_watch", str(LW))
    spec = importlib.util.spec_from_loader("load_watch", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_ci_only_add_check_rm(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    top = os.path.realpath(repo)
    assert run(tmp_path, "ci-only", "add", str(repo / "."), "scripts/ci-run test").returncode == 0
    r = run(tmp_path, "ci-only", "check", str(repo))
    assert (r.returncode, r.stdout.strip()) == (0, "scripts/ci-run test")
    line = [ln for ln in (tmp_path / "ci-only.tsv").read_text().splitlines() if not ln.startswith("#")][0]
    assert line.split("\t")[:3] == [top, "ci", "scripts/ci-run test"]  # repo, mode, CI command, date
    assert run(tmp_path, "ci-only", "check", str(tmp_path)).returncode == 1
    assert run(tmp_path, "ci-only", "rm", str(repo)).returncode == 0
    assert run(tmp_path, "ci-only", "check", str(repo)).returncode == 1


def test_ci_only_add_needs_command(tmp_path):
    assert run(tmp_path, "ci-only", "add", str(tmp_path)).returncode == 2


def test_window_means_and_exited_parents():
    lw = load_module()
    st = {"samples": [{"t": 1, "d": {"10": [2.0, 501, "cc1", 5]}},
                      {"t": 2, "d": {"10": [1.0, 501, "cc1", 5], "11": [0.5, 501, "ld", 5]}}]}
    use, n = lw.window(st)
    assert n == 2 and use["10"][0] == 3.0 and use["11"][0] == 0.5
    parent = lw.ppids(st, {"12": (7, 501, 0.0, "make")})
    assert parent == {"10": 5, "11": 5, "12": 7}  # exited pids keep their ppid for attribution


def test_ack_records_and_unknown_id(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "incidents.jsonl").write_text(json.dumps({"id": "x1", "t": "", "load1": 20, "agent": "claude",
                                                       "session": "s", "cores": 3, "relayed": True}) + "\n")
    assert run(tmp_path, "ack", "x1", "moved to CI").returncode == 0
    assert "moved to CI" in json.loads((state / "incidents.jsonl").read_text())["ack"]
    assert run(tmp_path, "ack", "nope", "x").returncode == 1


def _sampler(tmp_path, monkeypatch):
    lw = load_module()
    clock = {"t": 1000.0}
    monkeypatch.setattr(lw, "STATE_DIR", tmp_path)
    monkeypatch.setattr(lw, "HERMES_PING", tmp_path / "no-such-ping")
    monkeypatch.setattr(lw, "now", lambda: clock["t"])
    monkeypatch.setattr(lw.os, "getloadavg", lambda: (40.0, 40.0, 40.0))
    monkeypatch.setattr(lw.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(lw, "ps_table", lambda: {"1": (0, 0, 0.1, "x")})
    monkeypatch.setattr(lw, "attribute", lambda use, span, parent: ({}, []))
    monkeypatch.setattr(lw, "guard", lambda *args: None)

    class A:
        dry_run = False
        verbose = False

    def at(t):
        clock["t"] = t
        lw.cmd_sample(A())
        return (tmp_path / "sample.log").read_text() if (tmp_path / "sample.log").exists() else ""
    return at


def test_sustain_is_time_based_and_tolerates_slow_samples(tmp_path, monkeypatch):
    at = _sampler(tmp_path, monkeypatch)
    assert at(1000) == ""
    assert at(1200) == ""            # 200 s hot: not yet
    assert "sustained load" in at(1400)  # 400 s hot, samples 200 s apart (a stalled launchd)


def test_long_gap_restarts_the_clock(tmp_path, monkeypatch):
    at = _sampler(tmp_path, monkeypatch)
    at(1000)
    assert at(2000) == ""            # 1000 s gap is a sleep: hot clock restarts at 2000
    assert at(2200) == ""
    assert "sustained load" in at(2400)


def test_ci_decide_check_modes_and_legacy_rows(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    top = os.path.realpath(repo)
    (tmp_path / "ci-only.tsv").write_text(f"{top}\tscripts/ci-run\t2026-10-18\n")  # pre-decide 3-column row
    assert run(tmp_path, "ci", "check", str(repo)).stdout.split("\t")[:2] == ["ci", "scripts/ci-run"]
    assert run(tmp_path, "ci-only", "check", str(repo)).stdout.strip() == "scripts/ci-run"
    assert run(tmp_path, "ci", "decide", str(repo), "local", "needs Xcode").returncode == 0
    assert run(tmp_path, "ci", "check", str(repo)).stdout.split("\t")[:2] == ["local", "needs Xcode"]
    assert run(tmp_path, "ci-only", "check", str(repo)).returncode == 1  # bg's old reader: only ci refuses
    assert run(tmp_path, "ci", "decide", str(repo), "local").returncode == 2  # a reason is required
    assert run(tmp_path, "ci", "check", str(tmp_path)).returncode == 1  # undecided


def test_ci_worktree_and_glob_take_a_decision(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(git + ["commit", "-q", "--allow-empty", "-m", "x"], check=True)
    subprocess.run(git + ["worktree", "add", "-q", str(tmp_path / "wt")], check=True)
    assert run(tmp_path, "ci", "decide", str(repo), "pending", "seeded").returncode == 0
    out = run(tmp_path, "ci", "check", str(tmp_path / "wt")).stdout.strip().split("\t")
    assert out == ["pending", "seeded", os.path.realpath(repo)]
    other = tmp_path / "pastures" / "p1"
    other.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    assert run(tmp_path, "ci", "check", str(other)).returncode == 1
    glob = os.path.realpath(tmp_path / "pastures") + "/*"
    assert run(tmp_path, "ci", "decide", glob, "local", "queue in flight").returncode == 0
    assert run(tmp_path, "ci", "check", str(other)).stdout.split("\t")[0] == "local"


def _guard(tmp_path, monkeypatch, jobs, runs=None):
    lw = load_module()
    calls = []
    monkeypatch.setattr(lw, "STATE_DIR", tmp_path)
    monkeypatch.setattr(lw, "GUARD", tmp_path / "guard.tsv")
    monkeypatch.setattr(lw, "HERMES_PING", tmp_path / "no-such-ping")
    monkeypatch.setattr(lw, "launchd_jobs", lambda: dict(jobs))
    monkeypatch.setattr(lw, "job_info", lambda label: (runs["n"] if runs else None, str(tmp_path / "j.plist")))
    monkeypatch.setattr(lw.time, "sleep", lambda s: None)
    monkeypatch.setattr(lw.subprocess, "run", lambda argv, **kw: calls.append(argv) or
                        subprocess.CompletedProcess(argv, 0, "", ""))
    (tmp_path / "j.plist").write_text("x")
    return lw, calls


def test_guard_hang_cools_down_retests_and_passes(tmp_path, monkeypatch):
    jobs = {"com.x.job": (100, "0")}
    lw, calls = _guard(tmp_path, monkeypatch, jobs)
    (tmp_path / "guard.tsv").write_text("com.x.job\thang_s=120\tAFS\n")
    table = {"100": (1, 501, 0.0, "python lockers"), "101": (100, 501, 0.0, "aklog -path /afs/x")}
    lw.PSTATE.clear()
    lw.PSTATE.update({"100": ("S", 1000), "101": ("U", 1000)})
    st = {}
    lw.guard(st, table, 1000.0, False)
    assert st["guard"]["com.x.job"].get("state") is None      # stuck, but not for 120 s yet
    lw.guard(st, table, 1130.0, False)
    s = st["guard"]["com.x.job"]
    assert s["state"] == "cooldown" and "hung" in s["trip"]
    assert ["launchctl", "bootout", f"gui/{lw.MY_UID}/com.x.job"] in calls
    assert any(c[:2] == ["kill", "-TERM"] and "101" in c for c in calls)
    jobs.clear()                                              # booted out
    lw.guard(st, {}, 1130.0 + lw.GUARD_COOLDOWN_S, False)
    assert s["state"] == "testing"
    assert ["launchctl", "bootstrap", f"gui/{lw.MY_UID}", str(tmp_path / "j.plist")] in calls
    lw.guard(st, {}, 1130.0 + lw.GUARD_COOLDOWN_S + lw.GUARD_TEST_S, False)
    assert s["state"] == "ok"


def test_guard_fifth_round_in_a_day_stops_for_good(tmp_path, monkeypatch):
    lw, calls = _guard(tmp_path, monkeypatch, {"com.x.job": (100, "0")})
    (tmp_path / "guard.tsv").write_text("com.x.job\tmax_rss_mb=10\t\n")
    lw.PSTATE.clear()
    lw.PSTATE["100"] = ("S", 50 * 1024)
    t = 10000.0
    st = {"guard": {"com.x.job": {"rounds": [t - 4000, t - 3000, t - 2000, t - 1000]}}}
    lw.guard(st, {"100": (1, 501, 0.0, "hog")}, t, False)
    assert st["guard"]["com.x.job"]["state"] == "permanent"
    assert ["launchctl", "disable", f"gui/{lw.MY_UID}/com.x.job"] in calls


def test_guard_catches_a_crash_loop_on_any_job(tmp_path, monkeypatch):
    runs = {"n": 100}
    lw, calls = _guard(tmp_path, monkeypatch, {"com.y.loop": (None, "1")}, runs)
    lw.PSTATE.clear()
    st = {}
    lw.guard(st, {}, 1000.0, False)
    runs["n"] = 130
    lw.guard(st, {}, 1000.0 + lw.LOOP_CHECK_S, False)
    s = st["guard"]["com.y.loop"]
    assert s["state"] == "cooldown" and "crash loop: 30 restarts" in s["trip"]
