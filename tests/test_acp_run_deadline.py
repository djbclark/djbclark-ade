"""Deadline controls with a fake ACP connection; never starts an agent."""
import ast
import asyncio
import fcntl
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

SCRIPT = Path(__file__).resolve().parents[1] / "tools/acp-run/acp-run"


class TestDeadline(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_still_cancels_and_runs_wrapup(self):
        tree = ast.parse(SCRIPT.read_text())
        tree.body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name in {"prompt_turn", "extend_deadline", "read_deadline_extension"}]
        clock = [100]
        wrapup = AsyncMock()
        ns = {"asyncio": asyncio, "time": SimpleNamespace(monotonic=lambda: clock[0]),
              "TextContentBlock": lambda **kw: kw, "RequestError": RuntimeError,
              "wrapup_turn": wrapup}
        exec(compile(tree, str(SCRIPT), "exec"), ns)  # noqa: S102 - only repository functions
        ended = asyncio.Event()
        async def prompt(**kw):
            await ended.wait()
            return SimpleNamespace(stop_reason="cancelled")
        async def cancel(**kw):
            ended.set()
        async def wait(task, seconds):
            clock[0] += seconds
            raise TimeoutError
        c = SimpleNamespace(tools=0, allowed=0, denied=0, err_path=None, text=[], cancelled=False)
        a = SimpleNamespace(timeout=10, prompt_retries=0, interactive=False, wrapup_grace=5)
        conn = SimpleNamespace(prompt=prompt, cancel=AsyncMock(side_effect=cancel))
        out = {}
        result = await ns["prompt_turn"](a, conn, SimpleNamespace(session_id="s"), c, "hi", out, wait)
        self.assertEqual(result[2], 124)
        self.assertEqual(out["stop_reason"], "cancelled")
        conn.cancel.assert_awaited_once_with(session_id="s")
        wrapup.assert_awaited_once()

    async def test_deadline_control_cases(self):
        tree = ast.parse(SCRIPT.read_text())
        names = {"prompt_turn", "extend_deadline", "read_deadline_extension"}
        tree.body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name in names]
        ns = dict(asyncio=asyncio, time=SimpleNamespace(monotonic=lambda: 100),  # noqa: C408
                  Path=Path, re=re, fcntl=fcntl, sys=SimpleNamespace(stderr=None), os=SimpleNamespace(),
                  TextContentBlock=lambda **kw: kw, dump=lambda x: {},
                  reply_failure=lambda *args: None, RequestError=RuntimeError)
        exec(compile(tree, str(SCRIPT), "exec"), ns)  # noqa: S102 - only repository functions
        for timeout, control, expected in ((0, None, None), (10, "50", 160),
                                            (10, "0", None), (10, "bad", 110),
                                            (10, "-1", 110), (0, "50", None)):
            with self.subTest(timeout=timeout, control=control), tempfile.TemporaryDirectory() as d:
                log = Path(d) / "slice.jsonl"
                ext = Path(str(log) + ".extend")
                if control is not None:
                    ext.write_text(control)
                rows, waits = [], []
                c = SimpleNamespace(log=SimpleNamespace(name=str(log)), rec=lambda k, v, rows=rows: rows.append((k, v)),
                                    tools=0, allowed=0, denied=0, err_path=None, text=[], cancelled=False)
                async def prompt(**kw):
                    return SimpleNamespace(stop_reason="end_turn", field_meta=None, usage=None)
                async def wait(task, seconds, waits=waits):
                    waits.append(seconds)
                    return await task
                a = SimpleNamespace(timeout=timeout, prompt_retries=0, interactive=False, wrapup_grace=300)
                cancel = Mock()
                result = await ns["prompt_turn"](a, SimpleNamespace(prompt=prompt, cancel=cancel),
                                                 SimpleNamespace(session_id="s"), c, "hi", {}, wait)
                self.assertTrue(result[0])
                cancel.assert_not_called()
                self.assertFalse(ext.exists())
                self.assertLessEqual(waits[0], 30)
                if control is not None:
                    event, data = rows[0]
                    if control in ("bad", "-1"):
                        self.assertEqual(event, "deadline_extension_invalid")
                    else:
                        self.assertEqual(event, "deadline_extended")
                        self.assertEqual(data["new_deadline"], expected)

    async def test_extension_arriving_while_waiting_keeps_same_prompt(self):
        tree = ast.parse(SCRIPT.read_text())
        tree.body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name in {"prompt_turn", "extend_deadline", "read_deadline_extension"}]
        clock = [100]
        ns = dict(asyncio=asyncio, time=SimpleNamespace(monotonic=lambda: clock[0]), Path=Path,  # noqa: C408
                  re=re, fcntl=fcntl, sys=SimpleNamespace(stderr=None), TextContentBlock=lambda **kw: kw,
                  dump=lambda x: {}, reply_failure=lambda *args: None, RequestError=RuntimeError)
        exec(compile(tree, str(SCRIPT), "exec"), ns)  # noqa: S102 - only repository functions
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "slice.jsonl"
            c = SimpleNamespace(log=SimpleNamespace(name=str(log)), rec=Mock(), tools=0,
                                allowed=0, denied=0, err_path=None, text=[], cancelled=False)
            calls, waits = [], []
            async def prompt(**kw):
                calls.append(kw)
                return SimpleNamespace(stop_reason="end_turn", field_meta=None, usage=None)
            async def wait(task, seconds):
                waits.append(seconds)
                if len(waits) == 1:
                    clock[0] = 110
                    Path(str(log) + ".extend").write_text("60")
                    raise TimeoutError
                return await task
            a = SimpleNamespace(timeout=10, prompt_retries=0, interactive=False, wrapup_grace=0)
            result = await ns["prompt_turn"](a, SimpleNamespace(prompt=prompt, cancel=Mock()),
                                             SimpleNamespace(session_id="s"), c, "hi", {}, wait)
            self.assertTrue(result[0])
            self.assertEqual(len(calls), 1)
            self.assertEqual(waits, [10, 30])


class TestGoAdvisoryDeadlineIsFixed(unittest.IsolatedAsyncioTestCase):
    """A costly Go advisory turn (a.go_bounded) never gets a longer deadline, whatever the control file says."""

    def load(self, clock):
        tree = ast.parse(SCRIPT.read_text())
        tree.body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name in {"prompt_turn", "extend_deadline", "read_deadline_extension"}]
        ns = dict(asyncio=asyncio, time=SimpleNamespace(monotonic=lambda: clock[0]), Path=Path,  # noqa: C408
                  re=re, fcntl=fcntl, sys=SimpleNamespace(stderr=None), TextContentBlock=lambda **kw: kw,
                  dump=lambda x: {}, reply_failure=lambda *args: None, RequestError=RuntimeError)
        exec(compile(tree, str(SCRIPT), "exec"), ns)  # noqa: S102 - only repository functions
        return ns

    async def run_turn(self, bounded, control_values, timeout=600):
        """The prompt never ends; each poll tick advances the fake clock 30 s and may write a control file.
        Returns (result, out, rows, clock time when the turn ended)."""
        clock = [1000.0]
        ns = self.load(clock)
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "slice.jsonl"
            ext = Path(str(log) + ".extend")
            rows, ticks = [], [0]
            ended = asyncio.Event()
            async def prompt(**kw):
                await ended.wait()
                return SimpleNamespace(stop_reason="cancelled", field_meta=None, usage=None)
            async def cancel(**kw):
                ended.set()
            async def wait(task, seconds):
                clock[0] += seconds
                ticks[0] += 1
                if ticks[0] in control_values:
                    ext.write_text(control_values[ticks[0]])  # a dispatcher extend, or a hand edit
                raise TimeoutError
            c = SimpleNamespace(log=SimpleNamespace(name=str(log)), rec=lambda k, v: rows.append((k, v)),
                                tools=0, allowed=0, denied=0, err_path=None, text=[], cancelled=False)
            a = SimpleNamespace(timeout=timeout, prompt_retries=0, interactive=False, wrapup_grace=0,
                                go_bounded=bounded)
            conn = SimpleNamespace(prompt=prompt, cancel=AsyncMock(side_effect=cancel))
            out = {}
            with patch_stderr():
                result = await ns["prompt_turn"](a, conn, SimpleNamespace(session_id="s"), c, "hi", out, wait)
            return result, out, rows, clock[0], ext.exists()

    async def test_costly_go_advisory_times_out_at_the_original_deadline(self):
        # polling is min(30, left): 1 s ticks under deny, but the fake agent here is not deny, so 30 s.
        for label, controls in (("zero", {2: "0"}), ("positive", {2: "600"}), ("repeated", {2: "600", 5: "600", 9: "1"}),
                                ("garbage", {2: "junk"})):
            with self.subTest(label):
                result, out, rows, end, left_over = await self.run_turn(True, controls)
                self.assertEqual(result[2], 124)
                self.assertEqual(end, 1000.0 + 600, "original start + admitted timeout, never later")
                self.assertFalse(left_over, "the control file is consumed, not left to re-apply")
                kinds = [k for k, _ in rows]
                self.assertNotIn("deadline_extended", kinds)

    async def test_refusal_is_logged_for_valid_values(self):
        _, _, rows, _, _ = await self.run_turn(True, {2: "600"})
        refused = [v for k, v in rows if k == "deadline_extension_refused"]
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0]["deadline"], 1600.0)

    async def test_ordinary_turn_still_extends_and_unlimited_still_works(self):
        result, _, rows, end, _ = await self.run_turn(False, {2: "60"}, timeout=120)
        self.assertEqual(result[2], 124)
        self.assertEqual(end, 1000.0 + 120 + 60 + 0, "ordinary extension keeps adding to the deadline")
        self.assertIn("deadline_extended", [k for k, _ in rows])
        clock = [0.0]
        ns = self.load(clock)
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "s.jsonl"
            Path(str(log) + ".extend").write_text("0")
            c = SimpleNamespace(log=SimpleNamespace(name=str(log)), rec=Mock())
            self.assertIsNone(ns["extend_deadline"](c, 50.0))


def patch_stderr():
    import contextlib
    import io
    return contextlib.redirect_stderr(io.StringIO())
