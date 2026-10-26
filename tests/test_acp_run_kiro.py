#!/usr/bin/env python3
"""kiro in acp-run (2026-10-25): `kiro-cli acp` runs yolo under --perm all only, and is never routed.

kiro-cli 2.34.0 takes -a/--trust-all-tools on `chat` and `acp`, not on the root command, so the
flag follows the subcommand. It is in YOLO_CMD (applied for --perm all) and not in AGENTS, so a
--perm deny run starts `kiro-cli acp` bare and Kiro asks for every tool. acp-run is read as source
(it imports the ACP SDK, which the test runner does not have); the table entries are literals.
"""
from __future__ import annotations

import ast
import os
import tomllib
import unittest
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("ACP_RUN_SCRIPT", str(ROOT / "tools" / "acp-run" / "acp-run")))


def table_entry(name: str, key: str) -> object:
    """The literal value stored under `key` in the module-level dict `name` (first element of an
    AGENTS tuple is the command)."""
    for node in ast.parse(SCRIPT.read_text()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            assert isinstance(node.value, ast.Dict), name
            for k, v in zip(node.value.keys, node.value.values, strict=True):
                if isinstance(k, ast.Constant) and k.value == key:
                    return cast(object, ast.literal_eval(v))
    raise AssertionError(f"{name}[{key!r}] not found in {SCRIPT}")


class TestKiroYolo(unittest.TestCase):
    def test_bare_command_has_no_trust_flag(self):
        self.assertEqual(table_entry("AGENTS", "kiro"), (["kiro-cli", "acp"], None))

    def test_yolo_command_puts_the_flag_after_the_subcommand(self):
        self.assertEqual(table_entry("YOLO_CMD", "kiro"), ["kiro-cli", "acp", "--trust-all-tools"])

    def test_discovery_never_routes_kiro(self):
        policy = tomllib.loads((ROOT / "config" / "routing.toml").read_text())
        self.assertIn("kiro", policy["discovery"]["never_route"])


if __name__ == "__main__":
    unittest.main()
