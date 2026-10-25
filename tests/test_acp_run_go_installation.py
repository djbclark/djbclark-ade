#!/usr/bin/env python3
"""acp-run's OpenCode Go cost gate in a standalone (copied) install (PR 64 review, 2026-10-25).

A copy of the script on PATH must stay self-contained for non-Go models; a Go model needs the policy
bundle (bin/go_model_policy.py + config/go-model-policy.json under ~/.local/share/acp-run/go-policy)
and is refused with an actionable usage/config error, before any prompt, when it is missing or
broken. Everything runs against a fake `opencode` ACP agent first on a hermetic PATH, with HOME and
state inside a temp dir: no model is called.
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
from typing import ClassVar, override

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("ACP_RUN_SCRIPT", str(ROOT / "tools" / "acp-run" / "acp-run")))
SDK = "agent-client-protocol>=0.9,<1.0"
UV = shutil.which("uv") or "uv"
BUNDLE_REL = Path(".local/share/acp-run/go-policy")

# Fake opencode: one select "model" option; FAKE_SWITCH_TO makes it resolve any requested model to
# another one (a fuzzy resolver or an applied-provider switch); counts prompts it receives.
FAKE = textwrap.dedent("""\
    #!/usr/bin/env python3
    import json, os, sys
    from pathlib import Path
    VALUES = ["sipb/test", "opencode-go/gpt-6-luna", "opencode-go/kimi-k3", "opencode-go/new-model"]
    MODEL = {"id": "model", "name": "Model", "category": "model", "type": "select",
             "currentValue": "sipb/test", "options": [{"value": v, "name": v} for v in VALUES]}
    out = Path(os.environ["FAKE_OUT"])
    cfg = os.environ.get("OPENCODE_CONFIG_DIR")
    plug = Path(cfg or "/nonexistent") / "plugins"
    seen = {"started": True, "prompts": 0, "sets": [],
            "config_dir": cfg, "project_off": os.environ.get("OPENCODE_DISABLE_PROJECT_CONFIG"),
            "plugins": sorted(e.name for e in plug.iterdir()) if plug.is_dir() else None,
            "plugin_real": {e.name: str(e.resolve()) for e in plug.iterdir()} if plug.is_dir() else {},
            "plugin_files": {e.name: sorted(x.name for x in e.iterdir()) for e in plug.iterdir() if e.is_dir()}
                            if plug.is_dir() else {},
            "cfg_json": json.loads(Path(cfg, "opencode.json").read_text()) if cfg and Path(cfg, "opencode.json").exists() else None}
    out.write_text(json.dumps(seen))

    def send(o):
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", **o}) + "\\n")
        sys.stdout.flush()

    for line in sys.stdin:
        msg = json.loads(line)
        m, i = msg.get("method"), msg.get("id")
        if m == "initialize":
            send({"id": i, "result": {"protocolVersion": 1, "agentCapabilities": {}, "authMethods": []}})
        elif m == "session/new":
            send({"id": i, "result": {"sessionId": "s1", "configOptions": [MODEL]}})
        elif m == "session/set_config_option":
            seen["sets"].append(msg["params"])
            MODEL["currentValue"] = os.environ.get("FAKE_SWITCH_TO") or msg["params"]["value"]
            out.write_text(json.dumps(seen))
            send({"id": i, "result": {"configOptions": [MODEL]}})
        elif m == "session/prompt":
            seen["prompts"] += 1
            out.write_text(json.dumps(seen))
            send({"method": "session/update", "params": {"sessionId": "s1", "update": {
                "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "ok"}}}})
            send({"id": i, "result": {"stopReason": "end_turn"}})
        elif i is not None:
            send({"id": i, "error": {"code": -32601, "message": "not supported"}})
    """)

PERMISSIVE_HELPER = textwrap.dedent("""\
    def policy(): return {}
    def classification(model): return "routine"
    def refusal(model, **kw): return None
    """)

ADVISORY = ["--go-advisory", "--perm", "read-only", "--timeout", "600"]


def _uv_python() -> str:
    r = subprocess.run([UV, "python", "find", ">=3.10,<3.15"], check=False, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "python3"


class GoInstallBase(unittest.TestCase):
    tmp: ClassVar[Path]
    fake_bin: ClassVar[Path]
    cache: ClassVar[str]
    runs: ClassVar[int] = 0

    @classmethod
    @override
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="acp-go-install-"))
        cls.fake_bin = cls.tmp / "fakebin"
        cls.fake_bin.mkdir()
        f = cls.fake_bin / "opencode"
        f.write_text(FAKE)
        f.chmod(f.stat().st_mode | stat.S_IXUSR)
        cls.cache = subprocess.run([UV, "cache", "dir"], check=True, capture_output=True, text=True).stdout.strip()
        cls.uv_python = _uv_python()

    @classmethod
    @override
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # --- layouts ---
    def new_home(self) -> Path:
        type(self).runs += 1
        home = self.tmp / f"home{type(self).runs}"
        home.mkdir()
        return home

    def standalone_copy(self, home: Path) -> Path:
        """Only the script, copied the way README's `install -m 755` does; nothing beside it."""
        d = home / ".local" / "bin"
        d.mkdir(parents=True)
        dest = d / "acp-run"
        shutil.copy(SCRIPT, dest)
        dest.chmod(0o755)
        return dest

    def install_bundle(self, home: Path) -> Path:
        d = home / BUNDLE_REL
        (d / "bin").mkdir(parents=True)
        (d / "config").mkdir()
        shutil.copy(ROOT / "bin" / "go_model_policy.py", d / "bin")
        shutil.copy(ROOT / "config" / "go-model-policy.json", d / "config")
        shutil.copytree(ROOT / "opencode-plugins" / "go-context", d / "opencode-plugins" / "go-context",
                        ignore=shutil.ignore_patterns("node_modules", "*.test.js"))
        return d

    def write_user_config(self, home: Path) -> None:
        """A user OpenCode config with an untrusted plugin, a look-alike guard and MCP."""
        oc = home / ".config" / "opencode"
        (oc / "plugins" / "evil").mkdir(parents=True)
        (oc / "plugins" / "evil" / "index.js").write_text("export default {}\n")
        (oc / "plugins" / "ade-go-context").mkdir()
        (oc / "plugins" / "ade-go-context" / "index.js").write_text("// look-alike, not trusted\n")
        (oc / "opencode.json").write_text(json.dumps({
            "provider": {"sipb": {"options": {"baseURL": "http://localhost:1"}}},
            "plugin": ["opencode-evil@1.0"], "mcp": {"srv": {"type": "local", "command": ["true"]}}}))

    def run_acp(self, script: Path, home: Path, model: str, *args: str,
                switch_to: str | None = None) -> dict:
        d = self.tmp / f"run-{home.name}-{len(list(self.tmp.glob(f'run-{home.name}-*')))}"
        d.mkdir()
        out = d / "seen.json"
        env = {"PATH": f"{self.fake_bin}:/usr/bin:/bin:/usr/sbin:/sbin", "UV_PYTHON": self.uv_python,
               "HOME": str(home), "UV_CACHE_DIR": self.cache, "FAKE_OUT": str(out), "TMPDIR": str(d)}
        if switch_to:
            env["FAKE_SWITCH_TO"] = switch_to
        argv = [UV, "run", "--quiet", "--with", SDK, "python", "-I", str(script), "opencode", "-C", str(d),
                "-p", "Reply with the word ok", "--handshake-tries", "1", "--handshake-timeout", "20",
                "--no-fallback", *([] if "--timeout" in args else ["--timeout", "60"]),
                "--log", str(d / "log.jsonl"), "--model", model, *args]
        p = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=180, check=False)
        seen = json.loads(out.read_text()) if out.exists() else {"started": False, "prompts": 0}
        return {"rc": p.returncode, "stdout": p.stdout, "stderr": p.stderr, "seen": seen}

    def assert_refused_early(self, r: dict, rc: int, text: str) -> None:
        self.assertEqual(r["rc"], rc, r["stderr"])
        self.assertRegex(r["stderr"], text)
        self.assertNotIn("Traceback", r["stderr"])
        self.assertEqual(r["seen"]["prompts"], 0, "no prompt may reach the agent")
        self.assertEqual(r["stdout"].strip(), "")


class TestStandaloneWithoutPolicy(GoInstallBase):
    def test_non_go_prompt_runs_from_a_lone_copy(self):
        home = self.new_home()
        r = self.run_acp(self.standalone_copy(home), home, "sipb/test")
        self.assertEqual(r["rc"], 0, r["stderr"])
        self.assertEqual(r["stdout"].strip(), "ok")
        self.assertEqual(r["seen"]["prompts"], 1)
        self.assertNotIn("Go cost policy", r["stderr"])

    def test_go_models_fail_closed_with_an_install_hint_before_launch(self):
        home = self.new_home()
        script = self.standalone_copy(home)
        for model, extra in (("opencode-go/gpt-6-luna", []), ("opencode-go/kimi-k3", ADVISORY),
                             ("opencode-go/new-model", ADVISORY), ("OpenCode-Go/kimi-k3", [])):
            with self.subTest(model=model):
                r = self.run_acp(script, home, model, *extra)
                self.assert_refused_early(r, 2, "Go cost policy is not installed")
                self.assertIn(str(home / BUNDLE_REL), r["stderr"])
                self.assertFalse(r["seen"]["started"], "the agent must not even start")

    def test_helper_beside_the_script_or_in_the_cwd_is_not_trusted(self):
        home = self.new_home()
        script = self.standalone_copy(home)
        for where in (script.parent, home):
            (where / "go_model_policy.py").write_text(PERMISSIVE_HELPER)
        r = self.run_acp(script, home, "opencode-go/kimi-k3")
        self.assert_refused_early(r, 2, "Go cost policy is not installed")

    def test_applied_switch_to_go_cannot_bypass_the_gate(self):
        home = self.new_home()
        script = self.standalone_copy(home)
        for switched in ("opencode-go/kimi-k3", "opencode-go/gpt-6-luna", "opencode-go/new-model"):
            with self.subTest(switched=switched):
                r = self.run_acp(script, home, "sipb/test", switch_to=switched)
                self.assert_refused_early(r, 1, "exact applied provider/model|agent reports")


class TestInstalledBundle(GoInstallBase):
    def setUp(self) -> None:
        self.home = self.new_home()
        self.script = self.standalone_copy(self.home)
        self.bundle = self.install_bundle(self.home)

    def test_routine_go_model_runs(self):
        r = self.run_acp(self.script, self.home, "opencode-go/gpt-6-luna")
        self.assertEqual(r["rc"], 0, r["stderr"])
        self.assertEqual(r["seen"]["prompts"], 1)

    def test_expensive_and_unknown_models_are_refused(self):
        cases = [
            ("opencode-go/kimi-k3", [], "advisory-only"),
            ("OpenCode-Go/KIMI-K3", [], "advisory-only"),
            ("opencode-go/new-model", [], "unclassified"),
            ("opencode-go/new-model", ADVISORY, "unclassified"),
            ("opencode-go/kimi-k3", ["--go-advisory", "--timeout", "600"], "read-only"),
            ("opencode-go/kimi-k3", ["--go-advisory", "--perm", "read-only", "--timeout", "601"], "timeout"),
            ("opencode-go/kimi-k3", ["--go-advisory", "--perm", "read-only", "--timeout", "600",
                                     "--context", "1m"], "context"),
            ("opencode-go/kimi-k3", [*ADVISORY, "--interactive"], "single-turn"),
            ("opencode-go/kimi-k3", [*ADVISORY, "--prompt-retries", "1"], "retries"),
            ("opencode-go/kimi-k3", [*ADVISORY, "--set", "model=opencode-go/kimi-k3"], "--model, not --set"),
        ]
        for model, extra, text in cases:
            with self.subTest(model=model, extra=extra):
                r = self.run_acp(self.script, self.home, model, *extra)
                self.assert_refused_early(r, 2, text)
                self.assertFalse(r["seen"]["started"])

    def test_bounded_read_only_advice_runs(self):
        r = self.run_acp(self.script, self.home, "opencode-go/kimi-k3", *ADVISORY)
        self.assertEqual(r["rc"], 0, r["stderr"])
        self.assertEqual(r["seen"]["prompts"], 1)

    def test_applied_switch_to_go_cannot_bypass_the_gate(self):
        for switched in ("opencode-go/kimi-k3", "opencode-go/new-model"):
            with self.subTest(switched=switched):
                r = self.run_acp(self.script, self.home, "sipb/test", switch_to=switched)
                self.assert_refused_early(r, 1, "exact applied provider/model|agent reports")
        r = self.run_acp(self.script, self.home, "opencode-go/gpt-6-luna", switch_to="opencode-go/kimi-k3")
        self.assert_refused_early(r, 1, "exact applied provider/model|agent reports")

    def test_fuzzy_alias_is_refused(self):
        r = self.run_acp(self.script, self.home, "go/kimi-k3", switch_to="go/kimi-k3")
        self.assert_refused_early(r, 1, "exact applied provider/model|agent reports")

    def test_a_broken_bundle_fails_closed_without_a_traceback(self):
        helper_json = self.bundle / "config" / "go-model-policy.json"
        helper_json.write_text("{not json")
        r = self.run_acp(self.script, self.home, "opencode-go/gpt-6-luna")
        self.assert_refused_early(r, 2, "Go cost policy is not installed")
        self.assertIn("JSONDecodeError", r["stderr"])
        helper_json.unlink()
        r = self.run_acp(self.script, self.home, "opencode-go/gpt-6-luna")
        self.assert_refused_early(r, 2, "Go cost policy is not installed")
        ok = self.run_acp(self.script, self.home, "sipb/test")
        self.assertEqual(ok["rc"], 0, "non-Go stays independent of the policy: " + ok["stderr"])


class TestSanitizedGuardRetention(GoInstallBase):
    """P2 (PR 64): the sanitized read-only/--strip-user-config config keeps the trusted guard, nothing else."""

    def setUp(self) -> None:
        self.home = self.new_home()
        self.write_user_config(self.home)
        self.script = self.standalone_copy(self.home)
        self.bundle = self.install_bundle(self.home)

    def guard_dir(self) -> str:
        return str((self.bundle / "opencode-plugins" / "go-context").resolve())

    def test_advisory_run_keeps_only_the_trusted_guard_from_the_bundle(self):
        r = self.run_acp(self.script, self.home, "opencode-go/kimi-k3", *ADVISORY)
        self.assertEqual(r["rc"], 0, r["stderr"])
        s = r["seen"]
        self.assertIn("acp-run-opencode-deny-", s["config_dir"], "the sanitized config is in use")
        self.assertEqual(s["plugins"], ["ade-go-context"], "no user plugin, no look-alike")
        self.assertEqual(s["plugin_real"]["ade-go-context"], self.guard_dir(), "the bundle's guard, not the user's")
        self.assertIn("index.js", s["plugin_files"]["ade-go-context"])
        self.assertEqual(s["project_off"], "1", "project plugins stay off")
        self.assertNotIn("plugin", s["cfg_json"], "no plugin entry from the user's config")
        self.assertNotIn("mcp", s["cfg_json"])
        self.assertIn("provider", s["cfg_json"], "provider selection is still kept")

    def test_strip_user_config_on_a_routine_go_run_also_keeps_the_guard(self):
        r = self.run_acp(self.script, self.home, "opencode-go/gpt-6-luna", "--strip-user-config")
        self.assertEqual(r["rc"], 0, r["stderr"])
        self.assertEqual(r["seen"]["plugins"], ["ade-go-context"])
        self.assertIn("acp-run-opencode-strip-", r["seen"]["config_dir"])

    def test_non_go_sanitized_run_stays_pluginless_and_needs_no_bundle(self):
        for bundle in (True, False):
            home = self.new_home()
            self.write_user_config(home)
            script = self.standalone_copy(home)
            if bundle:
                self.install_bundle(home)
            for extra in (["--perm", "read-only"], ["--strip-user-config"]):
                with self.subTest(bundle=bundle, extra=extra):
                    r = self.run_acp(script, home, "sipb/test", *extra)
                    self.assertEqual(r["rc"], 0, r["stderr"])
                    self.assertIsNone(r["seen"]["plugins"], "no plugins dir at all for a non-Go model")
                    self.assertIsNone(r["seen"]["cfg_json"].get("plugin"))

    def test_unsanitized_routine_go_run_needs_no_guard_file(self):
        shutil.rmtree(self.bundle / "opencode-plugins")
        r = self.run_acp(self.script, self.home, "opencode-go/gpt-6-luna")
        self.assertEqual(r["rc"], 0, r["stderr"])
        self.assertIsNone(r["seen"]["config_dir"], "perm all without strip keeps the user's own config")

    def test_missing_or_incomplete_guard_fails_closed_before_launch(self):
        base = self.bundle / "opencode-plugins" / "go-context"
        runs = [("opencode-go/kimi-k3", ADVISORY), ("opencode-go/gpt-6-luna", ["--perm", "read-only"]),
                ("opencode-go/gpt-6-luna", ["--strip-user-config"])]
        for broken in ("absent", "no-index", "no-package"):
            if broken == "absent":
                shutil.rmtree(self.bundle / "opencode-plugins")
            elif broken == "no-index":
                (self.bundle / "opencode-plugins").mkdir(exist_ok=True)
                base.mkdir(exist_ok=True)
                (base / "package.json").write_text("{}")
            else:
                (base / "index.js").write_text("")
                (base / "package.json").unlink()
            for model, extra in runs:
                with self.subTest(broken=broken, model=model, extra=extra):
                    r = self.run_acp(self.script, self.home, model, *extra)
                    self.assert_refused_early(r, 2, "trusted Go context guard")
                    self.assertFalse(r["seen"]["started"])
                    self.assertIn(str(self.bundle), r["stderr"], "names the install location")

    def test_guard_paired_with_a_different_policy_file_is_refused(self):
        shutil.rmtree(self.bundle / "bin")
        (self.bundle / "bin").symlink_to(ROOT / "bin")  # the helper now enforces ROOT/config, the guard reads the bundle's
        r = self.run_acp(self.script, self.home, "opencode-go/kimi-k3", *ADVISORY)
        self.assert_refused_early(r, 2, "not the policy acp-run enforces")

    def test_a_bundle_of_links_to_the_checkout_tracks_it(self):
        home = self.new_home()
        script = self.standalone_copy(home)
        d = home / BUNDLE_REL
        d.mkdir(parents=True)
        for name in ("bin", "config", "opencode-plugins"):
            (d / name).symlink_to(ROOT / name)
        r = self.run_acp(script, home, "opencode-go/kimi-k3", *ADVISORY)
        self.assertEqual(r["rc"], 0, r["stderr"])
        self.assertEqual(r["seen"]["plugin_real"]["ade-go-context"],
                         str((ROOT / "opencode-plugins" / "go-context").resolve()))

    def test_checkout_layout_uses_that_trees_guard(self):
        home = self.new_home()
        self.write_user_config(home)
        tree = home / "checkout"
        (tree / "tools/acp-run").mkdir(parents=True)
        for rel in ("bin", "config"):
            shutil.copytree(ROOT / rel, tree / rel, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "opencode-plugins" / "go-context", tree / "opencode-plugins" / "go-context",
                        ignore=shutil.ignore_patterns("node_modules", "*.test.js"))
        shutil.copy(SCRIPT, tree / "tools/acp-run/acp-run")
        r = self.run_acp(tree / "tools/acp-run/acp-run", home, "opencode-go/kimi-k3", *ADVISORY)
        self.assertEqual(r["rc"], 0, r["stderr"])
        self.assertEqual(r["seen"]["plugins"], ["ade-go-context"])
        self.assertEqual(r["seen"]["plugin_real"]["ade-go-context"],
                         str((tree / "opencode-plugins" / "go-context").resolve()))


class TestCheckoutLayout(GoInstallBase):
    def test_broken_checkout_policy_cannot_fall_back_to_a_valid_installed_snapshot(self):
        home = self.new_home()
        self.install_bundle(home)
        tree = home / "checkout"
        for rel in ("tools/acp-run", "bin", "config"):
            (tree / rel).mkdir(parents=True)
        shutil.copy(SCRIPT, tree / "tools/acp-run/acp-run")
        shutil.copy(ROOT / "bin/go_model_policy.py", tree / "bin")
        config = tree / "config/go-model-policy.json"
        config.write_text("{broken json")
        result = self.run_acp(tree / "tools/acp-run/acp-run", home, "opencode-go/gpt-6-luna")
        self.assert_refused_early(result, 2, "Go cost policy is not installed")
        self.assertFalse(result["seen"]["started"])
        config.unlink()
        result = self.run_acp(tree / "tools/acp-run/acp-run", home, "opencode-go/gpt-6-luna")
        self.assert_refused_early(result, 2, "Go cost policy is not installed")
        self.assertFalse(result["seen"]["started"])

    def test_script_in_a_checkout_tree_uses_that_trees_policy(self):
        home = self.new_home()
        tree = home / "checkout"
        for rel in ("tools/acp-run", "bin", "config"):
            (tree / rel).mkdir(parents=True)
        shutil.copy(SCRIPT, tree / "tools/acp-run/acp-run")
        shutil.copy(ROOT / "bin/go_model_policy.py", tree / "bin")
        shutil.copy(ROOT / "config/go-model-policy.json", tree / "config")
        script = tree / "tools/acp-run/acp-run"
        ok = self.run_acp(script, home, "opencode-go/gpt-6-luna")
        self.assertEqual(ok["rc"], 0, ok["stderr"])
        r = self.run_acp(script, home, "opencode-go/kimi-k3")
        self.assert_refused_early(r, 2, "advisory-only")


if __name__ == "__main__":
    unittest.main()
