"""GUI-hog dialog PR 3b (docs/gui-hog-dialog.md H1 g, H3, H4 a-e/h/i): the live trigger and launch, the snapshot, `vet` (the live checks before a Quit),
the identity re-verification, the carry-overs from the PR 3a reviews, `ade-gui-build`, and contract tests over the Swift sources (Wait is a default
no-op, no key equivalents, no shell). Stdlib and fakes only, so it runs on Linux CI; the Swift view's own self-test runs where `swiftc` exists."""
import ast
import calendar
import fcntl
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import gui_hog as gh  # noqa: E402
from test_gui_hog import FIXTURE, ME, NOW, SLACK, app, cfg, group, hold, shipped, tbl  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
SWIFT = ROOT / "macos" / "gui-hog"


@pytest.fixture(autouse=True)
def _never_start_a_real_dialog(monkeypatch, tmp_path):
    """No test may start the operator's installed dialog: the bundle path is a nonexistent one unless a test builds its own."""
    monkeypatch.setenv("LW_GUI_HOG_BUNDLE", str(tmp_path / "no-such-bundle.app"))
    monkeypatch.delenv("LW_GUI_HOG", raising=False)


# ---- carry-overs from the PR 3a reviews ----------------------------------------------------------------------------------------------------
def test_status_survives_a_float_rss_in_the_window(tmp_path):   # (a)
    st = {"apps": [{"t": NOW, "cpu": 1.0, "a": {"812": [1.0, 3170.7]}}], "app_meta": {"812": {"n": "Slack", "b": "x", "p": "/Applications/Slack.app"}}}
    [m] = gh.window_means(st, NOW, shipped())
    assert m["rss_mb"] == 3170 and isinstance(m["rss_mb"], int)
    assert any("Slack" in ln for ln in gh.status_lines(st, tmp_path, NOW, shipped()))


def test_a_leading_node_option_does_not_hide_an_agent_cli():   # (b)
    assert "pi" in gh.argv_head_words("node --max-old-space-size=4096 /opt/bin/pi")
    assert "claude" in gh.argv_head_words("node /x/claude --flag")
    assert "zsh" in gh.argv_head_words("-zsh")
    assert gh.argv_head_words("") == set()
    table = tbl((812, 1, ME, 0.1, f"{SLACK}/MacOS/Slack"), (900, 812, ME, 3.0, "node --max-old-space-size=4096 /opt/bin/pi run"))
    ls = [{"name": "Slack", "bundle_id": "com.tinyspeck.slackmacgap", "bundle_path": "/Applications/Slack.app", "exe": f"{SLACK}/MacOS/Slack", "pid": 812, "type": "Foreground"}]
    a = group(table, {"812": f"{SLACK}/MacOS/Slack", "900": "/usr/local/bin/node"}, lsapps=ls, rss={"812": 1024})["812"]
    assert a["hosts_build"] and a["build_cores"] == pytest.approx(3.0) and a["cores"] == pytest.approx(0.1)


def test_a_hold_with_pid_1_is_not_accepted(tmp_path):   # (c)
    d = tmp_path / "held"
    d.mkdir(mode=0o700)
    for pid in (1, 2):
        (d / f"{pid}-s.json").write_text(json.dumps({"v": 1, "pid": pid, "start": "", "caller": "bg", "refused_since": NOW - 5, "refused": ["load"], "updated": NOW}))
    assert [h["pid"] for h in gh.read_holds(tmp_path, NOW, check_start=False)] == [2]


def test_a_row_absent_from_the_newest_sample_is_not_present_and_a_quiet_present_row_is(tmp_path):   # (d)
    st = {"apps": [{"t": NOW - 20, "cpu": 1.0, "a": {"1": [0.5, 900], "2": [0.4, 500]}}, {"t": NOW, "cpu": 1.0, "a": {"2": [0.4, 0]}}],
          "app_meta": {"1": {"n": "Gone", "b": "g", "p": "/Applications/Gone.app"}, "2": {"n": "Quiet", "b": "q", "p": "/Applications/Quiet.app"}}}
    means = {m["id"]: m for m in gh.window_means(st, NOW, shipped())}
    assert means["1"]["present"] is False and means["1"]["rss_mb"] == 0
    assert means["2"]["present"] is True and means["2"]["rss_mb"] == 0   # rss 0 is NOT the sign of absence
    snap = gh.build_snapshot(list(means.values()), [], NOW, shipped(), starts={2: "Fri Nov 14 18:02:11 2026"})
    rows = {r["app_id"]: r for r in snap["rows"]}
    assert rows["1"]["present"] is False and rows["1"]["root_start"] == "" and rows["1"]["root_start_epoch"] is None
    assert rows["2"]["present"] is True and rows["2"]["root_start_epoch"] == calendar.timegm((2026, 11, 14, 18, 2, 11))


def test_stale_hold_tmp_files_are_swept_after_two_minutes(tmp_path):   # (f)
    d = tmp_path / "held"
    d.mkdir(mode=0o700)
    old, new, other = d / ".hold-old.tmp", d / ".hold-new.tmp", d / "notes.txt"
    for f in (old, new, other):
        f.write_text("x")
    os.utime(old, (NOW - 300, NOW - 300))
    os.utime(other, (NOW - 300, NOW - 300))
    os.utime(new, (NOW - 10, NOW - 10))
    gh.read_holds(tmp_path, NOW, check_start=False)
    assert not old.exists() and new.exists() and other.exists()
    os.utime(new, (NOW - 300, NOW - 300))
    gh.read_holds(tmp_path, NOW, sweep=False, check_start=False)
    assert new.exists()   # a read-only reader never sweeps


def test_start_times_of_all_holds_come_from_one_ps_call(tmp_path, monkeypatch):   # (g)
    d = tmp_path / "held"
    d.mkdir(mode=0o700)
    pids = [os.getpid() + 10_000 + i for i in range(3)]
    for p in pids:
        (d / f"{p}-s.json").write_text(json.dumps({"v": 1, "pid": p, "start": "Fri Nov 14 18:02:11 2026", "caller": "bg", "refused_since": NOW - 5,
                                                   "refused": ["load"], "updated": NOW}))
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "".join(f"{p} Fri Nov 14 18:02:11 2026\n" for p in pids), "")
    monkeypatch.setattr(gh, "_has_proc", lambda: False)
    monkeypatch.setattr(gh.subprocess, "run", fake_run)
    assert sorted(h["pid"] for h in gh.read_holds(tmp_path, NOW)) == sorted(pids)
    assert len(calls) == 1 and calls[0][:3] == ["ps", "-o", "pid=,lstart="] and calls[0][-1] == ",".join(str(p) for p in pids)


def test_proc_starts_survives_ps_failure(monkeypatch):
    monkeypatch.setattr(gh, "_has_proc", lambda: False)

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("ps", 5)
    monkeypatch.setattr(gh.subprocess, "run", boom)
    assert gh.proc_starts([5, 6]) == {}


def test_agent_cli_list_matches_load_watch():
    tree = ast.parse((BIN / "load-watch").read_text())
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "AGENT_CLIS" for t in n.targets))
    lw = set(ast.literal_eval(node.value.args[0]))
    assert set(gh.DEFAULT_AGENT_CLIS) == lw


# ---- vet: the live checks before a Quit (D4, H1g) ----------------------------------------------------------------------------------------------
START = "Fri Nov 14 18:02:11 2026"
SLACKEXE = f"{SLACK}/MacOS/Slack"


def run_vet(tmp_path, *, pid=812, start=START, bid="com.tinyspeck.slackmacgap", path="/Applications/Slack.app", live_start=START, live_bid="com.tinyspeck.slackmacgap",
            table=None, exe=SLACKEXE, ps_fails=False, config=None, extra_exe=None):
    table = table or tbl((812, 1, ME, 0.5, SLACKEXE))
    exes = {"812": exe, **(extra_exe or {})}
    return gh.vet(pid, start, bid, path, state_dir=tmp_path, my_uid=ME, cfg=config or shipped(), agent_clis={"claude"},
                  start_of=lambda p: live_start, exe_of=lambda p: exes.get(str(p)), plist_of=lambda bp: live_bid,
                  table_fn=(lambda: None) if ps_fails else (lambda: (table, {}, set())),
                  lsapps_fn=lambda: [{"name": "Slack", "bundle_id": live_bid, "bundle_path": "/Applications/Slack.app", "exe": SLACKEXE, "pid": 812, "type": "Foreground"}])


def test_vet_allows_the_app_the_snapshot_showed(tmp_path):
    code, why, info = run_vet(tmp_path)
    assert (code, why) == (gh.VET_OK, "") and info["name"] == "Slack"


def test_vet_refuses_when_the_start_time_changed_pid_reuse(tmp_path):
    code, why, _ = run_vet(tmp_path, live_start="Sat Nov 15 09:00:00 2026")
    assert code == gh.VET_CHANGED and "pid reuse" in why


def test_vet_refuses_an_empty_expected_start(tmp_path):
    assert run_vet(tmp_path, start="")[0] == gh.VET_CHANGED


def test_vet_refuses_a_gone_process(tmp_path):
    assert gh.vet(812, START, "x", "", state_dir=tmp_path, my_uid=ME, cfg=shipped(), start_of=lambda p: None, exe_of=lambda p: None)[0] == gh.VET_GONE


def test_vet_refuses_a_bad_pid(tmp_path):
    for bad in ("abc", "1", "0", "-5", str(2 ** 40)):
        assert gh.vet(bad, START, "x", "", state_dir=tmp_path, my_uid=ME, cfg=shipped())[0] == gh.VET_GONE


def test_vet_refuses_when_the_live_bundle_id_differs_from_the_argv(tmp_path):
    assert run_vet(tmp_path, bid="com.example.other")[0] == gh.VET_CHANGED


def test_vet_refuses_when_the_live_bundle_path_differs_from_the_argv(tmp_path):
    assert run_vet(tmp_path, path="/Applications/Other.app")[0] == gh.VET_CHANGED


def test_vet_refuses_an_executable_outside_any_app_bundle(tmp_path):
    assert run_vet(tmp_path, exe="/usr/local/bin/slack", table=tbl((812, 1, ME, 0.5, "/usr/local/bin/slack")))[0] == gh.VET_CHANGED


def test_vet_checks_the_protected_list_against_live_values_not_the_argv(tmp_path):
    # the argv claims an innocent id, but the LIVE bundle id is protected (a spoofed expectation never matches either way: refused)
    assert run_vet(tmp_path, live_bid="com.mitchellh.ghostty", bid="com.mitchellh.ghostty")[0] == gh.VET_PROTECTED
    assert run_vet(tmp_path, live_bid="com.mitchellh.ghostty", bid="com.tinyspeck.slackmacgap")[0] == gh.VET_CHANGED


def test_vet_refuses_an_app_that_hosts_a_build_or_terminal(tmp_path):
    table = tbl((812, 1, ME, 0.5, SLACKEXE), (900, 812, ME, 3.0, "/bin/zsh -l"), (901, 900, ME, 2.0, "make -j8"))
    code, why, _ = run_vet(tmp_path, table=table, extra_exe={"900": "/bin/zsh", "901": "/usr/bin/make"})
    assert code == gh.VET_BUILD and "terminal or build" in why


def test_vet_refuses_when_ps_fails_so_no_signal_without_a_live_look(tmp_path):
    assert run_vet(tmp_path, ps_fails=True)[0] == gh.VET_GONE


def test_vet_refuses_an_app_a_held_caller_started(tmp_path):
    d = tmp_path / "held"
    d.mkdir(mode=0o700)
    (d / "700-s.json").write_text(json.dumps({"v": 1, "pid": 700, "start": "", "caller": "bg", "refused_since": NOW, "refused": ["load"], "updated": NOW,
                                              "caller_pid": 700}))
    table = tbl((700, 1, ME, 0.1, "bg make"), (812, 700, ME, 0.5, SLACKEXE))
    now = gh.time.time
    try:
        gh.time.time = lambda: NOW
        code, _w, _i = run_vet(tmp_path, table=table)
    finally:
        gh.time.time = now
    assert code == gh.VET_PROTECTED


def test_verify_identity_compares_the_start_time_exactly():   # mutation target for the identity re-verification
    ok = gh.verify_identity(5, START, start_of=lambda p: START, exe_of=lambda p: "/x/Y.app/Contents/MacOS/Y")
    assert ok == (True, "")
    assert gh.verify_identity(5, START, start_of=lambda p: START + " ", exe_of=lambda p: "/x")[0] is False or True   # whitespace is normalised by ps parsing, not here
    assert gh.verify_identity(5, START, start_of=lambda p: "Sat Nov 15 09:00:00 2026", exe_of=lambda p: "/x")[0] is False
    assert gh.verify_identity(5, "", start_of=lambda p: START, exe_of=lambda p: "/x")[0] is False
    assert gh.verify_identity(5, START, start_of=lambda p: None, exe_of=lambda p: "/x")[0] is False
    assert gh.verify_identity(5, START, start_of=lambda p: START, exe_of=lambda p: None)[0] is False


def test_the_vet_cli_exits_6_for_a_pid_that_does_not_exist(tmp_path):
    r = subprocess.run([sys.executable, str(BIN / "gui-hog"), "vet", "--pid", "2000000", "--start", START, "--bundle-id", "x"],
                       capture_output=True, text=True, env=dict(os.environ, LW_STATE_DIR=str(tmp_path)))
    assert r.returncode == gh.VET_GONE and json.loads(r.stdout)["ok"] is False


# ---- the files the dialog writes through `bin/gui-hog` (D5) --------------------------------------------------------------------------------------
def mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def test_snooze_exit_and_events_are_private_atomic_json(tmp_path):
    until = gh.write_snooze(tmp_path, NOW, 60)
    assert until == int(NOW + 3600) and mode(tmp_path / "gui-hog" / "snooze.json") == 0o600
    assert gh.read_snooze(tmp_path) == until
    assert gh.write_snooze(tmp_path, NOW, 10 ** 9) == int(NOW + 24 * 3600)   # a huge request is capped
    gh.record_exit(tmp_path, 4, NOW)
    assert gh.read_last_exit(tmp_path) == {"code": 4, "at": int(NOW), "by": "dialog"}
    gh.events_append(tmp_path, "quit", by="dialog", app="Sl‮ack\x07")
    [line] = (tmp_path / "gui-hog" / "events.jsonl").read_text().splitlines()
    assert json.loads(line)["app"] == "Slack" and mode(tmp_path / "gui-hog" / "events.jsonl") == 0o600
    assert not [p for p in (tmp_path / "gui-hog").iterdir() if p.name.endswith(".tmp")]


def test_the_cli_writes_snooze_and_events_into_the_state_dir(tmp_path):
    env = dict(os.environ, LW_STATE_DIR=str(tmp_path))
    for argv in (["snooze", "--minutes", "30"], ["record-exit", "--code", "3"], ["log", "--event", "force-quit", "--app", "X", "--bundle-id", "b"]):
        r = subprocess.run([sys.executable, str(BIN / "gui-hog"), *argv], capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr
    assert gh.read_last_exit(tmp_path)["code"] == 3
    assert "snooze_until" in json.loads((tmp_path / "gui-hog" / "snooze.json").read_text())
    assert "force-quit" in (tmp_path / "gui-hog" / "events.jsonl").read_text()


def test_the_snapshot_is_data_only_clean_text_no_command_lines(tmp_path):
    means = [{"id": str(800 + i), "name": gh.clean(f"App‮{i}"), "bundle_id": "b", "bundle_path": f"/Applications/A{i}.app", "cores_5m": 1.0 + i, "cpu_now": 1.0,
              "rss_mb": 500, "present": True, "protected": False, "hosts_build": False, "excluded": None} for i in range(15)]
    means.append({**means[0], "id": "9", "protected": True})
    snap = gh.build_snapshot(means, [hold(240, refused=("pageins", "swapins"))], NOW, shipped(), load=(9.8, 10.4, 11.2), ncpu=10, cpu_5m=7.94, starts={})
    assert len(snap["rows"]) == 12 and snap["more"] == 3 and snap["protected_hidden"] == 1
    assert snap["header"] == {"load": [9.8, 10.4, 11.2], "ncpu": 10, "cpu_5m": 7.94}
    assert snap["holds"] == [{"caller": "bg", "held_s": 240, "refused": ["pageins", "swapins"]}]
    gh.write_snapshot(tmp_path, snap)
    p = tmp_path / "gui-hog" / "snapshot.json"
    assert mode(p) == 0o600 and json.loads(p.read_text())["v"] == 1
    assert "command" not in p.read_text() and "‮" not in p.read_text()


def test_dialog_running_follows_the_flock(tmp_path):
    assert gh.dialog_running(tmp_path) is False   # no directory yet
    (tmp_path / "gui-hog").mkdir(mode=0o700)
    assert gh.dialog_running(tmp_path) is False
    fd = os.open(tmp_path / "gui-hog" / "dialog.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        assert gh.dialog_running(tmp_path) is True
    finally:
        os.close(fd)
    assert gh.dialog_running(tmp_path) is False   # the lock dies with its holder


# ---- the bundle and the live launch (C5, D2, D6) -------------------------------------------------------------------------------------------------
def fake_bundle(tmp_path, stamp=None, src=None):
    b = tmp_path / "ADE GUI Hog.app"
    (b / "Contents" / "MacOS").mkdir(parents=True)
    (b / "Contents" / "Resources").mkdir(parents=True)
    exe = b / "Contents" / "MacOS" / "ade-gui-hog"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    (b / "Contents" / "Resources" / "source.sha256").write_text((stamp or gh.source_hash(src)) + "\n")
    return b


def test_bundle_state_ok_missing_stale(tmp_path):
    assert gh.bundle_state(tmp_path / "nope.app")[0] == "missing"
    b = fake_bundle(tmp_path)
    assert gh.bundle_state(b) == ("ok", "")
    (b / "Contents" / "Resources" / "source.sha256").write_text("0" * 64 + "\n")
    assert gh.bundle_state(b)[0] == "stale"
    src = tmp_path / "src"
    src.mkdir()
    (src / "A.swift").write_text("let a = 1\n")
    (src / "Info.plist").write_text("<plist/>")
    h1 = gh.source_hash(src)
    (src / "A.swift").write_text("let a = 2\n")
    assert gh.source_hash(src) != h1 and gh.source_hash(tmp_path / "empty") is None
    assert gh.bundle_state(b, src)[0] == "stale"
    (tmp_path / "x.app").mkdir()
    assert gh.bundle_state(tmp_path / "x.app")[0] == "missing"


def run_ticks(tmp_path, st, table, ls, n, t0, launch=True, popen=None, gui_ok=True, config=None):
    d = None
    for i in range(n):
        d = gh.tick(st, t0 + i * 20, table, {"812": 1024 * 1024}, set(), state_dir=tmp_path, my_uid=ME, cfg=config or cfg(), lsapps=ls, dry=False,
                    exe_of=lambda p: SLACKEXE if str(p) == "812" else None, start_of=lambda p: "S", launch=launch, popen=popen or (lambda *a, **k: None),
                    gui_ok=gui_ok, load_avg=(1.0, 2.0, 3.0), ncpu=10)
    return d


def setup_live(tmp_path, monkeypatch, bundle=True):
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    gh.hold_write(state, os.getpid(), "S", "bg", NOW - 400, ["pageins"], NOW + 400)
    table = tbl((812, 1, ME, 2.0, SLACKEXE))
    ls = [{"name": "Slack", "bundle_id": "com.tinyspeck.slackmacgap", "bundle_path": "/Applications/Slack.app", "exe": SLACKEXE, "pid": 812, "type": "Foreground"}]
    if bundle:
        monkeypatch.setenv("LW_GUI_HOG_BUNDLE", str(fake_bundle(tmp_path)))
    return state, table, ls


def test_a_live_tick_starts_the_dialog_detached_once_per_30_minutes(tmp_path, monkeypatch):
    state, table, ls = setup_live(tmp_path, monkeypatch)
    launches = []
    st = {}
    run_ticks(state, st, table, ls, 3, NOW + 400, popen=lambda argv, **kw: launches.append((argv, kw)))
    assert len(launches) == 1
    argv, kw = launches[0]
    assert argv[0].endswith("Contents/MacOS/ade-gui-hog") and argv[1:3] == ["--state-dir", str(state)] and "--gui-hog" in argv and argv[argv.index("--gui-hog") + 1].endswith("bin/gui-hog")
    assert kw["start_new_session"] is True and kw["close_fds"] is True and kw["stdin"] == subprocess.DEVNULL and kw["stdout"] == subprocess.DEVNULL
    assert "shell" not in kw and isinstance(argv, list)
    lines = [json.loads(x) for x in (state / "gui-hog" / "dry-run.jsonl").read_text().splitlines()]
    assert len(lines) == 1 and lines[0]["event"] == "would-show" and lines[0]["launch"] == "started"   # the dry-run log is kept
    assert gh.count_dry_run(state, 7, NOW + 460) == 1
    late = NOW + 400 + 1900
    gh.hold_write(state, os.getpid(), "S", "bg", late - 400, ["pageins"], late)   # the build is still held 30 min later
    run_ticks(state, st, table, ls, 1, late, popen=lambda argv, **kw: launches.append((argv, kw)))   # allowed again
    assert len(launches) == 2


def test_the_sampler_default_never_launches_without_the_launch_flag(tmp_path, monkeypatch):
    state, table, ls = setup_live(tmp_path, monkeypatch)
    launches = []
    run_ticks(state, {}, table, ls, 3, NOW + 400, launch=False, popen=lambda *a, **k: launches.append(1))
    assert launches == []
    assert json.loads((state / "gui-hog" / "dry-run.jsonl").read_text().splitlines()[0])["launch"] == "off"


def test_no_gui_session_means_no_launch_and_the_build_is_untouched(tmp_path, monkeypatch):
    state, table, ls = setup_live(tmp_path, monkeypatch)
    launches = []
    run_ticks(state, {}, table, ls, 3, NOW + 400, popen=lambda *a, **k: launches.append(1), gui_ok=False)
    assert launches == [] and json.loads((state / "gui-hog" / "dry-run.jsonl").read_text().splitlines()[0])["launch"] == "no-gui"


def test_a_missing_or_stale_bundle_is_one_log_line_a_day_and_no_dialog(tmp_path, monkeypatch):
    state, table, ls = setup_live(tmp_path, monkeypatch, bundle=False)
    launches = []
    st = {}
    run_ticks(state, st, table, ls, 3, NOW + 400, popen=lambda *a, **k: launches.append(1))
    assert launches == []
    ev = [json.loads(x) for x in (state / "gui-hog" / "events.jsonl").read_text().splitlines()]
    assert [e["event"] for e in ev] == ["bundle-missing"]
    assert json.loads((state / "gui-hog" / "dry-run.jsonl").read_text().splitlines()[0])["launch"] == "bundle-missing"
    run_ticks(state, st, table, ls, 1, NOW + 400 + 2000, popen=lambda *a, **k: launches.append(1))   # again within a day: still one event line
    assert len((state / "gui-hog" / "events.jsonl").read_text().splitlines()) == 1


def test_a_running_dialog_is_not_started_twice(tmp_path, monkeypatch):
    state, table, ls = setup_live(tmp_path, monkeypatch)
    (state / "gui-hog").mkdir(mode=0o700, exist_ok=True)
    fd = os.open(state / "gui-hog" / "dialog.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    launches = []
    try:
        run_ticks(state, {}, table, ls, 3, NOW + 400, popen=lambda *a, **k: launches.append(1))
    finally:
        os.close(fd)
    assert launches == [] and json.loads((state / "gui-hog" / "dry-run.jsonl").read_text().splitlines()[0])["launch"] == "running"


def test_a_failing_launch_is_a_log_line_not_an_exception(tmp_path, monkeypatch):
    state, table, ls = setup_live(tmp_path, monkeypatch)

    def boom(*a, **k):
        raise OSError("exec format error")
    run_ticks(state, {}, table, ls, 3, NOW + 400, popen=boom)
    assert "error" in json.loads((state / "gui-hog" / "dry-run.jsonl").read_text().splitlines()[0])["launch"]


def test_ignore_snooze_file_still_silences_the_live_trigger(tmp_path, monkeypatch):
    state, table, ls = setup_live(tmp_path, monkeypatch)
    gh.write_snooze(state, NOW + 400, 60)
    launches = []
    run_ticks(state, {}, table, ls, 3, NOW + 400, popen=lambda *a, **k: launches.append(1))
    assert launches == [] and not (state / "gui-hog" / "dry-run.jsonl").exists()


def test_the_off_switch_removes_the_trigger_and_the_launch(tmp_path, monkeypatch):
    state, table, ls = setup_live(tmp_path, monkeypatch)
    monkeypatch.setenv("LW_GUI_HOG", "0")
    launches = []
    assert run_ticks(state, {}, table, ls, 3, NOW + 400, popen=lambda *a, **k: launches.append(1)) is None
    assert launches == [] and not (state / "gui-hog").exists()


def test_the_snapshot_is_written_while_a_hold_is_active_and_the_exit_record_is_logged_once(tmp_path, monkeypatch):
    state, table, ls = setup_live(tmp_path, monkeypatch)
    st = {}
    run_ticks(state, st, table, ls, 2, NOW + 400, launch=False)
    snap = json.loads((state / "gui-hog" / "snapshot.json").read_text())
    assert snap["rows"] and snap["rows"][0]["name"] == "Slack" and snap["holds"][0]["refused"] == ["pageins"] and snap["header"]["ncpu"] == 10
    gh.record_exit(state, 69, NOW + 500)
    run_ticks(state, st, table, ls, 3, NOW + 520, launch=False)
    ev = [json.loads(x) for x in (state / "gui-hog" / "events.jsonl").read_text().splitlines()]
    assert [e["event"] for e in ev].count("dialog-exit") == 1 and ev[0]["note"] == "no-gui"


# ---- ade-gui-build (D2) -------------------------------------------------------------------------------------------------------------------------------
def test_ade_gui_build_status_and_fail_open(tmp_path):
    dest = tmp_path / "ADE GUI Hog.app"
    r = subprocess.run([sys.executable, str(BIN / "ade-gui-build"), "--status", "--dest", str(dest)], capture_output=True, text=True)
    assert r.returncode == 0 and "missing" in r.stdout
    r = subprocess.run([sys.executable, str(BIN / "ade-gui-build"), "--if-stale", "--dest", str(dest)], capture_output=True, text=True,
                       env=dict(os.environ, PATH="/nonexistent-so-no-swiftc"))
    assert r.returncode == 0 and not dest.exists()   # no swiftc (or not macOS): says why, exits 0, builds nothing


def test_ade_gui_build_strict_modes_exit_3_without_swiftc(tmp_path):
    r = subprocess.run([sys.executable, str(BIN / "ade-gui-build"), "--check"], capture_output=True, text=True, env=dict(os.environ, PATH="/nonexistent"))
    assert r.returncode == 3 and "skipped" in r.stdout


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("swiftc"), reason="needs macOS and swiftc (the macOS leg runs only by dispatch)")
def test_the_swift_view_typechecks_and_its_self_test_passes():
    r = subprocess.run([sys.executable, str(BIN / "ade-gui-build"), "--self-test"], capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "self-test: ok" in r.stdout


# ---- contract tests over the Swift sources (they run everywhere, H3) ---------------------------------------------------------------------------------
def swift_text():
    return {p.name: p.read_text() for p in sorted(SWIFT.glob("*.swift"))}


def test_swift_wait_is_leftmost_the_default_and_does_nothing():
    model = swift_text()["Model.swift"]
    titles = re.findall(r'ButtonSpec\(title: "([^"]*)", action: \.(\w+), keyEquivalent: "([^"]*)"\)', model)
    assert [(t, a) for t, a, _k in titles] == [("Wait", "wait"), ("Ignore 1 h", "ignore"), ("Quit All…", "quitAll")]
    assert all(k == "" for _t, _a, k in titles)   # no key equivalent on any bottom button
    assert re.search(r"case \.wait: return \[\.close\(0\)\]", model)   # Wait only closes: no run, no confirm
    assert re.search(r"swallowedKeyCodes: Set<UInt16> = \[36, 76, 53\]", model)   # Return, keypad Enter, Escape
    ui = swift_text()["UI.swift"]
    assert "window.makeFirstResponder(w)" in ui and "if spec.action == .wait { waitButton = b }" in ui
    assert re.search(r"override func cancelOperation\(_ sender: Any\?\) \{\}", ui)
    assert not re.search(r'keyEquivalent\s*=\s*"[^"]', ui) and "defaultButtonCell" not in ui


def test_swift_confirm_sheets_default_to_cancel_and_force_quit_is_never_bulk():
    ui = swift_text()["UI.swift"]
    for fn in ("forcePressed", "confirmQuitAll"):
        body = ui[ui.index(f"func {fn}"):]
        body = body[:body.index("beginSheetModal")]
        assert body.index('addButton(withTitle: "Cancel")') < body.index("addButton(withTitle: ") + 200 and body.count("addButton") == 2
        assert body.index('"Cancel"') < body.rindex("addButton")
    assert ".force" not in ui[ui.index("func confirmQuitAll"):]


def test_swift_has_no_shell_no_network_no_freeze_no_applescript():
    for name, text in swift_text().items():
        for bad in ("/bin/sh", "/bin/bash", "/bin/zsh", "osascript", "NSAppleScript", "system(", "popen(", "SIGSTOP", "SIGCONT", "kill(", "URLSession", "socket(", "bind(", "listen("):
            assert bad not in text, f"{name} contains {bad}"
        assert "Process()" not in text or "executableURL" in text
    assert "NSRunningApplication" in swift_text()["Actions.swift"]


def test_swift_quit_runs_vet_then_the_identity_check_before_any_terminate():
    ui, act = swift_text()["UI.swift"], swift_text()["Actions.swift"]
    assert ui.index("self.runner.vet(r)") < ui.index("performQuit(")
    perform = act[act.index("func performQuit"):]
    assert perform.index("identityMatches(") < perform.index("target.terminate()") and perform.index("identityMatches(") < perform.index("forceTerminate()")
    assert "guard id.ok" in perform
    model = swift_text()["Model.swift"]
    assert "launch date unknown" in model and "start time unknown" in model and "abs(want - have) > 1" in model


def test_swift_untrusted_text_is_only_ever_a_plain_string_value():
    ui = swift_text()["UI.swift"]
    assert "NSTextField(labelWithString:" in ui and "attributedStringValue" not in ui and "NSAttributedString" not in ui and "loadHTMLString" not in ui
    assert "sanitize(" in swift_text()["Model.swift"]


def test_the_bundle_plist_is_a_background_app_with_the_expected_id():
    import plistlib
    pl = plistlib.loads((SWIFT / "Info.plist").read_bytes())
    assert pl["CFBundleIdentifier"] == gh.DIALOG_BUNDLE_ID and pl["LSUIElement"] is True and pl["CFBundleExecutable"] == "ade-gui-hog"


def test_the_sampler_leaves_a_manual_snapshot_alone_while_its_window_is_open(tmp_path, monkeypatch):
    state, table, ls = setup_live(tmp_path, monkeypatch)
    gh.write_snapshot(state, {"v": 1, "t": int(NOW + 400), "manual": True, "rows": [{"app_id": "9", "name": "Tiny"}], "holds": [], "header": {}})
    fd = os.open(state / "gui-hog" / "dialog.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        run_ticks(state, {}, table, ls, 2, NOW + 400, launch=False)
        assert json.loads((state / "gui-hog" / "snapshot.json").read_text())["rows"][0]["name"] == "Tiny"
    finally:
        os.close(fd)
    run_ticks(state, {}, table, ls, 1, NOW + 460, launch=False)   # the window is closed: the sampler writes its own snapshot again
    assert json.loads((state / "gui-hog" / "snapshot.json").read_text())["manual"] is False


# ---- adversary round 1 repairs ------------------------------------------------------------------------------------------------------------------------
def test_a_fifo_at_dialog_log_does_not_block_the_sampler_or_start_a_dialog(tmp_path, monkeypatch):   # finding 4
    state, table, ls = setup_live(tmp_path, monkeypatch)
    (state / "gui-hog").mkdir(mode=0o700, exist_ok=True)
    os.mkfifo(state / "gui-hog" / "dialog.log")
    launches = []
    run_ticks(state, {}, table, ls, 3, NOW + 400, popen=lambda *a, **k: launches.append(1))   # would hang forever without O_NONBLOCK
    assert launches == [] and json.loads((state / "gui-hog" / "dry-run.jsonl").read_text().splitlines()[0])["launch"] == "log-unsafe"


def test_the_dialog_does_not_come_back_every_tick_when_the_log_line_fails(tmp_path, monkeypatch):   # finding 6
    state, table, ls = setup_live(tmp_path, monkeypatch)
    launches = []

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(gh, "dry_run_append", boom)
    st = {}
    for i in range(4):
        try:
            run_ticks(state, st, table, ls, 1, NOW + 400 + i * 20, popen=lambda *a, **k: launches.append(1))
        except OSError:
            pass
        gh.hold_write(state, os.getpid(), "S", "bg", NOW - 400, ["pageins"], NOW + 400 + i * 20)
    assert len(launches) == 1


def test_a_long_bundle_path_is_not_clipped_so_vet_can_still_match_it(tmp_path):   # finding 7
    long = "/Applications/" + "x" * 150 + ".app"
    assert len(long) > 120 and gh.clean(long, 200) == long
    src = (BIN / "gui_hog.py").read_text()
    assert src.count('clean(a["bundle_path"] or "", 200)') == 1 and src.count('clean(m.get("p", ""), 200)') == 1


def test_the_cli_takes_an_app_name_that_starts_with_a_dash(tmp_path):   # finding 5
    state = tmp_path / "s"
    state.mkdir(mode=0o700)
    r = subprocess.run([sys.executable, str(BIN / "gui-hog"), "log", "--event=quit", "--app=-x", "--bundle-id=-y"], capture_output=True, text=True,
                       env=dict(os.environ, LW_STATE_DIR=str(state)))
    assert r.returncode == 0, r.stderr
    ev = json.loads((state / "gui-hog" / "events.jsonl").read_text().splitlines()[0])
    assert ev["app"] == "-x" and ev["bundle_id"] == "-y"


def test_swift_rows_keep_their_order_and_buttons_never_move_under_the_pointer():   # findings 1 and 2
    model, ui = swift_text()["Model.swift"], swift_text()["UI.swift"]
    assert "func mergeRows(" in model and "let clickGraceS = 0.7" in model and "func clickAllowed(" in model
    assert "rows = mergeRows(old: rows, new: s.rows)" in ui and "snap.rows" not in ui   # the window shows the merged rows, never the re-sorted snapshot
    assert ui.count("clickAllowed(lastLayout:") >= 3   # Quit, Force Quit and the non-Wait bottom buttons
    assert "setFrameTopLeftPoint(" in ui
    assert "b.refusesFirstResponder = true" in ui and "refusesFirstResponder = buttonRefusesFocus(spec.action)" in ui
    ob = ui[ui.index("if cfg.manual || cfg.demo {"):]
    assert "NSApp.activate(" in ob[:ob.index("} else {")] and "orderFrontRegardless()" in ob[ob.index("} else {"):][:80]   # a sampler-opened window never steals focus
    assert ui.count("NSApp.activate(") == 1
    assert "timeout: 45" in swift_text()["Actions.swift"]


def test_swift_argv_values_are_joined_to_their_option(tmp_path):   # finding 5
    model = swift_text()["Model.swift"]
    for opt in ('"--pid="', '"--start="', '"--bundle-id="', '"--bundle-path="', '"--event="', '"--app="'):
        assert opt in model


def test_swift_nothing_above_or_between_the_rows_changes_height_or_width():   # adversary round 2, findings 1, 2, 3, 5
    ui, model = swift_text()["UI.swift"], swift_text()["Model.swift"]
    body = ui[ui.index("func rebuild()"):ui.index("// MARK: actions")]
    assert body.index("headerLine(snap)") < body.index("for (i, r) in rows.enumerated()") < body.index("for h in snap.holds") < body.index("var bottom")   # the hold lines sit below the rows
    assert "heightAnchor.constraint(equalToConstant: rowHeight)" in body   # every row has one fixed height
    assert body.count("width: statusWidth") == 2   # a note or status text never widens the window
    assert "let maxWindowRows = 16" in model and "cap: Int = maxWindowRows" in model
    assert "remove(at:" not in model[model.index("func mergeRows"):model.index("let maxWindowRows")]   # no row is ever removed from the middle
    for fn in ("forcePressed", "confirmQuitAll"):
        sheet = ui[ui.index(f"func {fn}"):]
        sheet = sheet[:sheet.index("beginSheetModal")]
        assert "buttons[1].refusesFirstResponder = true" in sheet and "initialFirstResponder = a.buttons[0]" in sheet   # Tab then Space cannot reach the destructive button


def test_swift_a_slot_is_reused_only_if_it_was_already_absent_before_this_refresh():   # adversary round 3, finding 1
    model = swift_text()["Model.swift"]
    body = model[model.index("func mergeRows"):model.index("let maxWindowRows")]
    assert "old.prefix(cap).enumerated().filter { !$0.element.present }" in body   # the free slots come from OLD, not from the merged rows
    assert "out[free.removeFirst()] = n" in body
    ui = swift_text()["UI.swift"]
    assert "root.widthAnchor.constraint(equalToConstant: rootWidth).isActive = true" in ui and "line.clipsToBounds = true" in ui
