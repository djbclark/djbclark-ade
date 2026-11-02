"""bin/cow-pasture untrust: `remove` must not leave a pasture's seeded Claude Code trust entry behind in ~/.claude.json
(2026-11-01: three btww pastures were removed and their entries stayed), and must not drop one a session extended."""
import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "cow-pasture"

SEEDED = {
    "allowedTools": [], "mcpContextUris": [], "mcpServers": {},
    "enabledMcpjsonServers": [], "disabledMcpjsonServers": [],
    "hasTrustDialogAccepted": True,
    "hasClaudeMdExternalIncludesApproved": False,
    "hasClaudeMdExternalIncludesWarningShown": False,
}


def untrust(home, path):
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run(["bash", str(SCRIPT), "untrust", str(path)], capture_output=True, text=True, env=env, timeout=30)


def projects(home):
    return json.loads((home / ".claude.json").read_text())["projects"]


def test_seeded_entry_is_dropped_and_others_are_kept(tmp_path):
    gone, other = tmp_path / "pasture-gone", tmp_path / "pasture-other"
    (tmp_path / ".claude.json").write_text(json.dumps({"theme": "dark", "projects": {str(gone): SEEDED, str(other): SEEDED}}))
    r = untrust(tmp_path, gone)  # the directory need not exist: `remove` calls this after cow deleted it
    assert r.returncode == 0, r.stderr
    assert projects(tmp_path) == {str(other): SEEDED}
    assert json.loads((tmp_path / ".claude.json").read_text())["theme"] == "dark"


def test_an_entry_a_session_extended_is_left_alone(tmp_path):
    kept = tmp_path / "pasture-kept"
    extended = {**SEEDED, "allowedTools": ["Bash(git status:*)"]}
    (tmp_path / ".claude.json").write_text(json.dumps({"projects": {str(kept): extended}}))
    assert untrust(tmp_path, kept).returncode == 0
    assert projects(tmp_path) == {str(kept): extended}


def test_missing_claude_json_is_not_an_error(tmp_path):
    assert untrust(tmp_path, tmp_path / "nothing").returncode == 0
    assert not (tmp_path / ".claude.json").exists()
