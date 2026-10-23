"""bin/claude-quota-guard and claude/hooks/quota_nudge.py (2026-10-23).

Everything runs against fakes: a script standing in for aiuse (prints a fixture, exits N), a
snapshot directory, a fake hermes-ping that appends its argv to a file, a temp HOME. Nothing
here reads the real aiuse cache, pings, or touches launchd.
"""
import importlib.machinery
import importlib.util
import json
import os
import plistlib
import stat
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
GUARD = REPO / "bin" / "claude-quota-guard"
HOOK = REPO / "claude" / "hooks" / "quota_nudge.py"

NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)
WEEK_RESET = (NOW + timedelta(days=3)).isoformat()
FIVE_RESET = (NOW + timedelta(hours=3)).isoformat()


def _window(label, left, resets_at, **extra):
    return {"label": label, "used_percent": 100 - left, "remaining_percent": left,
            "resets_at": resets_at, "pace_percent": -5, **extra}


def aiuse_fixture(weekly=80.0, five=90.0, fable=97.0, week_reset=WEEK_RESET, with_claude=True):
    shared = [_window("Claude Code 5-hour", five, FIVE_RESET, pool_family="default", quota_scope="shared"),
              _window("Claude Code weekly", weekly, week_reset, pool_family="default", quota_scope="shared")]
    fable_w = _window("Claude Code weekly \u2014 Fable", fable, week_reset, pool_family="fable",
                      quota_scope="model_sublimit")
    rows = [{"provider": "codex", "windows": [_window("Codex 5-hour", 50, FIVE_RESET)]}]
    if with_claude:
        rows += [{"provider": "claude", "pool_family": "default", "windows": shared},
                 {"provider": "claude", "pool_family": "fable", "windows": shared + [fable_w]}]
    return {"schema_version": "1.4", "available": rows}


def alert(message, window_label="Claude Code weekly", provider="claude", kind="conserve"):
    return {"kind": kind, "provider": provider, "window_label": window_label, "message": message,
            "remaining_percent": 34.0, "urgency": "high"}


PROJECTED = "claude \u00b7 Claude Code weekly: pace yourself \u2014 projected to run out ~1 day before reset (34% left)"


class Rig:
    """A temp HOME with fake aiuse, snapshots, ping and state paths, and a way to run the tools."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.home = tmp / "home"
        self.home.mkdir()
        self.snaps = tmp / "snaps"
        self.snaps.mkdir()
        self.state = tmp / "state" / "quota-guard.json"
        self.nudges = tmp / "nudges.json"
        self.ping_log = tmp / "pings.log"
        self.aiuse = tmp / "aiuse"
        self.ping = tmp / "hermes-ping"
        self.launch_agents = tmp / "LaunchAgents"
        self.launchctl_log = tmp / "launchctl.log"
        self.fakebin = tmp / "fakebin"
        self.fakebin.mkdir()
        self._script(self.fakebin / "launchctl", f'echo "$@" >> {self.launchctl_log}\n')
        self.set_ping_ok()
        self.set_aiuse(aiuse_fixture())
        self.now = NOW

    @staticmethod
    def _script(path: Path, body: str):
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def set_aiuse(self, fixture, rc=0):
        data = self.tmp / "aiuse.json"
        data.write_text(fixture if isinstance(fixture, str) else json.dumps(fixture))
        self._script(self.aiuse, f'[ "$1" = "--available" ] && [ "$2" = "--json" ] || exit 64\n'
                                 f'cat {data}\nexit {rc}\n')

    def set_ping_ok(self):
        self._script(self.ping, f'printf "%s\\n" "$1" >> {self.ping_log}\n')

    def set_ping_failing(self):
        self._script(self.ping, "exit 7\n")

    def set_alerts(self, alerts, age_s=60):
        for f in self.snaps.glob("*.json"):
            f.unlink()
        snap = self.snaps / "2026-10-23T115900.000000Z.json"
        snap.write_text(json.dumps({"alerts": alerts}))
        t = self.now.timestamp() - age_s
        os.utime(snap, (t, t))

    def pings(self):
        return self.ping_log.read_text().splitlines() if self.ping_log.exists() else []

    def env(self, **over):
        env = {"HOME": str(self.home), "PATH": f"{self.fakebin}:/usr/bin:/bin",
               "CLAUDE_QUOTA_GUARD_AIUSE": str(self.aiuse),
               "CLAUDE_QUOTA_GUARD_SNAPSHOTS": str(self.snaps),
               "CLAUDE_QUOTA_GUARD_STATE": str(self.state),
               "CLAUDE_QUOTA_GUARD_PING": str(self.ping),
               "CLAUDE_QUOTA_GUARD_LAUNCH_AGENTS": str(self.launch_agents),
               "CLAUDE_QUOTA_NUDGE_STATE": str(self.nudges),
               "CLAUDE_QUOTA_GUARD_NOW": self.now.isoformat()}
        env.update(over)
        return env

    def guard(self, *args, **env_over):
        return subprocess.run([sys.executable, "-I", str(GUARD), *args], env=self.env(**env_over),
                              capture_output=True, text=True, timeout=60)

    def state_json(self):
        return json.loads(self.state.read_text())

    def hook(self, session="s1", stdin=None, **env_over):
        payload = json.dumps({"session_id": session}) if stdin is None else stdin
        return subprocess.run([sys.executable, str(HOOK)], input=payload, env=self.env(**env_over),
                              capture_output=True, text=True, timeout=30)


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


# -- levels -----------------------------------------------------------------

@pytest.mark.parametrize("fixture_kw, alerts, level, code", [
    (dict(weekly=80), [], "ok", 0),
    (dict(weekly=40), [], "ok", 0),                       # the threshold itself is not "under"
    (dict(weekly=39), [], "watch", 1),
    (dict(weekly=30), [], "watch", 1),
    (dict(weekly=29), [], "tight", 2),
    (dict(weekly=15), [], "tight", 2),
    (dict(weekly=14), [], "critical", 3),
    (dict(weekly=80, five=9), [], "critical", 3),         # 5-hour alone is enough
    (dict(weekly=80, five=10), [], "ok", 0),
    (dict(weekly=80, fable=10), [], "watch", 1),          # Fable's sublimit row counts
    (dict(weekly=80, fable=60), [], "ok", 0),
    (dict(weekly=80), [alert("pace yourself")], "watch", 1),
    (dict(weekly=60), [alert(PROJECTED)], "tight", 2),    # projected to run out before reset
    (dict(weekly=60), [alert(PROJECTED, window_label="Claude Code 5-hour")], "watch", 1),
    (dict(weekly=80), [alert("x", provider="codex")], "ok", 0),
    (dict(weekly=80), [alert("x", kind="exhausted")], "ok", 0),
])
def test_levels_and_exit_codes(rig, fixture_kw, alerts, level, code):
    rig.set_aiuse(aiuse_fixture(**fixture_kw))
    rig.set_alerts(alerts)
    r = rig.guard()
    assert r.returncode == code, r.stderr
    st = rig.state_json()
    assert st["level"] == level
    if level == "ok":
        assert st["advice"] == ""
    else:
        assert "acp-dispatch omp --model anthropic/claude-opus-5-5 --kind judgment --effort high" in st["advice"]
        assert "no Fable or Opus Agent-tool sub-agents" in st["advice"]
    assert st["weekly_left"] == fixture_kw.get("weekly", 80.0)
    assert st["resets_at"] in (WEEK_RESET, FIVE_RESET)
    assert st["snapshot_age_s"] == 60


def test_advice_grows_with_level(rig):
    rig.set_aiuse(aiuse_fixture(weekly=25))
    assert rig.guard().returncode == 2
    tight = rig.state_json()["advice"]
    assert "--finish --successor claude/claude-sonnet-5-5 --thinking high" in tight
    assert "No `acp-dispatch claude` slices" in tight
    assert "until the reset" not in tight
    rig.set_aiuse(aiuse_fixture(weekly=5))
    assert rig.guard().returncode == 3
    crit = rig.state_json()["advice"]
    assert "--finish --successor" in crit
    assert f"No new Claude work of any kind until the reset at {WEEK_RESET}" in crit


def test_five_hour_critical_names_the_five_hour_reset(rig):
    rig.set_aiuse(aiuse_fixture(weekly=80, five=4))
    assert rig.guard().returncode == 3
    st = rig.state_json()
    assert st["resets_at"] == FIVE_RESET and st["five_hour_left"] == 4
    assert st["weekly_left"] == 80 and st["fable_left"] == 97


def test_state_carries_every_documented_field(rig):
    rig.set_aiuse(aiuse_fixture(weekly=35))
    rig.guard()
    st = rig.state_json()
    assert {"level", "weekly_left", "five_hour_left", "fable_left", "resets_at", "pace", "advice",
            "checked_at", "snapshot_age_s", "last_pinged_level", "last_pinged_at"} <= set(st)
    assert st["pace"] == -5 and st["fable_left"] == 97 and st["five_hour_left"] == 90
    assert st["checked_at"] == "2026-10-23T12:00:00Z"


def test_stale_snapshot_alerts_are_ignored(rig):
    rig.set_aiuse(aiuse_fixture(weekly=80))
    rig.set_alerts([alert(PROJECTED)], age_s=7 * 3600)
    assert rig.guard().returncode == 0
    assert rig.state_json()["snapshot_age_s"] == 7 * 3600


def test_missing_snapshot_dir_is_not_an_error(rig):
    rig.set_aiuse(aiuse_fixture(weekly=80))
    r = rig.guard(CLAUDE_QUOTA_GUARD_SNAPSHOTS=str(rig.tmp / "nope"))
    assert r.returncode == 0 and rig.state_json()["snapshot_age_s"] is None


def test_threshold_override(rig):
    rig.set_aiuse(aiuse_fixture(weekly=50))
    assert rig.guard().returncode == 0
    r = rig.guard(CLAUDE_QUOTA_GUARD_THRESHOLDS=json.dumps({"watch_weekly": 60, "tight_weekly": 55}))
    assert r.returncode == 2
    bad = rig.guard(CLAUDE_QUOTA_GUARD_THRESHOLDS=json.dumps({"nonsense": 1}))
    assert bad.returncode not in (0, 1, 2, 3) and "unknown" in bad.stderr


# -- aiuse failures ---------------------------------------------------------

def test_aiuse_exit_3_without_claude_row_is_critical(rig):
    rig.set_aiuse(aiuse_fixture(with_claude=False), rc=3)
    r = rig.guard()
    assert r.returncode == 3
    st = rig.state_json()
    assert st["level"] == "critical" and st["weekly_left"] == 0.0


def test_aiuse_exit_3_with_prose_output_is_critical(rig):
    rig.set_aiuse("nothing usable right now\n", rc=3)
    assert rig.guard().returncode == 3


@pytest.mark.parametrize("fixture, rc", [
    (aiuse_fixture(), 1),                       # aiuse itself failed
    (aiuse_fixture(), 2),
    ("not json", 0),
    ("[]", 0),
    (aiuse_fixture(with_claude=False), 0),      # no Claude row and aiuse says things are usable
])
def test_unreadable_aiuse_exits_10_and_leaves_state_alone(rig, fixture, rc):
    rig.guard()  # a good first state
    before = rig.state.read_bytes()
    rig.set_aiuse(fixture, rc=rc)
    r = rig.guard()
    assert r.returncode == 10
    assert "state file left unchanged" in r.stderr
    assert rig.state.read_bytes() == before
    assert rig.pings() == []


def test_missing_aiuse_binary_exits_10(rig):
    r = rig.guard(CLAUDE_QUOTA_GUARD_AIUSE=str(rig.tmp / "no-such-aiuse"))
    assert r.returncode == 10 and not rig.state.exists()


# -- pings ------------------------------------------------------------------

def _run(rig, weekly, week_reset=WEEK_RESET, **kw):
    rig.set_aiuse(aiuse_fixture(weekly=weekly, week_reset=week_reset, **kw))
    return rig.guard()


def test_no_ping_on_ok(rig):
    assert _run(rig, 90).returncode == 0
    assert rig.pings() == [] and rig.state_json()["last_pinged_level"] is None


def test_ping_once_per_upward_crossing(rig):
    _run(rig, 35)                       # watch
    assert len(rig.pings()) == 1
    _run(rig, 34)                       # still watch: silent
    assert len(rig.pings()) == 1
    _run(rig, 25)                       # tight
    assert len(rig.pings()) == 2
    _run(rig, 24)                       # tight again: silent
    assert len(rig.pings()) == 2
    _run(rig, 10)                       # critical
    assert len(rig.pings()) == 3
    _run(rig, 9)
    assert len(rig.pings()) == 3
    watch, tight, critical = rig.pings()
    assert watch.startswith("djbclark-ade: Claude quota watch: weekly 35% left, resets ")
    assert "Claude quota tight: weekly 25% left" in tight
    assert "Claude quota critical: weekly 10% left" in critical
    assert "no Fable or Opus Agent-tool sub-agents" in watch      # the first advice line, no "1."
    st = rig.state_json()
    assert st["last_pinged_level"] == "critical" and st["last_pinged_at"] == "2026-10-23T12:00:00Z"


def test_a_jump_straight_to_critical_pings_once_as_critical(rig):
    _run(rig, 5)
    assert len(rig.pings()) == 1 and "quota critical" in rig.pings()[0]


def test_level_drop_is_silent_and_clears_so_a_rise_pings_again(rig):
    _run(rig, 10)                       # critical, pinged
    _run(rig, 25)                       # drop to tight: silent
    assert len(rig.pings()) == 1
    assert rig.state_json()["last_pinged_level"] == "tight"
    _run(rig, 10)                       # rise again: pings
    assert len(rig.pings()) == 2
    _run(rig, 90)                       # ok clears completely
    assert rig.state_json()["last_pinged_level"] is None
    _run(rig, 35)                       # watch again: pings again
    assert len(rig.pings()) == 3


def test_new_reset_period_pings_again_at_the_same_level(rig):
    _run(rig, 25)
    assert len(rig.pings()) == 1
    _run(rig, 25, week_reset=(NOW + timedelta(days=10)).isoformat())
    assert len(rig.pings()) == 2


def test_clock_jitter_in_resets_at_is_the_same_period(rig):
    _run(rig, 25)
    _run(rig, 25, week_reset=(NOW + timedelta(days=3, minutes=7)).isoformat())
    assert len(rig.pings()) == 1


def test_failed_ping_is_retried_next_run(rig):
    rig.set_ping_failing()
    _run(rig, 25)
    assert rig.state_json()["last_pinged_level"] is None
    rig.set_ping_ok()
    _run(rig, 25)
    assert len(rig.pings()) == 1 and rig.state_json()["last_pinged_level"] == "tight"


# -- state file -------------------------------------------------------------

def _load_guard_module(monkeypatch, rig):
    for k, v in rig.env().items():
        if k.startswith("CLAUDE_QUOTA"):
            monkeypatch.setenv(k, v)
    loader = importlib.machinery.SourceFileLoader("claude_quota_guard_under_test", str(GUARD))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_state_write_is_atomic_and_leaves_no_temp_files(rig):
    _run(rig, 35)
    assert sorted(p.name for p in rig.state.parent.iterdir()) == ["quota-guard.json"]


def test_a_failed_replace_keeps_the_old_state_and_removes_the_temp(rig, monkeypatch):
    _run(rig, 35)
    before = rig.state.read_bytes()
    mod = _load_guard_module(monkeypatch, rig)

    def boom(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(mod.os, "replace", boom)
    with pytest.raises(OSError):
        mod.save_state({"level": "critical"})
    assert rig.state.read_bytes() == before
    assert sorted(p.name for p in rig.state.parent.iterdir()) == ["quota-guard.json"]


# -- status and install -----------------------------------------------------

def test_status_reads_the_state_without_probing(rig):
    assert rig.guard("status").returncode == 10        # nothing written yet
    _run(rig, 25)
    r = rig.guard("status", CLAUDE_QUOTA_GUARD_AIUSE=str(rig.tmp / "no-such-aiuse"))
    assert r.returncode == 0 and "tight: weekly 25%" in r.stdout
    j = rig.guard("status", "--json", CLAUDE_QUOTA_GUARD_AIUSE=str(rig.tmp / "no-such-aiuse"))
    assert json.loads(j.stdout)["level"] == "tight"


def test_install_writes_the_plist_and_prints_but_never_runs_launchctl(rig):
    r = rig.guard("--install")
    assert r.returncode == 0, r.stderr
    plist = rig.launch_agents / "com.djbclark.claude-quota-guard.plist"
    job = plistlib.loads(plist.read_bytes())
    assert job["Label"] == "com.djbclark.claude-quota-guard"
    assert job["ProgramArguments"] == [str(GUARD), "check"]
    assert job["StartInterval"] == 900
    log_dir = rig.home / ".local/state/ade"
    assert job["StandardOutPath"].startswith(str(log_dir)) and job["StandardErrorPath"].startswith(str(log_dir))
    assert log_dir.is_dir()
    assert f"launchctl bootstrap gui/{os.getuid()} {plist}" in r.stdout
    assert not rig.launchctl_log.exists()


# -- the hook ---------------------------------------------------------------

def _write_guard_state(rig, level, advice="1. do the thing.", age=timedelta(minutes=5)):
    rig.state.parent.mkdir(parents=True, exist_ok=True)
    rig.state.write_text(json.dumps({"level": level, "advice": advice,
                                     "checked_at": (NOW - age).isoformat()}))


def test_hook_silent_without_state_or_with_stale_state(rig):
    r = rig.hook()
    assert r.returncode == 0 and r.stdout == ""
    _write_guard_state(rig, "critical", age=timedelta(hours=2, minutes=1))
    r = rig.hook()
    assert r.returncode == 0 and r.stdout == ""
    _write_guard_state(rig, "critical", age=timedelta(hours=1, minutes=59))
    assert "[quota-guard critical]" in rig.hook().stdout


def test_hook_silent_on_ok_and_on_garbage(rig):
    _write_guard_state(rig, "ok", advice="")
    assert rig.hook().stdout == ""
    rig.state.write_text("{not json")
    r = rig.hook()
    assert r.returncode == 0 and r.stdout == ""
    _write_guard_state(rig, "tight")
    r = rig.hook(stdin="not json at all")
    assert r.returncode == 0                      # an unreadable prompt payload never blocks


def test_hook_prints_advice_once_per_session_and_level(rig):
    _write_guard_state(rig, "watch", advice="1. stay frugal.\n2. use omp.")
    first = rig.hook("s1")
    assert first.stdout == "[quota-guard watch] 1. stay frugal.\n2. use omp.\n"
    assert rig.hook("s1").stdout == ""
    assert rig.hook("s2").stdout == first.stdout          # another session is told once too


def test_hook_speaks_again_on_a_rise_and_after_a_drop_then_rise(rig):
    _write_guard_state(rig, "watch", advice="w")
    assert rig.hook().stdout == "[quota-guard watch] w\n"
    _write_guard_state(rig, "tight", advice="t")
    assert rig.hook().stdout == "[quota-guard tight] t\n"
    assert rig.hook().stdout == ""
    _write_guard_state(rig, "watch", advice="w")          # drop: silent
    assert rig.hook().stdout == ""
    _write_guard_state(rig, "tight", advice="t")          # rise again: speaks again
    assert rig.hook().stdout == "[quota-guard tight] t\n"
    _write_guard_state(rig, "ok", advice="")
    assert rig.hook().stdout == ""
    _write_guard_state(rig, "watch", advice="w")
    assert rig.hook().stdout == "[quota-guard watch] w\n"


def test_hook_reads_only_the_state_file(rig):
    """No aiuse, no ping: with both pointed at tripwires the hook still answers and trips neither."""
    _write_guard_state(rig, "tight", advice="t")
    trip = rig.tmp / "tripped"
    rig._script(rig.aiuse, f"touch {trip}\n")
    rig._script(rig.ping, f"touch {trip}\n")
    t0 = time.monotonic()
    r = rig.hook()
    assert r.stdout == "[quota-guard tight] t\n" and not trip.exists()
    assert time.monotonic() - t0 < 2.0
