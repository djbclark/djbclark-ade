#!/usr/bin/env python3
"""launch.py successor: the herdr half of `self-slash --finish --successor` (design agreed 2026-10-25).

A stateful fake `herdr` (argv appended to $FAKE_LOG) stands in for the real one, so nothing starts. The
contract under test: wait for the old agent to be idle, open a tab in the SAME workspace, start a real
claude TUI there with the model asked, prompt /baton, verify it is up and is not the old agent, and
never close or touch the old pane. Any failure exits 11 and leaves the old pane alone.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import override

ROOT = Path(__file__).resolve().parent.parent
LAUNCH = ROOT / "skills" / "session-finder" / "launch.py"

FAKE_HERDR = """#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
log = os.environ["FAKE_LOG"]
open(log, "a").write(json.dumps(a) + "\\n")
d = os.path.dirname(log)
flag = lambda n: os.path.exists(os.path.join(d, n))
def out(result): print(json.dumps({"id": "x", "result": result})); sys.exit(0)
def err(code): print(json.dumps({"error": {"code": code}})); sys.exit(1)
OLD = {"pane_id": "w1:p1", "tab_id": "w1:t1", "workspace_id": "w1", "cwd": "/work/repo", "agent": "claude",
       "agent_status": os.environ.get("FAKE_OLD_STATUS", "idle"), "agent_session": {"value": "old-session"}}
NEW = {"pane_id": "w1:p9", "tab_id": "w1:t9", "workspace_id": "w1", "cwd": "/work/repo",
       "agent": os.environ.get("FAKE_NEW_AGENT", "claude"), "agent_status": "working",
       "agent_session": {"value": os.environ.get("FAKE_NEW_SESSION", "new-session")}}
k = " ".join(a[:2])
if k in ("pane get", "agent get"):
    key = "pane" if a[0] == "pane" else "agent"
    if a[2] == "w1:p1": out({key: OLD})
    if a[2] == "w1:p9" and (a[0] == "pane" or flag("started")): out({key: NEW})
    err("pane_not_found")
if k == "tab list": out({"tabs": [{"tab_id": "w1:t1", "label": "paseo-accent-t", "workspace_id": "w1"}]})
if k == "tab create": out({"tab": {"tab_id": "w1:t9"}})
if k == "pane list": out({"panes": [{"pane_id": "w1:p1", "tab_id": "w1:t1", "workspace_id": "w1"},
                                    {"pane_id": "w1:p9", "tab_id": "w1:t9", "workspace_id": "w1"}]})
if k == "pane read":
    print("old draft\\n\\u276f " + os.environ.get("FAKE_DRAFT", "") if a[2] == "w1:p1" else "user@host %"); sys.exit(0)
if k == "agent start":
    if os.environ.get("FAKE_START_FAIL"): err("agent_start_failed")
    open(os.path.join(d, "started"), "w").close(); out({"agent": NEW})
if k == "agent prompt":
    if os.environ.get("FAKE_PROMPT_FAIL"): err("agent_prompt_stalled")
    out({})
if k == "tab close": out({})
out({})
"""


class TestLaunchSuccessor(unittest.TestCase):
    tmp: Path = Path()
    home: Path = Path()
    log: Path = Path()
    env: dict[str, str] = {}

    @override
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="succ-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        (self.tmp / "fake").mkdir()
        self.log = self.tmp / "fake" / "calls.jsonl"
        herdr = self.tmp / "herdr"
        _ = herdr.write_text(FAKE_HERDR)
        herdr.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.home), HERDR_BIN_PATH=str(herdr), FAKE_LOG=str(self.log),
                        SESSION_FINDER_STATE=str(self.tmp / "state"), HERDR_PANE_ID="w1:p1")

    def run_succ(self, *extra: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-I", str(LAUNCH), "successor", "--model", "claude-sonnet-5-5",
                               "--poll", "0.05", "--wait", "1", "--settle", "3", *extra],
                              capture_output=True, text=True, env={**self.env, **env}, timeout=60)

    def calls(self) -> list[list[str]]:
        return [json.loads(ln) for ln in self.log.read_text().splitlines()] if self.log.exists() else []

    def verbs(self) -> list[str]:
        return [" ".join(c[:2]) for c in self.calls()]

    def test_dry_run_plans_without_starting_anything(self) -> None:
        r = self.run_succ("--dry-run", "--effort", "high")
        self.assertEqual(r.returncode, 0, r.stderr)
        plan = json.loads(r.stdout)
        self.assertEqual(plan["workspace"], "w1")
        self.assertEqual(plan["cwd"], "/work/repo")
        self.assertEqual(plan["tab_label"], "paseo-accent-sonnet-5-t")
        self.assertEqual(plan["claude_args"], ["--dangerously-skip-permissions", "--model", "sonnet", "--effort", "high"])
        self.assertEqual(plan["prompt"], "/baton")
        self.assertNotIn("agent start", self.verbs())
        self.assertNotIn("tab create", self.verbs())

    def test_starts_a_claude_tui_in_a_new_tab_of_the_same_workspace_and_leaves_the_old_pane(self) -> None:
        r = self.run_succ()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        calls = self.calls()
        create = next(c for c in calls if c[:2] == ["tab", "create"])
        self.assertEqual(create[create.index("--workspace") + 1], "w1")
        self.assertEqual(create[create.index("--cwd") + 1], "/work/repo")
        start = next(c for c in calls if c[:2] == ["agent", "start"])
        self.assertEqual(start[start.index("--kind") + 1], "claude")
        self.assertEqual(start[start.index("--pane") + 1], "w1:p9")
        self.assertEqual(start[start.index("--") + 1:], ["--dangerously-skip-permissions", "--model", "sonnet"])
        prompt = next(c for c in calls if c[:2] == ["agent", "prompt"])
        self.assertEqual(prompt[2:], ["w1:p9", "/baton"])
        self.assertLess(self.verbs().index("agent start"), self.verbs().index("agent prompt"))
        # nothing was typed into, closed or exited in the old pane
        for c in calls:
            if c[:2] in (["agent", "prompt"], ["tab", "close"], ["pane", "close"], ["pane", "send-text"], ["pane", "run"]):
                self.assertNotIn("w1:p1", c)
                self.assertNotIn("w1:t1", c)
        log = (self.home / ".local/state/self-slash.log").read_text()
        self.assertIn("herdr w1:p1: successor: claude is up in w1:p9", log)

    def test_baton_path_goes_into_the_first_prompt(self) -> None:
        chain = self.tmp / "SESSION_LOG.md"
        _ = chain.write_text("x")
        r = self.run_succ("--baton", str(chain))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        prompt = next(c for c in self.calls() if c[:2] == ["agent", "prompt"])
        self.assertEqual(prompt[3], f"/baton {chain}")

    def test_a_blocked_old_agent_is_not_replaced(self) -> None:
        r = self.run_succ(FAKE_OLD_STATUS="blocked")
        self.assertEqual(r.returncode, 11, r.stdout + r.stderr)
        self.assertIn("blocked on a question", r.stdout)
        self.assertNotIn("tab create", self.verbs())

    def test_a_working_old_agent_times_out_without_starting_anything(self) -> None:
        r = self.run_succ(FAKE_OLD_STATUS="working")
        self.assertEqual(r.returncode, 11, r.stdout + r.stderr)
        self.assertIn("still working after 1s", r.stdout)
        self.assertNotIn("tab create", self.verbs())

    def test_an_unsent_draft_in_the_old_pane_stops_it(self) -> None:
        r = self.run_succ(FAKE_DRAFT="half a thought")
        self.assertEqual(r.returncode, 11, r.stdout + r.stderr)
        self.assertIn("unsent draft", r.stdout)
        self.assertNotIn("tab create", self.verbs())

    def test_a_failed_agent_start_closes_only_the_empty_new_tab(self) -> None:
        r = self.run_succ(FAKE_START_FAIL="1")
        self.assertEqual(r.returncode, 11, r.stdout + r.stderr)
        close = [c for c in self.calls() if c[:2] == ["tab", "close"]]
        self.assertEqual(close, [["tab", "close", "w1:t9"]])
        self.assertNotIn("agent prompt", self.verbs())

    def test_a_prompt_that_stalls_leaves_the_successor_running(self) -> None:
        r = self.run_succ(FAKE_PROMPT_FAIL="1")
        self.assertEqual(r.returncode, 11, r.stdout + r.stderr)
        self.assertIn("left running", r.stdout)
        self.assertNotIn("tab close", self.verbs())

    def test_a_successor_that_is_the_old_session_is_refused(self) -> None:
        r = self.run_succ(FAKE_NEW_SESSION="old-session")
        self.assertEqual(r.returncode, 11, r.stdout + r.stderr)
        self.assertIn("not a new one", r.stdout)

    def test_a_pane_that_does_not_run_claude_is_not_verified(self) -> None:
        r = self.run_succ(FAKE_NEW_AGENT="codex")
        self.assertEqual(r.returncode, 11, r.stdout + r.stderr)
        self.assertIn("nothing verified", r.stdout)

    def start_cmd(self, *extra: str, **env: str) -> subprocess.CompletedProcess[str]:
        repo = self.tmp / "repo"
        if not repo.exists():
            repo.mkdir()
            _ = subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
        chain = self.tmp / "SESSION_LOG.md"
        _ = chain.write_text("x")
        acp_run = self.tmp / "acp-run"
        _ = acp_run.write_text("#!/bin/bash\n# fake acp-run: supports --interactive\nexit 0\n")
        acp_run.chmod(0o755)
        return subprocess.run([sys.executable, "-I", str(LAUNCH), "start", "--cwd", str(repo), "--host", "herdr",
                               "--chain", str(chain), "-p", "do it", *extra],
                              capture_output=True, text=True, timeout=60,
                              env={**self.env, "HERDR_WORKSPACE_ID": "w1", "ACP_RUN": str(acp_run), **env})

    def test_baton_on_herdr_starts_a_real_claude_tui_by_default(self) -> None:
        r = self.start_cmd("--agent", "claude", "--baton", "--model", "claude-sonnet-5-5", "--effort", "high")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        start = next(c for c in self.calls() if c[:2] == ["agent", "start"])
        self.assertEqual(start[start.index("--kind") + 1], "claude")
        # yolo, the family alias for claude-sonnet-5-5, and the effort: no acp-run, no model probe
        self.assertEqual(start[start.index("--") + 1:], ["--dangerously-skip-permissions", "--model", "sonnet", "--effort", "high"])
        prompt = next(c for c in self.calls() if c[:2] == ["agent", "prompt"])
        self.assertIn("baton", prompt[3])
        self.assertNotIn("pane run", self.verbs())

    def test_baton_on_herdr_starts_a_real_codex_tui_with_yolo_model_and_effort(self) -> None:
        r = self.start_cmd("--agent", "codex", "--baton", "--model", "gpt-6.1-sol", "--effort", "medium")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        start = next(c for c in self.calls() if c[:2] == ["agent", "start"])
        self.assertEqual(start[start.index("--kind") + 1], "codex")
        self.assertEqual(start[start.index("--") + 1:], ["--dangerously-bypass-approvals-and-sandbox", "-m", "gpt-6.1-sol",
                                                         "-c", 'model_reasoning_effort="medium"'])

    def test_acp_flag_keeps_the_acp_session_behind_baton(self) -> None:
        r = self.start_cmd("--agent", "claude", "--baton", "--acp", "--model", "claude-sonnet-5-5", "--dry-run", "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["acp_cmd"][d["acp_cmd"].index("--model") + 1], "claude-sonnet-5")    # mapped for acp-run
        self.assertNotIn("agent start", self.verbs())

    def test_a_headless_slice_is_never_a_tui(self) -> None:
        r = self.start_cmd("--agent", "claude", "--baton", "--no-interactive", "--kind", "code", "--model", "sonnet",
                           "--dry-run", "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(json.loads(r.stdout)["dispatch"])

    def test_without_baton_the_default_stays_acp(self) -> None:
        r = self.start_cmd("--agent", "claude", "--model", "sonnet", "--dry-run", "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(json.loads(r.stdout)["interactive"])
        self.assertEqual(json.loads(r.stdout)["host"]["kind"], "herdr")

    def test_tui_flag_forces_a_tui_without_baton(self) -> None:
        r = self.start_cmd("--agent", "claude", "--tui", "--model", "opus")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        start = next(c for c in self.calls() if c[:2] == ["agent", "start"])
        self.assertEqual(start[start.index("--") + 1:], ["--dangerously-skip-permissions", "--model", "opus"])

    def test_unknown_pane_is_a_usage_error(self) -> None:
        r = self.run_succ("--pane", "w9:p9")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
