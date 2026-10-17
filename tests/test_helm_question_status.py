"""helm.question_status: is the question the relay showed still pending, answered in the
terminal meanwhile, or replaced? (operator, 2026-10-11)"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills/helm"))
import helm  # noqa: E402

S = {"sid": "x", "agent": "claude"}


def item(kind, fp):
    return {"kind": kind, "fp": fp, "id": "i"}


def test_same_question_is_pending():
    assert helm.question_status(S, item("question", "toolu_abc123"), "toolu_abc123")[0] == "pending"
    assert helm.question_status(S, item("question", "toolu_abc123"), "abc123")[0] == "pending"
    assert helm.question_status(S, item("question", "toolu_abc123"), None)[0] == "pending"


def test_recorded_answer_means_answered(monkeypatch):
    monkeypatch.setattr(helm, "transcript", lambda sid: "p")
    monkeypatch.setattr(helm, "parse", lambda p: {"answers": {"toolu_old": {"Q?": "Yes"}}})
    assert helm.question_status(S, item("working", ""), "toolu_old") == ("answered", {"Q?": "Yes"})


def test_other_or_missing_question_is_changed(monkeypatch):
    monkeypatch.setattr(helm, "transcript", lambda sid: "p")
    monkeypatch.setattr(helm, "parse", lambda p: {"answers": {}})
    assert helm.question_status(S, item("question", "toolu_new"), "toolu_old")[0] == "changed"
    assert helm.question_status(S, item("working", ""), "toolu_old")[0] == "changed"
