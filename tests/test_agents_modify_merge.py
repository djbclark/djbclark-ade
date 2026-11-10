#!/usr/bin/env python3
"""Tests for agents/ Claude and Codex modify_ merge helpers (2026-11-10).

Fixture-only: never touches ~/.claude or ~/.codex.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LIB = REPO / "agents" / "modify_merge_lib.py"
CLAUDE = REPO / "agents" / "claude" / "modify_merge.py"
CODEX = REPO / "agents" / "codex" / "modify_merge.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


lib = _load(LIB, "agents_modify_merge_lib")
claude_cli = _load(CLAUDE, "claude_modify_merge")
codex_cli = _load(CODEX, "codex_modify_merge")


class MergeOwnedTest(unittest.TestCase):
    def test_keeps_unowned_top_level_and_applies_owned(self):
        live = {"model": "old", "tuiPluginWrote": True, "env": {"A": "1", "KEEP": "x"}}
        desired = {"model": "sonnet", "env": {"A": "2", "B": "3"}}
        got = lib.merge_owned(live, desired)
        self.assertEqual(got["model"], "sonnet")
        self.assertIs(got["tuiPluginWrote"], True)
        self.assertEqual(got["env"], {"A": "2", "KEEP": "x", "B": "3"})

    def test_lists_replace_not_append(self):
        live = {"allow": ["a", "b"]}
        desired = {"allow": ["c"]}
        self.assertEqual(lib.merge_owned(live, desired)["allow"], ["c"])

    def test_empty_live_is_desired(self):
        desired = {"model": "sonnet", "env": {"X": "1"}}
        self.assertEqual(lib.merge_owned({}, desired), desired)

    def test_codex_preserves_hooks_trust_and_tmp_projects_and_last_revision(self):
        live = {
            "model": "old",
            "hooks": {"trust": {"/tmp/hook.sh": "abc"}},
            "projects": {
                "/private/tmp/sess-1": {"trust_level": "trusted"},
                "/home/alex/src/ai": {"trust_level": "trusted"},
            },
            "marketplaces": {
                "composio": {
                    "source": "https://example.invalid/old.git",
                    "last_revision": "deadbeef",
                }
            },
        }
        desired = {
            "model": "gpt-6.1-sol",
            "projects": {
                "/home/alex/src/ai": {"trust_level": "trusted"},
                "/home/alex/src/new": {"trust_level": "trusted"},
            },
            "marketplaces": {
                "composio": {
                    "source_type": "git",
                    "source": "https://github.com/ComposioHQ/composio-plugin-openai.git",
                }
            },
        }
        got = lib.merge_owned(live, desired)
        self.assertEqual(got["model"], "gpt-6.1-sol")
        self.assertEqual(got["hooks"]["trust"]["/tmp/hook.sh"], "abc")
        self.assertIn("/private/tmp/sess-1", got["projects"])
        self.assertIn("/home/alex/src/new", got["projects"])
        self.assertEqual(
            got["marketplaces"]["composio"]["source"],
            "https://github.com/ComposioHQ/composio-plugin-openai.git",
        )
        self.assertEqual(got["marketplaces"]["composio"]["last_revision"], "deadbeef")


class RefuseLiveHomeTest(unittest.TestCase):
    def test_refuses_claude_and_codex_under_home(self):
        home = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(home))
        (home / ".claude").mkdir()
        (home / ".codex").mkdir()
        claude = home / ".claude" / "settings.json"
        codex = home / ".codex" / "config.toml"
        claude.write_text("{}")
        codex.write_text("")
        self.assertIsNotNone(lib.refuse_live_home(claude, home=home))
        self.assertIsNotNone(lib.refuse_live_home(codex, home=home))
        other = home / "fixture.json"
        self.assertIsNone(lib.refuse_live_home(other, home=home))


class TomlRoundtripTest(unittest.TestCase):
    def test_dump_load_preserves_merge_shape(self):
        data = {
            "model": "gpt-6.1-sol",
            "notify": ["/home/alex/bin/x", "turn-ended"],
            "marketplaces": {
                "composio": {
                    "source_type": "git",
                    "source": "https://github.com/ComposioHQ/composio-plugin-openai.git",
                    "last_revision": "abc123",
                }
            },
            "plugins": {'documents@openai-primary-runtime': {"enabled": True}},
            "shell_environment_policy": {
                "inherit": "all",
                "ignore_default_excludes": False,
                "set": {"FOO": "bar"},
            },
        }
        text = lib.dump_toml(data)
        back = tomllib.loads(text)
        self.assertEqual(back["model"], "gpt-6.1-sol")
        self.assertEqual(back["notify"], ["/home/alex/bin/x", "turn-ended"])
        self.assertEqual(back["marketplaces"]["composio"]["last_revision"], "abc123")
        self.assertTrue(back["plugins"]["documents@openai-primary-runtime"]["enabled"])
        self.assertEqual(back["shell_environment_policy"]["set"]["FOO"], "bar")


class ClaudeCliTest(unittest.TestCase):
    def test_write_merges_and_refuses_live_home(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root))
        desired = root / "desired.json"
        live = root / "live.json"
        out = root / "out.json"
        desired.write_text(json.dumps({"model": "sonnet", "env": {"A": "2"}}))
        live.write_text(json.dumps({"model": "old", "pluginOnly": 1, "env": {"A": "1", "Z": "z"}}))
        rc = claude_cli.main(["--desired", str(desired), "--live", str(live), "--write", str(out)])
        self.assertEqual(rc, 0)
        got = json.loads(out.read_text())
        self.assertEqual(got["model"], "sonnet")
        self.assertEqual(got["pluginOnly"], 1)
        self.assertEqual(got["env"]["Z"], "z")
        self.assertEqual(got["env"]["A"], "2")

        home = root / "home"
        (home / ".claude").mkdir(parents=True)
        banned = home / ".claude" / "settings.json"
        banned.write_text("{}")
        self.assertIsNotNone(lib.refuse_live_home(banned, home=home))
        env_home = dict(os.environ)
        env_home["HOME"] = str(home)
        # Re-exec through subprocess so Path.home() sees HOME.
        proc = subprocess.run(
            [sys.executable, str(CLAUDE), "--desired", str(desired), "--live", str(live),
             "--write", str(banned)],
            capture_output=True,
            text=True,
            env=env_home,
            check=False,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("refusing to write live", proc.stderr)
        self.assertEqual(banned.read_text(), "{}")


class CodexCliTest(unittest.TestCase):
    def test_stdin_stdout_keeps_unowned(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root))
        desired = root / "desired.toml"
        desired.write_text(
            'model = "gpt-6.1-sol"\n\n[marketplaces.composio]\n'
            'source_type = "git"\n'
            'source = "https://github.com/ComposioHQ/composio-plugin-openai.git"\n'
        )
        live = (
            'model = "old"\n\n[hooks.trust."/tmp/h"]\n'
            'hash = "abc"\n\n[marketplaces.composio]\n'
            'source = "https://example.invalid/old.git"\n'
            'last_revision = "deadbeef"\n'
        )
        proc = subprocess.run(
            [sys.executable, str(CODEX), "--desired", str(desired)],
            input=live,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        got = tomllib.loads(proc.stdout)
        self.assertEqual(got["model"], "gpt-6.1-sol")
        self.assertEqual(got["hooks"]["trust"]["/tmp/h"]["hash"], "abc")
        self.assertEqual(got["marketplaces"]["composio"]["last_revision"], "deadbeef")
        self.assertIn("github.com/ComposioHQ", got["marketplaces"]["composio"]["source"])


if __name__ == "__main__":
    unittest.main()
