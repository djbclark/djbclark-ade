"""bin/completion-notice: required push-on-completion message shape and paseo-send argv (no relay)."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "completion-notice"
FOOTER = ROOT / "docs" / "dispatch-footer.md"
FANOUT = ROOT / "skills" / "fan-out" / "SKILL.md"
ORCH = ROOT / "docs" / "orchestration-practices.md"

loader = importlib.machinery.SourceFileLoader("completion_notice", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

SENDER = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
REQUESTER = "11111111-2222-3333-4444-555555555555"


def run_cli(*args: str, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )


def test_build_and_parse_pr_shape():
    text = mod.build_message(
        title="queue item 5",
        detail="https://github.com/djbclark/djbclark-ade/pull/999",
        report=None,
        sender=SENDER,
    )
    assert text.splitlines()[0] == (
        "done: queue item 5, https://github.com/djbclark/djbclark-ade/pull/999"
    )
    assert text.splitlines()[1] == f"Please reply: ack {SENDER}"
    parsed = mod.parse_message(text)
    assert parsed == {
        "title": "queue item 5",
        "detail": "https://github.com/djbclark/djbclark-ade/pull/999",
        "sender": SENDER,
    }


def test_build_status_and_report_shape():
    text = mod.build_message(
        title="slice-a",
        detail="DONE",
        report="/abs/a-report.md",
        sender=SENDER,
    )
    assert text.startswith("done: slice-a, DONE, /abs/a-report.md\n")
    assert mod.parse_message(text)["report"] == "/abs/a-report.md"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"title": "", "detail": "DONE", "report": None, "sender": SENDER},
        {"title": "a,b", "detail": "DONE", "report": None, "sender": SENDER},
        {"title": "ok", "detail": "", "report": None, "sender": SENDER},
        {"title": "ok", "detail": "x,y", "report": None, "sender": SENDER},
        {"title": "ok", "detail": "DONE", "report": "x\ny", "sender": SENDER},
        {"title": "ok", "detail": "DONE", "report": None, "sender": ""},
        {"title": "ok", "detail": "DONE", "report": None, "sender": "a b"},
    ],
)
def test_invalid_fields_refused(kwargs):
    with pytest.raises(ValueError):
        mod.build_message(**kwargs)


@pytest.mark.parametrize(
    "text",
    [
        "done: only-one-field\nPlease reply: ack x",
        "DONE: title, url\nPlease reply: ack x",
        "done: title, url\nack x",
        "done: title, url\nPlease reply: ack x\nextra",
        "written: /abs/report.md",
    ],
)
def test_parse_rejects_wrong_shape(text):
    with pytest.raises(ValueError):
        mod.parse_message(text)


def test_send_argv_is_paseo_send_json_no_wait_not_relay():
    msg = mod.build_message(title="t", detail="DONE", report=None, sender=SENDER)
    argv = mod.send_argv(REQUESTER, msg, paseo="/usr/bin/paseo")
    assert argv[:5] == ["/usr/bin/paseo", "send", "--json", "--no-wait", "--"]
    assert argv[5] == REQUESTER
    assert argv[6] == msg
    assert "relay" not in " ".join(argv).lower()


def test_cli_print_and_argv():
    r = run_cli(
        "--print",
        "--argv",
        "--requester",
        REQUESTER,
        "--title",
        "push on completion",
        "--pr",
        "https://example.test/pr/1",
        "--sender",
        SENDER,
        "--paseo",
        "paseo",
    )
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0] == "done: push on completion, https://example.test/pr/1"
    assert lines[1] == f"Please reply: ack {SENDER}"
    argv = json.loads(lines[2])
    assert argv[1:4] == ["send", "--json", "--no-wait"]


def test_cli_refuses_bad_title():
    r = run_cli(
        "--print",
        "--requester",
        REQUESTER,
        "--title",
        "a,b",
        "--status",
        "DONE",
        "--sender",
        SENDER,
    )
    assert r.returncode == 2
    assert "title" in r.stderr


def test_send_queued_is_accepted_exit_5(monkeypatch):
    msg = mod.build_message(title="t", detail="DONE", report=None, sender=SENDER)

    def fake_run(argv):
        assert argv[1:4] == ["send", "--json", "--no-wait"]
        return 0, json.dumps({"status": "queued"}), ""

    monkeypatch.setattr(mod, "run_send", fake_run)
    assert mod.main([
        "--send", "--requester", REQUESTER, "--title", "t", "--status", "DONE",
        "--sender", SENDER, "--paseo", "paseo",
    ]) == 5


def test_send_delivered_exit_0(monkeypatch):
    def fake_run(argv):
        return 0, json.dumps({"status": "sent"}), ""

    monkeypatch.setattr(mod, "run_send", fake_run)
    assert mod.main([
        "--send", "--requester", REQUESTER, "--title", "t", "--status", "DONE",
        "--sender", SENDER,
    ]) == 0


def test_footer_and_teaching_require_the_shape():
    footer = FOOTER.read_text()
    assert "done: <title>, <PR URL>" in footer
    assert "paseo send --json --no-wait" in footer
    assert "Please reply: ack <your agent id>" in footer
    assert "never `relay.py`" in footer
    assert "bin/completion-notice" in footer
    fan = FANOUT.read_text()
    assert "completion-notice" in fan
    assert "paseo send --json --no-wait" in fan
    assert "done: <title>, <PR URL>" in fan
    orch = ORCH.read_text()
    assert "Push on completion" in orch
    assert "completion-notice" in orch
    assert "never relay" in orch
