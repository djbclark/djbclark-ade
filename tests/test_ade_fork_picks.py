"""bin/ade_fork_picks: registry validation, list, apply, mark, check-upstream (no network)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bin"))
import ade_fork_picks as fp  # noqa: E402

FORKS = REPO / "config" / "forks.toml"
FORK_URL = "https://github.com/frdminc/paseo.git"
UPSTREAM_URL = "https://github.com/getpaseo/paseo"


def sh(cwd: Path, *argv: str) -> str:
    result = subprocess.run(["git", "-C", str(cwd), *argv], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def commit_file(repo: Path, name: str, content: str, msg: str) -> str:
    (repo / name).write_text(content)
    sh(repo, "add", name)
    sh(repo, "commit", "-q", "-m", msg)
    return sh(repo, "rev-parse", "HEAD")


@pytest.fixture
def world(tmp_path, monkeypatch):
    """upstream repo, fork clone with feature branches, primary checkout + linked worktree."""
    for key, value in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}.items():
        monkeypatch.setenv(key, value)
    up = tmp_path / "up"
    sh(tmp_path, "init", "-q", "-b", "main", str(up))
    commit_file(up, "a.txt", "one\ntwo\nthree\n", "base")
    fork = tmp_path / "fork"
    sh(tmp_path, "clone", "-q", str(up), str(fork))
    sh(fork, "config", "uploadpack.allowAnySHA1InWant", "true")
    sh(fork, "checkout", "-q", "-b", "feat")
    f1 = commit_file(fork, "f1.txt", "f1\n", "feat one")
    f2 = commit_file(fork, "f2.txt", "f2\n", "feat two")
    sh(fork, "checkout", "-q", "-b", "conf", "main")
    conf = commit_file(fork, "a.txt", "ONE\ntwo\nthree\n", "conflicting change")
    sh(fork, "checkout", "-q", "-b", "single", "main")
    single = commit_file(fork, "s.txt", "single\n", "single pick")
    sh(fork, "checkout", "-q", "main")
    primary = tmp_path / "primary"
    sh(tmp_path, "clone", "-q", str(up), str(primary))
    wt = tmp_path / "wt"
    sh(primary, "worktree", "add", "-q", "-b", "work", str(wt), "main")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "3")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.{fork}.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", FORK_URL)
    monkeypatch.setenv("GIT_CONFIG_KEY_1", f"url.{up}.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_1", UPSTREAM_URL)
    monkeypatch.setenv("GIT_CONFIG_KEY_2", "commit.gpgsign")
    monkeypatch.setenv("GIT_CONFIG_VALUE_2", "false")
    monkeypatch.setenv("ADE_FORK_PICKS_CACHE", str(tmp_path / "cache"))
    return {"up": up, "fork": fork, "primary": primary, "wt": wt, "f1": f1, "f2": f2,
            "conf": conf, "single": single, "tmp": tmp_path}


def pick(id, *, commit=None, branch=None, target="desktop-build-2", status="queued", order=None,
         upstream=None, notes=None, component="paseo", repo="frdminc/paseo", intent="an intent",
         extra=""):
    lines = ["[[pick]]", f'id = "{id}"', f'component = "{component}"']
    if repo:
        lines.append(f'repo = "{repo}"')
    if commit:
        lines.append(f'commit = "{commit}"')
    if branch:
        lines.append(f'branch = "{branch}"')
    lines += [f'intent = "{intent}"', f'status = "{status}"']
    if target:
        lines.append(f'target = "{target}"')
    if upstream:
        lines.append(f'upstream = "{upstream}"')
    if order is not None:
        lines.append(f"order = {order}")
    if notes:
        lines.append(f'notes = "{notes}"')
    if extra:
        lines.append(extra)
    return "\n".join(lines) + "\n"


def registry(tmp_path, *picks, name="reg.toml"):
    path = tmp_path / name
    path.write_text("# header comment\nschema_version = 1\n\n" + "\n".join(picks))
    return path


def run_main(registry_path, *argv):
    return fp.main(["--registry", str(registry_path), "--forks", str(FORKS), *argv])


GOOD_SHA = "a" * 40


# ------------------------------------------------------------------ parsing

def test_shipped_registry_is_valid():
    entries = fp.load_registry()
    by_id = {e["id"]: e for e in entries}
    assert len(by_id) == 13
    assert by_id["paseo-settings-search"]["pr"] == 9875
    assert by_id["paseo-settings-search"]["expected_head"] == "084d2be0cc12e38bb961684bf45fac7de34e50c6"
    assert by_id["paseo-settings-search"]["targets"] == ["desktop-build-3", "android-build-3"]
    assert by_id["paseo-settings-search"]["trial_required"] is True
    assert by_id["paseo-pi-permission-selected-action"]["order"] < by_id["paseo-pi-ask-user-question-scope"]["order"]
    assert by_id["paseo-sync-sidebar-order"]["pr"] == 9830 and by_id["paseo-sync-sidebar-order"]["trial_required"]
    assert by_id["paseo-sync-sidebar-order"]["targets"] == ["desktop-build-2", "android-build-2"]
    assert "android-build-2" in by_id["paseo-sync-sidebar-order"]["notes"]
    assert "local_path" not in by_id["paseo-about-fork-marker"]
    assert by_id["paseo-about-fork-marker"]["repo"] == "frdminc/paseo"
    assert "local only" not in by_id["paseo-about-fork-marker"]["notes"]
    sharp = by_id["worktree-setup-sharp-global-libvips"]
    assert sharp["commit"] == "b21068d965e144963e54ac9ab617c4e504887a2a" and sharp["targets"] == ["desktop-build-2"]
    assert sharp["status"] == "landed:2" and sharp["trial_required"] is False
    elic = by_id["plugin-acp-elicitation-forms"]
    assert "hold" not in elic and elic["trial_required"] is False and elic["local_path"].startswith("/") and "repo" not in elic
    assert by_id["paseo-bump-wrangler-sharp-0-35"]["status"] == "dropped"
    # 2026-11-22: every Pi entry is the whole stack branch at one pinned head
    for pid in ("paseo-pi-permission-selected-action", "paseo-pi-ask-user-question-scope"):
        assert by_id[pid]["branch"] == "trial/pi-8326-6643-on-fork2"
        assert by_id[pid]["expected_head"] == "43d4fa9584f7ca5ca9bf3e69fffbd61c98c69cb4"
        assert "b720fd6b6773b3036c59dd54a2efa89436a24f76" in by_id[pid]["notes"]
    assert "hold" not in by_id["paseo-shift-drag-copy"] and by_id["paseo-shift-drag-copy"]["trial_required"] is False
    assert by_id["paseo-android-fork-release"]["status"] == "landed:main"
    for pid in (
        "paseo-workspace-id-search",
        "desktop-app-dist-precompress",
        "paseo-sidebar-nav-divider",
        "worktree-setup-sharp-global-libvips",
        "paseo-about-fork-marker",
        "paseo-shift-drag-copy",
        "paseo-sync-sidebar-order",
        "paseo-pi-permission-selected-action",
        "paseo-pi-ask-user-question-scope",
        "plugin-acp-elicitation-forms",
    ):
        assert by_id[pid]["status"] == "landed:2"


@pytest.mark.parametrize("kwargs, needle", [
    ({"component": "nope", "commit": GOOD_SHA}, "not in config/forks.toml"),
    ({"commit": GOOD_SHA[:39]}, "40-hex"),
    ({"commit": GOOD_SHA.upper()}, "40-hex"),
    ({"commit": GOOD_SHA, "branch": "x"}, "exactly one"),
    ({}, "requires hold"),
    ({"commit": GOOD_SHA, "target": "desktop-2"}, "PLATFORM-build-N"),
    ({"commit": GOOD_SHA, "target": "desktop-build-0"}, "PLATFORM-build-N"),
    ({"commit": GOOD_SHA, "status": "landed"}, "status must be"),
    ({"commit": GOOD_SHA, "repo": "https://user:pw@github.com/a/b"}, "credential-free"),
    ({"commit": GOOD_SHA, "repo": "http://github.com/a/b"}, "credential-free"),
    ({"commit": GOOD_SHA, "repo": "https://example.com/a/b"}, "github.com"),
    ({"branch": "-bad"}, "branch"),
    ({"branch": "a..b"}, "branch"),
    ({"commit": GOOD_SHA, "upstream": "https://tok@github.com/a/b/pull/1"}, "credential-free"),
])
def test_validation_errors(tmp_path, kwargs, needle):
    path = registry(tmp_path, pick("one", **kwargs))
    with pytest.raises(fp.RegistryError, match=needle):
        fp.load_registry(path, FORKS)


def test_duplicate_id_unknown_field_and_bad_schema(tmp_path):
    with pytest.raises(fp.RegistryError, match="duplicate id"):
        fp.load_registry(registry(tmp_path, pick("one", commit=GOOD_SHA), pick("one", commit=GOOD_SHA)), FORKS)
    with pytest.raises(fp.RegistryError, match="unknown field"):
        fp.load_registry(registry(tmp_path, pick("one", commit=GOOD_SHA) + 'extra = 1\n'), FORKS)
    bad = tmp_path / "bad.toml"
    bad.write_text("schema_version = 2\n")
    with pytest.raises(fp.RegistryError, match="schema_version=1"):
        fp.load_registry(bad, FORKS)
    bad.write_text("not toml [")
    with pytest.raises(fp.RegistryError, match="cannot read"):
        fp.load_registry(bad, FORKS)


def test_repo_forms_normalize():
    assert fp.normalize_repo("frdminc/paseo") == FORK_URL
    assert fp.normalize_repo("https://github.com/frdminc/paseo") == FORK_URL
    assert fp.normalize_repo("https://github.com/frdminc/paseo.git") == FORK_URL


def test_main_reports_invalid_registry_exit_2(tmp_path, capsys):
    path = registry(tmp_path, pick("one", commit="zz"))
    assert run_main(path, "list") == 2
    assert "error" in capsys.readouterr().err


# ------------------------------------------------------------------ list

def test_list_filters(tmp_path, capsys):
    path = registry(tmp_path,
                    pick("a-one", commit=GOOD_SHA, order=2),
                    pick("b-two", commit=GOOD_SHA, target="android-build-2", order=1),
                    pick("c-three", commit=GOOD_SHA, status="landed:2"),
                    pick("d-four", commit=GOOD_SHA, status="dropped"))

    def ids(*argv):
        assert run_main(path, "list", "--json", *argv) == 0
        return [p["id"] for p in json.loads(capsys.readouterr().out)["picks"]]

    assert ids() == ["b-two", "a-one"]  # default queued, apply order
    assert ids("--target", "android-build-2") == ["b-two"]
    assert ids("--component", "paseo", "--status", "all") == ["b-two", "a-one", "c-three", "d-four"]
    assert ids("--status", "landed") == ["c-three"]
    assert ids("--status", "landed:2") == ["c-three"]
    assert ids("--status", "dropped") == ["d-four"]
    assert ids("--component", "baton") == []


# ------------------------------------------------------------------ apply

def test_apply_branch_and_commit_entries_in_order(world, tmp_path, capsys):
    path = registry(tmp_path,
                    pick("z-single", commit=world["single"], order=2),
                    pick("a-branch", branch="feat", order=1),
                    pick("other-target", branch="conf", target="android-build-2"))
    wt = world["wt"]
    start = sh(wt, "rev-parse", "HEAD")
    assert run_main(path, "apply", "--target", "desktop-build-2", "--workspace", str(wt), "--json") == 0
    report = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in report["applied"]] == ["a-branch", "z-single"]
    assert report["applied"][0]["commits"] == [world["f1"], world["f2"]]
    assert report["start_head"] == start and report["head"] == sh(wt, "rev-parse", "HEAD")
    assert (wt / "f1.txt").exists() and (wt / "f2.txt").exists() and (wt / "s.txt").exists()
    assert not (wt / "a.txt").read_text().startswith("ONE")
    assert "cherry picked from commit" in sh(wt, "log", "-1", "--format=%B")
    assert sh(wt, "status", "--porcelain") == ""
    # rerun is idempotent: everything already present
    assert run_main(path, "apply", "--target", "desktop-build-2", "--workspace", str(wt), "--json") == 0
    again = json.loads(capsys.readouterr().out)
    assert all(r["already_present"] for r in again["applied"]) and again["head"] == report["head"]


def test_apply_dry_run_changes_nothing(world, tmp_path, capsys):
    path = registry(tmp_path, pick("a-branch", branch="feat"))
    wt = world["wt"]
    start = sh(wt, "rev-parse", "HEAD")
    assert run_main(path, "apply", "--target", "desktop-build-2", "--workspace", str(wt), "--dry-run", "--json") == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"] and report["applied"][0]["commits"] == [world["f1"], world["f2"]]
    assert sh(wt, "rev-parse", "HEAD") == start and not (wt / "f1.txt").exists()


def test_apply_conflict_aborts_leaves_clean_tree_and_reports_files(world, tmp_path, capsys):
    wt = world["wt"]
    commit_file(wt, "a.txt", "uno\ntwo\nthree\n", "diverging change")
    path = registry(tmp_path,
                    pick("a-first", commit=world["single"], order=1),
                    pick("b-conflict", branch="conf", order=2),
                    pick("c-never", branch="feat", order=3))
    assert run_main(path, "apply", "--target", "desktop-build-2", "--workspace", str(wt), "--json") == 3
    report = json.loads(capsys.readouterr().out)
    assert report["conflict"]["id"] == "b-conflict"
    assert report["conflict"]["commit"] == world["conf"]
    assert report["conflict"]["files"] == ["a.txt"]
    assert sh(wt, "status", "--porcelain") == ""
    assert not Path(sh(wt, "rev-parse", "--git-path", "CHERRY_PICK_HEAD")).exists() \
        and not (wt / sh(wt, "rev-parse", "--git-path", "CHERRY_PICK_HEAD")).exists()
    assert (wt / "s.txt").exists() and not (wt / "f1.txt").exists()  # first applied, third never tried
    assert report["head"] == sh(wt, "rev-parse", "HEAD")


def test_apply_refuses_dirty_tree(world, tmp_path, capsys):
    path = registry(tmp_path, pick("a", branch="feat"))
    (world["wt"] / "a.txt").write_text("dirty\n")
    assert run_main(path, "apply", "--target", "desktop-build-2", "--workspace", str(world["wt"])) == 1
    assert "dirty" in capsys.readouterr().err
    assert not (world["wt"] / "f1.txt").exists()


def test_apply_refuses_untracked_files(world, tmp_path, capsys):
    path = registry(tmp_path, pick("a", branch="feat"))
    (world["wt"] / "new.txt").write_text("x\n")
    assert run_main(path, "apply", "--target", "desktop-build-2", "--workspace", str(world["wt"])) == 1


def test_apply_refuses_detached_head(world, tmp_path, capsys):
    path = registry(tmp_path, pick("a", branch="feat"))
    sh(world["wt"], "checkout", "-q", "--detach")
    assert run_main(path, "apply", "--target", "desktop-build-2", "--workspace", str(world["wt"])) == 1
    assert "detached" in capsys.readouterr().err


def test_apply_refuses_primary_checkout(world, tmp_path, capsys):
    path = registry(tmp_path, pick("a", branch="feat"))
    assert run_main(path, "apply", "--target", "desktop-build-2", "--workspace", str(world["primary"])) == 1
    assert "primary checkout" in capsys.readouterr().err
    assert not (world["primary"] / "f1.txt").exists()


@pytest.mark.parametrize("marker", ["MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"])
def test_apply_refuses_operation_in_progress(world, tmp_path, capsys, marker):
    path = registry(tmp_path, pick("a", branch="feat"))
    head = sh(world["wt"], "rev-parse", "HEAD")
    git_path = Path(sh(world["wt"], "rev-parse", "--path-format=absolute", "--git-path", marker))
    git_path.write_text(head + "\n")
    assert run_main(path, "apply", "--target", "desktop-build-2", "--workspace", str(world["wt"])) == 1
    assert marker in capsys.readouterr().err


def test_apply_refuses_rebase_in_progress(world, tmp_path, capsys):
    path = registry(tmp_path, pick("a", branch="feat"))
    Path(sh(world["wt"], "rev-parse", "--path-format=absolute", "--git-path", "rebase-merge")).mkdir()
    assert run_main(path, "apply", "--target", "desktop-build-2", "--workspace", str(world["wt"])) == 1
    assert "rebase-merge" in capsys.readouterr().err


def test_apply_rejects_non_repo_and_bad_target(world, tmp_path, capsys):
    path = registry(tmp_path, pick("a", branch="feat"))
    assert run_main(path, "apply", "--target", "desktop-build-2", "--workspace", str(tmp_path)) == 2
    assert run_main(path, "apply", "--target", "bogus", "--workspace", str(world["wt"])) == 2


def test_apply_unfetchable_branch_is_exit_2(world, tmp_path, capsys):
    path = registry(tmp_path, pick("a", branch="does-not-exist"))
    assert run_main(path, "apply", "--target", "desktop-build-2", "--workspace", str(world["wt"])) == 2


# ------------------------------------------------------------------ mark

@pytest.fixture
def reg_worktree(tmp_path):
    repo = tmp_path / "regrepo"
    sh(tmp_path, "init", "-q", "-b", "main", str(repo))
    text = ("# keep this comment\nschema_version = 1\n\n"
            + pick("first", commit=GOOD_SHA).replace('status = "queued"', 'status = "queued"  # trailing')
            + "\n# between entries\n" + pick("second", branch="feat", notes="old note"))
    (repo / "reg.toml").write_text(text)
    sh(repo, "add", "reg.toml")
    sh(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "init")
    wt = tmp_path / "regwt"
    sh(repo, "worktree", "add", "-q", "-b", "edit", str(wt), "main")
    return {"primary": repo, "wt": wt}


def test_mark_edits_only_the_status_line(reg_worktree, capsys):
    reg = reg_worktree["wt"] / "reg.toml"
    before = reg.read_text().splitlines()
    assert run_main(reg, "mark", "first", "--status", "landed:2") == 0
    after = reg.read_text().splitlines()
    changed = [(a, b) for a, b in zip(before, after) if a != b]
    assert len(before) == len(after) and len(changed) == 1
    assert changed[0][1] == 'status = "landed:2"  # trailing'
    assert fp.load_registry(reg, FORKS)[0]["status"] == "landed:2"
    assert not list(reg.parent.glob(".reg.toml.*"))


def test_mark_note_edits_and_appends_notes(reg_worktree):
    reg = reg_worktree["wt"] / "reg.toml"
    assert run_main(reg, "mark", "second", "--status", "upstreamed", "--note", "merged upstream") == 0
    entries = {e["id"]: e for e in fp.load_registry(reg, FORKS)}
    assert entries["second"]["status"] == "upstreamed"
    assert entries["second"]["notes"] == "old note | merged upstream"
    assert entries["first"]["status"] == "queued" and "notes" not in entries["first"]
    assert run_main(reg, "mark", "first", "--status", "dropped", "--note", "obsolete") == 0
    assert {e["id"]: e for e in fp.load_registry(reg, FORKS)}["first"]["notes"] == "obsolete"
    assert "# between entries" in reg.read_text() and "# keep this comment" in reg.read_text()


def test_mark_refuses_in_primary_checkout(reg_worktree, capsys):
    reg = reg_worktree["primary"] / "reg.toml"
    before = reg.read_text()
    assert run_main(reg, "mark", "first", "--status", "dropped") == 1
    assert "primary checkout" in capsys.readouterr().err
    assert reg.read_text() == before


def test_mark_refuses_outside_git(tmp_path, capsys):
    reg = registry(tmp_path, pick("first", commit=GOOD_SHA))
    assert run_main(reg, "mark", "first", "--status", "dropped") == 1


def test_mark_rejects_bad_status_and_unknown_id(reg_worktree):
    reg = reg_worktree["wt"] / "reg.toml"
    before = reg.read_text()
    assert run_main(reg, "mark", "first", "--status", "queued") == 2
    assert run_main(reg, "mark", "first", "--status", "landed:x") == 2
    assert run_main(reg, "mark", "missing", "--status", "dropped") == 2
    assert reg.read_text() == before


# ------------------------------------------------------------------ check-upstream

@pytest.fixture
def fake_gh(tmp_path, monkeypatch):
    bindir = tmp_path / "ghbin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text('#!/bin/sh\nif [ -n "$FAKE_GH_FAIL" ]; then echo boom >&2; exit 1; fi\n'
                  'echo "$FAKE_GH_JSON"\n')
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_JSON", json.dumps({"state": "OPEN", "mergedAt": None}))
    return gh


def test_check_upstream_detects_equivalent_patch(world, tmp_path, fake_gh, capsys):
    up = world["up"]
    # upstream lands the same change with another message and an unrelated commit in between
    commit_file(up, "other.txt", "o\n", "unrelated")
    commit_file(up, "s.txt", "single\n", "same change, different message")
    path = registry(tmp_path,
                    pick("dup", commit=world["single"]),
                    pick("fresh", commit=world["f2"]),
                    pick("branchy", branch="feat"))
    assert run_main(path, "check-upstream", "--json") == 4
    report = json.loads(capsys.readouterr().out)
    assert report["checked"] == ["dup", "fresh", "branchy"]
    assert [c["id"] for c in report["candidates"]] == ["dup"]
    assert report["candidates"][0]["reasons"][0]["code"] == "equivalent-patch-upstream"
    assert report["errors"] == []
    assert set(report) == {"schema_version", "checked", "candidates", "errors"}


def test_check_upstream_commit_already_in_upstream_history(world, tmp_path, fake_gh, capsys):
    up = world["up"]
    sh(up, "fetch", "-q", str(world["fork"]), "single")
    sh(up, "merge", "-q", "--ff-only", "FETCH_HEAD")
    path = registry(tmp_path, pick("dup", commit=world["single"]))
    assert run_main(path, "check-upstream", "--json") == 4
    assert json.loads(capsys.readouterr().out)["candidates"][0]["reasons"][0]["code"] == "commit-in-upstream"


def test_check_upstream_nothing_to_drop_exit_0_and_registry_untouched(world, tmp_path, fake_gh, capsys):
    path = registry(tmp_path, pick("fresh", commit=world["single"]))
    before = path.read_text()
    assert run_main(path, "check-upstream") == 0
    assert "no drop candidates" in capsys.readouterr().out
    assert path.read_text() == before


def test_check_upstream_merged_pr(world, tmp_path, fake_gh, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_GH_JSON", json.dumps({"state": "MERGED", "mergedAt": "2026-11-20T00:00:00Z"}))
    path = registry(tmp_path,
                    pick("merged", branch="feat", upstream="https://github.com/getpaseo/paseo/pull/9"),
                    pick("no-pr", branch="conf", upstream="https://github.com/getpaseo/paseo/issues/3"))
    assert run_main(path, "check-upstream", "--json") == 4
    report = json.loads(capsys.readouterr().out)
    assert [c["id"] for c in report["candidates"]] == ["merged"]
    assert report["candidates"][0]["reasons"][0]["code"] == "upstream-pr-merged"


def test_check_upstream_open_pr_is_not_a_candidate(world, tmp_path, fake_gh, capsys):
    path = registry(tmp_path, pick("open", branch="feat", upstream="https://github.com/getpaseo/paseo/pull/9"))
    assert run_main(path, "check-upstream") == 0


def test_check_upstream_gh_failure_is_exit_2_with_json(world, tmp_path, fake_gh, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_GH_FAIL", "1")
    path = registry(tmp_path, pick("open", branch="feat", upstream="https://github.com/getpaseo/paseo/pull/9"))
    assert run_main(path, "check-upstream", "--json") == 2
    report = json.loads(capsys.readouterr().out)
    assert report["errors"][0]["id"] == "open" and report["errors"][0]["check"] == "pr"


def test_check_upstream_skips_non_queued_and_filters_component(world, tmp_path, fake_gh, capsys):
    path = registry(tmp_path, pick("done", commit=world["single"], status="landed:2"))
    assert run_main(path, "check-upstream", "--json") == 0
    assert json.loads(capsys.readouterr().out)["checked"] == []
    assert run_main(path, "check-upstream", "--component", "baton", "--json") == 0


# ------------------------------------------------------------------ schema additions

def test_new_field_validation(tmp_path):
    cases = [
        (pick("a", commit=GOOD_SHA, extra="pr = 3"), "exactly one of commit, branch or pr"),
        (pick("a", extra="pr = 0"), "positive integer"),
        (pick("a", commit=GOOD_SHA, extra='local_path = "relative/x"'), "absolute"),
        (pick("a", branch="x", extra='local_path = "/tmp/x"'), "local_path requires a commit"),
        (pick("a", commit=GOOD_SHA, repo=None), "repo is required"),
        (pick("a", commit=GOOD_SHA, extra='targets = ["desktop-build-2"]'), "exactly one of target or targets"),
        (pick("a", commit=GOOD_SHA, target=None), "exactly one of target or targets"),
        (pick("a", commit=GOOD_SHA, target=None, extra='targets = ["desktop-build-2", "desktop-build-2"]'), "unique"),
        (pick("a", commit=GOOD_SHA, target=None, extra="targets = []"), "unique"),
        (pick("a", commit=GOOD_SHA, extra='trial_required = "yes"'), "boolean"),
        (pick("a", commit=GOOD_SHA, extra='hold = "  "'), "hold"),
        (pick("a", commit=GOOD_SHA, extra=f'expected_head = "{GOOD_SHA}"'), "branch or pr sources"),
        (pick("a", branch="x", extra='expected_head = "abc"'), "expected_head"),
    ]
    for text, needle in cases:
        with pytest.raises(fp.RegistryError, match=needle):
            fp.load_registry(registry(tmp_path, text), FORKS)


def test_targets_list_and_single_target_match_list_filter(tmp_path, capsys):
    path = registry(tmp_path,
                    pick("multi", commit=GOOD_SHA, target=None, extra='targets = ["desktop-build-2", "android-build-2"]'),
                    pick("single", commit=GOOD_SHA, target="android-build-2"),
                    pick("held", commit=GOOD_SHA, extra='hold = "wait for operator"\ntrial_required = true'))

    def ids(*argv):
        assert run_main(path, "list", "--json", *argv) == 0
        return [p["id"] for p in json.loads(capsys.readouterr().out)["picks"]]

    assert ids("--target", "android-build-2") == ["multi", "single"]
    assert ids("--target", "desktop-build-2") == ["multi", "held"]
    assert run_main(path, "list") == 0
    out = capsys.readouterr().out
    assert "[trial required]" in out and "[hold: wait for operator]" in out and "desktop-build-2,android-build-2" in out


def test_list_default_includes_carried(tmp_path, capsys):
    path = registry(tmp_path, pick("q", commit=GOOD_SHA), pick("c", commit=GOOD_SHA, status="carried"),
                    pick("m", commit=GOOD_SHA, status="landed:main"))
    assert run_main(path, "list", "--json") == 0
    assert [p["id"] for p in json.loads(capsys.readouterr().out)["picks"]] == ["q", "c"]
    assert run_main(path, "list", "--json", "--status", "landed") == 0
    assert [p["id"] for p in json.loads(capsys.readouterr().out)["picks"]] == ["m"]


def apply_json(path, wt, capsys, *extra):
    code = run_main(path, "apply", "--target", "desktop-build-2", "--workspace", str(wt), "--json", *extra)
    return code, json.loads(capsys.readouterr().out)


def test_apply_pr_source_fetches_pull_head(world, tmp_path, capsys):
    sh(world["fork"], "update-ref", "refs/pull/7/head", world["f2"])
    path = registry(tmp_path, pick("viapr", extra=f"pr = 7\nexpected_head = \"{world['f2']}\""))
    code, report = apply_json(path, world["wt"], capsys)
    assert code == 0 and report["applied"][0]["commits"] == [world["f1"], world["f2"]]
    assert (world["wt"] / "f2.txt").exists()


def test_apply_local_path_source_without_repo(world, tmp_path, capsys):
    local = world["tmp"] / "localonly"
    sh(world["tmp"], "clone", "-q", str(world["up"]), str(local))
    only = commit_file(local, "local.txt", "local\n", "local only commit")
    path = registry(tmp_path, pick("loc", commit=only, repo=None, extra=f'local_path = "{local}"'))
    code, report = apply_json(path, world["wt"], capsys)
    assert code == 0 and report["applied"][0]["commits"] == [only]
    assert (world["wt"] / "local.txt").exists()


def test_apply_skips_trial_and_held_unless_included(world, tmp_path, capsys):
    path = registry(tmp_path,
                    pick("trial", branch="feat", extra="trial_required = true", order=1),
                    pick("held", commit=world["single"], extra='hold = "operator testing"', order=2),
                    pick("plain", branch="conf", target="android-build-2"))
    code, report = apply_json(path, world["wt"], capsys)
    assert code == 0 and report["applied"] == []
    assert report["skipped"] == [{"id": "trial", "why": "trial_required"},
                                 {"id": "held", "why": "hold", "hold": "operator testing"}]
    assert not (world["wt"] / "f1.txt").exists()
    code, report = apply_json(path, world["wt"], capsys, "--include-trial")
    assert [r["id"] for r in report["applied"]] == ["trial"]
    assert report["skipped"] == [{"id": "held", "why": "hold", "hold": "operator testing"}]
    code, report = apply_json(path, world["wt"], capsys, "--include-held")
    assert [r["id"] for r in report["applied"]] == ["held"] and (world["wt"] / "s.txt").exists()


def test_apply_includes_carried_but_not_landed(world, tmp_path, capsys):
    path = registry(tmp_path, pick("carry", commit=world["single"], status="carried"),
                    pick("done", branch="feat", status="landed:main"))
    code, report = apply_json(path, world["wt"], capsys)
    assert [r["id"] for r in report["applied"]] == ["carry"]


def test_apply_reports_already_present_for_patch_equivalent_commit(world, tmp_path, capsys):
    wt = world["wt"]
    sh(wt, "fetch", "-q", str(world["fork"]), "single", "feat")
    sh(wt, "cherry-pick", world["single"])  # HEAD carries the same patch under another sha
    sh(wt, "cherry-pick", world["f1"])
    head = sh(wt, "rev-parse", "HEAD")
    path = registry(tmp_path, pick("dup", commit=world["single"], order=1), pick("branch", branch="feat", order=2))
    code, report = apply_json(path, wt, capsys)
    assert code == 0
    dup, branch = report["applied"]
    assert dup["commits"] == [] and dup["already_present"] and dup["already_present_commits"] == [world["single"]]
    assert branch["commits"] == [world["f2"]] and branch["already_present_commits"] == [world["f1"]]
    assert sh(wt, "log", "--format=%s", f"{head}..HEAD") == "feat two"
    assert sh(wt, "log", "--format=%s").splitlines().count("single pick") == 1


def test_exclude_names_skipped_commits_and_unused_ids(world, tmp_path, capsys):
    """A branch entry's `exclude` drops named commits, names them in both outputs, reports unmatched ids."""
    wt = world["wt"]
    base = sh(wt, "rev-parse", "HEAD")                # in the source's history, not a candidate: known but not needed
    path = registry(tmp_path, pick("ex", branch="feat",
                                   extra=f'exclude = ["{world["f1"]}", "{base}"]'))
    code, report = apply_json(path, wt, capsys)
    row = report["applied"][0]
    assert code == 0 and row["commits"] == [world["f2"]]
    assert row["excluded_by_entry"] == [{"commit": world["f1"], "subject": "feat one"}]
    assert row["exclude_unused"] == [base]
    assert (wt / "f2.txt").exists() and not (wt / "f1.txt").exists()
    assert run_main(path, "apply", "--dry-run", "--target", "desktop-build-2", "--workspace", str(wt)) == 0
    out = capsys.readouterr().out
    assert f"EXCLUDED by entry {world['f1'][:9]} (feat one)" in out
    assert f"exclude not needed (already present or excluded upstream): {base[:9]}" in out


def test_both_exclude_ids_are_honoured(world, tmp_path, capsys):
    """PR 946 review LOW-3: the second id of a list is dropped too (a mutant honouring only the first survived)."""
    path = registry(tmp_path, pick("ex", branch="feat", extra=f'exclude = ["{world["f1"]}", "{world["f2"]}"]'))
    code, report = apply_json(path, world["wt"], capsys)
    row = report["applied"][0]
    assert code == 0 and row["commits"] == [] and {x["commit"] for x in row["excluded_by_entry"]} == {world["f1"], world["f2"]}
    assert row["exclude_unused"] == []


@pytest.mark.parametrize("bad", ["f1-typo", "other-branch"])
def test_unknown_exclude_stops_before_any_pick_even_on_dry_run(world, tmp_path, capsys, bad):
    """PR 946 review LOW-2: an exclude id outside the source's history (a typo, or another branch's commit) would
    otherwise apply the commit it was meant to drop; the run stops before the first pick."""
    wt = world["wt"]
    unknown = world["f1"][:-1] + ("0" if world["f1"][-1] != "0" else "1") if bad == "f1-typo" else world["conf"]
    path = registry(tmp_path, pick("one", commit=world["single"], order=1),
                    pick("ex", branch="feat", order=2, extra=f'exclude = ["{unknown}"]'))
    start = sh(wt, "rev-parse", "HEAD")
    for extra in ((), ("--dry-run",)):
        code, report = apply_json(path, wt, capsys, *extra)
        assert code == 3 and report["conflict"]["reason"] == "exclude-unknown"
        assert report["conflict"]["unknown_excludes"] == [unknown] and report["applied"] == []
        assert sh(wt, "rev-parse", "HEAD") == start and not (wt / "s.txt").exists()
    assert run_main(path, "apply", "--target", "desktop-build-2", "--workspace", str(wt)) == 3
    assert f"not in the source's history: {unknown}" in capsys.readouterr().out


def test_exclude_with_trailing_newline_is_refused(tmp_path):
    """PR 946 review LOW-4: `$` accepted '<sha>\\n', which can never match a commit."""
    for text in (GOOD_SHA + "\\n", GOOD_SHA):
        entry = pick("e", branch="feat", extra=f'exclude = ["{text}"]')
        if text.endswith("\\n"):
            with pytest.raises(fp.RegistryError, match="40-hex"):
                fp.load_registry(registry(tmp_path, entry), FORKS)
        else:
            fp.load_registry(registry(tmp_path, entry), FORKS)
    assert not fp.COMMIT_RE.match(GOOD_SHA + "\n")


@pytest.mark.parametrize("extra, kwargs, needle", [
    ('exclude = ["' + GOOD_SHA + '"]', {"commit": GOOD_SHA}, "branch or pr"),
    ('exclude = "x"', {"branch": "feat"}, "non-empty list"),
    ("exclude = []", {"branch": "feat"}, "non-empty list"),
    ('exclude = ["' + GOOD_SHA[:39] + '"]', {"branch": "feat"}, "40-hex"),
    ('exclude = ["' + GOOD_SHA + '", "' + GOOD_SHA + '"]', {"branch": "feat"}, "unique"),
])
def test_exclude_validation(tmp_path, extra, kwargs, needle):
    with pytest.raises(fp.RegistryError, match=needle):
        fp.load_registry(registry(tmp_path, pick("e", extra=extra, **kwargs)), FORKS)


def test_cherry_pick_trailer_counts_as_present_when_patch_id_changed(world, tmp_path, capsys):
    """A pick whose context changed has another patch-id; its -x trailer still marks it present."""
    wt = world["wt"]
    sh(wt, "fetch", "-q", str(world["fork"]), "feat")
    commit_file(wt, "f1.txt", "f1 with other context\n", f"feat one\n\n(cherry picked from commit {world['f1']})")
    head = sh(wt, "rev-parse", "HEAD")
    path = registry(tmp_path, pick("br", branch="feat", order=1), pick("one", commit=world["f1"], order=2))
    code, report = apply_json(path, wt, capsys)
    br, one = report["applied"]
    assert code == 0
    assert br["commits"] == [world["f2"]] and br["already_present_commits"] == [world["f1"]]
    assert br["already_present_by_trailer"] == [world["f1"]]
    assert one["commits"] == [] and one["already_present"] and one["already_present_by_trailer"] == [world["f1"]]
    assert sh(wt, "log", "--format=%s", f"{head}..HEAD") == "feat two"
    # re-running is idempotent
    code, again = apply_json(path, wt, capsys)
    assert code == 0 and all(r["already_present"] for r in again["applied"])


def test_trailer_must_name_the_exact_sha(world, tmp_path, capsys):
    """A trailer naming another commit does not make f1 present (it would stop on the conflict instead)."""
    wt = world["wt"]
    sh(wt, "fetch", "-q", str(world["fork"]), "feat")
    commit_file(wt, "f1.txt", "different\n", f"feat one\n\n(cherry picked from commit {world['f2']})")
    path = registry(tmp_path, pick("br", branch="feat"))
    code, report = apply_json(path, wt, capsys)
    assert code == 3 and report["conflict"]["commit"] == world["f1"]


@pytest.mark.parametrize("message", [
    "feat one\n\n(cherry picked from commit {f1}) trailing words",          # not the whole line
    "feat one\n\n  (cherry picked from commit {f1}x)",                       # not anchored
    "feat one\n\n(cherry picked from commit {short})",                       # a prefix names nothing
    "feat one\n\n(cherry picked from commit {upper})",                       # uppercase hex
    "feat one\n\n(cherry picked from commit {f1})\n\nmore prose after it",   # mid-message, not the final paragraph
])
def test_only_a_whole_exact_trailer_line_in_the_final_paragraph_counts(world, tmp_path, capsys, message):
    """PR 946 review LOW-1 and LOW-3: a copied or mid-message line, a prefix, upper case or an unanchored line is no trailer."""
    wt = world["wt"]
    sh(wt, "fetch", "-q", str(world["fork"]), "feat")
    f1 = world["f1"]
    commit_file(wt, "f1.txt", "different\n", message.format(f1=f1, short=f1[:12], upper=f1.upper()))
    code, report = apply_json(registry(tmp_path, pick("br", branch="feat")), wt, capsys)
    assert code == 3 and report["conflict"]["commit"] == f1


def test_a_trailer_line_copied_from_a_picked_body_does_not_suppress_another_entry(world, tmp_path, capsys):
    """PR 946 review LOW-1 (P6): the line sits mid-message in a pick's body; `-x` appends the real trailer last."""
    wt = world["wt"]
    sh(wt, "fetch", "-q", str(world["fork"]), "feat")
    f1 = world["f1"]
    sh(world["fork"], "checkout", "-q", "-b", "evil", "main")
    evil = commit_file(world["fork"], "evil.txt", "e\n", f"evil\n\n(cherry picked from commit {f1})\n\nbody after the copied line")
    path = registry(tmp_path, pick("evil", commit=evil, order=1), pick("br", branch="feat", order=2))
    code, report = apply_json(path, wt, capsys)
    assert code == 0 and report["applied"][1]["commits"] == [f1, world["f2"]]
    assert report["applied"][1]["already_present_by_trailer"] == []
    assert (wt / "f1.txt").exists()


def test_final_paragraph_with_two_cherry_pick_trailers_counts_only_the_last(world, tmp_path, capsys):
    """PR 948 review LOW-4: re-`-x` produces two trailer lines in the final paragraph; only the last line counts."""
    wt = world["wt"]
    sh(wt, "fetch", "-q", str(world["fork"]), "feat")
    f1, f2 = world["f1"], world["f2"]
    tip = sh(wt, "rev-parse", "HEAD")
    commit_file(
        wt, "other.txt", "re-picked\n",
        f"re-picked commit\n\n(cherry picked from commit {f1})\n(cherry picked from commit {f2})",
    )
    assert fp.trailer_sources(wt, tip) == {f2}
    path = registry(tmp_path, pick("br", branch="feat"))
    code, report = apply_json(path, wt, capsys)
    assert code == 0
    assert report["applied"][0]["commits"] == [f1]
    assert report["applied"][0]["already_present_by_trailer"] == [f2]
    assert (wt / "f1.txt").exists() and not (wt / "f2.txt").exists()



def test_apply_already_present_when_commit_is_ancestor(world, tmp_path, capsys):
    sh(world["wt"], "fetch", "-q", str(world["fork"]), "single")
    sh(world["wt"], "merge", "-q", "--ff-only", "FETCH_HEAD")
    start = sh(world["wt"], "rev-parse", "HEAD")
    path = registry(tmp_path, pick("anc", commit=world["single"]))
    code, report = apply_json(path, world["wt"], capsys)
    assert code == 0 and report["applied"][0]["already_present"] and report["head"] == start


def test_apply_head_moved_refuses_before_changing_anything(world, tmp_path, capsys):
    path = registry(tmp_path,
                    pick("first", commit=world["single"], order=1),
                    pick("moved", branch="feat", order=2, extra=f'expected_head = "{world["f1"]}"'))
    wt = world["wt"]
    start = sh(wt, "rev-parse", "HEAD")
    code, report = apply_json(path, wt, capsys)
    assert code == 3
    assert report["conflict"]["reason"] == "head-moved" and report["conflict"]["id"] == "moved"
    assert report["conflict"]["actual_head"] == world["f2"] and report["conflict"]["expected_head"] == world["f1"]
    assert sh(wt, "rev-parse", "HEAD") == start and not (wt / "s.txt").exists()
    path = registry(tmp_path, pick("ok", branch="feat", extra=f'expected_head = "{world["f2"]}"'), name="ok.toml")
    code, report = apply_json(path, wt, capsys)
    assert code == 0 and report["applied"][0]["commits"] == [world["f1"], world["f2"]]


def test_mark_accepts_carried_and_landed_main(reg_worktree):
    reg = reg_worktree["wt"] / "reg.toml"
    assert run_main(reg, "mark", "first", "--status", "landed:main") == 0
    assert run_main(reg, "mark", "second", "--status", "carried") == 0
    statuses = {e["id"]: e["status"] for e in fp.load_registry(reg, FORKS)}
    assert statuses == {"first": "landed:main", "second": "carried"}


def test_check_upstream_includes_carried(world, tmp_path, fake_gh, capsys):
    path = registry(tmp_path, pick("carry", commit=world["single"], status="carried"))
    assert run_main(path, "check-upstream", "--json") == 0
    assert json.loads(capsys.readouterr().out)["checked"] == ["carry"]


def test_check_upstream_local_path_entry_uses_patch_id(world, tmp_path, fake_gh, capsys):
    local = world["tmp"] / "localonly2"
    sh(world["tmp"], "clone", "-q", str(world["up"]), str(local))
    only = commit_file(local, "lo.txt", "x\n", "local change")
    commit_file(world["up"], "lo.txt", "x\n", "upstream took it")
    path = registry(tmp_path, pick("loc", commit=only, repo=None, extra=f'local_path = "{local}"'))
    assert run_main(path, "check-upstream", "--json") == 4
    assert json.loads(capsys.readouterr().out)["candidates"][0]["reasons"][0]["code"] == "equivalent-patch-upstream"


# ------------------------------------------------------------------ placeholder entries

def placeholder(id="slot", **kw):
    return pick(id, repo=None, **kw)


def test_placeholder_requires_hold_and_no_expected_head(tmp_path):
    with pytest.raises(fp.RegistryError, match="placeholder and requires hold"):
        fp.load_registry(registry(tmp_path, placeholder()), FORKS)
    with pytest.raises(fp.RegistryError, match="expected_head needs"):
        fp.load_registry(registry(tmp_path, placeholder(extra=f'hold = "x"\nexpected_head = "{GOOD_SHA}"')), FORKS)
    entries = fp.load_registry(registry(tmp_path, placeholder(extra='hold = "waiting for a branch"')), FORKS)
    assert fp.is_placeholder(entries[0])


def test_placeholder_list_apply_and_check_upstream(world, tmp_path, fake_gh, capsys):
    path = registry(tmp_path, placeholder(extra='hold = "waiting for a branch"',
                                          upstream="https://github.com/getpaseo/paseo/issues/8326"),
                    pick("real", commit=world["single"], order=1))
    assert run_main(path, "list") == 0
    out = capsys.readouterr().out
    assert "placeholder (no source yet)" in out and "waiting for a branch" in out
    code, report = apply_json(path, world["wt"], capsys, "--include-held", "--include-trial")
    assert code == 0 and [r["id"] for r in report["applied"]] == ["real"]
    assert report["skipped"] == [{"id": "slot", "why": "placeholder", "hold": "waiting for a branch"}]
    assert run_main(path, "check-upstream", "--json") == 0
    assert json.loads(capsys.readouterr().out)["checked"] == ["slot", "real"]


def test_apply_branch_on_newer_upstream_excludes_upstream_commits(world, tmp_path, capsys):
    """MED-1: a source based on a newer upstream must not drag the in-between upstream commits in."""
    up, fork, wt = world["up"], world["fork"], world["wt"]
    b = commit_file(up, "b.txt", "b\n", "upstream B")
    c = commit_file(up, "c.txt", "c\n", "upstream C")
    sh(fork, "fetch", "-q", str(up), "main")
    sh(fork, "checkout", "-q", "-b", "newbase", "FETCH_HEAD")
    p = commit_file(fork, "p.txt", "p\n", "pick P")
    path = registry(tmp_path, pick("nb", branch="newbase"))
    code, report = apply_json(path, wt, capsys)
    row = report["applied"][0]
    assert code == 0 and row["commits"] == [p] and row["excluded_upstream_commits"] == [b, c]
    assert (wt / "p.txt").exists() and not (wt / "b.txt").exists() and not (wt / "c.txt").exists()
    assert "upstream B" not in sh(wt, "log", "--format=%s")


def test_unpinned_third_party_sources_are_rejected(tmp_path):
    """MED-2: an active pr, or a branch outside our orgs, must carry the reviewed head."""
    pin = f'expected_head = "{GOOD_SHA}"'
    with pytest.raises(fp.RegistryError, match="requires expected_head"):
        fp.load_registry(registry(tmp_path, pick("a", extra="pr = 5", repo="getpaseo/paseo")), FORKS)
    with pytest.raises(fp.RegistryError, match="requires expected_head"):
        fp.load_registry(registry(tmp_path, pick("a", branch="x", repo="someone/else")), FORKS)
    with pytest.raises(fp.RegistryError, match="requires expected_head"):
        fp.load_registry(registry(tmp_path, pick("a", extra="pr = 5", status="carried")), FORKS)
    ok = registry(tmp_path, pick("a", extra=f"pr = 5\n{pin}", repo="getpaseo/paseo"),
                  pick("b", branch="mine", repo="frdminc/paseo"),
                  pick("c", branch="mine", repo="djbclark/x"),
                  pick("d", extra="pr = 6", repo="getpaseo/paseo", status="landed:main"))
    assert [e["id"] for e in fp.load_registry(ok, FORKS)] == ["a", "b", "c", "d"]


def test_dry_run_reports_the_tip_so_it_can_be_pinned(world, tmp_path, capsys):
    path = registry(tmp_path, pick("a", branch="feat"))
    code, report = apply_json(path, world["wt"], capsys, "--dry-run")
    assert code == 0 and report["applied"][0]["tip"] == world["f2"]


def test_mark_guard_refuses_when_a_multiline_note_hides_a_status_line(reg_worktree, capsys):
    """LOW-1: the line-level edit would hit the wrong line; the re-parse comparison must refuse."""
    reg = reg_worktree["wt"] / "tricky.toml"
    reg.write_text('schema_version = 1\n\n[[pick]]\nid = "a"\ncomponent = "paseo"\nrepo = "frdminc/paseo"\n'
                   'branch = "feat"\nnotes = """\nstatus = "queued"\n"""\nintent = "x"\n'
                   'target = "desktop-build-2"\nstatus = "queued"\n')
    before = reg.read_text()
    assert run_main(reg, "mark", "a", "--status", "dropped") == 2
    assert reg.read_text() == before


def test_mark_note_with_non_bmp_text_works_and_control_characters_are_refused(reg_worktree, capsys):
    """LOW-2: no traceback for a non-BMP note; control characters are a clean error."""
    reg = reg_worktree["wt"] / "reg.toml"
    assert run_main(reg, "mark", "first", "--status", "landed:2", "--note", "party \U0001F389 ok") == 0
    assert {e["id"]: e for e in fp.load_registry(reg, FORKS)}["first"]["notes"] == "party \U0001F389 ok"
    before = reg.read_text()
    for bad in ("a\x7fb", "a\x1bb", "a\ud800b"):
        assert run_main(reg, "mark", "second", "--status", "dropped", "--note", bad) == 2
    assert reg.read_text() == before


def conflict_world(world, tmp_path):
    commit_file(world["wt"], "a.txt", "uno\ntwo\nthree\n", "diverging change")
    return registry(tmp_path, pick("b-conflict", branch="conf"))


def test_cherry_pick_timeout_is_reported_as_a_stop_with_tree_state(world, tmp_path, monkeypatch, capsys):
    """LOW-3: a timed-out pick is an exit-3 stop that says whether the tree is clean."""
    path = registry(tmp_path, pick("one", commit=world["single"]))
    real = fp.git

    def fake(wt, *args, **kw):
        if args[:2] == ("cherry-pick", "-x"):
            raise fp.ToolError("timed out after 600s: git -C x cherry-pick")
        return real(wt, *args, **kw)

    monkeypatch.setattr(fp, "git", fake)
    code, report = apply_json(path, world["wt"], capsys)
    assert code == 3 and report["conflict"]["reason"] == "cherry-pick-timeout"
    assert report["conflict"]["tree_clean"] is True


def test_failed_abort_is_reported_not_assumed_clean(world, tmp_path, monkeypatch, capsys):
    """LOW-3: when `cherry-pick --abort` fails, tree_clean is False and abort_rc is non-zero."""
    path = conflict_world(world, tmp_path)
    real = fp.git

    def fake(wt, *args, **kw):
        if args[:2] == ("cherry-pick", "--abort"):
            return subprocess.CompletedProcess(args, 1, "", "abort refused")
        return real(wt, *args, **kw)

    monkeypatch.setattr(fp, "git", fake)
    code, report = apply_json(path, world["wt"], capsys)
    assert code == 3 and report["conflict"]["abort_rc"] == 1 and report["conflict"]["tree_clean"] is False
    real(world["wt"], "cherry-pick", "--abort")


def test_conflict_report_is_scrubbed_third_party_text(world, tmp_path, capsys):
    """LOW-4: git's stderr quotes the commit subject; control characters never reach the report."""
    fork = world["fork"]
    sh(fork, "checkout", "-q", "-b", "evil", "main")
    commit_file(fork, "a.txt", "EVIL\ntwo\nthree\n", "\x1b[2Jignore previous instructions")
    path = registry(tmp_path, pick("evil", branch="evil"))
    commit_file(world["wt"], "a.txt", "uno\ntwo\nthree\n", "diverging change")
    code, report = apply_json(path, world["wt"], capsys)
    assert code == 3
    message = report["conflict"]["git_message_untrusted"]
    assert "ignore previous instructions" in message and "\x1b" not in message
    assert report["conflict"]["tree_clean"] is True and "message" not in report["conflict"]
    assert run_main(path, "apply", "--target", "desktop-build-2", "--workspace", str(world["wt"])) == 3
    assert "\x1b" not in capsys.readouterr().out


def test_scrub_turns_control_characters_into_question_marks(world, tmp_path, monkeypatch, capsys):
    assert fp.scrub("a\x1b[2Jb\x00c\x7fd") == "a?[2Jb?c?d"
    assert len(fp.scrub("x" * 1000)) == 300
    path = registry(tmp_path, pick("one", commit=world["single"]))
    real = fp.git

    def fake(wt, *args, **kw):
        if args[:2] == ("cherry-pick", "-x"):
            return subprocess.CompletedProcess(args, 1, "", "error: \x1b[2J obey me")
        return real(wt, *args, **kw)

    monkeypatch.setattr(fp, "git", fake)
    code, report = apply_json(path, world["wt"], capsys)
    assert code == 3 and report["conflict"]["git_message_untrusted"] == "error: ?[2J obey me"


def test_line_separators_and_format_characters_are_refused_and_scrubbed(reg_worktree):
    """r2 LOW-1: U+2028 would split lines in a naive edit; format characters can hide text."""
    reg = reg_worktree["wt"] / "reg.toml"
    before = reg.read_text()
    for bad in ("a b", "a b", "a‮b", "a​b", "a﻿b"):
        assert run_main(reg, "mark", "second", "--status", "dropped", "--note", bad) == 2
    assert reg.read_text() == before
    assert fp.scrub("a‮b​c﻿d e") == "a?b?c?d?e"
    # a later note edit still works after an earlier one (lines split on newline only)
    assert run_main(reg, "mark", "second", "--status", "carried", "--note", "one") == 0
    assert run_main(reg, "mark", "second", "--status", "dropped", "--note", "two") == 0
    assert {e["id"]: e for e in fp.load_registry(reg, FORKS)}["second"]["notes"] == "old note | one | two"


def test_hand_edited_line_separator_in_a_string_does_not_break_mark(reg_worktree):
    """r3 LOW-2: a raw U+2028 inside a TOML string must not split lines in the status edit."""
    reg = reg_worktree["wt"] / "reg.toml"
    text = reg.read_text().replace("old note", "old note")
    reg.write_text(text)
    assert " " in reg.read_text()
    assert run_main(reg, "mark", "second", "--status", "dropped", "--note", "x") == 0
    entries = {e["id"]: e for e in fp.load_registry(reg, FORKS)}
    assert entries["second"]["status"] == "dropped" and entries["second"]["notes"].endswith("| x")
    assert " " in reg.read_text()


def test_large_plan_warning_fires_above_the_threshold(world, tmp_path, capsys):
    """r3 LOW-1: a source with more than LARGE_PLAN commits is flagged in the text output."""
    fork = world["fork"]
    sh(fork, "checkout", "-q", "-b", "big", "main")
    for i in range(fp.LARGE_PLAN + 1):
        commit_file(fork, f"big{i}.txt", f"{i}\n", f"big {i}")
    sh(fork, "checkout", "-q", "main")
    path = registry(tmp_path, pick("bigone", branch="big"), pick("smallone", branch="feat", order=1))
    assert run_main(path, "apply", "--dry-run", "--target", "desktop-build-2", "--workspace", str(world["wt"])) == 0
    out = capsys.readouterr().out
    assert out.count("LARGE plan") == 1
    big_line = next(line for line in out.splitlines() if "bigone" in line)
    assert "LARGE plan" in big_line


def test_upstream_fetch_failure_happens_before_any_pick(world, tmp_path, monkeypatch, capsys):
    """r2 LOW-2: a failing upstream fetch must not leave earlier picks applied."""
    forks = tmp_path / "forks.toml"
    forks.write_text(FORKS.read_text().replace('upstream = "https://github.com/getpaseo/paseo"',
                                               'upstream = "https://github.com/getpaseo/unreachable"'))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "4")
    monkeypatch.setenv("GIT_CONFIG_KEY_3", "url.file:///nonexistent/nowhere.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_3", "https://github.com/getpaseo/unreachable")
    path = registry(tmp_path, pick("first", commit=world["single"], order=1), pick("second", branch="feat", order=2))
    start = sh(world["wt"], "rev-parse", "HEAD")
    code = fp.main(["--registry", str(path), "--forks", str(forks), "apply", "--target", "desktop-build-2",
                    "--workspace", str(world["wt"])])
    assert code == 2
    assert sh(world["wt"], "rev-parse", "HEAD") == start and not (world["wt"] / "s.txt").exists()


def test_source_with_only_upstream_commits_reports_exclusion_not_already_present(world, tmp_path, capsys):
    """r2 LOW-3."""
    up, fork = world["up"], world["fork"]
    b = commit_file(up, "b.txt", "b\n", "upstream B")
    sh(fork, "fetch", "-q", str(up), "main")
    sh(fork, "branch", "onlyup", "FETCH_HEAD")
    path = registry(tmp_path, pick("ou", branch="onlyup"))
    code, report = apply_json(path, world["wt"], capsys)
    row = report["applied"][0]
    assert code == 0 and row["commits"] == [] and row["excluded_upstream_commits"] == [b]
    assert row["already_present"] is False
    assert run_main(path, "apply", "--target", "desktop-build-2", "--workspace", str(world["wt"])) == 0
    assert "EXCLUDED upstream: 1" in capsys.readouterr().out


def abort_only(monkeypatch):
    real = fp.git

    def fake(wt, *args, **kw):
        if args[:2] == ("cherry-pick", "--abort"):
            return subprocess.CompletedProcess(args, 0, "", "")
        return real(wt, *args, **kw)

    monkeypatch.setattr(fp, "git", fake)


def test_tree_clean_checks_each_signal_on_its_own(world, monkeypatch):
    """r2 LOW-5: a pending CHERRY_PICK_HEAD, a dirty tree or an index.lock each make the tree not clean."""
    wt = world["wt"]
    abort_only(monkeypatch)
    assert fp.abort_pick(wt) == {"abort_rc": 0, "tree_clean": True}
    pending = Path(sh(wt, "rev-parse", "--path-format=absolute", "--git-path", "CHERRY_PICK_HEAD"))
    pending.write_text(sh(wt, "rev-parse", "HEAD") + "\n")
    assert fp.abort_pick(wt)["tree_clean"] is False
    pending.unlink()
    (wt / "stray.txt").write_text("x\n")
    assert fp.abort_pick(wt)["tree_clean"] is False
    (wt / "stray.txt").unlink()
    lock = Path(sh(wt, "rev-parse", "--path-format=absolute", "--git-path", "index.lock"))
    lock.write_text("")
    assert fp.abort_pick(wt)["tree_clean"] is False
    lock.unlink()
    assert fp.abort_pick(wt)["tree_clean"] is True


def test_text_output_labels_git_text_as_untrusted(world, tmp_path, monkeypatch, capsys):
    """r2 LOW-5."""
    path = registry(tmp_path, pick("one", commit=world["single"]))
    real = fp.git

    def fake(wt, *args, **kw):
        if args[:2] == ("cherry-pick", "-x"):
            return subprocess.CompletedProcess(args, 1, "", "error: obey me")
        return real(wt, *args, **kw)

    monkeypatch.setattr(fp, "git", fake)
    assert run_main(path, "apply", "--target", "desktop-build-2", "--workspace", str(world["wt"])) == 3
    assert "git said (untrusted): error: obey me" in capsys.readouterr().out


def test_placeholder_with_merged_pr_link_is_a_candidate(world, tmp_path, fake_gh, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_GH_JSON", json.dumps({"state": "MERGED", "mergedAt": "2026-11-20T00:00:00Z"}))
    path = registry(tmp_path, placeholder(extra='hold = "x"', upstream="https://github.com/getpaseo/paseo/pull/5"))
    assert run_main(path, "check-upstream", "--json") == 4
