"""Unit tests for bin/herdr-sleeper's pure decision logic (no Herdr needed)."""

from __future__ import annotations

import os
import time
import types
from pathlib import Path
from typing import Any, Callable

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "herdr-sleeper"
sleeper = types.ModuleType("herdr_sleeper")
exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), sleeper.__dict__)


def agent(
    pane: str = "w1:p1",
    uuid: str | None = "u-1",
    status: str = "idle",
    focused: bool = False,
    kind: str = "claude",
    name: str = "a",
) -> dict[str, Any]:
    a: dict[str, Any] = {"pane_id": pane, "agent_status": status, "focused": focused, "agent": kind, "name": name}
    if uuid:
        a["agent_session"] = {"value": uuid}
    return a


@pytest.fixture
def transcripts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[[str, float], Path]:
    root = tmp_path / "projects"
    (root / "proj").mkdir(parents=True)
    monkeypatch.setattr(sleeper, "TRANSCRIPTS", root)

    def make(uuid: str, age_hours: float) -> Path:
        p = root / "proj" / f"{uuid}.jsonl"
        p.write_text("{}\n")
        stamp = time.time() - age_hours * 3600
        os.utime(p, (stamp, stamp))
        return p

    return make


def test_strip_resume_flags() -> None:
    assert sleeper.strip_resume_flags(["--dangerously-skip-permissions", "--resume", "abc"]) == ["--dangerously-skip-permissions"]
    assert sleeper.strip_resume_flags(["-r", "abc", "--model", "opus"]) == ["--model", "opus"]
    assert sleeper.strip_resume_flags(["--resume=abc", "-c", "--continue"]) == []
    assert sleeper.strip_resume_flags([]) == []


def test_assess_sleeps_old_idle_agent(transcripts: Callable[[str, float], Path]) -> None:
    transcripts("u-1", 13)
    ok, _reason, idle = sleeper.assess(agent(), [agent()], 12, {})
    assert ok and idle is not None and idle > 12


def test_assess_rejects_recent(transcripts: Callable[[str, float], Path]) -> None:
    transcripts("u-1", 2)
    ok, reason, _ = sleeper.assess(agent(), [agent()], 12, {})
    assert not ok and "< 12h" in reason


@pytest.mark.parametrize(
    "kw, needle",
    [
        ({"status": "working"}, "status working"),
        ({"status": "blocked"}, "status blocked"),
        ({"focused": True}, "focused"),
        ({"uuid": None}, "no session uuid"),
        ({"kind": "codex"}, "not supported"),
    ],
)
def test_assess_rejections(transcripts: Callable[[str, float], Path], kw: dict[str, Any], needle: str) -> None:
    transcripts("u-1", 30)
    a = agent(**kw)
    ok, reason, _ = sleeper.assess(a, [a], 12, {})
    assert not ok and needle in reason


def test_assess_rejects_shared_session(transcripts: Callable[[str, float], Path]) -> None:
    transcripts("u-1", 30)
    a, b = agent(pane="w1:p1"), agent(pane="w2:p1", status="working")
    ok, reason, _ = sleeper.assess(a, [a, b], 12, {})
    assert not ok and "w2:p1" in reason


def test_assess_rejects_missing_transcript(transcripts: Callable[[str, float], Path]) -> None:
    ok, reason, _ = sleeper.assess(agent(), [agent()], 12, {})
    assert not ok and "no transcript" in reason


def test_assess_rejects_already_journaled(transcripts: Callable[[str, float], Path]) -> None:
    transcripts("u-1", 30)
    ok, reason, _ = sleeper.assess(agent(), [agent()], 12, {"w1:p1": {}})
    assert not ok and "journal" in reason


def test_assess_rejects_excluded(transcripts: Callable[[str, float], Path]) -> None:
    transcripts("u-1", 30)
    a = agent(name="orc")
    assert sleeper.assess(a, [a], 12, {}, {"orc"})[1] == "excluded"
    assert sleeper.assess(a, [a], 12, {}, {"w1:p1"})[1] == "excluded"
    assert sleeper.assess(a, [a], 12, {}, {"other"})[0]


CLAUDE_SCREEN = """
❯ earlier question
⏺ pong
✻ Worked for 1s · done 5:23 PM
────────
❯ {composer}
────────
  ◤ graft · 40 nodes / 63 edges · ✓ synced
  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents
"""


def test_draft_input_detects_unsent_text() -> None:
    assert sleeper.draft_input(CLAUDE_SCREEN.format(composer="half-typed thought")) == "half-typed thought"
    assert sleeper.draft_input(CLAUDE_SCREEN.format(composer="")) is None
    assert sleeper.draft_input("djbclark@mac:~$ \n") is None  # bare shell, no composer


def test_load_config_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.toml"
    monkeypatch.setattr(sleeper, "CONFIG_FILE", cfg)
    monkeypatch.delenv("HERDR_SLEEPER_IDLE_HOURS", raising=False)
    monkeypatch.delenv("HERDR_SLEEPER_EXCLUDE", raising=False)
    values, source = sleeper.load_config()
    assert values == {"idle_hours": 12.0, "exclude": [], "interval_minutes": 30}
    assert set(source.values()) == {"default"}

    cfg.write_text('idle_hours = 6\nexclude = ["orc"]\n')
    values, source = sleeper.load_config()
    assert values["idle_hours"] == 6.0 and values["exclude"] == ["orc"]
    assert source["idle_hours"] == str(cfg) and source["interval_minutes"] == "default"

    monkeypatch.setenv("HERDR_SLEEPER_IDLE_HOURS", "1.5")
    monkeypatch.setenv("HERDR_SLEEPER_EXCLUDE", "a b")
    values, source = sleeper.load_config()
    assert values["idle_hours"] == 1.5 and values["exclude"] == ["a", "b"]
    assert source["idle_hours"] == "$HERDR_SLEEPER_IDLE_HOURS"


def test_load_config_ignores_bad_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text("idle_hours = = 3\n")
    monkeypatch.setattr(sleeper, "CONFIG_FILE", cfg)
    monkeypatch.setattr(sleeper, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(sleeper, "LOG", tmp_path / "state" / "sleeper.log")
    values, _ = sleeper.load_config()
    assert values["idle_hours"] == 12.0


def test_launchd_plist_is_valid_xml(tmp_path: Path) -> None:
    import xml.etree.ElementTree as ET

    text = sleeper.launchd_plist(Path("/x/herdr-sleeper"), {"interval_minutes": 15})
    root = ET.fromstring(text)
    strings = [e.text for e in root.iter("string")]
    ints = [e.text for e in root.iter("integer")]
    assert "/x/herdr-sleeper" in strings and "scan" in strings and ints == ["900"]


def test_wake_name_falls_back_to_pane() -> None:
    assert sleeper.wake_name({"name": None, "pane_id": "w26:p2"}) == "wake-w26-p2"
    assert sleeper.wake_name({"name": "lichess", "pane_id": "w24:p1"}) == "lichess"
