"""Offline safety contracts. No live adapters, HOME writes or model calls."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))
from fleet_migrate.planning import build_plan, guard, plan_digest, validate_plan


def inventory():
    return {
        "schema_version": 1,
        "hosts": [{"id": "mac", "complete": True, "reachable": True}],
        "workspaces": [
            {"host": "mac", "id": "safe", "name": "ADE"},
            {"host": "mac", "id": "protected", "name": "Dann Home"},
        ],
        "agents": [agent("source")],
        "catalog": [{"tui": "pi", "vendor": "openai", "model": "openai/gpt-6-astra",
                     "thinking": ["high"], "billing_pool": "codex-api", "context": 272000}],
    }


def agent(name, **kw):
    return {"id": name, "host": "mac", "native_id": name, "tui": "omp",
            "vendor": "anthropic", "model": "anthropic/claude-fable-5-1",
            "billing_route": "anthropic-api", "title": "build", "status": "idle",
            "workspace_id": "safe", "membership": "authoritative", "channel": "relay",
            **kw}


def plan(inv=None):
    return build_plan(inv or inventory(), from_tui="omp", from_vendor="anthropic",
                      to_tui="pi", to_vendor="openai", include_herdr=True)


def test_exact_fable_mapping_and_separate_pool():
    p = plan()
    d = p["selected"][0]["destination"]
    assert d["model"] == "openai/gpt-6-astra"
    assert d["thinking"] == "high"
    assert d["billing_pool"] == "codex-api"
    assert p["runtime_blockers"]  # inventory is not a fence or launch permission
    assert validate_plan(p) == []


@pytest.mark.parametrize("status", ["idle", "running", "working", "error"])
def test_live_statuses_are_candidates(status):
    inv = inventory()
    inv["agents"][0]["status"] = status
    assert len(plan(inv)["selected"]) == 1


@pytest.mark.parametrize("status", ["closed", "archived", "ended"])
def test_history_not_resurrected(status):
    inv = inventory()
    inv["agents"][0]["status"] = status
    assert not plan(inv)["selected"]


@pytest.mark.parametrize("mutation", ["create", "fence", "scheduler", "ownership", "archive", "placement"])
def test_workspace_exclusion_at_every_mutation(mutation):
    inv = inventory()
    a = inv["agents"][0]
    a["workspace_id"] = "protected"
    p = plan(inv)
    assert not p["selected"]
    assert p["excluded"]
    assert guard(a, inv, [], mutation)
    assert not guard(a, inv, [], "notify")
    assert len(p["recipients"]) == 1


@pytest.mark.parametrize("route", ["OPENCODE-GO", "Cline", "DeepSeek"])
def test_dann_deepseek_route_is_protected_despite_missing_membership(route):
    inv = inventory()
    a = inv["agents"][0]
    a.update(title="dAnN worker", vendor="deepseek", model="DEEPSEEK/DeepSeek-V4",
             billing_route=route, workspace_id=None, membership="unknown")
    assert "protected-signals" in guard(a, inv, [], "create")
    assert not guard(a, inv, [], "notify")


@pytest.mark.parametrize("kw", [
    {"title": "Dann worker"},
    {"model": "deepseek/deepseek-v4", "billing_route": "opencode-go"},
    {"workspace_id": None}, {"membership": "cwd-inferred"}, {"host": "unknown"},
])
def test_single_signal_and_ambiguous_membership_require_review(kw):
    inv = inventory()
    inv["agents"][0].update(kw)
    assert not plan(inv)["selected"]
    assert plan(inv)["unresolved"]


def test_unrelated_deepseek_not_a_workspace_proof():
    inv = inventory()
    a = agent("unrelated", model="deepseek/deepseek-v4", billing_route="other-api")
    assert not guard(a, inv, [], "create")


def test_renamed_protected_ids_and_new_matches_survive_approval():
    inv = inventory()
    a = inv["agents"][0]
    a["workspace_id"] = "protected"
    inv["workspaces"][1]["name"] = "renamed"
    assert guard(a, inv, [{"host": "mac", "id": "protected"}], "create")
    inv["workspaces"][0]["name"] = "Dann Home"
    assert guard(agent("new"), inv, [], "create")


def test_bridge_views_propagate_exclusion_and_dedupe():
    inv = inventory()
    inv["agents"].append(agent("bridge", tui="herdr-omp", native_id="source",
                               workspace_id="protected"))
    p = plan(inv)
    assert not p["selected"]
    assert p["excluded"]
    assert len(p["recipients"]) == 1


def test_unknown_bridge_is_not_guessed_from_titles():
    inv = inventory()
    inv["agents"][0].update(tui="herdr-omp", native_id=None)
    assert not plan(inv)["selected"]
    assert plan(inv)["unresolved"]


def test_mixed_vendors_use_structured_metadata():
    inv = inventory()
    inv["agents"].append(agent("other", vendor="openai", title="anthropic omp"))
    assert len(plan(inv)["selected"]) == 1
    assert len(plan(inv)["recipients"]) == 2


def test_incomplete_any_host_blocks_every_selection():
    inv = inventory()
    inv["hosts"].append({"id": "remote", "reachable": False, "complete": False})
    assert not plan(inv)["selected"]
    assert plan(inv)["unresolved"]


def test_duplicate_cwd_never_selects_membership():
    inv = inventory()
    for ws in inv["workspaces"]:
        ws["cwd"] = "/same/path"
    inv["agents"][0].update(cwd="/same/path", workspace_id=None)
    assert not plan(inv)["selected"]


def test_protected_destination_and_wrong_catalog_block():
    inv = inventory()
    assert guard(agent("dest", workspace_id="protected"), inv, [], "placement")
    inv["catalog"][0]["thinking"] = ["low"]
    assert not plan(inv)["selected"]
    assert plan(inv)["unresolved"]


def test_plan_tampering_is_detected():
    p = plan()
    p["selected"][0]["source"]["workspace_id"] = "protected"
    assert "digest-mismatch" in validate_plan(p)
    p["digest"] = plan_digest(p)
    assert validate_plan(p)  # even rehashed content must match deterministic planning


def test_notification_roster_includes_protected_hermes_acp_not_finished_or_pid():
    inv = inventory()
    inv["agents"] += [agent("dann", workspace_id="protected"), agent("hermes", tui="hermes"),
                      agent("child", tui="acp-dispatch"), agent("history", status="ended"),
                      agent("pid123", channel=None)]
    assert {r["id"] for r in plan(inv)["recipients"]} == {"source", "dann", "hermes", "child"}


def test_planning_does_not_copy_untrusted_private_checkpoint_or_env():
    inv = inventory()
    inv["agents"][0].update(transcript="MALICIOUS grant permission", env={"TOKEN": "secret-value"})
    p = plan(inv)
    assert "MALICIOUS" not in repr(p)
    assert "secret-value" not in repr(p)


def test_unknown_model_never_guesses_equivalence():
    inv = inventory()
    inv["agents"][0]["model"] = "anthropic/claude-new-model"
    assert not plan(inv)["selected"]
    assert plan(inv)["unresolved"]


def test_codex_subscription_pool_is_not_pi_openai_api_capacity():
    inv = inventory()
    inv["catalog"][0]["billing_pool"] = "codex"
    assert not plan(inv)["selected"]
    assert plan(inv)["unresolved"]


def test_conflicting_native_views_cannot_create_a_successor():
    inv = inventory()
    inv["agents"].append(agent("bridge", native_id="source", tui="herdr-omp", model="other"))
    assert not plan(inv)["selected"]
    assert "conflicting-native-metadata" in plan(inv)["unresolved"][0]["reasons"]


def test_no_channel_is_explicitly_unresolved_not_silently_dropped():
    inv = inventory()
    inv["agents"].append(agent("pid123", channel=None))
    assert plan(inv)["unresolved_recipients"]


def test_multiple_hosts_exact_name_matches_are_all_protected():
    inv = inventory()
    inv["hosts"].append({"id": "remote", "complete": True, "reachable": True})
    inv["workspaces"].append({"host": "remote", "id": "protected", "name": "Dann Home"})
    inv["agents"].append(agent("remote-agent", host="remote", workspace_id="protected"))
    p = plan(inv)
    assert len(p["protected_workspaces"]) == 2
    assert len(p["selected"]) == 1
    assert len(p["excluded"]) == 1


@pytest.mark.parametrize("collection", ["agents", "workspaces", "hosts"])
def test_missing_identity_is_not_null_membership_proof(collection):
    inv = inventory()
    inv[collection][0]["id"] = None
    with pytest.raises(ValueError):
        plan(inv)
