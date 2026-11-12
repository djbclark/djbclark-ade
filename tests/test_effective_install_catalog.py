"""Joint catalog reader adoption: pure temp-root metadata, never live operations."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from unittest.mock import Mock

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))
import ade_config as ac
import ade_config_edit as edit
import ade_install as ai
import ade_install_catalog as pure


@pytest.fixture
def catalog_root(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    shutil.copy2(REPO / "config/install.schema.json", root / "config/install.schema.json")
    shutil.copy2(REPO / "tests/fixtures/install_catalog/minimal.toml", root / "config/install.toml")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("ROUTING_POLICY", "GATES_TOML", "MODEL_TIERS_TOML"):
        monkeypatch.delenv(name, raising=False)
    return root, home


def full_root(root):
    for name in ("ade.schema.json", "routing.toml", "gates.toml", "model-tiers.toml"):
        shutil.copy2(REPO / "config" / name, root / "config" / name)


def local(home, text):
    path = home / ".config/djbclark-ade/local.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def unified(root, *, keys=True):
    path = root / "config/ade.toml"
    path.write_text('schema_version=1\n[[install.component]]\nid="unified"\nclass="hard"\n'
                    'install_argv=["must-not-run"]\n' +
                    ('[keys.UNIFIED_KEY]\ncreate_url="fixture-url"\n' if keys else ""))
    return path


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None for p in root.rglob("*")}


def test_legacy_round_trip_and_install_only_root_have_no_effects(catalog_root, monkeypatch):
    root, home = catalog_root
    raw = tomllib.loads((root / "config/install.toml").read_text())
    before = snapshot(root.parent)
    forbidden = Mock(side_effect=AssertionError("metadata load performed an operation"))
    monkeypatch.setattr(ai.subprocess, "run", forbidden)
    monkeypatch.setattr(ai.shutil, "which", forbidden)
    actual = ai.load_catalog(root=root, home=home, environ={
        "ROUTING_POLICY": str(root / "absent-routing"),
        "GATES_TOML": str(root / "absent-gates"), "MODEL_TIERS_TOML": str(root / "absent-tiers"),
    })
    assert actual.data == raw == pure.catalog_from_effective(pure.project_catalog(raw))
    assert actual.path == root / "config/install.toml"
    assert actual.provenance["source"] == "install.toml"
    assert snapshot(root.parent) == before
    forbidden.assert_not_called()


def test_effective_schema_matches_catalog_structure():
    legacy = json.loads((REPO / "config/install.schema.json").read_text())
    effective = ac.read_schema(REPO / "config/ade.schema.json")
    for name, node in pure.effective_schema_parts(legacy).items():
        assert effective["properties"][name] == node
    for name in ("COMPONENT_CLASSES", "JOB_CLASSES", "JOB_KINDS", "PASEO_MODES", "CHOICE_CLASSES"):
        assert getattr(ai, name) == getattr(pure, name)


def test_unified_catalog_replaces_legacy_without_probing(catalog_root):
    root, home = catalog_root
    path = unified(root)
    (root / "config/install.toml").write_text("invalid legacy [")
    catalog = ai.load_catalog(root=root, home=home)
    assert [row["id"] for row in catalog.components] == ["unified"]
    assert [row["name"] for row in catalog.keys] == ["UNIFIED_KEY"]
    assert catalog.path == path
    assert catalog.provenance["ade_toml_present"]


def test_missing_unified_install_refuses_but_optional_keys_stay_empty(catalog_root):
    root, home = catalog_root
    path = unified(root, keys=False)
    catalog = ai.load_catalog(root=root, home=home)
    assert catalog.keys == []  # never resurrect EXAMPLE_API_KEY from legacy
    path.write_text("schema_version=1\n[keys]\n")
    with pytest.raises(ai.InstallError, match="missing effective catalog domain"):
        ai.load_catalog(root=root, home=home)


def test_named_keys_merge_per_leaf_and_arrays_replace_whole(catalog_root):
    root, home = catalog_root
    local_path = local(home, '''[[install.component]]
id="only-local"
class="offered"
chosen=false
[[install.login]]
id="local-login"
[[install.jobs]]
name="local-job"
kind="ade-sched"
owner="djbclark-ade"
class="optional"
chosen=false
[[install.retired_jobs]]
name="old-job"
kind="ade-sched"
owner="djbclark-ade"
label="fixture.old"
[keys.EXAMPLE_API_KEY]
expiry="fixture-expiry"
verify_argv=["must-not-run"]
''')
    catalog = ai.load_catalog(root=root, home=home)
    assert [r["id"] for r in catalog.components] == ["only-local"]
    assert [r["id"] for r in catalog.logins] == ["local-login"]
    assert [r["name"] for r in catalog.jobs] == ["local-job"]
    assert [r["name"] for r in catalog.retired_jobs] == ["old-job"]
    key = catalog.keys[0]
    assert key["name"] == "EXAMPLE_API_KEY"
    assert key["expiry"] == "fixture-expiry"
    assert key["components"] == ["tool-a"]
    assert key["create_url"] == "UNKNOWN"
    assert key["verify_argv"] == ["must-not-run"]
    assert catalog.provenance["local_config"] == str(local_path)


@pytest.mark.parametrize("source", ["unified", "local"])
@pytest.mark.parametrize("bad", [
    'routing="bad"', 'service=[1]',
    '[gates.frontier]\nfrontier2_per_wave="wide"', 'model_tiers="bad"',
])
def test_catalog_only_root_validates_raw_unrelated_domains(catalog_root, source, bad):
    root, home = catalog_root
    if source == "unified":
        path = unified(root)
        # Put a root scalar before the table headers.
        path.write_text("schema_version=1\n" + bad + "\n" + path.read_text().split("\n", 1)[1])
    else:
        local(home, bad + "\n")
    with pytest.raises(ai.InstallError):
        ai.load_catalog(root=root, home=home)


def test_raw_overlay_refuses_when_no_full_schema_is_available(catalog_root, monkeypatch):
    root, home = catalog_root
    monkeypatch.setattr(ac, "_BIN", root / "bin")
    # The old catalog-only input remains supported without unrelated schemas.
    assert ai.load_catalog(root=root, home=home).components
    local(home, '[keys.EXAMPLE_API_KEY]\nexpiry="fixture"\n')
    with pytest.raises(ai.InstallError, match="full effective schema required"):
        ai.load_catalog(root=root, home=home)


@pytest.mark.parametrize("bad,match", [
    ('[[install.component]]\nid="x"\nclass="offered"', "chosen"),
    ('[[install.component]]\nid="x"\nclass="hard"\nchosen=false', "cannot set chosen=false"),
    ('[[install.component]]\nid="x"\nclass="hard"\nsystem_argv=["no"]', "needs_system=true"),
    ('[[install.component]]\nid="x"\nclass="hard"\npaseo_plugin="x"\ninstall_argv=["no"]', "observe-only"),
    ('[[install.component]]\nid="x"\nclass="hard"\n[[install.component]]\nid="x"\nclass="hard"', "duplicate"),
    ('[keys.EXAMPLE_API_KEY]\nverify_argv=[]', "non-empty"),
    ('[keys.EXAMPLE_API_KEY]\nverify_argv=[1]', "must be string"),
    ('[keys.EXAMPLE_API_KEY]\nname="renamed"', "unknown key name"),
    ('[keys.EXAMPLE_API_KEY]\nvalue="forbidden-field"', "unknown key value"),
    ('[[install.jobs]]\nname="x"\nkind="paseo"\nowner="djbclark-ade"\nclass="hard"\nmode="guessed"', "mode"),
])
def test_invalid_local_catalog_metadata_refuses(catalog_root, bad, match):
    root, home = catalog_root
    local(home, bad + "\n")
    with pytest.raises(ai.InstallError, match=match):
        ai.load_catalog(root=root, home=home)


def test_legacy_duplicate_keys_reject_before_named_projection(catalog_root):
    root, home = catalog_root
    path = root / "config/install.toml"
    path.write_text(path.read_text() + '\n[[key]]\nname="EXAMPLE_API_KEY"\n')
    with pytest.raises(ai.InstallError, match="duplicate name"):
        ai.load_catalog(root=root, home=home)


def test_explicit_legacy_path_keeps_isolation_and_unified_refusal(catalog_root):
    root, home = catalog_root
    selected = root / "config/install.toml"
    local(home, "invalid [ local")
    assert ai.load_catalog(root=root, install_path=selected, home=home).components
    (root / "config/ade.toml").write_text("schema_version=1\n")
    with pytest.raises(ai.InstallError, match="refuse transitional"):
        ai.load_catalog(root=root, install_path=selected, home=home)


def test_generic_full_reader_exposes_catalog_and_local_differences(catalog_root):
    root, home = catalog_root
    full_root(root)
    local(home, '[keys.EXAMPLE_API_KEY]\nexpiry="changed"\n')
    effective = ac.load_effective(root=root, home=home, environ={})
    assert ac.get_path(effective.data, "install.component")[0]["id"] == "tool-a"
    assert ac.get_path(effective.data, "keys.EXAMPLE_API_KEY.expiry") == "changed"
    assert any(change.path == "keys.EXAMPLE_API_KEY.expiry" for change in ac.local_diff(root=root, home=home, environ={}))
    assert ac.check(root=root, home=home, environ={})[0] == []
    local(home, '[keys.EXAMPLE_API_KEY]\nverify_argv=[]\n')
    assert ac.check(root=root, home=home, environ={})[0]


def test_routing_and_gate_readers_do_not_require_or_read_legacy_install(catalog_root, monkeypatch):
    root, home = catalog_root
    full_root(root)
    import route_agent as router
    import ade_gates as gates
    monkeypatch.setattr(gates, "__file__", str(root / "bin/ade_gates.py"))
    for legacy in ("absent", "malformed"):
        path = root / "config/install.toml"
        path.unlink(missing_ok=True)
        if legacy == "malformed":
            path.write_text("invalid [ install")
        assert router.load_effective_policy(root=root, home=home, environ={})[0]["service"]
        assert gates.load_frontier()[0]["frontier2_per_wave"] == 1
    # A routing-only unified file is valid for those readers, not the Catalog.
    (root / "config/ade.toml").write_text("schema_version=1\n" + (root / "config/routing.toml").read_text())
    assert router.load_effective_policy(root=root, home=home, environ={})[0]["service"]
    with pytest.raises(ai.InstallError, match="missing effective catalog domain"):
        ai.load_catalog(root=root, home=home)


@pytest.mark.parametrize("target", ["local", "repo"])
@pytest.mark.parametrize("dotted", ["install.component", "install.login.example-login.command", "keys.EXAMPLE_API_KEY.value"])
def test_new_domains_remain_read_only_to_scalar_writer(catalog_root, target, dotted):
    root, home = catalog_root
    before = snapshot(root.parent)
    with pytest.raises(edit.EditError, match="unsupported|only supports|install set supports"):
        edit.set_scalar(dotted, "fixture", target=target, root=root, home=home)
    assert snapshot(root.parent) == before


def test_adopted_catalog_preserves_system_plugin_and_choice_boundaries(catalog_root, monkeypatch):
    root, home = catalog_root
    catalog = ai.load_catalog(root=root, home=home)
    monkeypatch.setattr(ai, "observe_component", lambda row, **kw: ai.Observation("component", row["id"], "missing", "fixture"))
    steps = {row.id: row for row in ai.build_apply_steps(catalog)}
    assert steps["tool-b"].action == "skip"
    assert steps["tool-d"].action == "refuse-system"
    shown = {row.id: row for row in ai.build_apply_steps(catalog, allow_system=True)}
    assert shown["tool-d"].action == "would-system-install"
    local(home, '[[install.component]]\nid="plugin"\nclass="offered"\nchosen=true\npaseo_plugin="fixture"\n')
    assert ai.build_apply_steps(ai.load_catalog(root=root, home=home))[0].action == "blocked"


def test_full_config_cli_exposes_new_domains_without_operations(catalog_root):
    root, home = catalog_root
    full_root(root)
    local(home, '[keys.EXAMPLE_API_KEY]\nexpiry="changed"\n')
    before = snapshot(root.parent)
    for args in (("check",), ("get", "keys.EXAMPLE_API_KEY.expiry"), ("diff",)):
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(REPO / "bin/ade-config"), *args,
             "--root", str(root), "--home", str(home), "--json"],
            env={**os.environ, "HOME": str(home)}, capture_output=True, text=True, check=False,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        if args[0] == "get":
            assert payload["value"] == "changed"
        elif args[0] == "diff":
            assert any(c["path"] == "keys.EXAMPLE_API_KEY.expiry" for c in payload["changes"])
    assert snapshot(root.parent) == before


def test_existing_keys_engine_receives_adopted_metadata_only(catalog_root, monkeypatch, tmp_path):
    root, home = catalog_root
    local(home, '[keys.EXAMPLE_API_KEY]\nverify_argv=["fixture-verify"]\n')
    catalog = ai.load_catalog(root=root, home=home)
    monkeypatch.setattr(ai, "observe_secretspec_check", lambda **kw: ai.Observation("keys", "check", "ok", "fixture"))
    seen = []
    def verify(row, **kwargs):
        seen.append(row)
        return ai.Observation("key", row["name"], "ok", "fixture")
    monkeypatch.setattr(ai, "observe_key_verify", verify)
    forbidden = Mock(side_effect=AssertionError("test attempted an external command"))
    observations, rc = ai.keys_observe(catalog, runner=forbidden, keys_state_path=tmp_path / "outcomes.json")
    assert rc == 0
    assert [row["name"] for row in seen] == ["EXAMPLE_API_KEY"]
    assert seen[0]["verify_argv"] == ["fixture-verify"]
    assert seen[0]["components"] == ["tool-a"]
    assert any(o.id == "EXAMPLE_API_KEY" and o.status == "ok" for o in observations)
    forbidden.assert_not_called()
