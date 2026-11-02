"""autorename: the Claude Code session id comes from the process registry, not the inherited env var (2026-11-02).

A session started from another session's environment (`/baton`, `/handoff`, a Paseo agent launched from a
predecessor's shell) keeps the predecessor's CLAUDE_CODE_SESSION_ID in its tool shells while
`<config>/sessions/<pid>.json` names its own session. Reproduced: env e236fcc3 had no transcript at all
("autorename: no transcript for session e236fcc3..."), the running session was 7c96a0ca."""

from __future__ import annotations

import importlib.util
import json
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
    monkeypatch.setattr(ar, "STATE_DIR", tmp_path / "state")
    (tmp_path / "sessions").mkdir()
    return tmp_path


def register(cfg: Path, pid: int, sid: Any, *, file_pid: Any = None) -> None:
    rec = {"pid": pid if file_pid is None else file_pid, "sessionId": sid, "kind": "interactive"}
    (cfg / "sessions" / f"{pid}.json").write_text(json.dumps(rec), encoding="utf-8")


def transcript(cfg: Path, sid: str, project: str = "-Users-x", title: str | None = None) -> Path:
    path = cfg / "projects" / project / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"type": "user", "sessionId": sid})]
    if title:
        lines.append(json.dumps({"type": "custom-title", "customTitle": title, "sessionId": sid}, separators=(",", ":")))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_registry_overrides_stale_env(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    register(cfg, 222, LIVE)
    monkeypatch.setattr(ar, "ancestor_pids", lambda: [111, 222, 1000])
    assert ar.session_id() == LIVE


def test_nearest_registered_ancestor_wins(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    register(cfg, 222, LIVE)
    register(cfg, 333, OTHER)
    monkeypatch.setattr(ar, "ancestor_pids", lambda: [111, 222, 333])
    assert ar.session_id() == LIVE


@pytest.mark.parametrize("bad", ["not-a-uuid", "", 7, None, [LIVE]])
def test_unusable_registry_entry_is_skipped(cfg: Path, monkeypatch: pytest.MonkeyPatch, bad: Any) -> None:
    register(cfg, 222, bad)
    register(cfg, 333, OTHER)
    monkeypatch.setattr(ar, "ancestor_pids", lambda: [222, 333])
    assert ar.session_id() == OTHER


def test_registry_file_of_a_reused_pid_is_not_trusted(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    register(cfg, 222, LIVE, file_pid=999)
    monkeypatch.setattr(ar, "ancestor_pids", lambda: [222])
    assert ar.session_id() == STALE


def test_non_object_registry_file_is_skipped(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (cfg / "sessions" / "222.json").write_text("[1]", encoding="utf-8")
    (cfg / "sessions" / "333.json").write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(ar, "ancestor_pids", lambda: [222, 333])
    assert ar.session_id() == STALE


def test_no_registered_ancestor_falls_back_to_env(cfg: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    register(cfg, 555, LIVE)  # a registered session that is not above this process
    monkeypatch.setattr(ar, "ancestor_pids", lambda: [111, 222])
    assert ar.session_id() == STALE


def test_show_reads_the_live_session_transcript(
    cfg: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # the stale id has only a sidecar directory (what the predecessor left), the live one a flat transcript
    (cfg / "projects" / "-Users-x" / STALE / "tool-results").mkdir(parents=True)
    transcript(cfg, LIVE, project="-Users-x-src-ade", title="ade lead")
    register(cfg, 222, LIVE)
    monkeypatch.setattr(ar, "ancestor_pids", lambda: [222])
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
