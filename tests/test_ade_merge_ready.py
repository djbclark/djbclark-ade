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


def test_merge_now_when_adversary_marker_pass(tmp_path: Path) -> None:
    """live_approve follows adversary-marker (attribution-aware), not a raw body marker."""
    head = "b" * 40
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
    gh = write_fake_gh(
        tmp_path,
        textwrap.dedent(
            f"""
            set -e
            case "$*" in
              *"pr list"*) echo '{listing}' ;;
              *"pr checks"*) printf '%s' '{checks}' ;;
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


def test_raw_body_approve_alone_is_not_live(tmp_path: Path) -> None:
    head = "d" * 40
    marker = f'<!-- adversary-verdict:v1 {{"verdict":"APPROVE","head":"{head}"}} -->'
    listing = json.dumps(
        [
            {
                "number": 341,
                "title": "outside approve noise",
                "headRefOid": head,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/noise-f576",
            }
        ]
    )
    checks = "pytest-linux\tpass\t0\tx\nadversary-marker\tfail\t0\tx\n"
    view = json.dumps({"body": marker, "comments": []})
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
    assert rows[0]["class"] == "needs_approve"
    assert rows[0]["live_approve"] is False


def test_parse_approves_ignores_non_forty_hex() -> None:
    import runpy

    mod = runpy.run_path(str(SCRIPT), run_name="ade_merge_ready")
    text = '<!-- adversary-verdict:v1 {"verdict":"APPROVE","head":"abc1234"} -->'
    assert mod["parse_approves"](text) == []
    full = "c" * 40
    ok = f'<!-- adversary-verdict:v1 {{"verdict":"APPROVE","head":"{full}"}} -->'
    assert mod["parse_approves"](ok) == [full]


def _row(
    number: int,
    *,
    branch: str,
    base: str,
    title: str,
    head: str | None = None,
) -> dict:
    h = head or (f"{number:040x}")
    return {
        "number": number,
        "title": title,
        "head": h,
        "base": base,
        "branch": branch,
        "mergeable": "MERGEABLE",
        "pytest_linux": "pass",
        "adversary_marker": "fail",
        "live_approve": False,
        "class": "needs_approve",
        "marker_template": (
            f'<!-- adversary-verdict:v1 {{"verdict":"APPROVE","head":"{h}"}} -->'
        ),
    }


def test_bottom_up_order_claims_and_s1_chains() -> None:
    import runpy

    mod = runpy.run_path(str(SCRIPT), run_name="ade_merge_ready")
    rows = [
        _row(336, branch="cursor/ade-claim-plugin-f576", base="master", title="ade-claim plugin"),
        _row(
            355,
            branch="cursor/ade-claim-w3-owner-f576",
            base="cursor/ade-claim-plugin-f576",
            title="ade-claim W3",
        ),
        _row(
            357,
            branch="cursor/ade-claim-w4-path-f576",
            base="cursor/ade-claim-w3-owner-f576",
            title="ade-claim W4",
        ),
        _row(
            381,
            branch="cursor/ade-claim-w2-release-f576",
            base="cursor/ade-claim-w4-path-f576",
            title="ade-claim W2",
        ),
        _row(332, branch="cursor/s1-gates-effective-f576", base="master", title="S1 gates"),
        _row(
            356,
            branch="cursor/s1-route-effective-f576",
            base="cursor/s1-gates-effective-f576",
            title="S1 route",
        ),
        _row(
            392,
            branch="cursor/s1-secret-pr-effective-f576",
            base="cursor/s1-route-effective-f576",
            title="S1 secret",
        ),
        _row(327, branch="cursor/wave6-checklist-f576", base="master", title="Wave 6 checklist"),
        _row(
            328,
            branch="cursor/wave6-fanout-paseo-f576",
            base="cursor/wave6-checklist-f576",
            title="Wave 6 fan-out",
        ),
        _row(
            351,
            branch="cursor/wave6-gates-doc-paseo-f576",
            base="cursor/s1-gates-effective-f576",
            title="docs(gates): Wave 6 Choice.dispatch",
        ),
        _row(334, branch="cursor/ade-install-harddeps-f576", base="master", title="ade-install hard"),
        _row(
            341,
            branch="cursor/ade-install-optionals-f576",
            base="cursor/ade-install-harddeps-f576",
            title="ade-install optionals",
        ),
    ]
    stacks = mod["build_named_stacks"](rows)
    by_group = {s["group"]: s for s in stacks}

    claims = [r["number"] for r in by_group["claims"]["order"]]
    assert claims == [336, 355, 357, 381]

    s1 = [r["number"] for r in by_group["s1"]["order"]]
    assert s1 == [332, 356, 392]

    install = [r["number"] for r in by_group["install"]["order"]]
    assert install == [334, 341]

    # Default all-groups view: wave6 bottoms only (group members whose open
    # parent is outside the wave6 set — not the non-wave6 ancestor itself).
    assert by_group["wave6"]["bottoms_only"] is True
    wave6 = [r["number"] for r in by_group["wave6"]["order"]]
    assert wave6 == [327, 351]
    assert 332 not in wave6


def test_stacks_cli_json_group_claims(tmp_path: Path) -> None:
    head_a = "a" * 40
    head_b = "b" * 40
    listing = json.dumps(
        [
            {
                "number": 336,
                "title": "ade-claim plugin",
                "headRefOid": head_a,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/ade-claim-plugin-f576",
            },
            {
                "number": 355,
                "title": "ade-claim W3",
                "headRefOid": head_b,
                "baseRefName": "cursor/ade-claim-plugin-f576",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/ade-claim-w3-owner-f576",
            },
        ]
    )
    checks = "pytest-linux\tpass\t0\tx\nadversary-marker\tfail\t0\tx\n"
    gh = write_fake_gh(
        tmp_path,
        textwrap.dedent(
            f"""
            set -e
            case "$*" in
              *"pr list"*) echo '{listing}' ;;
              *"pr checks"*) printf '%s' '{checks}' ; exit 1 ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(gh, "stacks", "--group", "claims", "--json", "--min", "300")
    assert r.returncode == 0, r.stderr
    stacks = json.loads(r.stdout)
    assert len(stacks) == 1
    assert stacks[0]["group"] == "claims"
    nums = [row["number"] for row in stacks[0]["order"]]
    assert nums == [336, 355]
    assert stacks[0]["order"][0]["head"] == head_a
    assert head_a in stacks[0]["order"][0]["marker_template"]
