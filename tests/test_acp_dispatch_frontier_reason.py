"""acp-dispatch --frontier-reason and the away frontier allowance (2026-10-27, docs/gates.md "Frontier allowance").

End to end through the fake acp-run (the claude pool: the guard's state file; the profile and gates.toml are the shipped ones),
and `frontier_judged` / `frontier_inflight` driven directly for the codex floor and the per-wave cap.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from test_acp_dispatch import SCRIPT, Base

_loader = importlib.machinery.SourceFileLoader("acp_dispatch_frontier_reason", str(SCRIPT))
_spec = importlib.util.spec_from_loader("acp_dispatch_frontier_reason", _loader)
acpd = importlib.util.module_from_spec(_spec)
_loader.exec_module(acpd)

FABLE = "claude-fable-5-1[1m]"
REASON = "the cross-file invariant needs frontier-level adjudication"


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class Gates:
    """Temp profile + guard state files and the env that points acp-dispatch at them."""

    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="acpd-gates-"))

    def profile(self, hours_left: float = 60, name: str = "away") -> str:
        now = datetime.now(UTC)
        path = self.dir / "gate-profile.json"
        path.write_text(json.dumps({"schema": 1, "profile": name, "since": _ts(now - timedelta(hours=1)),
                                    "until": _ts(now + timedelta(hours=hours_left)), "reason": "away", "set_by": "test"}))
        return str(path)

    def guard(self, **over) -> str:
        st = {"level": "ok", "reasons": [], "stale": False, "fable_left": 60.0,
              "checked_at": _ts(datetime.now(UTC) - timedelta(minutes=5)), **over}
        path = self.dir / "quota-guard.json"
        path.write_text(json.dumps({k: v for k, v in st.items() if v is not None}))
        return str(path)

    def env(self, profile: bool = True, guard: bool | dict = True, **extra: str) -> dict[str, str]:
        return {"GATE_PROFILE_STATE": self.profile() if profile else str(self.dir / "no-profile.json"),
                "CLAUDE_QUOTA_GUARD_STATE": self.guard(**(guard if isinstance(guard, dict) else {})) if guard
                else str(self.dir / "no-guard.json"), **extra}


class TestFrontierReasonFlow(Base):
    def setUp(self) -> None:
        super().setUp()
        self.g = Gates()

    def go(self, *reason: str, env: dict[str, str] | None = None, **gate_kw):
        r = self.dispatch_agent("claude", FABLE, "--kind", "frontier", "--no-model-check", *reason,
                                env=self.g.env(**gate_kw) if env is None else env)
        return r, (json.loads((self.out / "jobs/s1.json").read_text()) if (self.out / "jobs/s1.json").exists() else None)

    def test_a_reason_under_away_is_granted_recorded_and_announced(self):
        r, rec = self.go("--frontier-reason", REASON)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(rec["frontier_reason"], REASON)
        self.assertEqual((rec["frontier_judged"]["family"], rec["frontier_judged"]["profile"], rec["frontier_judged"]["per_wave"]),
                         (1, "away", 2))
        self.assertIsNone(rec["frontier_judged_note"])
        self.assertEqual(rec["role"], "advise")                       # unchanged under away
        self.assertIn(f"frontier judged use (away profile until", r.stderr)
        self.assertIn(REASON, r.stderr)

    def test_the_reason_is_what_claims_the_allowance(self):
        for reason in ((), ("--frontier-reason", ""), ("--frontier-reason", "   ")):
            shutil.rmtree(self.out, ignore_errors=True)
            r, rec = self.go(*reason)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual((rec["frontier_reason"], rec["frontier_judged"], rec["frontier_judged_note"]), (None, None, None), reason)

    def test_baseline_records_the_reason_but_grants_nothing(self):
        r, rec = self.go("--frontier-reason", REASON, profile=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(rec["frontier_reason"], REASON)
        self.assertIsNone(rec["frontier_judged"])
        self.assertIn("no away allowance is in force", rec["frontier_judged_note"])

    def test_an_expired_profile_grants_nothing(self):
        path = self.g.profile(hours_left=-1)
        r, rec = self.go("--frontier-reason", REASON, env={"GATE_PROFILE_STATE": path, "CLAUDE_QUOTA_GUARD_STATE": self.g.guard()})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIsNone(rec["frontier_judged"])
        self.assertIn("no away allowance", rec["frontier_judged_note"])

    def test_a_missing_stale_or_stopped_guard_grants_nothing(self):
        cases = [(False, "missing or unreadable"), ({"level": "tight"}, "tight"), ({"level": "critical"}, "critical"),
                 ({"checked_at": _ts(datetime.now(UTC) - timedelta(minutes=45))}, "min old"),
                 ({"fable_left": 9.0}, "frontier-1 cap has"), ({"level": "watch", "reasons": ["fable"]}, "other than the weekly"),
                 ({"stale": True}, "stale")]
        for guard, why in cases:
            shutil.rmtree(self.out, ignore_errors=True)
            r, rec = self.go("--frontier-reason", REASON, guard=guard)
            self.assertEqual(r.returncode, 0, r.stderr)          # the baseline dispatch still runs: the allowance is not a lock
            self.assertIsNone(rec["frontier_judged"], guard)
            self.assertIn(why, rec["frontier_judged_note"], guard)

    def test_reason_length_bounds_and_form_exit_2(self):
        for text, ok in (("a" * 9, False), ("a" * 10, True), ("a" * 200, True), ("a" * 201, False), ("ten chars\nsecond", False)):
            shutil.rmtree(self.out, ignore_errors=True)
            r, _ = self.go("--frontier-reason", text)
            self.assertEqual(r.returncode == 0, ok, (len(text), r.stderr))
            if not ok:
                self.assertEqual(r.returncode, 2)
                self.assertIn("--frontier-reason", r.stderr)

    def test_a_reason_on_another_kind_exits_2(self):
        r = self.dispatch_agent("claude", "opus", "--kind", "judgment", "--no-model-check", "--frontier-reason", REASON, env=self.g.env())
        self.assertEqual(r.returncode, 2)
        self.assertIn("--frontier-reason applies only", r.stderr)

    def test_a_non_frontier_model_records_the_reason_only(self):
        r = self.dispatch_agent("codex", "m1", "--kind", "frontier", "--frontier-reason", REASON, env=self.g.env())
        rec = json.loads((self.out / "jobs/s1.json").read_text())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(rec["frontier_reason"], REASON)
        self.assertIsNone(rec["frontier_judged"])
        self.assertIn("not a frontier model", rec["frontier_judged_note"])


class TestFrontierJudged(unittest.TestCase):
    """frontier_judged / frontier_inflight directly: the codex floor and the per-wave cap."""

    def setUp(self) -> None:
        self.g = Gates()
        patch = mock.patch.dict(os.environ, {k: v for k, v in self.g.env().items()})
        patch.start()
        self.addCleanup(patch.stop)
        models = mock.patch.object(acpd, "FRONTIER_MODELS", ["gpt-6-astra", "fable"])
        models.start()
        self.addCleanup(models.stop)

    def busy(self, n: int, kind: str = "frontier") -> list[Path]:
        paths = []
        for i in range(n):
            p = self.g.dir / f"busy{i}.json"
            p.write_text(json.dumps({"kind": kind, "status": "running"}))
            paths.append(p)
        return paths

    def judged(self, service="claude", model="fable", remaining=80.0, busy=()):
        return acpd.frontier_judged(REASON, service, model, remaining, list(busy))

    def test_per_wave_cap_boundary_on_the_claude_pool(self):
        self.assertIsNotNone(self.judged(busy=self.busy(1))[0])             # away: 2 per wave, one in flight, the second is allowed
        j, note = self.judged(busy=self.busy(2))
        self.assertIsNone(j)
        self.assertIn("2 frontier slice(s) already in flight on claude (cap 2 per wave)", note)
        self.assertIsNotNone(self.judged(busy=self.busy(5, kind="code"))[0])  # only frontier slices count

    def test_an_unreadable_in_flight_record_counts_toward_the_cap(self):
        bad = self.g.dir / "bad.json"
        bad.write_text("{")
        self.assertEqual(acpd.frontier_inflight([bad]), 1)
        self.assertEqual(acpd.frontier_inflight([self.g.dir / "gone.json"]), 1)

    def test_codex_floor_boundary(self):
        self.assertIsNotNone(self.judged("codex", "gpt-6-astra", 60.0)[0])
        j, note = self.judged("codex", "gpt-6-astra", 59.9)
        self.assertIsNone(j)
        self.assertIn("59.9% left (floor 60%)", note)
        self.assertIn("no reading", self.judged("codex", "gpt-6-astra", None)[1])

    def test_codex_per_wave_is_frontier2_per_wave(self):
        self.assertIsNone(self.judged("codex", "gpt-6-astra", 90.0, self.busy(1))[0])      # away leaves frontier2_per_wave at 1
        self.assertEqual(self.judged("codex", "gpt-6-astra", 90.0)[0]["family"], 2)

    def test_other_pools_and_models_are_never_granted(self):
        self.assertIn("not a frontier model", self.judged("agy", "fable")[1])
        self.assertIn("not a frontier model", self.judged("claude", "opus")[1])
        self.assertEqual(self.judged_none(), (None, None))

    def judged_none(self):
        return acpd.frontier_judged(None, "claude", "fable", 80.0, [])

    def test_a_broken_gates_file_is_never_a_grant_or_a_crash(self):
        bad = self.g.dir / "gates.toml"
        bad.write_text("[frontier\n")
        with mock.patch.dict(os.environ, {"GATES_TOML": str(bad)}):
            j, note = self.judged()
        self.assertIsNone(j)
        self.assertIn("no away allowance", note)


if __name__ == "__main__":
    unittest.main()
