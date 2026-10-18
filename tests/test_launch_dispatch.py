#!/usr/bin/env python3
"""launch.py's headless path is dispatched through acp-dispatch; the interactive path is not.

A headless (one turn and exit) launch is a report-producing sub-agent, so it gets the shared
delivery footer, <id>-report.md, the .done marker, the jobs record and the no-report/BLOCKED
exit codes from bin/acp-dispatch. An interactive session is a live conversation the operator
watches, so it keeps plain acp-run. Both are checked with --dry-run against a scratch state dir.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, override

ROOT = Path(__file__).resolve().parent.parent
LAUNCH = ROOT / "skills" / "session-finder" / "launch.py"
DISPATCH = ROOT / "bin" / "acp-dispatch"


class TestLaunchDispatch(unittest.TestCase):
    # class-level placeholders: unittest sets the real values in setUp, not __init__
    tmp: Path = Path()
    repo: Path = Path()
    acp_run: Path = Path()

    @override
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="launchd-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _ = subprocess.run(["git", "init", "-q", str(self.repo)], check=True, capture_output=True)
        # a stand-in acp-run whose text advertises --interactive (what launch.py sniffs for)
        self.acp_run = self.tmp / "acp-run"
        _ = self.acp_run.write_text("#!/bin/bash\n# fake acp-run: supports --interactive\nexit 0\n")
        self.acp_run.chmod(0o755)

    def launch(self, *extra: str) -> dict[str, Any]:
        env = dict(os.environ, SESSION_FINDER_STATE=str(self.tmp / "state"), ACP_RUN=str(self.acp_run),
                   ACP_DISPATCH=str(DISPATCH), HERDR_BIN_PATH=str(self.tmp / "no-herdr"))
        r = subprocess.run([sys.executable, "-I", str(LAUNCH), "start", "--agent", "codex", "--cwd", str(self.repo),
                            "--host", "none", "--dry-run", "--json", *extra], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_headless_launch_goes_through_acp_dispatch(self) -> None:
        d = self.launch("--model", "m1", "--kind", "frontier", "--no-interactive", "-p", "fix it",
                        "--perm", "deny", "--set", "provider=x")
        cmd = d["acp_cmd"]
        self.assertEqual(cmd[0], str(DISPATCH))
        self.assertEqual(cmd[1], "codex")
        self.assertIn("--model", cmd)
        self.assertEqual(cmd[cmd.index("--kind") + 1], "frontier")
        self.assertEqual(cmd[cmd.index("--name") + 1], d["id"])
        self.assertEqual(cmd[cmd.index("--out") + 1], str(Path(d["brief"]).parent))
        self.assertIn("--tee", cmd)
        self.assertEqual(cmd[cmd.index("--acp-run") + 1], str(self.acp_run))
        self.assertEqual(cmd[cmd.index("--perm") + 1], "deny")
        self.assertIn("--acp-arg=--set", cmd)
        self.assertIn("--acp-arg=provider=x", cmd)
        self.assertNotIn("--interactive", cmd)
        self.assertTrue(d["dispatch"])
        self.assertEqual(d["report"], str(Path(d["brief"]).parent / f"{d['id']}-report.md"))
        self.assertEqual(d["done"], d["report"] + ".done")
        self.assertTrue(d["job"].endswith(f"jobs/{d['id']}.json"))

    def test_headless_launch_requires_a_model(self) -> None:
        env = dict(os.environ, SESSION_FINDER_STATE=str(self.tmp / "state"), ACP_RUN=str(self.acp_run),
                   ACP_DISPATCH=str(DISPATCH), HERDR_BIN_PATH=str(self.tmp / "no-herdr"))
        r = subprocess.run([sys.executable, "-I", str(LAUNCH), "start", "--agent", "codex", "--cwd", str(self.repo),
                            "--host", "none", "--dry-run", "--no-interactive", "--kind", "frontier", "-p", "x"],
                           capture_output=True, text=True, env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--model is required", r.stderr)

    def test_headless_launch_requires_a_kind(self) -> None:
        env = dict(os.environ, SESSION_FINDER_STATE=str(self.tmp / "state"), ACP_RUN=str(self.acp_run),
                   ACP_DISPATCH=str(DISPATCH), HERDR_BIN_PATH=str(self.tmp / "no-herdr"))
        r = subprocess.run([sys.executable, "-I", str(LAUNCH), "start", "--agent", "codex", "--cwd", str(self.repo),
                            "--host", "none", "--dry-run", "--no-interactive", "--model", "m1", "-p", "x"],
                           capture_output=True, text=True, env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--kind is required", r.stderr)

    def test_interactive_launch_keeps_plain_acp_run_and_no_footer(self) -> None:
        d = self.launch("--model", "m1", "-p", "talk to me")
        cmd = d["acp_cmd"]
        self.assertEqual(cmd[0], str(self.acp_run))
        self.assertIn("--interactive", cmd)
        self.assertNotIn(str(DISPATCH), cmd)
        self.assertTrue(d.get("interactive"))
        self.assertNotIn("dispatch", d)
        self.assertNotIn("Delivery contract", " ".join(cmd))
        self.assertFalse(Path(d["brief"]).exists(), "a dry run writes nothing (hcom trial 6d)")

    def test_dispatch_dry_run_of_the_composed_command_appends_the_footer(self) -> None:
        """The command launch.py composes is accepted by acp-dispatch and yields a footer-bearing brief."""
        d = self.launch("--model", "m1", "--kind", "frontier", "--no-interactive", "-p", "fix it")
        # launch.py's dry run writes nothing (hcom trial 6d), so lay down the brief a real start would write
        Path(d["brief"]).parent.mkdir(parents=True)
        _ = Path(d["brief"]).write_text("fix it")
        cmd: list[str] = [sys.executable, *d["acp_cmd"], "--dry-run"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("dry-run\t"), r.stdout)
        brief_copy = Path(d["brief"]).parent / f"{d['id']}-brief.md"
        self.assertTrue(brief_copy.exists(), r.stdout)
        text = brief_copy.read_text()
        self.assertTrue(text.startswith("fix it"))
        self.assertIn("## Delivery contract", text)
        self.assertIn(d["report"], text)

    def test_headless_launch_stores_kind_and_reply_inherits_it(self) -> None:
        # F2: kind is stored on the launch record; reply passes it through without --kind.
        state = self.tmp / "state"
        env = dict(os.environ, SESSION_FINDER_STATE=str(state), ACP_RUN=str(self.acp_run),
                   ACP_DISPATCH=str(DISPATCH), HERDR_BIN_PATH=str(self.tmp / "no-herdr"))
        # Real (non-dry-run) start would need acp-dispatch to finish; plant a finished headless launch.
        lid = "codex-replykind"
        ldir = state / f"launch-{lid}"
        ldir.mkdir(parents=True)
        job = ldir / "jobs" / f"{lid}.json"
        job.parent.mkdir(parents=True)
        job.write_text(json.dumps({"kind": "frontier", "agent": "codex", "model": "m1"}))
        report = ldir / f"{lid}-report.md"
        report.write_text("STATUS: working\nok\nDONE\n")
        done = Path(str(report) + ".done")
        done.write_text("")
        log = ldir / f"{lid}.jsonl"
        log.write_text(json.dumps({"t": 1, "kind": "initialize",
                                   "data": {"agentCapabilities": {"loadSession": True}}}) + "\n"
                       + json.dumps({"t": 1, "kind": "new_session",
                                     "data": {"sessionId": "S1"}}) + "\n"
                       + json.dumps({"t": 2, "kind": "turn", "data": {}}) + "\n"
                       + json.dumps({"t": 3, "kind": "result", "data": {"exit": 0}}) + "\n")
        (state / "launches.jsonl").write_text(json.dumps({
            "id": lid, "ts": 1, "agent": "codex", "cwd": str(self.repo), "name": lid,
            "model": "m1", "kind": "frontier", "dispatch": True, "exit": 0,
            "brief": str(ldir / "brief.md"), "report": str(report), "done": str(done),
            "job": str(job), "log": str(log), "host": {"kind": "none"},
        }) + "\n")
        (ldir / "brief.md").write_text("fix it")
        r = subprocess.run([sys.executable, "-I", str(LAUNCH), "reply", lid, "next",
                            "--dry-run", "--json"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        cmd = d["acp_cmd"]
        self.assertEqual(cmd[0], str(DISPATCH))
        self.assertEqual(cmd[cmd.index("--kind") + 1], "frontier")

    def test_reply_recovers_kind_from_job_record(self) -> None:
        # Pre-change launch: no kind on the launch row; recover from jobs/<id>.json.
        state = self.tmp / "state"
        env = dict(os.environ, SESSION_FINDER_STATE=str(state), ACP_RUN=str(self.acp_run),
                   ACP_DISPATCH=str(DISPATCH), HERDR_BIN_PATH=str(self.tmp / "no-herdr"))
        lid = "codex-legacykind"
        ldir = state / f"launch-{lid}"
        ldir.mkdir(parents=True)
        job = ldir / "jobs" / f"{lid}.json"
        job.parent.mkdir(parents=True)
        job.write_text(json.dumps({"kind": "code", "agent": "codex", "model": "m1"}))
        report = ldir / f"{lid}-report.md"
        report.write_text("STATUS: working\nok\nDONE\n")
        done = Path(str(report) + ".done")
        done.write_text("")
        log = ldir / f"{lid}.jsonl"
        log.write_text(json.dumps({"t": 1, "kind": "initialize",
                                   "data": {"agentCapabilities": {"loadSession": True}}}) + "\n"
                       + json.dumps({"t": 1, "kind": "new_session",
                                     "data": {"sessionId": "S1"}}) + "\n"
                       + json.dumps({"t": 2, "kind": "turn", "data": {}}) + "\n"
                       + json.dumps({"t": 3, "kind": "result", "data": {"exit": 0}}) + "\n")
        (state / "launches.jsonl").write_text(json.dumps({
            "id": lid, "ts": 1, "agent": "codex", "cwd": str(self.repo), "name": lid,
            "model": "m1", "dispatch": True, "exit": 0,
            "brief": str(ldir / "brief.md"), "report": str(report), "done": str(done),
            "job": str(job), "log": str(log), "host": {"kind": "none"},
        }) + "\n")
        (ldir / "brief.md").write_text("fix it")
        r = subprocess.run([sys.executable, "-I", str(LAUNCH), "reply", lid, "next",
                            "--dry-run", "--json"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        cmd = json.loads(r.stdout)["acp_cmd"]
        self.assertEqual(cmd[cmd.index("--kind") + 1], "code")


if __name__ == "__main__":
    unittest.main()
