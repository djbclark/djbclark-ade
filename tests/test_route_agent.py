#!/usr/bin/env python3
"""Tests for vendor routing.

The rules under test are the operator's standing orders, which exist because
they encode consequences a score cannot see — routing bulk work at clinepass
would starve Hindsight and hermes of inference.
"""
from __future__ import annotations

import contextlib
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

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


ACP_LIST = """ok claude    claude-agent-acp
ok codex     codex-acp
ok cline     cline --acp
ok agy       /Users/x/.local/share/agy-acp-server/1.3.0/agy_acp_server.par
ok fresh-acp-agent  fresh-acp-agent acp
-- devin     devin acp
-- phantom-acp  phantom-acp acp
"""


@contextlib.contextmanager
def sources(acp: str = "", installed=(), orca=(), include_orca: bool = False):
    """Pin every discovery source so a test sees only what it declares."""
    env = dict(os.environ, ROUTE_AGENT_INCLUDE_ORCA="1" if include_orca else "")
    which = lambda name, *a, **k: f"/fake/bin/{name}" if name in installed else None
    with mock.patch.object(r, "acp_list_output", return_value=acp), \
            mock.patch.object(r.shutil, "which", side_effect=which), \
            mock.patch.object(r, "orca_roster", return_value=set(orca)), \
            mock.patch.dict(os.environ, env, clear=True):
        yield


class TestDiscoverySources(unittest.TestCase):
    """Discovery reflects what this machine can dispatch, not Orca's stock list.

    Orca's roster is its stock TUI list: on 2026-10-08, 12 of 28 enabled names
    were not installed here (amp, droid, kiro, ...). acp-run's table is what
    every launcher uses, so it is the authority; the non-ACP headless TUIs
    join only while installed; Orca is opt-in and intersected with PATH."""

    def names(self):
        return {s.name for s in r.discover(IDLE)}

    def test_only_ok_rows_of_acp_run_are_routable(self):
        with sources(acp=ACP_LIST):
            names = self.names()
        self.assertIn("fresh-acp-agent", names)
        self.assertNotIn("phantom-acp", names, "`--` rows have no binary")

    def test_acp_rows_pass_through_aliases(self):
        """`cline`/`agy` are TUIs of curated services; a second entry would
        dodge the constraints that protect clinepass."""
        with sources(acp=ACP_LIST):
            names = self.names()
        for alias in ("cline", "agy"):
            self.assertNotIn(alias, names)
        self.assertIn("clinepass", names)
        self.assertIn("antigravity", names)

    def test_non_acp_headless_tuis_count_only_while_installed(self):
        self.assertEqual(r.NON_ACP_HEADLESS, {"crush", "muse", "zcode"})
        with sources(installed=()):
            self.assertNotIn("muse", self.names())
        with sources(installed=("muse",)):
            self.assertIn("muse", self.names())

    def test_headless_tuis_pass_through_aliases(self):
        """crush is clinepass's TUI, zcode is zai's: they fold, not duplicate."""
        with sources(installed=("crush", "zcode", "muse")):
            names = self.names()
        self.assertNotIn("crush", names)
        self.assertNotIn("zcode", names)
        self.assertIn("clinepass", names)
        self.assertIn("zai", names)

    def test_phantom_orca_names_are_not_routable_by_default(self):
        phantoms = {"amp", "ante", "autohand", "droid", "kiro", "trae"}
        with sources(orca=phantoms | {"claude"}, installed=phantoms):
            names = self.names()
        self.assertFalse(phantoms & names, phantoms & names)

    def test_orca_source_when_enabled_is_intersected_with_installed(self):
        with sources(orca={"aider", "amp"}, installed=("aider",), include_orca=True):
            names = self.names()
        self.assertIn("aider", names)
        self.assertNotIn("amp", names, "enabled in Orca but not installed")

    def test_acp_run_failure_degrades_to_no_acp_agents(self):
        with mock.patch.object(r.subprocess, "run", side_effect=OSError("gone")):
            self.assertEqual(r.acp_agents(), set())
        with mock.patch.object(r.subprocess, "run",
                               side_effect=r.subprocess.TimeoutExpired("acp-run", 15)):
            self.assertEqual(r.acp_agents(), set())

    def test_acp_agents_parses_live_format(self):
        with mock.patch.object(r, "acp_list_output", return_value=ACP_LIST):
            self.assertEqual(r.acp_agents(),
                             {"claude", "codex", "cline", "agy", "fresh-acp-agent"})
