#!/usr/bin/env python3
"""kiro in acp-run (2026-10-25): `kiro-cli acp` runs yolo under --perm all only, never denies, never routes.

kiro-cli 2.34.0 takes -a/--trust-all-tools on `chat` and `acp`, not on the root command, so the
flag follows the subcommand. It is in YOLO_CMD (applied for --perm all) and not in AGENTS. --perm
deny is refused (DENY_UNSUPPORTED): Kiro runs workspace reads, grep, glob and `code` edits without
a session/request_permission, so only the tripwire would catch them, after the tool ran (adversary
BLOCK H1). acp-run is read as source (it imports the ACP SDK, which the test runner does not have);
the table entries are literals. Routing is checked on route_agent.discover() itself.
"""
from __future__ import annotations

import ast
import os
import sys
import tomllib
import unittest
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_route_agent import IDLE, r, sources  # noqa: E402  (pins every discovery source)

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("ACP_RUN_SCRIPT", str(ROOT / "tools" / "acp-run" / "acp-run")))


def table_entry(name: str, key: str) -> object:
    """The literal value stored under `key` in the module-level dict `name`."""
    for node in ast.parse(SCRIPT.read_text()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            assert isinstance(node.value, ast.Dict), name
            for k, v in zip(node.value.keys, node.value.values, strict=True):
                if isinstance(k, ast.Constant) and k.value == key:
                    return cast(object, ast.literal_eval(v))
    raise AssertionError(f"{name}[{key!r}] not found in {SCRIPT}")


def assigned_subscript(name: str, key: str) -> bool:
    """True when the module assigns `name[key] = ...` (DENY_UNSUPPORTED["kiro"] = ...)."""
    for node in ast.parse(SCRIPT.read_text()).body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                        and t.value.id == name and isinstance(t.slice, ast.Constant)
                        and t.slice.value == key):
                    return True
    return False


class TestKiroYolo(unittest.TestCase):
    def test_bare_command_has_no_trust_flag(self):
        self.assertEqual(table_entry("AGENTS", "kiro"), (["kiro-cli", "acp"], None))

    def test_yolo_command_puts_the_flag_after_the_subcommand(self):
        self.assertEqual(table_entry("YOLO_CMD", "kiro"), ["kiro-cli", "acp", "--trust-all-tools"])

    def test_deny_is_refused(self):
        """Not DENY_SET/DENY_ENV: nothing there makes Kiro ask before it reads or edits."""
        self.assertTrue(assigned_subscript("DENY_UNSUPPORTED", "kiro"))
        for table in ("DENY_SET", "DENY_ENV", "DENY_META"):
            with self.assertRaises(AssertionError):
                table_entry(table, "kiro")

    def test_first_run_model_download_gets_a_longer_handshake(self):
        self.assertEqual(table_entry("HANDSHAKE_TIMEOUT", "kiro"), 120)


class TestKiroNeverRouted(unittest.TestCase):
    def test_config_lists_it(self):
        policy = tomllib.loads((ROOT / "config" / "routing.toml").read_text())
        self.assertIn("kiro", policy["discovery"]["never_route"])

    def test_discovery_drops_an_ok_kiro_row(self):
        acp = "ok claude    claude-agent-acp\nok kiro      kiro-cli acp\n"
        with sources(acp=acp, installed=("kiro-cli",)):
            names = {s.name for s in r.discover(IDLE)}
        self.assertNotIn("kiro", names)
        self.assertIn("claude", names)


if __name__ == "__main__":
    unittest.main()
