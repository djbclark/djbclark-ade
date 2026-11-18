"""bin/ade-supervisor-scan (2026-11-18): one notice per newly stuck Pi agent, and no repeat while it stays stuck.

The scan runs its sibling bin/ade-pi-stuck (faked here by a script that prints a fixture) and `paseo send` (a fake that
records its argv and exits 5, Paseo's accepted-and-queued status for an agent-to-agent send). A temporary HOME isolates
the state dir, so nothing touches the real supervisor state, launchd, Paseo or the network."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCAN = REPO / "bin" / "ade-supervisor-scan"


def _harness(tmp_path: Path, feed: list[dict], paseo_rc: int = 5):
    """A sandbox with a copy of the scan, the fixture behind it and a recording `paseo`."""
    home = tmp_path / "home"
    state = home / ".local" / "state" / "djbclark-ade" / "supervisor"
    state.mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shutil.copy2(SCAN, bin_dir / "ade-supervisor-scan")
    fixture = bin_dir / "feed.json"
    fixture.write_text(json.dumps({"stuck": feed}))
    (bin_dir / "ade-pi-stuck").write_text(
        '#!/usr/bin/env python3\nimport pathlib, sys\nsys.stdout.write(pathlib.Path(sys.argv[0]).with_name("feed.json").read_text())\n')
    (bin_dir / "ade-pi-stuck").chmod(0o755)
    sent = tmp_path / "sent.log"
    (bin_dir / "paseo").write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {sent}\nexit {paseo_rc}\n")
    (bin_dir / "paseo").chmod(0o755)
    return bin_dir, home, state, fixture, sent


def _run(bin_dir: Path, home: Path) -> int:
    env = dict(os.environ, HOME=str(home), PATH=f"{bin_dir}:{os.environ['PATH']}")
    return subprocess.run([str(bin_dir / "ade-supervisor-scan")], env=env, capture_output=True, text=True).returncode


def _agent(ident: str, account: str = "openai") -> dict:
    return {"id": ident, "name": ident, "account": account, "model": f"{account}/gpt-6.1-sol", "status": "running",
            "stuck": True, "headroom_percent": 0.0, "quota_stale": False,
            "alternative": "pi/opencode-go-t-e/deepseek-v4-pro"}


def _messages(sent: Path) -> list[str]:
    return [line for line in sent.read_text().splitlines() if line] if sent.exists() else []


def test_one_message_names_every_newly_stuck_agent(tmp_path: Path) -> None:
    bin_dir, home, _, _, sent = _harness(tmp_path, [_agent("a1"), _agent("b2", "anthropic")])
    assert _run(bin_dir, home) == 0
    messages = _messages(sent)
    assert len(messages) == 1
    assert "b0b47ad8-8801-4780-a8e0-08824cd5ce27" in messages[0]      # the ADE lead
    assert "2 newly stuck" in messages[0] and "id=a1" in messages[0] and "id=b2" in messages[0]


def test_a_stuck_agent_is_noticed_once_not_every_run(tmp_path: Path) -> None:
    bin_dir, home, _, _, sent = _harness(tmp_path, [_agent("a1")])
    for _ in range(4):                                   # 4 runs at StartInterval 300 = 20 minutes
        assert _run(bin_dir, home) == 0
    assert len(_messages(sent)) == 1


def test_cleared_agent_leaves_the_state_and_is_noticed_again_later(tmp_path: Path) -> None:
    bin_dir, home, state, fixture, sent = _harness(tmp_path, [_agent("a1"), _agent("b2")])
    assert _run(bin_dir, home) == 0
    fixture.write_text(json.dumps({"stuck": [_agent("a1")]}))            # b2 recovered
    assert _run(bin_dir, home) == 0
    assert json.loads((state / "notified").read_text()) == ["a1|openai"]
    assert len(_messages(sent)) == 1                                     # the shrink alone says nothing
    fixture.write_text(json.dumps({"stuck": [_agent("a1"), _agent("b2")]}))  # b2 stuck again
    assert _run(bin_dir, home) == 0
    messages = _messages(sent)
    assert len(messages) == 2 and "id=b2" in messages[1] and "id=a1" not in messages[1]


def test_closed_and_archived_agents_are_ignored(tmp_path: Path) -> None:
    gone = _agent("a1")
    gone["status"] = "closed"
    bin_dir, home, state, _, sent = _harness(tmp_path, [gone])
    assert _run(bin_dir, home) == 0
    assert _messages(sent) == [] and json.loads((state / "notified").read_text()) == []


def test_an_undelivered_send_keeps_the_notice_for_the_next_run(tmp_path: Path) -> None:
    bin_dir, home, state, fixture, sent = _harness(tmp_path, [_agent("a1")], paseo_rc=2)   # 2 = not delivered
    assert _run(bin_dir, home) == 0
    assert len(_messages(sent)) == 1
    assert not (state / "notified").exists() or json.loads((state / "notified").read_text()) == []
    (bin_dir / "paseo").write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {sent}\nexit 5\n")  # now delivered
    assert _run(bin_dir, home) == 0
    assert len(_messages(sent)) == 2 and json.loads((state / "notified").read_text()) == ["a1|openai"]
