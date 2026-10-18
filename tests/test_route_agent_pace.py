#!/usr/bin/env python3
"""Pace- and reset-aware scoring (operator /steps 1.6, 2026-10-18)."""
from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import route_agent as r


def _bind(remaining: float, *, pace: float | None, hours_to_reset: float,
          window_hours: float, now: datetime) -> dict:
    return {
        "remaining": remaining,
        "pace_ratio": pace,
        "resets_at": (now + timedelta(hours=hours_to_reset)).isoformat(),
        "window_minutes": int(window_hours * 60),
    }


class TestExpectedWaste(unittest.TestCase):
    def test_formula_and_missing_fields(self):
        now = datetime.now(UTC)
        # r=80, W=100h, t=50h, p=1 → projected 50, waste 30
        w = r.expected_waste(80.0, 1.0, (now + timedelta(hours=50)).isoformat(),
                             100 * 60, now=now)
        self.assertAlmostEqual(w, 30.0, places=5)
        # missing pace → p=1
        w2 = r.expected_waste(80.0, None, (now + timedelta(hours=50)).isoformat(),
                              100 * 60, now=now)
        self.assertAlmostEqual(w2, 30.0, places=5)
        self.assertIsNone(r.expected_waste(80.0, 1.0, None, 100 * 60, now=now))
        self.assertIsNone(r.expected_waste(80.0, 1.0, now.isoformat(), None, now=now))


class TestPaceAndBurnFirstScoring(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(UTC)
        self.a = r.Service("pace-a", "pace-a", {"bulk": 1, "judgment": 1},
                           "subscription", judgment_tier=True)
        self.b = r.Service("pace-b", "pace-b", {"bulk": 1, "judgment": 1},
                           "subscription", judgment_tier=True)

    def _route(self, kind: str, quota: dict):
        services = (self.a, self.b)
        with mock.patch.object(r, "SERVICES", services), \
             mock.patch.object(r, "BY_NAME", {s.name: s for s in services}), \
             mock.patch.object(r, "discover", return_value=list(services)):
            return r.route(kind, quota=quota)

    def test_triple_pace_loses_to_equal_rank_one_x(self):
        # Same remaining; neither triggers burn_first waste; only pace differs.
        q = {
            "pace-a": _bind(50.0, pace=3.0, hours_to_reset=5,
                            window_hours=100, now=self.now),
            "pace-b": _bind(50.0, pace=1.0, hours_to_reset=5,
                            window_hours=100, now=self.now),
        }
        # waste ≈ 50 - 3*(100/100)*5 = 35 for a; 45 for b — both ≥ 30, so both
        # get the burn bonus. Pace penalty alone should decide.
        c = self._route("bulk", q)
        self.assertEqual(c.service.name, "pace-b")
        # Winner is the 1× pool; the 3× pool's why names the pace penalty.
        with mock.patch.object(r, "SERVICES", (self.a,)), \
             mock.patch.object(r, "BY_NAME", {"pace-a": self.a}), \
             mock.patch.object(r, "discover", return_value=[self.a]):
            alone = r.route("bulk", quota=q)
        self.assertIn("pace 3.0", alone.why)

    def test_waste_bonus_without_static_burn_first(self):
        # pace-a: high waste, burn_first=false (default). pace-b: no waste info.
        self.assertFalse(self.a.burn_first)
        q = {
            "pace-a": _bind(80.0, pace=0.2, hours_to_reset=10,
                            window_hours=168, now=self.now),
            "pace-b": {"remaining": 80.0},  # unknown waste → no computed bonus
        }
        # waste ≈ 80 - 0.2*(100/168)*10 ≈ 78.8 ≥ 30
        c = self._route("bulk", q)
        self.assertEqual(c.service.name, "pace-a")
        self.assertIn("would waste", c.why)

    def test_reset_present_pace_missing_uses_p_one(self):
        # pace None → p=1; waste = 80 - 1*(100/100)*20 = 60 ≥ waste_min.
        q = {
            "pace-a": _bind(80.0, pace=None, hours_to_reset=20,
                            window_hours=100, now=self.now),
            "pace-b": {"remaining": 80.0},
        }
        c = self._route("bulk", q)
        self.assertEqual(c.service.name, "pace-a")
        self.assertIn("would waste", c.why)

    def test_reserve_floor_skips_computed_burn_first_bonus(self):
        a = r.Service("pace-a", "pace-a", {"realtime-web": 1}, "subscription",
                      reserve_floor=60.0)
        b = r.Service("pace-b", "pace-b", {"realtime-web": 1}, "subscription")
        services = (a, b)
        q = {
            "pace-a": _bind(80.0, pace=0.1, hours_to_reset=10,
                            window_hours=168, now=self.now),
            "pace-b": _bind(80.0, pace=0.1, hours_to_reset=10,
                            window_hours=168, now=self.now),
        }
        with mock.patch.object(r, "SERVICES", services), \
             mock.patch.object(r, "BY_NAME", {s.name: s for s in services}), \
             mock.patch.object(r, "discover", return_value=list(services)):
            c = r.route("realtime-web", quota=q)
        self.assertEqual(c.service.name, "pace-b")
        self.assertIn("would waste", c.why)
        with mock.patch.object(r, "SERVICES", (a,)), \
             mock.patch.object(r, "BY_NAME", {"pace-a": a}), \
             mock.patch.object(r, "discover", return_value=[a]):
            alone = r.route("realtime-web", quota=q)
        self.assertNotIn("would waste", alone.why)

    def test_missing_pace_or_reset_falls_back_to_static_burn_first(self):
        a = r.Service("pace-a", "pace-a", {"bulk": 1}, "subscription",
                      burn_first=True)
        b = r.Service("pace-b", "pace-b", {"bulk": 1}, "subscription",
                      burn_first=False)
        services = (a, b)
        # No pace/reset → waste unknown; static burn_first + remaining ≥ min.
        q = {
            "pace-a": {"remaining": 90.0},
            "pace-b": {"remaining": 90.0},
        }
        with mock.patch.object(r, "SERVICES", services), \
             mock.patch.object(r, "BY_NAME", {s.name: s for s in services}), \
             mock.patch.object(r, "discover", return_value=list(services)):
            c = r.route("bulk", quota=q)
        self.assertEqual(c.service.name, "pace-a")

    def test_judgment_gets_half_pace_penalty(self):
        q = {
            "pace-a": _bind(50.0, pace=3.0, hours_to_reset=5,
                            window_hours=100, now=self.now),
            "pace-b": _bind(50.0, pace=1.0, hours_to_reset=5,
                            window_hours=100, now=self.now),
        }
        c = self._route("judgment", q)
        self.assertEqual(c.service.name, "pace-b")
        half = r.PACE_PENALTY * r.PACE_PENALTY_JUDGMENT_FACTOR
        with mock.patch.object(r, "SERVICES", (self.a,)), \
             mock.patch.object(r, "BY_NAME", {"pace-a": self.a}), \
             mock.patch.object(r, "discover", return_value=[self.a]):
            alone = r.route("judgment", quota=q)
        self.assertIn(f"penalty {half:g}", alone.why)
        # Full penalty on bulk is twice the judgment half.
        with mock.patch.object(r, "SERVICES", (self.a,)), \
             mock.patch.object(r, "BY_NAME", {"pace-a": self.a}), \
             mock.patch.object(r, "discover", return_value=[self.a]):
            bulk_alone = r.route("bulk", quota=q)
        self.assertIn(f"penalty {r.PACE_PENALTY:g}", bulk_alone.why)


class TestLoadSnapshotBindFields(unittest.TestCase):
    def test_binding_window_keeps_pace_and_reset(self):
        now = datetime.now(UTC)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "latest.json"
            path.write_text(r.json.dumps({
                "collected_at": now.isoformat(),
                "snapshot": {"accounts": [{
                    "provider": "codex",
                    "billing_kind": "subscription_window",
                    "windows": [
                        {"label": "5-hour", "remaining_percent": 10.0,
                         "headroom_percent": 10.0, "pace_ratio": 3.2,
                         "resets_at": (now + timedelta(hours=2)).isoformat(),
                         "window_minutes": 300, "state": "ok"},
                        {"label": "weekly", "remaining_percent": 82.0,
                         "headroom_percent": 82.0, "pace_ratio": 0.5,
                         "resets_at": (now + timedelta(days=4)).isoformat(),
                         "window_minutes": 10080, "state": "ok"},
                    ],
                }]},
            }))
            with mock.patch.object(r, "SNAPSHOT", path):
                q, _ = r.load_snapshot()
        self.assertEqual(q["codex"]["remaining"], 10.0)
        self.assertEqual(q["codex"]["pace_ratio"], 3.2)
        self.assertEqual(q["codex"]["window_minutes"], 300)


if __name__ == "__main__":
    unittest.main()
