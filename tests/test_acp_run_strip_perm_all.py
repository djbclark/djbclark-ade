#!/usr/bin/env python3
"""Tests for tools/acp-run/acp-run --strip-user-config outside --perm deny (2026-10-13).

The strip of the user's plugins, MCP servers and hooks fixed the 2026-10-13 startup
failures; it is not a permission control, so it is now its own switch
(--strip-user-config, env ACP_RUN_STRIP_USER_CONFIG=1) and the SkillOpt-Sleep night runs
--perm all with it (operator 2026-10-13: "I want all of the TUIs and hermes to be able to
run any tools they want"). Under --perm all + strip: opencode gets the stripped config but
no deny permission. Under --perm deny the flag adds nothing. (The agy, zcode and crush cases
were removed with those agents, 2026-11-06.) All against a fake HOME and fake agents: no model is called.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
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
PROBE = textwrap.dedent("""\
    import contextlib, importlib.machinery, importlib.util, io, json, os, shutil, sys
    from pathlib import Path
    from types import SimpleNamespace as NS
    loader = importlib.machinery.SourceFileLoader("acp_run", sys.argv[1])
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("acp_run", loader))
    loader.exec_module(mod)
    home, work = Path(sys.argv[2]), Path(sys.argv[3])

    def strip(agent, perm, flag=False, env_flag=None, keep=False, interactive=False):
        a = NS(agent=agent, perm=perm, interactive=interactive, keep_user_config=keep,
               strip_user_config=flag)
        env = {"XDG_CONFIG_HOME": str(home / ".config"), "KEEP": "me"}
        old = os.environ.pop("ACP_RUN_STRIP_USER_CONFIG", None)
        if env_flag is not None:
            os.environ["ACP_RUN_STRIP_USER_CONFIG"] = env_flag
        d0 = None
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
            shutil.rmtree(p)
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
        "claude_all": strip("claude", "all", flag=True),
        "hermes_all": strip("hermes", "all", flag=True),
        "re": {n: bool(mod.DENY_DIR_RE.fullmatch(n)) for n in (
            "acp-run-opencode-strip-999999-abcd1234", "acp-run-hermes-strip-12-x",
            "acp-run-opencode-yolo-5-y")},
    }))
    """)

# One fake agent: records argv, env, the config files it was pointed at and every
# session/set_config_option; offers a "mode" select; answers one turn with "ok".
FAKE = textwrap.dedent("""\
    #!/usr/bin/env python3
    import json, os, sys
    from pathlib import Path
    KEYS = ("OPENCODE_CONFIG_DIR", "OPENCODE_CONFIG", "OPENCODE_CONFIG_CONTENT",
            "OPENCODE_DISABLE_PROJECT_CONFIG", "OPENCODE_CONFIG_PROJECT_DISABLE")

    MODEL = {"id": "model", "name": "Model", "category": "model", "type": "select", "currentValue": "sipb/test", "options": [{"value": "sipb/test", "name": "Test"}, {"value": "opencode-go/kimi-k3", "name": "Kimi"}]}

    def rd(*parts):
        try:
            return Path(*parts).read_text()
        except (OSError, TypeError):
            return None

    e = os.environ.get
    out = {"argv": sys.argv[1:], "env": {k: e(k) for k in KEYS},
           "opencode_json": rd(e("OPENCODE_CONFIG_DIR") or "/x", "opencode.json"),
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
            send({"id": i, "result": {"sessionId": "s1", "configOptions": [MODE, MODEL]}})
        elif m == "session/set_config_option":
            if msg["params"].get("configId") == "model":
                MODEL["currentValue"] = msg["params"]["value"]
            out["sets"].append(msg.get("params"))
            fake_out.write_text(json.dumps(out))
            send({"id": i, "result": {"configOptions": [MODE, MODEL]}})
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


# The end-to-end classes put a fake agent named like the real one (opencode, ...) first on PATH.
# The child gets only that dir and the system dirs, and uv is called by absolute path, so a real
# opencode can never start: no network, no credentials, no quota. Two traps
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

    def test_other_agents_are_not_stripped(self):
        for key in ("claude_all", "hermes_all"):
            self.assertIsNone(self.r[key]["info"], key)
            self.assertFalse(self.r[key]["outside"], key)

    def test_strip_dirs_are_swept_like_deny_dirs(self):
        self.assertEqual(self.r["re"], {"acp-run-opencode-strip-999999-abcd1234": True,
                                        "acp-run-hermes-strip-12-x": True,
                                        "acp-run-opencode-yolo-5-y": False})


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
        for name in ("opencode",):
            f = cls.bin / name
            f.write_text(FAKE)
            f.chmod(f.stat().st_mode | stat.S_IXUSR)
        cls.cache = uv_cache()
        assert_fakes_win(cls.bin, cls.cache, ("opencode",))

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
             **hermetic_env(self.bin), "FAKE_OUT": str(out), "TMPDIR": str(d)}
        for k in ("ACP_RUN_KEEP_USER_CONFIG", "ACP_RUN_STRIP_USER_CONFIG", "OPENCODE_CONFIG",
                  "OPENCODE_CONFIG_DIR", "OPENCODE_CONFIG_CONTENT",
                  "XDG_CONFIG_HOME", "HERDR_PANE_ID", "HERDR_ENV"):
            e.pop(k, None)
        e.update(env or {})
        argv = [UV, "run", "--quiet", "--with", SDK, "python", "-I", str(SCRIPT), agent, "-C", str(d),
                "-p", "Reply with the word ok", "--handshake-tries", "1", "--handshake-timeout", "20",
                "--no-fallback", "--timeout", "60", "--log", str(log),
                *(["--model", "sipb/test"] if agent == "opencode" else []), *args]
        p = subprocess.run(argv, env=e, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=180, check=False)
        recs = [json.loads(x) for x in log.read_text().splitlines() if x.strip()] if log.exists() else []
        seen = json.loads(out.read_text()) if out.exists() else {}
        for k in ("opencode_json",):
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

    def test_fuzzy_go_alias_is_refused_after_resolution_before_prompt(self):
        r = self.run_acp("opencode", "--model", "go/kimi-k3", "--perm", "all", "--strip-user-config")
        self.assertEqual(r["rc"], 1, r["stderr"])
        self.assertIn("exact applied provider/model", r["stderr"])
        self.assertEqual(r["stdout"].strip(), "")

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

if __name__ == "__main__":
    unittest.main()
