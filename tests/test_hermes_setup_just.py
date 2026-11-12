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


@pytest.mark.skipif(JUST is None, reason="just not on PATH")
@pytest.mark.parametrize("choice,live", [("skip", True), ("self", True), ("ai", True), ("ai", False)])
def test_install_executes_choice_with_literal_args(tmp_path, choice, live):
    import json
    import os
    import sys
    text = JUSTFILE.read_text()
    recipe = text.split("[positional-arguments]\ninstall ", 1)[1].split("\nupdate ", 1)[0]
    (tmp_path / "justfile").write_text(
        'root := justfile_directory()\n[positional-arguments]\ninstall ' + recipe
        + '\n[positional-arguments]\nhermes-setup *args:\n    #!/usr/bin/env python3\n    import json, os, sys\n'
        + '    with open(os.environ["CAPTURE"], "a") as f: f.write(json.dumps(["setup", *sys.argv[1:]]) + "\\n")\n'
    )
    (tmp_path / "bin").mkdir()
    tool = tmp_path / "bin/ade-install"
    tool.write_text("#!" + sys.executable + '\nimport json, os, sys\n'
                    + 'with open(os.environ["CAPTURE"], "a") as f: f.write(json.dumps(sys.argv[1:]) + "\\n")\n')
    tool.chmod(0o755)
    capture = tmp_path / "calls"
    args = ["--id", "hermes", "--state-dir", "path with spaces;echo unsafe"]
    if live:
        args.append("--yes")
    result = subprocess.run([shutil.which("just"), "install", *args], cwd=tmp_path,
                            env={**os.environ, "ADE_HERMES_CHOICE": choice, "CAPTURE": str(capture)},
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in capture.read_text().splitlines()]
    assert calls[0] == ["hermes-choice", choice, "--state-dir", "path with spaces;echo unsafe"]
    assert calls[1] == ["apply", "--root", str(tmp_path), *args]
    assert calls[2:] == ([] if choice == "skip" or not live else
                        [["setup", *(["--self"] if choice == "self" else [])]])


@pytest.mark.parametrize("recipe,args,choice", [
    ("doctor", [], ""),
    ("doctor", ["hermes"], ""),
    ("install", [], "skip"),
    ("install", ["--state-dir", "space path"], "skip"),
])
def test_empty_arrays_under_system_bash(tmp_path, recipe, args, choice):
    """Execute actual recipe bodies with /bin/bash, including stock macOS 3.2."""
    import json
    import os
    import sys
    text = JUSTFILE.read_text()
    signature = 'doctor component="":' if recipe == "doctor" else 'install *args:'
    body = text.split(signature + "\n", 1)[1].split("\n\n", 1)[0]
    lines = body.splitlines()
    script = "\n".join(line[4:] for line in lines[1:]).replace("{{ root }}", str(tmp_path))
    (tmp_path / "bin").mkdir()
    capture = tmp_path / "calls"
    tool = tmp_path / "bin/ade-install"
    tool.write_text("#!" + sys.executable + '\nimport json, os, sys\n'
                    + 'with open(os.environ["CAPTURE"], "a") as f: f.write(json.dumps(sys.argv[1:]) + "\\n")\n')
    tool.chmod(0o755)
    result = subprocess.run(["/bin/bash", "-c", script, recipe, *args],
                            env={**os.environ, "CAPTURE": str(capture), "ADE_HERMES_CHOICE": choice},
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in capture.read_text().splitlines()]
    if recipe == "doctor":
        assert calls == [["doctor", "--root", str(tmp_path), *(["--id", "hermes"] if args else [])]]
    else:
        assert calls == [["hermes-choice", choice, *args], ["apply", "--root", str(tmp_path), *args]]
