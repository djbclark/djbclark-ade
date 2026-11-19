"""Shared real decision/write paths with synthetic Git DATA, not qualification."""
import importlib
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parents[1] / "bin"


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(BIN))
    return tuple(importlib.import_module(name) for name in
                 ("ade_claims", "ade_ws_names", "ade_ws_autoname"))


def no_git(*args, **kwargs):
    raise AssertionError("A shared decision launched nested Git")


def test_observed_naming_data_never_launches_git(modules, monkeypatch, tmp_path):
    claims, names, naming = modules
    monkeypatch.setattr(names.subprocess, "run", no_git)
    monkeypatch.setattr(claims, "_run_git", no_git)
    repository = names.repo_from_common_dir(str(tmp_path / "linked"), "/source/project/.git\n")
    result = naming.decide({"cwd": str(tmp_path / "linked"), "firstAgent": True,
                            "agent": {"title": "audit"}}, repository=repository)
    assert result == {"action": "rename", "name": "LEAD project (audit)",
                      "kind": "LEAD", "repo": "project", "work": "audit"}
    assert names.repo_from_common_dir(str(tmp_path / "linked"), "/source/project.git") == "project"
    assert names.repo_from_common_dir(str(tmp_path / "linked"), None) == "linked"


def test_default_naming_still_resolves_repository_only_when_needed(modules, monkeypatch):
    _, names, naming = modules
    calls = []
    monkeypatch.setattr(names, "repo_of", lambda cwd: calls.append(cwd) or "actual")
    assert naming.decide({"background": True})["action"] == "skip"
    assert calls == []
    result = naming.decide({"cwd": "/worktree", "firstAgent": True,
                            "agent": {"title": "trace"}})
    assert result["name"] == "LEAD actual (trace)"
    assert calls == ["/worktree"]


def test_fact_install_preserves_real_existing_hook_chain_without_git(modules, monkeypatch, tmp_path):
    claims, _, _ = modules
    monkeypatch.setattr(claims, "_run_git", no_git)
    common = tmp_path / ".git"
    hooks = common / "hooks"
    hooks.mkdir(parents=True)
    prior = hooks / "pre-push"
    original = "#!/bin/sh\nprintf original\n"
    prior.write_text(original)
    code, _ = claims.install_hooks_from_facts(str(tmp_path), str(common), 1, "")
    assert code == 0
    assert (hooks / "pre-push.pre-ade").read_text() == original
    installed = prior.read_text()
    assert claims.STUB_MARK in installed
    assert prior.stat().st_mode & 0o111
    assert claims.install_hooks_from_facts(str(tmp_path), str(common), 1, "")[0] == 0
    assert prior.read_text() == installed
    assert (hooks / "pre-push.pre-ade").read_text() == original


@pytest.mark.parametrize("status,output", [(0, "\0"), (0, "/other\0"), (2, "")])
def test_set_or_unknown_hookspath_never_writes_hooks(modules, monkeypatch, tmp_path, status, output):
    claims, _, _ = modules
    monkeypatch.setattr(claims, "_run_git", no_git)
    common = tmp_path / ".git"
    code, _ = claims.install_hooks_from_facts(str(tmp_path), str(common), status, output)
    assert code == claims.EXIT_HOOKSPATH
    assert not common.exists()


def test_ordinary_install_obtains_own_two_git_facts(modules, monkeypatch, tmp_path):
    claims, _, _ = modules
    common = tmp_path / ".git"
    calls = []
    def query(argv):
        calls.append(argv)
        return (0, str(common)) if len(calls) == 1 else (1, "")
    monkeypatch.setattr(claims, "_run_git", query)
    assert claims.install_hooks(str(tmp_path))[0] == 0
    assert calls == [["-C", str(tmp_path), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                     ["-C", str(tmp_path), "config", "--null", "--get-all", "core.hooksPath"]]


def test_hook_conflict_remains_refused_and_preserves_both_originals(modules, monkeypatch, tmp_path):
    claims, _, _ = modules
    monkeypatch.setattr(claims, "_run_git", no_git)
    common = tmp_path / ".git"
    hooks = common / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "pre-push").write_text("existing")
    (hooks / "pre-push.pre-ade").write_text("older")
    assert claims.install_hooks_from_facts(str(tmp_path), str(common), 1, "")[0] == claims.EXIT_PRE_ADE
    assert (hooks / "pre-push").read_text() == "existing"
    assert (hooks / "pre-push.pre-ade").read_text() == "older"
