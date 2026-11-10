"""Effective tier snapshots in router consumers, with no live config/providers."""
from __future__ import annotations

import copy
import json
import re

import pytest

from test_route_agent_effective_config import ac, cli, local_file, router, tree, unified_file
import model_tiers as mt


@pytest.fixture(autouse=True)
def restore_runtime():
    policy, path, provenance = router.POLICY, router.POLICY_PATH, router.POLICY_PROVENANCE
    tiers, families = router.MODEL_TIERS, router.SUBLIMIT_FAMILIES
    yield
    router.POLICY_PATH = path
    router.apply_policy(policy)
    router.POLICY_PROVENANCE = provenance
    router.MODEL_TIERS, router.SUBLIMIT_FAMILIES = tiers, families


def tier_text(raw):
    return "\n".join(
        "[model_tiers." + line[1:] if line.startswith("[") else line
        for line in mt.dump_toml(raw).splitlines()
    ) + "\n"


def modified_tiers(root):
    raw = mt.load(root / "config/model-tiers.toml", use_cache=False).data
    raw["vendor"]["claude"]["roles"].update(
        frontier="claude-fable-99", judgment="claude-sonnet-5-5",
    )
    raw["vendor"]["claude"]["pools"]["frontier"]["pool_family"] = "future_cap"
    raw["model"]["claude-fable-99"] = {"vendor": "claude", "alias": "future-frontier"}
    return raw


def reload_at(root, monkeypatch):
    monkeypatch.setattr(ac, "repo_root_from_here", lambda: root)
    return router.reload_policy()


def assert_modified_runtime():
    assert router.SUBLIMIT_FAMILIES == ("future_cap",)
    assert "future-frontier" in router.frontier_model_tokens()
    assert router.is_frontier_model("claude-fable-99 --effort high")
    assert router.suggest_model(
        router.BY_NAME["claude"], "frontier", {"sublimits": {"future_cap": 0}},
    ) == "sonnet --effort high"


def test_legacy_public_tiers_and_consumers_are_equivalent(tree, monkeypatch):
    root, _ = tree
    expected = mt.load(root / "config/model-tiers.toml", use_cache=False)
    reload_at(root, monkeypatch)
    assert router.MODEL_TIERS.data == expected.data
    assert router.frontier_model_tokens() == list(dict.fromkeys(
        router.POLICY["dispatch"]["frontier_models"] + mt.frontier_tokens(expected),
    ))
    result = cli(tree, "policy")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["model_tiers"] == mt.public_dict(expected)


@pytest.mark.parametrize("unified", [False, True])
def test_overlays_affect_router_tokens_sublimits_and_fallback(tree, monkeypatch, unified):
    root, home = tree
    raw = modified_tiers(root)
    if unified:
        path = unified_file(root)
        path.write_text(path.read_text() + tier_text(raw))
    else:
        local_file(home, tier_text(raw))
    reload_at(root, monkeypatch)
    assert_modified_runtime()
    result = cli(tree, "policy")
    assert result.returncode == 0, result.stderr
    printed = json.loads(result.stdout)["model_tiers"]
    assert printed["vendor"]["claude"]["roles"]["judgment"] == "claude-sonnet-5-5"
    assert printed["sublimit_families"] == ["future_cap"]
    assert "future-frontier" in printed["frontier_tokens"]
    assert printed["source"] == "effective"


def test_runtime_recomputes_derived_fields_and_does_not_trust_report_metadata(tree, monkeypatch):
    root, home = tree
    local_file(home, '''[model_tiers]
frontier_tokens = ["forged-token"]
sublimit_families = ["forged-cap"]
source = "forged-source"
path = "forged-path"
''')
    reload_at(root, monkeypatch)
    view = mt.public_dict(router.MODEL_TIERS)
    assert "forged-token" not in view["frontier_tokens"]
    assert view["sublimit_families"] == ["fable"]
    assert view["source"] == "effective"
    assert view["path"] == str(root / "config/model-tiers.toml")
    assert view["error"] is None
    forged = {**mt.DEFAULTS, "error": "forged-error", "frontier_tokens": ["forged-token"]}
    parsed = mt.from_dict(forged)
    assert parsed.error is None
    assert "forged-token" not in mt.frontier_tokens(parsed)


@pytest.mark.parametrize("edit,match", [
    (lambda d: d["vendor"]["claude"]["roles"].update(judgment="unknown-model"), "has no .model. entry"),
    (lambda d: d["vendor"]["claude"].update(family="["), "family"),
    (lambda d: d["vendor"]["claude"].update(cascade=True), "cascade must be an int"),
    (lambda d: d["vendor"]["claude"].update(spell=["bad"]), "spell must be a string map"),
    (lambda d: d["vendor"]["claude"]["pools"]["frontier"].update(pool_family=[]), "pool_family must be"),
    (lambda d: d.update(rank={"order": []}), "non-empty array"),
])
def test_pure_effective_constructor_rejects_invalid_consumed_shapes(tree, edit, match):
    root, _ = tree
    raw = copy.deepcopy(mt.DEFAULTS)
    edit(raw)
    with pytest.raises(mt.TiersError, match=match):
        mt.from_dict(raw, path=root / "config/ade.toml")


@pytest.mark.parametrize("replacement", [
    '[model_tiers.vendor.claude.roles]\njudgment = "missing-model"\n',
    '[model_tiers.vendor.claude]\nfamily = "["\n',
    '[model_tiers.rank]\norder = []\n',
])
def test_invalid_local_tiers_refuse_cold_start_without_route_output(tree, replacement):
    _, home = tree
    local_file(home, replacement)
    result = cli(tree, "policy")
    assert result.returncode != 0
    assert not result.stdout
    assert "effective model tiers" in result.stderr


@pytest.mark.parametrize("bad_field", ["spell", "pool_family"])
def test_unified_tier_consumer_type_gaps_refuse_cold_start(tree, bad_field):
    root, _ = tree
    path = unified_file(root)
    text = tier_text(mt.load(root / "config/model-tiers.toml", use_cache=False).data)
    if bad_field == "spell":
        text = re.sub(r"(?m)^spell = .*$", 'spell = ["bad"]', text, count=1)
    else:
        text = text.replace('pool_family = "fable"', 'pool_family = []')
    path.write_text(path.read_text() + text)
    result = cli(tree, "policy")
    assert result.returncode != 0
    assert not result.stdout
    assert f"{bad_field} must be" in result.stderr


def test_invalid_tier_reload_leaves_all_previous_runtime_state(tree, monkeypatch):
    root, home = tree
    reload_at(root, monkeypatch)
    previous = (router.POLICY, router.SERVICES, router.POLICY_PATH,
                router.POLICY_PROVENANCE, router.MODEL_TIERS, router.SUBLIMIT_FAMILIES)
    plenty = router.PLENTY_MIN
    local_file(home, '[routing]\nplenty_min = 87.0\n'
               '[model_tiers.vendor.claude.roles]\njudgment = "missing-model"\n')
    with pytest.raises(mt.TiersError):
        router.reload_policy()
    current = (router.POLICY, router.SERVICES, router.POLICY_PATH,
               router.POLICY_PROVENANCE, router.MODEL_TIERS, router.SUBLIMIT_FAMILIES)
    assert all(before is after for before, after in zip(previous, current))
    assert router.PLENTY_MIN == plenty


def test_effective_tiers_must_cover_the_configured_claude_service(tree):
    root, _ = tree
    raw = copy.deepcopy(mt.DEFAULTS)
    raw["vendor"].pop("claude")
    raw["rank"]["order"] = ["codex"]
    raw["model"] = {key: value for key, value in raw["model"].items() if value["vendor"] == "codex"}
    path = unified_file(root)
    path.write_text(path.read_text() + tier_text(raw))
    result = cli(tree, "policy")
    assert result.returncode != 0
    assert not result.stdout
    assert "unknown vendor 'claude'" in result.stderr


def test_reload_refreshes_same_path_overlay_and_legacy_cache(tree, monkeypatch):
    root, home = tree
    path = local_file(home, tier_text(modified_tiers(root)))
    reload_at(root, monkeypatch)
    assert_modified_runtime()
    mt.load(root / "config/model-tiers.toml")  # pre-populate the separate legacy cache
    path.write_text('[model_tiers.vendor.claude.roles]\njudgment = "claude-haiku-5-5"\n')
    router.reload_policy()
    assert router.SUBLIMIT_FAMILIES == ("fable",)
    assert "future-frontier" not in router.frontier_model_tokens()
    assert router.suggest_model(router.BY_NAME["claude"], "frontier", {"sublimits": {"fable": 0}}) == "haiku --effort high"
    # A new native tier file at the same path must also win on the next reload.
    native = root / "config/model-tiers.toml"
    native.write_text(mt.dump_toml(modified_tiers(root)))
    path.unlink()
    router.reload_policy()
    assert_modified_runtime()


def test_routing_override_does_not_isolate_model_tier_domain(tree, monkeypatch):
    root, home = tree
    local_file(home, '[routing]\nplenty_min = 88.0\n' + tier_text(modified_tiers(root)))
    monkeypatch.setenv("ROUTING_POLICY", str(root / "config/routing.toml"))
    reload_at(root, monkeypatch)
    assert router.PLENTY_MIN == 50
    assert_modified_runtime()


@pytest.mark.parametrize("bad_file", [False, True])
def test_model_tiers_override_preserves_default_fallback_and_isolation(tree, monkeypatch, bad_file):
    root, home = tree
    selected = root / "selected-tiers.toml"
    if bad_file:
        selected.write_text("invalid [ toml")
    local_file(home, tier_text(modified_tiers(root)))
    monkeypatch.setenv("MODEL_TIERS_TOML", str(selected))
    reload_at(root, monkeypatch)
    assert router.MODEL_TIERS.data == mt.DEFAULTS
    assert router.MODEL_TIERS.source == "code"
    assert router.MODEL_TIERS.error
    assert router.MODEL_TIERS.path == selected
    assert router.SUBLIMIT_FAMILIES == ("fable",)


def test_valid_model_tiers_override_ignores_unified_and_local_tiers(tree, monkeypatch):
    root, home = tree
    selected = root / "selected-tiers.toml"
    selected.write_text(mt.dump_toml(mt.DEFAULTS))
    path = unified_file(root)
    path.write_text(path.read_text() + tier_text(modified_tiers(root)))
    local_file(home, tier_text(modified_tiers(root)))
    monkeypatch.setenv("MODEL_TIERS_TOML", str(selected))
    reload_at(root, monkeypatch)
    assert router.MODEL_TIERS.data == mt.DEFAULTS
    assert router.MODEL_TIERS.path == selected
    assert "future-frontier" not in router.frontier_model_tokens()


def test_explicit_legacy_apis_stay_isolated_from_invalid_overlays(tree, monkeypatch):
    root, home = tree
    selected = root / "config/model-tiers.toml"
    monkeypatch.setenv("MODEL_TIERS_TOML", str(selected))
    (root / "config/ade.toml").write_text("invalid [ unified")
    local_file(home, "invalid [ local")
    assert mt.load(selected, use_cache=False).data == mt.DEFAULTS
    expected = router.load_policy(root / "config/routing.toml")
    assert router.reload_policy(root / "config/routing.toml") == expected
    assert router.MODEL_TIERS.data == mt.DEFAULTS
    assert router.MODEL_TIERS.source == "file"
