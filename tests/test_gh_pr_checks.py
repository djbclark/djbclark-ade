"""gh-pr-checks self-registers a deadline for `gh pr checks --watch` unless opted out or already covered."""
from __future__ import annotations

import importlib.util
import os
import signal
import subprocess
import sys
import time
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


def _fake_deadline_that_marks(tmp_path: Path, *, exit_code: int, seen: Path) -> Path:
    """Simulates a successful deadline run: touches the start mark, records argv, exits."""
    fake = tmp_path / "deadline"
    fake.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{seen}"\n'
        'if [ -n "${DEADLINE_WAIT_MARK:-}" ]; then : > "$DEADLINE_WAIT_MARK"; fi\n'
        f"exit {exit_code}\n"
    )
    fake.chmod(0o755)
    return fake


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
    fake = _fake_deadline_that_marks(tmp_path, exit_code=17, seen=seen)
    monkeypatch.setenv("DEADLINE_BIN", str(fake))
    rc = mod.maybe_supervise_under_deadline(
        ["42", "--watch", "--required"],
        budget="20m",
        no_deadline=False,
        self_argv=["--budget", "20m", "42", "--watch", "--required"],
    )
    assert rc == 17
    args = seen.read_text().splitlines()
    assert args[0] == "run"
    assert "--owner" in args and "agent-test" in args
    assert "--name" in args and any(a.startswith("gh-pr-checks-") for a in args)
    assert "--budget" in args and "20m" in args
    assert "--on-expire" in args and "kill" in args
    assert "--heartbeat" not in args
    dash = args.index("--")
    # re-execs this wrapper (so the supervised copy can touch the start mark), not gh directly
    assert args[dash + 1] == str(SCRIPT)
    assert args[dash + 2 :] == ["--budget", "20m", "42", "--watch", "--required"]


def test_missing_deadline_falls_through(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mod = _load()
    monkeypatch.delenv("DEADLINE_NAME", raising=False)
    monkeypatch.setenv("DEADLINE_BIN", str(tmp_path / "missing"))
    assert mod.maybe_supervise_under_deadline(["1", "--watch"], budget="20m", no_deadline=False) is None


def test_deadline_refuse_before_watch_falls_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    """Exit 2 / crash before the start mark: Never costs the wait — fall through to raw gh."""
    mod = _load()
    monkeypatch.delenv("DEADLINE_NAME", raising=False)
    refuse = tmp_path / "deadline"
    refuse.write_text("#!/bin/sh\nexit 2\n")  # name collision / refuse: never launches the command
    refuse.chmod(0o755)
    monkeypatch.setenv("DEADLINE_BIN", str(refuse))
    gh_seen = tmp_path / "gh-seen"
    gh = tmp_path / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{gh_seen}"\n'
        "exit 5\n"
    )
    gh.chmod(0o755)
    monkeypatch.setenv("GH_BIN", str(gh))
    assert mod.main(["99", "--watch", "--required"]) == 5
    assert gh_seen.read_text().splitlines() == ["pr", "checks", "99", "--watch", "--required"]
    err = capsys.readouterr().err
    assert "did not run the watch" in err and "exit 2" in err


def test_supervised_copy_touches_mark(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mod = _load()
    mark = tmp_path / "started"
    monkeypatch.setenv("DEADLINE_NAME", "gh-pr-checks-1")
    monkeypatch.setenv(mod.ENV_NAME, "gh-pr-checks-1")
    monkeypatch.setenv(mod.ENV_MARK, str(mark))
    monkeypatch.setenv(mod.ENV_SUP, "1")
    assert mod.maybe_supervise_under_deadline(["1", "--watch"], budget="20m", no_deadline=False) is None
    assert mark.is_file()
    assert mod.ENV_MARK not in os.environ and mod.ENV_NAME not in os.environ and mod.ENV_SUP not in os.environ


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
    fake = _fake_deadline_that_marks(tmp_path, exit_code=11, seen=seen)
    monkeypatch.setenv("DEADLINE_BIN", str(fake))
    assert mod.main(["--budget=15m", "88", "--watch"]) == 11
    args = seen.read_text().splitlines()
    assert "15m" in args and "--watch" in args
    assert args[args.index("--") + 1] == str(SCRIPT)


def test_sigterm_is_forwarded_to_deadline_supervisor(tmp_path: Path) -> None:
    """SIGTERM to the wrapper reaches `deadline run` (Codex P2); without forwarding the watch would detach."""
    sig_seen = tmp_path / "sig"
    ready = tmp_path / "ready"
    fake = tmp_path / "deadline"
    # own session: sleep until SIGTERM, record it, exit 143; touch mark so the wrapper does not fall back
    fake.write_text(
        "#!/bin/sh\n"
        'if [ -n "${DEADLINE_WAIT_MARK:-}" ]; then : > "$DEADLINE_WAIT_MARK"; fi\n'
        f'trap \'echo TERM > "{sig_seen}"; exit 143\' TERM\n'
        f': > "{ready}"\n'
        "while :; do sleep 0.05; done\n"
    )
    fake.chmod(0o755)
    env = {
        **os.environ,
        "DEADLINE_BIN": str(fake),
        "GH_BIN": str(tmp_path / "missing-gh"),
    }
    env.pop("DEADLINE_NAME", None)
    p = subprocess.Popen(
        [sys.executable, str(SCRIPT), "1", "--watch"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.time() + 5
    while time.time() < deadline and not ready.exists():
        if p.poll() is not None:
            out, err = p.communicate()
            raise AssertionError(f"wrapper exited early rc={p.returncode} err={err!r}")
        time.sleep(0.05)
    assert ready.exists(), "fake deadline never started"
    p.send_signal(signal.SIGTERM)
    try:
        out, err = p.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()
        raise
    assert p.returncode == 143, (p.returncode, out, err)
    assert sig_seen.read_text().strip() == "TERM"
