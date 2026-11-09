"""bin/ade-merge-ready classifies open PRs against the merge gate (read-only)."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "ade-merge-ready"


def write_fake_gh(tmp: Path, script: str) -> Path:
    path = tmp / "gh"
    path.write_text("#!/usr/bin/env bash\n" + script)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def run(gh: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--gh", str(gh), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_needs_approve_when_tests_pass_without_live_marker(tmp_path: Path) -> None:
    head = "a" * 40
    listing = json.dumps(
        [
            {
                "number": 327,
                "title": "wave6 checklist",
                "headRefOid": head,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/wave6-checklist-f576",
            }
        ]
    )
    checks = "pytest-linux\tpass\t0\thttps://example\nadversary-marker\tfail\t0\thttps://example\n"
    view = json.dumps({"body": "no marker", "comments": []})
    gh = write_fake_gh(
        tmp_path,
        textwrap.dedent(
            f"""
            set -e
            case "$*" in
              *"pr list"*) echo '{listing}' ;;
              *"pr checks"*) printf '%s' '{checks}' ; exit 1 ;;
              *"pr view"*) echo '{view}' ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(gh, "--json", "--min", "300")
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)
    assert len(rows) == 1
    assert rows[0]["class"] == "needs_approve"
    assert rows[0]["live_approve"] is False
    assert head in rows[0]["marker_template"]


def test_merge_now_when_live_approve_and_gates_green(tmp_path: Path) -> None:
    head = "b" * 40
    marker = f'<!-- adversary-verdict:v1 {{"verdict":"APPROVE","head":"{head}"}} -->'
    listing = json.dumps(
        [
            {
                "number": 340,
                "title": "deadline paseo",
                "headRefOid": head,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/wave6-deadline-paseo-f576",
            }
        ]
    )
    checks = "pytest-linux\tpass\t0\tx\nadversary-marker\tpass\t0\tx\n"
    view = json.dumps({"body": marker, "comments": []})
    gh = write_fake_gh(
        tmp_path,
        textwrap.dedent(
            f"""
            set -e
            case "$*" in
              *"pr list"*) echo '{listing}' ;;
              *"pr checks"*) printf '%s' '{checks}' ;;
              *"pr view"*) echo '{view}' ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(gh, "--json", "--min", "300")
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)
    assert rows[0]["class"] == "merge_now"
    assert rows[0]["live_approve"] is True


def test_parse_approves_ignores_non_forty_hex() -> None:
    import runpy

    mod = runpy.run_path(str(SCRIPT), run_name="ade_merge_ready")
    text = '<!-- adversary-verdict:v1 {"verdict":"APPROVE","head":"abc1234"} -->'
    assert mod["parse_approves"](text) == []
    full = "c" * 40
    ok = f'<!-- adversary-verdict:v1 {{"verdict":"APPROVE","head":"{full}"}} -->'
    assert mod["parse_approves"](ok) == [full]
