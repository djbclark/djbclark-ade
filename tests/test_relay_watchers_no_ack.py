#!/usr/bin/env python3
"""The in-repo watchers call relay.py as declared jobs and read exit 0 as "taken, or queued": each passes `--no-ack` explicitly, so the
default delivery watch (relay.py, 2026-10-25) can never change what they read, even where a session identity leaks into their environment.
load-watch's two relay calls are pinned in tests/test_load_watch.py."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
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
    monkeypatch.setattr(rw, "STATE_DIR", tmp_path / "state")   # never write the operator's log
    monkeypatch.setattr(rw, "LOG", tmp_path / "state" / "rumination.log")
    monkeypatch.setenv("RW_SESSION", "sess-1")
    argvs = []
    # `--json` since 2026-10-29: the outcome word comes from relay.py's machine report, not its prose
    # (a reworded "do not resend" was retried forever). The prose branch below still reads the
    # status line, for an older relay.py that prints no report.
    monkeypatch.setattr(rw, "run_split", lambda cmd, timeout=20: argvs.append(cmd) or
                        (0, json.dumps({"id": "sess-1", "result": "delivered", "via": "paseo"}), ""))
    assert rw.to_session("one open loop") == "delivered"   # relay.py's own word in its report
    assert argvs[0][3:5] == ["sess-1", "one open loop"] and "--no-ack" in argvs[0]
    assert "--json" in argvs[0], "the machine report is what the outcome word is read from"
    # no --idle: it blocks relay.py's deferral, so a busy target would drop the line instead of queueing it
    assert "--idle" not in argvs[0]
    # An exit 0 with no word this code recognises is `sent`, never `delivered`: the log must not
    # claim the strongest word for a shape nobody has proof of.
    monkeypatch.setattr(rw, "run_split", lambda cmd, timeout=20: (0, "", ""))
    assert rw.to_session("one open loop") == "sent"
