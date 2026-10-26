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
import runpy
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any, ClassVar, override
from unittest.mock import patch

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
        echo "{\\"agent\\": {\\"name\\": \\"fake\\"}, \\"perm_modes\\": ${FAKE_PERM_MODES:-[\\"all\\", \\"deny\\", \\"read-only\\"]}, \\"config_options\\": [{\\"id\\": \\"model\\", \\"category\\": \\"model\\","
        echo ' "options": [{"value": "m1", "name": "Model One"}, {"value": "claude-fable-5-1[1m]", "name": "Fable"},'
        echo '            {"value": "claude-opus-5-5-high", "name": "Opus"}, {"value": "gemini-2.5-pro", "name": "Gemini"},'
        echo '            {"value": "gpt-oss-120b", "name": "GPT"}]}]}'
        exit 0
      fi
      if [ "$x" = "Reply with exactly: OK" ]; then
        [ -n "$PREFLIGHT_COUNT" ] && echo probe >> "$PREFLIGHT_COUNT"
        case "${PREFLIGHT_MODE:-pass}" in
          pass) echo OK; exit 0;;
          outage) echo 'RequestError: Internal error: Internal service failure {"errorName":"ServiceUnavailableError"}' >&2; exit 1;;
          zcode_quota) echo 'ZCode turn failed: 1310 [1310][Weekly/Monthly Limit Exhausted. Your limit will reset at 2026-10-14 22:56:01]' >&2; exit 1;;
        esac
      fi
    done
    brief=""; log=""; while [ $# -gt 0 ]; do case "$1" in
      -f) brief="$2"; shift;; --log) log="$2"; shift;; esac; shift; done
    caps='{"loadSession":true}'; [ "$FAKE_CAPS" = none ] && caps='{}'
    printf '%s\\n' "{\\"kind\\":\\"initialize\\",\\"data\\":{\\"agentCapabilities\\":$caps}}" > "$log"
    [ "$FAKE_CAPS" = nosid ] || printf '%s\\n' '{"kind":"new_session","data":{"sessionId":"fake-session"}}' >> "$log"
    [ -n "$FAKE_APPLIED" ] && printf '%s\\n' "{\\"kind\\":\\"applied\\",\\"data\\":{\\"model\\":\\"$FAKE_APPLIED\\"}}" >> "$log"
    echo "$@" > /dev/null
    report=$(ggrep -o 'deliverable to `[^`]*`' "$brief" | ghead -1 | gsed 's/.*`\\(.*\\)`/\\1/')
    case "${FAKE_MODE:-writes}" in
      writes)   printf 'STATUS: working\\nfound it\\nDONE\\n' > "$report"; echo "written: $report"; exit 0;;
      slow)     sleep 2; printf 'STATUS: working\\nfound it\\nDONE\\n' > "$report"; exit 0;;
      stdout)   echo "the whole answer in the final message"; exit 0;;
      blocked)  printf 'BLOCKED: do I own ~/opt/cfengine-dev?\\n' > "$report"; echo "BLOCKED: do I own ~/opt/cfengine-dev?"; exit 0;;
      partial)  printf 'STATUS: working\\nhalf\\n' > "$report"; echo "written: $report"; exit 0;;
      nothing)  exit 0;;
      quota)    echo "FAILED quota" >&2; exit 1;;
      quota_codex_date)  # codex, gpt-6-astra, plektra-small-issues/s1-stderr.txt (2026-10-18), trimmed
                printf 'STATUS: working\\nsettings search wired; CI running\\n' > "$report"
                echo 'acp-run: FAILED quota: RequestError: Internal error {"message": "You hit your usage limit. Upgrade to Pro or try again at Oct 18th, 2036 4:41 AM.", "codexErrorInfo": "usageLimitExceeded"}' >&2
                echo "acp-run: agent=codex stop=error secs=523.0 tools=38 perm=0+/0- fail=quota error='usageLimitExceeded'" >&2
                exit 1;;
      quota_partial)
                printf 'STATUS: working\\n' > "$report"
                echo "acp-run: FAILED quota: RequestError: Internal error {\\"message\\": \\"You hit your usage limit. Upgrade to Pro or try again at 8:51 PM.\\"}" >&2
                echo "acp-run: agent=codex stop=error secs=102.3 tools=21 fail=quota error='usageLimitExceeded'" >&2
                exit 1;;
      quota_checkpoint)
                printf 'STATUS: working\\nstep one done\\nmore work left\\n' > "$report"
                echo "acp-run: FAILED quota: quota exhausted: retry in 2 hours" >&2
                echo "acp-run: agent=codex stop=error secs=10.0 tools=2 fail=quota" >&2
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
      fake_tool_calls)  # claude, fable, --perm deny, 2026-10-19: tool calls printed as text, no tools ran
                printf 'I will read the files.\\n\\n<invoke name="Read">\\n<parameter name="file_path">/x/README.md</parameter>\\n</invoke>\\n'
                echo "acp-run: FAILED fake-tool-calls: the reply is tool calls printed as text, not an answer: no tool ran" >&2
                echo "acp-run: agent=claude stop=end_turn secs=26.0 tools=0 perm=0+/0- fail=fake-tool-calls" >&2
                exit 1;;
      quotes_refusal)
                printf 'The model answered "Sorry, I cannot fulfill your request" to the first brief.\\nThe second brief fixed that.\\n'; exit 0;;
      agent_metrics)
                echo "acp-run: agent=codex stop=error secs=514.8 tools=536 fail=agent error='boom'" >&2
                exit 1;;
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
        self.no_quota_snap = self.tmp / "no-quota.json"
        self.no_quota_snap.write_text(json.dumps({
            "collected_at": "2099-01-01T00:00:00+00:00",
            "snapshot": {"accounts": []},
        }))
        # A quota stop schedules an in-place resume under launchd (2026-10-18); never a real one here.
        self.launchctl_calls = self.tmp / "launchctl.calls"
        self.fake_launchctl = self.tmp / "fake-launchctl"
        self.fake_launchctl.write_text(f'#!/bin/bash\necho "$@" >> "{self.launchctl_calls}"\nexit 0\n')
        self.fake_launchctl.chmod(0o755)

    def launchctl(self) -> list[str]:
        return self.launchctl_calls.read_text().splitlines() if self.launchctl_calls.exists() else []

    def base_env(self, mode: str = "writes", **extra: str) -> dict[str, str]:
        return {"FAKE_MODE": mode, "ACP_DISPATCH_MODEL_CACHE": str(self.tmp / "cache"),
                "ACP_DISPATCH_PREFLIGHT": str(self.tmp / "preflight"),
                "AIUSE_SNAPSHOT": str(self.no_quota_snap),
                "PREFLIGHT_COUNT": str(self.tmp / "preflight-count"),
                "ACP_DISPATCH_LAUNCHCTL": str(self.fake_launchctl),
                "INFO_COUNT": str(self.tmp / "info-count"), "ACP_DISPATCH_AIUSE": "off",
                # The in-flight cap scans this root: never the machine's real running slices.
                "ACP_DISPATCH_STATE": str(self.tmp / "state"),
                # D2: these suites' fixtures reset years out (2036); the far-reset
                # skip must not fire for them (D2's own tests cover the rule)
                "ACP_DISPATCH_MAX_WAIT_HOURS": "876576",
                # never the real pmset: a cached sudo ticket would wake the Mac for a fixture
                "ACP_DISPATCH_PMSET": "/usr/bin/false",
                # the load gate (load-watch admit, up to 30 min on a hot host) is off unless a test turns it on
                "ACP_DISPATCH_NO_LOAD_GATE": "1", **extra}

    def dispatch(self, *extra: str, mode: str = "writes", name: str = "s1",
                 env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return self.dispatch_model("m1", *extra, mode=mode, name=name, env=env)

    def default_kind(self, agent: str, model: str) -> str:
        """Eligible --kind for the common test agents (required since 2026-10-18)."""
        if agent in ("codex", "claude"):
            return "frontier" if "fable" in model.lower() or "astra" in model.lower() else (
                "frontier" if agent == "codex" else "judgment")
        if agent == "agy" and model.startswith(("claude-", "gpt-")):
            return "code"
        return "bulk"

    def dispatch_agent(self, agent: str, model: str, *extra: str, mode: str = "writes", name: str = "s1",
                       env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        e = self.base_env(mode, **(env or {}))
        kind = [] if any(x == "--kind" or str(x).startswith("--kind=") for x in extra) else [
            "--kind", self.default_kind(agent, model)]
        return run([agent, "--model", model, "--name", name, "-p", "do the thing", "-C", str(self.repo),
                    "--out", str(self.out), "--acp-run", str(self.fake), *kind, *extra], env=e)

    def dispatch_model(self, model: str, *extra: str, mode: str = "writes", name: str = "s1",
                       env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return self.dispatch_agent("codex", model, *extra, mode=mode, name=name, env=env)

    def probes(self) -> int:
        f = self.tmp / "info-count"
        return len(f.read_text().splitlines()) if f.exists() else 0

    def preflight_probes(self) -> int:
        f = self.tmp / "preflight-count"
        return len(f.read_text().splitlines()) if f.exists() else 0

    def record(self, name: str = "s1") -> dict[str, Any]:
        return json.loads((self.out / "jobs" / f"{name}.json").read_text())


class TestUsage(Base):
    def test_model_is_mandatory(self):
        r = run(["codex", "--kind", "frontier", "--name", "x", "-p", "hi", "--out", str(self.out),
                 "--acp-run", str(self.fake)])
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
        self.assertIn("acp-dispatch-wait", rec["rearm"])
        self.assertIn(str((self.out / "jobs" / "s1.json").resolve()), rec["rearm"])
        self.assertIn("--model m1", rec["cmd"])
        self.assertIn("--perm all", rec["cmd"])
        self.assertIn("--timeout 2400", rec["cmd"])

    def test_preflight_pass_then_cache_hit(self):
        self.assertEqual(self.dispatch(name="first").returncode, 0)
        self.assertEqual(self.dispatch(name="second").returncode, 0)
        self.assertEqual(self.preflight_probes(), 1)

    def test_no_preflight_skips_probe(self):
        self.assertEqual(self.dispatch("--no-preflight").returncode, 0)
        self.assertEqual(self.preflight_probes(), 0)

    def test_close_estimate_adds_checkpoint_instructions(self):
        snap = self.tmp / "latest.json"
        snap.write_text(json.dumps({"collected_at": "2099-01-01T00:00:00+00:00", "snapshot": {"accounts": [{
            "provider": "codex", "windows": [{"label": "weekly", "remaining_percent": 12.0}]}]}}))
        r = self.dispatch("--est-pct", "9", env={"AIUSE_SNAPSHOT": str(snap)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("## Checkpoint mode", (self.out / "s1-brief.md").read_text())
        self.assertTrue(self.record()["checkpoint"])

    def test_stale_snapshot_window_is_unmeasured_not_a_crash(self):
        # 2026-10-20: agy's aiuse row was 1658 s old (past STALE_SOFT, under STALE_HARD), route_agent
        # stored its binding window as None (unmeasured) and dispatch died in the window fit with
        # "float() argument must be ... not 'NoneType'" before launching anything. A collected_at
        # older than STALE_HARD (6 h) would not do: load_snapshot drops the whole reading then.
        snap = self.tmp / "latest.json"
        snap.write_text(json.dumps({"collected_at": "2099-01-01T00:00:00+00:00", "snapshot": {"accounts": [{
            "provider": "codex", "age_seconds": 1658,
            "windows": [{"label": "weekly", "remaining_percent": 12.0}]}]}}))
        r = self.dispatch("--est-pct", "9", env={"AIUSE_SNAPSHOT": str(snap)})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertTrue(self.record()["checkpoint"])

    def test_stale_exhausted_window_still_refuses(self):
        # The same staleness with an exhausted window: 0.0 survives staleness, so the headroom
        # floor refuses (exit 5) instead of launching into an empty pool (it crashed before the fix).
        snap = self.tmp / "latest.json"
        snap.write_text(json.dumps({"collected_at": "2099-01-01T00:00:00+00:00", "snapshot": {"accounts": [{
            "provider": "codex", "age_seconds": 1658,
            "windows": [{"label": "weekly", "remaining_percent": 0.0, "state": "exhausted"},
                        {"label": "5h", "remaining_percent": 80.0}]}]}}))
        r = self.dispatch("--est-pct", "9", env={"AIUSE_SNAPSHOT": str(snap)})
        self.assertEqual(r.returncode, 5, r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_wont_fit_refuses_without_launching(self):
        snap = self.tmp / "latest.json"
        snap.write_text(json.dumps({"collected_at": "2099-01-01T00:00:00+00:00", "snapshot": {"accounts": [{
            "provider": "codex", "windows": [{"label": "weekly", "remaining_percent": 12.0}]}]}}))
        r = self.dispatch("--min-headroom", "0", "--est-pct", "13", env={"AIUSE_SNAPSHOT": str(snap)})
        self.assertEqual(r.returncode, 5)
        self.assertIn("class=wont-fit", r.stdout)
        self.assertEqual(self.record()["status"], "unavailable")
        self.assertEqual(self.preflight_probes(), 0)

    def _window_history(self, five_hour: float, weekly: float) -> dict[str, str]:
        # A past codex slice that emptied the 5-hour window but used 15% of the week.
        (self.out / "jobs").mkdir(parents=True, exist_ok=True)
        (self.out / "jobs" / "old.json").write_text(json.dumps({
            "agent": "codex", "model": "m1", "measured_usage_pct": 70.0,
            "measured_usage_windows": {"5h": 100.0, "weekly": 15.0}}))
        snap = self.tmp / "latest.json"
        snap.write_text(json.dumps({"collected_at": "2099-01-01T00:00:00+00:00", "snapshot": {"accounts": [{
            "provider": "codex", "windows": [{"label": "5h", "remaining_percent": five_hour},
                                             {"label": "weekly", "remaining_percent": weekly}]}]}}))
        return {"AIUSE_SNAPSHOT": str(snap)}

    def test_fit_is_checked_per_window_not_against_the_tightest(self):
        # 2026-10-13: a 70% scalar (weekly-before minus 5h-after) refused this slice
        # against 69% weekly left; per window it needs 100% of a fresh 5h and 15% of the week.
        r = self.dispatch("--min-headroom", "0", env=self._window_history(100.0, 69.0))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.record()["checkpoint"], "100% estimate on 100% left is near the limit")

    def test_per_window_refusal_names_the_window(self):
        r = self.dispatch("--min-headroom", "0", env=self._window_history(100.0, 10.0))
        self.assertEqual(r.returncode, 5)
        self.assertIn("class=wont-fit", r.stdout)
        self.assertIn("left on weekly", r.stdout)
        self.assertEqual(self.preflight_probes(), 0)

    def test_reroute_builds_continuation_and_links_records(self):
        first = self.dispatch(mode="quota_partial")
        self.assertEqual(first.returncode, 1)          # resume-scheduled (2026-10-18)
        old = self.out / "jobs" / "s1.json"
        self.assertEqual(json.loads(old.read_text())["auto_resume"]["state"], "scheduled")
        env = {"FAKE_MODE": "writes", "ACP_DISPATCH_MODEL_CACHE": str(self.tmp / "cache"),
               "ACP_DISPATCH_PREFLIGHT": str(self.tmp / "preflight"),
               "AIUSE_SNAPSHOT": str(self.tmp / "missing.json"), "ACP_DISPATCH_AIUSE": "off"}
        result = run(["reroute", str(old), "--agent", "codex", "--model", "m1",
                      "--acp-run", str(self.fake), "--no-preflight"], env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        new = json.loads((self.out / "jobs" / "s1-reroute-1.json").read_text())
        self.assertEqual(new["rerouted_from"], str(old.resolve()))
        # the reroute supersedes the scheduled in-place resume of the old record
        self.assertEqual(json.loads(old.read_text())["auto_resume"]["state"], "cancelled")
        continuation = Path(new["brief"]).read_text()
        self.assertIn("Do not restart", continuation)
        self.assertIn("Last checkpoint report", continuation)
        self.assertIn("Current git diff --stat", continuation)
        self.assertTrue((self.out / "s1-report.md").exists(), "old report remains in place")

    def test_preflight_refusal_retains_context_and_reroutes_permissions(self):
        for perm in ("deny", "read-only"):
            with self.subTest(perm=perm):
                name = "refused-" + perm
                brief = self.tmp / (name + ".md")
                brief.write_text("Original task: preserve this exact constraint.\n")
                env = self.base_env(PREFLIGHT_MODE="outage")
                result = run(["claude", "--model", "m1", "--kind", "judgment",
                              "--name", name, "-f", str(brief), "-C", str(self.repo),
                              "--out", str(self.out), "--acp-run", str(self.fake),
                              "--perm", perm, "--effort", "high", "--context", "1m",
                              "--timeout", "123", "--wrapup-grace", "7", "--no-auto-resume"], env=env)
                self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
                old = self.out / "jobs" / (name + ".json")
                before = old.read_bytes()
                rec = json.loads(before)
                self.assertEqual(rec["status"], "unavailable")
                self.assertEqual(rec["prompt"], brief.read_text())
                self.assertEqual(rec["brief"], str(brief.resolve()))
                self.assertEqual(rec["perm"], perm)
                self.assertNotIn("session_id", rec)
                self.assertFalse((self.out / (name + ".jsonl")).exists())
                brief.unlink()  # retained text is independent of the original file
                result = run(["reroute", str(old), "--agent", "claude", "--model", "m1",
                              "--acp-run", str(self.fake), "--no-preflight"], env=self.base_env())
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                new = json.loads((self.out / "jobs" / (name + "-reroute-1.json")).read_text())
                self.assertEqual(new["rerouted_from"], str(old.resolve()))
                for key in ("perm", "effort", "context", "timeout", "wrapup_grace"):
                    self.assertEqual(new[key], rec[key], key)
                self.assertEqual(new["auto_resume"]["state"], "off")
                self.assertIn("--perm " + perm, new["cmd"])
                self.assertIn(rec["prompt"], new["prompt"])
                self.assertEqual(old.read_bytes(), before)

    def test_repeat_preflight_refusal_refreshes_task_and_permission(self):
        brief = self.tmp / "retry.md"
        for text, perm, effort, context, timeout in (
                ("Brief A: first task", "deny", "high", "1m", "123"),
                ("Brief B: latest task", "read-only", "low", "200k", "321")):
            brief.write_text(text)
            result = run(["claude", "--model", "m1", "--kind", "judgment", "--name", "retry",
                          "-f", str(brief), "-C", str(self.repo), "--out", str(self.out),
                          "--acp-run", str(self.fake), "--perm", perm, "--effort", effort,
                          "--context", context, "--timeout", timeout],
                         env=self.base_env(PREFLIGHT_MODE="outage"))
            self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
            rec = json.loads((self.out / "jobs" / "retry.json").read_text())
            self.assertEqual(rec["status"], "unavailable")
            self.assertEqual(rec["prompt"], text)
            self.assertEqual(rec["perm"], perm)
            self.assertEqual(rec["effort"], effort)
            self.assertEqual(rec["context"], context)
            self.assertEqual(rec["timeout"], int(timeout))
            self.assertNotIn("refusals", rec)
            self.assertFalse((self.out / "retry.jsonl").exists())

    def test_legacy_thin_record_gains_context_on_repeated_preflight_refusal(self):
        first = self.dispatch(env={"PREFLIGHT_MODE": "outage"})
        self.assertEqual(first.returncode, 5, first.stdout + first.stderr)
        old = self.out / "jobs" / "s1.json"
        rec = self.record()
        for key in ("prompt", "brief", "perm"):
            rec.pop(key, None)
        old.write_text(json.dumps(rec))
        brief = self.tmp / "latest.md"
        brief.write_text("Latest task after legacy refusal")
        result = run(["codex", "--model", "m1", "--kind", "frontier", "--name", "s1",
                      "-f", str(brief), "-C", str(self.repo), "--out", str(self.out),
                      "--acp-run", str(self.fake), "--perm", "read-only"],
                     env=self.base_env(PREFLIGHT_MODE="outage"))
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        after = self.record()
        self.assertEqual(after["prompt"], brief.read_text())
        self.assertEqual(after["brief"], str(brief.resolve()))
        self.assertEqual(after["perm"], "read-only")
        self.assertNotIn("refusals", after)
        self.assertFalse((self.out / "s1.jsonl").exists())

    def test_cross_agent_or_model_reroute_drops_old_effort_and_context(self):
        for target_agent, target_model, kind, role in (
                ("codex", "m1", "frontier", "advise"),
                ("claude", "claude-opus-5-5-high", "judgment", "exec")):
            with self.subTest(agent=target_agent, model=target_model):
                name = "cross-" + target_agent
                first = self.dispatch_agent("claude", "m1", "--effort", "high", "--context", "1m",
                                            name=name, env={"PREFLIGHT_MODE": "outage"})
                self.assertEqual(first.returncode, 5, first.stdout + first.stderr)
                old = self.out / "jobs" / (name + ".json")
                before = old.read_bytes()
                rec = json.loads(before)
                self.assertEqual((rec["effort"], rec["context"]), ("high", "1m"))
                result = run(["reroute", str(old), "--agent", target_agent, "--model", target_model,
                              "--kind", kind, "--role", role, "--acp-run", str(self.fake),
                              "--no-preflight"], env=self.base_env())
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                new = json.loads((self.out / "jobs" / (name + "-reroute-1.json")).read_text())
                self.assertIsNone(new["effort"])
                self.assertIsNone(new["context"])
                self.assertNotIn("--effort", new["cmd"])
                self.assertNotIn("--context", new["cmd"])
                self.assertEqual(new["rerouted_from"], str(old.resolve()))
                self.assertEqual(old.read_bytes(), before)

    def test_legacy_unavailable_context_refuses_cleanly_without_launch(self):
        # Produce a real preflight refusal, then reduce it to the older thin shape.
        first = self.dispatch(env={"PREFLIGHT_MODE": "outage"})
        self.assertEqual(first.returncode, 5, first.stdout + first.stderr)
        old = self.out / "jobs" / "s1.json"
        rec = self.record()
        rec.pop("prompt")
        rec.pop("perm")
        for brief in (None, str(self.tmp / "missing-brief.md")):
            with self.subTest(brief=brief):
                rec["brief"] = brief
                old.write_text(json.dumps(rec))
                before = old.read_bytes()
                probes = self.probes()
                result = run(["reroute", str(old), "--escalate"], env=self.base_env())
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertIn("-f FILE", result.stderr)
                self.assertEqual(old.read_bytes(), before)
                self.assertFalse((self.out / "jobs" / "s1-reroute-1.json").exists())
                self.assertEqual(self.probes(), probes)

    def test_legacy_unavailable_explicit_task_and_permission_recovery(self):
        for flag in ("-p", "-f"):
            with self.subTest(flag=flag):
                name = "legacy-" + flag[-1]
                first = self.dispatch(name=name, env={"PREFLIGHT_MODE": "outage"})
                self.assertEqual(first.returncode, 5, first.stdout + first.stderr)
                old = self.out / "jobs" / (name + ".json")
                rec = json.loads(old.read_text())
                for key in ("prompt", "brief", "perm"):
                    rec.pop(key, None)
                old.write_text(json.dumps(rec))
                before = old.read_bytes()
                brief = self.tmp / "recovery.md"
                original = "Recover original task; preserve the read-only constraint."
                brief.write_text(original)
                args = ["reroute", str(old), "--agent", "claude", "--model", "m1",
                        "--kind", "judgment", "--acp-run", str(self.fake), "--no-preflight",
                        flag, str(brief) if flag == "-f" else original]
                probes = self.probes()
                refused = run(args, env=self.base_env())
                self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
                self.assertIn("explicit --perm", refused.stderr)
                self.assertNotIn("Traceback", refused.stderr)
                self.assertEqual(self.probes(), probes)
                self.assertEqual(old.read_bytes(), before)
                self.assertFalse((self.out / "jobs" / (name + "-reroute-1.json")).exists())
                unsupported = run([*args, "--perm", "read-only"],
                                  env=self.base_env(FAKE_PERM_MODES='["all"]'))
                self.assertEqual(unsupported.returncode, 2, unsupported.stdout + unsupported.stderr)
                self.assertIn("no verified read-only mode", unsupported.stderr)
                self.assertEqual(old.read_bytes(), before)
                self.assertFalse((self.out / "jobs" / (name + "-reroute-1.json")).exists())
                recovered = run([*args, "--perm", "read-only"], env=self.base_env())
                self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
                new = json.loads((self.out / "jobs" / (name + "-reroute-1.json")).read_text())
                self.assertEqual(new["rerouted_from"], str(old.resolve()))
                self.assertIn(original, new["prompt"])
                self.assertEqual(new["perm"], "read-only")
                self.assertIn("--perm read-only", new["cmd"])
                self.assertEqual(old.read_bytes(), before)

    def test_completed_legacy_reroute_recovers_permission_from_command(self):
        for perm in ("deny", "read-only"):
            with self.subTest(perm=perm):
                name = "completed-" + perm
                first = self.dispatch_agent("claude", "m1", "--perm", perm, name=name)
                self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                old = self.out / "jobs" / (name + ".json")
                rec = json.loads(old.read_text())
                rec.pop("perm")  # older completed records retain the checked flag in cmd
                old.write_text(json.dumps(rec))
                refused = run(["reroute", str(old), "--agent", "claude", "--model", "m1",
                               "--perm", "all"], env=self.base_env())
                self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
                self.assertIn("preserve recorded permission", refused.stderr)
                result = run(["reroute", str(old), "--agent", "claude", "--model", "m1",
                              "--acp-run", str(self.fake), "--no-preflight"], env=self.base_env())
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                new = json.loads((self.out / "jobs" / (name + "-reroute-1.json")).read_text())
                self.assertEqual(new["perm"], perm)
                self.assertIn("--perm " + perm, new["cmd"])
                self.assertEqual(new["rerouted_from"], str(old.resolve()))

    def test_reroute_recovery_cannot_upgrade_recorded_permission(self):
        first = self.dispatch("--perm", "read-only", env={"PREFLIGHT_MODE": "outage"})
        self.assertEqual(first.returncode, 5, first.stdout + first.stderr)
        old = self.out / "jobs" / "s1.json"
        before = old.read_bytes()
        result = run(["reroute", str(old), "--agent", "codex", "--model", "m1",
                      "--perm", "all"], env=self.base_env())
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("preserve recorded permission", result.stderr)
        self.assertEqual(old.read_bytes(), before)
        self.assertFalse((self.out / "jobs" / "s1-reroute-1.json").exists())

    def test_scoped_perm_is_deprecated_and_runs_as_all(self):
        # operator 2026-10-14: acp-run runs yolo for every agent; scoped: warns and runs as all.
        r = self.dispatch("--perm", "scoped:x")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr.count("--perm scoped:x is no longer enforced"), 1, r.stderr)
        self.assertIn("treated as --perm all", r.stderr)
        rec = self.record()
        self.assertIn("--perm all ", rec["cmd"])
        self.assertNotIn("scoped:", rec["cmd"])
        self.assertEqual(rec["perm"], "all")

    def test_unknown_perm_is_refused(self):
        r = self.dispatch("--perm", "ask")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--perm must be all, read-only or deny", r.stderr)

    def test_dispatch_passes_add_dir_for_out(self):
        r = self.dispatch()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"--add-dir {self.out.resolve()}", self.record()["cmd"])

    def test_deny_perm_brief_says_the_final_message_is_the_report(self):
        # --perm deny refuses the report's Write too; the brief must not ask for the impossible.
        # frontier defaults to --role advise, which refuses deny (2026-10-19); exec is the old shape
        r = self.dispatch("--perm", "deny", "--role", "exec", env={"ACP_OPERATOR_APPROVED": "frontier-exec"})
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
        r = self.dispatch("--no-auto-resume", mode="quota")
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


class TestFrontierGates(Base):
    """2026-10-18: four gpt-6-astra slices started together emptied codex's 5-hour window and all
    four stopped; Fable at xhigh should almost never run."""

    def running_codex(self, estimated: float = 60.0) -> Path:
        jobs = self.tmp / "state" / "other-task" / "jobs"
        jobs.mkdir(parents=True)
        rec = jobs / "busy.json"
        pid_start = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(os.getpid())], check=False,
            capture_output=True, text=True).stdout.strip()
        rec.write_text(json.dumps({"name": "busy", "agent": "codex", "model": "m1", "service": "codex",
                                   "status": "running", "pid": os.getpid(), "pid_start": pid_start,
                                   "started": 0, "estimated_usage_pct": estimated}))
        return rec

    def codex_snap(self, remaining: float) -> dict[str, str]:
        snap = self.tmp / "latest.json"
        snap.write_text(json.dumps({"collected_at": "2099-01-01T00:00:00+00:00", "snapshot": {"accounts": [{
            "provider": "codex", "windows": [{"label": "5h", "remaining_percent": remaining}]}]}}))
        return {"AIUSE_SNAPSHOT": str(snap)}

    def test_fable_xhigh_needs_operator_approval(self):
        r = self.dispatch_model("fable-5-1", "--effort", "xhigh", "--no-model-check")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("ACP_OPERATOR_APPROVED=fable-xhigh", r.stderr)
        self.assertFalse((self.out / "jobs" / "s1.json").exists())
        r = self.dispatch_model("fable-5-1", "--effort", "xhigh", "--no-model-check",
                                env={"ACP_OPERATOR_APPROVED": "fable-xhigh"})
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_fable_high_is_not_gated(self):
        # frontier defaults to advise; no frontier-exec needed
        r = self.dispatch_model("fable-5-1", "--effort", "high", "--no-model-check")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_second_codex_slice_is_unavailable_while_one_is_in_flight(self):
        # Everyday Codex models have a 10% floor (2026-10-25): reserve 65 of 70%,
        # leaving 5%, below that floor. Frontier models retain their separate 60% floor.
        self.running_codex(65.0)
        r = self.dispatch(env=self.codex_snap(70.0))
        self.assertEqual(r.returncode, 5, (r.stdout, r.stderr))
        rec = self.record()
        self.assertEqual((rec["status"], rec["unavailable_class"]), ("unavailable", "inflight"))
        self.assertIn("busy", rec["detail"])
        # Hard-cap override still works when reservation leaves room (--est-pct under the remainder).
        self.assertEqual(self.dispatch(
            "--est-pct", "5", name="s2",
            env={**self.codex_snap(100.0), "ACP_DISPATCH_INFLIGHT": "codex=2"}).returncode, 0)

    def test_a_dead_or_finished_codex_record_does_not_count(self):
        rec = self.running_codex()
        rec.write_text(json.dumps({"agent": "codex", "status": "done", "pid": os.getpid()}))
        self.assertEqual(self.dispatch().returncode, 0)

    def test_other_agents_are_not_capped(self):
        self.running_codex()
        self.assertEqual(self.dispatch_agent("claude", "m1", env=self.codex_snap(70.0)).returncode, 0)


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

    def test_read_only_is_refused_for_an_agent_without_a_verified_mode(self):
        # 2026-10-23: `--perm read-only` on omp was refused by acp-run only after the record and
        # the preflight: a no-report in 2 s. The dispatch now reads acp-run's perm_modes first.
        r = self.dispatch_model("m1", "--perm", "read-only", "--detach", "--no-wait",
                                env={"FAKE_PERM_MODES": '["all", "deny"]'})
        self.assertEqual(r.returncode, 2, (r.stdout, r.stderr))
        self.assertIn("--perm read-only: codex has no verified read-only mode", r.stderr)
        self.assertIn("use --perm all with a read-only brief", r.stderr)
        self.assertFalse((self.out / "jobs" / "s1.json").exists())

    def test_read_only_dispatches_when_the_agent_lists_it(self):
        r = self.dispatch_model("m1", "--perm", "read-only")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.record()["perm"], "read-only")

    def test_read_only_without_perm_modes_warns_and_dispatches(self):
        r = self.dispatch_model("m1", "--perm", "read-only", env={"FAKE_PERM_MODES": "null"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("could not check --perm read-only", r.stderr)


class TestFailureNote(Base):
    """2026-10-10: codex died of quota after writing only `STATUS: working`; the waiter exited 0."""

    def test_quota_death_after_status_working_is_no_report_with_a_reason(self):
        # Since 2026-10-18 a quota stop schedules an in-place resume: the slice is still running
        # (exit 1, `resume-scheduled`); the NO-REPORT line is written all the same.
        r = self.dispatch(mode="quota_partial")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertTrue(r.stdout.startswith("resume-scheduled\t"), r.stdout)
        rec = self.record()
        self.assertEqual(rec["status"], "resume-scheduled")
        last = Path(rec["report"]).read_text().splitlines()[-1]
        self.assertTrue(last.startswith("NO-REPORT: quota (codex, m1, retry at 8:51 PM)"), last)
        self.assertEqual(rec["failure"], last)
        c = run(["check", str(self.out / "jobs" / "s1.json")])
        self.assertEqual(c.returncode, 1)
        self.assertIn("resume-scheduled", c.stdout)
        # opted out: the plain no-report, exit 3, with the manual resume command
        r = self.dispatch("--no-auto-resume", mode="quota_partial", name="s2")
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertTrue(r.stdout.startswith("no-report\t"), r.stdout)
        self.assertEqual(self.record("s2")["status"], "no-report")
        c = run(["check", str(self.out / "jobs" / "s2.json")])
        self.assertEqual(c.returncode, 3)
        self.assertIn("NO-REPORT: quota", c.stdout)
        self.assertIn(" resume ", c.stdout)

    def test_reset_in_a_duration_reads_retry_in(self):
        """2026-10-10: agy's refusal said "reset in 2 hours, 47 minutes", not a clock time."""
        r = self.dispatch("--no-auto-resume", mode="quota_reply")
        self.assertEqual(r.returncode, 3, r.stdout)
        last = Path(self.record()["report"]).read_text().splitlines()[-1]
        self.assertTrue(last.startswith("NO-REPORT: quota (codex, m1, retry in 2 hours, 47 minutes)"), last)

    def test_note_is_written_into_an_empty_report_too(self):
        r = self.dispatch("--no-auto-resume", mode="quota")
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
        self.dispatch("--no-auto-resume", mode="quota_partial")
        rec = self.out / "jobs" / "s1.json"
        r = run(["finalize", str(rec), "--exit", "1"])
        self.assertEqual(r.returncode, 3)
        text = Path(self.record()["report"]).read_text()
        self.assertEqual(text.count("NO-REPORT:"), 1, text)

    def test_rearm_waiter_exits_with_the_check_verdict(self):
        for mode, want in (("writes", 0), ("partial", 1), ("quota_partial", 3), ("blocked", 4)):
            # --no-auto-resume: with the automatic resume on, the waiter would wait through it
            self.dispatch("--no-auto-resume", mode=mode, name=mode.replace("_", "-"))
            rearm = self.record(mode.replace("_", "-"))["rearm"]
            self.assertIn("acp-dispatch-wait", rearm)   # ends in `check` inside the helper (2026-10-18)
            r = subprocess.run(["bash", "-c", rearm], check=False, capture_output=True, text=True)
            self.assertEqual(r.returncode, want, (mode, r.stdout, r.stderr))

    def test_rearm_waiter_outlasts_the_slice_timeout(self):
        # timeout + wrap-up grace (default 300) + 300 + acp-run's wait for a missing agent binary before its
        # own --timeout starts: ACP_RUN_BIN_WAIT (90) + bin_settle's up to 10 polls of ACP_RUN_BIN_POLL (2)
        self.dispatch("--timeout", "3600", name="long")
        self.assertEqual(self.record("long")["wait_timeout"], 4200 + 110)
        self.dispatch("--timeout", "3600", "--wait-timeout", "5000", name="waited")
        self.assertEqual(self.record("waited")["wait_timeout"], 5000)       # an explicit value is the caller's
        self.dispatch(name="default")
        self.assertEqual(self.record("default")["wait_timeout"], 3000 + 110)
        self.dispatch("--wrapup-grace", "0", name="nograce")
        self.assertEqual(self.record("nograce")["wait_timeout"], 2700 + 110)

    def test_rearm_waiter_covers_a_raised_binary_wait(self):
        # adversary PR 18 follow-up E: an operator who raises ACP_RUN_BIN_WAIT toward 600 must not see the
        # waiter give up before acp-run's own --timeout even starts
        self.dispatch("--timeout", "3600", name="raised", env={"ACP_RUN_BIN_WAIT": "600", "ACP_RUN_BIN_POLL": "5"})
        self.assertEqual(self.record("raised")["wait_timeout"], 4200 + 600 + 50)
        self.dispatch("--timeout", "3600", name="off", env={"ACP_RUN_BIN_WAIT": "0"})
        self.assertEqual(self.record("off")["wait_timeout"], 4200)           # no wait, no settle
        self.dispatch("--timeout", "3600", name="junk", env={"ACP_RUN_BIN_WAIT": "inf", "ACP_RUN_BIN_POLL": "abc"})
        self.assertEqual(self.record("junk")["wait_timeout"], 4200 + 110)    # acp-run's defaults


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

    def test_unlimited_has_no_budget_or_waiter_deadline(self):
        r = self.dispatch("--timeout", "0", "--wait-timeout", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        brief = Path(self.record()["brief"]).read_text()
        self.assertIn("no time limit", brief)
        self.assertNotIn("stops this slice", brief)
        self.assertEqual(self.record()["wait_timeout"], 0)
        self.assertIn("--timeout 0", self.record()["cmd"])


class TestSliceControls(Base):
    def record_path(self):
        return self.out / "jobs" / "s1.json"

    def test_session_id_is_saved_while_fake_agent_is_running(self):
        import time
        cmd = [sys.executable, str(SCRIPT), "codex", "--model", "m1", "--kind", "frontier",
               "--name", "s1",
               "-C", str(self.repo), "--out", str(self.out), "--acp-run", str(self.fake),
               "--no-model-check", "-p", "work"]
        with subprocess.Popen(cmd, env={**os.environ, **self.base_env("slow")},
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as proc:
            deadline = time.monotonic() + 10
            observed = None
            while time.monotonic() < deadline:
                if self.record_path().exists():
                    observed = self.record()
                    if observed.get("session_id"):
                        break
                time.sleep(0.05)
            stdout, stderr = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0, (stdout, stderr))
        self.assertIsNotNone(observed)
        self.assertEqual(observed["session_id"], "fake-session")
        self.assertIsNone(observed["finished"])

    def test_extend_live_and_refuse_finished(self):
        self.dispatch()
        p = self.record_path()
        self.assertEqual(run(["extend", str(p), "60"]).returncode, 2)
        rec = self.record()
        rec.update(finished=None, status="running", exit=None)
        Path(rec["done"]).unlink()
        p.write_text(json.dumps(rec))
        for value, want in (("60", 2460), ("0", 0)):
            r = run(["extend", str(p), value])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(Path(rec["log"] + ".extend").read_text().strip(), value)
            self.assertEqual(self.record()["timeout"], want)
        self.assertEqual(run(["extend", str(p), "-1"]).returncode, 2)

    def test_extend_refuses_costly_go_advisory_even_for_zero_and_leaves_no_control_file(self):
        self.dispatch()
        p = self.record_path()
        rec = self.record()
        rec.update(finished=None, status="running", exit=None, timeout=600,
                   cmd=rec["cmd"] + " --go-advisory --perm read-only --timeout 600")
        Path(rec["done"]).unlink()
        p.write_text(json.dumps(rec))
        for value in ("0", "60"):
            r = run(["extend", str(p), value])
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("costly Go advisory", r.stderr)
        self.assertFalse(Path(rec["log"] + ".extend").exists())
        self.assertEqual(self.record()["timeout"], 600)
        self.assertEqual(self.record().get("wait_timeout"), rec.get("wait_timeout"))

    def test_resume_preserves_session_and_archives_each_report(self):
        self.dispatch(mode="timeout_wrapup")
        self.assertEqual(self.record()["session_id"], "fake-session")
        for n in (1, 2):
            r = run(["resume", str(self.record_path()), "--timeout", "0"], env=self.base_env())
            self.assertEqual(r.returncode, 0, r.stderr)
            rec = self.record()
            self.assertIn("--resume fake-session", rec["cmd"])
            self.assertEqual(rec["resume_count"], n)
            self.assertTrue((self.out / f"s1-r{n}-report.md").exists())
            self.assertTrue(Path(rec["done"]).exists())
            self.assertEqual(run(["check", str(self.record_path())]).returncode, 0)
            brief = Path(rec["brief"]).read_text()
            self.assertIn("continue the brief", brief.lower())
            self.assertEqual(brief.count("## Delivery contract"), 1)

    def test_resume_legacy_log_and_custom_prompt(self):
        self.dispatch()
        rec = self.record()
        rec.pop("session_id", None)
        self.record_path().write_text(json.dumps(rec))
        prompt = self.tmp / "continue.txt"
        prompt.write_text("Finish the remaining check.")
        r = run(["resume", str(self.record_path()), "-f", str(prompt)], env=self.base_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(Path(rec["brief"]).read_text().startswith("Finish the remaining check."))

    def test_resume_unsupported_leaves_old_deliverable(self):
        self.dispatch()
        rec = self.record()
        Path(rec["log"]).write_text(json.dumps({"kind": "initialize", "data": {
            "agentCapabilities": {}}}) + "\n" + json.dumps({"kind": "new_session", "data": {
                "sessionId": "fake-session"}}) + "\n")
        old = Path(rec["report"]).read_text()
        r = run(["resume", str(self.record_path())], env=self.base_env())
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("neither load nor resume", r.stderr)
        self.assertEqual(Path(rec["report"]).read_text(), old)
        self.assertTrue(Path(rec["done"]).exists())

    def test_resume_of_an_agy_claude_slice_continues_in_a_new_session(self):
        # agy_acp_server strips thought signatures on session/load, so a reopened Claude
        # session 400s on its first turn (2026-10-18): continue fresh, with a checkpoint
        self.dispatch()
        rec = self.record()
        rec.update(agent="agy", model="claude-opus-5-5", model_applied="claude-opus-5-5")
        self.record_path().write_text(json.dumps(rec))
        with Path(rec["log"]).open("a") as log:
            log.write(json.dumps({"kind": "update", "data": {
                "sessionUpdate": "tool_call", "title": "Running edit_file"}}) + "\n")
        r = run(["resume", str(self.record_path()), "--timeout", "0"], env=self.base_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("continuing in a new session", r.stderr)
        rec = self.record()
        self.assertNotIn("--resume", rec["cmd"])
        brief = Path(rec["brief"]).read_text()
        self.assertTrue(brief.startswith("This continues a slice"), brief[:200])
        self.assertIn("Running edit_file", brief)
        self.assertIn("Git status of the working tree", brief)
        self.assertEqual(brief.count("## Delivery contract"), 1)

    def test_resume_of_an_agy_gemini_slice_reopens_its_session(self):
        self.dispatch()
        rec = self.record()
        rec.update(agent="agy", model="gemini-3.8-flash", model_applied="gemini-3.8-flash")
        self.record_path().write_text(json.dumps(rec))
        r = run(["resume", str(self.record_path()), "--timeout", "0"], env=self.base_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--resume fake-session", self.record()["cmd"])

    def test_resume_detached_runner_uses_same_finalize_contract(self):
        self.dispatch()
        mod = runpy.run_path(str(SCRIPT))
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")) as launch, \
             patch.dict(os.environ, self.base_env(), clear=False):
            rc = mod["main"](["resume", str(self.record_path()), "--detach", "--no-wait", "--timeout", "0"])
        self.assertEqual(rc, 0)
        self.assertTrue(launch.call_args.args[0][0].endswith("launchctl"), launch.call_args.args[0])
        self.assertEqual(launch.call_args.args[0][1], "submit")
        rec = self.record()
        self.assertFalse(Path(rec["done"]).exists())
        self.assertIn("--resume fake-session", rec["cmd"])
        runner = Path(rec["runner"]).read_text()
        self.assertIn(" execute ", runner)
        self.assertIn(" finalize ", runner)
        self.assertIn('--exit "$rc"', runner)
        # Invoke the fake agent through execute, never the launchd shell runner.
        self.assertEqual(mod["execute_record"](self.record_path()), 0)
        self.assertEqual(mod["finalize"](self.record_path(), 0)[0], "done")
        self.assertEqual(run(["check", str(self.record_path())]).returncode, 0)

    def test_waiter_observes_extension_after_it_starts(self):
        self.dispatch("--timeout", "1")
        rec = self.record()
        Path(rec["done"]).unlink()
        rec.update(started=0, finished=None, wait_timeout=2, timeout=1)
        self.record_path().write_text(json.dumps(rec))
        mod = runpy.run_path(str(SCRIPT))
        def next_tick(_):
            mod["extend_record"](self.record_path(), 0)
        with patch("time.time", side_effect=[1, 100]), patch("time.sleep", side_effect=next_tick):
            # On its second tick it sees unlimited; end the test with .done.
            count = [0]
            def ticks(_):
                count[0] += 1
                if count[0] == 1:
                    next_tick(0)
                else:
                    # finalize lands: `wait` returns on `finished`, not on `.done` alone (2026-10-18)
                    Path(rec["done"]).touch()
                    mod["update_record"](self.record_path(), finished=1.0, exit=0, pid=None)
            with patch("time.sleep", side_effect=ticks):
                self.assertEqual(mod["wait_record"](self.record_path()), 0)
        self.assertEqual(count[0], 2)

    def test_running_resume_refused_and_pending_extensions_accumulate(self):
        self.dispatch()
        rec = self.record()
        rec.update(finished=None, exit=None)
        Path(rec["done"]).unlink()
        self.record_path().write_text(json.dumps(rec))
        self.assertEqual(run(["resume", str(self.record_path())]).returncode, 2)
        for value in (30, 40):
            self.assertEqual(run(["extend", str(self.record_path()), str(value)]).returncode, 0)
        self.assertEqual(Path(rec["log"] + ".extend").read_text(), "70\n")
        self.assertEqual(self.record()["timeout"], 2470)

    def test_agy_delivers_from_non_git_workspace(self):
        r = self.dispatch_agent("agy", "m1", "--task", "test-task")
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = self.record()
        inner = self.repo / ".acp-dispatch" / "test-task-s1-report.md"
        self.assertEqual(Path(rec["agent_report"]), inner.resolve())
        self.assertIn(str(inner.resolve()), Path(rec["brief"]).read_text())
        self.assertFalse(inner.exists())
        self.assertTrue(Path(rec["report"]).exists())
        self.assertTrue(Path(rec["done"]).exists())

    def test_agy_git_exclude_appended_once(self):
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        for name in ("s1", "s2"):
            r = self.dispatch_agent("agy", "m1", name=name)
            self.assertEqual(r.returncode, 0, r.stderr)
        exclude = self.repo / ".git" / "info" / "exclude"
        self.assertEqual(exclude.read_text().splitlines().count(".acp-dispatch/"), 1)

    def test_agy_finalize_moves_inner_report_and_marker_before_out_done(self):
        self.dispatch_agent("agy", "m1")
        rec = self.record()
        self.assertIn(str(Path(rec["agent_report"]).parent), rec["cmd"])
        Path(rec["done"]).unlink()
        Path(rec["agent_report"]).write_text("STATUS: working\nnew inner result\nDONE\n")
        Path(rec["agent_done"]).touch()
        r = run(["finalize", str(self.record_path()), "--exit", "0"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("new inner result", Path(rec["report"]).read_text())
        self.assertFalse(Path(rec["agent_report"]).exists())
        self.assertFalse(Path(rec["agent_done"]).exists())
        self.assertTrue(Path(rec["done"]).exists())

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
        r = self.dispatch_agent("agy", "claude-opus-5-5-high", "--no-auto-resume", mode="quota_ts", env=env)
        self.assertEqual(r.returncode, 3)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertIn("note-exhausted antigravity --family claude_gpt --resets-at 2026-10-11T02:46:28Z", calls[0])
        self.assertIn("--reason", calls[0])

    def test_quota_refusal_agy_gemini_records_antigravity_gemini_resets_in(self):
        env = {"ACP_DISPATCH_AIUSE": str(self.fake_aiuse)}
        r = self.dispatch_agent("agy", "gemini-2.5-pro", "--no-auto-resume", mode="quota_gemini", env=env)
        self.assertEqual(r.returncode, 3)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertIn("note-exhausted antigravity --family gemini --resets-in 6d6h", calls[0])

    def test_quota_refusal_agy_gpt_records_antigravity_claude_gpt_resets_in(self):
        env = {"ACP_DISPATCH_AIUSE": str(self.fake_aiuse)}
        r = self.dispatch_agent("agy", "gpt-oss-120b", "--no-auto-resume", mode="quota_reply", env=env)
        self.assertEqual(r.returncode, 3)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertIn("note-exhausted antigravity --family claude_gpt --resets-in 2h47m", calls[0])

    def test_quota_refusal_codex_records_codex_resets_at_from_clock_time(self):
        env = {"ACP_DISPATCH_AIUSE": str(self.fake_aiuse)}
        r = self.dispatch_agent("codex", "m1", "--no-auto-resume", mode="quota_partial", env=env)
        self.assertEqual(r.returncode, 3)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("note-exhausted codex --resets-at "), calls[0])
        self.assertNotIn("--family", calls[0])

    def test_unknown_agent_runs_nothing_and_says_so(self):
        env = {"ACP_DISPATCH_AIUSE": str(self.fake_aiuse)}
        r = self.dispatch_agent("mystery", "m1", "--no-auto-resume", mode="quota_unknown", env=env)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.calls(), [])
        rec = self.record()
        self.assertIn("unknown agent", rec.get("failure", ""))

    def test_no_reset_time_runs_nothing_and_says_so(self):
        env = {"ACP_DISPATCH_AIUSE": str(self.fake_aiuse)}
        r = self.dispatch_agent("codex", "m1", "--no-auto-resume", mode="quota", env=env)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.calls(), [])
        rec = self.record()
        self.assertIn("no reset time", rec.get("failure", ""))

    def test_aiuse_failure_does_not_break_acp_dispatch(self):
        bad_aiuse = self.tmp / "failing-aiuse"
        bad_aiuse.write_text("#!/bin/bash\necho 'aiuse crashed' >&2\nexit 1\n")
        bad_aiuse.chmod(0o755)
        env = {"ACP_DISPATCH_AIUSE": str(bad_aiuse)}
        r = self.dispatch_agent("codex", "m1", "--no-auto-resume", mode="quota_partial", env=env)
        self.assertEqual(r.returncode, 3)
        self.assertIn("aiuse", r.stderr)

    def test_acp_dispatch_aiuse_off_disables_recording(self):
        env = {"ACP_DISPATCH_AIUSE": "off"}
        r = self.dispatch_agent("codex", "m1", "--no-auto-resume", mode="quota_partial", env=env)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.calls(), [])

    def test_preflight_outage_is_unavailable_and_notes_15m(self):
        r = self.dispatch(env={"ACP_DISPATCH_AIUSE": str(self.fake_aiuse), "PREFLIGHT_MODE": "outage"})
        self.assertEqual(r.returncode, 5)
        self.assertIn("class=outage", r.stdout)
        self.assertIn("note-exhausted codex --resets-in 15m --reason outage:", self.calls()[0])
        self.assertEqual(self.record()["status"], "unavailable")

    def test_zcode_1310_preflight_is_quota_with_reset(self):
        env = {"ACP_DISPATCH_AIUSE": str(self.fake_aiuse), "PREFLIGHT_MODE": "zcode_quota",
               "ACP_DISPATCH_PREFLIGHT": str(self.tmp / "preflight"),
               "PREFLIGHT_COUNT": str(self.tmp / "preflight-count"),
               "AIUSE_SNAPSHOT": str(self.tmp / "missing.json")}
        result = run(["zcode", "--kind", "bulk", "--name", "s1", "-p", "do it", "-C", str(self.repo),
                      "--out", str(self.out), "--acp-run", str(self.fake)], env=env)
        self.assertEqual(result.returncode, 5)
        self.assertIn("class=quota", result.stdout)
        # D2/MSG 2: zcode zone-less stamps are Beijing time, so aiuse gets the UTC instant
        self.assertIn("note-exhausted zai --resets-at 2026-10-14T14:56:01+00:00", self.calls()[0])
        old = self.out / "jobs" / "s1.json"
        before = old.read_bytes()
        rec = json.loads(before)
        self.assertEqual(rec["prompt"], "do it")
        self.assertEqual(rec["perm"], "all")
        self.assertNotIn("session_id", rec)
        self.assertFalse((self.out / "s1.jsonl").exists())
        recovered = run(["reroute", str(old), "--agent", "claude", "--model", "m1",
                         "--kind", "judgment", "--acp-run", str(self.fake), "--no-preflight"],
                        env=self.base_env())
        self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
        new = json.loads((self.out / "jobs" / "s1-reroute-1.json").read_text())
        self.assertEqual(new["rerouted_from"], str(old.resolve()))
        self.assertIn("do it", new["prompt"])
        self.assertEqual(new["perm"], "all")
        self.assertEqual(old.read_bytes(), before)

    def test_agent_metrics_stderr_is_not_classified_as_outage(self):
        env = {"ACP_DISPATCH_AIUSE": str(self.fake_aiuse)}
        r = self.dispatch(mode="agent_metrics", env=env)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.calls(), [])
        self.assertIn("NO-REPORT: agent", self.record().get("failure", ""))

    def test_slice_timeout_does_not_record_outage_note(self):
        env = {"ACP_DISPATCH_AIUSE": str(self.fake_aiuse)}
        r = self.dispatch(mode="timeout", env=env)
        self.assertEqual(r.returncode, 124)
        self.assertEqual(self.calls(), [])

    def test_quota_death_voids_cached_preflight(self):
        self.assertEqual(self.dispatch(name="first").returncode, 0)
        self.assertEqual(self.dispatch("--no-auto-resume", name="dies", mode="quota_checkpoint").returncode, 3)
        self.assertEqual(self.preflight_probes(), 1)
        self.assertEqual(self.dispatch(name="after").returncode, 0)
        self.assertEqual(self.preflight_probes(), 2)

    def test_quota_checkpointed_vs_plain_no_report(self):
        snap = self.tmp / "latest.json"
        snap.write_text(json.dumps({"collected_at": "2099-01-01T00:00:00+00:00", "snapshot": {"accounts": [{
            "provider": "codex", "windows": [{"label": "weekly", "remaining_percent": 12.0}]}]}}))
        env = {"AIUSE_SNAPSHOT": str(snap), "ACP_DISPATCH_AIUSE": "off"}
        r = self.dispatch("--est-pct", "9", mode="quota_checkpoint", env=env)
        self.assertEqual(r.returncode, 1)                 # resume-scheduled (2026-10-18)
        rec_path = self.out / "jobs" / "s1.json"
        chk = run(["check", str(rec_path)])
        self.assertEqual(chk.returncode, 1)
        self.assertIn("resume-scheduled", chk.stdout)
        self.assertIn(" reroute ", chk.stdout)            # the checkpoint reroute stays on offer
        # opted out of the automatic resume: the checkpoint reroute verdict as before
        r1 = self.dispatch("--est-pct", "9", "--no-auto-resume", mode="quota_checkpoint", name="s1b", env=env)
        self.assertEqual(r1.returncode, 3)
        chk1 = run(["check", str(self.out / "jobs" / "s1b.json")])
        self.assertEqual(chk1.returncode, 5)
        self.assertIn("quota-checkpointed", chk1.stdout)
        self.assertIn(" reroute ", chk1.stdout)
        r2 = self.dispatch("--name", "s2", "--no-auto-resume", mode="quota", env=env)
        self.assertEqual(r2.returncode, 3)
        chk2 = run(["check", str(self.out / "jobs" / "s2.json")])
        self.assertIn("no-report", chk2.stdout.splitlines()[0])
        self.assertNotIn("quota-checkpointed", chk2.stdout)

    def test_failure_class_rejects_bare_three_digit_metrics(self):
        mod = runpy.run_path(str(SCRIPT))
        cls, _ = mod["failure_class"](
            "acp-run: agent=codex stop=error secs=514.8 tools=536 fail=agent", 1)
        self.assertEqual(cls, "agent")

    def test_failure_class_label_stops_at_punctuation(self):
        # acp-run prints "FAILED <class>: <error>" and "fail=<class> error=..."; a class glued to
        # a colon or a parenthesis must not carry the punctuation into the class name.
        mod = runpy.run_path(str(SCRIPT))
        fc = mod["failure_class"]
        self.assertEqual(fc("FAILED quota:Individual quota reached", 1)[0], "quota")
        self.assertEqual(fc("FAILED transient (http/2 CANCEL)", 1)[0], "transient")
        self.assertEqual(fc("acp-run: agent=codex fail=transient: reply truncated", 1)[0], "transient")
        self.assertEqual(fc("FAILED agent-error: boom", 1)[0], "agent-error")


class TestCheckpointStale(Base):
    stale_env: ClassVar[dict[str, str]] = {"ACP_DISPATCH_STALE_CHECKPOINT_MIN": "1", "ACP_DISPATCH_AIUSE": "off"}

    def _live_checkpoint_rec(self, *, checkpoint: bool = True) -> Path:
        import time as time_mod
        jobs = self.out / "jobs"
        jobs.mkdir(parents=True, exist_ok=True)
        report = self.out / "s1-report.md"
        log = self.out / "s1.jsonl"
        done = self.out / "s1-report.md.done"
        record = jobs / "s1.json"
        report.write_text("")
        log.write_text('{"kind":"initialize"}\n')
        started = time_mod.time() - 7200
        rec = {
            "name": "s1", "agent": "codex", "model": "m1", "dir": str(self.repo),
            "task": "t", "out": str(self.out), "report": str(report), "done": str(done),
            "log": str(log), "record": str(record), "started": started,
            "checkpoint": checkpoint, "finished": None, "pid": os.getpid(), "pid_start": subprocess.run(["ps", "-o", "lstart=", "-p", str(os.getpid())], check=False, capture_output=True, text=True).stdout.strip(),
            "status": "running",
        }
        record.write_text(json.dumps(rec))
        old = time_mod.time() - 7200
        os.utime(report, (old, old))
        os.utime(log, None)
        return record

    def test_check_running_checkpoint_stale_when_report_old(self):
        record = self._live_checkpoint_rec()
        chk = run(["check", str(record)], env=self.stale_env)
        self.assertEqual(chk.returncode, 1)
        line = chk.stdout.splitlines()[0]
        self.assertTrue(line.startswith("running\t"), line)
        self.assertIn("checkpoint stale:", line)

    def test_check_no_stale_when_report_fresh(self):
        record = self._live_checkpoint_rec()
        os.utime(Path(json.loads(record.read_text())["report"]), None)
        chk = run(["check", str(record)], env=self.stale_env)
        self.assertNotIn("checkpoint stale:", chk.stdout)

    def test_check_no_stale_when_log_idle(self):
        record = self._live_checkpoint_rec()
        import time as time_mod
        rec = json.loads(record.read_text())
        old = time_mod.time() - 7200
        os.utime(rec["log"], (old, old))
        chk = run(["check", str(record)], env=self.stale_env)
        self.assertNotIn("checkpoint stale:", chk.stdout)

    def test_non_checkpoint_never_stale(self):
        record = self._live_checkpoint_rec(checkpoint=False)
        chk = run(["check", str(record)], env=self.stale_env)
        self.assertNotIn("checkpoint stale:", chk.stdout)

    def test_checkpoint_stale_seen_recorded_once(self):
        record = self._live_checkpoint_rec()
        env = self.stale_env
        run(["check", str(record)], env=env)
        first = json.loads(record.read_text()).get("checkpoint_stale_seen")
        self.assertIsNotNone(first)
        run(["check", str(record)], env=env)
        second = json.loads(record.read_text()).get("checkpoint_stale_seen")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()


class TestCancelledHint(unittest.TestCase):
    """2026-10-13: an opencode slice's 3,626 s foreground command was interrupted and cancelled the turn."""

    def test_stop_cancelled_note_points_at_the_footer_rule(self):
        import importlib.machinery
        import importlib.util
        import tempfile
        loader = importlib.machinery.SourceFileLoader("acp_dispatch_hint", str(Path(__file__).resolve().parent.parent / "bin" / "acp-dispatch"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as tmp:
            err = Path(tmp) / "err"
            err.write_text("acp-run: agent=opencode stop=cancelled secs=7444.2 tools=82\n")
            note = mod.failure_note(err, 1, "opencode", "m1")
        self.assertIn("stop=cancelled before the time limit", note)
        self.assertIn("dispatch-footer item 10", note)
