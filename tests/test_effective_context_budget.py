"""Effective context budgets: temporary roots and saved output, no live calls."""
from __future__ import annotations

import importlib.machinery
import importlib.util
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


def load_cli(path):
    loader = importlib.machinery.SourceFileLoader("effective_context_budget_cli", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def tree(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    shutil.copy2(REPO / "config/ade.schema.json", root / "config/ade.schema.json")
    shutil.copy2(REPO / "config/context-budget.toml", root / "config/context-budget.toml")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    cli = load_cli(REPO / "bin/context-budget-check")
    monkeypatch.setattr(cli, "REPO", root)
    return root, home, cli


def local(home, text):
    path = home / ".config/djbclark-ade/local.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def effective(root, home, **kwargs):
    return ac.load_effective(root=root, home=home, domains=ac.CONTEXT_BUDGET_DOMAINS, **kwargs)


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None for p in root.rglob("*")}


def test_legacy_equivalence_and_scoped_default_read_is_pure(tree, monkeypatch):
    root, home, cli = tree
    before = snapshot(root.parent)
    forbidden = Mock(side_effect=AssertionError("live effect"))
    monkeypatch.setattr(cli.subprocess, "run", forbidden)
    raw = tomllib.loads((root / "config/context-budget.toml").read_text())
    result = effective(root, home, environ={"ROUTING_POLICY": "/missing", "GATES_TOML": "/missing",
                                           "MODEL_TIERS_TOML": "/missing"})
    assert result.data == {"schema_version": 1, "context_budget": raw}
    assert result.provenance["context_budget_source"] == str(root / "config/context-budget.toml")
    assert cli.load_effective_config() == cli.load_config(root / "config/context-budget.toml")
    assert cli.budget_for(cli.load_effective_config(), "~")["memory"] == 12000
    assert snapshot(root.parent) == before
    forbidden.assert_not_called()


def test_unified_replaces_legacy_and_local_merges_directory_leaves(tree):
    root, home, cli = tree
    (root / "config/ade.toml").write_text('schema_version=1\n[context_budget]\ndirs=["a","b"]\n'
                                        '[context_budget.budget]\ntotal=70000\n'
                                        '[context_budget.budget.a]\nmemory=25000\nskills=20000\n')
    (root / "config/context-budget.toml").write_text("invalid legacy [")
    override = local(home, '[context_budget]\ndirs=["a"]\n[context_budget.budget.a]\nmemory=30000\n')
    cfg = cli.load_effective_config()
    assert cfg["dirs"] == ["a"]
    assert cli.budget_for(cfg, "a")["memory"] == 30000
    assert cli.budget_for(cfg, "a")["skills"] == 20000
    assert cli.budget_for(cfg, "a")["total"] == 70000
    assert effective(root, home).provenance["local_config"] == str(override)
    override.write_text('[context_budget.budget.a]\nmemory=35000\n')
    assert cli.budget_for(cli.load_effective_config(), "a")["memory"] == 35000


@pytest.mark.parametrize("unified", [False, True])
def test_missing_context_uses_code_defaults_without_legacy_revival(tree, unified):
    root, home, cli = tree
    if unified:
        (root / "config/ade.toml").write_text("schema_version=1\n")
    else:
        (root / "config/context-budget.toml").unlink()
    cfg = cli.load_effective_config()
    assert cfg == {"dirs": ["~/src/djbclark-ade", "~"], "budget": {}}
    assert cli.budget_for(cfg, "~") == cli.DEFAULT_BUDGET


def test_empty_dirs_and_budget_keep_existing_fallbacks(tree):
    root, home, cli = tree
    (root / "config/ade.toml").write_text("schema_version=1\n[context_budget]\ndirs=[]\nbudget={}\n")
    assert cli.load_effective_config() == cli.load_config(root / "absent")


@pytest.mark.parametrize("body", [
    'context_budget="bad"', '[context_budget]\ndirs=[1]', '[context_budget]\nbudget=1',
    '[context_budget.budget]\ntotal=true', '[context_budget.budget]\ngrow_alert="bad"',
    '[context_budget.budget]\nmemory=nan', '[context_budget.budget]\nskills=inf',
    '[context_budget.budget.total]\nwrong=4',
    '[context_budget.budget."~"]\nmemory=false',
    '[context_budget.budget."~".nested]\nmemory=1', '[context_budget]\nunknown=1',
])
@pytest.mark.parametrize("source", ["unified", "local"])
def test_invalid_raw_context_fails_before_effects(tree, monkeypatch, capsys, body, source):
    root, home, cli = tree
    if source == "unified":
        (root / "config/ade.toml").write_text("schema_version=1\n" + body + "\n")
    else:
        local(home, body + "\n")
    before = snapshot(root.parent)
    forbidden = Mock(side_effect=AssertionError("invalid config reached effects"))
    for name in ("measure", "previous", "send_ping", "write_state"):
        monkeypatch.setattr(cli, name, forbidden)
    assert cli.main([]) == 2
    assert "config:" in capsys.readouterr().err
    assert snapshot(root.parent) == before
    forbidden.assert_not_called()


def test_malformed_legacy_fails_default_reader_but_explicit_reader_stays_legacy(tree):
    root, home, cli = tree
    path = root / "config/context-budget.toml"
    path.write_text('[budget]\ntotal="legacy-value"\n')
    with pytest.raises(cli.ConfigError, match="finite number"):
        cli.load_effective_config()
    assert cli.load_config(path)["budget"]["total"] == "legacy-value"
    path.write_text("invalid [")
    with pytest.raises(tomllib.TOMLDecodeError):
        cli.load_config(path)


def test_explicit_cli_ignores_invalid_unified_and_local(tree, monkeypatch, capsys):
    root, home, cli = tree
    (root / "config/ade.toml").write_text("invalid [")
    local(home, "invalid [")
    explicit = root / "explicit.toml"
    explicit.write_text('dirs=["fixture"]\n[budget]\ntotal=99000\nmemory=99000\n'
                        'skills=99000\nmcp_tools=99000\nmcp_instructions=99000\n')
    forbidden = Mock(side_effect=AssertionError("explicit config read effective config"))
    monkeypatch.setattr(cli, "load_effective_config", forbidden)
    assert cli.main(["--config", str(explicit), "--from-file", str(REPO / "tests/fixtures/context-now.txt"),
                     "--dry-run"]) == 0
    assert "fixture: total" in capsys.readouterr().out
    forbidden.assert_not_called()


def test_overlaid_budget_changes_real_saved_output_alerts(tree, capsys):
    root, home, cli = tree
    args = ["--from-file", str(REPO / "tests/fixtures/context-now.txt"), "--dry-run"]
    assert cli.main(args) == 1
    assert "BREACH" in capsys.readouterr().out
    local(home, '[context_budget.budget]\ntotal=99000\nmemory=99000\nskills=99000\n'
                'mcp_tools=99000\nmcp_instructions=99000\n')
    before = snapshot(root.parent)
    assert cli.main(args) == 0
    assert "BREACH" not in capsys.readouterr().out
    assert snapshot(root.parent) == before


@pytest.mark.parametrize("domains", [{"install"}, ac.ROUTER_DOMAINS])
def test_raw_context_validated_even_when_scoped_away(tree, domains):
    root, home, cli = tree
    for name in ("routing.toml", "gates.toml", "model-tiers.toml"):
        shutil.copy2(REPO / "config" / name, root / "config" / name)
    local(home, '[context_budget.budget]\nmemory=false\n')
    with pytest.raises(ac.ConfigError, match="finite number"):
        ac.load_effective(root=root, home=home, domains=domains)


def test_router_scope_ignores_unselected_legacy_context(tree):
    root, home, cli = tree
    for name in ("routing.toml", "gates.toml", "model-tiers.toml"):
        shutil.copy2(REPO / "config" / name, root / "config" / name)
    (root / "config/context-budget.toml").write_text("invalid legacy [")
    assert "context_budget" not in ac.load_effective(root=root, home=home,
                                                    domains=ac.ROUTER_DOMAINS).data


@pytest.mark.parametrize("target", ["repo", "local"])
def test_scalar_writer_refuses_context_non_leaf_paths_without_effects(tree, target):
    root, home, cli = tree
    before = snapshot(root.parent)
    with pytest.raises(edit.EditError, match="numeric budget leaves and dirs"):
        edit.resolve_set_target("context_budget.budget", target=target, root=root, home=home)
    assert snapshot(root.parent) == before


def test_cold_default_cli_uses_effective_metadata_without_cache_or_other_writes(tree):
    root, home, cli = tree
    bindir = root / "bin"
    bindir.mkdir()
    for name in ("context-budget-check", "ade_config.py", "ade_install_catalog.py", "model_tiers.py"):
        shutil.copy2(REPO / "bin" / name, bindir / name)
    (root / "config/ade.toml").write_text('schema_version=1\n[context_budget]\ndirs=["fixture"]\n'
                                        '[context_budget.budget]\ntotal=99000\nmemory=99000\n'
                                        'skills=99000\nmcp_tools=99000\nmcp_instructions=99000\n')
    before = snapshot(root.parent)
    result = subprocess.run([sys.executable, str(bindir / "context-budget-check"), "--from-file",
                             str(REPO / "tests/fixtures/context-now.txt"), "--dry-run"],
                            capture_output=True, text=True, env={**os.environ, "HOME": str(home)})
    assert result.returncode == 0, result.stderr
    assert "fixture: total" in result.stdout
    assert snapshot(root.parent) == before


def test_default_context_reader_validates_unrelated_raw_domains(tree):
    root, home, cli = tree
    (root / "config/ade.toml").write_text('schema_version=1\nrouting="bad"\n')
    with pytest.raises(cli.ConfigError, match="must be object"):
        cli.load_effective_config()


def test_context_overlay_type_conflict_refuses(tree):
    root, home, cli = tree
    local(home, '[context_budget.budget]\n"~"=1\n')
    with pytest.raises(cli.ConfigError, match="type conflict"):
        cli.load_effective_config()


@pytest.mark.parametrize("kind", ["local", "unified"])
def test_other_scalar_edits_cannot_publish_invalid_context_metadata(tree, kind):
    root, home, cli = tree
    target = edit.SetTarget(path=root / "test.toml", file_parts=("lead", "fable_lead"),
                            kind=kind, target="local" if kind == "local" else "repo", created=False)
    before = snapshot(root.parent)
    with pytest.raises(ac.ConfigError, match="finite number"):
        edit.validate_target_tree({"schema_version": 1, "context_budget": {"budget": {"total": False}}},
                                  target, root=root)
    assert snapshot(root.parent) == before


@pytest.mark.parametrize("label,budget", [("fixture", "fixture=1"), ("total", "total=99000")])
@pytest.mark.parametrize("selected_by", ["configured", "cli"])
def test_scalar_directory_collision_refuses_before_effects(tree, monkeypatch, capsys, label, budget, selected_by):
    root, home, cli = tree
    configured = label if selected_by == "configured" else "other"
    (root / "config/ade.toml").write_text(f'schema_version=1\n[context_budget]\ndirs=["{configured}"]\n'
                                        f'[context_budget.budget]\n{budget}\n')
    forbidden = Mock(side_effect=AssertionError("directory collision reached effects"))
    for name in ("measure", "parse_context", "previous", "send_ping", "write_state"):
        monkeypatch.setattr(cli, name, forbidden)
    args = [] if selected_by == "configured" else ["--from-file", "unused", "--dir", label]
    before = snapshot(root.parent)
    assert cli.main(args) == 2
    assert "directory override table" in capsys.readouterr().err
    assert snapshot(root.parent) == before
    forbidden.assert_not_called()


@pytest.mark.parametrize("dirs", [None, "[]"])
def test_default_directory_collision_refuses_after_empty_or_missing_dirs(tree, monkeypatch, capsys, dirs):
    root, home, cli = tree
    text = 'schema_version=1\n[context_budget]\n' + (f'dirs={dirs}\n' if dirs is not None else "")
    (root / "config/ade.toml").write_text(text + '[context_budget.budget]\n"~"=1\n')
    forbidden = Mock(side_effect=AssertionError("default collision reached effects"))
    for name in ("measure", "previous", "send_ping", "write_state"):
        monkeypatch.setattr(cli, name, forbidden)
    before = snapshot(root.parent)
    assert cli.main([]) == 2
    assert "directory override table" in capsys.readouterr().err
    assert snapshot(root.parent) == before
    forbidden.assert_not_called()


def test_explicit_legacy_scalar_collision_retains_original_type_failure(tree):
    root, home, cli = tree
    path = root / "explicit.toml"
    path.write_text('dirs=["fixture"]\n[budget]\nfixture=1\n')
    cfg = cli.load_config(path)
    assert cfg["budget"]["fixture"] == 1
    with pytest.raises(TypeError):
        cli.budget_for(cfg, "fixture")


def test_empty_cli_directory_uses_same_validated_fallback_label(tree, monkeypatch, capsys):
    root, home, cli = tree
    (root / "config/ade.toml").write_text('schema_version=1\n[context_budget]\ndirs=[]\n'
                                        '[context_budget.budget]\n"~/src/djbclark-ade"=1\n')
    forbidden = Mock(side_effect=AssertionError("empty --dir collision reached effects"))
    for name in ("measure", "parse_context", "previous", "send_ping", "write_state"):
        monkeypatch.setattr(cli, name, forbidden)
    before = snapshot(root.parent)
    assert cli.main(["--from-file", "unused", "--dir", ""]) == 2
    assert "directory override table" in capsys.readouterr().err
    assert snapshot(root.parent) == before
    forbidden.assert_not_called()


def test_generic_config_cli_exposes_context_and_diff_without_effects(tree):
    root, home, cli = tree
    for name in ("routing.toml", "gates.toml", "model-tiers.toml"):
        shutil.copy2(REPO / "config" / name, root / "config" / name)
    local(home, '[context_budget.budget]\ntotal=50000\n')
    before = snapshot(root.parent)
    for args in (["check"], ["get", "context_budget.budget.total"], ["diff"]):
        result = subprocess.run([sys.executable, "-I", "-B", str(REPO / "bin/ade-config"), *args,
                                 "--root", str(root), "--home", str(home), "--json"],
                                capture_output=True, text=True, env={**os.environ, "HOME": str(home)})
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        if args[0] == "get":
            assert payload["value"] == 50000
        elif args[0] == "diff":
            assert any(c["path"] == "context_budget.budget.total" for c in payload["changes"])
    assert snapshot(root.parent) == before
