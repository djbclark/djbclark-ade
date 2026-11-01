#!/usr/bin/env python3
"""D2 tests (2026-10-18): quota-stop handling and cheap-first escalation in acp-dispatch.

Covers the brief's five items plus the lead's two additions: both new reset phrasings; a
far reset skipped with a reroute hint (agy and zcode — the rule is agent-general); the pmset
wake helper scheduling, reporting unavailable and cancelling through a fake sudo/pmset; the
exit-0 quota scan of the session log calling aiuse; the cheap-first ladder, `reroute
--escalate` (refused at the top rung) and the check hint; a partial checkpoint report
auto-resuming on quota (lead MSG 1); and zcode's zone-less reset stamp being Beijing time
(lead MSG 2, correcting MSG 1's UTC guess).

Reuses test_acp_dispatch's fake acp-run (extra FAKE_MODEs spliced in) and fake launchctl; a
tiny routing.toml of its own keeps route hints deterministic, and ACP_RUN points route_agent
at the same fake so discovery never touches the real acp-run.
"""
from __future__ import annotations

import json
import os
import runpy
import textwrap
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import override
from unittest import mock
from zoneinfo import ZoneInfo

from test_acp_dispatch import SCRIPT, Base, run

# agy's weekly cap, 6 days out; the stamp derives from it, the fake's "Resets in" text is the same
# duration as a literal (change both together)
FAR_RESET = timedelta(hours=148, minutes=22, seconds=36)

# Frozen-clock cases for the wake time (2026-11-01: the tests failed on the US fall-back because
# the code did its arithmetic on a fixed-offset `now`). quota_reply says "reset in 2 hours, 47
# minutes"; not_before adds the 5 min margin, so it is NOW + 2 h 52 min, and the wake is 2 min
# before it, as wall time in America/New_York AT THAT INSTANT. (now UTC, not_before UTC, wake
# stamp, not_before_iso); every figure is a literal, none is derived from the code under test.
NY = "America/New_York"
WAKE_CASES = {
    "fall-back": ("2026-11-01T04:30:00Z", "2026-11-01T07:22:00Z", "11/01/26 02:20:00",
                  "2026-11-01T02:22-05:00"),        # 00:30 EDT now, 02:22 EST then (a 3 h gap on the clock)
    "spring-forward": ("2026-03-08T06:30:00Z", "2026-03-08T09:22:00Z", "03/08/26 05:20:00",
                       "2026-03-08T05:22-04:00"),   # 01:30 EST now, 05:22 EDT then
    "no-transition": ("2026-07-01T12:00:00Z", "2026-07-01T14:52:00Z", "07/01/26 10:50:00",
                      "2026-07-01T10:52-04:00"),
}


def epoch(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()

EXTRA_MODES = textwrap.dedent("""\
      quota_far)  # agy's weekly cap as seen 2026-10-18: reset days out
              printf 'STATUS: working\\n' > "$report"
              echo "acp-run: FAILED quota: quota exhausted. Refreshes in 6 days and 4 hours" >&2
              echo "acp-run: agent=agy stop=error secs=50.0 tools=5 fail=quota" >&2
              exit 1;;
      quota_copilot_monthly)  # copilot as seen 2026-11-01 (bigteam fix-get): no reset text at all
              printf 'STATUS: working\\n' > "$report"
              echo "acp-run: FAILED quota: quota exhausted: Error: You have exceeded your monthly quota (Request ID: FBD4:1B828:16C3141:1CFD4D4:6AE77302)" >&2
              echo "acp-run: usage limit stopped session S1; after the reset continue it with: acp-run copilot --resume S1" >&2
              echo "acp-run: agent=copilot stop=end_turn secs=8.1 tools=0 fail=quota" >&2
              exit 1;;
      quota_exit0_log)  # the real agy event (acp-resume-hardening, 2026-10-18): exit 0,
              # report partial, 429 only in the session log — acp-run's stderr names no quota
              printf 'STATUS: working\\n' > "$report"
              printf '%s\\n' '{"kind":"update","data":{"content":"Agent run failed: Error 429, Message: Individual quota reached. Please upgrade your subscription to increase your limits. Resets in 148h22m36s., Status: RESOURCE_EXHAUSTED, Details: quotaResetTimeStamp:'"$QUOTA_RESET_STAMP"'"}}' >> "$log"
              echo "acp-run: agent=agy stop=end_turn secs=356.1 tools=38" >&2
              echo "written: $report"
              exit 0;;
      quota_zcode_exit0)  # lead MSG 1: zcode 1308, partial checkpoint report, nothing scheduled
              printf 'STATUS: working\\nstep one done\\n' > "$report"
              printf '%s\\n' '{"kind":"update","data":{"content":"1308 Usage limit reached for 5 hour. Your limit will reset at 2026-10-19 04:22:46"}}' >> "$log"
              echo "acp-run: agent=zcode stop=end_turn secs=356.1 tools=38" >&2
              echo "written: $report"
              exit 0;;
      quota_words_in_work)  # review 2026-10-18: a slice that greps quota code is not quota-stopped
              printf 'STATUS: working\\n' > "$report"
              printf '%s\\n' '{"kind":"update","data":{"sessionUpdate":"tool_call_update","status":"completed","rawOutput":"bin/acp-dispatch: Individual quota reached ... RESOURCE_EXHAUSTED"}}' >> "$log"
              printf '%s\\n' '{"kind":"update","data":{"sessionUpdate":"agent_thought_chunk","content":{"text":"the usage limit regex"}}}' >> "$log"
              echo "acp-run: agent=zcode stop=end_turn secs=56.1 tools=8" >&2
              echo "written: $report"
              exit 0;;
    """)

# fake acp-run with D2's modes plus a --list handler, so route_agent's discovery is hermetic


def make_fake(base_fake: str) -> str:
    out = base_fake.replace(
        'for x in "$@"; do',
        'if [ "$1" = "--list" ]; then echo "ok zcode /usr/local/bin/zcode"; '
        'echo "ok agy /usr/local/bin/agy"; echo "ok claude /usr/local/bin/claude"; exit 0; fi\n'
        'for x in "$@"; do', 1)
    # the dedented FAKE indents case labels 2 spaces; anchor on the bare label
    return out.replace("echoargs)", EXTRA_MODES.rstrip("\n") + "\n  echoargs)", 1)


FAKE_SUDO = """#!/bin/bash
# fake sudo: tests must never run a real sudo -n. Fails like the real non-tinteractive
# one when SUDO_FAIL is set (this machine has no NOPASSWD rule for pmset).
[ -n "$SUDO_FAIL" ] && { echo "sudo: a password is required" >&2; exit 1; }
echo "sudo $*" >> "$SUDO_LOG"
while [ "${1#-}" != "$1" ]; do shift; done     # sudo's own flags (-k -n), not pmset's
exec "$@"
"""

FAKE_PMSET = """#!/bin/bash
# fake pmset: logs its argv (the real one needs root; the helper wraps it in sudo -n)
echo "pmset $*" >> "$PMSET_LOG"
exit 0
"""

FAKE_AIUSE_LOG = """#!/bin/bash
# fake aiuse: note-exhausted logs its argv; everything else is accepted silently
[ "$1" = note-exhausted ] && { printf '%s\\n' "$*" >> "$AIUSE_NOTE_LOG"; exit 0; }
exit 0
"""

POLICY_TOML = """\
[routing]
kinds = ["judgment", "frontier", "code", "bulk", "research", "mechanical", "github", "realtime-web"]
burn_first_min = 40.0
burn_first_bonus = 4.0
burn_first_waste_min = 30.0
pace_penalty_above = 1.5
pace_penalty = 6.0
pace_penalty_judgment_factor = 0.5
plenty_min = 50.0
default_profile = { bulk = 60, mechanical = 60 }

[calibrate]
min_outcomes = 5
min_peers = 2
suggest_worse_below = 25.0
suggest_worse_delta = 5
suggest_better_above = 15.0
suggest_better_delta = 3

[discovery]
never_route = ["hermes"]
operator_gated = ["omp"]
aliases = {}

[dispatch]
operator_gated = ["omp", "hermes"]
fable_gated_efforts = ["xhigh", "max"]
frontier_models = ["gpt-6-astra", "fable"]
inflight_cap = {}
auto_resume_max_wait_hours = 6

[escalation]
# Operator 2026-10-18: cheap first; a failed slice climbs one rung, never straight to frontier.
ladder = ["mechanical", "bulk", "code", "judgment", "frontier"]

[escalation.next]
research = "judgment"

[hermes]

[[service]]
name = "codex"
cli = "codex"
good_at = { frontier = 1 }
billing = "subscription"
judgment_tier = true
models = { frontier = "m1 --effort high" }

[[service]]
name = "claude"
cli = "claude"
good_at = { judgment = 1, code = 15 }
billing = "subscription"
judgment_tier = true
models = { judgment = "m1 --effort high", code = "m1 --effort high" }

[[service]]
name = "antigravity-claude"
cli = "agy (claude/gpt pool)"
good_at = { code = 5 }
billing = "subscription"
pool = ["antigravity", "claude_gpt"]
agent = "agy"
models = { code = "m1 --effort high" }

[[service]]
name = "zai"
cli = "zcode"
good_at = { code = 10, bulk = 2 }
billing = "subscription"
agent = "zcode"
models = { code = "m1 --effort high", bulk = "m1 --effort low" }
"""


class QuotaBase(Base):
    """Base with D2's fake acp-run modes, its own routing policy, and fake sudo/pmset."""

    @override
    def setUp(self) -> None:
        super().setUp()
        import test_acp_dispatch as tad
        self.fake.write_text(make_fake(tad.FAKE))
        self.fake.chmod(0o755)
        self.bindir = self.tmp / "bin"
        self.bindir.mkdir()
        self.sudo = self.bindir / "sudo"
        _ = self.sudo.write_text(FAKE_SUDO)
        self.sudo.chmod(0o755)
        self.pmset = self.bindir / "pmset"
        _ = self.pmset.write_text(FAKE_PMSET)
        self.pmset.chmod(0o755)
        self.sudo_log = self.tmp / "sudo.log"
        self.pmset_log = self.tmp / "pmset.log"
        self.policy = self.tmp / "routing.toml"
        _ = self.policy.write_text(POLICY_TOML)
        self.aiuse_note_log = self.tmp / "aiuse-note.log"
        self.fake_aiuse = self.tmp / "fake-aiuse"
        _ = self.fake_aiuse.write_text(FAKE_AIUSE_LOG)
        self.fake_aiuse.chmod(0o755)

    @override
    def base_env(self, mode: str = "writes", **extra: str) -> dict[str, str]:
        return super().base_env(mode, **{
            "ROUTING_POLICY": str(self.policy), "ACP_RUN": str(self.fake),
            "PATH": f"{self.bindir}:{os.environ.get('PATH', '')}",
            "ACP_DISPATCH_MAX_WAIT_HOURS": "6",      # D2 tests exercise the rule itself
            "ACP_DISPATCH_PMSET": str(self.pmset), "SUDO_LOG": str(self.sudo_log),
            "PMSET_LOG": str(self.pmset_log), "AIUSE_NOTE_LOG": str(self.aiuse_note_log),
            **extra})

    def pmset_calls(self) -> list[str]:
        return self.pmset_log.read_text().splitlines() if self.pmset_log.exists() else []

    def record_path(self, name: str = "s1") -> Path:
        return self.out / "jobs" / f"{name}.json"

    def aiuse_notes(self) -> list[str]:
        return self.aiuse_note_log.read_text().splitlines() if self.aiuse_note_log.exists() else []


class TestResetFormatsD2(unittest.TestCase):
    """Item 1 (both new phrasings) and item 7 (zcode's zone-less stamp is Beijing time)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = runpy.run_path(str(SCRIPT))

    def parse(self, text: str, agent: str | None = None):
        fc = self.mod["failure_class"]
        return fc(text, 1)[1]

    def test_compact_units_parse(self):
        prd, prfa = self.mod["parse_reset_datetime"], self.mod["parse_reset_for_aiuse"]
        now = datetime(2026, 10, 18, 1, 0).astimezone()
        text = "FAILED quota: Error 429: Individual quota reached. Resets in 148h22m36s."
        when = self.parse(text)
        self.assertEqual(when.group(2), "148h22m36s")
        self.assertEqual(prd(text, when, now), now + timedelta(hours=148, minutes=22, seconds=36))
        self.assertEqual(prfa(text, when), ("--resets-in", "148h22m36s"))

    def test_refreshes_with_and_separator_parses(self):
        prd, prfa = self.mod["parse_reset_datetime"], self.mod["parse_reset_for_aiuse"]
        now = datetime(2026, 10, 18, 1, 0).astimezone()
        for text, want in (
            ("FAILED quota: quota exhausted. Refreshes in 6 days and 4 hours", timedelta(days=6, hours=4)),
            ("FAILED quota: Refreshes in 1 day and 30 minutes", timedelta(days=1, minutes=30)),
        ):
            when = self.parse(text)
            self.assertIsNotNone(when, text)
            self.assertEqual(prd(text, when, now), now + want, text)
        self.assertEqual(prfa("FAILED quota: Refreshes in 6 days and 4 hours", self.parse(
            "FAILED quota: Refreshes in 6 days and 4 hours")), ("--resets-in", "6d4h"))
        self.assertEqual(prfa("FAILED quota: Refreshes in 1 day and 30 minutes", self.parse(
            "FAILED quota: Refreshes in 1 day and 30 minutes")), ("--resets-in", "1d30m"))

    def test_older_phrasings_still_parse(self):
        prd = self.mod["parse_reset_datetime"]
        now = datetime(2026, 10, 18, 1, 0).astimezone()
        text = "FAILED quota: quota exhausted: retry in 2 hours, 47 minutes"
        self.assertEqual(prd(text, self.parse(text), now), now + timedelta(hours=2, minutes=47))

    def test_zcode_zoneless_stamp_is_beijing_time(self):
        """Lead MSG 2: `2026-10-19 04:22:46` is 2026-10-18T20:22:46+00:00 (Asia/Shanghai)."""
        prd, prfa = self.mod["parse_reset_datetime"], self.mod["parse_reset_for_aiuse"]
        text = "1308 Usage limit reached for 5 hour. Your limit will reset at 2026-10-19 04:22:46"
        now = datetime(2026, 10, 18, 1, 0).astimezone()
        want = datetime(2026, 10, 18, 20, 22, 46, tzinfo=timezone.utc)
        self.assertEqual(prd(text, self.parse(text), now, agent="zcode"), want)
        flag, val = prfa(text, self.parse(text), agent="zcode")
        self.assertEqual((flag, val), ("--resets-at", "2026-10-18T20:22:46+00:00"))
        # every other agent's zone-less stamp stays the local clock, as before
        local = datetime(2026, 10, 19, 4, 22, 46).astimezone()
        self.assertEqual(prd(text, self.parse(text), now, agent="codex"), local)
        # a stamp that carries its own zone is never reinterpreted
        zoned = "limit will reset at 2026-10-19 04:22:46+02:00"
        self.assertEqual(prd(zoned, None, now, agent="zcode"),
                         datetime.fromisoformat("2026-10-19T04:22:46+02:00"))


class TestCopilotQuotaClass(unittest.TestCase):
    """2026-11-01: GitHub Copilot's quota stops classify as `quota` (so far_reset says reroute)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = runpy.run_path(str(SCRIPT))

    def cls(self, text: str) -> str | None:
        return self.mod["failure_class"](text, 1)[0]

    def test_cli_402_no_quota(self):         # github/copilot-cli#3431
        self.assertEqual(self.cls('Model call failed: {"message":"You have no quota","code":"quota_exceeded"}'), "quota")
        self.assertEqual(self.cls("Execution failed: 402 You have no quota"), "quota")

    def test_cli_quota_exceeded_upgrade(self):
        self.assertEqual(self.cls("Quota exceeded. Upgrade to increase your limit: https://github.com/features/copilot/plans"),
                         "quota")

    def test_premium_request_allowance_and_limit(self):   # community discussions 165869, 158775
        self.assertEqual(self.cls("You have exceeded your premium request allowance. We have automatically "
                                  "switched you to GPT-4.1"), "quota")
        self.assertEqual(self.cls("You have exceeded your premium request limit, and do not currently have "
                                  "overages enabled."), "quota")

    def test_weekly_rate_limit_names_its_reset(self):     # github/copilot-cli#2742
        text = ("You've reached your weekly rate limit. Please wait for your limit to reset on "
                "April 19, 2026 at 9:00 PM or switch to auto model to continue.")
        cls, when = self.mod["failure_class"](text, 1)
        self.assertEqual(cls, "quota")
        self.assertEqual(self.mod["parse_reset_datetime"](text, when),
                         datetime(2026, 4, 19, 21, 0).astimezone())

    def test_ai_credits_exhausted(self):
        for text in ("You've used all of your AI credits for this month.",
                     "Your AI credits are exhausted; set a budget for additional usage."):
            self.assertEqual(self.cls(text), "quota", text)

    def test_bare_resource_names_do_not_match(self):
        for text in ("each prompt uses one premium request", "AI credits draw down your budget",
                     "monthly premium requests reset on the 1st", "weekly report written"):
            self.assertNotEqual(self.cls(text), "quota", text)

    def test_agent_text_about_premium_requests_is_not_a_stop(self):
        # a slice that greps or writes about Copilot quota: message chunks and completed tool output
        # are skipped by quota_log_tail, so exit0 detection never sees them
        import tempfile
        lines = [
            {"kind": "update", "data": {"sessionUpdate": "agent_message_chunk", "content": {
                "text": "You have exceeded your premium request allowance is the new term"}}},
            {"kind": "update", "data": {"sessionUpdate": "tool_call_update", "status": "completed",
                                        "rawOutput": 'bin/acp-dispatch: "you have no quota" quota_exceeded'}},
        ]
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "s.jsonl"
            log.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
            tail = self.mod["quota_log_tail"](log)
        self.assertEqual(tail, "")
        self.assertNotEqual(self.cls(tail), "quota")

    def test_current_monthly_quota_wording_and_error_json(self):   # microsoft/vscode#343806
        for text in ("Payment required error: 402 You have exceeded your monthly quota",
                     "Error: You have exceeded your monthly quota (Request ID: FBD4:1B828)",
                     '{"errorType":"quota","statusCode":402}'):
            self.assertEqual(self.mod["failure_class"](text, 1)[0], "quota", text)

    def test_retry_after_ms_is_the_reset(self):
        text = ('{"errorType":"quota","message":"You have exceeded your monthly quota","statusCode":402,'
                '"errorCode":"quota_exceeded","retry_after_ms":726841922}')
        now = datetime(2026, 10, 23, 12, 0).astimezone()
        prd, prfa = self.mod["parse_reset_datetime"], self.mod["parse_reset_for_aiuse"]
        when = self.mod["failure_class"](text, 1)[1]
        self.assertEqual(prd(text, when, now), now + timedelta(milliseconds=726841922))
        self.assertEqual(prfa(text, when), ("--resets-in", "726841s"))

    def test_error_json_inside_a_session_log_event_reads_the_same(self):
        # quota_log_tail hands the parsers raw JSONL, so the error's JSON is string-escaped there
        import tempfile
        for body in ('{"errorType":"quota","statusCode":402,"retry_after_ms":60000}',
                     '{\n  "errorType": "quota",\n  "statusCode": 402,\n  "retry_after_ms": 60000\n}'):
            ev = {"kind": "update", "data": {"content": "Agent run failed: " + body}}
            with tempfile.TemporaryDirectory() as d:
                log = Path(d) / "s.jsonl"
                log.write_text(json.dumps(ev) + "\n")
                text = self.mod["quota_log_tail"](log)
            self.assertIn('\\"', text)                    # really escaped
            cls, when = self.mod["failure_class"](text, 0)
            self.assertEqual(cls, "quota", text)
            now = datetime(2026, 11, 1, 12, 0).astimezone()
            self.assertEqual(self.mod["parse_reset_datetime"](text, when, now), now + timedelta(seconds=60))
            self.assertEqual(self.mod["parse_reset_for_aiuse"](text, when), ("--resets-in", "60s"))

    def test_on_phrases_need_a_dated_month_and_never_read_the_clock(self):
        fc, prd = self.mod["failure_class"], self.mod["parse_reset_datetime"]
        now = datetime(2026, 11, 1, 1, 0).astimezone()
        # no month name after `on`: not a reset phrase at all (was a global `retry on failure` match)
        self.assertIsNone(fc("FAILED transient: will retry on failure", 1)[1])
        # a month day without a year is not a clock time (was today/tomorrow 12:00, a wrong near reset)
        text = "quota exceeded. upgrade: resets on November 1 at 12:00 AM"
        self.assertEqual(fc(text, 1)[0], "quota")
        self.assertIsNone(prd(text, fc(text, 1)[1], now))
        self.assertIsNone(self.mod["parse_reset_for_aiuse"](text, fc(text, 1)[1]))

    def test_budget_limit_reached_is_not_a_quota_term(self):
        self.assertNotEqual(self.mod["failure_class"]("organization budget limit reached", 1)[0], "quota")


class TestFarResetSkips(QuotaBase):
    """Item 2: a reset beyond auto_resume_max_wait_hours is rerouted, not scheduled."""

    def test_agy_weekly_cap_skips_and_hints_a_reroute(self):
        r = self.dispatch_agent("agy", "claude-opus-5-5-high", "--kind", "code", mode="quota_far")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        rec = self.record()
        ar = rec["auto_resume"]
        self.assertEqual((ar["state"], ar.get("far_reset")), ("skipped", True))
        self.assertIn("reroute instead of waiting", ar["detail"])
        self.assertIn("is more than 6 h away", ar["detail"])       # the reset time is named
        self.assertEqual(self.launchctl(), [])                      # nothing sat in launchd
        c = run(["check", str(self.record_path())], env=self.base_env())
        self.assertEqual(c.returncode, 3, c.stdout)
        self.assertIn("reroute now:", c.stdout)
        self.assertIn("--agent zcode --model m1", c.stdout)         # top code route minus agy's pool

    def test_copilot_monthly_quota_without_reset_is_far_and_rerouted(self):
        # fix-get's record shape (2026-11-01): quota NO-REPORT, exit 1, no reset text, aiuse has no
        # copilot pool; it used to schedule a 30 min back-off resume on Copilot, three times
        r = self.dispatch_agent("copilot", "m1", "--kind", "code", mode="quota_copilot_monthly",
                                env={"ACP_OPERATOR_APPROVED": "route-override"})
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        rec = self.record()
        self.assertIn("NO-REPORT: quota (copilot, m1)", rec["failure"])
        ar = rec["auto_resume"]
        self.assertEqual((ar["state"], ar.get("far_reset")), ("skipped", True))
        self.assertNotEqual(ar.get("reset_source"), "backoff")
        self.assertIn("reroute instead of waiting", ar["detail"])
        self.assertEqual(self.launchctl(), [])                      # nothing sat in launchd
        c = run(["check", str(self.record_path())], env=self.base_env())
        self.assertEqual(c.returncode, 3, c.stdout)
        self.assertIn("reroute now:", c.stdout)
        self.assertNotIn("--agent copilot", c.stdout)               # the stopped pool is excluded

    def test_non_copilot_without_reset_still_resumes_in_place(self):
        r = self.dispatch_agent("zcode", "m1", "--kind", "code", mode="quota_copilot_monthly")
        ar = self.record()["auto_resume"]
        self.assertEqual(ar["state"], "scheduled", r.stdout + r.stderr)
        self.assertEqual(ar["reset_source"], "backoff")

    def test_the_rule_is_agent_general_zcode_weekly(self):
        r = self.dispatch_agent("zcode", "m1", "--kind", "code", mode="quota_far")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual(self.record()["auto_resume"]["state"], "skipped")
        c = run(["check", str(self.record_path())], env=self.base_env())
        self.assertIn("reroute now:", c.stdout)
        self.assertIn("--agent agy --model m1", c.stdout)           # zai excluded, agy's pool wins

    def test_no_eligible_pool_keeps_the_manual_hint(self):
        r = self.dispatch_agent("codex", "m1", "--kind", "frontier", mode="quota_far")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual(self.record()["auto_resume"].get("far_reset"), True)
        c = run(["check", str(self.record_path())], env=self.base_env())
        self.assertEqual(c.returncode, 3, c.stdout)
        self.assertNotIn("reroute now:", c.stdout)
        self.assertIn(" resume ", c.stdout)                          # the manual hint stays
        self.assertIn("no other pool eligible for kind 'frontier'", c.stdout)

    @staticmethod
    def frozen(case: str) -> dict[str, str]:
        return {"TZ": NY, "ACP_DISPATCH_NOW": WAKE_CASES[case][0]}

    def test_short_reset_still_schedules_with_a_wake(self):
        r = self.dispatch_agent("zcode", "m1", "--kind", "code", mode="quota_reply",
                                env=self.frozen("no-transition"))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)       # resume-scheduled
        rec = self.record()
        ar = rec["auto_resume"]
        self.assertEqual(ar["state"], "scheduled")
        self.assertNotIn("far_reset", ar)
        # the wake: 2 min before not_before, pmset's quoted MM/dd/yy HH:mm:ss (man pmset)
        want = WAKE_CASES["no-transition"][2]
        self.assertEqual(ar["wake"], f"scheduled {want}")
        self.assertEqual(self.pmset_calls(), [f"pmset schedule wake {want}"])
        # routed through sudo -k -n: a cached ticket must not stand in for the rule (2026-10-18)
        self.assertIn("sudo -k -n ", self.sudo_log.read_text())
        self.assertIn("schedule wake", self.sudo_log.read_text())

    def test_wake_unavailable_is_recorded_not_fatal(self):
        r = self.dispatch_agent("zcode", "m1", "--kind", "code", mode="quota_reply",
                                env={"SUDO_FAIL": "1"})
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        ar = self.record()["auto_resume"]
        self.assertEqual(ar["state"], "scheduled")                    # the resume stands
        self.assertTrue(ar["wake"].startswith("unavailable: "), ar["wake"])
        self.assertIn("password is required", ar["wake"])

    def test_reroute_cancels_the_wake_with_the_same_time(self):
        self.dispatch_agent("zcode", "m1", "--kind", "code", mode="quota_reply",
                            env=self.frozen("fall-back"))
        want = WAKE_CASES["fall-back"][2]
        rr = run(["reroute", str(self.record_path()), "--agent", "claude", "--model", "m1",
                 "--acp-run", str(self.fake)], env=self.base_env(TZ=NY))
        self.assertEqual(rr.returncode, 0, rr.stdout + rr.stderr)
        self.assertEqual(self.record()["auto_resume"]["state"], "cancelled")
        self.assertEqual(self.pmset_calls(),
                         [f"pmset schedule wake {want}", f"pmset schedule cancel wake {want}"])


class TestWakeAcrossDst(QuotaBase):
    """Frozen clock, TZ set: the schedule is computed in UTC and the wake is local wall time at the
    wake instant, so a DST change between now and the wake is right (it never depends on the day
    the suite runs)."""

    def check_case(self, case: str) -> None:
        now, not_before, wake, iso = WAKE_CASES[case]
        r = self.dispatch_agent("zcode", "m1", "--kind", "code", mode="quota_reply",
                                env={"TZ": NY, "ACP_DISPATCH_NOW": now})
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        ar = self.record()["auto_resume"]
        self.assertEqual(ar["state"], "scheduled")
        self.assertEqual(ar["not_before"], epoch(not_before))
        self.assertEqual(ar["not_before_iso"], iso)
        self.assertEqual(ar["wake"], f"scheduled {wake}")
        self.assertEqual(self.pmset_calls(), [f"pmset schedule wake {wake}"])

    def test_schedule_and_wake_across_fall_back(self):
        self.check_case("fall-back")

    def test_schedule_and_wake_across_spring_forward(self):
        self.check_case("spring-forward")

    def test_schedule_and_wake_with_no_transition(self):
        self.check_case("no-transition")

    def test_wake_stamp_is_wall_time_in_the_zone_at_the_wake_instant(self):
        mod = runpy.run_path(str(SCRIPT))
        wake_stamp = mod["wake_stamp"]
        with mock.patch.dict(os.environ, {"TZ": NY}):
            for case, (_, not_before, wake, _) in WAKE_CASES.items():
                with self.subTest(case=case):
                    aware = datetime.fromisoformat(not_before.replace("Z", "+00:00"))
                    self.assertEqual(wake_stamp(epoch(not_before)), wake)
                    self.assertEqual(wake_stamp(aware), wake)
                    # an aware datetime in a fixed offset taken BEFORE the change is the same instant
                    self.assertEqual(wake_stamp(aware.astimezone(timezone(timedelta(hours=-4)))), wake)
            # the 2 min lead itself crosses the change: 01:01 EST (06:01Z) minus 2 min is 01:59 EDT
            self.assertEqual(wake_stamp(epoch("2026-11-01T06:01:00Z")), "11/01/26 01:59:00")
            # spring-forward: 03:01 EDT (07:01Z) minus 2 min is 01:59 EST
            self.assertEqual(wake_stamp(epoch("2026-03-08T07:01:00Z")), "03/08/26 01:59:00")

    def test_local_zone_prefers_tz_and_now_is_frozen_in_utc(self):
        mod = runpy.run_path(str(SCRIPT))
        with mock.patch.dict(os.environ, {"TZ": NY, "ACP_DISPATCH_NOW": "2026-11-01T04:30:00Z"}):
            self.assertEqual(mod["local_zone"](), ZoneInfo(NY))
            self.assertEqual(mod["now_utc"](), datetime(2026, 11, 1, 4, 30, tzinfo=timezone.utc))
            self.assertEqual(mod["now_utc"]().utcoffset(), timedelta(0))

    def test_local_zone_resolves_every_tz_form_to_the_real_zone(self):
        """TZ=:/usr/share/zoneinfo/America/New_York is valid, and ZoneInfo(key) rejects a path: the
        fallback froze today's offset, so a wake after the change was an hour wrong (Codex, PR 213).
        Every spelling of the same zone, and a copied zone file outside any zoneinfo directory, must
        give the DST-aware zone."""
        import tempfile
        import zoneinfo
        zone_file = next((Path(root) / NY for root in zoneinfo.TZPATH if (Path(root) / NY).is_file()), None)
        if zone_file is None:
            self.skipTest("no system zoneinfo file for " + NY)
        mod = runpy.run_path(str(SCRIPT))
        wake_stamp = mod["wake_stamp"]
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "localtime-copy"
            copy.write_bytes(zone_file.read_bytes())
            forms = [NY, ":" + NY, str(zone_file), ":" + str(zone_file), str(copy), ":" + str(copy)]
            for form in forms:
                with self.subTest(tz=form), mock.patch.dict(os.environ, {"TZ": form}):
                    # 06:01Z on the fall-back day is 01:01 EST, a wake 2 min earlier is 01:59 EDT;
                    # a fixed offset taken on either side of the change gets one of these wrong
                    self.assertEqual(wake_stamp(epoch("2026-11-01T06:01:00Z")), "11/01/26 01:59:00")
                    self.assertEqual(wake_stamp(epoch("2026-11-01T07:22:00Z")), "11/01/26 02:20:00")
                    self.assertEqual(wake_stamp(epoch("2026-03-08T07:01:00Z")), "03/08/26 01:59:00")

    def test_empty_tz_is_utc_and_unset_tz_is_the_machine_zone(self):
        """libc reads TZ="" (and ":") as UTC; the /etc/localtime lookup is for an UNSET TZ only
        (Codex local review, PR 213)."""
        mod = runpy.run_path(str(SCRIPT))
        wake_stamp = mod["wake_stamp"]
        at = epoch("2026-11-01T06:01:00Z")
        for form in ("", ":"):
            with self.subTest(tz=form), mock.patch.dict(os.environ, {"TZ": form}):
                self.assertEqual(mod["local_zone"]().utcoffset(None), timedelta(0))
                self.assertEqual(wake_stamp(at), "11/01/26 05:59:00")
        env = {k: v for k, v in os.environ.items() if k != "TZ"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
                mod["os"].path, "realpath", return_value="/usr/share/zoneinfo/" + NY):
            self.assertEqual(wake_stamp(at), "11/01/26 01:59:00")

    def test_clock_time_reset_is_local_wall_clock_across_the_change(self):
        mod = runpy.run_path(str(SCRIPT))
        prd, fc = mod["parse_reset_datetime"], mod["failure_class"]
        text = "FAILED quota: try again at 8:51 PM."
        with mock.patch.dict(os.environ, {"TZ": NY}):
            # 00:30 EDT on 11-01; 8:51 PM that evening is EST (UTC-5)
            fall = datetime(2026, 11, 1, 4, 30, tzinfo=timezone.utc)
            self.assertEqual(prd(text, fc(text, 1)[1], fall), datetime(2026, 11, 2, 1, 51, tzinfo=timezone.utc))
            # 01:30 EST on 03-08; 8:51 PM that evening is EDT (UTC-4)
            spring = datetime(2026, 3, 8, 6, 30, tzinfo=timezone.utc)
            self.assertEqual(prd(text, fc(text, 1)[1], spring), datetime(2026, 3, 9, 0, 51, tzinfo=timezone.utc))
            # a duration is absolute elapsed time across the change: 00:30 EDT + 2 h 47 = 02:17 EST
            dur = "FAILED quota: quota exhausted: retry in 2 hours, 47 minutes"
            self.assertEqual(prd(dur, fc(dur, 1)[1], fall), datetime(2026, 11, 1, 7, 17, tzinfo=timezone.utc))


class TestExit0Quota(QuotaBase):
    """Item 4: rc 0 no longer skips quota detection; items 6-7 ride the same path."""

    def test_agy_exit0_quota_in_log_is_a_quota_stop(self):
        # the stamp is built from the real clock so the reset stays "6 days out" whenever this runs
        stamp = (datetime.now(timezone.utc) + FAR_RESET).strftime("%Y-%m-%dT%H:%M:%SZ")
        r = self.dispatch_agent("agy", "claude-opus-5-5-high", "--kind", "code",
                                mode="quota_exit0_log",
                                env={"ACP_DISPATCH_AIUSE": str(self.fake_aiuse),
                                     "QUOTA_RESET_STAMP": stamp})
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        rec = self.record()
        self.assertTrue(rec["failure"].startswith("NO-REPORT: quota (agy, claude-opus-5-5-high, "
                                                  "retry in 148h22m36s)"), rec["failure"])
        self.assertIn("acp-run exit 0", rec["failure"])
        ar = rec["auto_resume"]                       # reset 6 days out: skipped, reroute hint
        self.assertEqual((ar["state"], ar.get("far_reset")), ("skipped", True))
        # aiuse was notified exactly as the non-zero path does (family: the claude_gpt pool)
        self.assertEqual(len(self.aiuse_notes()), 1, self.aiuse_notes())
        self.assertIn(f"note-exhausted antigravity --family claude_gpt --resets-at {stamp}",
                      self.aiuse_notes()[0])
        c = run(["check", str(self.record_path())], env=self.base_env())
        self.assertEqual(c.returncode, 3, c.stdout)
        self.assertIn("reroute now:", c.stdout)

    def test_zcode_exit0_partial_report_auto_resumes_with_beijing_reset(self):
        r = self.dispatch_agent("zcode", "m1", "--kind", "code", mode="quota_zcode_exit0",
                                env={"ACP_DISPATCH_AIUSE": str(self.fake_aiuse)})
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)       # resume-scheduled
        rec = self.record()
        self.assertEqual(rec["status"], "resume-scheduled")
        self.assertTrue(rec["failure"].startswith("NO-REPORT: quota (zcode"), rec["failure"])
        ar = rec["auto_resume"]
        self.assertEqual(ar["state"], "scheduled")
        self.assertEqual(ar["reset_source"], "stderr")
        self.assertEqual(len(self.aiuse_notes()), 1, self.aiuse_notes())
        self.assertIn("--resets-at 2026-10-18T20:22:46+00:00", self.aiuse_notes()[0])

    def test_partial_checkpoint_report_gate_is_widened(self):
        """Lead MSG 1: the schedule gate fired on st == no-report only; partial must fire too."""
        self.dispatch_agent("zcode", "m1", "--kind", "code", mode="quota_zcode_exit0")
        rec = self.record()
        Path(rec["report"]).write_text("STATUS: working\nstep one done\n")  # strip the note line
        f = run(["finalize", str(self.record_path()), "--exit", "0"], env=self.base_env())
        rec = self.record()
        self.assertEqual(rec["status"], "resume-scheduled", f.stdout + f.stderr)
        self.assertEqual(rec["auto_resume"]["state"], "scheduled")   # the earlier schedule stands

    def test_a_done_report_never_auto_resumes(self):
        r = self.dispatch_agent("zcode", "m1", "--kind", "code", mode="timeout_wrapup",
                                env={"ACP_DISPATCH_AIUSE": str(self.fake_aiuse)})
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)       # done + acp-run exit 124
        rec = self.record()
        self.assertEqual(rec["status"], "done")
        self.assertIsNone(rec.get("auto_resume"))
        self.assertEqual(self.aiuse_notes(), [])

    def test_a_clean_success_is_not_flagged(self):
        r = self.dispatch_agent("zcode", "m1", "--kind", "code", mode="writes",
                                env={"ACP_DISPATCH_AIUSE": str(self.fake_aiuse)})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rec = self.record()
        self.assertEqual((rec["status"], rec.get("failure"), rec.get("auto_resume")),
                         ("done", None, None))
        self.assertEqual(self.aiuse_notes(), [])

    def test_quota_words_in_the_agents_own_work_are_not_a_refusal(self):
        """Only runtime events near the log's end count: tool output and thoughts that mention
        quota (a slice working on acp-dispatch itself) must not mark the pool exhausted."""
        self.dispatch_agent("zcode", "m1", "--kind", "code", mode="quota_words_in_work",
                            env={"ACP_DISPATCH_AIUSE": str(self.fake_aiuse)})
        rec = self.record()
        self.assertFalse(str(rec.get("failure") or "").startswith("NO-REPORT: quota"), rec.get("failure"))
        self.assertIsNone(rec.get("auto_resume"))
        self.assertEqual(self.aiuse_notes(), [])


class TestEscalation(QuotaBase):
    """Item 5: the ladder, reroute --escalate, and the check hint."""

    def setUp(self) -> None:
        super().setUp()
        mod = runpy.run_path(str(SCRIPT))
        router = mod["route_module"]()
        self._policy_path = router.POLICY_PATH
        router.reload_policy(str(self.policy))
        self.mod = mod

    def tearDown(self) -> None:
        # reload_policy mutates the shared route_agent module for the rest of this pytest
        # process; restore the repo policy or test_route_agent sees the toy one
        self.mod["route_module"]().reload_policy(str(self._policy_path))

    def test_ladder_next_kind_mapping(self):
        nxt = self.mod["escalation_next"]
        self.assertEqual(nxt("mechanical"), "bulk")
        self.assertEqual(nxt("bulk"), "code")
        self.assertEqual(nxt("code"), "judgment")
        self.assertEqual(nxt("judgment"), "frontier")
        self.assertEqual(nxt("research"), "judgment")                # explicit [escalation.next]
        self.assertIsNone(nxt("frontier"))                           # the top rung
        self.assertIsNone(nxt("github"))                             # off the ladder
        self.assertIsNone(nxt(None))

    def test_escalate_at_the_top_rung_refuses_exit_2(self):
        rec = {"name": "s1", "agent": "codex", "model": "m1", "kind": "frontier",
               "dir": str(self.repo), "out": str(self.out), "task": "out",
               "prompt": "do the thing", "report": str(self.out / "s1-report.md"),
               "done": str(self.out / "s1-report.md.done")}
        self.record_path().parent.mkdir(parents=True, exist_ok=True)
        self.record_path().write_text(json.dumps(rec))
        r = run(["reroute", str(self.record_path()), "--escalate",
                 "--acp-run", str(self.fake)], env=self.base_env())
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("no rung above", r.stderr)
        self.assertIn("route_agent.py plan", r.stderr)

    def test_escalate_and_agent_are_mutually_exclusive(self):
        self.dispatch_agent("zcode", "m1", "--kind", "code", mode="agent_metrics")
        r = run(["reroute", str(self.record_path()), "--agent", "claude", "--model", "m1",
                 "--escalate", "--acp-run", str(self.fake)], env=self.base_env())
        self.assertEqual(r.returncode, 2)

    def test_escalate_reroutes_one_rung_up_with_gates(self):
        self.dispatch_agent("zcode", "m1", "--kind", "code", mode="agent_metrics")
        c = run(["check", str(self.record_path())], env=self.base_env())
        self.assertEqual(c.returncode, 3, c.stdout)
        self.assertIn("escalate:", c.stdout)
        self.assertIn("reroute", c.stdout)
        self.assertIn("--escalate (-> judgment)", c.stdout)
        self.assertIn("--escalate (-> judgment)", c.stdout)
        r = run(["reroute", str(self.record_path()), "--escalate",
                 "--acp-run", str(self.fake)], env=self.base_env())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        new = self.record("s1-reroute-1")
        self.assertEqual((new["agent"], new["model"], new["kind"], new["effort"]),
                         ("claude", "m1", "judgment", "high"))
        self.assertEqual(new["rerouted_from"], str(self.record_path().resolve()))

    def test_partial_records_get_the_hint_too_but_quota_ones_do_not(self):
        self.dispatch_agent("zcode", "m1", "--kind", "code", mode="partial", name="p1")
        c = run(["check", str(self.record_path("p1"))], env=self.base_env())
        self.assertEqual(c.returncode, 1, c.stdout)
        self.assertIn("--escalate (-> judgment)", c.stdout)
        self.dispatch_agent("zcode", "m1", "--kind", "code", mode="quota_far", name="q1")
        c = run(["check", str(self.record_path("q1"))], env=self.base_env())
        self.assertNotIn("--escalate", c.stdout)          # quota carries its own reroute rule
        self.assertIn("reroute now:", c.stdout)


if __name__ == "__main__":
    unittest.main()
