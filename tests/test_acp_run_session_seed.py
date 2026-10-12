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
        out[-1]["input"] = kw.get("input")
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
            # the prompt goes on stdin, never argv (adversary review 2026-10-12, L4)
            self.assertEqual(cmd[:2], ["claude", "-p"])
            self.assertNotIn("hi", cmd)
            self.assertEqual(case["input"], "hi")
        self.assertEqual(seeded["cmd"][seeded["cmd"].index("--session-id") + 1], "0b8f6d0e-5d1c-4c35-9a77-3f1f2b6f9b10")

    def test_session_id_is_claude_only_and_must_be_a_uuid(self) -> None:
        for args, want in ((["codex", "--session-id", str(uuid.uuid4())], "claude only"),
                           (["claude", "--session-id", "not-a-uuid"], "must be a UUID")):
            r = subprocess.run([*WITH, str(SCRIPT), *args, "-p", "x"], check=False, capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn(want, r.stderr)


PROBE_ADD_DIR = textwrap.dedent("""\
    import asyncio, importlib.machinery, importlib.util, io, json, sys
    from types import SimpleNamespace
    from acp import RequestError
    loader = importlib.machinery.SourceFileLoader("acp_run", sys.argv[1])
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("acp_run", loader))
    loader.exec_module(mod)

    class Client:
        def __init__(self):
            self.rows = []

        def rec(self, kind, data):
            self.rows.append([kind, data])

    class FakeConn:
        def __init__(self, reject_add_dir=False):
            self.calls = []
            self.reject_add_dir = reject_add_dir

        async def new_session(self, cwd, additional_directories=None, mcp_servers=None, **kw):
            self.calls.append({"cwd": cwd, "additional_directories": additional_directories})
            if self.reject_add_dir and additional_directories is not None:
                raise RequestError.invalid_params({"message": "unknown field additionalDirectories"})
            return SimpleNamespace(session_id="sess-1", modes=[], config_options=[])

    async def run_cases():
        out = {}
        # Case 1: capability advertised, add-dir reaches session/new
        c1 = Client()
        conn1 = FakeConn()
        a1 = SimpleNamespace(resume=None, add_dir=["/tmp/extra1", "/tmp/extra2"])
        init1 = SimpleNamespace(agent_capabilities=SimpleNamespace(
            session_capabilities=SimpleNamespace(additional_directories=SimpleNamespace())
        ))
        s1 = await mod.open_session(a1, conn1, init1, c1, "/tmp/root", 10)
        out["advertised"] = {"calls": conn1.calls, "rows": c1.rows, "session_id": s1.session_id}

        # Case 2: capability absent, but agent accepts add-dir in session/new
        c2 = Client()
        conn2 = FakeConn()
        a2 = SimpleNamespace(resume=None, add_dir=["/tmp/extra"])
        init2 = SimpleNamespace(agent_capabilities=SimpleNamespace(
            session_capabilities=SimpleNamespace(additional_directories=None)
        ))
        s2 = await mod.open_session(a2, conn2, init2, c2, "/tmp/root", 10)
        out["unadvertised_accepted"] = {"calls": conn2.calls, "rows": c2.rows, "session_id": s2.session_id}

        # Case 3: capability absent, agent rejects add-dir -> fallback retry without it
        c3 = Client()
        conn3 = FakeConn(reject_add_dir=True)
        a3 = SimpleNamespace(resume=None, add_dir=["/tmp/extra"])
        init3 = SimpleNamespace(agent_capabilities=SimpleNamespace(
            session_capabilities=SimpleNamespace(additional_directories=None)
        ))
        s3 = await mod.open_session(a3, conn3, init3, c3, "/tmp/root", 10)
        out["fallback_retry"] = {"calls": conn3.calls, "rows": c3.rows, "session_id": s3.session_id}

        return out

    print(json.dumps(asyncio.run(run_cases()), default=str))
""")


class TestAddDir(unittest.TestCase):
    def test_add_dir_reaches_session_new_and_handles_fallback(self) -> None:
        r = subprocess.run([*WITH, "-c", PROBE_ADD_DIR, str(SCRIPT)], check=False, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        res = json.loads(r.stdout)

        # 1. Advertised capability: additional_directories reaches session/new with resolved paths
        adv = res["advertised"]
        self.assertEqual(len(adv["calls"]), 1)
        self.assertEqual(
            adv["calls"][0]["additional_directories"],
            [str(Path("/tmp/extra1").resolve()), str(Path("/tmp/extra2").resolve())],
        )

        # 2. Unadvertised capability: still sent
        unadv = res["unadvertised_accepted"]
        self.assertEqual(len(unadv["calls"]), 1)
        self.assertEqual(unadv["calls"][0]["additional_directories"], [str(Path("/tmp/extra").resolve())])

        # 3. Fallback when rejected: retried without additional_directories
        fb = res["fallback_retry"]
        self.assertEqual(len(fb["calls"]), 2)
        self.assertEqual(fb["calls"][0]["additional_directories"], [str(Path("/tmp/extra").resolve())])
        self.assertIsNone(fb["calls"][1]["additional_directories"])
        self.assertEqual(fb["rows"][0][0], "additional_directories_rejected")
        self.assertEqual(fb["rows"][1][0], "new_session")
        self.assertIn("retrying session/new without it", r.stderr)

    def test_add_dir_cli_argparse_repeatable(self) -> None:
        probe_args = textwrap.dedent("""\
            import importlib.machinery, importlib.util, json, sys
            loader = importlib.machinery.SourceFileLoader("acp_run", sys.argv[1])
            mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("acp_run", loader))
            loader.exec_module(mod)
            import argparse
            ap = argparse.ArgumentParser()
            ap.add_argument("--add-dir", action="append", default=[])
            args = ap.parse_args(["--add-dir", "/dir1", "--add-dir", "/dir2"])
            print(json.dumps(args.add_dir))
        """)
        r = subprocess.run([*WITH, "-c", probe_args, str(SCRIPT)], check=False, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), ["/dir1", "/dir2"])


if __name__ == "__main__":
    unittest.main()
