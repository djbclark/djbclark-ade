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
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import route_agent as r
from test_gates import close_frontier_baseline

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
        for name in ("opencode-zen",):
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
        # a bulk pool at 100% must not win judgment work. Since 2026-10-25 codex's judgment
        # row (rank 3, gpt-6.1-sol at high) is an eligible, lower-ranked pool while its quota is
        # plentiful: the router weighs pressure, burn and pace as well as rank, so it wins
        # when claude is short of room (it won at claude=15% too), never while claude has plenty.
        q = dict(IDLE, **{"cursor-auto": {"remaining": 100.0}}, claude={"remaining": 20.0})
        self.assertEqual(r.route("judgment", quota=q).service.name, "claude")
        q = dict(IDLE, claude={"remaining": 5.0})
        c = r.route("judgment", quota=q)
        self.assertEqual((c.service.name, c.model), ("codex", "gpt-6.1-sol --effort high"))
        q = dict(IDLE, claude={"remaining": 5.0}, codex={"remaining": r.PLENTY_MIN - 1})
        self.assertIsNone(r.route("judgment", quota=q))


@contextlib.contextmanager
def restorable_transport_policy():
    """Exercise retained ranking mechanics with explicitly restored transports.

    These synthetic fixtures do not describe the current operator policy;
    TestPiConsolidationPolicy checks the actual retirement decision separately.
    """
    legacy = {"omp", "opencode-go", "opencode-zen-free"}
    services = tuple(replace(s, retired=False) if s.name in legacy else s for s in r.SERVICES)
    with mock.patch.object(r, "SERVICES", services), mock.patch.object(
            r, "BY_NAME", {s.name: s for s in services}):
        yield


class RestorableTransportPolicyCase(unittest.TestCase):
    def setUp(self):
        self.enterContext(restorable_transport_policy())


class TestPiConsolidationPolicy(unittest.TestCase):
    def test_removed_transports_cannot_win_even_with_full_pools(self):
        for name in ("omp", "opencode-go", "opencode-zen-free", "opencode-zen"):
            service = r.BY_NAME[name]
            self.assertTrue(service.retired, name)
            for kind in r.KINDS:
                self.assertFalse(service.eligible(kind, any_headroom=True), (name, kind))
        for kind in r.KINDS:
            choice = r.route(kind, quota=IDLE)
            if choice:
                self.assertNotIn(choice.service.acp_agent, ("omp", "opencode"))
        self.assertIsNone(r.route("api-only", quota=IDLE))


class TestOpencodeGoTakesNoCode(RestorableTransportPolicyCase):
    """djbclark 2026-10-30: no code slice goes to opencode-go, however idle it is."""

    ONLY_GO = {name: {"remaining": 0.0} for name in IDLE} | {"opencode-go": {"remaining": 100.0}}

    def test_code_is_never_routed_to_opencode_go(self):
        choice = r.route("code", quota=self.ONLY_GO)
        self.assertTrue(choice is None or choice.service.name != "opencode-go")
        for _, c in r.plan(["code", "code", "code", "code"], quota=IDLE):
            self.assertTrue(c is None or c.service.name != "opencode-go")
        for _, c in r.plan(["code", "code", "code", "code"], quota=self.ONLY_GO):
            self.assertTrue(c is None or c.service.name != "opencode-go")

    def test_opencode_go_still_takes_bulk_and_mechanical(self):
        for kind in ("bulk", "mechanical"):
            c = r.route(kind, quota=self.ONLY_GO)
            self.assertIsNotNone(c, kind)
            self.assertEqual(c.service.name, "opencode-go")


class TestWasteBurning(RestorableTransportPolicyCase):
    def test_bulk_goes_to_idle_capacity(self):
        c = r.route("bulk", quota=IDLE)
        self.assertIn(c.service.name, {"cursor-auto", "opencode-go"})
        self.assertGreater(c.remaining, 90)

    def test_mechanical_prefers_the_free_tier(self):
        self.assertEqual(r.route("mechanical", quota=IDLE).service.name, "opencode-go")

    def test_headroom_shifts_bulk_away_from_a_drained_pool(self):
        drained = dict(IDLE, **{"opencode-go": {"remaining": 5.0}})
        self.assertNotEqual(r.route("bulk", quota=drained).service.name, "opencode-go")

    def test_min_headroom_excludes_tight_services(self):
        q = dict(IDLE, **{"opencode-go": {"remaining": 10.0}})
        c = r.route("bulk", quota=q, min_headroom=15.0)
        self.assertNotEqual(c.service.name, "opencode-go")

    def test_default_headroom_excludes_note_exhausted_pool(self):
        q = dict(IDLE, codex={"remaining": 0.0, "windows": {"weekly": 0.0}})
        self.assertNotEqual(r.route("code", quota=q).service.name, "codex")

class TestDegradation(RestorableTransportPolicyCase):
    def test_missing_quota_never_authorizes_a_family_scoped_route(self):
        """Unnamed legacy pools may degrade; named family pools require readings."""
        for kind in r.KINDS:
            c = r.route(kind, quota={})
            if kind in ("github", "realtime-web", "judgment"):
                self.assertIsNone(c, kind)
            elif c is not None:
                self.assertFalse(c.service.pool or c.service.pool_family or c.service.shares_pool)
                self.assertFalse(c.service.measured_only)

    def test_unknown_kind_rejected(self):
        with self.assertRaises(ValueError):
            r.route("vibes", quota=IDLE)

    def test_every_kind_is_servable(self):
        for kind in r.KINDS:
            if kind in ("github", "realtime-web"):      # copilot (2026-11-06) and the grok CLI (2026-11-07), their pools, retired
                self.assertIsNone(r.route(kind, quota=IDLE), kind)
                continue
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
        for curated in ("claude", "codex", "cursor-auto", "omp"):
            self.assertIn(curated, names)

    def test_unknown_provider_becomes_routable_conservatively(self):
        found = r.discover({**IDLE, "brand-new-vendor": {"remaining": 80.0}})
        svc = next(s for s in found if s.name == "brand-new-vendor")
        self.assertEqual(set(svc.good_at), {"bulk", "mechanical"})
        self.assertFalse(svc.judgment_tier, "unprofiled services must not take judgment")

    def test_aliases_do_not_become_second_services(self):
        """`claude-agent-teams` is claude's; a duplicate entry would dodge its constraints."""
        found = list(r.discover(IDLE))
        names = {s.name for s in found}
        for alias in ("claude-agent-teams", "openclaude"):
            self.assertNotIn(alias, names)
        for retired in ("antigravity", "copilot", "devin", "alibaba", "crush"):
            self.assertNotIn(retired, names, "a retired TUI's aiuse account is never a routable service")
        # Z.ai is an explicit measured Pi subscription profile, not its retired standalone client.
        zai = [s for s in found if s.name == "zai"]
        self.assertEqual(len(zai), 1)
        self.assertEqual(zai[0].acp_agent, "pi")
        self.assertTrue(zai[0].measured_only)
        self.assertEqual(r.ALIASES["openclaude"], "claude")

    def test_retired_tui_names_are_never_discovered(self):
        """Adapted from the old clinepass-alias test: a `cline` (or other retired TUI) account in aiuse, or a
        retired agent in acp-run's list, must not become a routable service."""
        names_in = ("cline", "agy", "qwen", "goose", "zcode", "pi", "crush", "muse", "kiro", "devin", "copilot", "aider", "venicecode")
        quota = {name: {"remaining": 100.0} for name in IDLE}
        quota.update({n: {"remaining": 100.0} for n in names_in})
        names = {s.name for s in r.discover(quota)}
        for n in names_in:
            self.assertNotIn(n, names)
        self.assertIn("clinepass", names)

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

    def test_retired_opencode_zen_free_is_not_routable(self):
        """It is the free half of opencode-zen, not a Hermes-only provider."""
        svc = r.BY_NAME["opencode-zen-free"]
        self.assertFalse(svc.hermes_only)
        self.assertTrue(svc.retired)
        self.assertFalse(svc.eligible("bulk"))

    def test_unmeasured_agents_remain_reachable_as_fallback(self):
        """All available agents should stay routable, just ranked last."""
        drained = {k: {"remaining": 0.0} for k in IDLE}
        with sources(PASEO_ROWS):                         # not whatever providers the host's Paseo lists
            choice = r.route("bulk", quota=drained)
        self.assertIsNotNone(choice, "roster agents should still provide a fallback")
        self.assertNotEqual(choice.service.name, "clinepass")


def prow(provider: str, status: str = "available", enabled: str = "Enabled") -> dict[str, str]:
    return {"provider": provider, "label": provider, "status": status, "enabled": enabled, "defaultMode": "default", "modes": ""}


PASEO_ROWS = [prow("claude"), prow("codex"), prow("opencode"), prow("fresh-provider"), prow("copilot"), prow("pi"),
              prow("antigravity"), prow("off-provider", enabled="Disabled"), prow("broken", status="error"),
              prow("gone", status="unavailable")]
FAKES = Path(__file__).resolve().parent / "fakes"


@contextlib.contextmanager
def sources(rows=()):
    """Pin the Paseo registry so a test sees only the provider rows it declares."""
    with mock.patch.object(r, "paseo_provider_rows", return_value=list(rows)):
        yield


@contextlib.contextmanager
def fake_paseo(**env: str):
    """route_agent's Paseo reads against tests/fakes/paseo, with its own state dir (no daemon, no network)."""
    with tempfile.TemporaryDirectory(prefix="ra-paseo-") as state, mock.patch.dict(os.environ, {
            "ROUTE_AGENT_PASEO": "on", "ROUTE_AGENT_PASEO_BIN": str(FAKES / "paseo"), "FAKE_PASEO_STATE": state,
            "ROUTE_AGENT_PI_BIN": str(FAKES / "pi"), "PI_CODING_AGENT_DIR": state, **env}), \
            mock.patch.object(r, "PASEO_LOADING_WAIT", 0.01):
        r._reset_paseo_cache()
        try:
            yield Path(state)
        finally:
            r._reset_paseo_cache()


class TestDiscoverySources(unittest.TestCase):
    """Discovery reflects what Paseo can dispatch now (`paseo provider ls --json`, 2026-11-07, slim-down E7): enabled and
    available rows only, through ALIASES, never a `never_route` provider; a `loading` row is retried, then absent."""

    def names(self):
        return {s.name for s in r.discover(IDLE)}

    def test_only_enabled_and_available_providers_are_routable(self):
        with sources(PASEO_ROWS):
            names = self.names()
        self.assertIn("fresh-provider", names)
        for absent in ("off-provider", "broken", "gone"):
            self.assertNotIn(absent, names)

    def test_paseo_rows_pass_through_aliases_and_never_route(self):
        """Paseo's `opencode` provider is the opencode-go pool, not a second entry; retired providers Paseo still lists
        (copilot, pi, antigravity) are never discovered."""
        with sources(PASEO_ROWS):
            names = self.names()
        self.assertNotIn("opencode", names)
        self.assertIn("opencode-go", names)
        for retired in ("copilot", "pi", "antigravity"):
            self.assertNotIn(retired, names)

    def test_paseo_failure_degrades_to_no_providers(self):
        r._reset_paseo_cache()
        with mock.patch.object(r.subprocess, "run", side_effect=OSError("gone")), \
                mock.patch.dict(os.environ, {"ROUTE_AGENT_PASEO": "on", "ROUTE_AGENT_PASEO_BIN": "/fake/paseo"}):
            self.assertEqual(r.paseo_providers(), set())
        r._reset_paseo_cache()
        with mock.patch.object(r.subprocess, "run", side_effect=r.subprocess.TimeoutExpired("paseo", 15)), \
                mock.patch.dict(os.environ, {"ROUTE_AGENT_PASEO": "on", "ROUTE_AGENT_PASEO_BIN": "/fake/paseo"}):
            self.assertEqual(r.paseo_providers(), set())
        with fake_paseo(FAKE_PASEO_PROVIDERS='{"not": "a list"}'):
            self.assertEqual(r.paseo_providers(), set())
        r._reset_paseo_cache()
        with mock.patch.dict(os.environ, {"ROUTE_AGENT_PASEO": "off"}):
            self.assertEqual(r.paseo_providers(), set())          # the suite's default: no spawn at all
        r._reset_paseo_cache()

    def test_provider_ls_is_read_once_per_process(self):
        with fake_paseo(FAKE_PASEO_PROVIDERS=json.dumps(PASEO_ROWS)) as state:
            first = r.paseo_providers()
            self.assertEqual(r.paseo_providers(), first)
            self.assertEqual({s.name for s in r.discover(IDLE)} >= {"fresh-provider"}, True)
            calls = [json.loads(x) for x in (state / "calls.jsonl").read_text().splitlines()]
            self.assertEqual(calls.count(["provider", "ls", "--json"]), 1)

    def test_the_fake_paseo_registry_is_read_and_filtered(self):
        rows = json.dumps(PASEO_ROWS)
        with fake_paseo(FAKE_PASEO_PROVIDERS=rows):
            self.assertEqual(r.paseo_providers(), {"claude", "codex", "opencode", "fresh-provider", "copilot", "pi",
                                                   "antigravity"})

    def test_loading_rows_are_retried_twice_then_absent_with_a_note(self):
        with fake_paseo(FAKE_PASEO_LOADING="2") as state:
            self.assertIn("claude", r.paseo_providers())           # loading, loading, available
            self.assertEqual((state / "provider-ls-count").read_text(), "3")
        err = io.StringIO()
        with fake_paseo(FAKE_PASEO_LOADING="3") as state, contextlib.redirect_stderr(err):
            self.assertEqual(r.paseo_providers(), set())           # still loading after the retries: absent
            self.assertEqual((state / "provider-ls-count").read_text(), "3")
        self.assertIn("still loading", err.getvalue())

    def test_provider_models_lists_ids_once_per_process(self):
        with fake_paseo(FAKE_PASEO_MODELS=json.dumps({"codex": ["gpt-6.1-sol", "gpt-6-luna"]})) as state:
            self.assertEqual(r.provider_models("codex"), ["gpt-6.1-sol", "gpt-6-luna"])
            self.assertEqual(r.provider_models("codex"), ["gpt-6.1-sol", "gpt-6-luna"])
            calls = [json.loads(x) for x in (state / "calls.jsonl").read_text().splitlines()]
            self.assertEqual(calls.count(["provider", "models", "codex", "--json"]), 1)
        with mock.patch.dict(os.environ, {"ROUTE_AGENT_PASEO": "off"}):
            r._reset_paseo_cache()
            self.assertIsNone(r.provider_models("codex"))

    PI_TABLE = ("provider     model              context  max-out  thinking  images\n"
                "antigravity  gemini-3.8-flash   1.0M     65.5K    yes       yes\n"
                "antigravity  gemini-4-argon     1.0M     65.5K    yes       yes\n"
                "cursor       composer-1         200K     64K      yes       no\n")

    def pi_paseo_list(self):
        return json.dumps({"pi": ["antigravity/gemini-3.8-flash", "antigravity/gemini-3.1-pro", "cursor/composer-2.5"]})

    def test_pi_models_follow_pis_own_catalog_where_pi_keeps_one(self):
        # 2026-11-10: Paseo's Pi list kept a model Pi dropped (gemini-3.1-pro) and omitted one Pi runs (gemini-4-argon).
        with fake_paseo(FAKE_PASEO_MODELS=self.pi_paseo_list(), FAKE_PI_LIST=self.PI_TABLE) as state:
            (state / "models-store.json").write_text(json.dumps({"antigravity": {"models": []}}))
            r._reset_paseo_cache()
            self.assertEqual(r.provider_models("pi"), [
                "cursor/composer-2.5",                       # live extension namespace: Paseo's list stands
                "antigravity/gemini-3.8-flash", "antigravity/gemini-4-argon"])

    def test_pi_models_are_paseos_when_pi_cannot_list_or_has_no_store(self):
        with fake_paseo(FAKE_PASEO_MODELS=self.pi_paseo_list()):          # fake pi exits 1
            self.assertEqual(r.provider_models("pi"), json.loads(self.pi_paseo_list())["pi"])
        with fake_paseo(FAKE_PASEO_MODELS=self.pi_paseo_list(), FAKE_PI_LIST=self.PI_TABLE):   # no models-store.json
            self.assertEqual(r.provider_models("pi"), json.loads(self.pi_paseo_list())["pi"])

    def test_pi_models_are_pis_when_paseo_cannot_say(self):
        with fake_paseo(FAKE_PI_LIST=self.PI_TABLE, ROUTE_AGENT_PASEO_BIN="/nonexistent/paseo"):
            self.assertEqual(r.provider_models("pi"), ["antigravity/gemini-3.8-flash", "antigravity/gemini-4-argon",
                                                       "cursor/composer-1"])

    def test_pi_models_do_not_touch_other_providers(self):
        with fake_paseo(FAKE_PASEO_MODELS=json.dumps({"codex": ["gpt-6-luna"]}), FAKE_PI_LIST=self.PI_TABLE):
            self.assertEqual(r.provider_models("codex"), ["gpt-6-luna"])

    def test_services_check_models_flags_a_suggestion_paseo_does_not_list(self):
        listed: dict[str, list[str]] = {}
        for s in r.SERVICES:                      # cursor-auto and cursor share the cursor provider
            listed[s.acp_agent] = sorted(set(listed.get(s.acp_agent, [])) | {m.split()[0] for m in s.models.values()})
        out = io.StringIO()
        with fake_paseo(FAKE_PASEO_MODELS=json.dumps(listed)), contextlib.redirect_stdout(out):
            self.assertEqual(r.main(["services", "--check-models"]), 0, out.getvalue())
        self.assertIn("every suggested model is listed", out.getvalue())
        listed["codex"] = [m for m in listed["codex"] if m != "gpt-6-astra"]
        out = io.StringIO()
        with fake_paseo(FAKE_PASEO_MODELS=json.dumps(listed)), contextlib.redirect_stdout(out):
            self.assertEqual(r.main(["services", "--check-models"]), 1)
        self.assertIn("MISSING codex frontier: gpt-6-astra", out.getvalue())
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"ROUTE_AGENT_PASEO": "off"}), contextlib.redirect_stdout(out):
            r._reset_paseo_cache()
            self.assertEqual(r.main(["services", "--check-models"]), 2)
        self.assertIn("paseo: ?", out.getvalue())


class TestPoolSplitIsGeneral(unittest.TestCase):
    """Any service can claim one pool family of its provider via `pool=`."""

    def test_any_declared_pool_is_split_and_undeclared_families_are_unknown(self):
        svc = r.Service("copilot-premium", "copilot", {"code": 20}, "subscription",
                        pool=("copilot", "premium"))
        with mock.patch.object(r, "SERVICES", r.SERVICES + (svc,)):
            self.assertEqual(r.pool_service("copilot", "premium"), "copilot-premium")
            self.assertEqual(r.pool_service("copilot", "chat"), None)
            self.assertEqual(r.pool_service("copilot", None), None)

    def test_claude_fable_sublimit_is_not_split(self):
        self.assertEqual(r.pool_service("claude", "fable"), "claude")


class TestDispatchUnattendedModes(unittest.TestCase):
    def test_each_provider_uses_its_native_unattended_mode(self):
        for service, model, mode in (
            ("claude", "sonnet --effort high", "bypassPermissions"),
            ("codex", "gpt-6.1-sol --effort high", "full-access"),
            ("antigravity-argon", "gemini-4-argon-high", "full-access"),
            ("zai", "zai/glm-5.3-flash --effort high", None),
            ("cursor-auto", "default", None),
        ):
            with self.subTest(service=service):
                argv = shlex.split(r.Choice(r.BY_NAME[service], 80, 1,
                                           model=model, kind="code").dispatch)
                if mode is None:
                    self.assertNotIn("--mode", argv)
                else:
                    self.assertEqual(argv[argv.index("--mode") + 1], mode)
                    self.assertEqual(argv.count("--mode"), 1)
                self.assertEqual(argv[argv.index("--label") + 1], "ade.kind=code")
                self.assertEqual(argv[-1], "--no-wait")
                if "--effort" in model:
                    self.assertEqual(argv[argv.index("--thinking") + 1], "high")

    def test_placeholder_dispatch_still_has_mode_and_pi_honors_configured_modes(self):
        argv = shlex.split(r.Choice(r.BY_NAME["codex"], 80, 1).dispatch)
        self.assertEqual(argv[argv.index("--mode") + 1], "full-access")
        with mock.patch.object(r, "DISPATCH_MODES", {"pi": "provider-native-mode"}):
            argv = shlex.split(r.Choice(r.BY_NAME["zai"], 80, 1,
                                       model="zai/glm-5.3-flash").dispatch)
            self.assertEqual(argv[argv.index("--mode") + 1], "provider-native-mode")


class TestQuotaFamilyIsolation(unittest.TestCase):
    """Sanitized shapes from aiuse schema 1.5, observed 2026-11-12."""

    @staticmethod
    def row(provider, family, left):
        return {"provider": provider, "pool_family": family, "usable_now": left > 1,
                "headroom_percent": left, "age_seconds": 60,
                "binding_window": family, "models_hint": "family-specific allowance",
                "windows": [{"label": family or "unnamed", "pool_family": family,
                             "remaining_percent": left, "headroom_percent": left,
                             "state": "ok" if left > 1 else "exhausted"}]}

    def test_canary_first_caps_each_blind_pool_at_one_and_prints_max(self):
        services = [r.Service(name, name, {"research": 1}, "subscription", max_parallel=4,
                              agent="antigravity" if name == "antigravity" else "pi",
                              models={"research": "zai/glm-5.3-flash"})
                    for name in ("antigravity", "openai_api", "zai")]
        services.append(r.Service("zai-alias", "alias", {"research": 1}, "subscription",
                                  shares_pool="zai", agent="pi", max_parallel=4,
                                  models={"research": "zai/glm-5.3-flash"}))
        quota = {s.name: {"remaining": 80} for s in services}
        with mock.patch.object(r, "discover", return_value=services), \
                mock.patch.object(r, "operator_disabled", return_value=set()), \
                mock.patch.object(r, "load_snapshot", return_value=(quota, 60)):
            rows = r.plan(["research"] * 6, quota=quota)
            names = [c.service.name for _, c in rows if c]
            self.assertEqual(sorted(names), ["antigravity", "openai_api", "zai"])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(r.main(["plan", "--kinds", "research,research", "--json"]), 0)
            self.assertEqual(json.loads(out.getvalue())["canary_pool_max"],
                             {"antigravity": 1, "openai_api": 1, "zai": 1})
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(r.main(["plan", "--kinds", "research"]), 0)
            self.assertIn("canary pool zai: max=1", out.getvalue())

    def test_dispatch_model_mapping_selects_explicit_policy_family(self):
        self.assertEqual(r.map_agent_to_provider("claude", "sonnet"), ("claude", "default"))
        self.assertEqual(r.map_agent_to_provider("claude", "fable"), ("claude", "default"))
        self.assertEqual(r.map_agent_to_provider("cursor", "composer-2.5"), ("cursor", "third_party"))
        self.assertEqual(r.map_agent_to_provider("pi", "cursor/composer-2.5"), ("cursor", "third_party"))
        self.assertEqual(r.dispatch_service_name("claude", "sonnet"), "claude")

    def test_cursor_grok_bot_cannot_fund_composer_or_auto(self):
        bot = self.row("cursor", "grok_bot", 82)
        for family in ("grok_bot", None, "unknown"):
            row = dict(bot, pool_family=family)
            q = r._providers_from_available([row], 60)
            for name in ("cursor", "cursor-auto"):
                self.assertNotIn(name, q)
                self.assertFalse(r.BY_NAME[name].eligible("research", q))
        windows = [self.row("cursor", f, 0)["windows"][0]
                   for f in ("total", "auto", "third_party", "on_demand")]
        q = r._providers_from_accounts([{"provider": "cursor", "windows": bot["windows"] + windows}], 60)
        self.assertEqual(q["cursor"]["remaining"], 0)
        self.assertEqual(q["cursor-auto"]["remaining"], 0)
        self.assertEqual(r._providers_from_available(
            [self.row("cursor", "third_party", 37)], 60)["cursor"]["remaining"], 37)

    def test_cursor_shared_total_still_constrains_each_child(self):
        windows = []
        for family, left in (("total", 0), ("auto", 80), ("third_party", 90)):
            w = self.row("cursor", family, left)["windows"][0]
            if family != "total":
                w["shared_pool_family"] = "total"
            windows.append(w)
        q = r._providers_from_accounts([{"provider": "cursor", "windows": windows}], 60)
        self.assertEqual(q["cursor"]["remaining"], 0)
        self.assertEqual(q["cursor-auto"]["remaining"], 0)

    def test_cursor_missing_declared_parent_is_unknown(self):
        w = self.row("cursor", "auto", 80)["windows"][0]
        w["shared_pool_family"] = "total"
        q = r._providers_from_accounts([{"provider": "cursor", "windows": [w]}], 60)
        self.assertIsNone(r.plenty_remaining(q["cursor-auto"]))
        self.assertFalse(r.BY_NAME["cursor-auto"].eligible("research", q))

    def test_paseo_provider_only_report_cannot_authorize_family_route(self):
        for provider in ("cursor", "antigravity"):
            rows = [{"sourceId": provider, "fetchedAt": datetime.now(UTC).isoformat(),
                     "report": {"status": "available", "windows": [
                         {"label": "usage", "remainingPct": 82}]}}]
            self.assertEqual(r.usage_from_paseo(rows), {})
            rows[0]["pool_family"] = "fable"
            self.assertEqual(r.usage_from_paseo(rows), {})

    def test_paseo_native_claude_defaults_only_missing_family(self):
        now = datetime(2026, 11, 12, 12, tzinfo=UTC)
        row = {"sourceId": "claude", "fetchedAt": now.isoformat(),
               "report": {"status": "available", "windows": [
                   {"label": "Weekly", "remainingPct": 23}]}}
        expected = r.usage_from_paseo([dict(row, pool_family="default")], now=now)
        self.assertEqual(expected["claude"]["remaining"], 23)
        self.assertEqual(r.usage_from_paseo([row], now=now), expected)
        self.assertEqual(r.usage_from_paseo([dict(row, pool_family=None)], now=now), expected)
        for family in ("fable", "unknown", "", "api"):
            with self.subTest(family=family):
                self.assertEqual(r.usage_from_paseo([dict(row, pool_family=family)], now=now), {})
        stale = dict(row, fetchedAt="2026-11-11T12:00:00+00:00")
        self.assertIsNone(r.usage_from_paseo([stale], now=now)["claude"]["remaining"])
        unavailable = dict(row, report={"status": "unavailable"})
        self.assertIsNone(r.usage_from_paseo([unavailable], now=now)["claude"]["remaining"])

    def test_argon_never_borrows_gemini_or_claude_gpt(self):
        for fold in (r._providers_from_available, r._providers_from_accounts):
            for family in ("gemini", "claude_gpt", None, "unknown"):
                with self.subTest(fold=fold.__name__, family=family):
                    q = fold([self.row("antigravity", family, 80)], 60)
                    self.assertNotIn("antigravity-argon", q)
                    self.assertFalse(r.BY_NAME["antigravity-argon"].eligible("frontier", q))
            q = fold([self.row("antigravity", "gemini", 57),
                      self.row("antigravity", "gemini_argon", 0),
                      self.row("antigravity", "claude_gpt", 24)], 60)
            self.assertEqual(q["antigravity-argon"]["remaining"], 0)
            self.assertEqual(fold([self.row("antigravity", "gemini_argon", 32)], 60)
                             ["antigravity-argon"]["remaining"], 32)

    def test_claude_default_and_fable_cap_are_not_interchangeable(self):
        default = self.row("claude", "default", 23)
        cap = {"pool_family": "fable", "label": "Fable", "quota_scope": "model_sublimit",
               "shared_pool_family": "default", "max_share_of_parent_percent": 50,
               "headroom_percent": 0, "remaining_percent": 0, "usable_now": False,
               "state": "exhausted"}
        default["model_sublimits"] = [cap]
        q = r._providers_from_available([default], 60)
        self.assertEqual(q["claude"]["remaining"], 23)
        self.assertEqual(q["claude"]["sublimits"]["fable"], 0)
        account = {"provider": "claude", "windows": default["windows"] + [cap]}
        q = r._providers_from_accounts([account], 60)
        self.assertEqual(q["claude"]["remaining"], 23)
        self.assertEqual(q["claude"]["sublimits"]["fable"], 0)
        for fold in (r._providers_from_available, r._providers_from_accounts):
            for family in ("fable", None, "unknown"):
                q = fold([self.row("claude", family, 80)], 60)
                self.assertIsNone(q.get("claude", {}).get("remaining"))
                self.assertFalse(r.BY_NAME["claude"].eligible("code", q))


class TestPlanWave(unittest.TestCase):
    """`plan` spreads one wave over pools and re-plans from live headroom."""

    Q: ClassVar[dict[str, Any]] = {**IDLE, "cursor-auto": {"remaining": 90.0}}

    def test_wave_respects_max_parallel_then_spills_to_the_next_pool(self):
        rows = r.plan(["code"] * 5, quota=self.Q)
        names = [c.service.name for _, c in rows]
        cap = next(s for s in r.SERVICES if s.name == "cursor-auto").max_parallel
        self.assertEqual(names[:cap], ["cursor-auto"] * cap)
        self.assertNotEqual(names[cap], "cursor-auto")

    def test_replan_follows_a_pool_that_just_drained(self):
        before = r.plan(["code"], quota=self.Q)[0][1].service.name
        after = r.plan(["code"], quota={**self.Q, "cursor-auto": {"remaining": 4.0}})[0][1].service.name
        self.assertEqual(before, "cursor-auto")
        self.assertNotEqual(after, "cursor-auto")

    def test_exclude_skips_a_service_that_just_failed(self):
        c = r.plan(["code"], quota=self.Q, exclude={"cursor-auto"})[0][1]
        self.assertNotEqual(c.service.name, "cursor-auto")

    def test_plan_applies_default_fifteen_percent_headroom(self):
        q = {**self.Q, "cursor-auto": {"remaining": 14.0}}
        c = r.plan(["code"], quota=q)[0][1]
        self.assertNotEqual(c.service.name, "cursor-auto")

    def test_plan_skips_note_exhausted_pool(self):
        q = {**self.Q, "codex": {"remaining": 0.0}}
        c = r.plan(["code"], quota=q)[0][1]
        self.assertIsNotNone(c)
        self.assertNotEqual(c.service.name, "codex")

    @mock.patch.dict(os.environ, {"ROUTE_AGENT_OMP_READY": "0"})   # omp-ready: TestOmpReadyRoster
    def test_no_room_comes_back_as_none_not_an_error(self):
        drained = {k: {"remaining": 1.0} for k in {*IDLE, "cursor-auto"}}
        rows = r.plan(["code"], quota=drained)
        self.assertIsNone(rows[0][1])

    def test_cli_plan_prints_one_numbered_line_per_slice(self):
        import contextlib
        import io
        buf = io.StringIO()
        with mock.patch.object(r, "load_snapshot", return_value=(self.Q, 60.0)), \
             contextlib.redirect_stdout(buf):
            self.assertEqual(r.main(["plan", "--kinds", "code,bulk"]), 0)
        lines = [line for line in buf.getvalue().strip().splitlines() if not line.startswith("canary pool ")]
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
            "provider": "cursor",
            "windows": [{
                "label": "Auto monthly",
                "pool_family": "auto",
                "remaining_percent": 47.6,
                "state": "exhausted",
            }],
        }]
        q = self.load(accts)
        self.assertEqual(q["cursor-auto"]["remaining"], 0.0)

    def test_zero_headroom_percent_counts_as_zero_remaining(self):
        """A window with headroom_percent == 0 counts as 0 remaining."""
        accts = [{
            "provider": "cursor",
            "windows": [{
                "label": "Auto monthly",
                "pool_family": "auto",
                "remaining_percent": 50.0,
                "headroom_percent": 0.0,
                "state": "ok",
            }],
        }]
        q = self.load(accts)
        self.assertEqual(q["cursor-auto"]["remaining"], 0.0)

    def test_old_reading_by_age_seconds_treated_as_unmeasured_none(self):
        """An account older than STALE_SOFT (25 min) has its headroom treated as None."""
        accts = [{
            "provider": "cursor",
            "age_seconds": 1800.0,  # 30 min > STALE_SOFT (1500s)
            "windows": [{
                "label": "Auto monthly",
                "pool_family": "auto",
                "remaining_percent": 90.0,
                "state": "ok",
            }],
        }]
        q = self.load(accts)
        self.assertIsNone(q["cursor-auto"]["remaining"])

    def test_old_reading_by_collected_at_treated_as_unmeasured_none(self):
        """An account whose collected_at is older than STALE_SOFT has headroom treated as None."""
        old_time = (datetime.now(UTC) - timedelta(minutes=35)).isoformat()
        accts = [{
            "provider": "cursor",
            "collected_at": old_time,
            "windows": [{
                "label": "Auto monthly",
                "pool_family": "auto",
                "remaining_percent": 90.0,
                "state": "ok",
            }],
        }]
        q = self.load(accts)
        self.assertIsNone(q["cursor-auto"]["remaining"])

    def test_old_reading_does_not_get_burn_first_bonus(self):
        """When headroom is None (unmeasured), burn_first bonus is not applied."""
        # claude has 30% headroom, cursor-auto is unmeasured (None)
        q = {**IDLE, "cursor-auto": {"remaining": None}, "claude": {"remaining": 30.0}}
        # Unmeasured: rank 14 + unmeasured pressure 5 and no bonus. Measured at
        # 90%: rank 14 + 0.25 - BURN_FIRST_BONUS. The gap must show the bonus.
        unmeasured = r.route("code", quota=q)
        measured = r.route("code", quota={**q, "cursor-auto": {"remaining": 90.0}})
        self.assertEqual(measured.service.name, "cursor-auto")
        if unmeasured.service.name == "cursor-auto":
            self.assertGreaterEqual(unmeasured.score - measured.score, r.BURN_FIRST_BONUS)

    def test_exhausted_state_on_old_reading_still_counts_as_zero(self):
        """An override on an older account reading still registers as 0.0 remaining (exhausted)."""
        accts = [{
            "provider": "cursor",
            "age_seconds": 2400.0,  # 40 min
            "windows": [{
                "label": "Auto monthly",
                "pool_family": "auto",
                "remaining_percent": 47.6,
                "state": "exhausted",
            }],
        }]
        q = self.load(accts)
        self.assertEqual(q["cursor-auto"]["remaining"], 0.0)



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

    def test_the_grok_cli_is_retired_and_grok_bot_is_never_a_target(self):
        """2026-11-07: the SuperGrok subscription was cancelled; grok-bot (Cursor-billed) stays but takes no slices."""
        self.assertNotIn("grok", r.BY_NAME)
        self.assertIsNone(r.map_agent_to_provider("grok", "grok-4.7"))
        q = {**{name: {"remaining": 0.0} for name in IDLE}, "grok": {"remaining": 100.0}, "grok-bot": {"remaining": 100.0}}
        names = {s.name for s in r.discover(q)}
        self.assertFalse({"grok", "grok-bot"} & names)
        for kind in r.KINDS:
            c = r.route(kind, quota=q)
            self.assertNotIn(c.service.name if c else None, ("grok", "grok-bot"), kind)

    def test_everyday_code_avoids_the_frontier_pools_when_others_have_room(self):
        q = {**IDLE, "cursor-auto": {"remaining": 75.0}}
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
                         "paseo run --provider codex/gpt-6-astra --thinking high --mode full-access "
                         "--label ade.kind=frontier --no-wait")


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

    def test_a_closed_baseline_puts_at_most_one_frontier_slice_on_each_pool(self):
        with mock.patch.dict(os.environ, self.gate_env(closed=True)):
            rows = r.plan(["frontier"] * 4, quota=IDLE)
        names = [c.service.name if c else None for _, c in rows]
        self.assertEqual(names, ["codex", "claude", None, None])

    def test_the_standing_baseline_puts_two_frontier_slices_on_claude_and_one_on_codex(self):
        with mock.patch.dict(os.environ, self.gate_env()):       # the shipped gates.toml copy, a fresh Claude reading
            rows = r.plan(["frontier"] * 4, quota=IDLE)
        names = [c.service.name if c else None for _, c in rows]
        self.assertEqual(names, ["codex", "claude", "claude", None])

    def test_judgment_slices_after_a_frontier_slice_stay_on_claude(self):
        rows = r.plan(["frontier", "judgment", "judgment"], quota=IDLE)
        self.assertEqual([c.service.name for _, c in rows], ["codex", "claude", "claude"])

    @staticmethod
    def claude_usage(claude: str | None, path: Path) -> Path | None:
        """A canned `paseo usage ls --json` with one Claude report: `fresh` (weekly 70% left, Fable 60%), `tight` (weekly 20%),
        `stale` (fetched 40 min ago), `unknown` (report unavailable, rejected 403); None: no report at all."""
        if claude is None:
            return None
        now = datetime.now(UTC)
        stamp = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
        weekly = 20.0 if claude == "tight" else 70.0
        fetched = now - (timedelta(minutes=40) if claude == "stale" else timedelta(seconds=30))
        report: dict[str, Any] = ({"status": "unavailable", "problem": {"kind": "rejected", "status": 403}} if claude == "unknown"
                                  else {"status": "available", "windows": [
                                      {"id": "w", "label": "Weekly", "usedPct": 100 - weekly, "remainingPct": weekly,
                                       "resetsAt": stamp(now + timedelta(days=3))},
                                      {"id": "5h", "label": "5-hour", "usedPct": 10.0, "remainingPct": 90.0,
                                       "resetsAt": stamp(now + timedelta(hours=2))},
                                      {"id": "f", "label": "Weekly (Fable)", "usedPct": 40.0, "remainingPct": 60.0,
                                       "resetsAt": stamp(now + timedelta(days=3))}]})
        path.write_text(json.dumps([{"id": "claude:default", "sourceId": "claude", "pool_family": "default", "sourceLabel": "Claude", "icon": "<svg/>",
                                     "account": "a", "fetchedAt": stamp(fetched), "report": report, "loginErrors": []}]))
        return path

    def gate_env(self, tighten_min_left: float | None = None, closed: bool = False,
                 claude: str | None = "fresh") -> dict[str, str]:
        """Env pointing the frontier gate at a temp gates.toml copy (`closed` closes its [frontier] baseline, the pre-2026-10-27 rule)
        and the Claude reading at a canned Paseo usage report (`claude_usage`); aiuse and its snapshot file are pinned away."""
        tmp = Path(tempfile.mkdtemp(prefix="ragate-"))
        toml = (Path(r.__file__).resolve().parent.parent / "config" / "gates.toml").read_text()
        if closed:
            toml = close_frontier_baseline(toml)
        if tighten_min_left is not None:
            toml = toml.replace("frontier1_min_left = 15.0 ", f"frontier1_min_left = {tighten_min_left} ", 1)
        (tmp / "gates.toml").write_text(toml)
        usage = self.claude_usage(claude, tmp / "usage.json")
        return {"GATES_TOML": str(tmp / "gates.toml"), "ROUTE_AGENT_AIUSE": "off", "AIUSE_SNAPSHOT": str(tmp / "no-snapshot.json"),
                "ROUTE_AGENT_PASEO": "off", "ROUTE_AGENT_PASEO_USAGE_JSON": str(usage) if usage else ""}

    @staticmethod
    def claude_slices() -> int:
        rows = r.plan(["frontier"] * 3, quota=IDLE)
        return sum(1 for _, c in rows if c and c.service.name == "claude")

    def test_the_standing_per_wave_cap_needs_a_fresh_known_claude_reading_above_its_floors(self):
        """Operator ruling 2026-10-27: the stop signal STOPS the allowance; a stale or missing reading fails closed. Since 2026-11-07 the
        reading is the merged snapshot's (aiuse plus `paseo usage ls`), so a Paseo report that is not `available` is unknown and fails
        closed too. The planner is the only per-wave limit a lead sees, so its 2-per-wave claude cap falls back to the closed 1."""
        for claude, want in (("fresh", 2), ("tight", 1), ("stale", 1), ("unknown", 1), (None, 1)):
            with self.subTest(claude=claude), mock.patch.dict(os.environ, self.gate_env(claude=claude)):
                self.assertEqual(self.claude_slices(), want)
                codex = [c.service.name if c else None for _, c in r.plan(["frontier"] * 3, quota={**IDLE, "claude": {"remaining": 0.0}})]
                self.assertEqual(codex.count("codex"), 1)           # codex's cap is 1 whatever the Claude reading says

    def test_frontier_per_wave_on_claude_with_a_fresh_a_stale_and_an_unknown_reading(self):
        """The slice's three cases (brief E7 1c), on frontier_per_wave itself: fresh grants the standing 2, stale and an unknown
        Paseo report give the closed 1; the reason is the one judged_pool_block names."""
        import ade_gates
        for claude, want, why in (("fresh", 2, None), ("stale", 1, "min old"), ("unknown", 1, "report unavailable")):
            with self.subTest(claude=claude), mock.patch.dict(os.environ, self.gate_env(claude=claude)):
                gate = r.frontier_gate()
                self.assertEqual(r.frontier_per_wave("claude", gate, IDLE), want)
                block = ade_gates.judged_pool_block(1, gate, datetime.now(UTC), r.claude_quota_state(), None)
                self.assertTrue(block is None if why is None else why in block, block)

    def test_a_fresh_aiuse_claude_reading_grants_and_an_unknown_paseo_report_does_not_take_it_away(self):
        """aiuse stays the primary reading: a fresh aiuse claude row with the Fable cap grants; an unavailable Paseo report beside
        it is recorded (`paseo_unknown`), never a loosening and never a block of a known reading."""
        tmp = Path(tempfile.mkdtemp(prefix="ragate-aiuse-"))
        (tmp / "aiuse.json").write_text(json.dumps({"fresh": True, "age_seconds": 60, "available": [
            {"provider": "claude", "pool_family": "default", "usable_now": True, "headroom_percent": 64.0, "age_seconds": 60,
             "binding_window": "weekly"},
            {"provider": "claude", "pool_family": "fable", "usable_now": True, "headroom_percent": 55.0, "age_seconds": 60}]}))
        env = {**self.gate_env(claude="unknown"), "ROUTE_AGENT_AIUSE_JSON": str(tmp / "aiuse.json")}
        with mock.patch.dict(os.environ, env):
            state = r.claude_quota_state()
            self.assertEqual((state["remaining"], state["fable_left"], state["unknown"]), (64.0, 55.0, None))
            self.assertIn("report unavailable", state["paseo_unknown"])
            self.assertEqual(r.frontier_per_wave("claude", r.frontier_gate(), IDLE), 2)
        (tmp / "aiuse.json").write_text(json.dumps({"fresh": True, "age_seconds": 60, "available": [
            {"provider": "claude", "pool_family": "default", "usable_now": True, "headroom_percent": 64.0, "age_seconds": 2400}]}))
        with mock.patch.dict(os.environ, env):
            self.assertEqual(r.frontier_per_wave("claude", r.frontier_gate(), IDLE), 1)     # a 40-minute-old row is stale

    def test_the_standing_per_wave_cap_for_a_non_claude_pool_needs_its_reading_at_the_floor(self):
        gate = {"frontier2_per_wave": 3.0, "frontier2_judged": 1.0, "frontier2_min_left": 60.0}
        self.assertEqual(r.frontier_per_wave("codex", gate, {"codex": {"remaining": 60.0}}), 3)
        self.assertEqual(r.frontier_per_wave("codex", gate, {"codex": {"remaining": 59.9}}), 1)
        self.assertEqual(r.frontier_per_wave("codex", gate, {}), 1)
        self.assertEqual(r.frontier_per_wave("codex", gate, {"codex": {"remaining": 90.0}}), 3)
        self.assertEqual(r.frontier_per_wave("codex", {**gate, "frontier2_judged": 0.0}, {"codex": {"remaining": 90.0}}), 1)

    def test_the_standing_baseline_lets_a_wave_put_two_frontier_slices_on_claude_but_still_one_on_codex(self):
        with mock.patch.dict(os.environ, self.gate_env()):           # the shipped gates.toml [frontier] (2026-10-27)
            rows = r.plan(["frontier"] * 5, quota=IDLE)
        self.assertEqual([c.service.name if c else None for _, c in rows], ["codex", "claude", "claude", None, None])
        with mock.patch.dict(os.environ, self.gate_env(closed=True)):
            rows = r.plan(["frontier"] * 5, quota=IDLE)
        self.assertEqual([c.service.name if c else None for _, c in rows], ["codex", "claude", None, None, None])

    def test_the_fable_floor_comes_from_the_frontier_gate(self):
        q = {**IDLE, "codex": {"remaining": 0.0}, "claude": {"remaining": 90.0, "sublimits": {"fable": 15.0}}}
        with mock.patch.dict(os.environ, self.gate_env()):
            self.assertEqual(r.route("frontier", quota=q).model, "fable --effort high")
        with mock.patch.dict(os.environ, self.gate_env(tighten_min_left=20.0)):      # a baseline may tighten
            self.assertEqual(r.route("frontier", quota=q).model, "opus --effort high")

    def test_the_policy_no_longer_carries_the_moved_keys(self):
        self.assertNotIn("frontier_per_wave", r.POLICY["routing"])
        self.assertNotIn("fable_min_left", r.POLICY["routing"])
        with mock.patch.dict(os.environ, self.gate_env()):
            gate = r.policy_public()["frontier_gate"]
        self.assertEqual((gate["frontier1_per_wave"], gate["frontier2_per_wave"], gate["frontier1_min_left"]), (2.0, 1.0, 15.0))

    def test_per_wave_key_by_pool(self):
        """frontier1_per_wave is the claude pool's, frontier2_per_wave every other pool's (codex's max_parallel = 1 hides it in plan)."""
        gate = {"frontier1_per_wave": 2.0, "frontier2_per_wave": 1.0, "frontier1_judged": 1.0, "frontier2_judged": 1.0,
                "frontier1_min_left": 10.0, "frontier2_min_left": 60.0}
        with mock.patch.dict(os.environ, self.gate_env()):
            self.assertEqual([r.frontier_per_wave(p, gate, IDLE) for p in ("claude", "codex", "cursor-auto", "unknown")], [2, 1, 1, 1])
            self.assertEqual(r.frontier_per_wave("codex", {**gate, "frontier1_per_wave": 1.0, "frontier2_per_wave": 3.0}, IDLE), 3)

    def test_dispatch_line_uses_the_acp_agent_name(self):
        svc = r.BY_NAME["cursor-auto"]            # the aiuse name is cursor-auto, the Paseo provider is cursor
        c = r.Choice(svc, 90.0, 1.0, model="default", kind="code")
        self.assertEqual(c.dispatch,
                         "paseo run --provider cursor/default --label ade.kind=code --no-wait")
        argv = shlex.split(r.Choice(svc, 90.0, 1.0, model=r"vendor\model", kind="code").dispatch)
        self.assertEqual(argv[3], r"cursor/vendor\model")

    def test_plan_json_carries_model_and_dispatch(self):
        rows = r.plan(["judgment", "bulk"], quota=IDLE)
        for _, c in rows:
            self.assertIsNotNone(c)
            self.assertTrue(c.dispatch.startswith("paseo run --provider "))


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
        self.assertEqual(c.dispatch,
                         "paseo run --provider cursor/default --label ade.kind=code --no-wait")


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
        "cursor-auto": {
            "cli": "cursor (Auto pool)",
            "good_at": {"code": 14, "mechanical": 4, "bulk": 6, "research": 12},
            "billing": "subscription",
            "judgment_tier": False,
            "models": {"code": "default", "mechanical": "default", "bulk": "default", "research": "default"},
            "pool": ("cursor", "auto"), "max_parallel": 2,
            "agent": "cursor", "burn_first": True,
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
                          "pipeline_effort": "medium", "fable_lead": True})

    def test_the_shipped_policy_allows_a_fable_lead_and_policy_md_says_so(self):
        """Operator 2026-11-07: `[lead].fable_lead = true` allows a Fable lead; `policy --md` prints the switch."""
        import io
        from contextlib import redirect_stdout
        self.assertIs(r.LEAD_FABLE_ALLOWED, True)
        md = io.StringIO()
        with redirect_stdout(md):
            self.assertEqual(r.main(["policy", "--md"]), 0)
        self.assertIn("| lead.fable_lead | true |", md.getvalue())
        self.assertIn("a Fable 5.2 lead is allowed", md.getvalue())

    def test_a_lead_table_without_fable_lead_keeps_the_never_fable_rule(self):
        """Absent (an older file) or false: the 2026-10-23 rule; a non-boolean is refused, naming the file."""
        import io
        from contextlib import redirect_stdout
        for line in ("", "fable_lead = false\n"):
            with self.subTest(line=line):
                path = self._lead_policy_variant('pipeline_effort = "medium"\n', line)
                try:
                    r.reload_policy(path)
                    self.assertIs(r.LEAD_FABLE_ALLOWED, False)
                    md = io.StringIO()
                    with redirect_stdout(md):
                        r.main(["policy", "--md"])
                    self.assertIn("| lead.fable_lead | false |", md.getvalue())
                    self.assertIn("not on Fable", md.getvalue())
                finally:
                    r.reload_policy(Path(__file__).resolve().parent.parent / "config" / "routing.toml")
        for value in ('"yes"', "1"):
            path = self._lead_policy_variant('pipeline_effort = "medium"\n', f"fable_lead = {value}\n")
            with self.assertRaises(ValueError) as ctx:
                r.load_policy(path)
            self.assertIn("fable_lead", str(ctx.exception))

    def _lead_policy_variant(self, replacement, fable_line=None):
        """Write routing.toml with the pipeline_effort line replaced (and, given `fable_line`, the fable_lead line too);
        return the temp path."""
        import tempfile
        src = (Path(__file__).resolve().parent.parent / "config" / "routing.toml").read_text()
        bad = src.replace('pipeline_effort = "medium"\n', replacement)
        if fable_line is not None:
            self.assertIn("fable_lead = true\n", bad)
            bad = bad.replace("fable_lead = true\n", fable_line, 1)
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

    def test_a_lead_effort_xhigh_and_max_load(self):
        """Paseo's top Claude levels are valid [lead] effort and pipeline_effort (PR 33 round 2)."""
        import tempfile
        src = (Path(__file__).resolve().parent.parent / "config" / "routing.toml").read_text()
        for value in ("xhigh", "max"):
            for key, needle in (("effort", 'effort = "high"\n'), ("pipeline_effort", 'pipeline_effort = "medium"\n')):
                with self.subTest(key=key, value=value):
                    bad = src.replace(needle, f'{key} = "{value}"\n', 1)
                    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
                        f.write(bad)
                    self.addCleanup(Path(f.name).unlink, missing_ok=True)
                    data = r.load_policy(f.name)
                    self.assertEqual(data["lead"][key], value)

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
    CASE = {"antigravity": {"remaining": 97.8},
            "opencode-go": {"remaining": 2.5}, "zai": {"remaining": 12.2},
            "cursor-auto": {"remaining": 0.0}, "cursor": {"remaining": 11.2},
            # claude was not a code pool then (code added 2026-10-18 by the operator); drained
            # here so the case still isolates the band
            "codex": {"remaining": 0.0}, "claude": {"remaining": 0.0},
            "opencode-zen-free": {"remaining": 100.0}, "clinepass": {"remaining": 100.0},
            "devin": {"remaining": 100.0}, "alibaba": {"remaining": 100.0},
            "crush": {"remaining": 100.0}}

    @mock.patch.dict(os.environ, {"ROUTE_AGENT_OMP_READY": "0"})   # omp-ready: TestOmpReadyRoster
    def test_the_2026_10_18_case_queues_code_instead_of_routing_far_down(self):
        best = r.quality_best("code", list(r.discover(self.CASE)), quota=self.CASE)
        self.assertIsNotNone(best)
        c = r.route("code", quota=self.CASE)
        self.assertIsNone(c, c and f"{c.service.name} r{c.service.rank_for('code')}")
        why = r.unrouted_why("code", self.CASE)
        self.assertIn(f"{best.name} r{best.rank_for('code')}", why)
        self.assertIn("quality_max_rank_gap", why)

    @mock.patch.object(r, "paseo_providers", return_value={"pi"})
    def test_a_far_lower_ranked_pool_never_wins_on_headroom(self, _providers):
        """Even with every pool idle, nothing outside the band is chosen for code; and the
        moment an in-band pool has room again, it gets the slice."""
        gap = r.QUALITY_MAX_RANK_GAP["code"]
        services = list(r.discover(self.CASE))
        best = r.quality_best("code", services, quota=self.CASE)
        assert best is not None
        far = [s.name for s in services
               if s.eligible("code", any_headroom=True) and s.rank_for("code") - best.rank_for("code") > gap]
        self.assertTrue(far, "fixture should include pools outside the band")
        q = dict(self.CASE, cursor={"remaining": 50.0, "age_s": 0})
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
        best = r.quality_best("code", services, quota=self.CASE)
        assert best is not None
        nxt = r.quality_best("code", services, {best.name}, quota=self.CASE)
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

    def test_the_default_constant_is_a_fifth_of_the_window(self):
        self.assertEqual(r.PLENTY_MIN, 20.0)

    def test_route_never_hands_codex_an_everyday_slice_below_the_constant(self):
        low = self.drained(codex={"remaining": r.PLENTY_MIN - 1})
        for kind in self.EVERYDAY:
            c = r.route(kind, quota=low)          # an installed unprofiled agent may still take bulk
            self.assertNotEqual(c.service.name if c else None, "codex", kind)
        self.assertTrue(self.codex().eligible("code", self.drained(codex={"remaining": r.PLENTY_MIN})))
        self.assertTrue(self.codex().eligible("frontier", low))      # frontier stays codex's below the constant ...
        at_floor = self.drained(codex={"remaining": 60.0})            # ... but the planner hands it a slice only at the astra estimate floor
        self.assertEqual(r.route("frontier", quota=at_floor).service.name, "codex")
        mid = self.drained(codex={"remaining": 49.0})                 # a fixed 49, independent of the plenty gate (20 since 2026-11-13)
        self.assertIsNone(r.route("frontier", quota=mid))             # uncalibrated, 49% is below what dispatch will demand
        # the positive control (adversary R4): the plenty gate (20 since 2026-11-13) does not reach frontier inside route();
        # with a calibrated history the planner hands codex a frontier slice BELOW the gate (19, median 10 fits above
        # min_headroom 15), and at a fixed 49 (median 20)
        for quota, pct in ((low, 10.0), (mid, 20.0)):
            state = Path(tempfile.mkdtemp(prefix="route-hist-"))
            (state / "task" / "jobs").mkdir(parents=True)
            for k in range(3):
                (state / "task" / "jobs" / f"s{k}.json").write_text(json.dumps(
                    {"agent": "codex", "model": "gpt-6-astra", "kind": "frontier", "effort": "high", "measured_usage_pct": pct}))
            r._FRONTIER_HISTORY_MEMO.clear()
            self.addCleanup(r._FRONTIER_HISTORY_MEMO.clear)
            with mock.patch.dict(os.environ, {"ROUTE_AGENT_CALIBRATED_FLOOR": "on", "SESSION_FINDER_STATE": str(state / "sf")}), \
                    mock.patch.object(r, "ACP_DISPATCH_STATE", state):
                self.assertEqual(r.route("frontier", quota=quota).service.name, "codex", quota)

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
        better = self.drained(codex={"remaining": 100.0}, **{"cursor-auto": {"remaining": 90.0}})
        self.assertEqual(r.route("code", quota=better).service.name, "cursor-auto")
        only = self.drained(codex={"remaining": 100.0}, cursor={"remaining": 90.0})
        self.assertEqual(r.route("code", quota=only).service.name, "codex")   # r15 beats cursor r20

    def test_a_wave_puts_one_slice_on_codex(self):
        q = self.drained(codex={"remaining": 100.0})
        rows = r.plan(["code", "code", "code"], quota=q)
        self.assertEqual([c.service.name if c else None for _, c in rows].count("codex"), 1)

    def test_policy_json_and_md_carry_the_constant_and_the_gated_kinds(self):
        pub = r.policy_public()
        self.assertEqual(pub["routing"]["plenty_min"], 20.0)
        row = next(s for s in pub["services"] if s["name"] == "codex")
        self.assertEqual(sorted(row["plenty_kinds"]), ["bulk", "code", "judgment", "mechanical"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(r.main(["policy", "--md"]), 0)
        self.assertIn("| routing.plenty_min | 20 |", buf.getvalue())



class TestOmpReadyRoster(RestorableTransportPolicyCase):
    """With a working omp login (ROUTE_AGENT_OMP_READY=1) omp is a code/bulk pool. conftest pins the
    probe off so the suite does not depend on the host; these are the omp-ready counterparts of
    test_measured_idle_capacity_beats_unmeasured, test_no_room_comes_back_as_none_not_an_error and
    test_the_2026_10_18_case_queues_code_instead_of_routing_far_down (docs/queue.md item 6, 2026-10-20).
    Left out on purpose: omp ready with NO quota reading (the state this Mac was in). There an unmeasured
    omp outranks a measured pool in all three scenarios, which is the open follow-up carried from item 6,
    not behaviour to pin (adversary, 2026-10-20)."""

    def setUp(self):
        super().setUp()
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
        drained = {k: {"remaining": 1.0} for k in IDLE}
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


class TestOmpCreditsTier(RestorableTransportPolicyCase):
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
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"ROUTE_AGENT_OMP_READY": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_omp_is_no_longer_gated_anywhere(self):
        self.assertNotIn("omp", r.OPERATOR_GATED)
        self.assertNotIn("omp", r.POLICY["dispatch"]["operator_gated"])
        self.assertIn("hermes", r.POLICY["dispatch"]["operator_gated"])

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

    def test_api_only_is_a_kind_for_the_api_billing_pool(self):
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
                body = ('{"age_seconds": 5, "available": [{"provider": "grok", "windows": '
                        f'[{{"label": "premium", "headroom_percent": {bad}}}]}}]}}')
                path = self.write("nan.json", body)
                quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
                self.assertIsNone(quota["grok"]["remaining"])
                for kind in r.KINDS:
                    choice = r.route(kind, quota={**IDLE, **quota})
                    if choice and choice.service.name == "grok":
                        self.assertIsNone(choice.remaining, kind)   # unmeasured, never NaN read as headroom

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
        {"provider": "cursor", "pool_family": "third_party", "usable_now": True,
         "headroom_percent": 16.0},
        {"provider": "cursor", "pool_family": "auto", "usable_now": False,
         "headroom_percent": 0},
    ]

    def test_foreign_family_windows_never_create_or_loosen_another_pool(self):
        exhausted = {"state": "exhausted", "headroom_percent": 0.0}
        self.accounts = [
            {"provider": "cursor", "age_seconds": 30, "windows": [
                {"label": "auto", "pool_family": "auto", **exhausted},
                {"label": "tp", "pool_family": "third_party", "headroom_percent": 50.0}]},
        ]
        rows = [
            {"provider": "cursor", "pool_family": "third_party", "usable_now": True,
             "headroom_percent": 50.0, "windows": [
                 {"label": "tp", "pool_family": "third_party", "headroom_percent": 50.0},
                 {"label": "auto", "pool_family": "auto", "headroom_percent": 63.5}]},
        ]
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(self.rows_payload(rows))})
        self.assertEqual(quota["cursor-auto"]["remaining"], 0.0)   # the auto window inside the third_party row does not loosen it
        self.assertEqual(quota["cursor"]["remaining"], 50.0)

    def test_foreign_window_may_tighten_an_existing_pool(self):
        rows = [
            {"provider": "cursor", "pool_family": "third_party", "usable_now": True,
             "headroom_percent": 80.0, "windows": [
                 {"label": "auto", "pool_family": "auto", "headroom_percent": 10.0}]},
            {"provider": "cursor", "pool_family": "auto", "usable_now": True,
             "headroom_percent": 60.0},
        ]
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(self.rows_payload(rows))})
        self.assertEqual(quota["cursor-auto"]["remaining"], 10.0)

    def test_rows_without_windows_follow_the_contract_fields(self):
        # a payload with no age at all reads stale by design, so the fixture carries one
        path = self.rows_payload(self.FAILOVER_FIXTURE_ROWS)
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertEqual(quota["claude"]["remaining"], 20.0)
        self.assertEqual(quota["claude"]["sublimits"], {"fable": 2.5})
        self.assertEqual(quota["opencode-go"]["remaining"], 8.0)
        self.assertEqual(quota["cursor"]["remaining"], 16.0)
        self.assertEqual(quota["cursor-auto"]["remaining"], 0.0)

    def test_plan_refuses_the_pools_under_min_headroom(self):
        path = self.rows_payload(self.FAILOVER_FIXTURE_ROWS)
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        quota = {**{k: v for k, v in quota.items()}}
        for kind in ("code", "bulk"):
            choice = r.route(kind, quota=quota, min_headroom=25)
            for refused in ("claude", "opencode-go", "cursor", "cursor-auto"):
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
            {"provider": "grok", "pool_family": None, "reason": "operator"}])
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertEqual(quota["grok"]["remaining"], 0.0)
        self.assertTrue(quota["grok"]["excluded"])
        for kind in r.KINDS:
            choice = r.route(kind, quota={**IDLE, **quota})
            self.assertFalse(choice and choice.service.name == "grok", kind)

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
            "junk", {"provider": 3}, {"provider": ""}, {"provider": "grok", "pool_family": 7}])
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertEqual(r.QuotaSource.kind, "canned")
        self.assertEqual(quota["omp"]["remaining"], 70.0)
        self.assertNotIn("grok", quota)

    def test_excluded_is_not_consulted_on_the_file_fallback(self):
        path = self.rows_payload(["junk"], excluded=[{"provider": "grok"}])
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertEqual(r.QuotaSource.kind, "snapshot")
        self.assertNotIn("grok", quota)

    def test_excluded_is_not_applied_from_a_stale_payload(self):
        path = self.rows_payload([], excluded=[{"provider": "grok"}], fresh=False)
        quota, _, _ = self.load({"ROUTE_AGENT_AIUSE_JSON": str(path)})
        self.assertNotIn("grok", quota)

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


class TestSubstrateChain(unittest.TestCase):
    """Main-loop substrate picker: Flash-primary, cline↔opencode-go failover.

    The rule under test is the 2026-10-23 accident: a live cross-provider model
    switch broke the ◈ Dann tab. The chain keeps the model constant across a
    provider failover and ranks healthy -> lifeline -> tight -> exhausted. A pool
    the operator disabled in aiuse is never chosen, bar the configured lifeline.
    """

    LIFELINE = frozenset({"clinepass"})

    @staticmethod
    def _opencode(windows: list[tuple[str, float, str]], **extra: Any) -> list[dict[str, Any]]:
        return [{"provider": "opencode-go", **extra,
                 "windows": [{"label": label, "remaining_percent": rem, "state": state}
                             for (label, rem, state) in windows]}]

    def _chain(self, accounts: list[dict[str, Any]] | None = None, quota: Any = None,
               disabled: Any = frozenset(), lifeline: Any = None,
               file_age: float | None = 60.0) -> list[dict[str, Any]]:
        return r.substrate_chain(quota or {}, accounts or [], file_age=file_age,
                                 disabled=disabled,
                                 lifeline=self.LIFELINE if lifeline is None else lifeline)

    HEALTHY = [("OpenCode Go 5-hour", 98.0, "ok"),
               ("OpenCode Go weekly", 96.0, "ok"),
               ("OpenCode Go monthly", 55.0, "ok")]

    def test_healthy_opencode_go_is_primary_with_cline_fallback(self):
        chain = self._chain(self._opencode(self.HEALTHY))
        self.assertEqual(chain[0]["role"], "primary")
        self.assertEqual(chain[0]["provider"], "opencode")
        self.assertEqual(chain[0]["model"], "opencode-go/deepseek-v4.1-flash")
        self.assertEqual(chain[1]["provider"], "cline")   # unmeasured lifeline
        self.assertEqual(len(chain), 2)
        self.assertNotIn("opencode-go/deepseek-v4-pro", [entry["model"] for entry in chain])

    def test_monthly_budget_binds_even_with_open_rate_windows(self):
        chain = self._chain(self._opencode(self.HEALTHY))
        self.assertAlmostEqual(chain[0]["remaining"], 55.0)
        spent = self._chain(self._opencode([
            ("OpenCode Go 5-hour", 98.0, "ok"),
            ("OpenCode Go weekly", 96.0, "ok"),
            ("OpenCode Go monthly", 0.6, "exhausted")]))
        self.assertEqual(spent[0]["provider"], "cline")
        self.assertEqual(spent[1]["remaining"], 0.0)
        self.assertEqual(spent[1]["monthly"], 0.6)

    def test_tight_opencode_go_yields_to_the_unmeasured_lifeline(self):
        chain = self._chain(self._opencode([
            ("OpenCode Go 5-hour", 4.0, "ok"), ("OpenCode Go weekly", 5.0, "ok")]))
        self.assertEqual(chain[0]["provider"], "cline")
        self.assertEqual(chain[1]["provider"], "opencode")

    def test_exhausted_opencode_go_falls_to_the_lifeline(self):
        chain = self._chain(self._opencode([
            ("OpenCode Go 5-hour", 0.0, "exhausted"),
            ("OpenCode Go weekly", 0.0, "exhausted")]))
        self.assertEqual(chain[0]["provider"], "cline")
        self.assertEqual(chain[1]["provider"], "opencode")
        self.assertFalse(chain[1]["usable"])
        self.assertEqual(chain[1]["role"], "exhausted")

    def test_exhausted_pool_is_not_named_primary_and_nothing_is_usable(self):
        chain = self._chain(self._opencode([("OpenCode Go monthly", 0.0, "exhausted")]),
                            quota={"clinepass": {"remaining": 0.0}})
        self.assertEqual({e["role"] for e in chain}, {"exhausted"})
        self.assertFalse(any(e["usable"] for e in chain))

    # F2: operator-disabled pools
    def test_disabled_pool_is_never_chosen_even_when_healthy(self):
        chain = self._chain(self._opencode(self.HEALTHY), disabled={"opencode-go"})
        self.assertEqual([e["pool"] for e in chain], ["clinepass"])
        self.assertEqual(chain[0]["role"], "primary")

    def test_disabled_without_data_is_dropped_not_kept_by_tuple_order(self):
        # both pools unmeasured (aiuse does not collect a disabled pool): opencode-go
        # used to win the tie by tuple order
        chain = self._chain([], disabled={"opencode-go", "clinepass"})
        self.assertEqual([e["pool"] for e in chain], ["clinepass"])

    def test_only_the_configured_lifeline_may_be_disabled(self):
        chain = self._chain([], disabled={"opencode-go", "clinepass"}, lifeline=frozenset())
        self.assertEqual(chain, [])
        chain = self._chain([], disabled={"clinepass"}, lifeline=frozenset())
        self.assertEqual([e["pool"] for e in chain], ["opencode-go"])

    def test_default_lifeline_comes_from_the_policy_and_default_disabled_from_aiuse(self):
        with mock.patch.object(r, "operator_disabled",
                               return_value={"opencode-go", "clinepass"}):
            chain = r.substrate_chain({}, [], file_age=60.0)
        self.assertEqual([e["pool"] for e in chain], ["clinepass"])

    # the lifeline is not collected by aiuse while disabled: absent from --available != exhausted
    ABSENT = {"clinepass": {"remaining": 0.0, "absent_from_available": True}}

    def test_disabled_lifeline_absent_from_available_is_listed_unmeasured(self):
        chain = self._chain(self._opencode(self.HEALTHY), quota=self.ABSENT,
                            disabled={"opencode-go", "clinepass"})
        self.assertEqual([(e["role"], e["pool"], e["remaining"], e["usable"]) for e in chain],
                         [("primary", "clinepass", None, True)])
        both = self._chain(self._opencode(self.HEALTHY), quota=self.ABSENT,
                           disabled={"clinepass"})
        self.assertEqual([e["pool"] for e in both], ["opencode-go", "clinepass"])
        self.assertIsNone(both[1]["remaining"])

    def test_enabled_pool_absent_from_available_is_still_exhausted(self):
        chain = self._chain(self._opencode(self.HEALTHY), quota=self.ABSENT, disabled=set())
        cline = next(e for e in chain if e["pool"] == "clinepass")
        self.assertEqual((cline["remaining"], cline["usable"]), (0.0, False))

    def test_disabled_lifeline_still_obeys_a_real_zero_reading(self):
        chain = self._chain([], quota={"clinepass": {"remaining": 0.0}},
                            disabled={"opencode-go", "clinepass"})
        self.assertEqual([(e["pool"], e["usable"]) for e in chain], [("clinepass", False)])

    # F3: the same guards load_snapshot applies
    def test_stale_snapshot_file_measures_nothing(self):
        chain = self._chain(self._opencode(self.HEALTHY), file_age=9 * 86400.0)
        self.assertIsNone(next(e for e in chain if e["pool"] == "opencode-go")["remaining"])

    def test_row_older_than_soft_stale_reads_unmeasured_but_keeps_an_exhausted_window(self):
        old = r.STALE_SOFT + 60
        chain = self._chain(self._opencode(self.HEALTHY, age_seconds=old))
        self.assertIsNone(next(e for e in chain if e["pool"] == "opencode-go")["remaining"])
        spent = self._chain(self._opencode(
            [("OpenCode Go monthly", 0.0, "exhausted")], age_seconds=old))
        self.assertEqual(next(e for e in spent if e["pool"] == "opencode-go")["remaining"], 0.0)

    def test_expired_reading_is_unmeasured(self):
        chain = self._chain(self._opencode(self.HEALTHY, reading_expired=True))
        self.assertIsNone(next(e for e in chain if e["pool"] == "opencode-go")["remaining"])

    def test_row_with_an_error_is_skipped(self):
        chain = self._chain(self._opencode(self.HEALTHY, error="auth expired"))
        self.assertIsNone(next(e for e in chain if e["pool"] == "opencode-go")["remaining"])

    def test_fresh_available_reading_can_only_tighten_the_file(self):
        chain = self._chain(self._opencode(self.HEALTHY),
                            quota={"opencode-go": {"remaining": 0.0,
                                                   "absent_from_available": True}})
        oc = next(e for e in chain if e["pool"] == "opencode-go")
        self.assertEqual(oc["remaining"], 0.0)
        self.assertEqual(chain[0]["pool"], "clinepass")
        loose = self._chain(self._opencode(self.HEALTHY),
                            quota={"opencode-go": {"remaining": 99.0}})
        self.assertAlmostEqual(next(e for e in loose if e["pool"] == "opencode-go")["remaining"],
                               55.0)

    # F6: _pct on every percentage
    def test_nonfinite_oversized_and_string_percentages(self):
        chain = self._chain(self._opencode([("OpenCode Go 5-hour", float("inf"), "ok")]))
        self.assertIsNone(next(e for e in chain if e["pool"] == "opencode-go")["remaining"])
        chain = self._chain(self._opencode([("OpenCode Go 5-hour", 250.0, "ok")]))
        self.assertEqual(next(e for e in chain if e["pool"] == "opencode-go")["remaining"], 100.0)
        chain = self._chain(self._opencode([("OpenCode Go 5-hour", "50", "ok")]))   # no TypeError
        self.assertEqual(next(e for e in chain if e["pool"] == "opencode-go")["remaining"], 50.0)


class TestSubstrateCommand(unittest.TestCase):
    """`route_agent.py substrate` end to end: output, exit codes, --apply."""

    HEALTHY_ROWS = [{"provider": "opencode-go", "windows": [
        {"label": "OpenCode Go monthly", "remaining_percent": 55.0, "state": "ok"}]}]

    def _run(self, argv: list[str], *, disabled: set[str] | None = None,
             rows: list[dict[str, Any]] | None = None, lifeline: Any = None,
             apply: Any = None, quota: Any = None) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        patches = [
            mock.patch.object(r, "load_snapshot", return_value=(quota or {}, 60.0)),
            mock.patch.object(r, "_read_snapshot_file",
                              return_value=(self.HEALTHY_ROWS if rows is None else rows, 60.0)),
            mock.patch.object(r, "operator_disabled", return_value=set(disabled or ())),
            mock.patch.object(r, "SUBSTRATE_LIFELINE",
                              frozenset({"clinepass"}) if lifeline is None else lifeline),
        ]
        if apply is not None:
            patches.append(mock.patch.object(r, "apply_substrate", side_effect=apply))
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            rc = r.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_plain_text_form_prints_the_chain(self):
        # the documented command used to raise NameError after building the chain
        rc, out, _ = self._run(["substrate"])
        self.assertEqual(rc, 0)
        self.assertIn("primary", out)
        self.assertIn("opencode/opencode-go/deepseek-v4.1-flash", out)
        self.assertIn("fallback", out)

    def test_disabled_pools_leave_only_the_lifeline(self):
        rc, out, _ = self._run(["substrate", "--json"], disabled={"opencode-go", "clinepass"})
        self.assertEqual(rc, 0)
        chain = json.loads(out)["chain"]
        self.assertEqual([(e["role"], e["pool"]) for e in chain], [("primary", "clinepass")])

    def test_nothing_usable_says_so_and_exits_nonzero(self):
        rc, out, _ = self._run(["substrate"], disabled={"opencode-go", "clinepass"},
                               lifeline=frozenset())
        self.assertEqual(rc, r.SUBSTRATE_EXIT_NONE_USABLE)
        self.assertIn("no usable substrate", out)
        rc, out, err = self._run(["substrate", "--json"], disabled={"opencode-go", "clinepass"},
                                 lifeline=frozenset())
        self.assertEqual(rc, r.SUBSTRATE_EXIT_NONE_USABLE)
        doc = json.loads(out)
        self.assertEqual((doc["usable"], doc["chain"]), (False, []))
        self.assertIn("no usable substrate", err)

    def test_all_exhausted_exits_nonzero_and_apply_is_not_attempted(self):
        rows = [{"provider": "opencode-go", "usable_now": False, "windows": []}]
        calls: list[Any] = []
        rc, out, _ = self._run(["substrate", "--apply", "ab1"], rows=rows,
                               quota={"clinepass": {"remaining": 0.0}},
                               apply=lambda *a: calls.append(a) or (0, "x"))
        self.assertEqual(rc, r.SUBSTRATE_EXIT_NONE_USABLE)
        self.assertIn("no usable substrate", out)
        self.assertEqual(calls, [])

    def test_lifeline_omitted_from_available_still_runs_the_command(self):
        rc, out, _ = self._run(["substrate", "--json"], disabled={"opencode-go", "clinepass"},
                               quota={"clinepass": {"remaining": 0.0,
                                                    "absent_from_available": True}})
        self.assertEqual(rc, 0)
        self.assertEqual([(e["pool"], e["remaining"]) for e in json.loads(out)["chain"]],
                         [("clinepass", None)])

    def test_apply_failure_exit_code_reaches_the_caller(self):
        rc, _, _ = self._run(["substrate", "--apply", "ab1"],
                             apply=lambda agent, chain: (5, "cross-provider: ..."))
        self.assertEqual(rc, 5)
        rc, _, _ = self._run(["substrate", "--apply", "ab1"],
                             apply=lambda agent, chain: (0, "ok"))
        self.assertEqual(rc, 0)


class TestApplySubstrate(unittest.TestCase):
    """`apply_substrate`: one agent, checked and set by the same id; failures carry exit codes."""

    CHAIN = [{"role": "primary", "usable": True, "pool": "opencode-go",
              "provider": "opencode", "model": "opencode-go/deepseek-v4.1-flash",
              "remaining": 55.0, "monthly": 55.0}]

    @staticmethod
    def _helper(agents: Any, *, list_rc: int = 0, set_rc: int = 0, set_out: str = "ok"):
        calls: list[list[str]] = []

        def run(argv, **kw):
            calls.append(list(argv))
            if argv[1] == "list":
                return subprocess.CompletedProcess(
                    argv, list_rc, stdout=agents if isinstance(agents, str) else json.dumps(agents),
                    stderr="boom")
            return subprocess.CompletedProcess(argv, set_rc, stdout=set_out, stderr="")
        return run, calls

    AGENTS: ClassVar[list[dict[str, str]]] = [
        {"id": "ab1-full-id", "provider": "opencode", "model": "x"},
        {"id": "cd2-full-id", "provider": "claude", "model": "y"}]

    def _apply(self, agent: str, agents: Any = None, chain: Any = None, **kw: Any):
        run, calls = self._helper(self.AGENTS if agents is None else agents, **kw)
        with mock.patch.object(r.subprocess, "run", side_effect=run):
            rc, msg = r.apply_substrate(agent, self.CHAIN if chain is None else chain)
        return rc, msg, calls

    def test_within_provider_move_sets_the_checked_agents_full_id(self):
        rc, _, calls = self._apply("ab1")
        self.assertEqual(rc, 0)
        self.assertEqual(calls[-1][1:], ["set", "ab1-full-id", "opencode-go/deepseek-v4.1-flash"])

    def test_cross_provider_is_refused_with_its_own_exit_code_and_no_set(self):
        rc, msg, calls = self._apply("cd2")
        self.assertEqual(rc, r.SUBSTRATE_EXIT_CROSS_PROVIDER)
        self.assertIn("NEW session", msg)
        self.assertEqual([c[1] for c in calls], ["list"])

    def test_unknown_agent_exits_3(self):
        rc, msg, _ = self._apply("zz9")
        self.assertEqual(rc, r.SUBSTRATE_EXIT_NO_AGENT)
        self.assertIn("no such agent", msg)

    def test_set_failure_passes_the_helpers_exit_code_through(self):
        for code in (1, 3, 4):
            rc, _, _ = self._apply("ab1", set_rc=code, set_out="")
            self.assertEqual(rc, code)

    def test_empty_or_ambiguous_prefix_is_refused_without_a_set(self):
        agents = [{"id": "ab1-x", "provider": "opencode", "model": "m"},
                  {"id": "ab1-y", "provider": "claude", "model": "m"}]
        for agent in ("", "ab1"):
            rc, _, calls = self._apply(agent, agents=agents)
            self.assertEqual(rc, r.SUBSTRATE_EXIT_BAD_AGENT, agent)
            self.assertNotIn("set", [c[1] for c in calls])

    def test_an_exact_id_beats_a_longer_id_it_prefixes(self):
        agents = [{"id": "ab1", "provider": "opencode", "model": "m"},
                  {"id": "ab1-longer", "provider": "claude", "model": "m"}]
        rc, _, calls = self._apply("ab1", agents=agents)
        self.assertEqual(rc, 0)
        self.assertEqual(calls[-1][2], "ab1")

    def test_unlistable_or_unparseable_agents_exit_7(self):
        self.assertEqual(self._apply("ab1", list_rc=1)[0], r.SUBSTRATE_EXIT_CANNOT_LIST)
        self.assertEqual(self._apply("ab1", agents="not json")[0], r.SUBSTRATE_EXIT_CANNOT_LIST)

    def test_valid_json_that_is_not_a_list_exits_7_not_3(self):
        for body in ({"id": "ab1-full-id", "provider": "opencode"}, '"ab1-full-id"', "null", 7):
            rc, msg, calls = self._apply("ab1", agents=body)
            self.assertEqual(rc, r.SUBSTRATE_EXIT_CANNOT_LIST, body)
            self.assertIn("not a JSON list", msg)
            self.assertEqual([c[1] for c in calls], ["list"])

    def test_no_usable_primary_never_touches_paseo(self):
        rc, _, calls = self._apply("ab1", chain=[])
        self.assertEqual(rc, r.SUBSTRATE_EXIT_NONE_USABLE)
        self.assertEqual(calls, [])


class TestQuotaFromPaseoUsage(unittest.TestCase):
    """`paseo usage ls --json` is the second quota source (2026-11-07, slim-down E7): an `available` report gives windows and
    balances, anything else is unknown (never a pass); it merges with aiuse by the tightest-known rule, and the source of each
    pool is reported."""

    NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)

    def row(self, source, status="available", windows=(), balances=(), age_min=1.0, **report):
        rep = {"status": status, **report}
        if status == "available":
            rep["windows"] = list(windows)
            rep["balances"] = list(balances)
        return {"id": f"{source}:default", "sourceId": source,
                "pool_family": {"claude": "default", "cursor": "third_party"}.get(source), "sourceLabel": source, "icon": "<svg>x</svg>", "account": "a",
                "fetchedAt": (self.NOW - timedelta(minutes=age_min)).strftime("%Y-%m-%dT%H:%M:%SZ"), "report": rep,
                "loginErrors": [{"message": "x"}]}

    @staticmethod
    def win(label, used=None, left=None, resets="2026-11-10T00:00:00Z"):
        return {"id": label, "label": label, "usedPct": used, "remainingPct": left, "resetsAt": resets}

    def test_an_overlapping_window_keeps_the_tighter_reading_from_either_source(self):
        # Codex P2 on PR 297 (2026-11-07): the merge overlaid the second source's windows, so aiuse 20% on 5-hour and
        # Paseo 80% left windows['5-hour'] = 80 while remaining = 20, and window_fit admitted a 30% slice.
        into = {"codex": {"remaining": 20.0, "windows": {"5-hour": 20.0, "Weekly": 60.0}}}
        r._merge_pool(into, "codex", {"remaining": 80.0, "windows": {"5-hour": 80.0, "Weekly": 50.0, "Monthly": 90.0}})
        self.assertEqual(into["codex"]["remaining"], 20.0)
        self.assertEqual(into["codex"]["windows"], {"5-hour": 20.0, "Weekly": 50.0, "Monthly": 90.0})
        self.assertIsNotNone(r.window_fit({"5-hour": 30.0}, into["codex"]["windows"])[0])

    def test_an_available_report_gives_windows_balances_the_tightest_and_its_reset(self):
        pools = r.usage_from_paseo([self.row("codex", windows=[self.win("5-hour", used=30.0, left=70.0),
                                                                 self.win("Weekly", used=55.0, resets="2026-11-12T00:00:00Z")],
                                             balances=[{"remaining": 5.0, "limit": 20.0, "unit": "USD"}])], now=self.NOW)
        codex = pools["codex"]
        self.assertEqual(codex["windows"], {"5-hour": 70.0, "Weekly": 45.0, "USD balance": 25.0})
        self.assertEqual((codex["remaining"], codex["resets_at"], codex["source"]), (25.0, None, "paseo"))
        self.assertNotIn("icon", codex)
        self.assertEqual(codex["age_s"], 60.0)

    def test_a_non_available_report_is_unknown_never_a_pass(self):
        for status in ("unavailable", "error", None):
            with self.subTest(status=status):
                pools = r.usage_from_paseo([self.row("claude", status=status, problem={"kind": "rejected", "status": 403})],
                                           now=self.NOW)
                self.assertIsNone(pools["claude"]["remaining"])
                self.assertIn(f"report {status or 'missing'}", pools["claude"]["unknown"])

    def test_the_fable_window_is_a_sublimit_and_opencode_is_the_go_pool(self):
        pools = r.usage_from_paseo([self.row("claude", windows=[self.win("Weekly", left=80.0), self.win("Weekly Fable", left=12.0)]),
                                    self.row("opencode", windows=[self.win("Monthly", used=40.0)])], now=self.NOW)
        self.assertEqual((pools["claude"]["remaining"], pools["claude"]["sublimits"]), (80.0, {"fable": 12.0}))
        self.assertEqual(pools["opencode-go"]["remaining"], 60.0)

    def test_a_report_whose_windows_or_balances_is_not_a_list_is_not_read_and_never_raises(self):
        """Adversary 2026-11-07: `windows: 5` raised TypeError into load_snapshot; now the pool is Paseo "not read"."""
        for over in ({"windows": 5}, {"windows": {"w": 1}}, {"balances": "x"}):
            with self.subTest(over=over):
                row = self.row("codex", windows=[self.win("w", left=50.0)])
                row["report"].update(over)
                pools = r.usage_from_paseo([row], now=self.NOW)
                self.assertIsNone(pools["codex"]["remaining"])
                self.assertIn("not read", pools["codex"]["unknown"])
        aiuse = [{"provider": "codex", "pool_family": None, "usable_now": True, "headroom_percent": 40.0, "age_seconds": 20}]
        row = self.row("codex", windows=[])
        row["report"]["windows"] = 5
        quota, _, info = self.load(aiuse, [row])
        self.assertEqual(quota["codex"]["remaining"], 40.0)          # aiuse's reading stands
        self.assertIn("not read", quota["codex"]["paseo_unknown"])

    def test_a_stale_report_keeps_only_an_exhausted_window(self):
        pools = r.usage_from_paseo([self.row("codex", windows=[self.win("5-hour", left=0.0), self.win("Weekly", left=90.0)],
                                             age_min=40)], now=self.NOW)
        self.assertEqual(pools["codex"]["windows"], {"5-hour": 0.0, "Weekly": None})
        self.assertEqual(pools["codex"]["remaining"], 0.0)

    def load(self, aiuse_rows, usage_rows, accounts=()):
        tmp = Path(tempfile.mkdtemp(prefix="ra-usage-"))
        (tmp / "aiuse.json").write_text(json.dumps({"fresh": True, "age_seconds": 20.0, "available": aiuse_rows}))
        now = datetime.now(UTC)
        for row in usage_rows:
            row["fetchedAt"] = (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        (tmp / "usage.json").write_text(json.dumps(usage_rows))
        env = {"ROUTE_AGENT_AIUSE_JSON": str(tmp / "aiuse.json") if aiuse_rows is not None else "",
               "ROUTE_AGENT_PASEO_USAGE_JSON": str(tmp / "usage.json"), "ROUTE_AGENT_OMP_READY": "0"}
        r._reset_aiuse_cache()
        with mock.patch.dict(os.environ, env), mock.patch.object(r, "_read_snapshot_file", return_value=(list(accounts), 60.0)), \
                contextlib.redirect_stderr(io.StringIO()):
            quota, age = r.load_snapshot()
            info = r.quota_source_info()
        r._reset_aiuse_cache()
        return quota, age, info

    def test_the_tighter_source_wins_per_pool_and_each_pool_names_its_source(self):
        aiuse = [{"provider": "codex", "pool_family": None, "usable_now": True, "headroom_percent": 80.0, "age_seconds": 20},
                 {"provider": "claude", "pool_family": "default", "usable_now": True, "headroom_percent": 40.0, "age_seconds": 20}]
        usage = [self.row("codex", windows=[self.win("5-hour", left=35.0)]), self.row("claude", windows=[self.win("Weekly", left=90.0)]),
                 self.row("cursor", windows=[self.win("Monthly", left=66.0)])]
        quota, _, info = self.load(aiuse, usage)
        self.assertEqual((quota["codex"]["remaining"], quota["claude"]["remaining"], quota["cursor"]["remaining"]), (35.0, 40.0, 66.0))
        self.assertEqual(info["pools"]["codex"], "canned+paseo")
        self.assertEqual(info["pools"]["cursor"], "paseo")
        self.assertTrue(info["paseo"].startswith("ROUTE_AGENT_PASEO_USAGE_JSON="))

    def test_an_unknown_paseo_report_never_loosens_an_aiuse_reading_or_stands_in_for_one(self):
        aiuse = [{"provider": "codex", "pool_family": None, "usable_now": True, "headroom_percent": 12.0, "age_seconds": 20}]
        usage = [self.row("codex", status="unavailable"), self.row("claude", status="error")]
        quota, _, _ = self.load(aiuse, usage)
        self.assertEqual(quota["codex"]["remaining"], 12.0)
        self.assertIn("report unavailable", quota["codex"]["paseo_unknown"])
        self.assertIsNone(quota["claude"]["remaining"])
        self.assertIn("report error", quota["claude"]["unknown"])
        self.assertIsNone(r.route("judgment", quota={"claude": quota["claude"]}))   # unmeasured, not 100%

    def test_paseo_alone_fills_the_snapshot_when_aiuse_is_absent(self):
        quota, age, info = self.load(None, [self.row("claude", windows=[self.win("Weekly", left=77.0)])])
        self.assertEqual(quota["claude"]["remaining"], 77.0)
        self.assertEqual(info["pools"]["claude"], "paseo")
        self.assertIsNotNone(age)

    def test_paseo_usage_failures_leave_the_aiuse_reading(self):
        with fake_paseo(FAKE_PASEO_USAGE_RC="1"), mock.patch.dict(os.environ, {"ROUTE_AGENT_PASEO_USAGE_JSON": ""}):
            rows, why = r.paseo_usage()
        self.assertIsNone(rows)
        self.assertIn("exited 1", why)
        with fake_paseo(FAKE_PASEO_USAGE=json.dumps([self.row("codex", windows=[self.win("w", left=50.0)])])), \
                mock.patch.dict(os.environ, {"ROUTE_AGENT_PASEO_USAGE_JSON": ""}) as _:
            rows, why = r.paseo_usage()
            again, _ = r.paseo_usage()
        self.assertEqual((len(rows), why), (1, "paseo usage ls --json"))
        self.assertEqual(again, rows)                     # memoised for PASEO_MEMO_TTL


class TestArgonFrontierFallback(unittest.TestCase):
    """Gemini 4 Argon, through Paseo's antigravity provider, is the frontier FALLBACK behind codex and claude (operator
    2026-10-31; restored 2026-11-07 for tendcf/nix2cf's review route 3)."""

    def test_the_argon_model_maps_to_its_own_pool_and_other_antigravity_models_to_none(self):
        self.assertEqual(r.map_agent_to_provider("antigravity", "gemini-4-argon"), ("antigravity", "gemini_argon"))
        self.assertEqual(r.dispatch_service_name("antigravity", "gemini-4-argon"), "antigravity-argon")
        self.assertIsNone(r.map_agent_to_provider("antigravity", "gemini-3.8-flash"))
        self.assertIn("gemini-4-argon", r.POLICY["dispatch"]["frontier_models"])
        self.assertNotIn("antigravity", {s.name for s in r.discover(IDLE)})      # the provider's other pools stay unrouted

    def test_argon_takes_frontier_only_while_codex_or_claude_is_short(self):
        q = {**IDLE, "antigravity-argon": {"remaining": 90.0}}
        self.assertNotEqual(r.route("frontier", quota=q).service.name, "antigravity-argon")
        q.update(codex={"remaining": 0.0}, claude={"remaining": 0.0})
        c = r.route("frontier", quota=q)
        self.assertEqual(
            (c.service.name, c.dispatch),
            ("antigravity-argon",
             "paseo run --provider antigravity/gemini-4-argon-high --mode full-access "
             "--label ade.kind=frontier --no-wait"),
        )
        q.pop("antigravity-argon")
        self.assertIsNone(r.route("frontier", quota=q))          # a fallback with no reading fails closed
