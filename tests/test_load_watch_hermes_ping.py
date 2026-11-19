"""bin/load-watch hermes-ping: a failed operator ping must not stamp a cooldown (2026-11-18).

The cooldown keys ("churn", "nocpu", ...) exist to stop re-paging after a page went out. The first version
stamped them after *attempting* hermes-ping, so one transient failure silenced the operator for the whole
LW_COOLDOWN_H (6 h). `hermes_ping()` now reports delivery and the two stamping sites (`churn_alert` and
`operator_notice`) stamp only on success; a failure is logged and the next sample retries.
"""
import importlib.machinery
import importlib.util
from pathlib import Path

LW = Path(__file__).resolve().parent.parent / "bin" / "load-watch"


def load_module():
    loader = importlib.machinery.SourceFileLoader("load_watch", str(LW))
    spec = importlib.util.spec_from_loader("load_watch", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _exe(tmp_path, name, body):
    p = tmp_path / name
    p.write_text("#!/bin/sh\n" + body + "\n")
    p.chmod(0o755)
    return p


def _table():
    return {"1": (0, 0, 2.5, "/usr/bin/cc1 -O2")}


def test_hermes_ping_reports_delivery_without_touching_the_real_one(tmp_path, monkeypatch):
    lw = load_module()
    monkeypatch.setattr(lw, "STATE_DIR", tmp_path)
    monkeypatch.setattr(lw, "HERMES_PING", tmp_path / "absent")  # never the operator's real hermes-ping
    assert lw.hermes_ping("x") is True  # no hermes-ping on this host: nothing to retry
    monkeypatch.setattr(lw, "HERMES_PING", _exe(tmp_path, "ok-ping", "exit 0"))
    assert lw.hermes_ping("x") is True
    monkeypatch.setattr(lw, "HERMES_PING", _exe(tmp_path, "bad-ping", "exit 1"))
    assert lw.hermes_ping("x") is False


def test_churn_alert_stamps_the_cooldown_only_after_a_successful_ping(tmp_path, monkeypatch):
    lw = load_module()
    monkeypatch.setattr(lw, "STATE_DIR", tmp_path)
    monkeypatch.setattr(lw, "tell_watcher", lambda *a, **k: None)
    st = {"cooldown": {}, "churn_since": 100.0, "churn_pages_s": 120000}
    monkeypatch.setattr(lw, "HERMES_PING", _exe(tmp_path, "bad-ping", "exit 1"))
    lw.churn_alert(st, 300.0, _table(), dry=False)
    assert "churn" not in st["cooldown"]  # the failed page left the key unset, so the next sample retries
    monkeypatch.setattr(lw, "HERMES_PING", _exe(tmp_path, "ok-ping", "exit 0"))
    lw.churn_alert(st, 300.0, _table(), dry=False)
    assert "churn" in st["cooldown"]


def test_operator_notice_stamps_the_cooldown_only_after_a_successful_ping(tmp_path, monkeypatch):
    lw = load_module()
    monkeypatch.setattr(lw, "STATE_DIR", tmp_path)
    monkeypatch.setattr(lw, "tell_watcher", lambda *a, **k: None)
    st = {"cooldown": {}}
    monkeypatch.setattr(lw, "HERMES_PING", _exe(tmp_path, "bad-ping", "exit 1"))
    lw.operator_notice(st, 300.0, "nocpu", "load 90 for 5+ min")
    assert "nocpu" not in st["cooldown"]
    monkeypatch.setattr(lw, "HERMES_PING", _exe(tmp_path, "ok-ping", "exit 0"))
    lw.operator_notice(st, 300.0, "nocpu", "load 90 for 5+ min")
    assert "nocpu" in st["cooldown"]
