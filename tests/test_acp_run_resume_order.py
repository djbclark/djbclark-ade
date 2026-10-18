#!/usr/bin/env python3
"""acp-run --resume hardening (2026-10-18, ACP session-resume RFD stabilised 2026-04-22).

open_session prefers session/resume (no history replay) over session/load, falls back to load on
-32601/-32602, resends --add-dir only when sessionCapabilities.additionalDirectories is advertised
(else one stderr line), exits 2 for an unknown or a different session, and close_session sends
session/close only when sessionCapabilities.close is advertised. Same harness as
test_acp_run_session_seed.py: the script is loaded in a `uv run --with` subprocess and driven with
a fake connection; the client is acp-run's own RunClient writing its log to a StringIO.
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(
    os.environ.get("ACP_RUN_SCRIPT", str(ROOT / "tools" / "acp-run" / "acp-run"))
)
WITH = [
    "uv",
    "run",
    "--quiet",
    "--with",
    "agent-client-protocol>=0.9,<1.0",
    "python",
    "-I",
]
SID = "5f0c2a8e-1111-4222-8333-944455556666"

PROBE = textwrap.dedent("""\
    import asyncio, contextlib, importlib.machinery, importlib.util, io, json, sys
    from types import SimpleNamespace
    from acp import RequestError
    loader = importlib.machinery.SourceFileLoader("acp_run", sys.argv[1])
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("acp_run", loader))
    loader.exec_module(mod)
    SID = sys.argv[2]

    class FakeConn:
        def __init__(self, client, resume_err=None, load_err=None, replay_sid=None, close_err=None):
            self.client, self.calls = client, []
            self.resume_err, self.load_err, self.close_err = resume_err, load_err, close_err
            self.replay_sid = replay_sid

        async def _replay(self, session_id):
            for kind in ("user_message_chunk", "agent_message_chunk"):
                await self.client.session_update(self.replay_sid or session_id,
                                                 SimpleNamespace(session_update=kind))

        async def resume_session(self, cwd, session_id, mcp_servers=None, additional_directories=None):
            self.calls.append(["resume", session_id, additional_directories])
            if self.replay_sid:  # a buggy agent that opened another session
                await self._replay(session_id)
            if self.resume_err:
                raise self.resume_err
            return SimpleNamespace(modes=None, config_options=None)

        async def load_session(self, cwd, session_id, mcp_servers=None, additional_directories=None):
            self.calls.append(["load", session_id, additional_directories])
            if self.load_err:
                raise self.load_err
            await self._replay(session_id)
            return SimpleNamespace(modes=None, config_options=None)

        async def close_session(self, session_id):
            self.calls.append(["close", session_id])
            if self.close_err:
                raise self.close_err

    def init_of(load=True, resume=True, add_dirs=False, close=False):
        return SimpleNamespace(agent_capabilities=SimpleNamespace(
            load_session=load,
            session_capabilities=SimpleNamespace(
                resume=SimpleNamespace() if resume else None,
                additional_directories=SimpleNamespace() if add_dirs else None,
                close=SimpleNamespace() if close else None,
            ),
        ))

    def rows(log):
        return [json.loads(l)["kind"] for l in log.getvalue().splitlines()]

    async def case(init, add_dir=(), **conn_kw):
        log, err = io.StringIO(), io.StringIO()
        client = mod.RunClient(log, "all", "/tmp/root")
        conn = FakeConn(client, **conn_kw)
        a = SimpleNamespace(agent="claude", resume=SID, add_dir=list(add_dir), interactive=False)
        res = {"exit": None}
        with contextlib.redirect_stderr(err):
            try:
                s = await mod.open_session(a, conn, init, client, "/tmp/root", 10)
                res["session_id"] = s.session_id
            except SystemExit as e:
                res["exit"] = e.code
            except RequestError as e:
                res["error"] = e.code
        res.update(calls=conn.calls, rows=rows(log), stderr=err.getvalue(), replayed=client.replayed)
        return res

    async def close_case(init, close_err=None):
        log = io.StringIO()
        client = mod.RunClient(log, "all", "/tmp/root")
        conn = FakeConn(client, close_err=close_err)
        a = SimpleNamespace(agent="claude", info=False)
        await mod.close_session(a, conn, init, SimpleNamespace(session_id=SID), client,
                                SimpleNamespace(returncode=None))
        return {"calls": conn.calls, "rows": rows(log)}

    async def main():
        return {
            "both": await case(init_of()),
            "load_only": await case(init_of(resume=False)),
            "resume_only": await case(init_of(load=False)),
            "fallback": await case(init_of(), resume_err=RequestError.method_not_found("session/resume")),
            "no_fallback_resume_only": await case(
                init_of(load=False), resume_err=RequestError.method_not_found("session/resume")),
            "add_dir_sent": await case(init_of(add_dirs=True), add_dir=["/tmp/extra"]),
            "add_dir_warned": await case(init_of(), add_dir=["/tmp/extra"]),
            "not_found": await case(init_of(), resume_err=RequestError.resource_not_found(SID)),
            "not_found_text": await case(
                init_of(resume=False), load_err=RequestError(-32603, f"Session {SID} not found")),
            "mismatch": await case(init_of(resume=False), replay_sid="another-session"),
            "close_advertised": await close_case(init_of(close=True)),
            "close_absent": await close_case(init_of(close=False)),
            "close_fails": await close_case(init_of(close=True), close_err=RequestError(-32603, "boom")),
        }

    try:
        print(json.dumps(asyncio.run(main()), default=str))
    except Exception as e:  # surface an unexpected exception as a failing test, not a hang
        print(json.dumps({"crash": repr(e)}))
""")


class TestResumeOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        r = subprocess.run(
            [*WITH, "-c", PROBE, str(SCRIPT), SID],
            check=False,
            capture_output=True,
            text=True,
            timeout=600,
        )
        assert r.returncode == 0, r.stderr
        cls.res = json.loads(r.stdout)
        assert "crash" not in cls.res, cls.res

    def test_resume_preferred_when_both_advertised(self) -> None:
        both = self.res["both"]
        self.assertIsNone(both["exit"], both["stderr"])
        self.assertEqual([c[0] for c in both["calls"]], ["resume"])
        self.assertIn("resume_session", both["rows"])
        self.assertNotIn("load_session", both["rows"])
        self.assertEqual(both["replayed"], 0)
        self.assertIn(f"resumed session {SID} (0 messages)", both["stderr"])
        self.assertEqual([c[0] for c in self.res["resume_only"]["calls"]], ["resume"])

    def test_load_only_still_loads_and_counts_the_replay(self) -> None:
        lo = self.res["load_only"]
        self.assertIsNone(lo["exit"], lo["stderr"])
        self.assertEqual([c[0] for c in lo["calls"]], ["load"])
        self.assertIn("load_session", lo["rows"])
        self.assertIn(f"resumed session {SID} (2 messages)", lo["stderr"])

    def test_fallback_to_load_on_method_not_found(self) -> None:
        fb = self.res["fallback"]
        self.assertIsNone(fb["exit"], fb["stderr"])
        self.assertEqual([c[0] for c in fb["calls"]], ["resume", "load"])
        self.assertLess(
            fb["rows"].index("resume_fallback_load"), fb["rows"].index("load_session")
        )
        self.assertIn("falling back to session/load", fb["stderr"])
        self.assertEqual(fb["replayed"], 2)
        # with load not advertised the error is the run's, no load attempted
        self.assertEqual(
            [c[0] for c in self.res["no_fallback_resume_only"]["calls"]], ["resume"]
        )
        self.assertEqual(self.res["no_fallback_resume_only"]["exit"], None)
        self.assertEqual(self.res["no_fallback_resume_only"]["error"], -32601)

    def test_add_dir_sent_on_resume_only_when_advertised(self) -> None:
        extra = str(Path("/tmp/extra").resolve())
        sent = self.res["add_dir_sent"]
        self.assertEqual(sent["calls"][0][2], [extra])
        self.assertNotIn("--add-dir not sent", sent["stderr"])
        warned = self.res["add_dir_warned"]
        self.assertIsNone(warned["calls"][0][2])
        self.assertIn("additional_directories_not_sent", warned["rows"])
        self.assertEqual(warned["stderr"].count("--add-dir not sent on resume"), 1)
        self.assertIn(extra, warned["stderr"])

    def test_unknown_session_exits_2(self) -> None:
        for name in ("not_found", "not_found_text"):
            nf = self.res[name]
            self.assertEqual(nf["exit"], 2, nf)
            self.assertIn(
                f"acp-run: claude has no session {SID} to resume", nf["stderr"]
            )
            self.assertIn("resume_not_found", nf["rows"])
            self.assertNotIn("Traceback", nf["stderr"])
        # resource-not-found on resume is final: no load retry for a missing id
        self.assertEqual([c[0] for c in self.res["not_found"]["calls"]], ["resume"])

    def test_replay_from_another_session_exits_2(self) -> None:
        mm = self.res["mismatch"]
        self.assertEqual(mm["exit"], 2, mm)
        self.assertIn("resume_session_mismatch", mm["rows"])
        self.assertIn("reopened session another-session", mm["stderr"])

    def test_close_only_when_advertised_and_errors_are_logged(self) -> None:
        self.assertEqual(self.res["close_advertised"]["calls"], [["close", SID]])
        self.assertIn("close_session", self.res["close_advertised"]["rows"])
        self.assertEqual(self.res["close_absent"]["calls"], [])
        self.assertEqual(self.res["close_absent"]["rows"], [])
        self.assertEqual(self.res["close_fails"]["calls"], [["close", SID]])
        self.assertEqual(self.res["close_fails"]["rows"], ["close_session_failed"])


if __name__ == "__main__":
    unittest.main()
