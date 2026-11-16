"""Regression: deleted worktrees silently remove Pi providers."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import ade_install as ai


def settings(home, value):
    path = home / ".pi/agent/settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(value))
    return path


def test_absent_settings_is_not_failure(tmp_path):
    assert ai.observe_pi_extension_paths(home=tmp_path) is None


def test_removed_worktree_and_dangling_symlink_are_reported(tmp_path):
    gone = tmp_path / "removed-wt/index.mjs"
    link = tmp_path / "dangling.mjs"
    link.symlink_to(gone)
    path = settings(tmp_path, {"extensions": [str(gone), str(link)]})
    before = path.read_bytes()
    row = ai.observe_pi_extension_paths(home=tmp_path)
    assert row.status == "missing"
    assert str(gone) in row.detail and str(link) in row.detail
    assert "durable checkout" in row.detail
    assert path.read_bytes() == before


def test_existing_files_directories_and_home_expansion(tmp_path):
    (tmp_path / "index.mjs").touch()
    (tmp_path / "extension").mkdir()
    settings(tmp_path, {"extensions": ["~/index.mjs", str(tmp_path / "extension")]})
    assert ai.observe_pi_extension_paths(home=tmp_path).status == "ok"


@pytest.mark.parametrize("value", [None, [], {"extensions": None}, {"extensions": [42]}])
def test_invalid_settings_fail_without_echoing_values(tmp_path, value):
    settings(tmp_path, value)
    row = ai.observe_pi_extension_paths(home=tmp_path)
    assert row.status == "error"
    assert row.detail == "Invalid Pi settings or extensions list"


def test_bad_json_is_reported(tmp_path):
    path = settings(tmp_path, {})
    path.write_text("{not-json")
    assert ai.observe_pi_extension_paths(home=tmp_path).status == "error"


def test_pi_patterns_and_relative_sources_are_left_to_pi(tmp_path):
    settings(tmp_path, {"extensions": ["builtin:mcp", "-builtin:mcp", "npm:example", "./local.mjs",
                                      "/missing/*.mjs", "!/missing/disabled.mjs"]})
    assert ai.observe_pi_extension_paths(home=tmp_path).status == "ok"
