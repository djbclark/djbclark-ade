"""bin/paseo-bypass-watch against a stub `paseo` (PASEO_CLI): no daemon, no agents, no ~/.paseo."""
from __future__ import annotations

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

# The stub speaks the three calls the watcher makes, over a JSON fixture (FIXTURE env), logging every
# call to CALLS: `agent ls --json`, `agent inspect ID --json`, `agent mode ID MODE`.
STUB = textwrap.dedent(
    """\
    #!{python}
    import json, os, sys
    fx_path, calls = os.environ["FIXTURE"], os.environ["CALLS"]
    with open(calls, "a") as f:
        f.write(" ".join(sys.argv[1:]) + "\\n")
    fx = json.load(open(fx_path))
    a = sys.argv[1:]
    if fx.get("ls_fails") and a[:2] == ["agent", "ls"]:
        print("daemon not running", file=sys.stderr); sys.exit(1)
    if a[:3] == ["agent", "ls", "--json"]:
        print(json.dumps([{{"id": i, "shortId": i[:7], "name": v["name"], "provider": v["ls_provider"],
                          "status": v.get("status", "idle"), "created": "just now"}}
                         for i, v in fx["agents"].items()]))
    elif a[:2] == ["agent", "inspect"] and a[3:] == ["--json"]:
        v = fx["agents"][a[2]]
        out = {{"Id": a[2], "Name": v["name"], "Provider": v["ls_provider"].split("/")[0], "Status": v.get("status", "idle"),
               "Archived": v.get("archived", False), "Mode": v["mode"], "CreatedAt": v["created_at"]}}
        if "labels" in v:
            out["Labels"] = v["labels"]
        print(json.dumps(out))
    elif a[:2] == ["agent", "mode"] and len(a) == 4:
        if a[2] in fx.get("fail_mode", []):
            print("mode refused", file=sys.stderr); sys.exit(1)
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


def test_perm_ask_label_keeps_the_agent_in_its_mode(w: World):
    w.set_agents({"aaa-1": agent("asker", labels={"perm": "ask"})})
    assert w.run().returncode == 0
    assert w.mode_calls() == []
    assert w.mode_of("aaa-1") == "default"
    assert w.handled()["aaa-1"]["result"] == "recorded"


def test_perm_ask_label_as_list_of_pairs(w: World):
    w.set_agents({"aaa-1": agent("asker", labels=["team=x", "perm=ask"])})
    assert w.run().returncode == 0
    assert w.mode_calls() == []


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
    p = subprocess.Popen(w.argv("--loop", "0.2"), env=w.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 30
        while time.time() < deadline and not (w.mode_calls() and w.calls.read_text().count("agent ls") >= 2):
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
    p = subprocess.Popen(w.argv("--loop", "0.2"), env=w.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.time() + 30
        while time.time() < deadline and w.calls.read_text().count("agent ls") < 3:
            assert p.poll() is None, p.stderr.read()
            time.sleep(0.1)
        assert p.poll() is None
        p.send_signal(signal.SIGTERM)
        assert p.wait(timeout=30) == 0
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
