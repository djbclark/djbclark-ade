#!/usr/bin/env python3
"""rumination-watch must find the session it speaks to AT RUN TIME.

A launchd job has no session identity, so the first implementation resolved the target from
`RW_SESSION`/`PASEO_AGENT_ID` only and returned False when both were unset — which under launchd is
always. It ran every 5 minutes for two days and logged `session=False` 870 times: the entity's "voice
in the head" had never once been audible (2026-10-29). These tests pin the resolution chain, the
liveness check that keeps a stale registry row from swallowing the line, and the honest failure.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"
LIVE = "d2a505dd-8c93-4ba5-8684-e98a3865a1ae"


def load(monkeypatch, tmp_path, registry: dict | None = None):
    loader = importlib.machinery.SourceFileLoader("rumination_watch", str(BIN / "rumination-watch"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    rw = importlib.util.module_from_spec(spec)
    loader.exec_module(rw)
    repo = tmp_path / "techno-euphora"
    (repo / "agents" / "comm").mkdir(parents=True)
    if registry is not None:
        (repo / "agents" / "comm" / "registry.json").write_text(json.dumps(registry))
    monkeypatch.setattr(rw, "REPO", repo)
    monkeypatch.setattr(rw, "HOME", tmp_path)          # no relay.py, no fleet.py: nothing to exec
    monkeypatch.delenv("RW_SESSION", raising=False)
    monkeypatch.delenv("PASEO_AGENT_ID", raising=False)
    monkeypatch.setattr(rw, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(rw, "LOG", tmp_path / "state" / "rumination.log")
    return rw


def test_launchd_resolves_the_registry_row(monkeypatch, tmp_path):
    """No env at all — the launchd case — and the registry's paseo id is the target."""
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE, "instance": "Dann 7"}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    assert rw.owner_session() == (LIVE, "registry")


def test_an_env_override_wins_without_a_lookup(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": LIVE}})
    monkeypatch.setenv("RW_SESSION", "abcd1234")
    assert rw.owner_session() == ("abcd1234", "RW_SESSION")


def test_a_stale_registry_row_does_not_swallow_the_line(monkeypatch, tmp_path):
    """A died-and-replaced seat leaves an id fleet no longer lists: try the next source, never send."""
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": "0000dead-0000-4000-8000-000000000000"}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    mail = rw.REPO / "projects/hiwymi/spec/composite-individual/tools/peer-comms/peer_mail.py"
    mail.parent.mkdir(parents=True)
    mail.write_text("")
    seen = []

    def fake_run(cmd, timeout=20):
        seen.append(cmd)
        if "peer_mail.py" in cmd[2]:
            return 0, json.dumps({"live_paseo_ids": [LIVE]})
        return 1, ""

    monkeypatch.setattr(rw, "run", fake_run)
    assert rw.owner_session() == (LIVE, "peer_mail")


def test_nothing_live_is_an_honest_failure_not_a_silent_one(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path, {"dann": {"paseo": "0000dead-0000-4000-8000-000000000000"}})
    monkeypatch.setattr(rw, "live_sessions", lambda: {})
    assert rw.owner_session()[0] == ""
    assert "no live session" in rw.owner_session()[1]
    called = []
    monkeypatch.setattr(rw, "run", lambda cmd, timeout=20: called.append(cmd) or (0, ""))
    assert rw.to_session("one open loop") is False
    assert called == []                                  # no relay attempt into a void
    assert "cannot speak to session" in rw.LOG.read_text()


def test_an_archived_agent_is_not_usable(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    monkeypatch.setattr(rw, "live_sessions",
                        lambda: {LIVE[:8]: {"paseo": LIVE, "ended": True, "archived": True}})
    assert rw.usable(LIVE) is False
    monkeypatch.setattr(rw, "live_sessions", lambda: {LIVE[:8]: {"paseo": LIVE}})
    assert rw.usable(LIVE) is True
    assert rw.usable("0000dead") is False                # not listed at all
