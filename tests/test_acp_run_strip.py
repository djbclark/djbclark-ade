#!/usr/bin/env python3
"""Tests for tools/acp-run/acp-run starting opencode and agy without the user's plugins,
MCP servers and hooks under --perm deny (2026-10-13).

On the 2026-10-13 SkillOpt-Sleep night every failed attempt died while the agent started:
opencode's plugins never finished activating and agy's 7 MCP servers were still
connecting. Under --perm deny (not --interactive) acp-run now gives opencode a per-run
OPENCODE_CONFIG_DIR with only provider/model keys and agy a per-run GEMINI_HOME with
empty mcp_config.json/hooks.json/plugins, logs a "user_config" record, removes the temp
dir afterwards, and keeps everything as before under --keep-user-config,
ACP_RUN_KEEP_USER_CONFIG=1, --perm all or --interactive. All against a fake HOME and a
fake agent: no real agent starts and no model is called.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any, ClassVar, override

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("ACP_RUN_SCRIPT", str(ROOT / "tools" / "acp-run" / "acp-run")))
SDK = "agent-client-protocol>=0.9,<1.0"
SECRET = "sk-SECRET-VALUE-123"

USER_OPENCODE = {
    "$schema": "https://opencode.ai/config.json",
    "experimental": {"max_retries": 1, "hook": {"session_completed": [{"command": ["x"]}]}},
    "provider": {"sipb": {"npm": "@ai-sdk/openai-compatible", "options": {
        "baseURL": "http://127.0.0.1:8890/api", "apiKey": SECRET}, "models": {"qwen3-coder:30b": {}}}},
    "model": "sipb/qwen3-coder:30b",
    "mcp": {"basic-memory": {"type": "remote", "url": "http://127.0.0.1:18796/mcp"},
            "exa": {"type": "remote", "url": "https://mcp.exa.ai/mcp",
                    "headers": {"Authorization": "Bearer " + SECRET}}},
    "plugin": ["opencode-foo@1.0", ["opencode-bar", {"token": SECRET}]],
    "agent": {"build": {"prompt": "x"}},
    "permission": {"bash": "allow"},
}
USER_JSONC = """{
  // a comment with "quotes" and a URL http://example.com
  "$schema": "https://opencode.ai/config.json", /* block */
  "small_model": "sipb/qwen3.5:9b",
  "mcp": {"servers": {"jsonc-server": {"type": "local", "command": ["x"]}}}
}
"""

PROBE = textwrap.dedent("""\
    import importlib.machinery, importlib.util, json, os, shutil, stat, sys
    from pathlib import Path
    from types import SimpleNamespace as NS
    loader = importlib.machinery.SourceFileLoader("acp_run", sys.argv[1])
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("acp_run", loader))
    loader.exec_module(mod)
    home = Path(sys.argv[2])

    def mode(p):
        return oct(stat.S_IMODE(p.lstat().st_mode))

    def oc(env):
        d, info = mod.opencode_deny_config(env)
        out = {"info": info, "written": json.loads((d / "opencode.json").read_text()),
               "files": sorted(x.name for x in d.iterdir()), "dir_mode": mode(d),
               "file_mode": mode(d / "opencode.json")}
        shutil.rmtree(d)
        return out

    def agy():
        d, info = mod.agy_deny_home()
        c = d / "config"
        out = {"info": info, "dir_mode": mode(d),
               "top": {x.name: x.is_symlink() for x in d.iterdir()},
               "config": {x.name: x.is_symlink() for x in c.iterdir()},
               "mcp": json.loads((c / "mcp_config.json").read_text()),
               "hooks": json.loads((c / "hooks.json").read_text()),
               "plugins": sorted(x.name for x in (c / "plugins").iterdir()),
               "oauth_target": os.readlink(d / "oauth_creds.json")}
        shutil.rmtree(d)
        out["gone"] = not d.exists()
        g = home / ".gemini"
        out["real_intact"] = {
            "oauth": (g / "oauth_creds.json").read_text(),
            "mcp": json.loads((g / "config" / "mcp_config.json").read_text()),
            "plugins": sorted(x.name for x in (g / "config" / "plugins").iterdir()),
            "hooks": (g / "config" / "hooks.json").read_text()}
        return out

    def strip(agent, perm, interactive=False, keep=False, env_keep=None):
        a = NS(agent=agent, perm=perm, interactive=interactive, keep_user_config=keep)
        env = {"OPENCODE_CONFIG": str(home / "explicit.json"), "KEEP": "me"}
        old = os.environ.pop("ACP_RUN_KEEP_USER_CONFIG", None)
        if env_keep is not None:
            os.environ["ACP_RUN_KEEP_USER_CONFIG"] = env_keep
        try:
            d, info = mod.strip_user_config(a, env, "PASSED")
        finally:
            os.environ.pop("ACP_RUN_KEEP_USER_CONFIG", None)
            if old is not None:
                os.environ["ACP_RUN_KEEP_USER_CONFIG"] = old
        out = {"dir": None if d in (None, "PASSED") else str(d), "passed": d == "PASSED",
               "info": info, "env": env}
        if out["dir"]:
            shutil.rmtree(d)
        return out

    print(json.dumps({
        "oc": oc({"XDG_CONFIG_HOME": str(home / ".config")}),
        "oc_explicit": oc({"XDG_CONFIG_HOME": str(home / ".config"),
                           "OPENCODE_CONFIG": str(home / "explicit.json")}),
        "oc_none": oc({"XDG_CONFIG_HOME": str(home / "nowhere")}),
        "agy": agy(),
        "jsonc": mod.jsonc_loads('{"a": "x // y /* z */", /* c */ "b": 1 // d\\n}'),
        "s_oc_deny": strip("opencode", "deny"),
        "s_oc_flag": strip("opencode", "deny", keep=True),
        "s_oc_env": strip("opencode", "deny", env_keep="1"),
        "s_oc_env0": strip("opencode", "deny", env_keep="0"),
        "s_oc_all": strip("opencode", "all"),
        "s_oc_scoped": strip("opencode", "scoped:."),
        "s_oc_interactive": strip("opencode", "deny", interactive=True),
        "s_agy_deny": strip("agy", "deny"),
        "s_zcode_deny": strip("zcode", "deny"),
        "s_claude_deny": strip("claude", "deny"),
    }))
    """)

FAKE_AGENT = textwrap.dedent("""\
    #!/usr/bin/python3
    import json, os, sys
    from pathlib import Path
    keys = ("OPENCODE_CONFIG_DIR", "OPENCODE_CONFIG", "OPENCODE_CONFIG_CONTENT",
            "OPENCODE_DISABLE_PROJECT_CONFIG", "OPENCODE_CONFIG_PROJECT_DISABLE", "GEMINI_HOME")
    out = {k: os.environ.get(k) for k in keys}
    d = os.environ.get("OPENCODE_CONFIG_DIR")
    if d and Path(d, "opencode.json").exists():
        out["opencode_json"] = json.loads(Path(d, "opencode.json").read_text())
    g = os.environ.get("GEMINI_HOME")
    if g and Path(g, "config", "mcp_config.json").exists():
        out["agy_mcp"] = json.loads(Path(g, "config", "mcp_config.json").read_text())
    Path(os.environ["FAKE_OUT"]).write_text(json.dumps(out))
    sys.exit(0)  # die before the handshake: acp-run fails fast, then cleans up
    """)


def write_home(home: Path) -> None:
    oc = home / ".config" / "opencode"
    (oc / "plugins").mkdir(parents=True)
    (oc / "opencode.json").write_text(json.dumps(USER_OPENCODE))
    (oc / "opencode.jsonc").write_text(USER_JSONC)
    for name in ("rtk.ts", "moshi-hooks.ts"):
        (oc / "plugins" / name).write_text("export default {}\n")
    (home / "explicit.json").write_text(json.dumps({
        "provider": {"extra": {"npm": "x"}}, "mcp": {"explicit-mcp": {"type": "local"}}}))
    g = home / ".gemini"
    (g / "config" / "plugins" / "flutter").mkdir(parents=True)
    (g / "config" / "plugins" / "flutter" / "mcp_config.json").write_text('{"mcpServers": {"dart": {}}}')
    (g / "antigravity-cli").mkdir()
    (g / "oauth_creds.json").write_text('{"refresh_token": "' + SECRET + '"}')
    (g / "settings.json").write_text("{}")
    (g / "config" / "config.json").write_text('{"plugins": {"flutter": {"enabled": true}}}')
    (g / "config" / "mcp_config.json").write_text(json.dumps({"mcpServers": {
        "basic-memory": {"serverUrl": "http://127.0.0.1:18796/mcp"},
        "exa": {"serverUrl": "https://mcp.exa.ai/mcp", "headers": {"x-api-key": SECRET}}}}))
    (g / "config" / "mcp_config.json.bak-old").write_text("{}")
    (g / "config" / "hooks.json").write_text('{"PreToolUse": [{"command": "orca-status"}]}')


def uv_cache() -> str:
    r = subprocess.run(["uv", "cache", "dir"], check=True, capture_output=True, text=True)
    return r.stdout.strip()


class TestStripUserConfig(unittest.TestCase):
    r: ClassVar[dict[str, Any]] = {}
    tmp: ClassVar[Path]
    home: ClassVar[Path]
    cache: ClassVar[str]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="acp-strip-test-"))
        cls.home = cls.tmp / "home"
        write_home(cls.home)
        cls.cache = uv_cache()
        r = subprocess.run(
            ["uv", "run", "--quiet", "--with", SDK, "python", "-I", "-c", PROBE, str(SCRIPT), str(cls.home)],
            check=False, capture_output=True, text=True, timeout=180,
            env={**os.environ, "HOME": str(cls.home), "UV_CACHE_DIR": cls.cache})
        if r.returncode:
            raise RuntimeError(r.stderr)
        cls.r = json.loads(r.stdout)

    @classmethod
    @override
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # --- opencode config construction ---
    def test_opencode_keeps_provider_and_model_only(self):
        w = self.r["oc"]["written"]
        self.assertEqual(sorted(w), ["$schema", "experimental", "model", "provider", "small_model"])
        self.assertEqual(w["provider"]["sipb"]["options"]["baseURL"], "http://127.0.0.1:8890/api")
        self.assertEqual(w["model"], "sipb/qwen3-coder:30b")
        self.assertEqual(w["small_model"], "sipb/qwen3.5:9b", "opencode.jsonc with comments is read")
        self.assertEqual(w["experimental"], {"max_retries": 1}, "experimental hooks are dropped")
        for k in ("mcp", "plugin", "plugins", "agent", "permission"):
            self.assertNotIn(k, w)

    def test_opencode_temp_dir_is_private_and_holds_one_file(self):
        o = self.r["oc"]
        self.assertEqual(o["files"], ["opencode.json"], "no plugins dir in the temp config dir")
        self.assertEqual(o["dir_mode"], "0o700")
        self.assertEqual(o["file_mode"], "0o600")

    def test_opencode_log_info_names_what_was_stripped_without_values(self):
        i = self.r["oc"]["info"]
        self.assertEqual(i["action"], "stripped")
        self.assertEqual(i["mcp_servers"], ["basic-memory", "exa", "jsonc-server"])
        self.assertIn("plugins/rtk.ts", i["plugins"])
        self.assertIn("plugins/moshi-hooks.ts", i["plugins"])
        self.assertIn("opencode-foo@1.0", i["plugins"])
        self.assertIn("opencode-bar", i["plugins"])
        self.assertIn("mcp", i["dropped_keys"])
        self.assertIn("experimental.hook", i["dropped_keys"])
        self.assertEqual(i["project_config"], "off")
        self.assertNotIn(SECRET, json.dumps(i), "the log record carries names, never values")

    def test_opencode_explicit_config_file_is_merged_then_unset(self):
        w = self.r["oc_explicit"]["written"]
        self.assertEqual(sorted(w["provider"]), ["extra", "sipb"])
        self.assertIn("explicit-mcp", self.r["oc_explicit"]["info"]["mcp_servers"])
        env = self.r["s_oc_deny"]["env"]
        self.assertNotIn("OPENCODE_CONFIG", env, "the explicit file would load its mcp on top")

    def test_opencode_without_any_user_config_still_starts(self):
        self.assertEqual(self.r["oc_none"]["written"], {})
        self.assertEqual(self.r["oc_none"]["info"]["mcp_servers"], [])

    def test_jsonc_comments_outside_strings_only(self):
        self.assertEqual(self.r["jsonc"], {"a": "x // y /* z */", "b": 1})

    # --- agy home construction ---
    def test_agy_home_has_no_mcp_hooks_or_plugins(self):
        a = self.r["agy"]
        self.assertEqual(a["mcp"], {"mcpServers": {}})
        self.assertEqual(a["hooks"], {})
        self.assertEqual(a["plugins"], [])
        self.assertFalse(a["config"]["mcp_config.json"])
        self.assertFalse(a["config"]["hooks.json"])
        self.assertFalse(a["config"]["plugins"])
        self.assertNotIn("mcp_config.json.bak-old", a["config"])
        self.assertTrue(a["config"]["config.json"], "the rest of config/ is linked")
        self.assertEqual(a["dir_mode"], "0o700")

    def test_agy_home_keeps_the_login(self):
        a = self.r["agy"]
        self.assertTrue(a["top"]["oauth_creds.json"])
        self.assertTrue(a["top"]["antigravity-cli"])
        self.assertTrue(a["oauth_target"].endswith(".gemini/oauth_creds.json"))
        self.assertNotIn("config", [k for k, v in a["top"].items() if v], "config/ is a real dir")

    def test_agy_info_and_cleanup_leave_the_real_home_intact(self):
        a = self.r["agy"]
        self.assertEqual(a["info"]["mcp_servers"], ["basic-memory", "exa"])
        self.assertEqual(a["info"]["plugins"], ["flutter"])
        self.assertNotIn(SECRET, json.dumps(a["info"]))
        self.assertTrue(a["gone"])
        real = a["real_intact"]
        self.assertIn(SECRET, real["oauth"])
        self.assertEqual(sorted(real["mcp"]["mcpServers"]), ["basic-memory", "exa"])
        self.assertEqual(real["plugins"], ["flutter"])
        self.assertIn("orca-status", real["hooks"])

    # --- when it applies, and the override ---
    def test_deny_strips_opencode_env(self):
        s = self.r["s_oc_deny"]
        self.assertIsNotNone(s["dir"])
        self.assertEqual(s["env"]["OPENCODE_CONFIG_DIR"], s["dir"])
        self.assertEqual(s["env"]["OPENCODE_DISABLE_PROJECT_CONFIG"], "1")
        self.assertEqual(s["env"]["OPENCODE_CONFIG_PROJECT_DISABLE"], "1")
        self.assertEqual(s["env"]["KEEP"], "me")

    def test_override_flag_and_env_keep_user_config(self):
        for key, why in (("s_oc_flag", "--keep-user-config"), ("s_oc_env", "ACP_RUN_KEEP_USER_CONFIG")):
            s = self.r[key]
            self.assertEqual(s["info"], {"agent": "opencode", "action": "kept", "why": why})
            self.assertTrue(s["passed"])
            self.assertNotIn("OPENCODE_CONFIG_DIR", s["env"])
            self.assertIn("OPENCODE_CONFIG", s["env"])
        self.assertEqual(self.r["s_oc_env0"]["info"]["action"], "stripped", "=0 does not keep")

    def test_perm_all_scoped_interactive_and_other_agents_untouched(self):
        for key in ("s_oc_all", "s_oc_scoped", "s_oc_interactive", "s_zcode_deny", "s_claude_deny"):
            s = self.r[key]
            self.assertIsNone(s["info"], key)
            self.assertTrue(s["passed"], key)
            self.assertEqual(s["env"], {"OPENCODE_CONFIG": str(self.home / "explicit.json"), "KEEP": "me"}, key)

    def test_agy_deny_returns_a_temp_home(self):
        s = self.r["s_agy_deny"]
        self.assertIsNotNone(s["dir"])
        self.assertEqual(s["info"]["action"], "stripped")


class TestStripEndToEnd(unittest.TestCase):
    """The real main()/run() against a fake agent that records its env and exits."""

    tmp: ClassVar[Path]
    home: ClassVar[Path]
    bin: ClassVar[Path]
    cache: ClassVar[str]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="acp-strip-e2e-"))
        cls.home = cls.tmp / "home"
        write_home(cls.home)
        cls.bin = cls.tmp / "bin"
        cls.bin.mkdir()
        fake = cls.bin / "opencode"
        fake.write_text(FAKE_AGENT)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        cls.cache = uv_cache()

    @classmethod
    @override
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_acp(self, agent: str, *args: str, env: dict[str, str] | None = None) -> dict[str, Any]:
        n = len(list(self.tmp.glob("run-*")))
        d = self.tmp / f"run-{n}"
        d.mkdir()
        out, log = d / "env.json", d / "log.jsonl"
        e = {**os.environ, "HOME": str(self.home), "UV_CACHE_DIR": self.cache,
             "PATH": f"{self.bin}:{os.environ['PATH']}", "FAKE_OUT": str(out),
             "ACP_RUN_AGY_SERVER": str(self.bin / "opencode"), "TMPDIR": str(d)}
        e.pop("ACP_RUN_KEEP_USER_CONFIG", None)
        e.pop("OPENCODE_CONFIG", None)
        e.pop("OPENCODE_CONFIG_DIR", None)
        e.update(env or {})
        r = subprocess.run(
            ["uv", "run", "--quiet", "--with", SDK, "python", "-I", str(SCRIPT), agent, "-C", str(d),
             "-p", "Reply with the word ok", "--handshake-tries", "1", "--handshake-timeout", "10",
             "--no-fallback", "--log", str(log), *args],
            check=False, capture_output=True, text=True, timeout=180, env=e)
        recs = [json.loads(x) for x in log.read_text().splitlines() if x.strip()]
        leftovers = [p.name for p in d.iterdir() if p.name.startswith("acp-run-")]
        return {"rc": r.returncode, "stderr": r.stderr, "seen": json.loads(out.read_text()),
                "user_config": [x["data"] for x in recs if x["kind"] == "user_config"],
                "result": next((x["data"] for x in recs if x["kind"] == "result"), {}),
                "leftovers": leftovers}

    def test_opencode_deny_gets_the_temp_config_and_it_is_removed(self):
        r = self.run_acp("opencode", "--perm", "deny")
        seen = r["seen"]
        self.assertIsNotNone(seen["OPENCODE_CONFIG_DIR"], r["stderr"])
        self.assertIn("acp-run-opencode-deny-", seen["OPENCODE_CONFIG_DIR"])
        self.assertNotIn("mcp", seen["opencode_json"])
        self.assertIn("sipb", seen["opencode_json"]["provider"])
        self.assertEqual(json.loads(seen["OPENCODE_CONFIG_CONTENT"]), {"permission": "deny"})
        self.assertEqual(seen["OPENCODE_DISABLE_PROJECT_CONFIG"], "1")
        self.assertEqual(len(r["user_config"]), 1)
        self.assertEqual(r["user_config"][0]["action"], "stripped")
        self.assertIn("plugins/rtk.ts", r["user_config"][0]["plugins"])
        self.assertNotIn(SECRET, json.dumps(r["user_config"]))
        self.assertEqual(r["leftovers"], [], "the temp config dir is removed after the run")
        self.assertFalse(Path(seen["OPENCODE_CONFIG_DIR"]).exists())

    def test_opencode_deny_keep_user_config_flag(self):
        r = self.run_acp("opencode", "--perm", "deny", "--keep-user-config")
        self.assertIsNone(r["seen"]["OPENCODE_CONFIG_DIR"])
        self.assertEqual(json.loads(r["seen"]["OPENCODE_CONFIG_CONTENT"]), {"permission": "deny"})
        self.assertEqual(r["user_config"], [{"agent": "opencode", "action": "kept", "why": "--keep-user-config"}])

    def test_opencode_deny_keep_user_config_env(self):
        r = self.run_acp("opencode", "--perm", "deny", env={"ACP_RUN_KEEP_USER_CONFIG": "1"})
        self.assertIsNone(r["seen"]["OPENCODE_CONFIG_DIR"])
        self.assertEqual(r["user_config"][0]["why"], "ACP_RUN_KEEP_USER_CONFIG")

    def test_opencode_perm_all_is_untouched(self):
        r = self.run_acp("opencode", "--perm", "all")
        seen = r["seen"]
        self.assertIsNone(seen["OPENCODE_CONFIG_DIR"])
        self.assertIsNone(seen["OPENCODE_CONFIG_CONTENT"])
        self.assertIsNone(seen["OPENCODE_DISABLE_PROJECT_CONFIG"])
        self.assertEqual(r["user_config"], [])
        self.assertNotIn("user_config", r["result"])

    def test_agy_deny_gets_a_temp_home_without_mcp(self):
        r = self.run_acp("agy", "--perm", "deny")
        seen = r["seen"]
        self.assertIn("acp-run-agy-deny-", seen["GEMINI_HOME"], r["stderr"])
        self.assertEqual(seen["agy_mcp"], {"mcpServers": {}})
        self.assertEqual(r["user_config"][0]["mcp_servers"], ["basic-memory", "exa"])
        self.assertEqual(r["leftovers"], [])
        self.assertFalse(Path(seen["GEMINI_HOME"]).exists())
        self.assertTrue((self.home / ".gemini" / "oauth_creds.json").exists())

    def test_agy_perm_all_keeps_the_shared_shadow_home(self):
        r = self.run_acp("agy", "--perm", "all")
        self.assertEqual(r["seen"]["GEMINI_HOME"], str(self.home / ".local/share/agy-acp-home"))
        self.assertEqual(sorted(r["seen"]["agy_mcp"]["mcpServers"]), ["basic-memory", "exa"])
        self.assertEqual(r["user_config"], [])


if __name__ == "__main__":
    unittest.main()
