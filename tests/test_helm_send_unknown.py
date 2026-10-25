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
        self.screens: list[list[str] | None] = [READY]
        monkeypatch.setattr(helm, "STATE_DIR", tmp_path / "state")
        monkeypatch.setattr(helm, "STATE", tmp_path / "state" / "state.json")
        monkeypatch.setattr(helm, "find", lambda ident, state: (self.s, item(self.s, kind)))
        monkeypatch.setattr(helm, "screen", lambda s, lines=30, width=160: self.read(s, lines, width) or "")
        monkeypatch.setattr(helm, "screen_read", self.read)
        monkeypatch.setattr(helm, "submit", lambda s, text: self.sent.append(text) or True)
        monkeypatch.setattr(helm, "submit_attested", lambda s, text: (self.sent.append(text) or True, None))

    def read(self, s: dict[str, Any], lines: int = 30, width: int = 160) -> str | None:
        """What successive reads return: rows, or None for a failed read (the last entry repeats)."""
        rows = self.screens[min(self.reads, len(self.screens) - 1)]
        self.reads += 1
        return None if rows is None else "\n".join(ln.rstrip()[:width] for ln in rows if ln.strip())

    def fp(self) -> str | None:
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
    refused(rig, fp, "changed or could not be read just before the submit")


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


def test_an_unreadable_or_blank_screen_gives_no_fingerprint_and_no_send_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                                                capsys: pytest.CaptureFixture[str]) -> None:
    """F1: every read failing (a herdr outage, a timeout) or returning no rows must never produce a usable fingerprint."""
    for label, shown in {"failed": None, "blank": ""}.items():
        rig = Rig(monkeypatch, tmp_path, row())
        rig.screens = [shown]
        assert rig.fp() is None, label
        helm.cmd_show(argparse.Namespace(id="w1:p1", json=False), {})
        out = capsys.readouterr().out
        assert "screen unreadable" in out
        assert "screen-fp" not in out.replace("no screen-fp", "") and "helm.py send" not in out
        refused(rig, "0" * 16, "could not be read")    # the fingerprint a caller would have held for an empty screen
        helm.cmd_show(argparse.Namespace(id="w1:p1", json=True), {})
        assert "screen_fp" not in capsys.readouterr().out


def test_the_final_read_failing_refuses_the_send(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rig = Rig(monkeypatch, tmp_path, row())
    fp = rig.fp()
    rig.screens = [READY, None]    # the check reads the screen, the last look before the submit cannot
    refused(rig, fp, "could not be read just before the submit")


@pytest.mark.parametrize(("rc", "out", "usable"), [(127, "", False), (1, "a row\n", False), (2, "a row\n", False), (0, "", False),
                                                    (0, "   \n\n", False), (0, "a row\n\n  b row  \n", True)])
def test_screen_read_and_the_fingerprint_need_a_successful_non_blank_read(monkeypatch: pytest.MonkeyPatch, rc: int, out: str, usable: bool) -> None:
    monkeypatch.setattr(helm, "run", lambda *cmd, timeout=10: (rc, out))
    s = row()
    assert (helm.screen_fp(s) is not None) is usable
    assert (helm.screen_read(s) is not None and bool(helm.screen_read(s))) is usable
    if rc != 0:
        assert helm.screen_read(s) is None
        assert helm.screen(s) == "".join(ln.rstrip() + "\n" for ln in out.splitlines() if ln.strip()).rstrip("\n")    # the other callers still get what was printed


def test_a_channel_less_row_cannot_be_read(monkeypatch: pytest.MonkeyPatch) -> None:
    assert helm.screen_read(row(chan=None)) is None
    assert helm.screen_fp(row(chan=None)) is None


def test_show_hashes_and_displays_one_capture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """D1: a second read between the display and the hash would let the caller attest screen A while holding the fingerprint of B."""
    rig = Rig(monkeypatch, tmp_path, row())
    a_rows = [f"row {i}" for i in range(30)]
    b_rows = [*a_rows, "Approve this command? [y/N]"]
    rig.screens = [a_rows, b_rows]    # a second read would see the approval prompt
    helm.cmd_show(argparse.Namespace(id="w1:p1", json=False), {})
    out = capsys.readouterr().out
    assert rig.reads == 1
    assert "Approve this command" not in out
    assert "| row 29" in out
    assert "| row 7" not in out and "| row 8" in out    # the last 22 rows of that one capture
    assert f"screen-fp: {helm.fp_of(rig.s, chr(10).join(a_rows))}" in out
    assert f"screen-fp: {helm.fp_of(rig.s, chr(10).join(b_rows))}" not in out


# ---- the exact herdr argv: an undetected pane has no herdr AGENT entry (agent_not_found), so only `herdr pane ...` verbs reach it ----


class Argv:
    """Replaces helm.run: records every argv. READS are the successive `read` outputs (rc 0); FAIL maps a verb pair to its exit status."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, s: dict[str, Any], kind: str = "unknown") -> None:
        self.s, self.calls, self.reads, self.fail = s, [], [list(READY)], {}
        monkeypatch.setattr(helm, "STATE_DIR", tmp_path / "state")
        monkeypatch.setattr(helm, "STATE", tmp_path / "state" / "state.json")
        monkeypatch.setattr(helm, "find", lambda ident, state: (self.s, item(self.s, kind)))
        monkeypatch.setattr(helm, "run", self.run)
        monkeypatch.setattr(helm.time, "sleep", lambda secs: None)
        monkeypatch.setattr(helm, "HERDR", "herdr")

    def run(self, *cmd: str, timeout: int = 10) -> tuple[int, str]:
        self.calls.append(list(cmd))
        verb = " ".join(cmd[1:3])
        if cmd[2] == "read":
            n = sum(1 for c in self.calls if c[2] == "read") - 1
            return self.fail.get(verb, 0), "\n".join(self.reads[min(n, len(self.reads) - 1)])
        return self.fail.get(verb, 0), ""

    def verbs(self) -> list[str]:
        return [" ".join(c[1:3]) for c in self.calls]

    def fp(self) -> str | None:
        return helm.screen_fp(self.s)

    def send(self, fp: str | None, text: str = "please say ok") -> None:
        helm.cmd_send(argparse.Namespace(id=self.s["id"], prompt=text, screen_fp=fp), {})


def test_an_undetected_row_is_read_with_pane_read_and_a_detected_one_with_agent_read(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rig = Argv(monkeypatch, tmp_path, row())
    assert rig.fp() is not None
    assert rig.calls == [["herdr", "pane", "read", "w1:p1", "--source", "visible", "--lines", "200"]]
    rig = Argv(monkeypatch, tmp_path, row(undetected=False, status="idle", agent="codex"), kind="idle")
    helm.screen(rig.s, 30)
    assert rig.calls == [["herdr", "agent", "read", "w1:p1", "--source", "visible", "--lines", "30"]]


def test_an_attested_send_reads_twice_then_types_and_presses_enter_with_pane_verbs_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rig = Argv(monkeypatch, tmp_path, row())
    fp = rig.fp()
    rig.calls.clear()
    rig.send(fp)
    assert rig.verbs() == ["pane read", "pane read", "pane send-text", "pane send-keys"]    # both fingerprint checks come first
    assert rig.calls[2] == ["herdr", "pane", "send-text", "w1:p1", "please say ok"]
    assert rig.calls[3] == ["herdr", "pane", "send-keys", "w1:p1", "enter"]
    assert not any(c[1] == "agent" for c in rig.calls)


def test_a_changed_screen_types_nothing_and_presses_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rig = Argv(monkeypatch, tmp_path, row())
    fp = rig.fp()
    rig.calls.clear()
    rig.reads = [[*READY, "Approve this command? [y/N]"]]
    with pytest.raises(SystemExit):
        rig.send(fp)
    assert rig.verbs() == ["pane read"]
    rig.calls.clear()
    rig.reads = [READY, [*READY, "Approve this command? [y/N]"]]    # the last look before the submit differs
    with pytest.raises(SystemExit):
        rig.send(fp)
    assert rig.verbs() == ["pane read", "pane read"]


@pytest.mark.parametrize("status", [1, 127])
def test_failed_or_timed_out_typing_stops_before_enter_and_says_unverified(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: int) -> None:
    rig = Argv(monkeypatch, tmp_path, row())
    fp = rig.fp()
    rig.calls.clear()
    rig.fail["pane send-text"] = status
    with pytest.raises(SystemExit) as e:
        rig.send(fp)
    assert rig.verbs() == ["pane read", "pane read", "pane send-text"]    # no Enter, no second try, no agent verb
    msg = str(e.value)
    assert "unverified" in msg and "Do not resend" in msg and "NOT pressed" in msg


def test_a_failed_enter_after_typing_is_unverified_and_not_retried(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rig = Argv(monkeypatch, tmp_path, row())
    fp = rig.fp()
    rig.calls.clear()
    rig.fail["pane send-keys"] = 1
    with pytest.raises(SystemExit) as e:
        rig.send(fp)
    assert rig.verbs() == ["pane read", "pane read", "pane send-text", "pane send-keys"]
    assert "typed" in str(e.value) and "Enter failed" in str(e.value) and "Do not resend" in str(e.value)


def test_newlines_fold_and_other_control_characters_refuse_before_typing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rig = Argv(monkeypatch, tmp_path, row())
    fp = rig.fp()
    rig.calls.clear()
    rig.send(fp, "line one\nline two\t end")
    assert rig.calls[2][-1] == "line one line two end"    # a raw newline would have submitted early
    rig.calls.clear()
    with pytest.raises(SystemExit) as e:
        rig.send(fp, "esc \x1b[31m here")
    assert rig.verbs() == ["pane read", "pane read"]
    assert "control characters" in str(e.value)


def test_a_detected_idle_session_still_submits_with_agent_prompt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rig = Argv(monkeypatch, tmp_path, row(undetected=False, status="idle", agent="codex"), kind="idle")
    rig.send(None)
    assert rig.calls == [["herdr", "agent", "prompt", "w1:p1", "please say ok"]]
