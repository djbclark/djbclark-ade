"""bin/quota-surplus: the use-it-or-lose-it algorithm, episode dedup, scope and the relay argv. Nothing is sent."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 11, 2, 0, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def qs():
    loader = importlib.machinery.SourceFileLoader("quota_surplus_t", str(REPO / "bin/quota-surplus"))
    spec = importlib.util.spec_from_loader("quota_surplus_t", loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["quota_surplus_t"] = mod
    loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("QUOTA_SURPLUS_STATE", str(tmp_path / "state" / "state.json"))
    monkeypatch.setenv("QUOTA_SURPLUS_PING", str(tmp_path / "no-such-ping"))
    monkeypatch.setenv("QUOTA_SURPLUS_SRC", str(tmp_path / "src"))
    monkeypatch.setenv("AIUSE_CONFIG", str(tmp_path / "no-aiuse.toml"))


def window(remaining, hours_to_reset, *, minutes=10080, pace=None, label="Gemini 4 Argon weekly", now=NOW):
    return {"label": label, "remaining_percent": remaining, "used_percent": 100 - remaining,
            "resets_at": (now + timedelta(hours=hours_to_reset)).isoformat(), "window_minutes": minutes,
            "pace_ratio": pace, "state": "ok"}


def row(provider="antigravity", family="gemini_argon", windows=(), *, fresh=True, **kw):
    return {"provider": provider, "pool_family": family, "usable_now": True, "fresh": fresh, "stale": not fresh,
            "age_seconds": 60 if fresh else 2165.6, "binding_window": windows[0]["label"] if windows else None,
            "windows": list(windows), **kw}


def policy(qs):
    P = qs.PoolPolicy
    return qs.Policy(pools={
        ("antigravity", "gemini_argon"): P("antigravity-argon", "subscription", frontier=True, kinds=("frontier",),
                                           dispatch="acp-run agy --model gemini-4-argon --effort high"),
        ("omp", None): P("omp", "credits", blocked="credits: prepaid credits roll over"),
        ("opencode-go", None): P("opencode-go", "subscription", kinds=("bulk",), allow_repos=("techno-euphora",),
                                 allow_seats=("hermes",)),
        ("zai", None): P("zai", "subscription", kinds=("code",)),
    }, never={"hermes"})


def only(verdicts, pool):
    hits = [v for v in verdicts if v["pool"] == pool]
    assert len(hits) == 1, verdicts
    return hits[0]


def argon_data(remaining=25, hours=2.08, pace=0.757, now=NOW):
    return {"available": [row(windows=[window(remaining, hours, pace=pace, now=now)])]}


def test_argon_case_alerts_act(qs):
    v = only(qs.assess(argon_data(), policy(qs), NOW), "antigravity/gemini_argon")
    assert v["verdict"] == "alert" and v["severity"] == "act"
    # 0.757 * 100 * 125 min / 10080 min ~ 0.9% burn before reset: ~24% is thrown away
    assert 23 < v["surplus"] < 25
    assert v["dispatch"] == "acp-run agy --model gemini-4-argon --effort high"


def test_fast_pace_spends_it_no_alert(qs):
    # at 60x even pace the last 2 h burn ~75%: capped at the 25% left, nothing is lost
    v = only(qs.assess(argon_data(pace=60.0), policy(qs), NOW), "antigravity/gemini_argon")
    assert v["verdict"] == "none" and v["surplus"] == 0


def test_reset_three_days_away_no_alert(qs):
    v = only(qs.assess(argon_data(hours=72), policy(qs), NOW), "antigravity/gemini_argon")
    assert v["verdict"] == "none" and "horizon" in v["reason"]


def test_five_hour_window_uses_short_horizon(qs):
    data = {"available": [row("zai", None, [window(60, 2.0, minutes=300, pace=0.2, label="z.ai 5-hour")])]}
    assert only(qs.assess(data, policy(qs), NOW), "zai")["verdict"] == "none"     # 2 h > 1.5 h
    data = {"available": [row("zai", None, [window(60, 1.0, minutes=300, pace=0.2, label="z.ai 5-hour")])]}
    assert only(qs.assess(data, policy(qs), NOW), "zai")["verdict"] == "alert"


def test_average_use_when_no_pace(qs):
    # 75 used over 168 - 2 h elapsed: ~0.45%/h, ~0.9% before the reset
    v = only(qs.assess(argon_data(pace=None), policy(qs), NOW), "antigravity/gemini_argon")
    assert v["verdict"] == "alert" and 23 < v["surplus"] < 25


def test_stale_reading_gives_no_verdict(qs):
    data = {"available": [row(windows=[window(25, 2.08, pace=0.757)], fresh=False, stale_reason="agy probe failed")]}
    v = only(qs.assess(data, policy(qs), NOW), "antigravity/gemini_argon")
    assert v["verdict"] == "no-verdict" and v["stale_reason"] == "agy probe failed"
    assert "agy probe failed" in v["reason"]


def test_missing_reading_gives_no_verdict(qs):
    data = {"available": [row(windows=[{"label": "Gemini 4 Argon weekly", "remaining_percent": 25}])]}
    assert only(qs.assess(data, policy(qs), NOW), "antigravity/gemini_argon")["verdict"] == "no-verdict"


def test_credits_never_alerted(qs):
    credits = window(90, 1.0, minutes=32400, pace=0.1, label="credits")
    data = {"available": [row("omp", "claude", [credits]), row("someone", None, [credits])]}
    verdicts = qs.assess(data, policy(qs), NOW)
    assert {v["verdict"] for v in verdicts if v["pool"] in ("omp/claude", "someone")} == {"skip"}
    assert not [v for v in verdicts if v["verdict"] == "alert"]


def test_disabled_and_never_route_skipped(qs):
    w = window(90, 1.0, pace=0.1, label="weekly")
    data = {"available": [row("zai", None, [w]), row("hermes", None, [w])], "disabled_services": {"zai": "off"}}
    verdicts = qs.assess(data, policy(qs), NOW)
    assert {v["verdict"] for v in verdicts if v["pool"] in ("zai", "hermes")} == {"skip"}


def test_frontier_pool_absent_from_aiuse_is_no_verdict(qs):
    # aiuse --available drops an exhausted pool (2026-11-03: Argon after an agent-reported quota refusal)
    data = {"available": [row("zai", None, [window(10, 50, pace=1.0, label="weekly")])]}
    v = only(qs.assess(data, policy(qs), NOW), "antigravity/gemini_argon")
    assert v["verdict"] == "no-verdict" and "no reading" in v["reason"]


def test_dedup_same_resets_at(qs):
    state = {"episodes": {}}
    first = [v for v in qs.assess(argon_data(), policy(qs), NOW) if v["verdict"] == "alert"]
    qs.record(state, first, NOW)
    sent = []
    acts = qs.notify(first, state, NOW, dry_run=False, rows=[], items=[], ping=sent.append, relay=sent.append)
    assert len(sent) == 1 and acts[0]["action"] == "ping"
    # 15 min later, resets_at jittered by a second: same episode, nothing sent again
    later = NOW + timedelta(minutes=15)
    second = [v for v in qs.assess(argon_data(hours=2.08 - 0.25 + 1 / 3600, now=later), policy(qs), later)
              if v["verdict"] == "alert"]
    qs.record(state, second, later)
    assert second[0]["episode"] == first[0]["episode"]
    assert qs.notify(second, state, later, dry_run=False, rows=[], items=[], ping=sent.append,
                     relay=sent.append) == []
    assert len(sent) == 1


def test_new_episode_after_reset(qs):
    state = {"episodes": {}}
    first = [v for v in qs.assess(argon_data(), policy(qs), NOW) if v["verdict"] == "alert"]
    qs.record(state, first, NOW)
    qs.notify(first, state, NOW, dry_run=False, rows=[], items=[], ping=lambda t: None, relay=lambda a: None)
    week = NOW + timedelta(days=7)
    again = [v for v in qs.assess(argon_data(now=week), policy(qs), week) if v["verdict"] == "alert"]
    qs.record(state, again, week)
    assert again[0]["episode"] != first[0]["episode"]
    sent = []
    qs.notify(again, state, week, dry_run=False, rows=[], items=[], ping=sent.append, relay=sent.append)
    assert len(sent) == 1
    assert first[0]["episode"] not in state["episodes"]      # pruned a day after its reset


def test_dry_run_sends_and_marks_nothing(qs):
    state = {"episodes": {}}
    alerts = [v for v in qs.assess(argon_data(), policy(qs), NOW) if v["verdict"] == "alert"]
    qs.record(state, alerts, NOW)
    sent = []
    acts = qs.notify(alerts, state, NOW, dry_run=True, rows=[], items=[], ping=sent.append, relay=sent.append)
    assert acts and sent == []
    assert not state["episodes"][alerts[0]["episode"]].get("notified_at")


LEADS = [
    {"id": "aaaa1111", "name": "LEAD paseo-only rearch", "host": "paseo", "agent": "claude", "status": "idle",
     "cwd": "/nonexistent/djbclark-ade"},
    {"id": "bbbb2222", "name": "LEAD tendcf", "host": "paseo", "agent": "omp", "status": "working",
     "cwd": "/nonexistent/tendcf"},
    {"id": "cccc3333", "name": "Dann lead", "host": "paseo", "agent": "opencode", "status": "idle",
     "cwd": "/nonexistent/techno-euphora", "title": "LEAD techno-euphora"},
    {"id": "dddd4444", "name": "not a lead", "host": "paseo", "agent": "omp", "status": "idle", "cwd": "/x"},
    {"id": "eeee5555", "name": "LEAD old", "host": "paseo", "agent": "omp", "status": "closed", "cwd": "/x"},
]


def test_scoped_pool_not_offered_to_other_repos(qs):
    data = {"available": [row("opencode-go", None, [window(80, 3.0, minutes=43200, pace=0.1, label="monthly")])]}
    state = {"episodes": {}}
    alerts = [v for v in qs.assess(data, policy(qs), NOW) if v["verdict"] == "alert"]
    assert alerts and alerts[0]["severity"] == "act"
    qs.record(state, alerts, NOW)
    items = [{"repo": "djbclark-ade", "n": 1, "fit": ["bulk"], "read_only": True},
             {"repo": "techno-euphora", "n": 1, "fit": ["bulk"], "read_only": True}]
    assert [i["repo"] for i in qs.work_for(alerts[0], items)] == ["techno-euphora"]
    acts = qs.notify(alerts, state, NOW, dry_run=True, rows=LEADS, items=items)
    assert [a["target"] for a in acts if a["action"] == "relay"] == ["cccc3333"]
    assert qs.in_scope(alerts[0], None, "hermes") and not qs.in_scope(alerts[0], "tendcf", None)


def test_relay_argv_idle_only_for_claude_paseo(qs):
    claude, omp = LEADS[0], LEADS[1]
    a = qs.relay_argv("/r/relay.py", claude, "hi")
    b = qs.relay_argv("/r/relay.py", omp, "hi")
    assert a[1:] == ["/r/relay.py", "aaaa1111", "hi", "--fyi", "--idle", "1800"]
    assert b[1:] == ["/r/relay.py", "bbbb2222", "hi", "--fyi"]
    assert "--steer" not in a + b


def test_notify_reaches_live_leads_only(qs):
    state = {"episodes": {}}
    alerts = [v for v in qs.assess(argon_data(), policy(qs), NOW) if v["verdict"] == "alert"]
    qs.record(state, alerts, NOW)
    acts = qs.notify(alerts, state, NOW, dry_run=True, rows=LEADS, items=[])
    assert [a["target"] for a in acts if a["action"] == "relay"] == ["aaaa1111", "bbbb2222", "cccc3333"]
    ping = [a for a in acts if a["action"] == "ping"][0]["text"]
    assert ping.startswith("quota surplus: antigravity/gemini_argon 25% left, resets ")
    assert "use it for frontier" in ping


def test_routing_policy_marks_argon_frontier_and_skips_credits(qs):
    pol = qs.policy_from_routing({})
    argon = pol.for_row("antigravity", "gemini_argon")
    assert argon.frontier and argon.blocked is None
    assert argon.dispatch == "acp-run agy --model gemini-4-argon --effort high"
    assert pol.for_row("omp", "claude").blocked
    assert pol.for_row("hermes", None).blocked
    assert pol.for_row("opencode-go", None).allow_repos == ("techno-euphora",)


def test_work_list_of_this_repo_parses(qs, monkeypatch):
    items = qs.find_work([REPO])
    assert len(items) >= 5
    for i in items:
        assert i["task"] and i.get("kind") and i.get("size") in ("S", "M", "L") and i.get("value") in (
            "high", "medium", "low")
        assert set(i["fit"]) <= {"frontier", "bulk", "any"}
    values = [qs.VALUE_RANK[i["value"]] for i in items]
    assert values == sorted(values, reverse=True)


def test_cli_check_dry_run_writes_no_state(qs, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("QUOTA_SURPLUS_NOW", NOW.isoformat())
    f = tmp_path / "aiuse.json"
    f.write_text(json.dumps(argon_data()))
    assert qs.main(["check", "--dry-run", "--input", str(f)]) == 0
    assert capsys.readouterr().out.startswith("ACT  antigravity/gemini_argon")
    assert not (tmp_path / "state" / "state.json").exists()
    assert qs.main(["check", "--input", str(f)]) == 0
    assert json.loads((tmp_path / "state" / "state.json").read_text())["episodes"]


def test_cli_unreadable_aiuse_is_no_verdict(qs, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    assert qs.main(["check", "--input", str(bad)]) == 3
    assert not (tmp_path / "state" / "state.json").exists()
