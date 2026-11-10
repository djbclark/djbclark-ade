"""Bounded context/key writes: temporary config, whole-tree and consumer proof."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
from unittest.mock import Mock

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))
import ade_config as ac
import ade_config_edit as edit
import ade_install as install


@pytest.fixture
def tree(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    for name in ("ade.schema.json", "install.schema.json", "context-budget.toml"):
        shutil.copy2(REPO / "config" / name, root / "config" / name)
    shutil.copy2(REPO / "tests/fixtures/install_catalog/minimal.toml", root / "config/install.toml")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("ROUTING_POLICY", "GATES_TOML", "MODEL_TIERS_TOML"):
        monkeypatch.setenv(name, str(tmp_path / "unreadable-isolated-domain"))
    return root, home


def local(home, text):
    path = ac.default_local_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def unified(root):
    path = root / "config/ade.toml"
    path.write_text('schema_version=1\n[[install.component]]\nid="fixture"\nclass="hard"\n'
                    '[keys.EXAMPLE_API_KEY]\ncreate_url="UNKNOWN"\nverify="UNKNOWN"\n'
                    'expiry="unknown"\nnotes="base"\n'
                    '[context_budget]\ndirs=["~"]\n[context_budget.budget]\ntotal=30000\n'
                    '[context_budget.budget."~"]\nmemory=12000\n')
    return path


def set_value(tree, path, value, **kwargs):
    root, home = tree
    return edit.set_scalar(path, value, root=root, home=home, **kwargs)


def effective_context(tree):
    root, home = tree
    return ac.context_budget_config(ac.load_effective(root=root, home=home,
                                                      domains=ac.CONTEXT_BUDGET_DOMAINS).data)


@pytest.mark.parametrize("target,base", [("repo", "legacy"), ("local", "legacy"),
                                        ("repo", "unified"), ("local", "unified")])
def test_context_globals_and_real_quoted_directory_leaves(tree, target, base):
    root, home = tree
    if base == "unified":
        unified(root)
    result = set_value(tree, 'context_budget.budget."~".memory', 22000, target=target)
    assert result.changed and result.adoption == "recorded-only"
    assert effective_context(tree)["budget"]["~"]["memory"] == 22000
    set_value(tree, "context_budget.budget.total", 50000, target=target)
    assert effective_context(tree)["budget"]["total"] == 50000
    assert not (root / "config/ade.toml").exists() if base == "legacy" else True


@pytest.mark.parametrize("field", sorted(edit.KEY_METADATA_FIELDS))
@pytest.mark.parametrize("target,base", [("repo", "legacy"), ("local", "legacy"),
                                        ("repo", "unified"), ("local", "unified")])
def test_four_existing_key_metadata_fields_affect_catalog(tree, field, target, base):
    root, home = tree
    if base == "unified":
        unified(root)
    result = set_value(tree, f"keys.EXAMPLE_API_KEY.{field}", "changed metadata", target=target)
    catalog = install.load_catalog(root=root, home=home)
    row = next(row for row in catalog.keys if row["name"] == "EXAMPLE_API_KEY")
    assert row[field] == "changed metadata"
    assert result.target.kind == ({"local": "local"}.get(target) or
                                  ("unified" if base == "unified" else "legacy_key"))


def test_full_legacy_catalog_one_named_slot_preserves_every_other_byte(tree):
    root, home = tree
    path = root / "config/install.toml"
    text = (REPO / "config/install.toml").read_text()
    text += '\n# trailing bytes retained\n'
    path.write_text(text)
    parsed = tomllib.loads(text)
    result = set_value(tree, "keys.ANTHROPIC_API_KEY.expiry", "2028-01-01", target="repo")
    expected = copy.deepcopy(parsed)
    row = next(row for row in expected["key"] if row["name"] == "ANTHROPIC_API_KEY")
    row["expiry"] = "2028-01-01"
    assert edit.values_equal(tomllib.loads(path.read_text()), expected)
    assert path.read_text() == text.replace('expiry = "unknown"', 'expiry = "2028-01-01"', 1)
    assert result.before == "unknown" and result.after == "2028-01-01"


def test_named_row_adapter_skips_fake_headers_and_supports_quoted_identity(tree):
    root, home = tree
    path = root / "config/install.toml"
    text = path.read_text().replace('summary = "fixture hard tool"',
                                   'summary = """fixture\n[[key]]\nname="FAKE"\n"""')
    text = text.replace('name = "EXAMPLE_API_KEY"', 'name = "KEY.WITH#DOT"').replace('[[key]]', '[["key"]]')
    path.write_text(text)
    before = tomllib.loads(text)
    set_value(tree, 'keys."KEY.WITH#DOT".notes', "new note", target="repo")
    after = tomllib.loads(path.read_text())
    expected = copy.deepcopy(before)
    expected["key"][0]["notes"] = "new note"
    assert edit.values_equal(after, expected)
    assert '[[' in after["component"][0]["summary"]


def test_quoted_path_hash_dot_and_quote_are_literal_parts(tree):
    root, home = tree
    label = '~/a.b#c"d'
    path = 'context_budget.budget.' + json.dumps(label) + '.memory'
    set_value(tree, path, 21000)
    assert effective_context(tree)["budget"][label]["memory"] == 21000


@pytest.mark.parametrize("path,value", [
    ("install.component.chosen", True), ("install.component[0].chosen", True),
    ("context_budget.dirs", "fixture"), ("context_budget.budget.total", True),
    ("context_budget.budget.total", float("nan")), ("context_budget.budget.total", "30000"),
    ("keys.EXAMPLE_API_KEY.verify_argv", "ignored"), ("keys.EXAMPLE_API_KEY.components", "ignored"),
    ("keys.EXAMPLE_API_KEY.name", "OTHER"), ("keys.EXAMPLE_API_KEY.value", "forbidden"),
    ("keys.EXAMPLE_API_KEY.notes", 1), ("keys.NEW_ID.notes", "cannot create"),
])
def test_unsupported_surfaces_do_not_change_config(tree, path, value):
    root, home = tree
    before = {p: p.read_bytes() for p in (root / "config").iterdir()}
    with pytest.raises(ac.ConfigError):
        set_value(tree, path, value, target="repo")
    assert {p: p.read_bytes() for p in before} == before
    assert not ac.default_local_path(home).exists()


@pytest.mark.parametrize("target", ["local", "repo"])
def test_dry_run_and_valid_noop_keep_bytes_mode_mtime(tree, target):
    root, home = tree
    if target == "local":
        path = local(home, '[context_budget.budget]\ntotal=30000 # keep comment\n')
    else:
        path = root / "config/context-budget.toml"
    path.chmod(0o640)
    before, stat = path.read_bytes(), path.stat()
    preview = set_value(tree, "context_budget.budget.total", 45000, target=target, dry_run=True)
    assert preview.changed and path.read_bytes() == before
    noop = set_value(tree, "context_budget.budget.total", 30000, target=target)
    assert not noop.changed
    assert (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns) == (before, stat.st_mode, stat.st_mtime_ns)


@pytest.mark.parametrize("noop", [False, True])
def test_effective_context_collision_refuses_even_noop(tree, noop):
    root, home = tree
    path = root / "config/context-budget.toml"
    path.write_text('dirs=["fixture"]\n[budget]\ntotal=30000\n')
    local(home, '[context_budget]\ndirs=[]\n[context_budget.budget]\n"~"=1\n')
    before = path.read_bytes()
    with pytest.raises(ac.ConfigError, match="directory override table"):
        set_value(tree, "context_budget.budget.total", 30000 if noop else 60000, target="repo")
    assert path.read_bytes() == before


def test_partial_local_context_source_cannot_publish_final_type_conflict(tree):
    root, home = tree
    with pytest.raises(ac.ConfigError, match="type conflict"):
        set_value(tree, 'context_budget.budget."~"', 1)
    assert not ac.default_local_path(home).exists()


@pytest.mark.parametrize("metadata", ["context", "key"])
def test_unrelated_raw_overlay_invalidity_still_blocks_candidate(tree, metadata):
    root, home = tree
    local(home, 'routing="bad"\n')
    path = root / "config" / ("context-budget.toml" if metadata == "context" else "install.toml")
    before = path.read_bytes()
    with pytest.raises(ac.ConfigError, match="must be object"):
        set_value(tree, "context_budget.budget.total" if metadata == "context" else "keys.EXAMPLE_API_KEY.notes",
                  60000 if metadata == "context" else "note", target="repo")
    assert path.read_bytes() == before


def test_candidate_new_local_is_validated_and_input_is_not_mutated(tree):
    root, home = tree
    candidate = {"context_budget": {"budget": {"total": 60000}}}
    before = copy.deepcopy(candidate)
    result = ac.load_effective(root=root, home=home, domains=ac.CONTEXT_BUDGET_DOMAINS,
                               _candidate=(ac.default_local_path(home), candidate))
    assert result.data["context_budget"]["budget"]["total"] == 60000
    assert candidate == before and not ac.default_local_path(home).exists()
    with pytest.raises(ac.ConfigError, match="restricted"):
        ac.load_effective(root=root, home=home, domains=ac.CONTEXT_BUDGET_DOMAINS, include_local=False,
                          _candidate=(ac.default_local_path(home), candidate))


def test_unified_source_selected_without_legacy_fallback(tree):
    root, home = tree
    path = unified(root)
    legacy = root / "config/install.toml"
    before = legacy.read_bytes()
    set_value(tree, "keys.EXAMPLE_API_KEY.notes", "new", target="repo")
    assert legacy.read_bytes() == before
    assert tomllib.loads(path.read_text())["keys"]["EXAMPLE_API_KEY"]["notes"] == "new"
    path.write_text('schema_version=1\n[context_budget.budget]\ntotal=1\n')
    with pytest.raises(ac.ConfigError):
        set_value(tree, "keys.EXAMPLE_API_KEY.notes", "cannot revive legacy", target="repo")
    assert legacy.read_bytes() == before


def test_noop_requires_valid_existing_key_registry(tree):
    root, home = tree
    local(home, '[keys.EXAMPLE_API_KEY]\nverify_argv=[]\n')
    before = (root / "config/install.toml").read_bytes()
    with pytest.raises(ac.ConfigError, match="non-empty"):
        set_value(tree, "keys.EXAMPLE_API_KEY.expiry", "unknown", target="repo")
    assert (root / "config/install.toml").read_bytes() == before


def test_duplicate_legacy_key_identity_refused_before_edit(tree):
    root, home = tree
    path = root / "config/install.toml"
    path.write_text(path.read_text() + '\n[[key]]\nname="EXAMPLE_API_KEY"\n')
    before = path.read_bytes()
    with pytest.raises(ac.ConfigError, match="duplicate"):
        set_value(tree, "keys.EXAMPLE_API_KEY.notes", "no", target="repo")
    assert path.read_bytes() == before


def test_dangling_local_symlink_is_never_replaced(tree):
    root, home = tree
    path = ac.default_local_path(home)
    path.parent.mkdir(parents=True)
    path.symlink_to(home / "missing")
    with pytest.raises(ac.ConfigError, match="symlink"):
        set_value(tree, "context_budget.budget.total", 55000)
    assert path.is_symlink() and not (home / "missing").exists()


def test_atomic_failure_leaves_source_unchanged(tree, monkeypatch):
    root, home = tree
    path = root / "config/context-budget.toml"
    before = path.read_bytes()
    monkeypatch.setattr(edit.os, "replace", Mock(side_effect=OSError("injected failure")))
    with pytest.raises(OSError, match="injected failure"):
        set_value(tree, "context_budget.budget.total", 55000, target="repo")
    assert path.read_bytes() == before
    assert not [p for p in path.parent.glob(path.name + ".*") if p.name != path.name + ".lock"]


def test_cli_quoted_set_reports_result_without_dotted_get_roundtrip(tree):
    root, home = tree
    result = subprocess.run([sys.executable, "-I", "-B", str(REPO / "bin/ade-config"), "set",
                             'context_budget.budget."~".memory', "21000", "--root", str(root),
                             "--home", str(home), "--json"], capture_output=True, text=True,
                            env={**os.environ, "HOME": str(home)})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["after"] == 21000
    assert effective_context(tree)["budget"]["~"]["memory"] == 21000


def test_candidate_cannot_skip_raw_ignored_domain_validation(tree):
    root, home = tree
    with pytest.raises(ac.ConfigError, match="must be object"):
        ac.load_effective(root=root, home=home, domains=ac.CONTEXT_BUDGET_DOMAINS,
                          _candidate=(ac.default_local_path(home), {"routing": "bad",
                                      "context_budget": {"budget": {"total": 60000}}}))
    assert not ac.default_local_path(home).exists()


def test_candidate_scope_and_repository_creation_are_restricted(tree):
    root, home = tree
    with pytest.raises(ac.ConfigError, match="restricted"):
        ac.load_effective(root=root, home=home, domains=ac.ROUTER_DOMAINS,
                          _candidate=(root / "config/install.toml", {}))
    with pytest.raises(ac.ConfigError, match="refuses creation"):
        ac.load_effective(root=root, home=home, domains=ac.CONTEXT_BUDGET_DOMAINS,
                          _candidate=(root / "config/ade.toml", {"schema_version": 1}))
    assert not (root / "config/ade.toml").exists()
