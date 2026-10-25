#!/usr/bin/env python3
"""The suite never touches the operator's real deferred-send queue (~/.local/state/relay), 2026-10-24.

tests/conftest.py points RELAY_DEFER_DIR at a throwaway directory before relay.py is imported. No snapshot of the real
directory is compared: every agent's relay.py run on the machine changes it while the suite runs.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import conftest  # type: ignore[import-not-found]  # pyright: ignore[reportMissingImports]

SF = Path(__file__).resolve().parent.parent / "skills" / "session-finder"


def test_a_freshly_loaded_relay_never_points_at_the_real_queue() -> None:
    sys.path.insert(0, str(SF))
    spec = importlib.util.spec_from_file_location("relay_guard_probe", SF / "relay.py")
    assert spec and spec.loader
    relay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(relay)
    real = conftest.REAL_RELAY_DIR.resolve()
    assert real not in (relay.DEFER_DIR.resolve(), *relay.DEFER_DIR.resolve().parents)


def test_the_links_ledger_never_points_at_the_real_state() -> None:
    sys.path.insert(0, str(SF))
    import fleet  # noqa: PLC0415  # pyright: ignore[reportMissingImports]
    real = conftest.REAL_RELAY_DIR.resolve()
    assert real not in (fleet.LINKS_FILE.resolve(), *fleet.LINKS_FILE.resolve().parents)
