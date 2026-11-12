"""Offline advisory boundaries, expiry and CLI integration."""
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
spec = importlib.util.spec_from_file_location("quota_advisory_test", ROOT / "bin/quota_nudge.py")
nudge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nudge)


def test_levels_freshness_overrides_and_bad_numbers(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("[thresholds]\ncritical_left=10\nconserve_left=30\nmax_age_seconds=60\n[pools.custom]\nconserve_left=60\n")
    values = {"ok": 31, "conserve": 30, "critical": 10, "empty": 0,
              "bad": float("nan"), "bool": True, "outside": 101, "custom": 50}
    quota = {key: {"remaining": value, "age_s": 60} for key, value in values.items()}
    quota.update(stale={"remaining": 90, "age_s": 61}, future={"remaining": 90, "age_s": -1},
                 missing={"remaining": 90}, unknown={"remaining": None, "age_s": 0})
    rows = {row["pool"]: row["level"] for row in nudge.report(quota, config=config, profiles={})}
    assert rows == {"ok": "ok", "conserve": "conserve", "critical": "critical", "empty": "critical",
                    "bad": "unknown", "bool": "unknown", "outside": "unknown", "custom": "conserve",
                    "stale": "unknown", "future": "unknown", "missing": "unknown", "unknown": "unknown"}


def test_profiles_expire_at_boundary_and_read_never_writes(tmp_path):
    path = tmp_path / "profiles.json"
    raw = {"agy": {"name": "spend headroom", "until": "2026-11-13T00:00:00Z"},
           "bad": {"name": "bad", "until": "2026-11-14T00:00:00"}}
    path.write_text(json.dumps(raw))
    before = path.read_bytes()
    assert list(nudge.load_profiles(path, datetime(2026, 11, 12, tzinfo=timezone.utc))) == ["agy"]
    assert nudge.load_profiles(path, datetime(2026, 11, 13, tzinfo=timezone.utc)) == {}
    assert path.read_bytes() == before


def test_set_clear_and_profile_without_measurement(tmp_path, monkeypatch, capsys):
    path = tmp_path / "profiles.json"
    monkeypatch.setenv("ADE_SPENDING_PROFILES", str(path))
    assert nudge.main(["--set-profile", "openai", "--name", "metered allowed", "--until", "2099-01-01T00:00:00Z"]) == 0
    nudge.print_reminder({})
    output = capsys.readouterr().out
    assert "openai: unknown" in output and "metered allowed" in output
    assert nudge.main(["--clear-profile", "openai"]) == 0
    assert json.loads(path.read_text()) == {}


def test_reminder_uses_merged_router_sources(monkeypatch, capsys):
    import route_agent
    monkeypatch.setattr(route_agent, "load_snapshot", lambda: ({"pool": {"remaining": 10, "age_s": 0}}, 0))
    monkeypatch.setattr(nudge, "load_profiles", lambda: {})
    assert nudge.main([]) == 0
    assert "pool: critical" in capsys.readouterr().out


def test_invalid_profile_rejected(tmp_path):
    import pytest
    for until in ("2026-01-01T00:00:00Z", "2099-01-01T00:00:00", "nonsense"):
        with pytest.raises(ValueError):
            nudge.save_profile("pool", "spend", until, tmp_path / "profiles.json")
    assert not (tmp_path / "profiles.json").exists()


def test_invalid_config_is_advisory(tmp_path, monkeypatch, capsys):
    import pytest
    config = tmp_path / "bad.toml"
    config.write_text("pools=[]\n[thresholds]\ncritical_left=10\nconserve_left=30\nmax_age_seconds=60\n")
    original = nudge.report
    with pytest.raises(ValueError, match="must be tables"):
        original({"pool": {}}, config=config)
    monkeypatch.setattr(nudge, "report", lambda quota: original(quota, config=config))
    nudge.print_reminder({"pool": {}})
    assert "unavailable" in capsys.readouterr().out


def test_cli_reads_aiuse_and_paseo_and_show(tmp_path):
    import os
    import subprocess
    # Both sources identify the configured Claude pool. Provider-only readings
    # are deliberately rejected by the router's pool-family contract (#581).
    now = "2026-11-12T12:00:00+00:00"
    aiuse = tmp_path / "aiuse.json"
    aiuse.write_text(json.dumps({"schema_version": "1.3", "fresh": True, "age_seconds": 0,
        "available": [{"provider": "claude", "pool_family": "default", "age_seconds": 0,
                       "usable_now": True, "headroom_percent": 80}]}))
    paseo = tmp_path / "paseo.json"
    env = {**os.environ, "ROUTE_AGENT_AIUSE_JSON": str(aiuse),
           "ROUTE_AGENT_PASEO_USAGE_JSON": str(paseo), "ROUTE_AGENT_PASEO": "on",
           "AIUSE_SNAPSHOT": str(tmp_path / "absent.json"),
           "ADE_SPENDING_PROFILES": str(tmp_path / "absent-profiles.json")}
    # Freeze only the router's clock in each child. The real entry points,
    # parser, source merge and freshness checks all run against fixed fixtures.
    runner = """
import runpy
import sys
from datetime import datetime
sys.path.insert(0, sys.argv[1])
import route_agent
class FixtureDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        stamp = cls.fromisoformat("2026-11-12T12:00:00+00:00")
        return stamp.astimezone(tz) if tz else stamp.replace(tzinfo=None)
route_agent.datetime = FixtureDatetime
sys.argv = sys.argv[2:]
if sys.argv[0].endswith("/route_agent.py"):
    raise SystemExit(route_agent.main(sys.argv[1:]))
runpy.run_path(sys.argv[0], run_name="__main__")
"""
    # Exercise both directions: ignoring either source must fail an assertion.
    for paseo_left, expected in ((5, "claude: critical (5% left)"),
                                 (90, "claude: ok (80% left)")):
        paseo.write_text(json.dumps([{"sourceId": "claude", "pool_family": "default",
            "id": "claude:default", "fetchedAt": now,
            "report": {"status": "available", "windows": [{"id": "weekly", "label": "Weekly",
                       "usedPct": 100 - paseo_left, "remainingPct": paseo_left}]}}]))
        for entry in ([str(ROOT / "bin/quota_nudge.py")],
                      [str(ROOT / "bin/route_agent.py"), "show"]):
            command = [sys.executable, "-c", runner, str(ROOT / "bin"), *entry]
            run = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)
            assert run.returncode == 0, run.stderr
            assert expected in run.stdout, (run.stdout, run.stderr)


def test_malformed_pool_values_are_unknown(monkeypatch, capsys):
    monkeypatch.setattr(nudge, "load_profiles", lambda: {})
    quota = {"null": None, "list": [], "number": 42, "string": "bad"}
    rows = nudge.report(quota)
    assert {row["pool"] for row in rows} == set(quota)
    assert all(row["level"] == "unknown" and row["remaining_percent"] is None for row in rows)
    nudge.print_reminder(quota)
    output = capsys.readouterr().out
    for pool in quota:
        assert f"{pool}: unknown" in output


def test_clear_rejects_profile_options_without_writing(tmp_path, monkeypatch, capsys):
    import pytest
    path = tmp_path / "profiles.json"
    original = '{"openai":{"name":"keep","until":"2099-01-01T00:00:00Z"}}'
    path.write_text(original)
    monkeypatch.setenv("ADE_SPENDING_PROFILES", str(path))
    for option in (["--name", "discard"], ["--until", "2099-01-01T00:00:00Z"],
                   ["--name", ""], ["--until", ""]):
        with pytest.raises(SystemExit) as exc:
            nudge.main(["--clear-profile", "openai", *option])
        assert exc.value.code == 2
        assert "require --set-profile" in capsys.readouterr().err
        assert path.read_text() == original
