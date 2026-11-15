"""bin/gui_hog_freeze.py, GUI-hog dialog PR 3c (docs/gui-hog-dialog.md H1 d, e, g, H1a and the Python side of H4 f, g): the frozen-list state
machine on a fake clock and a fake process table, the four-field identity check before every signal, the protected list on the root
and on every member, the write-ahead order, crash recovery, every thaw path, a hand-edited or symlinked state, and real SIGSTOP/SIGCONT on
disposable process trees this file starts itself (never a real app, never a pid it did not create)."""
import ast
import json
import os
import plistlib
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import gui_hog as gh  # noqa: E402
import gui_hog_freeze as gf  # noqa: E402
from test_load_watch_pr2 import load_module  # noqa: E402

BIN = Path(__file__).resolve().parent.parent / "bin"
T0 = 1_800_000_000.0
ME = os.getuid()


class Crash(BaseException):
    """A process death in the middle of an operation: nothing catches it (a real crash runs no cleanup)."""


def cfg(**freeze):
    c = gh.load_config(path=Path("/nonexistent"), local=Path("/nonexistent"))
    c["freeze"].update(freeze)
    return c


# ---- a fake process table ----------------------------------------------------------------------------------------------------------------------
class FakeOps(gf.Ops):
    """gf.Ops over a dict of fake processes; signals are recorded and change the fake state (STOP -> T, CONT -> S)."""

    def __init__(self, procs):
        super().__init__(my_uid=ME)
        self.procs, self.sent, self.on_kill, self.info_error = procs, [], None, False

    def table(self, timeout=20):
        live = {p: d for p, d in self.procs.items() if d["state"] != "gone"}
        return ({str(p): (d["ppid"], d["uid"], 0.5, d["cmd"]) for p, d in live.items()}, {str(p): 100 * 1024 for p in live},
                {str(p) for p, d in live.items() if d.get("tty")}, {str(p): d["state"] for p, d in live.items()})

    def exe(self, pid):
        d = self.procs.get(int(pid))
        return d["exe"] if d and d["state"] != "gone" else None

    def info(self, pids):
        if self.info_error:
            raise OSError("ps timed out")
        return {p: {"start": d["start"], "uid": d["uid"], "state": d["state"], "exe": d["exe"]} for p in pids
                if (d := self.procs.get(p)) and d["state"] != "gone"}

    def kill(self, pid, sig):
        if self.on_kill:
            self.on_kill(pid, sig)
        d = self.procs.get(pid)
        if d is None or d["state"] == "gone":
            return False
        self.sent.append((pid, sig))
        d["state"] = "T" if sig == signal.SIGSTOP else "S"
        return True

    def sent_to(self, pid):
        return [s for p, s in self.sent if p == pid]


def proc(ppid, exe, uid=ME, state="S", start=None, pid=None):
    return {"ppid": ppid, "uid": uid, "exe": str(exe), "cmd": str(exe), "state": state, "start": start or f"start-{pid}", "tty": False}


@pytest.fixture
def world(tmp_path):
    """A fake app (Fake.app: root 5000, helpers 5001 and 5002) under launchd (pid 1), and a state directory."""
    app = tmp_path / "Apps" / "Fake.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.example.fake"}))
    exe, helper = app / "Contents" / "MacOS" / "Fake", app / "Contents" / "MacOS" / "Helper"
    procs = {1: proc(0, "/sbin/launchd", uid=0, pid=1), 5000: proc(1, exe, pid=5000), 5001: proc(5000, helper, pid=5001),
             5002: proc(5000, helper, pid=5002)}
    state = tmp_path / "state"
    state.mkdir()

    class W:
        pass
    w = W()
    w.ops, w.state, w.app, w.exe, w.helper, w.tmp = FakeOps(procs), state, app, exe, helper, tmp_path
    w.freeze = lambda **kw: gf.freeze(state, 5000, start="start-5000", ops=w.ops, cfg=kw.pop("cfg", cfg()), now=kw.pop("now", T0), check_sampler=False,
                                      agent_clis=(), **kw)
    w.entries = lambda: json.loads((state / "gui-hog" / "frozen.json").read_text())["entries"]
    w.events = lambda: [json.loads(x) for x in (state / "gui-hog" / "events.jsonl").read_text().splitlines()]
    return w


# ---- the state machine (H1 d): freezing -> frozen -> thawing -> gone ----------------------------------------------------------------------------
def test_a_timed_freeze_stops_the_root_first_and_resumes_children_first_when_due(world):
    e = world.freeze(minutes=10, by="dialog")
    assert e["state"] == "frozen" and e["mode"] == "timed" and e["thaw_at"] == T0 + 600 and e["by"] == "dialog"
    assert [p for p, s in world.ops.sent if s == signal.SIGSTOP] == [5000, 5001, 5002]   # F4b: the root first
    assert [x["state"] for x in world.entries()] == ["frozen"] and world.ops.procs[5001]["state"] == "T"
    assert gf.thaw_due(world.state, ops=world.ops, now=T0 + 599)["resumed"] == []
    assert world.ops.procs[5000]["state"] == "T"
    assert gf.thaw_due(world.state, ops=world.ops, now=T0 + 600)["resumed"] == [e["id"]]
    assert [p for p, s in world.ops.sent if s == signal.SIGCONT] == [5002, 5001, 5000]   # F4: children first, the root last
    assert world.entries() == [] and all(world.ops.procs[p]["state"] == "S" for p in (5000, 5001, 5002))


def test_every_freeze_and_thaw_is_recorded_with_by(world):
    world.freeze(minutes=1, by="dialog")
    gf.thaw_due(world.state, ops=world.ops, now=T0 + 61, by="sampler")
    ev = [(x["event"], x["by"]) for x in world.events()]
    assert ev == [("freeze", "dialog"), ("thaw", "sampler")]
    assert world.events()[0]["app"]["bundle_id"] == "com.example.fake" and world.events()[1]["entry"] == world.events()[0]["entry"]
    assert (world.state / "gui-hog" / "events.jsonl").stat().st_mode & 0o777 == 0o600


def test_an_indefinite_freeze_is_never_due_but_thaw_all_resumes_it(world):
    e = world.freeze()
    assert e["mode"] == "indefinite" and e["thaw_at"] is None
    r = gf.thaw_due(world.state, ops=world.ops, now=T0 + 10 ** 7)
    assert r["resumed"] == [] and world.ops.procs[5000]["state"] == "T"
    assert gf.thaw_all(world.state, ops=world.ops, now=T0 + 1, by="cli") == ([e["id"]], [])
    assert world.entries() == [] and world.ops.procs[5000]["state"] == "S"


def test_state_files_are_private_and_the_previous_good_file_is_kept(world):
    world.freeze(minutes=1)
    g = world.state / "gui-hog"
    assert g.stat().st_mode & 0o777 == 0o700 and (g / "frozen.json").stat().st_mode & 0o777 == 0o600
    assert json.loads((g / "frozen.json.prev").read_text())["v"] == 1
    assert not [p for p in g.iterdir() if p.name.endswith(".tmp")]


def test_a_member_already_stopped_by_someone_else_is_not_recorded_or_signalled(world):
    world.ops.procs[5002]["state"] = "T"
    e = world.freeze(minutes=5)
    assert [m["pid"] for m in e["members"]] == [5001] and world.ops.sent_to(5002) == []


def test_a_root_already_stopped_is_refused(world):
    world.ops.procs[5000]["state"] = "T"
    with pytest.raises(gf.Refusal) as r:
        world.freeze(minutes=5)
    assert r.value.code == gf.REFUSED and world.ops.sent == []


def test_a_second_freeze_of_the_same_app_is_refused(world):
    world.freeze(minutes=5)
    with pytest.raises(gf.Refusal) as r:
        world.freeze(minutes=5)
    assert r.value.code == gf.REFUSED and "already" in r.value.msg


# ---- write-ahead (F2) and crashes -----------------------------------------------------------------------------------------------------------------
def test_the_entry_is_written_before_the_first_sigstop(world):
    seen = []

    def check(pid, sig):
        if sig == signal.SIGSTOP and not seen:
            e = world.entries()
            seen.append((e[0]["state"], e[0]["root"]["pid"], sorted(m["pid"] for m in e[0]["members"])))
    world.ops.on_kill = check
    world.freeze(minutes=5)
    assert seen == [("freezing", 5000, [5001, 5002])]


@pytest.mark.parametrize("crash_at", [1, 2, 3])
def test_a_crash_after_the_write_ahead_is_recovered_by_the_next_tick(world, crash_at):
    n = []

    def boom(pid, sig):
        n.append(pid)
        if len(n) == crash_at:
            raise Crash

    world.ops.on_kill = boom
    with pytest.raises(Crash):
        world.freeze(minutes=5)
    assert [x["state"] for x in world.entries()] == ["freezing"]   # the record names every process that might be stopped
    world.ops.on_kill = None
    stopped = {p for p in (5000, 5001, 5002) if world.ops.procs[p]["state"] == "T"}
    assert len(stopped) == crash_at - 1
    r = gf.thaw_due(world.state, ops=world.ops, now=T0 + 1)   # not even due: an orphaned `freezing` entry is resumed at once
    assert len(r["resumed"]) == 1 and world.entries() == []
    assert {p for p, s in world.ops.sent if s == signal.SIGCONT} == stopped   # only what was really stopped is signalled
    assert all(world.ops.procs[p]["state"] == "S" for p in (5000, 5001, 5002))


def test_a_crash_while_thawing_is_finished_by_the_next_tick(world):
    world.freeze(minutes=1)
    n = []

    def boom(pid, sig):
        n.append(pid)
        if len(n) == 2:
            raise Crash

    world.ops.on_kill = boom
    with pytest.raises(Crash):
        gf.thaw_due(world.state, ops=world.ops, now=T0 + 61)
    assert [x["state"] for x in world.entries()] == ["thawing"]
    world.ops.on_kill = None
    assert gf.thaw_due(world.state, ops=world.ops, now=T0 + 62)["resumed"]
    assert world.entries() == [] and all(world.ops.procs[p]["state"] == "S" for p in (5000, 5001, 5002))


def test_a_failed_signal_rolls_everything_back(world):
    def eperm(pid, sig):
        if sig == signal.SIGSTOP and pid == 5002:
            raise PermissionError(1, "Operation not permitted")

    world.ops.on_kill = eperm
    with pytest.raises(gf.Refusal) as r:
        world.freeze(minutes=5)
    assert r.value.code == gf.REFUSED
    assert world.entries() == [] and all(world.ops.procs[p]["state"] == "S" for p in (5000, 5001, 5002))
    assert [(p, s) for p, s in world.ops.sent if s == signal.SIGCONT]   # what had been stopped was resumed


# ---- identity (F3, H1 e): pid, start, uid and executable, before EVERY signal ----------------------------------------------------------------------
@pytest.mark.parametrize("field,why", [("start", "start"), ("uid", "uid"), ("state", "gone")])
def test_thaw_signals_nothing_when_one_identity_field_differs(world, field, why):
    world.freeze()
    d = world.ops.procs[5001]
    if field == "start":
        d["start"] = "start-other"
    elif field == "uid":
        d["uid"] = ME + 1
    elif field == "exe":
        d["exe"] = "/usr/bin/stranger"
    else:
        d["state"] = "gone"
    done, left = gf.thaw_all(world.state, ops=world.ops, now=T0 + 1)
    assert done and not left and world.ops.sent_to(5001) == [signal.SIGSTOP]   # never signalled again
    assert world.ops.sent_to(5000)[-1] == signal.SIGCONT
    assert [(x["event"], x.get("why")) for x in world.events() if x["event"] == "drop"] == [("drop", why)]


def test_a_reused_pid_inside_the_window_is_not_stopped_or_resumed(world):
    """The app exits and the kernel hands its pid to a stranger that is itself stopped: a thaw must leave it alone."""
    world.freeze()
    world.ops.procs[5000].update(start="start-new", exe="/usr/bin/stranger", state="T")
    gf.thaw_all(world.state, ops=world.ops, now=T0 + 5)
    assert world.ops.sent_to(5000) == [signal.SIGSTOP] and world.ops.procs[5000]["state"] == "T"


def test_a_freeze_with_a_wrong_expected_start_refuses_before_any_signal(world):
    with pytest.raises(gf.Refusal) as r:
        gf.freeze(world.state, 5000, start="start-STALE", ops=world.ops, cfg=cfg(), now=T0, check_sampler=False, agent_clis=())
    assert r.value.code == gf.IDENTITY and world.ops.sent == []


@pytest.mark.parametrize("kw", [{"bundle_id": "com.example.other"}, {"bundle_path": "/Applications/Other.app"}])
def test_expected_bundle_values_are_checked_against_the_live_ones(world, kw):
    with pytest.raises(gf.Refusal) as r:
        gf.freeze(world.state, 5000, start="start-5000", ops=world.ops, cfg=cfg(), now=T0, check_sampler=False, agent_clis=(), **kw)
    assert r.value.code == gf.IDENTITY and world.ops.sent == []


def test_the_live_bundle_values_match_when_expected_ones_are_right(world):
    e = gf.freeze(world.state, 5000, start="start-5000", bundle_id="com.example.fake", bundle_path=str(world.app), minutes=3, ops=world.ops,
                  cfg=cfg(), now=T0, check_sampler=False, agent_clis=())
    assert e["app"]["bundle_id"] == "com.example.fake"


def test_the_mismatch_function_checks_each_of_the_four_fields():
    rec = {"pid": 9, "start": "s", "uid": ME, "exe": "/a"}
    good = {"start": "s", "uid": ME, "state": "S", "exe": "/a"}
    assert gf.mismatch(rec, good, ME) is None and gf.mismatch(rec, None, ME) == "gone"
    assert gf.mismatch(rec, dict(good, state="Z"), ME) == "gone" and gf.mismatch(rec, dict(good, start="t"), ME) == "start"
    assert gf.mismatch(rec, dict(good, uid=0), ME) == "uid" and gf.mismatch(dict(rec, uid=0), dict(good, uid=0), ME) == "uid"
    assert gf.mismatch(rec, dict(good, exe="/b"), ME) == "exe" and gf.mismatch(rec, dict(good, exe=None), ME) == "exe"


def test_a_ps_timeout_defers_a_thaw_without_signalling(world):
    world.freeze(minutes=1)
    world.ops.info_error = True
    world.ops.sent.clear()
    r = gf.thaw_due(world.state, ops=world.ops, now=T0 + 61)
    assert r["resumed"] == [] and r["deferred"] == 1 and world.ops.sent == []
    assert [x["state"] for x in world.entries()] == ["thawing"]
    world.ops.info_error = False
    assert gf.thaw_due(world.state, ops=world.ops, now=T0 + 62)["resumed"]


def test_an_exhausted_budget_defers_and_never_signals_without_an_identity_check(world):
    world.freeze(minutes=1)
    world.ops.sent.clear()
    r = gf.thaw_due(world.state, ops=world.ops, now=T0 + 61, budget_s=-1)
    assert r["deferred"] == 1 and world.ops.sent == []
    assert gf.thaw_due(world.state, ops=world.ops, now=T0 + 62)["resumed"]


def test_a_partial_thaw_keeps_only_the_unfinished_processes(world):
    world.freeze(minutes=1)
    calls = []
    orig = world.ops.info

    def flaky(pids):
        calls.append(pids)
        if len(calls) == 3:   # the thaw's third identity read (pid 5000, the root) times out
            raise OSError("ps timed out")
        return orig(pids)
    world.ops.info = flaky
    r = gf.thaw_due(world.state, ops=world.ops, now=T0 + 61)
    assert r["resumed"] == [] and r["deferred"] == 1
    left = world.entries()[0]
    assert left["state"] == "thawing" and [left["root"]["pid"]] + [m["pid"] for m in left["members"]] == [5000]
    world.ops.info = orig
    assert gf.thaw_due(world.state, ops=world.ops, now=T0 + 62)["resumed"] and world.ops.procs[5000]["state"] == "S"


# ---- the protected list is enforced in the core (F6): root, every member, hard floor --------------------------------------------------------------
def test_a_protected_root_is_refused_with_no_state_and_no_signal(world):
    c = cfg()
    c["protected"]["bundle_ids"] = ["com.example.fake"]
    with pytest.raises(gf.Refusal) as r:
        world.freeze(minutes=5, cfg=c)
    assert r.value.code == gf.PROTECTED and world.ops.sent == [] and not (world.state / "gui-hog" / "frozen.json").exists()


def test_a_protected_helper_inside_the_tree_refuses_the_whole_freeze(world):
    """Reached through a child: the root is fine, one helper's executable is on the protected list."""
    c = cfg()
    c["protected"]["exe_paths"] = [str(world.tmp / "Apps" / "Fake.app" / "Contents" / "MacOS" / "Special")]
    world.ops.procs[5002]["exe"] = str(world.tmp / "Apps" / "Fake.app" / "Contents" / "MacOS" / "Special")
    with pytest.raises(gf.Refusal) as r:
        world.freeze(minutes=5, cfg=c)
    assert r.value.code == gf.PROTECTED and "5002" in r.value.msg and world.ops.sent == []


@pytest.mark.parametrize("name", ["WindowServer", "Dock", "loginwindow", "Finder", "ade-gui-hog"])
def test_a_hard_floor_executable_in_the_tree_cannot_be_unlocked_by_config(world, name):
    world.ops.procs[5001]["exe"] = str(world.app / "Contents" / "MacOS" / name)
    with pytest.raises(gf.Refusal) as r:
        world.freeze(minutes=5, cfg=cfg())
    assert r.value.code == gf.PROTECTED and world.ops.sent == []


def test_a_member_of_another_user_refuses_the_freeze(world):
    world.ops.procs[5001]["uid"] = 0
    with pytest.raises(gf.Refusal) as r:
        world.freeze(minutes=5)
    assert r.value.code == gf.PROTECTED and world.ops.sent == []


def test_this_tool_and_its_ancestors_are_never_frozen(world):
    """The process running the freeze sits under the app (the dialog's own button click): never a member."""
    world.ops.procs[os.getpid()] = proc(5001, world.helper, pid=os.getpid())
    with pytest.raises(gf.Refusal) as r:
        world.freeze(minutes=5)
    assert r.value.code == gf.PROTECTED and "ancestors" in r.value.msg and world.ops.sent == []


def test_an_app_with_a_build_or_terminal_inside_is_refused_with_5(world):
    world.ops.procs[5003] = proc(5001, "/usr/bin/make", pid=5003)
    with pytest.raises(gf.Refusal) as r:
        world.freeze(minutes=5)
    assert r.value.code == gf.HOSTS_BUILD and world.ops.sent == []


def test_an_app_under_a_held_build_or_an_agent_is_refused_with_3(world):
    world.ops.procs[4000] = {**proc(1, "/usr/local/bin/claude", pid=4000), "cmd": "/usr/local/bin/claude"}
    world.ops.procs[5000]["ppid"] = 4000   # Playwright's Chrome for Testing: started by an agent
    with pytest.raises(gf.Refusal) as r:
        gf.freeze(world.state, 5000, start="start-5000", ops=world.ops, cfg=cfg(), now=T0, check_sampler=False, agent_clis=gf.DEFAULT_AGENT_CLIS)
    assert r.value.code == gf.PROTECTED and world.ops.sent == []


def test_a_system_app_and_a_non_app_are_refused(world):
    world.ops.procs[5000]["exe"] = "/usr/bin/sleep"
    with pytest.raises(gf.Refusal) as r:
        world.freeze(minutes=5)
    assert r.value.code == gf.IDENTITY and world.ops.sent == []
    world.ops.procs[5000]["exe"] = "/System/Applications/Clock.app/Contents/MacOS/Clock"
    with pytest.raises(gf.Refusal) as r:
        world.freeze(minutes=5)
    assert r.value.code == gf.PROTECTED and world.ops.sent == []


# ---- the rescan (F4d) -------------------------------------------------------------------------------------------------------------------------------
def test_a_helper_forked_during_the_freeze_is_recorded_then_stopped(world):
    seen = {}
    added = []

    def spawn_then_check(pid, sig):
        if sig == signal.SIGSTOP and pid == 5002 and not added:   # after the root and 5001 are stopped, a new helper appears under the root
            world.ops.procs[5003] = proc(5000, world.helper, pid=5003)
            added.append(1)
        if sig == signal.SIGSTOP and pid == 5003:
            seen["recorded"] = sorted(m["pid"] for m in world.entries()[0]["members"])
    world.ops.on_kill = spawn_then_check
    e = world.freeze(minutes=5)
    assert seen["recorded"] == [5001, 5002, 5003]   # recorded (written) BEFORE its SIGSTOP
    assert world.ops.procs[5003]["state"] == "T" and sorted(m["pid"] for m in e["members"]) == [5001, 5002, 5003]


def test_helpers_still_appearing_after_three_rescans_are_logged_and_left_running(world):
    counter = [5100]

    def keep_forking(pid, sig):
        if sig == signal.SIGSTOP:
            counter[0] += 1
            world.ops.procs[counter[0]] = proc(5000, world.helper, pid=counter[0])
    world.ops.on_kill = keep_forking
    e = world.freeze(minutes=5)
    assert e.get("kept_running", 0) >= 1 and any(x["event"] == "late-helpers" for x in world.events())
    stopped = [p for p, d in world.ops.procs.items() if d["state"] == "T"]
    assert 5000 in stopped and len(stopped) < len(world.ops.procs) - 1   # some helper was left running


def test_a_protected_process_that_appears_mid_freeze_rolls_it_back(world):
    def appear(pid, sig):
        if sig == signal.SIGSTOP and pid == 5002 and 5003 not in world.ops.procs:
            world.ops.procs[5003] = proc(5000, world.app / "Contents" / "MacOS" / "Dock", pid=5003)
    world.ops.on_kill = appear
    with pytest.raises(gf.Refusal) as r:
        world.freeze(minutes=5)
    assert r.value.code == gf.PROTECTED and world.entries() == []
    assert all(world.ops.procs[p]["state"] == "S" for p in (5000, 5001, 5002)) and world.ops.sent_to(5003) == []


# ---- a hand-edited, corrupt or symlinked state (J4) ------------------------------------------------------------------------------------------------
def entry_dict(**kw):
    e = {"id": "f-1", "state": "frozen", "app": {"name": "X", "bundle_id": "b", "bundle_path": "/A/X.app"},
         "root": {"pid": 5000, "start": "start-5000", "uid": ME, "exe": ""}, "members": [], "mode": "indefinite", "frozen_at": T0, "thaw_at": None, "by": "cli"}
    e.update(kw)
    return e


def put(world, entries, name="frozen.json"):
    g = world.state / "gui-hog"
    g.mkdir(mode=0o700, exist_ok=True)
    (g / name).write_text(json.dumps({"v": 1, "entries": entries}))


@pytest.mark.parametrize("bad", [0, -1, 1, True, "5000", 1.5, 2 ** 31, 2 ** 70, None, [5000]])
def test_a_hand_edited_pid_that_is_not_a_plain_process_id_is_never_signalled(world, bad):
    """0 and -1 are process groups to kill(2): `frozen.json` may not make us signal them."""
    e = entry_dict(root={"pid": bad, "start": "x", "uid": ME, "exe": "/a"}, members=[{"pid": bad, "start": "x", "uid": ME, "exe": "/a"}])
    put(world, [e])
    assert gf.thaw_all(world.state, ops=world.ops, now=T0) == ([], []) and world.ops.sent == []
    gf.thaw_due(world.state, ops=world.ops, now=T0 + 10 ** 6)
    assert world.ops.sent == []


def test_a_hand_edited_entry_only_ever_continues_a_stopped_process_that_matches(world):
    """An entry naming a running, matching process (nothing stopped it) sends no signal at all; one naming a stopped stranger sends none either."""
    world.ops.procs[5000]["state"] = "S"
    exe = world.ops.procs[5000]["exe"]
    put(world, [entry_dict(root={"pid": 5000, "start": "start-5000", "uid": ME, "exe": exe}),
                entry_dict(id="f-2", root={"pid": 5001, "start": "FORGED", "uid": ME, "exe": exe})])
    world.ops.procs[5001]["state"] = "T"
    done, left = gf.thaw_all(world.state, ops=world.ops, now=T0)
    assert sorted(done) == ["f-1", "f-2"] and world.ops.sent == [] and world.ops.procs[5001]["state"] == "T"


def test_a_far_future_thaw_at_is_clamped_to_a_day(world):
    e = gf.norm_entry(entry_dict(mode="timed", thaw_at=10 ** 18, root={"pid": 5000, "start": "s", "uid": ME, "exe": "/a"}))
    assert e["thaw_at"] == T0 + gf.MAX_TIMED_S
    for junk in (None, "soon", float("nan"), True):
        assert gf.norm_entry(entry_dict(mode="timed", thaw_at=junk, root={"pid": 5000, "start": "s", "uid": ME, "exe": "/a"}))["thaw_at"] == T0   # due


@pytest.mark.parametrize("mut", [lambda e: e.pop("frozen_at"), lambda e: e.update(state="evil"), lambda e: e.update(mode="x"),
                                 lambda e: e.update(id="../../etc"), lambda e: e.update(id=""), lambda e: e.update(root="no"),
                                 lambda e: e.update(frozen_at=float("inf")), lambda e: e.update(members="no")])
def test_invalid_entries_are_dropped_not_trusted(mut):
    e = entry_dict(root={"pid": 5000, "start": "s", "uid": ME, "exe": "/a"})
    mut(e)
    assert gf.norm_entry(e) is None or gf.norm_entry(e)["members"] == []


def test_a_corrupt_state_file_falls_back_to_the_previous_good_one(world):
    world.freeze(minutes=1)
    world.freeze_again = None
    g = world.state / "gui-hog"
    shutil.copy(g / "frozen.json", g / "frozen.json.prev")
    (g / "frozen.json").write_text("{not json")
    entries, notes = gf.load_entries(os.open(g, os.O_RDONLY))
    assert len(entries) == 1 and "using frozen.json.prev" in notes
    assert gf.thaw_all(world.state, ops=world.ops, now=T0 + 1)[0]


def test_a_corrupt_state_file_with_no_good_copy_refuses_and_signals_nothing(world):
    g = world.state / "gui-hog"
    g.mkdir(mode=0o700)
    (g / "frozen.json").write_text("{not json")
    with pytest.raises(gf.Refusal) as r:
        gf.thaw_all(world.state, ops=world.ops, now=T0)
    assert r.value.code == gf.REFUSED and "--stopped-apps" in r.value.msg and world.ops.sent == []
    with pytest.raises(gf.Refusal):
        world.freeze(minutes=1)   # and a freeze cannot write its write-ahead record onto it either
    assert world.ops.sent == []


def test_a_symlinked_frozen_json_is_not_followed(world, tmp_path):
    g = world.state / "gui-hog"
    g.mkdir(mode=0o700)
    secret = tmp_path / "elsewhere.json"
    secret.write_text(json.dumps({"v": 1, "entries": [entry_dict(root={"pid": 5000, "start": "start-5000", "uid": ME, "exe": world.ops.procs[5000]["exe"]})]}))
    os.symlink(secret, g / "frozen.json")
    with pytest.raises(gf.Refusal):
        gf.thaw_all(world.state, ops=world.ops, now=T0)
    assert world.ops.sent == []


def test_a_freeze_never_writes_through_a_symlink_at_frozen_json(world, tmp_path):
    g = world.state / "gui-hog"
    g.mkdir(mode=0o700)
    target = tmp_path / "victim.json"
    target.write_text("untouched")
    os.symlink(target, g / "frozen.json")
    with pytest.raises(gf.Refusal):   # unreadable state: no write-ahead possible, so nothing is stopped
        world.freeze(minutes=1)
    assert target.read_text() == "untouched" and world.ops.sent == []


@pytest.mark.parametrize("which", ["state", "gui-hog"])
def test_a_symlinked_state_directory_is_refused(world, tmp_path, which):
    other = tmp_path / "other"
    other.mkdir()
    if which == "state":
        link = tmp_path / "link"
        os.symlink(other, link)
        sd = link
    else:
        os.symlink(other, world.state / "gui-hog")
        sd = world.state
    with pytest.raises(gf.Refusal) as r:
        gf.freeze(sd, 5000, start="start-5000", minutes=1, ops=world.ops, cfg=cfg(), now=T0, check_sampler=False, agent_clis=())
    assert r.value.code == gf.REFUSED and world.ops.sent == [] and list(other.iterdir()) == []
    with pytest.raises(gf.Refusal):
        gf.thaw_all(sd, ops=world.ops, now=T0)


def test_a_group_writable_state_directory_is_refused(world):
    g = world.state / "gui-hog"
    g.mkdir(mode=0o700)
    g.chmod(0o770)
    with pytest.raises(gf.Refusal) as r:
        world.freeze(minutes=1)
    assert r.value.code == gf.REFUSED and world.ops.sent == []


def test_thaw_due_with_no_state_does_nothing(world):
    assert gf.thaw_due(world.state, ops=world.ops, now=T0) == {"resumed": [], "dropped": [], "deferred": 0}
    assert not (world.state / "gui-hog").exists()   # reading never creates the directory


# ---- the lock (F1), disabled (I3), sampler not loaded (F8-2) -----------------------------------------------------------------------------------------
def test_a_held_lock_times_out_and_nothing_is_signalled(world):
    import fcntl
    g = world.state / "gui-hog"
    g.mkdir(mode=0o700)
    fd = os.open(g / "frozen.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        t = time.monotonic()
        with pytest.raises(gf.Refusal) as r:
            world.freeze(minutes=1, lock_timeout=0.2)
        assert r.value.code == gf.LOCK_TIMEOUT and time.monotonic() - t < 3 and world.ops.sent == []
        with pytest.raises(gf.Refusal):
            gf.thaw_all(world.state, ops=world.ops, now=T0, lock_timeout=0.1)
    finally:
        os.close(fd)


def test_freeze_disabled_in_the_config_refuses_but_thaw_still_works(world):
    e = world.freeze(minutes=1)
    with pytest.raises(gf.Refusal) as r:
        world.freeze(cfg=cfg(enabled=False), minutes=1)
    assert r.value.code == gf.DISABLED
    assert gf.thaw_all(world.state, ops=world.ops, now=T0 + 1) == ([e["id"]], [])


def test_freeze_refuses_when_the_sampler_is_not_loaded(world, monkeypatch):
    monkeypatch.setattr(gf, "sampler_loaded", lambda uid: False)
    with pytest.raises(gf.Refusal) as r:
        gf.freeze(world.state, 5000, start="start-5000", minutes=1, ops=world.ops, cfg=cfg(), now=T0, agent_clis=())
    assert r.value.code == gf.SAMPLER and world.ops.sent == []


@pytest.mark.parametrize("minutes", [0, -5, 1441, 2 ** 40])
def test_minutes_out_of_range_are_refused(world, minutes):
    with pytest.raises(gf.Refusal) as r:
        world.freeze(minutes=minutes)
    assert r.value.code == gf.USAGE and world.ops.sent == []


def test_a_bad_by_is_refused(world):
    with pytest.raises(gf.Refusal) as r:
        world.freeze(minutes=1, by="a script")
    assert r.value.code == gf.USAGE


# ---- the other thaw paths (F5, F7) -----------------------------------------------------------------------------------------------------------------
def test_after_a_reboot_every_entry_whose_processes_are_gone_is_dropped_without_a_signal(world):
    world.freeze()
    for p in (5000, 5001, 5002):
        world.ops.procs[p]["state"] = "gone"
    world.ops.sent.clear()
    r = gf.thaw_due(world.state, ops=world.ops, now=T0 + 3600)
    assert len(r["dropped"]) == 1 and world.entries() == [] and world.ops.sent == []
    assert {"drop"} <= {x["event"] for x in world.events()} and all(x.get("why") == "gone" for x in world.events() if x["event"] == "drop")


def test_a_changed_executable_is_resumed_not_dropped_on_thaw_and_still_refused_on_stop(world):
    """F3 for SIGCONT is pid + start + uid + state T (round 1, A1); SIGSTOP still compares the executable too."""
    world.freeze()
    world.ops.procs[5001]["exe"] = "/usr/bin/other"
    gf.thaw_all(world.state, ops=world.ops, now=T0 + 1)
    assert world.ops.procs[5001]["state"] == "S" and any(x["event"] == "exe-changed" and x["pid"] == 5001 for x in world.events())
    rec = {"pid": 5002, "start": "start-5002", "uid": ME, "exe": "/not/its/exe"}
    assert gf._signal_one(world.ops, rec, signal.SIGSTOP) == "exe"


def test_a_helper_that_exited_while_frozen_is_pruned_from_the_entry(world):
    world.freeze()
    world.ops.procs[5001]["state"] = "gone"
    gf.thaw_due(world.state, ops=world.ops, now=T0 + 5)
    assert [m["pid"] for m in world.entries()[0]["members"]] == [5002]


def test_a_member_resumed_by_someone_else_is_logged_not_signalled(world):
    world.freeze()
    world.ops.procs[5001]["state"] = "S"
    world.ops.sent.clear()
    gf.thaw_all(world.state, ops=world.ops, now=T0 + 1)
    assert world.ops.sent_to(5001) == [] and any(x["event"] == "not-stopped" and x["pid"] == 5001 for x in world.events())


def test_resume_one_entry_by_id(world):
    e = world.freeze()
    with pytest.raises(gf.Refusal):
        gf.thaw_all(world.state, ops=world.ops, now=T0, entry_id="f-nope")
    assert gf.thaw_all(world.state, ops=world.ops, now=T0, entry_id=e["id"]) == ([e["id"]], [])


def test_the_stopped_app_escape_hatch_lists_and_resumes_only_stopped_app_processes(world):
    world.ops.procs[5002]["state"] = "T"
    world.ops.procs[7000] = proc(1, "/usr/bin/vim", pid=7000, state="T")   # stopped, but not an app: left alone
    world.ops.procs[7001] = proc(1, world.exe, uid=ME + 1, pid=7001, state="T")   # another user's: left alone
    recs = gf.stopped_apps(world.ops)
    assert [r["pid"] for r in recs] == [5002]
    assert gf.thaw_stopped_apps(world.ops, recs) == [5002] and world.ops.sent_to(7000) == [] and world.ops.sent_to(7001) == []


def test_the_stopped_app_escape_hatch_rechecks_identity_before_it_signals(world):
    world.ops.procs[5002]["state"] = "T"
    recs = gf.stopped_apps(world.ops)
    world.ops.procs[5002]["start"] = "start-new"   # replaced between the list and the CONT
    assert gf.thaw_stopped_apps(world.ops, recs) == [] and world.ops.sent == []


def test_frozen_view_lists_entries_with_liveness(world):
    e = world.freeze(minutes=10)
    v = gf.frozen_view(world.state, ops=world.ops, now=T0)
    assert [x["id"] for x in v["entries"]] == [e["id"]] and v["entries"][0]["alive"] and v["entries"][0]["members"] == 3
    world.ops.procs[5000]["state"] = "gone"
    assert gf.frozen_view(world.state, ops=world.ops)["entries"][0]["alive"] is False
    assert gf.frozen_view(world.state / "nope", ops=world.ops) == {"v": 1, "entries": [], "notes": []}


def test_thaw_due_dry_run_reports_without_signalling(world):
    world.freeze(minutes=1)
    world.ops.sent.clear()
    lines = []
    r = gf.thaw_due(world.state, ops=world.ops, now=T0 + 61, dry=True, out=lines.append)
    assert len(r["resumed"]) == 1 and lines and world.ops.sent == [] and world.entries()


# ---- wiring ---------------------------------------------------------------------------------------------------------------------------------------
def test_default_agent_clis_match_load_watchs():
    tree = ast.parse((BIN / "load-watch").read_text())
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "AGENT_CLIS" for t in n.targets))
    assert gf.DEFAULT_AGENT_CLIS == frozenset(ast.literal_eval(node.value.args[0]))


def test_the_shipped_config_enables_freeze_with_a_ten_minute_default():
    c = gh.load_config(local=Path("/nonexistent"))
    assert c["freeze"]["enabled"] is True and c["freeze"]["default_minutes"] == 10 and c["freeze"]["max_minutes"] == 1440


def test_the_sampler_resumes_a_due_freeze_before_it_reads_ps(monkeypatch, tmp_path, world):
    """F5a: `thaw --due` runs before ps_table(), so a ps stall (ps_table() -> None) never delays a resume."""
    import argparse
    lw = load_module(monkeypatch, world.state)
    e = world.freeze(minutes=1)
    monkeypatch.setattr(gf, "Ops", lambda *a, **k: world.ops)
    monkeypatch.setattr(lw, "now", lambda: T0 + 61)
    monkeypatch.setattr(lw, "ps_table", lambda: None)
    assert lw.cmd_sample(argparse.Namespace(dry_run=False, verbose=False)) == 0
    assert world.entries() == [] and world.ops.procs[5000]["state"] == "S"
    assert world.events()[-1]["by"] == "sampler" and e["id"] in (lw.STATE_DIR / "sample.log").read_text()


def test_a_failing_thaw_never_stops_the_sampler(monkeypatch, tmp_path, world):
    import argparse
    lw = load_module(monkeypatch, world.state)
    world.freeze(minutes=1)
    monkeypatch.setattr(gf, "thaw_due", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(lw, "ps_table", lambda: {"1": (0, 0, 0.1, "x")})
    assert lw.cmd_sample(argparse.Namespace(dry_run=False, verbose=False)) == 0
    assert "gui-hog thaw error" in (lw.STATE_DIR / "sample.log").read_text()


def test_the_sampler_thaws_even_with_lw_gui_hog_off(monkeypatch, world):
    import argparse
    lw = load_module(monkeypatch, world.state)
    monkeypatch.setenv("LW_GUI_HOG", "0")
    world.freeze(minutes=1)
    monkeypatch.setattr(gf, "Ops", lambda *a, **k: world.ops)
    monkeypatch.setattr(lw, "now", lambda: T0 + 61)
    monkeypatch.setattr(lw, "ps_table", lambda: {"1": (0, 0, 0.1, "x")})
    lw.cmd_sample(argparse.Namespace(dry_run=False, verbose=False))
    assert world.entries() == []


def test_uninstalling_load_watch_resumes_frozen_apps_first(monkeypatch, world):
    import ade_sched
    world.freeze()
    monkeypatch.setattr(gf, "Ops", lambda *a, **k: world.ops)
    env = {"LW_STATE_DIR": str(world.state)}
    ade_sched.thaw_gui_hog_before_removal("com.example.other", env)   # another job: nothing
    assert world.ops.procs[5000]["state"] == "T"
    ade_sched.thaw_gui_hog_before_removal(ade_sched.LOAD_WATCH_LABEL, env)
    assert world.entries() == [] and world.ops.procs[5000]["state"] == "S" and world.events()[-1]["by"] == "uninstall"


def test_uninstall_is_refused_when_a_frozen_app_cannot_be_resumed(monkeypatch, world):
    import ade_sched
    world.freeze()
    world.ops.info_error = True
    monkeypatch.setattr(gf, "Ops", lambda *a, **k: world.ops)
    with pytest.raises(ade_sched.SchedError):
        ade_sched.thaw_gui_hog_before_removal(ade_sched.LOAD_WATCH_LABEL, {"LW_STATE_DIR": str(world.state)})
    monkeypatch.setattr(gf, "thaw_all", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(ade_sched.SchedError):
        ade_sched.thaw_gui_hog_before_removal(ade_sched.LOAD_WATCH_LABEL, {"LW_STATE_DIR": str(world.state)})


def test_uninstall_with_nothing_frozen_does_not_import_the_freeze_module(monkeypatch, tmp_path):
    import ade_sched
    monkeypatch.setattr(gf, "thaw_all", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")))
    ade_sched.thaw_gui_hog_before_removal(ade_sched.LOAD_WATCH_LABEL, {"LW_STATE_DIR": str(tmp_path)})
    (tmp_path / "gui-hog").mkdir(mode=0o700)
    ade_sched.thaw_gui_hog_before_removal(ade_sched.LOAD_WATCH_LABEL, {"LW_STATE_DIR": str(tmp_path)})


# ---- real signals on real processes (H1a): disposable trees this file starts ---------------------------------------------------------------------
class Recorder(gf.Ops):
    """The real Ops, recording each signal (and optionally running a hook before it)."""

    def __init__(self):
        super().__init__()
        self.sent, self.hook = [], None

    def kill(self, pid, sig):
        if self.hook:
            self.hook(pid, sig)
        self.sent.append((pid, sig))
        return super().kill(pid, sig)


def _state(ops, pid):
    inf = ops.info([pid]).get(pid)
    return inf["state"] if inf else None


def _wait(cond, what, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


@pytest.fixture
def real(tmp_path):
    """Fake.app with a root (a copy of /bin/sh) and two helpers (copies of the shell, blocked on a fifo) inside its bundle, started detached (setsid, parent exits:
    launchd-like), so the tree under it is only ours. Everything it starts is killed at teardown."""
    app = tmp_path / "Apps" / "Fake.app"
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.example.real"}))
    shell = os.path.realpath("/bin/dash" if os.path.exists("/bin/dash") else "/bin/sh")
    # Both are copies of the shell: a copied `sleep` is a multi-call binary on some Linux runners (uutils coreutils) that refuses to run under another name (CI, 2026-11-15)
    for src, dst in ((shell, "Fake"), (shell, "Helper")):
        shutil.copy(src, macos / dst)
        if sys.platform == "darwin":   # macOS kills a copied Apple binary (exit 137) until it is ad-hoc signed
            subprocess.run(["codesign", "--force", "-s", "-", str(macos / dst)], capture_output=True, timeout=60)
    if subprocess.run([str(macos / "Fake"), "-c", "exit 0"], capture_output=True, timeout=20).returncode != 0:
        pytest.skip("a copied shell does not run here")
    fifo = tmp_path / "hold"
    os.mkfifo(fifo)   # a helper opens it read-write (never blocks) and then waits on a read that never gets data
    hold = f"{shlex.quote(str(macos / 'Helper'))} -c 'read x' <>{shlex.quote(str(fifo))}"
    script = f"{hold} & {hold} & wait"
    spawner = ("import subprocess,sys;p=subprocess.Popen([sys.argv[1],'-c',sys.argv[2]],start_new_session=True,close_fds=True,"
               "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);print(p.pid)")
    try:
        r = subprocess.run([sys.executable, "-c", spawner, str(macos / "Fake"), script], capture_output=True, text=True, timeout=20, check=True)
    except (subprocess.SubprocessError, OSError) as e:
        pytest.skip(f"cannot run a copied shell here: {e}")
    ops = Recorder()
    root = int(r.stdout.strip())
    created = {root}

    def kids():
        table = ops.table()[0]
        return sorted(int(p) for p, v in table.items() if v[0] == root)
    try:
        try:
            _wait(lambda: len(kids()) == 2, "the two helpers")
        except AssertionError as e:   # say what the machine looked like: a CI-only failure must leave evidence in the log
            probe = subprocess.run([str(macos / "Helper"), "-c", "exit 0"], capture_output=True, text=True, timeout=20)
            ps = subprocess.run(["ps", "-axo", "pid,ppid,state,comm,args"], capture_output=True, text=True, timeout=20).stdout
            mine = [ln for ln in ps.splitlines() if str(macos) in ln or ln.split()[:1] == [str(root)]]
            raise AssertionError(f"{e}: root {root}, table kids {kids()}, `Helper -c 'exit 0'` rc {probe.returncode} {probe.stderr.strip()[:200]!r}, ps lines {mine}") from None
        created |= set(kids())
        w = type("R", (), {})()
        w.ops, w.root, w.kids, w.state, w.app, w.macos, w.tmp = ops, root, kids(), tmp_path / "state", app, macos, tmp_path
        w.state.mkdir()
        w.start = ops.info([root])[root]["start"]
        yield w
    finally:
        for p in created:   # only pids this fixture started
            for sig in (signal.SIGCONT, signal.SIGKILL):
                try:
                    os.kill(p, sig)
                except OSError:
                    pass


def rfreeze(w, **kw):
    return gf.freeze(w.state, w.root, start=w.start, ops=w.ops, cfg=kw.pop("cfg", cfg()), check_sampler=False, agent_clis=(), **kw)


# ---- a timed freeze always has a clock (H4 run 2026-11-14: a dialog opened by hand, an old sampler, nothing resumed the freeze) -------------------
def _freeze_args(**kw):
    import argparse
    return argparse.Namespace(**{"pid": 5, "start": "s", "bundle_id": None, "bundle_path": None, "minutes": 10, "indefinite": False, "by": "dialog", **kw})


def test_a_successful_freeze_starts_the_menu_bar_item_so_a_timed_freeze_never_depends_on_the_sampler(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(gf, "freeze", lambda *a, **k: {"id": "f-1", "state": "frozen", "mode": "timed", "thaw_at": 1.0, "members": [], "kept_running": 0})
    monkeypatch.setattr(gf, "ensure_status_item", lambda sd, **k: calls.append(sd) or (True, "started"))
    assert gf.cmd_freeze(_freeze_args(), tmp_path) == gf.OK
    assert calls == [tmp_path]   # the second clock (the item's own 20 s timer) is started by the freeze itself, not only by a sampler tick
    assert json.loads(capsys.readouterr().out)["status_item"] == "started"


def test_a_menu_bar_item_that_cannot_start_never_fails_the_freeze(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gf, "freeze", lambda *a, **k: {"id": "f-1", "state": "frozen", "mode": "indefinite", "thaw_at": None, "members": [], "kept_running": 0})
    def boom(sd, **k):
        raise RuntimeError("no window server")
    monkeypatch.setattr(gf, "ensure_status_item", boom)
    assert gf.cmd_freeze(_freeze_args(indefinite=True, minutes=None), tmp_path) == gf.OK   # the app is stopped: the record and the exit code must say so
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_a_refused_freeze_starts_no_menu_bar_item(tmp_path, monkeypatch):
    calls = []
    def refuse(*a, **k):
        raise gf.Refusal(gf.PROTECTED, "protected")
    monkeypatch.setattr(gf, "freeze", refuse)
    monkeypatch.setattr(gf, "ensure_status_item", lambda sd, **k: calls.append(sd) or (True, "started"))
    assert gf.cmd_freeze(_freeze_args(), tmp_path) != gf.OK and calls == []


def test_the_dialog_drops_a_stale_frozen_label_once_the_app_runs_again():   # H4: a 30 min old manual window kept saying "frozen" after a thaw --all
    ui, model = ((BIN.parent / "macos" / "gui-hog" / n).read_text() for n in ("UI.swift", "Model.swift"))
    assert "func clearStaleFrozen(" in model and "clearStaleFrozen(" in ui


def test_the_dialog_ticks_a_thaw_clock_of_its_own():   # Swift side, structural: the window re-runs `thaw --due` every 20 s while it is open
    ui, model = ((BIN.parent / "macos" / "gui-hog" / n).read_text() for n in ("UI.swift", "Model.swift"))
    assert "func thawDueTick(" in model and "thawDueTick(" in ui and 'runner.thawDue(by: "dialog")' in ui
    assert ui.count('runner.thawDue(by: "dialog")') >= 2   # at start (F5b) and on the tick


def test_clock_text_is_new_york_12_hour_with_a_day_name_when_not_today():   # operator ruling 2026-11-14: a clock time, never a countdown
    due, same_day, other_day = 1794711120, 1794704400, 1794582000   # 2026-11-14 9:52 PM New York; 8:00 PM the same day; Fri 10:00 AM
    assert gf.clock_text(due, same_day, zone="America/New_York") == "9:52 PM"
    assert gf.clock_text(due, other_day, zone="America/New_York") == "Sat 9:52 PM"
    assert gf.clock_text(due, same_day, zone="UTC") == "2:52 AM" and gf.clock_text(due, other_day, zone="UTC") == "Sun 2:52 AM"   # the zone is a parameter
    assert gf.clock_text(due, same_day, zone="America/New_York") == gf.clock_text(due, same_day + 60, zone="America/New_York")   # no countdown
    assert gf.clock_text(1794744000, 1794744000, zone="UTC") == "12:00 PM" and gf.clock_text(1794700800, 1794700800, zone="UTC") == "12:00 AM"
    assert gf.clock_text(999999999999999, same_day) == "?" and gf.clock_text(1e13, same_day) == "?"   # far off: a hand-edited file, same as the Swift side
    week = 7 * 24 * 3600   # the guard's edge, a time inside the zone's range (so no other check can hide a missing guard)
    assert gf.clock_text(same_day + week, same_day, zone="UTC") not in ("?", "") and gf.clock_text(same_day + week + 1, same_day, zone="UTC") == "?"
    assert gf.clock_text(same_day - week, same_day, zone="UTC") != "?" and gf.clock_text(same_day - week - 1, same_day, zone="UTC") == "?"
    assert gf.clock_text(float("nan"), same_day) == "?" and gf.clock_text(10**30, same_day) == "?"
    assert gf.clock_text(due, same_day, zone="Not/AZone").endswith("UTC")   # a zone that cannot load says so


def test_cli_frozen_prints_the_resume_clock_time_or_until_you_resume(tmp_path):
    g = tmp_path / "gui-hog"
    g.mkdir(mode=0o700)
    now = time.time()
    root = {"pid": 5000, "start": "start-5000", "uid": ME, "exe": "/bin/x"}   # a valid record needs a non-empty exe
    (g / "frozen.json").write_text(json.dumps({"v": 1, "entries": [entry_dict(id="t-1", mode="timed", frozen_at=now, thaw_at=now + 3 * 3600, root=root),
                                                                    entry_dict(id="i-1", mode="indefinite", frozen_at=now, thaw_at=None, root=root)]}))
    out = cli(tmp_path, "frozen").stdout
    timed = next(ln for ln in out.splitlines() if ln.startswith("t-1"))
    assert "resumes at " in timed and "Z " not in timed and "indefinitely" not in out   # a clock time, not the ISO UTC stamp
    assert "until you Resume" in next(ln for ln in out.splitlines() if ln.startswith("i-1"))
    (g / "frozen.json").write_text(json.dumps({"v": 1, "entries": [entry_dict(id="t-0", mode="timed", frozen_at=now, thaw_at=0, root=root)]}))
    assert "until you Resume" not in cli(tmp_path, "frozen").stdout   # a timed entry with thaw_at 0 is a time (already due), not an indefinite freeze


def test_cli_freeze_takes_a_dash_leading_bundle_id_joined_with_equals(tmp_path):   # adversary round 4, C2: the Swift side joins values with `=`
    r = cli(tmp_path, "freeze", "--pid=5", "--start=x", "--bundle-id=-y", "--bundle-path=-z", "--minutes=5", "--by", "dialog")
    assert r.returncode != 2, r.stderr   # parsed (the pid is not ours, so it is refused for another reason)


def test_real_tree_is_stopped_root_first_and_resumed_children_first(real):
    e = rfreeze(real, minutes=10)
    assert [p for p, s in real.ops.sent if s == signal.SIGSTOP] == [real.root] + real.kids
    assert all(_state(real.ops, p).startswith("T") for p in [real.root] + real.kids)   # `ps` state T on the whole tree
    assert [m["pid"] for m in e["members"]] == real.kids
    real.ops.sent.clear()
    assert gf.thaw_all(real.state, ops=real.ops) == ([e["id"]], [])
    assert [p for p, s in real.ops.sent if s == signal.SIGCONT] == list(reversed(real.kids)) + [real.root]
    _wait(lambda: not any((_state(real.ops, p) or "").startswith("T") for p in [real.root] + real.kids), "the tree to run again")


def test_real_write_ahead_record_exists_before_the_first_sigstop(real):
    seen = []

    def look(pid, sig):
        if sig == signal.SIGSTOP and not seen:
            e = json.loads((real.state / "gui-hog" / "frozen.json").read_text())["entries"][0]
            seen.append((e["state"], e["root"]["pid"], sorted(m["pid"] for m in e["members"])))
    real.ops.hook = look
    rfreeze(real, minutes=5)
    assert seen == [("freezing", real.root, real.kids)]
    assert _state(real.ops, real.root).startswith("T")


def test_real_crash_after_the_root_stopped_is_recovered(real):
    n = []

    def boom(pid, sig):
        n.append(pid)
        if len(n) == 2:   # right after the root's SIGSTOP, before the first helper's
            raise Crash

    real.ops.hook = boom
    with pytest.raises(Crash):
        rfreeze(real, minutes=5)
    real.ops.hook = None
    assert _state(real.ops, real.root).startswith("T") and not _state(real.ops, real.kids[0]).startswith("T")
    g = json.loads((real.state / "gui-hog" / "frozen.json").read_text())["entries"]
    assert [x["state"] for x in g] == ["freezing"]
    real.ops.sent.clear()
    assert len(gf.thaw_due(real.state, ops=real.ops)["resumed"]) == 1
    assert [p for p, s in real.ops.sent if s == signal.SIGCONT] == [real.root]   # the helpers were never stopped: never signalled
    _wait(lambda: not _state(real.ops, real.root).startswith("T"), "the root to run again")


def test_real_timed_freeze_resumes_when_due_and_not_before(real):
    rfreeze(real, minutes=1, now=T0)
    assert gf.thaw_due(real.state, ops=real.ops, now=T0 + 59)["resumed"] == [] and _state(real.ops, real.root).startswith("T")
    assert len(gf.thaw_due(real.state, ops=real.ops, now=T0 + 61)["resumed"]) == 1
    _wait(lambda: not _state(real.ops, real.root).startswith("T"), "the root to run again")


def test_real_a_stranger_with_a_forged_or_reused_pid_is_never_continued(real, tmp_path):
    """The entry names a pid that now belongs to another process (stopped by this test): all four identity fields are compared first."""
    stranger = subprocess.Popen([shutil.which("sleep") or "/bin/sleep", "300"], start_new_session=True)   # run under its own name: a resolved multi-call binary would not
    try:
        os.kill(stranger.pid, signal.SIGSTOP)
        _wait(lambda: (_state(real.ops, stranger.pid) or "").startswith("T"), "the stranger to stop")
        inf = real.ops.info([stranger.pid])[stranger.pid]
        g = real.state / "gui-hog"
        g.mkdir(mode=0o700)
        for i, (start, exe) in enumerate([("old-start", inf["exe"])]):   # a changed exe alone is resumed (round 1, A1)
            rec = {"pid": stranger.pid, "start": start, "uid": ME, "exe": exe}
            (g / "frozen.json").write_text(json.dumps({"v": 1, "entries": [entry_dict(id=f"f-{i}", root=rec)]}))
            gf.thaw_all(real.state, ops=real.ops)
            assert (_state(real.ops, stranger.pid) or "").startswith("T") and (stranger.pid, signal.SIGCONT) not in real.ops.sent
    finally:
        stranger.kill()
        stranger.wait()


def test_real_a_protected_helper_refuses_and_nothing_is_stopped(real):
    c = cfg()
    c["protected"]["exe_paths"] = [str(real.macos / "Helper")]
    with pytest.raises(gf.Refusal) as r:
        rfreeze(real, minutes=5, cfg=c)
    assert r.value.code == gf.PROTECTED and not real.ops.sent
    assert not any(_state(real.ops, p).startswith("T") for p in [real.root] + real.kids)


def test_real_a_wrong_start_refuses_before_any_signal(real):
    with pytest.raises(gf.Refusal) as r:
        gf.freeze(real.state, real.root, start="proc:1" if os.path.isdir("/proc/self") else "Mon Jan  1 00:00:00 2001", ops=real.ops, cfg=cfg(),
                  check_sampler=False, agent_clis=())
    assert r.value.code == gf.IDENTITY and not real.ops.sent


# ---- the CLI ----------------------------------------------------------------------------------------------------------------------------------------
def cli(state, *args):
    # a freeze starts the menu-bar item: point the bundle at a path that does not exist so a test run never launches the real app on this desktop
    env = dict(os.environ, LW_STATE_DIR=str(state), LW_GUI_HOG_BUNDLE=str(Path(state) / "no-such-bundle" / "ADE GUI Hog.app"))
    return subprocess.run([sys.executable, str(BIN / "gui-hog"), *args], capture_output=True, text=True, env=env, timeout=60)


def test_cli_frozen_with_nothing_frozen(tmp_path):
    r = cli(tmp_path, "frozen")
    assert r.returncode == 0 and "nothing is frozen" in r.stdout
    assert json.loads(cli(tmp_path, "frozen", "--json").stdout)["entries"] == []


def test_cli_refuses_a_process_that_is_not_an_app_with_exit_4(tmp_path):
    sleeper = subprocess.Popen(["sleep", "300"], start_new_session=True)
    try:
        start = gh.proc_start(sleeper.pid)
        r = cli(tmp_path, "freeze", "--pid", str(sleeper.pid), "--start", start, "--minutes", "1")
        out = json.loads(r.stdout)
        assert r.returncode in (4, 8) and out["ok"] is False   # 8 only where the launchd sampler is not loaded (a Mac without it)
        assert not (_state(gf.Ops(), sleeper.pid) or "").startswith("T")
    finally:
        sleeper.kill()
        sleeper.wait()


def test_cli_rejects_both_minutes_and_indefinite_and_a_bad_by(tmp_path):
    assert cli(tmp_path, "freeze", "--pid", "5", "--start", "x", "--minutes", "5", "--indefinite").returncode == 2
    assert cli(tmp_path, "freeze", "--pid", "5", "--start", "x", "--by", "robot").returncode == 2


def test_cli_full_cycle_on_a_real_tree(real):
    r = cli(real.state, "freeze", "--pid", str(real.root), "--start", real.start, "--bundle-id", "com.example.real", "--minutes", "5", "--by", "dialog")
    if r.returncode == 8:
        pytest.skip("the load-watch launchd job is not loaded here (F8-2)")
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["ok"] and out["members"] == 3 and _state(real.ops, real.root).startswith("T")
    assert out["status_item"] in ("bundle-missing", "no-gui"), out   # never the real app
    listed = json.loads(cli(real.state, "frozen", "--json").stdout)["entries"]
    assert [x["id"] for x in listed] == [out["entry"]] and listed[0]["alive"] and listed[0]["by"] == "dialog"
    assert cli(real.state, "freeze", "--pid", str(real.root), "--start", real.start, "--minutes", "5").returncode == 9   # already frozen
    t = cli(real.state, "thaw", "--all")
    assert t.returncode == 0 and json.loads(t.stdout)["resumed"] == [out["entry"]]
    _wait(lambda: not _state(real.ops, real.root).startswith("T"), "the root to run again")
    assert "nothing is frozen" in cli(real.state, "frozen").stdout


def test_cli_thaw_stopped_apps_asks_unless_told_yes(real):
    os.kill(real.root, signal.SIGSTOP)
    _wait(lambda: _state(real.ops, real.root).startswith("T"), "the root to stop")
    env = dict(os.environ, LW_STATE_DIR=str(real.state))
    r = subprocess.run([sys.executable, str(BIN / "gui-hog"), "thaw", "--all", "--stopped-apps"], capture_output=True, text=True, env=env,
                       stdin=subprocess.DEVNULL, timeout=60)
    assert r.returncode == 9 and "not confirmed" in r.stderr and _state(real.ops, real.root).startswith("T")
    # (`--yes` is covered with fakes above: on a real machine it would resume every stopped app of the user, which a test must not do)


def test_the_event_log_is_not_followed_through_a_symlink(world, tmp_path):
    g = world.state / "gui-hog"
    g.mkdir(mode=0o700)
    victim = tmp_path / "victim.log"
    victim.write_text("keep")
    os.symlink(victim, g / "events.jsonl")
    world.freeze(minutes=1)   # the freeze still works; its log line is dropped, never written through the link
    assert victim.read_text() == "keep"


# ---- the menu-bar item (E5) and the snapshot's Freeze switch (PR 3c, view side) ------------------------------------------------------------------
def fake_bundle(tmp_path):
    b = tmp_path / "ADE GUI Hog.app"
    (b / "Contents" / "MacOS").mkdir(parents=True)
    (b / "Contents" / "Resources").mkdir(parents=True)
    exe = b / "Contents" / "MacOS" / "ade-gui-hog"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    (b / "Contents" / "Resources" / "source.sha256").write_text(gh.source_hash() + "\n")
    return b


def test_the_snapshot_carries_the_freeze_switch_so_the_view_can_hide_the_buttons():
    snap = gh.build_snapshot([], [], T0, cfg(enabled=False, default_minutes=15))
    assert snap["freeze"] == {"enabled": False, "default_minutes": 15}
    assert gh.build_snapshot([], [], T0, cfg())["freeze"] == {"enabled": True, "default_minutes": 10}


def test_the_menu_bar_item_starts_only_while_something_is_frozen(world, tmp_path):
    launches = []
    b = fake_bundle(tmp_path)
    popen = lambda argv, **k: launches.append(argv)  # noqa: E731
    assert gf.ensure_status_item(world.state, popen=popen, bundle=b) == (False, "nothing-frozen") and launches == []
    world.freeze(minutes=10)
    assert gf.ensure_status_item(world.state, popen=popen, bundle=b, gui_ok=False) == (False, "no-gui") and launches == []
    assert gf.ensure_status_item(world.state, popen=popen, bundle=b) == (True, "")
    assert launches[0][0].endswith("ade-gui-hog") and "--status-only" in launches[0] and "--state-dir" in launches[0]
    assert all(isinstance(a, str) for a in launches[0])


def test_the_menu_bar_item_is_one_instance_with_its_own_lock(world, tmp_path):
    import fcntl
    launches = []
    b = fake_bundle(tmp_path)
    world.freeze(minutes=10)
    d = world.state / "gui-hog"
    fd = os.open(d / "status.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert gf.ensure_status_item(world.state, popen=lambda *a, **k: launches.append(1), bundle=b) == (False, "running") and launches == []
        assert gh.dialog_running(world.state) is False   # the dialog's own lock is a different file: a running item never blocks the dialog
    finally:
        os.close(fd)


def test_a_missing_bundle_or_a_launch_error_never_raises(world, tmp_path):
    world.freeze(minutes=10)
    assert gf.ensure_status_item(world.state, bundle=tmp_path / "nope.app")[0] is False
    def boom(*a, **k):
        raise OSError("exec format error")
    assert gf.ensure_status_item(world.state, popen=boom, bundle=fake_bundle(tmp_path))[1].startswith("error")


def test_a_corrupt_frozen_file_reads_as_nothing_frozen_for_the_menu_bar(world):
    d = world.state / "gui-hog"
    d.mkdir(mode=0o700, exist_ok=True)
    (d / "frozen.json").write_text("{not json")
    assert gf.has_entries(world.state) is False


def test_the_sampler_starts_the_menu_bar_item_after_a_thaw_tick(monkeypatch, world, tmp_path):
    import argparse
    lw = load_module(monkeypatch, world.state)
    world.freeze(minutes=60)
    started = []
    monkeypatch.setattr(gf, "Ops", lambda *a, **k: world.ops)
    monkeypatch.setattr(gf, "ensure_status_item", lambda sd, **k: (started.append((sd, k)) or (True, "")))
    monkeypatch.setattr(lw, "now", lambda: T0 + 5)
    monkeypatch.setattr(lw, "ps_table", lambda: {"1": (0, 0, 0.1, "x")})
    assert lw.cmd_sample(argparse.Namespace(dry_run=False, verbose=False)) == 0
    assert len(started) == 1 and "menu-bar item started" in (lw.STATE_DIR / "sample.log").read_text()
    started.clear()
    lw.cmd_sample(argparse.Namespace(dry_run=True, verbose=False))   # a dry run never starts anything
    assert started == []


# ---- adversary round 1 (head 6b9aabc0): a frozen app must always be resumable ----------------------------------------------------------------
def test_a_bundle_replaced_while_frozen_is_still_resumed(world):
    """A1: an update or a move changes what the kernel reports as the executable path; SIGCONT needs pid, start, uid and state T only."""
    world.freeze(minutes=1)
    world.ops.procs[5000]["exe"] = ""          # the old vnode has no path any more
    world.ops.procs[5001]["exe"] = "/Users/x/.Trash/Fake.app/Contents/MacOS/Helper"   # a moved bundle: another path
    r = gf.thaw_due(world.state, ops=world.ops, now=T0 + 61)
    assert r["resumed"] == [world.events()[0]["entry"]] and world.entries() == []
    assert all(world.ops.procs[p]["state"] == "S" for p in (5000, 5001, 5002))
    assert {e["event"] for e in world.events()} >= {"exe-changed", "thaw"}


def test_thaw_all_resumes_a_replaced_bundle_and_never_a_reused_pid(world):
    e = world.freeze()
    world.ops.procs[5001]["exe"] = ""
    world.ops.procs[5002]["start"] = "a-different-start"   # pid reuse: another process, never signalled
    assert gf.thaw_all(world.state, ops=world.ops, now=T0 + 1) == ([e["id"]], [])
    assert world.ops.procs[5001]["state"] == "S" and world.ops.procs[5002]["state"] == "T" and 5002 not in [p for p, s in world.ops.sent if s == signal.SIGCONT]


def test_stopped_apps_lists_a_stopped_process_whose_path_is_unreadable(world):
    world.freeze()
    world.ops.procs[5001]["exe"] = ""
    pids = [r["pid"] for r in gf.stopped_apps(world.ops)]
    assert 5001 in pids and 5000 in pids


def test_a_killed_root_does_not_strand_its_stopped_helpers(world):
    """A2: the stopped root is SIGKILLed (a Force Quit reaches it); the next tick resumes the helpers before the entry is dropped."""
    world.freeze()                                   # indefinite: never due
    world.ops.procs[5000]["state"] = "gone"
    r = gf.thaw_due(world.state, ops=world.ops, now=T0 + 5)
    assert world.entries() == [] and r["resumed"] and world.ops.procs[5001]["state"] == "S" and world.ops.procs[5002]["state"] == "S"
    assert 5000 not in [p for p, s in world.ops.sent if s == signal.SIGCONT]


def test_a_reboot_or_exit_with_nothing_left_is_a_drop_not_a_resume(world):
    world.freeze(minutes=60)
    for p in (5000, 5001, 5002):
        world.ops.procs[p]["state"] = "gone"
    r = gf.thaw_due(world.state, ops=world.ops, now=T0 + 5)
    assert r["dropped"] and not r["resumed"] and world.entries() == []


def test_a_second_instance_of_the_same_app_is_never_frozen_with_the_first(world):
    """A3a: instance 1 (6000) hosts a terminal; freezing instance 2 (5000) must refuse rather than stop 6000 too."""
    world.ops.procs[6000] = proc(1, world.exe, pid=6000)
    with pytest.raises(gf.Refusal) as r:
        world.freeze(minutes=1)
    assert r.value.code == gf.HOSTS_BUILD and "another instance" in r.value.msg
    assert not world.ops.sent


def test_a_shell_under_a_launchd_started_helper_makes_the_app_host_a_build(world):
    """A3b: an in-bundle helper that launchd started (ppid 1) runs a shell: the app hosts a terminal, nothing is frozen."""
    world.ops.procs[8000] = proc(1, world.helper, pid=8000)
    world.ops.procs[8001] = proc(8000, "/bin/zsh", pid=8001)
    world.ops.procs[8001]["tty"] = True
    with pytest.raises(gf.Refusal) as r:
        world.freeze(minutes=1)
    assert r.value.code == gf.HOSTS_BUILD and not world.ops.sent


def test_a_full_disk_never_blocks_a_resume(world, monkeypatch):
    """A4: the state file cannot be written (ENOSPC); the identity-checked SIGCONTs still go out."""
    world.freeze(minutes=1)
    def full(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(gf, "save_entries", full)
    r = gf.thaw_due(world.state, ops=world.ops, now=T0 + 61)
    assert all(world.ops.procs[p]["state"] == "S" for p in (5000, 5001, 5002)) and r["resumed"]


def test_an_oserror_in_the_cli_is_exit_9_and_one_line_not_a_traceback(world, monkeypatch, capsys):
    import argparse
    monkeypatch.setattr(gf, "thaw_all", lambda *a, **k: (_ for _ in ()).throw(OSError(30, "Read-only file system")))
    a = argparse.Namespace(entry=None, all=True, by="cli", json=True)
    rc = gf._guard(gf.cmd_resume)(a, world.state)
    assert rc == gf.REFUSED and "Read-only" in capsys.readouterr().out


def test_a_sigterm_mid_freeze_rolls_back_what_it_stopped(world):
    """A6: the dialog gave up and sent SIGTERM; the handler raises, the freeze rolls back, nothing stays stopped."""
    def term_after_root(pid, sig):
        if pid == 5001 and sig == signal.SIGSTOP:
            raise gf.Terminated("terminated")
    world.ops.on_kill = term_after_root
    with pytest.raises(gf.Refusal):
        world.freeze(minutes=1)
    world.ops.on_kill = None
    assert all(world.ops.procs[p]["state"] != "T" for p in (5000, 5001, 5002)) and world.entries() == []


def test_a_frozen_at_in_the_future_is_due_now(world):
    """A8: a wrong clock or a hand edit puts frozen_at (and so thaw_at) far away; the safe direction is to resume."""
    world.freeze(minutes=1)
    d = world.state / "gui-hog" / "frozen.json"
    obj = json.loads(d.read_text())
    obj["entries"][0]["frozen_at"] = T0 + 4_000_000_000
    obj["entries"][0]["thaw_at"] = T0 + 4_000_000_060
    d.write_text(json.dumps(obj))
    assert gf.thaw_due(world.state, ops=world.ops, now=T0 + 5)["resumed"] and world.ops.procs[5000]["state"] == "S"


def test_an_entry_id_cannot_look_like_an_option():
    assert not gf.ID_RE.match("--all") and not gf.ID_RE.match("-h") and gf.ID_RE.match("f-20261114T000000Z-ab12")


# ---- adversary round 2 (head 4ce980ca), low findings -----------------------------------------------------------------------------------------
def test_a_shell_child_listed_before_its_launchd_started_helper_still_blocks_the_freeze(world):
    """B1: ps order must not decide it: the child (a shell inside the bundle) comes first in the table, its helper second."""
    shell = world.app / "Contents" / "MacOS" / "zsh"
    world.ops.procs[7999] = proc(8000, shell, pid=7999)   # the child is listed (and seen) first
    world.ops.procs[8000] = proc(1, world.helper, pid=8000)
    with pytest.raises(gf.Refusal) as r:
        world.freeze(minutes=1)
    assert r.value.code == gf.HOSTS_BUILD and not world.ops.sent


def test_the_frozen_view_keeps_a_replaced_bundle_alive_not_gone(world):
    world.freeze()
    world.ops.procs[5000]["exe"] = ""
    v = gf.frozen_view(world.state, ops=world.ops, now=T0 + 1)
    assert v["entries"][0]["alive"] is True


def test_a_killed_ps_is_an_error_not_an_empty_answer(monkeypatch):
    class R:
        returncode = -9
        stdout = ""
    monkeypatch.setattr(gf.subprocess, "run", lambda *a, **k: R())
    monkeypatch.setattr(gf.os.path, "isdir", lambda p: False)
    with pytest.raises(OSError):
        gf.Ops(my_uid=ME).info([4242])


def test_stopped_apps_resume_counts_a_replaced_bundle(world):
    world.freeze()
    world.ops.procs[5001]["exe"] = ""
    recs = gf.stopped_apps(world.ops)
    assert 5001 in gf.thaw_stopped_apps(world.ops, recs)
