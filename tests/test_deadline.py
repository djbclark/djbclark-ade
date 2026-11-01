"""Tests for bin/deadline: registered budgets enforced from outside. Hermetic: temp state dir, fake clock
(DEADLINE_NOW), fake relay / hermes-ping / acp-dispatch / paseo, and real short-lived child processes for the kill path."""
from __future__ import annotations

import json
import os
import plistlib
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "deadline"
T0 = 1_800_000_000


class Env:
    def __init__(self, tmp: Path):
        self.state = tmp / "state"
        self.log = tmp / "calls.log"
        self.tmp = tmp
        self.children: list[subprocess.Popen] = []
        for name, body in {
            "relay": ('#!/bin/sh\necho "RELAY $@" >> "$DL_LOG"\necho "SENDER $RELAY_SENDER_NAME" >> "$DL_LOG"\ncat >> "$DL_LOG"\necho >> "$DL_LOG"\n'
                      'if [ -f "$DL_RELAY_SLEEP" ]; then sleep "$(cat "$DL_RELAY_SLEEP")"; fi\n'
                      'if [ -f "$DL_RELAY_FAIL" ]; then echo "not sent" >&2; exit "$(cat "$DL_RELAY_FAIL")"; fi\n'),
            "ping": '#!/bin/sh\necho "PING $@" >> "$DL_LOG"\n',
            "dispatch": '#!/bin/sh\necho "DISPATCH $@" >> "$DL_LOG"\n',
            "paseo": (f'#!{sys.executable}\nimport os, sys\n'
                      'open(os.environ["DL_LOG"], "a").write("PASEO " + " ".join(sys.argv[1:]) + "\\n")\n'
                      'a = sys.argv[1:]\n'
                      'if a[:4] == ["ls", "-g", "--background", "--json"]:\n'
                      '    sys.stdout.write(open(os.environ["FAKE_PASEO_LS"]).read())\n'
                      'elif a[0] == "inspect":\n'
                      '    p = os.path.join(os.environ["FAKE_PASEO_DIR"], a[1] + ".json")\n'
                      '    if not os.path.exists(p): sys.exit(1)\n'
                      '    sys.stdout.write(open(p).read())\n'
                      'else:\n    sys.exit(2)\n'),
        }.items():
            p = tmp / name
            p.write_text(body)
            p.chmod(0o755)
        self.paseo_dir = tmp / "paseo-inspect"
        self.paseo_dir.mkdir()
        self.base = {
            "DEADLINE_STATE_DIR": str(self.state), "DL_LOG": str(self.log), "DEADLINE_SETTLE_S": "0.3",
            "DEADLINE_RELAY": str(tmp / "relay"), "DEADLINE_HERMES_PING": str(tmp / "ping"),
            "DEADLINE_ACP_DISPATCH": str(tmp / "dispatch"), "DEADLINE_PASEO": str(tmp / "paseo"),
            "FAKE_PASEO_LS": str(tmp / "ls.json"), "FAKE_PASEO_DIR": str(self.paseo_dir), "DL_RELAY_FAIL": str(tmp / "relay-fails"),
            "DL_RELAY_SLEEP": str(tmp / "relay-sleep"), "DEADLINE_INLINE_WORKER": "1",
        }
        (tmp / "ls.json").write_text("[]")

    def run(self, *args: str, now: float | None = T0, **extra) -> subprocess.CompletedProcess:
        env = {**os.environ, **self.base, **{k: str(v) for k, v in extra.items()}}
        env.pop("DEADLINE_NOW", None)
        if now is not None:
            env["DEADLINE_NOW"] = str(now)
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=60)

    def child(self, script: str = "trap '' TERM; sleep 60 & sleep 60; wait") -> subprocess.Popen:
        c = subprocess.Popen(["sh", "-c", script], start_new_session=True)
        self.children.append(c)
        return c

    def calls(self, kind: str) -> list[str]:
        if not self.log.exists():
            return []
        return [ln for ln in self.log.read_text().splitlines() if ln.startswith(kind + " ")]

    def record(self, name: str) -> dict:
        return json.loads((self.state / f"{name}.json").read_text())

    def group_alive(self, pgid: int) -> bool:
        out = subprocess.run(["ps", "-A", "-o", "pgid=,stat="], capture_output=True, text=True).stdout
        return any(ln.split()[0] == str(pgid) and not ln.split()[1].startswith("Z") for ln in out.splitlines() if ln.split())

    def cleanup(self) -> None:
        for c in self.children:
            try:
                os.killpg(c.pid, signal.SIGKILL)
            except OSError:
                pass
            c.wait()


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    e.cleanup()


def start(env: Env, name: str, *args: str, now: float = T0) -> subprocess.CompletedProcess:
    return env.run("start", name, "--owner", "owner-1", *args, now=now)


def test_budget_expiry_soft_then_hard_group_killed_recovery_once(env):
    c = env.child()
    time.sleep(0.3)   # let the shell start its background sleep
    assert start(env, "job", "--budget", "10", "--grace", "5", "--pid", str(c.pid), "--on-expire", "relay").returncode == 0
    assert env.run("sweep", "--no-agents", now=T0 + 5).stdout == ""
    assert c.poll() is None
    r = env.run("sweep", "--no-agents", now=T0 + 11)
    assert "soft stop" in r.stdout and env.record("job")["state"] == "stopping"
    assert c.poll() is None and env.group_alive(c.pid), "SIGTERM is ignored by the child, so it must still be alive inside the grace"
    assert env.run("sweep", "--no-agents", now=T0 + 14).stdout == "" and env.record("job")["state"] == "stopping", "within grace: quiet, still stopping"
    assert "within grace" in env.run("sweep", "--no-agents", "--dry-run", now=T0 + 14).stdout
    r = env.run("sweep", "--no-agents", now=T0 + 17)
    assert "hard kill" in r.stdout
    c.wait(timeout=5)
    assert not env.group_alive(c.pid), "the whole process group must be dead, grandchildren included"
    rec = env.record("job")
    assert rec["state"] == "expired" and rec["recovery"]["state"] == "done"
    assert len(env.calls("RELAY")) == 1 and "owner-1" in env.calls("RELAY")[0] and "budget exceeded" in env.log.read_text()
    env.run("sweep", "--no-agents", now=T0 + 500)
    assert len(env.calls("RELAY")) == 1, "recovery runs once"


def test_polite_child_stops_on_sigterm_and_recovers_in_the_same_pass(env):
    c = env.child("sleep 60")
    assert start(env, "polite", "--budget", "10", "--pid", str(c.pid)).returncode == 0
    r = env.run("sweep", "--no-agents", now=T0 + 11)
    assert "stopped" in r.stdout and env.record("polite")["state"] == "expired"
    assert len(env.calls("PING")) == 1 and env.calls("RELAY") == [], "kill action: Hermes ping, no owner relay when something was killed"
    c.wait(timeout=5)


def test_heartbeat_staleness_and_beat_carries_checkpoint(env):
    c = env.child("sleep 60")
    cp = str(env.tmp / "state.json")
    assert start(env, "hb", "--budget", "1000", "--heartbeat", "30", "--pid", str(c.pid), "--on-expire", "relay").returncode == 0
    assert env.run("sweep", "--no-agents", now=T0 + 20).stdout == ""
    assert env.run("beat", "hb", "--checkpoint", cp, now=T0 + 25).returncode == 0
    assert env.run("sweep", "--no-agents", now=T0 + 50).stdout == "", "25 s since the beat is inside the 30 s heartbeat"
    r = env.run("sweep", "--no-agents", now=T0 + 60)
    assert "no heartbeat" in r.stdout and env.record("hb")["state"] == "expired"
    assert cp in env.log.read_text(), "the recovery message names the last checkpoint"
    c.wait(timeout=5)


def test_extension_allowed_capped_and_refused_after_expiry(env):
    assert start(env, "ext", "--budget", "10", "--on-expire", "relay").returncode == 0
    assert env.run("extend", "ext", "--by", "6", "--reason", "slow reviewer", now=T0 + 8).returncode == 0
    assert env.run("sweep", "--no-agents", now=T0 + 12).stdout == "", "extended: 16 s budget"
    r = env.run("extend", "ext", "--by", "6", "--reason", "again", now=T0 + 13)
    assert r.returncode == 2 and "cap" in r.stderr, "cap defaults to the original budget (10 s): 6 + 6 refused"
    assert env.run("extend", "ext", "--by", "4", "--reason", "fits", now=T0 + 13).returncode == 0
    assert env.run("extend", "ext", "--by", "1", "--reason", "late", now=T0 + 25).returncode == 2, "past the 20 s budget: refused"
    assert start(env, "late", "--budget", "10", "--on-expire", "relay").returncode == 0
    r = env.run("extend", "late", "--by", "1", "--reason", "too late", now=T0 + 11)
    assert r.returncode == 2 and "BEFORE expiry" in r.stderr
    env.run("sweep", "--no-agents", now=T0 + 30)
    assert env.record("late")["state"] == "expired" and env.record("late")["extended_s"] == 0


def test_pid_reuse_is_never_signalled(env):
    c = env.child("sleep 60")
    assert start(env, "reuse", "--budget", "10", "--pid", str(c.pid), "--on-expire", "relay").returncode == 0
    p = env.state / "reuse.json"
    rec = json.loads(p.read_text())
    rec["pid_start"] = "a different start time"   # what a recycled pid would look like
    rec["pgid_start"] = "a different start time"
    p.write_text(json.dumps(rec))
    r = env.run("sweep", "--no-agents", now=T0 + 50)
    assert "lost (reused)" in r.stdout and env.record("reuse")["state"] == "lost"
    assert c.poll() is None and env.group_alive(c.pid), "a process with another start time must survive"
    assert len(env.calls("RELAY")) == 1 and "deadline reuse:" in env.log.read_text()


def test_lost_process_notifies_owner_once(env):
    c = env.child("sleep 60")
    assert start(env, "gone", "--budget", "1000", "--pid", str(c.pid)).returncode == 0
    os.killpg(c.pid, signal.SIGKILL)
    c.wait()
    assert "lost (gone)" in env.run("sweep", "--no-agents", now=T0 + 5).stdout
    env.run("sweep", "--no-agents", now=T0 + 10)
    assert len(env.calls("RELAY")) == 1 and env.record("gone")["state"] == "lost"


def test_run_returns_rc_and_deregisters(env):
    r = env.run("run", "--budget", "30", "--name", "quick", "--owner", "o", "--", "sh", "-c", "exit 3", now=None, DEADLINE_RUN_POLL="0.05")
    assert r.returncode == 3
    assert env.record("quick")["state"] == "done" and env.record("quick")["rc"] == 3


def test_run_backstop_kills_group_and_returns_124(env):
    t = time.monotonic()
    r = env.run("run", "--budget", "1", "--grace", "1", "--name", "slow", "--owner", "o", "--on-expire", "relay", "--",
                "sh", "-c", "trap '' TERM; sleep 60 & sleep 60; wait", now=None, DEADLINE_RUN_POLL="0.1")
    assert r.returncode == 124 and time.monotonic() - t < 20
    rec = env.record("slow")
    assert rec["state"] == "expired" and rec["recovery"]["state"] == "done" and rec["hard_at"]
    assert not env.group_alive(rec["pgid"])
    assert len(env.calls("RELAY")) == 1


def test_corrupt_record_does_not_stop_the_sweep(env):
    env.state.mkdir(parents=True)
    (env.state / "bad.json").write_text("{not json")
    (env.state / "wrongname.json").write_text(json.dumps({"name": "other"}))
    assert start(env, "good", "--budget", "5", "--on-expire", "relay").returncode == 0
    r = env.run("sweep", "--no-agents", now=T0 + 10)
    assert r.returncode == 0 and "bad: corrupt record quarantined" in r.stdout
    assert env.record("good")["state"] == "expired"
    assert "corrupt" in env.run("ls").stdout


def test_dry_run_changes_nothing(env):
    assert start(env, "dry", "--budget", "5", "--on-expire", "relay").returncode == 0
    r = env.run("sweep", "--dry-run", "--no-agents", now=T0 + 10)
    assert "would stop" in r.stdout and env.record("dry")["state"] == "running" and env.calls("RELAY") == []


def test_reroute_action_runs_acp_dispatch_once(env):
    assert start(env, "rr", "--budget", "5", "--on-expire", "reroute:/x/jobs/rec.json").returncode == 0
    env.run("sweep", "--no-agents", now=T0 + 10)
    env.run("sweep", "--no-agents", now=T0 + 20)
    d = env.calls("DISPATCH")
    assert len(d) == 1 and "reroute /x/jobs/rec.json --escalate --detach --no-wait" in d[0]


def test_duplicate_live_name_refused_and_terminal_name_reusable(env):
    assert start(env, "dup", "--budget", "50", "--on-expire", "notify").returncode == 0
    assert start(env, "dup", "--budget", "50", "--on-expire", "notify").returncode == 2
    assert env.run("done", "dup").returncode == 0
    assert start(env, "dup", "--budget", "50", "--on-expire", "notify").returncode == 0
    assert env.run("beat", "nope").returncode == 1


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def test_agent_idle_alerts_once_per_hour_and_never_kills(env):
    agents = [{"id": f"{c}" * 8 + "-0000", "shortId": c * 7, "name": f"agent {c}", "status": "running"} for c in "abcd"]
    agents.append({"id": "eeeeeeee-0000", "shortId": "eeeeeee", "name": "idle one", "status": "idle"})
    (env.tmp / "ls.json").write_text(json.dumps(agents))
    upd = {"a": T0 - 40 * 60, "b": T0 - 5 * 60, "c": T0 - 90 * 60}   # d: no UpdatedAt at all
    for c, ts in upd.items():
        (env.paseo_dir / f"{c * 8}-0000.json").write_text(json.dumps({"UpdatedAt": iso(ts), "Status": "running"}))
    (env.paseo_dir / "dddddddd-0000.json").write_text(json.dumps({"Status": "running"}))
    # agent c holds a live deadline record: owner is its id
    assert env.run("start", "cjob", "--owner", "cccccccc-0000", "--budget", "100000", "--on-expire", "notify", now=T0).returncode == 0
    r = env.run("sweep", "--agents-now", now=T0 + 1)
    relays = env.calls("RELAY")
    assert len(relays) == 1 and relays[0].startswith("RELAY aaaaaaaa-0000 --message-file -"), (relays, r.stdout, r.stderr)
    assert len(env.calls("PING")) == 1 and "no progress for 40 min" in env.calls("PING")[0]
    assert "if a command hangs, stop it" in env.log.read_text()
    env.run("sweep", "--agents-now", now=T0 + 600)
    assert len(env.calls("RELAY")) == 1, "at most once per agent per hour"
    env.run("sweep", "--agents-now", now=T0 + 3700)   # an hour on: a is re-alerted, and b is now idle too
    assert [ln.split()[1] for ln in env.calls("RELAY")] == ["aaaaaaaa-0000", "aaaaaaaa-0000", "bbbbbbbb-0000"]
    assert not [ln for ln in env.calls("PASEO") if ln.split()[1] not in ("ls", "inspect")], "alert only: never stop, delete or send through paseo"
    ls = env.run("ls", "--agents", now=T0 + 1).stdout
    assert "skipped: last activity unreadable" in ls and "holds a deadline" in ls


def test_agent_scan_is_throttled_without_force(env):
    (env.tmp / "ls.json").write_text(json.dumps([{"id": "aaaaaaaa-0000", "shortId": "aaaaaaa", "name": "x", "status": "running"}]))
    (env.paseo_dir / "aaaaaaaa-0000.json").write_text(json.dumps({"UpdatedAt": iso(T0 - 7200)}))
    env.run("sweep", now=T0)
    n = len(env.calls("PASEO"))
    env.run("sweep", now=T0 + 60)
    assert len(env.calls("PASEO")) == n, "second sweep inside 5 min must not call paseo again"


def test_install_dry_run_renders_a_valid_plist(env, tmp_path):
    ade = tmp_path / "ade"
    (ade / "bin").mkdir(parents=True)
    (ade / "config/launchd").mkdir(parents=True)
    shutil.copy(SCRIPT, ade / "bin/deadline")
    shutil.copy(ROOT / "config/launchd/com.djbclark.deadline-sweep.plist", ade / "config/launchd/")
    r = env.run("install", "--ade", str(ade), "--dry-run")
    assert r.returncode == 0, r.stderr
    p = plistlib.loads(r.stdout.encode())
    assert p["Label"] == "com.djbclark.deadline-sweep" and p["StartInterval"] == 60
    assert p["ProgramArguments"] == [f"{ade.resolve()}/bin/deadline", "sweep"] and "__" not in r.stdout


# ---------- PR 223 adversary round 1: failed kill, run/sweep race, start-time and ancestry guards, names ----------

def load_module():
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader("deadline_mod", str(SCRIPT))
    spec = importlib.util.spec_from_loader("deadline_mod", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


@pytest.fixture
def inproc(env, monkeypatch):
    for k, v in env.base.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("DEADLINE_NOW", str(T0))
    monkeypatch.setenv("DEADLINE_SETTLE_S", "0.05")
    return load_module()


def test_failed_kill_is_not_a_stop_and_owner_is_told(env, inproc):
    # pid 1 is alive with a readable start time but is never signalled (unsafe target): the stop FAILS.
    dl = inproc
    info = dl.proc_info(1)
    assert info, "pid 1 must be readable for this test"
    rec = {"name": "stuck", "owner": "owner-1", "pid": 1, "pgid": None, "pid_start": info[0], "pgid_start": None,
           "started": T0 - 100, "last_beat": T0 - 100, "budget_s": 10, "grace_s": 5, "on_expire": "kill", "state": "running"}
    dl.save(rec)
    out = dl.step(rec)
    assert "KILL FAILED" in out and rec["state"] == "kill-failed" and rec["recovery"]["state"] == "done"
    relays = env.calls("RELAY")
    assert len(relays) == 1 and "COULD NOT BE STOPPED" in env.log.read_text() and "stopped by the enforcer" not in env.log.read_text()
    assert dl.step(rec) == "kill-failed: still alive" and len(env.calls("RELAY")) == 1, "told once, retried silently"
    assert dl.quiet("kill-failed: still alive")
    assert dl.registrar_alive(rec) is False
    # the operator acknowledges it with `done`, which frees the name
    assert env.run("done", "stuck").returncode == 0 and env.record("stuck")["state"] == "done"


def test_survivor_of_sigkill_is_kill_failed_not_expired(env, inproc, monkeypatch):
    dl = inproc
    rec = {"name": "tough", "owner": "owner-1", "pid": 4242, "pgid": None, "pid_start": "x", "started": T0 - 100, "last_beat": T0 - 100,
           "budget_s": 10, "grace_s": 5, "on_expire": "relay", "state": "stopping", "soft_at": T0 - 50, "stopped_by_us": True}
    dl.save(rec)
    monkeypatch.setattr(dl, "target_status", lambda r: "alive")
    monkeypatch.setattr(dl, "signal_target", lambda r, s: ("sent", "signal 9"))
    monkeypatch.setattr(dl, "settle", lambda r, secs: False)
    assert "KILL FAILED" in dl.step(rec) and rec["state"] == "kill-failed"
    assert "still alive after SIGKILL" in env.log.read_text() and len(env.calls("RELAY")) == 1


def test_run_child_exit_before_registrar_polls_is_not_lost(env, inproc, monkeypatch):
    # the child has exited and is an unreaped zombie; its `run` registrar is alive and has not polled yet
    dl = inproc
    c = subprocess.Popen(["sleep", "0.2"], start_new_session=True)
    start_tok = dl.proc_info(c.pid)[0]
    reg = dl.proc_info(os.getpid())
    rec = {"name": "racy", "owner": "owner-1", "pid": c.pid, "pgid": c.pid, "pid_start": start_tok, "pgid_start": start_tok, "started": T0,
           "last_beat": T0, "budget_s": 1000, "grace_s": 5, "on_expire": "kill", "state": "running", "kind": "run",
           "registrar_pid": os.getpid(), "registrar_start": reg[0]}
    dl.save(rec)
    time.sleep(0.6)
    assert dl.target_status(rec) == "gone"
    assert dl.step(rec) == "ok" and rec["state"] == "running" and env.calls("RELAY") == [], "no false lost while the registrar lives"
    rec["registrar_start"] = "another process now"   # the `run` itself died: nobody will record the rc
    assert "lost" in dl.step(rec) and rec["state"] == "lost"
    c.wait()


def test_run_exit_code_of_a_signalled_child_is_128_plus_n(env):
    r = env.run("run", "--budget", "30", "--name", "sig", "--owner", "o", "--", "sh", "-c", "kill -KILL $$", now=None, DEADLINE_RUN_POLL="0.05")
    assert r.returncode == 137


def test_run_returns_124_when_the_sweep_did_the_stopping(env, inproc):
    dl = inproc
    assert dl.exit_code(-9) == 137 and dl.exit_code(3) == 3 and dl.exit_code(0) == 0


def test_start_refuses_a_pid_whose_start_time_cannot_be_read(env):
    r = start(env, "ghost", "--budget", "10", "--pid", "999999")
    assert r.returncode == 2 and ("not running" in r.stderr or "refusing to register" in r.stderr)
    assert not (env.state / "ghost.json").exists()


def test_record_without_a_start_time_is_never_signalled(env):
    c = env.child("sleep 60")
    assert start(env, "nostart", "--budget", "10", "--pid", str(c.pid), "--on-expire", "relay").returncode == 0
    p = env.state / "nostart.json"
    rec = json.loads(p.read_text())
    rec["pid_start"] = None
    rec["pgid_start"] = None
    p.write_text(json.dumps(rec))
    r = env.run("sweep", "--no-agents", now=T0 + 50)
    assert "lost (unverified)" in r.stdout and env.record("nostart")["state"] == "lost"
    assert c.poll() is None and env.group_alive(c.pid), "no recorded start time: never signalled"


def test_start_refuses_the_callers_own_ancestry_group_and_mismatched_group(env):
    me = os.getpid()   # the pytest process is the parent (an ancestor) of the `deadline start` it launches
    r = start(env, "self", "--budget", "10", "--pid", str(me))
    assert r.returncode == 2 and "ancestor" in r.stderr
    r = start(env, "mygroup", "--budget", "10", "--pgid", str(os.getpgrp()))
    assert r.returncode == 2 and "caller" in r.stderr
    c = env.child("sleep 60")
    r = start(env, "mismatch", "--budget", "10", "--pid", str(c.pid), "--pgid", str(os.getpgrp()))
    assert r.returncode == 2
    r = start(env, "mismatch2", "--budget", "10", "--pid", str(c.pid), "--pgid", str(c.pid + 1))
    assert r.returncode == 2 and "not in process group" in r.stderr
    assert not list(env.state.glob("*.json"))


def test_kill_with_nothing_to_kill_is_refused_but_announce_only_is_named(env):
    r = start(env, "waitonly", "--budget", "10")
    assert r.returncode == 2 and "nothing to kill" in r.stderr
    assert start(env, "waitonly", "--budget", "10", "--on-expire", "notify").returncode == 0


def test_reserved_and_hidden_names_are_refused(env):
    for name in ("agents", ".hidden", "-x", "a/b"):
        assert start(env, name, "--budget", "10", "--on-expire", "notify").returncode == 2, name
    assert env.run("run", "--budget", "5", "--name", "agents", "--", "true", now=None).returncode == 2


def test_record_missing_keys_does_not_crash_ls_or_sweep_and_is_reported_once(env):
    env.state.mkdir(parents=True)
    (env.state / "half.json").write_text(json.dumps({"name": "half"}))
    (env.state / "bad.json").write_text("{nope")
    r = env.run("ls")
    assert r.returncode == 0 and "corrupt" in r.stdout
    first = env.run("sweep", "--no-agents", now=T0 + 10)
    assert first.returncode == 0 and "quarantined" in first.stdout
    assert (env.state / "half.json.corrupt").exists() and not (env.state / "half.json").exists()
    assert env.run("sweep", "--no-agents", now=T0 + 70).stdout == "", "a corrupt record is not logged again every minute"
    assert "quarantined" in env.run("ls").stdout


def test_orphan_lock_files_are_pruned(env):
    assert start(env, "tmp1", "--budget", "10", "--on-expire", "notify").returncode == 0
    assert env.run("done", "tmp1").returncode == 0
    (env.state / "tmp1.json").unlink()
    env.run("sweep", "--no-agents")
    assert not (env.state / ".tmp1.lock").exists()


# ---------- PR 223 local-review round 1: group identity, notice delivery, name reservation, registration binding, background agents ----------

def test_leaderless_group_is_anchored_on_a_live_member_and_never_trusted_bare(env):
    c = subprocess.Popen(["sh", "-c", "sleep 60 & sleep 61 & exit 0"], start_new_session=True)
    env.children.append(c)
    c.wait()   # the group leader is gone and reaped; its sleep lives on in the group
    time.sleep(0.2)
    assert env.group_alive(c.pid)
    assert start(env, "leaderless", "--budget", "10", "--pgid", str(c.pid), "--on-expire", "relay").returncode == 0
    rec = env.record("leaderless")
    assert rec["pid"] and rec["pid"] != c.pid and rec["pid_start"] and rec["pgid_start"] is None, "anchored on a member's pid + start time"
    os.kill(rec["pid"], signal.SIGKILL)   # the anchor dies; the group id could now be recycled by anything
    time.sleep(0.3)
    r = env.run("sweep", "--no-agents", now=T0 + 50)
    assert "lost (unverified)" in r.stdout and env.record("leaderless")["state"] == "lost", "never trust a bare group id"


def test_failed_owner_notice_is_retried_until_delivered_not_marked_done(env):
    Path(env.base["DL_RELAY_FAIL"]).write_text("1")
    assert start(env, "flaky", "--budget", "5", "--on-expire", "relay").returncode == 0
    env.run("sweep", "--no-agents", now=T0 + 10)
    rec = env.record("flaky")
    assert rec["state"] == "expired" and rec["notice"]["done"] is False and rec["notice"]["attempts"] == 1
    env.run("sweep", "--no-agents", now=T0 + 30)
    assert len(env.calls("RELAY")) == 1, "retries are spaced 60 s * attempt"
    Path(env.base["DL_RELAY_FAIL"]).unlink()
    r = env.run("sweep", "--no-agents", now=T0 + 100)
    assert "owner notice retry 2" in r.stdout
    assert env.record("flaky")["notice"]["done"] is True and len(env.calls("RELAY")) == 2
    env.run("sweep", "--no-agents", now=T0 + 1000)
    assert len(env.calls("RELAY")) == 2, "delivered once: no more"


def test_notice_retries_are_bounded(env):
    Path(env.base["DL_RELAY_FAIL"]).write_text("3")   # 3 = unverified under --ack: not delivery proof
    assert start(env, "never", "--budget", "5", "--on-expire", "relay").returncode == 0
    for i in range(20):
        env.run("sweep", "--no-agents", now=T0 + 10 + i * 1000)
    assert len(env.calls("RELAY")) == 5 and env.record("never")["notice"]["attempts"] == 5


def test_run_with_a_taken_name_never_starts_the_command(env):
    assert start(env, "taken", "--budget", "100", "--on-expire", "notify").returncode == 0
    mark = env.tmp / "ran"
    r = env.run("run", "--budget", "30", "--name", "taken", "--", "sh", "-c", f"touch {mark}", now=None)
    assert r.returncode == 2 and not mark.exists(), "an irreversible command must not run before the name is reserved"


def test_old_run_cannot_finish_a_record_that_replaced_its_own(env):
    p = subprocess.Popen([sys.executable, str(SCRIPT), "run", "--budget", "1", "--name", "rebind", "--owner", "o", "--on-expire", "notify",
                          "--", "sh", "-c", "sleep 4"],
                         env={**os.environ, **env.base, "DEADLINE_RUN_POLL": "0.1"}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            time.sleep(0.25)
            if (env.state / "rebind.json").exists() and env.record("rebind")["state"] == "expired":
                break
        assert env.record("rebind")["state"] == "expired"   # announced only; the child still runs
        assert start(env, "rebind", "--budget", "1000", "--on-expire", "notify", now=None).returncode == 0
        new_id = env.record("rebind")["reg_id"]
        p.wait(timeout=30)
        rec = env.record("rebind")
        assert rec["state"] == "running" and rec["reg_id"] == new_id, "the old run must not mark the new registration done"
    finally:
        p.kill()
        p.wait()


def test_agent_scan_includes_background_workspaces(env):
    env.run("sweep", "--agents-now", now=T0)
    assert any(ln == "PASEO ls -g --background --json" for ln in env.calls("PASEO"))


# ---------- PR 223 local-review round 2: survivors after the leader, unverifiable stops, relay sender + proof, lock inodes, prune race ----------

def test_run_keeps_enforcing_until_the_group_is_stopped_after_the_leader_exits(env):
    # the leader dies on SIGTERM; a grandchild ignores it and must still get its SIGKILL and the recovery from `run` itself
    r = env.run("run", "--budget", "1", "--grace", "1", "--name", "orphans", "--owner", "o", "--on-expire", "relay", "--",
                "sh", "-c", "(trap '' TERM; sleep 60) & wait", now=None, DEADLINE_RUN_POLL="0.1")
    assert r.returncode == 124
    rec = env.record("orphans")
    assert rec["state"] == "expired" and rec["hard_at"] and rec["recovery"]["state"] == "done"
    assert not env.group_alive(rec["pgid"]), "no survivor of the process group may outlive `run`"
    assert len(env.calls("RELAY")) == 1


def test_an_unverifiable_target_is_never_a_confirmed_stop(env, inproc, monkeypatch):
    dl = inproc
    monkeypatch.setattr(dl, "target_status", lambda r: "unverified")
    assert dl.settle({}, 0.2) is False
    rec = {"name": "anchorless", "owner": "owner-1", "pid": 4242, "pgid": 4242, "pid_start": "x", "started": T0 - 100, "last_beat": T0 - 100,
           "budget_s": 10, "grace_s": 5, "on_expire": "reroute:/x/jobs/r.json", "state": "stopping", "soft_at": T0 - 1, "stopped_by_us": True}
    dl.save(rec)
    out = dl.step(rec)
    assert "KILL FAILED" in out and rec["state"] == "kill-failed" and env.calls("DISPATCH") == [], "no reroute while survivors may run"
    assert "identity can no longer be verified" in env.log.read_text()
    assert dl.step(rec) == "kill-failed: still alive (unverifiable)"


def test_an_empty_group_with_no_leader_start_is_gone_not_unverified(env, inproc):
    dl = inproc
    assert dl.target_status({"pid": None, "pgid": 987654, "pgid_start": None}) == "gone"


def test_owner_relay_declares_a_sender_and_asks_for_delivery_proof(env):
    assert start(env, "proof", "--budget", "5", "--on-expire", "relay").returncode == 0
    env.run("sweep", "--no-agents", now=T0 + 10)
    log = env.log.read_text()
    assert "RELAY owner-1 --message-file - --ack --wait 20" in log and "SENDER deadline" in log
    p = __import__("plistlib").loads((ROOT / "config/launchd/com.djbclark.deadline-sweep.plist").read_text().replace("__HOME__", "/h").replace("__ADE__", "/a").encode())
    assert p["EnvironmentVariables"]["RELAY_SENDER_NAME"] == "deadline-sweep", "a launchd job has no session: relay.py would refuse it with exit 4"


def test_waiting_registrar_never_holds_a_lock_on_an_unlinked_inode(env, inproc):
    import threading
    dl = inproc
    path = env.state / ".racer.lock"
    a = dl.Locked("racer")
    assert a.__enter__() is True
    got = {}

    def waiter():
        b = dl.Locked("racer", block=True)
        got["ok"] = b.__enter__()
        got["same"] = os.fstat(b.fd).st_ino == os.stat(path).st_ino
        got["lock"] = b
        got["third"] = dl.Locked("racer").__enter__()   # a third party must now be excluded by b

    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.4)   # b is blocked on the old inode
    path.unlink()     # prune removes the lock file while holding it
    a.__exit__()
    t.join(timeout=10)
    assert got["ok"] and got["same"], "b must end up holding the lock file that is on disk"
    assert got["third"] is False
    got["lock"].__exit__()


def test_prune_never_deletes_a_name_that_was_registered_again_meanwhile(env, inproc, monkeypatch):
    dl = inproc
    old = {"name": "reborn", "owner": "o", "state": "done", "started": T0 - 20 * 86400, "budget_s": 10, "ended": T0 - 10 * 86400}
    dl.save(old)
    stale = dl.all_records()
    new = {"name": "reborn", "owner": "o", "state": "running", "started": T0, "budget_s": 100, "on_expire": "notify", "reg_id": "new"}
    dl.save(new)   # re-registered after the scan, before the unlink
    monkeypatch.setattr(dl, "all_records", lambda: stale)
    dl.prune()
    assert env.record("reborn")["state"] == "running" and env.record("reborn")["reg_id"] == "new"
    old2 = dict(old, name="ancient")
    dl.save(old2)
    monkeypatch.setattr(dl, "all_records", lambda: [("ancient", old2)])
    dl.prune()
    assert not (env.state / "ancient.json").exists(), "a genuinely old terminal record is still pruned"


# ---------- PR 223 local-review round 3: anchor left its group, ps failures, startup handshake, async recovery ----------

def test_a_live_anchor_that_left_the_group_does_not_vouch_for_it(env, inproc):
    dl = inproc
    c = env.child("sleep 60")   # its own session: pgid == its pid
    time.sleep(0.2)
    rec = {"name": "left", "owner": "o", "pid": c.pid, "pgid": 987654, "pid_start": dl.proc_info(c.pid)[0], "pgid_start": None,
           "started": T0, "budget_s": 10, "state": "running"}
    assert dl.target_status(rec) == "unverified"
    outcome, text = dl.signal_target(rec, signal.SIGKILL)
    assert outcome == "failed" and c.poll() is None, "never killpg an id the anchor no longer belongs to"


def test_a_failed_ps_read_is_unknown_not_gone(env, inproc, monkeypatch):
    dl = inproc

    def fake(rc, out="", err=""):
        return lambda *a, **k: subprocess.CompletedProcess(a[0], rc, out, err)

    monkeypatch.setattr(dl.subprocess, "run", fake(2, "", "ps: Operation not permitted"))
    for call in (lambda: dl.proc_info(424242), lambda: dl.group_members(424242), lambda: dl.ancestors()):
        with pytest.raises(dl.ProcUnknown):
            call()
    monkeypatch.setattr(dl.subprocess, "run", fake(1, "", ""))   # `ps -p PID` for a pid that does not exist
    assert dl.proc_info(424242) is None
    monkeypatch.setattr(dl.subprocess, "run", fake(1, "", "ps: illegal option"))
    with pytest.raises(dl.ProcUnknown):
        dl.proc_info(424242)


def test_run_that_dies_before_the_release_never_runs_the_command(env):
    mark = env.tmp / "must-not-exist"
    r = env.run("run", "--budget", "30", "--name", "handshake", "--owner", "o", "--", "sh", "-c", f"touch {mark}; sleep 30",
                now=None, DEADLINE_TEST_ABORT_BEFORE_GO="1")
    assert r.returncode == 9
    time.sleep(1.5)   # the waiting child sees EOF on the pipe and exits 111
    assert not mark.exists()
    ps = subprocess.run(["ps", "-A", "-o", "command="], capture_output=True, text=True).stdout
    assert str(mark) not in ps, "the held child must be gone, not left waiting"


def test_recovery_io_runs_off_the_enforcement_pass(env):
    Path(env.base["DL_RELAY_SLEEP"]).write_text("3")
    assert start(env, "slowio", "--budget", "5", "--on-expire", "relay").returncode == 0
    t = time.monotonic()
    r = env.run("sweep", "--no-agents", now=T0 + 10, DEADLINE_INLINE_WORKER="0")
    assert time.monotonic() - t < 2.5, "the sweep must not wait for the 3 s relay"
    assert "expired" in r.stdout
    for _ in range(60):
        time.sleep(0.25)
        if env.record("slowio").get("recovery", {}).get("state") == "done":
            break
    rec = env.record("slowio")
    assert rec["recovery"]["state"] == "done" and rec["notice"]["done"] is True and len(env.calls("RELAY")) == 1
