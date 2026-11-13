"""Tests for bin/ade-progress (slice 1 of docs/persistent-progress-reminder-design.md). Hermetic: temp state dir, fake clock
(ADE_PROGRESS_NOW), and fake `paseo`, `hermes-ping` and `paseo-progress` executables that log every call. No network, no model."""
from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import textwrap
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "ade-progress"
T0 = 1_800_000_000
HOUR = 3600

FAKE_PASEO = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, sys, time
    d = os.environ["FAKE_DIR"]
    with open(d + "/calls.jsonl", "a") as f:
        f.write(json.dumps(sys.argv[1:]) + "\\n")
    if os.environ.get("FAKE_SLEEP"):
        time.sleep(float(os.environ["FAKE_SLEEP"]))
    cmd = sys.argv[1]
    if cmd == "ls":
        if os.path.exists(d + "/ls_fail"):
            sys.exit(1)
        print(open(d + "/ls.json").read())
    elif cmd == "inspect":
        p = d + "/inspect-" + sys.argv[2] + ".json"
        if not os.path.exists(p):
            sys.exit(1)
        seq = json.load(open(p))
        cur = seq[0]
        if len(seq) > 1:
            json.dump(seq[1:], open(p, "w"))
        print(json.dumps(cur))
    elif cmd == "send":
        out = open(d + "/send.json").read() if os.path.exists(d + "/send.json") else '{"status": "sent"}'
        print(out)
        if os.path.exists(d + "/send.err"):
            sys.stderr.write(open(d + "/send.err").read())
        sys.exit(int(open(d + "/send.rc").read()) if os.path.exists(d + "/send.rc") else 0)
''')
FAKE_PING = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, sys
    d = os.environ["FAKE_DIR"]
    with open(d + "/pings.jsonl", "a") as f:
        f.write(json.dumps(sys.argv[1:]) + "\\n")
    sys.exit(int(open(d + "/ping.rc").read()) if os.path.exists(d + "/ping.rc") else 0)
''')
FAKE_PP = textwrap.dedent('''\
    #!/usr/bin/env python3
    # Stateful fake of paseo-progress 1.14.6: ids restart per run (`start`), `show` lists `Title (S1: reason), since now`.
    import json, os, sys
    d = os.environ["FAKE_DIR"]
    a = sys.argv[1:]
    with open(d + "/pp.jsonl", "a") as f:
        f.write(json.dumps([os.getcwd()] + a) + "\\n")
    if os.path.exists(d + "/pp.norun"):
        print("The run is finished"); sys.exit(1)
    sp = d + "/pp.state.json"
    st = json.load(open(sp)) if os.path.exists(sp) else {"n": 0, "items": {}}
    def save():
        json.dump(st, open(sp, "w"))
    if a[:2] == ["stuck", "set"]:
        st["n"] += 1; i = "S%d" % st["n"]; st["items"][i] = a[2]; save()
        print("something else %d" % st["n"] if os.path.exists(d + "/pp.weird") else "Flagged %s: %s" % (i, a[2]))
    elif a[:2] == ["stuck", "clear"]:
        if a[2] not in st["items"]:
            print("No flagged blocker " + a[2]); sys.exit(1)
        del st["items"][a[2]]; save(); print("Cleared " + a[2])
    elif a[0] == "show":
        if os.path.exists(d + "/pp.fmt"):
            for i, r in st["items"].items():
                print("  Blocked [%s] %s" % (i, r))   # a drifted show format
        elif not os.path.exists(d + "/pp.noshow"):
            for i, r in st["items"].items():
                print("  Blocked (%s: %s), since now" % (i, r))
    elif a[0] == "start":
        st = {"n": 0, "items": {}}; save()
''')


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Env:
    def __init__(self, tmp: Path):
        self.tmp, self.fake, self.state = tmp, tmp / "fake", tmp / "state"
        self.fake.mkdir()
        for name, body in (("paseo", FAKE_PASEO), ("hermes-ping", FAKE_PING), ("paseo-progress", FAKE_PP)):
            (self.fake / name).write_text(body)
            (self.fake / name).chmod(0o755)
        self.clock = T0
        self.ws = tmp / "ws"
        self.ws.mkdir()
        self.agents: dict[str, list[dict]] = {}
        self.set_ls()

    def env(self, **extra) -> dict:
        e = {k: v for k, v in os.environ.items() if not k.startswith(("PASEO_", "ADE_PROGRESS"))}
        e.update(FAKE_DIR=str(self.fake), ADE_PROGRESS_STATE=str(self.state), ADE_PROGRESS_NOW=str(self.clock),
                 ADE_PROGRESS_PASEO=str(self.fake / "paseo"), ADE_PROGRESS_HERMES_PING=str(self.fake / "hermes-ping"),
                 ADE_PROGRESS_PASEO_PROGRESS=str(self.fake / "paseo-progress"), PASEO_HOME=str(self.tmp / "home"),
                 PASEO_AGENT_ID="caller-agent")
        e.update(extra)
        return e

    def run(self, *args: str, **extra) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=60,
                              env=self.env(**extra))

    def agent(self, aid: str, status="idle", idle_min=60, archived=False, perms=None, then=None):
        """Seed one agent. `then` = later inspect payloads (consumed one per call)."""
        base = {"Status": status, "Archived": archived, "PendingPermissions": perms or [],
                "UpdatedAt": iso(self.clock - idle_min * 60)}
        self.agents[aid] = [base] + (then or [])
        (self.fake / f"inspect-{aid}.json").write_text(json.dumps(self.agents[aid]))
        self.set_ls()

    def set_ls(self):
        rows = [{"id": a, "status": s[0]["Status"]} for a, s in self.agents.items()]
        (self.fake / "ls.json").write_text(json.dumps(rows))

    def declare(self, task="t1", agent="a1", pending=1, state="open", idle_after=30, review_after=None, summary="finish W4"):
        args = ["declare", "--task", task, "--agent", agent, "--summary", summary, "--pending", str(pending),
                "--state", state, "--idle-after-min", str(idle_after), "--workspace", str(self.ws), "--yes"]
        if review_after:
            args += ["--review-after", review_after]
        r = self.run(*args)
        assert r.returncode == 0, r.stderr
        return r

    def scan(self, *flags) -> dict:
        r = self.run("scan", "--yes", "--json", *flags)
        assert r.returncode == 0, r.stderr + r.stdout
        return json.loads(r.stdout)

    def calls(self, name="calls.jsonl") -> list[list[str]]:
        p = self.fake / name
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def sends(self) -> list[list[str]]:
        return [c for c in self.calls() if c[0] == "send"]

    def pings(self) -> list[list[str]]:
        return self.calls("pings.jsonl")

    def inbox(self) -> list[dict]:
        return json.loads(self.run("inbox", "--json").stdout)


@pytest.fixture
def e(tmp_path):
    return Env(tmp_path)


def test_cold_dry_run_writes_nothing(e):
    e.agent("a1")
    r = e.run("scan", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert not e.state.exists()
    assert e.sends() == [] and e.pings() == []


def test_declare_defaults_to_dry_run_and_generations(e):
    r = e.run("declare", "--task", "t1", "--agent", "a1", "--summary", "x")
    assert "would declare" in r.stdout and not e.state.exists()
    e.declare()
    assert (e.state / "decl" / "t1.json").exists()
    mode = oct((e.state / "decl" / "t1.json").stat().st_mode & 0o777)
    assert mode == "0o600" and oct(e.state.stat().st_mode & 0o777) == "0o700"
    stale = e.run("declare", "--task", "t1", "--agent", "a1", "--summary", "y", "--generation", "5", "--yes")
    assert stale.returncode == 4 and "stale generation" in stale.stderr
    ok = e.run("declare", "--task", "t1", "--agent", "a1", "--summary", "y", "--generation", "1", "--yes")
    assert ok.returncode == 0 and "generation 2" in ok.stdout
    noop = e.run("retire", "--task", "t1", "--generation", "1", "--yes")
    assert noop.returncode == 4
    assert e.run("retire", "--task", "t1", "--generation", "2", "--yes").returncode == 0
    assert e.scan()["events"] == []


def test_idle_with_work_wakes_pages_and_is_quiet_after(e):
    e.agent("a1")
    e.declare()
    rep = e.scan()
    assert [(x["reason"], x["wake"], x["ui"]) for x in rep["events"]] == [("idle_with_work", "sent", "verified")]
    assert len(e.sends()) == 1
    s = e.sends()[0]
    assert s[:4] == ["send", "--json", "--no-wait", "a1"] and "--behavior" not in s and "t1" in s[-1]
    assert e.pings() == [["djbclark-ade: progress: 1 notice(s): t1 idle_with_work; run ade-progress inbox"]]
    assert e.calls("pp.jsonl")[0][0] == str(e.ws.resolve())
    # unchanged facts stay quiet
    for _ in range(3):
        e.clock += 600
        e.agent("a1", idle_min=60 + (e.clock - T0) // 60)
        assert e.scan()["events"] == []
    assert len(e.sends()) == 1 and len(e.pings()) == 1


def test_cooldown_three_hours_then_notifies_again_without_second_wake_inside_window(e):
    e.agent("a1")
    e.declare()
    e.scan()
    e.clock += 3 * HOUR - 60
    e.agent("a1", idle_min=300)
    assert e.scan()["events"] == []
    e.clock += 120
    e.agent("a1", idle_min=305)
    rep = e.scan()
    assert [x["reason"] for x in rep["events"]] == ["idle_with_work"]
    assert len(e.sends()) == 2   # the 3-hour wake window has passed too
    assert len(e.inbox()) == 1


def test_not_idle_long_enough_busy_waiting_permission_unknown_never_wake(e):
    e.agent("fresh", idle_min=5)
    e.agent("busy", status="running")
    e.agent("perm", status="idle", perms=[{"id": "p"}])
    e.agent("wait", idle_min=90)
    e.agent("weird", idle_min=90)
    (e.fake / "inspect-weird.json").write_text(json.dumps([{"Status": "idle"}]))   # fields missing
    e.agent("ghost")
    (e.fake / "inspect-ghost.json").unlink()
    for task, agent, state in (("t-fresh", "fresh", "open"), ("t-busy", "busy", "open"), ("t-perm", "perm", "open"),
                               ("t-wait", "wait", "waiting"), ("t-weird", "weird", "open"), ("t-ghost", "ghost", "open")):
        e.declare(task=task, agent=agent, state=state)
    rep = e.scan()
    assert rep["events"] == [] and e.sends() == [] and e.pings() == []
    assert sum("unknown" in h for h in rep["health"]) == 2
    # a waiting declaration past review_after gets a due notice, never a wake
    e.declare(task="t-wait2", agent="wait", state="waiting", review_after=iso(T0 - 10))
    rep = e.scan()
    assert [(x["task"], x["reason"], x["wake"]) for x in rep["events"]] == [("t-wait2", "due", "na")]
    assert e.sends() == []


def test_over_cap_reports_partial_and_does_not_claim_clear(e):
    for i in range(18):
        e.agent(f"a{i}", status="running")
        e.declare(task=f"t{i:02d}", agent=f"a{i}")
    assert e.scan()["partial"] is True


@pytest.mark.parametrize("kw", [{"status": "closed"}, {"status": "error"}, {"archived": True}])
def test_stopped_agents_get_a_notice_and_no_send(e, kw):
    e.agent("a1", **kw)
    e.declare()
    rep = e.scan()
    assert [(x["reason"], x["wake"]) for x in rep["events"]] == [("stopped_with_open_work", "na")]
    assert e.sends() == []
    assert len(e.pings()) == 1


def test_due_on_a_busy_agent_notifies_without_wake(e):
    e.agent("a1", status="running")
    e.declare(review_after=iso(T0 - 1))
    rep = e.scan()
    assert [(x["reason"], x["wake"]) for x in rep["events"]] == [("due", "na")]
    assert e.sends() == []


def test_withdrawn_when_status_changes_before_second_reinspect(e):
    e.agent("a1")
    idle = json.loads((e.fake / "inspect-a1.json").read_text())[0]
    busy = dict(idle, Status="running")
    # reads: the scan, the preflight, then the re-inspect right before the send
    (e.fake / "inspect-a1.json").write_text(json.dumps([idle, idle, busy]))
    e.declare()
    rep = e.scan()
    assert rep["events"] == [] and rep["withdrawn"] == 1
    assert e.sends() == [] and e.pings() == [] and e.calls("pp.jsonl") == []
    assert all(r["state"] == "withdrawn" for r in e.inbox())
    e.agent("a1")   # cursor did not advance: once idle again, it notifies
    assert len(e.scan()["events"]) == 1 and len(e.sends()) == 1


def test_withdrawn_at_preflight_leaves_no_trace(e):
    idle = {"Status": "idle", "Archived": False, "PendingPermissions": [], "UpdatedAt": iso(T0 - 3600)}
    moved = dict(idle, UpdatedAt=iso(T0 - 5))
    (e.fake / "inspect-a1.json").write_text(json.dumps([idle, moved]))
    (e.fake / "ls.json").write_text(json.dumps([{"id": "a1", "status": "idle"}]))
    e.declare()
    rep = e.scan()
    assert rep["events"] == [] and rep["withdrawn"] == 1 and e.inbox() == []
    assert e.sends() == [] and e.pings() == []


def test_unknown_wake_still_pages_once_and_is_not_replayed(e):
    e.agent("a1")
    (e.fake / "send.json").write_text("not json at all")
    e.declare()
    rep = e.scan()
    assert [x["wake"] for x in rep["events"]] == ["unknown"] and len(e.pings()) == 1
    e.clock += 3 * HOUR + 60
    e.agent("a1", idle_min=400)
    rep = e.scan()   # next attempt only after the cooldown, and it records the earlier uncertain one
    assert len(e.sends()) == 2
    assert e.inbox()[0].get("prior_wake") == "unknown"


def test_refused_send_retries_at_most_three_times(e):
    e.agent("a1")
    (e.fake / "send.json").write_text('{"error": "no such agent"}')
    (e.fake / "send.rc").write_text("1")
    e.declare()
    for i in range(5):
        e.clock += 3 * HOUR + 60
        e.agent("a1", idle_min=600)
        e.scan()
    assert len(e.sends()) == 3


def test_sixteen_events_one_ping_and_hourly_cap_defers_not_loses(e):
    for i in range(16):
        e.agent(f"a{i}", status="closed")
        e.declare(task=f"task-{i:02d}", agent=f"a{i}")
    rep = e.scan()
    assert len(rep["events"]) == 16 and len(e.pings()) == 1
    line = e.pings()[0][0]
    assert line.startswith("djbclark-ade: progress: 16 notice(s): ") and len(line) <= 300 and "\n" not in line
    assert "(+" in line and line.endswith("run ade-progress inbox")
    assert {r["ping"] for r in e.inbox()} == {"sent"}


def test_hourly_cap_exact(e):
    for n in range(4):
        e.agent(f"b{n}", status="closed")
        e.declare(task=f"x{n}", agent=f"b{n}")
        e.clock += 60
        e.scan()
    assert len(e.pings()) == 3
    assert [r["ping"] for r in e.inbox() if r["task"] == "x3"] == ["deferred-rate-limit"]
    e.clock += HOUR
    e.scan()
    assert len(e.pings()) == 4 and "x3" in e.pings()[-1][0]
    assert [r["ping"] for r in e.inbox() if r["task"] == "x3"] == ["sent"]


@pytest.mark.parametrize("mode", ["norun", "absent", "unverified"])
def test_no_run_absent_unverified_degrade_to_page_and_inbox(e, mode):
    e.agent("a1")
    e.declare()
    extra = {}
    if mode == "norun":
        (e.fake / "pp.norun").write_text("1")
    elif mode == "absent":
        extra = {"ADE_PROGRESS_PASEO_PROGRESS": str(e.tmp / "missing"), "HOME": str(e.tmp / "nohome")}
    else:
        (e.fake / "pp.noshow").write_text("1")
    r = e.run("scan", "--yes", "--json", **extra)
    assert r.returncode == 0, r.stderr
    ev = json.loads(r.stdout)["events"][0]
    assert ev["ui"] == {"norun": "no-run", "absent": "absent", "unverified": "unverified"}[mode]
    assert ev["wake"] == "sent" and len(e.pings()) == 1


def test_one_channel_failing_does_not_block_others(e):
    e.agent("a1")
    e.declare()
    (e.fake / "ping.rc").write_text("3")
    (e.fake / "pp.norun").write_text("1")
    rep = e.scan()
    assert rep["events"][0]["wake"] == "sent" and rep["ping"] == "rc=3"
    rec = e.inbox()[0]
    assert rec["state"] == "published-local" and rec["ping"] == "failed" and rec["ui"] == "no-run"


def test_ack_and_retire_close_the_progress_item_and_stop_reminders(e):
    e.agent("a1")
    e.declare()
    e.scan()
    assert e.run("ack", "--task", "t1").stdout.startswith("would ack")
    assert e.run("ack", "--task", "t1", "--yes").returncode == 0
    clears = [c for c in e.calls("pp.jsonl") if c[1:3] == ["stuck", "clear"]]
    assert len(clears) == 1 and clears[0][3] == "S1"
    e.clock += 4 * HOUR
    e.agent("a1", idle_min=900)
    assert e.scan()["events"] == []
    assert e.inbox()[0].get("acked")


def test_generation_bump_is_a_new_event_key(e):
    e.agent("a1", status="closed")
    e.declare()
    e.scan()
    e.run("declare", "--task", "t1", "--agent", "a1", "--summary", "next phase", "--generation", "1", "--yes")
    e.clock += 60
    assert len(e.scan()["events"]) == 1 and len(e.inbox()) == 2


def test_corrupt_state_is_kept_and_reported(e):
    e.agent("a1")
    e.declare()
    e.scan()
    sp = e.state / "state.json"
    sp.write_text("{ not json")
    r = e.run("scan", "--yes")
    assert r.returncode == 3 and "corrupt" in r.stderr
    assert sp.read_text() == "{ not json"


def test_concurrent_scans_take_the_lock_once(e):
    e.agent("a1")
    e.declare()
    env = e.env(FAKE_SLEEP="1.5")
    cmd = [sys.executable, str(SCRIPT), "scan", "--yes", "--json"]
    p1 = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, text=True)
    time.sleep(0.4)
    p2 = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=60)
    out1, _ = p1.communicate(timeout=60)
    assert p2.returncode == 0 and json.loads(p2.stdout)["busy"] is True
    assert json.loads(out1)["events"] and len(e.sends()) == 1 and len(e.pings()) == 1


def test_crash_between_intent_and_receipt_reconciles_without_duplicate_send(e):
    e.agent("a1")
    e.declare()
    e.scan()
    sp = e.state / "state.json"
    st = json.loads(sp.read_text())
    (rec,) = st["events"].values()
    rec.update(state="prepared", wake="intent", ping=None, ui=None, last_published=0)   # crashed after the wake intent
    for w in st["wakes"].values():
        w["ts"] = T0
    sp.write_text(json.dumps(st))
    before = len(e.sends())
    rep = e.scan()
    assert len(e.sends()) == before   # the wake that may have gone out is not repeated
    assert [x["wake"] for x in rep["events"]] == ["unknown"]
    assert len(e.inbox()) == 1


def test_clock_rollback_suppresses_sends(e):
    e.agent("a1")
    e.declare()
    e.scan()
    e.clock -= 2 * HOUR
    rep = e.scan()
    assert rep["suppressed"] and e.sends() and len(e.sends()) == 1 and len(e.pings()) == 1


def test_ls_failure_claims_nothing(e):
    e.agent("a1")
    e.declare()
    (e.fake / "ls_fail").write_text("1")
    rep = e.scan()
    assert rep["events"] == [] and any("unreadable" in h for h in rep["health"])
    assert e.sends() == [] and e.pings() == []


def test_no_model_call_and_only_native_verbs(e):
    e.agent("a1")
    e.declare()
    e.scan()
    verbs = {c[0] for c in e.calls()}
    assert verbs <= {"ls", "inspect", "send"}
    src = SCRIPT.read_text()
    for banned in ("anthropic", "openai", "urllib", "http.client", "socket", "claude -p", '"git"', "'git'"):
        assert banned not in src


def test_plist_template_and_inventory_row():
    d = plistlib.loads((ROOT / "config" / "launchd" / "com.djbclark.ade-progress.plist").read_bytes())
    assert d["Label"] == "com.djbclark.ade-progress"
    assert d["ProgramArguments"] == ["__ADE__/bin/ade-job-run", "com.djbclark.ade-progress", "--",
                                     "__ADE__/bin/ade-progress", "scan", "--yes"] and d["StartInterval"] == 300
    # slice 1b: inventoried as an optional row; chosen = true since 2026-11-13, so doctor expects the label
    rows = [r for r in tomllib.loads((ROOT / "config" / "install.toml").read_text())["install"]["jobs"]
            if r["name"] == "ade-progress"]
    assert len(rows) == 1
    r = rows[0]
    assert (r["kind"], r["owner"], r["class"], r["chosen"]) == ("ade-sched", "djbclark-ade", "optional", True)
    assert r["label"] == d["Label"] and r["plist"] == "config/launchd/com.djbclark.ade-progress.plist"


def test_inventory_row_doctor_expectations():
    """Unchosen: quiet whether or not the label is live. Chosen: ok when live, a failing `missing` row when absent."""
    sys.path.insert(0, str(ROOT / "bin"))
    import ade_sched as S
    row = next(r for r in tomllib.loads((ROOT / "config" / "install.toml").read_text())["install"]["jobs"]
               if r["name"] == "ade-progress")
    live = S.LiveScan("launchd", (S.LiveJob("com.djbclark.ade-progress", "launchd", "generated"),), ())
    none = S.LiveScan("launchd", (), ())

    def status(r, scan):
        return [(x.status, x.fail) for x in S.diff_jobs([r], [], scan) if x.name == "ade-progress"]

    unchosen = dict(row, chosen=False)
    assert status(unchosen, live) == [("unchosen", False)] and status(unchosen, none) == [("unchosen", False)]
    chosen = dict(row, chosen=True)
    assert status(chosen, live) == [("ok", False)]
    assert status(chosen, none) == [("missing", True)]
    # installed but unchosen: still quiet, and the detail says the label is live
    detail = [x.detail for x in S.diff_jobs([unchosen], [], live) if x.name == "ade-progress"]
    assert len(detail) == 1 and "live (installed but unchosen)" in detail[0]


def test_one_wake_per_agent_per_window_even_with_several_tasks(e):
    e.agent("a1")
    for t in ("t1", "t2", "t3"):
        e.declare(task=t)
    rep = e.scan()
    assert sorted(x["wake"] for x in rep["events"]) == ["na", "na", "sent"]
    assert len(e.sends()) == 1 and len(e.pings()) == 1
    dry = e.run("scan", "--dry-run", "--json")
    assert dry.returncode == 0


def test_busy_lock_makes_state_changing_commands_exit_75_not_success(e):
    e.agent("a1")
    e.declare()
    p1 = subprocess.Popen([sys.executable, str(SCRIPT), "scan", "--yes"], env=e.env(FAKE_SLEEP="1.5"),
                          stdout=subprocess.PIPE, text=True)
    time.sleep(0.4)
    for args in (["retire", "--task", "t1", "--generation", "1", "--yes"], ["ack", "--task", "t1", "--yes"],
                 ["declare", "--task", "t1", "--agent", "a1", "--summary", "z", "--generation", "1", "--yes"]):
        r = e.run(*args)
        assert r.returncode == 75 and "busy" in r.stderr, (args, r.stdout, r.stderr)
    p1.communicate(timeout=60)
    assert json.loads((e.state / "decl" / "t1.json").read_text())["state"] == "open"
    assert e.run("retire", "--task", "t1", "--generation", "1", "--yes").returncode == 0


def test_repeat_notice_reuses_the_progress_item_and_ack_clears_it(e):
    e.agent("a1", status="closed")
    e.declare()
    e.scan()
    e.clock += 3 * HOUR + 60
    e.scan()
    sets = [c for c in e.calls("pp.jsonl") if c[1:3] == ["stuck", "set"]]
    assert len(sets) == 1
    e.run("ack", "--task", "t1", "--yes")
    assert [c[3] for c in e.calls("pp.jsonl") if c[1:3] == ["stuck", "clear"]] == ["S1"]


def test_a_published_record_that_was_never_paged_rides_the_next_digest(e):
    e.agent("a1", status="closed")
    e.declare()
    e.scan()
    sp = e.state / "state.json"
    st = json.loads(sp.read_text())
    for rec in st["events"].values():
        rec["ping"] = None   # a crash after publishing, before the page
    st["pings"] = []
    sp.write_text(json.dumps(st))
    before = len(e.pings())
    e.clock += 60
    e.scan()
    assert len(e.pings()) == before + 1


def test_option_injection_and_unsafe_text_rejected(e):
    for args in (["--task", "-h", "--summary", "x", "--agent", "a1"], ["--task=ok", "--summary", "x", "--agent=--x"],
                 ["--task", "ok", "--summary", "a\u2028b", "--agent", "a1"], ["--task", "ok", "--summary", "x\x1b[31m", "--agent", "a1"],
                 ["--task", "ok", "--summary", "x", "--agent", "a1", "--idle-after-min", "0"],
                 ["--task", "ok", "--summary", "x", "--agent", "a1", "--pending", "-1"]):
        r = e.run("declare", *args, "--yes")
        assert r.returncode == 2, (args, r.stdout, r.stderr)
    assert not (e.state / "decl").exists()


def test_naive_review_after_is_utc_and_padded_summary_is_trimmed(e):
    e.agent("a1", status="running")
    r = e.run("declare", "--task", "t1", "--agent", "a1", "--summary", "  padded  ", "--review-after", "2027-01-01T00:00:00", "--yes")
    assert r.returncode == 0
    d = json.loads((e.state / "decl" / "t1.json").read_text())
    assert d["summary"] == "padded" and d["review_after"] == "2027-01-01T00:00:00"
    e.clock = datetime(2027, 1, 1, 0, 0, 1, tzinfo=timezone.utc).timestamp()
    e.agent("a1", status="running")
    assert [x["reason"] for x in e.scan()["events"]] == ["due"]


def test_refusal_is_parsed_from_stdout_even_with_stderr_noise(e):
    e.agent("a1")
    (e.fake / "send.json").write_text('{"error": "no such agent"}')
    (e.fake / "send.err").write_text("warning: something\n")
    (e.fake / "send.rc").write_text("1")
    e.declare()
    assert [x["wake"] for x in e.scan()["events"]] == ["refused"]


def test_declaration_from_another_paseo_home_is_skipped(e):
    e.agent("a1")
    e.declare()
    r = e.run("scan", "--yes", "--json", PASEO_HOME=str(e.tmp / "other-home"))
    rep = json.loads(r.stdout)
    assert rep["events"] == [] and any("another PASEO_HOME" in h for h in rep["health"]) and e.sends() == []


def test_progress_id_is_read_from_the_real_flagged_line(e):
    e.agent("a1", status="closed")
    e.declare()
    e.scan()
    rec = e.inbox()[0]
    assert rec["ui_id"] == "S1" and rec["ui"] == "verified"


def test_rc0_without_a_readable_id_is_unverified_and_never_set_twice(e):
    e.agent("a1", status="closed")
    e.declare()
    (e.fake / "pp.weird").write_text("1")
    e.scan()
    assert e.inbox()[0]["ui"] == "unverified"
    e.clock += 3 * HOUR + 60
    e.scan()
    assert len([c for c in e.calls("pp.jsonl") if c[1:3] == ["stuck", "set"]]) == 1


def test_generation_bump_reuses_the_open_progress_item(e):
    e.agent("a1", status="closed")
    e.declare()
    e.scan()
    e.run("declare", "--task", "t1", "--agent", "a1", "--summary", "next", "--generation", "1", "--yes")
    e.clock += 60
    e.scan()
    assert len([c for c in e.calls("pp.jsonl") if c[1:3] == ["stuck", "set"]]) == 1
    assert {r["ui_id"] for r in e.inbox()} == {"S1"}


def test_crash_between_stuck_set_and_save_does_not_set_a_second_item(e):
    e.agent("a1", status="closed")
    e.declare()
    e.scan()
    sp = e.state / "state.json"
    st = json.loads(sp.read_text())
    (rec,) = st["events"].values()
    rec.update(state="prepared", ui="intent", ui_id=None, ping=None, last_published=0)
    sp.write_text(json.dumps(st))
    e.scan()
    assert len([c for c in e.calls("pp.jsonl") if c[1:3] == ["stuck", "set"]]) == 1
    assert e.inbox()[0]["ui"] == "unverified"


def test_prepared_record_with_unknown_wake_is_still_paged(e):
    e.agent("a1")
    e.declare()
    e.scan()
    sp = e.state / "state.json"
    st = json.loads(sp.read_text())
    (rec,) = st["events"].values()
    rec.update(state="prepared", wake="intent", ping=None, ui=None, last_published=0)
    st["pings"] = []
    sp.write_text(json.dumps(st))
    e.agent("a1", status="running")   # the woken agent is busy now: the trigger is gone
    before = len(e.pings())
    e.clock += 60
    e.scan()
    assert len(e.pings()) == before + 1 and len(e.sends()) == 1


def test_busy_scan_json_is_json(e):
    e.agent("a1")
    e.declare()
    p1 = subprocess.Popen([sys.executable, str(SCRIPT), "scan", "--yes"], env=e.env(FAKE_SLEEP="1.5"), stdout=subprocess.PIPE, text=True)
    time.sleep(0.4)
    r = e.run("scan", "--yes", "--json")
    p1.communicate(timeout=60)
    assert r.returncode == 0 and json.loads(r.stdout)["busy"] is True


def pp_state(e) -> dict:
    return json.loads((e.fake / "pp.state.json").read_text())


def test_item_the_agent_cleared_is_not_carried_as_verified(e):
    e.agent("a1", status="closed")
    e.declare()
    e.scan()
    (e.fake / "pp.state.json").write_text(json.dumps({"n": 1, "items": {}}))   # the agent ran `stuck clear S1` to finish
    e.run("declare", "--task", "t1", "--agent", "a1", "--summary", "next", "--generation", "1", "--yes")
    e.clock += 60
    e.scan()
    recs = {r["key"].split("|")[3]: r for r in e.inbox()}
    assert recs["2"]["ui_id"] == "S2" and recs["2"]["ui"] == "verified" and recs["1"].get("ui_gone")
    e.run("ack", "--task", "t1", "--yes")
    assert pp_state(e)["items"] == {}   # S2 cleared, S1 was never touched again


def test_ack_never_clears_an_id_that_is_now_the_agents_own_item(e):
    e.agent("a1", status="closed")
    e.declare()
    e.scan()
    (e.fake / "pp.state.json").write_text(json.dumps({"n": 1, "items": {"S1": "need creds"}}))   # new run reused S1
    r = e.run("ack", "--task", "t1", "--yes")
    assert r.returncode == 0 and "not cleared (absent)" in r.stdout
    assert pp_state(e)["items"] == {"S1": "need creds"}
    assert not [c for c in e.calls("pp.jsonl") if c[1:3] == ["stuck", "clear"]]


def test_shared_item_is_cleared_once_and_a_failed_check_is_shown_in_the_inbox(e):
    e.agent("a1", status="closed")
    e.declare()
    e.scan()
    e.run("declare", "--task", "t1", "--agent", "a1", "--summary", "next", "--generation", "1", "--yes")
    e.clock += 60
    e.scan()   # second generation shares S1
    e.run("ack", "--task", "t1", "--yes")
    assert len([c for c in e.calls("pp.jsonl") if c[1:3] == ["stuck", "clear"]]) == 1
    assert all(r["ui_cleared"] is True for r in e.inbox())


def test_show_failure_never_triggers_a_blind_clear(e):
    e.agent("a1", status="closed")
    e.declare()
    e.scan()
    (e.fake / "pp.norun").write_text("1")   # show fails from now on
    r = e.run("ack", "--task", "t1", "--yes")
    assert "could not check" in r.stdout
    assert not [c for c in e.calls("pp.jsonl") if c[1:3] == ["stuck", "clear"]]
    assert "ui_cleared=False" in e.run("inbox").stdout


def test_withdrawn_repeat_notice_keeps_the_item_reference(e):
    e.agent("a1")
    e.declare()
    e.scan()   # S1 set
    e.clock += 3 * HOUR + 60
    e.agent("a1", idle_min=400)
    idle = json.loads((e.fake / "inspect-a1.json").read_text())[0]
    (e.fake / "inspect-a1.json").write_text(json.dumps([idle, idle, dict(idle, Status="running")]))   # step-2 withdrawal
    assert e.scan()["withdrawn"] == 1
    assert e.inbox()[0]["ui_id"] == "S1"   # the withdrawn record still holds the item
    e.agent("a1", idle_min=400)
    e.clock += 60
    e.scan()
    assert len([c for c in e.calls("pp.jsonl") if c[1:3] == ["stuck", "set"]]) == 1
    e.run("ack", "--task", "t1", "--yes")
    assert pp_state(e)["items"] == {}


def test_show_format_drift_never_stacks_or_clears_blindly(e):
    e.agent("a1", status="closed")
    e.declare()
    (e.fake / "pp.fmt").write_text("1")
    rep = e.scan()
    rec = e.inbox()[0]
    assert rec["ui"] == "unverified" and rec["marker_seen"] is False and any("format drift" in h for h in rep["health"])
    e.clock += 3 * HOUR + 60
    e.scan()
    assert len([c for c in e.calls("pp.jsonl") if c[1:3] == ["stuck", "set"]]) == 1
    e.run("ack", "--task", "t1", "--yes")
    assert not [c for c in e.calls("pp.jsonl") if c[1:3] == ["stuck", "clear"]]
    assert "ui_cleared=False" in e.run("inbox").stdout


def test_marker_is_the_exact_text_we_set(e):
    e.agent("a1", status="closed")
    e.declare()
    e.scan()
    # the agent's own item reusing the id with a similar prefix is not ours
    (e.fake / "pp.state.json").write_text(json.dumps({"n": 1, "items": {"S1": "t1: waiting on X"}}))
    r = e.run("ack", "--task", "t1", "--yes")
    assert "not cleared (absent)" in r.stdout and pp_state(e)["items"] == {"S1": "t1: waiting on X"}
