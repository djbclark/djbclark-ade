"""gh-pr-checks self-registers a deadline for `gh pr checks --watch` unless opted out or already covered."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "gh-pr-checks"


def _load():
    # bin/gh-pr-checks uses `#!/usr/bin/env -S python3 -I`; importlib rejects that shebang.
    src = SCRIPT.read_text(encoding="utf-8")
    if src.startswith("#!"):
        src = src.split("\n", 1)[1]
    spec = importlib.util.spec_from_loader("gh_pr_checks", loader=None, origin=str(SCRIPT))
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    mod.__dict__["__file__"] = str(SCRIPT)
    exec(compile(src, str(SCRIPT), "exec"), mod.__dict__)
    return mod


def test_split_argv_budget_and_passthrough() -> None:
    mod = _load()
    budget, no_dl, rest = mod.split_argv(["--budget", "45m", "123", "--watch", "--required"])
    assert budget == "45m" and no_dl is False
    assert rest == ["123", "--watch", "--required"]
    budget, no_dl, rest = mod.split_argv(["--budget=10m", "--no-deadline", "--", "9", "--watch"])
    assert budget == "10m" and no_dl is True and rest == ["9", "--watch"]


def test_no_supervise_without_watch(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    monkeypatch.delenv("DEADLINE_NAME", raising=False)
    assert mod.maybe_supervise_under_deadline(["123"], budget="20m", no_deadline=False) is None


def test_no_supervise_when_no_deadline_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load()
    monkeypatch.delenv("DEADLINE_NAME", raising=False)
    assert mod.maybe_supervise_under_deadline(["123", "--watch"], budget="20m", no_deadline=True) is None


def test_no_supervise_when_already_under_deadline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mod = _load()
    monkeypatch.setenv("DEADLINE_NAME", "caller")
    fake = tmp_path / "deadline"
    fake.write_text("#!/bin/sh\nexit 99\n")
    fake.chmod(0o755)
    monkeypatch.setenv("DEADLINE_BIN", str(fake))
    assert mod.maybe_supervise_under_deadline(["123", "--watch"], budget="20m", no_deadline=False) is None


def test_supervise_invokes_deadline_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mod = _load()
    monkeypatch.delenv("DEADLINE_NAME", raising=False)
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-test")
    monkeypatch.setenv("GH_BIN", str(tmp_path / "gh"))
    seen = tmp_path / "seen"
    fake = tmp_path / "deadline"
    fake.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{seen}"\n'
        "exit 17\n"
    )
    fake.chmod(0o755)
    monkeypatch.setenv("DEADLINE_BIN", str(fake))
    rc = mod.maybe_supervise_under_deadline(["42", "--watch", "--required"], budget="20m", no_deadline=False)
    assert rc == 17
    args = seen.read_text().splitlines()
    assert args[0] == "run"
    assert "--owner" in args and "agent-test" in args
    assert "--name" in args and any(a.startswith("gh-pr-checks-") for a in args)
    assert "--budget" in args and "20m" in args
    assert "--on-expire" in args and "kill" in args
    assert "--heartbeat" not in args
    dash = args.index("--")
    assert args[dash + 1 :] == [str(tmp_path / "gh"), "pr", "checks", "42", "--watch", "--required"]


def test_missing_deadline_falls_through(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mod = _load()
    monkeypatch.delenv("DEADLINE_NAME", raising=False)
    monkeypatch.setenv("DEADLINE_BIN", str(tmp_path / "missing"))
    assert mod.maybe_supervise_under_deadline(["1", "--watch"], budget="20m", no_deadline=False) is None


def test_run_gh_forwards(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mod = _load()
    seen = tmp_path / "gh-seen"
    gh = tmp_path / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{seen}"\n'
        "exit 3\n"
    )
    gh.chmod(0o755)
    monkeypatch.setenv("GH_BIN", str(gh))
    assert mod.run_gh(["7", "--json", "name"]) == 3
    assert seen.read_text().splitlines() == ["pr", "checks", "7", "--json", "name"]


def test_main_watch_under_deadline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mod = _load()
    monkeypatch.delenv("DEADLINE_NAME", raising=False)
    monkeypatch.setenv("GH_BIN", str(tmp_path / "gh"))
    seen = tmp_path / "seen"
    fake = tmp_path / "deadline"
    fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{seen}"\nexit 11\n')
    fake.chmod(0o755)
    monkeypatch.setenv("DEADLINE_BIN", str(fake))
    assert mod.main(["--budget=15m", "88", "--watch"]) == 11
    args = seen.read_text().splitlines()
    assert "15m" in args and "--watch" in args
