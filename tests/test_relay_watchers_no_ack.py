#!/usr/bin/env python3
"""The in-repo watchers call relay.py as declared jobs and read exit 0 as "taken, or queued": each passes `--no-ack` explicitly, so the
default delivery watch (relay.py, 2026-10-25) can never change what they read, even where a session identity leaks into their environment.
load-watch's two relay calls are pinned in tests/test_load_watch.py."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"


def load(name: str):
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), str(BIN / name))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_session_load_watch_relay_argv_has_no_ack(monkeypatch):
    slw = load("session-load-watch")
    argvs = []
    monkeypatch.setattr(slw.subprocess, "run", lambda argv, **kw: argvs.append(argv) or subprocess.CompletedProcess(argv, 0))
    assert slw.ask("w1:p1", 95.0, 3.0, False) == 0
    assert argvs[0][1].endswith("relay.py") and argvs[0][2] == "w1:p1"
    assert "--no-ack" in argvs[0] and "--no-defer" in argvs[0]


def test_rumination_watch_relay_argv_has_no_ack(monkeypatch, tmp_path):
    rw = load("rumination-watch")
    relay = tmp_path / "src/djbclark-ade/skills/session-finder/relay.py"
    relay.parent.mkdir(parents=True)
    relay.write_text("")
    monkeypatch.setattr(rw, "HOME", tmp_path)
    monkeypatch.setenv("RW_SESSION", "sess-1")
    argvs = []
    monkeypatch.setattr(rw, "run", lambda cmd, timeout=20: argvs.append(cmd) or (0, ""))
    assert rw.to_session("one open loop") is True
    assert argvs[0][3:5] == ["sess-1", "one open loop"] and "--no-ack" in argvs[0]
