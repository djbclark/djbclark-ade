#!/usr/bin/env python3
"""Tests for tools/acp-run/acp-run's --perm deny for crush (2026-10-13).

crush-acp asks permission for bash/edit/write/fetch/download but runs its read-only tools
(glob, grep, ls, view, ...) unasked, so the 2026-10-13 03:43 SkillOpt-Sleep canary tripped
(exit 77) on a `glob`. Under --perm deny acp-run now gives crush a per-run temp dir whose
data and workspace config layers disable every built-in tool (options.disabled_tools =
CRUSH_TOOLS), moves --data-dir out of -C, disables MCP servers named by project configs,
and (unless --keep-user-config) points CRUSH_GLOBAL_CONFIG at a crushrc that sources the
user's crushrc with mcp/lsp/hook/permissions shadowed, with no global context or skills.

acp-run imports the ACP SDK, so it is loaded in a `uv run --with` subprocess against a fake
HOME. The end-to-end class drives the real main()/run() against a fake `crush-acp` on PATH.
Two optional checks use the real crush-acp build when installed (no model is called): its
allToolNames() matches CRUSH_TOOLS, and its config loader accepts the stripped crushrc.
"""
from __future__ import annotations

import json
import os
import re
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
SECRET = "sk-CRUSH-SECRET-456"
CRUSH_SRC = Path.home() / "src" / "crush-acp" / "internal" / "config" / "config.go"
CRUSH_BIN = shutil.which("crush-acp") or str(Path.home() / ".local" / "bin" / "crush-acp")

USER_CRUSHRC = textwrap.dedent(f"""\
    provider add fakeprov \\
      --name "Fake" \\
      --type openai-compat \\
      --base-url "http://127.0.0.1:1/api" \\
      --api-key "{SECRET}"
    model add fakeprov/fake-model --name "Fake Model" --context-window 32768
    model large fakeprov/fake-model
    model small fakeprov/fake-model
    mcp add user-mcp --type stdio --command /bin/false
    lsp add gopls --command gopls
    hook add PreToolUse --command /bin/false
    permissions yolo
    permissions allow bash view
    option context-path /etc/passwd
    option skill-path /tmp
    option request-timeout 600
    option disable-skill foo
    """)
USER_CRUSH_JSON = {
    "$schema": "https://charm.land/crush.json",
    "providers": {"jsonprov": {"type": "openai-compat", "base_url": "http://127.0.0.1:2/v1",
                               "api_key": SECRET, "models": [{"id": "m"}]},
                  "envprov": {"type": "openai-compat", "api_key": "$ENV_KEY"}},
    "models": {"large": {"provider": "fakeprov", "model": "fake-model"}},
    "mcp": {"json-mcp": {"type": "http", "url": "http://127.0.0.1:3/mcp"}},
    "lsp": {"go": {"command": "gopls"}},
    "hooks": {"PreToolUse": [{"command": "x"}]},
    "permissions": {"skip_requests": True},
    "options": {"request_timeout": 300, "context_paths": ["/etc/passwd"], "skills_paths": ["/tmp"]},
}

PROBE = textwrap.dedent("""\
    import contextlib, importlib.machinery, importlib.util, io, json, os, shutil, stat, sys
    from pathlib import Path
    from types import SimpleNamespace as NS
    loader = importlib.machinery.SourceFileLoader("acp_run", sys.argv[1])
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("acp_run", loader))
    loader.exec_module(mod)
    home, work = Path(sys.argv[2]), Path(sys.argv[3])

    def mode(p):
        return oct(stat.S_IMODE(p.lstat().st_mode))

    def deny(root, cmd=None, env=None):
        env = dict(env or {})
        cmd = cmd or mod.AGENTS["crush"][0]
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            d, new, info = mod.crush_deny_dir(cmd, root, env)
        out = {"cmd": new, "info": info, "env": env, "dir_mode": mode(d),
               "data": json.loads((d / "data" / "crush.json").read_text()),
               "project": json.loads((d / "project" / "crush.json").read_text()),
               "file_mode": mode(d / "data" / "crush.json"),
               "files": sorted(str(p.relative_to(d)) for p in d.rglob("*")),
               "providers": (d / "data" / "providers.json").read_text()
               if (d / "data" / "providers.json").exists() else None, "dir": str(d),
               "stderr": buf.getvalue()}
        shutil.rmtree(d)
        return out

    def strip(env, keep=False, interactive=False, deny_dir="make"):
        a = NS(agent="crush", perm="deny", interactive=interactive, keep_user_config=keep)
        env = dict(env)
        d = None
        if deny_dir == "make":
            d, _, _ = mod.crush_deny_dir(mod.AGENTS["crush"][0], work, {})
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            got, info = mod.strip_user_config(a, env, d)
        out = {"info": info, "env": env, "stderr": buf.getvalue(), "same_dir": got == d}
        if d is not None:
            cfg = d / "config"
            out["files"] = sorted(str(p.relative_to(d)) for p in d.rglob("*"))
            if (cfg / "crushrc").exists():
                out["crushrc"] = (cfg / "crushrc").read_text()
                out["crushrc_mode"] = mode(cfg / "crushrc")
            if (cfg / "crush.json").exists():
                out["crush_json"] = json.loads((cfg / "crush.json").read_text())
            shutil.rmtree(d)
        return out

    data = home / "data"
    data.mkdir(exist_ok=True)
    (data / "providers.json").write_text('[{"id": "cached"}]')
    cmd = ["env", "CRUSH_DISABLE_METRICS=1", f"CRUSH_GLOBAL_DATA={data}", "crush-acp", "acp"]
    print(json.dumps({
        "plain": deny(work, cmd),
        "no_data_arg": deny(work, ["crush-acp", "acp"], {"CRUSH_GLOBAL_DATA": str(home / "nowhere")}),
        "project": deny(home / "repo" / "sub", cmd),
        "tools": list(mod.CRUSH_TOOLS),
        "s_deny": strip({"XDG_CONFIG_HOME": str(home / ".config")}),
        "s_explicit": strip({"CRUSH_GLOBAL_CONFIG": str(home / "explicit")}),
        "s_none": strip({"XDG_CONFIG_HOME": str(home / "nowhere")}),
        "s_bypass": strip({"XDG_CONFIG_HOME": str(home / "bypass")}),
        "s_unset": strip({"XDG_CONFIG_HOME": str(home / "unset")}),
        "s_envrun": strip({"XDG_CONFIG_HOME": str(home / "envrun")}),
        "s_exec": strip({"XDG_CONFIG_HOME": str(home / "exec")}),
        "s_comment": strip({"XDG_CONFIG_HOME": str(home / "comment")}),
        "s_badjson": strip({"XDG_CONFIG_HOME": str(home / "badjson")}),
        "s_keep": strip({"XDG_CONFIG_HOME": str(home / ".config")}, keep=True),
        "s_interactive": strip({"XDG_CONFIG_HOME": str(home / ".config")}, interactive=True),
        "s_nodir": strip({"XDG_CONFIG_HOME": str(home / ".config")}, deny_dir=None),
    }))
    """)

FAKE_CRUSH = textwrap.dedent("""\
    #!/usr/bin/env python3
    # A minimal crush-acp: records argv/env and the config files it was given, needs
    # authenticate("local") like the real one, answers one turn with "ok".
    import json, os, sys
    from pathlib import Path
    out = {"argv": sys.argv[1:], "env": {k: os.environ.get(k) for k in (
        "CRUSH_GLOBAL_DATA", "CRUSH_GLOBAL_CONFIG", "CRUSH_SKILLS_DIR", "CRUSH_DISABLE_METRICS")}}
    for k in ("CRUSH_GLOBAL_DATA", "CRUSH_GLOBAL_CONFIG"):
        f = Path(os.environ.get(k) or "/nonexistent") / "crush.json"
        out[k + "_json"] = json.loads(f.read_text()) if f.exists() else None
    if "--data-dir" in sys.argv:
        f = Path(sys.argv[sys.argv.index("--data-dir") + 1]) / "crush.json"
        out["workspace_json"] = json.loads(f.read_text()) if f.exists() else None
    Path(os.environ["FAKE_OUT"]).write_text(json.dumps(out))

    def send(o):
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", **o}) + "\\n")
        sys.stdout.flush()

    authed = False
    for line in sys.stdin:
        msg = json.loads(line)
        m, i = msg.get("method"), msg.get("id")
        if m == "initialize":
            send({"id": i, "result": {"protocolVersion": 1, "agentCapabilities": {},
                                      "authMethods": [{"id": "local", "name": "Local"}]}})
        elif m == "authenticate":
            authed = True
            send({"id": i, "result": {}})
        elif m == "session/new":
            if not authed:
                send({"id": i, "error": {"code": -32000, "message": "authentication required"}})
                continue
            send({"id": i, "result": {"sessionId": "s1"}})
        elif m == "session/prompt":
            send({"method": "session/update", "params": {"sessionId": "s1", "update": {
                "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "ok"}}}})
            send({"id": i, "result": {"stopReason": "end_turn"}})
        elif i is not None:
            send({"id": i, "error": {"code": -32601, "message": "not supported"}})
    """)


def write_home(home: Path) -> None:
    cfg = home / ".config" / "crush"
    cfg.mkdir(parents=True)
    (cfg / "crushrc").write_text(USER_CRUSHRC)
    (cfg / "crush.json").write_text(json.dumps(USER_CRUSH_JSON))
    (cfg / "CRUSH.md").write_text("Always use tools.\n")
    (home / "explicit").mkdir()
    (home / "explicit" / "crushrc").write_text("option request-timeout 5\n")
    for name, text in (("bypass", "command mcp add sneaky --type stdio --command x\n"),
                       ("unset", "unset -f mcp\nmcp add sneaky --type stdio\n"),
                       ("envrun", "env FOO=1 mcp add sneaky --type stdio --command x\n"),
                       ("exec", "x=$(exec permissions yolo)\n"),
                       ("comment", "# use command mcp or env ... option here; unset -f is bad\n"
                                   "option request-timeout 5  # the env option\n")):
        (home / name / "crush").mkdir(parents=True)
        (home / name / "crush" / "crushrc").write_text(text)
    (home / "badjson" / "crush").mkdir(parents=True)
    (home / "badjson" / "crush" / "crush.json").write_text('{"providers": ')
    repo = home / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "sub").mkdir()
    (repo / "crush.json").write_text(json.dumps({"mcp": {"repo-mcp": {"type": "stdio", "command": "x"}}}))
    (repo / "sub" / ".crushrc").write_text("mcp add 'sub-mcp' --type stdio --command x\n")
    (home / "crush.json").write_text(json.dumps({"mcp": {"above-git-root": {"type": "stdio"}}}))


def uv_cache() -> str:
    r = subprocess.run(["uv", "cache", "dir"], check=True, capture_output=True, text=True)
    return r.stdout.strip()


class TestCrushDenyConfig(unittest.TestCase):
    r: ClassVar[dict[str, Any]] = {}
    tmp: ClassVar[Path]
    home: ClassVar[Path]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="acp-crush-test-"))
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

    # --- tools off (crush_deny_dir) ---
    def test_both_layers_disable_every_tool_and_yolo(self):
        p = self.r["plain"]
        for layer in ("data", "project"):
            c = p[layer]
            self.assertEqual(c["options"]["disabled_tools"], self.r["tools"])
            self.assertIs(c["options"]["auto_lsp"], False)
            self.assertIs(c["permissions"]["skip_requests"], False)
            self.assertNotIn("mcp", c, "no project config, nothing to disable")

    def test_cmd_points_data_and_data_dir_into_the_temp_dir(self):
        p = self.r["plain"]
        d = p["dir"]
        self.assertIn(f"CRUSH_GLOBAL_DATA={d}/data", p["cmd"])
        self.assertEqual(p["cmd"][-2:], ["--data-dir", f"{d}/project"])
        self.assertEqual(p["cmd"][:2], ["env", "CRUSH_DISABLE_METRICS=1"])
        self.assertEqual(p["env"]["CRUSH_GLOBAL_DATA"], f"{d}/data")
        self.assertIn("acp-run-crush-deny-", d)
        self.assertNotIn("--yolo", p["cmd"])

    def test_temp_dir_is_private_and_copies_the_catalog_cache(self):
        p = self.r["plain"]
        self.assertEqual(p["dir_mode"], "0o700")
        self.assertEqual(p["file_mode"], "0o600")
        self.assertEqual(p["providers"], '[{"id": "cached"}]')
        self.assertEqual(p["files"], ["data", "data/crush.json", "data/providers.json",
                                      "project", "project/crush.json"])

    def test_a_cmd_without_a_data_arg_still_gets_the_env_and_data_dir(self):
        n = self.r["no_data_arg"]
        self.assertEqual(n["cmd"][:2], ["crush-acp", "acp"])
        self.assertIn("--data-dir", n["cmd"])
        self.assertTrue(n["env"]["CRUSH_GLOBAL_DATA"].endswith("/data"))
        self.assertIsNone(n["providers"], "a missing catalog cache is not an error")

    def test_project_mcp_servers_up_to_the_git_root_are_disabled(self):
        p = self.r["project"]
        self.assertEqual(p["info"]["project_mcp_disabled"], ["repo-mcp", "sub-mcp"])
        self.assertEqual(p["project"]["mcp"], {"repo-mcp": {"disabled": True}, "sub-mcp": {"disabled": True}})
        self.assertEqual(p["data"]["mcp"], p["project"]["mcp"])
        self.assertEqual(len(p["info"]["project_config"]), 2)
        self.assertNotIn("above-git-root", json.dumps(p), "the walk stops at the git root, as crush's does")

    def test_tool_list_is_complete_and_has_no_duplicates(self):
        t = self.r["tools"]
        self.assertEqual(len(t), len(set(t)))
        for name in ("bash", "glob", "grep", "ls", "view", "sourcegraph", "agent", "agentic_fetch",
                     "lsp_symbols", "lsp_definition", "lsp_call_hierarchy", "write", "edit"):
            self.assertIn(name, t)

    @unittest.skipUnless(CRUSH_SRC.exists(), "crush-acp source not checked out")
    def test_tool_list_matches_the_installed_builds_allToolNames(self):
        src = CRUSH_SRC.read_text()
        body = re.search(r"func allToolNames\(\) \[\]string \{\s*return \[\]string\{(.*?)\}", src, re.S)
        self.assertIsNotNone(body)
        names = re.findall(r'"([a-z_]+)"', body.group(1))  # type: ignore[union-attr]
        self.assertEqual(sorted(names), sorted(self.r["tools"]))

    # --- user config strip (crush_strip_config) ---
    def test_stripped_crushrc_sources_the_user_crushrc_with_builtins_shadowed(self):
        s = self.r["s_deny"]
        rc = s["crushrc"]
        for fn in ("mcp", "lsp", "hook", "permissions"):
            self.assertIn(f"{fn}() {{ :; }}", rc)
        self.assertIn("request-timeout|disable-skill", rc)
        self.assertNotIn("context-path", rc)
        self.assertIn(f"source {self.home}/.config/crush/crushrc", rc)
        self.assertLess(rc.index("permissions() {"), rc.index("source "), "shadows come first")
        self.assertEqual(s["crushrc_mode"], "0o600")
        self.assertNotIn(SECRET, rc, "the crushrc is sourced in place, never copied")

    def test_stripped_env_and_no_context_or_skills(self):
        s = self.r["s_deny"]
        self.assertTrue(s["same_dir"])
        self.assertTrue(s["env"]["CRUSH_GLOBAL_CONFIG"].endswith("/config"))
        self.assertTrue(s["env"]["CRUSH_SKILLS_DIR"].endswith("/skills"))
        self.assertIn("skills", s["files"])
        self.assertNotIn("config/CRUSH.md", s["files"], "no global context file in the temp config dir")
        i = s["info"]
        self.assertEqual(i["action"], "stripped")
        self.assertEqual(i["mcp_servers"], ["json-mcp", "user-mcp"])
        self.assertEqual((i["lsp"], i["hooks"]), (1, 1))
        self.assertEqual(i["global_context"], "off")
        self.assertNotIn(SECRET, json.dumps(i), "names, never values")

    def test_user_crush_json_keeps_providers_models_and_safe_options_only(self):
        s = self.r["s_deny"]
        j = s["crush_json"]
        self.assertEqual(sorted(j), ["$schema", "models", "options", "providers"])
        self.assertEqual(j["options"], {"request_timeout": 300})
        self.assertEqual(sorted(s["info"]["dropped_keys"]),
                         ["hooks", "lsp", "mcp", "options.context_paths", "options.skills_paths", "permissions"])
        self.assertEqual(s["info"]["secrets_in_file"], ["providers.jsonprov.api_key"])

    def test_explicit_global_config_and_missing_config(self):
        self.assertIn(f"source {self.home}/explicit/crushrc", self.r["s_explicit"]["crushrc"])
        n = self.r["s_none"]
        self.assertEqual(n["info"]["action"], "stripped")
        self.assertNotIn("source ", n["crushrc"])
        self.assertNotIn("crush_json", n)

    def test_a_crushrc_that_could_bypass_the_shadows_keeps_the_user_config(self):
        for k in ("s_bypass", "s_unset", "s_envrun", "s_exec", "s_badjson"):
            s = self.r[k]
            self.assertEqual(s["info"]["action"], "kept", k)
            self.assertTrue(s["info"]["why"].startswith("error:"), k)
            self.assertNotIn("CRUSH_GLOBAL_CONFIG", s["env"], k)
            self.assertNotIn("CRUSH_SKILLS_DIR", s["env"], k)
            self.assertIn("could not strip crush", s["stderr"])
            self.assertTrue(s["same_dir"], "the tools-off dir is still returned for cleanup")

    def test_bypass_words_in_comments_do_not_block_the_strip(self):
        self.assertEqual(self.r["s_comment"]["info"]["action"], "stripped")

    def test_a_project_crushrc_is_named_on_stderr(self):
        self.assertIn("will run project crushrc", self.r["project"]["stderr"])
        self.assertIn("sub/.crushrc", self.r["project"]["stderr"])
        self.assertEqual(self.r["plain"]["stderr"], "")

    def test_keep_user_config_and_interactive(self):
        k = self.r["s_keep"]
        self.assertEqual(k["info"], {"agent": "crush", "action": "kept", "why": "--keep-user-config"})
        self.assertNotIn("CRUSH_GLOBAL_CONFIG", k["env"])
        self.assertIsNone(self.r["s_interactive"]["info"])
        self.assertNotIn("CRUSH_GLOBAL_CONFIG", self.r["s_interactive"]["env"])

    def test_no_tools_off_dir_means_no_strip(self):
        s = self.r["s_nodir"]
        self.assertEqual(s["info"]["action"], "kept")
        self.assertNotIn("CRUSH_GLOBAL_CONFIG", s["env"])

    @unittest.skipUnless(Path(CRUSH_BIN).exists(), "crush-acp not installed")
    def test_real_crush_loads_the_stripped_config(self):
        """The real crush config loader runs the stripped crushrc (shadows and `command
        option` included) and still sees the user's provider. `crush-acp models` reads
        config only: no model is called."""
        d = self.tmp / "real"
        (d / "config").mkdir(parents=True)
        (d / "data").mkdir()
        (d / "work").mkdir()
        user = d / "user-crushrc"
        user.write_text(USER_CRUSHRC)
        rc = textwrap.dedent(f"""\
            mcp() {{ :; }}
            lsp() {{ :; }}
            hook() {{ :; }}
            permissions() {{ :; }}
            option() {{
              case "$1" in
                request-timeout|disable-skill) command option "$@" ;;
              esac
            }}
            source {user}
            """)
        (d / "config" / "crushrc").write_text(rc)
        env = {**os.environ, "CRUSH_GLOBAL_CONFIG": str(d / "config"), "CRUSH_GLOBAL_DATA": str(d / "data"),
               "CRUSH_SKILLS_DIR": str(d / "skills"), "CRUSH_DISABLE_METRICS": "1",
               "CRUSH_DISABLE_PROVIDER_AUTO_UPDATE": "1"}
        r = subprocess.run([CRUSH_BIN, "models", "--data-dir", str(d / "proj")], env=env, cwd=d / "work",
                           capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("fakeprov/fake-model", r.stdout)
        # the same crushrc with the provider builtin shadowed fails: shadowing is real
        (d / "config" / "crushrc").write_text("provider() { :; }\n" + rc)
        r = subprocess.run([CRUSH_BIN, "models", "--data-dir", str(d / "proj")], env=env, cwd=d / "work",
                           capture_output=True, text=True, timeout=60, check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("does not exist", r.stdout + r.stderr)


class TestCrushDenyEndToEnd(unittest.TestCase):
    """The real main()/run() against a fake crush-acp that records what it was given."""

    tmp: ClassVar[Path]
    home: ClassVar[Path]
    bin: ClassVar[Path]
    cache: ClassVar[str]

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="acp-crush-e2e-"))
        cls.home = cls.tmp / "home"
        write_home(cls.home)
        cls.bin = cls.tmp / "bin"
        cls.bin.mkdir()
        fake = cls.bin / "crush-acp"
        fake.write_text(FAKE_CRUSH)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        cls.cache = uv_cache()

    @classmethod
    @override
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_acp(self, *args: str, env: dict[str, str] | None = None) -> dict[str, Any]:
        n = len(list(self.tmp.glob("run-*")))
        d = self.tmp / f"run-{n}"
        d.mkdir()
        out, log = d / "seen.json", d / "log.jsonl"
        e = {**os.environ, "HOME": str(self.home), "UV_CACHE_DIR": self.cache,
             "PATH": f"{self.bin}:{os.environ['PATH']}", "FAKE_OUT": str(out), "TMPDIR": str(d)}
        for k in ("ACP_RUN_KEEP_USER_CONFIG", "CRUSH_GLOBAL_CONFIG", "CRUSH_GLOBAL_DATA",
                  "XDG_CONFIG_HOME", "HERDR_PANE_ID", "HERDR_ENV"):
            e.pop(k, None)
        e.update(env or {})
        argv = ["uv", "run", "--quiet", "--with", SDK, "python", "-I", str(SCRIPT), "crush", "-C", str(d),
                "-p", "Reply with the word ok", "--handshake-tries", "1", "--handshake-timeout", "20",
                "--no-fallback", "--timeout", "60", "--log", str(log), *args]
        p = subprocess.run(argv, env=e, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180,
                           check=False)
        recs = [json.loads(x) for x in log.read_text().splitlines() if x.strip()] if log.exists() else []
        return {"rc": p.returncode, "stdout": p.stdout, "stderr": p.stderr,
                "seen": json.loads(out.read_text()) if out.exists() else {},
                "deny_config": [x["data"] for x in recs if x["kind"] == "deny_config"],
                "user_config": [x["data"] for x in recs if x["kind"] == "user_config"],
                "leftovers": [q.name for q in d.iterdir() if q.name.startswith("acp-run-")]}

    def test_deny_run_gets_no_tools_stripped_config_and_cleans_up(self):
        r = self.run_acp("--perm", "deny")
        self.assertEqual(r["rc"], 0, r["stderr"])
        self.assertEqual(r["stdout"].strip(), "ok")
        s = r["seen"]
        self.assertIn("--data-dir", s["argv"])
        self.assertNotIn("--yolo", s["argv"])
        self.assertIn("acp-run-crush-deny-", s["env"]["CRUSH_GLOBAL_DATA"])
        self.assertIn("acp-run-crush-deny-", s["env"]["CRUSH_GLOBAL_CONFIG"])
        self.assertIn("acp-run-crush-deny-", s["env"]["CRUSH_SKILLS_DIR"])
        self.assertEqual(s["env"]["CRUSH_DISABLE_METRICS"], "1")
        for k in ("CRUSH_GLOBAL_DATA_json", "workspace_json"):
            self.assertIn("bash", s[k]["options"]["disabled_tools"], k)
            self.assertIn("glob", s[k]["options"]["disabled_tools"], k)
        self.assertEqual(s["CRUSH_GLOBAL_CONFIG_json"]["options"], {"request_timeout": 300})
        self.assertEqual(r["deny_config"][0]["tools"], "none")
        self.assertEqual(r["user_config"][0]["action"], "stripped")
        self.assertEqual(r["leftovers"], [], "the per-run dir is removed")

    def test_keep_user_config_still_turns_tools_off(self):
        r = self.run_acp("--perm", "deny", "--keep-user-config")
        self.assertEqual(r["rc"], 0, r["stderr"])
        s = r["seen"]
        self.assertIsNone(s["env"]["CRUSH_GLOBAL_CONFIG"])
        self.assertIn("glob", s["CRUSH_GLOBAL_DATA_json"]["options"]["disabled_tools"])
        self.assertEqual(r["user_config"][0]["action"], "kept")
        self.assertEqual(r["leftovers"], [])

    def test_perm_all_is_untouched_and_runs_yolo(self):
        r = self.run_acp("--perm", "all")
        self.assertEqual(r["rc"], 0, r["stderr"])
        s = r["seen"]
        self.assertIn("--yolo", s["argv"])
        self.assertNotIn("--data-dir", s["argv"])
        self.assertNotIn("acp-run-", s["env"]["CRUSH_GLOBAL_DATA"])
        self.assertIsNone(s["env"]["CRUSH_GLOBAL_CONFIG"])
        self.assertEqual((r["deny_config"], r["user_config"]), ([], []))


if __name__ == "__main__":
    unittest.main()
