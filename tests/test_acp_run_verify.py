#!/usr/bin/env python3
"""Tests for tools/acp-run/acp-run's verify-and-retry loop (--verify).

Tests pure helpers (build_verify_prompt, run_verify), argument parsing in main(),
and driving prompt_turn against FakeConn with real shell commands.
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
    import asyncio, importlib.machinery, importlib.util, io, json, os, sys, tempfile
    from types import SimpleNamespace
    loader = importlib.machinery.SourceFileLoader("acp_run", sys.argv[1])
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("acp_run", loader))
    loader.exec_module(mod)

    # 1. Test build_verify_prompt
    short_prompt = mod.build_verify_prompt("pytest", 1, "AssertionError: 1 != 2")
    many_lines = "\\n".join(f"line {i}" for i in range(100))
    line_prompt = mod.build_verify_prompt("pytest", 1, many_lines)
    huge_output = "x" * 5000
    char_prompt = mod.build_verify_prompt("pytest", 1, huge_output)
    empty_prompt = mod.build_verify_prompt("pytest", 2, "")

    build_tests = {
        "short_contains_cmd_and_rc": 'The check "pytest" failed (exit 1).' in short_prompt,
        "short_contains_instructions": "Fix the problem, run the check yourself, and only stop when it passes." in short_prompt,
        "short_contains_output": "AssertionError: 1 != 2" in short_prompt,
        "line_prompt_max_40_lines": "line 59" not in line_prompt and "line 60" in line_prompt,
        "char_prompt_max_3000_chars": len(mod.tail_lines(huge_output)) <= 3000,
        "empty_prompt_valid": 'The check "pytest" failed (exit 2). Last output:\\n\\nFix the problem' in empty_prompt,
    }

    # 2. Test run_verify
    with tempfile.TemporaryDirectory() as td:
        rc0, out0 = mod.run_verify("echo 'all good'", td, 10)
        rc1, out1 = mod.run_verify("echo 'bad news' >&2; exit 2", td, 10)
        rc_cwd, out_cwd = mod.run_verify("pwd", td, 10)
        rc_to, _ = mod.run_verify("sleep 1", td, 0.05)

    run_tests = {
        "pass_rc": rc0 == 0,
        "pass_out": "all good" in out0,
        "fail_rc": rc1 == 2,
        "fail_out": "bad news" in out1,
        "cwd_respected": os.path.realpath(td) in os.path.realpath(out_cwd),
        "timeout_rc": rc_to == 124,
    }

    # 3. prompt_turn against FakeConn
    class FakeConn:
        def __init__(self, client, stop_reason="end_turn", reply="Done."):
            self.client = client
            self.stop_reason = stop_reason
            self.reply = reply
            self.prompts = []

        async def prompt(self, session_id, prompt):
            self.prompts.append(prompt[0].text)
            self.client.text.append(self.reply)
            return SimpleNamespace(stop_reason=self.stop_reason, field_meta=None, usage=None)

        async def cancel(self, session_id):
            pass

    async def turn_case(verify=None, retries=2, timeout=180, verify_cmd_script=None, stop_reason="end_turn", reply="Done."):
        with tempfile.TemporaryDirectory() as td:
            client = mod.RunClient(io.StringIO(), "all", td)
            conn = FakeConn(client, stop_reason=stop_reason, reply=reply)
            cmd = verify
            if verify_cmd_script:
                script_path = os.path.join(td, "check.sh")
                with open(script_path, "w") as f:
                    f.write(verify_cmd_script)
                os.chmod(script_path, 0o755)
                cmd = script_path

            a = SimpleNamespace(
                dir=td,
                timeout=timeout,
                prompt_retries=0,
                interactive=False,
                wrapup_grace=0,
                perm="all",
                verify=cmd,
                verify_retries=retries,
                verify_timeout=10,
            )
            out = {}
            finished, failure, code = await mod.prompt_turn(
                a, conn, SimpleNamespace(session_id="s"), client, "initial prompt", out
            )
            return {
                "finished": finished,
                "failure": failure,
                "code": code,
                "out": out,
                "prompts": conn.prompts,
            }

    script_pass_second = (
        "#!/bin/sh\\n"
        "if [ -f marker.txt ]; then\\n"
        "    echo 'check passed'\\n"
        "    exit 0\\n"
        "else\\n"
        "    echo marker > marker.txt\\n"
        "    echo 'check failed on first try' >&2\\n"
        "    exit 1\\n"
        "fi\\n"
    )

    async def main():
        return {
            "build_tests": build_tests,
            "run_tests": run_tests,
            "off": await turn_case(verify=None),
            "pass_first": await turn_case(verify="echo 'success'"),
            "pass_second": await turn_case(verify_cmd_script=script_pass_second, retries=2),
            "all_failed": await turn_case(verify="echo 'fail' >&2; exit 1", retries=2),
            "retries_zero": await turn_case(verify="exit 1", retries=0),
            "stopped_on_deadline": await turn_case(verify="sleep 0.15; exit 1", retries=2, timeout=0.08),
            "delivery_failure": await turn_case(verify="echo ok", reply="Sorry, I cannot fulfill this request"),
        }

    print(json.dumps(asyncio.run(main())))
    """)


def probe() -> dict[str, Any]:
    r = subprocess.run(
        ["uv", "run", "--quiet", "--with", "agent-client-protocol>=0.9,<1.0", "python", "-I", "-c", PROBE,
         str(SCRIPT)], check=False, capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


class TestVerify(unittest.TestCase):
    results: ClassVar[dict[str, Any]] = {}

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.results = probe()

    def test_build_verify_prompt(self):
        b = self.results["build_tests"]
        for k, v in b.items():
            self.assertTrue(v, f"build test failed: {k}")

    def test_run_verify(self):
        r = self.results["run_tests"]
        for k, v in r.items():
            self.assertTrue(v, f"run_verify test failed: {k}")

    def test_verify_off_by_default(self):
        r = self.results["off"]
        self.assertTrue(r["finished"])
        self.assertEqual(len(r["prompts"]), 1)
        self.assertNotIn("verify", r["out"])
        self.assertNotIn("verify_attempts", r["out"])

    def test_verify_pass_first_try(self):
        r = self.results["pass_first"]
        self.assertTrue(r["finished"])
        self.assertEqual(len(r["prompts"]), 1)
        self.assertEqual(r["out"].get("verify"), "pass")
        self.assertEqual(r["out"].get("verify_attempts"), 1)

    def test_verify_retry_and_pass(self):
        r = self.results["pass_second"]
        self.assertTrue(r["finished"])
        self.assertEqual(len(r["prompts"]), 2)
        self.assertEqual(r["prompts"][0], "initial prompt")
        self.assertIn("The check ", r["prompts"][1])
        self.assertIn("failed (exit 1)", r["prompts"][1])
        self.assertIn("check failed on first try", r["prompts"][1])
        self.assertEqual(r["out"].get("verify"), "pass")
        self.assertEqual(r["out"].get("verify_attempts"), 2)

    def test_verify_all_failed_preserves_exit_0(self):
        r = self.results["all_failed"]
        self.assertTrue(r["finished"])
        # Initial prompt + 2 retries = 3 prompts sent
        self.assertEqual(len(r["prompts"]), 3)
        self.assertEqual(r["out"].get("verify"), "fail")
        self.assertEqual(r["out"].get("verify_attempts"), 3)
        self.assertIsNone(r["code"], "failed verification does not change turn exit code")

    def test_verify_retries_zero(self):
        r = self.results["retries_zero"]
        self.assertTrue(r["finished"])
        self.assertEqual(len(r["prompts"]), 1)
        self.assertEqual(r["out"].get("verify"), "fail")
        self.assertEqual(r["out"].get("verify_attempts"), 1)

    def test_verify_stopped_when_deadline_passed(self):
        r = self.results["stopped_on_deadline"]
        # timeout=-1 means time.monotonic() >= deadline immediately after initial prompt
        self.assertEqual(len(r["prompts"]), 1)
        self.assertEqual(r["out"].get("verify"), "fail")
        self.assertEqual(r["out"].get("verify_attempts"), 1)

    def test_verify_not_run_on_delivery_check_failure(self):
        r = self.results["delivery_failure"]
        self.assertEqual(len(r["prompts"]), 1)
        self.assertEqual(r["out"].get("verify"), "fail")
        self.assertEqual(r["out"].get("verify_attempts"), 0)

    def test_cli_flags(self):
        p = subprocess.run([str(SCRIPT), "--help"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        self.assertIn("--verify CMD", p.stdout)
        self.assertIn("--verify-retries N", p.stdout)
        self.assertIn("--verify-timeout SECS", p.stdout)

        p_bad = subprocess.run([str(SCRIPT), "crush", "-p", "hi", "--verify", "true", "--verify-retries", "-1"],
                               capture_output=True, text=True)
        self.assertNotEqual(p_bad.returncode, 0)
        self.assertIn("--verify-retries must be 0 or more", p_bad.stderr)

        p_bad_to = subprocess.run([str(SCRIPT), "crush", "-p", "hi", "--verify", "true", "--verify-timeout", "0"],
                                  capture_output=True, text=True)
        self.assertNotEqual(p_bad_to.returncode, 0)
        self.assertIn("--verify-timeout must be positive", p_bad_to.stderr)


if __name__ == "__main__":
    unittest.main()
