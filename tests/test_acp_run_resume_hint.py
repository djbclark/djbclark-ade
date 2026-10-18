#!/usr/bin/env python3
"""tools/acp-run/acp-run: after a quota stop in a one-shot run, stderr names the session and the
exact `acp-run ... --resume <sid>` command that continues it (operator 2026-10-18: a session's
thinking is work; never re-task it from a fresh brief). acp-run imports the ACP SDK, so the script
is loaded in a `uv run --with` subprocess, as test_acp_run_failure.py does.
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
    import argparse, importlib.machinery, importlib.util, json, sys
    from pathlib import Path
    loader = importlib.machinery.SourceFileLoader("acp_run", sys.argv[1])
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("acp_run", loader))
    loader.exec_module(mod)
    out = {}
    for name, kw in json.load(sys.stdin).items():
        a = argparse.Namespace(**{"agent": "codex", "model": None, "effort": None, "context": None, **kw})
        out[name] = mod.resume_hint(a, Path("/w/plektra djbclark"), "01a14d19-sid")
    print(json.dumps(out))
    """)


class TestResumeHint(unittest.TestCase):
    def test_hint_names_the_session_and_a_runnable_resume_command(self):
        cases = {"full": {"model": "gpt-6-astra", "effort": "high"}, "bare": {}}
        r = subprocess.run(
            ["uv", "run", "--quiet", "--with", "agent-client-protocol>=0.9,<1.0", "python", "-I", "-c", PROBE,
             str(SCRIPT)], input=json.dumps(cases), check=False, capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        full = out["full"]
        self.assertTrue(full.startswith("acp-run: usage limit stopped session 01a14d19-sid; after the reset continue it with: "), full)
        self.assertIn("acp-run codex -C '/w/plektra djbclark' --resume 01a14d19-sid --model gpt-6-astra --effort high -p ", full)
        self.assertIn("usage limit, not by you", full)
        self.assertIn("without redoing finished work", full)
        self.assertNotIn("--model", out["bare"])
        self.assertNotIn("--interactive", full)


if __name__ == "__main__":
    unittest.main()
