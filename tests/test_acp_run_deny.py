#!/usr/bin/env python3
"""Tests for tools/acp-run/acp-run's real --perm deny (adversary review 2026-10-12, C1).

`--perm deny` used to answer only permission requests, and four agents never sent any:
claude-agent-acp inherited settings.json's bypassPermissions, zcode-acp-server started in
yolo, crush-acp ran with --yolo and opencode allowed tools by default. Now under deny
acp-run sets the strictest mode per agent, passes deny env and session/new _meta, drops
crush's --yolo, and trips (exit 77) when a non-think tool starts or completes without a
permission request. acp-run imports the ACP SDK, so it is loaded in a `uv run --with`
subprocess and driven against fakes.
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
    import asyncio, importlib.machinery, importlib.util, io, json, subprocess, sys
    from types import SimpleNamespace as NS
    loader = importlib.machinery.SourceFileLoader("acp_run", sys.argv[1])
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("acp_run", loader))
    loader.exec_module(mod)
    REAL_WAIT_FOR = asyncio.wait_for

    def upd(kind, tid, status=None, tkind=None, title="Bash"):
        return NS(session_update=kind, tool_call_id=tid, status=status, kind=tkind, title=title)

    class FakeConn:
        # script: list of ("update", obj) | ("perm", tid) | ("sleep", s) steps run inside the
        # prompt; then the turn ends end_turn with `reply`, or waits for session/cancel.
        def __init__(self, client, script, reply="answer", wait_cancel=False):
            self.client, self.script, self.reply, self.wait_cancel = client, script, reply, wait_cancel
            self.cancels, self.ev = 0, asyncio.Event()

        async def prompt(self, session_id, prompt):
            for step, arg in self.script:
                if step == "update":
                    await self.client.session_update("s", arg)
                elif step == "perm":
                    tc = NS(tool_call_id=arg, kind="execute", title="Bash", locations=[])
                    opts = [NS(kind="allow_once", option_id="a"), NS(kind="reject_once", option_id="r")]
                    await self.client.request_permission("s", tc, opts)
                elif step == "sleep":
                    await asyncio.sleep(arg)
            if self.wait_cancel:
                await self.ev.wait()
                return NS(stop_reason="cancelled", field_meta=None, usage=None)
            self.client.text.append(self.reply)
            return NS(stop_reason="end_turn", field_meta=None, usage=None)

        async def cancel(self, session_id):
            self.cancels += 1
            self.ev.set()

    async def turn(perm, script, exempt=(), **kw):
        client = mod.RunClient(io.StringIO(), perm, ".")
        client.exempt_kinds = frozenset(exempt)
        conn = FakeConn(client, script, **kw)
        a = NS(timeout=10, prompt_retries=0, interactive=False, wrapup_grace=0, wrapup=None, perm=perm)
        out = {}
        async def short(aw, t):
            return await REAL_WAIT_FOR(aw, min(t, 0.5))
        mod.asyncio.wait_for = short
        try:
            finished, failure, code = await mod.prompt_turn(a, conn, NS(session_id="s"), client, "q", out)
        finally:
            mod.asyncio.wait_for = REAL_WAIT_FOR
        return {"code": code, "finished": finished, "failure": failure, "out": out,
                "cancels": conn.cancels, "tripped": client.tripped}

    async def sessions():
        got = {}
        class C:
            async def new_session(self, **kw):
                got.setdefault(kw.get("cwd"), []).append(kw)
                return NS(session_id="s")
        init = NS(agent_capabilities=None)
        for agent, perm in (("claude", "deny"), ("claude", "all"), ("opencode", "deny")):
            a = NS(add_dir=[], resume=None, perm=perm, agent=agent)
            await mod.open_session(a, C(), init, mod.RunClient(io.StringIO(), perm, "."), "/" + agent + perm, 5)
        return {k: [sorted(x) for x in v] for k, v in got.items()} | {
            "claude_meta": got["/claudedeny"][0].get("claudeCode")}

    def fallback(perm):
        seen = {}
        real = subprocess.run
        def fake(cmd, **kw):
            seen.update(cmd=cmd, input=kw.get("input"))
            return NS(returncode=0)
        mod.subprocess.run = fake
        try:
            a = NS(agent="claude", model="haiku", perm=perm, dir=".", prompt_text="SECRET PROMPT")
            mod.fallback_cli(a)
        finally:
            mod.subprocess.run = real
        return seen

    def zcode_settings():
        import os, shutil, tempfile
        from pathlib import Path
        home = Path(tempfile.mkdtemp())
        (home / ".zcode" / "cli").mkdir(parents=True)
        (home / ".zcode" / "cli" / "setting.json").write_text(json.dumps({
            "permission": {"mode": "yolo", "autoApproveHighRisk": True},
            "features": {"mcp": True, "subagent": True, "skill": True},
            "mcp": {"servers": {"basic-memory": {"command": "x"}}},
            "plugins": {"enabled": True, "enabledPlugins": {"p@m": True}},
            "hooks": {"enabled": True, "events": {"Stop": [{"command": "x"}]}},
            "storage": {"dir": "~/.zcode"}}))
        old = os.environ.get("HOME")
        os.environ["HOME"] = str(home)
        try:
            d = mod.zcode_deny_settings()
        finally:
            os.environ["HOME"] = old
        out = {"settings": json.loads((d / "cli" / "setting.json").read_text()),
               "config": json.loads((d / "cli" / "config.json").read_text()),
               "mode": oct((d.stat().st_mode) & 0o777)}
        shutil.rmtree(d)
        shutil.rmtree(home)
        return out

    async def main():
        return {
            "zcode_settings": zcode_settings(),
            "trip_running": await turn("deny", [("update", upd("tool_call", "t1", "in_progress", "execute"))],
                                      wait_cancel=True),
            "trip_last_update": await turn("deny", [("update", upd("tool_call", "t1", "pending", "read")),
                                                   ("update", upd("tool_call_update", "t1", "completed"))]),
            "asked_then_denied": await turn("deny", [("update", upd("tool_call", "t1", "pending", "execute")),
                                                    ("perm", "t1"),
                                                    ("update", upd("tool_call_update", "t1", "failed"))]),
            "think_ok": await turn("deny", [("update", upd("tool_call", "t1", "completed", "think"))]),
            # --tripwire-exempt-kinds read (agy): an unasked read runs, an unasked execute still trips
            "exempt_read": await turn("deny", [("update", upd("tool_call", "t1", "in_progress", "read")),
                                              ("update", upd("tool_call_update", "t1", "completed"))],
                                      exempt=("read",)),
            "exempt_exec": await turn("deny", [("update", upd("tool_call", "t1", "completed", "execute"))],
                                      exempt=("read",)),
            "no_exempt_read": await turn("deny", [("update", upd("tool_call", "t1", "completed", "read"))]),
            # crush-acp: in_progress 1 ms before its permission request, then denied -> failed
            "crush_order": await turn("deny", [("update", upd("tool_call", "t1", "pending", "execute")),
                                              ("update", upd("tool_call_update", "t1", "in_progress")),
                                              ("perm", "t1"),
                                              ("update", upd("tool_call_update", "t1", "failed")),
                                              ("update", upd("tool_call_update", "t1", "in_progress"))]),
            # started, never asked, and the turn ends at once: the end-of-turn check trips
            "started_never_asked": await turn("deny", [("update", upd("tool_call", "t1", "in_progress", "execute"))]),
            "perm_all": await turn("all", [("update", upd("tool_call", "t1", "completed", "execute"))]),
            "sessions": await sessions(),
            "fallback_deny": fallback("deny"),
            "fallback_all": fallback("all"),
            "crush_base": mod.AGENTS["crush"][0],
            "crush_yolo": mod.YOLO_CMD["crush"],
            "opencode_env": json.loads(mod.DENY_ENV["opencode"]["OPENCODE_CONFIG_CONTENT"]),
            "zcode_env": mod.DENY_ENV["zcode"],
            "deny_set": mod.DENY_SET,
            "exit": mod.EXIT_TRIPWIRE,
        }

    print(json.dumps(asyncio.run(main()), default=str))
    """)


def probe() -> dict[str, Any]:
    r = subprocess.run(
        ["uv", "run", "--quiet", "--with", "agent-client-protocol>=0.9,<1.0", "python", "-I", "-c", PROBE,
         str(SCRIPT)], check=False, capture_output=True, text=True, timeout=180)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


class TestPermDeny(unittest.TestCase):
    r: ClassVar[dict[str, Any]] = {}

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.r = probe()

    def test_tool_running_without_permission_trips_and_cancels(self):
        t = self.r["trip_running"]
        self.assertEqual(t["code"], 77)
        self.assertEqual(t["out"]["stop_reason"], "tripwire")
        self.assertEqual(t["cancels"], 1)
        self.assertEqual(t["failure"][0], "tripwire")

    def test_trip_on_the_last_update_still_fails_the_turn(self):
        t = self.r["trip_last_update"]
        self.assertEqual(t["code"], 77)
        self.assertIn("ran without a permission request", t["out"]["error"])

    def test_a_tool_that_asked_and_was_denied_does_not_trip(self):
        t = self.r["asked_then_denied"]
        self.assertIsNone(t["tripped"])
        self.assertTrue(t["finished"])
        self.assertNotEqual(t["code"], 77)

    def test_in_progress_just_before_the_permission_request_is_not_a_trip(self):
        t = self.r["crush_order"]
        self.assertIsNone(t["tripped"])
        self.assertTrue(t["finished"])
        self.assertNotEqual(t["code"], 77)

    def test_a_started_tool_that_never_asks_trips_at_turn_end(self):
        t = self.r["started_never_asked"]
        self.assertEqual(t["code"], 77)
        self.assertEqual(t["out"]["stop_reason"], "tripwire")

    def test_exempt_kinds_let_reads_run_and_nothing_else(self):
        self.assertIsNone(self.r["exempt_read"]["tripped"])
        self.assertTrue(self.r["exempt_read"]["finished"])
        self.assertEqual(self.r["exempt_exec"]["code"], 77)
        self.assertEqual(self.r["no_exempt_read"]["code"], 77, "without the flag a read still trips")

    def test_only_read_only_kinds_can_be_exempted(self):
        r = subprocess.run(["uv", "run", "--quiet", "--script", str(SCRIPT), "claude", "--perm", "deny",
                            "--tripwire-exempt-kinds", "read,execute", "-p", "hi"],
                           check=False, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("only read-only kinds", r.stderr)

    def test_think_tools_and_perm_all_never_trip(self):
        self.assertIsNone(self.r["think_ok"]["tripped"])
        self.assertIsNone(self.r["perm_all"]["tripped"])

    def test_claude_session_gets_no_tools_meta_only_under_deny(self):
        s = self.r["sessions"]
        self.assertIn("claudeCode", s["/claudedeny"][0])
        self.assertIn("disableBuiltInTools", s["/claudedeny"][0])
        self.assertNotIn("claudeCode", s["/claudeall"][0])
        self.assertNotIn("claudeCode", s["/opencodedeny"][0])
        opts = self.r["sessions"]["claude_meta"]["options"]
        self.assertEqual(opts["tools"], [])
        self.assertEqual(opts["settingSources"], [])
        self.assertIs(opts["allowDangerouslySkipPermissions"], False)
        self.assertIs(opts["strictMcpConfig"], True)

    def test_claude_cli_fallback_reads_stdin_and_has_no_tools_under_deny(self):
        d = self.r["fallback_deny"]
        self.assertNotIn("SECRET PROMPT", d["cmd"])
        self.assertEqual(d["input"], "SECRET PROMPT")
        self.assertEqual(d["cmd"][d["cmd"].index("--tools") + 1], "")
        self.assertIn("--strict-mcp-config", d["cmd"])
        self.assertNotIn("--dangerously-skip-permissions", d["cmd"])
        self.assertIn("--dangerously-skip-permissions", self.r["fallback_all"]["cmd"])

    def test_zcode_deny_settings_turn_off_mcp_plugins_hooks(self):
        z = self.r["zcode_settings"]
        st = z["settings"]
        self.assertEqual(st["mcp"], {"servers": {}})
        self.assertEqual(st["features"], {"mcp": False, "subagent": False, "skill": False})
        self.assertFalse(st["plugins"]["enabled"])
        self.assertEqual(st["plugins"]["enabledPlugins"], {})
        self.assertFalse(st["hooks"]["enabled"])
        self.assertEqual(st["permission"]["mode"], "plan")
        self.assertFalse(st["permission"]["autoApproveHighRisk"])
        for tool in ("Agent", "Skill", "SendMessage", "TaskOutput", "TaskStop", "mcp__*", "Bash"):
            self.assertIn(tool, st["permission"]["disallowedTools"])
        self.assertEqual(st["storage"], {"dir": "~/.zcode"}, "unrelated keys are kept")
        self.assertFalse(z["config"]["hooks"]["enabled"])
        self.assertEqual(z["mode"], "0o700")

    def test_fallback_skips_user_settings_under_deny(self):
        d = self.r["fallback_deny"]["cmd"]
        self.assertEqual(d[d.index("--setting-sources") + 1], "project")

    def test_no_option_abbreviations(self):
        r = subprocess.run(["uv", "run", "--quiet", "--script", str(SCRIPT), "claude", "--per", "all", "-p", "hi"],
                           check=False, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("unrecognized arguments: --per", r.stderr)

    def test_crush_yolo_only_under_perm_all(self):
        self.assertNotIn("--yolo", self.r["crush_base"])
        self.assertIn("--yolo", self.r["crush_yolo"])

    def test_deny_env_and_modes(self):
        self.assertEqual(self.r["opencode_env"], {"permission": "deny"})
        self.assertEqual(self.r["zcode_env"]["ZCODE_ACP_MODE"], "plan")
        self.assertIn("Bash", self.r["zcode_env"]["ZCODE_DISALLOWED_TOOLS"])
        self.assertEqual(self.r["deny_set"]["claude"], {"mode": "default"})
        self.assertEqual(self.r["deny_set"]["zcode"], {"mode": "plan"})
        self.assertEqual(self.r["exit"], 77)


if __name__ == "__main__":
    unittest.main()
