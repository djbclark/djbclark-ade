"""Repo-level pins for the secret read-deny wiring (issue 284).

The committed Claude template must equal what bin/render-secret-deny produces from
config/secret-deny.toml, and its PreToolUse gate entry must exec the hook directly (a missing
file then exits 127, which never blocks) with timeout 15 and no fail-closed `onFailure`.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "agents" / "claude" / "settings.json.tmpl"


def test_render_check_clean_on_repo():
    p = subprocess.run([sys.executable, str(REPO / "bin" / "render-secret-deny"), "--check"],
                       cwd=REPO, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stdout + p.stderr


def _settings():
    return json.loads(re.sub(r"\{\{.*?\}\}", "x", TEMPLATE.read_text()))


def test_gate_entry_exec_direct_fail_open():
    entries = [h for grp in _settings()["hooks"]["PreToolUse"] for h in grp["hooks"]
               if "secret_read_gate.py" in h.get("command", "")]
    assert len(entries) == 1
    h = entries[0]
    assert not h["command"].lstrip().startswith("python"), "exec it: python3 FILE exits 2 when FILE is missing"
    assert h["timeout"] >= 15
    assert "onFailure" not in h


def test_gate_matcher_covers_file_tools_not_glob():
    groups = [g for g in _settings()["hooks"]["PreToolUse"]
              if any("secret_read_gate.py" in h.get("command", "") for h in g["hooks"])]
    tools = set(groups[0]["matcher"].split("|"))
    assert {"Read", "Edit", "Bash", "Grep"} <= tools and "Glob" not in tools
