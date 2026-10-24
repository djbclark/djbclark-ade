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

from test_acp_dispatch import SCRIPT, Base, run

# agy's weekly cap, 6 days out; the fake's "Resets in" text and the stamp both derive from it
FAR_RESET = timedelta(hours=148, minutes=22, seconds=36)

EXTRA_MODES = textwrap.dedent("""\
      quota_far)  # agy's weekly cap as seen 2026-10-18: reset days out
              printf 'STATUS: working\\n' > "$report"
              echo "acp-run: FAILED quota: quota exhausted. Refreshes in 6 days and 4 hours" >&2
              echo "acp-run: agent=agy stop=error secs=50.0 tools=5 fail=quota" >&2
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
frontier_per_wave = 1
fable_min_left = 10.0
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

    def test_short_reset_still_schedules_with_a_wake(self):
        r = self.dispatch_agent("zcode", "m1", "--kind", "code", mode="quota_reply")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)       # resume-scheduled
        rec = self.record()
        ar = rec["auto_resume"]
        self.assertEqual(ar["state"], "scheduled")
        self.assertNotIn("far_reset", ar)
        # the wake: 2 min before not_before, pmset's quoted MM/dd/yy HH:mm:ss (man pmset)
        want = self.mod_wake_stamp(ar["not_before"])
        self.assertEqual(ar["wake"], f"scheduled {want}")
        self.assertEqual(self.pmset_calls(), [f"pmset schedule wake {want}"])
        # routed through sudo -k -n: a cached ticket must not stand in for the rule (2026-10-18)
        self.assertIn("sudo -k -n ", self.sudo_log.read_text())
        self.assertIn("schedule wake", self.sudo_log.read_text())

    @staticmethod
    def mod_wake_stamp(not_before: float) -> str:
        return (datetime.fromtimestamp(not_before) - timedelta(seconds=120)).strftime(
            "%m/%d/%y %H:%M:%S")

    def test_wake_unavailable_is_recorded_not_fatal(self):
        r = self.dispatch_agent("zcode", "m1", "--kind", "code", mode="quota_reply",
                                env={"SUDO_FAIL": "1"})
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        ar = self.record()["auto_resume"]
        self.assertEqual(ar["state"], "scheduled")                    # the resume stands
        self.assertTrue(ar["wake"].startswith("unavailable: "), ar["wake"])
        self.assertIn("password is required", ar["wake"])

    def test_reroute_cancels_the_wake_with_the_same_time(self):
        self.dispatch_agent("zcode", "m1", "--kind", "code", mode="quota_reply")
        want = self.mod_wake_stamp(self.record()["auto_resume"]["not_before"])
        rr = run(["reroute", str(self.record_path()), "--agent", "claude", "--model", "m1",
                 "--acp-run", str(self.fake)], env=self.base_env())
        self.assertEqual(rr.returncode, 0, rr.stdout + rr.stderr)
        self.assertEqual(self.record()["auto_resume"]["state"], "cancelled")
        self.assertEqual(self.pmset_calls(),
                         [f"pmset schedule wake {want}", f"pmset schedule cancel wake {want}"])


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
