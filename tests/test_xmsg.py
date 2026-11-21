"""bin/xmsg (2026-11-21): the cross-harness messaging contract, machine-checkable.

The reply path is always explicit, never guessed (the ~/.local/state/agent-reports/<id>/inbox
guess cost two failed exchanges). These tests prove: a to-claude write is atomic and the
target file appears whole; to-paseo with --reply-file records the send's own status; ack
writes the first line the sender requires. Nothing reaches a live Paseo: paseo is faked.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
XMSG = REPO / "bin" / "xmsg"


def _fake_paseo(tmp_path: Path) -> Path:
    """A `paseo` on PATH that records its argv and answers `{"status": "queued"}`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "paseo.argv"
    (bin_dir / "paseo").write_text(
        "#!/bin/sh\necho \"$*\" >> '" + str(log) + "'\n"
        "echo '{\"status\": \"queued\"}'\n")
    (bin_dir / "paseo").chmod(0o755)
    return bin_dir, log


def test_to_claude_writes_atomically_to_the_exact_path(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "lead-reply.md"
    r = subprocess.run([str(XMSG), "to-claude", str(target), "ack sess-1 hello"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert target.read_text() == "ack sess-1 hello\n"
    # no temp litter beside it
    assert sorted(p.name for p in target.parent.iterdir()) == ["lead-reply.md"]


def test_to_paseo_records_status_at_the_reply_file(tmp_path: Path) -> None:
    bin_dir, _ = _fake_paseo(tmp_path)
    reply = tmp_path / "lead-reply.md"
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    r = subprocess.run([str(XMSG), "to-paseo", "b0b47ad8", "hello", "--reply-file", str(reply)],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert reply.read_text() == "xmsg-status: queued\n"


def test_ack_writes_the_first_line_the_sender_requires(tmp_path: Path) -> None:
    target = tmp_path / "lead-reply.md"
    r = subprocess.run([str(XMSG), "ack", str(target), "ack sess-9 hello"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert target.read_text().splitlines()[0] == "ack sess-9 hello"
