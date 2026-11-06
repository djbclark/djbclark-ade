"""bin/quota-surplus: the use-it-or-lose-it algorithm, episode dedup, cooldown, scope and the relay argv. Nothing is sent."""
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
    monkeypatch.delenv("QUOTA_SURPLUS_LEADS", raising=False)


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
        ("antigravity", "gemini"): P("antigravity", "subscription", kinds=("bulk",)),
        ("omp", "claude"): P("omp", "credits", kinds=("api-only",)),
        ("opencode-go", None): P("opencode-go", "subscription", kinds=("bulk",), allow_repos=("techno-euphora",),
                                 allow_seats=("hermes",)),
        # a repo-scoped pool the ruling lets run out (cursor), to exercise the scope path
        ("cursor", None): P("cursor", "subscription", kinds=("code",), allow_repos=("techno-euphora",),
                            allow_seats=("hermes",)),
        ("zai", None): P("zai", "subscription", kinds=("code",)),
        ("codex", None): P("codex", "subscription", kinds=("frontier",)),
    }, never={"hermes"})


def only(verdicts, pool):
    hits = [v for v in verdicts if v["pool"] == pool]
    assert len(hits) == 1, verdicts
    return hits[0]


def argon_data(remaining=25, hours=2.08, pace=0.757, now=NOW):
    return {"available": [row(windows=[window(remaining, hours, pace=pace, now=now)])]}


def alerts_of(qs, data, now=NOW, state=None):
    state = {"episodes": {}} if state is None else state
    verdicts = qs.assess(data, policy(qs), now, state=state)
    qs.record(state, verdicts, now)
    return [v for v in verdicts if v["verdict"] == "alert"], state


def ok_ping(sent):
    return lambda text: sent.append(text) or True


# -- the algorithm --------------------------------------------------------------------------

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


def test_average_use_when_no_pace(qs):
    # 75 used over 168 - 2 h elapsed: ~0.45%/h, ~0.9% before the reset
    v = only(qs.assess(argon_data(pace=None), policy(qs), NOW), "antigravity/gemini_argon")
    assert v["verdict"] == "alert" and 23 < v["surplus"] < 25


def test_five_hour_window_short_horizon_and_info_only(qs):
    def five(hours):
        return {"available": [row("zai", None, [window(60, hours, minutes=300, pace=0.2, label="z.ai 5-hour")])]}
    assert only(qs.assess(five(2.0), policy(qs), NOW), "zai")["verdict"] == "none"     # 2 h > 1.5 h
    v = only(qs.assess(five(1.0), policy(qs), NOW), "zai")
    # adversary r1 finding 1: a rolling 5-hour window refills all the time; it never pages
    assert v["verdict"] == "alert" and v["severity"] == "info" and v["score"] >= qs.ACT_SCORE


# -- no verdict -----------------------------------------------------------------------------

def test_stale_reading_gives_no_verdict(qs):
    data = {"available": [row(windows=[window(25, 2.08, pace=0.757)], fresh=False, stale_reason="agy probe failed")]}
    v = only(qs.assess(data, policy(qs), NOW), "antigravity/gemini_argon")
    assert v["verdict"] == "no-verdict" and v["stale_reason"] == "agy probe failed"
    assert "agy probe failed" in v["reason"]


def test_missing_reading_gives_no_verdict(qs):
    data = {"available": [row(windows=[{"label": "Gemini 4 Argon weekly", "remaining_percent": 25}])]}
    assert only(qs.assess(data, policy(qs), NOW), "antigravity/gemini_argon")["verdict"] == "no-verdict"


def test_frontier_pool_absent_from_aiuse_is_no_verdict(qs):
    # aiuse --available drops an exhausted pool (2026-11-03: Argon after an agent-reported quota refusal)
    data = {"available": [row("zai", None, [window(10, 50, pace=1.0, label="weekly")])]}
    v = only(qs.assess(data, policy(qs), NOW), "antigravity/gemini_argon")
    assert v["verdict"] == "no-verdict" and "no reading" in v["reason"]


def test_exhausted_window_is_no_verdict_whatever_its_percentage(qs):
    data = argon_data()
    data["available"][0]["windows"][0]["state"] = "exhausted"     # agent-reported refusal, still reading 25%
    v = only(qs.assess(data, policy(qs), NOW), "antigravity/gemini_argon")
    assert v["verdict"] == "no-verdict" and "exhausted" in v["reason"]


def test_reset_already_passed_is_no_verdict(qs):
    v = only(qs.assess(argon_data(hours=-0.1), policy(qs), NOW), "antigravity/gemini_argon")
    assert v["verdict"] == "no-verdict" and "passed" in v["reason"]


def test_after_a_reset_waits_for_a_fresh_reading_with_the_new_resets_at(qs):
    # 2026-11-02: Argon still refused 5 min after aiuse dropped the window
    _, state = alerts_of(qs, argon_data())
    after = NOW + timedelta(hours=2.2)          # the 02:35 reset has passed
    new_reset = 168
    # a reading taken BEFORE the reset that already names the next resets_at proves nothing
    early = argon_data(remaining=90, hours=new_reset, pace=0.1, now=after)
    early["available"][0]["collected_at"] = (NOW + timedelta(hours=1)).isoformat()
    v = only(qs.assess(early, policy(qs), after, state=state), "antigravity/gemini_argon")
    assert v["verdict"] == "no-verdict" and "before the reset" in v["reason"]
    # local-review P2 on b2053c1: the held reading must not move the baseline, so the next run still holds it
    later = after + timedelta(minutes=15)
    qs.record(state, qs.assess(early, policy(qs), after, state=state), after)
    v = only(qs.assess(early, policy(qs), later, state=state), "antigravity/gemini_argon")
    assert v["verdict"] == "no-verdict" and "before the reset" in v["reason"]
    # a reading whose resets_at is still the old one (jitter included) proves nothing either
    same = argon_data(remaining=90, hours=2.08 - 2.2 + 0.05, pace=0.1, now=after)
    same["available"][0]["windows"][0]["resets_at"] = (NOW + timedelta(hours=2.08, seconds=120)).isoformat()
    same["available"][0]["collected_at"] = after.isoformat()
    v = only(qs.assess(same, policy(qs), after, state=state), "antigravity/gemini_argon")
    assert v["verdict"] == "no-verdict"
    # collected after the reset with the new resets_at: judged normally (a week away: no alert, but a verdict)
    fresh = argon_data(remaining=90, hours=new_reset, pace=0.1, now=after)
    fresh["available"][0]["collected_at"] = after.isoformat()
    v = only(qs.assess(fresh, policy(qs), after, state=state), "antigravity/gemini_argon")
    assert v["verdict"] == "none" and "horizon" in v["reason"]


# -- never alerted --------------------------------------------------------------------------

def test_ruling_never_claude_opencode_go_cline_nor_unnamed_pools(qs):
    # djbclark 2026-11-03: running out is fine on agy, omp, codex, zcode, cursor, grok; never Claude, opencode-go, cline
    w = window(90, 1.0, pace=0.1, label="weekly")
    data = {"available": [row(p, f, [w]) for p, f in (("claude", "default"), ("claude", "fable"), ("opencode-go", None),
                                                      ("cline", None), ("clinepass", None), ("someone", None))]}
    verdicts = qs.assess(data, policy(qs), NOW)
    assert verdicts and {v["verdict"] for v in verdicts if v["pool"] != "antigravity/gemini_argon"} == {"skip"}
    assert "never fine on claude" in only(verdicts, "claude/default")["reason"]
    assert "not on djbclark" in only(verdicts, "someone")["reason"]


def test_real_routing_never_alerts_cline_or_clinepass(qs):
    w = window(90, 1.0, pace=0.1, label="weekly")
    data = {"available": [row("cline", None, [w]), row("clinepass", None, [w])]}
    verdicts = qs.assess(data, qs.policy_from_routing({}), NOW)
    assert {v["verdict"] for v in verdicts if v["pool"] in ("cline", "clinepass")} == {"skip"}


def test_omp_grant_may_run_out_other_credits_roll_over(qs):
    credits = window(90, 1.0, minutes=32400, pace=0.1, label="credits")
    data = {"available": [row("omp", "claude", [credits]), row("cursor", None, [credits])]}
    verdicts = qs.assess(data, policy(qs), NOW)
    assert only(verdicts, "omp/claude")["verdict"] == "alert"
    assert only(verdicts, "cursor")["verdict"] == "skip" and "roll over" in only(verdicts, "cursor")["reason"]


def test_disabled_and_never_route_skipped(qs):
    w = window(90, 1.0, pace=0.1, label="weekly")
    data = {"available": [row("zai", None, [w]), row("hermes", None, [w])], "disabled_services": {"zai": "off"}}
    verdicts = qs.assess(data, policy(qs), NOW)
    assert {v["verdict"] for v in verdicts if v["pool"] in ("zai", "hermes")} == {"skip"}


# -- notify: episodes, cooldown, failures ---------------------------------------------------

def test_dedup_same_resets_at(qs):
    first, state = alerts_of(qs, argon_data())
    sent = []
    acts = qs.notify(first, state, NOW, dry_run=False, rows=[], items=[], ping=ok_ping(sent), relay=sent.append)
    assert len(sent) == 1 and acts[0]["action"] == "ping"
    # 15 min later, resets_at jittered by a second: same episode, nothing sent again
    later = NOW + timedelta(minutes=15)
    second, _ = alerts_of(qs, argon_data(hours=2.08 - 0.25 + 1 / 3600, now=later), later, state)
    assert second[0]["episode"] == first[0]["episode"]
    assert qs.notify(second, state, later, dry_run=False, rows=[], items=[], ping=ok_ping(sent),
                     relay=sent.append) == []
    assert len(sent) == 1


def test_new_episode_after_reset(qs):
    first, state = alerts_of(qs, argon_data())
    qs.notify(first, state, NOW, dry_run=False, rows=[], items=[], ping=lambda t: True, relay=lambda a: True)
    week = NOW + timedelta(days=7)
    again, _ = alerts_of(qs, argon_data(now=week), week, state)
    assert again == []          # no collected_at: nothing proves the reading came after the old reset
    data = argon_data(now=week)
    data["available"][0]["collected_at"] = week.isoformat()
    again, _ = alerts_of(qs, data, week, state)
    assert again and again[0]["episode"] != first[0]["episode"]
    sent = []
    qs.notify(again, state, week, dry_run=False, rows=[], items=[], ping=ok_ping(sent), relay=sent.append)
    assert len(sent) == 1
    assert first[0]["episode"] not in state["episodes"]      # pruned a day after its reset


def test_cooldown_bounds_pages_per_pool_across_episodes(qs):
    # adversary r1 finding 1: two act episodes of one pool within renotify_h page once
    first, state = alerts_of(qs, argon_data())
    sent = []
    qs.notify(first, state, NOW, dry_run=False, rows=[], items=[], ping=ok_ping(sent), relay=sent.append)
    soon = NOW + timedelta(hours=5)
    data = argon_data(hours=4, now=soon)
    data["available"][0]["collected_at"] = soon.isoformat()
    second, _ = alerts_of(qs, data, soon, state)
    assert second and second[0]["episode"] != first[0]["episode"] and second[0]["severity"] == "act"
    acts = qs.notify(second, state, soon, dry_run=False, rows=[], items=[], ping=ok_ping(sent), relay=sent.append)
    assert [a["action"] for a in acts] == ["cooldown"] and len(sent) == 1
    late = NOW + timedelta(hours=25)
    acts = qs.notify(second, state, late, dry_run=False, rows=[], items=[], ping=ok_ping(sent), relay=sent.append)
    assert [a["action"] for a in acts] == ["ping"] and len(sent) == 2


def test_idle_five_hour_windows_never_page(qs):
    sent, state = [], {"episodes": {}}
    for k in range(3):
        at = NOW + timedelta(hours=5 * k)
        data = {"available": [row("antigravity", "gemini",
                                  [window(100, 1.0, minutes=300, label="Gemini 5-hour", now=at)],
                                  collected_at=at.isoformat())]}
        alerts, _ = alerts_of(qs, data, at, state)
        assert alerts and alerts[0]["severity"] == "info"
        assert qs.notify(alerts, state, at, dry_run=False, rows=[], items=[], ping=ok_ping(sent),
                         relay=sent.append) == []
    assert sent == []


def test_failed_ping_and_no_relay_leaves_episode_unnotified(qs):
    alerts, state = alerts_of(qs, argon_data())
    acts = qs.notify(alerts, state, NOW, dry_run=False, rows=[], items=[], ping=lambda t: False,
                     relay=lambda a, out: True)
    ep = state["episodes"][alerts[0]["episode"]]
    assert "failed" in [a["action"] for a in acts]
    assert not ep.get("notified_at") and ep.get("failed_at") and not state.get("pools")
    sent = []                                          # next run retries
    qs.notify(alerts, state, NOW + timedelta(minutes=15), dry_run=False, rows=[], items=[], ping=ok_ping(sent),
              relay=lambda a, out: True)
    assert len(sent) == 1 and state["episodes"][alerts[0]["episode"]].get("notified_at")


def test_relay_delivery_tracked_per_lead_and_retried(qs, tmp_path):
    # local-review P2s on b2053c1 and 3fec121: a launched relay is not a delivery; each lead is tracked on its own and a
    # failed relay is retried even after the operator ping succeeded
    alerts, state = alerts_of(qs, argon_data())
    ep = state["episodes"][alerts[0]["episode"]]
    started = []

    def relay(argv, out):
        started.append((argv[2], out))
        return True

    def run(minutes, ping):
        return qs.notify(alerts, state, NOW + timedelta(minutes=minutes), dry_run=False, rows=LEADS[:2], items=[],
                         ping=ping, relay=relay)

    run(0, lambda t: False)
    assert not ep.get("notified_at") and len(started) == 2                   # both leads started, nothing delivered
    sent = []
    run(15, ok_ping(sent))                                                   # relays still running: not restarted
    assert len(sent) == 1 and ep.get("notified_at") and len(started) == 2
    outs = dict(started)
    Path(outs["aaaa1111"]).write_text(json.dumps({"rc": 0}))
    Path(outs["bbbb2222"]).write_text(json.dumps({"rc": 1}))
    run(30, ok_ping(sent))                       # the refused lead is retried, the delivered one is not; no new page
    assert [t for t, _ in started[2:]] == ["bbbb2222"] and len(sent) == 1
    assert ep["relays"]["aaaa1111"].get("delivered_at") and ep["relays"]["bbbb2222"]["attempts"] == 2
    for k in range(3, 6):                        # capped at MAX_RELAY_ATTEMPTS
        Path(started[-1][1]).write_text(json.dumps({"rc": 1}))
        run(15 * k + 30, ok_ping(sent))
    assert ep["relays"]["bbbb2222"]["attempts"] == qs.MAX_RELAY_ATTEMPTS


def test_relay_runner_records_relay_exit_status(qs, tmp_path):
    out = tmp_path / "o.json"
    assert qs.main(["_relay-run", str(out), "--", sys.executable, "-c", "import sys; sys.exit(4)"]) == 0
    assert qs.relay_outcome(str(out)) == 4
    assert qs.relay_outcome(str(tmp_path / "missing.json")) is None


def test_dry_run_sends_and_marks_nothing(qs):
    alerts, state = alerts_of(qs, argon_data())
    sent = []
    acts = qs.notify(alerts, state, NOW, dry_run=True, rows=[], items=[], ping=ok_ping(sent), relay=sent.append)
    assert acts and sent == []
    assert not state["episodes"][alerts[0]["episode"]].get("notified_at") and not state.get("pools")


# -- leads, scope, relay text ---------------------------------------------------------------

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


def test_lead_match_is_strict(qs):
    rows = [{"id": str(i), "name": n, "status": "idle"} for i, n in enumerate(
        ["LEAD x", "LEAD", "Lead review", "lead-gen", "LEADER y", "/helm lead", "  LEAD padded", "watch lead 3"])]
    assert [r["name"] for r in qs.lead_seats(rows, [])] == ["LEAD x", "LEAD"]
    assert [r["name"] for r in qs.lead_seats(rows, ["5"])] == ["LEAD x", "LEAD", "/helm lead"]


def test_scoped_pool_not_offered_to_other_repos(qs):
    data = {"available": [row("cursor", None, [window(80, 3.0, minutes=43200, pace=0.1, label="monthly")])]}
    alerts, state = alerts_of(qs, data)
    assert alerts and alerts[0]["severity"] == "act"
    items = [{"repo": "djbclark-ade", "n": 1, "fit": ["bulk"], "read_only": True},
             {"repo": "techno-euphora", "n": 1, "fit": ["bulk"], "read_only": True}]
    assert [i["repo"] for i in qs.work_for(alerts[0], items)] == ["techno-euphora"]
    acts = qs.notify(alerts, state, NOW, dry_run=True, rows=LEADS, items=items)
    assert [a["target"] for a in acts if a["action"] == "relay"] == ["cccc3333"]
    assert qs.in_scope(alerts[0], None, "hermes") and not qs.in_scope(alerts[0], "tendcf", None)


def test_list_work_pool_respects_scope(qs, tmp_path, capsys):
    for name in ("techno-euphora", "other"):
        d = tmp_path / "src" / name / "docs"
        d.mkdir(parents=True)
        (d / "surplus-work.md").write_text(
            "1. Bulk thing | kind: research | size: S | fit: bulk | read-only: yes | value: high\n"
            "2. Frontier thing | kind: review | size: M | fit: frontier | read-only: yes | value: high\n")
    repos = ["--repo", str(tmp_path / "src" / "techno-euphora"), "--repo", str(tmp_path / "src" / "other")]
    assert qs.main(["list-work", *repos, "--pool", "opencode-go", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert [(i["repo"], i["n"]) for i in got] == [("techno-euphora", 1)]
    assert qs.main(["list-work", *repos, "--pool", "antigravity-argon", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert sorted((i["repo"], i["n"]) for i in got) == [("other", 2), ("techno-euphora", 2)]
    assert qs.main(["list-work", *repos, "--pool", "no-such-pool"]) == 2


def test_relay_argv_idle_only_for_claude_paseo(qs):
    claude, omp = LEADS[0], LEADS[1]
    a = qs.relay_argv("/r/relay.py", claude, "hi")
    b = qs.relay_argv("/r/relay.py", omp, "hi")
    assert a[1:] == ["/r/relay.py", "aaaa1111", "hi", "--fyi", "--idle", "1800"]
    assert b[1:] == ["/r/relay.py", "bbbb2222", "hi", "--fyi"]
    assert "--steer" not in a + b


def test_notify_reaches_live_leads_only(qs):
    alerts, state = alerts_of(qs, argon_data())
    acts = qs.notify(alerts, state, NOW, dry_run=True, rows=LEADS, items=[])
    assert [a["target"] for a in acts if a["action"] == "relay"] == ["aaaa1111", "bbbb2222", "cccc3333"]
    ping = [a for a in acts if a["action"] == "ping"][0]["text"]
    assert ping.startswith("quota surplus: antigravity/gemini_argon 25% left, resets ")
    assert "use it for frontier" in ping


def test_advises_bounded_concurrent_slices(qs):
    # lead 7c58015b, 2026-11-03: four parallel agy runs spent a 25% Argon surplus in ~10 min while aiuse still read 25%
    argon = only(qs.assess(argon_data(), policy(qs), NOW), "antigravity/gemini_argon")
    text = qs.relay_text(argon, NOW, 3)
    assert "Run at most 1 concurrent slice and re-check" in text and "Usage Limit Reached" in text
    assert "list-work --pool antigravity-argon" in text
    assert qs.slice_advice(dict(argon, max_parallel=4)) == (2, None)          # no per-slice cost: 1-2 at a time
    assert qs.slice_advice(dict(argon, max_parallel=4, slice_cost=10.0)) == (2, 2)   # ~24% buys two 10% slices
    text = qs.relay_text(dict(argon, max_parallel=4, slice_cost=10.0), NOW, 3)
    assert "at most 2 concurrent slices (it buys about 2 at ~10% each)" in text


def test_surplus_that_buys_no_slice_advises_zero_and_does_not_page(qs):
    # adversary r1 finding 4: never "at most 1 slice" when the surplus buys none
    argon = only(qs.assess(argon_data(), policy(qs), NOW), "antigravity/gemini_argon")
    assert qs.slice_advice(dict(argon, max_parallel=4, slice_cost=40.0)) == (0, 0)
    text = qs.relay_text(dict(argon, max_parallel=4, slice_cost=40.0), NOW, 3)
    assert "buys no whole slice" in text and "do not dispatch" in text and "at most" not in text
    pol = policy(qs)
    pol.pools[("antigravity", "gemini_argon")].slice_cost = 40.0
    v = only(qs.assess(argon_data(), pol, NOW), "antigravity/gemini_argon")
    assert v["verdict"] == "alert" and v["severity"] == "info"


# -- routing, lists, CLI, state -------------------------------------------------------------

def test_routing_policy_marks_argon_frontier_and_scopes_opencode_go(qs):
    pol = qs.policy_from_routing({})
    argon = pol.for_row("antigravity", "gemini_argon")
    assert argon.frontier and argon.blocked is None
    assert argon.dispatch == "acp-run agy --model gemini-4-argon --effort high"
    assert pol.for_row("hermes", None).blocked
    assert pol.for_row("opencode-go", None).allow_repos == ("techno-euphora",)


def test_state_lock_serializes_check_and_notify(qs, tmp_path, monkeypatch, capsys):
    # local-review P2 on 28bd211: an overlapping run must not replace the state another run is updating
    import fcntl
    monkeypatch.setenv("QUOTA_SURPLUS_NOW", NOW.isoformat())
    monkeypatch.setenv("QUOTA_SURPLUS_LOCK_TIMEOUT", "0.3")
    f = tmp_path / "aiuse.json"
    f.write_text(json.dumps(argon_data()))
    lock = tmp_path / "state" / "state.json.lock"
    lock.parent.mkdir(parents=True)
    with lock.open("a") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)
        assert qs.main(["check", "--input", str(f)]) == 75
        assert qs.main(["notify", "--input", str(f)]) == 75
        assert not (tmp_path / "state" / "state.json").exists()
        assert qs.main(["check", "--dry-run", "--input", str(f)]) == 0      # a dry run takes no lock
    assert qs.main(["check", "--input", str(f)]) == 0
    assert (tmp_path / "state" / "state.json").exists()


def test_dispatch_line_survives_the_shell(qs):
    # local-review P2 on 911bf68: zai's model id holds a backslash the shell would eat unquoted
    import shlex
    pol = qs.policy_from_routing({})
    zai = pol.for_row("zai", None)
    argv = shlex.split(zai.dispatch)
    assert argv[:3] == ["acp-run", "zcode", "--model"] and "\\GLM-" in argv[3]
    for pp in pol.pools.values():
        if pp.dispatch:
            assert shlex.split(pp.dispatch)[0] == "acp-run"


def test_work_list_of_this_repo_parses(qs):
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
    saved = json.loads((tmp_path / "state" / "state.json").read_text())
    assert saved["episodes"] and saved["windows"]


def test_corrupt_state_kept_aside_and_replaced(qs, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("QUOTA_SURPLUS_NOW", NOW.isoformat())
    st = tmp_path / "state" / "state.json"
    st.parent.mkdir(parents=True)
    st.write_text("{not json")
    f = tmp_path / "aiuse.json"
    f.write_text(json.dumps(argon_data()))
    assert qs.main(["check", "--dry-run", "--input", str(f)]) == 0
    assert st.read_text() == "{not json"                          # a dry run touches nothing
    assert qs.main(["check", "--input", str(f)]) == 0
    assert (tmp_path / "state" / "state.json.corrupt").read_text() == "{not json"
    assert json.loads(st.read_text())["episodes"]
    assert "corrupt state" in capsys.readouterr().err


def test_cli_unreadable_aiuse_is_no_verdict(qs, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    assert qs.main(["check", "--input", str(bad)]) == 3
    assert not (tmp_path / "state" / "state.json").exists()
