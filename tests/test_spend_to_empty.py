#!/usr/bin/env python3
"""djbclark 2026-11-02: "It is fine if we run out of quota on agy omp codex zcode cursor grok, just not claude ocgo cline."
The protective floors of those pools are gone (they are spent down to empty); claude, opencode-go and clinepass keep theirs."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import ade_gates
import route_agent as r
from test_acp_dispatch import Base

OPEN_POOLS = ("antigravity", "antigravity-claude", "antigravity-argon", "omp", "codex", "zai", "cursor", "cursor-auto",
              "cursor-cloud", "grok")
KEPT_POOLS = ("claude", "opencode-go", "clinepass", "copilot")
DISPATCH = Path(__file__).resolve().parent.parent / "bin" / "acp-dispatch"


def only(*names: str):
    return mock.patch.object(r, "discover", side_effect=lambda quota=None: [r.BY_NAME[n] for n in names])


class TestFloorsAreGone(unittest.TestCase):
    def test_open_pools_take_work_down_to_nearly_empty_and_kept_pools_do_not(self):
        for name in OPEN_POOLS:
            self.assertEqual(r.headroom_floor(r.BY_NAME[name], 15.0), r.EMPTY_POOL_PERCENT, name)
            self.assertEqual(r.headroom_floor(r.BY_NAME[name], 10.0, default=10.0), r.EMPTY_POOL_PERCENT, name)
        for name in KEPT_POOLS:
            self.assertEqual(r.headroom_floor(r.BY_NAME[name], 15.0), 15.0, name)

    def test_an_explicit_min_headroom_still_wins(self):
        self.assertEqual(r.headroom_floor(r.BY_NAME["zai"], 30.0), 30.0)

    def test_zai_is_routed_at_5_percent_but_claude_is_not(self):
        with only("zai"):
            self.assertEqual(r.route("code", quota={"zai": {"remaining": 5.0}}).service.name, "zai")
            self.assertIsNone(r.route("code", quota={"zai": {"remaining": 0.0}}))
            self.assertIsNone(r.route("code", quota={"zai": {"remaining": 5.0}}, min_headroom=30.0))
        with only("claude"):
            self.assertIsNone(r.route("code", quota={"claude": {"remaining": 5.0}}))

    def test_codex_everyday_kinds_need_only_a_complete_reading(self):
        codex = r.BY_NAME["codex"]
        low = {"codex": {"remaining": 8.0, "windows": {"5h": 8.0, "weekly": 40.0}}}
        self.assertTrue(codex.eligible("code", low))
        self.assertFalse(codex.eligible("code", {}))                                       # no reading still fails closed
        self.assertFalse(codex.eligible("code", {"codex": {"remaining": 8.0, "windows": {"5h": 8.0, "weekly": None}}}))

    def test_astra_is_estimated_by_the_measured_median_or_the_brief_default_not_60(self):
        codex = r.BY_NAME["codex"]
        info = {"remaining": 30.0, "windows": {"5h": 30.0}}
        self.assertEqual(r.estimate_floor(codex, "frontier", info)[0], 0.0)
        self.assertTrue(r.pool_fits(codex, "frontier", info))
        self.assertEqual(r.estimate_floor(r.BY_NAME["antigravity-claude"], "code", info)[0], 0.0)
        self.assertEqual(r.estimate_floor(r.BY_NAME["claude"], "code", info)[0], 8.0)       # claude's floor stays

    def test_no_repo_override_remains(self):
        self.assertEqual(r.repo_floors("tendcf"), {})
        self.assertEqual(r.repo_floors("nix2cf"), {})

    def test_the_judged_frontier_grant_needs_only_a_codex_reading(self):
        t = {"frontier2_min_left": ade_gates.FRONTIER_DEFAULTS["frontier2_min_left"]}
        now = datetime.now(UTC)
        self.assertIsNone(ade_gates.judged_pool_block(2, t, now, None, 12.0))
        self.assertIsNotNone(ade_gates.judged_pool_block(2, t, now, None, None))           # no reading: closed


class TestDispatchSpendsDown(Base):
    def snap(self, provider: str, left: float) -> dict[str, str]:
        path = self.tmp / f"{provider}-{left}.json"
        path.write_text(json.dumps({"collected_at": "2099-01-01T00:00:00+00:00", "snapshot": {"accounts": [{
            "provider": provider, "windows": [{"label": "5h", "remaining_percent": left}]}]}}))
        return {"AIUSE_SNAPSHOT": str(path)}

    def go(self, agent: str, provider: str, left: float, kind: str, *extra: str):
        repo = self.tmp / "work"
        repo.mkdir(exist_ok=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
        env = {**os.environ, **self.base_env("writes", **self.snap(provider, left))}
        return subprocess.run([sys.executable, str(DISPATCH), agent, "--model", "m1", "--name", "s1", "-p", "x", "-C", str(repo),
                               "--out", str(self.out), "--acp-run", str(self.fake), "--kind", kind, "--no-model-check",
                               "--no-preflight", *extra], check=False, capture_output=True, text=True, env=env)

    def test_zcode_runs_at_4_percent(self):
        p = self.go("zcode", "zai", 4.0, "bulk")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)

    def test_a_zcode_pool_at_zero_is_still_refused_as_empty(self):
        p = self.go("zcode", "zai", 0.0, "bulk")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("headroom 0.0% < minimum", p.stdout + p.stderr)

    def test_claude_keeps_its_10_percent_minimum(self):
        p = self.go("claude", "claude", 6.0, "code")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("< minimum 10.0%", p.stdout + p.stderr)

    def test_an_explicit_min_headroom_applies_to_an_open_pool_too(self):
        p = self.go("zcode", "zai", 20.0, "bulk", "--min-headroom", "30")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("< minimum 30.0%", p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
