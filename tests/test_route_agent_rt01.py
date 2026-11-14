"""route_agent.py rt-01 (2026-11-14): `--available` rows of two accounts fold fail-closed (D1), an error row is an unmeasured
account (D2), and a repository's declared frontier reviewer order (`frontier_order`) decides `plan --kinds frontier --repo R`.

D1/D2 are the Lows of the lw-02 adversary review of PR 698; the order is tendcf's standing rule 3 (Astra, Fable, Argon).
"""
from __future__ import annotations

import itertools
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import route_agent as r  # noqa: E402


def _row(left, *, expired=False, family="default"):
    w = {"label": "weekly", "pool_family": family, "remaining_percent": left, "headroom_percent": left, "state": "ok"}
    row = {"provider": "claude", "pool_family": family, "usable_now": True, "headroom_percent": left,
           "binding_window": "weekly", "age_seconds": 60, "windows": [w]}
    if expired:
        row["reading_expired"] = True
    return row


FRESH, EXPIRED = _row(50), _row(90, expired=True)
ERROR = {"provider": "claude", "error": "auth failed"}


@pytest.mark.parametrize("order", list(itertools.permutations([FRESH, EXPIRED])))
def test_a_fresh_row_does_not_open_the_plenty_gate_beside_an_expired_row_of_the_same_pool(order):
    """D1: two `--available` rows of one pool key are two accounts; the expired one is unmeasured, so the measured one
    must not open the pool alone (before: remaining 50 and plenty 50 in both orders)."""
    pool = r._providers_from_available(list(order), 60)["claude"]
    assert pool["remaining"] == 50
    assert r.plenty_remaining(pool) is None


CAP = {**_row(35, family="fable"), "binding_window": "Claude Code weekly - Fable"}
BARE_EXPIRED = {"provider": "claude", "pool_family": "default", "usable_now": True, "headroom_percent": 90,
                "reading_expired": True, "age_seconds": 60}


@pytest.mark.parametrize("order", list(itertools.permutations([CAP, FRESH, EXPIRED])), ids=lambda o: "-".join(
    {id(CAP): "cap", id(FRESH): "fresh", id(EXPIRED): "expired"}[id(x)] for x in o) if isinstance(o, tuple) else None)
def test_a_cap_row_among_two_accounts_in_every_order_keeps_the_pool_closed(order):
    """The cap row is no account and adds no marker, but the expired account still closes the pool wherever the cap sits."""
    pool = r._providers_from_available(list(order), 60)["claude"]
    assert pool["remaining"] == 50 and pool["sublimits"] == {"fable": 35.0}
    assert r.plenty_remaining(pool) is None


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_an_expired_row_with_no_window_at_all_still_closes_the_pool_in_either_order(order):
    """No `binding_window` and no `windows[]`: nothing but the marker can carry the unknown (`remaining` alone cannot)."""
    pool = r._providers_from_available([[BARE_EXPIRED, FRESH][i] for i in order], 60)["claude"]
    assert pool["remaining"] == 50
    assert r.plenty_remaining(pool) is None


def test_two_measured_available_rows_still_open_the_plenty_gate_on_the_tighter_one():
    pool = r._providers_from_available([FRESH, _row(80)], 60)["claude"]
    assert pool["windows"] == {"weekly": 50.0}
    assert r.plenty_remaining(pool) == 50


def test_a_lone_expired_available_row_is_unchanged():
    pool = r._providers_from_available([EXPIRED], 60)["claude"]
    assert pool["remaining"] is None and r.plenty_remaining(pool) is None
    assert r.UNMEASURED_WINDOW not in pool["windows"]


def test_the_fable_cap_row_is_not_a_second_account():
    """The `fable` row of a claude account is a model cap inside the shared pool (cap-only entry): it must not mark the
    pool unmeasured, or every claude pool with a Fable row would close the gate."""
    cap = {**_row(35, family="fable"), "binding_window": "Claude Code weekly - Fable"}
    for rows in ([FRESH, cap], [cap, FRESH]):
        pool = r._providers_from_available(rows, 60)["claude"]
        assert pool["remaining"] == 50
        assert pool["sublimits"] == {"fable": 35.0}
        assert r.plenty_remaining(pool) == 50


def test_two_sources_of_one_pool_still_fold_to_the_known_reading():
    """`_merge_pool` without `accounts` (aiuse + Paseo reading one pool) keeps `_merge_caps`: known beats unknown."""
    into = {"claude": {"remaining": None, "windows": {"weekly": None}, "sublimits": {}}}
    r._merge_pool(into, "claude", {"remaining": 60.0, "windows": {"weekly": 60.0}, "sublimits": {}})
    assert into["claude"]["windows"] == {"weekly": 60.0} and r.plenty_remaining(into["claude"]) == 60


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_an_error_available_row_keeps_the_provider_pools_closed_for_the_plenty_gate(order):
    """D2: an aiuse collection/auth error says nothing about the account's quota and Paseo may still launch on it."""
    pool = r._providers_from_available([[FRESH, ERROR][i] for i in order], 60)["claude"]
    assert pool["remaining"] == 50
    assert r.plenty_remaining(pool) is None


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_an_error_snapshot_account_counts_as_an_unmeasured_account(order):
    known = {"provider": "claude", "age_seconds": 60, "windows": [{k: v for k, v in _row(50)["windows"][0].items()}]}
    pool = r._providers_from_accounts([[known, ERROR][i] for i in order], 60)["claude"]
    assert pool["remaining"] == 50
    assert r.plenty_remaining(pool) is None


def test_a_lone_error_account_builds_no_pool_and_an_error_elsewhere_does_not_touch_other_providers():
    assert "claude" not in r._providers_from_accounts([ERROR], 60)
    assert "claude" not in r._providers_from_available([ERROR], 60)
    codex = {"provider": "codex", "pool_family": None, "usable_now": True, "headroom_percent": 70, "age_seconds": 60,
             "binding_window": "Codex weekly"}
    pool = r._providers_from_available([codex, ERROR], 60)["codex"]
    assert r.UNMEASURED_WINDOW not in pool["windows"] and r.plenty_remaining(pool) == 70


def test_account_folds_close_a_window_one_account_cannot_measure_even_with_both_remainings_known():
    """`_merge_pool(accounts=True)` folds windows with `_merge_windows`: a window one account reads None stays None."""
    into = {"claude": {"remaining": 50.0, "windows": {"weekly": 50.0, "5h": None}, "sublimits": {}}}
    r._merge_pool(into, "claude", {"remaining": 60.0, "windows": {"weekly": 60.0, "5h": 70.0}, "sublimits": {}}, accounts=True)
    assert into["claude"]["windows"] == {"weekly": 50.0, "5h": None}
    assert r.plenty_remaining(into["claude"]) is None


def test_account_folds_mark_an_account_with_unknown_remaining_even_when_it_lists_no_window():
    into = {"claude": {"remaining": 50.0, "windows": {"weekly": 50.0}, "sublimits": {}}}
    r._merge_pool(into, "claude", {"remaining": None, "windows": {}, "sublimits": {}}, accounts=True)
    assert into["claude"]["windows"] == {"weekly": 50.0, r.UNMEASURED_WINDOW: None}
    assert r.plenty_remaining(into["claude"]) is None


# ---- a repository's declared frontier reviewer order -------------------------------------------------------------------

# codex paces ahead (penalty 3) so the plain score puts claude first: the tendcf lead's case.
OPEN = {"codex": {"remaining": 90.0, "pace_ratio": 2.0}, "claude": {"remaining": 90.0},
        "antigravity-argon": {"remaining": 90.0}}


def _first(quota, repo):
    choice = r.route("frontier", quota=quota, repo=repo)
    return None if choice is None else choice.service.name


def test_tendcf_orders_astra_before_fable_while_both_are_open_other_repos_keep_the_score():
    assert _first(OPEN, None) == "claude"
    assert _first(OPEN, "nix2cf") == "claude"
    assert _first(OPEN, "tendcf") == "codex"
    assert _first(OPEN, "TendCF") == "codex"            # repo names are lower-cased like the floor override


def test_the_plan_honours_the_order_and_still_fills_the_next_pool_in_order():
    plan = r.plan(["frontier", "frontier"], quota=OPEN, repo="tendcf")
    assert [c.service.name for _, c in plan] == ["codex", "claude"]


def test_a_listed_but_closed_pool_is_still_skipped():
    """The order only sorts pools that passed every gate: codex out of quota never leads, and Argon stays last."""
    closed = {**OPEN, "codex": {"remaining": 0.0}}
    assert _first(closed, "tendcf") == "claude"
    no_fable = {**OPEN, "claude": {"remaining": 90.0, "sublimits": {"fable": 4.0}}}
    assert _first({**no_fable, "codex": {"remaining": 0.0}}, "tendcf") == "antigravity-argon"
    assert _first({**no_fable, "codex": {"remaining": 0.0}, "antigravity-argon": {"remaining": 0.0}}, "tendcf") is None


def test_argon_never_outranks_a_usable_pool_it_sits_behind_even_when_the_order_lists_it_first():
    """Fable short: Argon (a fallback behind codex and claude) is a candidate beside open codex. Listed first, it still
    sorts behind codex."""
    quota = {**OPEN, "claude": {"remaining": 90.0, "sublimits": {"fable": 4.0}}}
    table = r.POLICY["dispatch"]["repo_overrides"]["tendcf"]
    saved = table["frontier_order"]
    table["frontier_order"] = ["antigravity-argon", "claude", "codex"]
    try:
        assert _first(quota, "tendcf") == "codex"
        assert _first({**quota, "codex": {"remaining": 0.0}}, "tendcf") == "antigravity-argon"
    finally:
        table["frontier_order"] = saved


@pytest.mark.parametrize("order, first", [(["codex"], "codex"), (["claude"], "claude"), (["claude", "codex"], "claude"),
                                           (["codex", "claude"], "codex")])
def test_listed_pools_lead_unlisted_ones_whatever_the_score(order, first):
    table = r.POLICY["dispatch"]["repo_overrides"]["tendcf"]
    saved = table["frontier_order"]
    table["frontier_order"] = order
    try:
        assert _first(OPEN, "tendcf") == first
    finally:
        table["frontier_order"] = saved


def test_a_malformed_order_read_without_the_loader_is_ignored_not_a_crash():
    table = r.POLICY["dispatch"]["repo_overrides"]["tendcf"]
    saved = table["frontier_order"]
    try:
        for bad in (5, "codex", {"a": 1}):
            table["frontier_order"] = bad
            assert r.repo_frontier_order("tendcf") == ()
            assert _first(OPEN, "tendcf") == "claude"
        table["frontier_order"] = ["codex", 3]
        assert r.repo_frontier_order("tendcf") == ("codex",)
    finally:
        table["frontier_order"] = saved


def test_the_order_is_for_frontier_only():
    code_quota = {"codex": {"remaining": 90.0}, "claude": {"remaining": 90.0}}
    assert r.route("code", quota=code_quota, repo="tendcf").service.name == r.route("code", quota=code_quota).service.name


def test_the_shipped_tendcf_order_is_astra_fable_argon():
    assert r.repo_frontier_order("tendcf") == ("codex", "claude", "antigravity-argon")
    assert r.repo_frontier_order("nix2cf") == () and r.repo_frontier_order(None) == ()


def _policy_with(tmp_path, order_line):
    text = (ROOT / "config" / "routing.toml").read_text()
    new = re.sub(r"^frontier_order = .*$", order_line, text, count=1, flags=re.MULTILINE)
    assert new != text or order_line in text
    path = tmp_path / "routing.toml"
    path.write_text(new)
    return path


def test_the_shipped_policy_loads(tmp_path):
    r.load_policy(_policy_with(tmp_path, 'frontier_order = ["codex", "claude", "antigravity-argon"]'))


@pytest.mark.parametrize("line, message", [
    ('frontier_order = ["codex", "claud", "antigravity-argon"]', "names no known service: ['claud']"),
    ('frontier_order = ["codex", "codex"]', "repeats a service"),
    ('frontier_order = []', "non-empty array"),
    ('frontier_order = "codex"', "non-empty array"),
    ('frontier_order = [1]', "non-empty array"),
], ids=["unknown name", "duplicate", "empty", "not a list", "not strings"])
def test_a_bad_frontier_order_fails_the_policy_load_loudly(tmp_path, line, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        r.load_policy(_policy_with(tmp_path, line))


def test_an_upper_case_repo_key_fails_the_load_because_the_lookup_lower_cases(tmp_path):
    text = (ROOT / "config" / "routing.toml").read_text().replace("[dispatch.repo_overrides.tendcf]\nfrontier_order",
                                                                   "[dispatch.repo_overrides.TendCF]\nfrontier_order")
    path = tmp_path / "routing.toml"
    path.write_text(text)
    with pytest.raises(ValueError, match="lower case"):
        r.load_policy(path)
