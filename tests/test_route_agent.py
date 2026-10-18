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
    "zai": {"remaining": 70.3}, "grok": {"remaining": 65.0},  # above its 60% reserve floor
    "cursor": {"remaining": 56.0}, "devin": {"remaining": 100.0},
    # The free half of opencode-zen. Present in the fixture because it is a
    # strong default for bulk, so leaving it out let it win tests by accident.
    "opencode-zen-free": {"remaining": 100.0},
    # 2026-10-15 rows: Cursor's Auto pool, the free SIPB models via crush and
    # the aiuse-disabled Alibaba plan; present so "drain every pool" fixtures
    # drain them too instead of leaving them unmeasured and routable.
    "cursor-auto": {"remaining": 56.0}, "crush": {"remaining": 100.0},
    "alibaba": {"remaining": 50.0},
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

    def test_judgment_never_reaches_codex_even_when_claude_is_tight(self):
        # antigravity at 100% must not win judgment work, and since 2026-10-18
        # codex is reached only through the explicit frontier kind.
        q = dict(IDLE, antigravity={"remaining": 100.0}, claude={"remaining": 20.0})
        self.assertEqual(r.route("judgment", quota=q).service.name, "claude")
        q = dict(IDLE, claude={"remaining": 5.0})
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
        except for the reserve pools, which fail closed without a fresh
        reading (review 2026-10-15): github and realtime-web stay queued."""
        for kind in r.KINDS:
            c = r.route(kind, quota={})
            if kind in ("github", "realtime-web"):
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

    def test_hermes_and_omp_are_never_discovered(self):
        q = {**IDLE, "hermes": {"remaining": 100.0}, "omp": {"remaining": 99.7}}
        names = {s.name for s in r.discover(q)}
        self.assertNotIn("hermes", names)
        self.assertNotIn("omp", names)
        for kind in r.KINDS:
            c = r.route(kind, quota=q)
            self.assertNotIn(c.service.name if c else None, {"hermes", "omp"})

    def test_reserve_floor_blocks_grok_and_copilot_below_sixty_percent(self):
        q = {name: {"remaining": 0.0} for name in (*IDLE, "antigravity-claude")}
        q["grok"] = {"remaining": 59.0}
        q["copilot"] = {"remaining": 59.0}
        self.assertIsNone(r.route("github", quota=q))
        self.assertIsNone(r.route("realtime-web", quota=q))
        # Generic kinds never reach the reserves, whatever their headroom.
        q["grok"] = {"remaining": 100.0}
        q["copilot"] = {"remaining": 100.0}
        for kind in ("research", "bulk", "code"):
            c = r.route(kind, quota=q)
            self.assertNotIn(c.service.name if c else None, {"grok", "copilot"}, kind)
        q["grok"] = {"remaining": 61.0}
        q["copilot"] = {"remaining": 61.0}
        self.assertEqual(r.route("github", quota=q).service.name, "copilot")
        self.assertEqual(r.route("realtime-web", quota=q).service.name, "grok")
        # A reserve with no reading at all fails closed.
        q["grok"] = {}
        self.assertIsNone(r.route("realtime-web", quota=q))
        self.assertIn("RESERVE", r.route("github", quota=q).why)

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
        self.assertEqual(c.dispatch, "acp-dispatch codex --model gpt-6-astra --effort high")


class TestFrontierConservative2026_10_18(unittest.TestCase):
    """Operator 2026-10-18: a wave of four astra slices emptied codex's 5-hour
    window; codex only for work that really needs astra, Fable xhigh almost never."""

    def test_codex_takes_only_the_frontier_kind(self):
        q = {name: {"remaining": 0.0} for name in (*IDLE, "antigravity-claude", "cursor-auto")}
        q["codex"] = {"remaining": 100.0}
        for kind in r.KINDS:
            c = r.route(kind, quota=q)
            if kind != "frontier":
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
        self.assertEqual(c.dispatch, "acp-dispatch cursor --model default")


class TestRoutingPolicyToml(unittest.TestCase):
    """config/routing.toml is the source of truth for curated routing data."""

    # Frozen expectation for three representative rows (behaviour-preserving refactor).
    EXPECTED: ClassVar[dict[str, dict[str, Any]]] = {
        "claude": {
            "cli": "claude (Opus 5.5 @ high for judgment; Fable only for frontier)",
            "good_at": {"judgment": 1, "frontier": 2},
            "billing": "subscription",
            "judgment_tier": True,
            "models": {"judgment": "opus --effort high", "frontier": "fable --effort high"},
            "pool": None, "max_parallel": 4, "agent": "", "burn_first": False,
        },
        "codex": {
            "cli": "codex (gpt-6-astra, frontier only)",
            "good_at": {"frontier": 1},
            "billing": "subscription",
            "judgment_tier": True,
            "models": {"frontier": "gpt-6-astra --effort high"},
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
