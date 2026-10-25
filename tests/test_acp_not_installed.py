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
    """Codex 4322594869 (PR 18): YOLO_CMD['crush'] starts with `env NAME=VAL ... crush-acp`, so
    shutil.which(cmd[0]) found /usr/bin/env and crush skipped the binary wait and the exit-127 path."""

    def acp(self, *args: str, wait: str = "0.5") -> subprocess.CompletedProcess[str]:
        # PATH has env (/usr/bin) but never crush-acp
        env = {**os.environ, "PATH": "/usr/bin:/bin", "ACP_RUN_BIN_WAIT": wait, "ACP_RUN_BIN_POLL": "0.1"}
        return subprocess.run([UV, "run", "--quiet", "--script", str(ACP_RUN), *args], env=env, check=False,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)

    def test_crush_with_no_crush_acp_waits_then_exits_127(self):
        r = self.acp("crush", "-p", "hi", "--timeout", "5", "--perm", "all")
        self.assertEqual(r.returncode, 127, r.stderr)
        self.assertIn("crush-acp not found on PATH; waiting up to 0.5 s", r.stderr)
        self.assertIn("acp-run: crush-acp not installed", r.stderr)

    def test_crush_with_the_wait_disabled_is_still_not_installed(self):
        r = self.acp("crush", "-p", "hi", "--timeout", "5", "--perm", "all", wait="0")
        self.assertEqual(r.returncode, 127, r.stderr)
        self.assertNotIn("waiting", r.stderr)
        self.assertIn("acp-run: crush-acp not installed", r.stderr)

    def test_list_marks_crush_missing_when_only_env_is_on_path(self):
        r = self.acp("--list")
        self.assertEqual(r.returncode, 0, r.stderr)
        crush = [ln for ln in r.stdout.splitlines() if ln[3:].startswith("crush ")]
        self.assertEqual(len(crush), 1, r.stdout)
        self.assertTrue(crush[0].startswith("-- "), crush[0])

    def test_the_executable_skips_env_and_its_assignments(self):
        import ast
        tree = ast.parse(ACP_RUN.read_text())
        fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "agent_executable"]
        self.assertEqual(len(fn), 1)
        ns: dict = {"os": os}
        exec(compile(ast.Module(fn, []), str(ACP_RUN), "exec"), ns)     # noqa: S102 - the repo's own file
        exe = ns["agent_executable"]
        self.assertEqual(exe(["env", "A=1", "B=x=y", "crush-acp", "acp", "--yolo"]), "crush-acp")
        self.assertEqual(exe(["env", "crush-acp"]), "crush-acp")
        self.assertEqual(exe(["claude-agent-acp"]), "claude-agent-acp")
        self.assertEqual(exe(["codex-acp", "A=1"]), "codex-acp")        # only env's own assignments are skipped
        self.assertEqual(exe(["env"]), "env")


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
        # 30 s of waiting, then bin_settle's up to 10 polls of the default 2 s, then 10 s of margin
        self.assertEqual(seen["timeout"], mod["PREFLIGHT_TIMEOUT"] + 30 + 10 * 2 + 10)
        self.assertEqual(seen["env"]["ACP_RUN_BIN_WAIT"], "30")
        self.assertEqual(seen["env"]["ACP_RUN_BIN_POLL"], "2")

    def probe_timeout(self, **env: str) -> float:
        seen: dict = {}
        self.pf_runs = getattr(self, "pf_runs", 0) + 1       # a fresh state dir: an ok probe is cached

        def fake_run(cmd, **kw):
            seen.update(kw)
            return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")
        with unittest.mock.patch.dict(os.environ, {"ACP_DISPATCH_PREFLIGHT": str(self.tmp / f"pf{self.pf_runs}"), **env}):
            mod = runpy.run_path(str(SCRIPT))
            with unittest.mock.patch("subprocess.run", fake_run):
                _ = mod["preflight"]("acp-run", "codex", "m1")
        return seen["timeout"] - mod["PREFLIGHT_TIMEOUT"]

    def test_probe_timeout_covers_bin_settle(self):
        # adversary PR 18 follow-up C: settle polls ACP_RUN_BIN_POLL up to 10 times after the binary appears
        self.assertEqual(self.probe_timeout(ACP_RUN_BIN_WAIT="30", ACP_RUN_BIN_POLL="5"), 30 + 50 + 10)
        self.assertEqual(self.probe_timeout(ACP_RUN_BIN_WAIT="30", ACP_RUN_BIN_POLL="999"), 30 + 300 + 10)  # clamped to 30
        self.assertEqual(self.probe_timeout(ACP_RUN_BIN_WAIT="30", ACP_RUN_BIN_POLL="0"), 30 + 0.5 + 10)    # clamped to 0.05
        self.assertEqual(self.probe_timeout(ACP_RUN_BIN_WAIT="0", ACP_RUN_BIN_POLL="5"), 10)                # no wait, no settle

    def test_default_and_junk_waits(self):
        fn = runpy.run_path(str(SCRIPT))["bin_wait_seconds"]
        cases = {None: 90.0, "abc": 90.0, "nan": 90.0, "inf": 90.0, "-5": 0.0, "0": 0.0, "12.5": 12.5, "9999": 600.0}
        for value, want in cases.items():
            env = {} if value is None else {"ACP_RUN_BIN_WAIT": value}
            with unittest.mock.patch.dict(os.environ, env, clear=False):
                if value is None:
                    os.environ.pop("ACP_RUN_BIN_WAIT", None)
                self.assertEqual(fn(), want, value)

    def test_default_and_junk_polls_mirror_acp_run(self):
        mod = runpy.run_path(str(SCRIPT))
        acp = acp_run_bin_settings()
        for value in (None, "abc", "nan", "inf", "-inf", "", "-5", "0", "0.01", "0.05", "1.5", "30", "31", "1e9"):
            env = {} if value is None else {"ACP_RUN_BIN_POLL": value}
            with unittest.mock.patch.dict(os.environ, env, clear=False):
                if value is None:
                    os.environ.pop("ACP_RUN_BIN_POLL", None)
                self.assertEqual(mod["bin_poll_seconds"](), acp["bin_wait_settings"]()[1], value)
        for value in ("abc", "nan", "inf", "-5", "0", "12.5", "9999", ""):
            with unittest.mock.patch.dict(os.environ, {"ACP_RUN_BIN_WAIT": value}, clear=False):
                self.assertEqual(mod["bin_wait_seconds"](), acp["bin_wait_settings"]()[0], value)


class TestPreflightRemembersANotInstalledAgent(Base):
    """adversary PR 18 follow-up D: acp-run waits 90 s for a missing binary, so a wave of dispatches to an
    agent that is not installed must pay that once, not once each (nor hold the pool's flock that long)."""

    MISSING = "acp-run: claude-agent-acp not installed\n"

    def run_preflight(self, results: list, **env: str):
        calls: list = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            rc, out, err = results[min(len(calls), len(results)) - 1]
            return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr=err)
        with unittest.mock.patch.dict(os.environ, {"ACP_DISPATCH_PREFLIGHT": str(self.tmp / "pf"), **env}):
            mod = runpy.run_path(str(SCRIPT))
            with unittest.mock.patch("subprocess.run", fake_run), \
                    unittest.mock.patch.dict(mod["preflight"].__globals__, {"note_outage_in_aiuse": lambda *a: "off"}):
                first = mod["preflight"]("acp-run", "claude", "m1")
                second = mod["preflight"]("acp-run", "claude", "m1")
                state = mod["not_installed_state"]("claude")
                ttl = mod["NOT_INSTALLED_TTL"]
                # age the negative entry past its TTL: the next dispatch probes again
                rec = json.loads(state.read_text()) if state.exists() else None
                if rec:
                    rec["time"] -= ttl + 1
                    _ = state.write_text(json.dumps(rec))
                third = mod["preflight"]("acp-run", "claude", "m1")
        return calls, first, second, third, ttl

    def test_a_second_dispatch_does_not_probe_again_until_the_ttl(self):
        calls, first, second, third, ttl = self.run_preflight([(127, "", self.MISSING)])
        self.assertFalse(first[0])
        self.assertEqual(first[2], "not-installed")
        self.assertEqual(second[0], False)
        self.assertEqual(second[2], "not-installed")
        self.assertIn("claude-agent-acp not installed", second[1])
        self.assertIn("retry after", second[1])
        self.assertEqual(len(calls), 2, calls)          # probe 1, (cached), probe 3 after the TTL
        self.assertEqual(ttl, 120)

    def test_another_model_of_the_same_agent_reuses_the_negative_result(self):
        # Codex 4323297404 (PR 22): the record was keyed by (agent, model), so m2 paid the binary wait again;
        # acp-run picks the executable from the agent alone. A different agent still probes.
        calls: list = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 127, stdout="", stderr=self.MISSING)
        with unittest.mock.patch.dict(os.environ, {"ACP_DISPATCH_PREFLIGHT": str(self.tmp / "pf")}):
            mod = runpy.run_path(str(SCRIPT))
            with unittest.mock.patch("subprocess.run", fake_run), \
                    unittest.mock.patch.dict(mod["preflight"].__globals__, {"note_outage_in_aiuse": lambda *a: "off"}):
                first = mod["preflight"]("acp-run", "claude", "m1")
                n_first = len(calls)
                other_model = mod["preflight"]("acp-run", "claude", "m2")
                no_model = mod["preflight"]("acp-run", "claude", None)
                n_same_agent = len(calls)
                other_agent = mod["preflight"]("acp-run", "codex", "m1")
        self.assertEqual(first[2], "not-installed")
        self.assertEqual((other_model[0], other_model[2]), (False, "not-installed"))
        self.assertEqual((no_model[0], no_model[2]), (False, "not-installed"))
        self.assertIn("retry after", other_model[1])
        self.assertEqual(n_same_agent, n_first, calls)      # m2 and the default model never probed
        self.assertEqual(other_agent[2], "not-installed")
        self.assertGreater(len(calls), n_same_agent)         # codex had its own probe

    def test_other_failures_and_successes_are_not_negatively_cached(self):
        calls, first, second, third, _ = self.run_preflight([(1, "", "boom: connection reset\n")])
        self.assertFalse(first[0])
        self.assertNotEqual(first[2], "not-installed")
        self.assertEqual(len(calls), 3, calls)          # every call probed
        calls, first, second, third, _ = self.run_preflight([(0, "OK\n", "")])
        self.assertTrue(first[0])
        self.assertEqual(second[1], "cached")

    def test_an_ok_entry_from_the_future_is_not_trusted(self):
        # PR 22 review: a clock step back or a crafted `time` must not keep `ok` cached forever
        calls: list = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="OK\n", stderr="")
        with unittest.mock.patch.dict(os.environ, {"ACP_DISPATCH_PREFLIGHT": str(self.tmp / "pf")}):
            mod = runpy.run_path(str(SCRIPT))
            with unittest.mock.patch("subprocess.run", fake_run):
                self.assertTrue(mod["preflight"]("acp-run", "claude", "m1")[0])
                state = mod["preflight_state"]("claude", "m1")
                rec = json.loads(state.read_text())
                rec["time"] += 10 ** 6
                _ = state.write_text(json.dumps(rec))
                again = mod["preflight"]("acp-run", "claude", "m1")
        self.assertTrue(again[0])
        self.assertNotEqual(again[1], "cached")
        self.assertEqual(len(calls), 2, calls)


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
