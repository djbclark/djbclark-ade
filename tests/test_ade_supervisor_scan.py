"""bin/ade-supervisor-scan (2026-11-18): one notice per newly stuck Pi agent, and no repeat while it stays stuck.

The scan runs its sibling bin/ade-pi-stuck (faked here by a script that prints a fixture) and `paseo` (a fake that
records its argv and answers `agent inspect` from a file). A temporary HOME and state dir isolate the run, so nothing
touches the real supervisor state, launchd, Paseo or the network. Every fake is written through `_script`, which joins
lines with a real newline: no shell text is ever assembled by escaping inside a Python literal.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCAN = REPO / "bin" / "ade-supervisor-scan"
LEAD = "11111111-2222-3333-4444-555555555555"      # the test's own lead id, never a real session
NL = chr(10)


def _script(path: Path, *lines: str) -> None:
    path.write_text(NL.join(lines) + NL)
    path.chmod(0o755)


def _harness(tmp_path: Path, feed: list[dict], paseo_rc: int = 5):
    """A sandbox with a copy of the scan, the fixture behind it and a recording `paseo`."""
    home = tmp_path / "home"
    state = home / ".local" / "state" / "djbclark-ade" / "supervisor"
    state.mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shutil.copy2(SCAN, bin_dir / "ade-supervisor-scan")
    (bin_dir / "feed.json").write_text(json.dumps({"stuck": feed}))
    _script(bin_dir / "ade-pi-stuck", "#!/bin/sh", "cat " + str(bin_dir / "feed.json"))
    sent = tmp_path / "sent.log"
    _script(bin_dir / "paseo", "#!/bin/sh", 'case "$1" in',
            '  send) echo "$*" >> ' + str(sent) + '; exit ' + str(paseo_rc) + ";;",
            "esac", "exit 0")
    return bin_dir, home, state, sent


def _run(bin_dir: Path, home: Path, lead: str | None = LEAD) -> int:
    """Run the copy under the test's own HOME and state dir: the caller's ADE_SUPERVISOR_* never leak in."""
    state = home / ".local" / "state" / "djbclark-ade" / "supervisor"
    env = dict(os.environ, HOME=str(home), PATH=f"{bin_dir}:{os.environ['PATH']}")
    env.pop("ADE_SUPERVISOR_LEAD", None)
    env["ADE_SUPERVISOR_STATE_DIR"] = str(state)
    if lead is not None:
        env["ADE_SUPERVISOR_LEAD"] = lead
    return subprocess.run([str(bin_dir / "ade-supervisor-scan")], env=env, capture_output=True, text=True).returncode


def _calls(sent: Path, verb: str) -> list[str]:
    return [line for line in sent.read_text().splitlines() if line.startswith(verb + " ")] if sent.exists() else []


def _messages(sent: Path) -> list[str]:
    """The `paseo send` calls only: the scan also inspects the lead before sending."""
    return _calls(sent, "send")


def _agent(ident: str, account: str = "openai", status: str = "running") -> dict:
    return {"id": ident, "name": ident, "account": account, "model": f"{account}/gpt-6.1-sol", "status": status,
            "stuck": True, "headroom_percent": 0.0, "quota_stale": False,
            "alternative": "pi/opencode-go-t-e/deepseek-v4-pro"}


def test_one_message_names_every_newly_stuck_agent(tmp_path: Path) -> None:
    bin_dir, home, _, sent = _harness(tmp_path, [_agent("a1"), _agent("b2", "anthropic")])
    assert _run(bin_dir, home) == 0
    messages = _messages(sent)
    assert len(messages) == 1
    assert LEAD in messages[0]
    assert "2 new finding(s)" in messages[0] and "id=a1" in messages[0] and "id=b2" in messages[0]


def test_a_stuck_agent_is_noticed_once_not_every_run(tmp_path: Path) -> None:
    bin_dir, home, _, sent = _harness(tmp_path, [_agent("a1")])
    for _ in range(4):                                   # 4 runs at StartInterval 300 = 20 minutes
        assert _run(bin_dir, home) == 0
    assert len(_messages(sent)) == 1


def test_cleared_agent_leaves_the_state_and_is_noticed_again_later(tmp_path: Path) -> None:
    bin_dir, home, state, sent = _harness(tmp_path, [_agent("a1"), _agent("b2")])
    assert _run(bin_dir, home) == 0
    (bin_dir / "feed.json").write_text(json.dumps({"stuck": [_agent("a1")]}))            # b2 recovered
    assert _run(bin_dir, home) == 0
    assert json.loads((state / "notified").read_text()) == ["a1|openai"]
    assert len(_messages(sent)) == 1                                     # the shrink alone says nothing
    (bin_dir / "feed.json").write_text(json.dumps({"stuck": [_agent("a1"), _agent("b2")]}))  # b2 stuck again
    assert _run(bin_dir, home) == 0
    messages = _messages(sent)
    assert len(messages) == 2 and "id=b2" in messages[1] and "id=a1" not in messages[1]


def test_closed_and_archived_agents_are_ignored(tmp_path: Path) -> None:
    bin_dir, home, state, sent = _harness(tmp_path, [_agent("a1", status="closed"), _agent("b2", status="archived")])
    assert _run(bin_dir, home) == 0
    assert _messages(sent) == [] and json.loads((state / "notified").read_text()) == []


def test_an_undelivered_send_keeps_the_notice_for_the_next_run(tmp_path: Path) -> None:
    bin_dir, home, state, sent = _harness(tmp_path, [_agent("a1")], paseo_rc=2)   # 2 = not delivered
    assert _run(bin_dir, home) == 0
    assert len(_messages(sent)) == 1
    assert not (state / "notified").exists() or json.loads((state / "notified").read_text()) == []
    _script(bin_dir / "paseo", "#!/bin/sh", 'case "$1" in', '  send) echo "$*" >> ' + str(sent) + "; exit 5;;", "esac")
    assert _run(bin_dir, home) == 0
    assert len(_messages(sent)) == 2 and json.loads((state / "notified").read_text()) == ["a1|openai"]


def test_an_unset_lead_is_logged_and_sends_nothing(tmp_path: Path) -> None:
    """The lead id is never baked into the script: the environment or the state file supplies it."""
    bin_dir, home, state, sent = _harness(tmp_path, [_agent("a1")])
    assert _run(bin_dir, home, lead=None) == 0
    assert _messages(sent) == []
    assert "no lead (neither ADE_SUPERVISOR_LEAD nor" in (state / "supervisor.log").read_text()


def test_the_lead_can_come_from_the_state_file(tmp_path: Path) -> None:
    """A lead handoff rewrites one file; the plist and its inventory row carry no agent id at all."""
    bin_dir, home, state, sent = _harness(tmp_path, [_agent("a1")])
    (state / "lead").write_text(LEAD + NL)
    assert _run(bin_dir, home, lead=None) == 0
    messages = _messages(sent)
    assert len(messages) == 1 and LEAD in messages[0]


def test_a_broken_scan_alerts_the_lead_once(tmp_path: Path) -> None:
    bin_dir, home, state, sent = _harness(tmp_path, [])
    _script(bin_dir / "ade-pi-stuck", "#!/bin/sh", "exit 7")
    for _ in range(3):
        assert _run(bin_dir, home) == 0
    messages = _messages(sent)
    assert len(messages) == 1 and "exit 7" in messages[0]
    assert "scan|broken" in json.loads((state / "notified").read_text())
    _script(bin_dir / "ade-pi-stuck", "#!/bin/sh", "cat " + str(bin_dir / "feed.json"))
    assert _run(bin_dir, home) == 0
    assert "scan|broken" not in json.loads((state / "notified").read_text())


def test_non_json_output_alerts_the_lead_once(tmp_path: Path) -> None:
    bin_dir, home, state, sent = _harness(tmp_path, [])
    _script(bin_dir / "ade-pi-stuck", "#!/bin/sh", "echo not json at all")
    for _ in range(2):
        assert _run(bin_dir, home) == 0
    messages = _messages(sent)
    assert len(messages) == 1 and "no usable JSON" in messages[0]


def test_json_that_is_not_an_object_alerts_instead_of_vanishing(tmp_path: Path) -> None:
    bin_dir, home, state, sent = _harness(tmp_path, [])
    _script(bin_dir / "ade-pi-stuck", "#!/bin/sh", "echo []")
    assert _run(bin_dir, home) == 0
    messages = _messages(sent)
    assert len(messages) == 1 and "no usable JSON" in messages[0]


def test_a_transient_failure_does_not_reannounce_known_agents(tmp_path: Path) -> None:
    """The broken-scan alert keeps the keys already told: a stuck agent is not re-announced after a blip."""
    bin_dir, home, state, sent = _harness(tmp_path, [_agent("a1")])
    assert _run(bin_dir, home) == 0
    _script(bin_dir / "ade-pi-stuck", "#!/bin/sh", "exit 7")
    assert _run(bin_dir, home) == 0                                     # the outage alert
    _script(bin_dir / "ade-pi-stuck", "#!/bin/sh", "cat " + str(bin_dir / "feed.json"))
    assert _run(bin_dir, home) == 0                                     # a1 is still stuck
    messages = _messages(sent)
    assert len(messages) == 2 and "id=a1" not in messages[1]
    assert json.loads((state / "notified").read_text()) == ["a1|openai"]


def test_an_archived_lead_is_not_messaged_and_the_operator_is_pinged_once(tmp_path: Path) -> None:
    """A send to an archived agent un-archives it, so the scan refuses; the operator hears about it once."""
    bin_dir, home, state, sent = _harness(tmp_path, [_agent("a1")])
    inspect = tmp_path / "inspect.json"
    inspect.write_text(json.dumps({"Archived": True}))
    _script(bin_dir / "paseo", "#!/bin/sh", 'case "$1" in',
            '  send) echo "$*" >> ' + str(sent) + ";;",
            "  *) cat " + str(inspect) + ";;",
            "esac")
    pinged = tmp_path / "hermes.log"
    _script(bin_dir / "hermes-ping", "#!/bin/sh", 'echo "$*" >> ' + str(pinged))
    for _ in range(2):
        assert _run(bin_dir, home) == 0
    assert _messages(sent) == []
    assert len(pinged.read_text().splitlines()) == 1
    assert not (state / "notified").exists()          # nothing was told, so the notice is still pending
