"""herdr_place.py in a Paseo-hosted agent (djbclark, 2026-10-30): /autorename all is not supported there, and
nothing touches herdr, even when the daemon was started from a herdr pane and passed HERDR_ENV/HERDR_PANE_ID down."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "skills/autorename/herdr_place.py"


def run(tmp_path: Path, *args: str, paseo: bool = True) -> tuple[subprocess.CompletedProcess, list[str]]:
    log = tmp_path / "herdr.log"
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    herdr = bindir / "herdr"
    herdr.write_text(f'#!/bin/sh\necho "$@" >> {log}\necho "{{}}"\n')
    herdr.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PASEO_", "HERDR_"))}
    env.update(PATH=f"{bindir}{os.pathsep}{env.get('PATH', '')}", HOME=str(tmp_path),
               HERDR_ENV="1", HERDR_PANE_ID="w1:p1", AUTORENAME_WORKSPACES=str(tmp_path / "none.conf"))
    if paseo:
        env["PASEO_AGENT_ID"] = "abc"
    r = subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=30)
    return r, (log.read_text().splitlines() if log.exists() else [])


def test_all_pass_is_refused_in_paseo(tmp_path: Path) -> None:
    r, calls = run(tmp_path, "config")
    assert r.returncode == 2 and "autorename all is not yet supported in Paseo" in r.stderr
    assert r.stdout == "" and calls == []


def test_all_pass_still_runs_in_herdr(tmp_path: Path) -> None:
    r, _ = run(tmp_path, "config", paseo=False)
    assert r.returncode == 0 and "workspaces" in json.loads(r.stdout)


@pytest.mark.parametrize(("args", "rc", "stream", "text"), [
    (("label", "x-t", "--force"), 0, "stdout", "skipped: not in a herdr pane"),
    (("check",), 0, "stdout", '"in_herdr": false'),
    (("move", "--workspace", "w2", "--tab-label", "x-t"), 1, "stderr", "not in a herdr pane (Paseo-hosted)"),
])
def test_a_leaked_herdr_environment_never_reaches_herdr(tmp_path: Path, args: tuple[str, ...], rc: int,
                                                       stream: str, text: str) -> None:
    r, calls = run(tmp_path, *args)
    assert r.returncode == rc and text in getattr(r, stream)
    assert calls == []
