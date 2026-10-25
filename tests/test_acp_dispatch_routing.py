#!/usr/bin/env python3
"""acp-dispatch --kind / eligibility / frontier advisor / machine-wide estimate / reservation
(operator 2026-10-18 via /steps)."""
from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path
from typing import override

from test_acp_dispatch import Base, run


def _pid_start() -> str:
    return subprocess.run(
        ["ps", "-o", "lstart=", "-p", str(os.getpid())], check=False,
        capture_output=True, text=True).stdout.strip()


class RoutingDispatch(Base):
    @override
    def setUp(self) -> None:
        super().setUp()
        # git repo so advisor tree snaps work
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "t@example.com"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "t"],
                       check=True, capture_output=True)
        (self.repo / "README").write_text("x\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "README"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", "i"],
                       check=True, capture_output=True)

    def snap_codex(self, remaining: float) -> dict[str, str]:
        snap = self.tmp / "latest.json"
        snap.write_text(json.dumps({
            "collected_at": "2099-01-01T00:00:00+00:00",
            "snapshot": {"accounts": [{"provider": "codex", "windows": [
                {"label": "5h", "remaining_percent": remaining}]}]},
        }))
        return {"AIUSE_SNAPSHOT": str(snap)}

    def busy_row(self, **extra: object) -> dict:
        row: dict = {"name": "busy", "agent": "codex", "model": "m1", "service": "codex",
                     "status": "running", "pid": os.getpid(), "pid_start": _pid_start(),
                     "started": 0, "estimated_usage_pct": 60.0}
        row.update(extra)
        return row


class TestKindRequired(RoutingDispatch):
    def test_missing_kind_exits_2(self):
        r = run(["codex", "--model", "m1", "--name", "x", "-p", "hi", "-C", str(self.repo),
                 "--out", str(self.out), "--acp-run", str(self.fake), "--no-model-check",
                 "--no-preflight"], env=self.base_env())
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("--kind is required", r.stderr)
        self.assertIn("route_agent.py plan", r.stderr)


class TestEligibility(RoutingDispatch):
    def test_claude_bulk_refused_names_eligible(self):
        # claude codes since 2026-10-18 (operator); bulk is still not its kind
        r = self.dispatch_agent("claude", "m1", "--kind", "bulk", "--no-model-check", "--no-preflight")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("not eligible for --kind bulk", r.stderr)
        self.assertIn("eligible:", r.stderr)
        self.assertIn("route-override", r.stderr)

    def test_route_override_passes_eligibility(self):
        r = self.dispatch_agent(
            "claude", "m1", "--kind", "bulk", "--no-model-check", "--no-preflight",
            env={"ACP_OPERATOR_APPROVED": "route-override"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.record()["kind"], "bulk")


class TestCodexEverydayGate(RoutingDispatch):
    """Operator 2026-10-25: codex takes non-frontier kinds while its quota is plentiful
    ([routing].plenty_min), never astra; below it, frontier-only again."""

    def code(self, model: str, remaining: float | None, *extra: str, kind: str = "code"):
        env = self.snap_codex(remaining) if remaining is not None else {}
        return self.dispatch_agent("codex", model, "--kind", kind, "--no-model-check", "--no-preflight",
                                   *extra, env=env)

    def test_eligible_with_plenty_of_quota(self):
        r = self.code("gpt-6.1-sol", 90.0)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.record()["kind"], "code")

    def test_refused_below_plenty_min_naming_the_reason_and_the_pools_that_remain(self):
        r = self.code("gpt-6.1-sol", 40.0)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("codex is not eligible for --kind code", r.stderr)
        self.assertIn("at least 50% left", r.stderr)
        self.assertIn("40% left", r.stderr)
        self.assertIn("route-override", r.stderr)
        listed = r.stderr.split("eligible:", 1)[1].split(";", 1)[0]
        self.assertNotIn("codex", listed)
        self.assertIn("zai", listed)

    def test_the_threshold_is_inclusive_and_the_tightest_window_binds(self):
        self.assertEqual(self.code("gpt-6.1-sol", 50.0).returncode, 0)
        snap = self.tmp / "tight.json"
        snap.write_text(json.dumps({"collected_at": "2099-01-01T00:00:00+00:00", "snapshot": {"accounts": [{
            "provider": "codex", "windows": [{"label": "5h", "remaining_percent": 95.0},
                                             {"label": "weekly", "remaining_percent": 30.0}]}]}}))
        r = self.dispatch_agent("codex", "gpt-6.1-sol", "--kind", "code", "--no-model-check",
                                "--no-preflight", name="s2", env={"AIUSE_SNAPSHOT": str(snap)})
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("30% left", r.stderr)

    def test_no_reading_fails_closed(self):
        r = self.code("gpt-6.1-sol", None)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("no fresh reading", r.stderr)

    def test_judgment_is_eligible_with_plenty_and_refused_below_it(self):
        """Operator 2026-10-25: a Codex adversary round was refused as not eligible for judgment."""
        ok = self.code("gpt-6.1-sol", 90.0, kind="judgment")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(self.record()["kind"], "judgment")
        low = self.code("gpt-6.1-sol", 40.0, kind="judgment")
        self.assertEqual(low.returncode, 2, low.stderr)
        self.assertIn("codex is not eligible for --kind judgment", low.stderr)
        self.assertIn("40% left", low.stderr)

    def test_judgment_runs_the_everyday_model_never_astra(self):
        r = self.code("gpt-6-astra", 100.0, kind="judgment")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("frontier model", r.stderr)

    def test_astra_stays_frontier_only_however_plentiful_the_quota(self):
        r = self.code("gpt-6-astra", 100.0)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("frontier model", r.stderr)

    def test_frontier_needs_no_plenty(self):
        r = self.code("gpt-6-astra", 30.0, "--min-headroom", "0", "--est-pct", "5", kind="frontier")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_route_override_skips_the_headroom_gate(self):
        r = self.dispatch_agent("codex", "gpt-6.1-sol", "--kind", "code", "--no-model-check", "--no-preflight",
                                env={**self.snap_codex(40.0), "ACP_OPERATOR_APPROVED": "route-override"})
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_an_everyday_slice_is_not_floored_at_the_astra_estimate(self):
        """dispatch.estimate_floor: `codex:frontier` (60) is for astra; the everyday models get
        `codex` (10), else a brief-size default would reserve 60% of the window per slice."""
        everyday = json.loads(self.code("gpt-6.1-sol", 100.0, "--dry-run", "--json").stdout)
        frontier = json.loads(self.code("gpt-6-astra", 100.0, "--dry-run", "--json",
                                        "--min-headroom", "0", kind="frontier").stdout)
        self.assertEqual(everyday["estimated_usage_pct"], 10.0)
        self.assertEqual(frontier["estimated_usage_pct"], 60.0)


class TestFrontierModelGate(RoutingDispatch):
    def test_astra_with_code_refused_even_with_route_override(self):
        r = self.dispatch_agent(
            "codex", "gpt-6-astra", "--kind", "code", "--no-model-check", "--no-preflight",
            env={"ACP_OPERATOR_APPROVED": "route-override"})
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("frontier model", r.stderr)
        self.assertIn("--kind frontier", r.stderr)


class TestAdvisorRole(RoutingDispatch):
    def test_frontier_defaults_to_advise(self):
        r = self.dispatch_model("m1", "--kind", "frontier", "--no-model-check", "--no-preflight")
        self.assertEqual(r.returncode, 0, r.stderr)
        brief = (self.out / "s1-brief.md").read_text()
        self.assertIn("## Advisor role", brief)
        rec = self.record()
        self.assertEqual(rec["role"], "advise")
        self.assertIsNotNone(rec.get("advisor_tree_before"))

    def test_frontier_exec_needs_approval(self):
        r = self.dispatch_model("m1", "--kind", "frontier", "--role", "exec",
                                "--no-model-check", "--no-preflight")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("frontier-exec", r.stderr)
        r = self.dispatch_model(
            "m1", "--kind", "frontier", "--role", "exec", "--no-model-check", "--no-preflight",
            name="s2", env={"ACP_OPERATOR_APPROVED": "frontier-exec"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.record("s2")["role"], "exec")
        self.assertNotIn("## Advisor role", (self.out / "s2-brief.md").read_text())

    def test_advisor_edited_tree_flagged(self):
        # Fake that touches the working tree after the before-snap.
        fake = self.tmp / "acp-run-edit"
        fake.write_text("""#!/bin/bash
for x in "$@"; do [ "$x" = --info ] && {
  echo '{"agent": {"name": "fake"}, "config_options": [{"id": "model", "category": "model",'
  echo ' "options": [{"value": "m1", "name": "Model One"}]}]}'
  exit 0
}; done
cwd=""; brief=""; log=""
while [ $# -gt 0 ]; do case "$1" in
  -C) cwd="$2"; shift;; -f) brief="$2"; shift;; --log) log="$2"; shift;; esac; shift
done
printf '%s\\n' '{"kind":"initialize","data":{"agentCapabilities":{"loadSession":true}}}' > "$log"
printf '%s\\n' '{"kind":"new_session","data":{"sessionId":"fake-session"}}' >> "$log"
report=$(ggrep -o 'deliverable to `[^`]*`' "$brief" | ghead -1 | gsed 's/.*`\\(.*\\)`/\\1/')
echo touched > "$cwd/edited-by-advisor"
printf 'STATUS: working\\nfound it\\nDONE\\n' > "$report"
echo "written: $report"
exit 0
""")
        fake.chmod(0o755)
        env = self.base_env()
        r = run(["codex", "--model", "m1", "--kind", "frontier", "--name", "s1",
                 "-p", "review", "-C", str(self.repo), "--out", str(self.out),
                 "--acp-run", str(fake), "--no-model-check", "--no-preflight"], env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = self.record()
        self.assertTrue(rec.get("advisor_edited"), rec)
        self.assertEqual(rec.get("advisor_changed_paths"), ["edited-by-advisor"], rec)
        chk = run(["check", str(self.out / "jobs" / "s1.json")], env=env)
        self.assertIn("ADVISOR EDITED THE TREE: edited-by-advisor", chk.stdout)

    def test_lead_commit_during_a_read_only_advise_is_not_an_edit(self):
        # Only HEAD moves (the lead commits in the same checkout); the tree shape is unchanged.
        fake = self.tmp / "acp-run-lead-commit"
        fake.write_text("""#!/bin/bash
for x in "$@"; do [ "$x" = --info ] && {
  echo '{"agent": {"name": "fake"}, "config_options": [{"id": "model", "category": "model",'
  echo ' "options": [{"value": "m1", "name": "Model One"}]}]}'
  exit 0
}; done
cwd=""; brief=""; log=""
while [ $# -gt 0 ]; do case "$1" in
  -C) cwd="$2"; shift;; -f) brief="$2"; shift;; --log) log="$2"; shift;; esac; shift
done
printf '%s\\n' '{"kind":"initialize","data":{"agentCapabilities":{"loadSession":true}}}' > "$log"
printf '%s\\n' '{"kind":"new_session","data":{"sessionId":"fake-session"}}' >> "$log"
report=$(ggrep -o 'deliverable to `[^`]*`' "$brief" | ghead -1 | gsed 's/.*`\\(.*\\)`/\\1/')
git -C "$cwd" -c user.email=t@t -c user.name=t commit -q --allow-empty -m "lead commit"
printf 'STATUS: working\\nfound it\\nDONE\\n' > "$report"
echo "written: $report"
exit 0
""")
        fake.chmod(0o755)
        env = self.base_env()
        for name, perm, edited in (("s1", "read-only", False), ("s2", "all", True)):
            r = run(["codex", "--model", "m1", "--kind", "frontier", "--name", name,
                     "--perm", perm, "-p", "review", "-C", str(self.repo), "--out", str(self.out),
                     "--acp-run", str(fake), "--no-model-check", "--no-preflight"], env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            rec = self.record(name)
            self.assertEqual(bool(rec.get("advisor_edited")), edited, rec)
            self.assertEqual(len(rec.get("head_moved_during_run") or []), 2, rec)
            chk = run(["check", str(self.out / "jobs" / f"{name}.json")], env=env)
            if edited:
                self.assertIn("ADVISOR EDITED THE TREE", chk.stdout)
            else:
                self.assertNotIn("ADVISOR EDITED", chk.stdout)
                self.assertIn("HEAD moved during the run", chk.stdout)


class TestMachineHistory(RoutingDispatch):
    def test_machine_wide_history_drives_estimate(self):
        other = self.tmp / "state" / "other-task" / "jobs"
        other.mkdir(parents=True)
        for i, pct in enumerate((50.0, 55.0, 60.0)):
            (other / f"h{i}.json").write_text(json.dumps({
                "agent": "codex", "model": "gpt-6-astra", "measured_usage_pct": pct,
                "status": "done"}))
        r = self.dispatch_agent(
            "codex", "gpt-6-astra", "--kind", "frontier", "--no-model-check", "--no-preflight",
            "--min-headroom", "0", env=self.snap_codex(90.0))
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = self.record()
        self.assertEqual(rec["estimated_usage_pct"], 55.0)
        self.assertIn("machine", rec["estimate_source"])


class TestReservation(RoutingDispatch):
    def test_inflight_reservation_refuses_second_codex(self):
        jobs = self.tmp / "state" / "other-task" / "jobs"
        jobs.mkdir(parents=True)
        # m1 is not a frontier model, so its estimate floor is codex's plain 10.0 (not the frontier 60.0):
        # reserve 65 of the 70 left so that 5 is under it
        (jobs / "busy.json").write_text(json.dumps(self.busy_row(estimated_usage_pct=65.0)))
        r = self.dispatch(env=self.snap_codex(70.0))
        self.assertEqual(r.returncode, 5, (r.stdout, r.stderr))
        self.assertIn("class=inflight", r.stdout)
        self.assertIn("busy", r.stdout)

    def test_resume_skips_reservation(self):
        # Land a finished slice, plant a competing in-flight estimate, resume the finished one.
        self.assertEqual(self.dispatch("--no-preflight").returncode, 0)
        jobs = self.tmp / "state" / "other-task" / "jobs"
        jobs.mkdir(parents=True)
        (jobs / "busy.json").write_text(json.dumps(self.busy_row()))
        env = {**self.base_env(), **self.snap_codex(70.0)}
        r = run(["resume", str(self.out / "jobs" / "s1.json"), "--timeout", "0"], env=env)
        self.assertEqual(r.returncode, 0, r.stderr)


class TestLegacyRecord(RoutingDispatch):
    def test_resume_without_kind_still_works(self):
        self.assertEqual(self.dispatch("--no-preflight").returncode, 0)
        path = self.out / "jobs" / "s1.json"
        rec = json.loads(path.read_text())
        rec.pop("kind", None)
        rec.pop("service", None)
        rec.pop("role", None)
        path.write_text(json.dumps(rec))
        r = run(["resume", str(path), "--timeout", "0"], env=self.base_env())
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_reroute_without_kind_still_works(self):
        self.assertEqual(self.dispatch("--no-preflight", mode="quota_partial").returncode, 1)
        path = self.out / "jobs" / "s1.json"
        rec = json.loads(path.read_text())
        rec.pop("kind", None)
        path.write_text(json.dumps(rec))
        r = run(["reroute", str(path), "--agent", "codex", "--model", "m1",
                 "--acp-run", str(self.fake), "--no-preflight"], env=self.base_env())
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_reroute_code_to_astra_exits_2(self):
        # F1: reroute runs the frontier-model gate; a code record cannot become astra.
        self.assertEqual(self.dispatch_agent(
            "codex", "m1", "--kind", "code", "--no-preflight",
            env={"ACP_OPERATOR_APPROVED": "route-override"}).returncode, 0)
        path = self.out / "jobs" / "s1.json"
        r = run(["reroute", str(path), "--agent", "codex", "--model", "gpt-6-astra",
                 "--acp-run", str(self.fake), "--no-preflight"], env=self.base_env())
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("frontier model", r.stderr)


class TestWindowReservation(RoutingDispatch):
    def test_scalar_only_inflight_reserves_every_window_label(self):
        # F3: a busy row with no estimated_usage_windows still reserves its scalar.
        jobs = self.tmp / "state" / "other-task" / "jobs"
        jobs.mkdir(parents=True)
        (jobs / "busy.json").write_text(json.dumps(self.busy_row(
            model="gpt-6-astra", estimated_usage_pct=60.0)))
        # Plant per-window history so the new dispatch uses the window path.
        for i, pct in enumerate((50.0, 55.0, 70.0)):
            (jobs / f"h{i}.json").write_text(json.dumps({
                "agent": "codex", "model": "gpt-6-astra", "status": "done",
                "measured_usage_pct": 12.0,
                "measured_usage_windows": {"5h": pct}}))
        snap = self.tmp / "latest.json"
        snap.write_text(json.dumps({
            "collected_at": "2099-01-01T00:00:00+00:00",
            "snapshot": {"accounts": [{"provider": "codex", "windows": [
                {"label": "5h", "remaining_percent": 100.0}]}]},
        }))
        r = self.dispatch_agent(
            "codex", "gpt-6-astra", "--kind", "frontier", "--no-model-check", "--no-preflight",
            "--min-headroom", "0", "--dry-run", "--json",
            env={"AIUSE_SNAPSHOT": str(snap)})
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = json.loads(r.stdout)
        self.assertEqual(rec["reserved_usage_windows"].get("5h"), 60.0)
        self.assertIn("would_refuse_class", rec)  # 55 + 60 > 100 → reserved fit fails
        self.assertEqual(rec["would_refuse_class"], "inflight")


class TestInflightByAgent(RoutingDispatch):
    def test_unknown_service_cap_matches_by_agent(self):
        # F7: ACP_DISPATCH_INFLIGHT=crush=1 with no aiuse service map.
        jobs = self.tmp / "state" / "other-task" / "jobs"
        jobs.mkdir(parents=True)
        (jobs / "busy.json").write_text(json.dumps(self.busy_row(
            agent="crush", model="m1", service=None, estimated_usage_pct=1.0)))
        r = self.dispatch_agent(
            "crush", "m1", "--kind", "bulk", "--no-model-check", "--no-preflight",
            "--min-headroom", "0",
            env={"ACP_DISPATCH_INFLIGHT": "crush=1"})
        self.assertEqual(r.returncode, 5, (r.stdout, r.stderr))
        self.assertIn("class=inflight", r.stdout)


class TestFloorWithShortHistory(RoutingDispatch):
    def test_one_slice_history_still_applies_floor(self):
        # F10: n < 3 → max(est, floor). claude floor is 8. Use a non-placeholder model
        # so machine-wide history is not skipped (PLACEHOLDER_MODELS includes m1).
        other = self.tmp / "state" / "other-task" / "jobs"
        other.mkdir(parents=True)
        (other / "h0.json").write_text(json.dumps({
            "agent": "claude", "model": "opus", "measured_usage_pct": 0.0, "status": "done"}))
        r = self.dispatch_agent(
            "claude", "opus", "--kind", "judgment", "--no-model-check", "--no-preflight",
            "--min-headroom", "0", "--dry-run", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = json.loads(r.stdout)
        self.assertGreaterEqual(rec["estimated_usage_pct"], 8.0)
        self.assertIn("history", rec["estimate_source"])


if __name__ == "__main__":
    unittest.main()
