"""autorename: the Claude Code session id comes from the process registry, not the inherited env var (2026-11-02).

A session started from another session's environment (`/baton`, `/handoff`, a Paseo agent launched from a
predecessor's shell) keeps the predecessor's CLAUDE_CODE_SESSION_ID in its tool shells while
`<config>/sessions/<pid>.json` names its own session. Reproduced: env e236fcc3 had no transcript at all
("autorename: no transcript for session e236fcc3..."), the running session was 7c96a0ca.

The registry file is the one of `CLAUDE_PID` (Claude Code sets it, with CLAUDE_CODE_SESSION_ID, to its own pid in every
child shell), never "the nearest ancestor with a file": a nested unregistered Claude would then rename its parent's
session (adversary BLOCK on PR 259)."""

from __future__ import annotations

import importlib.util
import calendar
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

SKILL = Path(__file__).resolve().parent.parent / "skills/autorename"
STALE = "e236fcc3-287f-4c89-b6f4-435db7aef10c"
LIVE = "7c96a0ca-bb70-4584-a254-f33bb399de58"
OTHER = "08bd3978-0f3a-4a31-86e3-33a073fd62be"


def load() -> Any:
    spec = importlib.util.spec_from_file_location("autorename", SKILL / "autorename.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ar = load()


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    for var in ("OMPCODE", "GROK_SESSION_ID", "GROK_AGENT", "CURSOR_CONVERSATION_ID", "CURSOR_AGENT",
                "OPENCODE_SESSION_ID", "CODEX_THREAD_ID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", STALE)
    monkeypatch.delenv("CLAUDE_PID", raising=False)
    monkeypatch.setattr(ar, "STATE_DIR", tmp_path / "state")
    (tmp_path / "sessions").mkdir()
    return tmp_path


def register(cfg: Path, pid: int, sid: Any, *, file_pid: Any = None, proc_start: str | None = None) -> None:
    rec: dict[str, Any] = {"pid": pid if file_pid is None else file_pid, "sessionId": sid, "kind": "interactive"}
    if proc_start is not None:
        rec["procStart"] = proc_start
    (cfg / "sessions" / f"{pid}.json").write_text(json.dumps(rec), encoding="utf-8")


def transcript(cfg: Path, sid: str, project: str = "-Users-x", title: str | None = None) -> Path:
    path = cfg / "projects" / project / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"type": "user", "sessionId": sid})]
    if title:
        lines.append(json.dumps({"type": "custom-title", "customTitle": title, "sessionId": sid}, separators=(",", ":")))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def own(monkeypatch: pytest.MonkeyPatch, pid: int, ancestors: list[int]) -> None:
    """This shell belongs to the Claude Code process `pid`, whose chain of ancestors is `ancestors`."""
    monkeypatch.setenv("CLAUDE_PID", str(pid))
    monkeypatch.setattr(ar, "ancestor_pids", lambda: ancestors)


def test_registry_overrides_stale_env(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    register(cfg, 222, LIVE)
    own(monkeypatch, 222, [111, 222, 1000])
    assert ar.session_id() == LIVE


def test_nested_unregistered_claude_keeps_its_own_env_id_not_the_parents(
    cfg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # lead Claude 333 (registered) -> shell -> `claude -p` child 222 (no registry file) -> its shell runs autorename.
    # Claude sets CLAUDE_PID=222 for the child's shell: the farther registered ancestor must not win.
    register(cfg, 333, LIVE)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", OTHER)
    own(monkeypatch, 222, [111, 222, 250, 333])
    assert ar.session_id() == OTHER


def test_no_claude_pid_falls_back_to_env(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    register(cfg, 222, LIVE)
    monkeypatch.setattr(ar, "ancestor_pids", lambda: [111, 222])
    assert ar.session_id() == STALE


def test_claude_pid_that_is_not_an_ancestor_is_ignored(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    register(cfg, 555, LIVE)  # an inherited, stale CLAUDE_PID of a session that is not above this process
    own(monkeypatch, 555, [111, 222])
    assert ar.session_id() == STALE


@pytest.mark.parametrize("bad", ["not-a-uuid", "", 7, None, [LIVE]])
def test_unusable_registry_entry_falls_back_to_env(cfg: Path, monkeypatch: pytest.MonkeyPatch, bad: Any) -> None:
    register(cfg, 222, bad)
    own(monkeypatch, 222, [222])
    assert ar.session_id() == STALE


@pytest.mark.parametrize("raw", ["", "abc", "0", "1", "-5", "22 2"])
def test_malformed_claude_pid_is_ignored(cfg: Path, monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    register(cfg, 222, LIVE)
    monkeypatch.setenv("CLAUDE_PID", raw)
    monkeypatch.setattr(ar, "ancestor_pids", lambda: [1, 222])
    assert ar.session_id() == STALE


def test_registry_file_naming_another_pid_is_not_trusted(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    register(cfg, 222, LIVE, file_pid=999)
    own(monkeypatch, 222, [222])
    assert ar.session_id() == STALE


def test_non_object_or_broken_registry_file_falls_back_to_env(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (cfg / "sessions" / "222.json").write_text("[1]", encoding="utf-8")
    own(monkeypatch, 222, [222])
    assert ar.session_id() == STALE
    (cfg / "sessions" / "222.json").write_text("{broken", encoding="utf-8")
    assert ar.session_id() == STALE


PS_LSTART = "Mon Nov  2 16:36:39 2026"  # what `TZ=UTC ps -o lstart=` prints
FMT = "%a %b %d %H:%M:%S %Y"


def fake_ps(monkeypatch: pytest.MonkeyPatch, stdout: str) -> None:
    def run(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        assert cmd[:3] == ["ps", "-o", "lstart="], cmd
        # the same environment Claude Code uses to write procStart: UTC, so no local-time conversion
        assert kw["env"]["TZ"] == "UTC" and kw["env"]["LC_ALL"] == "C", kw["env"]
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(ar.subprocess, "run", run)


def utc_stamp(offset_s: int = 0, base: str = PS_LSTART) -> str:
    """A `procStart` `offset_s` seconds from `base` (both UTC text, as Claude Code writes them)."""
    return time.strftime(FMT, time.gmtime(calendar.timegm(time.strptime(base, FMT)) + offset_s))


def test_proc_start_that_matches_the_live_process_is_trusted(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    register(cfg, 222, LIVE, proc_start=utc_stamp())
    own(monkeypatch, 222, [222])
    fake_ps(monkeypatch, PS_LSTART + "\n")
    assert ar.session_id() == LIVE


def test_recycled_pid_with_other_proc_start_is_not_trusted(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # a crashed Claude left 222.json behind; pid 222 now belongs to a process started an hour later
    register(cfg, 222, LIVE, proc_start=utc_stamp(-3600))
    own(monkeypatch, 222, [222])
    fake_ps(monkeypatch, PS_LSTART + "\n")
    assert ar.session_id() == STALE


@pytest.mark.parametrize("ps_out", ["", "garbage\n"])
def test_unreadable_ps_start_does_not_veto_the_registry(cfg: Path, monkeypatch: pytest.MonkeyPatch, ps_out: str) -> None:
    register(cfg, 222, LIVE, proc_start=utc_stamp())
    own(monkeypatch, 222, [222])
    fake_ps(monkeypatch, ps_out)
    assert ar.session_id() == LIVE


@pytest.mark.parametrize("tz", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_proc_start_comparison_ignores_the_machine_timezone_and_dst(
    cfg: Path, monkeypatch: pytest.MonkeyPatch, tz: str
) -> None:
    # 2026-11-01 06:30Z falls in the hour US clocks repeat (01:30 EDT and 01:30 EST): local conversion is ambiguous
    night = "Sun Nov  1 06:30:00 2026"
    monkeypatch.setenv("TZ", tz)
    time.tzset()
    try:
        register(cfg, 222, LIVE, proc_start=night)
        own(monkeypatch, 222, [222])
        fake_ps(monkeypatch, night + "\n")
        assert ar.session_id() == LIVE
        register(cfg, 222, LIVE, proc_start=utc_stamp(-3600, night))
        assert ar.session_id() == STALE
    finally:
        monkeypatch.undo()
        time.tzset()


def test_ancestor_walk_follows_parent_pointers_from_a_process_table(
    cfg: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # tool shell 300 <- claude 200 (comm is a version string) <- paseo 100 <- launchd 1
    table = {300: (200, "bash"), 200: (100, "2.1.316"), 100: (1, "Paseo Daemon"), 1: (0, "launchd"), 77: (1, "x")}
    monkeypatch.setattr(ar, "_proc_table", lambda: table)
    monkeypatch.setattr(ar.os, "getppid", lambda: 300)
    assert ar.ancestor_pids() == [300, 200, 100]
    register(cfg, 200, LIVE)
    register(cfg, 100, OTHER)  # a farther registered ancestor must not matter
    monkeypatch.setenv("CLAUDE_PID", "200")
    assert ar.session_id() == LIVE


def test_ancestor_walk_returns_nothing_when_ps_fails(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ar, "_proc_table", lambda: None)
    register(cfg, 200, LIVE)
    monkeypatch.setenv("CLAUDE_PID", "200")
    assert ar.ancestor_pids() == []
    assert ar.session_id() == STALE


def test_show_reads_the_live_session_transcript(
    cfg: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # the stale id has only a sidecar directory (what the predecessor left), the live one a flat transcript
    (cfg / "projects" / "-Users-x" / STALE / "tool-results").mkdir(parents=True)
    transcript(cfg, LIVE, project="-Users-x-src-ade", title="ade lead")
    register(cfg, 222, LIVE)
    own(monkeypatch, 222, [222])
    monkeypatch.setattr("sys.argv", ["autorename", "--show"])
    assert ar.main() == 0
    assert capsys.readouterr().out.strip() == "ade lead"


def test_stale_env_alone_still_reports_no_transcript(
    cfg: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (cfg / "projects" / "-Users-x" / STALE / "tool-results").mkdir(parents=True)
    monkeypatch.setattr(ar, "ancestor_pids", lambda: [])
    monkeypatch.setattr("sys.argv", ["autorename", "--show"])
    assert ar.main() == 2
    assert f"no transcript for session {STALE}" in capsys.readouterr().err


def test_flat_transcript_lookup_across_projects_and_explicit_id(cfg: Path) -> None:
    flat = transcript(cfg, OTHER, project="-Users-x-src-other")
    assert ar.find_transcript(OTHER) == flat
    assert ar.find_transcript(STALE) is None
