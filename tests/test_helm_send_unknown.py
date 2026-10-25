"""helm.py send --screen-fp: a TUI herdr does not detect (status unknown) is sent to only when the caller read its screen and the
very same fresh screen is still there (2026-10-25). Nothing is inferred idle from a screen; every other kind of session is
refused with the flag, and the existing idle path is unchanged."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills/helm"))
import helm  # noqa: E402

READY = ["header: example-model", "", "  some banner text", "status 8m | timer 0s | model-x", "> a dimmed suggestion"]


def row(**kw: Any) -> dict[str, Any]:
    base = {"id": "w1:p1", "agent": "hermes", "name": "", "title": "", "where": "herdr", "focus": "", "status": "unknown", "cwd": "/x",
            "self": False, "pid": 4242, "chan": ("herdr", "w1:p1"), "undetected": True, "host": "herdr", "reach": ""}
    base.update(kw)
    return base


def item(s: dict[str, Any], kind: str = "unknown") -> dict[str, Any]:
    return {"id": s["id"], "kind": kind, "where": s["where"], "focus": "", "project": "x", "reachable": bool(s.get("chan")), "fp": "",
            "agent": s["agent"], "name": s["name"], "title": s["title"]}


class Rig:
    """Replaces the herdr-facing helm functions: SCREENS is what successive reads of the pane return (the last one repeats)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, s: dict[str, Any], kind: str = "unknown") -> None:
        self.s, self.sent, self.reads = s, [], 0
        self.screens: list[list[str]] = [READY]
        monkeypatch.setattr(helm, "STATE_DIR", tmp_path / "state")
        monkeypatch.setattr(helm, "STATE", tmp_path / "state" / "state.json")
        monkeypatch.setattr(helm, "find", lambda ident, state: (self.s, item(self.s, kind)))
        monkeypatch.setattr(helm, "screen", self.read)
        monkeypatch.setattr(helm, "submit", lambda s, text: self.sent.append(text) or True)

    def read(self, s: dict[str, Any], lines: int = 30, width: int = 160) -> str:
        rows = self.screens[min(self.reads, len(self.screens) - 1)]
        self.reads += 1
        return "\n".join(ln.rstrip()[:width] for ln in rows if ln.strip())

    def fp(self) -> str:
        self.reads = 0
        return helm.screen_fp(self.s)

    def send(self, fp: str | None, text: str | None = "please say ok") -> None:
        self.reads = 0
        helm.cmd_send(argparse.Namespace(id=self.s["id"], prompt=text, screen_fp=fp), {})


def refused(rig: Rig, fp: str | None, *needles: str, text: str | None = "please say ok") -> None:
    with pytest.raises(SystemExit) as e:
        rig.send(fp, text)
    assert rig.sent == []
    for n in needles:
        assert n in str(e.value)


def test_the_screen_that_was_read_is_sent_to_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rig = Rig(monkeypatch, tmp_path, row())
    rig.send(rig.fp())
    assert rig.sent == ["please say ok"]


def test_without_the_flag_an_unknown_tui_is_refused_and_told_how(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rig = Rig(monkeypatch, tmp_path, row())
    refused(rig, None, "is unknown, not idle", "helm.py show w1:p1", "--screen-fp")


def test_a_changed_screen_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rig = Rig(monkeypatch, tmp_path, row())
    fp = rig.fp()
    for label, changed in {"a prompt appeared": [*READY, "Approve this command? [y/N]"], "a draft was typed": [*READY[:-1], "> half a mess"],
                           "a turn started": [*READY[:-1], "thinking... esc to interrupt"]}.items():
        rig.screens = [changed]
        refused(rig, fp, "not the one you fingerprinted")
        assert label


def test_the_screen_changing_between_the_check_and_the_submit_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rig = Rig(monkeypatch, tmp_path, row())
    fp = rig.fp()
    rig.screens = [READY, [*READY, "Approve this command? [y/N]"]]    # the first read (the check) matches, the last look does not
    refused(rig, fp, "changed just before the submit")


def test_only_elapsed_time_counters_are_ignored(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rig = Rig(monkeypatch, tmp_path, row())
    fp = rig.fp()
    rig.screens = [[ln.replace("8m", "9m").replace("0s", "12s") for ln in READY]]
    rig.send(fp)
    assert rig.sent == ["please say ok"]
    rig.sent.clear()
    rig.screens = [[ln.replace("model-x", "model-y") for ln in READY]]    # any other word is a change
    refused(rig, fp, "not the one you fingerprinted")


def test_the_fingerprint_names_its_pane_and_process(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rig = Rig(monkeypatch, tmp_path, row())
    fp = rig.fp()
    rig.s = row(id="w1:p2", chan=("herdr", "w1:p2"))
    refused(rig, fp, "another pane or process")
    rig.s = row(pid=4343)    # the TUI was restarted: same pane, same screen text, another process
    refused(rig, fp, "another pane or process")


@pytest.mark.parametrize("kind", ["working", "question", "permission", "plan", "blocked", "busy-background", "finished", "idle", "remote"])
def test_a_known_kind_never_takes_the_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str) -> None:
    rig = Rig(monkeypatch, tmp_path, row(), kind=kind)
    refused(rig, rig.fp(), "only for a TUI herdr does not detect")


def test_an_unknown_row_herdr_does_detect_or_outside_herdr_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for s in (row(undetected=False), row(status="working"), row(chan=("tmux", "%1"), host="tmux"), row(chan=("orca", "t1"), host="orca")):
        rig = Rig(monkeypatch, tmp_path, s)
        refused(rig, rig.fp(), "only for a TUI herdr does not detect")


def test_no_channel_and_this_session_are_refused_before_any_read(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rig = Rig(monkeypatch, tmp_path, row(chan=None))
    refused(rig, "0" * 16, "no channel")
    assert rig.reads == 0
    rig = Rig(monkeypatch, tmp_path, row(self=True))
    refused(rig, "0" * 16, "that is this session")
    assert rig.reads == 0


def test_the_audit_never_takes_the_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rig = Rig(monkeypatch, tmp_path, row())
    refused(rig, rig.fp(), "audit is never sent", text=None)


def test_an_idle_session_still_sends_without_the_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rig = Rig(monkeypatch, tmp_path, row(status="idle", undetected=False, agent="codex"), kind="idle")
    rig.send(None)
    assert rig.sent == ["please say ok"]


def test_show_prints_the_fingerprint_only_for_an_eligible_row(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rig = Rig(monkeypatch, tmp_path, row())
    helm.cmd_show(argparse.Namespace(id="w1:p1", json=False), {})
    out = capsys.readouterr().out
    assert f"screen-fp: {rig.fp()}" in out
    assert f"helm.py send w1:p1 --screen-fp {rig.fp()}" in out
    for s, kind in ((row(undetected=False), "unknown"), (row(), "working")):
        Rig(monkeypatch, tmp_path, s, kind)
        helm.cmd_show(argparse.Namespace(id=s["id"], json=False), {})
        assert "screen-fp" not in capsys.readouterr().out
