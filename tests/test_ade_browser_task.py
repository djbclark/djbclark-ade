"""ade-browser-task: list / render / dry-run relay / secret + widen refusal."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
sys.path.insert(0, str(BIN))
import ade_browser_task as abt  # noqa: E402


def _run(*args: str, root: Path | None = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, "-I", "-B", str(BIN / "ade-browser-task"), *args]
    if root is not None:
        argv[4:4] = ["--root", str(root)]
    return subprocess.run(
        argv, capture_output=True, text=True, cwd=str(REPO), check=False
    )


def _fixture_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "prompts" / "browser").mkdir(parents=True)
    (root / "config").mkdir(parents=True)
    (root / "config" / "github.toml").write_text(
        "schema_version = 1\n\n"
        "[github]\n"
        'owner = "djbclark"\n'
        'repository = "djbclark-ade"\n'
        'app_name = "ade-merge-gate"\n'
        'manifest = ".github/app-manifest.json"\n'
    )
    for name, body in (
        (
            "issue-access.md",
            "---\n"
            "title: Restrict issue creation\n"
            "url: https://github.com/{{owner}}/{{repo}}/settings/general\n"
            "widens_access: false\n"
            "---\n"
            "Open https://github.com/{{owner}}/{{repo}}/settings/general\n"
            "Set Issues creation to Collaborators only on {{owner_repo}}.\n"
            "Change nothing else; report before and after; ask on surprise.\n",
        ),
        (
            "github-app-create.md",
            "---\n"
            "title: Create App\n"
            "url: https://github.com/settings/apps/new\n"
            "widens_access: false\n"
            "---\n"
            "Create {{app_name}} from {{manifest}} for {{owner_repo}}.\n"
            "Change nothing else; report before and after; ask on surprise.\n",
        ),
    ):
        (root / "prompts" / "browser" / name).write_text(body)
    return root


def test_repo_templates_list_and_render_clean():
    proc = _run("list", "--json", root=REPO)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True
    ids = {t["id"] for t in payload["tasks"]}
    assert {"github-app-create", "pr-access", "issue-access"} <= ids

    # Master tip has no config/github.toml (that lives with S8 github-setup); pass flags.
    proc_r = _run(
        "render", "issue-access", "--json",
        "--owner", "djbclark", "--repo", "djbclark-ade",
        root=REPO,
    )
    assert proc_r.returncode == 0, proc_r.stderr
    rendered = json.loads(proc_r.stdout)
    assert rendered["ok"] is True
    assert "djbclark/djbclark-ade" in rendered["prompt"]
    assert rendered["url"] == (
        "https://github.com/djbclark/djbclark-ade/settings/general"
    )
    assert "Change nothing else" in rendered["prompt"] or "change nothing else" in (
        rendered["prompt"].lower()
    )


def test_list_render_relay_dry_run_fixture(tmp_path):
    root = _fixture_root(tmp_path)
    proc = _run("list", "--json", root=root)
    assert proc.returncode == 0, proc.stderr
    ids = {t["id"] for t in json.loads(proc.stdout)["tasks"]}
    assert ids == {"github-app-create", "issue-access"}

    proc_r = _run(
        "render",
        "issue-access",
        "--owner",
        "acme",
        "--repo",
        "widgets",
        "--json",
        root=root,
    )
    assert proc_r.returncode == 0, proc_r.stderr
    body = json.loads(proc_r.stdout)
    assert "acme/widgets" in body["prompt"]
    assert body["url"].endswith("/acme/widgets/settings/general")

    proc_d = _run("relay", "github-app-create", "--dry-run", "--json", root=root)
    assert proc_d.returncode == 0, proc_d.stderr
    dry = json.loads(proc_d.stdout)
    assert dry["status"] == "dry-run"
    assert dry["prompt"] and "ade-merge-gate" in dry["prompt"]


def test_relay_send_unsent_without_coding_bot(tmp_path):
    root = _fixture_root(tmp_path)
    rendered = abt.render_task(root, "issue-access")
    result = abt.relay_task(rendered, dry_run=False, coding_bot=None)
    assert result.status == "unsent"
    assert result.prompt and "Collaborators only" in result.prompt
    assert "never claim sent" in result.detail

    # CLI --send with coding-bot absent from PATH → unsent, exit 0.
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    env = {**os.environ, "PATH": str(empty)}
    argv = [
        sys.executable,
        "-I",
        "-B",
        str(BIN / "ade-browser-task"),
        "--root",
        str(root),
        "relay",
        "issue-access",
        "--send",
        "--json",
    ]
    proc = subprocess.run(
        argv, capture_output=True, text=True, cwd=str(REPO), check=False, env=env
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "unsent"
    assert payload.get("prompt")


def test_relay_send_with_fake_coding_bot(tmp_path):
    root = _fixture_root(tmp_path)
    rendered = abt.render_task(root, "github-app-create")
    calls: list[tuple[list[str], str | None]] = []

    def fake_runner(argv: list[str], *, input_text: str | None = None):
        calls.append((list(argv), input_text))
        return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")

    result = abt.relay_task(
        rendered,
        dry_run=False,
        coding_bot="/fake/coding-bot",
        runner=fake_runner,
    )
    assert result.status == "sent"
    assert calls and calls[0][0] == ["/fake/coding-bot", "ask", "-"]
    assert calls[0][1] and "ade-merge-gate" in calls[0][1]
    assert "neither completion" in result.detail


def test_refuse_widen_frontmatter_and_task_id(tmp_path):
    root = _fixture_root(tmp_path)
    bad = root / "prompts" / "browser" / "sneaky.md"
    bad.write_text(
        "---\nurl: https://github.com/settings\nwidens_access: true\n---\n"
        "Add a collaborator.\n"
    )
    with pytest.raises(abt.BrowserTaskError, match="widens_access"):
        abt.load_template(bad, task_id="sneaky")

    with pytest.raises(abt.BrowserTaskError, match="widens access"):
        abt.validate_task_id("add-collaborator")


def test_refuse_non_github_url_and_bad_owner(tmp_path):
    root = _fixture_root(tmp_path)
    evil = root / "prompts" / "browser" / "evil-host.md"
    evil.write_text(
        "---\nurl: https://evil.example/{{owner}}\nwidens_access: false\n---\n"
        "Go to {{owner}}.\n"
    )
    with pytest.raises(abt.BrowserTaskError, match="https://github.com/"):
        abt.render_task(root, "evil-host", owner="djbclark", repo="x")

    with pytest.raises(abt.BrowserTaskError, match="owner must match"):
        abt.render_task(root, "issue-access", owner="../etc", repo="x")


def test_refuse_secret_argv_pem_and_flags():
    with pytest.raises(abt.BrowserTaskError, match="secret material"):
        abt.refuse_secret_argv(
            ["relay", "issue-access", "-----BEGIN RSA PRIVATE KEY-----\nMII"]
        )
    with pytest.raises(abt.BrowserTaskError, match="secret flag"):
        abt.refuse_secret_argv(["relay", "--token", "abc"])
    proc = _run("list", "--private-key", "/tmp/x.pem")
    assert proc.returncode == 2
    assert "refuse" in proc.stderr.lower()
    # Equals-form: message names the flag only (never the value).
    proc2 = _run("list", "--token=super-secret-value")
    assert proc2.returncode == 2
    assert "super-secret-value" not in proc2.stderr
    assert "--token" in proc2.stderr


def test_missing_task_exits_1(tmp_path):
    root = _fixture_root(tmp_path)
    proc = _run("render", "no-such-task", "--json", root=root)
    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["ok"] is False


def test_root_after_subcommand_matches_just_recipes(tmp_path):
    """Just recipes put --root after the subcommand; that order must parse."""
    root = _fixture_root(tmp_path)
    argv = [
        sys.executable,
        "-I",
        "-B",
        str(BIN / "ade-browser-task"),
        "list",
        "--root",
        str(root),
        "--json",
    ]
    proc = subprocess.run(
        argv, capture_output=True, text=True, cwd=str(REPO), check=False
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["ok"] is True

    argv_r = [
        sys.executable,
        "-I",
        "-B",
        str(BIN / "ade-browser-task"),
        "relay",
        "github-app-create",
        "--dry-run",
        "--root",
        str(root),
        "--json",
    ]
    proc_r = subprocess.run(
        argv_r, capture_output=True, text=True, cwd=str(REPO), check=False
    )
    assert proc_r.returncode == 0, proc_r.stderr
    assert json.loads(proc_r.stdout)["status"] == "dry-run"


def test_send_and_dry_run_are_mutually_exclusive(tmp_path):
    root = _fixture_root(tmp_path)
    # Fake coding-bot on PATH so a silent --send win would actually send.
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_bot = fake_bin / "coding-bot"
    fake_bot.write_text("#!/bin/sh\nexit 0\n")
    fake_bot.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}"}
    argv = [
        sys.executable,
        "-I",
        "-B",
        str(BIN / "ade-browser-task"),
        "relay",
        "issue-access",
        "--send",
        "--dry-run",
        "--root",
        str(root),
        "--json",
    ]
    proc = subprocess.run(
        argv, capture_output=True, text=True, cwd=str(REPO), check=False, env=env
    )
    assert proc.returncode == 2
    assert "not allowed with" in proc.stderr or "mutually exclusive" in proc.stderr.lower()
    assert "sent" not in (proc.stdout or "").lower()
