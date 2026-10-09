#!/usr/bin/env python3
"""Tests for bin/acp-dispatch.

The rules under test are the delivery contract that used to live as prose in bigteam,
model-routing and home-agents.md: report file named <name>-report.md (never a basename
Claude Code refuses), the shared footer appended to every brief, a jobs record, a `.done`
marker touched last, --model mandatory, and the exit codes that make "idle with no report"
and "BLOCKED: <question>" visible to the lead instead of silent.

acp-run is replaced by a fake shell script whose behaviour FAKE_MODE selects.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "acp-dispatch"
FOOTER = ROOT / "docs" / "dispatch-footer.md"

FAKE = textwrap.dedent("""\
    #!/bin/bash
    # fake acp-run: args are <agent> -C DIR -f BRIEF --model M --perm P --timeout S --log LOG
    brief=""; while [ $# -gt 0 ]; do case "$1" in -f) brief="$2"; shift;; esac; shift; done
    echo "$@" > /dev/null
    report=$(grep -o 'deliverable to `[^`]*`' "$brief" | head -1 | sed 's/.*`\\(.*\\)`/\\1/')
    case "${FAKE_MODE:-writes}" in
      writes)   printf 'STATUS: working\\nfound it\\nDONE\\n' > "$report"; echo "written: $report"; exit 0;;
      stdout)   echo "the whole answer in the final message"; exit 0;;
      blocked)  printf 'BLOCKED: do I own ~/opt/cfengine-dev?\\n' > "$report"; echo "BLOCKED: do I own ~/opt/cfengine-dev?"; exit 0;;
      partial)  printf 'STATUS: working\\nhalf\\n' > "$report"; echo "written: $report"; exit 0;;
      nothing)  exit 0;;
      quota)    echo "FAILED quota" >&2; exit 1;;
      timeout)  exit 124;;
      echoargs) echo "$ARGS_SINK" > /dev/null; printf 'STATUS: working\\nDONE\\n' > "$report"; exit 0;;
    esac
    """)


def run(args: list[str], env: dict[str, str] | None = None,
        cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=e, cwd=cwd)


class Base(unittest.TestCase):
    tmp: Path
    fake: Path
    out: Path
    repo: Path

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="acpd-"))
        self.fake = self.tmp / "acp-run"
        self.fake.write_text(FAKE)
        self.fake.chmod(0o755)
        self.out = self.tmp / "out"
        self.repo = self.tmp / "repo"
        self.repo.mkdir()

    def dispatch(self, *extra, mode="writes", name="s1"):
        return run(["codex", "--model", "m1", "--name", name, "-p", "do the thing", "-C", str(self.repo),
                    "--out", str(self.out), "--acp-run", str(self.fake), *extra], env={"FAKE_MODE": mode})

    def record(self, name="s1"):
        return json.loads((self.out / "jobs" / f"{name}.json").read_text())


class TestUsage(Base):
    def test_model_is_mandatory(self):
        r = run(["codex", "--name", "x", "-p", "hi", "--out", str(self.out), "--acp-run", str(self.fake)])
        self.assertEqual(r.returncode, 2)
        self.assertIn("--model is required", r.stderr)

    def test_footer_refuses_claude_blocked_basename(self):
        for bad in ("/tmp/a/report.md", "/tmp/a/Summary-x.md", "/tmp/a/FINDINGS.md", "/tmp/a/analysis-1.md"):
            r = run(["footer", "--report", bad])
            self.assertEqual(r.returncode, 2, bad)
            self.assertIn("refuses", r.stderr)
        ok = run(["footer", "--report", "/tmp/a/review-json-report.md"])
        self.assertEqual(ok.returncode, 0)

    def test_footer_fills_placeholders_and_keeps_the_rules(self):
        r = run(["footer", "--report", "/abs/x-report.md", "--lead", "main"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("/abs/x-report.md.done", r.stdout)
        self.assertIn("SendMessage that same line to `main`", r.stdout)
        self.assertNotIn("{report}", r.stdout)
        for rule in ("4,000 characters", "3,500 characters", "BLOCKED:", "never end your turn waiting",
                     "report`, `summary`, `findings` or `analysis`"):
            self.assertIn(rule.lower(), r.stdout.lower(), rule)

    def test_footer_needs_absolute_path(self):
        r = run(["footer", "--report", "rel-report.md"])
        self.assertEqual(r.returncode, 2)

    def test_dry_run_writes_nothing(self):
        r = self.dispatch("--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dry-run", r.stdout)
        self.assertFalse((self.out / "jobs" / "s1.json").exists())


class TestDispatch(Base):
    def test_happy_path_writes_brief_record_done_and_exits_0(self):
        r = self.dispatch()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("done\ts1\t"), r.stdout)
        brief = (self.out / "s1-brief.md").read_text()
        self.assertTrue(brief.startswith("do the thing\n"))
        self.assertIn(str(self.out / "s1-report.md"), brief)
        self.assertIn("## Delivery contract", brief)
        rec = self.record()
        self.assertEqual(rec["status"], "done")
        self.assertEqual(rec["exit"], 0)
        self.assertEqual(rec["report_source"], "agent")
        self.assertTrue(Path(rec["done"]).exists())
        self.assertIn("until [ -e", rec["rearm"])
        self.assertIn("--model m1", rec["cmd"])
        self.assertIn("--perm all", rec["cmd"])
        self.assertIn("--timeout 2400", rec["cmd"])

    def test_scoped_perm_gets_the_out_dir_added(self):
        r = self.dispatch("--perm", "scoped:src/a.py")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"--perm scoped:src/a.py,{self.out.resolve()}", self.record()["cmd"])

    def test_bad_perm_is_usage(self):
        r = self.dispatch("--perm", "yolo")
        self.assertEqual(r.returncode, 2)

    def test_stdout_only_is_recovered_with_a_warning(self):
        r = self.dispatch(mode="stdout")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("recovered from its final message", r.stderr)
        rec = self.record()
        self.assertEqual(rec["report_source"], "final-message")
        text = Path(rec["report"]).read_text()
        self.assertIn("the whole answer in the final message", text)
        self.assertTrue(text.startswith("STATUS: recovered"))
        self.assertTrue(text.rstrip().endswith("DONE"))

    def test_blocked_report_exits_4_and_shows_the_question(self):
        r = self.dispatch(mode="blocked")
        self.assertEqual(r.returncode, 4, r.stdout)
        self.assertTrue(r.stdout.startswith("blocked\ts1\t"))
        self.assertIn("do I own ~/opt/cfengine-dev?", r.stdout)
        self.assertEqual(self.record()["status"], "blocked")

    def test_partial_report_exits_1(self):
        r = self.dispatch(mode="partial")
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stdout.startswith("partial\t"))

    def test_finished_with_no_report_is_a_delivery_failure_exit_3(self):
        r = self.dispatch(mode="nothing")
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertTrue(r.stdout.startswith("no-report\t"))
        self.assertIn("delivery failure", r.stdout)
        self.assertTrue(Path(self.record()["done"]).exists(), ".done is touched even on failure")

    def test_acp_run_failure_without_report_keeps_its_summary(self):
        r = self.dispatch(mode="quota")
        self.assertEqual(r.returncode, 3)
        self.assertIn("FAILED quota", r.stderr)
        self.assertEqual(self.record()["exit"], 1)

    def test_timeout_without_report_exits_124(self):
        r = self.dispatch(mode="timeout")
        self.assertEqual(r.returncode, 124)

    def test_second_dispatch_of_a_finished_name_is_refused_unless_forced(self):
        self.assertEqual(self.dispatch().returncode, 0)
        r = self.dispatch()
        self.assertEqual(r.returncode, 2)
        self.assertIn("already finished", r.stderr)
        self.assertEqual(self.dispatch("--force").returncode, 0)


class TestCheck(Base):
    def test_check_classifies_records_and_reports_worst_exit(self):
        self.dispatch(mode="writes", name="ok")
        self.dispatch(mode="blocked", name="blk")
        self.dispatch(mode="nothing", name="gone")
        r = run(["check", str(self.out)])
        self.assertEqual(r.returncode, 4, r.stdout)       # blocked outranks no-report
        lines = dict((ln.split("\t")[1], ln.split("\t")[0]) for ln in r.stdout.splitlines())
        self.assertEqual(lines, {"ok": "done", "blk": "blocked", "gone": "no-report"})

    def test_check_bare_report_paths_for_agent_tool_subagents(self):
        scratch = self.tmp / "scratch"
        scratch.mkdir()
        (scratch / "fix-swap-report.md").write_text("STATUS: working\nall good\nDONE\n")
        (scratch / "fix-guard-report.md").write_text("BLOCKED: do I own ~/opt/cfengine-dev?\n")
        missing = scratch / "fix-removal-report.md"
        r = run(["check", str(scratch / "fix-swap-report.md"), str(scratch / "fix-guard-report.md"), str(missing)])
        self.assertEqual(r.returncode, 4)
        rows = {ln.split("\t")[1]: ln.split("\t")[0] for ln in r.stdout.splitlines()}
        self.assertEqual(rows, {"fix-swap": "done", "fix-guard": "blocked", "fix-removal": "pending"})
        # a .done beside a missing report means the agent finished without delivering
        (scratch / "fix-removal-report.md.done").touch()
        r = run(["check", str(missing)])
        self.assertEqual(r.returncode, 3)
        self.assertTrue(r.stdout.startswith("no-report\t"))

    def test_check_scans_a_directory_of_bare_reports(self):
        scratch = self.tmp / "scratch"
        scratch.mkdir()
        (scratch / "a-report.md").write_text("STATUS: working\nDONE\n")
        r = run(["check", str(scratch)])
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("done\ta\t", r.stdout)

    def test_check_with_nothing_is_usage(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        self.assertEqual(run(["check", str(empty)]).returncode, 2)


class TestFooterFile(unittest.TestCase):
    def test_footer_file_has_every_placeholder_and_numbered_rules(self):
        text = FOOTER.read_text()
        for ph in ("{report}", "{done}", "{lead}"):
            self.assertIn(ph, text)
        rules = [ln for ln in text.splitlines() if ln[:2].rstrip(".").isdigit()]
        self.assertGreaterEqual(len(rules), 7)
        self.assertNotIn("\n- ", text, "operator rule: numbered lists, never bullets")


if __name__ == "__main__":
    unittest.main()
