#!/usr/bin/env python3
"""acp-run fixes of 2026-10-15 for grok under --perm deny, the herdr scrub and model ordering.

1. `acp-run grok --perm deny` launched `grok agent --always-approve stdio`, so grok never sent
   session/request_permission and any tool call tripped the deny tripwire (exit 77); that broke
   acp-dispatch's preflight probe ("Reply with exactly: OK"). The probe's tool was read_file of
   the autorename skill, run because the user's grok Stop hook (autorename_nudge) asked for a
   title. Now a deny run drops --always-approve and starts grok on a per-run GROK_HOME without the
   user's hooks, skills, plugins and MCP servers, whose config.toml asks before every tool.
2. HERDR_PANE_ID and HERDR_ENV are removed from the agent's environment on every run (a grok probe
   fired the autorename hook, which renamed the caller's herdr tab).
3. The model is applied first for every agent, then the other options (a model switch resets
   effort and changes which effort values exist); pick_config tries every option of a category and
   strips a trailing "(openai)" from model tokens (qwen).
4. zcode-acp-server gets ZCODE_BIN (its model switch failed without it); the tripwire names the tool.
acp-run imports the ACP SDK, so the script is loaded in a `uv run --with` subprocess against fakes.
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

CONFIG = textwrap.dedent("""\
    [cli]
    installer = "internal"

    [ui]
    max_thoughts_width = 120
    permission_mode = "always-approve"
    yolo = false

    [models]
    default = "grok-4.7"

    [compat.claude]
    hooks = false

    [plugins]
    enabled = ["composio"]

    [mcp_servers.basic-memory]
    url = "http://127.0.0.1:18796/mcp"
    enabled = true

    [mcp_servers.graft]
    command = "graft"
    args = ["mcp"]

    [permission]
    allow = ["Bash(git *)"]

    [[hooks.PreToolUse]]
    matcher = "Bash"
      [[hooks.PreToolUse.hooks]]
      type = "command"
      command = "/opt/guard.sh"

    [model_providers.localproxy]
    base_url = "http://127.0.0.1:10100/v1"

    [model.local-gpt-6-astra]
    model = "gpt-6-astra"
    """)

PROBE = textwrap.dedent("""\
    import asyncio, contextlib, importlib.machinery, importlib.util, io, json, os, shutil, sys, tempfile, tomllib
    from pathlib import Path
    from types import SimpleNamespace as NS
    loader = importlib.machinery.SourceFileLoader("acp_run", sys.argv[1])
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("acp_run", loader))
    loader.exec_module(mod)
    CONFIG = Path(sys.argv[2]).read_text()
    home = Path(tempfile.mkdtemp())
    os.environ["HOME"] = str(home)
    os.environ.pop("GROK_HOME", None)
    g = home / ".grok"
    for sub in ("hooks", "skills/autorename", "plugins", "sessions", "installed-plugins"):
        (g / sub).mkdir(parents=True)
    (g / "hooks" / "autorename.json").write_text("{}")
    (g / "auth.json").write_text('{"token": "old"}')
    (g / "models_cache.json").write_text("{}")
    (g / "config.toml").write_text(CONFIG)

    def tmpl(deny):
        text, dropped = mod.grok_filter_config(CONFIG, deny)
        return {"text": text, "dropped": dropped, "ok": mod.grok_check_config(CONFIG, text, deny),
                "parsed": tomllib.loads(text)}

    def strip(perm, strip_flag=False, keep=False, interactive=False, optout=None):
        a = NS(agent="grok", perm=perm, interactive=interactive, keep_user_config=keep,
               strip_user_config=strip_flag)
        env = {}
        if optout is not None:
            os.environ["ACP_RUN_GROK_USER_HOOKS"] = optout
        try:
            d, info = mod.strip_user_config(a, env, None)
        finally:
            os.environ.pop("ACP_RUN_GROK_USER_HOOKS", None)
        out = {"info": info, "env": env}
        if d:
            p = Path(d)
            out["names"] = sorted(x.name for x in p.iterdir())
            out["links"] = {x.name: os.readlink(x) for x in p.iterdir() if x.is_symlink()}
            out["config"] = tomllib.loads((p / "config.toml").read_text())
            out["mode"] = oct((p / "config.toml").stat().st_mode & 0o777)
            shutil.rmtree(p)
        return out

    def sync_auth():
        d, _ = mod.grok_strip_home()
        res = {"symlink_untouched": mod.grok_sync_auth(d)}
        os.unlink(d / "auth.json")                      # rename-over replaces the symlink
        (d / "auth.json").write_text('{"token": "rotated"}')
        os.utime(d / "auth.json", (4102444800, 4102444800))
        res["copied"] = mod.grok_sync_auth(d)
        res["real"] = (g / "auth.json").read_text()
        (d / "auth.json").write_text("not json")
        os.utime(d / "auth.json", (4102444900, 4102444900))
        res["bad_json_copied"] = mod.grok_sync_auth(d)
        res["real_after_bad"] = (g / "auth.json").read_text()
        shutil.rmtree(d)
        (g / "auth.json").write_text('{"token": "old"}')
        return res

    INIT = NS(agent_capabilities=None, agent_info={"name": "fake"}, auth_methods=[])
    SESS = NS(session_id="s1", modes=None, config_options=None)

    class Conn:
        async def initialize(self, **kw):
            return INIT
        async def authenticate(self, **kw):
            return None
        async def new_session(self, **kw):
            return SESS

    async def spawn(agent, perm, extra_env=None, strip_flag=False):
        seen = {}
        async def fake_exec(*cmd, **kw):
            seen.update(cmd=list(cmd), env=kw["env"])
            return NS(stdin=None, stdout=None, returncode=0)
        mod.asyncio.create_subprocess_exec = fake_exec
        mod.connect_to_agent = lambda client, i, o: Conn()
        old = dict(os.environ)
        os.environ.update({"HERDR_PANE_ID": "w1:p1", "HERDR_ENV": "1", "HERDR_TAB_ID": "w1:t1",
                           **(extra_env or {})})
        try:
            with tempfile.TemporaryDirectory() as d:
                a = NS(agent=agent, auth=None, perm=perm, mode=None, dir=d, prompt_text=None,
                       interactive=False, show_thinking=False, handshake_timeout=5, handshake_tries=1,
                       tripwire_exempt_kinds="", info=True, no_fallback=True, resume=None,
                       add_dir=[], set=[], model=None, json=False, verify=None,
                       keep_user_config=False, strip_user_config=strip_flag)
                log_path = Path(d) / "run.jsonl"
                with open(log_path, "w") as log, open(Path(d) / "run.stderr", "w") as err, \\
                        contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    rc = await mod.run(a, log, err, log_path)
                rows = [json.loads(ln) for ln in log_path.read_text().splitlines()]
        finally:
            os.environ.clear()
            os.environ.update(old)
        env = seen["env"]
        return {"rc": rc, "cmd": seen["cmd"],
                "herdr": sorted(k for k in env if k.startswith("HERDR_")),
                "grok_home": env.get("GROK_HOME"), "zcode_bin": env.get("ZCODE_BIN"),
                "user_config": [r["data"] for r in rows if r["kind"] == "user_config"]}

    def upd(kind, tid, status=None, tkind=None, title=None):
        return NS(session_update=kind, tool_call_id=tid, status=status, kind=tkind, title=title)

    async def tripwire_title():
        c = mod.RunClient(io.StringIO(), "deny", ".")
        await c.session_update("s", upd("tool_call", "t1", "pending", "read", "read_file"))
        await c.session_update("s", upd("tool_call_update", "t1", "completed"))
        return c.tripped

    def picks():
        def opt(oid, cat, vals):
            return {"id": oid, "category": cat, "type": "select", "options": [{"value": v, "name": v} for v in vals]}
        cursor = [opt("thinking", "thought_level", ["true", "false"]),
                  opt("effort", "thought_level", ["low", "extra-high"])]
        qwen = [opt("model", "model", ["qwen3.8-max(openai)", "glm-5(openai)", "qwen3.5-plus(openai)"])]
        out = {"second_option": mod.pick_config(cursor, "extra-high", "thought_level"),
               "qwen_suffix": mod.pick_config(qwen, "qwen3.8-max", "model"),
               "qwen_exact": mod.pick_config(qwen, "glm-5(openai)", "model")}
        try:
            mod.pick_config(cursor, "max", "thought_level")
        except SystemExit as e:
            out["miss"] = str(e)
        try:
            mod.pick_config(qwen, "kimi", "model")
        except SystemExit as e:
            out["miss_single"] = str(e)
        try:
            mod.pick_config([], "x", "model")
        except SystemExit as e:
            out["no_option"] = str(e)
        return out

    def zcode():
        pkg = home / "lib" / "zcode-app-cli"
        (pkg / "bin").mkdir(parents=True)
        (pkg / "vendor" / "provider").mkdir(parents=True)
        (pkg / "bin" / "zcode.js").write_text("")
        (pkg / "bin" / "zcode.js").chmod(0o755)
        (pkg / "vendor" / "zcode.cjs").write_text("")
        (pkg / "vendor" / "provider" / "zcode-builtin.json").write_text("{}")
        (home / "bin").mkdir()
        (home / "bin" / "zcode").symlink_to(pkg / "bin" / "zcode.js")
        old = os.environ["PATH"]
        os.environ["PATH"] = str(home / "bin") + os.pathsep + old
        try:
            found = mod.zcode_bin()
            (pkg / "vendor" / "provider" / "zcode-builtin.json").unlink()
            missing = mod.zcode_bin()
        finally:
            os.environ["PATH"] = old
        return {"found": found == str((pkg / "vendor" / "zcode.cjs").resolve()), "got": found, "missing": missing}

    async def main():
        return {
            "deny": tmpl(True), "keep": tmpl(False),
            "strip_deny": strip("deny"), "strip_outside": strip("all", strip_flag=True),
            "strip_all_no_flag": strip("all"), "strip_kept": strip("deny", keep=True),
            "hooks_all": strip("all"), "hooks_interactive": strip("all", interactive=True),
            "hooks_optout": strip("all", optout="1"), "hooks_optout_off": strip("all", optout="0"),
            "hooks_optout_deny": strip("deny", optout="1"),
            "hooks_keep_flag": strip("all", keep=True),
            "hooks_tmpl": {"text": mod.grok_filter_config(CONFIG, False, False)[0],
                           "ok": mod.grok_check_config(CONFIG, mod.grok_filter_config(CONFIG, False, False)[0], False, False)},
            "sync": sync_auth(),
            "spawn_grok_deny": await spawn("grok", "deny"),
            "spawn_grok_all": await spawn("grok", "all"),
            "spawn_grok_strip": await spawn("grok", "all", strip_flag=True),
            "spawn_codex": await spawn("codex", "all"),
            "spawn_zcode": await spawn("zcode", "all"),
            "tripwire": await tripwire_title(),
            "order": [list(mod.order_sets(d)) for d in (
                {"mode": "x", "effort": "y", "model": "m", "provider": "p"}, {"mode": "x"}, {"model": "m", "a": "b"})],
            "picks": picks(), "zcode": zcode(),
            "scrub": list(mod.SCRUB_ENV),
        }

    print(json.dumps(asyncio.run(main()), default=str))
    """)


class TestGrokDenyAndScrub(unittest.TestCase):
    r: ClassVar[dict[str, Any]] = {}

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cfg = ROOT / "tests" / ".grok-deny-config.tmp"
        cfg.write_text(CONFIG)
        try:
            p = subprocess.run([*WITH, "-c", PROBE, str(SCRIPT), str(cfg)], check=False, capture_output=True,
                               text=True, timeout=240)
        finally:
            cfg.unlink(missing_ok=True)
        if p.returncode:
            raise AssertionError(p.stderr)
        cls.r = json.loads(p.stdout)

    def test_deny_config_has_no_user_hooks_plugins_mcp_or_allow_rules(self):
        d = self.r["deny"]
        self.assertTrue(d["ok"])
        parsed = d["parsed"]
        for gone in ("hooks", "plugins", "mcp_servers"):
            self.assertNotIn(gone, parsed)
        self.assertEqual(parsed["permission"], {"ask": ["*"]})
        self.assertEqual(parsed["ui"], {"max_thoughts_width": 120})
        self.assertEqual(parsed["models"], {"default": "grok-4.7"})
        self.assertEqual(parsed["compat"]["claude"], {"hooks": False})
        self.assertIn("local-gpt-6-astra", parsed["model"])
        self.assertEqual(parsed["model_providers"]["localproxy"]["base_url"], "http://127.0.0.1:10100/v1")
        self.assertEqual(sorted(d["dropped"]), ["hooks", "mcp_servers", "permission", "plugins", "ui.permission_mode", "ui.yolo"])

    def test_strip_outside_deny_keeps_the_users_permissions(self):
        k = self.r["keep"]
        self.assertTrue(k["ok"])
        self.assertEqual(k["parsed"]["ui"]["permission_mode"], "always-approve")
        self.assertEqual(k["parsed"]["permission"], {"allow": ["Bash(git *)"]})
        for gone in ("hooks", "plugins", "mcp_servers"):
            self.assertNotIn(gone, k["parsed"])

    def test_deny_home_symlinks_everything_but_the_dropped_entries(self):
        s = self.r["strip_deny"]
        self.assertEqual(s["names"], ["auth.json", "config.toml", "models_cache.json", "sessions"])
        self.assertEqual(set(s["links"]), {"auth.json", "models_cache.json", "sessions"})
        self.assertEqual(s["mode"], "0o600")
        self.assertEqual(s["info"]["action"], "stripped")
        self.assertEqual(s["info"]["mcp"], "off")
        self.assertIn("autorename.json", s["info"]["hooks"])
        self.assertEqual(s["env"], {"GROK_HOME": s["env"]["GROK_HOME"]})
        self.assertEqual(s["config"]["permission"], {"ask": ["*"]})

    def test_strip_flag_applies_outside_deny_but_not_without_it(self):
        out = self.r["strip_outside"]
        self.assertIn("GROK_HOME", out["env"])
        self.assertEqual(out["config"]["ui"]["permission_mode"], "always-approve")
        self.assertIn("dropped", out["info"])
        self.assertEqual(self.r["strip_kept"]["info"]["action"], "kept")
        self.assertIn("home", out["info"])
        self.assertEqual(out["info"]["mcp"], "off")

    def test_rotated_token_is_copied_back_only_when_a_valid_newer_file(self):
        s = self.r["sync"]
        self.assertFalse(s["symlink_untouched"])
        self.assertTrue(s["copied"])
        self.assertEqual(s["real"], '{"token": "rotated"}')
        self.assertFalse(s["bad_json_copied"])
        self.assertEqual(s["real_after_bad"], '{"token": "rotated"}')

    def test_deny_run_launches_grok_without_always_approve(self):
        deny, allow = self.r["spawn_grok_deny"], self.r["spawn_grok_all"]
        self.assertEqual(deny["cmd"], ["grok", "agent", "stdio"])
        self.assertEqual(allow["cmd"], ["grok", "agent", "--always-approve", "stdio"])
        self.assertTrue(deny["grok_home"])
        self.assertEqual(deny["user_config"][0]["action"], "stripped")
        # --perm all, headless: the stripped home too (2026-10-15), still with --always-approve
        self.assertTrue(allow["grok_home"])
        self.assertEqual(allow["user_config"][0]["action"], "stripped")
        self.assertEqual(allow["user_config"][0]["home"], allow["grok_home"])
        strip = self.r["spawn_grok_strip"]
        self.assertTrue(strip["grok_home"])
        self.assertIn("--always-approve", strip["cmd"])

    def test_all_headless_runs_a_stripped_home_without_the_ask_rule(self):
        s = self.r["hooks_all"]
        self.assertEqual(s["info"]["action"], "stripped")
        self.assertEqual(s["info"]["mcp"], "kept")
        self.assertEqual(s["info"]["home"], s["env"]["GROK_HOME"])
        self.assertEqual(s["names"], ["auth.json", "config.toml", "models_cache.json", "sessions"])
        c = s["config"]
        for gone in ("hooks", "plugins"):
            self.assertNotIn(gone, c)
        self.assertEqual(c["permission"], {"allow": ["Bash(git *)"]})  # the user's rules, no ask = ["*"]
        self.assertEqual(c["ui"]["permission_mode"], "always-approve")
        self.assertEqual(sorted(c["mcp_servers"]), ["basic-memory", "graft"])
        self.assertEqual(c["models"], {"default": "grok-4.7"})
        self.assertIn("local-gpt-6-astra", c["model"])
        self.assertEqual(sorted(s["info"]["dropped"]), ["hooks", "plugins"])
        self.assertTrue(self.r["hooks_tmpl"]["ok"])

    def test_interactive_grok_keeps_the_users_home(self):
        s = self.r["hooks_interactive"]
        self.assertIsNone(s["info"])
        self.assertNotIn("GROK_HOME", s["env"])

    def test_opt_out_var_keeps_the_users_home_and_logs_it(self):
        s = self.r["hooks_optout"]
        self.assertEqual(s["info"]["action"], "kept")
        self.assertEqual(s["info"]["why"], "ACP_RUN_GROK_USER_HOOKS")
        self.assertTrue(s["info"]["home"].endswith("/.grok"))
        self.assertNotIn("GROK_HOME", s["env"])
        for name in ("hooks_optout_off", "hooks_keep_flag"):
            with self.subTest(name=name):
                off = self.r[name]
                self.assertEqual(off["info"]["action"] == "kept", name == "hooks_keep_flag")
                self.assertEqual("GROK_HOME" in off["env"], name == "hooks_optout_off")

    def test_opt_out_var_does_not_loosen_deny(self):
        s = self.r["hooks_optout_deny"]
        self.assertEqual(s["info"]["action"], "stripped")
        self.assertEqual(s["info"]["mcp"], "off")
        self.assertEqual(s["config"]["permission"], {"ask": ["*"]})
        self.assertNotIn("mcp_servers", s["config"])

    def test_herdr_pane_vars_never_reach_the_agent(self):
        self.assertEqual(self.r["scrub"], ["HERDR_PANE_ID", "HERDR_ENV"])
        for name in ("spawn_grok_deny", "spawn_grok_all", "spawn_codex", "spawn_zcode"):
            with self.subTest(name=name):
                self.assertNotIn("HERDR_PANE_ID", self.r[name]["herdr"])
                self.assertNotIn("HERDR_ENV", self.r[name]["herdr"])
                self.assertIn("HERDR_TAB_ID", self.r[name]["herdr"])  # only the pane is scrubbed

    def test_zcode_gets_its_cli_entry(self):
        self.assertTrue(self.r["zcode"]["found"], self.r["zcode"])
        self.assertIsNone(self.r["zcode"]["missing"])
        self.assertIsNone(self.r["spawn_codex"]["zcode_bin"])

    def test_tripwire_names_the_tool_not_its_id(self):
        self.assertEqual(self.r["tripwire"], "tool 'read_file' ran without a permission request under --perm deny")

    def test_provider_then_model_then_the_rest(self):
        self.assertEqual(self.r["order"], [["provider", "model", "mode", "effort"], ["mode"], ["model", "a"]])

    def test_pick_config_tries_every_option_and_strips_a_suffix(self):
        p = self.r["picks"]
        self.assertEqual(p["second_option"], ["effort", "extra-high"])
        self.assertEqual(p["qwen_suffix"], ["model", "qwen3.8-max(openai)"])
        self.assertEqual(p["qwen_exact"], ["model", "glm-5(openai)"])
        self.assertEqual(p["miss"], "acp-run: no thought_level 'max'; thinking: have: true, false | effort: have: low, extra-high")
        self.assertEqual(p["miss_single"], "acp-run: no model 'kimi'; have: qwen3.8-max(openai), glm-5(openai), qwen3.5-plus(openai)")
        self.assertIn("offers no 'model' config option", p["no_option"])


if __name__ == "__main__":
    unittest.main()
