#!/usr/bin/env python3
"""Tests for tools/acp-run/acp-run --strip-user-config outside --perm deny (2026-10-13).

The strip of the user's plugins, MCP servers and hooks fixed the 2026-10-13 startup
failures; it is not a permission control, so it is now its own switch
(--strip-user-config, env ACP_RUN_STRIP_USER_CONFIG=1) and the SkillOpt-Sleep night runs
--perm all with it (operator 2026-10-13: "I want all of the TUIs and hermes to be able to
run any tools they want"). Under --perm all + strip: opencode gets the stripped config but
no deny permission; agy the stripped GEMINI_HOME and its yolo mode, not deny's default;
zcode a stripped settings file with the user's permission block, its yolo mode and no
ZCODE_ACP_MODE=plan; crush every built-in tool (no disabled_tools), --yolo, a temp
--data-dir and CRUSH_GLOBAL_DATA, and the stripped CRUSH_GLOBAL_CONFIG. Under --perm deny
the flag adds nothing. All against a fake HOME and fake agents: no model is called.
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
SECRET = "sk-STRIP-ALL-789"

USER_OPENCODE = {
    "$schema": "https://opencode.ai/config.json",
    "provider": {"sipb": {"options": {"baseURL": "http://127.0.0.1:8890/api", "apiKey": SECRET},
                          "models": {"qwen3-coder:30b": {}}}},
    "model": "sipb/qwen3-coder:30b",
    "mcp": {"basic-memory": {"type": "remote", "url": "http://127.0.0.1:18796/mcp"}},
    "plugin": ["opencode-foo@1.0"],
    "permission": {"bash": "ask"},
}
USER_ZCODE = {
    "storage": {"dir": "~/.zcode"},
    "features": {"subagent": True, "mcp": True, "skill": True},
    "mcp": {"servers": {"basic-memory": {"url": "http://127.0.0.1:18796/mcp"}}},
    "plugins": {"enabled": True, "enabledPlugins": {"p": True}},
    "hooks": {"enabled": True, "events": {"PreToolUse": [{"command": "x"}]}},
    "permission": {"mode": "auto", "allowedTools": ["Bash"], "autoApproveHighRisk": True},
}
USER_CRUSHRC = textwrap.dedent("""\
    model large fakeprov/fake-model
    mcp add user-mcp --type stdio --command /bin/false
    lsp add gopls --command gopls
    hook add PreToolUse --command /bin/false
    permissions allow bash view
    option request-timeout 600
    """)
USER_CRUSH_JSON = {"providers": {"jsonprov": {"type": "openai-compat"}},
                   "options": {"disabled_tools": ["bash"], "request_timeout": 300},
                   "mcp": {"json-mcp": {"type": "http", "url": "http://127.0.0.1:3/mcp"}}}

PROBE = textwrap.dedent("""\
    import contextlib, importlib.machinery, importlib.util, io, json, os, shutil, sys
    from pathlib import Path
    from types import SimpleNamespace as NS
    loader = importlib.machinery.SourceFileLoader("acp_run", sys.argv[1])
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("acp_run", loader))
    loader.exec_module(mod)
    home, work = Path(sys.argv[2]), Path(sys.argv[3])

    def strip(agent, perm, flag=False, env_flag=None, keep=False, interactive=False, crush_dir=False):
        a = NS(agent=agent, perm=perm, interactive=interactive, keep_user_config=keep,
               strip_user_config=flag)
        env = {"XDG_CONFIG_HOME": str(home / ".config"), "KEEP": "me"}
        old = os.environ.pop("ACP_RUN_STRIP_USER_CONFIG", None)
        if env_flag is not None:
            os.environ["ACP_RUN_STRIP_USER_CONFIG"] = env_flag
        d0 = None
        if crush_dir:
            d0, _, _ = mod.crush_deny_dir(mod.AGENTS["crush"][0], work, env,
                                          tools_off=(perm == "deny"))
        buf = io.StringIO()
        try:
            with contextlib.redirect_stderr(buf):
                d, info = mod.strip_user_config(a, env, d0)
            outside = mod.strips_outside_deny(a)
        finally:
            os.environ.pop("ACP_RUN_STRIP_USER_CONFIG", None)
            if old is not None:
                os.environ["ACP_RUN_STRIP_USER_CONFIG"] = old
        out = {"dir": str(d) if d else None, "info": info, "env": env, "outside": outside,
               "stderr": buf.getvalue()}
        if d:
            p = Path(d)
            if (p / "opencode.json").exists():
                out["opencode_json"] = json.loads((p / "opencode.json").read_text())
            if (p / "cli" / "setting.json").exists():
                out["zcode_settings"] = json.loads((p / "cli" / "setting.json").read_text())
            if (p / "config" / "mcp_config.json").exists():
                out["agy_mcp"] = json.loads((p / "config" / "mcp_config.json").read_text())
            if (p / "config" / "crushrc").exists():
                out["crushrc"] = (p / "config" / "crushrc").read_text()
            if (p / "data" / "crush.json").exists():
                out["crush_data"] = json.loads((p / "data" / "crush.json").read_text())
                out["crush_project"] = json.loads((p / "project" / "crush.json").read_text())
            shutil.rmtree(p)
        return out

    def crush_dir(tools_off):
        env = {}
        cmd = mod.YOLO_CMD["crush"] if not tools_off else mod.AGENTS["crush"][0]
        d, new, info = mod.crush_deny_dir(cmd, work, env, tools_off=tools_off)
        out = {"dir": str(d), "cmd": new, "info": info, "env": env,
               "data": json.loads((d / "data" / "crush.json").read_text()),
               "project": json.loads((d / "project" / "crush.json").read_text())}
        shutil.rmtree(d)
        return out

    def zsettings(fn):
        d = fn()
        out = {"dir": str(d), "settings": json.loads((d / "cli" / "setting.json").read_text()),
               "config": json.loads((d / "cli" / "config.json").read_text())}
        shutil.rmtree(d)
        return out

    print(json.dumps({
        "oc_all": strip("opencode", "all", flag=True),
        "oc_all_env": strip("opencode", "all", env_flag="1"),
        "oc_all_env0": strip("opencode", "all", env_flag="0"),
        "oc_all_noflag": strip("opencode", "all"),
        "oc_deny": strip("opencode", "deny"),
        "oc_deny_flag": strip("opencode", "deny", flag=True),
        "oc_all_keep": strip("opencode", "all", flag=True, keep=True),
        "oc_all_interactive": strip("opencode", "all", flag=True, interactive=True),
        "agy_all": strip("agy", "all", flag=True),
        "zcode_all": strip("zcode", "all", flag=True),
        "zcode_deny_flag": strip("zcode", "deny", flag=True),
        "crush_all": strip("crush", "all", flag=True, crush_dir=True),
        "crush_all_nodir": strip("crush", "all", flag=True),
        "claude_all": strip("claude", "all", flag=True),
        "hermes_all": strip("hermes", "all", flag=True),
        "crush_dir_on": crush_dir(False),
        "crush_dir_off": crush_dir(True),
        "z_strip": zsettings(mod.zcode_strip_settings),
        "z_deny": zsettings(mod.zcode_deny_settings),
        "re": {n: bool(mod.DENY_DIR_RE.fullmatch(n)) for n in (
            "acp-run-opencode-strip-999999-abcd1234", "acp-run-zcode-strip-12-x",
            "acp-run-crush-deny-5-y", "acp-run-crush-yolo-5-y")},
    }))
    """)

# One fake for every agent: records argv, env, the config files it was pointed at and every
# session/set_config_option; needs authenticate when offered (crush); offers a "mode" select
# (default/plan/yolo) like agy and zcode; answers one turn with "ok".
FAKE = textwrap.dedent("""\
    #!/usr/bin/env python3
    import json, os, sys
    from pathlib import Path
    KEYS = ("OPENCODE_CONFIG_DIR", "OPENCODE_CONFIG", "OPENCODE_CONFIG_CONTENT",
            "OPENCODE_DISABLE_PROJECT_CONFIG", "OPENCODE_CONFIG_PROJECT_DISABLE", "GEMINI_HOME",
            "ZCODE_ACP_MODE", "ZCODE_DISALLOWED_TOOLS", "ZCODE_CLI_SETTINGS_FILE",
            "CRUSH_GLOBAL_DATA", "CRUSH_GLOBAL_CONFIG", "CRUSH_SKILLS_DIR", "CRUSH_DISABLE_METRICS")

    def rd(*parts):
        try:
            return Path(*parts).read_text()
        except (OSError, TypeError):
            return None

    e = os.environ.get
    out = {"argv": sys.argv[1:], "env": {k: e(k) for k in KEYS},
           "opencode_json": rd(e("OPENCODE_CONFIG_DIR") or "/x", "opencode.json"),
           "agy_mcp": rd(e("GEMINI_HOME") or "/x", "config", "mcp_config.json"),
           "zcode_settings": rd(e("ZCODE_CLI_SETTINGS_FILE") or "/x"),
           "crushrc": rd(e("CRUSH_GLOBAL_CONFIG") or "/x", "crushrc"),
           "crush_global_json": rd(e("CRUSH_GLOBAL_CONFIG") or "/x", "crush.json"),
           "crush_data_json": rd(e("CRUSH_GLOBAL_DATA") or "/x", "crush.json"),
           "crush_workspace_json": rd(sys.argv[sys.argv.index("--data-dir") + 1], "crush.json")
           if "--data-dir" in sys.argv else None,
           "sets": []}
    fake_out = Path(os.environ["FAKE_OUT"])
    fake_out.write_text(json.dumps(out))
    MODE = {"id": "mode", "name": "Mode", "type": "select", "currentValue": "default",
            "options": [{"value": v, "name": v} for v in ("default", "plan", "yolo")]}

    def send(o):
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", **o}) + "\\n")
        sys.stdout.flush()

    for line in sys.stdin:
        msg = json.loads(line)
        m, i = msg.get("method"), msg.get("id")
        if m == "initialize":
            send({"id": i, "result": {"protocolVersion": 1, "agentCapabilities": {},
                                      "authMethods": [{"id": "local", "name": "Local"}]}})
        elif m == "authenticate":
            send({"id": i, "result": {}})
        elif m == "session/new":
            send({"id": i, "result": {"sessionId": "s1", "configOptions": [MODE]}})
        elif m == "session/set_config_option":
            out["sets"].append(msg.get("params"))
            fake_out.write_text(json.dumps(out))
            send({"id": i, "result": {"configOptions": [MODE]}})
        elif m == "session/prompt":
            send({"method": "session/update", "params": {"sessionId": "s1", "update": {
                "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "ok"}}}})
            send({"id": i, "result": {"stopReason": "end_turn"}})
        elif i is not None:
            send({"id": i, "error": {"code": -32601, "message": "not supported"}})
    """)


def write_home(home: Path) -> None:
    oc = home / ".config" / "opencode"
    (oc / "plugins").mkdir(parents=True)
    (oc / "opencode.json").write_text(json.dumps(USER_OPENCODE))
    (oc / "plugins" / "rtk.ts").write_text("export default {}\n")
    g = home / ".gemini"
    (g / "config" / "plugins" / "flutter").mkdir(parents=True)
    (g / "oauth_creds.json").write_text("{}")
    (g / "config" / "mcp_config.json").write_text(json.dumps({"mcpServers": {"basic-memory": {}}}))
    (g / "config" / "hooks.json").write_text('{"PreToolUse": [{"command": "orca-status"}]}')
    z = home / ".zcode" / "cli"
    z.mkdir(parents=True)
    (z / "setting.json").write_text(json.dumps(USER_ZCODE))
    c = home / ".config" / "crush"
    c.mkdir(parents=True)
    (c / "crushrc").write_text(USER_CRUSHRC)
    (c / "crush.json").write_text(json.dumps(USER_CRUSH_JSON))
    data = home / ".local" / "share" / "crush-acp"
    data.mkdir(parents=True)
    (data / "providers.json").write_text('[{"id": "cached"}]')


# The end-to-end classes put a fake agent named like the real one (opencode, ...) first on PATH.
# PATH holds only that dir and the system dirs, and uv is called by absolute path, so a real
# opencode/agy/crush/zcode in ~/.local/bin, ~/.opencode/bin or Homebrew can never start: no
# network, no credentials, no quota (a real opencode answered "Authentication required" here
# on 2026-10-18 and failed 12 of these tests).
UV = shutil.which("uv") or "uv"


def hermetic_path(fake_bin: Path) -> str:
    return f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin"


def uv_cache() -> str:
    r = subprocess.run(["uv", "cache", "dir"], check=True, capture_output=True, text=True)
    return r.stdout.strip()


class TestStripOutsideDenyConfig(unittest.TestCase):
    r: ClassVar[dict[str, Any]] = {}
    tmp: ClassVar[Path]
    home: ClassVar[Path]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="acp-strip-all-test-"))
        cls.home = cls.tmp / "home"
        write_home(cls.home)
        work = cls.tmp / "work"
        work.mkdir()
        r = subprocess.run(
            ["uv", "run", "--quiet", "--with", SDK, "python", "-I", "-c", PROBE, str(SCRIPT),
             str(cls.home), str(work)],
            check=False, capture_output=True, text=True, timeout=180,
            env={**os.environ, "HOME": str(cls.home), "UV_CACHE_DIR": uv_cache(), "TMPDIR": str(cls.tmp)})
        if r.returncode:
            raise RuntimeError(r.stderr)
        cls.r = json.loads(r.stdout)

    @classmethod
    @override
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # --- opencode: stripped, no deny permission ---
    def test_opencode_perm_all_strip_has_no_deny_permission(self):
        for key in ("oc_all", "oc_all_env"):
            s = self.r[key]
            self.assertTrue(s["outside"], key)
            self.assertIn("acp-run-opencode-strip-", s["dir"], key)
            self.assertEqual(s["env"]["OPENCODE_CONFIG_DIR"], s["dir"], key)
            self.assertEqual(s["env"]["OPENCODE_DISABLE_PROJECT_CONFIG"], "1", key)
            self.assertNotIn("OPENCODE_CONFIG_CONTENT", s["env"], key)
            self.assertNotIn("permission", s["opencode_json"], key)
            self.assertNotIn("mcp", s["opencode_json"], key)
            self.assertIn("sipb", s["opencode_json"]["provider"], key)
            self.assertEqual(s["info"]["action"], "stripped", key)
            self.assertEqual(s["env"]["KEEP"], "me", key)

    def test_without_the_switch_perm_all_is_untouched(self):
        for key in ("oc_all_noflag", "oc_all_env0", "oc_all_interactive"):
            s = self.r[key]
            self.assertIsNone(s["info"], key)
            self.assertEqual(s["env"], {"XDG_CONFIG_HOME": str(self.home / ".config"), "KEEP": "me"}, key)

    def test_keep_user_config_wins(self):
        s = self.r["oc_all_keep"]
        self.assertEqual(s["info"], {"agent": "opencode", "action": "kept", "why": "--keep-user-config"})
        self.assertNotIn("OPENCODE_CONFIG_DIR", s["env"])

    def test_under_deny_the_switch_adds_nothing(self):
        d, f = self.r["oc_deny"], self.r["oc_deny_flag"]
        self.assertFalse(f["outside"])
        self.assertIn("acp-run-opencode-deny-", f["dir"])
        self.assertEqual(d["info"], f["info"])
        self.assertEqual({k: v for k, v in d["env"].items() if k != "OPENCODE_CONFIG_DIR"},
                         {k: v for k, v in f["env"].items() if k != "OPENCODE_CONFIG_DIR"})
        self.assertEqual(d["opencode_json"], f["opencode_json"])
        z = self.r["zcode_deny_flag"]
        self.assertIsNone(z["info"], "zcode's deny strip is run()'s zcode_deny_settings, unchanged")

    # --- agy ---
    def test_agy_perm_all_strip_gets_a_temp_home_without_mcp(self):
        s = self.r["agy_all"]
        self.assertIn("acp-run-agy-strip-", s["dir"])
        self.assertEqual(s["agy_mcp"], {"mcpServers": {}})
        self.assertEqual(s["info"]["mcp_servers"], ["basic-memory"])

    # --- zcode ---
    def test_zcode_perm_all_strip_settings_keep_the_user_permission(self):
        s = self.r["zcode_all"]
        self.assertIn("acp-run-zcode-strip-", s["dir"])
        self.assertTrue(s["env"]["ZCODE_CLI_SETTINGS_FILE"].endswith("/cli/setting.json"))
        self.assertNotIn("ZCODE_ACP_MODE", s["env"])
        st = s["zcode_settings"]
        self.assertEqual(st["permission"], USER_ZCODE["permission"], "no plan mode, no disallowedTools")
        self.assertEqual(st["features"], {"subagent": True, "mcp": False, "skill": False})
        self.assertEqual(st["mcp"], {"servers": {}})
        self.assertFalse(st["plugins"]["enabled"])
        self.assertFalse(st["hooks"]["enabled"])
        self.assertEqual(st["storage"], {"dir": "~/.zcode"})
        self.assertEqual(s["info"]["permission"], "user's")

    def test_zcode_deny_settings_unchanged(self):
        z = self.r["z_deny"]["settings"]
        self.assertIn("acp-run-zcode-deny-", self.r["z_deny"]["dir"])
        self.assertEqual(z["permission"]["mode"], "plan")
        self.assertEqual(z["features"], {"subagent": False, "mcp": False, "skill": False})
        self.assertIn("Bash", z["permission"]["disallowedTools"])
        self.assertIn("acp-run-zcode-strip-", self.r["z_strip"]["dir"])
        self.assertEqual(self.r["z_strip"]["config"], {"hooks": {"enabled": False, "events": {}}})

    # --- crush: every tool on ---
    def test_crush_tools_on_dir_has_no_disabled_tools(self):
        c = self.r["crush_dir_on"]
        self.assertIn("acp-run-crush-strip-", c["dir"])
        for layer in ("data", "project"):
            self.assertEqual(c[layer], {"options": {"auto_lsp": False}}, layer)
        self.assertIn("--yolo", c["cmd"])
        self.assertEqual(c["cmd"][-2:], ["--data-dir", f"{c['dir']}/project"])
        self.assertIn(f"CRUSH_GLOBAL_DATA={c['dir']}/data", c["cmd"])
        self.assertEqual((c["info"]["tools"], c["info"]["disabled_tools"]), ("all", 0))
        off = self.r["crush_dir_off"]
        self.assertIn("acp-run-crush-deny-", off["dir"])
        self.assertIn("bash", off["data"]["options"]["disabled_tools"], "deny is unchanged")
        self.assertIs(off["data"]["permissions"]["skip_requests"], False)

    def test_crush_perm_all_strip_shadows_mcp_lsp_hooks_keeps_tools(self):
        s = self.r["crush_all"]
        self.assertEqual(s["info"]["action"], "stripped")
        rc = s["crushrc"]
        for fn in ("mcp", "lsp", "hook", "permissions"):
            self.assertIn(f"{fn}() {{ :; }}", rc)
        self.assertIn("# acp-run --strip-user-config:", rc)
        self.assertNotIn("disabled_tools", json.dumps(s["crush_data"]))
        self.assertNotIn("disabled_tools", json.dumps(s["crush_project"]))
        self.assertTrue(s["env"]["CRUSH_GLOBAL_CONFIG"].endswith("/config"))
        self.assertEqual(s["info"]["mcp_servers"], ["json-mcp", "user-mcp"])

    def test_crush_without_its_dir_keeps_the_user_config(self):
        s = self.r["crush_all_nodir"]
        self.assertEqual(s["info"]["action"], "kept")
        self.assertNotIn("CRUSH_GLOBAL_CONFIG", s["env"])

    def test_other_agents_are_not_stripped(self):
        for key in ("claude_all", "hermes_all"):
            self.assertIsNone(self.r[key]["info"], key)
            self.assertFalse(self.r[key]["outside"], key)

    def test_strip_dirs_are_swept_like_deny_dirs(self):
        self.assertEqual(self.r["re"], {"acp-run-opencode-strip-999999-abcd1234": True,
                                        "acp-run-zcode-strip-12-x": True,
                                        "acp-run-crush-deny-5-y": True,
                                        "acp-run-crush-yolo-5-y": False})


class TestStripOutsideDenyEndToEnd(unittest.TestCase):
    """The real main()/run() against a fake agent that records what it was given."""

    tmp: ClassVar[Path]
    home: ClassVar[Path]
    bin: ClassVar[Path]
    cache: ClassVar[str]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="acp-strip-all-e2e-"))
        cls.home = cls.tmp / "home"
        write_home(cls.home)
        cls.bin = cls.tmp / "bin"
        cls.bin.mkdir()
        for name in ("opencode", "zcode-acp-server", "crush-acp", "fake-agy"):
            f = cls.bin / name
            f.write_text(FAKE)
            f.chmod(f.stat().st_mode | stat.S_IXUSR)
        cls.cache = uv_cache()
        assert shutil.which("opencode", path=hermetic_path(cls.bin)) == str(cls.bin / "opencode"), "a real opencode is reachable"

    @classmethod
    @override
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_acp(self, agent: str, *args: str, env: dict[str, str] | None = None) -> dict[str, Any]:
        n = len(list(self.tmp.glob("run-*")))
        d = self.tmp / f"run-{n}"
        d.mkdir()
        out, log = d / "seen.json", d / "log.jsonl"
        e = {**os.environ, "HOME": str(self.home), "UV_CACHE_DIR": self.cache,
             "PATH": hermetic_path(self.bin), "FAKE_OUT": str(out), "TMPDIR": str(d),
             "ACP_RUN_AGY_SERVER": str(self.bin / "fake-agy")}
        for k in ("ACP_RUN_KEEP_USER_CONFIG", "ACP_RUN_STRIP_USER_CONFIG", "OPENCODE_CONFIG",
                  "OPENCODE_CONFIG_DIR", "OPENCODE_CONFIG_CONTENT", "CRUSH_GLOBAL_CONFIG",
                  "CRUSH_GLOBAL_DATA", "XDG_CONFIG_HOME", "HERDR_PANE_ID", "HERDR_ENV",
                  "ZCODE_CLI_SETTINGS_FILE", "ZCODE_ACP_MODE"):
            e.pop(k, None)
        e.update(env or {})
        argv = [UV, "run", "--quiet", "--with", SDK, "python", "-I", str(SCRIPT), agent, "-C", str(d),
                "-p", "Reply with the word ok", "--handshake-tries", "1", "--handshake-timeout", "20",
                "--no-fallback", "--timeout", "60", "--log", str(log), *args]
        p = subprocess.run(argv, env=e, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=180, check=False)
        recs = [json.loads(x) for x in log.read_text().splitlines() if x.strip()] if log.exists() else []
        seen = json.loads(out.read_text()) if out.exists() else {}
        for k in ("opencode_json", "agy_mcp", "zcode_settings", "crush_global_json", "crush_data_json",
                  "crush_workspace_json"):
            if seen.get(k):
                seen[k] = json.loads(seen[k])
        return {"rc": p.returncode, "stdout": p.stdout, "stderr": p.stderr, "seen": seen,
                "user_config": [x["data"] for x in recs if x["kind"] == "user_config"],
                "strip_config": [x["data"] for x in recs if x["kind"] == "strip_config"],
                "deny_config": [x["data"] for x in recs if x["kind"] == "deny_config"],
                "set_config": [x["data"] for x in recs if x["kind"] == "set_config"],
                "result": next((x["data"] for x in recs if x["kind"] == "result"), {}),
                "leftovers": [q.name for q in d.iterdir() if q.name.startswith("acp-run-")]}

    def assert_clean_ok(self, r: dict[str, Any]) -> None:
        self.assertEqual(r["rc"], 0, r["stderr"])
        self.assertEqual(r["stdout"].strip(), "ok")
        self.assertEqual(r["leftovers"], [], "the per-run dir is removed after the run")

    def test_opencode_perm_all_strip(self):
        r = self.run_acp("opencode", "--perm", "all", "--strip-user-config")
        self.assert_clean_ok(r)
        s = r["seen"]
        self.assertIn("acp-run-opencode-strip-", s["env"]["OPENCODE_CONFIG_DIR"])
        self.assertIsNone(s["env"]["OPENCODE_CONFIG_CONTENT"], "no {permission: deny} under --perm all")
        self.assertEqual(s["env"]["OPENCODE_DISABLE_PROJECT_CONFIG"], "1")
        self.assertNotIn("permission", s["opencode_json"])
        self.assertNotIn("mcp", s["opencode_json"])
        self.assertEqual(r["user_config"][0]["action"], "stripped")
        self.assertEqual(r["result"]["user_config"], "stripped")

    def test_opencode_env_switch(self):
        r = self.run_acp("opencode", "--perm", "all", env={"ACP_RUN_STRIP_USER_CONFIG": "1"})
        self.assert_clean_ok(r)
        self.assertIn("acp-run-opencode-strip-", r["seen"]["env"]["OPENCODE_CONFIG_DIR"])
        self.assertIsNone(r["seen"]["env"]["OPENCODE_CONFIG_CONTENT"])

    def test_opencode_deny_with_the_switch_is_plain_deny(self):
        r = self.run_acp("opencode", "--perm", "deny", "--strip-user-config")
        self.assert_clean_ok(r)
        s = r["seen"]
        self.assertIn("acp-run-opencode-deny-", s["env"]["OPENCODE_CONFIG_DIR"])
        self.assertEqual(json.loads(s["env"]["OPENCODE_CONFIG_CONTENT"]), {"permission": "deny"})

    def test_agy_perm_all_strip_is_not_in_deny_mode(self):
        r = self.run_acp("agy", "--perm", "all", "--strip-user-config")
        self.assert_clean_ok(r)
        s = r["seen"]
        self.assertIn("acp-run-agy-strip-", s["env"]["GEMINI_HOME"])
        self.assertEqual(s["agy_mcp"], {"mcpServers": {}})
        self.assertEqual(r["set_config"], [{"id": "mode", "value": "yolo"}], "YOLO_SET, not DENY_SET's default")
        d = self.run_acp("agy", "--perm", "deny", "--strip-user-config")
        self.assertEqual(d["set_config"], [{"id": "mode", "value": "default"}], "deny still sets default")

    def test_zcode_perm_all_strip(self):
        r = self.run_acp("zcode", "--perm", "all", "--strip-user-config")
        self.assert_clean_ok(r)
        s = r["seen"]
        self.assertIn("acp-run-zcode-strip-", s["env"]["ZCODE_CLI_SETTINGS_FILE"])
        self.assertIsNone(s["env"]["ZCODE_ACP_MODE"], "no plan mode env")
        self.assertIsNone(s["env"]["ZCODE_DISALLOWED_TOOLS"])
        self.assertEqual(s["zcode_settings"]["permission"], USER_ZCODE["permission"])
        self.assertEqual(s["zcode_settings"]["mcp"], {"servers": {}})
        self.assertEqual(r["set_config"], [{"id": "mode", "value": "yolo"}])

    def test_crush_perm_all_strip_keeps_every_tool(self):
        r = self.run_acp("crush", "--perm", "all", "--strip-user-config")
        self.assert_clean_ok(r)
        s = r["seen"]
        self.assertIn("--yolo", s["argv"])
        self.assertIn("--data-dir", s["argv"])
        self.assertIn("acp-run-crush-strip-", s["argv"][s["argv"].index("--data-dir") + 1])
        self.assertIn("acp-run-crush-strip-", s["env"]["CRUSH_GLOBAL_DATA"])
        self.assertIn("acp-run-crush-strip-", s["env"]["CRUSH_GLOBAL_CONFIG"])
        for k in ("crush_data_json", "crush_workspace_json"):
            self.assertEqual(s[k], {"options": {"auto_lsp": False}}, k)
        self.assertNotIn("disabled_tools", json.dumps(s["crush_global_json"]),
                         "the user's own disabled_tools is not carried into the stripped config")
        for fn in ("mcp", "lsp", "hook"):
            self.assertIn(f"{fn}() {{ :; }}", s["crushrc"])
        self.assertEqual(r["strip_config"][0]["tools"], "all")
        self.assertEqual(r["deny_config"], [])
        self.assertEqual(r["user_config"][0]["action"], "stripped")

    def test_crush_perm_all_without_the_switch_is_unchanged(self):
        r = self.run_acp("crush", "--perm", "all")
        self.assert_clean_ok(r)
        s = r["seen"]
        self.assertNotIn("--data-dir", s["argv"])
        self.assertIsNone(s["env"]["CRUSH_GLOBAL_CONFIG"])
        self.assertEqual((r["strip_config"], r["user_config"]), ([], []))

    def test_crush_keep_user_config_skips_the_dir(self):
        r = self.run_acp("crush", "--perm", "all", "--strip-user-config", "--keep-user-config")
        self.assert_clean_ok(r)
        self.assertNotIn("--data-dir", r["seen"]["argv"])
        self.assertEqual(r["user_config"][0]["action"], "kept")


if __name__ == "__main__":
    unittest.main()
