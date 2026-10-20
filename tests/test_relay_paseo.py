#!/usr/bin/env python3
"""relay.py and where.py learn the Paseo host (2026-10-20).

A Claude Code the Paseo daemon spawned has no terminal, so where.py reported "unknown terminal" and relay.py
refused it ("no terminal channel") although PASEO_AGENT_ID names it exactly. relay.py now reaches it with
`paseo send <id> --behavior steer`; these tests drive it against a fake `paseo` that records its argv.
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

AGENT = "6ebd939d-1eb7-49d0-9f4a-d2f284e8ff78"
SID = "a0c69a11-ada2-4969-9ba9-1b6b54bac91c"

FAKE = """#!/bin/bash
# fake paseo: log argv (one line per call) and whether PASEO_AGENT_ID leaked in, then answer like the real one
echo "${PASEO_AGENT_ID:+LEAK }$*" >> "$FAKE_LOG"
case "$1 $2" in
  "agent inspect") [ "$3" = "$FAKE_KNOWN" ] || { echo "no such agent" >&2; exit 1; }
    echo "{\\"Id\\": \\"$3\\", \\"Name\\": \\"fake\\", \\"Provider\\": \\"${FAKE_PROVIDER:-claude}\\", \\"Status\\": \\"${FAKE_STATUS:-idle}\\", \\"Cwd\\": \\"/tmp\\"}" ;;
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
        fake = Path(self.tmp.name) / "paseo"
        _ = fake.write_text(FAKE)
        fake.chmod(0o755)
        saved_env = dict(os.environ)
        os.environ.update(PASEO_CLI=str(fake), FAKE_LOG=str(self.log), FAKE_KNOWN=AGENT, PASEO_AGENT_ID="11111111-2222-3333-4444-555555555555")
        for k in ("FAKE_PROVIDER", "FAKE_STATUS", "FAKE_WAIT_RC"):
            os.environ.pop(k, None)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved_env)))
        saved_sessions = relay.fleet.sessions
        self.addCleanup(lambda: setattr(relay.fleet, "sessions", saved_sessions))

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

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
        self.assertEqual(self.calls(), [f"agent inspect {AGENT} --json",
                                        f"send {AGENT} --no-wait --behavior steer --json hello there"])
        rec = json.loads(out)
        self.assertEqual((rec["result"], rec["via"]), ("accepted", f"paseo {AGENT}"))

    def test_the_sending_agents_own_id_never_reaches_paseo_send(self) -> None:
        _ = self.main([], AGENT, "hi", "--wait", "1")
        self.assertFalse([c for c in self.calls() if c.startswith("LEAK")], self.calls())

    def test_sid_of_a_paseo_hosted_session_is_sent_via_paseo(self) -> None:
        rc, _out, err = self.main([sess()], SID, "ping", "--wait", "1")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.calls(), [f"send {AGENT} --no-wait --behavior steer --json ping"])

    def test_name_and_agent_id_find_the_same_session(self) -> None:
        for ident in ("djbclark-ade-db", AGENT):
            self.log.unlink(missing_ok=True)
            rc, _out, err = self.main([sess()], ident, "ping", "--wait", "1")
            self.assertEqual(rc, 0, err)
            self.assertEqual(len(self.calls()), 1, ident)

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

    def test_unknown_terminal_for_a_pid_nobody_hosts_still_errors_and_names_paseo(self) -> None:
        s = sess(host="terminal", chan=None, paseo=None, where="unknown terminal")
        rc, _out, err = self.main([s], SID, "ping", "--wait", "1")
        self.assertEqual(rc, 1)
        self.assertIn("no terminal channel (unknown terminal)", err)
        self.assertIn("Paseo", err)
        self.assertIn("agent id", err)
        self.assertEqual(self.calls(), [])

    def test_uuid_paseo_does_not_know_is_no_match(self) -> None:
        rc, _out, err = self.main([], "99999999-0000-0000-0000-000000000000", "ping")
        self.assertEqual(rc, 1)
        self.assertIn("no session(s) match", err)
        self.assertFalse([c for c in self.calls() if c.startswith("send")])

    def test_closed_or_errored_paseo_agent_is_refused(self) -> None:
        os.environ["FAKE_STATUS"] = "closed"
        rc, _out, err = self.main([], AGENT, "ping")
        self.assertEqual(rc, 1)
        self.assertIn("closed", err)
        self.assertFalse([c for c in self.calls() if c.startswith("send")])

    def test_own_paseo_agent_is_refused(self) -> None:
        os.environ["PASEO_AGENT_ID"] = AGENT
        rc, _out, err = self.main([], AGENT, "ping")
        self.assertEqual(rc, 1)
        self.assertIn("this session", err)

    def test_working_non_claude_agent_needs_idle_and_then_waits_first(self) -> None:
        os.environ.update(FAKE_PROVIDER="codex", FAKE_STATUS="running")
        rc, _out, err = self.main([], AGENT, "ping")
        self.assertEqual(rc, 1)
        self.assertIn("only idle ones", err)
        self.log.unlink(missing_ok=True)
        rc, _out, err = self.main([], AGENT, "ping", "--idle", "5", "--wait", "1")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.calls(), [f"agent inspect {AGENT} --json", f"wait {AGENT} --timeout 5 --json",
                                        f"send {AGENT} --no-wait --behavior steer --json ping"])

    def test_idle_timeout_sends_nothing(self) -> None:
        os.environ.update(FAKE_PROVIDER="codex", FAKE_STATUS="running", FAKE_WAIT_RC="124")
        rc, _out, err = self.main([], AGENT, "ping", "--idle", "5")
        self.assertEqual(rc, 1)
        self.assertIn("still running", err)
        self.assertFalse([c for c in self.calls() if c.startswith("send")])

    def test_missing_paseo_cli_is_reported(self) -> None:
        os.environ["PASEO_CLI"] = "/nonexistent/paseo"
        rc, _out, err = self.main([sess()], SID, "ping")
        self.assertEqual(rc, 1)
        self.assertIn("failed", err)


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

    def test_a_cached_unknown_terminal_row_is_looked_up_again(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            db = Path(t) / "h.sqlite"
            con = sqlite3.connect(db)
            _ = con.execute("CREATE TABLE locations(pid INTEGER PRIMARY KEY, proc_start TEXT, ts REAL, data TEXT)")
            stale = json.dumps({"pid": 10, "where": "unknown terminal", "title": "", "cwd": "", "focus": ""})
            _ = con.execute("INSERT INTO locations VALUES (10, 'S', ?, ?)", (__import__("time").time(), stale))
            con.commit()
            con.close()
            saved = (where.DB, where.where)
            where.DB = db
            where.where = lambda pid: {"pid": pid, "where": f"host=paseo agent={AGENT}", "paseo_agent": AGENT}
            try:
                w = where.lookup(10, "S")
            finally:
                where.DB, where.where = saved
        assert w
        self.assertEqual(w["paseo_agent"], AGENT)


if __name__ == "__main__":
    unittest.main()
