#!/usr/bin/env python3
"""A missing agent binary is infrastructure (2026-10-20).

03:25 an `npm i -g` replaced claude-agent-acp just as ime-onstart started: acp-run died "not
installed" and `acp-dispatch check` offered `--escalate (-> judgment)`. acp-run now waits for the
binary (ACP_RUN_BIN_WAIT) and exits 127. acp-dispatch's preflight, check hint and failure classes for it went with
the Paseo shim (slim-down E6, 2026-11-06); the acp-run halves stay with acp-run.
"""
from __future__ import annotations

import os
import subprocess
import shutil
import tempfile
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

ACP_RUN = Path(os.environ.get("ACP_RUN_SCRIPT", str(Path(__file__).resolve().parent.parent
                                                    / "tools" / "acp-run" / "acp-run")))
UV = shutil.which("uv") or "uv"


def acp_run_bin_settings() -> dict:
    """acp-run's own env_seconds and bin_wait_settings, compiled from its source (the script needs the
    `acp` package, which only `uv run --script` provides)."""
    import ast
    import math
    tree = ast.parse(ACP_RUN.read_text())
    keep = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in ("env_seconds", "bin_wait_settings"))
            or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ("BIN_WAIT", "BIN_WAIT_MAX", "BIN_POLL")
                                                  for t in n.targets))]
    ns: dict = {"os": os, "math": math}
    exec(compile(ast.Module(keep, []), str(ACP_RUN), "exec"), ns)     # noqa: S102 - the repo's own file
    return ns


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


class TestAcpRunNamesTheWrappedExecutable(unittest.TestCase):
    """Codex 4322594869 (PR 18): a launch command `env NAME=VAL ... PROGRAM` made shutil.which(cmd[0])
    find /usr/bin/env and skip the binary wait and the exit-127 path (crush's was one; crush retired 2026-11-06,
    the executable-name logic stays)."""

    def acp(self, *args: str, wait: str = "0.5") -> subprocess.CompletedProcess[str]:
        # PATH has env (/usr/bin) but no agent binary
        env = {**os.environ, "PATH": "/usr/bin:/bin", "ACP_RUN_BIN_WAIT": wait, "ACP_RUN_BIN_POLL": "0.1"}
        return subprocess.run([UV, "run", "--quiet", "--script", str(ACP_RUN), *args], env=env, check=False,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)

    def test_codex_with_no_binary_waits_then_exits_127(self):
        # the wait and exit-127 path that crush's env-wrapped command used to cover end to end
        r = self.acp("codex", "-p", "hi", "--timeout", "5", "--perm", "all")
        self.assertEqual(r.returncode, 127, r.stderr)
        self.assertIn("codex-acp not found on PATH; waiting up to 0.5 s", r.stderr)
        self.assertIn("acp-run: codex-acp not installed", r.stderr)

    def test_codex_with_the_wait_disabled_is_still_not_installed(self):
        r = self.acp("codex", "-p", "hi", "--timeout", "5", "--perm", "all", wait="0")
        self.assertEqual(r.returncode, 127, r.stderr)
        self.assertNotIn("waiting", r.stderr)
        self.assertIn("acp-run: codex-acp not installed", r.stderr)

    def test_list_marks_a_missing_agent(self):
        r = self.acp("--list")
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = [ln for ln in r.stdout.splitlines() if ln[3:].startswith("codex ")]
        self.assertEqual(len(rows), 1, r.stdout)
        self.assertTrue(rows[0].startswith("-- "), rows[0])

    def test_the_executable_skips_env_and_its_assignments(self):
        import ast
        tree = ast.parse(ACP_RUN.read_text())
        fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "agent_executable"]
        self.assertEqual(len(fn), 1)
        ns: dict = {"os": os}
        exec(compile(ast.Module(fn, []), str(ACP_RUN), "exec"), ns)     # noqa: S102 - the repo's own file
        exe = ns["agent_executable"]
        self.assertEqual(exe(["env", "A=1", "B=x=y", "agent-acp", "acp", "--yolo"]), "agent-acp")
        self.assertEqual(exe(["env", "agent-acp"]), "agent-acp")
        self.assertEqual(exe(["claude-agent-acp"]), "claude-agent-acp")
        self.assertEqual(exe(["codex-acp", "A=1"]), "codex-acp")        # only env's own assignments are skipped
        self.assertEqual(exe(["env"]), "env")

if __name__ == "__main__":
    unittest.main()
