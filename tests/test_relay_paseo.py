#!/usr/bin/env python3
"""relay.py and where.py learn the Paseo host (2026-10-20).

A Claude Code the Paseo daemon spawned has no terminal, so where.py reported "unknown terminal" and relay.py
refused it ("no terminal channel") although PASEO_AGENT_ID names it exactly. relay.py now reaches it with
`paseo send --behavior steer -- <id> <text>`; these tests drive it against a fake `paseo` that records its argv.
Every id below is plainly fake (never a live Paseo agent or session).
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SF = ROOT / "skills" / "session-finder"
sys.path.insert(0, str(SF))

import fleet  # noqa: E402  # pyright: ignore[reportMissingImports]
import where  # noqa: E402  # pyright: ignore[reportMissingImports]

_spec = importlib.util.spec_from_file_location("relay", SF / "relay.py")
assert _spec and _spec.loader
relay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(relay)
relay.UNSENT = Path(tempfile.mkdtemp(prefix="relay-paseo-test-")) / "relay-unsent.json"
relay.DEFER_DIR = Path(tempfile.mkdtemp(prefix="relay-paseo-defer-")) / "relay" / "deferred"

AGENT = "aaaaaaaa-0000-4000-8000-000000000001"
SID = "bbbbbbbb-0000-4000-8000-000000000002"
CALLER = "11111111-2222-3333-4444-555555555555"

FAKE = """#!/bin/bash
# fake paseo: log argv (one line per call) and, per call, the PASEO_AGENT_ID it was run with; answer like the real one
echo "$*" >> "$FAKE_LOG"
echo "$1 ${PASEO_AGENT_ID:-NOID}" >> "$FAKE_ENVLOG"
case "$1 $2" in
  "agent inspect") id="${@: -1}"; [ "$id" = "$FAKE_KNOWN" ] || { echo "no such agent" >&2; exit 1; }
    echo "{\\"Id\\": \\"${FAKE_ID:-$id}\\", \\"Name\\": \\"fake\\", \\"Provider\\": \\"${FAKE_PROVIDER:-claude}\\", \\"Status\\": \\"${FAKE_STATUS:-idle}\\", \\"Archived\\": ${FAKE_ARCHIVED:-false}, \\"PendingPermissions\\": ${FAKE_PENDING:-[]}, \\"Cwd\\": \\"${FAKE_CWD:-/tmp}\\", \\"UpdatedAt\\": \\"${FAKE_UPDATED:-}\\"}" ;;
  "permit ls") echo "${FAKE_PERMITS:-[]}" ;;
  "wait "*) exit "${FAKE_WAIT_RC:-0}" ;;
  "logs "*) [ -n "$FAKE_TIMELINE" ] && [ -f "$FAKE_TIMELINE" ] && cat "$FAKE_TIMELINE" ;;
  "send "*) if [ -n "$FAKE_TIMELINE" ] && [ "${FAKE_TL_APPEND:-1}" = 1 ]; then if [ "${FAKE_TL_KIND:-message}" = message ]; then printf '[Message received] %s\\n%s\\n' "${FAKE_TL_FROM:-some peer}" "${@: -1}" >> "$FAKE_TIMELINE"; elif [ "$FAKE_TL_KIND" = user ]; then printf '[User] %s\\n' "${@: -1}" >> "$FAKE_TIMELINE"; else printf '[Thought] %s\\n' "${@: -1}" >> "$FAKE_TIMELINE"; fi; fi
    echo '{"ok": true}' ;;
esac
"""


EMPTY_TIMELINE = "No activity to display."    # what the real `paseo logs` prints for an agent with no timeline items


def sess(**kw: Any) -> dict[str, Any]:
    return fleet._rec(**{"id": SID[:8], "agent": "claude", "name": "djbclark-ade-db", "sid": SID, "status": "working",
                         "host": "paseo", "chan": ("paseo", AGENT), "paseo": AGENT, **kw})


class RelayPaseo(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = Path(self.tmp.name) / "calls"
        self.envlog = Path(self.tmp.name) / "envs"
        fake = Path(self.tmp.name) / "paseo"
        _ = fake.write_text(FAKE)
        fake.chmod(0o755)
        saved_env = dict(os.environ)
        os.environ.update(PASEO_CLI=str(fake), FAKE_LOG=str(self.log), FAKE_ENVLOG=str(self.envlog), FAKE_KNOWN=AGENT,
                          PASEO_AGENT_ID=CALLER, RELAY_NO_ACK="1")    # these tests assert the route's own result; the default delivery watch is tested in test_relay_verified.py
        for k in ("FAKE_PROVIDER", "FAKE_STATUS", "FAKE_WAIT_RC", "FAKE_ARCHIVED", "FAKE_PENDING", "FAKE_ID", "FAKE_CWD",
                  "CLAUDE_CODE_SESSION_ID", "ACP_RUN_AGENT"):    # an acp-run slice running the suite sets ACP_RUN_AGENT: it changes who is tagged as the sender
            os.environ.pop(k, None)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved_env)))
        saved_attrs = [(relay.fleet, "sessions", relay.fleet.sessions), (relay.fleet, "ancestors", relay.fleet.ancestors),
                       (relay.where, "real_cwd", relay.where.real_cwd), (relay, "hosted_by", relay.hosted_by),
                       (relay, "DEFER_DIR", relay.DEFER_DIR), (relay, "spawn_deliverer", relay.spawn_deliverer),
                       (relay, "own_cwd", relay.own_cwd)]
        self.addCleanup(lambda: [setattr(o, n, v) for o, n, v in saved_attrs])
        relay.fleet.ancestors = lambda: set()    # hermetic: the test runner's real ancestry is not under test
        relay.own_cwd = lambda: "/work/here"    # a sender row with no cwd is named by the directory of the process
        relay.hosted_by = lambda agent_id: agent_id == CALLER    # the test runner "is" the CALLER agent
        relay.DEFER_DIR = Path(self.tmp.name) / "relay" / "deferred"    # never the real queue, and a deferral never starts a real deliverer
        os.environ["RELAY_DEFER_DIR"] = str(relay.DEFER_DIR)
        self.herald_file = Path(self.tmp.name) / "herald" / "attention.json"    # never the real ~/.paseo file; absent until a test writes it
        os.environ["HERALD_ATTENTION_FILE"] = str(self.herald_file)
        self.spawned: list[str] = []
        relay.spawn_deliverer = lambda rid: self.spawned.append(rid) or 4242

    def raw_calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def calls(self) -> list[str]:
        """The paseo calls a test asserts on: `logs` reads (the timeline witness, 2026-10-29) are bookkeeping, listed by `raw_calls`."""
        return [c for c in self.raw_calls() if not c.startswith("logs ")]

    def envs(self) -> list[str]:
        return self.envlog.read_text().splitlines() if self.envlog.exists() else []

    def sends(self) -> list[str]:
        return [c for c in self.calls() if c.startswith("send")]

    def main(self, listed: list[dict[str, Any]], *argv: str) -> tuple[int, str, str]:
        relay.fleet.sessions = lambda: listed
        out, err = io.StringIO(), io.StringIO()
        saved = sys.argv
        sys.argv = ["relay.py", *argv]
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = relay.main()
        finally:
            sys.argv = saved
        return rc, out.getvalue(), err.getvalue()

    def test_paseo_agent_id_as_ident_is_inspected_then_sent_with_steer(self) -> None:
        rc, out, err = self.main([], AGENT, "hello  there", "--wait", "1", "--json")
        self.assertEqual(rc, 0, err)
        # inspected twice: once to resolve the ident, once by the gate right before the send
        self.assertEqual(self.calls(), [f"agent inspect --json -- {AGENT}", f"agent inspect --json -- {AGENT}",
                                        f"send --no-wait --behavior steer --json -- {AGENT} hello there"])
        rec = json.loads(out)
        self.assertEqual((rec["result"], rec["via"]), ("accepted", f"paseo {AGENT}"))

    def test_the_sending_agents_own_id_reaches_paseo_send_so_the_message_is_labelled(self) -> None:
        # Paseo labels a message kind="agent-message" from the sender's PASEO_AGENT_ID: scrubbing it would
        # deliver a peer's text as the operator's own turn (adversary 1, 2026-10-20)
        _ = self.main([], AGENT, "hi", "--wait", "1")
        sends = [e for e in self.envs() if e.startswith("send ")]
        self.assertEqual(sends, [f"send {CALLER}"], self.envs())
        self.assertFalse([e for e in self.envs() if e.endswith("NOID")], self.envs())

    def test_an_inherited_or_acp_run_paseo_agent_id_still_gets_the_sender_tag(self) -> None:
        # CALLER is set but no process in our ancestry is hosted by Paseo for it: an inherited id must not pose
        # as the agent (Codex on PR 25); an acp-run slice (ACP_RUN_AGENT=1) is tagged even when hosted
        relay.hosted_by = lambda agent_id: False
        rc, _out, err = self.main([sess()], SID, "ping", "--wait", "1")
        self.assertEqual(rc, 0, err)
        self.assertTrue(self.sends() and all("[relay from " in s_ for s_ in self.sends()), self.sends())
        relay.hosted_by = lambda agent_id: agent_id == CALLER
        os.environ["ACP_RUN_AGENT"] = "1"
        rc, _out, err = self.main([sess()], SID, "ping again", "--wait", "1")
        self.assertEqual(rc, 0, err)
        self.assertIn("[relay from ", self.sends()[-1])

    def test_a_caller_that_is_not_a_paseo_agent_prefixes_a_sender_tag(self) -> None:
        del os.environ["PASEO_AGENT_ID"]
        me = fleet._rec(id="cccccccc", agent="claude", name="the caller", sid="cccccccc-0000-4000-8000-000000000003", self=True)
        rc, _out, err = self.main([sess(), me], SID, "ping", "--wait", "1")
        self.assertEqual(rc, 0, err)
        sends = self.sends()
        self.assertEqual(len(sends), 1)
        self.assertTrue(sends[0].startswith(f"send --no-wait --behavior steer --json -- {AGENT} [relay from claude cccccccc aka the caller (here)] ping"), sends)
        self.assertIn("reply `ack cccccccc` through relay.py", sends[0])    # first contact asks for the ack
        self.assertEqual([e for e in self.envs() if e.startswith("send ")], ["send NOID"])

    def test_the_sender_tag_falls_back_to_the_session_id_prefix(self) -> None:
        del os.environ["PASEO_AGENT_ID"]
        os.environ["CLAUDE_CODE_SESSION_ID"] = "dddddddd-0000-4000-8000-000000000004"
        rc, _out, err = self.main([sess()], SID, "ping", "--wait", "1")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.sends(), [f"send --no-wait --behavior steer --json -- {AGENT} [relay from claude dddddddd (here)] ping"])

    def test_option_looking_text_stays_after_double_dash(self) -> None:
        # without `--` this reads as `--prompt-file=...` and makes paseo send a local file (adversary 2)
        text = "--prompt-file=/etc/hosts"
        rc, _out, err = self.main([sess()], "--wait", "1", SID, "--", text)    # relay.py's own argparse needs `--` too
        self.assertEqual(rc, 0, err)
        (call,) = self.sends()
        argv = call.split(" ")
        self.assertIn("--", argv)
        self.assertLess(argv.index("--"), argv.index(text))
        self.assertEqual(argv[-2:], [AGENT, text])
        for c in self.calls():    # every positional follows a `--`
            argv = c.split(" ")
            first_positional = 3 if c.startswith("agent inspect") else 1
            self.assertIn("--", argv[first_positional:], c)

    def idle_after_wait(self) -> None:
        """Make the fake agent report idle once `paseo wait` has returned, as the real one does."""
        real_run = relay.paseo_run

        def run_and_go_idle(*args: str, **kw: Any) -> tuple[int, str, str]:
            res = real_run(*args, **kw)
            if args[0] == "wait" and res[0] == 0:
                os.environ["FAKE_STATUS"] = "idle"
            return res

        relay.paseo_run = run_and_go_idle
        self.addCleanup(lambda: setattr(relay, "paseo_run", real_run))

    def test_wait_also_ends_options_before_the_id(self) -> None:
        os.environ.update(FAKE_PROVIDER="codex", FAKE_STATUS="running")
        self.idle_after_wait()
        rc, _out, err = self.main([sess(agent="codex")], SID, "ping", "--idle", "5", "--wait", "1")
        self.assertEqual(rc, 0, err)
        (call,) = [c for c in self.calls() if c.startswith("wait")]
        self.assertEqual(call, f"wait --timeout 5 --json -- {AGENT}")

    def test_sid_of_a_paseo_hosted_session_is_gated_then_sent_via_paseo(self) -> None:
        rc, _out, err = self.main([sess()], SID, "ping", "--wait", "1")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.calls(), [f"agent inspect --json -- {AGENT}",
                                        f"send --no-wait --behavior steer --json -- {AGENT} ping"])

    def test_name_and_agent_id_find_the_same_session(self) -> None:
        for ident in ("djbclark-ade-db", AGENT):
            self.log.unlink(missing_ok=True)
            rc, _out, err = self.main([sess()], ident, "ping", "--wait", "1")
            self.assertEqual(rc, 0, err)
            self.assertEqual(len(self.sends()), 1, ident)

    def test_delivered_once_the_claude_transcript_shows_the_text(self) -> None:
        tx = Path(self.tmp.name) / "tx.jsonl"
        _ = tx.write_text("{}\n")
        s = sess(transcript=str(tx))
        real_run = relay.paseo_run

        def run_and_record(*args: str, **kw: Any) -> tuple[int, str, str]:
            res = real_run(*args, **kw)
            if args[0] == "send":
                with tx.open("a") as fh:
                    _ = fh.write(json.dumps({"text": "ping from a peer"}) + "\n")
            return res

        relay.paseo_run = run_and_record
        try:
            rc, out, err = self.main([s], SID, "ping from a peer", "--wait", "3", "--json")
        finally:
            relay.paseo_run = real_run
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)["result"], "delivered")

    def test_delivered_check_matches_the_xml_escaped_form_inside_the_label(self) -> None:
        # the daemon escapes & < > " ' in the text: the transcript holds the escaped form
        tx = Path(self.tmp.name) / "tx.jsonl"
        _ = tx.write_text("{}\n")
        s = sess(transcript=str(tx))
        real_run = relay.paseo_run

        def run_and_record(*args: str, **kw: Any) -> tuple[int, str, str]:
            res = real_run(*args, **kw)
            if args[0] == "send":
                body = "<paseo-system>\nuse &lt;b&gt; &amp; &quot;q&quot; &apos;s&apos;\n</paseo-system>"
                with tx.open("a") as fh:
                    _ = fh.write(json.dumps({"text": body}) + "\n")
            return res

        relay.paseo_run = run_and_record
        try:
            rc, out, err = self.main([s], SID, "use <b> & \"q\" 's'", "--wait", "3", "--json")
        finally:
            relay.paseo_run = real_run
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)["result"], "delivered")

    HDR = "[relay from claude cccccccc aka the caller (djbclark-ade-relay-verified-wt)] "    # longer than any fixed-length probe prefix

    def send_and_probe(self, tx: Path, text: str, arrives: str | None) -> tuple[str | None, Any]:
        """send_paseo(TEXT) to a fake agent whose transcript TX gets the line ARRIVES while the send runs (None: nothing arrives)."""
        real_run = relay.paseo_run

        def run_and_record(*args: str, **kw: Any) -> tuple[int, str, str]:
            res = real_run(*args, **kw)
            if args[0] == "send" and arrives is not None:
                with tx.open("a") as fh:
                    _ = fh.write(json.dumps({"text": arrives}) + "\n")
            return res

        relay.paseo_run = run_and_record
        try:
            s = sess(transcript=str(tx))
            seen = relay.send_paseo(s, text, 1)
        finally:
            relay.paseo_run = real_run
        return seen, s.get("proof")

    def test_two_relays_sharing_one_sender_header_are_not_certified_by_one_transcript_line(self) -> None:
        # Codex P1, PR 74: the probe was the first 40 characters, which the expanded header alone fills, so a line of
        # message A certified message B (and an --ack watch) of the same sender to the same target
        tx = Path(self.tmp.name) / "tx.jsonl"
        _ = tx.write_text("{}\n")
        first, second = self.HDR + "first body", self.HDR + "second body"
        self.assertEqual(self.send_and_probe(tx, first, first)[0], "delivered")
        seen, proof = self.send_and_probe(tx, second, first)    # concurrent relays: only A's line reached the transcript during B's send
        self.assertEqual(seen, "accepted")
        self.assertIsNone(proof())    # the --ack watch is not fooled either
        with tx.open("a") as fh:
            _ = fh.write(json.dumps({"text": second}) + "\n")
        self.assertEqual(proof(), "delivered")    # and it still sees the message once it does arrive

    SPECIAL = "use <b> & \"q\" 's' tail"

    def esc(self, text: str) -> str:
        return "".join(relay.XML_ESCAPES.get(c, c) for c in text)

    def envelope(self, body: str) -> str:
        """The Paseo 0.13.0 text of a send that carries a source agent: its label around the XML-escaped body."""
        return '<paseo-system version="1" kind="agent-message" source-agent-id="a1" message-id="m2">\n' + body + "\n</paseo-system>"

    def test_a_paseo_agent_message_is_verified_whole_with_its_escapes_past_the_old_probe_length(self) -> None:
        # a source-bearing send (a Paseo-hosted sender) carries no relay header: Paseo wraps the XML-escaped text in its own label
        tx = Path(self.tmp.name) / "tx.jsonl"
        _ = tx.write_text("{}\n")
        text = "x" * 50 + " " + self.SPECIAL
        line = self.envelope(self.esc(text))
        self.assertEqual(self.send_and_probe(tx, text, line)[0], "delivered")
        self.assertEqual(self.send_and_probe(tx, text, line.replace("tail", "other"))[0], "accepted")    # same first 50 characters, another end

    def test_the_relay_prefix_route_is_verified_whole(self) -> None:
        # no source agent on this route: Paseo stores the text raw
        tx = Path(self.tmp.name) / "tx.jsonl"
        _ = tx.write_text("{}\n")
        self.assertEqual(self.send_and_probe(tx, self.HDR + "ping & more", self.HDR + "ping & more")[0], "delivered")

    def test_a_sourceless_send_is_stored_raw_and_delivered_with_every_special_character(self) -> None:
        tx = Path(self.tmp.name) / "tx.jsonl"
        _ = tx.write_text("{}\n")
        seen, proof = self.send_and_probe(tx, self.SPECIAL, self.SPECIAL)
        self.assertEqual(seen, "delivered")
        self.assertIsNone(proof)    # nothing left to wait for

    def test_a_source_bearing_send_is_stored_escaped_and_delivered(self) -> None:
        tx = Path(self.tmp.name) / "tx.jsonl"
        _ = tx.write_text("{}\n")
        self.assertEqual(self.send_and_probe(tx, self.SPECIAL, self.envelope(self.esc(self.SPECIAL)))[0], "delivered")

    def test_the_ack_proof_accepts_the_raw_and_the_escaped_whole_text(self) -> None:
        for stored in (self.SPECIAL, self.envelope(self.esc(self.SPECIAL))):
            tx = Path(self.tmp.name) / "tx.jsonl"
            _ = tx.write_text("{}\n")
            seen, proof = self.send_and_probe(tx, self.SPECIAL, None)    # nothing arrives during the send window
            self.assertEqual(seen, "accepted", stored)
            self.assertIsNone(proof(), stored)
            with tx.open("a") as fh:
                _ = fh.write(json.dumps({"text": stored}) + "\n")
            self.assertEqual(proof(), "delivered", stored)

    def test_a_text_present_in_neither_form_stays_accepted(self) -> None:
        tx = Path(self.tmp.name) / "tx.jsonl"
        _ = tx.write_text("{}\n")
        # the other message's escaped line, a half-escaped mix, and an unrelated line: none is the whole text in either form
        for line in (self.esc(self.SPECIAL.replace("tail", "other")), self.SPECIAL.replace("&", "&amp;"), "unrelated"):
            seen, proof = self.send_and_probe(tx, self.SPECIAL, line)
            self.assertEqual(seen, "accepted", line)
            self.assertIsNone(proof(), line)

    def test_unknown_terminal_for_a_pid_nobody_hosts_still_errors_and_names_paseo(self) -> None:
        s = sess(host="terminal", chan=None, paseo=None, where="unknown terminal")
        rc, _out, err = self.main([s], SID, "ping", "--wait", "1")
        self.assertEqual(rc, 1)
        self.assertIn("no terminal channel (unknown terminal)", err)
        self.assertIn("Paseo", err)
        self.assertIn("agent id", err)
        self.assertEqual(self.calls(), [])

    def test_uuid_paseo_does_not_know_is_no_match(self) -> None:
        rc, _out, err = self.main([], "99999999-0000-4000-8000-000000000009", "ping")
        self.assertEqual(rc, 1)
        self.assertIn("no session(s) match", err)
        self.assertFalse(self.sends())

    def test_closed_or_errored_paseo_agent_is_refused(self) -> None:
        os.environ["FAKE_STATUS"] = "closed"
        rc, _out, err = self.main([], AGENT, "ping")
        self.assertEqual(rc, 1)
        self.assertIn("closed", err)
        self.assertFalse(self.sends())

    def test_fleet_listed_but_closed_paseo_agent_is_refused(self) -> None:
        # a fleet-listed record never ran `inspect` before; the gate now does it for every Paseo target
        os.environ["FAKE_STATUS"] = "closed"
        rc, _out, err = self.main([sess()], SID, "ping")
        self.assertEqual(rc, 1)
        self.assertIn("closed", err)
        self.assertFalse(self.sends())

    def test_archived_paseo_agent_is_refused_listed_or_not(self) -> None:
        os.environ["FAKE_ARCHIVED"] = "true"
        for listed, ident in (([], AGENT), ([sess()], SID)):
            rc, _out, err = self.main(listed, ident, "ping")
            self.assertEqual(rc, 1)
            self.assertIn("archived", err)
        self.assertFalse(self.sends())

    def test_paseo_agent_with_a_pending_permission_is_refused_when_deferring_is_off(self) -> None:
        os.environ["FAKE_PENDING"] = '[{"id": "p1", "tool": "Bash"}]'
        for listed, ident in (([], AGENT), ([sess()], SID)):
            rc, _out, err = self.main(listed, ident, "ping", "--no-defer")
            self.assertEqual(rc, 1)
            self.assertIn("permission or question", err)
            self.assertIn("helm", err)
        self.assertFalse(self.sends())

    def test_paseo_agent_with_a_pending_permission_is_queued_not_typed_into_the_card(self) -> None:
        os.environ["FAKE_PENDING"] = '[{"id": "p1", "tool": "Bash"}]'
        rc, out, err = self.main([], AGENT, "ping")
        self.assertEqual((rc, out.startswith("queued: "), self.sends(), len(self.spawned)), (0, True, [], 1), err)
        self.assertIn("once its card is answered", out)

    def test_inspect_naming_another_agent_is_refused(self) -> None:
        os.environ["FAKE_ID"] = "eeeeeeee-0000-4000-8000-000000000005"
        rc, _out, err = self.main([sess()], SID, "ping")
        self.assertEqual(rc, 1)
        self.assertIn("does not confirm", err)
        self.assertFalse(self.sends())

    def test_state_is_checked_again_after_the_idle_wait(self) -> None:
        # the agent is archived (or asks a question) while we wait for it: the second inspect catches it
        os.environ.update(FAKE_PROVIDER="codex", FAKE_STATUS="running")
        real_run = relay.paseo_run

        def run_and_archive(*args: str, **kw: Any) -> tuple[int, str, str]:
            res = real_run(*args, **kw)
            if args[0] == "wait":
                os.environ["FAKE_ARCHIVED"] = "true"
            return res

        relay.paseo_run = run_and_archive
        try:
            rc, _out, err = self.main([sess(agent="codex")], SID, "ping", "--idle", "5")
        finally:
            relay.paseo_run = real_run
        self.assertEqual(rc, 1)
        self.assertIn("archived", err)
        self.assertFalse(self.sends())
        self.assertEqual([c.split(" ")[0] for c in self.calls()], ["agent", "wait", "agent"])

    def test_slash_text_is_refused_on_the_paseo_path(self) -> None:
        for listed, ident in (([], AGENT), ([sess()], SID)):
            rc, _out, err = self.main(listed, ident, "/clear")
            self.assertEqual(rc, 2)
            self.assertIn("built-ins", err)
        self.assertEqual(self.calls(), [f"agent inspect --json -- {AGENT}"])    # only the ident resolution

    def test_slash_text_hidden_behind_zero_width_or_full_width_characters_is_refused(self) -> None:
        for text in ("\ufeff/clear", " \u200b/clear", "\n/clear", "\uff0fclear"):
            rc, _out, err = self.main([sess()], SID, text)
            self.assertEqual(rc, 2, text)
            self.assertIn("built-ins", err)
        self.assertFalse(self.sends())

    def test_an_empty_or_junk_paseo_agent_id_does_not_identify_the_sender(self) -> None:
        # a junk id names nobody: the send is refused (exit 4, nothing sent) unless the caller declares a label
        for value in (" ", "", "not-a-uuid"):
            os.environ["PASEO_AGENT_ID"] = value
            os.environ.pop("RELAY_SENDER_NAME", None)
            sent = len(self.sends())
            rc, _out, err = self.main([sess()], SID, "ping", "--wait", "1")
            self.assertEqual(rc, 4, (value, err))
            self.assertEqual(len(self.sends()), sent, value)
            os.environ["RELAY_SENDER_NAME"] = "junk-id-test"
            rc, _out, err = self.main([sess()], SID, "ping", "--wait", "1")
            self.assertEqual(rc, 0, (value, err))
            self.assertTrue(all("[relay from " in s_ and "junk-id-test" in s_ for s_ in self.sends()), (value, self.sends()))

    def test_slash_text_is_not_refused_in_the_middle_of_a_message(self) -> None:
        rc, _out, err = self.main([sess()], SID, "see /tmp/x and /clear", "--wait", "1")
        self.assertEqual(rc, 0, err)

    def test_own_paseo_agent_is_refused(self) -> None:
        os.environ["PASEO_AGENT_ID"] = AGENT
        rc, _out, err = self.main([], AGENT, "ping")
        self.assertEqual(rc, 1)
        self.assertIn("this session", err)
        self.assertFalse(self.sends())

    def test_own_paseo_agent_is_refused_when_the_variable_was_scrubbed_from_the_env(self) -> None:
        # the caller's env lost PASEO_AGENT_ID, but an ancestor process is hosted by AGENT
        del os.environ["PASEO_AGENT_ID"]
        saved = (relay.where.env_of, relay.where.paseo_agent)
        relay.fleet.ancestors = lambda: {4242}
        relay.where.env_of = lambda pid: {"PASEO_AGENT_ID": AGENT}
        relay.where.paseo_agent = lambda pid, env: env.get("PASEO_AGENT_ID") if pid == 4242 else None
        try:
            rc, _out, err = self.main([], AGENT, "ping")
        finally:
            relay.where.env_of, relay.where.paseo_agent = saved
        self.assertEqual(rc, 1)
        self.assertIn("this session", err)
        self.assertFalse(self.sends())

    def test_process_cwd_that_differs_from_the_agents_cwd_is_not_trusted(self) -> None:
        s = sess(pid=4242)
        relay.where.real_cwd = lambda pid: "/somewhere/else"
        os.environ["FAKE_CWD"] = "/tmp/agent-dir"
        rc, _out, err = self.main([s], SID, "ping")
        self.assertEqual(rc, 1)
        self.assertIn("mapping not trusted", err)
        self.assertFalse(self.sends())

    # ---- the Paseo timeline as a second delivery witness, both ways (2026-10-29) --------------------------------------------------------

    def timeline(self, *lines: str) -> Path:
        path = Path(self.tmp.name) / "timeline"
        path.write_text("".join(line + "\n" for line in lines))
        os.environ["FAKE_TIMELINE"] = str(path)
        return path

    def codex(self) -> dict[str, Any]:
        os.environ.update(FAKE_PROVIDER="codex", FAKE_STATUS="idle")
        return sess(agent="codex", transcript=None, status="idle")

    def logs_calls(self) -> list[str]:
        return [c for c in self.raw_calls() if c.startswith("logs ")]

    def test_an_agent_with_no_transcript_is_proven_delivered_by_its_paseo_timeline(self) -> None:
        self.timeline(EMPTY_TIMELINE)
        rc, out, err = self.main([self.codex()], SID, "hello there friend", "--wait", "5", "--ack")
        self.assertEqual(rc, 0, err)
        self.assertIn(": delivered;", out)
        self.assertTrue(self.logs_calls())

    def test_a_caller_that_wants_no_proof_gets_the_instant_accepted_and_no_timeline_read(self) -> None:
        self.timeline(EMPTY_TIMELINE)    # RELAY_NO_ACK=1 in this class: no --ack, so no witness is needed
        rc, out, err = self.main([self.codex()], SID, "hello there friend", "--wait", "5")
        self.assertEqual(rc, 0, err)
        self.assertIn(": accepted;", out)
        self.assertEqual(self.logs_calls(), [])

    def test_a_timeline_that_cannot_be_read_leaves_the_send_accepted_not_proven(self) -> None:
        rc, out, err = self.main([self.codex()], SID, "hello there friend", "--wait", "1", "--ack")    # no FAKE_TIMELINE: `paseo logs` exits 1
        self.assertEqual(rc, 3, err)    # unverified: sent, no witness
        self.assertIn(": accepted;", out)

    def test_only_a_received_message_counts_not_the_agents_own_reasoning_or_output(self) -> None:
        self.timeline(EMPTY_TIMELINE)
        os.environ["FAKE_TL_KIND"] = "thought"    # the daemon takes the send, and the agent's timeline shows the text only inside its own reasoning
        rc, out, err = self.main([self.codex()], SID, "ack task42 please", "--wait", "2", "--ack")
        self.assertEqual(rc, 3, err)
        self.assertIn(": accepted;", out)

    def test_the_same_text_twice_is_two_deliveries_a_copy_already_there_proves_nothing(self) -> None:
        self.timeline(EMPTY_TIMELINE)
        row = self.codex()
        self.assertIn(": delivered;", self.main([row], SID, "hello there friend", "--wait", "5", "--ack")[1])
        os.environ["FAKE_TL_APPEND"] = "0"    # the daemon takes the second copy but the timeline never shows it
        rc, out, err = self.main([row], SID, "hello there friend", "--wait", "1", "--ack")
        self.assertEqual(rc, 3, err)
        self.assertIn(": accepted;", out)    # a copy is already there: a rolling window cannot tell a new one from a scrolled one, so no witness

    def test_a_text_too_short_to_be_a_witness_is_never_proven_by_the_timeline(self) -> None:
        self.timeline(EMPTY_TIMELINE)
        rc, out, err = self.main([self.codex()], SID, "ack x1", "--wait", "1", "--ack")    # the fake DID append it as a received message
        self.assertEqual((rc, ": accepted;" in out), (3, True), err)

    def test_the_timeline_shows_the_text_unescaped_where_the_transcript_keeps_it_xml_escaped(self) -> None:
        self.timeline(EMPTY_TIMELINE)
        rc, out, err = self.main([self.codex()], SID, 'a&b <c> "q" ]x[', "--wait", "5", "--ack")
        self.assertEqual((rc, ": delivered;" in out), (0, True), err)

    def test_a_long_text_is_matched_whole_so_two_long_texts_sharing_a_tail_never_certify_each_other(self) -> None:
        self.timeline(EMPTY_TIMELINE)
        tail = "tail [reply through relay.py to zz: ack T-long]"
        a, b = "alpha " * 80 + tail, "bravo " * 80 + tail
        self.assertEqual(relay.timeline_probe(a), " ".join(a.split()))
        rc, out, err = self.main([self.codex()], SID, a, "--wait", "5", "--ack")
        self.assertEqual((rc, ": delivered;" in out), (0, True), err)
        os.environ["FAKE_TL_APPEND"] = "0"    # b is sent but never shown; a, with the same last 160 characters, is
        rc, out, err = self.main([self.codex()], SID, b, "--wait", "2", "--ack")
        self.assertEqual((rc, ": accepted;" in out), (3, True), err)

    def test_a_message_from_a_sender_that_is_not_a_paseo_agent_shows_as_a_user_entry_and_counts(self) -> None:
        self.timeline(EMPTY_TIMELINE)
        os.environ["FAKE_TL_KIND"] = "user"    # `paseo send` with no source agent: the timeline shows `[User] <text>` (checked live, 2026-10-29)
        rc, out, err = self.main([self.codex()], SID, "hello there friend", "--wait", "5", "--ack")
        self.assertEqual((rc, ": delivered;" in out), (0, True), err)
        self.timeline("[User] [relay from claude peer-long-name (d)] ack tok12", "[Thought] x")
        self.assertEqual(relay.timeline_messages(AGENT), [("", "[relay from claude peer-long-name (d)] ack tok12")])
        self.assertEqual(self.sweep("tok12", "[User] [relay from claude peer-long-name (d)] ack tok12"), (1, "acked"))    # a non-Paseo peer's header names it
        self.assertEqual(self.sweep("tok13", "[User] ack tok13 from peer-long-name"), (0, "open"))    # no header, no title: nothing says who

    def expectation(self, token: str, **kw: Any) -> None:
        relay.atomic_json(relay.expect_dir() / f"{token}.json", {
            "id": token, "state": "open", "created": time.time(), "acked": None, "within": 1800, "sender": "cccccccc", "sender_sid": "",
            "sender_label": "me", "tx": None, "sender_paseo": CALLER, "mark": 0, "tl_base": {},    # a readable, empty timeline when the question was asked
            "target": {"id": "dddddddd", "name": "peer-long-name", "paseo": AGENT, "sid8": "", "sid": "", "host": "paseo"}, **kw})

    def sweep(self, token: str, *timeline: str, **kw: Any) -> tuple[int, str]:
        """Open expectation TOKEN (fields KW), show TIMELINE to its transcript-less sender, sweep: (acked count, resulting state)."""
        with mock.patch.object(relay.fleet, "LINKS_FILE", Path(self.tmp.name) / "links.json"):
            self.expectation(token, **kw)
            self.timeline(*timeline)
            acked, _ = relay.ack_sweep()
        return acked, relay.expect_read(token)["state"]

    def test_a_sender_with_no_transcript_gets_its_ack_from_its_own_paseo_timeline(self) -> None:
        self.assertEqual(self.sweep("tok1", "[Message received] peer-long-name", "ack tok1"), (1, "acked"))
        self.assertEqual(relay.expect_read("tok1").get("acked_via"), "timeline")

    def test_an_ack_in_a_timeline_from_someone_else_closes_nothing(self) -> None:
        self.assertEqual(self.sweep("tok2", "[Message received] stranger-agent", "ack tok2"), (0, "open"))

    def test_the_sender_is_the_entrys_own_title_not_a_name_quoted_in_the_body_or_a_longer_title(self) -> None:
        self.assertEqual(self.sweep("tok4", "[Message received] unrelated-agent", "Forwarding peer-long-name says ack tok4"), (0, "open"))
        self.assertEqual(self.sweep("tok7", "[Message received] peer-long-name-impostor", "ack tok7"), (0, "open"))
        self.assertEqual(self.sweep("tok6", "[Message received] stranger", "x [relay from claude peer-long-name (d)] ack tok6"), (0, "open"))    # a header not at the start is a quote
        self.assertEqual(self.sweep("tok5", "[Message received] anything", "[relay from claude peer-long-name (d)] ack tok5"), (1, "acked"))    # a non-Paseo peer's own header names it

    def test_an_ack_that_was_already_in_the_timeline_before_the_question_cannot_answer_it(self) -> None:
        old = {relay.timeline_key("peer-long-name", "ack tok3"): 1}
        self.assertEqual(self.sweep("tok3", "[Message received] peer-long-name", "ack tok3", tl_base=old), (0, "open"))    # a reused ID: the old reply
        self.assertEqual(self.sweep("tok10", "[Message received] peer-long-name", "ack tok10", "[Message received] peer-long-name", "ack tok10",
                                    tl_base={relay.timeline_key("peer-long-name", "ack tok10"): 1}), (1, "acked"))    # an identical repeat AFTER the question: a second copy
        self.assertEqual(self.sweep("tok8", "[Message received] peer-long-name", "ack tok8 done",
                                    tl_base={relay.timeline_key("peer-long-name", "ack tok8"): 1}), (1, "acked"))    # a new one differs
        self.assertEqual(self.sweep("tok11", "[Message received] peer-long-name", "ack tok11", tl_base=None), (0, "open"))    # no baseline (unreadable): the timeline closes nothing

    def test_a_hand_edited_sender_paseo_is_skipped_never_an_exception(self) -> None:
        self.assertEqual(self.sweep("tok9", "[Message received] peer-long-name", "ack tok9", sender_paseo=["x"]), (0, "open"))

    def test_a_transcript_less_senders_baseline_is_what_it_had_received_before_it_asked(self) -> None:
        self.timeline("[Message received] peer-long-name", "ack old1", "[Shell] ls")
        self.assertEqual(relay.timeline_base({"id": "cccccccc", "paseo": CALLER, "transcript": None}), {relay.timeline_key("peer-long-name", "ack old1"): 1})
        self.timeline(EMPTY_TIMELINE)
        self.assertEqual(relay.timeline_base({"id": "cccccccc", "paseo": CALLER, "transcript": None}), {})    # readable and empty: a baseline that closes the next ack
        os.environ.pop("FAKE_TIMELINE")
        self.assertIsNone(relay.timeline_base({"id": "cccccccc", "paseo": CALLER, "transcript": None}))    # unreadable: no baseline
        self.assertIsNone(relay.timeline_base({"id": "cccccccc", "paseo": CALLER, "transcript": "/x.jsonl"}))    # a transcript has its own mark
        self.assertIsNone(relay.timeline_base({"id": "cccccccc", "paseo": "", "transcript": None}))

    def test_a_first_contact_link_is_acked_from_the_senders_timeline_too(self) -> None:
        links = Path(self.tmp.name) / "links.json"
        now = time.time()
        key = relay.fleet.link_key("cccccccc", "dddddddd")
        relay.atomic_json(links, {"links": {key: {"sender": "cccccccc", "target": "dddddddd", "first_sent": now, "last_sent": now, "sent": 1, "acked": None,
                                                  "tx": "", "mark": 0, "who": ["peer-long-name"], "sender_paseo": CALLER, "tl_base": {}}}})
        self.timeline("[Message received] peer-long-name", "ack cccccccc")
        with mock.patch.object(relay.fleet, "LINKS_FILE", links):
            acked, _ = relay.ack_sweep()
            ln = relay.fleet.links_read()["links"][key]
        self.assertEqual(acked, 1)
        self.assertTrue(ln["acked"])

    # ---- why a message cannot be delivered yet: two methods compared (2026-10-29) --------------------------------------------------------

    QUESTION = '[{"id": "p1", "tool": "AskUserQuestion"}]'
    PERMIT_Q = json.dumps([{"id": "p1", "agentId": AGENT, "name": "AskUserQuestion", "description": "Which branch should I use?"}])

    def test_a_card_is_named_by_its_kind_a_question_is_not_a_permission(self) -> None:
        self.assertIn("a QUESTION (AskUserQuestion)", relay.paseo_blocker({"Status": "idle", "PendingPermissions": [{"id": "p1", "tool": "AskUserQuestion"}]}) or "")
        self.assertIn("a PERMISSION (Bash)", relay.paseo_blocker({"Status": "idle", "PendingPermissions": [{"id": "p2", "tool": "Bash"}]}) or "")
        self.assertIn("a PLAN (ExitPlanMode)", relay.paseo_blocker({"Status": "idle", "PendingPermissions": [{"id": "p3", "tool": "ExitPlanMode"}]}) or "")
        why = relay.paseo_blocker({"Status": "idle", "PendingPermissions": [{"id": "p1", "tool": "Bash"}, {"id": "p2", "tool": "Edit"}] * 3}) or ""
        self.assertIn("and 3 more", why)
        self.assertTrue(relay.card_why(why))    # every card reason keeps the prefix split_card and the deliverer key on
        self.assertEqual(relay.card_kind("OMP ask"), "question")    # omp's picklist tool, as `paseo permit ls` showed it live (2026-10-29)
        self.assertEqual(relay.card_kind("Bash"), "permission")

    def test_a_dash_description_is_no_text_and_the_tool_name_stands_in_and_the_text_is_sanitized(self) -> None:
        os.environ["FAKE_PERMITS"] = json.dumps([{"id": "p1", "agentId": AGENT, "name": "OMP ask", "description": "-"}])
        self.assertEqual(relay.paseo_card_detail(AGENT), ("OMP ask", True))
        os.environ["FAKE_PERMITS"] = json.dumps([{"id": "p1", "agentId": AGENT, "name": "Bash", "description": "rm \x1b[31m-rf\x1b[0m /tmp/x\x07\x00 now"}])
        self.assertEqual(relay.paseo_card_detail(AGENT), ("rm -rf /tmp/x now", True))    # no escape sequence reaches an operator's terminal
        self.assertEqual(relay.clean_text("a\x1b]0;title\x07b\x9bc"), "a b c")

    def test_diagnose_reads_the_api_the_card_text_and_the_timeline_and_they_agree(self) -> None:
        os.environ.update(FAKE_PENDING=self.QUESTION, FAKE_PERMITS=self.PERMIT_Q)
        self.timeline("[Shell] ls", "I need to know which branch you want.")
        d = relay.diagnose(sess())
        self.assertEqual((d["state"], d["deliverable"], d["agree"]), ("card:question", False, True))
        self.assertIn("Which branch should I use?", d["why"])
        self.assertEqual([e["src"] for e in d["evidence"]], ["paseo-inspect", "paseo-logs", "paseo-permit-ls"])
        self.assertEqual(d["evidence"][1]["line"], "I need to know which branch you want.")

    def test_diagnose_reports_when_inspect_and_the_card_list_disagree(self) -> None:
        os.environ.update(FAKE_PENDING=self.QUESTION, FAKE_PERMITS="[]")    # inspect says a card, `permit ls` has none: just answered, or stale
        d = relay.diagnose(sess())
        self.assertEqual((d["state"], d["agree"]), ("card:question", False))
        self.assertIn("`paseo permit ls` does not", d["why"])

    def test_a_card_only_permit_ls_lists_is_a_disagreement_and_blocks(self) -> None:
        os.environ.update(FAKE_PENDING="[]", FAKE_PERMITS=self.PERMIT_Q)    # `inspect` has no card, `permit ls` has one: blocked, and the methods disagree
        d = relay.diagnose(sess())
        self.assertEqual((d["state"], d["deliverable"], d["agree"]), ("card:unknown", False, False))
        self.assertIn("`paseo agent inspect` does not", d["why"])

    # ---- Herald's attention file as the third witness (issue 135, 2026-10-30): synthetic entries only, never a live headline ----

    HEAD = "SYNTHETIC-HEADLINE which branch"

    def herald(self, *entries: Any, raw: str | None = None) -> None:
        self.herald_file.parent.mkdir(parents=True, exist_ok=True)
        self.herald_file.write_text(raw if raw is not None else json.dumps(list(entries)))

    def entry(self, reason: str, agent: str = AGENT, **kw: Any) -> dict[str, Any]:
        return {"agentId": agent, "reason": reason, "eventId": "ev-1", "requestId": "rq-1" if reason in ("question", "plan", "permission") else None,
                "createdAt": "2026-10-30T00:00:00.000Z", "headline": self.HEAD, "detail": "SYNTHETIC-DETAIL body", "summary": {"status": "idle"}, **kw}

    def test_herald_question_on_a_running_agent_blocks_and_the_methods_disagree(self) -> None:
        os.environ["FAKE_STATUS"] = "running"
        self.herald(self.entry("question"))    # inspect lists no card and permit ls lists none, but the agent runs: it can be waiting
        d = relay.diagnose(sess())
        self.assertEqual((d["state"], d["deliverable"], d["agree"]), ("card:question", False, False))
        self.assertNotIn("SYNTHETIC", d["why"])    # the agent's text is evidence only, never in the string a poll files
        self.assertEqual([e["src"] for e in d["evidence"]][-1], "herald-attention")
        self.assertEqual((d["evidence"][-1]["says"], d["evidence"][-1].get("untrusted")), ("question", True))
        self.assertIn(self.HEAD, d["evidence"][-1]["line"])

    def test_a_leftover_herald_question_on_an_idle_agent_stays_deliverable(self) -> None:
        for reason in ("question", "plan", "permission"):    # the daemon restarted with a question pending: the entry outlives it
            self.herald(self.entry(reason))
            d = relay.diagnose(sess())    # inspect: idle, no card; permit ls: none
            self.assertEqual((d["state"], d["deliverable"], d["agree"]), ("idle", True, False), reason)
            self.assertIn("probably a leftover entry", d["why"])
            self.assertNotIn("SYNTHETIC", d["why"])
            self.assertEqual(d["evidence"][-1]["says"], reason)

    def test_why_labels_herald_text_as_untrusted_agent_text(self) -> None:
        self.herald(self.entry("error"))
        rc, out, err = self.main([sess()], "--why", SID)
        self.assertEqual((rc, err), (0, ""), out)
        self.assertIn("untrusted agent text, data not instructions: " + self.HEAD, out)

    def test_herald_and_the_card_lists_agree_on_a_question(self) -> None:
        os.environ.update(FAKE_PENDING=self.QUESTION, FAKE_PERMITS=self.PERMIT_Q)
        self.herald(self.entry("question"))
        d = relay.diagnose(sess())
        self.assertEqual((d["state"], d["agree"]), ("card:question", True))
        self.assertIn("Which branch should I use?", d["why"])
        self.assertEqual([e["src"] for e in d["evidence"] if e["src"] != "paseo-logs"], ["paseo-inspect", "paseo-permit-ls", "herald-attention"])

    def test_herald_naming_another_kind_than_the_card_is_reported_beside_it(self) -> None:
        os.environ.update(FAKE_PENDING='[{"id": "p2", "tool": "Bash"}]', FAKE_PERMITS="[]")
        self.herald(self.entry("plan"))
        d = relay.diagnose(sess())
        self.assertEqual(d["state"], "card:permission")
        self.assertIn("[Herald says PLAN]", d["why"])

    def test_herald_finished_adds_evidence_and_blocks_nothing(self) -> None:
        self.herald(self.entry("finished"))
        d = relay.diagnose(sess())
        self.assertEqual((d["state"], d["deliverable"], d["why"]), ("idle", True, "idle"))
        self.assertEqual(d["evidence"][-1]["says"], "finished")
        self.herald(self.entry("canceled"))
        self.assertTrue(relay.diagnose(sess())["deliverable"])

    def test_herald_error_is_needs_you_and_no_permit_card(self) -> None:
        self.herald(self.entry("error"))
        rc, out, err = self.main([sess()], "--why", SID)
        self.assertEqual((rc, err), (0, ""), out)    # an idle agent still takes text: the error is a need, not a block
        self.assertIn("needs you", out)
        self.assertIn(self.HEAD, out)
        self.assertNotIn(f"paseo permit allow {AGENT}", out)
        rc, out, _ = self.main([sess()], "--why", SID, "--json")
        d = json.loads(out)
        self.assertEqual((d["state"], d["needs_you"], d["deliverable"]), ("idle", "error", True))
        self.assertEqual(d["evidence"][-1]["src"], "herald-attention")

    def test_a_stale_herald_error_on_a_running_agent_is_evidence_only(self) -> None:
        os.environ["FAKE_STATUS"] = "running"
        self.herald(self.entry("error"))
        d = relay.diagnose(sess())
        self.assertEqual(d["state"], "working")
        self.assertNotIn("needs_you", d)
        self.assertNotIn("needs you", d["why"])

    def test_a_missing_unreadable_or_non_array_herald_file_changes_nothing(self) -> None:
        base = relay.diagnose(sess())
        self.assertNotIn("herald-attention", [e["src"] for e in base["evidence"]])
        for raw in ("not json", '{"agentId": "x"}', '"question"', "", "null"):
            self.herald(raw=raw)
            self.assertEqual(relay.diagnose(sess()), base, raw)
        self.herald_file.unlink()
        self.herald_file.mkdir()    # a directory where the file should be: unreadable
        self.assertEqual(relay.diagnose(sess()), base)

    def test_one_bad_herald_entry_does_not_drop_the_good_one(self) -> None:
        os.environ["FAKE_STATUS"] = "running"
        self.herald("junk", 7, None, {"agentId": 5, "reason": "question"}, {"agentId": AGENT, "reason": "bogus"}, self.entry("question"))
        self.assertEqual(relay.diagnose(sess())["state"], "card:question")

    def test_herald_text_is_shown_by_why_but_never_filed_by_a_poll(self) -> None:
        os.environ["FAKE_PENDING"] = self.QUESTION
        self.herald(self.entry("question", headline=self.HEAD + " \x1b[31mred\x07"))
        shown = relay.diagnose(sess())
        self.assertIn(self.HEAD + " red", shown["evidence"][-1]["line"])    # no escape sequence reaches the terminal
        self.assertNotIn("SYNTHETIC", shown["why"])
        self.assertNotIn("\x1b", json.dumps(shown))
        relay.target_poll({"target": {"paseo": AGENT}})
        filed = json.dumps(relay.target_poll.look)    # the look a deliverer files on a record and in deferred.log
        self.assertNotIn("SYNTHETIC", filed)

    def test_why_reports_a_hard_stop_as_refused_though_the_agent_is_idle(self) -> None:
        me = sess(self=True)
        rc, out, err = self.main([me], "--why", SID)
        self.assertEqual(rc, 1, err)
        self.assertIn(": refused", out)

    def test_a_malformed_sender_token_never_aborts_a_sweep(self) -> None:
        msgs = [("peer-long-name", "ack tok1")]
        for bad in ({"x": 1}, ["a"], None, ""):
            self.assertFalse(relay.timeline_ack(msgs, bad, ["peer-long-name"], {}))

    def test_a_running_agent_that_shows_nothing_new_for_a_long_time_is_silent_not_just_working(self) -> None:
        stamp = lambda secs: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - secs))
        os.environ["FAKE_STATUS"] = "running"
        os.environ["FAKE_UPDATED"] = stamp(40 * 60)
        d = relay.diagnose(sess())
        self.assertEqual((d["state"], d["deliverable"]), ("silent", False))
        self.assertIn("40 min", d["why"])
        os.environ["FAKE_UPDATED"] = stamp(30)
        self.assertEqual(relay.diagnose(sess())["state"], "working")

    def test_an_idle_agent_is_deliverable_an_unknown_one_is_gone_and_a_daemon_that_cannot_answer_is_an_error(self) -> None:
        self.assertEqual((relay.diagnose(sess())["state"], relay.diagnose(sess())["deliverable"]), ("idle", True))
        with mock.patch.object(relay, "paseo_probe", lambda agent: (None, "notfound")):
            d = relay.diagnose(sess())
        self.assertEqual((d["state"], d["deliverable"]), ("gone", False))
        os.environ["FAKE_KNOWN"] = "someone-else"    # the fake exits 1 with no AGENT_NOT_FOUND code: a daemon that cannot answer
        d = relay.diagnose(sess())
        self.assertEqual((d["state"], d["deliverable"]), ("error", False))

    def test_the_screen_classifier_names_a_picker_a_permission_a_slash_menu_and_a_running_turn(self) -> None:
        picker = "  Choose a model\n  1. sonnet\n  2. opus\n                ↑/↓ navigate, Enter to select, Ctrl+C to exit"
        self.assertEqual(relay.classify_screen(picker)[0], "picker")
        self.assertEqual(relay.classify_screen("  1. sonnet\n  2. opus\n  Esc to cancel")[0], "picker")
        self.assertEqual(relay.classify_screen("Bash command\n  rm -rf x\nDo you want to proceed?\n❯ 1. Yes\n  2. No")[0], "permission")
        self.assertEqual(relay.classify_screen("Run it? [y/N]")[0], "permission")
        self.assertEqual(relay.classify_screen("│ Do you want to proceed?        │\n│ ❯ 1. Yes                       │\n│   2. No                        │")[0], "permission")    # a boxed dialog
        self.assertEqual(relay.clean_text("a\u202eb\u200bc\ufeffd"), "a b c d")    # bidi override, zero-width and BOM characters
        self.assertEqual(relay.classify_screen("  /help     show help\n  /clear    clear the screen\n  /model    switch model\n")[0], "slash_menu")
        self.assertEqual(relay.classify_screen("✻ Thinking… (12s · esc to interrupt)")[0], "busy")
        self.assertEqual(relay.classify_screen("❯ \n  ? for shortcuts")[0], "unknown")
        for prose in ("you can select a model with /model later, and enter works",
                      "I will select the one and press enter to proceed; to select one then esc",    # reviewer's false positives (PR 124)
                      "allow this request ok",
                      "Do you want to proceed with X?",    # a question in the agent's own prose, no dialog options under it
                      "  /a  one\n  /b  two\n  /c  three\nthen the agent kept typing a long reply here\nand more\nand more\nand more\nand more\nand more"):
            self.assertEqual(relay.classify_screen(prose)[0], "unknown", prose)
        self.assertEqual(relay.classify_screen("Do you want to proceed?\n❯ 1. Yes\n  2. No\n" + "agent output line\n" * 12)[0], "unknown")    # a dialog is at the bottom, not history
        self.assertEqual(relay.classify_screen("x" * 50000 + "\n" + "  /a  b\n" * 4000)[0], "slash_menu")    # hostile text is read in linear time (the test would hang otherwise)

    def test_a_pane_whose_status_says_idle_over_a_picker_is_blocked_and_the_disagreement_is_reported(self) -> None:
        picker = "  1. sonnet\n  2. opus\n  ↑/↓ navigate, Enter to select, Esc to cancel"
        pane = {"id": "w2N:pZ", "status": "idle", "chan": ("herdr", "w2N:pZ")}
        with mock.patch.object(relay, "screen", lambda chan, lines=20: picker):
            d = relay.pane_look(pane)
            self.assertEqual((d["state"], d["deliverable"], d["agree"]), ("card:picker", False, False))
            self.assertIn("the status says idle but the screen shows a picker", d["why"])
            self.assertTrue(relay.card_why(d["why"]))
            self.assertNotIn("sonnet", d["why"])    # the screen row can hold a command or a token: evidence for `--why` only
            self.assertEqual([e for e in d["evidence"] if e["src"] == "screen"][0]["line"], "1. sonnet")
            self.assertEqual(relay.pane_look({**pane, "status": "blocked"})["agree"], True)
        with mock.patch.object(relay, "screen", lambda chan, lines=20: "❯ \n  ? for shortcuts"):
            self.assertEqual(relay.pane_look(pane)["state"], "idle")
            d = relay.pane_look({**pane, "status": "blocked"})    # blocked status, nothing on screen: still a card, and the disagreement says so
            self.assertEqual((d["state"], d["agree"]), ("card:unknown", False))
        with mock.patch.object(relay, "screen", lambda chan, lines=20: "✻ Thinking… (esc to interrupt)"):
            d = relay.pane_look(pane)
            self.assertEqual((d["state"], d["agree"]), ("working", False))

    def test_why_prints_the_state_the_reason_and_the_evidence_and_exits_1_while_something_is_in_the_way(self) -> None:
        os.environ.update(FAKE_PENDING=self.QUESTION, FAKE_PERMITS=self.PERMIT_Q)
        self.timeline("[Shell] ls")
        rc, out, err = self.main([sess()], "--why", SID)
        self.assertEqual(rc, 1, err)
        self.assertIn("card:question", out)
        self.assertIn("Which branch should I use?", out)
        self.assertIn("paseo-permit-ls", out)
        rc, out, _ = self.main([sess()], "--why", SID, "--json")
        self.assertEqual((rc, json.loads(out)["state"]), (1, "card:question"))
        os.environ.pop("FAKE_PENDING")
        os.environ.pop("FAKE_PERMITS")
        self.assertEqual(self.main([sess()], "--why", SID)[0], 0)    # idle: it can take a text now
        self.assertEqual(self.main([sess()], "--why")[0], 2)
        self.assertEqual(self.main([sess()], "--why", SID, "some text")[0], 2)

    def test_a_pending_card_does_not_hide_an_untrusted_process_mapping(self) -> None:
        """Codex, PR 112: the card reason came back before the directory check, so a mismatched mapping would have been queued (the
        record keeps only the Paseo id, never the process that was mapped to it)."""
        s = sess(pid=4242)
        relay.where.real_cwd = lambda pid: "/somewhere/else"
        os.environ.update(FAKE_CWD="/tmp/agent-dir", FAKE_PENDING='[{"id": "p1", "tool": "Bash"}]')
        rc, out, err = self.main([s], SID, "ping")
        self.assertEqual((rc, out, self.sends(), len(self.spawned)), (1, "", [], 0))
        self.assertIn("mapping not trusted", err)

    def test_process_cwd_that_matches_the_agents_cwd_is_sent(self) -> None:
        s = sess(pid=4242)
        relay.where.real_cwd = lambda pid: "/tmp/agent-dir"
        os.environ["FAKE_CWD"] = "/tmp/agent-dir"
        rc, _out, err = self.main([s], SID, "ping", "--wait", "1")
        self.assertEqual(rc, 0, err)

    def test_working_non_steering_agent_is_queued_with_exit_0_and_nothing_is_sent(self) -> None:
        os.environ.update(FAKE_PROVIDER="cline", FAKE_STATUS="running")
        rc, out, err = self.main([], AGENT, "ping")
        self.assertEqual((rc, out.startswith("queued: "), self.sends(), len(self.spawned)), (0, True, [], 1), err)
        self.assertEqual([p.name for p in relay.DEFER_DIR.glob("*.json")], [f"{self.spawned[0]}.json"])    # in the test's own queue

    def test_working_non_steering_agent_needs_idle_and_then_waits_first(self) -> None:
        os.environ.update(FAKE_PROVIDER="cline", FAKE_STATUS="running")
        rc, _out, err = self.main([], AGENT, "ping", "--no-defer")
        self.assertEqual(rc, 1)
        self.assertIn("cannot steer", err)
        self.assertFalse(self.sends())
        self.log.unlink(missing_ok=True)
        self.idle_after_wait()
        rc, _out, err = self.main([], AGENT, "ping", "--idle", "5", "--wait", "1")
        self.assertEqual(rc, 0, err)
        self.assertEqual([c.split(" ")[0] for c in self.calls()], ["agent", "agent", "wait", "agent", "send"])
        self.assertIn(f"wait --timeout 5 --json -- {AGENT}", self.calls())

    def test_idle_timeout_sends_nothing(self) -> None:
        os.environ.update(FAKE_PROVIDER="cline", FAKE_STATUS="running", FAKE_WAIT_RC="124")
        rc, _out, err = self.main([], AGENT, "ping", "--idle", "5")
        self.assertEqual(rc, 1)
        self.assertIn("still running", err)
        self.assertFalse(self.sends())

    def test_idle_must_be_finite_and_positive(self) -> None:
        for bad in ("nan", "inf", "-inf", "0", "-3"):
            rc, _out, err = self.main([], AGENT, "ping", f"--idle={bad}")
            self.assertEqual(rc, 2, bad)
            self.assertIn("--idle", err)
        self.assertEqual(self.calls(), [])

    def test_missing_paseo_cli_is_reported(self) -> None:
        os.environ["PASEO_CLI"] = "/nonexistent/paseo"
        rc, _out, err = self.main([sess()], SID, "ping")
        self.assertEqual(rc, 1)
        self.assertIn("does not confirm", err)

    def test_paseo_cli_that_is_not_executable_is_refused(self) -> None:
        plain = Path(self.tmp.name) / "plain"
        _ = plain.write_text("#!/bin/sh\n")
        os.environ["PASEO_CLI"] = str(plain)
        rc, _out, err = relay.paseo_run("ls")
        self.assertEqual(rc, 127)
        self.assertIn("not executable", err)

    def test_paseo_run_closes_stdin(self) -> None:
        reader = Path(self.tmp.name) / "reader"
        _ = reader.write_text("#!/bin/bash\nread -t 5 line; echo \"rc=$? line=[$line]\"\n")
        reader.chmod(0o755)
        os.environ["PASEO_CLI"] = str(reader)
        rc, out, _err = relay.paseo_run("x")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "rc=1 line=[]")    # EOF at once: no prompt on an inherited terminal


class WherePaseo(unittest.TestCase):
    def fake_run(self, parent_cmd: str):
        def run(*cmd: str) -> str:
            if cmd[:3] == ("ps", "-o", "ppid="):
                return "4242\n"
            if cmd[:3] == ("ps", "-o", "command="):
                return parent_cmd + "\n"
            if cmd[:2] == ("ps", "-p"):
                return "1\n"
            return ""
        return run

    def test_daemon_parent_and_uuid_env_is_a_paseo_agent(self) -> None:
        saved = where.run
        where.run = self.fake_run("Paseo Daemon")
        try:
            self.assertEqual(where.paseo_agent(10, {"PASEO_AGENT_ID": AGENT}), AGENT)
            self.assertIsNone(where.paseo_agent(10, {"PASEO_AGENT_ID": "not-a-uuid"}))
            self.assertIsNone(where.paseo_agent(10, {}))
        finally:
            where.run = saved

    def test_a_claude_started_from_an_agents_shell_is_not_the_agent(self) -> None:
        # inherits PASEO_AGENT_ID but its parent is the outer claude / a shell, not the daemon
        saved = where.run
        where.run = self.fake_run("/Users/x/.local/bin/claude --output-format stream-json")
        try:
            self.assertIsNone(where.paseo_agent(10, {"PASEO_AGENT_ID": AGENT}))
        finally:
            where.run = saved

    def test_only_the_exact_daemon_title_is_the_parent(self) -> None:
        saved = where.run
        try:
            for title in ("Paseo Supervisor", "Paseo Voice", "Paseo Daemon extra", "PaseoX"):
                where.run = self.fake_run(title)
                self.assertIsNone(where.paseo_agent(10, {"PASEO_AGENT_ID": AGENT}), title)
            where.run = self.fake_run("Paseo Daemon  ")
            self.assertEqual(where.paseo_agent(10, {"PASEO_AGENT_ID": AGENT}), AGENT)
        finally:
            where.run = saved

    def test_paseo_agent_id_is_read_only_from_the_env_part_of_ps_eww(self) -> None:
        other = "cccccccc-0000-4000-8000-000000000003"
        argv = f"/bin/claude --note PASEO_AGENT_ID={other}"
        eww = f"{argv} HERDR_ENV=1 PASEO_AGENT_ID={AGENT} X=a PASEO_AGENT_ID={other}"

        def run(*cmd: str) -> str:
            return eww if cmd[:2] == ("ps", "eww") else argv if cmd[:2] == ("ps", "-ww") else ""

        saved = where.run
        where.run = run
        try:
            env = where.env_of(999999999)    # no /proc entry: the ps path
        finally:
            where.run = saved
        self.assertEqual(env["PASEO_AGENT_ID"], AGENT)
        self.assertEqual(env["HERDR_ENV"], "1")

    def ps_env(self, argv: str, eww: str) -> dict[str, str]:
        def run(*cmd: str) -> str:
            return eww if cmd[:2] == ("ps", "eww") else argv if cmd[:2] == ("ps", "-ww") else ""
        saved = where.run
        where.run = run
        try:
            return where.env_of(999999999)    # no /proc entry: the ps path
        finally:
            where.run = saved

    def test_every_key_is_read_only_from_the_env_part_of_ps_eww(self) -> None:
        """Adversary r1 A5 (2026-10-25): a prompt in argv that quotes HERDR_PANE_ID=w5:p3 names no pane of that process."""
        argv = "/bin/codex exec HERDR_PANE_ID=w5:p3 TMUX=/tmp/fake,1,0"
        self.assertEqual(self.ps_env(argv, f"{argv} PATH=/bin"), {})
        self.assertEqual(self.ps_env(argv, f"{argv} HERDR_PANE_ID=w1:p1 HERDR_PANE_ID=w9:p9"), {"HERDR_PANE_ID": "w1:p1"})

    def test_no_key_is_read_when_the_argv_cannot_be_separated(self) -> None:
        self.assertEqual(self.ps_env("totally different", "/bin/x HERDR_PANE_ID=w5:p3 HERDR_ENV=1"), {})

    def test_paseo_agent_id_is_dropped_when_the_argv_cannot_be_separated(self) -> None:
        def run(*cmd: str) -> str:
            return "totally different" if cmd[:2] == ("ps", "-ww") else f"/bin/x HERDR_ENV=1 PASEO_AGENT_ID={AGENT}"

        saved = where.run
        where.run = run
        try:
            env = where.env_of(999999999)
        finally:
            where.run = saved
        self.assertNotIn("PASEO_AGENT_ID", env)

    def test_linux_reads_proc_environ(self) -> None:
        class Fake:
            def __init__(self, _path: str) -> None:
                pass

            def read_bytes(self) -> bytes:
                return f"A=1\0PASEO_AGENT_ID={AGENT}\0PASEO_AGENT_ID=zzz\0HERDR_ENV=1".encode()

        saved = where.Path
        where.Path = Fake    # pyright: ignore[reportAttributeAccessIssue]
        try:
            env = where.env_of(10)
        finally:
            where.Path = saved
        self.assertEqual(env, {"PASEO_AGENT_ID": AGENT, "HERDR_ENV": "1"})

    def test_where_line_and_json_carry_the_agent(self) -> None:
        saved = (where.run, where.env_of, where.cwd_of)
        where.run = self.fake_run("Paseo Daemon")
        where.env_of = lambda pid: {"PASEO_AGENT_ID": AGENT, "HERDR_ENV": "1", "HERDR_PANE_ID": "w1:p1"}
        where.cwd_of = lambda pid: "~/src/x"
        try:
            w = where.where(10)
        finally:
            where.run, where.env_of, where.cwd_of = saved
        assert w
        self.assertEqual(w["where"], f"host=paseo agent={AGENT}")
        self.assertEqual(w["paseo_agent"], AGENT)

    def test_other_hosts_have_no_paseo_key(self) -> None:
        saved = (where.run, where.env_of, where.cwd_of)
        where.run = self.fake_run("zsh")
        where.env_of = lambda pid: {"TMUX": "x", "TMUX_PANE": "%1"}
        where.cwd_of = lambda pid: ""
        try:
            w = where.where(10)
        finally:
            where.run, where.env_of, where.cwd_of = saved
        assert w
        self.assertNotIn("paseo_agent", w)

    def lookup_with_row(self, row: dict[str, Any]) -> tuple[dict[str, Any] | None, int, dict[str, Any]]:
        """lookup(10, 'S') against a history DB holding ROW; (result, where() calls, the row stored afterwards)."""
        calls: list[int] = []
        with tempfile.TemporaryDirectory() as t:
            db = Path(t) / "h.sqlite"
            con = sqlite3.connect(db)
            _ = con.execute("CREATE TABLE locations(pid INTEGER PRIMARY KEY, proc_start TEXT, ts REAL, data TEXT)")
            _ = con.execute("INSERT INTO locations VALUES (10, 'S', ?, ?)", (time.time(), json.dumps(row)))
            con.commit()
            con.close()
            saved = (where.DB, where.where)
            where.DB = db
            where.where = lambda pid: (calls.append(pid), {"pid": pid, "where": f"host=paseo agent={AGENT}", "paseo_agent": AGENT})[1]
            try:
                w = where.lookup(10, "S")
            finally:
                where.DB, where.where = saved
            con = sqlite3.connect(db)
            stored = json.loads(con.execute("SELECT data FROM locations WHERE pid=10").fetchone()[0])
            con.close()
        return w, len(calls), stored

    def test_a_cached_row_without_a_version_is_looked_up_again(self) -> None:
        w, n, stored = self.lookup_with_row({"pid": 10, "where": "unknown terminal", "title": "", "cwd": "", "focus": ""})
        assert w
        self.assertEqual((n, w["paseo_agent"], stored["v"]), (1, AGENT, where.ROW_VERSION))

    def test_a_versioned_unknown_terminal_row_is_served_from_the_cache(self) -> None:
        row = {"pid": 10, "where": "unknown terminal", "title": "", "cwd": "", "focus": "", "v": 2}
        w, n, _stored = self.lookup_with_row(row)
        self.assertEqual((n, w), (0, row))


if __name__ == "__main__":
    unittest.main()
