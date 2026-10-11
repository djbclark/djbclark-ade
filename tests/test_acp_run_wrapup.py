#!/usr/bin/env python3
"""Tests for tools/acp-run/acp-run's wrap-up turn after a --timeout cancel (--wrapup-grace).

2026-10-10, wedge-grants/stlib: opencode + deepseek-v4-pro had its change verified at 2009 s of a
2400 s timeout, then sat in `git commit` while the pre-commit Gradle hook queued on the machine-wide
Gradle slot. acp-run sent session/cancel at 2400 s and exited 124; the agent never got a turn to write
its report, which stayed at `STATUS: working`. Now, with --wrapup-grace S, acp-run sends one more
prompt after the cancel and waits up to S seconds for it.

acp-run imports the ACP SDK, so the script is loaded in a `uv run --with` subprocess and
prompt_turn is driven against a fake connection whose behaviour each case selects.
"""
from __future__ import annotations

import json
import os
import subprocess
import textwrap
import unittest
from pathlib import Path
from typing import Any, ClassVar, override

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("ACP_RUN_SCRIPT", str(ROOT / "tools" / "acp-run" / "acp-run")))

PROBE = textwrap.dedent("""\
    import asyncio, importlib.machinery, importlib.util, io, json, sys
    from types import SimpleNamespace
    loader = importlib.machinery.SourceFileLoader("acp_run", sys.argv[1])
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("acp_run", loader))
    loader.exec_module(mod)
    REAL_WAIT_FOR = asyncio.wait_for  # mod.asyncio is this same module: patch and restore through it

    class FakeConn:
        # first prompt: the main turn, which runs past --timeout; it ends "cancelled" on
        # session/cancel unless `stuck`. Later prompts: the wrap-up, which writes `reply` and
        # ends end_turn after `wrapup_secs` (None: never, until cancelled).
        def __init__(self, client, stuck=False, wrapup_secs=0.0, reply="written: /r.md"):
            self.client, self.stuck, self.wrapup_secs, self.reply = client, stuck, wrapup_secs, reply
            self.prompts, self.cancels, self.ev = [], 0, None

        async def prompt(self, session_id, prompt):
            self.prompts.append(prompt[0].text)
            self.ev = asyncio.Event()
            if len(self.prompts) == 1:
                await self.ev.wait()
                if self.stuck:
                    await asyncio.sleep(3600)
                return SimpleNamespace(stop_reason="cancelled")
            if self.wrapup_secs is None:
                await self.ev.wait()
                return SimpleNamespace(stop_reason="cancelled")
            await asyncio.sleep(self.wrapup_secs)
            self.client.text.append(self.reply)
            return SimpleNamespace(stop_reason="end_turn")

        async def cancel(self, session_id):
            self.cancels += 1
            if self.ev is not None:
                self.ev.set()

    async def case(grace, wrapup=None, interactive=False, **kw):
        client = mod.RunClient(io.StringIO(), "all", ".")
        conn = FakeConn(client, **kw)
        a = SimpleNamespace(timeout=0.2, prompt_retries=0, interactive=interactive,
                            wrapup_grace=grace, wrapup=wrapup)
        out = {}
        if kw.get("stuck"):
            # the 15 s wait for the cancelled turn would make this case slow: shorten it
            async def short(aw, t):
                return await REAL_WAIT_FOR(aw, min(t, 0.3))
            mod.asyncio.wait_for = short
        try:
            finished, failure, code = await mod.prompt_turn(
                a, conn, SimpleNamespace(session_id="s"), client, "do the work", out)
        finally:
            mod.asyncio.wait_for = REAL_WAIT_FOR
        return {"code": code, "finished": finished, "out": out, "prompts": conn.prompts,
                "cancels": conn.cancels, "text": "".join(client.text)}

    async def main():
        return {
            "off": await case(0),
            "wrapup": await case(5),
            "custom": await case(5, wrapup="report to /x.md within {grace} s"),
            "wrapup_hangs": await case(0.3, wrapup_secs=None),
            "stuck": await case(5, stuck=True),
            "interactive": await case(5, interactive=True),
        }

    print(json.dumps(asyncio.run(main())))
    """)


def probe() -> dict[str, dict[str, Any]]:
    r = subprocess.run(
        ["uv", "run", "--quiet", "--with", "agent-client-protocol>=0.9,<1.0", "python", "-I", "-c", PROBE,
         str(SCRIPT)], check=False, capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


class TestWrapup(unittest.TestCase):
    results: ClassVar[dict[str, dict[str, Any]]] = {}

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.results = probe()

    def test_without_grace_the_timeout_is_a_bare_cancel(self):
        r = self.results["off"]
        self.assertEqual(r["code"], 124)
        self.assertEqual(len(r["prompts"]), 1)
        self.assertNotIn("wrapup", r["out"])
        self.assertEqual(r["out"]["stop_reason"], "cancelled")

    def test_grace_sends_one_wrapup_prompt_after_the_cancel(self):
        r = self.results["wrapup"]
        self.assertEqual(r["code"], 124, "a timed-out run still exits 124")
        self.assertFalse(r["finished"])
        self.assertEqual(len(r["prompts"]), 2)
        self.assertIn("TIME IS UP", r["prompts"][1])
        self.assertIn("5 seconds", r["prompts"][1])
        self.assertEqual(r["out"]["wrapup"], "end_turn")
        self.assertEqual(r["out"]["stop_reason"], "cancelled", "the main turn's stop reason is kept")
        self.assertEqual(r["text"], "written: /r.md", "the final message is the wrap-up reply")

    def test_custom_wrapup_text_gets_the_grace_filled_in(self):
        r = self.results["custom"]
        self.assertEqual(r["prompts"][1], "report to /x.md within 5 s")

    def test_a_wrapup_that_overruns_is_cancelled_too(self):
        r = self.results["wrapup_hangs"]
        self.assertEqual(r["code"], 124)
        self.assertEqual(r["out"]["wrapup"], "timeout")
        self.assertEqual(r["cancels"], 2)

    def test_no_wrapup_while_the_cancelled_turn_has_not_ended(self):
        r = self.results["stuck"]
        self.assertEqual(r["code"], 124)
        self.assertEqual(len(r["prompts"]), 1, "a prompt sent now would queue behind the stuck turn")
        self.assertTrue(r["out"]["wrapup"].startswith("skipped"))

    def test_interactive_turns_get_no_wrapup(self):
        r = self.results["interactive"]
        self.assertEqual(len(r["prompts"]), 1)
        self.assertNotIn("wrapup", r["out"])


if __name__ == "__main__":
    unittest.main()
