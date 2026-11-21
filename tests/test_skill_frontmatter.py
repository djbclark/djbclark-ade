"""Every skills/*/SKILL.md frontmatter must be valid YAML with a name and a description.

An unquoted description holding ": " is a YAML scanner error (PR 848, 2026-11-21: tell-coding-bot), and a strict
skill loader then skips the skill or drops its description.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SKILLS = sorted((Path(__file__).resolve().parents[1] / "skills").glob("*/SKILL.md"))


def _frontmatter(path: Path) -> str:
    text = path.read_text()
    assert text.startswith("---\n"), f"{path}: no frontmatter"
    return text.split("---\n", 2)[1]


def test_skills_were_found():
    assert SKILLS


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_skill_frontmatter_is_valid_yaml(path):
    data = yaml.safe_load(_frontmatter(path))
    assert isinstance(data, dict)
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("description"), str) and data["description"]
