"""Offline tests for bin/ade_ws_autoname.py (the window-naming decision) and plugins/ade-window-name (its Paseo hook wrapper)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import ade_ws_autoname as an  # noqa: E402
import ade_ws_names as wsn  # noqa: E402

LEAD = "8cd86203-d33b-49db-abde-9baba52bcf61"


def git_repo(tmp_path: Path, name: str = "my-repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True, env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")})
    return repo


def info(cwd, **over):
    base = {"cwd": str(cwd), "windowTitle": None, "firstAgent": True, "agent": {"title": "Fix the thing"}}
    base.update(over)
    return base


def test_operator_started_first_agent_is_main(tmp_path):
    d = an.decide(info(git_repo(tmp_path)))
    assert d == {"action": "rename", "name": "MAIN my-repo (Fix the thing)", "kind": "MAIN", "repo": "my-repo", "work": "Fix the thing"}
    assert wsn.parse(d["name"]) == ("MAIN", "my-repo", "Fix the thing")  # the builder/parser round trip: no second format


def test_linked_worktree_reads_as_its_main_repo(tmp_path):
    repo = git_repo(tmp_path)
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x"],
                   check=True, capture_output=True, env=env)
    wt = tmp_path / "my-repo-feature-wt"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", "feature", str(wt)], check=True, capture_output=True, env=env)
    assert an.decide(info(wt))["repo"] == "my-repo"


@pytest.mark.parametrize("agent", [
    {"title": "Review", "parentAgentId": "lead-agent"},
    {"title": "Review", "labels": {"ade.lead": LEAD}},
    {"title": "Review", "labels": {"ade.placement": "workers"}},
])
def test_worker_window_is_workers(tmp_path, agent):
    assert an.decide(info(git_repo(tmp_path), agent=agent))["kind"] == "WORKERS"


def test_placement_label_can_say_main_or_user_but_user_is_never_a_guess(tmp_path):
    repo = git_repo(tmp_path)
    assert an.decide(info(repo, agent={"title": "t", "labels": {"ade.placement": "user"}}))["kind"] == "USER"
    assert an.decide(info(repo, agent={"title": "t", "parentAgentId": "p", "labels": {"ade.placement": "main"}}))["kind"] == "MAIN"
    assert an.decide(info(repo, agent={"title": "t"}))["kind"] == "MAIN"
    assert an.decide(info(repo, agent={"title": "t", "labels": {"ade.placement": "bogus"}}))["kind"] == "MAIN"


@pytest.mark.parametrize("title", ["my own name", "MAIN my-repo (x)", "WORKERS my-repo (Wave 7)", "master", " x"])
def test_a_title_set_on_purpose_is_left_alone(tmp_path, title):
    d = an.decide(info(git_repo(tmp_path), windowTitle=title))
    assert d["action"] == "skip" and d["retry"] is False


@pytest.mark.parametrize("over", [{"background": True}, {"firstAgent": False}, {"firstAgent": "yes"}, {"cwd": ""}, {"cwd": None}, {"windowTitle": 5}])
def test_skips(tmp_path, over):
    assert an.decide(info(git_repo(tmp_path), **over))["action"] == "skip"


def test_not_first_agent_asks_for_a_retry(tmp_path):
    d = an.decide(info(git_repo(tmp_path), firstAgent=False))
    assert d["action"] == "skip" and d["retry"] is True


def test_null_and_blank_window_title_count_as_default(tmp_path):
    assert an.decide(info(git_repo(tmp_path), windowTitle="  "))["action"] == "rename"  # Paseo trims a title to null; so do we
    assert an.decide(info(git_repo(tmp_path), windowTitle=None))["action"] == "rename"


def test_non_git_and_missing_cwd_use_the_directory_name(tmp_path):
    plain = tmp_path / "plain-dir"
    plain.mkdir()
    assert an.decide(info(plain))["name"] == "MAIN plain-dir (Fix the thing)"
    assert an.decide(info(tmp_path / "does-not-exist"))["repo"] == "does-not-exist"


def test_a_repo_name_that_cannot_be_a_window_name_part_is_skipped(tmp_path):
    bad = tmp_path / "has space"
    bad.mkdir()
    d = an.decide(info(bad))
    assert d["action"] == "skip" and d["retry"] is False


def test_no_agent_title_yet_asks_for_a_retry(tmp_path):
    d = an.decide(info(git_repo(tmp_path), agent={"title": None}))
    assert d["action"] == "skip" and d["retry"] is True
    assert an.decide(info(git_repo(tmp_path), agent={"title": "   "}))["retry"] is True


@pytest.mark.parametrize("title,work", [
    (f"worker auto-naming {LEAD}", "auto-naming"),
    ("LEAD my-repo Wave 7", "Wave 7"),
    ("main my-repo Wave 7", "Wave 7"),
    ("my-repo cleanup", "cleanup"),
    ("fix (a) and (b)", "fix [a] and [b]"),
    ("two\nlines  here\t!", "two lines here !"),
    ("x" * 120, "x" * 50),
    ("word " * 30, "word word word word word word word word word"),
])
def test_work_text(title, work):
    assert an.work_from_title(title, "my-repo") == work


def test_work_text_never_empty_or_just_the_repo():
    for t in (None, 5, "", "  ", "my-repo", "LEAD my-repo"):
        assert an.work_from_title(t, "my-repo") is None


def test_every_built_name_is_valid_for_the_shared_parser(tmp_path):
    repo = git_repo(tmp_path)
    for title in ["a (b) c", "x" * 200, "LEAD my-repo Wave 7", f"worker s {LEAD}", "ünïcode ✓ title"]:
        d = an.decide(info(repo, agent={"title": title}))
        assert d["action"] == "rename", title
        assert wsn.parse(d["name"]) is not None and len(d["name"]) <= wsn.NAME_LIMIT


def test_cli_reads_json_on_stdin_and_exits_nonzero_on_garbage(tmp_path):
    script = ROOT / "bin" / "ade_ws_autoname.py"
    ok = subprocess.run([sys.executable, str(script)], input=json.dumps(info(git_repo(tmp_path))), capture_output=True, text=True, timeout=30)
    assert ok.returncode == 0 and json.loads(ok.stdout)["name"] == "MAIN my-repo (Fix the thing)"
    bad = subprocess.run([sys.executable, str(script)], input="not json", capture_output=True, text=True, timeout=30)
    assert bad.returncode == 2 and bad.stdout == ""


def test_ade_window_name_plugin_node_tests():
    """plugins/ade-window-name/server/name-lib.test.mjs: hook wiring, default-name detection, worker window, non-git cwd (real decision script)."""
    node = shutil.which("node")
    assert node, "Node is required to validate the ade-window-name Paseo plugin"
    env = {k: v for k, v in os.environ.items() if k not in ("ADE_WS_AUTONAME_PY", "ADE_WINDOW_NAME_DRY_RUN", "ADE_PYTHON")}
    r = subprocess.run([node, "--test", str(ROOT / "plugins" / "ade-window-name" / "server" / "name-lib.test.mjs")],
                       capture_output=True, text=True, timeout=120, env=env)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-1500:]
