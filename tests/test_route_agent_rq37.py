"""route_agent.py rq-37 (2026-11-15): the rt-01 Lows of PR 708. Rows and reports of one pool are told apart by the ACCOUNT they
read (aiuse `account`, Paseo `id`), not by the pool key: a repeat of one account's quota is one reading (known beats unknown),
anything else is another account and folds fail closed. `cap_only` is gone. No test here touches the live quota.
"""
from __future__ import annotations

import itertools
import sys
from typing import Any
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import route_agent as r  # noqa: E402


def _row(left, *, account=None, family="default", expired=False, window="weekly", bare=False):
    row = {"provider": "claude", "pool_family": family, "usable_now": True, "headroom_percent": left, "age_seconds": 60}
    if account is not None:
        row["account"] = account
    if expired:
        row["reading_expired"] = True
    if not bare:
        row["binding_window"] = window
        row["windows"] = [{"label": window, "pool_family": family, "remaining_percent": left,
                           "headroom_percent": left, "state": "ok"}]
    return row


def _fold(*rows):
    return r._providers_from_available(list(rows), 60)["claude"]


# ---- 1. aiuse rows: the account, not the pool key, decides --------------------------------------------------------------

@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_a_repeated_reading_of_one_account_lets_the_known_one_win(order):
    """Same account and family twice (a fresh and an expired reading): one quota, the known reading opens the gate.
    Before, the second row counted as another account and closed the pool."""
    rows = [_row(50, account="a@x"), _row(90, account="a@x", expired=True, bare=True)]
    pool = _fold(*[rows[i] for i in order])
    assert pool["remaining"] == 50
    assert r.UNMEASURED_WINDOW not in pool["windows"]
    assert r.plenty_remaining(pool) == 50


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_two_accounts_still_fold_as_accounts_and_an_expired_one_closes_the_pool(order):
    rows = [_row(50, account="a@x"), _row(90, account="b@x", expired=True, bare=True)]
    pool = _fold(*[rows[i] for i in order])
    assert pool["remaining"] == 50
    assert r.UNMEASURED_WINDOW in pool["windows"]
    assert r.plenty_remaining(pool) is None


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_rows_without_an_account_cannot_be_shown_to_be_one_account_and_stay_fail_closed(order):
    """Unidentified rows (older aiuse, hand-made fixtures) fold as accounts, as before this change."""
    rows = [_row(50), _row(90, expired=True, bare=True)]
    pool = _fold(*[rows[i] for i in order])
    assert r.plenty_remaining(pool) is None and r.UNMEASURED_WINDOW in pool["windows"]


def test_a_blank_account_counts_as_no_account():
    pool = _fold(_row(50, account="  "), _row(90, account="  ", expired=True, bare=True))
    assert r.plenty_remaining(pool) is None


def test_an_account_seen_beside_another_never_counts_as_a_repeat():
    """a, b, then a again: `a` repeats, but `b` is folded under the key, so the third row still folds as an account."""
    pool = _fold(_row(50, account="a@x"), _row(60, account="b@x"), _row(90, account="a@x", expired=True, bare=True))
    assert r.plenty_remaining(pool) is None


@pytest.mark.parametrize("order", list(itertools.permutations(range(3))))
def test_one_account_with_its_fable_cap_row_is_unchanged_in_every_order(order):
    """The cap row is no account whatever its `account` says; a one-account pool reads as it did with `cap_only`."""
    cap = {**_row(35, account="a@x", family="fable"), "binding_window": "Claude Code weekly - Fable"}
    rows = [_row(50, account="a@x"), cap, _row(50, account="a@x", window="session")]
    pool = _fold(*[rows[i] for i in order])
    assert pool["remaining"] == 50 and pool["sublimits"] == {"fable": 35.0}
    assert r.UNMEASURED_WINDOW not in pool["windows"]


def test_one_account_with_a_fable_cap_row_opens_the_gate_in_either_order():
    cap = {**_row(35, account="a@x", family="fable"), "binding_window": "Claude Code weekly - Fable"}
    for rows in ([_row(50, account="a@x"), cap], [cap, _row(50, account="a@x")]):
        pool = _fold(*rows)
        assert pool["remaining"] == 50 and pool["sublimits"] == {"fable": 35.0}
        assert r.UNMEASURED_WINDOW not in pool["windows"]
        assert r.plenty_remaining(pool) == 50


@pytest.mark.parametrize("order", list(itertools.permutations(range(4))))
def test_two_accounts_each_with_a_fable_cap_row_close_only_for_the_unread_one(order):
    """Two measured accounts and their cap rows, every order: the pool opens on the tighter account."""
    rows = [_row(50, account="a@x"), _row(70, account="b@x"),
            {**_row(35, account="a@x", family="fable"), "binding_window": "Claude Code weekly - Fable"},
            {**_row(40, account="b@x", family="fable"), "binding_window": "Claude Code weekly - Fable"}]
    pool = _fold(*[rows[i] for i in order])
    assert pool["remaining"] == 50 and pool["sublimits"] == {"fable": 35.0}
    assert r.UNMEASURED_WINDOW not in pool["windows"]
    assert r.plenty_remaining(pool) == 50


def test_cap_only_is_gone_from_the_aiuse_fold():
    import inspect
    assert "cap_only" not in inspect.getsource(r._providers_from_available)


def test_the_identity_helpers():
    assert r._identity("a@x", "f") == ("a@x", "f") and r._identity(" a@x ") == ("a@x", None)
    assert r._identity(None)[0] is None and r._identity(5)[0] is None and r._identity("")[0] is None
    me = ("a@x", "f")
    assert not r._folds_as_accounts([], me)                       # nothing folded yet: no merge
    assert not r._folds_as_accounts([me], me)                     # the same quota again
    assert not r._folds_as_accounts([me, me], me)
    assert r._folds_as_accounts([me], ("b@x", "f"))               # another account
    assert r._folds_as_accounts([me], ("a@x", "g"))               # another family of it
    assert r._folds_as_accounts([me, ("b@x", "f")], me)           # another account is folded beside it
    assert r._folds_as_accounts([(None, "f")], (None, "f"))       # unidentified: cannot be shown to be the same
    assert r._folds_as_accounts([me], (None, "f"))


# ---- 2. Paseo reports: `id` is the account ------------------------------------------------------------------------------

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def _report(rid, left=None, *, status="available", age_min=1.0, source="claude", label="Weekly", **extra):
    rep: dict[str, Any] = {"status": status}
    if status == "available":
        rep["windows"] = [] if left is None else [{"id": label, "label": label, "remainingPct": left,
                                                    "resetsAt": "2026-11-20T00:00:00Z"}]
        rep["balances"] = []
    row = {"sourceId": source, "fetchedAt": (NOW - timedelta(minutes=age_min)).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "report": rep, **extra}
    if rid is not None:
        row["id"] = rid
    return row


def _paseo(*rows):
    return r.usage_from_paseo(list(rows), now=NOW)["claude"]


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_two_paseo_accounts_close_the_gate_when_one_cannot_be_read(order):
    """`claude:a` measured, `claude:b` unavailable: before, the unreadable report was dropped (or replaced) and the pool
    opened on the measured account alone."""
    rows = [_report("claude:a", 60), _report("claude:b", status="unavailable")]
    pool = _paseo(*[rows[i] for i in order])
    assert pool["remaining"] == 60
    assert pool["windows"][r.UNMEASURED_WINDOW] is None
    assert r.plenty_remaining(pool) is None


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_two_measured_paseo_accounts_open_the_gate_on_the_tighter_one(order):
    rows = [_report("claude:a", 60), _report("claude:b", 40)]
    pool = _paseo(*[rows[i] for i in order])
    assert pool["remaining"] == 40 and r.UNMEASURED_WINDOW not in pool["windows"]
    assert r.plenty_remaining(pool) == 40


def test_two_paseo_accounts_with_a_window_only_one_reads_keep_that_window_closed():
    a = _report("claude:a", 60)
    b = _report("claude:b", 70)
    b["report"]["windows"].append({"id": "5h", "label": "5h", "remainingPct": None, "resetsAt": None})
    pool = _paseo(a, b)
    assert pool["windows"]["5h"] is None and r.plenty_remaining(pool) is None


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_two_paseo_accounts_one_window_one_cannot_measure_stays_closed_but_a_repeat_of_one_account_does_not(order):
    """Same window label: account b reads it as unknown. Another account: the unknown stays (closed); the same `id`
    again: the known reading wins (`_merge_caps`)."""
    unread = _report("claude:b", None)
    unread["report"]["windows"] = [{"id": "Weekly", "label": "Weekly", "remainingPct": None, "usedPct": None}]
    rows = [_report("claude:a", 60), unread]
    pool = _paseo(*[rows[i] for i in order])
    assert pool["windows"]["Weekly"] is None and r.plenty_remaining(pool) is None
    again = dict(unread, id="claude:a")
    pool = _paseo(*[[_report("claude:a", 60), again][i] for i in order])
    assert pool["windows"]["Weekly"] == 60.0 and r.plenty_remaining(pool) == 60


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_a_repeated_paseo_report_of_one_account_is_unchanged(order):
    """Same `id` twice: one account re-read, known beats unknown, no marker (the pre-rq-37 behaviour)."""
    rows = [_report("claude:a", 60), _report("claude:a", status="unavailable")]
    pool = _paseo(*[rows[i] for i in order])
    assert pool["remaining"] == 60 and r.UNMEASURED_WINDOW not in pool["windows"]
    assert r.plenty_remaining(pool) == 60


def test_a_repeated_available_paseo_report_of_one_account_takes_the_tighter_known_window():
    pool = _paseo(_report("claude:a", 60), _report("claude:a", 30))
    assert pool["remaining"] == 30 and r.UNMEASURED_WINDOW not in pool["windows"]


def test_one_unreadable_paseo_account_alone_is_unknown_as_before():
    pool = _paseo(_report("claude:a", status="unavailable"))
    assert pool["remaining"] is None and "unknown" in pool and r.UNMEASURED_WINDOW not in pool["windows"]


def test_two_unreadable_paseo_accounts_stay_unknown():
    pool = _paseo(_report("claude:a", status="unavailable"), _report("claude:b", status="unavailable"))
    assert pool["remaining"] is None and "unknown" in pool


def test_a_paseo_report_without_an_id_cannot_be_shown_to_be_the_same_account():
    """Hand-made rows with no `id`: a second report of the key is another account (fail closed)."""
    pool = _paseo(_report(None, 60), _report(None, status="unavailable"))
    assert pool["remaining"] == 60 and r.plenty_remaining(pool) is None


def test_the_lone_paseo_report_is_unchanged_and_the_marker_survives_the_aiuse_merge():
    paseo = r.usage_from_paseo([_report("claude:a", 60), _report("claude:b", status="unavailable")], now=NOW)
    aiuse = {"claude": {"remaining": 80.0, "windows": {"weekly": 80.0}, "sublimits": {}}}
    r._fold_paseo(aiuse, paseo)
    assert aiuse["claude"]["remaining"] == 60 and r.plenty_remaining(aiuse["claude"]) is None
    only = r.usage_from_paseo([_report("claude:a", 60)], now=NOW)["claude"]
    assert only["windows"] == {"Weekly": 60.0} and r.plenty_remaining(only) == 60


def test_the_live_shaped_rows_one_account_with_a_fable_window_read_as_before():
    rep = _report("claude:abc.def", 60)
    rep["report"]["windows"].append({"id": "f", "label": "Weekly · Fable", "remainingPct": 30, "resetsAt": None})
    pool = _paseo(rep)
    assert pool["remaining"] == 60 and pool["sublimits"] == {"fable": 30.0}
    assert pool["windows"] == {"Weekly": 60.0}


# ---- 3. frontier_order default ------------------------------------------------------------------------------------------

def test_a_repo_with_no_frontier_order_gets_the_empty_order():
    """The default is no order (the score decides); only a repository that declares one gets a sort."""
    assert r.repo_frontier_order(None) == () and r.repo_frontier_order("no-such-repo") == ()
    assert r.repo_frontier_order("tendcf") == ("codex", "claude", "antigravity-argon")
