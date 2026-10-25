#!/usr/bin/env python3
"""The suite never touches the operator's real deferred-send queue (~/.local/state/relay), 2026-10-24.

Named test_zz_ so a full run reaches it last; run alone it still proves a freshly loaded relay.py points at a
throwaway directory. tests/conftest.py snapshots the real directory (every entry's mtime and size) when the run starts.
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


def test_the_real_queue_is_unchanged_since_the_run_started() -> None:
    assert conftest.relay_state_snapshot() == conftest.REAL_RELAY_BEFORE
