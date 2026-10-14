"""Unit tests for bin/crush-context-check: what Crush would load, the symlink double-count, the answers."""
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "crush-context-check"


def run(tmp, *, answer="", files=None, symlink=False, extra=()):
    proj = tmp / "proj"
    proj.mkdir(exist_ok=True)
    for name, text in (files or {}).items():
        f = proj / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    if symlink:
        (proj / "CLAUDE.md").symlink_to("AGENTS.md")
    home = tmp / "home"
    (home / ".config/crush").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HOME=str(home), CRUSH_GLOBAL_CONFIG=str(home / ".config/crush"),
               CRUSH_CONTEXT_OK_FILE=str(tmp / "ok.txt"))
    env.pop("CRUSH_CONTEXT_OK", None)
    return subprocess.run([sys.executable, str(SCRIPT), "--cwd", str(proj), "--force-interactive", *extra],
                          input=answer + "\n", capture_output=True, text=True, env=env)


def test_nothing_to_load_is_silent(tmp_path):
    r = run(tmp_path)
    assert r.returncode == 0 and r.stdout == ""


def test_lists_files_and_asks_decline(tmp_path):
    r = run(tmp_path, files={"AGENTS.md": "x" * 2700})
    assert r.returncode == 1
    assert "AGENTS.md  2,700 bytes (~1,000 tokens)" in r.stdout
    assert "Not started" in r.stdout


def test_yes_starts(tmp_path):
    assert run(tmp_path, answer="y", files={"AGENTS.md": "x"}).returncode == 0


def test_symlink_pair_counted_twice(tmp_path):
    r = run(tmp_path, answer="y", files={"AGENTS.md": "x" * 2700}, symlink=True)
    assert "Crush sends it twice" in r.stdout
    assert "total ~2,000 tokens" in r.stdout


def test_over_window_flagged(tmp_path):
    r = run(tmp_path, files={"AGENTS.md": "x" * 40000})
    assert "ABOVE the summarize trigger" in r.stdout


def test_always_remembers_until_file_changes(tmp_path):
    assert run(tmp_path, answer="a", files={"AGENTS.md": "one"}).returncode == 0
    again = run(tmp_path)  # no answer given: remembered, so no question
    assert again.returncode == 0 and again.stdout == ""
    (tmp_path / "proj" / "AGENTS.md").write_text("changed content")
    assert run(tmp_path).returncode == 1


def test_global_crush_md_listed_and_cursor_rules_dir(tmp_path):
    (tmp_path / "home/.config/crush").mkdir(parents=True)
    (tmp_path / "home/.config/crush/CRUSH.md").write_text("rules")
    r = run(tmp_path, files={".cursor/rules/a.mdc": "r"})
    assert ".cursor/rules/a.mdc" in r.stdout and "CRUSH.md" in r.stdout


def test_skip_env_and_no_tty(tmp_path):
    env = dict(os.environ, CRUSH_CONTEXT_OK="1")
    (tmp_path / "AGENTS.md").write_text("x")
    assert subprocess.run([sys.executable, str(SCRIPT), "--cwd", str(tmp_path), "--force-interactive"],
                          input="\n", capture_output=True, text=True, env=env).returncode == 0
    assert subprocess.run([sys.executable, str(SCRIPT), "--cwd", str(tmp_path)], stdin=subprocess.DEVNULL,
                          capture_output=True, text=True).returncode == 0
