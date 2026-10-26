"""bin/load-watch: the ci-only registry `bg` reads, the sample window, and incident acks. No launchd, no relay."""
import importlib.machinery
import importlib.util
import itertools
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
    at.lw = lw
    return at


def test_sustain_is_time_based_and_tolerates_slow_samples(tmp_path, monkeypatch):
    at = _sampler(tmp_path, monkeypatch)
    assert at(1000) == ""
    assert at(1200) == ""            # 200 s hot: not yet
    assert "sustained load" in at(1400)  # 400 s hot, samples 200 s apart (a stalled launchd)



def test_unexplained_load_reaches_the_watcher_hourly(tmp_path, monkeypatch):
    """Hermes hears an unexplained sustained load every 6 h; the watcher every hour (djbclark, 2026-10-20)."""
    at = _sampler(tmp_path, monkeypatch)
    lw = at.lw
    load = {"v": 40.0}
    monkeypatch.setattr(lw.os, "getloadavg", lambda: (load["v"],) * 3)
    sent = []
    monkeypatch.setattr(lw, "send_to", lambda w, text: sent.append(text) or True)
    lw.save_watcher({"channel": "paseo", "target": "agent-a"})

    def episode(start):
        load["v"] = 40.0
        at(start)
        at(start + 400)
        load["v"] = 1.0
        at(start + 500)  # cools off: the next spike is a new episode

    episode(1000)
    assert len(sent) == 1 and "no agent build behind it" in sent[0]
    episode(2000)                      # 1000 s later: inside the hour
    assert len(sent) == 1
    episode(1000 + lw.WATCHER_NOCPU_S + 100)
    assert len(sent) == 2

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



def test_guard_catches_a_slow_crash_loop(tmp_path, monkeypatch):
    """litellm, 2026-10-20: a restart every ~32 s stays under the fast rule (20 per 10 min) for ever; the slow
    rule (60 in 2 h) must trip it."""
    runs = {"n": 100}
    lw, calls = _guard(tmp_path, monkeypatch, {"com.y.slow": (None, "1")}, runs)
    lw.PSTATE.clear()
    st, t, checks = {}, 1000.0, 0
    while st.get("guard", {}).get("com.y.slow", {}).get("state") != "cooldown":
        assert checks < 60, "slow loop never tripped"
        lw.guard(st, {}, t, False)
        t += lw.LOOP_CHECK_S
        runs["n"] += 3  # 15 per 10 min: under the fast rule
        checks += 1
    s = st["guard"]["com.y.slow"]
    assert "crash loop: 60 restarts in 40 min" in s["trip"]
    assert ["launchctl", "bootout", f"gui/{lw.MY_UID}/com.y.slow"] in calls

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


def fake_paseo(tmp_path, rc=0):
    """A `paseo` stand-in that appends its argv (one JSON list per line) to sent.jsonl."""
    log = tmp_path / "sent.jsonl"
    cli = tmp_path / "paseo"
    cli.write_text(f"#!{sys.executable}\nimport json, sys\nopen({str(log)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
                   f"sys.exit({rc})\n")
    cli.chmod(0o755)
    return cli, log


def run_env(tmp_path, env, *args):
    base = {k: v for k, v in os.environ.items() if k not in ("PASEO_AGENT_ID", "PASEO_CLI", "CLAUDE_CODE_SESSION_ID")}
    base.update(LW_STATE_DIR=str(tmp_path / "state"), LW_REGISTRY=str(tmp_path / "ci-only.tsv"), **env)
    return subprocess.run([sys.executable, str(LW), *args], capture_output=True, text=True, env=base, timeout=30)


def test_watcher_set_from_paseo_env_show_clear(tmp_path):
    cli, log = fake_paseo(tmp_path)
    env = {"PASEO_AGENT_ID": "agent-a", "PASEO_CLI": str(cli), "CLAUDE_CODE_SESSION_ID": "sid-a"}
    assert run_env(tmp_path, {}, "watcher", "show").returncode == 1
    r = run_env(tmp_path, env, "watcher", "set", "--name", "lw", "--chain", "load-spike-monitor-t")
    assert r.returncode == 0 and "paseo agent-a" in r.stdout
    w = json.loads(run_env(tmp_path, {}, "watcher", "show", "--json").stdout)
    assert (w["channel"], w["target"], w["sid"], w["paseo_cli"], w["chain"]) == \
        ("paseo", "agent-a", "sid-a", str(cli), "load-spike-monitor-t")
    assert not log.exists()  # nobody to tell on a first set
    assert run_env(tmp_path, {}, "watcher", "clear", "someone-else").returncode == 1
    assert run_env(tmp_path, {}, "watcher", "clear", "sid-a").returncode == 0
    assert run_env(tmp_path, {}, "watcher", "show").returncode == 1


def test_watcher_set_replaces_and_tells_the_old_one(tmp_path):
    cli, log = fake_paseo(tmp_path)
    assert run_env(tmp_path, {"PASEO_AGENT_ID": "old", "PASEO_CLI": str(cli)}, "watcher", "set").returncode == 0
    r = run_env(tmp_path, {"PASEO_AGENT_ID": "new", "PASEO_CLI": str(cli)}, "watcher", "set", "--name", "B")
    assert r.returncode == 0 and "replaced paseo old" in r.stdout and "told the old watcher" in r.stdout
    sent = [json.loads(ln) for ln in log.read_text().splitlines()]
    assert len(sent) == 1 and sent[0][:7] == ["send", "--no-wait", "--json", "--behavior", "steer", "--", "old"]
    assert "no longer the load watcher" in sent[0][-1] and "B took over" in sent[0][-1]
    assert json.loads((tmp_path / "state" / "watcher.json").read_text())["target"] == "new"


def fake_send(monkeypatch, lw, results, clock=None):
    """Fake subprocess.run and time.sleep for send_to: `results` is a list of (rc, stderr) (or (rc, stderr, stdout)),
    the last one repeats; `paseo send --json` writes its error to stderr. Returns (argvs, pauses, timeouts)."""
    argvs, pauses, timeouts = [], [], []

    def run(argv, **kw):
        argvs.append(argv)
        timeouts.append(kw.get("timeout"))
        res = results[min(len(argvs), len(results)) - 1]
        return subprocess.CompletedProcess(argv, res[0], res[2] if len(res) > 2 else "", res[1])

    monkeypatch.setattr(lw.subprocess, "run", run)
    monkeypatch.setattr(lw.time, "sleep", lambda s: pauses.append(s))
    if clock is not None:
        monkeypatch.setattr(lw.time, "monotonic", clock)
    return argvs, pauses, timeouts


def err(code, message="x"):
    return json.dumps({"error": {"code": code, "message": message}})


PASEO_W = {"channel": "paseo", "target": "agent-a", "paseo_cli": "paseo-fake"}
UNREACHABLE = err("DAEMON_UNREACHABLE", "Cannot connect to daemon")


def test_send_to_first_attempt_succeeds_without_retry(monkeypatch):
    lw = load_module()
    argvs, pauses, timeouts = fake_send(monkeypatch, lw, [(0, "")])
    assert lw.send_to(PASEO_W, "hi") is True
    assert len(argvs) == 1 and not pauses and timeouts == [60]
    assert argvs[0] == ["paseo-fake", "send", "--no-wait", "--json", "--behavior", "steer", "--", "agent-a", "hi"]


def test_send_to_text_starting_with_a_dash_stays_after_the_separator(monkeypatch):
    lw = load_module()
    argvs, _, _ = fake_send(monkeypatch, lw, [(0, "")])
    assert lw.send_to(PASEO_W, "--prompt-file=/x") is True
    argv = argvs[0]
    assert argv.index("--") < argv.index("agent-a") < argv.index("--prompt-file=/x") == len(argv) - 1


def test_send_to_retries_each_real_restart_code_then_succeeds(monkeypatch):
    lw = load_module()
    assert set(lw.SEND_TRANSIENT) == {"DAEMON_UNREACHABLE", "DAEMON_CONNECTION_LOST", "DAEMON_NOT_READY",
                                      "DAEMON_NOT_RUNNING"}
    for code in ("DAEMON_UNREACHABLE", "DAEMON_CONNECTION_LOST", "DAEMON_NOT_READY", "DAEMON_NOT_RUNNING"):
        argvs, pauses, _ = fake_send(monkeypatch, lw, [(1, err(code)), (0, "")])
        assert lw.send_to(PASEO_W, "hi") is True, code
        assert len(argvs) == 2 and pauses == [lw.SEND_RETRY_PAUSE_S], code


def test_send_to_reads_the_code_from_stdout_too(monkeypatch):
    lw = load_module()
    argvs, pauses, _ = fake_send(monkeypatch, lw, [(1, "", err("DAEMON_NOT_RUNNING")), (0, "")])
    assert lw.send_to(PASEO_W, "hi") is True and len(argvs) == 2 and len(pauses) == 1


def test_send_to_gives_up_after_two_retries(monkeypatch):
    lw = load_module()
    argvs, pauses, _ = fake_send(monkeypatch, lw, [(1, UNREACHABLE)])
    assert lw.send_to(PASEO_W, "hi") is False
    assert len(argvs) == 1 + lw.SEND_RETRIES == 3 and len(pauses) == 2
    assert lw.SEND_RETRIES * lw.SEND_RETRY_PAUSE_S < lw.SEND_RETRY_BUDGET_S <= 30


def test_send_to_does_not_retry_other_failures(monkeypatch):
    lw = load_module()
    argvs, pauses, _ = fake_send(monkeypatch, lw, [(1, err("SEND_FAILED", "Agent not found"))])
    assert lw.send_to(PASEO_W, "hi") is False
    assert len(argvs) == 1 and not pauses


def test_send_transient_is_an_exact_code_match():
    lw = load_module()
    run = lambda err_, out="": subprocess.CompletedProcess([], 1, out, err_)  # noqa: E731
    # the four real codes, on stderr or stdout
    for code in lw.SEND_TRANSIENT:
        assert lw.send_transient(run(err(code))) and lw.send_transient(run("", err(code)))
    # another code that merely contains the text of a real one
    for code in ("AGENT_NOT_READY", "PROVIDER_NOT_READY", "DAEMON_NOT_READY_YET", "XDAEMON_NOT_RUNNING", "CONNECTION_LOST",
                 "NOT_READY", "SEND_FAILED"):
        assert not lw.send_transient(run(err(code))), code
    # the text inside prose, in the message, in details or in an unrelated field
    assert not lw.send_transient(run(err("SEND_FAILED", "Failed to send: DAEMON_NOT_READY DAEMON_UNREACHABLE")))
    assert not lw.send_transient(run(json.dumps({"error": {"code": "SEND_FAILED", "details": "DAEMON_NOT_RUNNING"}})))
    assert not lw.send_transient(run("Error: DAEMON_NOT_RUNNING: Cannot connect to daemon"))
    # non-JSON, empty, None and wrongly shaped output
    for bad in ("", "not json DAEMON_UNREACHABLE", "[1, 2]", '"DAEMON_UNREACHABLE"', "null", "42",
                '{"error": "DAEMON_UNREACHABLE"}', '{"error": {"code": ["DAEMON_UNREACHABLE"]}}', '{"error": null}'):
        assert not lw.send_transient(run(bad)), bad
        assert not lw.send_transient(run("", bad)), bad
    assert not lw.send_transient(subprocess.CompletedProcess([], 1, None, None))


def test_send_to_a_code_named_only_in_prose_is_not_retried(monkeypatch):
    lw = load_module()
    for e in (err("AGENT_NOT_READY"), "DAEMON_NOT_READY: still starting", err("SEND_FAILED", "DAEMON_UNREACHABLE")):
        argvs, pauses, _ = fake_send(monkeypatch, lw, [(1, e)])
        assert lw.send_to(PASEO_W, "hi") is False
        assert len(argvs) == 1 and not pauses, e
    assert lw._paseo_down is False


def test_send_to_timeouts_stay_inside_the_budget(monkeypatch):
    lw = load_module()
    now = [0.0]
    pauses_seen = []

    def clock():
        return now[0]

    argvs, pauses, timeouts = fake_send(monkeypatch, lw, [(1, UNREACHABLE)], clock=clock)
    monkeypatch.setattr(lw.time, "sleep", lambda s: (pauses_seen.append(s), now.__setitem__(0, now[0] + s + 7.0)))
    assert lw.send_to(PASEO_W, "hi") is False
    assert timeouts[0] == 60
    assert len(timeouts) >= 2
    for t in timeouts[1:]:
        assert 1.0 <= t <= lw.SEND_RETRY_BUDGET_S - lw.SEND_RETRY_PAUSE_S, timeouts
    # each pause here advances the clock 12 s: the retries start at 12 s and 24 s, so their timeouts are 18 and 6
    assert timeouts == [60, lw.SEND_RETRY_BUDGET_S - 12.0, lw.SEND_RETRY_BUDGET_S - 24.0]


def test_send_to_retry_timeout_never_drops_below_one_second(monkeypatch):
    lw = load_module()
    clock = itertools.chain([0.0, 24.5], itertools.repeat(29.5))  # start, check before the pause, then 0.5 s of budget left
    argvs, pauses, timeouts = fake_send(monkeypatch, lw, [(1, UNREACHABLE)], clock=lambda: next(clock))
    assert lw.send_to(PASEO_W, "hi") is False
    assert timeouts == [60, 1.0] and len(pauses) == 1


def test_send_to_retry_stays_inside_the_budget(monkeypatch):
    lw = load_module()
    clock = itertools.chain([0.0], itertools.repeat(28.0))  # the first attempt took 28 s: no pause fits in 30 s
    argvs, pauses, _ = fake_send(monkeypatch, lw, [(1, UNREACHABLE)], clock=lambda: next(clock))
    assert lw.send_to(PASEO_W, "hi") is False
    assert len(argvs) == 1 and not pauses


def test_send_to_after_giving_up_later_sends_make_one_attempt(monkeypatch):
    lw = load_module()
    argvs, pauses, _ = fake_send(monkeypatch, lw, [(1, UNREACHABLE)])
    assert lw._paseo_down is False
    assert lw.send_to(PASEO_W, "a") is False
    assert len(argvs) == 3 and len(pauses) == 2 and lw._paseo_down is True
    for n in (4, 5):
        assert lw.send_to(PASEO_W, "b") is False
        assert len(argvs) == n and len(pauses) == 2   # one attempt each, no pause
    # a success proves the daemon is back: retries return
    argvs2, pauses2, _ = fake_send(monkeypatch, lw, [(0, "")])
    assert lw.send_to(PASEO_W, "c") is True and lw._paseo_down is False
    argvs3, pauses3, _ = fake_send(monkeypatch, lw, [(1, UNREACHABLE), (0, "")])
    assert lw.send_to(PASEO_W, "d") is True and len(argvs3) == 2 and len(pauses3) == 1


def test_send_to_running_out_of_budget_on_a_restart_code_also_gives_up_for_the_process(monkeypatch):
    lw = load_module()
    clock = itertools.chain([0.0], itertools.repeat(28.0))
    argvs, pauses, _ = fake_send(monkeypatch, lw, [(1, UNREACHABLE)], clock=lambda: next(clock))
    assert lw.send_to(PASEO_W, "a") is False and lw._paseo_down is True
    assert len(argvs) == 1 and not pauses


def test_send_to_a_non_restart_failure_does_not_set_the_process_flag(monkeypatch):
    lw = load_module()
    fake_send(monkeypatch, lw, [(1, err("SEND_FAILED", "Agent not found"))])
    assert lw.send_to(PASEO_W, "a") is False and lw._paseo_down is False


def test_send_to_relay_channel_never_sets_or_reads_the_process_flag(monkeypatch):
    lw = load_module()
    argvs, pauses, _ = fake_send(monkeypatch, lw, [(1, UNREACHABLE)])
    assert lw.send_to({"channel": "relay", "target": "t"}, "hi") is False
    assert lw._paseo_down is False
    lw._paseo_down = True
    fake_send(monkeypatch, lw, [(0, "")])
    assert lw.send_to({"channel": "relay", "target": "t"}, "hi") is True and lw._paseo_down is True


def test_send_to_timeout_and_oserror_do_not_escape(monkeypatch):
    lw = load_module()
    pauses = []
    monkeypatch.setattr(lw.time, "sleep", lambda s: pauses.append(s))
    for exc in (subprocess.TimeoutExpired("paseo", 60), OSError("gone")):
        def run(argv, exc=exc, **kw):
            raise exc
        monkeypatch.setattr(lw.subprocess, "run", run)
        assert lw.send_to(PASEO_W, "hi") is False
    assert not pauses


def test_send_to_relay_channel_is_one_attempt_even_on_a_restart_code(monkeypatch):
    lw = load_module()
    argvs, pauses, _ = fake_send(monkeypatch, lw, [(1, UNREACHABLE), (0, "")])
    assert lw.send_to({"channel": "relay", "target": "t"}, "hi") is False
    assert len(argvs) == 1 and not pauses and "relay.py" in argvs[0][1] and "--json" not in argvs[0]
    assert argvs[0][2:] == ["t", "hi", "--no-defer", "--no-ack"] and "--" not in argvs[0]


def test_send_to_relay_defers_only_when_asked_for_the_registration_check(monkeypatch):
    lw = load_module()
    argvs, _, _ = fake_send(monkeypatch, lw, [(0, "")])
    assert lw.send_to({"channel": "relay", "target": "t"}, "hi", defer=True) is True
    assert argvs[0][2:] == ["t", "hi", "--no-ack"]


def test_notify_never_lets_relay_queue_the_incident_brief(monkeypatch):
    lw = load_module()
    argvs = []

    def run(argv, **kw):
        argvs.append(argv)
        return subprocess.CompletedProcess(argv, 1, "", "relay: [x] not sent: it is working")
    monkeypatch.setattr(lw.subprocess, "run", run)
    g = {"session": {"id": "abcd1234", "sid": "abcd1234-0000", "agent": "omp", "name": "n", "where": "herdr"},
         "procs": [{"cmd": "cargo build", "cores": 3.0}], "cores": 3.0}
    relayed, ping = lw.notify("inc1", g, "/tmp/top", "/tmp/brief.md", 12.0, 8, False)
    assert relayed is False and "could not reach it" in ping and "acp-dispatch cursor" in ping
    relay_argv = next(a for a in argvs if "relay.py" in a[1])
    assert relay_argv[-2:] == ["--no-defer", "--no-ack"] and relay_argv[2] == "abcd1234-0000"


def test_watcher_set_needs_a_session(tmp_path):
    assert run_env(tmp_path, {}, "watcher", "set").returncode == 2


def test_tell_watcher_skips_relayed_offender_and_stamps(tmp_path, monkeypatch):
    lw = load_module()
    monkeypatch.setattr(lw, "STATE_DIR", tmp_path)
    sent = []
    monkeypatch.setattr(lw, "send_to", lambda w, text: sent.append((w["target"], text)) or True)
    assert lw.tell_watcher("x.", False) is None  # no watcher registered
    lw.save_watcher({"channel": "paseo", "target": "agent-a", "sid": "sid-a"})
    assert lw.tell_watcher("x.", False, skip={"sid-a"}) is None and not sent
    assert lw.tell_watcher("load 30.", False) is True
    assert sent[0][0] == "agent-a" and "load 30." in sent[0][1] and "loadwatch skill" in sent[0][1]
    assert "last_ok" in json.loads((tmp_path / "watcher.json").read_text())
    monkeypatch.setattr(lw, "send_to", lambda w, text: False)
    assert lw.tell_watcher("y.", False) is False
    assert "last_fail" in json.loads((tmp_path / "watcher.json").read_text())


def test_watcher_record_must_be_well_formed(tmp_path, monkeypatch):
    lw = load_module()
    monkeypatch.setattr(lw, "STATE_DIR", tmp_path)
    for bad in ("[]", "{}", '{"channel": "smoke", "target": "x"}', "not json"):
        (tmp_path / "watcher.json").write_text(bad)
        assert lw.watcher() is None
