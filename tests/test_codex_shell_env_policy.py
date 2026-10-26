#!/usr/bin/env python3
"""Codex tool-subprocess environment policy in agents/codex/config.toml.tmpl (2026-10-25).

`inherit = "core"` stripped the Herdr pane identity (HERDR_ENV, HERDR_WORKSPACE_ID, HERDR_TAB_ID, HERDR_PANE_ID, and
the routing paths HERDR_SOCKET_PATH, HERDR_BIN_PATH) and the multiplexer and runtime variables of the launching
terminal from every tool Codex ran. Operator ruling (2026-10-25, after a first allowlist design): the template says
`inherit = "all"` with Codex's default KEY/SECRET/TOKEN name exclusions on and the explicit `set` keys applied after
them. Inheriting an arbitrary terminal environment is intentional; these tests prove what that policy does, not
whether it should.

Three layers:

1. Structure of the rendered policy (always runs).
2. The installed Codex, through `codex app-server` and `thread/shellCommand` (the `!cmd` path): no model is
   called, a throwaway CODEX_HOME holds the rendered policy, and the tool's real environment is read back.
   Skipped where `codex` is not installed (hosted CI).
3. The detached-child scrub: what `acp-run` and the relay deliverer would start a Codex with, run through the
   same probe, shows none of the four owner ids.
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

OWNER = ("HERDR_ENV", "HERDR_WORKSPACE_ID", "HERDR_TAB_ID", "HERDR_PANE_ID")  # who this pane is
ROUTING = ("HERDR_SOCKET_PATH", "HERDR_BIN_PATH")  # which Herdr to talk to: service paths, not identity
HERDR = OWNER + ROUTING  # the six names a live Codex process had (2026-10-25)
SET_KEYS = {
    "NODE_REPL_TRUSTED_BROWSER_CLIENT_SHA256S": "DIGESTS",
    "BASH_ENV": "HOME/.bashrc",
    "ENABLE_PROMPT_CACHING_1H": "1",
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
    "MCP_TIMEOUT": "300000",
    "CLAUDE_CODE_HARBOR_KITE": "1",
    "GRAFT_NO_GITIGNORE": "1",
}
IN_HERDR = {"HERDR_ENV": "1", "HERDR_WORKSPACE_ID": "w9", "HERDR_TAB_ID": "w9:t7", "HERDR_PANE_ID": "w9:p7",
            "HERDR_SOCKET_PATH": "/tmp/herdr-test.sock", "HERDR_BIN_PATH": "/tmp/herdr-test-bin"}
# Other HERDR_* names: a named session, plugin popup context, the active-pane hints. `inherit = "all"` passes them too.
HERDR_NEIGHBOURS = {"HERDR_SESSION": "other", "HERDR_ACTIVE_PANE_ID": "w1:p1", "HERDR_PLUGIN_ID": "p"}
# What `inherit = "core"` dropped and the launching terminal's context needs (the operator's ruling).
TERMINAL_CONTEXT = {"TERM": "xterm-256color", "COLORTERM": "truecolor", "TMUX": "/tmp/tmux-1/default,1,0", "TMUX_PANE": "%3",
                    "SSH_AUTH_SOCK": "/tmp/agent.sock", "XDG_STATE_HOME": "/x/state", "TZ": "UTC", "HTTPS_PROXY": "http://p"}
# Names Codex's default exclusions (KEY, SECRET, TOKEN) remove before `set` runs.
SYNTHETIC_SECRETS = {"ZZ_SYNTHETIC_SECRET": "s3", "OPENAI_API_KEY": "k1", "GITHUB_TOKEN": "t1"}


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

    def test_inherit_all_keeps_codex_default_exclusions(self) -> None:
        self.assertEqual(self.p["inherit"], "all")
        self.assertIs(self.p.get("ignore_default_excludes"), False)  # KEY/SECRET/TOKEN names are removed first
        for k in ("include_only", "exclude", "filters"):  # the operator's ruling: no allowlist, no extra filter
            self.assertNotIn(k, self.p)

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
            if not k.startswith("CODEX_") and k not in ("PWD", "SHLVL", "_", "OLDPWD", "__CF_USER_TEXT_ENCODING")}


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
        got = tool_env(self.old_toml, {**base_env(self.home), **IN_HERDR, **TERMINAL_CONTEXT})
        self.assertEqual([k for k in got if k.startswith("HERDR_")], [])
        self.assertEqual([k for k in TERMINAL_CONTEXT if k in got], [])

    def test_outside_herdr_nothing_herdr_appears(self) -> None:
        got = tool_env(self.new_toml, base_env(self.home))
        self.assertEqual([k for k in got if k.startswith("HERDR_")], [])

    def test_the_launching_terminals_context_reaches_the_tool(self) -> None:
        got = tool_env(self.new_toml, {**base_env(self.home), **IN_HERDR, **HERDR_NEIGHBOURS, **TERMINAL_CONTEXT})
        for k, v in {**TERMINAL_CONTEXT, **HERDR_NEIGHBOURS}.items():
            self.assertEqual(got.get(k), v, k)

    def test_default_exclusions_still_remove_key_secret_token_names(self) -> None:
        got = tool_env(self.new_toml, {**base_env(self.home), **TERMINAL_CONTEXT})
        for k in SYNTHETIC_SECRETS:
            self.assertNotIn(k, got, k)
        self.assertIn("SSH_AUTH_SOCK", got)

    def test_explicit_set_wins_over_the_inherited_value(self) -> None:
        env = {**base_env(self.home), "MCP_TIMEOUT": "1", "BASH_ENV": "/elsewhere", "GRAFT_NO_GITIGNORE": "0"}
        got = tool_env(self.new_toml, env)
        for k, v in self.new["set"].items():
            self.assertEqual(got.get(k), v, k)

    def test_core_and_explicit_set_survive_exactly_as_under_inherit_core(self) -> None:
        # Same host environment under the old and the new policy: everything the old policy gave is still there with
        # the same value (nothing narrower), and the new one adds only what inherit core had dropped.
        rich = {**base_env(self.home), **TERMINAL_CONTEXT, "LC_MESSAGES": "C", "EDITOR": "vi", "NO_COLOR": "1"}
        before = noise(tool_env(self.old_toml, rich))
        after = noise(tool_env(self.new_toml, rich))
        self.assertEqual({k: v for k, v in after.items() if k in before}, before)
        self.assertEqual(sorted(set(after) - set(before)), sorted([*TERMINAL_CONTEXT, "EDITOR", "LC_MESSAGES", "NO_COLOR"]))


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
    now passes the six names on. Owner identity (the four ids) must never arrive; the routing paths (HERDR_SOCKET_PATH,
    HERDR_BIN_PATH) are service locations and may, where acp-run or the relay deliverer keep them."""

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

    def test_acp_run_drops_the_callers_owner_ids_before_the_agent_starts(self) -> None:
        try:
            mod = load("acp_run_under_test", ROOT / "tools" / "acp-run" / "acp-run")
        except ImportError as e:
            self.skipTest(f"acp-run needs its ACP SDK: {e}")
        scrubbed = {k: v for k, v in self.caller_env().items() if k not in mod.SCRUB_ENV}
        self.assertEqual([k for k in scrubbed if k in OWNER], [])
        got = tool_env(self.toml, scrubbed)
        self.assertEqual([k for k in got if k in OWNER], [])
        self.assertLessEqual({k for k in got if k.startswith("HERDR_")}, set(ROUTING))  # nothing but service paths
        self.assertNotIn("PASEO_AGENT_ID", got)

    def test_a_relay_deliverer_has_no_owner_id_in_its_tools(self) -> None:
        spec = importlib.util.spec_from_file_location("relay_under_test", ROOT / "skills" / "session-finder" / "relay.py")
        relay = importlib.util.module_from_spec(spec)
        sys.modules["relay_under_test"] = relay
        spec.loader.exec_module(relay)
        with mock.patch.dict(os.environ, {**self.caller_env(), **HERDR_NEIGHBOURS}, clear=True):
            env = relay.deliverer_env()
        self.assertEqual([k for k in env if k.startswith("HERDR_") and k != "HERDR_BIN_PATH"], [])  # the deliverer's own, deliberate keep
        got = tool_env(self.toml, {**env, "HOME": self.home})
        self.assertEqual([k for k in got if k in OWNER], [])
        self.assertLessEqual({k for k in got if k.startswith("HERDR_")}, {"HERDR_BIN_PATH"})

    def test_the_unscrubbed_caller_environment_would_leak_the_ids(self) -> None:
        # Why the scrub matters now: without it the same Codex hands all six names to its tools.
        got = tool_env(self.toml, self.caller_env())
        self.assertEqual(sorted(k for k in got if k.startswith("HERDR_")), sorted(HERDR))


# ---- the deployment helper ----------------------------------------------------------------------------------------

class ApplyScript(unittest.TestCase):
    """bin/codex-env-policy-apply changes only the policy tables of a config Codex also writes."""

    LIVE = """model = "m"

[projects."/x"]
trust_level = "trusted"

[mcp_servers.above.env]
API_KEY = "SECRET-ABOVE-1"
# note SECRET-COMMENT-3
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

[mcp_servers.below.http_headers]
Authorization = "Bearer SECRET-BELOW-2"

[hooks.state."/y"]
trusted_hash = "abc"
"""
    NEIGHBOUR_SECRETS = ("SECRET-ABOVE-1", "SECRET-COMMENT-3", "SECRET-BELOW-2", "SECRETDIGEST-0123")

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
            self.assertEqual((after["shell_environment_policy"]["inherit"], after["shell_environment_policy"]["ignore_default_excludes"],
                              "include_only" in after["shell_environment_policy"]), ("all", False, False))
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

    def test_dry_run_and_write_output_hide_every_set_value_and_all_neighbours(self) -> None:
        # 2026-10-25 adversary: unified_diff's 3 lines of context printed the table above the policy.
        with tempfile.TemporaryDirectory() as d:
            t = pathlib.Path(d, "config.toml")
            t.write_text(self.LIVE.format(home=d))
            for flags in ((), ("--write",)):
                r = self.run_apply(t, *flags)
                self.assertEqual(r.returncode, 0, r.stderr)
                if flags:
                    self.assertIn("SECRET-ABOVE-1", t.read_text())  # the neighbours are still in the file, only the output hides them
                self.assertIn('inherit = "all"', r.stdout)  # the diff itself is shown
                for secret in self.NEIGHBOUR_SECRETS:  # the set table, the table above and below, a comment above the header
                    self.assertNotIn(secret, r.stdout + r.stderr, secret)
                self.assertNotIn("[mcp_servers", r.stdout)  # not a line of any neighbouring table
                self.assertNotIn("API_KEY", r.stdout)
                self.assertNotIn("Authorization", r.stdout)

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

    def test_operator_text_in_the_root_policy_table_never_prints(self) -> None:
        # 2026-10-25 adversary r2 (C2): a root key's value, a trailing comment and a comment inside include_only printed.
        live = self.LIVE.format(home="/h").replace('inherit = "core"\n', """inherit = "core"  # SECRET-TRAILING-8
exclude = ["SECRET-EXCL-7"]
include_only = [
  "HOME",  # SECRET-OPCOMMENT-6
  "PATH",
  "SECRET-ENTRY-9",
]
ignore_default_excludes = true
""", 1).replace('[mcp_servers.below.http_headers]', '[shell_environment_policy.extra]\ninherit = "SECRET-SUBINHERIT-5"\n\n[mcp_servers.below.http_headers]')
        secrets = ("SECRET-TRAILING-8", "SECRET-EXCL-7", "SECRET-OPCOMMENT-6", "SECRET-ENTRY-9", "SECRET-SUBINHERIT-5",
                   "SECRET-ABOVE-1", "SECRET-COMMENT-3", "SECRET-BELOW-2", "SECRETDIGEST-0123")
        with tempfile.TemporaryDirectory() as d:
            t = pathlib.Path(d, "config.toml")
            t.write_text(live.replace("/h/.bashrc", d + "/.bashrc"))
            for flags in ((), ("--write",)):
                r = self.run_apply(t, *flags)
                self.assertEqual(r.returncode, 0, r.stderr)
                for secret in secrets:
                    self.assertNotIn(secret, r.stdout + r.stderr, secret)
                self.assertIn('inherit = "core"', r.stdout)  # the fixed literal still prints, without its comment
                self.assertIn("<assignment hidden>", r.stdout)

    def test_multiline_strings_never_print_assignment_shaped_content(self) -> None:
        # PR71 review: a base64-like continuation was mistaken for a key and partly disclosed.
        for delimiter in ('"""', chr(39) * 3):
            for flags in ((), ("--write",)):
                with self.subTest(delimiter=delimiter, flags=flags), tempfile.TemporaryDirectory() as d:
                    target = pathlib.Path(d, "config.toml")
                    secret = "c2VjcmV0=="
                    original = self.LIVE.format(home=d).replace(
                        'inherit = "core"\n',
                        'inherit = "core"\nexclude = [' + delimiter + '\n' + secret
                        + '\nSYNTHETIC_CREDENTIAL = hidden-value\n' + delimiter + ']\n', 1)
                    tomllib.loads(original)  # exercise valid basic and literal multiline TOML
                    target.write_text(original)
                    result = self.run_apply(target, *flags)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    for private in (secret, "c2VjcmV0", "SYNTHETIC_CREDENTIAL", "hidden-value"):
                        self.assertNotIn(private, result.stdout + result.stderr)
                    self.assertIn("<assignment hidden>", result.stdout)
                    self.assertIn('inherit = "all"', result.stdout)
                    if flags:
                        (backup,) = pathlib.Path(d).glob("config.toml.bak-*-env-policy")
                        self.assertEqual(backup.read_text(), original)
                        self.assertEqual(tomllib.loads(target.read_text())["shell_environment_policy"]["set"],
                                         tomllib.loads(original)["shell_environment_policy"]["set"])
                    else:
                        self.assertEqual(target.read_text(), original)

    def test_a_subtable_key_named_inherit_is_hidden_even_when_the_header_is_the_templates(self) -> None:
        # 2026-10-25 adversary r2 (C1): the template's own `.set` header used to switch hiding off for what followed.
        mod = self.apply_module()
        header = "[shell_environment_policy.set]"
        public = {"[shell_environment_policy]", header, 'ENABLE_PROMPT_CACHING_1H = "1"', 'inherit = "core"'}
        view = mod.safe_view("[shell_environment_policy]\n" + header + '\ninherit = "SECRET-SUB-5"\nENABLE_PROMPT_CACHING_1H = "1"\n'
                             '[shell_environment_policy.extra]\nignore_default_excludes = true  # SECRET-C\n', public)
        self.assertNotIn("SECRET", view)
        self.assertEqual(view.split("\n")[1:4], [header, "<assignment hidden>", "<assignment hidden>"])
        self.assertIn("[<table hidden>]\n<assignment hidden>", view)

    def test_an_inline_set_in_the_old_policy_never_prints(self) -> None:
        # adversary MSG 4: the old policy may spell its explicit set inline under [shell_environment_policy].
        def live(d: str, timeout: str) -> str:
            inline = ('set = { NODE_REPL_TRUSTED_BROWSER_CLIENT_SHA256S = "SECRETDIGEST-0123", BASH_ENV = "%s/.bashrc", ENABLE_PROMPT_CACHING_1H = "1", '
                      'CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS = "1", MCP_TIMEOUT = "%s", CLAUDE_CODE_HARBOR_KITE = "1", GRAFT_NO_GITIGNORE = "1" }' % (d, timeout))
            return f'model = "m"\n\n[projects."/x"]\ntrust_level = "trusted"\n\n[shell_environment_policy]\ninherit = "core"\n{inline}\n\n[hooks.state."/y"]\ntrusted_hash = "SECRET-AFTER-8"\n'
        secrets = ("SECRETDIGEST-0123", "SECRET-INLINE-7", "SECRET-AFTER-8")
        with tempfile.TemporaryDirectory() as d:
            t = pathlib.Path(d, "config.toml")
            t.write_text(live(d, "SECRET-INLINE-7"))  # differs from the template's set: refused, key named, no value
            for flags in ((), ("--write",)):
                r = self.run_apply(t, *flags)
                self.assertEqual(r.returncode, 1, flags)
                self.assertIn("MCP_TIMEOUT", r.stderr)
                for secret in secrets:
                    self.assertNotIn(secret, r.stdout + r.stderr, secret)
            self.assertEqual(t.read_text(), live(d, "SECRET-INLINE-7"))
            t.write_text(live(d, "300000"))  # equal to the template's set: applied, nothing printed
            for flags in ((), ("--write",)):
                r = self.run_apply(t, *flags)
                self.assertEqual(r.returncode, 0, (flags, r.stderr))
                for secret in secrets:
                    self.assertNotIn(secret, r.stdout + r.stderr, secret)
                self.assertIn("<assignment hidden>", r.stdout) if not flags else None
            after = tomllib.loads(t.read_text())
            self.assertEqual(after["shell_environment_policy"]["set"]["NODE_REPL_TRUSTED_BROWSER_CLIENT_SHA256S"], "SECRETDIGEST-0123")
            self.assertEqual(after["hooks"]["state"]["/y"]["trusted_hash"], "SECRET-AFTER-8")  # neighbours kept

    # ---- the two changed-file refusals, driven deterministically through the module --------------------------------

    def apply_module(self):
        return load("codex_env_policy_apply_under_test", ROOT / "bin" / "codex-env-policy-apply")

    def edited_by_codex(self, t: pathlib.Path) -> bytes:
        """What a concurrent Codex write does: new content and a later mtime."""
        st = t.stat()
        data = t.read_bytes() + b'\n[projects."/concurrent"]\ntrust_level = "trusted"\n'
        t.write_bytes(data)
        os.utime(t, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
        return data

    def run_module(self, mod, t: pathlib.Path, home: str) -> tuple[object, str]:
        import contextlib, io
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": home}), contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            try:
                return mod.main([str(TEMPLATE), str(t), "--write"]), err.getvalue()
            except SystemExit as e:
                return e.code, err.getvalue()

    def test_a_change_between_read_and_recheck_refuses_and_keeps_the_concurrent_edit(self) -> None:
        mod = self.apply_module()
        with tempfile.TemporaryDirectory() as d:
            t = pathlib.Path(d, "config.toml")
            t.write_text(self.LIVE.format(home=d))
            real_read, calls, edited = mod.read, [], []

            def read_then_edit(path, what):
                calls.append(what)
                if what == "target" and calls.count("target") == 2:  # the recheck: Codex wrote just before it
                    edited.append(self.edited_by_codex(t))
                return real_read(path, what)

            with mock.patch.object(mod, "read", read_then_edit), mock.patch.object(mod.os, "replace", side_effect=AssertionError("replaced")) as rep:
                code, err = self.run_module(mod, t, d)
            self.assertEqual(code, 1)
            self.assertIn("changed while reading", err)
            self.assertEqual((rep.call_count, t.read_bytes()), (0, edited[0]))  # no replace; their edit stands, byte for byte
            self.assertEqual(sorted(os.listdir(d)), ["config.toml"])  # no backup, no temp file

    def test_a_change_after_the_temp_file_is_written_refuses_and_keeps_the_concurrent_edit(self) -> None:
        mod = self.apply_module()
        with tempfile.TemporaryDirectory() as d:
            t = pathlib.Path(d, "config.toml")
            t.write_text(self.LIVE.format(home=d))
            t.chmod(0o600)
            real_chmod, edited = mod.os.chmod, []

            def chmod_then_edit(path, mode, *a, **k):
                real_chmod(path, mode, *a, **k)
                if os.path.basename(str(path)).startswith(".config.toml."):  # the temp file is complete; Codex writes now
                    edited.append(self.edited_by_codex(t))

            with mock.patch.object(mod.os, "chmod", chmod_then_edit), mock.patch.object(mod.os, "replace", side_effect=AssertionError("replaced")) as rep:
                code, err = self.run_module(mod, t, d)
            self.assertEqual(code, 1)
            self.assertIn("target changed", err)
            self.assertEqual((rep.call_count, t.read_bytes()), (0, edited[0]))
            left = sorted(os.listdir(d))
            self.assertEqual([n for n in left if not n.startswith("config.toml.bak-")], ["config.toml"])  # temp file removed
            (bak,) = [n for n in left if n.startswith("config.toml.bak-")]  # the backup of what was read stays, private
            self.assertEqual((stat_mode(pathlib.Path(d, bak)), pathlib.Path(d, bak).read_text()), (0o600, self.LIVE.format(home=d)))

    def test_toml_parse_errors_are_reduced_to_a_position(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            t = pathlib.Path(d, "config.toml")
            t.write_text('a = 1\nSECRET-IN-KEY = "x"\nb = "SECRET-VALUE-4\n')
            r = self.run_apply(t)
            self.assertEqual(r.returncode, 1)
            self.assertRegex(r.stderr, r"line \d+, column \d+")
            for secret in ("SECRET-IN-KEY", "SECRET-VALUE-4"):
                self.assertNotIn(secret, r.stdout + r.stderr)


def stat_mode(p: pathlib.Path) -> int:
    return p.stat().st_mode & 0o777


if __name__ == "__main__":
    unittest.main()
