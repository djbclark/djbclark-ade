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
import signal
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
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
        "baseURL": "http://127.0.0.1:8890/api", "apiKey": SECRET,
        "headers": {"Authorization": "Bearer " + SECRET, "X-Key": "{file:./key.txt}"}},
        "models": {"qwen3-coder:30b": {}}},
        "odd": {"options": {"apiKey": 'ab"odd-literal'}}, "uni": {"options": {"apiKey": "abc\u2028def"}}, "envd": {"options": {"apiKey": "{env:MY_KEY}"}}},
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
        d, info, extra = mod.opencode_deny_config(env)
        raw = (d / "opencode.json").read_text()
        out = {"info": info, "written": json.loads(raw), "raw": raw, "extra": extra,
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

    def oc_error(env):
        try:
            mod.opencode_deny_config(env)
        except ValueError as e:
            return str(e)
        return None

    def strip(agent, perm, interactive=False, keep=False, env_keep=None, xdg=None, mkdtemp_fails=False):
        import contextlib, io as _io
        a = NS(agent=agent, perm=perm, interactive=interactive, keep_user_config=keep)
        env = {"OPENCODE_CONFIG": str(home / "explicit.json"), "KEEP": "me"}
        if xdg:
            env["XDG_CONFIG_HOME"] = str(home / xdg)
        real_mkdtemp = mod.tempfile.mkdtemp
        if mkdtemp_fails:
            def boom(*a, **k):
                raise OSError(28, "No space left on device")
            mod.tempfile.mkdtemp = boom
        errbuf = _io.StringIO()
        old = os.environ.pop("ACP_RUN_KEEP_USER_CONFIG", None)
        if env_keep is not None:
            os.environ["ACP_RUN_KEEP_USER_CONFIG"] = env_keep
        try:
            with contextlib.redirect_stderr(errbuf):
                d, info = mod.strip_user_config(a, env, "PASSED")
        finally:
            mod.tempfile.mkdtemp = real_mkdtemp
            os.environ.pop("ACP_RUN_KEEP_USER_CONFIG", None)
            if old is not None:
                os.environ["ACP_RUN_KEEP_USER_CONFIG"] = old
        out = {"dir": None if d in (None, "PASSED") else str(d), "passed": d == "PASSED",
               "info": info, "env": env, "stderr": errbuf.getvalue()}
        if out["dir"]:
            shutil.rmtree(d)
        return out

    def sweep():
        import os, tempfile, time
        base = Path(tempfile.mkdtemp())
        old = time.time() - 4 * 3600
        target = Path(tempfile.mkdtemp())
        (target / "keep.txt").write_text("x")
        names = {"dead_old": "acp-run-opencode-deny-999999-abcd1234",
                 "nopid_old": "acp-run-agy-deny-odedcp3y",
                 "dead_fresh": "acp-run-zcode-deny-999998-abcd1234",
                 "live_old": f"acp-run-opencode-deny-{os.getppid()}-abcd1234",
                 "other_old": "something-else-old"}
        for n in names.values():
            (base / n).mkdir()
            (base / n / "f").write_text("x")
        link = base / "acp-run-opencode-deny-999997-linkxxxx"
        link.symlink_to(target)
        planted = ["acp-run-x-deny-99999999999-a", "acp-run-opencode-deny-99999999999-abc",
                   "acp-run-agy-deny-999995-abc\\n"]
        for n in planted:
            (base / n).mkdir()
            os.utime(base / n, (old, old))
        afile = base / "acp-run-agy-deny-999996-filexxxx"
        afile.write_text("x")
        for k, n in names.items():
            if k != "dead_fresh":
                os.utime(base / n, (old, old))
        os.utime(link, (old, old), follow_symlinks=False)
        os.utime(afile, (old, old))
        gone = mod.sweep_stale_deny_dirs(str(base))
        left = sorted(x.name for x in base.iterdir())
        out = {"names": names, "gone": sorted(gone), "left": left,
               "target_intact": (target / "keep.txt").exists()}
        shutil.rmtree(base)
        shutil.rmtree(target)
        return out

    def robustness():
        import contextlib, io as _io
        out = {"pid_big": mod._pid_alive(10 ** 20)}
        real = mod.sweep_stale_deny_dirs
        def boom(*a, **k):
            raise RuntimeError("planted")
        mod.sweep_stale_deny_dirs = boom
        buf = _io.StringIO()
        try:
            with contextlib.redirect_stderr(buf):
                out["safe_sweep"] = mod.safe_sweep_stale_deny_dirs()
        finally:
            mod.sweep_stale_deny_dirs = real
        out["safe_sweep_stderr"] = buf.getvalue()
        class Broken:
            def write(self, s):
                raise BrokenPipeError(32, "Broken pipe")
            def flush(self):
                raise BrokenPipeError(32, "Broken pipe")
        calls = []
        real_rmtree = mod.shutil.rmtree
        def failing(path, ignore_errors=False, **k):
            calls.append(ignore_errors)
            if not ignore_errors:
                raise PermissionError(13, "denied")
        mod.shutil.rmtree = failing
        old_err = sys.stderr
        sys.stderr = Broken()
        try:
            mod.remove_deny_dir("/nonexistent/acp-run-opencode-deny-1-x")
            out["broken_stderr"] = "ok"
        except BaseException as e:
            out["broken_stderr"] = repr(e)
        finally:
            sys.stderr = old_err
            mod.shutil.rmtree = real_rmtree
        out["rmtree_calls"] = calls
        return out

    print(json.dumps({
        "robust": robustness(),
        "oc_broken": oc_error({"XDG_CONFIG_HOME": str(home / "broken")}),
        "oc_commas": oc({"XDG_CONFIG_HOME": str(home / "commas")}),
        "jsonc_commas": mod.jsonc_loads('{"a": [1, 2,], "b": {"c": "x,}",}, /* k */ }'),
        "sweep": sweep(),
        "s_oc_broken": strip("opencode", "deny", xdg="broken"),
        "s_oc_mkdtemp": strip("opencode", "deny", mkdtemp_fails=True),
        "s_agy_mkdtemp": strip("agy", "deny", mkdtemp_fails=True),
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
        "s_oc_interactive": strip("opencode", "deny", interactive=True),
        "s_agy_deny": strip("agy", "deny"),
        "s_zcode_deny": strip("zcode", "deny"),
        "s_claude_deny": strip("claude", "deny"),
    }))
    """)

FAKE_AGENT = textwrap.dedent("""\
    #!/usr/bin/python3
    # A minimal ACP agent: records its env, then (FAKE_MODE) exits at once, answers
    # one turn with "ok", or hangs in the turn until cancelled.
    import json, os, sys
    from pathlib import Path
    keys = ("OPENCODE_CONFIG_DIR", "OPENCODE_CONFIG", "OPENCODE_CONFIG_CONTENT",
            "OPENCODE_DISABLE_PROJECT_CONFIG", "OPENCODE_CONFIG_PROJECT_DISABLE", "GEMINI_HOME")
    out = {k: os.environ.get(k) for k in keys}
    out["all_env"] = dict(os.environ)
    out["acp_run_pid"] = os.getppid()
    d = os.environ.get("OPENCODE_CONFIG_DIR")
    if d and Path(d, "opencode.json").exists():
        out["opencode_json"] = json.loads(Path(d, "opencode.json").read_text())
    g = os.environ.get("GEMINI_HOME")
    if g and Path(g, "config", "mcp_config.json").exists():
        out["agy_mcp"] = json.loads(Path(g, "config", "mcp_config.json").read_text())
    fake_out = Path(os.environ["FAKE_OUT"])
    fake_out.write_text(json.dumps(out))
    mode = os.environ.get("FAKE_MODE", "exit")
    if os.environ.get("FAKE_ON_TERM") == "recreate":
        import signal, time

        def on_term(*_):
            # like agy rotating a credential under its home while it is being stopped
            g = os.environ["GEMINI_HOME"]
            os.makedirs(g, exist_ok=True)
            Path(g, "rotated.json").write_text("{}")
            Path(str(fake_out) + ".term").write_text(g)
            time.sleep(0.3)
            os._exit(0)
        signal.signal(signal.SIGTERM, on_term)
    if mode == "exit":
        sys.exit(0)  # die before the handshake: acp-run fails fast, then cleans up

    def send(o):
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", **o}) + "\\n")
        sys.stdout.flush()

    pending = None
    for line in sys.stdin:
        msg = json.loads(line)
        m, i = msg.get("method"), msg.get("id")
        if m == "initialize":
            send({"id": i, "result": {"protocolVersion": 1, "agentCapabilities": {}, "authMethods": []}})
        elif m == "session/new":
            send({"id": i, "result": {"sessionId": "s1", "configOptions": [{"id": "model", "name": "Model", "category": "model", "type": "select", "currentValue": "sipb/test", "options": [{"value": "sipb/test", "name": "Test"}]}]}})
        elif m == "session/prompt":
            cfg = os.environ.get("OPENCODE_CONFIG_DIR") or os.environ.get("GEMINI_HOME")
            Path(str(fake_out) + ".turn").write_text(json.dumps({"cfg": cfg, "exists": bool(cfg) and Path(cfg).exists()}))
            if mode == "hang":
                pending = i
                continue
            send({"method": "session/update", "params": {"sessionId": "s1", "update": {
                "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "ok"}}}})
            send({"id": i, "result": {"stopReason": "end_turn"}})
        elif m == "session/cancel":
            if pending is not None:
                send({"id": pending, "result": {"stopReason": "cancelled"}})
                pending = None
        elif m == "session/set_config_option":
            send({"id": i, "result": {"configOptions": [{"id": "model", "name": "Model", "category": "model", "type": "select", "currentValue": "sipb/test", "options": [{"value": "sipb/test", "name": "Test"}]}]}})
        elif m == "session/set_mode":
            send({"id": i, "result": {}})
        elif i is not None:
            send({"id": i, "error": {"code": -32601, "message": "not supported"}})
    """)


def write_home(home: Path) -> None:
    oc = home / ".config" / "opencode"
    (oc / "plugins").mkdir(parents=True)
    (oc / "opencode.json").write_text(json.dumps(USER_OPENCODE))
    (oc / "opencode.jsonc").write_text(USER_JSONC)
    for name in ("rtk.ts", "moshi-hooks.ts"):
        (oc / "plugins" / name).write_text("export default {}\n")
    (home / "explicit.json").write_text(json.dumps({
        "provider": {"extra": {"npm": "x"}, "sipb": {"options": {"baseURL": "http://127.0.0.1:9999/api"}}},
        "mcp": {"explicit-mcp": {"type": "local"}}}))
    (home / "broken" / "opencode").mkdir(parents=True)
    (home / "broken" / "opencode" / "opencode.json").write_text('{"provider": {"sipb": {}}')
    (home / "commas" / "opencode").mkdir(parents=True)
    (home / "commas" / "opencode" / "opencode.jsonc").write_text(
        '{"model": "sipb/x", // c\n "provider": {"sipb": {"models": {"x": {},},},},}')
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


# The end-to-end classes put a fake agent named like the real one (opencode, ...) first on PATH.
# The child gets only that dir and the system dirs, and uv is called by absolute path, so a real
# opencode/agy/crush/zcode can never start: no network, no credentials, no quota. Two traps
# (2026-10-18): `uv run` prepends the dir of the interpreter it picks to the child's PATH, and for
# Homebrew's python that dir is /opt/homebrew/bin, where a real opencode sits ahead of the fake
# (the real one answered "Authentication required" and failed 12 tests); and the system PATH alone
# leaves uv only /usr/bin's Python 3.9, which cannot resolve the ACP SDK. So UV_PYTHON pins a
# managed interpreter (dir holds no agents), and assert_fakes_win probes the whole chain.
UV = shutil.which("uv") or "uv"


def _uv_python() -> str:
    r = subprocess.run([UV, "python", "find", ">=3.10,<3.15"], check=False, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else sys.executable


def hermetic_env(fake_bin: Path) -> dict[str, str]:
    return {"PATH": f"{fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin", "UV_PYTHON": _uv_python()}


def assert_fakes_win(fake_bin: Path, cache: str, names: tuple[str, ...]) -> None:
    """Resolve each agent name the way acp-run's child sees PATH (inside `uv run`): it must be the fake."""
    env = {**os.environ, "UV_CACHE_DIR": cache, **hermetic_env(fake_bin)}
    code = "import shutil,sys;print(*(shutil.which(n) for n in sys.argv[1:]), sep='\\n')"
    r = subprocess.run([UV, "run", "--quiet", "--with", SDK, "python", "-I", "-c", code, *names],
                       check=False, capture_output=True, text=True, env=env, timeout=180)
    got = r.stdout.split()
    want = [str(fake_bin / n) for n in names]
    assert got == want, f"a real agent binary shadows the fake: {got} != {want}\n{r.stderr}"


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
        self.assertEqual(sorted(w["provider"]), ["envd", "extra", "odd", "sipb", "uni"])
        sipb = w["provider"]["sipb"]
        self.assertEqual(sipb["options"]["baseURL"], "http://127.0.0.1:9999/api", "the override wins")
        self.assertIn("qwen3-coder:30b", sipb["models"], "deep merge keeps models (finding 3)")
        self.assertIn("apiKey", sipb["options"], "deep merge keeps the key reference (finding 3)")
        self.assertIn("explicit-mcp", self.r["oc_explicit"]["info"]["mcp_servers"])
        env = self.r["s_oc_deny"]["env"]
        self.assertNotIn("OPENCODE_CONFIG", env, "the explicit file would load its mcp on top")

    def test_opencode_without_any_user_config_still_starts(self):
        self.assertEqual(self.r["oc_none"]["written"], {})
        self.assertEqual(self.r["oc_none"]["info"]["mcp_servers"], [])

    def test_literal_secrets_go_to_env_not_the_file(self):
        o = self.r["oc"]
        opts = o["written"]["provider"]["sipb"]["options"]
        self.assertTrue(opts["apiKey"].startswith("{env:ACP_RUN_OPENCODE_SECRET_"))
        self.assertTrue(opts["headers"]["Authorization"].startswith("{env:ACP_RUN_OPENCODE_SECRET_"))
        self.assertEqual(o["extra"][opts["apiKey"][5:-1]], SECRET)
        self.assertEqual(o["extra"][opts["headers"]["Authorization"][5:-1]], "Bearer " + SECRET)
        self.assertEqual(o["written"]["provider"]["envd"]["options"]["apiKey"], "{env:MY_KEY}",
                         "an existing reference is left alone")
        # a value {env:} substitution would corrupt (a quote) stays in the 0600 file, and is listed
        self.assertEqual(sorted(o["info"]["secrets_in_file"]),
                         ["provider.odd.options.apiKey", "provider.uni.options.apiKey"],
                         "non-ASCII stays in the file (re-review finding 3)")
        self.assertEqual(o["info"]["secrets_via_env"], 2)
        self.assertNotIn("Bearer " + SECRET, o["raw"])
        self.assertNotIn(json.dumps(SECRET), o["raw"])
        self.assertNotIn(SECRET, json.dumps(o["info"]))

    def test_relative_file_refs_are_made_absolute(self):
        x = self.r["oc"]["written"]["provider"]["sipb"]["options"]["headers"]["X-Key"]
        self.assertEqual(x, "{file:" + str(self.home / ".config" / "opencode" / "key.txt") + "}")

    def test_unparseable_config_refuses_to_strip(self):
        self.assertIn("broken/opencode/opencode.json", self.r["oc_broken"])
        s = self.r["s_oc_broken"]
        self.assertEqual(s["info"]["action"], "kept")
        self.assertIn("broken/opencode/opencode.json", s["info"]["why"])
        self.assertIn("keeping them", s["stderr"])
        self.assertIn("broken/opencode/opencode.json", s["stderr"])
        self.assertNotIn("OPENCODE_CONFIG_DIR", s["env"])
        self.assertTrue(s["passed"])

    def test_trailing_commas_are_accepted(self):
        self.assertEqual(self.r["jsonc_commas"], {"a": [1, 2], "b": {"c": "x,}"}})
        w = self.r["oc_commas"]["written"]
        self.assertEqual(w["model"], "sipb/x")
        self.assertIn("x", w["provider"]["sipb"]["models"])

    def test_build_error_falls_back_to_the_user_config_with_a_stderr_line(self):
        for key, agent in (("s_oc_mkdtemp", "opencode"), ("s_agy_mkdtemp", "agy")):
            s = self.r[key]
            self.assertEqual(s["info"]["action"], "kept", key)
            self.assertIn("No space left", s["info"]["why"], key)
            self.assertIn(f"could not strip {agent}", s["stderr"], key)
            self.assertTrue(s["passed"], key)
            self.assertNotIn("OPENCODE_CONFIG_DIR", s["env"], key)

    def test_planted_huge_pid_names_never_break_the_sweep(self):
        w = self.r["sweep"]
        for n in ("acp-run-x-deny-99999999999-a", "acp-run-opencode-deny-99999999999-abc",
                  "acp-run-agy-deny-999995-abc\n"):
            self.assertIn(n, w["left"], "not matched (bounded pid, fullmatch), so never swept")
        self.assertTrue(self.r["robust"]["pid_big"], "an unbounded pid counts as alive")

    def test_a_failing_sweep_only_warns(self):
        r = self.r["robust"]
        self.assertIsNone(r["safe_sweep"])
        self.assertIn("stale deny-dir sweep failed", r["safe_sweep_stderr"])

    def test_remove_deny_dir_survives_a_broken_stderr(self):
        r = self.r["robust"]
        self.assertEqual(r["broken_stderr"], "ok")
        self.assertEqual(r["rmtree_calls"], [False, True], "still retries with ignore_errors")

    def test_sweep_removes_only_stale_dead_own_dirs(self):
        w = self.r["sweep"]
        n = w["names"]
        self.assertEqual(w["gone"], sorted([n["dead_old"], n["nopid_old"]]))
        for k in ("dead_fresh", "live_old", "other_old"):
            self.assertIn(n[k], w["left"], k)
        self.assertIn("acp-run-opencode-deny-999997-linkxxxx", w["left"], "a symlink is never swept")
        self.assertIn("acp-run-agy-deny-999996-filexxxx", w["left"], "a file is never swept")
        self.assertTrue(w["target_intact"])

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

    def test_perm_all_interactive_and_other_agents_untouched(self):
        for key in ("s_oc_all", "s_oc_interactive", "s_zcode_deny", "s_claude_deny"):
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
        broken = cls.bin / "broken-agent"
        broken.write_text("#!/nonexistent/interpreter\n")
        broken.chmod(broken.stat().st_mode | stat.S_IXUSR)
        cls.cache = uv_cache()
        assert_fakes_win(cls.bin, cls.cache, ("opencode",))

    @classmethod
    @override
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_acp(self, agent: str, *args: str, env: dict[str, str] | None = None, mode: str = "exit",
                sigterm: bool = False, fake: str = "opencode", planted: str = "") -> dict[str, Any]:
        n = len(list(self.tmp.glob("run-*")))
        d = self.tmp / f"run-{n}"
        d.mkdir()
        out, log = d / "env.json", d / "log.jsonl"
        if planted:
            (d / planted).mkdir()
            old = time.time() - 4 * 3600
            os.utime(d / planted, (old, old))
        e = {**os.environ, "HOME": str(self.home), "UV_CACHE_DIR": self.cache,
             **hermetic_env(self.bin), "FAKE_OUT": str(out), "FAKE_MODE": mode,
             "ACP_RUN_AGY_SERVER": str(self.bin / fake), "TMPDIR": str(d)}
        # XDG_CONFIG_HOME too: a host that sets it (GitHub runners) would hide the fake HOME's config
        for k in ("ACP_RUN_KEEP_USER_CONFIG", "OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "XDG_CONFIG_HOME",
                  "HERDR_PANE_ID", "HERDR_ENV"):
            e.pop(k, None)
        e.update(env or {})
        argv = [UV, "run", "--quiet", "--with", SDK, "python", "-I", str(SCRIPT), agent, "-C", str(d),
                "-p", "Reply with the word ok", "--handshake-tries", "1", "--handshake-timeout", "10",
                "--no-fallback", "--timeout", "60", "--log", str(log),
                *(["--model", "sipb/test"] if agent == "opencode" else []), *args]
        proc = subprocess.Popen(argv, env=e, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        live: list[str] = []
        if sigterm:
            turn = Path(str(out) + ".turn")
            deadline = time.time() + 120
            while not turn.exists() and time.time() < deadline and proc.poll() is None:
                time.sleep(0.2)
            live = [p.name for p in d.iterdir() if p.name.startswith("acp-run-")]
            os.kill(json.loads(out.read_text())["acp_run_pid"], signal.SIGTERM)
        stdout, stderr = proc.communicate(timeout=180)
        recs = [json.loads(x) for x in log.read_text().splitlines() if x.strip()] if log.exists() else []
        leftovers = [p.name for p in d.iterdir() if p.name.startswith("acp-run-") and p.name != planted]
        term_file = Path(str(out) + ".term")
        turn_file = Path(str(out) + ".turn")
        return {"rc": proc.returncode, "stdout": stdout, "stderr": stderr,
                "seen": json.loads(out.read_text()) if out.exists() else {},
                "turn": json.loads(turn_file.read_text()) if turn_file.exists() else None,
                "user_config": [x["data"] for x in recs if x["kind"] == "user_config"],
                "result": next((x["data"] for x in recs if x["kind"] == "result"), {}),
                "leftovers": leftovers, "live": live, "planted_left": bool(planted) and (d / planted).exists(),
                "term": term_file.read_text() if term_file.exists() else None}

    def test_successful_turn_keeps_the_config_during_the_turn_then_removes_it(self):
        r = self.run_acp("opencode", "--perm", "deny", mode="turn")
        self.assertEqual(r["rc"], 0, r["stderr"])
        self.assertEqual(r["stdout"].strip(), "ok")
        self.assertTrue(r["turn"]["exists"], "the agent can still read its config during the turn")
        self.assertIn("acp-run-opencode-deny-", r["turn"]["cfg"])
        self.assertEqual(r["result"]["user_config"], "stripped")
        self.assertEqual(r["leftovers"], [])

    def test_a_planted_huge_pid_dir_does_not_stop_a_deny_run(self):
        r = self.run_acp("opencode", "--perm", "deny", mode="turn", planted="acp-run-x-deny-99999999999-a")
        self.assertEqual(r["rc"], 0, r["stderr"])
        self.assertEqual(r["stdout"].strip(), "ok")
        self.assertTrue(r["planted_left"])
        self.assertNotIn("Traceback", r["stderr"])

    def test_agy_home_is_removed_after_the_agent_stopped(self):
        # the fake agy recreates its GEMINI_HOME and writes a file there on SIGTERM;
        # removing the dir before _kill would leave that file behind
        r = self.run_acp("agy", "--perm", "deny", "--mode", "default", mode="hang", sigterm=True,
                         env={"FAKE_ON_TERM": "recreate"})
        self.assertEqual(r["rc"], 143, r["stderr"])
        self.assertIn("acp-run-agy-deny-", r["term"] or "", "the agent wrote under its home while stopping")
        self.assertEqual(r["leftovers"], [])

    def test_sigterm_mid_turn_removes_the_temp_dir(self):
        r = self.run_acp("opencode", "--perm", "deny", mode="hang", sigterm=True)
        self.assertEqual(r["rc"], 143, r["stderr"])
        self.assertEqual(len(r["live"]), 1, "the dir existed while the turn ran")
        self.assertEqual(r["leftovers"], [], "SIGTERM still removes it")

    def test_early_exception_removes_the_temp_dir(self):
        # the agent cannot even be started (missing interpreter): run() fails in
        # create_subprocess_exec, after the temp config was built
        r = self.run_acp("agy", "--perm", "deny", fake="broken-agent")
        self.assertEqual(r["rc"], 1, r["stderr"])
        self.assertEqual(r["user_config"][0]["action"], "stripped")
        self.assertEqual(r["leftovers"], [])

    def test_unparseable_config_keeps_the_user_config_end_to_end(self):
        r = self.run_acp("opencode", "--perm", "deny", env={"XDG_CONFIG_HOME": str(self.home / "broken")})
        self.assertIsNone(r["seen"]["OPENCODE_CONFIG_DIR"])
        self.assertEqual(json.loads(r["seen"]["OPENCODE_CONFIG_CONTENT"]), {"permission": "deny"},
                         "the kept fallback still denies every tool")
        self.assertEqual(r["user_config"][0]["action"], "kept")
        self.assertIn("broken/opencode/opencode.json", r["stderr"])

    def test_deprecated_scoped_ask_and_interactive_runs_get_the_same_env_as_perm_all(self):
        # operator 2026-10-14: --perm scoped:/ask warn once and run as --perm all (ask needs no
        # --interactive any more).
        def env_of(*args: str) -> dict[str, str]:
            r = self.run_acp("opencode", *args)
            self.assertEqual(r["user_config"], [], args)
            warned = r["stderr"].count("is no longer enforced: acp-run runs yolo for every agent"
                                       " (treated as --perm all)")
            self.assertEqual(warned, 1 if args[-1] in ("scoped:.", "ask") else 0, (args, r["stderr"]))
            self.assertNotIn("needs --interactive", r["stderr"], args)
            got = dict(r["seen"]["all_env"])
            for k in ("FAKE_OUT", "TMPDIR", "VIRTUAL_ENV", "PATH", "_"):
                got.pop(k, None)
            return {k: v for k, v in got.items() if not k.startswith("UV_")}
        base = env_of("--perm", "all")
        for args in (("--perm", "scoped:."), ("--perm", "ask"), ("--interactive", "--perm", "ask"),
                     ("--interactive", "--perm", "deny")):
            got = env_of(*args)
            extra = {k: v for k, v in got.items() if base.get(k) != v}
            missing = sorted(set(base) - set(got))
            if args[-1] == "deny":  # DENY_ENV still applies; nothing else may differ
                self.assertEqual(json.loads(extra.pop("OPENCODE_CONFIG_CONTENT")), {"permission": "deny"})
            self.assertEqual((extra, missing), ({}, []), args)
            self.assertFalse([k for k in got if k.startswith("ACP_RUN_OPENCODE_SECRET")], args)

    def test_opencode_deny_gets_the_temp_config_and_it_is_removed(self):
        r = self.run_acp("opencode", "--perm", "deny")
        seen = r["seen"]
        self.assertIsNotNone(seen["OPENCODE_CONFIG_DIR"], r["stderr"])
        self.assertIn("acp-run-opencode-deny-", seen["OPENCODE_CONFIG_DIR"])
        self.assertNotIn("mcp", seen["opencode_json"])
        self.assertIn("sipb", seen["opencode_json"]["provider"])
        self.assertNotIn(SECRET, json.dumps(seen["opencode_json"]["provider"]["sipb"]))
        self.assertEqual(seen["all_env"]["ACP_RUN_OPENCODE_SECRET_0"], SECRET, "the key reaches opencode by env")
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
