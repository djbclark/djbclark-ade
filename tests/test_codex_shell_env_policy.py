#!/usr/bin/env python3
"""Codex tool-subprocess environment policy in agents/codex/config.toml.tmpl (2026-10-25).

`inherit = "core"` stripped the Herdr pane identity from every tool Codex ran, so a Herdr-aware tool could not
find its own pane (HERDR_ENV, HERDR_WORKSPACE_ID, HERDR_TAB_ID, HERDR_PANE_ID were set in the Codex process and
its parent shell, absent in the tool). The template now says `inherit = "all"` plus a legacy `include_only`
allowlist: the old core set, the four Herdr ids and the explicit `set` keys, and nothing else.

Three layers:

1. Structure of the rendered policy (always runs). Facts about Codex it depends on, probed 2026-10-25 on 0.160.1,
   0.163.0 and 0.164.0: `include_only` runs AFTER `set` (a `set` key that is not listed vanishes); 0.163.0 ignores
   the newer `filters` table, so under `inherit = "all"` it would pass the whole environment.
2. The installed Codex, through `codex app-server` and `thread/shellCommand` (the `!cmd` path): no model is
   called, a throwaway CODEX_HOME holds the rendered policy, and the tool's real environment is read back.
   Skipped where `codex` is not installed (hosted CI).
3. The detached-child scrub: what `acp-run` and the relay deliverer would start a Codex with, run through the
   same probe, shows no Herdr id.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import pathlib
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "agents" / "codex" / "config.toml.tmpl"

CORE = ("HOME", "LANG", "LC_ALL", "LC_CTYPE", "LOGNAME", "PATH", "SHELL", "TEMP", "TMP", "TMPDIR", "USER")
HERDR = ("HERDR_ENV", "HERDR_WORKSPACE_ID", "HERDR_TAB_ID", "HERDR_PANE_ID")
SET_KEYS = {
    "NODE_REPL_TRUSTED_BROWSER_CLIENT_SHA256S": "DIGESTS",
    "BASH_ENV": "HOME/.bashrc",
    "ENABLE_PROMPT_CACHING_1H": "1",
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
    "MCP_TIMEOUT": "300000",
    "CLAUDE_CODE_HARBOR_KITE": "1",
    "GRAFT_NO_GITIGNORE": "1",
}
IN_HERDR = {"HERDR_ENV": "1", "HERDR_WORKSPACE_ID": "w9", "HERDR_TAB_ID": "w9:t7", "HERDR_PANE_ID": "w9:p7"}
# Not in a pane's environment (2026-10-25) and so never wanted in a tool's: routing to a server, a plugin, a session.
HERDR_NEIGHBOURS = {"HERDR_BIN_PATH": "/bin/herdr", "HERDR_SOCKET_PATH": "/tmp/h.sock", "HERDR_SESSION": "other",
                    "HERDR_ACTIVE_PANE_ID": "w1:p1"}
SYNTHETIC_SECRETS = {"ZZ_SYNTHETIC_SECRET": "s3", "OPENAI_API_KEY": "k1", "GITHUB_TOKEN": "t1", "AWS_SESSION": "a1",
                     "DB_PASSWORD": "p1", "SSH_AUTH_SOCK": "/tmp/agent.sock", "ANTHROPIC_AUTH": "x1", "TERM": "xterm"}


def rendered(home: str) -> dict:
    """The template with every {{ }} tag filled (each sits in a quoted scalar) and parsed."""
    text = TEMPLATE.read_text()
    text = text.replace("{{ .home }}", home).replace("{{ .codex_browser_client_sha256s }}", "DIGESTS")
    return tomllib.loads(re.sub(r"\{\{.*?\}\}", "x", text))


def policy_toml(policy: dict) -> str:
    out = ["[shell_environment_policy]"]
    for k, v in policy.items():
        if k != "set":
            out.append(f"{k} = {json.dumps(v)}")
    out.append("[shell_environment_policy.set]")
    out += [f"{k} = {json.dumps(v)}" for k, v in policy.get("set", {}).items()]
    return "\n".join(out) + "\n"


class Policy(unittest.TestCase):
    """Layer 1: what the rendered template says."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.home = "/h"
        cls.p = rendered(cls.home)["shell_environment_policy"]

    def test_existing_explicit_set_is_preserved(self) -> None:
        want = {**SET_KEYS, "BASH_ENV": self.home + "/.bashrc"}
        self.assertEqual(self.p["set"], want)

    def test_every_set_key_is_on_the_allowlist(self) -> None:
        # include_only runs after set: an unlisted set key is silently dropped (probed on Codex 0.160.1-0.164.0).
        allowed = {x.upper() for x in self.p["include_only"]}
        for k in self.p["set"]:
            self.assertIn(k.upper(), allowed, k)

    def test_the_allowlist_is_core_plus_the_four_herdr_ids_plus_set_keys_and_nothing_else(self) -> None:
        names = self.p["include_only"]
        self.assertEqual(len(names), len(set(names)), "duplicate entry")
        self.assertEqual(set(names), set(CORE) | set(HERDR) | set(self.p["set"]))
        for n in names:
            self.assertNotRegex(n, r"[*?\[]", f"{n}: a pattern, not a name")

    def test_inherit_all_is_never_unfiltered(self) -> None:
        self.assertEqual(self.p["inherit"], "all")
        self.assertTrue(self.p["include_only"])
        self.assertIs(self.p.get("ignore_default_excludes"), False)  # KEY/SECRET/TOKEN names go first, whatever is listed
        # 0.163.0 ignores `filters`; mixing it with include_only is rejected by 0.164.0.
        self.assertNotIn("filters", self.p)
        self.assertNotIn("exclude", self.p)

    def test_no_fixed_pane_id_is_written_into_the_policy(self) -> None:
        # ids come from the process Codex runs in: nothing in the policy may name a pane
        for k, v in self.p["set"].items():
            self.assertFalse(k.startswith("HERDR_"), k)
            self.assertNotRegex(str(v), r"\bw\d+[A-Za-z]*:[pt]\d+\b")


# ---- layer 2: the installed Codex ---------------------------------------------------------------------------------

CODEX = os.environ.get("CX_BIN") or shutil.which("codex")


def tool_env(policy_text: str, env: dict[str, str], timeout: float = 90.0) -> dict[str, str]:
    """The environment a Codex tool command gets, read through the user-shell path (`thread/shellCommand`).

    A throwaway CODEX_HOME holds only `policy_text`; `env` is the whole environment of the app-server process (the
    stand-in for the Codex process inside its pane). No model is called."""
    with tempfile.TemporaryDirectory(prefix="cxpol-") as home:
        pathlib.Path(home, "config.toml").write_text(policy_text)
        full = {**env, "CODEX_HOME": home}
        proc = subprocess.Popen([CODEX, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, env=full, text=True, cwd=home, start_new_session=True)
        n = [0]

        def send(method: str, params: dict | None = None, notify: bool = False) -> int:
            msg: dict = {"method": method}
            if params is not None:
                msg["params"] = params
            if not notify:
                n[0] += 1
                msg["id"] = n[0]
            proc.stdin.write(json.dumps(msg) + "\n")
            proc.stdin.flush()
            return n[0]

        def wait_for(pred) -> dict:
            end = time.time() + timeout
            while time.time() < end:
                if not select.select([proc.stdout], [], [], 1)[0]:
                    continue
                line = proc.stdout.readline()
                if not line:
                    break
                msg = json.loads(line)
                if pred(msg):
                    return msg
            raise TimeoutError("codex app-server did not answer")

        try:
            i = send("initialize", {"clientInfo": {"name": "env-policy-test", "version": "0"}})
            wait_for(lambda m: m.get("id") == i)
            send("initialized", notify=True)
            i = send("thread/start", {"cwd": home})
            tid = wait_for(lambda m: m.get("id") == i)["result"]["thread"]["id"]
            send("thread/shellCommand", {"threadId": tid, "command": "/usr/bin/env -0"})
            done = wait_for(lambda m: m.get("method") == "item/completed"
                            and m["params"]["item"].get("type") == "commandExecution")
            out = done["params"]["item"]["aggregatedOutput"]
        finally:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
    return dict(x.split("=", 1) for x in out.split("\0") if "=" in x)


def base_env(home: str) -> dict[str, str]:
    return {"PATH": "/usr/bin:/bin", "HOME": home, "SHELL": "/bin/bash", "USER": "tester", "LOGNAME": "tester",
            "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "LC_CTYPE": "en_US.UTF-8", "TMPDIR": home + "/tmp",
            "TEMP": home + "/tmp", "TMP": home + "/tmp", **SYNTHETIC_SECRETS}


def noise(env: dict[str, str]) -> dict[str, str]:
    """Drop what the tool shell and Codex add on their own and that differs per run."""
    tidy = lambda v: re.sub(r"codex-arg0\w+", "codex-arg0X", re.sub(r"/cxpol-[^/:]+", "/cxpol-X", v))  # per-run temp names
    # PATH: Codex adds its own directories and the login shell reorders it, run to run; compare its entries as a set.
    return {k: (frozenset(tidy(v).split(":")) if k == "PATH" else tidy(v)) for k, v in env.items()
            if not k.startswith("CODEX_") and k not in ("PWD", "SHLVL", "_", "OLDPWD")}


@unittest.skipUnless(CODEX and sys.platform in ("darwin", "linux"), "no installed codex")
class InstalledCodex(unittest.TestCase):
    """Layer 2: the real policy engine of the installed Codex, whatever version `codex` resolves to."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="cxhome-")
        cls.home = cls.tmp.name
        os.makedirs(cls.home + "/tmp", exist_ok=True)
        cls.new = rendered(cls.home)["shell_environment_policy"]
        cls.new_toml = policy_toml(cls.new)
        # The policy this replaced: same explicit set, old inheritance.
        cls.old_toml = policy_toml({"inherit": "core", "set": cls.new["set"]})
        try:
            tool_env(cls.old_toml, base_env(cls.home))
        except (TimeoutError, OSError, KeyError, ValueError) as e:
            cls.tmp.cleanup()
            raise unittest.SkipTest(f"this codex has no usable app-server shell probe: {e!r}")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_pane_identity_survives_in_herdr(self) -> None:
        got = tool_env(self.new_toml, {**base_env(self.home), **IN_HERDR})
        for k, v in IN_HERDR.items():
            self.assertEqual(got.get(k), v, k)

    def test_the_old_policy_really_stripped_it(self) -> None:
        # The bug itself, on the installed Codex: otherwise the fix tests above prove nothing.
        got = tool_env(self.old_toml, {**base_env(self.home), **IN_HERDR})
        self.assertEqual([k for k in got if k.startswith("HERDR_")], [])

    def test_outside_herdr_nothing_herdr_appears(self) -> None:
        got = tool_env(self.new_toml, base_env(self.home))
        self.assertEqual([k for k in got if k.startswith("HERDR_")], [])

    def test_only_the_four_ids_pass_and_no_secret_does(self) -> None:
        env = {**base_env(self.home), **IN_HERDR, **HERDR_NEIGHBOURS}
        got = tool_env(self.new_toml, env)
        self.assertEqual(sorted(k for k in got if k.startswith("HERDR_")), sorted(HERDR))
        for k in SYNTHETIC_SECRETS:
            self.assertNotIn(k, got, k)

    def test_core_and_explicit_set_are_exactly_what_inherit_core_gave(self) -> None:
        # Same host environment under the old and the new policy: outside Herdr the tool sees the same thing; inside,
        # the same plus the four ids. Catches a core variable this Codex has and the allowlist forgot.
        rich = {**base_env(self.home), "COLORTERM": "truecolor", "XDG_STATE_HOME": "/x", "LC_MESSAGES": "C",
                "TZ": "UTC", "EDITOR": "vi", "HTTPS_PROXY": "http://p", "USERNAME": "tester", "NO_COLOR": "1"}
        before = noise(tool_env(self.old_toml, rich))
        after = noise(tool_env(self.new_toml, rich))
        self.assertEqual(after, before)
        inside = noise(tool_env(self.new_toml, {**rich, **IN_HERDR}))
        self.assertEqual({k: v for k, v in inside.items() if k not in IN_HERDR}, before)
        for k, v in self.new["set"].items():
            self.assertEqual(after.get(k), v, k)
        for k in CORE:
            if k == "PATH":  # Codex and the login shell extend it; it must still hold the caller's directories
                self.assertLessEqual(set(rich[k].split(":")), after[k])
            else:
                self.assertEqual(after.get(k), rich[k], k)


# ---- layer 3: detached children -----------------------------------------------------------------------------------

def load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, str(path)))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@unittest.skipUnless(CODEX and sys.platform in ("darwin", "linux"), "no installed codex")
class DetachedChildren(unittest.TestCase):
    """Layer 3: a Codex started by acp-run or by a relay deliverer gets no Herdr id in its tools, though the policy
    now passes the four ids on."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="cxhome-")
        cls.home = cls.tmp.name
        os.makedirs(cls.home + "/tmp", exist_ok=True)
        cls.toml = policy_toml(rendered(cls.home)["shell_environment_policy"])

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def caller_env(self) -> dict[str, str]:
        return {**base_env(self.home), **IN_HERDR, "PASEO_AGENT_ID": "a1", "ORCA_TERMINAL_HANDLE": "t1"}

    def test_acp_run_drops_the_callers_herdr_ids_before_the_agent_starts(self) -> None:
        try:
            mod = load("acp_run_under_test", ROOT / "tools" / "acp-run" / "acp-run")
        except ImportError as e:
            self.skipTest(f"acp-run needs its ACP SDK: {e}")
        scrubbed = {k: v for k, v in self.caller_env().items() if k not in mod.SCRUB_ENV}
        self.assertEqual([k for k in scrubbed if k.startswith("HERDR_")], [])
        got = tool_env(self.toml, scrubbed)
        self.assertEqual([k for k in got if k.startswith("HERDR_")], [])
        self.assertNotIn("PASEO_AGENT_ID", got)

    def test_a_relay_deliverer_has_no_herdr_id_in_its_tools(self) -> None:
        spec = importlib.util.spec_from_file_location("relay_under_test", ROOT / "skills" / "session-finder" / "relay.py")
        relay = importlib.util.module_from_spec(spec)
        sys.modules["relay_under_test"] = relay
        spec.loader.exec_module(relay)
        with mock.patch.dict(os.environ, {**self.caller_env(), **HERDR_NEIGHBOURS}, clear=True):
            env = relay.deliverer_env()
        self.assertEqual([k for k in env if k.startswith("HERDR_") and k != "HERDR_BIN_PATH"], [])
        got = tool_env(self.toml, {**env, "HOME": self.home})
        self.assertEqual([k for k in got if k.startswith("HERDR_")], [])

    def test_the_unscrubbed_caller_environment_would_leak_the_ids(self) -> None:
        # Why the scrub matters now: without it the same Codex hands all four ids to its tools.
        got = tool_env(self.toml, self.caller_env())
        self.assertEqual(sorted(k for k in got if k.startswith("HERDR_")), sorted(HERDR))


# ---- the deployment helper ----------------------------------------------------------------------------------------

class ApplyScript(unittest.TestCase):
    """bin/codex-env-policy-apply changes only the policy tables of a config Codex also writes."""

    LIVE = """model = "m"

[projects."/x"]
trust_level = "trusted"

[shell_environment_policy]
inherit = "core"

[shell_environment_policy.set]
NODE_REPL_TRUSTED_BROWSER_CLIENT_SHA256S = "SECRETDIGEST-0123"
BASH_ENV = "{home}/.bashrc"
ENABLE_PROMPT_CACHING_1H = "1"
CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS = "1"
MCP_TIMEOUT = "300000"
CLAUDE_CODE_HARBOR_KITE = "1"
GRAFT_NO_GITIGNORE = "1"

[hooks.state."/y"]
trusted_hash = "abc"
"""

    def run_apply(self, target: pathlib.Path, *flags: str, umask: int | None = None, template: pathlib.Path = TEMPLATE,
                  args: list[str] | None = None) -> subprocess.CompletedProcess:
        argv = args if args is not None else [str(template), str(target), *flags]
        return subprocess.run([sys.executable, str(ROOT / "bin" / "codex-env-policy-apply"), *argv],
                              capture_output=True, text=True, env={**os.environ, "HOME": str(target.parent)},
                              preexec_fn=(lambda: os.umask(umask)) if umask is not None else None)

    def test_only_the_policy_changes_and_a_second_run_changes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            t = pathlib.Path(d, "config.toml")
            t.write_text(self.LIVE.format(home=d))
            t.chmod(0o600)
            before = tomllib.loads(t.read_text())
            dry = self.run_apply(t)
            self.assertEqual((dry.returncode, t.read_text()), (0, self.LIVE.format(home=d)), dry.stderr)  # dry run writes nothing
            r = self.run_apply(t, "--write")
            self.assertEqual(r.returncode, 0, r.stderr)
            after = tomllib.loads(t.read_text())
            self.assertEqual({k: v for k, v in after.items() if k != "shell_environment_policy"},
                             {k: v for k, v in before.items() if k != "shell_environment_policy"})
            self.assertEqual(after["shell_environment_policy"]["set"], before["shell_environment_policy"]["set"])  # machine digest kept
            self.assertEqual((after["shell_environment_policy"]["inherit"], set(HERDR) <= set(after["shell_environment_policy"]["include_only"])),
                             ("all", True))
            self.assertEqual(stat_mode(t), 0o600)  # Codex keeps its config private
            self.assertEqual(len(list(pathlib.Path(d).glob("config.toml.bak-*-env-policy"))), 1)
            self.assertEqual([p.name for p in pathlib.Path(d).glob(".config.toml.*")], [])  # no temp file left
            once = t.read_text()
            self.assertEqual(self.run_apply(t, "--write").returncode, 0)
            self.assertEqual(t.read_text(), once)

    def test_it_refuses_when_the_explicit_set_would_change_and_never_prints_a_value(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            t = pathlib.Path(d, "config.toml")
            t.write_text(self.LIVE.format(home=d).replace('MCP_TIMEOUT = "300000"', 'MCP_TIMEOUT = "SECRETVALUE-9"'))
            for flags in ((), ("--write",)):
                r = self.run_apply(t, *flags)
                self.assertEqual(r.returncode, 1, flags)
                self.assertIn("MCP_TIMEOUT", r.stderr)  # the key is named
                for secret in ("SECRETVALUE-9", "SECRETDIGEST-0123", "300000"):
                    self.assertNotIn(secret, r.stdout + r.stderr, secret)
            self.assertIn('MCP_TIMEOUT = "SECRETVALUE-9"', t.read_text())
            self.assertEqual(list(pathlib.Path(d).glob("*.bak-*")), [])

    def test_dry_run_and_write_output_hide_every_set_value(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            t = pathlib.Path(d, "config.toml")
            t.write_text(self.LIVE.format(home=d))
            for flags in ((), ("--write",)):
                r = self.run_apply(t, *flags)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("include_only", r.stdout)  # the diff itself is shown
                self.assertNotIn("SECRETDIGEST-0123", r.stdout + r.stderr)

    def test_the_backup_is_created_private_and_holds_the_original_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            t = pathlib.Path(d, "config.toml")
            original = self.LIVE.format(home=d).replace("\n", "\r\n").encode()  # CRLF outside the policy must survive too
            t.write_bytes(original)
            r = self.run_apply(t, "--write", umask=0)  # a permissive umask must not widen the backup
            self.assertEqual(r.returncode, 0, r.stderr)
            (bak,) = pathlib.Path(d).glob("config.toml.bak-*-env-policy")
            self.assertEqual((stat_mode(bak), bak.read_bytes()), (0o600, original))
            self.assertTrue(t.read_bytes().startswith(b'model = "m"\r\n\r\n[projects."/x"]\r\n'))

    def test_write_is_a_true_no_op_when_already_applied(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            t = pathlib.Path(d, "config.toml")
            t.write_text(self.LIVE.format(home=d))
            self.assertEqual(self.run_apply(t, "--write").returncode, 0)
            before = (t.read_bytes(), t.stat().st_mtime_ns, t.stat().st_ino, sorted(os.listdir(d)))
            time.sleep(0.05)
            r = self.run_apply(t, "--write")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual((t.read_bytes(), t.stat().st_mtime_ns, t.stat().st_ino, sorted(os.listdir(d))), before)  # no new backup or temp

    def test_bad_arguments_are_a_usage_error_not_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            t = pathlib.Path(d, "config.toml")
            t.write_text(self.LIVE.format(home=d))
            for args in ([], [str(TEMPLATE)], [str(TEMPLATE), str(t), "--wrte"], [str(TEMPLATE), str(t), "extra"]):
                r = self.run_apply(t, args=args)
                self.assertEqual(r.returncode, 2, args)
                self.assertIn("usage: codex-env-policy-apply", r.stderr)
                self.assertNotIn("Traceback", r.stderr)
            self.assertEqual(t.read_text(), self.LIVE.format(home=d))

    def test_unreadable_or_odd_files_fail_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            t = pathlib.Path(d, "config.toml")
            t.write_text(self.LIVE.format(home=d))
            missing = pathlib.Path(d, "nope.toml")
            bad = pathlib.Path(d, "bad.toml")
            bad.write_text('key = "SECRETDIGEST-0123\n')
            nodigest = pathlib.Path(d, "nodigest.toml")
            nodigest.write_text('[shell_environment_policy]\ninherit = "core"\n')
            for target, template in ((missing, TEMPLATE), (t, missing), (bad, TEMPLATE), (nodigest, TEMPLATE)):
                r = self.run_apply(target, "--write", template=template)
                self.assertEqual(r.returncode, 1, (target, template))
                self.assertIn("codex-env-policy-apply:", r.stderr)
                self.assertNotIn("Traceback", r.stderr)
                self.assertNotIn("SECRETDIGEST-0123", r.stdout + r.stderr)


def stat_mode(p: pathlib.Path) -> int:
    return p.stat().st_mode & 0o777


if __name__ == "__main__":
    unittest.main()
