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


def _harness(tmp_path: Path, feed: list[dict], paseo_rc: int = 5, extra: dict | None = None):
    """A sandbox with a copy of the scan, the fixture behind it and a recording `paseo`."""
    home = tmp_path / "home"
    state = home / ".local" / "state" / "djbclark-ade" / "supervisor"
    state.mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shutil.copy2(SCAN, bin_dir / "ade-supervisor-scan")
    for module in (REPO / "bin").glob("*.py"):      # ade_send_guard.py and its imports, as an install has them
        (bin_dir / module.name).symlink_to(module)
    (bin_dir / "feed.json").write_text(json.dumps(dict({"stuck": feed}, **(extra or {}))))
    _script(bin_dir / "ade-pi-stuck", "#!/bin/sh", "cat " + str(bin_dir / "feed.json"))
    sent = tmp_path / "sent.log"
    _paseo(bin_dir, tmp_path, sent, rc=paseo_rc)
    # Always stub hermes-ping: a real one on PATH would message the operator for real from a test.
    pinged = tmp_path / "hermes.log"
    _script(bin_dir / "hermes-ping", "#!/bin/sh", 'echo "$*" >> ' + str(pinged))
    return bin_dir, home, state, sent


def _paseo(bin_dir: Path, tmp_path: Path, sent: Path, rc: int = 5, archived: bool = False) -> None:
    """A fake `paseo`: `send` logs and exits with `rc`; `agent inspect` answers from a file (live unless `archived`)."""
    inspect = tmp_path / "inspect.json"
    inspect.write_text(json.dumps({"Archived": archived, "Id": LEAD, "Status": "idle"}))
    _script(bin_dir / "paseo", "#!/bin/sh", 'case "$1" in',
            '  send) echo "$*" >> ' + str(sent) + "; exit " + str(rc) + ";;",
            "  agent) cat " + str(inspect) + ";;",
            "esac", "exit 0")


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
    _paseo(bin_dir, tmp_path, sent, rc=5)
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
    _paseo(bin_dir, tmp_path, sent, archived=True)
    _script(bin_dir / "hermes-ping", "#!/bin/sh", 'echo "$*" >> ' + str(tmp_path / "hermes.log"))
    for _ in range(2):
        assert _run(bin_dir, home) == 0
    assert _messages(sent) == []
    assert len((tmp_path / "hermes.log").read_text().splitlines()) == 1
    assert not (state / "notified").exists()          # nothing was told, so the notice is still pending


def test_a_paseo_outage_escalates_after_the_guard_fails_open(tmp_path: Path) -> None:
    """The guard fails open when Paseo cannot answer (a documented choice, as in ade-progress): the send then fails
    and the operator is pinged once, rather than the notice vanishing."""
    bin_dir, home, state, sent = _harness(tmp_path, [_agent("a1")])
    _script(bin_dir / "paseo", "#!/bin/sh",
            'case "$1" in', '  send) echo "$*" >> ' + str(sent) + "; exit 2;;", "  *) exit 4;;", "esac")
    assert _run(bin_dir, home) == 0
    assert len(_messages(sent)) == 1                                     # attempted, and it failed
    assert len((tmp_path / "hermes.log").read_text().splitlines()) == 1
    assert (state / ".lead-unreachable.unreachable").exists()


def test_a_failed_escalation_is_retried_next_run(tmp_path: Path) -> None:
    """The unreachable marker is written only after hermes-ping succeeds, so a failed ping is retried."""
    bin_dir, home, state, sent = _harness(tmp_path, [_agent("a1")])
    _paseo(bin_dir, tmp_path, sent, archived=True)
    calls = tmp_path / "ping.calls"
    _script(bin_dir / "hermes-ping", "#!/bin/sh", "echo x >> " + str(calls), "exit 1")
    assert _run(bin_dir, home) == 0
    assert _run(bin_dir, home) == 0
    assert len(calls.read_text().splitlines()) == 2          # retried, because it never reached the operator
    assert not (state / ".lead-unreachable.unreachable").exists()


def test_a_replaced_lead_redirects_the_notice_to_its_successor(tmp_path: Path) -> None:
    """After a lead self-handoff ade_send_guard answers "redirect" (exit 3): the notice follows the successor."""
    bin_dir, home, state, sent = _harness(tmp_path, [_agent("a1")])
    (bin_dir / "ade_send_guard.py").unlink()          # stands in for the guard's redirect decision
    _script(bin_dir / "ade_send_guard.py", "#!/usr/bin/env python3", "import json",
            'print(json.dumps({"action": "redirect", "target": "SUCCESSOR-ID", "reason": "replaced by a handoff"}))',
            "raise SystemExit(3)")
    (state / "lead").write_text(LEAD + NL)               # the lead comes from the file, so the redirect rewrites it
    assert _run(bin_dir, home, lead=None) == 0
    messages = _messages(sent)
    assert len(messages) == 1 and "-- SUCCESSOR-ID " in messages[0]     # `--` before the id, as ade-net-resume does
    assert json.loads((state / "notified").read_text()) == ["a1|openai"]
    assert "was replaced; sending to SUCCESSOR-ID" in (state / "supervisor.log").read_text()
    assert (state / "lead").read_text().strip() == "SUCCESSOR-ID"      # the handoff is followed, not logged forever
    assert _run(bin_dir, home, lead=None) == 0                        # the next run reads the new lead ...
    assert len(_messages(sent)) == 1                                  # ... and has nothing new to say


def test_a_lead_value_that_is_not_an_id_is_ignored(tmp_path: Path) -> None:
    """A lead value that could be read as a `paseo send` option never reaches the command."""
    bin_dir, home, state, sent = _harness(tmp_path, [_agent("a1")])
    assert _run(bin_dir, home, lead="--dangerous") == 0
    assert _messages(sent) == []
    assert "is not an agent id" in (state / "supervisor.log").read_text()


def test_a_thin_account_is_reported_before_it_hits_zero(tmp_path: Path) -> None:
    extra = {"low": ["anthropic"], "accounts": {"anthropic": {"headroom": 4.0, "usable": True, "stale": False}}}
    bin_dir, home, state, sent = _harness(tmp_path, [], extra=extra)
    assert _run(bin_dir, home) == 0
    messages = _messages(sent)
    assert len(messages) == 1 and "anthropic is thin (4.0% headroom)" in messages[0]
    assert _run(bin_dir, home) == 0
    assert len(_messages(sent)) == 1                     # told once, not every 300 s


def test_a_failed_quota_read_alerts_the_lead_once(tmp_path: Path) -> None:
    """ade-pi-stuck still reports the known-empty agents; the unread rest is its own once-per-outage alert."""
    extra = {"quota_error": "aiuse exited 1"}
    bin_dir, home, state, sent = _harness(tmp_path, [_agent("a1")], extra=extra)
    for _ in range(2):
        assert _run(bin_dir, home) == 0
    messages = _messages(sent)
    assert len(messages) == 1
    assert "quota unread" in messages[0] and "id=a1" in messages[0]
    assert "scan|quota-unread" in json.loads((state / "notified").read_text())


def test_a_guard_redirect_with_an_unusable_successor_is_refused(tmp_path: Path) -> None:
    bin_dir, home, state, sent = _harness(tmp_path, [_agent("a1")])
    (bin_dir / "ade_send_guard.py").unlink()
    _script(bin_dir / "ade_send_guard.py", "#!/usr/bin/env python3", "import json",
            'print(json.dumps({"action": "redirect", "target": "--not-an-id", "reason": "replaced"}))',
            "raise SystemExit(3)")
    assert _run(bin_dir, home) == 0
    assert _messages(sent) == []
    log = (state / "supervisor.log").read_text()
    assert 'successor id "--not-an-id" is unusable' in log        # %r would have cut the line short here
    assert len((tmp_path / "hermes.log").read_text().splitlines()) == 1
    assert not (state / "lead").exists()


def test_a_quota_unread_run_keeps_the_thin_accounts_it_already_told(tmp_path: Path) -> None:
    """Nothing can be read during an outage, so a thin account told before it is not announced again after it."""
    extra = {"low": ["anthropic"], "accounts": {"anthropic": {"headroom": 4.0, "usable": True, "stale": False}}}
    bin_dir, home, state, sent = _harness(tmp_path, [], extra=extra)
    assert _run(bin_dir, home) == 0
    assert len(_messages(sent)) == 1
    (bin_dir / "feed.json").write_text(json.dumps({"stuck": [], "quota_error": "aiuse exited 1"}))
    assert _run(bin_dir, home) == 0
    (bin_dir / "feed.json").write_text(json.dumps(
        {"stuck": [], "low": ["anthropic"], "accounts": {"anthropic": {"headroom": 4.0, "usable": True, "stale": False}}}))
    assert _run(bin_dir, home) == 0
    assert len(_messages(sent)) == 2                                     # the outage notice only, no repeat of thin|anthropic
    assert "anthropic is thin" not in _messages(sent)[-1]


def test_only_a_delivery_clears_the_escalation_marker(tmp_path: Path) -> None:
    bin_dir, home, state, sent = _harness(tmp_path, [_agent("a1")])
    _paseo(bin_dir, tmp_path, sent, rc=2)                                # the send fails
    assert _run(bin_dir, home) == 0
    assert (state / ".lead-unreachable.unreachable").exists()
    (bin_dir / "feed.json").write_text(json.dumps({"stuck": []}))        # nothing to send: no proof either
    _paseo(bin_dir, tmp_path, sent, rc=5)
    assert _run(bin_dir, home) == 0
    assert (state / ".lead-unreachable.unreachable").exists()


def test_each_cause_gets_its_own_escalation(tmp_path: Path) -> None:
    """One marker per cause: a bad lead during the same outage is still reported, not swallowed by the first."""
    bin_dir, home, state, sent = _harness(tmp_path, [_agent("a1")])
    assert _run(bin_dir, home, lead=None) == 0                                 # no lead at all
    assert _run(bin_dir, home, lead="--nope") == 0                             # a lead that is not an id
    assert _run(bin_dir, home, lead="not an id") == 0
    pings = (tmp_path / "hermes.log").read_text().splitlines()
    assert len(pings) == 2                                                     # one per distinct cause
    assert (state / ".lead-unreachable.no-lead").exists()
    assert (state / ".lead-unreachable.bad-lead").exists()


def test_an_unreadable_stuck_list_alerts_instead_of_dying(tmp_path: Path) -> None:
    bin_dir, home, state, sent = _harness(tmp_path, [])
    (bin_dir / "feed.json").write_text(json.dumps({"stuck": None}))
    assert _run(bin_dir, home) == 0
    messages = _messages(sent)
    assert len(messages) == 1 and "cannot read" in messages[0]
    (bin_dir / "feed.json").write_text(json.dumps({"stuck": ["not-a-dict"]}))
    assert _run(bin_dir, home) == 0
    assert len(_messages(sent)) == 1                     # the same alert key: told once
