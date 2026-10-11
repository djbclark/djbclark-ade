#!/usr/bin/env python3
"""acp-run --session-id (2026-10-11, hcom trial: borrow uam's Claude --session-id seeding).

The claude CLI fallback (ACP handshake hang, headless only) runs `claude -p --session-id <id>` with the
seeded id, or a fresh UUID, and logs it as new_session, so launch.py's reply/resume lands in exactly that
conversation. acp-run imports the ACP SDK, so the script is loaded in a `uv run --with` subprocess.
"""
from __future__ import annotations

import json
import os
import subprocess
import textwrap
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("ACP_RUN_SCRIPT", str(ROOT / "tools" / "acp-run" / "acp-run")))
WITH = ["uv", "run", "--quiet", "--with", "agent-client-protocol>=0.9,<1.0", "python", "-I"]

PROBE = textwrap.dedent("""\
    import importlib.machinery, importlib.util, json, sys
    from types import SimpleNamespace
    loader = importlib.machinery.SourceFileLoader("acp_run", sys.argv[1])
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("acp_run", loader))
    loader.exec_module(mod)
    out = []
    class Client:
        def __init__(self): self.rows = []
        def rec(self, kind, data): self.rows.append([kind, data])
    def fake_run(cmd, **kw):
        out[-1]["cmd"] = cmd
        return SimpleNamespace(returncode=0)
    mod.subprocess.run = fake_run
    for seed in (None, "0b8f6d0e-5d1c-4c35-9a77-3f1f2b6f9b10"):
        c = Client()
        out.append({})
        a = SimpleNamespace(agent="claude", model="haiku", prompt_text="hi", perm="all", dir=".", session_id=seed)
        out[-1]["rc"] = mod.fallback_cli(a, c)
        out[-1]["rows"] = c.rows
    print(json.dumps(out))
    """)


class TestSessionSeed(unittest.TestCase):
    def test_cli_fallback_runs_as_the_seeded_or_a_fresh_id_and_logs_it(self) -> None:
        r = subprocess.run([*WITH, "-c", PROBE, str(SCRIPT)], check=False, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        fresh, seeded = json.loads(r.stdout)
        for case in (fresh, seeded):
            cmd = case["cmd"]
            sid = cmd[cmd.index("--session-id") + 1]
            self.assertEqual(str(uuid.UUID(sid)), sid)
            self.assertEqual(case["rows"], [["new_session", {"sessionId": sid, "via": "claude-cli"}]])
            self.assertEqual(cmd[:3], ["claude", "-p", "hi"])
        self.assertEqual(seeded["cmd"][seeded["cmd"].index("--session-id") + 1], "0b8f6d0e-5d1c-4c35-9a77-3f1f2b6f9b10")

    def test_session_id_is_claude_only_and_must_be_a_uuid(self) -> None:
        for args, want in ((["codex", "--session-id", str(uuid.uuid4())], "claude only"),
                           (["claude", "--session-id", "not-a-uuid"], "must be a UUID")):
            r = subprocess.run([*WITH, str(SCRIPT), *args, "-p", "x"], check=False, capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn(want, r.stderr)


if __name__ == "__main__":
    unittest.main()
