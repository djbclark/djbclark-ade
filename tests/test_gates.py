"""bin/ade_gates.py, config/gates.toml and bin/gate-profile (2026-10-26).

The loader is imported and driven with a small fixture gates.toml; the CLI runs as a subprocess against fake hermes-ping,
governor and guard programs (env overrides) and temp state paths. Nothing touches the real ~/.local/state/ade, launchd,
Paseo or Hermes. Wiring into the two scripts is exercised in test_claude_fleet_governor.py and test_claude_quota_guard.py."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
CLI = BIN / "gate-profile"
sys.path.insert(0, str(BIN))
import ade_gates as g  # noqa: E402

NOW = datetime(2026, 10, 26, 16, 0, 0, tzinfo=UTC)      # 12:00 PM EDT, a Monday

FIXTURE = """
[meta]
schema = 1
max_profile_hours = 100

[governor]
a = 10.0
b = 20.0
c = 30.0

[quota_guard]
q = 1.0

[floors.governor]
a = { loosen = "lower", bound = 2.0 }
c = { loosen = "higher", bound = 90.0 }

[floors.quota_guard]
q = { loosen = "lower", bound = 0.5 }

[profiles.away.governor]
a = 5.0
c = 60.0
[profiles.away.quota_guard]
q = 0.8

[profiles.below_floor.governor]
a = 1.0
[profiles.tighter.governor]
a = 15.0
[profiles.wrong_direction.governor]
c = 25.0
[profiles.above_ceiling.governor]
c = 95.0
[profiles.unlisted.governor]
b = 10.0
[profiles.other_gate_bad.governor]
a = 5.0
[profiles.other_gate_bad.quota_guard]
q = 0.1
[profiles.not_a_number.governor]
a = "5"
"""
# the fixture baseline (a 10, c 30, q 1) is never looser than these in its floor direction (a, q: lower is looser; c: higher is
# looser), as the run-time baseline guard requires; b has no floor entry
CODE_DEFAULTS = {"a": 5.0, "b": 99.0, "c": 40.0}
GUARD_DEFAULTS = {"q": 0.9}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fixture gates.toml, a missing profile state and no env override; returns the path helper object."""
    toml = tmp_path / "gates.toml"
    toml.write_text(FIXTURE)
    monkeypatch.setenv("GATES_TOML", str(toml))
    monkeypatch.setenv("GATE_PROFILE_STATE", str(tmp_path / "state" / "gate-profile.json"))
    for var in g.ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    g._LOGGED.clear()
    return tmp_path


def write_state(path: Path | str, **over) -> dict:
    s = {"schema": 1, "profile": "away", "since": g.iso(NOW - timedelta(hours=1)), "until": g.iso(NOW + timedelta(hours=72)),
         "reason": "away 3 days", "set_by": "djbclark"}
    s.update(over)
    s = {k: v for k, v in s.items() if v is not None}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(s))
    return s


def state_path() -> str:
    return os.environ["GATE_PROFILE_STATE"]


def gov(now=NOW):
    return g.load_gates("governor", now, CODE_DEFAULTS)


# -- the baseline cannot drift from the code -----------------------------------------------------------------------------

def _thresholds(script: str) -> dict:
    loader = importlib.machinery.SourceFileLoader("_t_" + script, str(BIN / script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod.THRESHOLDS


def test_gates_toml_baseline_equals_the_code_defaults():
    import tomllib
    cfg = tomllib.loads((REPO / "config" / "gates.toml").read_text())
    assert cfg["governor"] == pytest.approx(_thresholds("claude-fleet-governor"))
    assert cfg["quota_guard"] == pytest.approx(_thresholds("claude-quota-guard"))


def test_the_shipped_frontier_baseline_is_the_ruled_standing_allowance_and_its_floors_equal_it():
    """The code default stays all-closed (fail-safe); gates.toml carries the ruling of 2026-10-27, floors included."""
    import tomllib
    cfg = tomllib.loads((REPO / "config" / "gates.toml").read_text())
    assert cfg["frontier"] == pytest.approx(STANDING)
    floors = cfg["floors"]["frontier"]
    for k, v in STANDING.items():
        if not k.endswith("_min_left"):
            assert floors[k] == {"loosen": "higher", "bound": v}, k       # the baseline may not exceed what the floors allow
    assert (cfg["frontier"]["frontier1_min_left"], cfg["frontier"]["frontier2_min_left"]) == (
        g.FRONTIER_DEFAULTS["frontier1_min_left"], g.FRONTIER_DEFAULTS["frontier2_min_left"])
    assert all(g.FRONTIER_DEFAULTS[k] == 0 for k in ("frontier1_judged", "frontier2_judged", "frontier1_agent_calls_per_day"))


def test_the_shipped_gates_toml_validates():
    r = subprocess.run([sys.executable, "-I", str(CLI), "validate"], capture_output=True, text=True, timeout=60,
                       env={"PATH": os.environ["PATH"], "HOME": "/nonexistent"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "away" in r.stdout


# -- precedence -------------------------------------------------------------------------------------------------------------

def test_precedence_code_then_toml_then_profile_then_env(env, monkeypatch):
    toml = g.toml_path()
    toml.write_text("[governor]\nb = 20.0\n")                      # a toml with no `a`: the code default shows through
    t, info = gov()
    assert (t["a"], t["b"], t["c"]) == (5.0, 20.0, 40.0) and info["source"] == "gates.toml"
    toml.write_text(FIXTURE)
    t, info = gov()
    assert (t["a"], t["b"], t["c"]) == (10.0, 20.0, 30.0)         # baseline over code
    write_state(state_path())
    t, info = gov()
    assert (t["a"], t["b"], t["c"]) == (5.0, 20.0, 60.0)          # profile over baseline
    assert info["profile"]["name"] == "away" and info["profile_values"] == {"a": 5.0, "c": 60.0}
    monkeypatch.setenv("CLAUDE_GOVERNOR_THRESHOLDS", json.dumps({"a": 4.0}))
    t, info = gov()
    assert (t["a"], t["c"]) == (4.0, 60.0)                         # env over profile, untouched keys keep the profile
    assert info["env_values"] == {"a": 4.0}


def test_env_can_undo_a_profile_value_even_to_a_tighter_number(env, monkeypatch):
    write_state(state_path())
    monkeypatch.setenv("CLAUDE_GOVERNOR_THRESHOLDS", json.dumps({"a": 50.0, "c": 1.0}))
    t, _ = gov()
    assert (t["a"], t["c"]) == (50.0, 1.0)


@pytest.mark.parametrize("raw, msg", [("{", "not JSON"), ("[1]", "JSON object"), ('{"zzz": 1}', "unknown or non-numeric"),
                                      ('{"a": "x"}', "unknown or non-numeric"), ('{"a": true}', "unknown or non-numeric")])
def test_bad_env_json_is_an_error(env, monkeypatch, raw, msg):
    monkeypatch.setenv("CLAUDE_GOVERNOR_THRESHOLDS", raw)
    with pytest.raises(g.GateEnvError, match=msg):
        gov()


def test_each_gate_reads_only_its_own_table(env):
    write_state(state_path())
    assert g.load_gates("quota_guard", NOW, GUARD_DEFAULTS)[0] == {"q": 0.8}
    assert gov()[0]["a"] == 5.0


# -- fail-safe: the toml --------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [None, "not = [valid", "[meta]\nschema = 1\n", "[governor]\na = \"ten\"\n", "[governor]\n"])
def test_missing_or_unusable_toml_uses_the_code_defaults_and_ignores_any_profile(env, capsys, text):
    if text is None:
        g.toml_path().unlink()
    else:
        g.toml_path().write_text(text)
    write_state(state_path())
    t, info = gov()
    assert t == CODE_DEFAULTS and info["source"] == "code" and info["toml_error"]
    assert info["profile"] is None and info["ignored"]
    gov()                                                            # a second load in the process does not repeat the message
    assert capsys.readouterr().err.count("using the code defaults") == 1


# -- fail-safe: the profile -----------------------------------------------------------------------------------------------

def test_a_valid_profile_applies_and_reports_its_fields(env):
    write_state(state_path())
    t, info = gov()
    assert t["a"] == 5.0 and info["ignored"] is None
    assert info["profile"] == {"name": "away", "since": g.iso(NOW - timedelta(hours=1)), "until": g.iso(NOW + timedelta(hours=72)),
                               "reason": "away 3 days", "set_by": "djbclark"}
    assert g.profile_brief(info) == {"name": "away", "until": g.iso(NOW + timedelta(hours=72))}


def test_the_profile_ends_exactly_at_until(env):
    until = NOW + timedelta(hours=2)
    write_state(state_path(), until=g.iso(until))
    assert gov(until - timedelta(seconds=1))[0]["a"] == 5.0
    t, info = gov(until)
    assert t["a"] == 10.0 and info["profile"] is None and "expired" in info["ignored"]
    assert gov(until + timedelta(seconds=1))[0]["a"] == 10.0


def test_a_profile_that_has_not_started_does_not_apply(env):
    write_state(state_path(), since=g.iso(NOW + timedelta(minutes=1)), until=g.iso(NOW + timedelta(hours=5)))
    t, info = gov()
    assert t["a"] == 10.0 and "future" in info["ignored"]
    assert gov(NOW + timedelta(minutes=1))[0]["a"] == 5.0           # from the second it starts


@pytest.mark.parametrize("over, why", [
    ({"profile": "nope"}, "no profile 'nope'"),
    ({"profile": "below_floor"}, "below the floor 2"),
    ({"profile": "tighter"}, "tighter than the baseline"),
    ({"profile": "wrong_direction"}, "tighter than the baseline"),
    ({"profile": "above_ceiling"}, "above the ceiling 90"),
    ({"profile": "unlisted"}, "not overridable"),
    ({"profile": "other_gate_bad"}, "below the floor 0.5"),         # one bad value on the OTHER gate rejects the whole profile
    ({"profile": "not_a_number"}, "not a number"),
    ({"profile": None}, "`profile` is missing"),
    ({"until": g.iso(NOW + timedelta(hours=101)), "since": g.iso(NOW - timedelta(hours=1))}, "over max_profile_hours 100"),
    ({"since": g.iso(NOW - timedelta(hours=50)), "until": g.iso(NOW + timedelta(hours=50, seconds=1))}, "over max_profile_hours"),
    ({"since": g.iso(NOW + timedelta(hours=5)), "until": g.iso(NOW + timedelta(hours=1))}, "future"),
    ({"since": g.iso(NOW - timedelta(hours=5)), "until": g.iso(NOW - timedelta(hours=5))}, "expired"),
    ({"until": "2026-10-28T16:00:00"}, "not a UTC time"),           # naive
    ({"until": "2026-10-28T21:00:00+05:00"}, "not a UTC time"),     # aware but not UTC
    ({"since": "2026-10-26T11:00:00"}, "`since`"),
    ({"until": None}, "not a UTC time"),
    ({"until": 1793000000}, "not a UTC time"),
    ({"schema": 2}, "schema"),
    ({"schema": None}, "schema"),
])
def test_a_profile_that_fails_any_check_means_baseline(env, over, why):
    write_state(state_path(), **over)
    t, info = gov()
    assert (t["a"], t["c"]) == (10.0, 30.0), info
    assert info["profile"] is None and why in info["ignored"], info["ignored"]


@pytest.mark.parametrize("text", ["{", "", "[]", '"away"', "null"])
def test_a_corrupt_profile_file_means_baseline(env, text):
    Path(state_path()).parent.mkdir(parents=True)
    Path(state_path()).write_text(text)
    t, info = gov()
    assert t["a"] == 10.0 and info["profile"] is None and info["ignored"]


def test_no_profile_file_is_plain_baseline_with_no_complaint(env):
    t, info = gov()
    assert t["a"] == 10.0 and info["profile"] is None and info["ignored"] is None


def test_a_profile_value_equal_to_the_baseline_is_allowed(env):
    # a no-op profile value (equal to the baseline) is allowed: not tighter, not past the floor
    g.toml_path().write_text(FIXTURE.replace("[profiles.away.governor]\na = 5.0", "[profiles.away.governor]\na = 10.0"))
    write_state(state_path())
    assert gov()[0]["a"] == 10.0 and gov()[1]["profile"]["name"] == "away"


# -- expiry notice ----------------------------------------------------------------------------------------------------------

def test_an_expired_file_is_announced_once_and_left_in_place(env):
    until = g.iso(NOW - timedelta(minutes=1))
    write_state(state_path(), until=until, since=g.iso(NOW - timedelta(hours=70)))
    sent: list[str] = []
    t, info = gov()
    assert t["a"] == 10.0 and info["expired"]["name"] == "away"
    assert g.notify_expired(info, lambda m: sent.append(m) or True, NOW) is True
    assert len(sent) == 1 and "away profile expired, baseline restored" in sent[0]
    saved = json.loads(Path(state_path()).read_text())
    assert saved["expired_notified"] == g.iso(NOW) and saved["profile"] == "away" and saved["until"] == until
    _, again = gov()
    assert again["expired"] is None and again["ignored"]            # still ignored, no longer news
    assert g.notify_expired(again, lambda m: sent.append(m) or True, NOW) is False
    assert g.notify_expired(info, lambda m: sent.append(m) or True, NOW) is False   # a stale info from a parallel run: the file wins
    assert len(sent) == 1


def test_a_failed_expiry_ping_is_retried_next_run(env):
    write_state(state_path(), until=g.iso(NOW - timedelta(minutes=1)), since=g.iso(NOW - timedelta(hours=70)))
    _, info = gov()
    assert g.notify_expired(info, lambda m: False, NOW) is False
    assert "expired_notified" not in json.loads(Path(state_path()).read_text())
    _, info = gov()
    assert info["expired"] is not None
    sent: list[str] = []
    assert g.notify_expired(info, lambda m: sent.append(m) or True, NOW) and len(sent) == 1


def test_no_expiry_notice_for_a_corrupt_or_missing_file_or_an_active_profile(env):
    sent: list[str] = []
    for prep in (lambda: None, lambda: write_state(state_path()), lambda: Path(state_path()).write_text("{")):
        prep()
        _, info = gov()
        assert info["expired"] is None
        assert g.notify_expired(info, lambda m: sent.append(m) or True, NOW) is False
    assert sent == []


# -- the CLI ----------------------------------------------------------------------------------------------------------------

class Cli:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.state = tmp / "state" / "gate-profile.json"
        self.log = tmp / "state" / "gate-profile.log"
        self.calls = tmp / "calls.log"
        for name in ("ping", "governor", "guard"):
            p = tmp / f"fake-{name}"
            p.write_text(f"#!/bin/sh\nprintf '%s %s\\n' {name} \"$*\" >> {self.calls}\nexit 0\n")
            p.chmod(0o755)

    def env(self, now: datetime = NOW, **extra) -> dict:
        return {"PATH": os.environ["PATH"], "HOME": str(self.tmp / "home"), "USER": "tester", "GATE_PROFILE_STATE": str(self.state),
                "GATE_PROFILE_LOG": str(self.log), "GATE_PROFILE_PING": str(self.tmp / "fake-ping"),
                "GATE_PROFILE_GOVERNOR": str(self.tmp / "fake-governor"), "GATE_PROFILE_GUARD": str(self.tmp / "fake-guard"),
                "GATE_PROFILE_NOW": g.iso(now), **extra}

    def run(self, *args, now: datetime = NOW, **extra):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=self.env(now, **extra), capture_output=True, text=True,
                              timeout=60)

    def popen(self, *args, now: datetime = NOW, **extra):
        return subprocess.Popen([sys.executable, "-I", str(CLI), *args], env=self.env(now, **extra), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)

    def called(self) -> list[str]:
        return self.calls.read_text().splitlines() if self.calls.exists() else []


@pytest.fixture
def cli(tmp_path):
    return Cli(tmp_path)


def test_set_writes_state_audit_line_ping_and_recompute(cli):
    r = cli.run("set", "away", "--for", "72h", "--reason", "three days off")
    assert r.returncode == 0, r.stderr
    st = json.loads(cli.state.read_text())
    assert st == {"schema": 1, "profile": "away", "since": "2026-10-26T16:00:00Z", "until": "2026-10-29T16:00:00Z",
                  "reason": "three days off", "set_by": "tester", "last_daily_nudge": "2026-10-26"}
    entry = json.loads(cli.log.read_text().splitlines()[-1])
    assert entry["action"] == "set" and entry["profile"] == "away" and entry["until"] == "2026-10-29T16:00:00Z"
    assert entry["reason"] == "three days off" and entry["at"] == "2026-10-26T16:00:00Z"
    calls = cli.called()
    assert any(c.startswith("ping ") and "away SET until Thu Oct 29 12:00 PM EDT" in c for c in calls)
    assert "governor run" in calls and "guard check" in calls
    assert "Thu Oct 29 12:00 PM EDT" in r.stdout


def test_set_until_and_status_in_new_york_time(cli):
    assert cli.run("set", "away", "--until", "2026-10-28T21:30:00Z", "--reason", "x").returncode == 0
    r = cli.run("status")
    assert r.returncode == 0
    assert "profile away: active until Wed Oct 28 5:30 PM EDT (2d 5h 30m left)" in r.stdout
    assert "tight_projected: 90 -> 500 (profile)" in r.stdout and "watch_weekly: 40 -> 20 (profile)" in r.stdout
    assert "critical_left" not in r.stdout                           # unchanged keys are not listed
    data = json.loads(cli.run("status", "--json").stdout)
    assert data["profile"]["name"] == "away" and data["gates"]["governor"]["changed"]["tight_projected"] == {
        "baseline": 90.0, "effective": 500.0}


@pytest.mark.parametrize("args, why", [
    (["set", "away", "--for", "241h"], "over max_profile_hours"),
    (["set", "away", "--until", "2026-11-05T17:00:00Z"], "over max_profile_hours"),     # 241 h
    (["set", "away", "--until", "2026-10-26T15:59:59Z"], "not in the future"),
    (["set", "away", "--until", "2026-10-26T16:00:00Z"], "not in the future"),
    (["set", "away", "--until", "2026-10-28T16:00:00"], "not a timezone-aware UTC"),
    (["set", "away", "--until", "2026-10-28T16:00:00-04:00"], "not a timezone-aware UTC"),
    (["set", "away", "--for", "soon"], "not Nm, Nh or Nd"),
    (["set", "away", "--for", "0h"], "not Nm, Nh or Nd"),
    (["set", "nope", "--for", "1h"], "no profile 'nope'"),
])
def test_set_refusals_exit_1_and_change_nothing(cli, args, why):
    r = cli.run(*args, "--reason", "x")
    assert r.returncode == 1 and why in r.stderr, r.stderr
    assert not cli.state.exists() and not cli.log.exists() and cli.called() == []


def test_set_needs_a_reason_and_exactly_one_window(cli):
    assert cli.run("set", "away", "--for", "1h").returncode == 2
    assert cli.run("set", "away", "--reason", "x").returncode == 2
    assert cli.run("set", "away", "--for", "1h", "--until", "2026-10-27T00:00:00Z", "--reason", "x").returncode == 2
    assert cli.run("set", "away", "--for", "1h", "--reason", "  ").returncode == 1
    assert not cli.state.exists()


def test_set_refuses_a_profile_that_fails_validation(cli, tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text((REPO / "config/gates.toml").read_text().replace("critical_weekly = 10.0", "critical_weekly = 2.0"))
    r = cli.run("set", "away", "--for", "1h", "--reason", "x", GATES_TOML=str(bad))
    assert r.returncode == 1 and "below the floor 3" in r.stderr and not cli.state.exists()


def test_clear_removes_the_file_logs_pings_and_recomputes(cli):
    cli.run("set", "away", "--for", "2h", "--reason", "x")
    cli.calls.unlink()
    r = cli.run("clear")
    assert r.returncode == 0 and not cli.state.exists()
    entries = [json.loads(line) for line in cli.log.read_text().splitlines()]
    assert [e["action"] for e in entries] == ["set", "clear"] and entries[1]["profile"] == "away"
    assert any("CLEARED" in c for c in cli.called()) and "governor run" in cli.called() and "guard check" in cli.called()
    again = cli.run("clear")
    assert again.returncode == 0 and "already in force" in again.stdout
    assert len(cli.log.read_text().splitlines()) == 2                # nothing to clear: no audit line


def test_set_and_clear_soft_fail_when_ping_and_scripts_are_missing(cli):
    r = cli.run("set", "away", "--for", "2h", "--reason", "x", GATE_PROFILE_PING="/nonexistent/p",
                GATE_PROFILE_GOVERNOR="/nonexistent/g", GATE_PROFILE_GUARD="/nonexistent/q")
    assert r.returncode == 0 and "ping: not found" in r.stdout and cli.state.exists()


def test_status_says_why_a_profile_is_ignored(cli):
    cli.state.parent.mkdir(parents=True)
    write_state(cli.state, until=g.iso(NOW - timedelta(hours=1)), since=g.iso(NOW - timedelta(hours=60)))
    r = cli.run("status")
    assert r.returncode == 0 and "baseline: no profile active" in r.stdout and "expired at 2026-10-26T15:00:00Z" in r.stdout
    write_state(cli.state, profile="away", since="2026-10-26T10:00:00")
    assert "`since`" in cli.run("status").stdout


def test_diff_and_show(cli):
    r = cli.run("diff", "away")
    assert r.returncode == 0
    assert "tight_projected: 90 -> 500  (higher is looser, bound 1000)" in r.stdout
    assert "critical_left" not in r.stdout
    assert "quota_guard:" in r.stdout and "critical_weekly: 15 -> 10  (lower is looser, bound 3)" in r.stdout
    assert cli.run("show", "nope").returncode == 1


def test_validate_catches_drift_floors_and_directions(cli, tmp_path):
    real = (REPO / "config/gates.toml").read_text()
    assert cli.run("validate").returncode == 0
    for old, new, expect in [
        ("critical_left = 10.0 ", "critical_left = 11.0 ", "critical_left: gates.toml 11 != code default 10"),
        ("tight_projected = 500.0", "tight_projected = 50.0", "tighter than the baseline"),
        ("tight_projected = 500.0", "tight_projected = 5000.0", "above the ceiling 1000"),
        ("watch_weekly = 20.0", "watch_weekly = 10.0", "below the floor 15"),
        ("frontier1_per_wave = 2 ", "frontier1_per_wave = 3 ", "[frontier].frontier1_per_wave: gates.toml 3 is above its floor bound 2"),
        ("frontier1_agent_calls_per_day = 4 ", "frontier1_agent_calls_per_day = 5 ", "frontier1_agent_calls_per_day: gates.toml 5 is above its floor bound 4"),
        ("frontier1_per_wave = 2 ", "frontier1_per_wave = 0 ", "frontier1_per_wave: gates.toml 0 is tighter than the code default 1"),
        ("frontier1_min_left = 10.0 ", "frontier1_min_left = 9.0 ", "[frontier].frontier1_min_left: gates.toml 9 != code default 10"),
        ("frontier2_min_left = 60.0 ", "frontier2_min_left = 50.0 ", "[frontier].frontier2_min_left: gates.toml 50 != code default 60"),
        ("tight_weekly = 15.0\n# Aligned", "tight_weekly = 15.0\nlock_wait_s = 0.1\n# Aligned", "not overridable"),
        ("[meta]\nschema = 1", "[meta]\nschema = 2", "schema"),
        ("max_profile_hours = 240", "max_profile_hours = 0", "max_profile_hours"),
        ('loosen = "higher", bound = 1000.0', 'loosen = "sideways", bound = 1000.0', "loosen"),
        ("conserve_alert_level = 1.0\n", "conserve_alert_level = 0.0\n", "conserve_alert_level: 0 is below the floor 1"),
        ("conserve_alert_level = 1.0\n", "conserve_alert_level = 2.5\n", "conserve_alert_level: 2.5 is tighter than the baseline 2"),
        ("watch_weekly = 20.0\ntight_weekly = 15.0\n", "watch_weekly = 15.0\ntight_weekly = 18.0\n",
         "profile away.quota_guard: watch_weekly 15 must be at least tight_weekly 18"),
        ("watch_weekly = 20.0\ntight_weekly = 15.0\n", "watch_weekly = 15.0\n",            # tight_weekly left at the baseline 30
         "profile away.quota_guard: watch_weekly 15 must be at least tight_weekly 30"),
        ("tight_weekly = 30.0 ", "tight_weekly = 45.0 ", "[quota_guard] baseline: watch_weekly 40 must be at least tight_weekly 45"),
    ]:
        assert old in real, old
        bad = tmp_path / "bad.toml"
        bad.write_text(real.replace(old, new, 1))
        r = cli.run("validate", GATES_TOML=str(bad))
        assert r.returncode == 1 and expect in r.stdout, (old, r.stdout)
    r = cli.run("validate", GATES_TOML=str(tmp_path / "missing.toml"))
    assert r.returncode == 1
    broken = tmp_path / "broken.toml"
    broken.write_text("[governor\n")
    assert cli.run("validate", GATES_TOML=str(broken)).returncode == 1


def test_validate_accepts_a_closed_frontier_baseline(cli, tmp_path):
    """Closing the standing allowance is a PR to `[frontier]` alone: the code defaults are inside the allowed range."""
    closed = tmp_path / "closed.toml"
    closed.write_text(close_frontier_baseline((REPO / "config/gates.toml").read_text()))
    r = cli.run("validate", GATES_TOML=str(closed))
    assert r.returncode == 0, r.stdout + r.stderr


# -- the real gates.toml through the loader: conserve_alert_level floor and the weekly-trigger ordering ------------------------

REAL = (REPO / "config" / "gates.toml").read_text()


def _real_guard(env, monkeypatch, edit: tuple[str, str] | None = None):
    toml = REAL if edit is None else REAL.replace(*edit, 1)
    assert edit is None or edit[0] in REAL, edit
    g.toml_path().write_text(toml)
    write_state(state_path())
    return g.load_gates("quota_guard", NOW, _thresholds("claude-quota-guard"))


def test_the_away_profile_lowers_the_conserve_cap_to_watch(env, monkeypatch):
    t, info = _real_guard(env, monkeypatch)
    assert info["profile"]["name"] == "away", info["ignored"]
    assert (info["baseline"]["conserve_alert_level"], t["conserve_alert_level"]) == (2.0, 1.0)


@pytest.mark.parametrize("edit, why", [
    (("conserve_alert_level = 1.0\n", "conserve_alert_level = 0.0\n"), "below the floor 1"),   # a profile may never ignore alerts
    (("conserve_alert_level = 1.0\n", "conserve_alert_level = 3.0\n"), "tighter than the baseline 2"),
    (("watch_weekly = 20.0\ntight_weekly = 15.0\n", "watch_weekly = 15.0\ntight_weekly = 18.0\n"), "watch_weekly 15 must be at least tight_weekly 18"),
    (("critical_weekly = 10.0\n", "critical_weekly = 3.0\n"), None),                              # control: a valid change still applies
    (("watch_weekly = 20.0\ntight_weekly = 15.0\n", "watch_weekly = 15.0\n"), "watch_weekly 15 must be at least tight_weekly 30"),
])
def test_a_profile_that_breaks_a_floor_or_the_weekly_order_is_rejected_whole(env, monkeypatch, edit, why):
    t, info = _real_guard(env, monkeypatch, edit)
    base = info["baseline"]
    if why is None:
        assert info["profile"]["name"] == "away" and t["critical_weekly"] == 3.0
        return
    assert info["profile"] is None and why in info["ignored"], info["ignored"]
    assert t == base                                  # not one key of the profile applies, not even the valid ones


def test_env_json_can_still_set_the_conserve_cap_to_zero_under_a_profile(env, monkeypatch):
    monkeypatch.setenv("CLAUDE_QUOTA_GUARD_THRESHOLDS", json.dumps({"conserve_alert_level": 0}))
    t, info = _real_guard(env, monkeypatch)
    assert info["profile"]["name"] == "away" and t["conserve_alert_level"] == 0.0


def test_ordering_problems_unit():
    ok = {"watch_weekly": 40.0, "tight_weekly": 30.0, "critical_weekly": 15.0}
    assert g.ordering_problems("quota_guard", ok) == []
    assert g.ordering_problems("quota_guard", {**ok, "tight_weekly": 15.0, "critical_weekly": 15.0}) == []      # equal is in order
    assert len(g.ordering_problems("quota_guard", {**ok, "critical_weekly": 31.0})) == 1
    assert len(g.ordering_problems("quota_guard", {"watch_weekly": 10.0, "tight_weekly": 20.0, "critical_weekly": 30.0})) == 2
    assert g.ordering_problems("quota_guard", {"watch_weekly": 10.0}) == []                                      # keys absent: nothing to order
    assert g.ordering_problems("governor", {"a": 1.0}) == []


# -- daily nudge ----------------------------------------------------------------------------------------------------------

def _nudger(sent):
    def nudge(t, ok=True):
        _, info = gov(t)
        return g.notify_daily(info, lambda m: sent.append(m) or ok, t)
    return nudge


def test_daily_nudge_is_once_per_new_york_day_and_not_on_the_expiry_day(env):
    # Mon 8:00 AM EDT -> Thu 12:00 PM EDT; the set day (Mon) already had its ping from `set`
    write_state(state_path(), since="2026-10-26T12:00:00Z", until="2026-10-29T16:00:00Z", last_daily_nudge="2026-10-26")
    sent: list[str] = []
    nudge = _nudger(sent)
    assert not nudge(NOW) and not nudge(datetime(2026, 10, 27, 3, 59, 59, tzinfo=UTC))      # 23:59:59 EDT Monday: still the set day
    assert nudge(datetime(2026, 10, 27, 4, 0, 0, tzinfo=UTC))                                # 00:00 EDT Tuesday
    assert "away profile active until Thu Oct 29 12:00 PM EDT, 2 days left; restore normal routing now: gate-profile clear" in sent[0]
    assert "gate-profile extend --for 24h" in sent[0]
    assert not nudge(datetime(2026, 10, 27, 4, 5, 0, tzinfo=UTC)) and not nudge(datetime(2026, 10, 27, 20, 0, 0, tzinfo=UTC))
    assert json.loads(Path(state_path()).read_text())["last_daily_nudge"] == "2026-10-27"
    assert nudge(datetime(2026, 10, 28, 4, 0, 0, tzinfo=UTC)) and len(sent) == 2             # Wednesday
    assert not nudge(datetime(2026, 10, 29, 4, 0, 0, tzinfo=UTC))                            # Thursday is the expiry day: the expiry ping instead
    assert not nudge(datetime(2026, 10, 29, 15, 59, 0, tzinfo=UTC))
    assert not nudge(datetime(2026, 10, 29, 16, 0, 0, tzinfo=UTC)) and len(sent) == 2        # expired: no profile, no nudge
    assert json.loads(Path(state_path()).read_text())["until"] == "2026-10-29T16:00:00Z"


def test_daily_nudge_follows_the_new_york_calendar_across_the_dst_change(env):
    # DST ended Sun 2026-11-01 02:00 EDT: that New York day is 25 h long, so "24 h after the last nudge" would nudge twice
    write_state(state_path(), since="2026-10-31T20:00:00Z", until="2026-11-04T20:00:00Z", last_daily_nudge="2026-10-31")
    sent: list[str] = []
    nudge = _nudger(sent)
    assert not nudge(datetime(2026, 11, 1, 3, 59, 59, tzinfo=UTC))                           # 23:59:59 EDT Saturday
    assert nudge(datetime(2026, 11, 1, 4, 0, 0, tzinfo=UTC))                                 # 00:00 EDT Sunday
    assert not nudge(datetime(2026, 11, 2, 4, 0, 0, tzinfo=UTC))                             # 24 h later = 23:00 EST Sunday, same day
    assert not nudge(datetime(2026, 11, 2, 4, 59, 59, tzinfo=UTC))                           # 23:59:59 EST Sunday
    assert nudge(datetime(2026, 11, 2, 5, 0, 0, tzinfo=UTC))                                 # 00:00 EST Monday
    assert nudge(datetime(2026, 11, 3, 5, 0, 0, tzinfo=UTC)) and len(sent) == 3
    assert "EST" in sent[-1] or "EDT" in sent[-1]


def test_daily_nudge_none_without_a_profile_or_after_it_ends_or_with_a_failing_ping(env):
    sent: list[str] = []
    nudge = _nudger(sent)
    assert not nudge(NOW)                                                                    # no state file
    write_state(state_path(), profile="nope")
    assert not nudge(NOW)                                                                    # profile ignored
    write_state(state_path(), until=g.iso(NOW - timedelta(minutes=1)), since=g.iso(NOW - timedelta(hours=30)))
    assert not nudge(NOW)                                                                    # expired
    assert sent == []
    write_state(state_path())
    assert not nudge(NOW, ok=False)                                                          # a failed ping is not recorded ...
    assert "last_daily_nudge" not in json.loads(Path(state_path()).read_text())
    assert nudge(NOW) and len(sent) == 2                                                     # ... so the next run tries again


def test_daily_nudge_is_skipped_for_a_profile_that_changed_under_it(env):
    write_state(state_path())
    _, info = gov()
    write_state(state_path(), until=g.iso(NOW + timedelta(hours=60)))                        # `extend` ran in between
    assert g.notify_daily(info, lambda m: True, NOW) is False


def test_set_records_its_own_day_so_it_is_not_nudged_the_same_day(cli):
    cli.run("set", "away", "--for", "72h", "--reason", "x")
    assert json.loads(cli.state.read_text())["last_daily_nudge"] == "2026-10-26"


# -- extend and the status nudge line ------------------------------------------------------------------------------------

def test_extend_moves_until_logs_pings_and_recomputes(cli):
    cli.run("set", "away", "--for", "72h", "--reason", "three days")
    cli.calls.unlink()
    r = cli.run("extend", "--for", "24h", now=NOW + timedelta(hours=1))
    assert r.returncode == 0, r.stderr
    st = json.loads(cli.state.read_text())
    assert st["until"] == "2026-10-30T16:00:00Z" and st["since"] == "2026-10-26T16:00:00Z" and st["reason"] == "three days"
    assert st["last_daily_nudge"] == "2026-10-26"
    entry = json.loads(cli.log.read_text().splitlines()[-1])
    assert (entry["action"], entry["previous_until"], entry["until"]) == ("extend", "2026-10-29T16:00:00Z", "2026-10-30T16:00:00Z")
    assert any("EXTENDED to Fri Oct 30 12:00 PM EDT" in c for c in cli.called())
    assert "governor run" in cli.called() and "guard check" in cli.called()


def test_extend_honours_max_profile_hours_and_needs_an_active_profile(cli):
    assert cli.run("extend", "--for", "1h").returncode == 1                                  # nothing to extend
    assert cli.run("set", "away", "--for", "240h", "--reason", "x").returncode == 0           # exactly the cap
    before = cli.state.read_text()
    r = cli.run("extend", "--for", "1m", now=NOW + timedelta(hours=1))
    assert r.returncode == 1 and "over max_profile_hours 240" in r.stderr
    assert cli.state.read_text() == before and len(cli.log.read_text().splitlines()) == 1
    assert cli.run("extend", "--for", "soon").returncode == 1


def test_extend_refuses_an_expired_profile(cli):
    cli.run("set", "away", "--for", "2h", "--reason", "x")
    r = cli.run("extend", "--for", "24h", now=NOW + timedelta(hours=3))
    assert r.returncode == 1 and "no active profile" in r.stderr
    assert json.loads(cli.state.read_text())["until"] == "2026-10-26T18:00:00Z"


def test_extend_up_to_the_cap_is_allowed(cli):
    cli.run("set", "away", "--for", "216h", "--reason", "x")
    assert cli.run("extend", "--for", "24h", now=NOW + timedelta(hours=1)).returncode == 0   # 240 h since `since`


def test_status_shows_the_next_nudge_and_the_restore_commands(cli):
    cli.run("set", "away", "--for", "72h", "--reason", "x")
    r = cli.run("status")
    assert "next nudge: Tue Oct 27 12:00 AM EDT" in r.stdout
    assert "restore normal routing: gate-profile clear; stay longer: gate-profile extend --for 24h" in r.stdout
    assert json.loads(cli.run("status", "--json").stdout)["next_nudge"] == "2026-10-27T04:00:00Z"
    owed = cli.run("status", now=NOW + timedelta(days=1))
    assert "next nudge: due at the next governor run" in owed.stdout
    cli.state.write_text(json.dumps({**json.loads(cli.state.read_text()), "last_daily_nudge": "2026-10-28"}))   # Wednesday's was sent
    last = cli.run("status", now=NOW + timedelta(days=2, hours=5))                            # Wed 5 PM: Thursday is the expiry day
    assert "next nudge: none" in last.stdout
    assert json.loads(cli.run("status", "--json").stdout)["extend"] == "gate-profile extend --for 24h"


# -- adversary round 1 (A1-A6): the state lock, the baseline guard, number and file limits ---------------------------------------

def _bounded(fn, secs: float = 5.0):
    """Run fn() in a thread and fail the test, not the run, when it does not return: a hang is the bug under test."""
    out: list = []
    th = threading.Thread(target=lambda: out.append(fn()), daemon=True)
    th.start()
    th.join(secs)
    assert not th.is_alive(), "hung"
    return out[0]


def _probe_fakes(cli: Cli) -> Path:
    """Replace the fake ping and governor with programs that record whether the profile lock is free when they run."""
    probe = cli.tmp / "probe.log"
    lock = f"{cli.state}.lock"
    for name in ("ping", "governor"):
        p = cli.tmp / f"fake-{name}"
        p.write_text(f"#!{sys.executable}\nimport fcntl\nf = open({lock!r}, 'a')\ntry:\n"
                     f"    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)\n    r = 'free'\nexcept OSError:\n    r = 'held'\n"
                     f"open({str(probe)!r}, 'a').write(r + chr(10))\n")
        p.chmod(0o755)
    return probe


def test_a_clear_during_a_failed_ping_waits_for_it_and_the_profile_stays_cleared(cli, env):
    assert cli.run("set", "away", "--for", "72h", "--reason", "x").returncode == 0
    later = NOW + timedelta(days=1)                                      # a daily nudge is owed
    _, info = gov(later)
    procs, seen = [], {}

    def ping(text: str) -> bool:
        procs.append(cli.popen("clear", now=later, GATE_PROFILE_LOCK_WAIT="30"))
        time.sleep(1.0)                                                  # the CLI is up and asking for the lock by now
        seen["state"] = json.loads(cli.state.read_text()) if cli.state.exists() else None
        return False                                                     # hermes is down

    assert g.notify_daily(info, ping, later) is False
    out, err = procs[0].communicate(timeout=60)
    assert procs[0].returncode == 0, err
    assert seen["state"] and seen["state"]["last_daily_nudge"] == "2026-10-27", "clear did not wait for the lock held by the ping"
    assert not cli.state.exists(), "the failed ping's restore brought the cleared profile back"


def test_a_set_during_a_failed_ping_waits_for_it_and_its_window_wins(cli, env):
    assert cli.run("set", "away", "--for", "72h", "--reason", "x").returncode == 0
    first = json.loads(cli.state.read_text())
    later = NOW + timedelta(days=1)
    _, info = gov(later)
    procs, seen = [], {}

    def ping(text: str) -> bool:
        procs.append(cli.popen("set", "away", "--for", "2h", "--reason", "shorter", now=later, GATE_PROFILE_LOCK_WAIT="30"))
        time.sleep(1.0)
        seen["until"] = json.loads(cli.state.read_text())["until"]
        return False

    assert g.notify_daily(info, ping, later) is False
    out, err = procs[0].communicate(timeout=60)
    assert procs[0].returncode == 0, err
    assert seen["until"] == first["until"], "set did not wait for the lock held by the ping"
    assert json.loads(cli.state.read_text())["until"] == g.iso(later + timedelta(hours=2)), "the old window overwrote the new one"


def test_a_failed_ping_restores_the_mark_only_while_the_file_is_still_the_marked_one(env):
    """Defence in depth for a writer that does not take the lock (an older gate-profile, a hand edit)."""
    later = NOW + timedelta(days=1)
    write_state(state_path())
    _, info = gov(later)
    assert g.notify_daily(info, lambda m: Path(state_path()).unlink() or False, later) is False
    assert not Path(state_path()).exists()                                     # cleared meanwhile: stays cleared
    write_state(state_path())
    _, info = gov(later)
    new = g.iso(later + timedelta(hours=2))
    assert g.notify_daily(info, lambda m: write_state(state_path(), since=g.iso(later), until=new) and False, later) is False
    assert json.loads(Path(state_path()).read_text())["until"] == new         # set again meanwhile: the new window is kept
    write_state(state_path())
    _, info = gov(later)
    assert g.notify_daily(info, lambda m: False, later) is False
    assert "last_daily_nudge" not in json.loads(Path(state_path()).read_text())   # control: an untouched file is restored


def test_the_cli_refuses_with_a_message_when_the_lock_stays_held_and_changes_nothing(cli, env):
    assert cli.run("set", "away", "--for", "72h", "--reason", "x").returncode == 0
    before = cli.state.read_text()
    cli.calls.unlink()
    with g._state_lock(5, create=True):                                          # a ping in flight
        for args in (("set", "away", "--for", "2h", "--reason", "y"), ("clear",), ("extend", "--for", "1h")):
            t0 = time.monotonic()
            r = cli.run(*args, GATE_PROFILE_LOCK_WAIT="0.5")
            assert r.returncode == 1 and "the profile lock is still held after 0.5 s" in r.stderr, (args, r.stderr)
            assert "nothing changed" in r.stderr and "Traceback" not in r.stderr
            assert 0.4 < time.monotonic() - t0 < 20, args
    assert cli.state.read_text() == before and cli.called() == []


def test_a_notice_skips_and_is_retried_instead_of_hanging_while_another_ping_holds_the_lock(env, monkeypatch):
    monkeypatch.setattr(g, "NOTIFY_LOCK_WAIT", 0.3)
    sent: list[str] = []
    send = lambda m: sent.append(m) or True              # noqa: E731
    write_state(state_path())
    _, active = gov()
    write_state(state_path(), until=g.iso(NOW - timedelta(minutes=1)), since=g.iso(NOW - timedelta(hours=70)))
    _, expired = gov()
    before = Path(state_path()).read_text()
    with g._state_lock(5, create=True):
        assert _bounded(lambda: g.notify_expired(expired, send, NOW)) is False
        assert _bounded(lambda: g.notify_daily(active, send, NOW)) is False
    assert sent == [] and Path(state_path()).read_text() == before                # nothing recorded: the next run retries
    assert g.notify_expired(expired, send, NOW) is True and len(sent) == 1


def test_set_extend_and_clear_release_the_lock_before_the_ping_and_the_recompute(cli):
    """The recompute runs the governor, which takes the same lock for its notices: holding it across would stall it."""
    probe = _probe_fakes(cli)
    for args in (("set", "away", "--for", "72h", "--reason", "x"), ("extend", "--for", "1h"), ("clear",)):
        probe.unlink(missing_ok=True)
        r = cli.run(*args)
        assert r.returncode == 0, r.stderr
        assert probe.read_text().split() == ["free", "free"], args


def test_a_toml_baseline_looser_than_the_code_default_is_replaced_by_it_and_logged_once(env, capsys):
    # a: lower is looser (4 < code 5), c: higher is looser (50 > code 40); b has no floor entry, so its 20 stands
    g.toml_path().write_text(FIXTURE.replace("a = 10.0", "a = 4.0").replace("c = 30.0", "c = 50.0"))
    t, info = gov()
    assert (t["a"], t["b"], t["c"]) == (5.0, 20.0, 40.0)
    assert info["baseline_guarded"] == {"a": 4.0, "c": 50.0} and info["baseline"]["a"] == 5.0
    err = capsys.readouterr().err
    assert err.count("looser than the code default") == 2 and "[governor].a = 4 is looser than the code default 5" in err
    gov()
    assert capsys.readouterr().err == ""                                          # once per process


def test_a_toml_baseline_tighter_than_or_equal_to_the_code_default_is_kept(env, capsys):
    g.toml_path().write_text(FIXTURE.replace("a = 10.0", "a = 7.0").replace("c = 30.0", "c = 40.0"))   # a tighter, c equal
    t, info = gov()
    assert (t["a"], t["c"]) == (7.0, 40.0) and info["baseline_guarded"] == {}
    assert "looser" not in capsys.readouterr().err


def _huge(digits: int) -> str:
    return "1" + "0" * (digits - 1)


@pytest.mark.parametrize("digits", [400, 5000])      # 400: too big for a float; 5000: past Python's 4300-digit int<->str limit
def test_a_huge_integer_in_the_toml_baseline_cannot_crash_a_gate(env, digits):
    g.toml_path().write_text(FIXTURE.replace("a = 10.0", f"a = {_huge(digits)}"))
    t, info = gov()
    assert t == CODE_DEFAULTS and info["toml_error"]


@pytest.mark.parametrize("digits", [400, 5000])
def test_a_huge_integer_in_a_toml_profile_cannot_crash_a_gate(env, digits):
    g.toml_path().write_text(FIXTURE.replace("[profiles.away.governor]\na = 5.0", f"[profiles.away.governor]\na = {_huge(digits)}"))
    write_state(state_path())
    t, info = gov()
    assert info["profile"] is None and t["a"] in (10.0, CODE_DEFAULTS["a"]), info


def test_a_huge_integer_as_max_profile_hours_means_the_default_cap(env):
    g.toml_path().write_text(FIXTURE.replace("max_profile_hours = 100", f"max_profile_hours = {_huge(400)}"))
    write_state(state_path())
    t, info = gov()
    assert info["profile"]["name"] == "away" and t["a"] == 5.0
    write_state(state_path(), since=g.iso(NOW - timedelta(hours=1)), until=g.iso(NOW + timedelta(hours=500)))
    assert "over max_profile_hours" in gov()[1]["ignored"]
    g.toml_path().write_text(FIXTURE.replace("max_profile_hours = 100", f"max_profile_hours = {_huge(5000)}"))
    assert gov()[1]["toml_error"]


@pytest.mark.parametrize("digits, why", [(400, "unknown or non-numeric"), (5000, "not JSON")])
def test_a_huge_integer_in_the_env_json_is_a_gate_env_error_not_a_crash(env, monkeypatch, digits, why):
    monkeypatch.setenv("CLAUDE_GOVERNOR_THRESHOLDS", '{"a": %s}' % _huge(digits))
    with pytest.raises(g.GateEnvError, match=why):
        gov()


def test_a_huge_integer_in_the_profile_file_is_baseline(env):
    Path(state_path()).parent.mkdir(parents=True)
    Path(state_path()).write_text('{"schema": 1, "reason": %s}' % _huge(5000))
    t, info = gov()
    assert t["a"] == 10.0 and "corrupt JSON" in info["ignored"]


@pytest.mark.parametrize("span", ["99999999999d", "9" * 5000 + "d", "999999999999999h"])
def test_an_absurd_duration_is_a_clean_refusal(cli, span):
    r = cli.run("set", "away", "--for", span, "--reason", "x")
    assert r.returncode == 1 and "is not Nm, Nh or Nd" in r.stderr and "Traceback" not in r.stderr, r.stderr
    assert not cli.state.exists()
    assert cli.run("set", "away", "--for", "2h", "--reason", "x").returncode == 0
    r = cli.run("extend", "--for", span)
    assert r.returncode == 1 and "is not Nm, Nh or Nd" in r.stderr and "Traceback" not in r.stderr, r.stderr


def _plant(kind: str, path: Path, tmp: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "dir":
        path.mkdir()
    elif kind in ("symlink_to_valid_file", "symlink_to_dev_zero", "dangling_symlink"):
        target = {"symlink_to_valid_file": tmp / "real.json", "symlink_to_dev_zero": Path("/dev/zero"),
                  "dangling_symlink": tmp / "nothing"}[kind]
        if kind == "symlink_to_valid_file":
            write_state(target)
        path.symlink_to(target)
    elif kind == "oversized":
        write_state(path, pad="x" * 70000)               # valid JSON and a valid profile, 70 KB


@pytest.mark.parametrize("kind, why", [
    ("fifo", "not a regular file"), ("dir", "not a regular file"), ("symlink_to_valid_file", "symlink"),
    ("symlink_to_dev_zero", "symlink"), ("dangling_symlink", "symlink"), ("oversized", "larger than 64 KiB"),
])
def test_the_profile_file_must_be_a_small_regular_file_never_read_through_a_link_or_waited_on(env, tmp_path, kind, why):
    _plant(kind, Path(state_path()), tmp_path)
    t, info = _bounded(gov)
    assert info["profile"] is None and t["a"] == 10.0 and why in info["ignored"], info["ignored"]


def test_a_profile_file_under_the_cap_still_applies(env):
    write_state(state_path(), pad="x" * 30000)
    assert gov()[0]["a"] == 5.0


def test_a_lock_file_that_is_a_fifo_or_a_link_is_no_lock_and_never_blocks(env, tmp_path):
    lock = Path(state_path() + ".lock")
    lock.parent.mkdir(parents=True)
    os.mkfifo(lock)
    assert _bounded(lambda: g._state_lock(0.2)) is None
    lock.unlink()
    lock.symlink_to(tmp_path / "elsewhere")
    assert g._state_lock(0.2) is None and not (tmp_path / "elsewhere").exists()


@pytest.mark.parametrize("schema", [True, 1.0, "1", 2])
def test_the_schema_must_be_the_integer_one(env, schema):
    write_state(state_path(), schema=schema)
    t, info = gov()
    assert info["profile"] is None and t["a"] == 10.0 and "schema" in info["ignored"]


@pytest.mark.parametrize("name", ["Away", "ａway", "a" * 33, "away day"])
def test_a_profile_name_outside_ascii_a_z_0_9_underscore_hyphen_is_ignored_at_run_time_and_refused_by_set(env, cli, name):
    g.toml_path().write_text(FIXTURE + f'\n[profiles."{name}".governor]\na = 5.0\n')
    write_state(state_path(), profile=name)
    t, info = gov()
    assert info["profile"] is None and t["a"] == 10.0 and "not a valid name" in info["ignored"], info["ignored"]
    r = cli.run("set", name, "--for", "2h", "--reason", "x", GATES_TOML=str(g.toml_path()))
    assert r.returncode == 1 and "[a-z0-9_-]" in r.stderr and json.loads(cli.state.read_text())["profile"] == name


def test_the_set_ping_is_one_clean_clipped_line_and_an_over_long_reason_or_by_is_refused(cli):
    r = cli.run("set", "away", "--for", "72h", "--reason", "line one\nline two \x1b[31m" + "y" * 300, "--by", "bob\nsmith")
    assert r.returncode == 0, r.stderr
    pings = [ln for ln in cli.called() if ln.startswith("ping ")]
    assert len(pings) == 1 and "\x1b" not in pings[0] and "by bob smith: line one line two" in pings[0]
    clipped = pings[0].split(" by bob smith: ", 1)[1]
    assert clipped.endswith("…") and len(clipped) == 120
    assert json.loads(cli.state.read_text())["set_by"] == "bob\nsmith"            # the audit trail keeps what was typed
    for args in (("--reason", "r" * 501), ("--reason", "x", "--by", "b" * 65)):
        cli.state.unlink(missing_ok=True)
        r = cli.run("set", "away", "--for", "2h", *args)
        assert r.returncode == 1 and "limited to" in r.stderr and not cli.state.exists(), args


def test_the_guard_recomputes_before_the_governor_runs_after_every_change(cli):
    """Codex P2 on PR 84: the governor takes the stricter cached guard level, so a loosening change must refresh the guard first."""
    for args in (("set", "away", "--for", "2h", "--reason", "x"), ("extend", "--for", "1h"), ("clear",)):
        cli.calls.unlink(missing_ok=True)
        r = cli.run(*args)
        assert r.returncode == 0, (args, r.stderr)
        order = [ln.split()[0] for ln in cli.called()]
        assert order == ["ping", "guard", "governor"], (args, order)


def test_clear_removes_the_file_and_warns_when_the_guard_recompute_fails(cli):
    cli.run("set", "away", "--for", "2h", "--reason", "x")
    bad = cli.tmp / "bad-guard"
    bad.write_text("#!/bin/sh\nexit 1\n")
    bad.chmod(0o755)
    r = cli.run("clear", GATE_PROFILE_GUARD=str(bad))
    assert r.returncode == 0 and not cli.state.exists()
    assert "guard recompute: rc=1" in r.stdout and "hook may keep printing the profile line until the next guard run" in r.stderr
    cli.run("set", "away", "--for", "2h", "--reason", "x")
    assert "warning" not in cli.run("clear").stderr                                 # control: a working guard, no warning


def _real_gov(env, edit: tuple[str, str] | None = None):
    toml = REAL if edit is None else REAL.replace(*edit, 1)
    assert edit is None or edit[0] in REAL, edit
    g.toml_path().write_text(toml)
    write_state(state_path())
    return g.load_gates("governor", NOW, _thresholds("claude-fleet-governor"))


@pytest.mark.parametrize("edit, why", [
    (("tight_left_weekly = 15.0", "tight_left_weekly = 8.0"), "tight_left_weekly 8 must be at least critical_left 10"),
    (("tight_left_five_hour = 15.0", "tight_left_five_hour = 10.0"), None),            # equal is in order: the control
])
def test_a_profile_that_puts_the_governors_tight_triggers_below_critical_is_rejected_whole(env, edit, why):
    t, info = _real_gov(env, edit)
    if why is None:
        assert info["profile"]["name"] == "away" and t["tight_left_five_hour"] == 10.0
        return
    assert info["profile"] is None and why in info["ignored"], info["ignored"]
    assert t == info["baseline"]
    r = subprocess.run([sys.executable, "-I", str(CLI), "validate"], capture_output=True, text=True, timeout=60,
                       env={"PATH": os.environ["PATH"], "HOME": "/nonexistent", "GATES_TOML": str(g.toml_path())})
    assert r.returncode == 1 and "profile away.governor:" in r.stdout and why in r.stdout


# -- adversary round 2 follow-up (2026-10-27): deep toml, an unusable lock path, a stale expiry mark -------------------------

DEEP_TOML = "x = " + "[" * 5000 + "]" * 5000 + "\n"           # past the interpreter's recursion limit


@pytest.mark.parametrize("gate, defaults", [("governor", CODE_DEFAULTS), ("quota_guard", GUARD_DEFAULTS)])
def test_a_deeply_nested_gates_toml_is_unreadable_not_a_crash(env, gate, defaults):
    g.toml_path().write_text(DEEP_TOML)
    t, info = g.load_gates(gate, NOW, defaults)
    assert t == defaults and "not valid TOML" in info["toml_error"]


def test_the_cli_reads_a_deeply_nested_gates_toml_as_unreadable_not_a_traceback(env, cli):
    g.toml_path().write_text(DEEP_TOML)
    for args in (("status",), ("validate",)):
        r = cli.run(*args, GATES_TOML=str(g.toml_path()))
        assert "Traceback" not in r.stderr and "RecursionError" not in r.stderr, (args, r.stderr[-300:])
    assert cli.run("validate", GATES_TOML=str(g.toml_path())).returncode == 1


LOCK_KINDS = ["fifo", "dir", "dangling_symlink", "symlink_to_valid_file"]


def _break_lock(cli, kind: str) -> Path:
    lock = Path(f"{cli.state}.lock")
    lock.unlink(missing_ok=True)
    _plant(kind, lock, cli.tmp)
    return lock


@pytest.mark.parametrize("kind", LOCK_KINDS)
def test_clear_works_without_a_usable_lock_and_names_the_lock_path(cli, kind):
    assert cli.run("set", "away", "--for", "2h", "--reason", "x").returncode == 0
    lock = _break_lock(cli, kind)
    target = lock.resolve() if lock.is_symlink() else None
    before = target.read_bytes() if target is not None and target.exists() else None
    r = cli.run("clear", GATE_PROFILE_LOCK_WAIT="0.5")
    assert r.returncode == 0 and not cli.state.exists(), r.stderr
    assert str(lock) in r.stderr and "cleared: baseline in force" in r.stdout
    after = target.read_bytes() if target is not None and target.exists() else None
    assert after == before                                                              # a link's target is never written through


@pytest.mark.parametrize("kind", LOCK_KINDS)
def test_set_and_extend_refuse_an_unusable_lock_naming_its_path(cli, kind):
    assert cli.run("set", "away", "--for", "2h", "--reason", "x").returncode == 0
    lock = _break_lock(cli, kind)
    before = cli.state.read_text()
    for args in (("set", "away", "--for", "3h", "--reason", "y"), ("extend", "--for", "1h")):
        r = cli.run(*args)
        assert r.returncode == 1 and str(lock) in r.stderr, (args, r.stderr)
        assert cli.state.read_text() == before


@pytest.mark.parametrize("kind", LOCK_KINDS)
def test_the_notices_say_so_once_when_the_lock_path_is_unusable(env, cli, capsys, kind):
    lock = _break_lock(cli, kind)
    write_state(state_path(), since="2026-10-26T12:00:00Z", until="2026-10-29T16:00:00Z", last_daily_nudge="2026-10-26")
    _, active = gov(NOW + timedelta(days=1))
    sent: list[str] = []
    for _ in range(2):
        assert _bounded(lambda: g.notify_daily(active, lambda m: sent.append(m) or True, NOW + timedelta(days=1))) is False
    write_state(state_path(), until=g.iso(NOW - timedelta(minutes=1)), since=g.iso(NOW - timedelta(hours=70)))
    _, expired = gov()
    for _ in range(2):
        assert _bounded(lambda: g.notify_expired(expired, lambda m: sent.append(m) or True, NOW)) is False
    err = capsys.readouterr().err
    assert sent == [] and err.count(str(lock)) == 2, err                         # one line per notice kind, not one per run
    assert "daily nudge skipped" in err and "expiry notice skipped" in err


def test_extend_does_not_carry_a_stale_expiry_mark_so_the_real_expiry_pings(env, cli):
    # the state an expiry notice that raced `extend` leaves: an unexpired profile that already carries `expired_notified`
    write_state(state_path(), since=g.iso(NOW - timedelta(hours=1)), until=g.iso(NOW + timedelta(hours=2)),
                expired_notified=g.iso(NOW - timedelta(minutes=5)))
    r = cli.run("extend", "--for", "1h", GATES_TOML=str(g.toml_path()))
    assert r.returncode == 0, r.stderr
    saved = json.loads(Path(state_path()).read_text())
    assert "expired_notified" not in saved and saved["until"] == g.iso(NOW + timedelta(hours=3))
    later = NOW + timedelta(hours=4)
    _, info = gov(later)
    assert info["expired"] is not None and info["expired"]["name"] == "away"
    sent: list[str] = []
    assert g.notify_expired(info, lambda m: sent.append(m) or True, later) is True and len(sent) == 1


# -- the [frontier] gate (2026-10-27): floors, baseline guard, no env override, the guard-state check, the reason form ----------

@pytest.fixture
def fenv(tmp_path, monkeypatch):
    """A copy of the SHIPPED gates.toml, a missing profile state and no env override; returns the toml path."""
    toml = tmp_path / "gates.toml"
    toml.write_text((REPO / "config" / "gates.toml").read_text())
    monkeypatch.setenv("GATES_TOML", str(toml))
    monkeypatch.setenv("GATE_PROFILE_STATE", str(tmp_path / "state" / "gate-profile.json"))
    for var in g.ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    g._LOGGED.clear()
    return toml


STANDING = {"frontier1_judged": 1.0, "frontier2_judged": 1.0, "frontier1_per_wave": 2.0, "frontier2_per_wave": 1.0,
            "frontier1_agent_calls_per_day": 4.0, "frontier1_min_left": 10.0, "frontier2_min_left": 60.0}     # the 2026-10-27 ruling


def close_frontier_baseline(text: str) -> str:
    """The shipped file with its `[frontier]` BASELINE set to the all-closed code defaults (floors and the away profile unchanged)."""
    import re
    def close(m):
        body = m.group(0)
        for k, v in g.FRONTIER_DEFAULTS.items():
            body = re.sub(rf"(?m)^{k} = [0-9.]+", f"{k} = {v:g}", body, count=1)
        return body
    out = re.sub(r"(?ms)^\[frontier\]\n.*?(?=^\[|\Z)", close, text, count=1)
    assert out != text
    return out


@pytest.fixture
def fenv_closed(fenv):
    """`fenv` with a CLOSED frontier baseline: the pre-2026-10-27 rule, so the profile floors and fail-closed behaviour stay covered."""
    fenv.write_text(close_frontier_baseline(fenv.read_text()))
    return fenv


def front(now=NOW):
    return g.load_frontier(now)


def test_the_shipped_frontier_baseline_is_the_ruled_standing_allowance(fenv):
    t, info = front()
    assert t == STANDING and info["profile"] is None and info["baseline_guarded"] == {} and info["toml_error"] is None


def test_a_closed_frontier_baseline_is_the_code_default(fenv_closed):
    t, info = front()
    assert t == g.FRONTIER_DEFAULTS and info["profile"] is None
    assert (t["frontier1_judged"], t["frontier2_judged"], t["frontier1_agent_calls_per_day"]) == (0, 0, 0)
    assert (t["frontier1_per_wave"], t["frontier2_per_wave"], t["frontier1_min_left"]) == (1, 1, 10)


def test_the_shipped_away_profile_equals_the_standing_baseline(fenv):
    write_state(state_path())
    t, info = front()
    assert info["profile"]["name"] == "away" and info["ignored"] is None
    assert t == STANDING


def test_the_shipped_away_profile_raises_a_closed_baseline_to_the_ruled_values(fenv_closed):
    write_state(state_path())
    t, info = front()
    assert info["profile"]["name"] == "away" and info["ignored"] is None
    assert t == STANDING


@pytest.mark.parametrize("key, value, why", [("frontier1_judged", 0, "tighter than the baseline 1"),
                                              ("frontier1_agent_calls_per_day", 3, "tighter than the baseline 4"),
                                              ("frontier1_agent_calls_per_day", 5, "above the ceiling 4"),
                                              ("frontier1_per_wave", 3, "above the ceiling 2"),
                                              ("frontier2_min_left", 70, "tighter than the baseline 60")])
def test_a_profile_can_neither_tighten_nor_widen_the_standing_baseline(fenv, key, value, why):
    """gate-profile cannot close the standing allowance (a value under the baseline rejects the whole profile) nor pass its floors."""
    fenv.write_text(fenv.read_text() + f"\n[profiles.t.frontier]\n{key} = {value}\n")
    write_state(state_path(), profile="t")
    t, info = front()
    assert t == STANDING and why in info["ignored"], (t, info["ignored"])


def test_an_expired_profile_gives_the_frontier_baseline(fenv_closed):
    write_state(state_path(), since=g.iso(NOW - timedelta(hours=80)), until=g.iso(NOW - timedelta(seconds=1)))
    t, info = front()
    assert t == g.FRONTIER_DEFAULTS and "expired" in info["ignored"]


@pytest.mark.parametrize("key, value, why", [
    ("frontier1_judged", 2, "above the ceiling 1"),
    ("frontier2_judged", 2, "above the ceiling 1"),
    ("frontier1_per_wave", 3, "above the ceiling 2"),
    ("frontier2_per_wave", 2, "above the ceiling 1"),
    ("frontier1_agent_calls_per_day", 5, "above the ceiling 4"),
    ("frontier1_min_left", 9.9, "below the floor 10"),
    ("frontier2_min_left", 39.9, "below the floor 40"),
    ("frontier1_per_wave", 0, "tighter than the baseline 1"),
    ("frontier1_min_left", 11, "tighter than the baseline 10"),
    ("frontier1_judged", -1, "tighter than the baseline 0"),
    ("frontier1_per_wave", "2", "not a number"),
    ("frontier3_judged", 1, "not overridable"),
])
def test_the_floors_refuse_a_looser_frontier_value_and_the_whole_profile_is_baseline(fenv_closed, key, value, why):
    fenv = fenv_closed
    shown = value if isinstance(value, (int, float)) else f'"{value}"'
    good = "frontier2_judged" if key == "frontier1_judged" else "frontier1_judged"       # a valid companion value
    fenv.write_text(fenv.read_text() + f"\n[profiles.t.frontier]\n{good} = 1\n{key} = {shown}\n")
    write_state(state_path(), profile="t")
    t, info = front()
    assert t == g.FRONTIER_DEFAULTS, f"one bad value rejects the whole profile: even the valid {good} = 1"
    assert why in info["ignored"], info["ignored"]


@pytest.mark.parametrize("key, value", [("frontier1_agent_calls_per_day", 4), ("frontier1_per_wave", 2), ("frontier2_min_left", 40),
                                        ("frontier2_per_wave", 1), ("frontier1_min_left", 10)])
def test_a_frontier_value_at_its_bound_is_allowed(fenv_closed, key, value):
    fenv = fenv_closed
    fenv.write_text(fenv.read_text() + f"\n[profiles.t.frontier]\n{key} = {value}\n")
    write_state(state_path(), profile="t")
    t, info = front()
    assert info["ignored"] is None and t[key] == float(value)


def test_a_gates_toml_baseline_past_its_floor_bound_is_replaced_by_the_code_default(fenv):
    """The standing numbers are the ceiling a hand edit of the baseline can reach: a value past its floor bound, or a lower
    `*_min_left`, gets the code default; the in-bound standing values stay."""
    fenv.write_text(fenv.read_text().replace("frontier1_agent_calls_per_day = 4 ", "frontier1_agent_calls_per_day = 5 ", 1)
                    .replace("frontier1_per_wave = 2 ", "frontier1_per_wave = 3 ", 1)
                    .replace("frontier1_min_left = 10.0 ", "frontier1_min_left = 1.0 ", 1))
    t, info = front()
    assert (t["frontier1_agent_calls_per_day"], t["frontier1_per_wave"], t["frontier1_min_left"]) == (0, 1, 10)
    assert (t["frontier1_judged"], t["frontier2_judged"], t["frontier2_per_wave"]) == (1, 1, 1)
    assert set(info["baseline_guarded"]) == {"frontier1_agent_calls_per_day", "frontier1_per_wave", "frontier1_min_left"}


def test_a_frontier_min_left_baseline_is_never_looser_than_the_code_default_even_inside_its_floor(fenv):
    """frontier2_min_left's floor is 40 (a profile may go there), but the baseline may not: 50 is inside the floor and still guarded."""
    fenv.write_text(fenv.read_text().replace("frontier2_min_left = 60.0 ", "frontier2_min_left = 50.0 ", 1))
    t, info = front()
    assert t["frontier2_min_left"] == 60 and set(info["baseline_guarded"]) == {"frontier2_min_left"}


def test_a_missing_frontier_floor_table_still_guards_every_frontier_key(fenv):
    """With no floor entry there is no bound to rise to: every standing key above its code default falls back to it."""
    fenv.write_text(fenv.read_text().replace("[floors.frontier]", "[floors.unused]", 1)
                    .replace("frontier1_min_left = 10.0 ", "frontier1_min_left = 1.0 ", 1)
                    .replace("frontier2_min_left = 60.0 ", "frontier2_min_left = 70.0 ", 1))
    t, info = front()
    assert t == {**g.FRONTIER_DEFAULTS, "frontier2_min_left": 70.0}     # tighter than the code default: the file may tighten
    assert set(info["baseline_guarded"]) == {"frontier1_judged", "frontier2_judged", "frontier1_per_wave", "frontier1_agent_calls_per_day",
                                             "frontier1_min_left"}


def test_a_flipped_frontier_floor_direction_does_not_loosen_the_baseline(fenv):
    """The code direction rules the frontier gate: a floor entry whose `loosen` disagrees (adversary round 2, A4) changes nothing:
    its `bound` (0) still caps the baseline, so the standing 1 and 4 are looser than it and the code default stands."""
    text = (fenv.read_text()
            .replace('frontier1_judged = { loosen = "higher", bound = 1 }', 'frontier1_judged = { loosen = "lower", bound = 0 }')
            .replace('frontier1_agent_calls_per_day = { loosen = "higher", bound = 4 }',
                     'frontier1_agent_calls_per_day = { loosen = "lower", bound = 0 }'))
    assert text.count('loosen = "lower", bound = 0') == 2
    fenv.write_text(text)
    t, info = front()
    assert (t["frontier1_judged"], t["frontier1_agent_calls_per_day"]) == (0, 0)
    assert set(info["baseline_guarded"]) == {"frontier1_judged", "frontier1_agent_calls_per_day"}


def flipped_floor_toml(text, floor_key, loosen, bound, baseline, profile_key, profile_value):
    """The shipped file with one frontier floor's `loosen`/`bound` rewritten, its baseline raised and the away profile set to a value."""
    import re
    text = re.sub(rf"(?m)^{floor_key} = \{{.*\}}", f'{floor_key} = {{ loosen = "{loosen}", bound = {bound} }}', text)
    text = re.sub(rf"(?ms)(^\[frontier\]\n.*?^){floor_key} = [0-9.]+", rf"\g<1>{floor_key} = {baseline}", text, count=1)
    def in_profile(m):
        body = m.group(1)
        if re.search(rf"(?m)^{profile_key} = ", body):
            body = re.sub(rf"(?m)^{profile_key} = [0-9.]+", f"{profile_key} = {profile_value}", body)
        else:
            body += f"{profile_key} = {profile_value}\n"
        return body + m.group(2)
    return re.sub(r"(?ms)(^\[profiles\.away\.frontier\]\n.*?)(^\[|\Z)", in_profile, text, count=1)


@pytest.mark.parametrize("key, loosen, bound, baseline, value, why", [
    ("frontier1_agent_calls_per_day", "lower", 0, 100, 100, "above the ceiling 0"),      # code: higher is looser, so 100 busts a bound of 0
    ("frontier1_min_left", "higher", 100, 0, 0, "below the floor 100"),                   # code: lower is looser, so 0 busts a bound of 100
])
def test_a_flipped_frontier_floor_cannot_let_a_profile_exceed_its_bound(fenv_closed, key, loosen, bound, baseline, value, why):
    """The profile check uses the code direction too (adversary round 3, P3-2), not only the baseline guard."""
    fenv = fenv_closed
    text = flipped_floor_toml(fenv.read_text(), key, loosen, bound, baseline, key, value)
    fenv.write_text(text)
    write_state(state_path())
    t, info = front()
    assert t == g.FRONTIER_DEFAULTS and why in info["ignored"], (t, info["ignored"])


def test_the_code_direction_leaves_the_shipped_floors_and_other_gates_alone(fenv):
    cfg, err = g.read_toml()
    assert err is None
    assert g.profile_problems(cfg, "away", g.toml_baselines(cfg)) == []
    assert g.effective_spec(cfg, "frontier", "frontier1_min_left") == g.floor_spec(cfg, "frontier", "frontier1_min_left")
    assert g.effective_spec(cfg, "frontier", "frontier1_per_wave")["loosen"] == "higher"
    assert g.effective_spec(cfg, "governor", "no_such_key") is None
    assert g.code_direction("quota_guard", "frontier1_min_left") is None


@pytest.mark.parametrize("text", ["line\u2028two reason", "zero\u200dwidth joiner", "soft\u00adhyphen reason", "tab\there reason", "esc\x1b[31m red"])
def test_a_frontier_reason_with_a_control_or_format_character_names_that_rule(text):
    reason, problem = g.frontier_reason(text)
    assert reason is None and "one line, no control or format character" in problem


def test_a_gates_toml_that_is_a_fifo_is_unusable_not_a_hang(tmp_path, monkeypatch):
    fifo = tmp_path / "gates.toml"
    os.mkfifo(fifo)
    monkeypatch.setenv("GATES_TOML", str(fifo))
    cfg, err = g.read_toml()
    assert cfg is None and "not a regular file" in err


def test_no_environment_variable_changes_the_frontier_gate(fenv_closed, monkeypatch):
    assert "frontier" not in g.ENV_VARS
    for var in (*g.ENV_VARS.values(), "FRONTIER_GATE_THRESHOLDS", "CLAUDE_FRONTIER_THRESHOLDS"):
        monkeypatch.setenv(var, json.dumps({"frontier1_judged": 1, "frontier1_agent_calls_per_day": 99}))
    assert front()[0] == g.FRONTIER_DEFAULTS
    assert g.env_overrides("frontier", dict(g.FRONTIER_DEFAULTS)) == {}


def test_a_missing_gates_toml_is_the_frontier_code_default(fenv, monkeypatch):
    monkeypatch.setenv("GATES_TOML", "/nonexistent/gates.toml")
    write_state(state_path())
    t, info = front()
    assert t == g.FRONTIER_DEFAULTS and info["profile"] is None
    assert (t["frontier1_judged"], t["frontier2_judged"], t["frontier1_agent_calls_per_day"]) == (0, 0, 0)


@pytest.mark.parametrize("text", ["[frontier\n", "[frontier]\nfrontier1_judged = \"1\"\n", "", "[governor]\na = 1\n"])
def test_an_unreadable_or_invalid_gates_toml_leaves_the_frontier_gate_closed(fenv, text):
    """The standing allowance lives only in a readable [frontier] table: corrupt TOML, a non-number, an empty file or a file with no
    [frontier] table all fall back to the all-closed code default (so the hook asks)."""
    fenv.write_text(text)
    write_state(state_path())
    t, info = front()
    assert t == g.FRONTIER_DEFAULTS and info["toml_error"] is not None
    assert (t["frontier1_judged"], t["frontier2_judged"], t["frontier1_agent_calls_per_day"]) == (0, 0, 0)       # closed, not merely "the default"


GUARD_OK = {"level": "ok", "reasons": [], "stale": False, "fable_left": 50.0, "checked_at": g.iso(NOW - timedelta(minutes=1))}


def test_judged_guard_block_passes_a_fresh_ok_state_and_a_weekly_watch():
    t = g.FRONTIER_DEFAULTS
    assert g.judged_guard_block(GUARD_OK, t, NOW) is None
    assert g.judged_guard_block({**GUARD_OK, "level": "watch", "reasons": ["weekly"]}, t, NOW) is None


@pytest.mark.parametrize("over, why", [
    ({"level": "tight"}, "tight"), ({"level": "critical"}, "critical"), ({"level": None}, "None"),
    ({"stale": True}, "stale"), ({"stale": None}, "stale"),
    ({"level": "watch", "reasons": ["fable"]}, "other than the weekly"),
    ({"level": "watch", "reasons": ["weekly", "stale"]}, "other than the weekly"),
    ({"level": "watch", "reasons": []}, "other than the weekly"),
    ({"reasons": ["weekly"]}, "at level ok"),
    ({"fable_left": 9.99}, "frontier-1 cap has"), ({"fable_left": None}, "missing"), ({"fable_left": True}, "missing"),
    ({"checked_at": None}, "checked_at"), ({"checked_at": "2026-10-26T11:59:00"}, "checked_at"),
])
def test_judged_guard_block_refuses(over, why):
    st = {**GUARD_OK, **over}
    assert why in g.judged_guard_block(st, g.FRONTIER_DEFAULTS, NOW)


def test_judged_guard_block_age_and_cap_boundaries():
    t = g.FRONTIER_DEFAULTS
    at = lambda secs: {**GUARD_OK, "checked_at": g.iso(NOW - timedelta(seconds=secs))}      # noqa: E731
    assert g.judged_guard_block(at(1800), t, NOW) is None and "min old" in g.judged_guard_block(at(1801), t, NOW)
    assert g.judged_guard_block(at(-60), t, NOW) is None and "min old" in g.judged_guard_block(at(-61), t, NOW)
    assert g.judged_guard_block({**GUARD_OK, "fable_left": 10.0}, t, NOW) is None
    assert g.judged_guard_block({**GUARD_OK, "fable_left": 19.9}, {**t, "frontier1_min_left": 20.0}, NOW) is not None
    for bad in (None, [], "ok", 7):
        assert "missing or unreadable" in g.judged_guard_block(bad, t, NOW)


@pytest.mark.parametrize("text, ok", [("a" * 9, False), ("a" * 10, True), ("  " + "a" * 200 + "  ", True), ("a" * 201, False),
                                      ("", None), ("   ", None), (None, None), ("ten chars\nmore", False), ("tab\tin the reason", False),
                                      (12345, False), ("ten chars\u2028more", False), ("ten chars\u0085more", False),
                                      ("ten chars\u009bmore", False), ("ten chars\u202emore", False)])
def test_frontier_reason_form(text, ok):
    reason, problem = g.frontier_reason(text)
    if ok is None:
        assert (reason, problem) == (None, None)             # missing or blank: the baseline treatment, not an error
    elif ok:
        assert reason == text.strip() and problem is None
    else:
        assert reason is None and problem
