#!/usr/bin/env python3
"""acp-run's FAILURE_CLASSES must not read a bare number as an HTTP status (2026-10-19).

`classify` matched `\\b429\\b` (quota) and `\\b5\\d\\d\\b` (transient) anywhere in the text, so a
stderr tail or an ACP error that merely counted things was a provider failure: "tools=536" on the
acp-run summary line became transient, and "processed 429 files" became quota, which sends the
slice down the quota path (auto-resume, reroute). Only a status written as one (HTTP 429, Error
503, "code": 500, 503 Service Unavailable) is a failure now. acp-run imports the ACP SDK, so the
script is loaded in a `uv run --with` subprocess, as in test_acp_run_failure.py.
"""
from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path
from typing import ClassVar, override

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("ACP_RUN_SCRIPT", str(ROOT / "tools" / "acp-run" / "acp-run")))

LOADER = """
import json, runpy, sys
mod = runpy.run_path(sys.argv[1], run_name="acp_run_module")
print(json.dumps({"classify": [mod["classify"](t) for t in json.loads(sys.argv[2])]}))
"""

METRICS = [
    "acp-run: agent=codex stop=error secs=514.8 tools=536 fail=agent",
    "build finished: processed 429 files, 0 errors",
    "copied 503 fixtures and 500 snapshots",
    "wrote 512 lines to the report",
]
HTTP_STATUSES = [
    ("Error: HTTP 503 Service Unavailable", "transient"),
    ("Error 429, Message: Individual quota reached", "quota"),
    ('{"code": 500, "message": "internal"}', "transient"),
    ("status 502 from the gateway", "transient"),
    ("503 Service Unavailable", "transient"),
    # zcode, 2026-10-16..18: an auth wall inside an "Internal error" envelope was transient and retried
    ('RequestError: Internal error {"details": "model_request_failed project_token_login_failed (Turn execution failed)"}', "auth"),
    ("project_token_login_failed", "auth"),
    ("Login failed: please sign in again", "auth"),
]


class TestClassifyNumbers(unittest.TestCase):
    classes: ClassVar[dict[str, list[str | None]]] = {}

    @classmethod
    @override
    def setUpClass(cls) -> None:
        texts = METRICS + [text for text, _ in HTTP_STATUSES]
        out = subprocess.run(
            ["uv", "run", "--quiet", "--with", "agent-client-protocol>=0.9,<1.0",
             "python", "-I", "-c", LOADER, str(SCRIPT), json.dumps(texts)],
            check=True, capture_output=True, text=True, timeout=300)
        cls.classes = {"all": json.loads(out.stdout.strip().splitlines()[-1])["classify"]}

    def test_bare_numbers_are_not_provider_failures(self):
        got = self.classes["all"][:len(METRICS)]
        self.assertEqual(got, [None] * len(METRICS))

    def test_http_statuses_still_classify(self):
        got = self.classes["all"][len(METRICS):]
        self.assertEqual(got, [cls for _, cls in HTTP_STATUSES])


if __name__ == "__main__":
    unittest.main()
