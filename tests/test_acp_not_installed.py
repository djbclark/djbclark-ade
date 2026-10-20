#!/usr/bin/env python3
"""A missing agent binary is infrastructure (2026-10-20).

03:25 an `npm i -g` replaced claude-agent-acp just as ime-onstart started: acp-run died "not
installed" and `acp-dispatch check` offered `--escalate (-> judgment)`. acp-run now waits for the
binary (ACP_RUN_BIN_WAIT) and exits 127; check offers a plain re-dispatch, never --escalate.
"""
from __future__ import annotations

import json
import os
import subprocess
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import override

from test_acp_dispatch import FAKE, Base, run

ACP_RUN = Path(os.environ.get("ACP_RUN_SCRIPT", str(Path(__file__).resolve().parent.parent
                                                    / "tools" / "acp-run" / "acp-run")))
UV = shutil.which("uv") or "uv"
FAKE_MISSING = FAKE.replace(
    'quota)    echo "FAILED quota"',
    'missing)  echo "acp-run: claude-agent-acp not installed" >&2; exit 127;;\n  quota)    echo "FAILED quota"', 1)


class TestAcpRunWaits(unittest.TestCase):
    def run_acp(self, wait: str, appear_after: float | None) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as td:
            bindir = Path(td)
            def install() -> None:
                time.sleep(appear_after or 0)
                exe = bindir / "claude-agent-acp"
                _ = exe.write_text("#!/bin/sh\nexit 3\n")
                exe.chmod(0o755)
            if appear_after is not None:
                threading.Thread(target=install, daemon=True).start()
            env = {**os.environ, "PATH": f"{bindir}:/usr/bin:/bin", "ACP_RUN_BIN_WAIT": wait,
                   "ACP_RUN_BIN_POLL": "0.1"}
            return subprocess.run([UV, "run", "--quiet", "--script", str(ACP_RUN), "claude", "-p", "hi", "--timeout", "5"],
                                  env=env, capture_output=True, text=True, check=False, timeout=60)

    def test_binary_that_appears_is_found(self):
        r = self.run_acp("10", 1.0)
        self.assertIn("waiting up to 10 s", r.stderr)
        self.assertNotIn("not installed", r.stderr)

    def test_binary_that_never_appears_exits_127(self):
        r = self.run_acp("0.5", None)
        self.assertEqual(r.returncode, 127, r.stderr)
        self.assertIn("claude-agent-acp not installed", r.stderr)

    def test_wait_zero_does_not_wait(self):
        t0 = time.monotonic()
        r = self.run_acp("0", None)
        self.assertEqual(r.returncode, 127, r.stderr)
        self.assertNotIn("waiting", r.stderr)
        self.assertLess(time.monotonic() - t0, 5)


class TestCheck(Base):
    @override
    def setUp(self) -> None:
        super().setUp()
        _ = self.fake.write_text(FAKE_MISSING)

    def test_not_installed_gets_redispatch_not_escalate(self):
        _ = self.dispatch_agent("codex", "m1", "--no-preflight", mode="missing")
        path = self.out / "jobs" / "s1.json"
        rec = json.loads(path.read_text())
        self.assertTrue(rec["failure"].startswith("NO-REPORT: not-installed"), rec["failure"])
        rec["kind"] = "code"
        _ = path.write_text(json.dumps(rec))
        out = run(["check", str(path)], env=self.base_env("missing")).stdout
        self.assertIn("re-dispatch", out)
        self.assertNotIn("escalate", out)


if __name__ == "__main__":
    unittest.main()
