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


# ---- brief attribution: the work's repo, and whether it ran under bg (incident 20261018-2056-82c4844a) -----------
BG = str(Path.home() / "ops/site-private/bin/bg")


def _work(monkeypatch, procs, parent, cmds, cwds, tops, rows=None, session_top="/r/ade"):
    lw = load_module()
    monkeypatch.setattr(lw, "proc_cwds", lambda pids: {str(p): cwds[str(p)] for p in pids if str(p) in cwds})
    monkeypatch.setattr(lw, "git_top", lambda path: tops.get(path, ""))
    monkeypatch.setattr(lw, "forgejo_remote", lambda top: "")
    monkeypatch.setattr(lw, "main_worktree", lambda top: "")
    monkeypatch.setattr(lw, "pasture_source", lambda top: "")
    monkeypatch.setattr(lw, "registry", lambda: rows or {})
    session = {"id": "s1", "pid": 1000, "agent": "claude", "name": "ade-87", "cwd": "/r/ade"}
    g = {"session": session, "cores": sum(c for _, c in procs),
         "procs": [{"pid": pid, "cores": c, "cmd": "rustc x"} for pid, c in procs]}
    return lw, g, lw.work_repos(g, session_top, parent, cmds)


def test_work_repo_is_the_process_cwd_not_the_sessions(monkeypatch):
    _, _, w = _work(monkeypatch, [(100, 1.0)], {"100": 1000}, {"100": "rustc"}, {"100": "/r/sudo"},
                    {"/r/sudo": "/r/sudo"})
    assert not w["guess"] and [r["top"] for r in w["repos"]] == ["/r/sudo"]


def test_brew_child_in_a_temp_dir_takes_its_ancestors_repo(monkeypatch):
    parent = {"300": 250, "250": 200, "200": 150, "150": 1000}
    cwds = {"300": "/tmp/build", "250": "/tmp", "200": "/r/sudo", "150": "/r/ade"}
    _, _, w = _work(monkeypatch, [(300, 0.8)], parent, {}, cwds, {"/r/sudo": "/r/sudo", "/r/ade": "/r/ade"})
    assert [r["top"] for r in w["repos"]] == ["/r/sudo"]  # nearest ancestor inside a repo, not the farther one


def test_under_bg_and_outside_bg(monkeypatch):
    parent = {"300": 200, "200": 150, "150": 1000, "400": 1000}
    cmds = {"150": f"/bin/bash {BG} just release", "200": "just release"}
    cwds = {"300": "/r/sudo", "400": "/r/sudo"}
    _, _, w = _work(monkeypatch, [(300, 1.0), (400, 0.5)], parent, cmds, cwds, {"/r/sudo": "/r/sudo"})
    r = w["repos"][0]
    assert r["cores"] == 1.5 and r["bg_cores"] == 1.0 and r["rule"] == "release"
    _, _, w = _work(monkeypatch, [(400, 0.5)], parent, cmds, cwds, {"/r/sudo": "/r/sudo"})
    assert w["repos"][0]["bg_cores"] == 0.0


def test_bg_rules_and_lookalikes():
    lw = load_module()
    assert lw.bg_args(f"/bin/bash {BG} pytest tests/test_x.py") == ["pytest", "tests/test_x.py"]
    assert lw.bg_args(f"{BG} just release") == ["just", "release"]
    assert lw.bg_args("cat /Users/x/ops/site-private/bin/bg") is None  # reading it is not running it
    assert lw.bg_args("python other/bin/bg") is None
    assert lw.bg_rule(["just", "release-all"]) == "release"
    assert lw.bg_rule(["just", "build"]) == ""
    assert lw.bg_rule(["just", "release", "--local-tests"]) == ""
    assert lw.bg_rule(["uv", "run", "pytest", "tests/test_x.py"]) == "targeted test"
    assert lw.bg_rule(["pytest", "tests/", "-k", "foo"]) == "targeted test"
    assert lw.bg_rule(["pytest", "tests/"]) == ""


def test_nothing_maps_falls_back_to_the_session_and_says_guess(monkeypatch):
    lw, g, w = _work(monkeypatch, [(100, 1.0)], {"100": 1000}, {}, {"100": "/tmp/x"}, {})
    assert w["guess"] and [r["top"] for r in w["repos"]] == ["/r/ade"]
    text = lw.brief("inc1", g, w, 30.0, 8)
    assert "a guess" in text and "`/r/ade`" in text


def test_two_repos_are_listed_with_their_shares(monkeypatch):
    cwds = {"100": "/r/a", "101": "/r/b", "102": "/tmp/x"}
    lw, g, w = _work(monkeypatch, [(100, 1.2), (101, 0.6), (102, 0.2)], {}, {}, cwds,
                     {"/r/a": "/r/a", "/r/b": "/r/b"})
    assert [(r["top"], round(r["cores"], 1)) for r in w["repos"]] == [("/r/a", 1.2), ("/r/b", 0.6)]
    assert w["unmapped"] == 0.2
    text = lw.brief("inc2", g, w, 30.0, 8)
    assert "a. `/r/a`, 1.2 of those cores" in text and "b. `/r/b`, 0.6" in text
    assert "0.2 cores ran in no git repo" in text and "ci-only add /r/a" in text and "ci-only add /r/b" in text
    assert "ci-only add /r/ade" not in text


def test_brief_for_the_2056_incident(monkeypatch):
    rows = {"/r/sudo": ["ci", "scripts/github-test-ref", "2026-10-18"]}
    parent = {"35811": 35000, "35000": 34000, "34000": 1000}
    cmds = {"34000": f"/bin/bash {BG} just release"}
    cwds = {"35811": "/private/tmp/secretspec-x", "35000": "/private/tmp", "34000": "/r/sudo"}
    lw, g, w = _work(monkeypatch, [(35811, 0.61)], parent, cmds, cwds, {"/r/sudo": "/r/sudo", "/r/ade": "/r/ade"},
                     rows)
    text = lw.brief("20261018-2056-82c4844a", g, w, 39.9, 8)
    assert "`/r/sudo`" in text and "It ran under `bg` (through bg's release rule)." in text
    assert "Your session's cwd (`/r/ade`) is outside it." in text
    assert "ci-only add" not in text and "Nothing to register" in text
    assert "no Forgejo remote" in text and "outside `bg`" not in text


def test_proc_cwds_parses_one_lsof_call(monkeypatch):
    lw = load_module()
    calls = []
    out = "p100\nn/r/a\np101\nn/tmp/x y\n"
    monkeypatch.setattr(lw.subprocess, "run", lambda argv, **kw: calls.append(argv) or
                        subprocess.CompletedProcess(argv, 1, out, ""))
    assert lw.proc_cwds([101, 100, 100, 0]) == {"100": "/r/a", "101": "/tmp/x y"}
    assert len(calls) == 1 and calls[0][-1] == "100,101"
    assert lw.proc_cwds([]) == {} and len(calls) == 1
