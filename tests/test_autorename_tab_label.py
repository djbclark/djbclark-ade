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
