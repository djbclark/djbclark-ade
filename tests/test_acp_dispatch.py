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
from typing import Any, override

ROOT = Path(__file__).resolve().parent.parent
# ACP_DISPATCH_SCRIPT: test a candidate copy (in a tree whose docs/ links here) before it replaces the live one
SCRIPT = Path(os.environ.get("ACP_DISPATCH_SCRIPT", str(ROOT / "bin" / "acp-dispatch")))
FOOTER = ROOT / "docs" / "dispatch-footer.md"

FAKE = textwrap.dedent("""\
    #!/bin/bash
    # fake acp-run: args are <agent> -C DIR -f BRIEF --model M --perm P --timeout S --log LOG
    for x in "$@"; do
      if [ "$x" = --info ]; then
        [ -n "$INFO_COUNT" ] && echo probe >> "$INFO_COUNT"
        [ -n "$FAKE_INFO_FAIL" ] && { echo "acp-run: agent down" >&2; exit 1; }
        echo '{"agent": {"name": "fake"}, "config_options": [{"id": "model", "category": "model",'
        echo ' "options": [{"value": "m1", "name": "Model One"}, {"value": "claude-fable-5-1[1m]", "name": "Fable"},'
        echo '            {"value": "claude-opus-5-5-high", "name": "Opus"}, {"value": "gemini-2.5-pro", "name": "Gemini"},'
        echo '            {"value": "gpt-oss-120b", "name": "GPT"}]}]}'
        exit 0
      fi
    done
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
      quota_partial)
                printf 'STATUS: working\\n' > "$report"
                echo "acp-run: FAILED quota: RequestError: Internal error {\\"message\\": \\"You hit your usage limit. Upgrade to Pro or try again at 8:51 PM.\\"}" >&2
                echo "acp-run: agent=codex stop=error secs=102.3 tools=21 fail=quota error='usageLimitExceeded'" >&2
                exit 1;;
      quota_reply)
                printf 'STATUS: working\\n' > "$report"
                echo "acp-run: FAILED quota: quota exhausted: reply truncated; edits may be present; it ended with 'You have reached your current quota for this period. Your limit will reset in 2 hours, 47 minutes.'" >&2
                echo "acp-run: agent=agy stop=end_turn secs=356.1 tools=38 fail=quota" >&2
                exit 1;;
      quota_ts)
                printf 'STATUS: working\\n' > "$report"
                echo "acp-run: FAILED quota: Error 429: Individual quota reached. Resets in 2h47m44s. Details: quotaResetTimeStamp:2026-10-11T02:46:28Z" >&2
                echo "acp-run: agent=agy stop=error secs=227.1 tools=38 fail=quota" >&2
                exit 1;;
      quota_gemini)
                printf 'STATUS: working\\n' > "$report"
                echo "acp-run: FAILED quota: quota exhausted: retry in 6 days, 6 hours" >&2
                echo "acp-run: agent=agy stop=error secs=50.0 tools=5 fail=quota" >&2
                exit 1;;
      quota_unknown)
                printf 'STATUS: working\\n' > "$report"
                echo "acp-run: FAILED quota: quota exhausted: retry in 2 hours" >&2
                echo "acp-run: agent=mystery stop=error secs=10.0 tools=2 fail=quota" >&2
                exit 1;;
      refused)  # agy, gemini-pro-agent, wedge-grants/advisory2g-final.txt (2026-10-10), trimmed
                echo "Sorry, I cannot fulfill your request. I am unable to analyze the upstream repository. I must decline tasks involving vulnerability analysis."
                echo "acp-run: FAILED refused: model refused the task: reply was 'Sorry, I cannot fulfill your request.'" >&2
                echo "acp-run: agent=agy stop=end_turn secs=4.2 tools=0 fail=refused" >&2
                exit 1;;
      quotes_refusal)
                printf 'The model answered "Sorry, I cannot fulfill your request" to the first brief.\\nThe second brief fixed that.\\n'; exit 0;;
      timeout)  exit 124;;
      timeout_wrapup)  # stlib, 2026-10-10: cancelled at --timeout, report written in the wrap-up turn
                printf 'STATUS: timed out\\nstaged 13 files, tests pass, not committed\\nDONE\\n' > "$report"
                echo "written: $report"
                echo "acp-run: agent=opencode stop=cancelled secs=2402.2 tools=109 perm=0+/0- wrapup=end_turn" >&2
                exit 124;;
      echoargs) echo "$ARGS_SINK" > /dev/null; printf 'STATUS: working\\nDONE\\n' > "$report"; exit 0;;
    esac
    """)


def run(args: list[str], env: dict[str, str] | None = None,
        cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run([sys.executable, str(SCRIPT), *args], check=False, capture_output=True, text=True, env=e, cwd=cwd)


class Base(unittest.TestCase):
    # class-level placeholders: unittest sets the real values in setUp, not __init__
    tmp: Path = Path()
    fake: Path = Path()
    out: Path = Path()
    repo: Path = Path()

    @override
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="acpd-"))
        self.fake = self.tmp / "acp-run"
        _ = self.fake.write_text(FAKE)
        self.fake.chmod(0o755)
        self.out = self.tmp / "out"
        self.repo = self.tmp / "repo"
        self.repo.mkdir()

    def dispatch(self, *extra: str, mode: str = "writes", name: str = "s1") -> subprocess.CompletedProcess[str]:
        return self.dispatch_model("m1", *extra, mode=mode, name=name)

    def dispatch_agent(self, agent: str, model: str, *extra: str, mode: str = "writes", name: str = "s1",
                       env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        e = {"FAKE_MODE": mode, "ACP_DISPATCH_MODEL_CACHE": str(self.tmp / "cache"),
             "INFO_COUNT": str(self.tmp / "info-count"), "ACP_DISPATCH_AIUSE": "off", **(env or {})}
        return run([agent, "--model", model, "--name", name, "-p", "do the thing", "-C", str(self.repo),
                    "--out", str(self.out), "--acp-run", str(self.fake), *extra], env=e)

    def dispatch_model(self, model: str, *extra: str, mode: str = "writes", name: str = "s1",
                       env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return self.dispatch_agent("codex", model, *extra, mode=mode, name=name, env=env)

    def probes(self) -> int:
        f = self.tmp / "info-count"
        return len(f.read_text().splitlines()) if f.exists() else 0

    def record(self, name: str = "s1") -> dict[str, Any]:
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

    def test_dispatch_passes_add_dir_for_out(self):
        r = self.dispatch()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"--add-dir {self.out.resolve()}", self.record()["cmd"])

    def test_deny_perm_brief_says_the_final_message_is_the_report(self):
        # --perm deny refuses the report's Write too; the brief must not ask for the impossible.
        r = self.dispatch("--perm", "deny")
        self.assertEqual(r.returncode, 0, r.stderr)
        brief = (self.out / "s1-brief.md").read_text()
        self.assertIn("read-only (`--perm deny`)", brief)
        self.assertIn("final message", brief)

    def test_all_perm_brief_has_no_read_only_note(self):
        self.dispatch()
        self.assertNotIn("--perm deny", (self.out / "s1-brief.md").read_text())

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


class TestModelCheck(Base):
    """2026-10-10: a bad agy model detached, failed inside launchd, and surfaced only as no-report."""

    def test_unknown_model_is_refused_before_anything_is_written_or_detached(self):
        for extra in ((), ("--dry-run",), ("--detach", "--no-wait")):
            r = self.dispatch_model("no-such-model-9", *extra)
            self.assertEqual(r.returncode, 2, (extra, r.stdout, r.stderr))
            self.assertIn("no model 'no-such-model-9' for codex; have: m1, claude-fable-5-1[1m], "
                          "claude-opus-5-5-high, gemini-2.5-pro, gpt-oss-120b", r.stderr)
            self.assertFalse((self.out / "jobs" / "s1.json").exists(), extra)
            self.assertFalse((self.out / "s1-run.sh").exists(), extra)

    def test_token_match_like_acp_run(self):
        r = self.dispatch_model("fable-5-1")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_list_is_cached_and_a_miss_reprobes_once(self):
        self.assertEqual(self.dispatch_model("m1", name="a").returncode, 0)
        self.assertEqual(self.dispatch_model("m1", name="b").returncode, 0)
        self.assertEqual(self.probes(), 1, "the second dispatch used the cache")
        self.assertEqual(self.dispatch_model("nope", name="c").returncode, 2)
        self.assertEqual(self.probes(), 2, "a miss re-reads the live list before refusing")

    def test_probe_failure_warns_and_dispatches(self):
        r = self.dispatch_model("m1", env={"FAKE_INFO_FAIL": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("could not check --model", r.stderr)

    def test_no_model_check_skips_the_probe(self):
        r = self.dispatch_model("whatever", "--no-model-check")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.probes(), 0)


class TestFailureNote(Base):
    """2026-10-10: codex died of quota after writing only `STATUS: working`; the waiter exited 0."""

    def test_quota_death_after_status_working_is_no_report_with_a_reason(self):
        r = self.dispatch(mode="quota_partial")
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertTrue(r.stdout.startswith("no-report\t"), r.stdout)
        rec = self.record()
        self.assertEqual(rec["status"], "no-report")
        last = Path(rec["report"]).read_text().splitlines()[-1]
        self.assertTrue(last.startswith("NO-REPORT: quota (codex, m1, retry at 8:51 PM)"), last)
        self.assertEqual(rec["failure"], last)
        c = run(["check", str(self.out / "jobs" / "s1.json")])
        self.assertEqual(c.returncode, 3)
        self.assertIn("NO-REPORT: quota", c.stdout)

    def test_reset_in_a_duration_reads_retry_in(self):
        """2026-10-10: agy's refusal said "reset in 2 hours, 47 minutes", not a clock time."""
        r = self.dispatch(mode="quota_reply")
        self.assertEqual(r.returncode, 3, r.stdout)
        last = Path(self.record()["report"]).read_text().splitlines()[-1]
        self.assertTrue(last.startswith("NO-REPORT: quota (codex, m1, retry in 2 hours, 47 minutes)"), last)

    def test_note_is_written_into_an_empty_report_too(self):
        r = self.dispatch(mode="quota")
        self.assertEqual(r.returncode, 3)
        text = Path(self.record()["report"]).read_text()
        self.assertTrue(text.startswith("NO-REPORT: quota (codex, m1)"), text)

    def test_model_refusal_in_the_final_message_is_no_report_not_done(self):
        """2026-10-10: agy declined a security slice; the refusal was recovered, got DONE, checked `done`."""
        r = self.dispatch(mode="refused")
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertTrue(r.stdout.startswith("no-report\t"), r.stdout)
        rec = self.record()
        self.assertEqual(rec["status"], "no-report")
        self.assertEqual(rec["report_source"], "final-message-failed")
        text = Path(rec["report"]).read_text()
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith("Sorry, I cannot"), text)
        self.assertTrue(
            lines[-1].startswith("NO-REPORT: refused (codex, m1): Sorry, I cannot fulfill your request."), lines[-1])
        self.assertNotIn("DONE", lines)
        self.assertNotIn("recovered by acp-dispatch", text)
        c = run(["check", str(self.out / "jobs" / "s1.json")])
        self.assertEqual(c.returncode, 3, c.stdout)
        self.assertTrue(c.stdout.startswith("no-report\t"), c.stdout)
        w = subprocess.run(["bash", "-c", rec["rearm"]], check=False, capture_output=True, text=True)
        self.assertEqual(w.returncode, 3, (w.stdout, w.stderr))

    def test_genuine_final_message_that_quotes_a_refusal_is_still_recovered(self):
        r = self.dispatch(mode="quotes_refusal")
        self.assertEqual(r.returncode, 0, r.stdout)
        rec = self.record()
        self.assertEqual(rec["status"], "done")
        self.assertEqual(rec["report_source"], "final-message")
        self.assertNotIn("NO-REPORT", Path(rec["report"]).read_text())

    def test_clean_exit_partial_gets_no_note(self):
        self.dispatch(mode="partial")
        self.assertNotIn("NO-REPORT", Path(self.record()["report"]).read_text())

    def test_finalize_twice_does_not_append_twice(self):
        self.dispatch(mode="quota_partial")
        rec = self.out / "jobs" / "s1.json"
        r = run(["finalize", str(rec), "--exit", "1"])
        self.assertEqual(r.returncode, 3)
        text = Path(self.record()["report"]).read_text()
        self.assertEqual(text.count("NO-REPORT:"), 1, text)

    def test_rearm_waiter_exits_with_the_check_verdict(self):
        for mode, want in (("writes", 0), ("partial", 1), ("quota_partial", 3), ("blocked", 4)):
            self.dispatch(mode=mode, name=mode.replace("_", "-"))
            rearm = self.record(mode.replace("_", "-"))["rearm"]
            self.assertIn(" check ", rearm)
            r = subprocess.run(["bash", "-c", rearm], check=False, capture_output=True, text=True)
            self.assertEqual(r.returncode, want, (mode, r.stdout, r.stderr))

    def test_rearm_waiter_outlasts_the_slice_timeout(self):
        # timeout + wrap-up grace (default 300) + 300
        self.dispatch("--timeout", "3600", name="long")
        self.assertTrue(self.record("long")["rearm"].startswith("timeout 4200 "), self.record("long")["rearm"])
        self.dispatch("--timeout", "3600", "--wait-timeout", "5000", name="waited")
        self.assertTrue(self.record("waited")["rearm"].startswith("timeout 5000 "))
        self.dispatch(name="default")
        self.assertTrue(self.record("default")["rearm"].startswith("timeout 3000 "))
        self.dispatch("--wrapup-grace", "0", name="nograce")
        self.assertTrue(self.record("nograce")["rearm"].startswith("timeout 2700 "))


class TestTimeBudget(Base):
    """2026-10-10, wedge-grants/stlib: opencode + deepseek-v4-pro had its 13-file change verified at
    2009 s of 2400, then sat in `git commit` while the pre-commit Gradle hook queued on the
    machine-wide Gradle slot. It was never told its deadline, and acp-run's cancel ended the run with
    no chance to write the report, which stayed at `STATUS: working`."""

    def test_brief_states_the_deadline_and_the_wrapup_turn(self):
        self.dispatch("--timeout", "1800")
        brief = (self.out / "s1-brief.md").read_text()
        self.assertIn("## Time budget", brief)
        self.assertIn("30 minutes after it starts", brief)
        self.assertIn("before a commit", brief)
        self.assertIn("one last turn of 300 seconds", brief)
        self.assertLess(brief.index("## Delivery contract"), brief.index("## Time budget"))

    def test_acp_run_gets_the_wrapup_prompt_naming_the_report(self):
        self.dispatch()
        cmd = self.record()["cmd"]
        self.assertIn("--wrapup-grace 300", cmd)
        self.assertIn("--wrapup ", cmd)
        self.assertIn(str(self.out / "s1-report.md"), cmd.split("--wrapup ", 1)[1])
        self.assertIn("{grace} seconds", cmd, "acp-run fills in the grace")
        self.assertIn("STATUS: timed out", cmd)

    def test_wrapup_grace_0_turns_it_off(self):
        self.dispatch("--wrapup-grace", "0")
        self.assertNotIn("--wrapup", self.record()["cmd"])
        brief = (self.out / "s1-brief.md").read_text()
        self.assertIn("## Time budget", brief)
        self.assertNotIn("one last turn", brief)

    def test_wrapup_report_is_delivered_but_not_a_clean_success(self):
        r = self.dispatch(mode="timeout_wrapup")
        self.assertEqual(r.returncode, 1, (r.stdout, r.stderr))
        rec = self.record()
        self.assertEqual(rec["status"], "done")
        self.assertEqual(rec["exit"], 124)
        text = Path(rec["report"]).read_text()
        self.assertNotIn("NO-REPORT", text)
        self.assertTrue(text.startswith("STATUS: timed out"))
        c = run(["check", str(self.out / "jobs" / "s1.json")])
        self.assertEqual(c.returncode, 1, c.stdout)
        self.assertIn("acp-run exit=124 (timed out", c.stdout)
        w = subprocess.run(["bash", "-c", rec["rearm"]], check=False, capture_output=True, text=True)
        self.assertEqual(w.returncode, 1, (w.stdout, w.stderr))


class TestCheck(Base):
    def test_check_classifies_records_and_reports_worst_exit(self):
        self.dispatch(mode="writes", name="ok")
        self.dispatch(mode="blocked", name="blk")
        self.dispatch(mode="nothing", name="gone")
        r = run(["check", str(self.out)])
        self.assertEqual(r.returncode, 4, r.stdout)       # blocked outranks no-report
        lines = {ln.split("\t")[1]: ln.split("\t")[0] for ln in r.stdout.splitlines()}
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


class TestAiuseNoteExhausted(Base):
    @override
    def setUp(self) -> None:
        super().setUp()
        self.calls_file = self.tmp / "aiuse.calls"
        self.fake_aiuse = self.tmp / "fake-aiuse"
        self.fake_aiuse.write_text(f'#!/bin/bash\necho "$@" >> "{self.calls_file}"\nexit 0\n')
        self.fake_aiuse.chmod(0o755)

    def calls(self) -> list[str]:
        return self.calls_file.read_text().splitlines() if self.calls_file.exists() else []

    def test_quota_refusal_agy_claude_records_antigravity_claude_gpt_resets_at(self):
        env = {"ACP_DISPATCH_AIUSE": str(self.fake_aiuse)}
        r = self.dispatch_agent("agy", "claude-opus-5-5-high", mode="quota_ts", env=env)
        self.assertEqual(r.returncode, 3)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertIn("note-exhausted antigravity --family claude_gpt --resets-at 2026-10-11T02:46:28Z", calls[0])
        self.assertIn("--reason", calls[0])

    def test_quota_refusal_agy_gemini_records_antigravity_gemini_resets_in(self):
        env = {"ACP_DISPATCH_AIUSE": str(self.fake_aiuse)}
        r = self.dispatch_agent("agy", "gemini-2.5-pro", mode="quota_gemini", env=env)
        self.assertEqual(r.returncode, 3)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertIn("note-exhausted antigravity --family gemini --resets-in 6d6h", calls[0])

    def test_quota_refusal_agy_gpt_records_antigravity_claude_gpt_resets_in(self):
        env = {"ACP_DISPATCH_AIUSE": str(self.fake_aiuse)}
        r = self.dispatch_agent("agy", "gpt-oss-120b", mode="quota_reply", env=env)
        self.assertEqual(r.returncode, 3)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertIn("note-exhausted antigravity --family claude_gpt --resets-in 2h47m", calls[0])

    def test_quota_refusal_codex_records_codex_resets_at_from_clock_time(self):
        env = {"ACP_DISPATCH_AIUSE": str(self.fake_aiuse)}
        r = self.dispatch_agent("codex", "m1", mode="quota_partial", env=env)
        self.assertEqual(r.returncode, 3)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("note-exhausted codex --resets-at "), calls[0])
        self.assertNotIn("--family", calls[0])

    def test_unknown_agent_runs_nothing_and_says_so(self):
        env = {"ACP_DISPATCH_AIUSE": str(self.fake_aiuse)}
        r = self.dispatch_agent("mystery", "m1", mode="quota_unknown", env=env)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.calls(), [])
        rec = self.record()
        self.assertIn("unknown agent", rec.get("failure", ""))

    def test_no_reset_time_runs_nothing_and_says_so(self):
        env = {"ACP_DISPATCH_AIUSE": str(self.fake_aiuse)}
        r = self.dispatch_agent("codex", "m1", mode="quota", env=env)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.calls(), [])
        rec = self.record()
        self.assertIn("no reset time", rec.get("failure", ""))

    def test_aiuse_failure_does_not_break_acp_dispatch(self):
        bad_aiuse = self.tmp / "failing-aiuse"
        bad_aiuse.write_text("#!/bin/bash\necho 'aiuse crashed' >&2\nexit 1\n")
        bad_aiuse.chmod(0o755)
        env = {"ACP_DISPATCH_AIUSE": str(bad_aiuse)}
        r = self.dispatch_agent("codex", "m1", mode="quota_partial", env=env)
        self.assertEqual(r.returncode, 3)
        self.assertIn("aiuse", r.stderr)

    def test_acp_dispatch_aiuse_off_disables_recording(self):
        env = {"ACP_DISPATCH_AIUSE": "off"}
        r = self.dispatch_agent("codex", "m1", mode="quota_partial", env=env)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
