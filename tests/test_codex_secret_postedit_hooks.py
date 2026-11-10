"""Pin Codex template wiring for secret_read_gate + post-edit-check (2026-11-09, issue #284).

agents/codex/config.toml.tmpl must register both gates as inline [[hooks.*]] handlers (not only in
docs). Live ~/.codex/config.toml is not touched here (operator order 11).
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "agents" / "codex" / "config.toml.tmpl"


def _rendered() -> dict:
    text = TEMPLATE.read_text()
    text = re.sub(r"\{\{\s*\.home\s*\}\}", "/home/x", text)
    text = re.sub(r"\{\{\s*secret\s+\"[A-Za-z0-9_]+\"\s*\}\}", "SECRET", text)
    text = re.sub(r"\{\{\s*\.[A-Za-z_][A-Za-z0-9_]*\s*\}\}", "x", text)
    return tomllib.loads(text)


def test_codex_template_registers_secret_read_gate_pretooluse():
    hooks = _rendered()["hooks"]
    groups = hooks["PreToolUse"]
    hits = [
        (g, h)
        for g in groups
        for h in g.get("hooks", [])
        if "secret_read_gate.py" in h.get("command", "")
    ]
    assert len(hits) == 1, hits
    group, handler = hits[0]
    tools = set(group["matcher"].split("|"))
    assert {"Bash", "Edit", "Write", "apply_patch"} <= tools
    assert handler["type"] == "command"
    assert handler["timeout"] >= 15
    assert not handler["command"].lstrip().startswith("python")
    assert handler["command"].endswith("secret_read_gate.py") or "/secret_read_gate.py" in handler["command"]


def test_codex_template_registers_post_edit_check_posttooluse():
    hooks = _rendered()["hooks"]
    groups = hooks["PostToolUse"]
    hits = [
        (g, h)
        for g in groups
        for h in g.get("hooks", [])
        if "post-edit-check" in h.get("command", "")
    ]
    assert len(hits) == 1, hits
    group, handler = hits[0]
    tools = set(group["matcher"].split("|"))
    assert {"Edit", "Write", "apply_patch"} <= tools
    assert "--hook" in handler["command"]
    assert handler["type"] == "command"
    assert handler["timeout"] >= 20
    assert "hook-deadline" not in handler["command"]
