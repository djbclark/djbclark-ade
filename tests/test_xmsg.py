"""bin/xmsg (2026-11-21): the cross-harness messaging contract, machine-checkable.

The reply path is explicit, an ack file is written only by its receiver, and the
sender's own `queued` status is never an ack. paseo is faked; nothing reaches a live Paseo.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
XMSG = REPO / "bin" / "xmsg"


def _fake_paseo(tmp_path: Path, status: str = "queued", rc: int = 0, stdout: str | None = None) -> tuple[dict[str, str], Path]:
    """A `paseo` on PATH that records its argv (one arg per line) and answers JSON."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir()
    log = tmp_path / "paseo.argv"
    out = stdout if stdout is not None else '{"status": "%s"}' % status
    script = "#!/bin/sh\nfor a in \"$@\"; do printf '%s\\n' \"$a\" >> '" + str(log) + "'; done\n"
    script += "printf '%s\\n' '" + out + "'\nexit " + str(rc) + "\n"
    _ = (bin_dir / "paseo").write_text(script)
    _ = (bin_dir / "paseo").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "PASEO_AGENT_ID"}
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return env, log


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(XMSG), *args], capture_output=True, text=True, env=env)


def test_to_claude_writes_atomically_to_the_exact_path(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "lead-reply.md"
    r = _run("to-claude", str(target), "ack sess-1 hello")
    assert r.returncode == 0, r.stderr
    assert target.read_text() == "ack sess-1 hello\n"
    assert sorted(p.name for p in target.parent.iterdir()) == ["lead-reply.md"]  # no temp litter


def test_ack_writes_the_first_line_the_sender_requires(tmp_path: Path) -> None:
    target = tmp_path / "lead-reply.md"
    r = _run("ack", str(target), "ack sess-9 hello")
    assert r.returncode == 0, r.stderr
    assert target.read_text().splitlines()[0] == "ack sess-9 hello"


def test_ack_never_clobbers_an_existing_file_unless_replace(tmp_path: Path) -> None:
    target = tmp_path / "lead-reply.md"
    assert _run("ack", str(target), "ack first").returncode == 0
    r = _run("ack", str(target), "ack second")
    assert r.returncode == 3 and "already exists" in r.stderr
    assert target.read_text() == "ack first\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["lead-reply.md"]  # temp removed on refusal
    assert _run("ack", "--replace", str(target), "ack second").returncode == 0
    assert target.read_text() == "ack second\n"


def test_to_paseo_never_writes_the_ack_file_only_a_status_file(tmp_path: Path) -> None:
    """M2: the sender's own `queued` must not appear where the peer's ack lands."""
    env, _ = _fake_paseo(tmp_path, "queued")
    reply = tmp_path / "lead-reply.md"
    r = _run("to-paseo", "--reply-file", str(reply), "--reply-name", "djbclark-3b", "b0b47ad8", "hello", env=env)
    assert r.returncode == 5, r.stderr  # accepted, not delivered
    assert not reply.exists()
    assert Path(str(reply) + ".status").read_text() == "xmsg-status: queued\n"


def test_peer_ack_after_to_paseo_is_not_overwritten_by_the_sender(tmp_path: Path) -> None:
    env, _ = _fake_paseo(tmp_path, "queued")
    reply = tmp_path / "lead-reply.md"
    assert _run("ack", str(reply), "ack peer-1 real ack").returncode == 0  # peer ack lands first
    r = _run("to-paseo", "--reply-file", str(reply), "--reply-name", "n", "b0b47ad8", "again", env=env)
    assert r.returncode == 3  # refuses a pre-existing reply path
    assert reply.read_text() == "ack peer-1 real ack\n"


def test_reply_path_and_route_are_in_the_message_text(tmp_path: Path) -> None:
    env, log = _fake_paseo(tmp_path, "queued")
    reply = tmp_path / "r.md"
    _ = _run("to-paseo", "--reply-file", str(reply), "--reply-name", "djbclark-3b", "b0b47ad8", "hello", env=env)
    argv = log.read_text().splitlines()
    assert argv[:3] == ["send", "--json", "--no-wait"]
    assert argv[-2:] == ["--", "b0b47ad8"]  # id after --, so a leading "-" cannot be a flag
    prompt = argv[argv.index("--prompt") + 1:argv.index("--")]
    text = "\n".join(prompt)
    assert "hello" in text and f"xmsg ack {reply}" in text and "SendMessage to djbclark-3b" in text


def test_sender_outside_paseo_needs_both_reply_routes(tmp_path: Path) -> None:
    env, log = _fake_paseo(tmp_path)
    assert _run("to-paseo", "b0b47ad8", "hi", env=env).returncode == 2
    assert _run("to-paseo", "--reply-file", str(tmp_path / "r.md"), "b0b47ad8", "hi", env=env).returncode == 2
    assert _run("to-paseo", "--reply-name", "n", "b0b47ad8", "hi", env=env).returncode == 2
    assert not log.exists()  # nothing was sent


def test_a_paseo_sender_asks_for_an_ack_to_its_own_id(tmp_path: Path) -> None:
    env, log = _fake_paseo(tmp_path, "queued")
    env["PASEO_AGENT_ID"] = "aaaa1111-0000-0000-0000-000000000000"
    r = _run("to-paseo", "b0b47ad8", "hi", env=env)
    assert r.returncode == 5
    assert "ack aaaa1111-0000-0000-0000-000000000000" in log.read_text()


def test_exit_code_separates_delivered_from_accepted_from_failed(tmp_path: Path) -> None:
    for status, want in (("sent", 0), ("completed", 0), ("queued", 5)):
        sub = tmp_path / status
        sub.mkdir()
        env, _ = _fake_paseo(sub, status)
        env["PASEO_AGENT_ID"] = "me"
        assert _run("to-paseo", "x", "hi", env=env).returncode == want, status
    sub = tmp_path / "fail"
    sub.mkdir()
    env, _ = _fake_paseo(sub, rc=1)
    env["PASEO_AGENT_ID"] = "me"
    assert _run("to-paseo", "x", "hi", env=env).returncode == 1
    sub = tmp_path / "notjson"
    sub.mkdir()
    env, _ = _fake_paseo(sub, stdout="not json")
    env["PASEO_AGENT_ID"] = "me"
    r = _run("to-paseo", "x", "hi", env=env)
    assert r.returncode == 1 and "failed" in r.stderr


def test_unknown_direction_and_missing_args_are_usage_errors() -> None:
    assert _run("bogus").returncode == 2
    assert _run("ack", "only-a-path").returncode == 2
    assert _run().returncode == 2


def test_agent_surfaces_skill_never_routes_keystrokes_into_an_agent_pane() -> None:
    """M1 and M3, held in the skill text."""
    text = (REPO / "skills" / "agent-surfaces" / "SKILL.md").read_text()
    assert "inbox/<anything>" not in text and ".msg" not in text
    assert "SendMessage" in text and "xmsg to-claude" in text
    # the only mention of pane typing is the prohibition (matches the herdr skill's ADE overlay)
    flat = " ".join(text.split())
    assert re.search(r"Never `herdr agent prompt`, `send-keys` or `pane run` into an agent pane", flat)
    allowed = flat.replace("Never `herdr agent prompt`, `send-keys` or `pane run` into an agent pane", "")
    assert "herdr agent prompt" not in allowed and "pane run" not in allowed.replace("`pane run` has no", "")
