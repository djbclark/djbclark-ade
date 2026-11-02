"""Every skill in skills/ must load in clients that parse SKILL.md front matter as YAML.

Regression (2026-11-01, Codex P1 on PR 229): an unquoted `description:` containing `machine: run` (a colon followed by a
space) is invalid YAML, so YAML-parsing clients could not load the skill at all. Also checked, because a client rejects
them: name and description must be plain strings (crush's all-strings schema) and the description at most 1024 bytes
(crush's cap; bin/fix-skill-frontmatter.py documents both)."""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SKILLS = sorted(p for p in (ROOT / "skills").glob("*/SKILL.md") if p.is_file())
FRONT = re.compile(r"^---\n(.*?)\n---\n", re.S)


def front_matter(path):
    m = FRONT.match(path.read_text(encoding="utf-8"))
    assert m, f"{path.relative_to(ROOT)}: no front matter block"
    return m.group(1)


@pytest.mark.parametrize("path", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_front_matter_is_valid_yaml_with_string_name_and_description(path):
    data = yaml.safe_load(front_matter(path))
    assert isinstance(data, dict), f"{path.relative_to(ROOT)}: front matter is not a mapping"
    assert isinstance(data.get("name"), str) and data["name"], "name must be a non-empty string"
    assert isinstance(data.get("description"), str) and data["description"], "description must be a non-empty string"
    assert len(data["description"].encode()) <= 1024, "description over 1024 bytes (crush rejects it)"


def test_an_unquoted_colon_space_in_a_description_is_caught():
    """The checker itself must catch the exact PR 229 shape, so the suite cannot pass on a parser that tolerates it."""
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load("name: x\ndescription: Greptile on this machine: run reviews\n")
