#!/usr/bin/env python3
"""Tests for vendor routing.

The rules under test are the operator's standing orders, which exist because
they encode consequences a score cannot see — routing bulk work at clinepass
would starve Hindsight and hermes of inference.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import route_agent as r

IDLE = {
    "antigravity": {"remaining": 96.5}, "opencode-go": {"remaining": 97.0},
    "claude": {"remaining": 47.0}, "codex": {"remaining": 100.0},
    "clinepass": {"remaining": 48.0}, "copilot": {"remaining": 69.8},
    "zai": {"remaining": 70.3}, "grok": {"remaining": 65.0},
    "cursor": {"remaining": 56.0}, "devin": {"remaining": 100.0},
    # The free half of opencode-zen. Present in the fixture because it is a
    # strong default for bulk, so leaving it out let it win tests by accident.
    "opencode-zen-free": {"remaining": 100.0},
    # 2026-10-15 rows: Cursor's Auto pool, the free SIPB models via crush and
    # the aiuse-disabled Alibaba plan; present so "drain every pool" fixtures
    # drain them too instead of leaving them unmeasured and routable.
    "cursor-auto": {"remaining": 56.0}, "crush": {"remaining": 100.0},
    "alibaba": {"remaining": 50.0}, "cursor-cloud": {"remaining": 56.0},
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
        self.assertEqual(c.service.name, "claude")

    def test_judgment_reaches_codex_only_when_claude_is_tight_and_codex_is_plentiful(self):
        # antigravity at 100% must not win judgment work. Since 2026-10-25 codex's judgment
        # row (rank 3, gpt-6.1-sol at high) is eligible while its quota is plentiful, but it
        # ranks behind claude, so it only wins once claude is out of room.
        q = dict(IDLE, antigravity={"remaining": 100.0}, claude={"remaining": 20.0})
        self.assertEqual(r.route("judgment", quota=q).service.name, "claude")
        q = dict(IDLE, claude={"remaining": 5.0})
        c = r.route("judgment", quota=q)
        self.assertEqual((c.service.name, c.model), ("codex", "gpt-6.1-sol --effort high"))
        q = dict(IDLE, claude={"remaining": 5.0}, codex={"remaining": r.PLENTY_MIN - 1})
        self.assertIsNone(r.route("judgment", quota=q))


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

    def test_default_headroom_gate_excludes_below_fifteen(self):
        q = dict(IDLE, antigravity={"remaining": 14.9})
        self.assertNotEqual(r.route("bulk", quota=q).service.name, "antigravity")

    def test_default_headroom_excludes_note_exhausted_pool(self):
        q = dict(IDLE, codex={"remaining": 0.0, "windows": {"weekly": 0.0}})
        self.assertNotEqual(r.route("code", quota=q).service.name, "codex")

    def test_github_work_routes_to_copilot(self):
        self.assertEqual(r.route("github", quota=IDLE).service.name, "copilot")


class TestDegradation(unittest.TestCase):
    def test_works_with_no_quota_at_all(self):
        """A stale or missing cache must degrade to capability-only routing,
        except for the reserve pool (copilot), which fails closed without a fresh
        reading (review 2026-10-15): github stays queued. realtime-web routes
        again since grok stopped being a reserve (2026-10-18)."""
        for kind in r.KINDS:
            c = r.route(kind, quota={})
            if kind == "github":
                self.assertIsNone(c, f"{kind} is reserve-only and must not route unmeasured")
            else:
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
        for alias in ("cline", "claude-agent-teams"):
            self.assertNotIn(alias, names)
        self.assertTrue(all(s.cli.startswith("zcode") and s.acp_agent == "zcode"
                            for s in r.discover(IDLE) if s.name == "zai"))
        self.assertEqual(r.ALIASES["cline"], "clinepass")

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

    @mock.patch.dict(os.environ, {"ROUTE_AGENT_OMP_READY": "0"})   # omp-ready: TestOmpReadyRoster
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
        with sources(acp=ACP_LIST):                       # not whatever agents the host has installed
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
        self.assertEqual(r.NON_ACP_HEADLESS, {"muse"})
        with sources(installed=()):
            self.assertNotIn("muse", self.names())
        with sources(installed=("muse",)):
            self.assertIn("muse", self.names())

    def test_headless_tuis_pass_through_aliases(self):
        """zcode is zai's TUI: it folds onto zai, not a duplicate; muse has none."""
        with sources(installed=("zcode", "muse")):
            names = self.names()
        self.assertNotIn("zcode", names)
        self.assertIn("zai", names)
        self.assertIn("muse", names)

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


class TestAgyClaudeGptPool(unittest.TestCase):
    """agy's Claude/GPT window is its own service (operator, 2026-10-10)."""

    def snapshot(self, tmp, claude_gpt_left, gemini_left=100.0):
        path = Path(tmp) / "latest.json"
        path.write_text(r.json.dumps({"snapshot": {"accounts": [{
            "provider": "antigravity", "billing_kind": "subscription_window",
            "windows": [
                {"label": "Gemini 5-hour", "remaining_percent": gemini_left,
                 "pool_family": "gemini"},
                {"label": "Claude/GPT weekly", "remaining_percent": claude_gpt_left,
                 "pool_family": "claude_gpt"},
            ]}]}, "collected_at": r.datetime.now(r.UTC).isoformat()}))
        return path

    def load(self, **kw):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(r, "SNAPSHOT", self.snapshot(tmp, **kw)):
            return r.load_snapshot()[0]

    def test_pools_are_split_so_neither_drags_the_other(self):
        q = self.load(claude_gpt_left=3.0)
        self.assertEqual(q["antigravity"]["remaining"], 100.0)
        self.assertEqual(q["antigravity-claude"]["remaining"], 3.0)

    def test_code_routes_to_the_claude_pool_while_it_has_headroom(self):
        q = {**IDLE, "antigravity-claude": {"remaining": 49.0}}
        self.assertEqual(r.route("code", quota=q).service.name, "antigravity-claude")

    def test_drained_claude_pool_is_skipped_but_gemini_pool_is_not(self):
        q = {**IDLE, "antigravity-claude": {"remaining": 5.0}}
        self.assertNotEqual(r.route("code", quota=q).service.name, "antigravity-claude")
        self.assertEqual(r.route("bulk", quota=q).service.name, "antigravity")

    def test_never_judgment_tier(self):
        q = {**IDLE, "antigravity-claude": {"remaining": 100.0}}
        self.assertNotEqual(r.route("judgment", quota=q).service.name, "antigravity-claude")

    def test_alias_agy_does_not_create_a_second_service(self):
        names = [s.name for s in r.discover({**IDLE, "antigravity-claude": {"remaining": 90.0}})]
        self.assertEqual(names.count("antigravity-claude"), 1)
        self.assertNotIn("agy", names)


class TestPoolSplitIsGeneral(unittest.TestCase):
    """Any service can claim one pool family of its provider via `pool=`."""

    def test_any_declared_pool_is_split_and_undeclared_families_stay_home(self):
        svc = r.Service("copilot-premium", "copilot", {"code": 20}, "subscription",
                        pool=("copilot", "premium"))
        with mock.patch.object(r, "SERVICES", r.SERVICES + (svc,)):
            self.assertEqual(r.pool_service("copilot", "premium"), "copilot-premium")
            self.assertEqual(r.pool_service("copilot", "chat"), "copilot")
            self.assertEqual(r.pool_service("copilot", None), "copilot")

    def test_claude_fable_sublimit_is_not_split(self):
        self.assertEqual(r.pool_service("claude", "fable"), "claude")


class TestPlanWave(unittest.TestCase):
    """`plan` spreads one wave over pools and re-plans from live headroom."""

    Q: ClassVar[dict[str, Any]] = {**IDLE, "antigravity-claude": {"remaining": 90.0}}

    def test_wave_respects_max_parallel_then_spills_to_the_next_pool(self):
        rows = r.plan(["code"] * 5, quota=self.Q)
        names = [c.service.name for _, c in rows]
        cap = next(s for s in r.SERVICES if s.name == "antigravity-claude").max_parallel
        self.assertEqual(names[:cap], ["antigravity-claude"] * cap)
        self.assertNotEqual(names[cap], "antigravity-claude")

    def test_replan_follows_a_pool_that_just_drained(self):
        before = r.plan(["code"], quota=self.Q)[0][1].service.name
        after = r.plan(["code"], quota={**self.Q, "antigravity-claude": {"remaining": 4.0}})[0][1].service.name
        self.assertEqual(before, "antigravity-claude")
        self.assertNotEqual(after, "antigravity-claude")

    def test_exclude_skips_a_service_that_just_failed(self):
        c = r.plan(["code"], quota=self.Q, exclude={"antigravity-claude"})[0][1]
        self.assertNotEqual(c.service.name, "antigravity-claude")

    def test_plan_applies_default_fifteen_percent_headroom(self):
        q = {**self.Q, "antigravity-claude": {"remaining": 14.0}}
        c = r.plan(["code"], quota=q)[0][1]
        self.assertNotEqual(c.service.name, "antigravity-claude")

    def test_plan_skips_note_exhausted_pool(self):
        q = {**self.Q, "codex": {"remaining": 0.0}}
        c = r.plan(["code"], quota=q)[0][1]
        self.assertIsNotNone(c)
        self.assertNotEqual(c.service.name, "codex")

    @mock.patch.dict(os.environ, {"ROUTE_AGENT_OMP_READY": "0"})   # omp-ready: TestOmpReadyRoster
    def test_no_room_comes_back_as_none_not_an_error(self):
        drained = {k: {"remaining": 1.0} for k in {*IDLE, "antigravity-claude"}}
        rows = r.plan(["code"], quota=drained)
        self.assertIsNone(rows[0][1])

    def test_cli_plan_prints_one_numbered_line_per_slice(self):
        import contextlib
        import io
        buf = io.StringIO()
        with mock.patch.object(r, "load_snapshot", return_value=(self.Q, 60.0)), \
             contextlib.redirect_stdout(buf):
            self.assertEqual(r.main(["plan", "--kinds", "code,bulk"]), 0)
        lines = buf.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("1. code"))


class TestExhaustedAndStaleReadings(unittest.TestCase):
    """(b) route_agent obeys exhausted state and ignores old readings."""

    def make_snapshot(self, tmp, *, accounts, collected_at=None):
        path = Path(tmp) / "latest.json"
        data = {
            "snapshot": {"accounts": accounts},
            "collected_at": collected_at or r.datetime.now(r.UTC).isoformat(),
        }
        path.write_text(r.json.dumps(data))
        return path

    def load(self, accounts, collected_at=None):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            snap = self.make_snapshot(tmp, accounts=accounts, collected_at=collected_at)
            with mock.patch.object(r, "SNAPSHOT", snap):
                return r.load_snapshot()[0]

    def test_exhausted_state_counts_as_zero_remaining(self):
        """A window with state == 'exhausted' counts as 0 remaining even if remaining_percent is positive."""
        accts = [{
            "provider": "antigravity",
            "windows": [{
                "label": "Claude/GPT weekly",
                "pool_family": "claude_gpt",
                "remaining_percent": 47.6,
                "state": "exhausted",
            }],
        }]
        q = self.load(accts)
        self.assertEqual(q["antigravity-claude"]["remaining"], 0.0)

    def test_zero_headroom_percent_counts_as_zero_remaining(self):
        """A window with headroom_percent == 0 counts as 0 remaining."""
        accts = [{
            "provider": "antigravity",
            "windows": [{
                "label": "Claude/GPT weekly",
                "pool_family": "claude_gpt",
                "remaining_percent": 50.0,
                "headroom_percent": 0.0,
                "state": "ok",
            }],
        }]
        q = self.load(accts)
        self.assertEqual(q["antigravity-claude"]["remaining"], 0.0)

    def test_old_reading_by_age_seconds_treated_as_unmeasured_none(self):
        """An account older than STALE_SOFT (25 min) has its headroom treated as None."""
        accts = [{
            "provider": "antigravity",
            "age_seconds": 1800.0,  # 30 min > STALE_SOFT (1500s)
            "windows": [{
                "label": "Claude/GPT weekly",
                "pool_family": "claude_gpt",
                "remaining_percent": 90.0,
                "state": "ok",
            }],
        }]
        q = self.load(accts)
        self.assertIsNone(q["antigravity-claude"]["remaining"])

    def test_old_reading_by_collected_at_treated_as_unmeasured_none(self):
        """An account whose collected_at is older than STALE_SOFT has headroom treated as None."""
        old_time = (datetime.now(UTC) - timedelta(minutes=35)).isoformat()
        accts = [{
            "provider": "antigravity",
            "collected_at": old_time,
            "windows": [{
                "label": "Claude/GPT weekly",
                "pool_family": "claude_gpt",
                "remaining_percent": 90.0,
                "state": "ok",
            }],
        }]
        q = self.load(accts)
        self.assertIsNone(q["antigravity-claude"]["remaining"])

    def test_old_reading_does_not_get_burn_first_bonus(self):
        """When headroom is None (unmeasured), burn_first bonus is not applied."""
        # claude has 30% headroom, antigravity-claude is unmeasured (None)
        q = {**IDLE, "antigravity-claude": {"remaining": None}, "claude": {"remaining": 30.0}}
        # Unmeasured: rank 11 + unmeasured pressure 5 and no bonus. Measured at
        # 90%: rank 11 + 0.25 - BURN_FIRST_BONUS. The gap must show the bonus.
        unmeasured = r.route("code", quota=q)
        measured = r.route("code", quota={**q, "antigravity-claude": {"remaining": 90.0}})
        self.assertEqual(measured.service.name, "antigravity-claude")
        if unmeasured.service.name == "antigravity-claude":
            self.assertGreaterEqual(unmeasured.score - measured.score, r.BURN_FIRST_BONUS)

    def test_exhausted_state_on_old_reading_still_counts_as_zero(self):
        """An override on an older account reading still registers as 0.0 remaining (exhausted)."""
        accts = [{
            "provider": "antigravity",
            "age_seconds": 2400.0,  # 40 min
            "windows": [{
                "label": "Claude/GPT weekly",
                "pool_family": "claude_gpt",
                "remaining_percent": 47.6,
                "state": "exhausted",
            }],
        }]
        q = self.load(accts)
        self.assertEqual(q["antigravity-claude"]["remaining"], 0.0)



class ShadowKindTests(unittest.TestCase):
    """The agent-choice shadow ask never changes or delays a route."""

    def test_brief_is_sent_on_stdin_with_incumbent_and_all_kinds(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".md") as f:
            f.write("Fix the flaky test in tests/test_x.py")
            f.flush()
            with mock.patch.object(r.subprocess, "Popen") as popen:
                r.shadow_kind(f.name, "code", "claude")
        args = popen.call_args.args[0]
        self.assertEqual(args[1:3], ["decide", "--site"])
        self.assertIn("agent-choice", args)
        self.assertEqual(args[args.index("--incumbent") + 1], "code")
        self.assertEqual([args[i + 1] for i, a in enumerate(args) if a == "--option"], list(r.KINDS))
        popen.return_value.stdin.write.assert_called_once_with("Fix the flaky test in tests/test_x.py")
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_failures_are_swallowed(self):
        r.shadow_kind("/nonexistent/brief.md", "code", None)
        with mock.patch.object(r.subprocess, "Popen", side_effect=OSError):
            r.shadow_kind(__file__, "code", None)


class TestRoutingPolicy2026_10_15(unittest.TestCase):
    """Operator policy of 2026-10-15: frontier pools for serious work, reserves
    with a floor, hermes/omp never routable, Fable a sublimit of the shared pool,
    a model suggestion on every route."""

    def test_hermes_is_never_discovered(self):
        q = {**IDLE, "hermes": {"remaining": 100.0}, "omp": {"remaining": 99.7}}
        names = {s.name for s in r.discover(q)}
        self.assertNotIn("hermes", names)
        for kind in r.KINDS:
            c = r.route(kind, quota=q)
            self.assertNotEqual(c.service.name if c else None, "hermes")

    def test_reserve_floor_blocks_copilot_below_sixty_percent(self):
        q = {name: {"remaining": 0.0} for name in (*IDLE, "antigravity-claude")}
        q["copilot"] = {"remaining": 59.0}
        self.assertIsNone(r.route("github", quota=q))
        # Generic kinds never reach the reserve, whatever its headroom.
        q["copilot"] = {"remaining": 100.0}
        for kind in ("research", "bulk", "code"):
            c = r.route(kind, quota=q)
            self.assertNotIn(c.service.name if c else None, {"copilot"}, kind)
        q["copilot"] = {"remaining": 61.0}
        self.assertEqual(r.route("github", quota=q).service.name, "copilot")
        # A reserve with no reading at all fails closed.
        q["copilot"] = {}
        self.assertIsNone(r.route("github", quota=q))

    def test_grok_is_an_ordinary_pool_since_grokbot_moved_off_it(self):
        # 2026-10-18: GrokBot runs on its own Cursor pool, so grok has no floor.
        svc = next(s for s in r.SERVICES if s.name == "grok")
        self.assertEqual(svc.reserve_floor, 0.0)
        self.assertGreater(svc.max_parallel, 1)
        for kind in ("realtime-web", "research", "bulk"):
            self.assertTrue(svc.eligible(kind), kind)
        q = {name: {"remaining": 0.0} for name in (*IDLE, "antigravity-claude")}
        q["grok"] = {"remaining": 20.0}
        self.assertEqual(r.route("realtime-web", quota=q).service.name, "grok")
        # Behind the burn-first pools: with antigravity open, research goes there.
        q["antigravity"] = {"remaining": 90.0}
        q["grok"] = {"remaining": 90.0}
        self.assertEqual(r.route("research", quota=q).service.name, "antigravity")

    def test_everyday_code_avoids_the_frontier_pools_when_others_have_room(self):
        q = {**IDLE, "antigravity-claude": {"remaining": 0.0}, "cursor-auto": {"remaining": 75.0}}
        c = r.route("code", quota=q)
        self.assertNotIn(c.service.name, {"claude", "codex"})

    def test_judgment_is_opus_high_and_never_fable(self):
        q = {**IDLE, "claude": {"remaining": 90.0, "sublimits": {"fable": 97.0}}}
        self.assertEqual(r.route("judgment", quota=q).model, "opus --effort high")

    def test_frontier_suggests_fable_high_then_falls_back_to_opus(self):
        q = {**IDLE, "codex": {"remaining": 0.0},
             "claude": {"remaining": 90.0, "sublimits": {"fable": 97.0}}}
        self.assertEqual(r.route("frontier", quota=q).model, "fable --effort high")
        q["claude"] = {"remaining": 90.0, "sublimits": {"fable": 4.0}}
        self.assertEqual(r.route("frontier", quota=q).model, "opus --effort high")
        for svc in r.SERVICES:
            self.assertFalse(any("xhigh" in m and "fable" in m for m in svc.models.values()), svc.name)

    def test_codex_frontier_is_the_top_frontier_model(self):
        c = r.route("frontier", quota=IDLE)
        self.assertEqual(c.service.name, "codex")
        self.assertEqual(c.dispatch,
                         "acp-dispatch codex --model gpt-6-astra --effort high --kind frontier")


class TestFrontierConservative2026_10_18(unittest.TestCase):
    """Operator 2026-10-18: a wave of four astra slices emptied codex's 5-hour
    window; codex only for work that really needs astra, Fable xhigh almost never."""

    def test_codex_takes_only_frontier_and_the_plentiful_everyday_kinds(self):
        """2026-10-25 widened this: judgment, code, bulk and mechanical only while plentiful (see
        TestCodexEverydayKinds); every other kind stays off codex at any headroom."""
        q = {s.name: {"remaining": 0.0} for s in r.SERVICES}
        q["codex"] = {"remaining": 100.0}
        for kind in r.KINDS:
            c = r.route(kind, quota=q)
            if kind not in ("frontier", "judgment", "code", "bulk", "mechanical"):
                self.assertNotEqual(c.service.name if c else None, "codex", kind)

    def test_a_wave_puts_at_most_one_frontier_slice_on_each_pool(self):
        rows = r.plan(["frontier"] * 4, quota=IDLE)
        names = [c.service.name if c else None for _, c in rows]
        self.assertEqual(names, ["codex", "claude", None, None])

    def test_judgment_slices_after_a_frontier_slice_stay_on_claude(self):
        rows = r.plan(["frontier", "judgment", "judgment"], quota=IDLE)
        self.assertEqual([c.service.name for _, c in rows], ["codex", "claude", "claude"])

    def test_dispatch_line_uses_the_acp_agent_name(self):
        q = {**IDLE, "antigravity-claude": {"remaining": 90.0}}
        c = r.route("code", quota=q)
        self.assertEqual(c.service.name, "antigravity-claude")
        self.assertTrue(c.dispatch.startswith("acp-dispatch agy --model claude-opus-5-5"))

    def test_dispatch_quotes_zcode_model_with_backslash(self):
        # F12: zcode ids contain a backslash; shlex.split must round-trip the model token.
        svc = next(s for s in r.SERVICES if s.name == "zai")
        choice = r.Choice(svc, 80.0, 1.0, model=r"builtin:zai-coding-plan\GLM-5.3", kind="code")
        parts = shlex.split(choice.dispatch)
        self.assertEqual(parts[parts.index("--model") + 1], r"builtin:zai-coding-plan\GLM-5.3")

    def test_plan_json_carries_model_and_dispatch(self):
        rows = r.plan(["judgment", "bulk"], quota=IDLE)
        for _, c in rows:
            self.assertIsNotNone(c)
            self.assertTrue(c.dispatch.startswith("acp-dispatch "))


class TestFableSublimitAndCursorSplit(unittest.TestCase):
    def load(self, accounts):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "latest.json"
            path.write_text(r.json.dumps({"snapshot": {"accounts": accounts},
                                          "collected_at": r.datetime.now(r.UTC).isoformat()}))
            with mock.patch.object(r, "SNAPSHOT", path):
                return r.load_snapshot()[0]

    def test_spent_fable_sublimit_does_not_exhaust_the_claude_pool(self):
        q = self.load([{"provider": "claude", "windows": [
            {"label": "Claude Code 5-hour", "pool_family": "default", "remaining_percent": 86.0,
             "headroom_percent": 86.0, "state": "ok", "quota_scope": "shared"},
            {"label": "Claude Code weekly", "pool_family": "default", "remaining_percent": 96.0,
             "headroom_percent": 96.0, "state": "ok", "quota_scope": "shared"},
            {"label": "Claude Code weekly — Fable", "pool_family": "fable", "remaining_percent": 0.0,
             "headroom_percent": 0.0, "state": "exhausted", "quota_scope": "model_sublimit",
             "shared_pool_family": "default", "max_share_of_parent_percent": 50.0}]}])
        self.assertEqual(q["claude"]["remaining"], 86.0)
        self.assertEqual(q["claude"]["sublimits"], {"fable": 0.0})
        self.assertEqual(r.route("frontier", quota={**q, "codex": {"remaining": 0.0}}).model,
                         "opus --effort high")

    def test_cursor_auto_pool_is_split_from_the_tight_third_party_pool(self):
        q = self.load([{"provider": "cursor", "windows": [
            {"label": "total", "pool_family": "total", "remaining_percent": 73.9,
             "headroom_percent": 73.9, "state": "ok"},
            {"label": "auto", "pool_family": "auto", "remaining_percent": 75.4,
             "headroom_percent": 73.9, "state": "ok", "quota_scope": "model_sublimit",
             "shared_pool_family": "total"},
            {"label": "third-party", "pool_family": "third_party", "remaining_percent": 11.2,
             "headroom_percent": 11.2, "state": "tight", "quota_scope": "model_sublimit",
             "shared_pool_family": "total"}]}])
        self.assertEqual(q["cursor-auto"]["remaining"], 73.9)
        self.assertEqual(q["cursor"]["remaining"], 11.2)
        c = r.route("code", quota=q)
        self.assertEqual(c.service.name, "cursor-auto")
        self.assertEqual(c.dispatch, "acp-dispatch cursor --model default --kind code")


class TestRoutingPolicyToml(unittest.TestCase):
    """config/routing.toml is the source of truth for curated routing data."""

    # Frozen expectation for three representative rows (behaviour-preserving refactor).
    EXPECTED: ClassVar[dict[str, dict[str, Any]]] = {
        "claude": {
            "cli": "claude (Opus 5.5 @ high for judgment; Sonnet 5.5 for code; Fable only for frontier)",
            "good_at": {"judgment": 1, "frontier": 2, "code": 12},
            "billing": "subscription",
            "judgment_tier": True,
            "models": {"judgment": "opus --effort high", "frontier": "fable --effort high",
                       "code": "sonnet --effort high"},
            "pool": None, "max_parallel": 4, "agent": "", "burn_first": False,
        },
        "codex": {
            "cli": ("codex (gpt-6-astra for frontier; gpt-6.1-sol / gpt-6-luna for everyday kinds "
                    "while quota is plentiful)"),
            "good_at": {"frontier": 1, "judgment": 3, "mechanical": 12, "code": 15, "bulk": 20},
            "billing": "subscription",
            "judgment_tier": True,
            "models": {"frontier": "gpt-6-astra --effort high", "judgment": "gpt-6.1-sol --effort high",
                       "code": "gpt-6.1-sol --effort medium",
                       "bulk": "gpt-6-luna --effort low", "mechanical": "gpt-6-luna --effort low"},
            "pool": None, "max_parallel": 1, "agent": "", "burn_first": False,
        },
        "antigravity-claude": {
            "cli": "agy (acp-run agy --model claude-opus-5-5 --effort high | claude-sonnet-5-5)",
            "good_at": {"code": 11, "research": 3, "mechanical": 6},
            "billing": "subscription",
            "judgment_tier": False,
            "models": {"code": "claude-opus-5-5 --effort high",
                       "research": "claude-sonnet-5-5 --effort high",
                       "mechanical": "claude-sonnet-5-5 --effort low"},
            "pool": ("antigravity", "claude_gpt"), "max_parallel": 3,
            "agent": "agy", "burn_first": True,
        },
    }

    def tearDown(self):
        # Restore the repo policy after any test that reloads a temp file.
        r.reload_policy(Path(__file__).resolve().parent.parent / "config" / "routing.toml")

    def test_loaded_services_match_frozen_expectation(self):
        for name, expect in self.EXPECTED.items():
            svc = r.BY_NAME[name]
            self.assertEqual(svc.cli, expect["cli"], name)
            self.assertEqual(svc.good_at, expect["good_at"], name)
            self.assertEqual(svc.billing, expect["billing"], name)
            self.assertEqual(svc.judgment_tier, expect["judgment_tier"], name)
            self.assertEqual(svc.models, expect["models"], name)
            self.assertEqual(svc.pool, expect["pool"], name)
            self.assertEqual(svc.max_parallel, expect["max_parallel"], name)
            self.assertEqual(svc.agent, expect["agent"], name)
            self.assertEqual(svc.burn_first, expect["burn_first"], name)

    def test_routing_policy_env_changes_route_output(self):
        import tempfile
        import textwrap
        base = (Path(__file__).resolve().parent.parent / "config" / "routing.toml").read_text()
        # Make claude lose judgment (rank 99) and invent a fake judgment winner.
        patched = base.replace(
            'good_at = { judgment = 1, frontier = 2 }',
            'good_at = { judgment = 99, frontier = 2 }',
            1,
        )
        # Inject a judgment-tier service that wins when claude is demoted.
        inject = textwrap.dedent('''
            [[service]]
            name = "policy-test-judge"
            cli = "policy-test-judge"
            good_at = { judgment = 1 }
            billing = "subscription"
            judgment_tier = true
            models = { judgment = "test-model" }
        ''')
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write(patched + inject)
            tmp = fh.name
        try:
            with mock.patch.dict(os.environ, {"ROUTING_POLICY": tmp}):
                r.reload_policy()
            # Drain everything else; only our test judge should take judgment.
            q = {**IDLE, "claude": {"remaining": 5.0},
                 "policy-test-judge": {"remaining": 100.0}}
            choice = r.route("judgment", quota=q)
            self.assertIsNotNone(choice)
            self.assertEqual(choice.service.name, "policy-test-judge")
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_unknown_key_names_the_file(self):
        import tempfile
        import textwrap
        bad = textwrap.dedent('''
            [routing]
            kinds = ["bulk"]
            burn_first_min = 40.0
            burn_first_bonus = 4.0
            burn_first_waste_min = 30.0
            pace_penalty_above = 1.5
            pace_penalty = 6.0
            pace_penalty_judgment_factor = 0.5
            frontier_per_wave = 1
            fable_min_left = 10.0
            default_profile = { bulk = 60 }

            [calibrate]
            min_outcomes = 5
            min_peers = 2
            suggest_worse_below = 25.0
            suggest_worse_delta = 5
            suggest_better_above = 15.0
            suggest_better_delta = 3

            [discovery]
            never_route = []
            operator_gated = []
            aliases = {}

            [dispatch]
            operator_gated = []
            fable_gated_efforts = []
            inflight_cap = {}
            extra = {}

            [hermes]
            provider_name = {}

            [hermes.models]

            [[service]]
            name = "x"
            cli = "x"
            good_at = { bulk = 1 }
            billing = "free"
            not_a_field = true
        ''')
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write(bad)
            tmp = fh.name
        try:
            with self.assertRaises(ValueError) as ctx:
                r.load_policy(tmp)
            msg = str(ctx.exception)
            self.assertIn(tmp, msg)
            self.assertIn("unknown key", msg)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_missing_name_names_the_file(self):
        import tempfile
        import textwrap
        bad = textwrap.dedent('''
            [routing]
            kinds = ["bulk"]
            burn_first_min = 40.0
            burn_first_bonus = 4.0
            burn_first_waste_min = 30.0
            pace_penalty_above = 1.5
            pace_penalty = 6.0
            pace_penalty_judgment_factor = 0.5
            frontier_per_wave = 1
            fable_min_left = 10.0
            default_profile = { bulk = 60 }

            [calibrate]
            min_outcomes = 5
            min_peers = 2
            suggest_worse_below = 25.0
            suggest_worse_delta = 5
            suggest_better_above = 15.0
            suggest_better_delta = 3

            [discovery]
            never_route = []
            operator_gated = []
            aliases = {}

            [dispatch]
            operator_gated = []
            fable_gated_efforts = []
            inflight_cap = {}
            extra = {}

            [hermes]
            provider_name = {}

            [hermes.models]

            [[service]]
            cli = "x"
            good_at = { bulk = 1 }
            billing = "free"
        ''')
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write(bad)
            tmp = fh.name
        try:
            with self.assertRaises(ValueError) as ctx:
                r.load_policy(tmp)
            msg = str(ctx.exception)
            self.assertIn(tmp, msg)
            self.assertIn("missing required", msg)
            self.assertIn("name", msg)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_missing_routing_or_calibrate_key_names_the_file(self):
        import tempfile
        import textwrap
        # Missing [calibrate] table → load_policy ValueError with path.
        no_cal = textwrap.dedent('''
            [routing]
            kinds = ["bulk"]
            burn_first_min = 40.0
            burn_first_bonus = 4.0
            burn_first_waste_min = 30.0
            pace_penalty_above = 1.5
            pace_penalty = 6.0
            pace_penalty_judgment_factor = 0.5
            frontier_per_wave = 1
            fable_min_left = 10.0
            default_profile = { bulk = 60 }

            [discovery]
            never_route = []
            operator_gated = []
            aliases = {}

            [dispatch]
            operator_gated = []
            fable_gated_efforts = []
            inflight_cap = {}
            extra = {}

            [hermes]
            provider_name = {}

            [hermes.models]

            [[service]]
            name = "x"
            cli = "x"
            good_at = { bulk = 1 }
            billing = "free"
        ''')
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write(no_cal)
            tmp = fh.name
        try:
            with self.assertRaises(ValueError) as ctx:
                r.load_policy(tmp)
            msg = str(ctx.exception)
            self.assertIn(tmp, msg)
            self.assertIn("calibrate", msg)
        finally:
            Path(tmp).unlink(missing_ok=True)

        # Present sections but a missing routing key → apply_policy ValueError.
        base = (Path(__file__).resolve().parent.parent / "config" / "routing.toml"
                ).read_text()
        patched = base.replace(
            "pace_penalty_judgment_factor = 0.5\n", "", 1)
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as fh:
            fh.write(patched)
            tmp = fh.name
        try:
            data = r.load_policy(tmp)
            with self.assertRaises(ValueError) as ctx:
                r.POLICY_PATH = Path(tmp)
                r.apply_policy(data)
            msg = str(ctx.exception)
            self.assertIn(tmp, msg)
            self.assertIn("pace_penalty_judgment_factor", msg)
            self.assertNotIsInstance(ctx.exception, KeyError)
        finally:
            Path(tmp).unlink(missing_ok=True)
            r.reload_policy(
                Path(__file__).resolve().parent.parent / "config" / "routing.toml")

    def test_policy_md_contains_codex_frontier_row(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = r.main(["policy", "--md"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("codex", out)
        self.assertIn("frontier", out)
        self.assertIn("gpt-6-astra", out)

    def test_policy_md_and_json_carry_the_lead_session_model(self):
        """[lead] (2026-10-23): the session that dispatches runs on Opus 5.5 at high, Sonnet at
        medium to drive a pipeline, never Fable; `policy --md` and `--json` must say so."""
        import io
        import json
        from contextlib import redirect_stdout
        md, js = io.StringIO(), io.StringIO()
        with redirect_stdout(md):
            self.assertEqual(r.main(["policy", "--md"]), 0)
        with redirect_stdout(js):
            self.assertEqual(r.main(["policy"]), 0)
        self.assertIn("## Lead / orchestrator session", md.getvalue())
        self.assertIn("| lead.model | opus |", md.getvalue())
        self.assertIn("| lead.effort | high |", md.getvalue())
        self.assertIn("| lead.pipeline_model | sonnet |", md.getvalue())
        self.assertIn("| lead.pipeline_effort | medium |", md.getvalue())
        self.assertIn("pipeline lead: sonnet at medium; high for judgment turns", md.getvalue())
        self.assertEqual(json.loads(js.getvalue())["lead"],
                         {"model": "opus", "effort": "high", "pipeline_model": "sonnet",
                          "pipeline_effort": "medium"})

    def _lead_policy_variant(self, replacement):
        """Write routing.toml with the pipeline_effort line replaced; return the temp path."""
        import tempfile
        src = (Path(__file__).resolve().parent.parent / "config" / "routing.toml").read_text()
        bad = src.replace('pipeline_effort = "medium"\n', replacement)
        self.assertNotEqual(src, bad)
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write(bad)
        self.addCleanup(Path(f.name).unlink, missing_ok=True)
        return f.name

    def test_a_lead_table_without_pipeline_effort_defaults_to_high(self):
        """Older policy files predate pipeline_effort and must still load, at high."""
        data = r.load_policy(self._lead_policy_variant(""))
        self.assertEqual(data["lead"]["pipeline_effort"], "high")

    def test_a_pipeline_effort_a_claude_lead_cannot_take_is_rejected_naming_the_file(self):
        """Strings outside Paseo's Claude levels (acp-run's `minimal`, `none`, `ultra`) and
        non-strings (TOML integer, boolean) all fail at load, naming the file."""
        for value in ('"turbo"', '"minimal"', '"none"', '"ultra"', '"Medium"', "3", "true"):
            with self.subTest(value=value):
                path = self._lead_policy_variant(f"pipeline_effort = {value}\n")
                with self.assertRaises(ValueError) as ctx:
                    r.load_policy(path)
                self.assertIn(path, str(ctx.exception))
                self.assertIn("pipeline_effort", str(ctx.exception))

    def test_a_judgment_lead_effort_outside_the_claude_levels_is_rejected(self):
        import tempfile
        src = (Path(__file__).resolve().parent.parent / "config" / "routing.toml").read_text()
        bad = src.replace('effort = "high"\npipeline_model', 'effort = "minimal"\npipeline_model')
        self.assertNotEqual(src, bad)
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write(bad)
        self.addCleanup(Path(f.name).unlink, missing_ok=True)
        with self.assertRaises(ValueError) as ctx:
            r.load_policy(f.name)
        self.assertIn(f.name, str(ctx.exception))
        self.assertIn("effort", str(ctx.exception))

    def test_a_misspelt_lead_key_is_rejected_not_silently_defaulted(self):
        """`pipline_effort = "medium"` must not load as the default high."""
        path = self._lead_policy_variant('pipline_effort = "medium"\n')
        with self.assertRaises(ValueError) as ctx:
            r.load_policy(path)
        self.assertIn(path, str(ctx.exception))
        self.assertIn("pipline_effort", str(ctx.exception))

    def test_a_lead_table_missing_a_key_is_rejected_naming_the_file(self):
        import tempfile
        src = (Path(__file__).resolve().parent.parent / "config" / "routing.toml").read_text()
        bad = src.replace('pipeline_model = "sonnet"\n', "")
        self.assertNotEqual(src, bad)
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
            f.write(bad)
        try:
            with self.assertRaises(ValueError) as ctx:
                r.load_policy(f.name)
            self.assertIn(f.name, str(ctx.exception))
            self.assertIn("[lead]", str(ctx.exception))
        finally:
            Path(f.name).unlink(missing_ok=True)


class TestQualityBand(unittest.TestCase):
    """[routing].quality_max_rank_gap (2026-10-18, plektra lead with djbclark's approval): quota
    never buys a much weaker pool into code or judgment."""

    # The live readings when `plan --kinds code` picked Gemini Flash (r40): every r11-r20 code
    # pool was under the 15% headroom floor, and Flash had 98% left.
    CASE = {"antigravity-claude": {"remaining": 0.0}, "antigravity": {"remaining": 97.8},
            "opencode-go": {"remaining": 2.5}, "zai": {"remaining": 12.2},
            "cursor-auto": {"remaining": 0.0}, "cursor": {"remaining": 11.2},
            # claude was not a code pool then (code added 2026-10-18 by the operator); drained
            # here so the case still isolates the band
            "codex": {"remaining": 0.0}, "claude": {"remaining": 0.0},
            "opencode-zen-free": {"remaining": 100.0}, "clinepass": {"remaining": 100.0},
            "devin": {"remaining": 100.0}, "alibaba": {"remaining": 100.0},
            "crush": {"remaining": 100.0}}

    def test_flash_is_not_a_code_pool(self):
        self.assertFalse(r.BY_NAME["antigravity"].eligible("code"))

    @mock.patch.dict(os.environ, {"ROUTE_AGENT_OMP_READY": "0"})   # omp-ready: TestOmpReadyRoster
    def test_the_2026_10_18_case_queues_code_instead_of_routing_far_down(self):
        best = r.quality_best("code", list(r.discover(self.CASE)))
        self.assertIsNotNone(best)
        c = r.route("code", quota=self.CASE)
        self.assertIsNone(c, c and f"{c.service.name} r{c.service.rank_for('code')}")
        why = r.unrouted_why("code", self.CASE)
        self.assertIn(f"{best.name} r{best.rank_for('code')}", why)
        self.assertIn("quality_max_rank_gap", why)

    def test_a_far_lower_ranked_pool_never_wins_on_headroom(self):
        """Even with every pool idle, nothing outside the band is chosen for code; and the
        moment an in-band pool has room again, it gets the slice."""
        gap = r.QUALITY_MAX_RANK_GAP["code"]
        services = list(r.discover(self.CASE))
        best = r.quality_best("code", services)
        assert best is not None
        far = [s.name for s in services
               if s.eligible("code") and s.rank_for("code") - best.rank_for("code") > gap]
        self.assertTrue(far, "fixture should include pools outside the band")
        q = dict(self.CASE, zai={"remaining": 50.0})
        c = r.route("code", quota=q)
        self.assertIsNotNone(c)
        self.assertNotIn(c.service.name, far)
        self.assertLessEqual(c.service.rank_for("code") - best.rank_for("code"), gap)

    def test_claude_codes_on_sonnet_never_fable(self):
        """Operator 2026-10-18: claude is a code pool; only Fable is not."""
        c = r.route("code", quota=dict(self.CASE, claude={"remaining": 61.0}))
        self.assertIsNotNone(c)
        self.assertEqual((c.service.name, c.model), ("claude", "sonnet --effort high"))
        self.assertNotIn("fable", c.model)

    def test_judgment_has_a_band_too(self):
        self.assertIn("judgment", r.QUALITY_MAX_RANK_GAP)

    def test_an_excluded_best_pool_moves_the_band(self):
        """A failed pool passed in `exclude` no longer anchors the band (the reroute path)."""
        services = list(r.discover(self.CASE))
        best = r.quality_best("code", services)
        assert best is not None
        nxt = r.quality_best("code", services, {best.name})
        self.assertIsNotNone(nxt)
        self.assertNotEqual(nxt.name, best.name)


class TestCodexEverydayKinds(unittest.TestCase):
    """Operator 2026-10-25: "if we have lots of codex quota and it is the best of available
    options we can use it for non-frontier". Everyday kinds are gated on [routing].plenty_min of
    the binding headroom; astra stays frontier-only; ranking is the normal one."""

    EVERYDAY = ("judgment", "code", "bulk", "mechanical")

    def codex(self):
        return r.BY_NAME["codex"]

    def drained(self, **over):
        return {**{s.name: {"remaining": 0.0} for s in r.SERVICES}, **over}

    def test_eligible_at_high_headroom_only_for_the_everyday_kinds_profiled(self):
        q = {"codex": {"remaining": 100.0}}
        for kind in self.EVERYDAY:
            self.assertTrue(self.codex().eligible(kind, q), kind)
        for kind in ("research", "github", "api-only", "realtime-web"):
            self.assertFalse(self.codex().eligible(kind, q), kind)
        self.assertTrue(self.codex().eligible("frontier", q))

    def test_ineligible_below_the_constant_and_without_a_reading_but_frontier_stays(self):
        edge = r.PLENTY_MIN
        for kind in self.EVERYDAY:
            self.assertTrue(self.codex().eligible(kind, {"codex": {"remaining": edge}}), kind)
            self.assertFalse(self.codex().eligible(kind, {"codex": {"remaining": edge - 0.1}}), kind)
            self.assertFalse(self.codex().eligible(kind, {"codex": {"remaining": None}}), kind)
            self.assertFalse(self.codex().eligible(kind), kind)
        self.assertTrue(self.codex().eligible("frontier", {"codex": {"remaining": 1.0}}))
        self.assertTrue(self.codex().eligible("frontier"))

    def test_a_window_with_no_reading_fails_closed_for_the_gated_kinds(self):
        """One known 95% window must not stand for every window (adversary 7802361, A2): the
        reader keeps `remaining` = the tightest KNOWN window, and lists the null one."""
        known = [{"label": "5h", "remaining_percent": 95.0}, {"label": "weekly", "remaining_percent": 80.0}]
        partial = [known[0], {"label": "weekly", "remaining_percent": None}]
        whole = r._providers_from_accounts([{"provider": "codex", "windows": known}], 0.0)
        half = r._providers_from_accounts([{"provider": "codex", "windows": partial}], 0.0)
        self.assertEqual(half["codex"]["remaining"], 95.0)
        for kind in self.EVERYDAY:
            self.assertTrue(self.codex().eligible(kind, whole), kind)
            self.assertFalse(self.codex().eligible(kind, half), kind)
        self.assertTrue(self.codex().eligible("frontier", half))      # frontier needs no plenty
        self.assertTrue(self.codex().eligible("code", {"codex": {"remaining": 95.0}}))   # no windows listed

    def test_only_codex_has_a_plenty_gate(self):
        """The partial-reading rule lives in the plenty gate: no other pool carries one."""
        self.assertEqual([s.name for s in r.SERVICES if s.plenty_kinds], ["codex"])

    def test_the_default_constant_is_half_the_window(self):
        self.assertEqual(r.PLENTY_MIN, 50.0)

    def test_route_never_hands_codex_an_everyday_slice_below_the_constant(self):
        low = self.drained(codex={"remaining": r.PLENTY_MIN - 1})
        for kind in self.EVERYDAY:
            c = r.route(kind, quota=low)          # an installed unprofiled agent may still take bulk
            self.assertNotEqual(c.service.name if c else None, "codex", kind)
        self.assertTrue(self.codex().eligible("code", self.drained(codex={"remaining": r.PLENTY_MIN})))
        self.assertEqual(r.route("frontier", quota=low).service.name, "codex")

    def test_astra_is_frontier_only_in_the_profile(self):
        models = self.codex().models
        frontier = [str(m).lower() for m in r.POLICY["dispatch"]["frontier_models"]]
        self.assertIn("gpt-6-astra", models["frontier"])
        for kind in self.EVERYDAY:
            self.assertFalse(any(tok in models[kind].lower() for tok in frontier), (kind, models[kind]))
        c = r.route("code", quota=self.drained(codex={"remaining": 100.0}))
        self.assertEqual((c.service.name, c.model), ("codex", "gpt-6.1-sol --effort medium"))
        c = r.route("mechanical", quota=self.drained(codex={"remaining": 100.0}))
        self.assertEqual((c.service.name, c.model), ("codex", "gpt-6-luna --effort low"))

    def test_codex_competes_on_rank_it_is_not_forced_first(self):
        q = {**IDLE, "codex": {"remaining": 100.0}}
        for kind in ("bulk", "mechanical"):          # free and idle pools stay first
            c = r.route(kind, quota=q)
            self.assertNotEqual(c.service.name, "codex", kind)
        better = self.drained(codex={"remaining": 100.0}, **{"antigravity-claude": {"remaining": 90.0}})
        self.assertEqual(r.route("code", quota=better).service.name, "antigravity-claude")
        only = self.drained(codex={"remaining": 100.0}, zai={"remaining": 90.0})
        self.assertEqual(r.route("code", quota=only).service.name, "codex")   # r15 beats zai r16

    def test_a_wave_puts_one_slice_on_codex(self):
        q = self.drained(codex={"remaining": 100.0})
        rows = r.plan(["code", "code", "code"], quota=q)
        self.assertEqual([c.service.name if c else None for _, c in rows].count("codex"), 1)

    def test_policy_json_and_md_carry_the_constant_and_the_gated_kinds(self):
        pub = r.policy_public()
        self.assertEqual(pub["routing"]["plenty_min"], 50.0)
        row = next(s for s in pub["services"] if s["name"] == "codex")
        self.assertEqual(sorted(row["plenty_kinds"]), ["bulk", "code", "judgment", "mechanical"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(r.main(["policy", "--md"]), 0)
        self.assertIn("| routing.plenty_min | 50 |", buf.getvalue())



class TestOmpReadyRoster(unittest.TestCase):
    """With a working omp login (ROUTE_AGENT_OMP_READY=1) omp is a code/bulk pool. conftest pins the
    probe off so the suite does not depend on the host; these are the omp-ready counterparts of
    test_measured_idle_capacity_beats_unmeasured, test_no_room_comes_back_as_none_not_an_error and
    test_the_2026_10_18_case_queues_code_instead_of_routing_far_down (docs/queue.md item 6, 2026-10-20).
    Left out on purpose: omp ready with NO quota reading (the state this Mac was in). There an unmeasured
    omp outranks a measured pool in all three scenarios, which is the open follow-up carried from item 6,
    not behaviour to pin (adversary, 2026-10-20)."""

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"ROUTE_AGENT_OMP_READY": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_measured_full_omp_pool_beats_another_measured_idle_pool_for_bulk(self):
        q = {**{k: {"remaining": 0.0} for k in IDLE},
             "fresh-pool": {"remaining": 99.0}, "murky-pool": {}, "omp": {"remaining": 100.0}}
        self.assertEqual(r.route("bulk", quota=q).service.name, "omp")
        # ...and a drained omp leaves the original ordering alone.
        q["omp"] = {"remaining": 0.0}
        self.assertEqual(r.route("bulk", quota=q).service.name, "fresh-pool")

    def test_omp_is_the_room_when_every_other_code_pool_is_drained(self):
        drained = {k: {"remaining": 1.0} for k in {*IDLE, "antigravity-claude"}}
        self.assertIsNone(r.plan(["code"], quota={**drained, "omp": {"remaining": 1.0}})[0][1])
        c = r.plan(["code"], quota={**drained, "omp": {"remaining": 100.0}})[0][1]
        self.assertIsNotNone(c)
        self.assertEqual(c.service.name, "omp")

    def test_omp_with_room_is_inside_the_2026_10_18_quality_band(self):
        """omp (code r13) is within quality_max_rank_gap of the band's best (r11), so with credits
        left the case no longer queues; with omp drained it still does."""
        case = TestQualityBand.CASE
        c = r.route("code", quota={**case, "omp": {"remaining": 100.0}})
        self.assertIsNotNone(c)
        self.assertEqual(c.service.name, "omp")
        self.assertIsNone(r.route("code", quota={**case, "omp": {"remaining": 1.0}}))
        self.assertIn("quality_max_rank_gap",
                      r.unrouted_why("code", {**case, "omp": {"remaining": 1.0}}))


class TestOmpCreditsTier(unittest.TestCase):
    """Operator 2026-10-19: omp (the Claude Max plan's monthly API credits) is a normal tier, no
    per-run approval: `api-only` work first, code/bulk so the grant is spent before it expires."""

    # Credits 100% left, expiring 16 days out of a 30-day grant (omp's real snapshot shape: a
    # reset date, no window_minutes, no pace). Relative to now: the router reads the clock.
    @property
    def EXPIRY(self):
        return (datetime.now(UTC) + timedelta(days=16)).isoformat()

    def quota(self, remaining=99.7, **over):
        q = {**IDLE, "omp": {"remaining": remaining, "resets_at": self.EXPIRY,
                             "window_minutes": None, "pace_ratio": None}}
        q.update(over)
        return q

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"ROUTE_AGENT_OMP_READY": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_omp_is_no_longer_gated_anywhere(self):
        self.assertNotIn("omp", r.OPERATOR_GATED)
        self.assertNotIn("omp", r.POLICY["dispatch"]["operator_gated"])
        self.assertIn("hermes", r.POLICY["dispatch"]["operator_gated"])
        self.assertIn("cline", r.OPERATOR_GATED)

    def test_omp_is_eligible_for_code_and_bulk_without_operator_approval(self):
        env = {k: v for k, v in os.environ.items() if k != "ACP_OPERATOR_APPROVED"}
        with mock.patch.dict(os.environ, env, clear=True):
            svc = r.BY_NAME["omp"]
            self.assertTrue(svc.eligible("code"))
            self.assertTrue(svc.eligible("bulk"))
            self.assertTrue(svc.eligible("api-only"))
            self.assertTrue(svc.eligible("judgment"))     # adversary rounds, 2026-10-23
            self.assertFalse(svc.eligible("frontier"))
            self.assertIn("omp", {s.name for s in r.discover(self.quota())})

    def test_omp_takes_judgment_on_opus_when_claude_is_drained_and_never_frontier(self):
        """Adversary rounds go to omp (2026-10-23): Opus 5.5 at high on the credits. With claude
        drained it is the only judgment pool left; frontier never lands on omp."""
        drained = self.quota(claude={"remaining": 0.0})
        c = r.route("judgment", quota=drained)
        self.assertEqual(c.service.name, "omp")
        self.assertEqual(c.model, "anthropic/claude-opus-5-5 --effort high")
        self.assertNotIn("omp", {s.name for s in r.SERVICES if s.eligible("frontier")})
        self.assertEqual(r.route("judgment", quota=self.quota(omp={"remaining": 0.0})).service.name, "claude")

    def test_api_only_is_a_kind_and_only_omp_takes_it(self):
        self.assertIn("api-only", r.KINDS)
        self.assertEqual([s.name for s in r.SERVICES if s.eligible("api-only")], ["omp"])
        c = r.route("api-only", quota=self.quota())
        self.assertIsNotNone(c)
        self.assertEqual(c.service.name, "omp")
        self.assertIn("claude", c.model)
        self.assertEqual(c.kind, "api-only")

    def test_api_only_ignores_the_acp_readiness_probe(self):
        """api-only is the caller's own API call, so a broken omp login does not block it."""
        with mock.patch.dict(os.environ, {"ROUTE_AGENT_OMP_READY": "0"}):
            self.assertEqual(r.route("api-only", quota=self.quota()).service.name, "omp")

    def test_omp_gets_code_slices_so_the_credits_are_spent(self):
        # Every other code pool at its floor: omp, with the grant untouched, takes the slice.
        q = {name: {"remaining": 0.0} for name in IDLE}
        q["claude"] = {"remaining": 10.0}
        q = self.quota(**{k: v for k, v in q.items()})
        c = r.route("code", quota=q)
        self.assertEqual(c.service.name, "omp")
        self.assertEqual(c.model, "anthropic/claude-sonnet-5-5 --effort high")

    def test_unspent_grant_far_ahead_of_an_even_spend_earns_the_burn_bonus(self):
        # 16 days of 30 left means an even spend leaves 53.3%; 99.7% is about 46 points ahead.
        waste = r.grant_waste(99.7, self.EXPIRY, 30)
        self.assertAlmostEqual(waste, 99.7 - 100 * 16 / 30, delta=1.0)
        c = r.route("code", quota=self.quota())
        self.assertEqual(c.service.name, "omp")
        self.assertIn("burn before reset", c.why)

    def test_grant_waste_is_zero_when_spending_on_schedule_and_none_when_unknown(self):
        soon = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        self.assertAlmostEqual(r.grant_waste(10.0, soon, 30), 0.0, places=3)  # 3/30 left, holds 10%: on schedule
        self.assertGreater(r.grant_waste(60.0, soon, 30), 30.0)    # late in the month, far from spent
        self.assertIsNone(r.grant_waste(None, soon, 30))
        self.assertIsNone(r.grant_waste(50.0, None, 30))
        self.assertIsNone(r.grant_waste(50.0, soon, 0))

    def test_late_month_unspent_credits_win_code_over_a_healthy_pool(self):
        soon = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        q = self.quota(**{"omp": {"remaining": 90.0, "resets_at": soon,
                                  "window_minutes": None, "pace_ratio": None}})
        q["claude"] = {"remaining": 60.0}
        q["antigravity-claude"] = {"remaining": 0.0}
        c = r.route("code", quota=q)
        self.assertEqual(c.service.name, "omp")
        self.assertIn("burn before reset", c.why)

    def test_not_ready_omp_is_skipped_for_dispatch_kinds_but_not_for_api_only(self):
        with mock.patch.dict(os.environ, {"ROUTE_AGENT_OMP_READY": "0"}):
            for kind in ("code", "bulk"):
                c = r.route(kind, quota=self.quota())
                self.assertNotEqual(c.service.name if c else None, "omp", kind)

    def test_readiness_probe_reads_only_an_enabled_anthropic_login(self):
        import sqlite3
        import tempfile
        env = {k: v for k, v in os.environ.items() if k != "ROUTE_AGENT_OMP_READY"}
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, env, clear=True):
            os.environ["PI_CODING_AGENT_DIR"] = d
            self.assertFalse(r.omp_anthropic_ready())            # no agent.db
            con = sqlite3.connect(Path(d) / "agent.db")
            con.execute("create table auth_credentials (id integer primary key, provider text,"
                        " disabled_cause text)")
            con.execute("insert into auth_credentials(provider, disabled_cause) values"
                        " ('anthropic', 'oauth refresh failed')")
            con.commit()
            self.assertFalse(r.omp_anthropic_ready())            # disabled
            con.execute("insert into auth_credentials(provider, disabled_cause) values"
                        " ('anthropic', null)")
            con.commit()
            con.close()
            self.assertTrue(r.omp_anthropic_ready())


class TestQuotaFromAiuseAvailable(unittest.TestCase):
    """Pool state comes from `aiuse --available --json`, not the snapshot file (2026-10-20)."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        r._reset_aiuse_cache()
        self.addCleanup(r._reset_aiuse_cache)
        now = datetime.now(UTC)
        self.accounts = [
            {"provider": "codex", "age_seconds": 30,
             "windows": [{"label": "weekly", "remaining_percent": 60.0,
                          "headroom_percent": 60.0, "state": "ok"}]},
            {"provider": "omp", "age_seconds": 30, "windows": [
                {"label": "omp credits", "remaining_percent": 2.0, "headroom_percent": 2.0,
                 "state": "tight", "resets_at": (now + timedelta(days=19)).isoformat()}]},
        ]

    def payload(self, rows, **extra):
        return {"schema_version": "1.3", "age_seconds": 20.0, "fresh": True,
                "available": rows, **extra}

    def write(self, name, obj):
        path = self.tmp / name
        path.write_text(obj if isinstance(obj, str) else r.json.dumps(obj))
        return path

    def load(self, env):
        import io
        env = {"ROUTE_AGENT_OMP_READY": "0", **env}
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("AIUSE_SNAPSHOT", "ROUTE_AGENT_AIUSE_JSON", "ROUTE_AGENT_AIUSE",
                              "ROUTE_AGENT_AIUSE_BIN")}
        with mock.patch.dict(os.environ, {**clean, **env}, clear=True), \
                mock.patch.object(r, "_read_snapshot_file",
                                  return_value=(self.accounts, 60.0)), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            quota, age = r.load_snapshot()
        return quota, age, err.getvalue()

    def test_override_row_wins_over_the_snapshot_file(self):
        # the file says omp is nearly empty; aiuse's read-time override says 80% left,
        # and 3.8-only fields (expires_at, burn_before_reset, source) are tolerated
        row = {"provider": "omp", "age_seconds": 5, "expires_at": "2026-11-08T00:00:00Z",
               "burn_before_reset": True, "source": "override",
               "windows": [{"label": "omp credits", "remaining_percent": 80.0,
                            "headroom_percent": 80.0, "state": "ok", "source": "override",
                            "resets_at": "2026-11-08T00:00:00+00:00"}]}
        path = self.write("a.json", self.payload([row]))
        quota, age, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertEqual(quota["omp"]["remaining"], 80.0)
        self.assertEqual(r.QuotaSource.kind, "canned")
        self.assertEqual(age, 20.0)
        self.assertIsNone(r.quota_source_info()["fallback_reason"])

    def test_row_without_3_8_fields_still_loads(self):
        row = {"provider": "omp", "windows": [{"label": "omp credits", "headroom_percent": 55.0}]}
        path = self.write("a.json", self.payload([row]))
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertEqual(quota["omp"]["remaining"], 55.0)

    def test_pool_missing_from_available_reads_exhausted_not_unknown(self):
        path = self.write("a.json", self.payload([]))
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertEqual(quota["codex"]["remaining"], 0.0)
        self.assertEqual(quota["omp"]["remaining"], 0.0)

    def test_reading_expired_row_is_unknown(self):
        row = {"provider": "omp", "age_seconds": 5, "reading_expired": True,
               "windows": [{"label": "omp credits", "remaining_percent": 90.0,
                            "headroom_percent": 90.0, "state": "ok"}]}
        path = self.write("a.json", self.payload([row]))
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertIsNone(quota["omp"]["remaining"])

    def test_missing_aiuse_falls_back_to_the_file_and_says_so(self):
        with mock.patch.object(r.shutil, "which", return_value=None):
            quota, age, err = self.load({})
        self.assertEqual(quota["codex"]["remaining"], 60.0)
        self.assertEqual(r.QuotaSource.kind, "snapshot")
        self.assertIn("aiuse not on PATH", r.quota_source_info()["fallback_reason"])
        self.assertIn("aiuse not on PATH", err)

    def test_malformed_json_falls_back(self):
        path = self.write("bad.json", "not json {")
        quota, _, err = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertEqual(quota["codex"]["remaining"], 60.0)
        self.assertIn("malformed JSON", r.quota_source_info()["fallback_reason"])
        self.assertIn("malformed JSON", err)

    def test_payload_without_available_array_falls_back(self):
        path = self.write("odd.json", {"schema_version": "1.3"})
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertEqual(quota["codex"]["remaining"], 60.0)
        self.assertEqual(r.QuotaSource.kind, "snapshot")

    def fake_aiuse(self, body, rc):
        script = self.tmp / "aiuse"
        script.write_text(f"#!/bin/sh\ncat <<'EOF'\n{body}\nEOF\nexit {rc}\n")
        script.chmod(0o755)
        return str(script)

    def test_subprocess_path_runs_argv_and_accepts_exit_3(self):
        body = r.json.dumps(self.payload([]))
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_BIN": self.fake_aiuse(body, 3)})
        self.assertEqual(r.QuotaSource.kind, "aiuse")
        self.assertEqual(quota["codex"]["remaining"], 0.0)

    def test_failing_aiuse_falls_back(self):
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_BIN": self.fake_aiuse("boom", 1)})
        self.assertEqual(r.QuotaSource.kind, "snapshot")
        self.assertIn("exited 1", r.quota_source_info()["fallback_reason"])
        self.assertEqual(quota["codex"]["remaining"], 60.0)

    def test_pinned_snapshot_never_spawns_aiuse(self):
        with mock.patch.object(r.subprocess, "run") as run:
            self.load({"AIUSE_SNAPSHOT": str(self.tmp / "x.json")})
        run.assert_not_called()
        self.assertEqual(r.QuotaSource.kind, "snapshot")

    # -- hardening (adversary review 2026-10-20) --------------------------------

    def rows_payload(self, rows, **extra):
        return self.write("rows.json", self.payload(rows, **extra))

    def test_aiuse_off_never_spawns(self):
        marker = self.tmp / "spawned"
        script = self.tmp / "aiuse"
        script.write_text(f"#!/bin/sh\ntouch {shlex.quote(str(marker))}\necho '{{}}'\n")
        script.chmod(0o755)
        import io
        with mock.patch.dict(os.environ, {"ROUTE_AGENT_AIUSE": "off",
                                          "ROUTE_AGENT_AIUSE_BIN": str(script)}), \
                mock.patch.object(r, "_read_snapshot_file", return_value=([], None)), \
                contextlib.redirect_stderr(io.StringIO()):
            os.environ.pop("AIUSE_SNAPSHOT", None)
            os.environ.pop("ROUTE_AGENT_AIUSE_JSON", None)
            r.load_snapshot()
        self.assertFalse(marker.exists())

    def test_unparseable_shapes_fall_back_to_the_file(self):
        good_w = {"label": "w", "headroom_percent": 50.0}
        shapes = {
            "windows non-dict": [{"provider": "codex", "windows": [5]}],
            "windows object": [{"provider": "codex", "windows": {"a": 1}}],
            "provider list": [{"provider": ["codex"], "windows": [good_w]}],
        }
        for name, rows in shapes.items():
            with self.subTest(name):
                path = self.rows_payload(rows)
                quota, _, err = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
                self.assertEqual(r.QuotaSource.kind, "snapshot")
                self.assertRegex(r.quota_source_info()["fallback_reason"], "unparseable rows|invalid row")
                self.assertEqual(quota["codex"]["remaining"], 60.0)

    def test_non_numeric_percentage_reads_unknown_not_a_crash(self):
        row = {"provider": "codex", "windows": [{"label": "w", "headroom_percent": "lots",
                                                 "remaining_percent": "plenty"}]}
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(self.rows_payload([row]))})
        self.assertIsNone(quota["codex"]["remaining"])

    def test_invalid_utf8_falls_back(self):
        bad = self.tmp / "bad.json"
        bad.write_bytes(b'{"available": [], "x": "\xff\xfe"}')
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(bad)})
        self.assertEqual(r.QuotaSource.kind, "snapshot")
        self.assertIn("malformed JSON", r.quota_source_info()["fallback_reason"])
        script = self.tmp / "aiuse"
        script.write_bytes(b"#!/bin/sh\nprintf '{\"available\": [], \"x\": \"\\377\"}'\n")
        script.chmod(0o755)
        self.load({"ROUTE_AGENT_AIUSE_BIN": str(script)})
        self.assertEqual(r.QuotaSource.kind, "snapshot")

    def test_non_finite_percentages_never_read_as_headroom(self):
        for bad in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(bad):
                body = ('{"age_seconds": 5, "available": [{"provider": "copilot", "windows": '
                        f'[{{"label": "premium", "headroom_percent": {bad}}}]}}]}}')
                path = self.write("nan.json", body)
                quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
                self.assertIsNone(quota["copilot"]["remaining"])
                for kind in r.KINDS:
                    choice = r.route(kind, quota={**IDLE, **quota})
                    self.assertFalse(choice and choice.service.name == "copilot", kind)

    def test_percentages_are_clamped(self):
        row = {"provider": "codex", "windows": [{"label": "w", "headroom_percent": 250}]}
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(self.rows_payload([row]))})
        self.assertEqual(quota["codex"]["remaining"], 100.0)

    def test_unknown_or_nonfinite_age_does_not_zero_absent_pools_and_rows_are_stale(self):
        row = {"provider": "omp", "windows": [{"label": "c", "headroom_percent": 70.0}]}
        for name, extra in (("nan", {"age_seconds": float("nan")}),
                            ("none", {"age_seconds": None}),
                            ("negative", {"age_seconds": -5})):
            with self.subTest(name):
                payload = {"available": [row], **extra}
                path = self.write("age.json", r.json.dumps(payload))
                quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
                self.assertEqual(quota["codex"]["remaining"], 60.0)   # not zeroed
                self.assertIsNone(quota["omp"]["remaining"])           # stale row

    def test_stale_payload_does_not_zero_absent_pools(self):
        path = self.write("old.json", self.payload([], age_seconds=r.STALE_SOFT + 100))
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertEqual(quota["codex"]["remaining"], 60.0)

    def test_canned_is_labelled_and_logged_and_beats_off_and_pin(self):
        path = self.write("a.json", self.payload([]))
        quota, _, err = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path),
                                   "ROUTE_AGENT_AIUSE": "off",
                                   "AIUSE_SNAPSHOT": str(self.tmp / "pin.json")})
        self.assertEqual(r.QuotaSource.kind, "canned")
        self.assertIn("canned", err)
        self.assertEqual(quota["codex"]["remaining"], 0.0)

    def test_subprocess_with_valid_rows(self):
        body = r.json.dumps(self.payload([{"provider": "omp", "windows": [
            {"label": "c", "headroom_percent": 42.0, "state": "ok"}]}]))
        quota, age, _ = self.load({"ROUTE_AGENT_AIUSE_BIN": self.fake_aiuse(body, 0)})
        self.assertEqual(r.QuotaSource.kind, "aiuse")
        self.assertEqual(quota["omp"]["remaining"], 42.0)
        self.assertEqual(quota["codex"]["remaining"], 0.0)

    def test_timeout_falls_back_quickly(self):
        import time as _t
        script = self.tmp / "aiuse"
        script.write_text("#!/bin/sh\nexec sleep 5\n")
        script.chmod(0o755)
        t0 = _t.monotonic()
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_BIN": str(script),
                                 "ROUTE_AGENT_AIUSE_TIMEOUT": "0.5"})
        self.assertLess(_t.monotonic() - t0, 4.0)
        self.assertIn("timed out", r.quota_source_info()["fallback_reason"])
        self.assertEqual(quota["codex"]["remaining"], 60.0)

    def test_timeout_env_is_clamped(self):
        for bad in ("inf", "nan", "0", "-3", "999", "x"):
            with self.subTest(bad), mock.patch.dict(os.environ, {"ROUTE_AGENT_AIUSE_TIMEOUT": bad}):
                self.assertEqual(r._aiuse_timeout(), 20.0)
        with mock.patch.dict(os.environ, {"ROUTE_AGENT_AIUSE_TIMEOUT": "7"}):
            self.assertEqual(r._aiuse_timeout(), 7.0)

    def test_spawn_is_memoised_only_within_the_ttl(self):
        body = r.json.dumps(self.payload([]))
        exe = self.fake_aiuse(body, 0)
        clock = [1000.0]
        with mock.patch.object(r.time, "monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(r.subprocess, "run", wraps=r.subprocess.run) as run:
            self.load({"ROUTE_AGENT_AIUSE_BIN": exe})
            clock[0] += r.AIUSE_MEMO_TTL - 1
            self.load({"ROUTE_AGENT_AIUSE_BIN": exe})
            self.assertEqual(run.call_count, 1)
            clock[0] += 2
            self.load({"ROUTE_AGENT_AIUSE_BIN": exe})
            self.assertEqual(run.call_count, 2)

    def counting_aiuse(self):
        counter = self.tmp / "count"
        counter.write_text("0")
        script = self.tmp / "aiuse"
        script.write_text(
            "#!/bin/sh\n"
            f"n=$(cat {shlex.quote(str(counter))}); n=$((n+1)); echo $n > {shlex.quote(str(counter))}\n"
            "cat <<EOF\n"
            '{"age_seconds": 5, "available": [{"provider": "omp", "age_seconds": 5, "windows": '
            '[{"label": "c", "headroom_percent": $((n*10))}]}]}\n'
            "EOF\n")
        script.chmod(0o755)
        return str(script)

    def test_changing_reading_is_new_after_the_ttl_and_aged_within_it(self):
        exe = self.counting_aiuse()
        clock = [1000.0]
        with mock.patch.object(r.time, "monotonic", side_effect=lambda: clock[0]):
            q1, age1, _ = self.load({"ROUTE_AGENT_AIUSE_BIN": exe})
            self.assertEqual(q1["omp"]["remaining"], 10.0)
            self.assertEqual(age1, 5.0)
            clock[0] += 20
            q2, age2, _ = self.load({"ROUTE_AGENT_AIUSE_BIN": exe})
            self.assertEqual(q2["omp"]["remaining"], 10.0)      # the old reading ...
            self.assertEqual(age2, 25.0)                         # ... aged by the elapsed time
            clock[0] += 20
            q3, age3, _ = self.load({"ROUTE_AGENT_AIUSE_BIN": exe})
            self.assertEqual(q3["omp"]["remaining"], 20.0)      # a fresh spawn
            self.assertEqual(age3, 5.0)

    def test_cached_reading_goes_stale_as_it_ages(self):
        r._AIUSE_MEMO.clear()
        cached = {"age_seconds": r.STALE_SOFT - 5, "available": [
            {"provider": "omp", "age_seconds": r.STALE_SOFT - 5,
             "windows": [{"label": "c", "headroom_percent": 70.0}]}]}
        aged, _ = r._aged_copy((cached, "x"), 10)
        self.assertEqual(aged["available"][0]["age_seconds"], r.STALE_SOFT + 5)
        self.assertEqual(cached["available"][0]["age_seconds"], r.STALE_SOFT - 5)  # untouched

    def test_failures_are_memoised_no_longer_than_the_ttl(self):
        clock = [1000.0]
        exe = self.fake_aiuse("boom", 1)
        with mock.patch.object(r.time, "monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(r.subprocess, "run", wraps=r.subprocess.run) as run:
            self.load({"ROUTE_AGENT_AIUSE_BIN": exe})
            self.load({"ROUTE_AGENT_AIUSE_BIN": exe})
            self.assertEqual(run.call_count, 1)
            clock[0] += r.AIUSE_MEMO_TTL + 1
            self.load({"ROUTE_AGENT_AIUSE_BIN": exe})
            self.assertEqual(run.call_count, 2)

    # -- the available-row contract: top-level fields, windows[] optional (Codex P1) ----------

    FAILOVER_FIXTURE_ROWS = [   # tests/test_failover.py AIUSE, no windows[]; age added (see below)
        {"provider": "opencode-go", "pool_family": None, "usable_now": True,
         "headroom_percent": 8.0},
        {"provider": "claude", "pool_family": "default", "usable_now": True,
         "headroom_percent": 20.0},
        {"provider": "claude", "pool_family": "fable", "usable_now": True,
         "headroom_percent": 2.5},
        {"provider": "antigravity", "pool_family": "gemini", "usable_now": True,
         "headroom_percent": 16.0},
        {"provider": "antigravity", "pool_family": "claude_gpt", "usable_now": False,
         "headroom_percent": 0},
    ]

    def test_rows_without_windows_follow_the_contract_fields(self):
        # a payload with no age at all reads stale by design, so the fixture carries one
        path = self.rows_payload(self.FAILOVER_FIXTURE_ROWS)
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertEqual(quota["claude"]["remaining"], 20.0)
        self.assertEqual(quota["claude"]["sublimits"], {"fable": 2.5})
        self.assertEqual(quota["opencode-go"]["remaining"], 8.0)
        self.assertEqual(quota["antigravity"]["remaining"], 16.0)
        self.assertEqual(quota["antigravity-claude"]["remaining"], 0.0)

    def test_plan_refuses_the_pools_under_min_headroom(self):
        path = self.rows_payload(self.FAILOVER_FIXTURE_ROWS)
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        quota = {**{k: v for k, v in quota.items()}}
        for kind in ("code", "bulk"):
            choice = r.route(kind, quota=quota, min_headroom=25)
            for refused in ("claude", "opencode-go", "antigravity", "antigravity-claude"):
                self.assertFalse(choice and choice.service.name == refused, (kind, refused))

    def test_row_with_windows_keeps_detail_and_the_tighter_remaining(self):
        row = {"provider": "codex", "usable_now": True, "headroom_percent": 40.0,
               "binding_window": "weekly",
               "windows": [{"label": "5-hour", "headroom_percent": 55.0, "pace_ratio": 0.5,
                            "resets_at": "2026-10-25T00:00:00+00:00", "window_minutes": 300},
                           {"label": "weekly", "headroom_percent": 40.0}]}
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(self.rows_payload([row]))})
        self.assertEqual(quota["codex"]["remaining"], 40.0)
        self.assertEqual(quota["codex"]["windows"], {"weekly": 40.0, "5-hour": 55.0})
        # windows tighter than the top-level field tighten, never loosen
        row2 = dict(row, headroom_percent=90.0)
        quota2, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(self.rows_payload([row2]))})
        self.assertEqual(quota2["codex"]["remaining"], 40.0)

    def test_usable_now_false_reads_zero_whatever_the_headroom(self):
        row = {"provider": "codex", "usable_now": False, "headroom_percent": 60.0}
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(self.rows_payload([row]))})
        self.assertEqual(quota["codex"]["remaining"], 0.0)

    def test_row_carries_binding_window_and_operator_gate(self):
        row = {"provider": "omp", "usable_now": True, "headroom_percent": 33.0,
               "binding_window": "omp credits", "available_at": None,
               "requires_operator_approval": True}
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(self.rows_payload([row]))})
        self.assertEqual(quota["omp"]["remaining"], 33.0)
        self.assertEqual(quota["omp"]["binding_window"], "omp credits")
        self.assertTrue(quota["omp"]["requires_operator_approval"])

    def test_live_aiuse_matches_the_file_read(self):
        # opt-in: spawns the host's real aiuse and reads ~/.cache/aiuse (conftest keeps the
        # suite off both), and an hourly refresh between the two reads can differ
        if os.environ.get("ROUTE_AGENT_LIVE_TESTS") != "1":
            self.skipTest("set ROUTE_AGENT_LIVE_TESTS=1 to compare against the live aiuse")
        import shutil as _sh
        import subprocess as _sp
        exe = _sh.which("aiuse")
        snap = Path.home() / ".cache/aiuse/snapshots/latest.json"
        if not exe or not snap.is_file():
            self.skipTest("no live aiuse on this host")
        proc = _sp.run([exe, "--available", "--json"], capture_output=True, timeout=30)
        if proc.returncode not in (0, 3):
            self.skipTest("aiuse --available failed")
        live = self.tmp / "live.json"
        live.write_bytes(proc.stdout)
        payload = r.json.loads(proc.stdout)
        in_payload = {r.pool_service(row["provider"], row.get("pool_family"))
                      for row in payload.get("available", [])}
        noted = {n.get("provider") for n in payload.get("agent_notes") or []}
        got, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(live)})
        want, _ = self.fileonly(snap)
        for key, info in want.items():
            if key in in_payload and key not in noted and got[key].get("remaining") is not None \
                    and info.get("remaining") is not None:
                self.assertAlmostEqual(got[key]["remaining"], info["remaining"], delta=3.0,
                                       msg=key)

    # -- adversary round 4 ------------------------------------------------------------------

    def test_foreign_family_windows_never_create_or_loosen_another_pool(self):
        exhausted = {"state": "exhausted", "headroom_percent": 0.0}
        self.accounts = [
            {"provider": "cursor", "age_seconds": 30, "windows": [
                {"label": "auto", "pool_family": "auto", **exhausted},
                {"label": "tp", "pool_family": "third_party", "headroom_percent": 50.0}]},
            {"provider": "antigravity", "age_seconds": 30, "windows": [
                {"label": "g", "pool_family": "gemini", "headroom_percent": 80.0},
                {"label": "cg", "pool_family": "claude_gpt", **exhausted}]},
        ]
        rows = [
            {"provider": "cursor", "pool_family": "third_party", "usable_now": True,
             "headroom_percent": 50.0, "windows": [
                 {"label": "tp", "pool_family": "third_party", "headroom_percent": 50.0},
                 {"label": "auto", "pool_family": "auto", "headroom_percent": 63.5}]},
            {"provider": "antigravity", "pool_family": "gemini", "usable_now": True,
             "headroom_percent": 80.0, "windows": [
                 {"label": "g", "pool_family": "gemini", "headroom_percent": 80.0},
                 {"label": "cg", "pool_family": "claude_gpt", "headroom_percent": 70.0}]},
        ]
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(self.rows_payload(rows))})
        self.assertEqual(quota["cursor-auto"]["remaining"], 0.0)
        self.assertEqual(quota["antigravity-claude"]["remaining"], 0.0)

    def test_foreign_window_may_tighten_an_existing_pool(self):
        rows = [
            {"provider": "antigravity", "pool_family": "gemini", "usable_now": True,
             "headroom_percent": 80.0, "windows": [
                 {"label": "cg", "pool_family": "claude_gpt", "headroom_percent": 10.0}]},
            {"provider": "antigravity", "pool_family": "claude_gpt", "usable_now": True,
             "headroom_percent": 60.0},
        ]
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(self.rows_payload(rows))})
        self.assertEqual(quota["antigravity-claude"]["remaining"], 10.0)

    def test_fable_cap_merges_to_the_tighter_in_either_order(self):
        fable = {"provider": "claude", "pool_family": "fable", "usable_now": True,
                 "headroom_percent": 2.0}
        default = {"provider": "claude", "pool_family": "default", "usable_now": True,
                   "headroom_percent": 30.0, "windows": [
                       {"label": "w", "pool_family": "default", "headroom_percent": 30.0},
                       {"label": "fable", "pool_family": "fable",
                        "quota_scope": "model_sublimit", "max_share_of_parent_percent": 50,
                        "headroom_percent": 45.0}]}
        for rows in ([fable, default], [default, fable]):
            quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(self.rows_payload(rows))})
            self.assertEqual(quota["claude"]["sublimits"], {"fable": 2.0})
            self.assertEqual(quota["claude"]["remaining"], 30.0)

    def test_stale_row_with_an_exhausted_window_reads_zero(self):
        row = {"provider": "codex", "age_seconds": r.STALE_SOFT + 100, "windows": [
            {"label": "w", "state": "exhausted", "headroom_percent": 0.0}]}
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(self.rows_payload([row]))})
        self.assertEqual(quota["codex"]["remaining"], 0.0)

    def test_non_true_usable_now_reads_zero(self):
        for val in ("false", 0, None, "no"):
            with self.subTest(val):
                row = {"provider": "codex", "usable_now": val, "headroom_percent": 60.0}
                quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON":
                                         str(self.rows_payload([row]))})
                self.assertEqual(quota["codex"]["remaining"], 0.0)

    # -- Codex P2: excluded[] ------------------------------------------------------------

    def test_excluded_pool_without_a_snapshot_row_reads_zero_and_is_never_routed(self):
        path = self.rows_payload([self.GOOD_ROW], excluded=[
            {"provider": "zai", "pool_family": None, "reason": "operator"}])
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertEqual(quota["zai"]["remaining"], 0.0)
        self.assertTrue(quota["zai"]["excluded"])
        for kind in r.KINDS:
            choice = r.route(kind, quota={**IDLE, **quota})
            self.assertFalse(choice and choice.service.name == "zai", kind)

    def test_excluded_pool_with_a_snapshot_row_reads_zero(self):
        path = self.rows_payload([{"provider": "codex", "usable_now": True,
                                   "headroom_percent": 60.0}],
                                 excluded=[{"provider": "codex"}])
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertEqual(quota["codex"]["remaining"], 0.0)

    def test_excluded_sublimit_family_caps_only_that_model(self):
        path = self.rows_payload(
            [{"provider": "claude", "pool_family": "default", "usable_now": True,
              "headroom_percent": 30.0}],
            excluded=[{"provider": "claude", "pool_family": "fable"}])
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertEqual(quota["claude"]["remaining"], 30.0)
        self.assertEqual(quota["claude"]["sublimits"]["fable"], 0.0)

    def test_invalid_excluded_rows_are_ignored_not_a_fallback(self):
        path = self.rows_payload([self.GOOD_ROW], excluded=[
            "junk", {"provider": 3}, {"provider": ""}, {"provider": "zai", "pool_family": 7}])
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertEqual(r.QuotaSource.kind, "canned")
        self.assertEqual(quota["omp"]["remaining"], 70.0)
        self.assertNotIn("zai", quota)

    def test_excluded_is_not_consulted_on_the_file_fallback(self):
        path = self.rows_payload(["junk"], excluded=[{"provider": "zai"}])
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertEqual(r.QuotaSource.kind, "snapshot")
        self.assertNotIn("zai", quota)

    def test_excluded_is_not_applied_from_a_stale_payload(self):
        path = self.rows_payload([], excluded=[{"provider": "zai"}], fresh=False)
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertNotIn("zai", quota)

    def test_windowless_headroom_is_rounded_like_the_windowed_form(self):
        row = {"provider": "codex", "usable_now": True, "headroom_percent": 5.345454545}
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(self.rows_payload([row]))})
        self.assertEqual(quota["codex"]["remaining"], 5.3)

    def fileonly(self, snap):
        import io
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("ROUTE_AGENT_AIUSE_JSON", "ROUTE_AGENT_AIUSE")}
        with mock.patch.dict(os.environ, {**clean, "AIUSE_SNAPSHOT": str(snap),
                                          "ROUTE_AGENT_OMP_READY": "0"}, clear=True), \
                contextlib.redirect_stderr(io.StringIO()):
            return r.load_snapshot()

    # -- Codex P2s: the payload's `fresh` marker, and row validation ------------------------

    GOOD_ROW = {"provider": "omp", "usable_now": True, "headroom_percent": 70.0}

    def test_fresh_false_reads_every_row_unknown_and_zeroes_nothing(self):
        path = self.write("f.json", self.payload([self.GOOD_ROW], fresh=False, age_seconds=5))
        quota, age, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertIsNone(quota["omp"]["remaining"])
        self.assertEqual(quota["codex"]["remaining"], 60.0)        # absent pool not zeroed
        self.assertGreater(age, r.STALE_SOFT)
        self.assertIn("fresh=False", r.quota_source_info()["detail"])

    def test_fresh_true_with_young_age_behaves_as_before(self):
        path = self.write("f.json", self.payload([self.GOOD_ROW], fresh=True, age_seconds=5))
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertEqual(quota["omp"]["remaining"], 70.0)
        self.assertEqual(quota["codex"]["remaining"], 0.0)

    def test_no_fresh_key_uses_the_age_rule(self):
        base = {"available": [self.GOOD_ROW]}
        young = self.write("y.json", r.json.dumps({**base, "age_seconds": 5}))
        old = self.write("o.json", r.json.dumps({**base, "age_seconds": r.STALE_SOFT + 60}))
        q_young, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(young)})
        q_old, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(old)})
        self.assertEqual(q_young["omp"]["remaining"], 70.0)
        self.assertIsNone(q_old["omp"]["remaining"])

    def test_invalid_row_falls_back_to_the_file_with_nothing_zeroed(self):
        bad_rows = {
            "string row": [self.GOOD_ROW, "junk"],
            "no provider": [self.GOOD_ROW, {"usable_now": True, "headroom_percent": 50}],
            "empty provider": [self.GOOD_ROW, {"provider": ""}],
            "list provider": [self.GOOD_ROW, {"provider": ["codex"]}],
            "bad family": [self.GOOD_ROW, {"provider": "codex", "pool_family": 3}],
        }
        for name, rows in bad_rows.items():
            with self.subTest(name):
                quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON":
                                         str(self.rows_payload(rows))})
                self.assertEqual(r.QuotaSource.kind, "snapshot")
                self.assertIn("invalid row", r.quota_source_info()["fallback_reason"])
                self.assertEqual(quota["codex"]["remaining"], 60.0)

    def test_huge_integer_percentage_reads_unknown_not_a_crash(self):
        body = ('{"age_seconds": 5, "available": [{"provider": "codex", "age_seconds": 1' + "0" * 400
                + ', "windows": [{"label": "w", "headroom_percent": 1' + "0" * 400 + "}]}]}")
        path = self.write("huge.json", body)
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertIsNone(quota["codex"]["remaining"])


class TestGovernorHold(unittest.TestCase):
    """2026-10-23: bin/claude-fleet-governor writes `level`; while it says tight or critical (and is under
    30 min old) the Claude subscription is an exhausted pool for code/bulk/research/mechanical, and
    judgment prefers omp's API credits. `plan --kind code` had printed `claude 30% left` while the
    5-hour window was projected to run out before its reset."""

    QUOTA: ClassVar[dict[str, Any]] = {**IDLE, "claude": {"remaining": 30.0}, "omp": {"remaining": 90.0}}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "fleet-governor.json"
        patcher = mock.patch.dict(os.environ, {"CLAUDE_GOVERNOR_STATE": str(self.path),
                                               "ROUTE_AGENT_OMP_READY": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        # no `acp-run --list` subprocess per route(): the curated roster is enough here
        patcher = mock.patch.object(r, "acp_list_output", return_value="")
        patcher.start()
        self.addCleanup(patcher.stop)

    def state(self, level, age_min=5, **over):
        body = {"level": level, "checked_at": (datetime.now(UTC) - timedelta(minutes=age_min)).isoformat(),
                "windows": {"five_hour": {"label": "Claude Code 5-hour", "used": 70.0, "level": level,
                                          "projected_at_reset": 116.0, "resets_at": "2026-10-23T14:59:59Z"}}}
        body.update(over)
        self.path.write_text(json.dumps(body))

    def test_without_state_claude_is_still_chosen_for_code(self):
        # a missing state file holds nothing: claude stays in the roster for judgment (omp, eligible since the quota
        # guard's routing change, may rank first: claude is the choice or an alternative)
        choice = r.route("judgment", quota=self.QUOTA)
        self.assertIn("claude", {choice.service.name, *choice.alternatives})
        self.assertIsNone(r.governor_hold())

    def test_tight_and_critical_never_pick_claude_for_the_four_kinds(self):
        for level in ("tight", "critical"):
            self.state(level)
            for kind in ("code", "bulk", "research", "mechanical"):
                with self.subTest(level=level, kind=kind):
                    choice = r.route(kind, quota=self.QUOTA)
                    self.assertIsNotNone(choice)
                    self.assertNotEqual(choice.service.name, "claude")
                    self.assertNotIn("claude", choice.alternatives)
                    self.assertIn(f"claude skipped: Claude subscription {level}", choice.why)
                    self.assertIn("5-hour 70% used", choice.why)

    def test_plan_never_dispatches_claude_while_held(self):
        self.state("critical")
        rows = r.plan(["code", "code", "research", "bulk", "mechanical"], quota=self.QUOTA)
        self.assertTrue(all(c is not None and c.service.name != "claude" for _, c in rows))
        self.assertFalse(any(c.dispatch.startswith("acp-dispatch claude") for _, c in rows))

    def test_judgment_prefers_omp_opus_on_api_credits(self):
        self.state("tight")
        choice = r.route("judgment", quota=self.QUOTA)
        self.assertEqual(choice.service.name, "omp")
        self.assertEqual(choice.model, "anthropic/claude-opus-5-5 --effort high")
        self.assertEqual(choice.dispatch, "acp-dispatch omp --model anthropic/claude-opus-5-5 --effort high --kind judgment")
        self.assertIn("off the subscription", choice.why)

    def test_judgment_falls_back_to_claude_when_omp_cannot_take_it(self):
        self.state("tight")
        for label, quota, env in (("omp not logged in", self.QUOTA, {"ROUTE_AGENT_OMP_READY": "0"}),
                                  ("omp credits spent", {**self.QUOTA, "omp": {"remaining": 3.0}}, {})):
            with self.subTest(label), mock.patch.dict(os.environ, env):
                self.assertEqual(r.route("judgment", quota=quota).service.name, "claude")

    def test_judgment_does_not_force_an_ineligible_omp(self):
        """Codex pass 7 on PR 31, P2: a retired omp, or one without the judgment capability, is not preferred just
        because the governor holds Claude."""
        self.state("tight")
        original = r.Service.eligible
        with mock.patch.object(r.Service, "eligible",
                               lambda self, kind, quota=None: self.name != "omp" and original(self, kind, quota)):
            choice = r.route("judgment", quota=self.QUOTA)
        self.assertNotEqual(choice.service.name, "omp")

    def test_frontier_routes_as_before(self):
        before = r.route("frontier", quota=self.QUOTA).service.name
        self.state("critical")
        self.assertEqual(r.route("frontier", quota=self.QUOTA).service.name, before)

    def test_ok_stale_and_unreadable_state_hold_nothing(self):
        self.state("ok")
        self.assertIsNone(r.governor_hold())
        self.state("critical", age_min=31)
        self.assertIsNone(r.governor_hold())
        self.state("stale")
        self.assertIsNone(r.governor_hold())
        self.path.write_text("{not json")
        self.assertIsNone(r.governor_hold())
        self.path.write_text(json.dumps({"level": "tight"}))           # no checked_at: not fresh
        self.assertIsNone(r.governor_hold())

    def test_the_leads_manual_state_file_holds_nothing(self):
        self.path.write_text(json.dumps({"note": "manual", "window_resets_at": "2026-10-23T14:59:59Z",
                                         "downshifted": {"955e2b2": "claude-opus-5-5"}}))
        self.assertIsNone(r.governor_hold())

    def test_unrouted_reason_names_the_hold(self):
        self.state("critical")
        everything_else_full = {name: {"remaining": 0.0} for name in IDLE}
        self.assertIn("Claude subscription critical", r.unrouted_why("code", everything_else_full))

    def test_cli_plan_prints_the_reason(self):
        self.state("critical")
        out = io.StringIO()
        err = io.StringIO()
        with (contextlib.redirect_stdout(out), contextlib.redirect_stderr(err),
              mock.patch.object(r, "load_snapshot", return_value=(self.QUOTA, 60.0))):
            self.assertEqual(r.main(["plan", "--kinds", "code,judgment"]), 0)
        self.assertNotIn("acp-dispatch claude", out.getvalue())
        self.assertIn("Claude subscription critical", err.getvalue())
        self.assertIn("acp-dispatch omp --model anthropic/claude-opus-5-5", out.getvalue())


class TestSubstrateChain(unittest.TestCase):
    """Main-loop substrate picker: Flash-primary, cline↔opencode-go failover.

    The rule under test is the 2026-10-23 accident: a live cross-provider model
    switch broke the ◈ Dann tab. The chain keeps the model constant across a
    provider failover and ranks healthy -> lifeline -> tight -> exhausted.
    """

    @staticmethod
    def _opencode(windows: list[tuple[str, float, str]]) -> list[dict[str, Any]]:
        return [{"provider": "opencode-go",
                 "windows": [{"label": label, "remaining_percent": rem, "state": state}
                             for (label, rem, state) in windows]}]

    HEALTHY = [("OpenCode Go 5-hour", 98.0, "ok"),
               ("OpenCode Go weekly", 96.0, "ok"),
               ("OpenCode Go monthly", 0.6, "exhausted")]

    def test_healthy_opencode_go_is_primary_with_cline_fallback(self):
        chain = r.substrate_chain({}, self._opencode(self.HEALTHY))
        self.assertEqual(chain[0]["role"], "primary")
        self.assertEqual(chain[0]["provider"], "opencode")
        self.assertEqual(chain[0]["model"], "opencode-go/deepseek-v4.1-flash")
        self.assertEqual(chain[1]["provider"], "cline")   # unmeasured lifeline
        self.assertEqual(chain[2]["role"], "escalate")
        self.assertEqual(chain[2]["model"], "opencode-go/deepseek-v4-pro")

    def test_monthly_budget_does_not_bind_rolling_headroom(self):
        chain = r.substrate_chain({}, self._opencode(self.HEALTHY))
        self.assertAlmostEqual(chain[0]["remaining"], 96.0)   # min(5h, week), not the monthly
        self.assertAlmostEqual(chain[0]["monthly"], 0.6)
        self.assertEqual(chain[0]["role"], "primary")

    def test_tight_opencode_go_yields_to_the_unmeasured_lifeline(self):
        chain = r.substrate_chain({}, self._opencode([
            ("OpenCode Go 5-hour", 4.0, "ok"), ("OpenCode Go weekly", 5.0, "ok")]))
        self.assertEqual(chain[0]["provider"], "cline")
        self.assertEqual(chain[1]["provider"], "opencode")

    def test_exhausted_opencode_go_falls_to_the_lifeline(self):
        chain = r.substrate_chain({}, self._opencode([
            ("OpenCode Go 5-hour", 0.0, "exhausted"),
            ("OpenCode Go weekly", 0.0, "exhausted")]))
        self.assertEqual(chain[0]["provider"], "cline")
        self.assertEqual(chain[1]["provider"], "opencode")

    def test_unmeasured_quota_still_returns_the_full_chain(self):
        chain = r.substrate_chain({}, [])
        self.assertEqual([e["role"] for e in chain], ["primary", "fallback", "escalate"])
        # no data: original order preserved, so opencode-go stays primary
        self.assertEqual(chain[0]["provider"], "opencode")
