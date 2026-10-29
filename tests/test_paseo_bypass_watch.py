"""bin/paseo-bypass-watch against a stub `paseo` (PASEO_CLI): no daemon, no agents, no ~/.paseo."""
from __future__ import annotations

import fcntl
import importlib.machinery
import importlib.util
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "paseo-bypass-watch"

# The stub speaks the calls the watcher makes, over a JSON fixture (FIXTURE env), logging every call to
# CALLS, and prints exactly the keys the real Paseo CLI prints (read from its source, 2026-10-29):
#   `agent ls [--label K=V]... --json` rows: created, cwd, id, name, provider, shortId, status, thinking
#   `agent inspect ID --json`: Id, Name, Provider, Model, Thinking, Status, Archived, ArchivedAt, Mode, Cwd,
#       CreatedAt, UpdatedAt, LastUsage, Capabilities, AvailableModes, PendingPermissions, Worktree, ParentAgentId
# Neither prints labels. The fixture's top-level "labels" table ({id: {k: v}}) lives outside every printed
# output and is reachable only through the `--label` filter. `agent mode ID MODE` sets the mode.
# Fixture switches: ls_fails, label_ls ("fail" | "garbage"), fail_mode [ids], noop_mode [ids] (exit 0, no change).
STUB = textwrap.dedent(
    """\
    #!{python}
    import json, os, sys
    fx_path, calls = os.environ["FIXTURE"], os.environ["CALLS"]
    with open(calls, "a") as f:
        f.write(" ".join(sys.argv[1:]) + "\\n")
    fx = json.load(open(fx_path))
    a = sys.argv[1:]
    if a[:2] == ["agent", "ls"] and a[-1:] == ["--json"]:
        wanted = [tuple(a[i + 1].split("=", 1)) for i, x in enumerate(a) if x == "--label"]
        if fx.get("ls_fails") or (wanted and fx.get("label_ls") == "fail"):
            print("daemon not running", file=sys.stderr); sys.exit(1)
        if wanted and fx.get("label_ls") == "garbage":
            print("not json at all"); sys.exit(0)
        table = fx.get("labels", {{}})
        print(json.dumps([{{"created": "just now", "cwd": "/w", "id": i, "name": v["name"], "provider": v["ls_provider"],
                          "shortId": i[:7], "status": v.get("status", "idle"), "thinking": "default"}}
                         for i, v in fx["agents"].items()
                         if all(table.get(i, {{}}).get(k) == val for k, val in wanted)]))
    elif a[:2] == ["agent", "inspect"] and a[3:] == ["--json"]:
        v = fx["agents"][a[2]]
        print(json.dumps({{"Id": a[2], "Name": v["name"], "Provider": v["ls_provider"].split("/")[0],
                          "Model": v["ls_provider"].split("/", 1)[-1], "Thinking": "default",
                          "Status": v.get("status", "idle"), "Archived": v.get("archived", False), "ArchivedAt": None,
                          "Mode": v["mode"], "Cwd": "/w", "CreatedAt": v["created_at"], "UpdatedAt": v["created_at"],
                          "LastUsage": None, "Capabilities": {{}}, "AvailableModes": [], "PendingPermissions": [],
                          "Worktree": None, "ParentAgentId": None}}))
    elif a[:2] == ["agent", "mode"] and len(a) == 4:
        if a[2] in fx.get("fail_mode", []):
            print("mode refused", file=sys.stderr); sys.exit(1)
        if a[2] not in fx.get("noop_mode", []):
            fx["agents"][a[2]]["mode"] = a[3]
            json.dump(fx, open(fx_path, "w"))
    else:
        print("stub: unexpected call " + " ".join(a), file=sys.stderr); sys.exit(9)
    """
)


def iso(seconds_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat(timespec="milliseconds")


def agent(name: str, *, provider: str = "claude/claude-sonnet-5-5", mode: str = "default", age: float = 10, **extra) -> dict:
    return {"name": name, "ls_provider": provider, "mode": mode, "created_at": iso(age), **extra}


class World:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.fixture = tmp / "fixture.json"
        self.calls = tmp / "calls.log"
        self.state = tmp / "state" / "w.json"
        self.stub = tmp / "paseo"
        self.stub.write_text(STUB.format(python=sys.executable))
        self.stub.chmod(0o755)
        self.calls.write_text("")
        self.env = {**os.environ, "PASEO_CLI": str(self.stub), "FIXTURE": str(self.fixture), "CALLS": str(self.calls),
                    "HOME": str(tmp / "home")}

    def set_agents(self, agents: dict, **extra) -> None:
        self.fixture.write_text(json.dumps({"agents": agents, **extra}))

    def argv(self, *flags: str) -> list[str]:
        return [sys.executable, "-I", str(SCRIPT), "--state", str(self.state), *flags]

    def run(self, *flags: str) -> subprocess.CompletedProcess:
        return subprocess.run(self.argv(*flags), env=self.env, capture_output=True, text=True, timeout=60)

    def mode_calls(self) -> list[str]:
        return [ln for ln in self.calls.read_text().splitlines() if ln.startswith("agent mode ")]

    def mode_of(self, agent_id: str) -> str:
        return json.loads(self.fixture.read_text())["agents"][agent_id]["mode"]

    def handled(self) -> dict:
        return json.loads(self.state.read_text())["handled"]


@pytest.fixture()
def w(tmp_path: Path) -> World:
    return World(tmp_path)


def test_new_claude_agent_in_default_mode_is_set_once(w: World):
    w.set_agents({"aaa-1": agent("seat one")})
    r = w.run()
    assert r.returncode == 0, r.stderr
    assert w.mode_calls() == ["agent mode aaa-1 bypassPermissions"]
    assert w.mode_of("aaa-1") == "bypassPermissions"
    assert "set aaa-1 seat one" in r.stdout
    assert w.handled()["aaa-1"]["result"] == "set"
    w.run()
    assert len(w.mode_calls()) == 1


def test_already_bypass_agent_is_untouched_but_recorded(w: World):
    w.set_agents({"aaa-1": agent("yolo", mode="bypassPermissions")})
    assert w.run().returncode == 0
    assert w.mode_calls() == []
    assert w.handled()["aaa-1"]["result"] == "recorded"


def test_closed_agent_is_untouched(w: World):
    w.set_agents({"aaa-1": agent("closed seat", status="closed")})
    assert w.run().returncode == 0
    assert w.mode_calls() == []
    assert w.mode_of("aaa-1") == "default"
    assert w.handled()["aaa-1"]["result"] == "recorded"


def test_non_claude_agents_are_never_touched(w: World):
    w.set_agents({
        "omp-1": agent("omp seat", provider="omp/anthropic/claude-sonnet-5-5"),
        "cline-1": agent("cline seat", provider="cline/cline-pass/deepseek-v4.1-flash"),
    })
    assert w.run().returncode == 0
    assert w.mode_calls() == []
    assert not w.state.exists() or w.handled() == {}


def test_perm_ask_agent_found_by_the_label_filter_keeps_its_mode(w: World):
    # The CLI prints no labels: the only way to know is `agent ls --label perm=ask`.
    w.set_agents({"aaa-1": agent("asker"), "bbb-2": agent("other")},
                 labels={"aaa-1": {"perm": "ask"}, "bbb-2": {"team": "x"}})
    assert w.run().returncode == 0
    assert w.mode_calls() == ["agent mode bbb-2 bypassPermissions"]
    assert w.mode_of("aaa-1") == "default"
    assert w.handled()["aaa-1"]["result"] == "recorded"
    assert not any(ln.startswith("agent inspect aaa-1") for ln in w.calls.read_text().splitlines())
    assert "agent ls --label perm=ask --json" in w.calls.read_text().splitlines()


def test_the_stub_prints_no_labels(w: World):
    # Guards the fixture itself: if the stub leaked labels the exemption tests would prove nothing.
    w.set_agents({"aaa-1": agent("seat")}, labels={"aaa-1": {"perm": "ask"}})
    for argv in (["agent", "ls", "--json"], ["agent", "inspect", "aaa-1", "--json"]):
        out = subprocess.run([str(w.stub), *argv], env=w.env, capture_output=True, text=True, check=True).stdout
        assert "label" not in out.lower() and "perm" not in out


@pytest.mark.parametrize("failure", ["fail", "garbage"])
def test_failing_label_filter_aborts_the_pass_without_touching_anything(w: World, failure: str):
    w.set_agents({"aaa-1": agent("asker")}, labels={"aaa-1": {"perm": "ask"}}, label_ls=failure)
    r = w.run()
    assert r.returncode == 1, r.stderr
    assert w.mode_calls() == []
    assert not any(ln.startswith("agent inspect") for ln in w.calls.read_text().splitlines())
    assert w.mode_of("aaa-1") == "default"
    assert not w.state.exists() or "aaa-1" not in w.handled()


def test_loop_with_a_failing_label_filter_never_touches_and_keeps_going(w: World):
    w.set_agents({"aaa-1": agent("asker")}, label_ls="fail")
    p = subprocess.Popen(w.argv("--loop", "1"), env=w.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 30
        while time.time() < deadline and w.calls.read_text().count("agent ls --label") < 2:
            assert p.poll() is None, p.stderr.read()
            time.sleep(0.1)
        assert w.calls.read_text().count("agent ls --label") >= 2
        assert p.poll() is None
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=30) == 0
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
    assert w.mode_calls() == []


@pytest.mark.parametrize("mode", ["plan", "acceptEdits", "auto", "someFutureMode"])
def test_only_default_mode_is_acted_on(w: World, mode: str):
    w.set_agents({"aaa-1": agent("deliberate", mode=mode)})
    assert w.run().returncode == 0
    assert w.mode_calls() == []
    assert w.mode_of("aaa-1") == mode
    assert w.handled()["aaa-1"]["result"] == "recorded"


def test_a_later_plan_sticks_even_after_a_failed_set(w: World):
    w.set_agents({"aaa-1": agent("slow")}, fail_mode=["aaa-1"])
    assert w.run().returncode == 0
    assert len(w.mode_calls()) == 1  # attempt 1 failed, the agent is queued for a retry
    data = json.loads(w.fixture.read_text())
    data["agents"]["aaa-1"]["mode"] = "plan"  # the operator's choice between two passes
    data["fail_mode"] = []
    w.fixture.write_text(json.dumps(data))
    assert w.run().returncode == 0
    assert len(w.mode_calls()) == 1  # the retry re-checked the mode and left plan alone
    assert w.mode_of("aaa-1") == "plan"
    assert w.handled()["aaa-1"]["result"] == "recorded"


def test_a_set_that_exits_0_but_leaves_the_mode_is_not_recorded_as_set(w: World):
    w.set_agents({"aaa-1": agent("liar")}, noop_mode=["aaa-1"])
    r = w.run("--json")
    assert r.returncode == 0
    report = json.loads(r.stdout.splitlines()[-1])
    assert report["set"] == []
    assert "set aaa-1 liar" not in r.stdout
    assert "attempt 1/5" in r.stderr
    assert "aaa-1" not in w.handled()
    assert json.loads(w.state.read_text())["attempts"] == {"aaa-1": 1}


def test_a_busy_lock_means_the_pass_does_nothing(w: World):
    w.set_agents({"aaa-1": agent("seat")})
    w.state.parent.mkdir(parents=True)
    with open(w.state.with_name(w.state.name + ".lock"), "w") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)  # another pass is running
        r = w.run()
        assert r.returncode == 0, r.stderr
        assert "lock" in r.stderr
        assert w.calls.read_text() == ""  # not even an `agent ls`
        assert not w.state.exists()
    assert w.run().returncode == 0  # holder gone: the pass runs
    assert w.mode_calls() == ["agent mode aaa-1 bypassPermissions"]


def test_loop_skips_a_pass_while_the_lock_is_busy(w: World):
    w.set_agents({"aaa-1": agent("seat")})
    w.state.parent.mkdir(parents=True)
    with open(w.state.with_name(w.state.name + ".lock"), "w") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        p = subprocess.Popen(w.argv("--loop", "1"), env=w.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            time.sleep(2.5)
            assert p.poll() is None
            assert w.calls.read_text() == ""
        finally:
            p.send_signal(signal.SIGTERM)
            p.wait(timeout=30)
    assert w.mode_calls() == []


# A seat created right after the `--label` query answered (adversary round 2, A1). The wrapper makes
# that happen inside the stub's own call sequence.
RACE_WRAP = textwrap.dedent(
    """\
    #!{python}
    import json, os, subprocess, sys
    r = subprocess.run([{inner!r}, *sys.argv[1:]])
    if "--label" in sys.argv:  # the seat is created right after the exempt query answered
        p = os.environ["FIXTURE"]
        fx = json.load(open(p))
        for i, v in fx.pop("pending", {{}}).items():
            fx["agents"][i] = v["agent"]
            fx.setdefault("labels", {{}})[i] = v["labels"]
        json.dump(fx, open(p, "w"))
    sys.exit(r.returncode)
    """
)


def test_perm_ask_seat_created_right_after_the_label_query_keeps_its_mode(w: World):
    # The agent list must be read BEFORE the exemption list: a seat that appears after the label query
    # answered is then simply not in this pass's list. Swapped, it would be listed but missing from the
    # exemption set, inspected as a young `default` seat and flipped.
    inner = w.tmp / "paseo-inner"
    w.stub.rename(inner)
    w.stub.write_text(RACE_WRAP.format(python=sys.executable, inner=str(inner)))
    w.stub.chmod(0o755)
    w.set_agents({}, pending={"ask-1": {"agent": agent("careful seat"), "labels": {"perm": "ask"}}})
    r = w.run()
    assert r.returncode == 0, r.stderr
    assert w.mode_of("ask-1") == "default", "perm=ask seat was flipped to bypassPermissions"
    assert w.mode_calls() == []
    r = w.run()  # next pass: the seat is listed and now exempt
    assert r.returncode == 0, r.stderr
    assert w.mode_of("ask-1") == "default"
    assert w.mode_calls() == []
    assert w.handled()["ask-1"]["result"] == "recorded"


def test_loop_reads_the_exemption_on_every_pass(w: World):
    # A perm=ask default seat appears between pass 1 and pass 2; a control seat beside it proves pass 2
    # acts. An exemption cached for the process lifetime would flip the perm=ask seat.
    w.set_agents({})
    p = subprocess.Popen(w.argv("--loop", "1"), env=w.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 30
        while time.time() < deadline and w.calls.read_text().count("--label perm=ask") < 1:
            assert p.poll() is None, p.stderr.read()
            time.sleep(0.05)
        assert w.calls.read_text().count("--label perm=ask") >= 1, "pass 1 never ran"
        time.sleep(0.3)  # pass 1 is over (nothing to inspect); pass 2 starts about 1 s after it began
        tmp = w.tmp / "fixture.tmp"
        tmp.write_text(json.dumps({
            "agents": {"ask-1": agent("careful seat"), "ctl-1": agent("control seat")},
            "labels": {"ask-1": {"perm": "ask"}},
        }))
        os.replace(tmp, w.fixture)
        deadline = time.time() + 30
        while time.time() < deadline and not w.mode_calls():
            assert p.poll() is None, p.stderr.read()
            time.sleep(0.05)
        time.sleep(0.5)
        assert p.poll() is None
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=30) == 0
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
    assert w.mode_calls() == ["agent mode ctl-1 bypassPermissions"]
    assert w.mode_of("ask-1") == "default"


def test_state_is_loaded_while_the_lock_is_held(tmp_path: Path, monkeypatch):
    # Loading before locking lets two passes read the same state and lose one's records.
    loader = importlib.machinery.SourceFileLoader("paseo_bypass_watch_lock_under_test", str(SCRIPT))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    state_path = tmp_path / "s" / "state.json"
    lock_path = state_path.with_name(state_path.name + ".lock")
    seen: list[bool] = []
    real_load = mod.load_state

    def load_checking_the_lock(path):
        lock_path.parent.mkdir(parents=True, exist_ok=True)  # load-before-lock gets here with no directory yet
        probe = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                seen.append(False)  # we got it: the pass was not holding it
            except BlockingIOError:
                seen.append(True)
        finally:
            os.close(probe)
        return real_load(path)

    monkeypatch.setattr(mod, "load_state", load_checking_the_lock)
    monkeypatch.setattr(mod, "one_pass", lambda state, max_age, dry_run: {"set": []})
    assert mod.run_pass(state_path, 120.0, False, False) is True
    assert seen == [True]
    probe = os.open(lock_path, os.O_RDWR)
    try:
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)  # released after the pass
    finally:
        os.close(probe)


def test_archived_agent_is_untouched(w: World):
    w.set_agents({"aaa-1": agent("gone", archived=True)})
    assert w.run().returncode == 0
    assert w.mode_calls() == []


def test_agent_older_than_max_age_is_only_recorded(w: World):
    w.set_agents({"old-1": agent("old seat", age=500)})
    assert w.run().returncode == 0
    assert w.mode_calls() == []
    assert w.mode_of("old-1") == "default"
    assert w.handled()["old-1"]["result"] == "recorded"
    assert w.run("--max-age", "1000").returncode == 0  # recorded stays recorded, even with a wider window
    assert w.mode_calls() == []


def test_max_age_flag_widens_the_window(w: World):
    w.set_agents({"old-1": agent("old seat", age=500)})
    assert w.run("--max-age", "1000").returncode == 0
    assert w.mode_calls() == ["agent mode old-1 bypassPermissions"]


def test_handled_agent_is_never_touched_again_even_if_mode_changes(w: World):
    w.set_agents({"aaa-1": agent("seat")})
    assert w.run().returncode == 0
    data = json.loads(w.fixture.read_text())
    data["agents"]["aaa-1"]["mode"] = "plan"  # the operator's own later choice
    w.fixture.write_text(json.dumps(data))
    assert w.run().returncode == 0
    assert w.mode_of("aaa-1") == "plan"
    assert len(w.mode_calls()) == 1


def test_failed_set_is_retried_and_capped_at_five(w: World):
    w.set_agents({"aaa-1": agent("stubborn")}, fail_mode=["aaa-1"])
    for n in range(1, 4):
        r = w.run()
        assert r.returncode == 0
        assert len(w.mode_calls()) == n  # still retrying: a failure is not recorded
        assert "aaa-1" not in w.handled()
    for _ in range(5):
        assert w.run().returncode == 0
    assert len(w.mode_calls()) == 5
    assert w.handled()["aaa-1"]["result"] == "failed"


def test_retry_continues_after_the_agent_ages_past_max_age(w: World):
    # The set decision was taken while the agent was young; a transient failure must not silently drop it.
    w.set_agents({"aaa-1": agent("slow", age=100)}, fail_mode=["aaa-1"])
    assert w.run("--max-age", "120").returncode == 0
    data = json.loads(w.fixture.read_text())
    data["agents"]["aaa-1"]["created_at"] = iso(900)
    data["fail_mode"] = []
    w.fixture.write_text(json.dumps(data))
    assert w.run("--max-age", "120").returncode == 0
    assert w.mode_of("aaa-1") == "bypassPermissions"


def test_dry_run_sets_nothing_and_writes_no_state(w: World):
    w.set_agents({"aaa-1": agent("seat")})
    r = w.run("--dry-run")
    assert r.returncode == 0
    assert "would set aaa-1 seat" in r.stdout
    assert w.mode_calls() == []
    assert w.mode_of("aaa-1") == "default"
    assert not w.state.exists()
    assert not w.state.parent.exists()


def test_json_report_lists_what_was_done(w: World):
    w.set_agents({"aaa-1": agent("seat"), "old-1": agent("old", age=900)})
    r = w.run("--json")
    assert r.returncode == 0
    report = json.loads(r.stdout.splitlines()[-1])
    assert report["set"] == ["aaa-1"]
    assert report["recorded"] == ["old-1"]


def test_once_exits_1_when_the_daemon_is_down(w: World):
    w.set_agents({}, ls_fails=True)
    r = w.run("--once")
    assert r.returncode == 1
    assert "exited 1" in r.stderr


def test_once_with_nothing_to_do_exits_0(w: World):
    w.set_agents({})
    assert w.run().returncode == 0
    assert w.mode_calls() == []


def test_loop_sets_new_agent_and_sigterm_ends_it_with_0(w: World):
    w.set_agents({"aaa-1": agent("seat")})
    p = subprocess.Popen(w.argv("--loop", "1"), env=w.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 30
        while time.time() < deadline and not (w.mode_calls() and w.calls.read_text().count("agent ls --json") >= 2):
            assert p.poll() is None, p.stderr.read()
            time.sleep(0.1)
        assert w.mode_calls() == ["agent mode aaa-1 bypassPermissions"]
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=30) == 0
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
    assert len(w.mode_calls()) == 1


def test_loop_survives_a_failing_pass(w: World):
    w.set_agents({}, ls_fails=True)
    p = subprocess.Popen(w.argv("--loop", "1"), env=w.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 30
        while time.time() < deadline and w.calls.read_text().count("agent ls") < 2:
            assert p.poll() is None, p.stderr.read()
            time.sleep(0.1)
        assert p.poll() is None
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=30) == 0
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()


def test_loop_survives_an_interval_the_platform_cannot_wait_for(w: World):
    # Event.wait(1e300) raises OverflowError; a ValueError/OverflowError from the wait must not end the loop.
    w.set_agents({})
    p = subprocess.Popen(w.argv("--loop", "1e300"), env=w.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 30
        while time.time() < deadline and w.calls.read_text().count("agent ls --json") < 2:
            assert p.poll() is None, p.stderr.read()
            time.sleep(0.1)
        assert w.calls.read_text().count("agent ls --json") >= 2
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=30) == 0
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()


@pytest.mark.parametrize("flags", [
    ["--max-age", "nan"], ["--max-age", "inf"], ["--max-age", "-inf"], ["--max-age", "0"], ["--max-age", "-5"],
    ["--loop", "nan"], ["--loop", "inf"], ["--loop", "0"], ["--loop", "0.5"], ["--loop", "-3"], ["--loop"],
])
def test_bad_numeric_arguments_are_usage_errors(w: World, flags: list[str]):
    w.set_agents({"aaa-1": agent("seat")})
    r = w.run(*flags)
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert w.calls.read_text() == ""


@pytest.mark.parametrize("flags", [["--max-age", "0.5"], ["--max-age", "1e6"]])
def test_small_and_large_finite_max_age_are_accepted(w: World, flags: list[str]):
    w.set_agents({})
    assert w.run(*flags).returncode == 0


@pytest.mark.parametrize("body", [
    {"version": 1, "handled": [], "attempts": {}},
    {"version": 1, "handled": {}, "attempts": []},
    {"version": 1, "handled": None, "attempts": {}},
    {"version": 1, "handled": {"aaa-1": "set"}, "attempts": {}},
    {"version": 1, "handled": {}, "attempts": {"aaa-1": "two"}},
    [],
])
def test_state_of_the_wrong_type_is_reported_not_a_traceback(w: World, body):
    w.set_agents({"aaa-1": agent("seat")})
    w.state.parent.mkdir(parents=True)
    w.state.write_text(json.dumps(body))
    r = w.run()
    assert r.returncode == 1
    assert "unexpected shape" in r.stderr
    assert "Traceback" not in r.stderr
    assert w.mode_calls() == []


def test_state_is_fsynced_before_it_replaces_the_old_file(tmp_path: Path, monkeypatch):
    loader = importlib.machinery.SourceFileLoader("paseo_bypass_watch_under_test", str(SCRIPT))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    events: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(os, "fsync", lambda fd: (events.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(os, "replace", lambda a, b: (events.append("replace"), real_replace(a, b))[1])
    target = tmp_path / "s" / "state.json"
    mod.save_state(target, {"version": 1, "handled": {}, "attempts": {}})
    assert events == ["fsync", "replace"]
    assert json.loads(target.read_text())["version"] == 1
