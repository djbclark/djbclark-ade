#!/usr/bin/env python3
"""launch.py turn safety and the hcom-trial fixes (2026-10-11, scratchpad q-hcom-trial.md section 6).

6a  `reply` refuses a launch that was already continued (superseded_by) or whose ACP session another
    open launch holds; `audit` refuses the same, and a --mark'ed launch.
6b  `reply` keeps the original host (--host none stays detached), mode and mark.
6c  a detached interactive launch reads a FIFO, so stdin EOF no longer ends it after turn 1.
6d  --dry-run writes nothing and touches no pane.
a   `wait <id>` waits for that launch's turn only (and follows superseded_by).
b   headless Claude launches pass a seeded --session-id to acp-run.
c   --mark / SESSION_FINDER_MARK, recorded and inherited.
All runs use a scratch SESSION_FINDER_STATE, BIGTEAM_STATE and a non-existent herdr binary.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from typing import Any, override

ROOT = Path(__file__).resolve().parent.parent
LAUNCH = ROOT / "skills" / "session-finder" / "launch.py"
DISPATCH = ROOT / "bin" / "acp-dispatch"

FAKE_ACP = """#!/bin/bash
# fake acp-run: supports --interactive and --session-id
log=""
while [ $# -gt 0 ]; do case "$1" in --log) log=$2; shift;; esac; shift; done
echo '{"t": 1, "kind": "initialize", "data": {"agentCapabilities": {"loadSession": true}}}' >> "$log"
echo '{"t": 1, "kind": "new_session", "data": {"sessionId": "S-FAKE"}}' >> "$log"
echo '{"t": 2, "kind": "update", "data": {"sessionUpdate": "agent_message_chunk", "content": {"text": "hi"}}}' >> "$log"
echo '{"t": 3, "kind": "turn", "data": {"n": 1}}' >> "$log"
while IFS= read -r line; do [ "$line" = "/exit" ] && exit 0; done
exit 7
"""


class LaunchCase(unittest.TestCase):
    tmp: Path = Path()
    state: Path = Path()
    repo: Path = Path()
    env: dict[str, str] = {}

    @override
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="lturn-"))
        self.state = self.tmp / "state"
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _ = subprocess.run(["git", "init", "-q", str(self.repo)], check=True, capture_output=True)
        acp = self.tmp / "acp-run"
        _ = acp.write_text(FAKE_ACP)
        acp.chmod(0o755)
        self.env = {k: v for k, v in os.environ.items() if k != "SESSION_FINDER_MARK"}
        self.env.update(SESSION_FINDER_STATE=str(self.state), BIGTEAM_STATE=str(self.tmp / "bigteam"),
                        ACP_RUN=str(acp), ACP_DISPATCH=str(DISPATCH), HERDR_BIN_PATH=str(self.tmp / "no-herdr"))

    def run_launch(self, *args: str, timeout: float = 120, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-I", str(LAUNCH), *args], capture_output=True, text=True,
                              env={**self.env, **env}, timeout=timeout)

    def write_launches(self, *records: dict[str, Any]) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        with (self.state / "launches.jsonl").open("a") as fh:
            for r in records:
                _ = fh.write(json.dumps(r) + "\n")

    def log(self, name: str, *rows: tuple[str, dict[str, Any]]) -> str:
        p = self.tmp / f"{name}.jsonl"
        with p.open("a") as fh:
            for kind, data in rows:
                _ = fh.write(json.dumps({"t": time.time(), "kind": kind, "data": data}) + "\n")
        return str(p)

    def launch_rec(self, lid: str, **kw: Any) -> dict[str, Any]:
        d: dict[str, Any] = {"id": lid, "ts": time.time() - 60, "agent": "claude", "cwd": str(self.repo), "name": lid,
                             "model": "haiku", "brief": str(self.tmp / "brief.md"), "host": {"kind": "none"}}
        d.update(kw)
        return d


class TestDryRun(LaunchCase):
    def test_dry_run_writes_nothing(self) -> None:
        for extra in (["--agent", "claude", "--model", "m"], ["--agent", "claude", "--model", "m", "--no-interactive"],
                      ["--agent", "muse", "--host", "herdr"]):
            host = [] if "--host" in extra else ["--host", "none"]
            r = self.run_launch("start", "--cwd", str(self.repo), "-p", "x", "--dry-run", "--json", *host, *extra)
            self.assertEqual(r.returncode, 0, r.stderr)
            d = json.loads(r.stdout)
            self.assertIn("nothing was written", d["dry_run"])
            self.assertFalse(self.state.exists(), f"{extra}: {list(self.state.rglob('*'))}")
            self.assertFalse((self.tmp / "bigteam").exists())

    def test_dry_run_shows_the_runner_script(self) -> None:
        r = self.run_launch("start", "--agent", "claude", "--cwd", str(self.repo), "--model", "m", "--host", "none",
                            "-p", "x", "--dry-run", "--json")
        d = json.loads(r.stdout)
        self.assertIn("acp-run", d["runner_script"])
        self.assertNotIn("ACP_OPERATOR_APPROVED", d["runner_script"])

    def test_runner_script_carries_the_operator_approval(self) -> None:
        # the herdr pane is a fresh shell: without this a gated agent's run exits 2 there (2026-10-17)
        r = self.run_launch("start", "--agent", "claude", "--cwd", str(self.repo), "--model", "m", "--host", "none",
                            "-p", "x", "--dry-run", "--json", ACP_OPERATOR_APPROVED="hermes")
        d = json.loads(r.stdout)
        self.assertIn("export ACP_OPERATOR_APPROVED='hermes'", d["runner_script"])


class TestDetachedInteractive(LaunchCase):
    def test_host_none_interactive_reads_a_fifo(self) -> None:
        r = self.run_launch("start", "--agent", "claude", "--cwd", str(self.repo), "--model", "m", "--host", "none",
                            "-p", "x", "--dry-run", "--json")
        d = json.loads(r.stdout)
        self.assertTrue(d["stdin"].endswith("stdin.fifo"))
        self.assertIn(f"0<> '{d['stdin']}'", d["runner_script"])

    def test_herdr_hosted_launch_keeps_the_terminal_stdin(self) -> None:
        r = self.run_launch("start", "--agent", "claude", "--cwd", str(self.repo), "--model", "m", "--host", "herdr",
                            "-p", "x", "--dry-run", "--json")
        d = json.loads(r.stdout)
        self.assertNotIn("stdin", d)
        self.assertNotIn("0<>", d["runner_script"])

    def test_detached_session_survives_turn_one_and_ends_on_exit(self) -> None:
        r = self.run_launch("start", "--agent", "claude", "--cwd", str(self.repo), "--model", "m", "--host", "none",
                            "-p", "x", "--json", "--mark", "test")
        self.assertEqual(r.returncode, 0, r.stderr)
        lid = json.loads(r.stdout)["id"]
        recs = [json.loads(x) for x in (self.state / "launches.jsonl").read_text().splitlines()]
        start = next(x for x in recs if x["id"] == lid and "stdin" in x)
        self.assertEqual(start["mark"], "test")

        def exits() -> list[int]:
            return [json.loads(x)["exit"] for x in (self.state / "launches.jsonl").read_text().splitlines()
                    if json.loads(x).get("id") == lid and "exit" in json.loads(x)]
        logp, deadline = Path(start["log"]), time.time() + 20
        while time.time() < deadline and not (logp.exists() and '"turn"' in logp.read_text(errors="replace")):
            time.sleep(0.3)
        self.assertIn('"turn"', logp.read_text(errors="replace"), "the fake agent never ran")
        time.sleep(2)
        self.assertEqual(exits(), [], "the detached session ended after turn 1 (stdin EOF)")
        with open(start["stdin"], "w") as fh:     # what /exit through the terminal would be
            _ = fh.write("/exit\n")
        deadline = time.time() + 15
        while time.time() < deadline and not exits():
            time.sleep(0.3)
        self.assertEqual(exits(), [0])
        self.assertFalse(Path(start["stdin"]).exists(), "runner removes its FIFO")


class TestReplyRefusals(LaunchCase):
    def test_reply_to_a_superseded_launch_is_refused_and_names_the_newest(self) -> None:
        self.write_launches(self.launch_rec("A", exit=0, log=self.log("A", ("turn", {}))),
                            self.launch_rec("B", parent="A", exit=0, log=self.log("B", ("turn", {}))),
                            {"id": "A", "closed": True, "superseded_by": "B"},
                            self.launch_rec("C", parent="B", log=self.log("C")),
                            {"id": "B", "closed": True, "superseded_by": "C"})
        r = self.run_launch("reply", "A", "more")
        self.assertEqual(r.returncode, 1)
        self.assertIn("already continued as B", r.stderr)
        self.assertIn("launch.py reply C", r.stderr)
        r = self.run_launch("audit", "A")
        self.assertEqual(r.returncode, 1)
        self.assertIn("continued as B", r.stderr)

    def test_reply_is_refused_while_another_open_launch_holds_the_session(self) -> None:
        a_log = self.log("A", ("initialize", {"agentCapabilities": {"loadSession": True}}),
                         ("new_session", {"sessionId": "S1"}), ("turn", {}), ("result", {"exit": 0}))
        self.write_launches(self.launch_rec("A", exit=0, log=a_log),
                            self.launch_rec("Z", resumed="S1", log=self.log("Z", ("load_session", {}))))
        r = self.run_launch("reply", "A", "more")
        self.assertEqual(r.returncode, 1)
        self.assertIn("already holds ACP session S1", r.stderr)
        self.assertIn("Z", r.stderr)

    def test_audit_refuses_a_marked_launch(self) -> None:
        self.write_launches(self.launch_rec("M", exit=0, mark="test", log=self.log("M", ("turn", {}))))
        r = self.run_launch("audit", "M")
        self.assertEqual(r.returncode, 1)
        self.assertIn("marked 'test'", r.stderr)
        recs = (self.state / "launches.jsonl").read_text()
        self.assertNotIn("audit_sent", recs)


class TestReplyInherits(LaunchCase):
    def exited(self, lid: str, **kw: Any) -> None:
        log = self.log(lid, ("initialize", {"agentCapabilities": {"loadSession": True}}),
                       ("new_session", {"sessionId": f"S-{lid}"}), ("turn", {}), ("result", {"exit": 0}))
        self.write_launches(self.launch_rec(lid, exit=0, log=log, **kw))

    def test_reply_keeps_host_none_and_the_mark(self) -> None:
        self.exited("A", interactive=True, mark="trial")
        r = self.run_launch("reply", "A", "next", "--dry-run", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["host"], {"kind": "none"})
        self.assertEqual(d["mark"], "trial")
        self.assertEqual(d["resumed"], "S-A")
        self.assertTrue(d["interactive"])
        self.assertIn("--resume", d["acp_cmd"])

    def test_reply_keeps_a_headless_launch_headless(self) -> None:
        self.exited("H", dispatch=True, report=str(self.tmp / "H-report.md"), done=str(self.tmp / "H-report.md.done"))
        r = self.run_launch("reply", "H", "next", "--dry-run", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["acp_cmd"][0], str(DISPATCH))
        self.assertEqual(d["host"], {"kind": "none"})

    def test_explicit_host_still_wins(self) -> None:
        self.exited("A")
        r = self.run_launch("reply", "A", "next", "--dry-run", "--json", "--host", "herdr")
        self.assertEqual(json.loads(r.stdout)["host"]["kind"], "herdr")


class TestSessionSeed(LaunchCase):
    def test_headless_claude_gets_a_seeded_session_id(self) -> None:
        r = self.run_launch("start", "--agent", "claude", "--cwd", str(self.repo), "--model", "m", "--host", "none",
                            "--no-interactive", "-p", "x", "--dry-run", "--json")
        d = json.loads(r.stdout)
        seed = d["session_seed"]
        self.assertEqual(str(uuid.UUID(seed)), seed)
        cmd = d["acp_cmd"]
        self.assertEqual(cmd[cmd.index("--acp-arg=--session-id") + 1], f"--acp-arg={seed}")

    def test_interactive_and_non_claude_launches_are_not_seeded(self) -> None:
        for extra in (["--agent", "claude"], ["--agent", "codex", "--no-interactive"]):
            r = self.run_launch("start", "--cwd", str(self.repo), "--model", "m", "--host", "none", "-p", "x",
                                "--dry-run", "--json", *extra)
            d = json.loads(r.stdout)
            self.assertNotIn("session_seed", d, extra)
            self.assertFalse(any("--session-id" in c for c in d["acp_cmd"]), extra)


class TestMark(LaunchCase):
    def test_env_mark_is_recorded(self) -> None:
        r = self.run_launch("start", "--agent", "claude", "--cwd", str(self.repo), "--model", "m", "--host", "none",
                            "-p", "x", "--dry-run", "--json", SESSION_FINDER_MARK="hcom-trial")
        self.assertEqual(json.loads(r.stdout)["mark"], "hcom-trial")


class TestWait(LaunchCase):
    def test_wait_holds_while_a_queued_prompt_is_untaken_then_returns_that_turn(self) -> None:
        inbox = self.tmp / "inbox"
        inbox.mkdir()
        _ = (inbox / "1.txt").write_text("next\n")
        log = self.log("W", ("new_session", {"sessionId": "S"}),
                       ("update", {"sessionUpdate": "agent_message_chunk", "content": {"text": "first"}}), ("turn", {}))
        self.write_launches(self.launch_rec("W", interactive=True, inbox=str(inbox), log=log))
        r = self.run_launch("wait", "W", "--timeout", "3", "--json")
        self.assertEqual(r.returncode, 3, "returned the previous turn while a prompt was still queued")
        p = subprocess.Popen([sys.executable, "-I", str(LAUNCH), "wait", "W", "--timeout", "30", "--json"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env)
        time.sleep(3)
        (inbox / "1.txt").unlink()          # acp-run took it ...
        time.sleep(3)
        self.assertIsNone(p.poll(), "returned before the queued turn ended")
        _ = self.log("W", ("update", {"sessionUpdate": "agent_message_chunk", "content": {"text": "second"}}), ("turn", {}))
        out, err = p.communicate(timeout=30)
        self.assertEqual(p.returncode, 0, err)
        d = json.loads(out)
        self.assertEqual((d["id"], d["turns"], d["final"], d["alive"]), ("W", 2, "second", True))

    def test_wait_follows_superseded_by_to_the_newest_turn(self) -> None:
        self.write_launches(self.launch_rec("A", exit=0, log=self.log("A", ("turn", {}))),
                            self.launch_rec("B", exit=0, log=self.log(
                                "B", ("load_session", {}),
                                ("update", {"sessionUpdate": "agent_message_chunk", "content": {"text": "b says"}}),
                                ("turn", {}), ("result", {"exit": 0}))),
                            {"id": "A", "closed": True, "superseded_by": "B"})
        r = self.run_launch("wait", "A", "--timeout", "10", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual((d["id"], d["followed"], d["final"]), ("B", ["B"], "b says"))

    def test_replayed_history_is_not_the_new_turns_text(self) -> None:
        log = self.log("R", ("update", {"sessionUpdate": "agent_message_chunk", "content": {"text": "OLD HISTORY "}}),
                       ("load_session", {}),
                       ("update", {"sessionUpdate": "agent_message_chunk", "content": {"text": "new answer"}}),
                       ("turn", {}), ("result", {"exit": 0}))
        self.write_launches(self.launch_rec("R", exit=0, resumed="S", log=log))
        d = json.loads(self.run_launch("wait", "R", "--timeout", "5", "--json").stdout)
        self.assertEqual(d["final"], "new answer")

    def test_wait_on_an_unknown_id_fails(self) -> None:
        self.write_launches(self.launch_rec("A", exit=0))
        self.assertEqual(self.run_launch("wait", "nope", "--timeout", "2").returncode, 1)


if __name__ == "__main__":
    unittest.main()
