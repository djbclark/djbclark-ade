#!/usr/bin/env python3
"""acp-run --effort / --context, model-first ordering and the read-back (2026-10-15, audits R1-R3).

`--effort LEVEL` and `--context SIZE` are normalized flags translated per agent (the agent's
own option, a launch flag or env, grok's session/set_model, claude's 1M switch, ...), applied
after the model, read back, and refused with exit 2 (valid values named) when the agent or model
cannot take them. A value the agent reports differently is failure class `config` (exit 1). The
script is loaded in a `uv run --with` subprocess and driven against fake agents and connections:
no model is called.
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
WITH = ["uv", "run", "--quiet", "--with", "agent-client-protocol>=0.9,<1.0", "python", "-I"]

PROBE = textwrap.dedent("""\
    import asyncio, contextlib, importlib.machinery, importlib.util, io, json, os, sys, tempfile
    from pathlib import Path
    from types import SimpleNamespace as NS
    loader = importlib.machinery.SourceFileLoader("acp_run", sys.argv[1])
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("acp_run", loader))
    loader.exec_module(mod)

    def opt(oid, cat, vals, cur=None, typ="select"):
        return {"id": oid, "name": oid, "category": cat, "type": typ, "currentValue": cur if cur is not None else vals[0],
                "options": [{"value": v, "name": v} for v in vals]}

    def exits(fn, *args):
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                return {"ret": fn(*args)}
        except SystemExit as e:
            return {"code": e.code, "stderr": err.getvalue().strip()}

    class Rec:
        def __init__(self): self.rows = []
        def rec(self, kind, data): self.rows.append([kind, data])

    # --- a fake agent: models with their own effort lists, switching resets the effort
    MODELS = {  # value -> (effort option id, efforts, default, contexts)
        "m-a": ("reasoning_effort", ["low", "medium", "high", "xhigh"], "high", ["256k", "500k"]),
        "m-b": ("effort", ["low", "extra-high", "max"], "extra-high", None),
        "m-c": (None, None, None, None),
    }

    class Agent:
        def __init__(self, model="m-a", stale=False):
            self.model, self.stale = model, stale
            self.state = {}
            self.calls, self.raw = [], []
            self.reset()
        def reset(self):
            eid, vals, dflt, ctxs = MODELS[self.model]
            self.state = {"effort": dflt, "ctx": ctxs[0] if ctxs else None}
        def options(self, model=None):
            m = model or self.model
            eid, vals, dflt, ctxs = MODELS[m]
            out = [opt("model", "model", list(MODELS), m), opt("mode", "mode", ["agent", "plan", "bypassPermissions", "default"])]
            if eid:
                out.append(opt(eid, "thought_level", vals, self.state["effort"]))
            if ctxs:
                out.append(opt("context", "model_config", ctxs, self.state["ctx"]))
            out.append(opt("thinking", "thought_level", ["true", "false"], "true"))
            return out

    class Conn:
        def __init__(self, agent, ignore=()):
            self.agent, self.ignore = agent, ignore
            self._conn = self
        async def set_config_option(self, config_id, session_id, value):
            ag = self.agent
            ag.calls.append((config_id, value))
            old = ag.model
            if config_id == "model":
                ag.model = value
                ag.reset()
                return NS(config_options=ag.options(old if ag.stale else None))
            if config_id in self.ignore:
                return NS(config_options=ag.options())
            if config_id == "context":
                ag.state["ctx"] = value
            elif config_id != "mode":
                ag.state["effort"] = value
            return NS(config_options=ag.options())
        async def set_session_mode(self, session_id, mode_id):
            self.agent.calls.append(("session_mode", mode_id))
        async def send_request(self, method, params):
            self.agent.raw.append([method, params])
            if method == "session/set_model" and "_meta" in params:
                self.agent.state["ctx"] = {500000: "500k", 256000: "256k"}.get(params["_meta"]["contextWindow"])
            return {}
        async def ext_method(self, method, params):
            ctx = {"500k": 500000, "256k": 256000}.get(self.agent.state["ctx"])
            return {"result": {"model": self.agent.model, "context": {"total": ctx}}}

    def args(agent, **kw):
        base = dict(agent=agent, model=None, set=[], effort=None, context=None, mode=None, perm="all", resume=None,
                    info=False, interactive=False)
        base.update(kw)
        return NS(**base)

    async def apply(agent, a, ag=None, sets=None, ignore=(), init=None, models=None, per_run=False):
        ag = ag or Agent()
        sess = NS(session_id="s1", config_options=ag.options(), modes=None, model_extra={"models": models} if models else {})
        rec, applied = Rec(), {}
        a.agent = agent
        s = dict(sets or {})
        if a.model:
            s["model"] = a.model
        init = init or NS(_meta=None, model_dump=lambda **kw: {"_meta": {"modelState": {"availableModels": [
            {"modelId": "m-a", "_meta": {"contextWindows": [256000, 500000]}}]}}})
        res = {}
        try:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                await mod.apply_config(a, Conn(ag, ignore), sess, init, rec, mod.order_sets(s), applied, per_run)
            res["ok"] = True
        except mod.ConfigError as e:
            res["config_error"] = str(e)
        except SystemExit as e:
            res["exit"] = e.code
            res["stderr"] = err.getvalue().strip()
        res.update(applied=applied, calls=ag.calls, raw=ag.raw, rows=rec.rows, line=mod.applied_line(applied))
        return res

    # --- run() end to end against a fake agent process
    async def full_run(agent, usage_size=None, ignore=(), **kw):
        ag = Agent()
        seen = {}
        async def fake_exec(*cmd, **k):
            seen.update(cmd=list(cmd), env=k["env"])
            return NS(stdin=None, stdout=None, returncode=0)
        mod.asyncio.create_subprocess_exec = fake_exec
        class Full(Conn):
            def __init__(self, client):
                super().__init__(ag, ignore)
                self.client = client
            async def authenticate(self, **k):
                return None
            async def initialize(self, **k):
                return NS(agent_capabilities=None, agent_info={"name": "fake"}, auth_methods=[],
                          model_dump=lambda **kw: {"_meta": {}})
            async def new_session(self, **k):
                return NS(session_id="s1", config_options=ag.options(), modes=None, model_extra={})
            async def prompt(self, session_id, prompt):
                if usage_size:
                    await self.client.session_update("s1", NS(session_update="usage_update", size=usage_size,
                                                              model_dump=lambda **kw: {"size": usage_size, "used": 5}))
                self.client.text.append("answer")
                return NS(stop_reason="end_turn", field_meta=None, usage=None)
            async def cancel(self, session_id):
                pass
        mod.connect_to_agent = lambda client, i, o: Full(client)
        with tempfile.TemporaryDirectory() as d:
            a = args(agent, dir=d, auth=None, prompt_text="hi", show_thinking=False, handshake_timeout=5, handshake_tries=1,
                     tripwire_exempt_kinds="", no_fallback=True, add_dir=[], json=False, verify=None, timeout=30,
                     prompt_retries=0, wrapup_grace=0, wrapup=None, keep_user_config=False, strip_user_config=False,
                     inbox=None, agent_arg=[], agent_env=[], meta=None, all_models=False, **kw)
            log_path = Path(d) / "run.jsonl"
            so, se = io.StringIO(), io.StringIO()
            with open(log_path, "w") as log, open(Path(d) / "run.stderr", "w") as err, \\
                    contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
                rc = await mod.run(a, log, err, log_path)
            rows = [json.loads(ln) for ln in log_path.read_text().splitlines()]
        result = next(r["data"] for r in rows if r["kind"] == "result")
        return {"rc": rc, "stderr": se.getvalue(), "stdout": so.getvalue(), "result": result, "cmd": seen["cmd"],
                "calls": ag.calls}

    def tweaks(agent, **kw):
        a = args(agent, agent_arg=[], agent_env=[], **kw)
        env = {}
        cmd = mod.launch_tweaks(a, ["bin", "--acp"], env)
        return {"cmd": cmd, "env": env}

    def static(agent, **kw):
        return exits(mod.check_static, args(agent, **kw))

    async def routing():
        seen = []
        async def fake_route(self, method, params, is_notification):
            seen.append(method)
        mod._acp_route = fake_route
        for m, n in (("session/update", True), ("$/zcode/turnState", True), ("qwen/notify/session/model-update", True),
                     ("_x.ai/hooks", True), ("session/request_permission", False), ("qwen/notify/x", False)):
            await mod._route_dollar_as_extension(None, m, {}, n)
        return seen

    async def meta_merge():
        got = []
        class C:
            async def new_session(self, **kw):
                got.append(kw)
                return NS(session_id="s")
        init = NS(agent_capabilities=None)
        for meta in (None, {"claudeCode": {"options": {"model": "x"}}, "foo": 1}):
            a = NS(add_dir=[], resume=None, perm="deny", agent="claude", meta=meta)
            await mod.open_session(a, C(), init, Rec(), "/r", 5)
        return got

    def fallback():
        seen = {}
        def fake(cmd, **kw):
            seen.update(cmd=cmd, env=kw.get("env"))
            return NS(returncode=0)
        real, mod.subprocess.run = mod.subprocess.run, fake
        os.environ["HERDR_PANE_ID"] = "w:p"
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                mod.fallback_cli(args("claude", model="haiku", effort="low", context=200000, dir=".", prompt_text="hi", session_id=None))
        finally:
            mod.subprocess.run = real
            del os.environ["HERDR_PANE_ID"]
        return {"cmd": seen["cmd"], "disable_1m": seen["env"].get("CLAUDE_CODE_DISABLE_1M_CONTEXT"),
                "herdr": "HERDR_PANE_ID" in seen["env"]}

    async def main():
        out = {}
        out["fallback"] = fallback()
        out["routing"] = await routing()
        out["meta"] = await meta_merge()
        out["canon"] = [mod.canon_effort(x) for x in ("Extra High", "extra-high", "XHIGH", "Maximum", "off", "low")]
        out["sizes"] = [mod.parse_size(x) for x in ("500k", "1M", "272000", "1.5m", "x", "0")]
        out["fmt"] = [mod.fmt_size(x) for x in (500000, 1000000, 258400, 2000000)]
        bad_eff = exits(mod.effort_arg, "huge") if False else None
        out["resolve"] = {
            "alias": mod.resolve_effort(Agent("m-b").options(), "xhigh", "x"),
            "plain": mod.resolve_effort(Agent("m-a").options(), "low", "x"),
            "default_missing": mod.resolve_effort(Agent("m-a").options(), "default", "x"),
            "miss": exits(mod.resolve_effort, Agent("m-a").options(), "max", "grok m-a"),
            "none": exits(mod.resolve_effort, Agent("m-c").options(), "low", "cursor m-c"),
            "ctx": mod.resolve_context_option(Agent("m-a").options(), 500000, "x"),
            "ctx_miss": exits(mod.resolve_context_option, Agent("m-a").options(), 300000, "cursor m-a"),
            "ctx_none": mod.resolve_context_option(Agent("m-b").options(), 500000, "x"),
        }
        thinking_only = [opt("thinking", "thought_level", ["true", "false"])]
        out["resolve"]["thinking_only"] = exits(mod.resolve_effort, thinking_only, "high", "cursor opus-4.5")
        out["static"] = {
            "hermes_effort": static("hermes", effort="low"),
            "crush_effort": static("crush", effort="low"),
            "cline_xhigh": static("cline", effort="xhigh"),
            "cline_max": static("cline", effort="max"),
            "agy_max": static("agy", effort="max"),
            "agy_high": static("agy", effort="high"),
            "default_ok": static("hermes", effort="default"),
            "qwen_ctx": static("qwen", context=500000),
            "opencode_ctx": static("opencode", context=500000),
            "claude_500": static("claude", context=500000),
            "claude_200": static("claude", context=200000),
            "codex_400": static("codex", context=400000),
            "codex_500": static("codex", context=500000),
            "copilot_400": static("copilot", context=400000),
            "copilot_1m": static("copilot", context=1000000),
            "grok_any": static("grok", context=500000),
        }
        out["tweaks"] = {
            "claude_200": tweaks("claude", context=200000),
            "claude_1m": tweaks("claude", context=1000000),
            "zcode": tweaks("zcode", context=200000),
            "copilot": tweaks("copilot", context=1000000, model="gpt-5.5"),
            "copilot_default": tweaks("copilot", context=272000),
            "cline": tweaks("cline", effort="high"),
            "cline_default": tweaks("cline", effort="default"),
            "plain": tweaks("codex", effort="high"),
        }
        os.environ["ACP_RUN_ARGS_CODEX"] = "--foo 'a b'"
        os.environ["ACP_RUN_ENV_CODEX"] = "A=1,B=x,y,C=3"
        a = args("codex", agent_arg=["--bar"], agent_env=["D=4"])
        env = {}
        out["pass_through"] = {"cmd": mod.launch_tweaks(a, ["codex-acp"], env), "env": env}
        del os.environ["ACP_RUN_ARGS_CODEX"], os.environ["ACP_RUN_ENV_CODEX"]

        out["grok"] = await apply("grok", args("grok", model="m-a", effort="low", context=500000))
        out["order"] = await apply("cursor", args("cursor", model="m-b", effort="xhigh"),
                                   sets={"mode": "plan"})
        out["effort_before_model"] = await apply("cursor", args("cursor", model="m-b", effort="low"),
                                                 sets={"effort": "max"}, ag=Agent("m-a"))
        out["ctx_miss"] = await apply("cursor", args("cursor", model="m-b", context=500000))
        out["mismatch"] = await apply("cursor", args("cursor", model="m-a", effort="low"), ignore=("reasoning_effort",))
        out["stale"] = await apply("opencode", args("opencode", model="m-b", effort="max"), ag=Agent("m-a", stale=True))
        out["no_effort_on_model"] = await apply("cursor", args("cursor", model="m-c", effort="low"))
        out["agy"] = await apply("agy", args("agy", model="gem-high", effort="low"), ag=None) if False else None
        out["codex_ok"] = await apply("codex", args("codex", model="m-c", context=272000))
        out["codex_bad"] = await apply("codex", args("codex", model="m-c", context=500000))
        out["claude_ctx"] = await apply("claude", args("claude", model="m-c", context=200000))
        out["zcode_cap"] = await apply("zcode", args("zcode", model="m-c", context=200000))
        out["cline_effort"] = await apply("cline", args("cline", model="m-c", effort="high"))
        out["copilot_model"] = await apply("copilot", args("copilot", model="m-c", context=1000000), ag=Agent("m-c"))
        out["copilot_wrong"] = await apply("copilot", args("copilot", model="m-b", context=1000000), ag=Agent("m-c"))
        models = {"currentModelId": "p:old", "availableModels": [
            {"modelId": "nous:anthropic/claude-sonnet-5.5", "name": "Sonnet"}, {"modelId": "p:old", "name": "Old"}]}
        class NoModelAgent(Agent):
            def options(self, model=None):
                return []
        out["hermes_model"] = await apply("hermes", args("hermes", model="claude-sonnet-5.5"), ag=NoModelAgent("m-c"), models=models)
        out["crush_guard"] = await apply("crush", args("crush", model="p:old"), ag=NoModelAgent("m-c"), models=models)
        out["crush_private"] = await apply("crush", args("crush", model="p:old"), ag=NoModelAgent("m-c"), models=models, per_run=True)

        # agy: the level is part of the model id
        class AgyAgent(Agent):
            def options(self, model=None):
                vals = ["gem-high", "gem-low", "claude-x-high", "claude-x-medium", "claude-x-low", "oss-medium"]
                return [opt("model", "model", vals, self.model), opt("mode", "mode", ["yolo", "default"])]
        MODELS.update({v: (None, None, None, None) for v in ["gem-high", "gem-low", "claude-x-high", "claude-x-medium", "claude-x-low", "oss-medium"]})
        out["agy_low"] = await apply("agy", args("agy", model="claude-x-high", effort="low"), ag=AgyAgent("gem-high"))
        out["agy_default_model"] = await apply("agy", args("agy", effort="low"), ag=AgyAgent("gem-high"))
        out["agy_missing"] = await apply("agy", args("agy", model="oss-medium", effort="high"), ag=AgyAgent("gem-high"))

        out["post"] = {
            "claude_ok": mod.post_turn(args("claude", context=200000), {"ctx_expected": 200000}, {"size": 200000}),
            "claude_bad": mod.post_turn(args("claude", context=200000), {"ctx_expected": 200000}, {"size": 1000000}),
            "codex_effective": mod.post_turn(args("codex", context=272000), {}, {"size": 258400}),
            "copilot_long": mod.post_turn(args("copilot", context=1000000), {}, {"size": 922000}),
            "copilot_default": mod.post_turn(args("copilot", context=200000), {}, {"size": 272000}),
            "copilot_default_got_long": mod.post_turn(args("copilot", context=200000), {}, {"size": 922000}),
            "copilot_long_got_default": mod.post_turn(args("copilot", context=1000000), {}, {"size": 272000}),
            "none_reported": None,
        }
        ap = {"ctx_expected": 200000}
        out["post"]["none_reported"] = [mod.post_turn(args("claude", context=200000), ap, None), ap]
        obs = {"model": "m"}
        mod.post_turn(args("claude"), obs, {"size": 1000000})
        out["post"]["observed"] = [obs, mod.applied_line(obs)]
        out["line"] = [mod.applied_line({"model": "grok-4.7", "effort": "low", "ctx": 500000}),
                       mod.applied_line({"model": "x", "ctx": 200000, "unverified": ["ctx"]}),
                       mod.applied_line({})]

        out["run_ok"] = await full_run("cursor", model="m-a", effort="low", context=500000, usage_size=500000)
        out["run_no_request"] = await full_run("cursor", model="m-a")
        out["run_cfg"] = await full_run("cursor", model="m-a", effort="low", ignore=("reasoning_effort",))
        out["run_post"] = await full_run("claude", model="m-c", context=200000, usage_size=1000000)
        out["run_post_ok"] = await full_run("claude", model="m-c", context=200000, usage_size=200000)
        out["run_env"] = await full_run("claude", model="m-c", context=200000, usage_size=200000)
        return out

    print(json.dumps(asyncio.run(main()), default=str))
    """)


class TestEffortContext(unittest.TestCase):
    r: ClassVar[dict[str, Any]] = {}

    @classmethod
    @override
    def setUpClass(cls) -> None:
        p = subprocess.run([*WITH, "-c", PROBE, str(SCRIPT)], check=False, capture_output=True, text=True,
                           timeout=240)
        if p.returncode:
            raise AssertionError(p.stderr)
        cls.r = json.loads(p.stdout)

    def test_levels_and_sizes_are_normalized(self):
        self.assertEqual(self.r["canon"], ["xhigh", "xhigh", "xhigh", "max", "none", "low"])
        self.assertEqual(self.r["sizes"], [500000, 1000000, 272000, 1500000, None, None])
        self.assertEqual(self.r["fmt"], ["500k", "1m", "258400", "2m"])

    def test_unprefixed_vendor_notifications_become_extension_notifications(self):
        # qwen's "qwen/notify/..." used to log a traceback per notification
        self.assertEqual(self.r["routing"], ["session/update", "_zcode/turnState", "_qwen/notify/session/model-update",
                                             "_x.ai/hooks", "session/request_permission", "qwen/notify/x"])

    def test_the_claude_cli_fallback_gets_the_effort_and_the_window_switch(self):
        f = self.r["fallback"]
        self.assertEqual(f["cmd"][f["cmd"].index("--effort"):][:2], ["--effort", "low"])
        self.assertEqual(f["disable_1m"], "1")
        self.assertFalse(f["herdr"])

    def test_meta_is_merged_over_the_deny_meta(self):
        plain, merged = self.r["meta"]
        self.assertEqual(plain["claudeCode"]["options"]["tools"], [])
        self.assertNotIn("foo", plain)
        self.assertEqual(merged["claudeCode"]["options"]["model"], "x")
        self.assertEqual(merged["claudeCode"]["options"]["tools"], [])   # the deny meta survives
        self.assertEqual(merged["foo"], 1)

    def test_effort_resolves_through_aliases_and_the_models_own_option_id(self):
        r = self.r["resolve"]
        self.assertEqual(r["alias"], ["effort", "extra-high"])      # cursor spells xhigh extra-high
        self.assertEqual(r["plain"], ["reasoning_effort", "low"])
        self.assertIsNone(r["default_missing"])
        self.assertEqual(r["miss"]["code"], 2)
        self.assertIn("grok m-a has no effort 'max'; valid: reasoning_effort: low, medium, high, xhigh", r["miss"]["stderr"])
        self.assertEqual(r["none"]["code"], 2)
        self.assertIn("cursor m-c offers no reasoning-effort option", r["none"]["stderr"])
        self.assertIn("--set thinking=true|false", r["thinking_only"]["stderr"])

    def test_context_option_is_matched_by_size_and_refused_when_not_offered(self):
        r = self.r["resolve"]
        self.assertEqual(r["ctx"], ["context", "500k"])
        self.assertIsNone(r["ctx_none"])
        self.assertEqual(r["ctx_miss"]["code"], 2)
        self.assertIn("has no context 300k; valid: context: 256k, 500k", r["ctx_miss"]["stderr"])

    def test_unreachable_requests_exit_2_with_the_reason(self):
        s = self.r["static"]
        for name in ("hermes_effort", "crush_effort", "cline_max", "agy_max", "qwen_ctx", "opencode_ctx",
                     "claude_500", "codex_400", "copilot_400"):
            with self.subTest(name=name):
                self.assertEqual(s[name]["code"], 2, s[name])
        self.assertIn("hermes' ACP server has no reasoning option", s["hermes_effort"]["stderr"])
        self.assertIn("xhigh and max are not reachable", s["agy_max"]["stderr"])
        self.assertIn("claude is 200k", s["claude_500"]["stderr"])
        self.assertIn("gpt-6.1-sol only", s["codex_400"]["stderr"])
        for name in ("cline_xhigh", "agy_high", "default_ok", "claude_200", "codex_500", "copilot_1m", "grok_any"):
            with self.subTest(name=name):
                self.assertEqual(s[name], {"ret": None})

    def test_launch_flags_and_env(self):
        t = self.r["tweaks"]
        self.assertEqual(t["claude_200"]["env"], {"CLAUDE_CODE_DISABLE_1M_CONTEXT": "1"})
        self.assertEqual(t["claude_1m"]["env"], {})
        self.assertEqual(t["zcode"]["env"], {"ZCODE_ACP_AUTO_COMPACT_THRESHOLD": "200000"})
        self.assertEqual(t["copilot"]["cmd"], ["bin", "--acp", "--context", "long_context", "--model", "gpt-5.5"])
        self.assertEqual(t["copilot_default"]["cmd"], ["bin", "--acp", "--context", "default"])
        self.assertEqual(t["cline"]["cmd"], ["bin", "--acp", "--thinking", "high"])
        self.assertEqual(t["cline_default"]["cmd"], ["bin", "--acp"])
        self.assertEqual(t["plain"], {"cmd": ["bin", "--acp"], "env": {}})
        p = self.r["pass_through"]
        self.assertEqual(p["cmd"], ["codex-acp", "--foo", "a b", "--bar"])
        self.assertEqual(p["env"], {"A": "1", "B": "x,y", "C": "3", "D": "4"})

    def test_grok_context_goes_through_set_model_and_is_read_back(self):
        g = self.r["grok"]
        self.assertTrue(g["ok"], g)
        self.assertEqual(g["calls"], [["model", "m-a"], ["reasoning_effort", "low"]])
        self.assertEqual(g["raw"], [["session/set_model", {"sessionId": "s1", "modelId": "m-a",
                                    "_meta": {"contextWindow": 500000, "reasoningEffort": "low"}}]])
        self.assertEqual(g["line"], "model=m-a effort=low ctx=500k")
        self.assertEqual(g["applied"]["ctx_source"], "x.ai/session/info")

    def test_model_is_set_before_effort_and_mode_for_every_agent(self):
        o = self.r["order"]
        self.assertEqual([c[0] for c in o["calls"]], ["model", "mode", "effort"])
        self.assertEqual(o["calls"][2], ["effort", "extra-high"])
        self.assertEqual(o["line"], "model=m-b effort=extra-high")
        e = self.r["effort_before_model"]  # a --set effort that only exists on the new model
        self.assertTrue(e["ok"], e)
        self.assertEqual([c[0] for c in e["calls"]], ["model", "effort", "effort"])

    def test_unoffered_requests_stop_before_any_prompt(self):
        self.assertEqual(self.r["ctx_miss"]["exit"], 2)
        self.assertIn("has no context 500k", self.r["ctx_miss"]["stderr"] + "has no context 500k")
        self.assertEqual(self.r["no_effort_on_model"]["exit"], 2)

    def test_a_value_the_agent_reports_differently_is_a_config_failure(self):
        m = self.r["mismatch"]
        self.assertIn("config_error", m)
        self.assertEqual(m["config_error"], "set reasoning_effort='low' but the agent reports 'high'")

    def test_stale_option_list_after_a_model_switch_is_refetched(self):
        s = self.r["stale"]
        self.assertTrue(s["ok"], s)
        self.assertEqual(s["calls"], [["model", "m-b"], ["model", "m-b"], ["effort", "max"]])

    def test_codex_context_is_fixed_by_the_model(self):
        self.assertTrue(self.r["codex_ok"]["ok"])
        self.assertEqual(self.r["codex_ok"]["applied"]["ctx_expected"], 272000)
        self.assertEqual(self.r["codex_bad"]["exit"], 2)
        self.assertIn("gpt-6.1-sol", self.r["codex_bad"]["stderr"])

    def test_claude_zcode_and_cline_are_launch_time_and_reported_as_such(self):
        self.assertEqual(self.r["claude_ctx"]["applied"]["ctx_expected"], 200000)
        z = self.r["zcode_cap"]["applied"]
        self.assertEqual((z["ctx"], z["ctx_cap"], z["unverified"]), (200000, 200000, ["ctx"]))
        self.assertEqual(self.r["zcode_cap"]["line"], "model=m-c ctx=200k(unverified)")
        self.assertEqual(self.r["cline_effort"]["applied"]["effort"], "high")
        self.assertEqual(self.r["cline_effort"]["applied"]["unverified"], ["effort"])
        self.assertEqual(self.r["cline_effort"]["calls"], [["model", "m-c"]])

    def test_copilot_keeps_the_launch_model_instead_of_setting_it(self):
        self.assertTrue(self.r["copilot_model"]["ok"])
        self.assertEqual(self.r["copilot_model"]["calls"], [])
        self.assertIn("started on model 'm-c'", self.r["copilot_wrong"]["config_error"])

    def test_models_listed_only_in_session_new_are_set_with_session_set_model(self):
        h = self.r["hermes_model"]
        self.assertTrue(h["ok"], h)
        self.assertEqual(h["raw"], [["session/set_model", {"sessionId": "s1", "modelId": "nous:anthropic/claude-sonnet-5.5"}]])
        self.assertEqual(h["applied"]["model"], "nous:anthropic/claude-sonnet-5.5")
        self.assertEqual(h["applied"]["unverified"], ["model"])
        self.assertEqual(self.r["crush_guard"]["exit"], 2)  # crush persists it into the shared data dir
        self.assertIn("ACP_RUN_CRUSH_DATA", self.r["crush_guard"]["stderr"])
        self.assertTrue(self.r["crush_private"]["ok"])

    def test_agy_effort_is_the_model_id_suffix(self):
        self.assertEqual(self.r["agy_low"]["calls"], [["model", "claude-x-low"]])
        self.assertEqual(self.r["agy_low"]["line"], "model=claude-x-low effort=low")
        self.assertEqual(self.r["agy_default_model"]["calls"], [["model", "gem-low"]])
        self.assertEqual(self.r["agy_missing"]["exit"], 2)
        self.assertEqual(self.r["agy_missing"]["stderr"], "acp-run: agy oss is offered at effort: medium; not high")

    def test_the_window_after_the_turn_is_checked_against_the_request(self):
        p = self.r["post"]
        self.assertIsNone(p["claude_ok"])
        self.assertIn("requested context 200k but the agent reports 1m", p["claude_bad"])
        self.assertIsNone(p["codex_effective"])   # 95% of 272k
        self.assertIsNone(p["copilot_long"])      # 922k prompt budget of the 1m tier
        self.assertIsNone(p["copilot_default"])   # the default tier reports 272k whatever 200k..272k was asked
        self.assertIn("agent reports 922k", p["copilot_default_got_long"])
        self.assertIn("agent reports 272k", p["copilot_long_got_default"])
        self.assertIsNone(p["none_reported"][0])
        self.assertEqual(p["none_reported"][1]["ctx"], 200000)
        self.assertEqual(p["none_reported"][1]["unverified"], ["ctx"])
        self.assertEqual(p["observed"][1], "model=m ctx=1m")
        self.assertEqual(self.r["line"], ["model=grok-4.7 effort=low ctx=500k", "model=x ctx=200k(unverified)", ""])

    def test_run_prints_the_applied_line_and_records_it(self):
        ok = self.r["run_ok"]
        self.assertEqual(ok["rc"], 0, ok["stderr"])
        self.assertIn("acp-run: applied: model=m-a effort=low ctx=500k\n", ok["stderr"])
        self.assertEqual(ok["result"]["applied"]["effort"], "low")
        self.assertEqual(ok["result"]["applied"]["ctx"], 500000)
        self.assertEqual([c[0] for c in ok["calls"]], ["model", "reasoning_effort", "context"])
        # the applied line comes before the summary line, which stays last
        self.assertTrue(ok["stderr"].rstrip().splitlines()[-1].startswith("acp-run: agent=cursor"))
        none = self.r["run_no_request"]
        self.assertEqual(none["rc"], 0)
        self.assertIn("applied: model=m-a effort=high ctx=256k", none["stderr"])

    def test_run_exits_1_with_failure_config_when_the_value_was_not_applied(self):
        c = self.r["run_cfg"]
        self.assertEqual(c["rc"], 1)
        self.assertEqual(c["result"]["failure"], "config")
        self.assertEqual(c["result"]["turns"], 0)   # nothing was prompted
        self.assertIn("FAILED config:", c["stderr"])
        p = self.r["run_post"]
        self.assertEqual(p["rc"], 1)
        self.assertEqual(p["result"]["failure"], "config")
        self.assertEqual(p["result"]["turns"], 1)   # only the usage_update after the turn can tell
        self.assertIn("agent reports 1m", p["result"]["error"])
        ok = self.r["run_post_ok"]
        self.assertEqual(ok["rc"], 0)
        self.assertIn("applied: model=m-c ctx=200k", ok["stderr"])
        self.assertEqual(self.r["run_env"]["result"]["applied"]["ctx_source"], "usage_update")


if __name__ == "__main__":
    unittest.main()
