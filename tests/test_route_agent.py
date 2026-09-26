#!/usr/bin/env python3
"""Tests for vendor routing.

The rules under test are the operator's standing orders, which exist because
they encode consequences a score cannot see — routing bulk work at clinepass
would starve Hindsight and hermes of inference.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import route_agent as r  # noqa: E402

IDLE = {
    "antigravity": {"remaining": 96.5}, "opencode-go": {"remaining": 97.0},
    "claude": {"remaining": 47.0}, "codex": {"remaining": 100.0},
    "clinepass": {"remaining": 48.0}, "copilot": {"remaining": 69.8},
    "zai": {"remaining": 70.3}, "grok": {"remaining": 45.0},
    "cursor": {"remaining": 56.0}, "devin": {"remaining": 100.0},
    # The free half of opencode-zen. Present in the fixture because it is a
    # strong default for bulk, so leaving it out let it win tests by accident.
    "opencode-zen-free": {"remaining": 100.0},
}


class TestStandingRules(unittest.TestCase):
    def test_clinepass_is_not_preferred_while_others_have_headroom(self):
        """The blanket never-bulk rule was retired 2026-08-24 in favour of a
        measured burn alert, so clinepass is now eligible — but it should
        still lose to genuinely idle pools rather than being picked first."""
        for kind in ("bulk", "mechanical"):
            self.assertNotEqual(r.route(kind, quota=IDLE).service.name, "clinepass")

    def test_clinepass_is_usable_when_it_is_the_pool_with_room(self):
        """Retired rule, deliberately inverted.

        Until 2026-08-24 a standing order forbade bulk on clinepass outright.
        That was a guess standing in for a measurement; it is now replaced by
        `agent_stats.py burn`, which projects hours-to-empty. So when clinepass
        is the pool with headroom, using it is correct."""
        tight = {name: {"remaining": 0.0} for name in IDLE}
        tight["clinepass"] = {"remaining": 100.0}
        choice = r.route("bulk", quota=tight)
        self.assertIsNotNone(choice)
        self.assertEqual(choice.service.name, "clinepass")

    def test_prepaid_tier_is_retired(self):
        for name in ("opencode-zen", "openrouter", "deepseek"):
            self.assertTrue(r.BY_NAME[name].retired)
            for kind in r.KINDS:
                c = r.route(kind, quota=IDLE)
                if c:
                    self.assertNotEqual(c.service.name, name)

    def test_judgment_only_goes_to_judgment_tier(self):
        c = r.route("judgment", quota=IDLE)
        self.assertTrue(c.service.judgment_tier)
        self.assertIn(c.service.name, {"claude", "codex"})

    def test_judgment_prefers_claude_even_when_idle_pools_are_emptier(self):
        # antigravity at 100% must not win judgment work
        q = dict(IDLE, antigravity={"remaining": 100.0}, claude={"remaining": 20.0})
        self.assertEqual(r.route("judgment", quota=q).service.name, "claude")


class TestWasteBurning(unittest.TestCase):
    def test_bulk_goes_to_idle_capacity(self):
        c = r.route("bulk", quota=IDLE)
        self.assertIn(c.service.name, {"antigravity", "opencode-go"})
        self.assertGreater(c.remaining, 90)

    def test_mechanical_prefers_the_free_tier(self):
        self.assertEqual(r.route("mechanical", quota=IDLE).service.name, "opencode-go")

    def test_headroom_shifts_bulk_away_from_a_drained_pool(self):
        drained = dict(IDLE, antigravity={"remaining": 5.0})
        self.assertNotEqual(r.route("bulk", quota=drained).service.name, "antigravity")

    def test_min_headroom_excludes_tight_services(self):
        q = dict(IDLE, antigravity={"remaining": 10.0})
        c = r.route("bulk", quota=q, min_headroom=15.0)
        self.assertNotEqual(c.service.name, "antigravity")

    def test_github_work_routes_to_copilot(self):
        self.assertEqual(r.route("github", quota=IDLE).service.name, "copilot")


class TestDegradation(unittest.TestCase):
    def test_works_with_no_quota_at_all(self):
        """A stale or missing cache must degrade to capability-only routing."""
        for kind in r.KINDS:
            c = r.route(kind, quota={})
            self.assertIsNotNone(c, f"{kind} should still route without quota")

    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValueError):
            r.route("vibes", quota=IDLE)

    def test_every_kind_is_servable(self):
        for kind in r.KINDS:
            self.assertIsNotNone(r.route(kind, quota=IDLE), kind)

    def test_alternatives_exclude_the_winner(self):
        c = r.route("bulk", quota=IDLE)
        self.assertNotIn(c.service.name, c.alternatives)


if __name__ == "__main__":
    unittest.main()


class TestDiscovery(unittest.TestCase):
    """Services are discovered, so the roster tracks reality over time."""

    def test_discovery_includes_curated_services(self):
        names = {s.name for s in r.discover(IDLE)}
        for curated in ("claude", "codex", "antigravity", "copilot"):
            self.assertIn(curated, names)

    def test_unknown_provider_becomes_routable_conservatively(self):
        found = r.discover({**IDLE, "brand-new-vendor": {"remaining": 80.0}})
        svc = next(s for s in found if s.name == "brand-new-vendor")
        self.assertEqual(set(svc.good_at), {"bulk", "mechanical"})
        self.assertFalse(svc.judgment_tier, "unprofiled services must not take judgment")

    def test_aliases_do_not_become_second_services(self):
        """`cline` is clinepass's TUI; a duplicate entry would dodge never-bulk."""
        names = {s.name for s in r.discover(IDLE)}
        for alias in ("cline", "crush", "claude-agent-teams"):
            self.assertNotIn(alias, names)
        self.assertIn("zcode", {s.cli for s in r.discover(IDLE) if s.name == "zai"})
        self.assertEqual(r.ALIASES["crush"], "clinepass")

    def test_alias_does_not_create_a_second_clinepass(self):
        """`cline` is clinepass's TUI. It must fold onto the curated service
        rather than appearing as an extra pool, or headroom gets double
        counted and constraints are evaluated twice."""
        quota = {name: {"remaining": 0.0} for name in IDLE}
        quota["clinepass"] = {"remaining": 100.0}
        quota["cline"] = {"remaining": 100.0}
        names = {s.name for s in r.discover(quota)}
        self.assertIn("clinepass", names)
        self.assertNotIn("cline", names)

    def test_measured_idle_capacity_beats_unmeasured(self):
        """Between two unprofiled pools, the one we can see is idle should win."""
        # Drain every curated pool so the comparison is strictly between two
        # discovered ones: measured-idle vs unmeasurable.
        q = {**{k: {"remaining": 0.0} for k in IDLE},
             "fresh-pool": {"remaining": 99.0}, "murky-pool": {}}
        self.assertEqual(r.route("bulk", quota=q).service.name, "fresh-pool")

    def test_hermes_only_providers_never_win_claude_side_routing(self):
        """A provider with no Claude-invocable CLI must not win here.

        Nothing sets this today — opencode-zen's free models are reachable
        from Claude via the `opencode` TUI — so this guards the mechanism
        against a future provider that genuinely is Hermes-only.
        """
        ghost = r.Service("ghost-pool", "n/a", {"bulk": 1}, "free",
                          "", access="api", hermes_only=True)
        self.assertFalse(ghost.eligible("bulk"))

    def test_opencode_zen_free_is_claude_routable(self):
        """It is the free half of opencode-zen, not a Hermes-only provider."""
        svc = r.BY_NAME["opencode-zen-free"]
        self.assertFalse(svc.hermes_only)
        self.assertTrue(svc.eligible("bulk"))

    def test_unmeasured_agents_remain_reachable_as_fallback(self):
        """All available agents should stay routable, just ranked last."""
        drained = {k: {"remaining": 0.0} for k in IDLE}
        choice = r.route("bulk", quota=drained)
        self.assertIsNotNone(choice, "roster agents should still provide a fallback")
        self.assertNotEqual(choice.service.name, "clinepass")
