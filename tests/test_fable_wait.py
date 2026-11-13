"""Tests for bin/fable-wait (operator ruling 2026-11-13: wait for Fable, list what must be re-checked, wake 1 minute after the window
resets). Hermetic: a temp state dir, a fixed clock (FABLE_WAIT_NOW) and fake `paseo`, `ade-sched` and `hermes-ping` executables that
log every call. No real launchd or cron install, no real send, no model."""
from __future__ import annotations

import json
import os
import plistlib
import subprocess
import sys
import textwrap
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "fable-wait"
sys.path.insert(0, str(ROOT / "bin"))

RESET = "2026-11-20T10:00:00.130176+00:00"
RESET_EPOCH = datetime.fromisoformat(RESET).timestamp()
NOW = datetime(2026, 11, 13, 16, 0, tzinfo=UTC).timestamp()
LEAD = "11111111-1111-4111-8111-111111111111"
LEAD2 = "22222222-2222-4222-8222-222222222222"

FAKE_PASEO = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, sys
    d = os.environ["FAKE_DIR"]
    with open(d + "/paseo.jsonl", "a") as f:
        f.write(json.dumps(sys.argv[1:]) + "\\n")
    if sys.argv[1:3] == ["usage", "ls"]:
        if os.path.exists(d + "/usage_fail"):
            sys.exit(1)
        print(open(d + "/usage.json").read())
    elif sys.argv[1] == "send":
        lead = sys.argv[sys.argv.index("--") + 1]
        if os.path.exists(d + "/send_fail_" + lead):
            print("boom", file=sys.stderr)
            sys.exit(2)
        print('{"status": "sent"}')
''')
FAKE_SCHED = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, shutil, sys
    d = os.environ["FAKE_DIR"]
    argv = sys.argv[1:]
    with open(d + "/sched.jsonl", "a") as f:
        f.write(json.dumps(argv) + "\\n")
    if "install" in argv:
        if os.path.exists(d + "/install_fail"):
            print("scheduler refused", file=sys.stderr)
            sys.exit(1)
        shutil.copy(argv[-1], d + "/installed.plist")
    if "uninstall" in argv and os.path.exists(d + "/uninstall_fail_once"):
        os.unlink(d + "/uninstall_fail_once")
        sys.exit(1)
''')
FAKE_PING = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, sys
    with open(os.environ["FAKE_DIR"] + "/ping.jsonl", "a") as f:
        f.write(json.dumps(sys.argv[1:]) + "\\n")
''')


def usage(fable: str | None = RESET, weekly: str | None = "2026-11-20T10:00:00.130048+00:00", status: str = "available",
          source: str = "claude") -> str:
    windows = []
    if weekly:
        windows.append({"id": "weekly", "label": "Weekly", "usedPct": 16, "remainingPct": 84, "resetsAt": weekly})
    if fable:
        windows.append({"id": "weekly_model_fable", "label": "Weekly - Fable", "usedPct": 12, "remainingPct": 88, "resetsAt": fable})
    rows = [{"sourceId": "codex", "report": {"status": "available", "windows": [
        {"id": "weekly", "resetsAt": "2026-11-18T17:06:26.000Z"}]}},
        {"sourceId": source, "report": {"status": status, "windows": windows}}]
    return json.dumps(rows)


class Env:
    def __init__(self, tmp: Path):
        self.dir = tmp / "fake"
        self.dir.mkdir()
        for name, body in (("paseo", FAKE_PASEO), ("ade-sched", FAKE_SCHED), ("hermes-ping", FAKE_PING)):
            (self.dir / name).write_text(body)
            (self.dir / name).chmod(0o755)
        self.state = tmp / "state"
        (self.dir / "usage.json").write_text(usage())
        self.env = {**os.environ, "FAKE_DIR": str(self.dir), "FABLE_WAIT_STATE_DIR": str(self.state),
                    "FABLE_WAIT_PASEO": str(self.dir / "paseo"), "FABLE_WAIT_ADE_SCHED": str(self.dir / "ade-sched"),
                    "FABLE_WAIT_HERMES_PING": str(self.dir / "hermes-ping"), "FABLE_WAIT_ADE": str(ROOT),
                    "FABLE_WAIT_NOW": str(NOW)}
        for key in ("PASEO_AGENT_ID", "PASEO_AGENT_CWD", "PASEO_WORKSPACE_ID"):
            self.env.pop(key, None)

    def run(self, *argv: str, now: float | None = None, cwd: Path | None = None, script: Path = SCRIPT
            ) -> subprocess.CompletedProcess:
        env = dict(self.env)
        if now is not None:
            env["FABLE_WAIT_NOW"] = str(now)
        return subprocess.run([sys.executable, str(script), *argv], check=False, capture_output=True, text=True, env=env, timeout=60,
                              cwd=cwd, stdin=subprocess.DEVNULL)

    def calls(self, name: str) -> list[list[str]]:
        path = self.dir / f"{name}.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def wait_for(self, name: str, n: int, timeout: float = 15.0) -> list[list[str]]:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            calls = self.calls(name)
            if len(calls) >= n:
                return calls
            time.sleep(0.1)
        return self.calls(name)

    def add(self, title: str = "recheck the router", lead: str = LEAD, *extra: str) -> str:
        r = self.run("add", "--title", title, "--lead", lead, "--json", *extra)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)["id"]


@pytest.fixture
def fw(tmp_path):
    return Env(tmp_path)


# ---------- the list ----------

def test_add_ls_close_keeps_every_record(fw, tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text("do it")
    a = fw.add("first", LEAD, "--brief-file", str(brief), "--note", "ran on Opus", "--kind", "degraded")
    b = fw.add("second", LEAD2)
    out = json.loads(fw.run("ls", "--json").stdout)
    assert [i["id"] for i in out["items"]] == [a, b]
    first = out["items"][0]
    assert (first["kind"], first["note"], first["brief_file"], first["lead"]) == ("degraded", "ran on Opus", str(brief.resolve()), LEAD)
    assert out["wake"] is None
    assert fw.run("close", a, "--note", "rechecked").returncode == 0
    assert [i["id"] for i in json.loads(fw.run("ls", "--json").stdout)["items"]] == [b]
    everything = json.loads(fw.run("ls", "--json", "--all").stdout)["items"]
    assert [i["id"] for i in everything] == [a, b] and everything[0]["closed"]["note"] == "rechecked"
    lines = (fw.state / "queue.jsonl").read_text().splitlines()
    assert [json.loads(x)["op"] for x in lines] == ["add", "add", "close"]          # nothing is deleted
    assert "already closed" in fw.run("close", a).stdout
    assert len((fw.state / "queue.jsonl").read_text().splitlines()) == 3


def test_add_rejects_bad_input(fw):
    assert fw.run("add", "--title", "x", "--lead", "--steer").returncode == 2        # an option is not an agent id
    assert fw.run("add", "--title", "x", "--lead", LEAD, "--brief-file", "/no/such/file").returncode == 2
    assert fw.run("add", "--title", "  ", "--lead", LEAD).returncode == 2
    assert fw.run("close", "nope").returncode == 2
    assert fw.run("close", "fw-20260101T000000Z-abcdef").returncode == 2             # well formed but unknown
    assert not (fw.state / "queue.jsonl").exists()


def test_corrupt_queue_is_kept_not_reset(fw):
    fw.state.mkdir()
    (fw.state / "queue.jsonl").write_text("{not json\n")
    r = fw.run("ls")
    assert r.returncode == 4 and "kept" in r.stderr
    assert (fw.state / "queue.jsonl").read_text() == "{not json\n"


# ---------- arm ----------

def test_arm_installs_one_wake_at_the_reset_plus_60s(fw):
    fw.add()
    r = fw.run("arm")
    assert r.returncode == 0, r.stderr
    wake = json.loads((fw.state / "wake.json").read_text())
    assert wake["window"] == "weekly_model_fable"
    fire = datetime.fromisoformat(wake["fire_at"])
    assert fire == datetime.fromtimestamp(RESET_EPOCH + 60, UTC).replace(microsecond=0)
    install = [c for c in fw.calls("sched") if "install" in c]
    assert install == [["--ade", str(ROOT), "install", str(fw.state / "wake.plist")]]
    plist = plistlib.loads((fw.dir / "installed.plist").read_bytes())
    assert plist["Label"] == "com.djbclark.fable-wait"
    assert plist["ProgramArguments"][-2:] == ["__ADE__/bin/fable-wait", "fire"]
    cal = plist["StartCalendarInterval"]
    local = datetime(fire.year, cal["Month"], cal["Day"], cal["Hour"], cal["Minute"]).astimezone()
    due = datetime.fromtimestamp(RESET_EPOCH + 60, UTC).astimezone()
    assert local >= due.replace(tzinfo=local.tzinfo) and local - due < timedelta(minutes=1, seconds=1)   # rounded UP to the minute
    assert not (fw.dir / "paseo.jsonl").read_text().count("send")                    # arming sends nothing


def test_the_wake_plist_is_valid_for_ade_sched(fw, tmp_path):
    import ade_sched
    fw.run("arm", "--dry-run")
    assert fw.run("arm").returncode == 0
    job = ade_sched.Job.from_plist(fw.state / "wake.plist", ade=ROOT)
    assert job.label == "com.djbclark.fable-wait" and len(job.calendar) == 1
    assert list(job.argv) == [str(ROOT / "bin/ade-job-run"), "--lock-dir", str(ade_sched.canonical_admission_dir()),
                              "com.djbclark.fable-wait", "--", str(ROOT / "bin/fable-wait"), "fire"]
    rendered = ade_sched.render(job, "launchd", agents_dir=tmp_path / "agents")
    assert any("fable-wait" in text for text in rendered.files.values())


def test_arm_dry_run_installs_nothing(fw):
    r = fw.run("arm", "--dry-run")
    assert r.returncode == 0 and "dry run" in r.stdout and "StartCalendarInterval" in r.stdout
    assert not fw.calls("sched") and not (fw.state / "wake.json").exists()


def test_arm_falls_back_to_the_weekly_window(fw):
    (fw.dir / "usage.json").write_text(usage(fable=None, weekly="2026-11-21T08:00:00+00:00"))
    assert fw.run("arm").returncode == 0
    wake = json.loads((fw.state / "wake.json").read_text())
    assert wake["window"] == "weekly" and wake["fire_at"] == "2026-11-21T08:01:00Z"


def test_arm_takes_the_latest_reset_of_several_claude_rows(fw):
    rows = json.loads(usage()) + json.loads(usage(fable="2026-11-22T10:00:00+00:00"))
    (fw.dir / "usage.json").write_text(json.dumps(rows))
    assert fw.run("arm").returncode == 0
    assert json.loads((fw.state / "wake.json").read_text())["reset_at"] == "2026-11-22T10:00:00Z"


@pytest.mark.parametrize("body", [
    usage(fable=None, weekly=None),                      # claude row, no usable window
    usage(status="unavailable"),                         # the report is not `available`
    usage(source="codex"),                               # no claude row at all
    usage(fable="not a time", weekly=None),              # resetsAt unparseable
    "not json", "{}",
])
def test_arm_refuses_when_the_reset_is_unknown(fw, body):
    (fw.dir / "usage.json").write_text(body)
    r = fw.run("arm")
    assert r.returncode == 3 and "unknown" in r.stderr
    assert not fw.calls("sched") and not (fw.state / "wake.json").exists()


def test_arm_refuses_when_paseo_fails(fw):
    (fw.dir / "usage_fail").write_text("")
    assert fw.run("arm").returncode == 3 and not fw.calls("sched")


def test_arm_refuses_a_reset_in_the_past(fw):
    r = fw.run("arm", now=RESET_EPOCH + 1)
    assert r.returncode == 3 and "past" in r.stderr
    assert fw.run("arm", now=RESET_EPOCH).returncode == 3          # the instant of the reset is not "ahead" either
    assert not fw.calls("sched") and not (fw.state / "wake.json").exists()


def test_rearming_replaces_the_previous_wake(fw):
    assert fw.run("arm").returncode == 0
    first = json.loads((fw.state / "wake.json").read_text())
    (fw.dir / "usage.json").write_text(usage(fable="2026-11-27T10:00:00+00:00"))
    r = fw.run("arm")
    assert r.returncode == 0 and "replaced the previous wake" in r.stdout
    second = json.loads((fw.state / "wake.json").read_text())
    assert second["wake_id"] != first["wake_id"] and second["reset_at"] == "2026-11-27T10:00:00Z"
    assert len([c for c in fw.calls("sched") if "install" in c]) == 2     # one label: install replaces, never two wakes
    assert not [c for c in fw.calls("sched") if "uninstall" in c]


def test_a_failed_install_restores_the_previous_wake(fw):
    assert fw.run("arm").returncode == 0
    first = (fw.state / "wake.json").read_text()
    (fw.dir / "install_fail").write_text("")
    (fw.dir / "usage.json").write_text(usage(fable="2026-11-27T10:00:00+00:00"))
    r = fw.run("arm")
    assert r.returncode == 1 and "scheduler refused" in r.stderr
    assert (fw.state / "wake.json").read_text() == first


def test_a_failed_first_install_leaves_no_wake(fw):
    (fw.dir / "install_fail").write_text("")
    assert fw.run("arm").returncode == 1 and not (fw.state / "wake.json").exists()


def test_arm_from_a_linked_worktree_needs_ade(fw, tmp_path):
    main = tmp_path / "main"
    (main / "bin").mkdir(parents=True)
    subprocess.run(["git", "-C", str(main), "init", "-q", "-b", "main"], check=True)
    (main / "bin/fable-wait").write_text(SCRIPT.read_text())
    subprocess.run(["git", "-C", str(main), "add", "."], check=True)
    subprocess.run(["git", "-C", str(main), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "x"], check=True)
    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", "-b", "side", str(wt)], check=True)
    (wt / "bin/ade_sched.py").write_text("")
    (fw.env).pop("FABLE_WAIT_ADE")
    r = fw.run("arm", script=wt / "bin/fable-wait")
    assert r.returncode == 2 and "linked worktree" in r.stderr and not fw.calls("sched")
    assert fw.run("arm", "--ade", str(main), script=wt / "bin/fable-wait").returncode == 0


# ---------- fire ----------

def arm(fw) -> dict:
    assert fw.run("arm").returncode == 0
    return json.loads((fw.state / "wake.json").read_text())


def test_fire_messages_each_lead_pings_once_and_disarms(fw, tmp_path):
    brief = tmp_path / "b.md"
    brief.write_text("x")
    a = fw.add("alpha", LEAD, "--brief-file", str(brief), "--note", "was Opus", "--kind", "degraded")
    b = fw.add("beta", LEAD)
    c = fw.add("gamma", LEAD2)
    closed = fw.add("done already", LEAD)
    fw.run("close", closed)
    wake = arm(fw)
    due = datetime.fromisoformat(wake["fire_at"]).timestamp()
    r = fw.run("fire", now=due)
    assert r.returncode == 0, r.stderr
    sends = [x for x in fw.calls("paseo") if x[0] == "send"]
    assert [s[:3] for s in sends] == [["send", "--json", "--no-wait"]] * 2
    by_lead = {s[s.index("--") + 1]: s[-1] for s in sends}
    assert set(by_lead) == {LEAD, LEAD2}
    assert a in by_lead[LEAD] and b in by_lead[LEAD] and closed not in by_lead[LEAD] and c not in by_lead[LEAD]
    assert c in by_lead[LEAD2] and a not in by_lead[LEAD2]
    assert "start these on Fable 5.2 now" in by_lead[LEAD] and "Please reply: ack fable-wait " + wake["wake_id"] in by_lead[LEAD]
    assert "[degraded] alpha" in by_lead[LEAD] and str(brief.resolve()) in by_lead[LEAD] and "was Opus" in by_lead[LEAD]
    assert fw.calls("ping") == [["djbclark-ade: Fable window reset, 3 items queued"]]
    assert not (fw.state / "wake.json").exists()                                  # disarmed
    assert fw.wait_for("sched", 3) and [c for c in fw.calls("sched") if c[-2:] == ["uninstall", "com.djbclark.fable-wait"]]
    # the items stay open (the lead closes them when it starts them); a second fire is a no-op
    assert len(json.loads(fw.run("ls", "--json").stdout)["items"]) == 3
    assert "no wake is armed" in fw.run("fire", now=due + 5).stdout
    assert len(fw.calls("ping")) == 1 and len([x for x in fw.calls("paseo") if x[0] == "send"]) == 2


def test_fire_before_the_wake_is_due_does_nothing(fw):
    fw.add()
    wake = arm(fw)
    due = datetime.fromisoformat(wake["fire_at"]).timestamp()
    r = fw.run("fire", now=due - 1)
    assert r.returncode == 0 and "not due yet" in r.stdout
    assert not [x for x in fw.calls("paseo") if x[0] == "send"] and not fw.calls("ping") and (fw.state / "wake.json").exists()


def test_fire_with_no_wake_armed_does_nothing_unless_forced(fw):
    fw.add()
    assert "no wake is armed" in fw.run("fire").stdout
    assert not fw.calls("ping")
    assert fw.run("fire", "--force").returncode == 0
    assert len(fw.calls("ping")) == 1 and len([x for x in fw.calls("paseo") if x[0] == "send"]) == 1


def test_fire_dry_run_sends_nothing(fw):
    fw.add()
    wake = arm(fw)
    due = datetime.fromisoformat(wake["fire_at"]).timestamp()
    r = fw.run("fire", "--dry-run", now=due)
    assert r.returncode == 0 and "would send" in r.stdout
    assert not [x for x in fw.calls("paseo") if x[0] == "send"] and not fw.calls("ping") and (fw.state / "wake.json").exists()


def test_fire_reports_a_lead_that_could_not_be_reached(fw):
    fw.add("alpha", LEAD)
    fw.add("beta", LEAD2)
    (fw.dir / ("send_fail_" + LEAD2)).write_text("")
    wake = arm(fw)
    due = datetime.fromisoformat(wake["fire_at"]).timestamp()
    r = fw.run("fire", now=due)
    assert r.returncode == 1
    assert fw.calls("ping") == [["djbclark-ade: Fable window reset, 2 items queued; 1 lead(s) not reached"]]
    report = json.loads(r.stdout.splitlines()[-1])
    assert report["leads"][LEAD]["status"] == "sent" and report["leads"][LEAD2]["status"].startswith("no status")
    assert not (fw.state / "wake.json").exists()


def test_fire_with_an_empty_list_sends_and_pings_nothing_but_still_disarms(fw):
    wake = arm(fw)
    due = datetime.fromisoformat(wake["fire_at"]).timestamp()
    r = fw.run("fire", now=due)
    assert r.returncode == 0
    assert not [x for x in fw.calls("paseo") if x[0] == "send"] and not fw.calls("ping")
    assert not (fw.state / "wake.json").exists()


def test_fire_spends_no_model_quota_and_starts_no_agent(fw):
    fw.add()
    wake = arm(fw)
    due = datetime.fromisoformat(wake["fire_at"]).timestamp()
    fw.run("fire", now=due)
    verbs = {x[0] for x in fw.calls("paseo")}
    assert verbs <= {"usage", "send"} and "run" not in verbs                       # it only tells leads; it launches nothing


# ---------- disarm ----------

def test_disarm_retries_while_the_running_wake_holds_its_lock(fw):
    arm(fw)
    (fw.dir / "uninstall_fail_once").write_text("")
    r = fw.run("disarm", "--wait", "30")
    assert r.returncode == 0 and "disarmed" in r.stdout
    assert len([c for c in fw.calls("sched") if "uninstall" in c]) == 2
    assert not (fw.state / "wake.json").exists() and not (fw.state / "wake.plist").exists()


def test_disarm_expect_leaves_a_newer_wake(fw):
    wake = arm(fw)
    r = fw.run("disarm", "--expect", "deadbeef")
    assert r.returncode == 0 and "newer wake" in r.stdout
    assert json.loads((fw.state / "wake.json").read_text())["wake_id"] == wake["wake_id"]
    assert not [c for c in fw.calls("sched") if "uninstall" in c]
