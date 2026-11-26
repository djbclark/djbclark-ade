#!/usr/bin/env python3
"""Tests for agents/ Claude and Codex modify_ merge helpers (2026-11-10).

Fixture-only: never touches ~/.claude or ~/.codex.
"""
from __future__ import annotations

import copy
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


def opaque_collection_cases():
    """Independent expected values for whole-entry preservation, not a merge oracle."""
    c = {"type": "command", "command": "local-check"}
    other = {"type": "command", "command": "other-check"}
    single = {"matcher": "*", "hooks": [c]}
    double = {"matcher": "*", "hooks": [c, c]}
    forward = {"matcher": "*", "hooks": [c, other]}
    reverse = {"matcher": "*", "hooks": [other, c]}
    events = [
        ("empty-keeps-inner-duplicates", [double], [], [double]),
        ("multiplicity-distinguishes-groups", [double], [single], [single, double]),
        ("outer-equality-only", [double, single, double], [double, double], [double, single]),
        ("nested-order-distinguishes-groups", [reverse], [forward], [forward, reverse]),
        ("opaque-nested-list-entries", [["a", "a"], ["a"]],
         [["a"], ["a"]], [["a"], ["a", "a"]]),
    ]
    cases = []
    for name, live_event, desired_event, expected_event in events:
        cases.append((name, {"hooks": {"PreToolUse": live_event}},
                      {"hooks": {"PreToolUse": desired_event}},
                      {"hooks": {"PreToolUse": expected_event}}))
    for name, live in [("missing-dict", {}), ("scalar-to-dict", {"hooks": "old"}),
                       ("missing-event", {"hooks": {}}),
                       ("scalar-to-list", {"hooks": {"PreToolUse": "old"}}),
                       ("dict-to-list", {"hooks": {"PreToolUse": {"old": True}}})]:
        cases.append((name, live, {"hooks": {"PreToolUse": [double, double]}},
                      {"hooks": {"PreToolUse": [double]}}))
    cases.append(("live-only-dict-key", {"local": {"event": [double, double]}}, {},
                  {"local": {"event": [double, double]}}))
    return copy.deepcopy(cases)


class MergeOwnedTest(unittest.TestCase):
    def test_keeps_unowned_top_level_and_applies_owned(self):
        live = {"model": "old", "tuiPluginWrote": True, "env": {"A": "1", "KEEP": "x"}}
        desired = {"model": "sonnet", "env": {"A": "2", "B": "3"}}
        got = lib.merge_owned(live, desired)
        self.assertEqual(got["model"], "sonnet")
        self.assertIs(got["tuiPluginWrote"], True)
        self.assertEqual(got["env"], {"A": "2", "KEEP": "x", "B": "3"})

    def test_lists_desired_first_preserve_live_and_deduplicate(self):
        live = {"allow": ["b", "a", "b", "local"], "deniedMcpServers": ["siyuan"]}
        desired = {"allow": ["c", "a", "c"], "deniedMcpServers": ["remote"]}
        self.assertEqual(lib.merge_owned(live, desired), {
            "allow": ["c", "a", "b", "local"],
            "deniedMcpServers": ["remote", "siyuan"],
        })
        self.assertEqual(lib.merge_owned(["local", "local"], []), ["local"])
        self.assertEqual(lib.merge_owned([], ["new", "new"]), ["new"])
        self.assertEqual(lib.merge_owned({}, {"new": ["x", "x"]}), {"new": ["x"]})

    def test_lists_hook_dicts_preserve_live_groups_and_copy_inputs(self):
        def group(command):
            return {"matcher": "*", "hooks": [{"type": "command", "command": command}]}
        owned = group("ade-check")
        local = [group("paseo hooks claude PreToolUse"), group("graft pre-bash || exit 0"),
                 group("collie beacon")]
        live = {"hooks": {"PreToolUse": [local[0], owned, *local[1:], local[0]],
                          "Stop": [group("local-stop")]}, "other": [{"nested": [1, 2]}]}
        desired = {"hooks": {"PreToolUse": [owned, owned, group("graft pre-bash")]},
                   "other": [{"nested": [2, 1]}, {"nested": [2, 1]}]}
        got = lib.merge_owned(live, desired)
        self.assertEqual(got["hooks"]["PreToolUse"], [owned, group("graft pre-bash"), *local])
        self.assertEqual(got["hooks"]["Stop"], [group("local-stop")])
        self.assertEqual(got["other"], [{"nested": [2, 1]}, {"nested": [1, 2]}])
        self.assertEqual(lib.merge_owned(got, desired), got)
        got["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = "changed"
        got["other"][1]["nested"].append(3)
        self.assertEqual(owned, group("ade-check"))
        self.assertEqual(live["other"], [{"nested": [1, 2]}])

    def test_lists_type_mismatch_and_scalars_use_desired(self):
        for live, desired in [(["live"], "desired"), ("live", ["desired"]),
                              ({"key": "live"}, []), (["live"], {"key": "desired"}),
                              ("live", "desired")]:
            with self.subTest(live=live, desired=desired):
                self.assertEqual(lib.merge_owned(live, desired), desired)

    def test_lists_first_merge_normalizes_new_and_type_changing_subtrees(self):
        # Recurse dictionary fields, but dedup only outer entries at a list boundary.
        # Repeated inner hooks belong to an opaque entry and must remain repeated.
        for live in [{}, {"new": "old"}, {"new": {}}, {"new": {"event": "old"}}]:
            for desired in [{"new": ["x", "x"]},
                            {"new": [{"hooks": ["x", "x"]}] * 2},
                            {"new": {"event": [{"hooks": ["x", "x"]}] * 2}}]:
                with self.subTest(live=live, desired=desired):
                    before = copy.deepcopy((live, desired))
                    first = lib.merge_owned(live, desired)
                    self.assertEqual(first, lib.merge_owned(first, desired))
                    expected = (["x"] if desired["new"] == ["x", "x"] else
                                [{"hooks": ["x", "x"]}] if isinstance(desired["new"], list) else
                                {"event": [{"hooks": ["x", "x"]}]})
                    self.assertEqual(first["new"], expected)
                    self.assertEqual((live, desired), before)
                    first["new"].clear()
                    self.assertEqual((live, desired), before)

    def test_opaque_entries_preserve_original_whole_values(self):
        for name, live, desired, expected in opaque_collection_cases():
            with self.subTest(case=name):
                originals = copy.deepcopy((live, desired, expected))
                first = lib.merge_owned(live, desired)
                self.assertEqual(first, expected)
                self.assertEqual(lib.merge_owned(first, desired), first)
                # Mutate every mutable level of the output to detect nested aliases.
                def mutate(value):
                    if isinstance(value, dict):
                        for child in list(value.values()):
                            mutate(child)
                        value["mutated"] = True
                    elif isinstance(value, list):
                        for child in value:
                            mutate(child)
                        value.append("mutated")
                mutate(first)
                self.assertEqual((live, desired, expected), originals)

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


class WrapperCollectionsTest(unittest.TestCase):
    def test_claude_wrapper_opaque_entries(self):
        for name, live, desired, expected in opaque_collection_cases():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as tmp:
                originals = copy.deepcopy((live, desired))
                target = Path(tmp) / "desired.json"
                target.write_text(json.dumps(desired))
                def run(value):
                    proc = subprocess.run([sys.executable, str(CLAUDE), "--desired", str(target)],
                                          input=json.dumps(value), text=True, capture_output=True)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    return json.loads(proc.stdout)
                first = run(live)
                self.assertEqual(first, expected)
                self.assertEqual(run(first), first)
                first.clear()
                self.assertEqual((live, desired), originals)

    def test_wrappers_collection_preservation_and_atomic_notify(self):
        for wrapper, suffix in [(CLAUDE, "json"), (CODEX, "toml")]:
            for old_notify in [["/old", "x"], ["/old", "different"], None]:
                for live_collection in [None, "old", ["local", "local"]]:
                    with self.subTest(wrapper=wrapper, notify=old_notify, collection=live_collection):
                        live = {}
                        if live_collection is not None:
                            live["deniedMcpServers"] = live_collection
                        if old_notify is not None:
                            live["notify"] = old_notify
                        desired = {"deniedMcpServers": ["remote", "remote"]}
                        if suffix == "json":
                            desired["hooks"] = {"PreToolUse": [{"hooks": [{"command": "ade"}]}] * 2}
                            live["hooks"] = {"PreToolUse": [{"hooks": [{"command": "collie"}]}]}
                        else:
                            desired["notify"] = ["/new", "x", "x"]
                        encode = json.dumps if suffix == "json" else lib.dump_toml
                        decode = json.loads if suffix == "json" else tomllib.loads
                        with tempfile.TemporaryDirectory() as tmp:
                            target = Path(tmp) / ("desired." + suffix)
                            target.write_text(encode(desired))
                            def run(value):
                                proc = subprocess.run([sys.executable, str(wrapper), "--desired", str(target)],
                                                      input=encode(value), text=True, capture_output=True)
                                self.assertEqual(proc.returncode, 0, proc.stderr)
                                return decode(proc.stdout)
                            first = run(live)
                            self.assertEqual(first, run(first))
                            self.assertEqual(first["deniedMcpServers"],
                                             ["remote", "local"] if isinstance(live_collection, list) else ["remote"])
                            if suffix == "toml":
                                self.assertEqual(first["notify"], ["/new", "x", "x"])
                                del desired["notify"]
                                target.write_text(encode(desired))
                                unowned = {"notify": ["/local", "x", "x"]}
                                kept = run(unowned)
                                self.assertEqual(kept["notify"], unowned["notify"])
                                self.assertEqual(kept, run(kept))
                            else:
                                self.assertEqual(first["hooks"]["PreToolUse"],
                                                 [desired["hooks"]["PreToolUse"][0], live["hooks"]["PreToolUse"][0]])

    def test_mcp_args_are_replaced_whole_not_merged(self):
        """args is a positional argv, like notify: repeated flags survive, desired [] clears live args,
        unowned live args stay intact with duplicates, copies are independent, and both wrappers agree."""
        live = {
            "mcp_servers": {
                "node_repl": {"command": "node", "args": ["--include", "old", "--weird"]},
                "local_only": {"command": "tool", "args": ["-v", "-v", "target"]},
            }
        }
        desired = {"mcp_servers": {"node_repl": {"command": "node", "args": ["--include", "a", "--include", "b"]}}}
        got = lib.merge_owned(live, desired)
        self.assertEqual(got["mcp_servers"]["node_repl"]["args"], ["--include", "a", "--include", "b"])
        self.assertEqual(got["mcp_servers"]["local_only"]["args"], ["-v", "-v", "target"])
        # Deep-copy independence: mutating merged output never mutates inputs
        got["mcp_servers"]["node_repl"]["args"].append("--mutated")
        got["mcp_servers"]["local_only"]["args"].append("--mutated")
        self.assertEqual(desired["mcp_servers"]["node_repl"]["args"], ["--include", "a", "--include", "b"])
        self.assertEqual(live["mcp_servers"]["local_only"]["args"], ["-v", "-v", "target"])

        cleared = lib.merge_owned(live, {"mcp_servers": {"node_repl": {"args": []}}})
        self.assertEqual(cleared["mcp_servers"]["node_repl"]["args"], [])

        # End-to-end wrapper subprocess check (Claude JSON + Codex TOML)
        for wrapper, suffix in ((CLAUDE, "json"), (CODEX, "toml")):
            encode = json.dumps if suffix == "json" else lib.dump_toml
            decode = json.loads if suffix == "json" else tomllib.loads
            with tempfile.TemporaryDirectory() as tmp:
                desired_path = Path(tmp) / f"desired.{suffix}"
                desired_path.write_text(encode(desired), encoding="utf-8")
                proc = subprocess.run(
                    [sys.executable, str(wrapper), "--desired", str(desired_path)],
                    input=encode(live),
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                merged = decode(proc.stdout)
                self.assertEqual(merged["mcp_servers"]["node_repl"]["args"], ["--include", "a", "--include", "b"])
                self.assertEqual(merged["mcp_servers"]["local_only"]["args"], ["-v", "-v", "target"])
                desired_path.write_text(encode({"mcp_servers": {"node_repl": {"args": []}}}), encoding="utf-8")
                proc2 = subprocess.run(
                    [sys.executable, str(wrapper), "--desired", str(desired_path)],
                    input=encode(live),
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(proc2.returncode, 0, proc2.stderr)
                self.assertEqual(decode(proc2.stdout)["mcp_servers"]["node_repl"]["args"], [])



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
