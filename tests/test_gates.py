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
CODE_DEFAULTS = {"a": 99.0, "b": 99.0, "c": 99.0}
GUARD_DEFAULTS = {"q": 99.0}


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
    assert (t["a"], t["b"], t["c"]) == (99.0, 20.0, 99.0) and info["source"] == "gates.toml"
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

    def run(self, *args, now: datetime = NOW, **extra):
        env = {"PATH": os.environ["PATH"], "HOME": str(self.tmp / "home"), "USER": "tester", "GATE_PROFILE_STATE": str(self.state),
               "GATE_PROFILE_LOG": str(self.log), "GATE_PROFILE_PING": str(self.tmp / "fake-ping"),
               "GATE_PROFILE_GOVERNOR": str(self.tmp / "fake-governor"), "GATE_PROFILE_GUARD": str(self.tmp / "fake-guard"),
               "GATE_PROFILE_NOW": g.iso(now), **extra}
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=env, capture_output=True, text=True, timeout=60)

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
        ("tight_weekly = 15.0\n# Aligned", "tight_weekly = 15.0\nlock_wait_s = 0.1\n# Aligned", "not overridable"),
        ("[meta]\nschema = 1", "[meta]\nschema = 2", "schema"),
        ("max_profile_hours = 240", "max_profile_hours = 0", "max_profile_hours"),
        ('loosen = "higher", bound = 1000.0', 'loosen = "sideways", bound = 1000.0', "loosen"),
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
