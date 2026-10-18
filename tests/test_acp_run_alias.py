#!/usr/bin/env python3
"""tools/acp-run/acp-run: a family alias (`fable`, `opus`) that several listed models contain
resolves to the newest version, the same way on a fresh and a resumed session. 2026-10-18: a
resumed claude session listed `claude-fable-5-1` and `claude-fable-5`, so `--model fable` (which a
fresh session had accepted) died "ambiguous" and the resume with it. Loaded in a `uv run --with`
subprocess like test_acp_run_failure.py.
"""
from __future__ import annotations

import json
import os
import subprocess
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("ACP_RUN_SCRIPT", str(ROOT / "tools" / "acp-run" / "acp-run")))

PROBE = textwrap.dedent("""\
    import importlib.machinery, importlib.util, json, sys
    loader = importlib.machinery.SourceFileLoader("acp_run", sys.argv[1])
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("acp_run", loader))
    loader.exec_module(mod)
    out = {}
    for name, (values, want) in json.load(sys.stdin).items():
        v, amb = mod.match_value([{"value": x} for x in values], want)
        out[name] = [v["value"] if v else None, [c["value"] for c in amb]]
    print(json.dumps(out))
    """)

RESUMED = ["default", "opus", "claude-fable-5-1", "sonnet", "claude-fable-5", "claude-opus-5-5", "claude-opus-5",
           "claude-sonnet-5-5", "haiku"]
FRESH = ["default", "fable", "opus", "sonnet", "haiku", "claude-fable-5-1[1m]"]


class TestAlias(unittest.TestCase):
    def test_family_alias_resolves_to_the_newest_version_on_both_lists(self):
        cases = {
            "fable_resumed": [RESUMED, "fable"],
            "fable_fresh": [FRESH, "fable"],
            "opus_resumed": [RESUMED, "claude-opus"],
            "exact": [RESUMED, "claude-fable-5"],
            "ambiguous_no_version": [["nous:anthropic/claude-x", "other:anthropic/claude-x"], "claude-x"],
            "tie": [["a-foo-5", "b-foo-5"], "foo"],
        }
        r = subprocess.run(
            ["uv", "run", "--quiet", "--with", "agent-client-protocol>=0.9,<1.0", "python", "-I", "-c", PROBE,
             str(SCRIPT)], input=json.dumps(cases), check=False, capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["fable_resumed"], ["claude-fable-5-1", []])
        self.assertEqual(out["fable_fresh"][0], "fable")                 # an exact name still wins
        self.assertEqual(out["opus_resumed"], ["claude-opus-5-5", []])
        self.assertEqual(out["exact"], ["claude-fable-5", []])          # an exact value is never upgraded
        self.assertIsNone(out["ambiguous_no_version"][0])
        self.assertEqual(len(out["ambiguous_no_version"][1]), 2)
        self.assertIsNone(out["tie"][0])


if __name__ == "__main__":
    unittest.main()
