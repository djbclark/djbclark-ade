"""bin/completion-notice: required push-on-completion message shape and paseo-send argv (no relay)."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "completion-notice"
FOOTER = ROOT / "docs" / "dispatch-footer.md"
FANOUT = ROOT / "skills" / "fan-out" / "SKILL.md"
ORCH = ROOT / "docs" / "orchestration-practices.md"
AGENTS = ROOT / "AGENTS.md"

loader = importlib.machinery.SourceFileLoader("completion_notice", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

SENDER = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
REQUESTER = "11111111-2222-3333-4444-555555555555"
TEST_MSG_ID = "msgid12345"


def run_cli(*args: str, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )


def test_build_and_parse_pr_shape_with_msg_id():
    text = mod.build_message(
        title="queue item 5",
        detail="https://github.com/djbclark/djbclark-ade/pull/999",
        report=None,
        sender=SENDER,
        msg_id=TEST_MSG_ID,
    )
    assert text.splitlines()[0] == (
        "done: queue item 5, https://github.com/djbclark/djbclark-ade/pull/999"
    )
    assert text.splitlines()[1] == f"Please reply: ack {SENDER} {TEST_MSG_ID}"
    parsed = mod.parse_message(text)
    assert parsed == {
        "title": "queue item 5",
        "detail": "https://github.com/djbclark/djbclark-ade/pull/999",
        "sender": SENDER,
        "msg_id": TEST_MSG_ID,
    }


def test_build_auto_generates_msg_id():
    text = mod.build_message(
        title="auto-msg-id",
        detail="DONE",
        report=None,
        sender=SENDER,
    )
    parsed = mod.parse_message(text)
    assert parsed["title"] == "auto-msg-id"
    assert parsed["sender"] == SENDER
    assert parsed["msg_id"] is not None
    assert len(parsed["msg_id"]) == 32  # uuid4 hex


def test_parse_message_without_msg_id_backwards_compatible():
    text = f"done: legacy, DONE\nPlease reply: ack {SENDER}"
    parsed = mod.parse_message(text)
    assert parsed["title"] == "legacy"
    assert parsed["detail"] == "DONE"
    assert parsed["sender"] == SENDER
    assert parsed["msg_id"] is None


def test_build_status_and_report_shape():
    text = mod.build_message(
        title="slice-a",
        detail="DONE",
        report="/abs/a-report.md",
        sender=SENDER,
        msg_id=TEST_MSG_ID,
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
        {"title": "ok", "detail": "DONE", "report": None, "sender": SENDER, "msg_id": "a b"},
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
        "done: title, url\nNo reply needed: slice finished",
    ],
)
def test_parse_rejects_wrong_shape(text):
    with pytest.raises(ValueError):
        mod.parse_message(text)


def test_send_argv_is_paseo_send_json_no_wait_not_relay():
    msg = mod.build_message(title="t", detail="DONE", report=None, sender=SENDER, msg_id=TEST_MSG_ID)
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
        "--msg-id",
        TEST_MSG_ID,
        "--paseo",
        "paseo",
    )
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0] == "done: push on completion, https://example.test/pr/1"
    assert lines[1] == f"Please reply: ack {SENDER} {TEST_MSG_ID}"
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


def test_disk_ack_atomic_write_and_check(tmp_path):
    done_file = tmp_path / "slice.done"
    done_file.write_text("DONE\n")
    ack_path = mod.write_ack_file(done_file, worker=SENDER, msg_id=TEST_MSG_ID)
    assert Path(ack_path).is_file()
    assert ack_path == str(done_file) + ".ack"

    # read_ack_file
    data = mod.read_ack_file(done_file)
    assert data is not None
    assert data["ack"] == SENDER
    assert data["msg_id"] == TEST_MSG_ID

    # check_ack matching
    checked = mod.check_ack(done_file, msg_id=TEST_MSG_ID)
    assert checked is not None
    assert checked["msg_id"] == TEST_MSG_ID

    # check_ack mismatch
    checked_bad = mod.check_ack(done_file, msg_id="other-id")
    assert checked_bad is None

    # CLI check-ack
    r = run_cli("--check-ack", str(done_file), "--msg-id", TEST_MSG_ID)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["status"] == "acked"
    assert out["data"]["msg_id"] == TEST_MSG_ID

    # CLI check-ack mismatch fails with exit 1
    r_bad = run_cli("--check-ack", str(done_file), "--msg-id", "mismatch")
    assert r_bad.returncode == 1


def test_lead_ack_flow(tmp_path):
    done_file = tmp_path / "lead_test.done"
    done_file.write_text("DONE\n")

    fake_paseo = tmp_path / "fake_paseo"
    fake_paseo.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, json\n"
        "if sys.argv[1:3] == ['agent', 'inspect']:\n"
        "    print(json.dumps({'Status': 'idle'}))\n"
        "    sys.exit(0)\n"
        "if sys.argv[1:3] == ['send', '--json']:\n"
        "    print(json.dumps({'status': 'queued'}))\n"
        "    sys.exit(0)\n"
        "sys.exit(1)\n"
    )
    fake_paseo.chmod(0o755)

    r = run_cli(
        "--lead-ack",
        "--worker",
        SENDER,
        "--msg-id",
        TEST_MSG_ID,
        "--done",
        str(done_file),
        "--paseo",
        str(fake_paseo),
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["status"] == "acked"
    assert "disk" in out["routes"]
    assert "prompt" in out["routes"]
    assert Path(out["ack_file"]).is_file()

    # Also test lead_ack function directly
    rc, result = mod.lead_ack(
        worker=SENDER,
        msg_id=TEST_MSG_ID,
        done=str(done_file),
        timeout=5.0,
        paseo=str(fake_paseo),
    )
    assert rc == 0
    assert result["status"] == "acked"


def test_footer_and_teaching_require_the_shape():
    footer = FOOTER.read_text()
    assert "done: <title>, <PR URL>" in footer
    assert "Please reply: ack <your agent id> <msg-id>" in footer
    assert "bin/completion-notice" in footer
    assert "dual routes" in footer
    assert "bin/completion-notice --check-ack" in footer

    fan = FANOUT.read_text()
    assert "completion-notice" in fan
    assert "paseo send --json --no-wait" in fan
    assert "done: <title>, <PR URL>" in fan
    assert "dual routes" in fan
    assert "bin/completion-notice --lead-ack" in fan

    orch = ORCH.read_text()
    assert "Push on completion" in orch
    assert "completion-notice" in orch
    assert "Dual-route completion proof" in orch
    assert "https://github.com/getpaseo/paseo/issues/9498" in orch
    assert "bin/completion-notice --lead-ack" in orch
    assert "bin/completion-notice --check-ack" in orch

    agents = AGENTS.read_text()
    assert "ruling 2026-11-12" in agents
    assert "dual routes" in agents
    assert "prompt `ack <sender id> <msg-id>`" in agents
    assert "atomic `<done>.ack` disk artifact" in agents
