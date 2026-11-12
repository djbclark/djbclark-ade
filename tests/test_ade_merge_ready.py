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
    # The marker self-heal state file must never land in the real home directory.
    env = {**os.environ, "ADE_MERGE_READY_STATE": str(gh.parent / "marker-state.json")}
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--gh", str(gh), *args],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
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


LISTING_REPO = "djbclark/djbclark-ade"
FORK_REPO = "outsider/djbclark-ade"


def _row(
    number: int,
    *,
    branch: str,
    base: str,
    title: str,
    head: str | None = None,
    head_repo: str = LISTING_REPO,
) -> dict:
    h = head or (f"{number:040x}")
    return {
        "number": number,
        "title": title,
        "head": h,
        "base": base,
        "branch": branch,
        "head_repo": head_repo,
        "listing_repo": LISTING_REPO,
        "mergeable": "MERGEABLE",
        "pytest_linux": "pass",
        "adversary_marker": "fail",
        "live_approve": False,
        "class": "needs_approve",
        "marker_template": (
            f'<!-- adversary-verdict:v1 {{"verdict":"APPROVE","head":"{h}"}} -->'
        ),
    }


def test_link_parents_ignores_fork_master_head() -> None:
    """A fork PR headed at master must not parent every PR targeting master."""
    import runpy

    mod = runpy.run_path(str(SCRIPT), run_name="ade_merge_ready")
    rows = [
        _row(
            99,
            branch="master",
            base="master",
            title="fork: master → master",
            head_repo=FORK_REPO,
        ),
        _row(336, branch="cursor/ade-claim-plugin-f576", base="master", title="same-repo tip"),
        _row(
            355,
            branch="cursor/ade-claim-w3-owner-f576",
            base="cursor/ade-claim-plugin-f576",
            title="stacked child",
        ),
    ]
    linked = mod["link_parents"](rows, listing_repo=LISTING_REPO)
    by_n = {r["number"]: r for r in linked}
    assert by_n[336]["parent_number"] is None
    assert by_n[99]["parent_number"] is None
    assert by_n[355]["parent_number"] == 336


def test_link_parents_ambiguous_same_repo_head_is_fail_safe() -> None:
    """Two open same-repo PRs sharing a headRefName → no guessed parent."""
    import runpy

    mod = runpy.run_path(str(SCRIPT), run_name="ade_merge_ready")
    rows = [
        _row(10, branch="cursor/shared-f576", base="master", title="dup A"),
        _row(11, branch="cursor/shared-f576", base="master", title="dup B"),
        _row(
            12,
            branch="cursor/child-f576",
            base="cursor/shared-f576",
            title="child of ambiguous",
        ),
    ]
    linked = mod["link_parents"](rows, listing_repo=LISTING_REPO)
    by_n = {r["number"]: r for r in linked}
    assert by_n[12]["parent_number"] is None
    assert by_n[10]["parent_number"] is None
    assert by_n[11]["parent_number"] is None


def test_head_repository_nwo_prefers_name_with_owner() -> None:
    import runpy

    mod = runpy.run_path(str(SCRIPT), run_name="ade_merge_ready")
    nwo = mod["head_repository_nwo"]
    assert (
        nwo(
            {
                "headRepository": {"nameWithOwner": "djbclark/djbclark-ade", "name": "x"},
                "headRepositoryOwner": {"login": "other"},
            },
            LISTING_REPO,
        )
        == LISTING_REPO
    )
    assert (
        nwo(
            {
                "headRepository": {"name": "djbclark-ade"},
                "headRepositoryOwner": {"login": "outsider"},
                "isCrossRepository": True,
            },
            LISTING_REPO,
        )
        == FORK_REPO
    )
    assert (
        nwo({"isCrossRepository": True}, LISTING_REPO) == ""
    )
    assert nwo({}, LISTING_REPO) == LISTING_REPO


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
    stacks = mod["build_named_stacks"](rows, listing_repo=LISTING_REPO)
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
                "headRepository": {"nameWithOwner": LISTING_REPO, "name": "djbclark-ade"},
                "headRepositoryOwner": {"login": "djbclark"},
                "isCrossRepository": False,
            },
            {
                "number": 355,
                "title": "ade-claim W3",
                "headRefOid": head_b,
                "baseRefName": "cursor/ade-claim-plugin-f576",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/ade-claim-w3-owner-f576",
                "headRepository": {"nameWithOwner": LISTING_REPO, "name": "djbclark-ade"},
                "headRepositoryOwner": {"login": "djbclark"},
                "isCrossRepository": False,
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
    assert stacks[0]["order"][1]["parent_number"] == 336


def test_stacks_cli_fork_master_does_not_parent_listing_tips(tmp_path: Path) -> None:
    head_fork = "f" * 40
    head_tip = "a" * 40
    listing = json.dumps(
        [
            {
                "number": 50,
                "title": "outsider fork onto master",
                "headRefOid": head_fork,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "master",
                "headRepository": {"nameWithOwner": FORK_REPO, "name": "djbclark-ade"},
                "headRepositoryOwner": {"login": "outsider"},
                "isCrossRepository": True,
            },
            {
                "number": 336,
                "title": "ade-claim plugin",
                "headRefOid": head_tip,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/ade-claim-plugin-f576",
                "headRepository": {"nameWithOwner": LISTING_REPO, "name": "djbclark-ade"},
                "headRepositoryOwner": {"login": "djbclark"},
                "isCrossRepository": False,
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
    r = run(gh, "stacks", "--group", "claims", "--json", "--min", "1")
    assert r.returncode == 0, r.stderr
    stacks = json.loads(r.stdout)
    assert len(stacks) == 1
    order = stacks[0]["order"]
    assert [row["number"] for row in order] == [336]
    assert order[0]["parent_number"] is None
    assert order[0]["head_repo"] == LISTING_REPO


def test_approve_paste_master_base_only(tmp_path: Path) -> None:
    """approve-paste --base master emits only matching needs_approve templates."""
    head_m = "c" * 40
    head_s = "d" * 40
    listing = json.dumps(
        [
            {
                "number": 334,
                "title": "install harddeps",
                "headRefOid": head_m,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/ade-install-harddeps-f576",
            },
            {
                "number": 469,
                "title": "linux e2e",
                "headRefOid": head_s,
                "baseRefName": "cursor/doctor-linger-linux-f576",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/ade-install-linux-e2e-f576",
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
    r = run(gh, "approve-paste", "--base", "master", "--min", "1")
    assert r.returncode == 0, r.stderr
    assert "do not paste through herdr" in r.stdout
    assert "approve-post" in r.stdout
    assert "--via auto" in r.stdout
    assert "# PR 334" in r.stdout
    assert head_m in r.stdout
    assert "# PR 469" not in r.stdout
    assert head_s not in r.stdout


def test_approve_post_dry_run_as_owner(tmp_path: Path) -> None:
    """approve-post dry-run posts nothing; owner tip uses body via auto."""
    head = "e" * 40
    listing = json.dumps(
        [
            {
                "number": 334,
                "title": "install harddeps",
                "headRefOid": head,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/ade-install-harddeps-f576",
                "author": {"login": "djbclark"},
            }
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
              *"api user"*) echo djbclark ;;
              *"repo view"*) echo djbclark ;;
              *"pr comment"*) echo "unexpected post: $*" >&2; exit 99 ;;
              *"pr view"*) echo "unexpected view: $*" >&2; exit 99 ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(gh, "approve-post", "--prs", "334", "--min", "1")
    assert r.returncode == 0, r.stderr
    assert "dry-run" in r.stdout
    assert head in r.stdout
    assert "would body-edit #334" in r.stdout


def test_approve_post_yes_requires_i_reviewed(tmp_path: Path) -> None:
    head = "f" * 40
    listing = json.dumps(
        [
            {
                "number": 334,
                "title": "install harddeps",
                "headRefOid": head,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/ade-install-harddeps-f576",
            }
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
    r = run(gh, "approve-post", "--yes", "--prs", "334", "--min", "1")
    assert r.returncode == 2
    assert "i-reviewed" in r.stderr


def test_approve_post_refuses_non_owner(tmp_path: Path) -> None:
    head = "a1" + "b" * 38
    listing = json.dumps(
        [
            {
                "number": 334,
                "title": "install harddeps",
                "headRefOid": head,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/ade-install-harddeps-f576",
            }
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
              *"api user"*) echo cursor-bot ;;
              *"repo view"*) echo djbclark ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(
        gh,
        "approve-post",
        "--i-reviewed",
        "--yes",
        "--prs",
        "334",
        "--min",
        "1",
    )
    assert r.returncode == 2
    assert "not repo owner" in r.stderr


def test_approve_post_yes_posts_comment_for_outside(tmp_path: Path) -> None:
    head = "c" * 40
    listing = json.dumps(
        [
            {
                "number": 334,
                "title": "outside tip",
                "headRefOid": head,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/outside-f576",
                "author": {"login": "stranger"},
            }
        ]
    )
    checks = "pytest-linux\tpass\t0\tx\nadversary-marker\tfail\t0\tx\n"
    log = tmp_path / "posts.log"
    gh = write_fake_gh(
        tmp_path,
        textwrap.dedent(
            f"""
            set -e
            case "$*" in
              *"pr list"*) echo '{listing}' ;;
              *"pr checks"*) printf '%s' '{checks}' ; exit 1 ;;
              *"api user"*) echo djbclark ;;
              *"repo view"*) echo djbclark ;;
              *"pr comment"*)
                echo "$*" >> '{log}'
                exit 0
                ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(
        gh,
        "approve-post",
        "--i-reviewed",
        "--yes",
        "--prs",
        "334",
        "--expect-head",
        f"334={head}",
        "--min",
        "1",
    )
    assert r.returncode == 0, r.stderr
    assert "commented #334" in r.stdout
    posted = log.read_text()
    assert "pr comment 334" in posted
    assert head in posted
    assert "adversary-verdict:v1" in posted


def test_approve_post_yes_body_edits_owner_pr(tmp_path: Path) -> None:
    head = "d" * 40
    listing = json.dumps(
        [
            {
                "number": 484,
                "title": "owner trust",
                "headRefOid": head,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/adversary-owner-trust-f576",
                "author": {"login": "djbclark"},
            }
        ]
    )
    checks = "pytest-linux\tpass\t0\tx\nadversary-marker\tfail\t0\tx\n"
    log = tmp_path / "patch.log"
    gh = write_fake_gh(
        tmp_path,
        textwrap.dedent(
            f"""
            set -e
            case "$*" in
              *"pr list"*) echo '{listing}' ;;
              *"pr checks"*) printf '%s' '{checks}' ; exit 1 ;;
              *"api user"*) echo djbclark ;;
              *"repo view"*) echo djbclark ;;
              *"pr view"*) echo '{{"body":"## Summary\\n"}}' ;;
              *"api"*"PATCH"*|*"pulls/484"*)
                cat >> '{log}'
                echo '{{"number":484}}'
                exit 0
                ;;
              *"pr comment"*) echo "unexpected comment: $*" >&2; exit 99 ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(
        gh,
        "approve-post",
        "--i-reviewed",
        "--yes",
        "--prs",
        "484",
        "--expect-head",
        f"484={head}",
        "--min",
        "1",
    )
    assert r.returncode == 0, r.stderr
    assert "body-edited #484" in r.stdout
    patched = log.read_text()
    assert head in patched
    assert "adversary-verdict:v1" in patched


def test_approve_post_yes_requires_expect_head(tmp_path: Path) -> None:
    head = "e" * 40
    listing = json.dumps(
        [
            {
                "number": 334,
                "title": "install",
                "headRefOid": head,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/x-f576",
                "author": {"login": "djbclark"},
            }
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
              *"api user"*) echo djbclark ;;
              *"repo view"*) echo djbclark ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(
        gh,
        "approve-post",
        "--i-reviewed",
        "--yes",
        "--prs",
        "334",
        "--min",
        "1",
    )
    assert r.returncode == 2
    assert "expect-head" in r.stderr


def test_approve_post_yes_refuses_moved_head(tmp_path: Path) -> None:
    live = "a" * 40
    reviewed = "b" * 40
    listing = json.dumps(
        [
            {
                "number": 334,
                "title": "install",
                "headRefOid": live,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/x-f576",
                "author": {"login": "djbclark"},
            }
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
              *"api user"*) echo djbclark ;;
              *"repo view"*) echo djbclark ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(
        gh,
        "approve-post",
        "--i-reviewed",
        "--yes",
        "--prs",
        "334",
        "--expect-head",
        f"334={reviewed}",
        "--min",
        "1",
    )
    assert r.returncode == 2
    assert "live head" in r.stderr
    assert "tip moved" in r.stderr


def test_collect_refuses_silent_500_truncation(tmp_path: Path) -> None:
    """If gh returns exactly 500 open PRs, refuse rather than drop bottoms."""
    prs = [
        {
            "number": 1000 + i,
            "title": f"pr{i}",
            "headRefOid": f"{i:040x}",
            "baseRefName": "master",
            "mergeable": "MERGEABLE",
            "headRefName": f"cursor/x-{i}-f576",
        }
        for i in range(500)
    ]
    listing = json.dumps(prs)
    gh = write_fake_gh(
        tmp_path,
        textwrap.dedent(
            f"""
            set -e
            case "$*" in
              *"pr list"*) echo '{listing}' ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(gh, "--json", "--min", "1")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "500" in (r.stderr + r.stdout)


def test_merge_now_refuses_without_adversary_success(tmp_path: Path) -> None:
    head = "1" * 40
    listing = json.dumps(
        [
            {
                "number": 481,
                "title": "docs",
                "headRefOid": head,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/x-f576",
                "author": {"login": "djbclark"},
            }
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
              *"repo view"*) echo djbclark ;;
              *"pr merge"*) echo "unexpected merge: $*" >&2; exit 99 ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(gh, "merge-now", "--prs", "481", "--yes", "--min", "1")
    assert r.returncode == 2
    assert "refuse merge" in r.stderr
    assert "merge_now" in r.stderr


def test_merge_now_dry_run_when_green(tmp_path: Path) -> None:
    head = "2" * 40
    listing = json.dumps(
        [
            {
                "number": 484,
                "title": "owner trust",
                "headRefOid": head,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/adversary-owner-trust-f576",
                "author": {"login": "djbclark"},
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
              *"repo view"*) echo djbclark ;;
              *"pr merge"*) echo "unexpected merge: $*" >&2; exit 99 ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(gh, "merge-now", "--prs", "484", "--min", "1")
    assert r.returncode == 0, r.stderr
    assert f"would merge #484 --squash --match-head-commit {head}" in r.stdout

def test_merge_now_falls_back_to_merge_async_for_stacked_prs(tmp_path: Path) -> None:
    head = "3" * 40
    listing = json.dumps(
        [
            {
                "number": 474,
                "title": "approve-paste",
                "headRefOid": head,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/ade-merge-ready-approve-paste-f576",
                "author": {"login": "djbclark"},
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
              *"repo view"*) echo djbclark ;;
              *"pr merge"*)
                echo 'GraphQL: This pull request is part of a stack and must be merged using the asynchronous merge REST API.' >&2
                exit 1
                ;;
              *"merge-async/"*)
                echo '{{"status":"merged","details":{{"message":"ok"}}}}'
                ;;
              *"merge-async"*)
                echo '{{"status":"pending","details":{{"uuid":"u-1","merge_method":"squash","expected_head_sha":"{head}"}}}}'
                ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(gh, "merge-now", "--prs", "474", "--yes", "--min", "1")
    assert r.returncode == 0, r.stderr
    assert f"merged #474 squash head={head}" in r.stdout


def test_retrigger_marker_refuses_bare_invoke(tmp_path: Path) -> None:
    head = "a" * 40
    listing = json.dumps(
        [
            {
                "number": 327,
                "title": "tip",
                "headRefOid": head,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/tip-f576",
                "author": {"login": "djbclark"},
            }
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
              *"repo view"*) echo djbclark ;;
              *"workflow run"*) echo "unexpected fire: $*" >&2; exit 99 ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(gh, "retrigger-marker", "--min", "1")
    assert r.returncode == 2
    assert "--prs" in r.stderr
    assert "--class" in r.stderr


def test_retrigger_marker_dry_run_class_needs_approve(tmp_path: Path) -> None:
    """Dry-run lists workflow runs; never invents APPROVE; never merges."""
    head_a = "a" * 40
    head_b = "b" * 40
    listing = json.dumps(
        [
            {
                "number": 327,
                "title": "needs approve tip",
                "headRefOid": head_a,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/needs-f576",
                "author": {"login": "djbclark"},
            },
            {
                "number": 328,
                "title": "already green",
                "headRefOid": head_b,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/green-f576",
                "author": {"login": "djbclark"},
            },
        ]
    )
    gh = write_fake_gh(
        tmp_path,
        textwrap.dedent(
            f"""
            set -e
            case "$*" in
              *"pr list"*) echo '{listing}' ;;
              *"pr checks 328"*) printf '%s' 'pytest-linux\tpass\t0\tx\nadversary-marker\tpass\t0\tx\n' ;;
              *"pr checks"*) printf '%s' 'pytest-linux\tpass\t0\tx\nadversary-marker\tfail\t0\tx\n' ; exit 1 ;;
              *"repo view"*) echo djbclark ;;
              *"workflow run"*) echo "unexpected fire: $*" >&2; exit 99 ;;
              *"pr merge"*) echo "unexpected merge: $*" >&2; exit 99 ;;
              *"pr comment"*) echo "unexpected comment: $*" >&2; exit 99 ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(
        gh,
        "retrigger-marker",
        "--class",
        "needs_approve",
        "--min",
        "1",
        "--json",
    )
    assert r.returncode == 0, r.stderr
    assert "would trigger adversary-marker.yml pr=327" in r.stderr
    assert "pr=328" not in r.stderr
    assert "APPROVE" not in r.stdout
    assert "APPROVE" not in r.stderr
    payload = json.loads(r.stdout)
    assert payload["dry_run"] is True
    assert payload["triggered"] == [327]
    assert payload["class"] == "needs_approve"


def test_retrigger_marker_yes_fires_workflow(tmp_path: Path) -> None:
    head = "c" * 40
    listing = json.dumps(
        [
            {
                "number": 359,
                "title": "bottom tip",
                "headRefOid": head,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/bottom-f576",
                "author": {"login": "djbclark"},
            }
        ]
    )
    checks = "pytest-linux\tpass\t0\tx\nadversary-marker\tfail\t0\tx\n"
    log = tmp_path / "workflow.log"
    gh = write_fake_gh(
        tmp_path,
        textwrap.dedent(
            f"""
            set -e
            case "$*" in
              *"pr list"*) echo '{listing}' ;;
              *"pr checks"*) printf '%s' '{checks}' ; exit 1 ;;
              *"repo view"*) echo djbclark ;;
              *"workflow run"*adversary-marker.yml*"-f"*"pr=359"*)
                echo "$*" >> '{log}'
                ;;
              *"pr merge"*) echo "unexpected merge: $*" >&2; exit 99 ;;
              *"pr comment"*) echo "unexpected comment: $*" >&2; exit 99 ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(gh, "retrigger-marker", "--prs", "359", "--yes", "--min", "1")
    assert r.returncode == 0, r.stderr
    assert "triggered adversary-marker.yml pr=359" in r.stdout
    assert "APPROVE" not in r.stdout
    assert log.exists()
    assert "adversary-marker.yml" in log.read_text()
    assert "pr=359" in log.read_text()


def test_retrigger_marker_bottoms_only(tmp_path: Path) -> None:
    """--bottoms-only keeps stack bottoms; child tips are skipped."""
    head_p = "d" * 40
    head_c = "e" * 40
    listing = json.dumps(
        [
            {
                "number": 400,
                "title": "parent bottom",
                "headRefOid": head_p,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/parent-f576",
                "author": {"login": "djbclark"},
            },
            {
                "number": 401,
                "title": "child tip",
                "headRefOid": head_c,
                "baseRefName": "cursor/parent-f576",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/child-f576",
                "author": {"login": "djbclark"},
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
              *"repo view"*) echo djbclark ;;
              *"workflow run"*) echo "unexpected fire: $*" >&2; exit 99 ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(
        gh,
        "retrigger-marker",
        "--bottoms-only",
        "--class",
        "needs_approve",
        "--min",
        "1",
    )
    assert r.returncode == 0, r.stderr
    assert "would trigger adversary-marker.yml pr=400" in r.stdout
    assert "pr=401" not in r.stdout


def test_stack_rebase_requires_prs(tmp_path: Path) -> None:
    listing = json.dumps(
        [
            {
                "number": 500,
                "title": "child",
                "headRefOid": "a" * 40,
                "baseRefName": "cursor/parent-f576",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/child-f576",
                "author": {"login": "djbclark"},
            }
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
              *"pr checks"*) printf '%s' '{checks}' ;;
              *"repo view"*) echo djbclark ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(gh, "stack-rebase", "--min", "1")
    assert r.returncode == 2, r.stderr
    assert "requires --prs" in r.stderr


def test_stack_rebase_dry_run_parent_gone(tmp_path: Path) -> None:
    head = "b" * 40
    listing = json.dumps(
        [
            {
                "number": 511,
                "title": "orphan child after bottom merged",
                "headRefOid": head,
                "baseRefName": "cursor/gone-parent-f576",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/sched-cron-reconcile-f576",
                "author": {"login": "djbclark"},
                "headRepository": {"nameWithOwner": "djbclark/djbclark-ade"},
            }
        ]
    )
    checks = "pytest-linux\tpending\t0\tx\nadversary-marker\tfail\t0\tx\n"
    gh = write_fake_gh(
        tmp_path,
        textwrap.dedent(
            f"""
            set -e
            case "$*" in
              *"pr list"*) echo '{listing}' ;;
              *"pr checks"*) printf '%s' '{checks}' ;;
              *"repo view"*) echo djbclark ;;
              *"pr edit"*) echo "unexpected edit: $*" >&2; exit 99 ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(gh, "stack-rebase", "--prs", "511", "--min", "1", "--json")
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["dry_run"] is True
    assert data["onto"] == "master"
    assert len(data["results"]) == 1
    res = data["results"][0]
    assert res["status"] == "would-rebase"
    assert res["onto"] == "master"
    assert res["need_base_edit"] is True
    assert res["reason"] == "parent_gone"
    assert res["upstream_exclude"] == "cursor/gone-parent-f576"
    assert "would rebase #511" in r.stderr
    assert "exclude cursor/gone-parent-f576" in r.stderr


def test_stack_rebase_dry_run_open_parent(tmp_path: Path) -> None:
    head_p = "c" * 40
    head_c = "d" * 40
    listing = json.dumps(
        [
            {
                "number": 500,
                "title": "parent",
                "headRefOid": head_p,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/parent-f576",
                "author": {"login": "djbclark"},
                "headRepository": {"nameWithOwner": "djbclark/djbclark-ade"},
            },
            {
                "number": 501,
                "title": "child",
                "headRefOid": head_c,
                "baseRefName": "cursor/parent-f576",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/child-f576",
                "author": {"login": "djbclark"},
                "headRepository": {"nameWithOwner": "djbclark/djbclark-ade"},
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
              *"pr checks"*) printf '%s' '{checks}' ;;
              *"repo view"*) echo djbclark ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(gh, "stack-rebase", "--prs", "501", "--min", "1", "--json")
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    res = data["results"][0]
    assert res["onto"] == "cursor/parent-f576"
    assert res["need_base_edit"] is False
    assert res["reason"] == "open_parent"
    assert res["status"] == "would-rebase"


def test_stack_rebase_yes_requires_repo_dir(tmp_path: Path) -> None:
    listing = json.dumps(
        [
            {
                "number": 511,
                "title": "child",
                "headRefOid": "e" * 40,
                "baseRefName": "cursor/gone-f576",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/child-f576",
                "author": {"login": "djbclark"},
                "headRepository": {"nameWithOwner": "djbclark/djbclark-ade"},
            }
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
              *"pr checks"*) printf '%s' '{checks}' ;;
              *"repo view"*) echo djbclark ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(gh, "stack-rebase", "--prs", "511", "--yes", "--min", "1")
    assert r.returncode == 2, r.stderr
    assert "--repo-dir" in r.stderr


def test_stack_rebase_yes_rebase_and_retarget(tmp_path: Path) -> None:
    head = "f" * 40
    listing = json.dumps(
        [
            {
                "number": 511,
                "title": "child",
                "headRefOid": head,
                "baseRefName": "cursor/gone-f576",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/child-f576",
                "author": {"login": "djbclark"},
                "headRepository": {"nameWithOwner": "djbclark/djbclark-ade"},
            }
        ]
    )
    checks = "pytest-linux\tpass\t0\tx\nadversary-marker\tfail\t0\tx\n"
    edits = tmp_path / "edits.log"
    gh = write_fake_gh(
        tmp_path,
        textwrap.dedent(
            f"""
            set -e
            case "$*" in
              *"pr list"*) echo '{listing}' ;;
              *"pr checks"*) printf '%s' '{checks}' ;;
              *"repo view"*) echo djbclark ;;
              *"pr edit"*)
                echo "$*" >> '{edits}'
                ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    git_log = tmp_path / "git.log"
    git = tmp_path / "git"
    git.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            echo "$*" >> '{git_log}'
            if [[ "$1" == fetch ]]; then exit 0; fi
            if [[ "$1" == worktree && "$2" == add ]]; then mkdir -p "$4"; exit 0; fi
            if [[ "$1" == worktree && "$2" == remove ]]; then exit 0; fi
            if [[ "$1" == rev-parse ]]; then echo deadbeef; exit 0; fi
            if [[ "$1" == rebase && "$2" == --abort ]]; then exit 0; fi
            if [[ "$1" == rebase && "$2" == --onto ]]; then exit 0; fi
            if [[ "$1" == rebase ]]; then echo "unexpected plain rebase: $*" >&2; exit 99; fi
            if [[ "$1" == push ]]; then exit 0; fi
            exit 0
            """
        )
    )
    git.chmod(git.stat().st_mode | stat.S_IXUSR)
    repo_dir = tmp_path / "clone"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()
    r = run(
        gh,
        "stack-rebase",
        "--prs",
        "511",
        "--yes",
        "--repo-dir",
        str(repo_dir),
        "--git",
        str(git),
        "--min",
        "1",
    )
    assert r.returncode == 0, r.stderr + r.stdout
    assert "rebased #511 cursor/child-f576 onto master (base retargeted)" in r.stdout
    assert edits.exists()
    assert "--base master" in edits.read_text()
    log = git_log.read_text()
    assert "push --force-with-lease" in log
    assert "rebase --onto origin/master origin/cursor/gone-f576" in log


def test_stack_rebase_yes_conflict_refuses(tmp_path: Path) -> None:
    head = "1" * 40
    listing = json.dumps(
        [
            {
                "number": 512,
                "title": "conflict child",
                "headRefOid": head,
                "baseRefName": "cursor/gone-f576",
                "mergeable": "CONFLICTING",
                "headRefName": "cursor/conflict-f576",
                "author": {"login": "djbclark"},
                "headRepository": {"nameWithOwner": "djbclark/djbclark-ade"},
            }
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
              *"pr checks"*) printf '%s' '{checks}' ;;
              *"repo view"*) echo djbclark ;;
              *"pr edit"*) echo "unexpected edit" >&2; exit 99 ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    git = tmp_path / "git"
    git.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            if [[ "$1" == fetch ]]; then exit 0; fi
            if [[ "$1" == worktree && "$2" == add ]]; then mkdir -p "$4"; exit 0; fi
            if [[ "$1" == worktree && "$2" == remove ]]; then exit 0; fi
            if [[ "$1" == rev-parse ]]; then echo deadbeef; exit 0; fi
            if [[ "$1" == rebase && "$2" == --abort ]]; then exit 0; fi
            if [[ "$1" == rebase && "$2" == --onto ]]; then
              echo "CONFLICT (content): merge conflict in x" >&2
              exit 1
            fi
            if [[ "$1" == rebase ]]; then echo "unexpected plain rebase" >&2; exit 99; fi
            if [[ "$1" == push ]]; then echo "unexpected push" >&2; exit 99; fi
            exit 0
            """
        )
    )
    git.chmod(git.stat().st_mode | stat.S_IXUSR)
    repo_dir = tmp_path / "clone"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()
    r = run(
        gh,
        "stack-rebase",
        "--prs",
        "512",
        "--yes",
        "--repo-dir",
        str(repo_dir),
        "--git",
        str(git),
        "--min",
        "1",
    )
    assert r.returncode == 1, r.stderr + r.stdout
    assert "refused #512: rebase conflict" in r.stdout


def test_stack_rebase_refuses_fork_head(tmp_path: Path) -> None:
    head = "a" * 40
    listing = json.dumps(
        [
            {
                "number": 600,
                "title": "fork child",
                "headRefOid": head,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/fork-child-f576",
                "author": {"login": "outsider"},
                "headRepository": {"nameWithOwner": "outsider/djbclark-ade"},
                "isCrossRepository": True,
            }
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
              *"pr checks"*) printf '%s' '{checks}' ;;
              *"repo view"*) echo djbclark ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(gh, "stack-rebase", "--prs", "600", "--min", "1", "--json")
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    res = data["results"][0]
    assert res["status"] == "would-refuse"
    assert res["reason"] == "cross_repo_head"
    assert "fork" in res["detail"] or "cross" in res["detail"]


def test_stack_rebase_align_onto_needs_upstream(tmp_path: Path) -> None:
    head = "b" * 40
    listing = json.dumps(
        [
            {
                "number": 601,
                "title": "retargeted child",
                "headRefOid": head,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "cursor/retargeted-f576",
                "author": {"login": "djbclark"},
                "headRepository": {"nameWithOwner": "djbclark/djbclark-ade"},
            }
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
              *"pr checks"*) printf '%s' '{checks}' ;;
              *"repo view"*) echo djbclark ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )
    r = run(gh, "stack-rebase", "--prs", "601", "--min", "1", "--json")
    assert r.returncode == 0, r.stderr + r.stdout
    res = json.loads(r.stdout)["results"][0]
    assert res["status"] == "would-refuse"
    assert res["reason"] == "align_onto_needs_upstream"


# --- marker self-heal (2026-11-12, PR #587 incident) ---------------------------------


def _heal_gh(
    tmp: Path,
    *,
    head: str,
    checks_tsv: str,
    completed_at: str,
    bucket: str = "pass",
    log: Path | None = None,
    view_head: str = "",
) -> Path:
    listing = json.dumps(
        [
            {
                "number": 587,
                "title": "advisory quota levels",
                "headRefOid": head,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "quota-levels",
            }
        ]
    )
    checks_json = json.dumps(
        [{"name": "pytest-linux", "bucket": bucket, "completedAt": completed_at}]
    )
    log = log or (tmp / "calls.log")
    return write_fake_gh(
        tmp,
        textwrap.dedent(
            f"""
            echo "$*" >> '{log}'
            case "$*" in
              *"pr list"*) echo '{listing}' ;;
              *"pr checks"*"--json"*) echo '{checks_json}' ;;
              *"pr checks"*) printf '%s' '{checks_tsv}' ;;
              *"pr view"*) echo '{{"headRefOid": "{view_head or head}"}}' ;;
              *"workflow run adversary-marker.yml"*"-f pr=587"*) echo dispatched ;;
              *) echo "unexpected: $*" >&2; exit 99 ;;
            esac
            """
        ),
    )


def _dispatch_calls(tmp: Path) -> list[str]:
    log = tmp / "calls.log"
    if not log.exists():
        return []
    return [ln for ln in log.read_text().splitlines() if "workflow run" in ln]


OLD_TS = "2026-11-12T10:00:00Z"
PASS_ONLY = "pytest-linux\tpass\t0\tx\n"


def test_missing_marker_check_is_dispatched_once_per_head(tmp_path: Path) -> None:
    head = "5" * 40
    gh = _heal_gh(tmp_path, head=head, checks_tsv=PASS_ONLY, completed_at=OLD_TS)
    r = run(gh, "--json", "--min", "500")
    assert r.returncode == 0, r.stderr
    rows = json.loads(r.stdout)
    assert rows[0]["class"] == "needs_approve"
    assert rows[0]["marker_dispatch"] == "dispatched"
    assert "marker-dispatch #587" in r.stderr
    assert len(_dispatch_calls(tmp_path)) == 1
    state = json.loads((tmp_path / "marker-state.json").read_text())
    assert f"djbclark/djbclark-ade#587@{head}" in state["dispatched"]
    # Second run for the same head: recorded, never repeated.
    r2 = run(gh, "--json", "--min", "500")
    assert json.loads(r2.stdout)[0]["marker_dispatch"] == "already_dispatched"
    assert len(_dispatch_calls(tmp_path)) == 1


def test_new_head_after_force_push_is_dispatched_again(tmp_path: Path) -> None:
    gh = _heal_gh(tmp_path, head="1" * 40, checks_tsv=PASS_ONLY, completed_at=OLD_TS)
    run(gh, "--json", "--min", "500")
    gh = _heal_gh(tmp_path, head="2" * 40, checks_tsv=PASS_ONLY, completed_at=OLD_TS)
    r = run(gh, "--json", "--min", "500")
    assert json.loads(r.stdout)[0]["marker_dispatch"] == "dispatched"
    assert len(_dispatch_calls(tmp_path)) == 2


def test_within_grace_waits_and_does_not_record(tmp_path: Path) -> None:
    import datetime as dt

    fresh = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    gh = _heal_gh(tmp_path, head="3" * 40, checks_tsv=PASS_ONLY, completed_at=fresh)
    r = run(gh, "--json", "--min", "500")
    assert json.loads(r.stdout)[0]["marker_dispatch"] == "waiting"
    assert _dispatch_calls(tmp_path) == []
    assert not (tmp_path / "marker-state.json").exists()
    # A zero grace dispatches immediately.
    r2 = run(gh, "--json", "--min", "500", "--marker-grace", "0")
    assert json.loads(r2.stdout)[0]["marker_dispatch"] == "dispatched"


@pytest.mark.parametrize("state", ["fail", "pending", "pass"])
def test_present_marker_check_is_never_dispatched(tmp_path: Path, state: str) -> None:
    tsv = PASS_ONLY + f"adversary-marker\t{state}\t0\tx\n"
    gh = _heal_gh(tmp_path, head="4" * 40, checks_tsv=tsv, completed_at=OLD_TS)
    r = run(gh, "--json", "--min", "500")
    assert r.returncode == 0, r.stderr
    assert "marker_dispatch" not in json.loads(r.stdout)[0]
    assert _dispatch_calls(tmp_path) == []


def test_failed_tests_never_dispatch(tmp_path: Path) -> None:
    gh = _heal_gh(
        tmp_path,
        head="6" * 40,
        checks_tsv="pytest-linux\tfail\t0\tx\n",
        completed_at=OLD_TS,
        bucket="fail",
    )
    r = run(gh, "--json", "--min", "500")
    assert json.loads(r.stdout)[0]["class"] == "tests_fail"
    assert _dispatch_calls(tmp_path) == []


def test_no_marker_dispatch_flag_disables_heal(tmp_path: Path) -> None:
    gh = _heal_gh(tmp_path, head="7" * 40, checks_tsv=PASS_ONLY, completed_at=OLD_TS)
    r = run(gh, "--json", "--min", "500", "--no-marker-dispatch")
    assert r.returncode == 0, r.stderr
    assert "marker_dispatch" not in json.loads(r.stdout)[0]
    assert _dispatch_calls(tmp_path) == []


def test_unparseable_completion_time_fails_closed(tmp_path: Path) -> None:
    gh = _heal_gh(tmp_path, head="8" * 40, checks_tsv=PASS_ONLY, completed_at="not-a-time")
    r = run(gh, "--json", "--min", "500")
    assert json.loads(r.stdout)[0]["marker_dispatch"] == "unknown_tests_time"
    assert _dispatch_calls(tmp_path) == []


def test_dispatch_failure_is_reported_and_not_recorded(tmp_path: Path) -> None:
    head = "9" * 40
    listing = json.dumps(
        [
            {
                "number": 587,
                "title": "t",
                "headRefOid": head,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": "b",
            }
        ]
    )
    checks_json = json.dumps(
        [{"name": "pytest-linux", "bucket": "pass", "completedAt": OLD_TS}]
    )
    gh = write_fake_gh(
        tmp_path,
        textwrap.dedent(
            f"""
            case "$*" in
              *"pr list"*) echo '{listing}' ;;
              *"pr checks"*"--json"*) echo '{checks_json}' ;;
              *"pr checks"*) printf '%s' 'pytest-linux\tpass\t0\tx\n' ;;
              *"pr view"*) echo '{{"headRefOid": "{head}"}}' ;;
              *"workflow run"*) echo boom >&2; exit 1 ;;
              *) exit 99 ;;
            esac
            """
        ),
    )
    r = run(gh, "--json", "--min", "500")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)[0]["marker_dispatch"] == "dispatch_failed"
    state = tmp_path / "marker-state.json"
    recorded = json.loads(state.read_text())["dispatched"] if state.exists() else {}
    assert recorded == {}  # the claim was released, so the next run retries


def test_merge_now_dispatches_but_still_refuses_without_marker(tmp_path: Path) -> None:
    gh = _heal_gh(tmp_path, head="a" * 40, checks_tsv=PASS_ONLY, completed_at=OLD_TS)
    r = run(gh, "merge-now", "--prs", "587", "--yes", "--min", "500")
    assert r.returncode == 2
    assert "refuse merge" in r.stderr
    assert "marker-dispatch #587" in r.stderr
    assert len(_dispatch_calls(tmp_path)) == 1
    assert not any("pr merge" in ln for ln in (tmp_path / "calls.log").read_text().splitlines())


def test_state_file_is_atomic_and_pruned(tmp_path: Path) -> None:
    import runpy

    mod = runpy.run_path(str(SCRIPT), run_name="ade_merge_ready_under_test")
    path = str(tmp_path / "sub" / "state.json")
    now = 10_000_000.0
    mod["save_dispatch_state"](path, {"old": 1.0, "new": now - 5}, now)
    assert mod["load_dispatch_state"](path) == {"new": now - 5}
    assert [p.name for p in (tmp_path / "sub").iterdir()] == ["state.json"]
    (tmp_path / "sub" / "state.json").write_text("{not json")
    assert mod["load_dispatch_state"](path) == {}


def test_corrupt_state_file_redispatches_once_then_records(tmp_path: Path) -> None:
    gh = _heal_gh(tmp_path, head="b" * 40, checks_tsv=PASS_ONLY, completed_at=OLD_TS)
    (tmp_path / "marker-state.json").write_text("{not json")
    r = run(gh, "--json", "--min", "500")
    assert json.loads(r.stdout)[0]["marker_dispatch"] == "dispatched"
    r2 = run(gh, "--json", "--min", "500")
    assert json.loads(r2.stdout)[0]["marker_dispatch"] == "already_dispatched"
    assert len(_dispatch_calls(tmp_path)) == 1


def test_merge_now_dry_run_or_without_prs_dispatches_nothing(tmp_path: Path) -> None:
    gh = _heal_gh(tmp_path, head="c" * 40, checks_tsv=PASS_ONLY, completed_at=OLD_TS)
    r = run(gh, "merge-now", "--prs", "587", "--min", "500")  # dry-run
    assert r.returncode == 2
    r = run(gh, "merge-now", "--min", "500")  # bare
    assert r.returncode == 2 and "requires --prs" in r.stderr
    assert _dispatch_calls(tmp_path) == []


def test_merge_now_heals_only_named_prs(tmp_path: Path) -> None:
    heads = {587: "7" * 40, 588: "8" * 40}
    listing = json.dumps(
        [
            {
                "number": n,
                "title": "t",
                "headRefOid": h,
                "baseRefName": "master",
                "mergeable": "MERGEABLE",
                "headRefName": f"b{n}",
            }
            for n, h in heads.items()
        ]
    )
    checks_json = json.dumps(
        [{"name": "pytest-linux", "bucket": "pass", "completedAt": OLD_TS}]
    )
    log = tmp_path / "calls.log"
    gh = write_fake_gh(
        tmp_path,
        textwrap.dedent(
            f"""
            echo "$*" >> '{log}'
            case "$*" in
              *"pr list"*) echo '{listing}' ;;
              *"pr checks"*"--json"*) echo '{checks_json}' ;;
              *"pr checks"*) printf '%s' 'pytest-linux\tpass\t0\tx\n' ;;
              *"pr view 587"*) echo '{{"headRefOid": "{heads[587]}"}}' ;;
              *"pr view 588"*) echo '{{"headRefOid": "{heads[588]}"}}' ;;
              *"workflow run"*) echo ok ;;
              *) exit 99 ;;
            esac
            """
        ),
    )
    r = run(gh, "merge-now", "--prs", "587", "--yes", "--min", "500")
    assert r.returncode == 2
    calls = _dispatch_calls(tmp_path)
    assert len(calls) == 1 and "pr=587" in calls[0]


def test_unwritable_state_stops_dispatch_and_command_still_runs(tmp_path: Path) -> None:
    gh = _heal_gh(tmp_path, head="d" * 40, checks_tsv=PASS_ONLY, completed_at=OLD_TS)
    env = {**os.environ, "ADE_MERGE_READY_STATE": str(tmp_path)}  # a directory
    for _ in range(2):
        r = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--gh", str(gh), "--json", "--min", "500"],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)[0]["marker_dispatch"] == "state_unwritable"
    assert _dispatch_calls(tmp_path) == []


def test_head_moved_since_listing_is_not_dispatched(tmp_path: Path) -> None:
    gh = _heal_gh(
        tmp_path,
        head="e" * 40,
        checks_tsv=PASS_ONLY,
        completed_at=OLD_TS,
        view_head="f" * 40,
    )
    r = run(gh, "--json", "--min", "500")
    assert json.loads(r.stdout)[0]["marker_dispatch"] == "head_moved"
    assert _dispatch_calls(tmp_path) == []


@pytest.mark.parametrize("bad", ["nan", "inf", "-5", "soon"])
def test_bad_marker_grace_is_a_clean_usage_error(tmp_path: Path, bad: str) -> None:
    gh = _heal_gh(tmp_path, head="1" * 40, checks_tsv=PASS_ONLY, completed_at=OLD_TS)
    r = run(gh, "--json", "--min", "500", f"--marker-grace={bad}")
    assert r.returncode == 2 and "Traceback" not in r.stderr
    assert _dispatch_calls(tmp_path) == []
    env = {
        **os.environ,
        "ADE_MERGE_READY_STATE": str(tmp_path / "s.json"),
        "ADE_MERGE_READY_MARKER_GRACE": bad,
    }
    r = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--gh", str(gh), "stacks", "--min", "500"],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert r.returncode == 2 and "Traceback" not in r.stderr


def test_newest_pytest_linux_entry_decides_grace() -> None:
    import datetime as dt
    import runpy

    mod = runpy.run_path(str(SCRIPT), run_name="ade_merge_ready_under_test")
    entries = [
        {"name": "pytest-linux", "bucket": "pass", "completedAt": "2026-11-12T10:00:00Z"},
        {"name": "pytest-linux", "bucket": "pass", "completedAt": "2026-11-12T11:00:00Z"},
    ]

    class P:
        returncode = 0
        stdout = json.dumps(entries)

    mod["tests_completed_epoch"].__globals__["run_gh"] = lambda *a, **k: P()
    want = dt.datetime(2026, 11, 12, 11, 0, tzinfo=dt.timezone.utc).timestamp()
    assert mod["tests_completed_epoch"]("gh", "o/r", 1) == want
    entries[1]["bucket"] = "fail"
    P.stdout = json.dumps(entries)
    assert mod["tests_completed_epoch"]("gh", "o/r", 1) is None
