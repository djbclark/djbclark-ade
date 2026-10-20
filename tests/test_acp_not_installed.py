#!/usr/bin/env python3
"""A missing agent binary is infrastructure (2026-10-20).

03:25 an `npm i -g` replaced claude-agent-acp just as ime-onstart started: acp-run died "not
installed" and `acp-dispatch check` offered `--escalate (-> judgment)`. acp-run now waits for the
binary (ACP_RUN_BIN_WAIT) and exits 127; check offers a plain re-dispatch, never --escalate.
"""
from __future__ import annotations

import json
import os
import runpy
import subprocess
import shutil
import tempfile
import threading
import time
import unittest
import unittest.mock
from pathlib import Path
from typing import override

from test_acp_dispatch import FAKE, SCRIPT, Base, run

ACP_RUN = Path(os.environ.get("ACP_RUN_SCRIPT", str(Path(__file__).resolve().parent.parent
                                                    / "tools" / "acp-run" / "acp-run")))
UV = shutil.which("uv") or "uv"
FAKE_MISSING = FAKE.replace(
    'quota)    echo "FAILED quota"',
    'missing)  echo "acp-run: claude-agent-acp not installed" >&2; exit 127;;\n  quota)    echo "FAILED quota"', 1)


class TestAcpRunWaits(unittest.TestCase):
    def run_acp(self, wait: str, appears: bool) -> subprocess.CompletedProcess[str]:
        """acp-run with the agent binary missing. With `appears`, the binary is installed only once
        acp-run has printed that it is waiting, so a slow start (uv, a loaded runner) cannot let the
        binary appear before the check and skip the wait."""
        with tempfile.TemporaryDirectory() as td:
            bindir = Path(td)
            env = {**os.environ, "PATH": f"{bindir}:/usr/bin:/bin", "ACP_RUN_BIN_WAIT": wait,
                   "ACP_RUN_BIN_POLL": "0.1"}
            proc = subprocess.Popen([UV, "run", "--quiet", "--script", str(ACP_RUN), "claude", "-p", "hi", "--timeout", "5"],
                                    env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True)
            seen: list[str] = []
            installed = threading.Event()

            def watch() -> None:
                assert proc.stderr is not None
                for line in proc.stderr:
                    seen.append(line)
                    if appears and "waiting up to" in line and not installed.is_set():
                        time.sleep(0.5)
                        exe = bindir / "claude-agent-acp"
                        _ = exe.write_text("#!/bin/sh\nexit 3\n")
                        exe.chmod(0o755)
                        installed.set()
            reader = threading.Thread(target=watch, daemon=True)
            reader.start()
            try:
                _ = proc.wait(timeout=60)
                out = proc.stdout.read() if proc.stdout else ""
            finally:
                proc.kill()
            reader.join(timeout=10)
            return subprocess.CompletedProcess(proc.args, proc.returncode, out, "".join(seen))

    def test_binary_that_appears_is_found(self):
        r = self.run_acp("10", True)
        self.assertIn("waiting up to 10 s", r.stderr)
        self.assertNotIn("not installed", r.stderr)
        self.assertNotEqual(r.returncode, 127, r.stderr)        # it went on to start the (fake) agent

    def test_junk_and_unbounded_waits_fall_back_or_clamp(self):
        # the default is 90 s: the binary appears at once, so each run proves the wait value, not a long wait
        for value, shown in (("abc", "90"), ("nan", "90"), ("inf", "90"), ("1e9", "600")):
            r = self.run_acp(value, True)
            self.assertIn(f"waiting up to {shown} s", r.stderr, (value, r.stderr))
            self.assertNotIn("Traceback", r.stderr, value)
            self.assertNotEqual(r.returncode, 127, (value, r.stderr))

    def test_a_negative_wait_does_not_wait(self):
        r = self.run_acp("-5", False)
        self.assertEqual(r.returncode, 127, r.stderr)
        self.assertNotIn("waiting", r.stderr)

    def test_binary_that_never_appears_exits_127(self):
        r = self.run_acp("0.5", False)
        self.assertEqual(r.returncode, 127, r.stderr)
        self.assertIn("claude-agent-acp not installed", r.stderr)

    def test_wait_zero_does_not_wait(self):
        t0 = time.monotonic()
        r = self.run_acp("0", False)
        self.assertEqual(r.returncode, 127, r.stderr)
        self.assertNotIn("waiting", r.stderr)
        self.assertLess(time.monotonic() - t0, 5)


class TestClassify(unittest.TestCase):
    """The not-installed class needs acp-run's own line and exit 127, not text that merely quotes it."""

    def cls(self, text: str, rc: int | None) -> str | None:
        return runpy.run_path(str(SCRIPT))["failure_class"](text, rc)[0]

    def test_the_line_with_exit_127(self):
        self.assertEqual(self.cls("acp-run: claude-agent-acp not installed\n", 127), "not-installed")

    def test_a_quoted_line_or_another_exit_is_something_else(self):
        quoted = "acp-run: FAILED x: error='acp-run: claude-agent-acp not installed' fail=transient\n"
        self.assertEqual(self.cls(quoted, 1), "transient")
        self.assertEqual(self.cls(quoted, 127), "transient")          # not at the start of a line
        self.assertNotEqual(self.cls("acp-run: claude-agent-acp not installed\n", 1), "not-installed")
        self.assertNotEqual(self.cls("acp-run: claude-agent-acp not installed\n", None), "not-installed")


class TestPreflightWaitsForTheBinary(Base):
    """acp-run waits up to ACP_RUN_BIN_WAIT before its own --timeout starts: the probe gets that on top
    (a binary that reappears late must not surface as a timeout, which reads as a provider outage)."""

    def test_probe_timeout_and_env_include_the_binary_wait(self):
        seen: dict = {}

        def fake_run(cmd, **kw):
            seen.update(kw)
            return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")
        with unittest.mock.patch.dict(os.environ, {"ACP_DISPATCH_PREFLIGHT": str(self.tmp / "pf"),
                                                   "ACP_RUN_BIN_WAIT": "30"}):
            mod = runpy.run_path(str(SCRIPT))
            with unittest.mock.patch("subprocess.run", fake_run):
                ok, _, _, _ = mod["preflight"]("acp-run", "codex", "m1")
        self.assertTrue(ok)
        self.assertEqual(seen["timeout"], mod["PREFLIGHT_TIMEOUT"] + 30 + 10)
        self.assertEqual(seen["env"]["ACP_RUN_BIN_WAIT"], "30")

    def test_default_and_junk_waits(self):
        fn = runpy.run_path(str(SCRIPT))["bin_wait_seconds"]
        cases = {None: 90.0, "abc": 90.0, "nan": 90.0, "inf": 90.0, "-5": 0.0, "0": 0.0, "12.5": 12.5, "9999": 600.0}
        for value, want in cases.items():
            env = {} if value is None else {"ACP_RUN_BIN_WAIT": value}
            with unittest.mock.patch.dict(os.environ, env, clear=False):
                if value is None:
                    os.environ.pop("ACP_RUN_BIN_WAIT", None)
                self.assertEqual(fn(), want, value)


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
