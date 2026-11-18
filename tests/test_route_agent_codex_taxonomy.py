"""Canonical aiuse subscription identity cannot fund the independent API pool."""
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import route_agent as r


def subscription():
    # Sanitized shape observed from installed aiuse 5.1.2 / Schema 1.6.
    return {"provider": "codex", "vendor": "openai", "pool_id": "openai:codex",
            "pool_family": None, "quota_scope": "pool", "usable_now": True,
            "headroom_percent": 74.0, "age_seconds": 0,
            "windows": [{"label": "Codex weekly quota", "window_id": "secondary",
                         "state": "ok", "remaining_percent": 74.0,
                         "headroom_percent": 74.0}]}


def test_canonical_subscription_available_and_windows_bind_only_subscription():
    pool = r._providers_from_available([subscription()], 0)
    assert pool["codex-subscription"]["remaining"] == 74.0
    assert pool["codex-subscription"]["windows"]["Codex weekly quota"] == 74.0
    assert "codex" not in pool
    assert r.pool_service("codex", None) is None  # unnamed metadata alone stays unknown


def test_parent_subscription_id_does_not_capture_labeled_api_window():
    account = subscription()
    account["windows"].extend([
        {"label": "session", "state": "ok", "remaining_percent": 17.0,
         "headroom_percent": 17.0},
        {"label": "OpenAI API credits", "pool_family": "openai_api",
         "state": "exhausted", "remaining_percent": 0.0, "headroom_percent": 0.0}])
    pools = r._providers_from_accounts([account], 0)
    assert pools["codex-subscription"]["remaining"] == 17.0
    assert pools["codex"]["remaining"] == 0.0


@pytest.mark.parametrize("change", [
    {"pool_id": None}, {"pool_id": "openai:unclaimed"},
    {"vendor": None}, {"vendor": "other"},
    {"pool_id": "openai:openai_api"},
    {"pool_family": "openai_api"}])
def test_missing_or_contradictory_identity_does_not_grant_subscription(change):
    row = subscription()
    row.update(change)
    pools = r._providers_from_available([row], 0)
    assert "codex-subscription" not in pools
    assert "codex" not in pools


@pytest.mark.parametrize("change,expected", [
    ({"age_seconds": r.STALE_SOFT + 1}, None),
    ({"usable_now": False}, 0.0),
    ({"state": "blocked"}, 0.0),
    ({"headroom_percent": 0.0}, 0.0)])
def test_canonical_id_preserves_freshness_and_blocking(change, expected):
    row = subscription()
    row.update(change)
    assert r._providers_from_available([row], 0)["codex-subscription"]["remaining"] == expected


def test_exclusion_tightens_subscription_without_spending_api_balance():
    pools = {"codex-subscription": {"remaining": 74.0}, "codex": {"remaining": 61.0}}
    row = subscription()
    row["reason"] = "operator-disabled"
    r._apply_excluded(pools, [row])
    assert pools["codex-subscription"]["remaining"] == 0.0
    assert pools["codex"]["remaining"] == 61.0


def test_subscription_can_route_mechanical_but_cannot_fund_api_code_or_frontier():
    pools = r._providers_from_available([subscription()], 0)
    services = [r.BY_NAME["codex"], r.BY_NAME["codex-subscription"]]
    with mock.patch.object(r, "discover", return_value=services), mock.patch.object(r, "operator_disabled", return_value=set()):
        choice = r.route("mechanical", quota=pools)
        assert choice.service.name == "codex-subscription"
        assert choice.model.startswith("gpt-6-luna")
        assert r.route("code", quota=pools) is None
        assert r.route("frontier", quota=pools) is None
