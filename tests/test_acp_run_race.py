#!/usr/bin/env python3
"""acp-run fixes from the 2026-10-13 SkillOpt-Sleep night; never starts an agent.

1. The end_turn/124 race: prompt_turn polls the prompt with wait_for(shield(task)) every 1 s
   (30 s without --perm deny). When the prompt finished on the same tick the poll timed out,
   the task was done and the code re-raised the poll's TimeoutError, so acp-run exited 124 with
   stop_reason=end_turn and threw the answer away (acp-logs 20261013-034908-opencode-009ed689 and
   20261013-035429-opencode-37d148b4). These cases load prompt_turn / wrapup_turn alone from the
   script, as test_acp_run_deadline.py does.
2. The handshake retry: only a TimeoutError was retried, so opencode's transient
   ServiceUnavailableError at session/new ("Location plugins did not finish activating") failed the
   run at once, and the timeout message always said "session/new hung", even when initialize never
   answered. These cases drive run() against a fake agent; acp-run imports the ACP SDK, so that part
   is loaded in a `uv run --with` subprocess.
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import subprocess
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar, override
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("ACP_RUN_SCRIPT", str(ROOT / "tools" / "acp-run" / "acp-run")))
WITH = ["uv", "run", "--quiet", "--with", "agent-client-protocol>=0.9,<1.0", "python", "-I"]


class RequestError(Exception):  # stands in for acp.RequestError in the extracted functions
    pass


def load(*names, **extra):
    """The named top-level functions of acp-run, exec'd into a namespace of fakes."""
    tree = ast.parse(SCRIPT.read_text())
    tree.body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name in names]
    ns = {"asyncio": asyncio, "time": SimpleNamespace(monotonic=lambda: 100), "Path": Path,
          "TextContentBlock": lambda **kw: kw, "RequestError": RequestError,
          "dump": lambda x: {}, "reply_failure": lambda *args: None,
          "error_text": lambda e: f"{type(e).__name__}: {e}", "retryable_error": lambda e: False,
          **extra}
    exec(compile(tree, str(SCRIPT), "exec"), ns)  # noqa: S102 - only repository functions
    return ns


def client():
    rows = []
    return SimpleNamespace(tools=0, allowed=0, denied=0, err_path=None, text=[], cancelled=False,
                           log=SimpleNamespace(name="/nonexistent/slice.jsonl"),
                           rec=lambda k, v: rows.append((k, v)), rows=rows)


async def same_tick(task, seconds):
    """The poll's timeout fires on the tick the prompt finishes: the task is done, wait raises."""
    try:
        await task
    except BaseException:  # noqa: BLE001, S110 - the caller reads the task's own outcome
        pass
    raise TimeoutError


class TestEndTurnRace(unittest.IsolatedAsyncioTestCase):
    async def run_turn(self, prompt, *, perm="deny", wrapup=None):
        ns = load("prompt_turn", "extend_deadline", "read_deadline_extension",
                  wrapup_turn=wrapup or AsyncMock())
        c = client()
        out = {}
        conn = SimpleNamespace(prompt=prompt, cancel=AsyncMock())
        a = SimpleNamespace(timeout=600, prompt_retries=0, interactive=False, wrapup_grace=0, perm=perm)
        result = await ns["prompt_turn"](a, conn, SimpleNamespace(session_id="s"), c, "hi", out, same_tick)
        return result, out, conn, c

    async def test_answer_finished_on_the_poll_timeout_tick_is_kept(self):
        for perm in ("deny", "all"):  # 1 s polls under --perm deny, 30 s otherwise
            with self.subTest(perm=perm):
                async def prompt(**kw):
                    return SimpleNamespace(stop_reason="end_turn", field_meta=None, usage=None)
                (finished, failure, code), out, conn, c = await self.run_turn(prompt, perm=perm)
                self.assertTrue(finished)
                self.assertIsNone(failure)
                self.assertIsNone(code)  # was 124 before the fix
                self.assertEqual(out["stop_reason"], "end_turn")
                conn.cancel.assert_not_called()
                self.assertEqual(c.rows[0][0], "prompt_response")

    async def test_error_finished_on_the_tick_is_the_prompts_own_error(self):
        async def prompt(**kw):
            raise RequestError("Internal error")
        with self.assertRaises(RequestError):  # not a 124 timeout
            await self.run_turn(prompt)

    async def test_adapter_timeout_is_still_a_timeout(self):
        async def prompt(**kw):
            raise TimeoutError
        (finished, _failure, code), out, conn, _c = await self.run_turn(prompt)
        self.assertFalse(finished)
        self.assertEqual(code, 124)
        self.assertEqual(out["stop_reason"], "timeout")
        conn.cancel.assert_awaited_once_with(session_id="s")

    async def test_pending_prompt_keeps_polling_until_it_answers(self):
        ticks = []
        ns = load("prompt_turn", "extend_deadline", "read_deadline_extension", wrapup_turn=AsyncMock())
        ended = asyncio.Event()
        async def prompt(**kw):
            await ended.wait()
            return SimpleNamespace(stop_reason="end_turn", field_meta=None, usage=None)
        async def wait(task, seconds):
            ticks.append(seconds)
            if len(ticks) < 3:
                raise TimeoutError  # an ordinary polling tick: the prompt is still running
            ended.set()
            return await task
        a = SimpleNamespace(timeout=600, prompt_retries=0, interactive=False, wrapup_grace=0, perm="deny")
        out = {}
        conn = SimpleNamespace(prompt=prompt, cancel=AsyncMock())
        finished, _f, code = await ns["prompt_turn"](a, conn, SimpleNamespace(session_id="s"),
                                                     client(), "hi", out, wait)
        self.assertEqual((finished, code, len(ticks)), (True, None, 3))
        self.assertEqual(ticks[0], 1)
        conn.cancel.assert_not_called()

    async def test_wrapup_finished_on_the_grace_timeout_tick_keeps_its_stop_reason(self):
        async def wait_for(fut, secs):
            await fut
            raise TimeoutError
        fake = SimpleNamespace(ensure_future=asyncio.ensure_future, shield=asyncio.shield, wait_for=wait_for)
        ns = load("wrapup_turn", asyncio=fake, WRAPUP_DEFAULT="time is up")
        async def prompt(**kw):
            return SimpleNamespace(stop_reason="end_turn")
        c = client()
        out = {"stop_reason": "cancelled"}
        conn = SimpleNamespace(prompt=prompt, cancel=AsyncMock())
        a = SimpleNamespace(wrapup=None, wrapup_grace=5)
        await ns["wrapup_turn"](a, conn, SimpleNamespace(session_id="s"), c, out)
        self.assertEqual(out["wrapup"], "end_turn")  # was "timeout"
        conn.cancel.assert_not_called()


PROBE = textwrap.dedent("""\
    import asyncio, contextlib, importlib.machinery, importlib.util, io, json, sys, tempfile
    from pathlib import Path
    from types import SimpleNamespace
    loader = importlib.machinery.SourceFileLoader("acp_run", sys.argv[1])
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("acp_run", loader))
    loader.exec_module(mod)
    from acp import RequestError

    def svc():  # opencode 2.0.27, acp-logs 20261013-043610-opencode-c999a2e6
        return RequestError(-32603, "Internal error: Internal service failure",
                            {"errorName": "ServiceUnavailableError"})
    ERRORS = {
        "svc": svc,
        "plugins": lambda: RequestError(-32603, "ServiceUnavailableError: Location plugins did not"
                                        " finish activating"),
        "invalid": lambda: RequestError.invalid_params({"cwd": "not absolute"}),
        "auth": lambda: RequestError(-32000, "Authentication required"),
        "quota": lambda: RequestError(-32603, "Internal error: quota exceeded"),
    }
    INIT = SimpleNamespace(agent_capabilities=None, agent_info={"name": "fake"}, auth_methods=[])
    SESS = SimpleNamespace(session_id="s1", modes=None, config_options=None)

    async def act(step, value):
        if step == "hang":
            await asyncio.Event().wait()  # until wait_for gives up
        if step in ERRORS:
            raise ERRORS[step]()
        return value

    class Conn:
        def __init__(self, plan):
            self.plan = plan
        async def initialize(self, **kw):
            return await act(self.plan.get("initialize"), INIT)
        async def authenticate(self, **kw):
            return None
        async def new_session(self, **kw):
            return await act(self.plan.get("session/new"), SESS)

    async def case(plans, tries):
        spawns, sleeps = [], []
        async def fake_exec(*cmd, **kw):
            spawns.append(cmd)
            return SimpleNamespace(stdin=None, stdout=None, returncode=0)
        async def fake_sleep(delay, *rest):
            sleeps.append(delay)
        mod.asyncio.create_subprocess_exec = fake_exec
        mod.asyncio.sleep = fake_sleep
        mod.connect_to_agent = lambda client, i, o: Conn(plans[len(spawns) - 1])
        with tempfile.TemporaryDirectory() as d:
            a = SimpleNamespace(agent="opencode", auth=None, perm="deny", mode=None, dir=d,
                                prompt_text=None, interactive=False, show_thinking=False,
                                handshake_timeout=0.05, handshake_tries=tries,
                                tripwire_exempt_kinds="", info=True, no_fallback=True, resume=None,
                                add_dir=[], set=[], model=None, json=False, verify=None)
            log_path = Path(d) / "run.jsonl"
            so, se = io.StringIO(), io.StringIO()
            with open(log_path, "w") as log, open(Path(d) / "run.stderr", "w") as err, \\
                    contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
                rc = await mod.run(a, log, err, log_path)
            rows = [json.loads(ln) for ln in log_path.read_text().splitlines()]
        return {"rc": rc, "spawns": len(spawns), "sleeps": sleeps, "stderr": se.getvalue(),
                "rows": [[r["kind"], r["data"]] for r in rows]}

    CASES = {
        "svc_then_ok": ([{"session/new": "svc"}, {}], 2),
        "svc_every_try": ([{"session/new": "svc"}] * 3, 3),
        "plugins_in_initialize_then_ok": ([{"initialize": "plugins"}, {}], 2),
        "invalid": ([{"session/new": "invalid"}, {}], 2),
        "auth": ([{"session/new": "auth"}, {}], 2),
        "quota": ([{"session/new": "quota"}, {}], 2),
        "initialize_hangs": ([{"initialize": "hang"}] * 2, 2),
        "session_new_hangs": ([{"session/new": "hang"}] * 2, 2),
        "init_then_session_new_hang": ([{"initialize": "hang"}, {"session/new": "hang"}], 2),
        "svc_then_hang": ([{"session/new": "svc"}, {"session/new": "hang"}], 2),
    }
    classes = {k: mod.classify(mod.error_text(f())) for k, f in ERRORS.items()}
    results = {name: asyncio.run(case(plans, tries)) for name, (plans, tries) in CASES.items()}
    print(json.dumps({"classes": classes, "cases": results}, default=str))
    """)


class TestHandshakeRetry(unittest.TestCase):
    res: ClassVar[dict]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        r = subprocess.run([*WITH, "-c", PROBE, str(SCRIPT)], check=False, capture_output=True,
                           text=True, timeout=300)
        if r.returncode != 0:
            raise AssertionError(r.stderr)
        cls.res = json.loads(r.stdout)

    def case(self, name):
        return self.res["cases"][name]

    def kinds(self, name):
        return [k for k, _ in self.case(name)["rows"]]

    def result(self, name):
        return next(d for k, d in self.case(name)["rows"] if k == "result")

    def test_service_unavailable_is_transient(self):
        self.assertEqual(self.res["classes"]["svc"], "transient")
        self.assertEqual(self.res["classes"]["plugins"], "transient")
        self.assertIsNone(self.res["classes"]["invalid"])
        self.assertEqual(self.res["classes"]["auth"], "auth")
        self.assertEqual(self.res["classes"]["quota"], "quota")

    def test_transient_session_new_error_retries_in_a_fresh_agent(self):
        c = self.case("svc_then_ok")
        self.assertEqual((c["rc"], c["spawns"], c["sleeps"]), (0, 2, [1.0]))
        retry = next(d for k, d in c["rows"] if k == "handshake_retry")
        self.assertEqual((retry["attempt"], retry["tries"], retry["phase"]), (1, 2, "session/new"))
        self.assertIn("ServiceUnavailableError", retry["why"])
        self.assertIn("handshake session/new failed, attempt 1/2; retry in 1s", c["stderr"])
        self.assertEqual(self.kinds("svc_then_ok")[-2:], ["initialize", "new_session"])

    def test_transient_initialize_error_is_retried_and_named(self):
        c = self.case("plugins_in_initialize_then_ok")
        self.assertEqual((c["rc"], c["spawns"]), (0, 2))
        retry = next(d for k, d in c["rows"] if k == "handshake_retry")
        self.assertEqual(retry["phase"], "initialize")

    def test_backoff_and_the_last_error_when_every_try_fails(self):
        c = self.case("svc_every_try")
        self.assertEqual((c["rc"], c["spawns"], c["sleeps"]), (1, 3, [1.0, 2.0]))
        res = self.result("svc_every_try")
        self.assertEqual(res["failure"], "transient")
        self.assertIn("ServiceUnavailableError", res["error"])
        self.assertEqual(res["turns"], 0)

    def test_non_transient_errors_are_not_retried(self):
        for name, failure in (("invalid", None), ("auth", "auth"), ("quota", "quota")):
            with self.subTest(name=name):
                c = self.case(name)
                self.assertEqual((c["rc"], c["spawns"], c["sleeps"]), (1, 1, []))
                self.assertNotIn("handshake_retry", self.kinds(name))
                self.assertEqual(self.result(name).get("failure"), failure)

    def test_timeout_message_names_the_phase_that_hung(self):
        for name, phases in (("initialize_hangs", "initialize hung"),
                             ("session_new_hangs", "session/new hung"),
                             ("init_then_session_new_hang", "initialize, session/new hung")):
            with self.subTest(name=name):
                c = self.case(name)
                self.assertEqual((c["rc"], c["spawns"]), (124, 2))
                err = self.result(name)["error"]
                self.assertEqual(err, f"TimeoutError: handshake after 2 tries of 0.05s ({phases})")
                timeouts = [d for k, d in c["rows"] if k == "handshake_timeout"]
                self.assertEqual(len(timeouts), 2)
        self.assertIn("initialize hung) attempt 1/2", self.case("initialize_hangs")["stderr"])
        self.assertNotIn("session/new", self.result("initialize_hangs")["error"])

    def test_a_transient_try_then_a_hang_says_both(self):
        c = self.case("svc_then_hang")
        self.assertEqual((c["rc"], c["spawns"], c["sleeps"]), (124, 2, [1.0]))
        self.assertEqual(self.result("svc_then_hang")["error"],
                         "TimeoutError: handshake after 2 tries of 0.05s (session/new hung);"
                         " 1 failed transiently")


if __name__ == "__main__":
    unittest.main()
