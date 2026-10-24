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

AGENT = "aaaaaaaa-0000-4000-8000-000000000001"
SID = "bbbbbbbb-0000-4000-8000-000000000002"
CALLER = "11111111-2222-3333-4444-555555555555"

FAKE = """#!/bin/bash
# fake paseo: log argv (one line per call) and, per call, the PASEO_AGENT_ID it was run with; answer like the real one
echo "$*" >> "$FAKE_LOG"
echo "$1 ${PASEO_AGENT_ID:-NOID}" >> "$FAKE_ENVLOG"
case "$1 $2" in
  "agent inspect") id="${@: -1}"; [ "$id" = "$FAKE_KNOWN" ] || { echo "no such agent" >&2; exit 1; }
    echo "{\\"Id\\": \\"${FAKE_ID:-$id}\\", \\"Name\\": \\"fake\\", \\"Provider\\": \\"${FAKE_PROVIDER:-claude}\\", \\"Status\\": \\"${FAKE_STATUS:-idle}\\", \\"Archived\\": ${FAKE_ARCHIVED:-false}, \\"PendingPermissions\\": ${FAKE_PENDING:-[]}, \\"Cwd\\": \\"${FAKE_CWD:-/tmp}\\"}" ;;
  "wait "*) exit "${FAKE_WAIT_RC:-0}" ;;
  "send "*) echo '{"ok": true}' ;;
esac
"""


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
                          PASEO_AGENT_ID=CALLER)
        for k in ("FAKE_PROVIDER", "FAKE_STATUS", "FAKE_WAIT_RC", "FAKE_ARCHIVED", "FAKE_PENDING", "FAKE_ID", "FAKE_CWD",
                  "CLAUDE_CODE_SESSION_ID"):
            os.environ.pop(k, None)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved_env)))
        saved_attrs = [(relay.fleet, "sessions", relay.fleet.sessions), (relay.fleet, "ancestors", relay.fleet.ancestors),
                       (relay.where, "real_cwd", relay.where.real_cwd), (relay, "hosted_by", relay.hosted_by)]
        self.addCleanup(lambda: [setattr(o, n, v) for o, n, v in saved_attrs])
        relay.fleet.ancestors = lambda: set()    # hermetic: the test runner's real ancestry is not under test
        relay.hosted_by = lambda agent_id: agent_id == CALLER    # the test runner "is" the CALLER agent

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

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
        self.assertEqual(self.sends(), [f"send --no-wait --behavior steer --json -- {AGENT} [relay from the caller] ping"])
        self.assertEqual([e for e in self.envs() if e.startswith("send ")], ["send NOID"])

    def test_the_sender_tag_falls_back_to_the_session_id_prefix(self) -> None:
        del os.environ["PASEO_AGENT_ID"]
        os.environ["CLAUDE_CODE_SESSION_ID"] = "dddddddd-0000-4000-8000-000000000004"
        rc, _out, err = self.main([sess()], SID, "ping", "--wait", "1")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.sends(), [f"send --no-wait --behavior steer --json -- {AGENT} [relay from dddddddd] ping"])

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

    def test_paseo_agent_with_a_pending_permission_is_refused(self) -> None:
        os.environ["FAKE_PENDING"] = '[{"id": "p1", "tool": "Bash"}]'
        for listed, ident in (([], AGENT), ([sess()], SID)):
            rc, _out, err = self.main(listed, ident, "ping")
            self.assertEqual(rc, 1)
            self.assertIn("permission or question", err)
            self.assertIn("helm", err)
        self.assertFalse(self.sends())

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

    def test_an_empty_or_junk_paseo_agent_id_still_gets_the_sender_tag(self) -> None:
        for value in (" ", "", "not-a-uuid"):
            os.environ["PASEO_AGENT_ID"] = value
            rc, _out, err = self.main([sess()], SID, "ping", "--wait", "1")
            self.assertEqual(rc, 0, err)
            self.assertTrue(all("[relay from " in s_ for s_ in self.sends()), (value, self.sends()))

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

    def test_process_cwd_that_matches_the_agents_cwd_is_sent(self) -> None:
        s = sess(pid=4242)
        relay.where.real_cwd = lambda pid: "/tmp/agent-dir"
        os.environ["FAKE_CWD"] = "/tmp/agent-dir"
        rc, _out, err = self.main([s], SID, "ping", "--wait", "1")
        self.assertEqual(rc, 0, err)

    def test_working_non_steering_agent_needs_idle_and_then_waits_first(self) -> None:
        os.environ.update(FAKE_PROVIDER="cline", FAKE_STATUS="running")
        rc, _out, err = self.main([], AGENT, "ping")
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
