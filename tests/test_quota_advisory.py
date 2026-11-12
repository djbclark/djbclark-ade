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
