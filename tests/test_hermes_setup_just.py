"""Smoke for just hermes-setup arg forwarding (PR #458 Codex P1).

Without Just's [positional-arguments] on the shebang recipe, *args never reach
$@, so --self / --help always fall through to the AI path.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
JUSTFILE = REPO / "justfile"
JUST = shutil.which("just")


def test_hermes_setup_declares_positional_arguments():
    text = JUSTFILE.read_text()
    assert re.search(
        r"(?m)^\[positional-arguments\]\s*\nhermes-setup \*args:",
        text,
    ), "hermes-setup shebang recipe needs [positional-arguments] so $@ gets --self/--help"


@pytest.mark.skipif(JUST is None, reason="just not on PATH")
def test_hermes_setup_help_and_self_forward_args():
    help_run = subprocess.run(
        [JUST, "hermes-setup", "--help"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert help_run.returncode == 0, help_run.stderr
    assert "Usage: just hermes-setup [--self]" in help_run.stdout

    self_run = subprocess.run(
        [JUST, "hermes-setup", "--self"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert self_run.returncode == 0, self_run.stderr
    assert "## DIY checklist" in self_run.stdout
    assert "claude not on PATH" not in self_run.stderr


def test_install_recipe_offers_three_hermes_paths():
    """just install asks skip/self/ai and records through ade-install hermes-choice."""
    text = JUSTFILE.read_text()
    body = text.split("install *args:", 1)[1].split("\nupdate *args:", 1)[0]
    for choice in ("skip", "self", "ai"):
        assert choice in body
    assert "hermes-choice" in body
    assert "hermes-setup --self" in body
    assert 'exec just --justfile "${root}/justfile" hermes-setup\n' in body
    # No tty and no ADE_HERMES_CHOICE: nothing is recorded, apply still runs.
    assert "ADE_HERMES_CHOICE" in body
    assert "-t 0" in body
