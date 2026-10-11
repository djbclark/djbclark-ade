#!/usr/bin/env python3
"""Tests for tools/acp-run/acp-run's delivery checks (reply_failure).

An agent returns a provider refusal as its answer (stop=end_turn, exit 0). 2026-10-10: agy
worked 356 s, then its backend answered HTTP 429 and the ACP server appended the refusal to the
message it had been streaming, so the refusal was the last paragraph of a longer reply, not the
whole reply. acp-run imports the ACP SDK, so the script is loaded in a `uv run --with` subprocess.
"""
from __future__ import annotations

import json
import os
import subprocess
import textwrap
import unittest
from pathlib import Path
from typing import ClassVar, override

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("ACP_RUN_SCRIPT", str(ROOT / "tools" / "acp-run" / "acp-run")))

# agy, claude-opus-5-5-high, wedge-grants/astra-review2-final.txt (227 characters)
AGY_REPLY = (
    "Shell works for those paths; I'll read via cat.Now the full current ShizukuService main and "
    "relevant parts.Usage Limit Reached\n\nYou have reached your current quota for this period. "
    "Your limit will reset in 2 hours, 47 minutes."
)
# the 429 from that turn's agy_acp_server stderr (trimmed)
AGY_STDERR = (
    "Antigravity SDK error processing prompt\n"
    "google.antigravity.types.AntigravityExecutionError: Error 429, Message: Individual quota "
    "reached. Resets in 2h47m44s., Status: RESOURCE_EXHAUSTED\n"
)
LONG_REPORT = (
    "STATUS: done\n\nThe wedge grants are held per UID in a rate limit table; when the quota for a "
    "caller is exceeded the service answers with a usage limit error and the manager shows it.\n\n"
    "Quota exhausted handling is covered in section 3; rate limit reached is a log line only.\n\n"
    "DONE"
)

CASES = {
    "agy": [AGY_REPLY, 38, ""],
    "agy_without_stderr": [AGY_REPLY, 38, ""],
    "whole_short_reply": ["Upgrade your plan to continue", 0, ""],
    "tail_error_line": ["worked a while\nError: RetriableError: [unavailable] PING timed out", 5, ""],
    "report_about_quotas": [LONG_REPORT, 12, ""],
    "report_about_quotas_with_429_in_stderr": [LONG_REPORT, 12, AGY_STDERR],
    "last_paragraph_mentions_limits_no_429": [
        "STATUS: done\n\nChecked everything.\n\nNote: the rate limit on the API is 60 per hour.", 3, ""],
    "last_paragraph_mentions_limits_with_429": [
        "I got through most of it.\n\nThe provider rejected the request: rate limit.", 3, AGY_STDERR],
    "empty": ["", 0, AGY_STDERR],
}

PROBE = textwrap.dedent("""\
    import importlib.machinery, importlib.util, json, sys
    loader = importlib.machinery.SourceFileLoader("acp_run", sys.argv[1])
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("acp_run", loader))
    loader.exec_module(mod)
    cases = json.load(sys.stdin)
    print(json.dumps({k: mod.reply_failure(*v) for k, v in cases.items()}))
    """)


def probe() -> dict[str, list[str] | None]:
    cases = dict(CASES)
    cases["agy"] = [AGY_REPLY, 38, AGY_STDERR]
    r = subprocess.run(
        ["uv", "run", "--quiet", "--with", "agent-client-protocol>=0.9,<1.0", "python", "-I", "-c", PROBE,
         str(SCRIPT)], input=json.dumps(cases), check=False, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


class TestReplyFailure(unittest.TestCase):
    results: ClassVar[dict[str, list[str] | None]] = {}

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.results = probe()

    def test_agy_refusal_after_progress_text_is_quota(self):
        for name in ("agy", "agy_without_stderr"):
            res = self.results[name]
            self.assertIsNotNone(res, name)
            assert res is not None
            self.assertEqual(res[0], "quota", name)
            self.assertIn("reset in 2 hours, 47 minutes", res[1])
            self.assertIn("edits may be present", res[1])

    def test_whole_short_refusal_still_fails(self):
        res = self.results["whole_short_reply"]
        assert res is not None
        self.assertEqual(res[0], "plan")

    def test_tail_error_line_still_fails_as_transient(self):
        res = self.results["tail_error_line"]
        assert res is not None
        self.assertEqual(res[0], "transient")

    def test_report_that_discusses_quotas_stays_a_success(self):
        self.assertIsNone(self.results["report_about_quotas"])
        self.assertIsNone(self.results["report_about_quotas_with_429_in_stderr"])
        self.assertIsNone(self.results["last_paragraph_mentions_limits_no_429"])
        self.assertIsNone(self.results["empty"])

    def test_429_in_stderr_backs_a_quota_mention_in_the_last_paragraph(self):
        res = self.results["last_paragraph_mentions_limits_with_429"]
        assert res is not None
        self.assertEqual(res[0], "quota")


if __name__ == "__main__":
    unittest.main()
