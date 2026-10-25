"""herdr_place.replaceable: which tab labels autorename may overwrite from the session title."""

from __future__ import annotations

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "herdr_place", Path(__file__).resolve().parent.parent / "skills/autorename/herdr_place.py")
hp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hp)


def test_generic_label_is_replaceable():
    assert hp.replaceable("3", 1)
    assert hp.replaceable("3", 2)


def test_previous_autorename_label_is_replaceable_on_a_single_pane_tab():
    # 2026-10-11: a stale `helm-t` outlived the session that made it.
    assert hp.replaceable("helm-t", 1)


def test_autorename_label_kept_on_a_multi_pane_tab():
    assert not hp.replaceable("helm-t", 2)


def test_hand_made_label_is_kept():
    assert not hp.replaceable("my notes", 1)


# A Codex pane title is returned in the Herdr CLI response envelope. Missing titles
# must stay absent: converting JSON null to "None" otherwise labels a tab none-t.
import json
import sys
from types import SimpleNamespace

import pytest

ar_spec = importlib.util.spec_from_file_location(
    "autorename", Path(__file__).resolve().parent.parent / "skills/autorename/autorename.py")
ar = importlib.util.module_from_spec(ar_spec)
ar_spec.loader.exec_module(ar)


@pytest.mark.parametrize("payload,expected", [
    ({"result": {"pane": {"label": "Real session title"}}}, "Real session title"),
    ({"result": {"pane": {"label": None, "title": "Fallback title"}}}, "Fallback title"),
    ({"label": "Legacy title"}, "Legacy title"),
    ({"result": {"pane": {"label": None, "title": None}}}, None),
    ({"result": {"pane": {"label": 123}}}, None),
    ({"result": []}, None),
    ({}, None),
])
def test_codex_pane_title_uses_cli_envelope_and_never_stringifies_null(monkeypatch, payload, expected):
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p1")
    monkeypatch.setattr(ar.shutil, "which", lambda _: "/tools/herdr")
    monkeypatch.setattr(ar.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=json.dumps(payload)))
    assert ar.codex_pane_title() == expected


@pytest.mark.parametrize("title,expected_rc,expected_rename", [
    ("Real title", 0, [("tab", "rename", "w1:t1", "real-title-t")]),
    (None, 2, []),
])
def test_label_from_codex_title_preserves_tab_when_title_missing(monkeypatch, title, expected_rc, expected_rename):
    monkeypatch.setenv("HERDR_ENV", "1")
    monkeypatch.setenv("HERDR_PANE_ID", "w1:p1")
    monkeypatch.setitem(sys.modules, "autorename", ar)
    monkeypatch.setattr(ar, "session_id", lambda: "thread")
    monkeypatch.setattr(ar, "backend_for", lambda _: "codex")
    monkeypatch.setattr(ar.shutil, "which", lambda _: "/tools/herdr")
    monkeypatch.setattr(ar.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=json.dumps({"result": {"pane": {"label": title}}})))
    renamed = []
    def herdr(*args):
        if args[:2] == ("pane", "get"):
            return {"pane": {"workspace_id": "w1", "tab_id": "w1:t1"}}
        if args[:2] == ("tab", "list"):
            return {"tabs": [{"tab_id": "w1:t1", "label": "3", "pane_count": 1}]}
        renamed.append(args)
        return {}
    monkeypatch.setattr(hp, "herdr", herdr)
    assert hp.label(None, True, False) == expected_rc
    assert renamed == expected_rename
