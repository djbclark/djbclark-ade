"""OpenCode Go cost policy (bin/go_model_policy.py) and the router rows that consume it.

The acp-run / acp-dispatch enforcement tests left with those shims (Wave 6 deletion, 2026-11-14)."""

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("go_model_policy", ROOT / "bin/go_model_policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


def test_economical_luna_is_not_gated_just_for_a_lower_monthly_allotment():
    assert policy.classification("opencode-go/gpt-6-luna") == "routine"
    assert policy.refusal("opencode-go/gpt-6-luna", timeout=1800) is None


@pytest.mark.parametrize("model", ["grok-4.7", "kimi-k3", "deepseek-v4-pro", "glm-5.3", "kimi-k2.7-code"])
def test_known_costly_models_require_explicit_advice(model):
    assert "advisory-only" in policy.refusal("opencode-go/" + model, timeout=600)


def test_unknown_go_is_not_implicitly_cheap_or_an_advisor():
    assert "unclassified" in policy.refusal("opencode-go/new-model", advisory=True,
                                             timeout=600, perm="read-only")
    assert policy.classification("opencode/deepseek-v4-pro") is None
    assert policy.classification("sipb/deepseek-v4-pro") is None


@pytest.mark.parametrize("timeout", [0, -1, 601, float("nan"), float("inf")])
def test_advisory_deadline_cannot_be_unbounded(timeout):
    assert "timeout" in policy.refusal("opencode-go/kimi-k3", advisory=True,
                                        timeout=timeout, perm="read-only")


def test_advice_requires_read_only_and_small_requested_context():
    assert "read-only" in policy.refusal("opencode-go/kimi-k3", advisory=True, timeout=600)
    assert policy.refusal("opencode-go/kimi-k3", advisory=True, timeout=600,
                          perm="read-only", context="64k") is None
    assert "context" in policy.refusal("opencode-go/kimi-k3", advisory=True, timeout=600,
                                        perm="read-only", context="1m")


def test_curated_go_default_routes_use_only_routine_models():
    import tomllib
    data = tomllib.loads((ROOT / "config/routing.toml").read_text())
    go = next(s for s in data["service"] if s["name"] == "opencode-go")
    assert go["billing"] == "subscription"
    assert all(policy.classification(m.split()[0]) == "routine" for m in go["models"].values())


def test_routine_router_refuses_a_costly_config_regression():
    sys.path.insert(0, str(ROOT / "bin"))
    import route_agent
    from dataclasses import replace
    svc = replace(route_agent.BY_NAME["opencode-go"], models={"code": "opencode-go/kimi-k3"})
    with pytest.raises(ValueError, match="routine Go routing"):
        route_agent.suggest_model(svc, "code", {})
