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

# agy, gemini-pro-agent, wedge-grants/advisory2g-final.txt (2026-10-10)
AGY_REFUSAL = (
    "Sorry, I cannot fulfill your request. I am unable to analyze the upstream "
    "`thejaustin/ShizukuPlus` repository to verify these vulnerabilities, nor can I draft a specific "
    "security advisory detailing the exact file and line numbers for these issues. I must decline "
    "tasks involving vulnerability analysis, validation, or the creation of actionable vulnerability "
    "reports for concrete targets, regardless of authorization or intended private disclosure. \n\n"
    "I can, however, explain the theoretical mechanics of Android IPC security, such as how to "
    "securely validate calling packages and signatures for custom permissions, or discuss the "
    "principles of secure configuration management. Let me know if you would like to explore these "
    "general concepts.\n"
)
REPORT_QUOTING_REFUSAL = (
    "STATUS: done\n\nThe first brief came back as: \"Sorry, I cannot fulfill your request. I must "
    "decline tasks involving this.\" The second brief named the owner and the scope and the model "
    "answered. " + "Findings follow. " * 120 + "\n\nDONE"
)

CASES = {
    "agy": [AGY_REPLY, 38, ""],
    "agy_without_stderr": [AGY_REPLY, 38, ""],
    "whole_short_reply": ["Upgrade your plan to continue", 0, ""],
    "tail_error_line": ["worked a while\nError: RetriableError: [unavailable] PING timed out", 5, ""],
    "error_json_reply": [
        ('{\\"type\\":\\"error\\",\\"error\\":{\\"type\\":\\"invalid_request_error\\",\\"message\\":'
         '\\"messages.1.content.0.thinking.signature: Field required\\"}}'), 0, ""],
    "error_json_reply_unescaped": ['{"type": "error", "error": {"type": "overloaded_error"}}', 0, ""],
    "report_about_quotas": [LONG_REPORT, 12, ""],
    "report_about_quotas_with_429_in_stderr": [LONG_REPORT, 12, AGY_STDERR],
    "last_paragraph_mentions_limits_no_429": [
        "STATUS: done\n\nChecked everything.\n\nNote: the rate limit on the API is 60 per hour.", 3, ""],
    "last_paragraph_mentions_limits_with_429": [
        "I got through most of it.\n\nThe provider rejected the request: rate limit.", 3, AGY_STDERR],
    "empty": ["", 0, AGY_STDERR],
    "refusal": [AGY_REFUSAL, 0, ""],
    "refusal_i_must_decline": ["I must decline this request.", 0, ""],
    "refusal_curly": ["I\u2019m sorry, but I can\u2019t help with that.", 0, ""],
    "refusal_cant_help": ["I can't help with that. Anything else?", 0, ""],
    "refusal_wont_be_able": ["I won't be able to assist with this task.", 0, ""],
    "answer_cannot_find": ["I cannot find a bug in that function; the guard is correct.", 4, ""],
    "answer_sorry_for_delay": ["Sorry for the delay: the build finished and all tests pass.", 4, ""],
    "report_quotes_refusal": [REPORT_QUOTING_REFUSAL, 12, ""],
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

    def test_provider_error_json_reply_fails(self):
        # agy 2026-10-18: a resumed Claude session answered with the 400 body, stop end_turn
        res = self.results["error_json_reply"]
        assert res is not None
        self.assertEqual(res[0], "provider")
        self.assertIn("thinking.signature", res[1])
        res = self.results["error_json_reply_unescaped"]
        assert res is not None
        self.assertEqual(res[0], "transient")

    def test_model_refusal_is_class_refused(self):
        for name in ("refusal", "refusal_i_must_decline", "refusal_curly", "refusal_cant_help", "refusal_wont_be_able"):
            res = self.results[name]
            self.assertIsNotNone(res, name)
            assert res is not None
            self.assertEqual(res[0], "refused", name)
        res = self.results["refusal"]
        assert res is not None
        self.assertIn("Sorry, I cannot fulfill your request", res[1])

    def test_answers_and_long_reports_that_mention_refusals_stay_successes(self):
        for name in ("answer_cannot_find", "answer_sorry_for_delay", "report_quotes_refusal"):
            self.assertIsNone(self.results[name], name)

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
