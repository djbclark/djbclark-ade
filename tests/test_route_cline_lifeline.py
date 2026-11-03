#!/usr/bin/env python3
"""cline / clinepass (djbclark 2026-11-02): eligible only for the techno-euphora repo and the hermes seat, and only while its
headroom is at least `lifeline_floor_percent` (40); unmeasured headroom counts as under the floor. The 2026-10-23 lifeline
rationale (Hermes and Dann live on this pool) is why the floor exists; route-override skips neither the scope nor the floor."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import override
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import route_agent as r
from test_acp_dispatch import Base

SCOPED_REPO = "techno-euphora"
OTHER_REPO = "djbclark-ade"
DISPATCH = Path(__file__).resolve().parent.parent / "bin" / "acp-dispatch"


def only_cline() -> mock._patch:
    return mock.patch.object(r, "discover", side_effect=lambda quota=None: [r.BY_NAME["clinepass"]])


def quota(left: float | None) -> dict:
    return {"clinepass": {"remaining": left}}


class TestPolicy(unittest.TestCase):
    def test_cline_is_scoped_and_floored_and_no_longer_gated_or_never_routed(self):
        svc = r.BY_NAME["clinepass"]
        self.assertEqual((svc.allow_repos, svc.allow_seats, svc.lifeline_floor_percent), ((SCOPED_REPO,), ("hermes",), 40.0))
        self.assertNotIn("clinepass", r.NEVER_ROUTE)
        self.assertNotIn("cline", r.OPERATOR_GATED)
        self.assertNotIn("cline", r.POLICY["dispatch"]["operator_gated"])
        self.assertIn("hermes", r.POLICY["dispatch"]["operator_gated"])


class TestRoute(unittest.TestCase):
    def test_refused_for_another_repo_at_any_headroom(self):
        with only_cline():
            for left in (100.0, 60.0, None):
                for kind in ("bulk", "mechanical", "code"):
                    self.assertIsNone(r.route(kind, quota=quota(left), repo=OTHER_REPO), (kind, left))
                    self.assertIsNone(r.route(kind, quota=quota(left)), (kind, left))

    def test_never_an_alternative_elsewhere(self):
        for kind in ("bulk", "mechanical", "code"):
            c = r.route(kind, quota={"clinepass": {"remaining": 100.0}}, repo=OTHER_REPO)
            self.assertTrue(c is None or "clinepass" not in [c.service.name, *c.alternatives], kind)

    def test_allowed_for_the_scoped_repo_above_the_floor_and_at_it(self):
        with only_cline():
            for left in (100.0, 40.0):
                for kind in ("bulk", "code"):
                    self.assertEqual(r.route(kind, quota=quota(left), repo=SCOPED_REPO).service.name, "clinepass", (kind, left))

    def test_refused_under_the_floor_and_when_unmeasured(self):
        with only_cline():
            for left in (39.9, 15.0, 0.0, None):
                self.assertIsNone(r.route("bulk", quota=quota(left), repo=SCOPED_REPO), left)
            self.assertIsNone(r.route("bulk", quota={}, repo=SCOPED_REPO))     # no reading at all

    def test_the_hermes_seat_is_admitted_from_any_repo_but_the_floor_still_holds(self):
        with only_cline():
            self.assertEqual(r.route("bulk", quota=quota(80.0), repo=OTHER_REPO, seat="hermes").service.name, "clinepass")
            self.assertIsNone(r.route("bulk", quota=quota(30.0), repo=OTHER_REPO, seat="hermes"))


class TestDispatch(Base):
    @override
    def setUp(self) -> None:
        super().setUp()
        self.te = self.tmp / SCOPED_REPO
        for d in (self.repo, self.te):
            d.mkdir(exist_ok=True)
            subprocess.run(["git", "init", "-q", str(d)], check=True, capture_output=True)

    def snap(self, left: float | None) -> dict[str, str]:
        if left is None:
            return {}
        path = self.tmp / f"cline-{left}.json"
        path.write_text(json.dumps({"collected_at": "2099-01-01T00:00:00+00:00", "snapshot": {"accounts": [{
            "provider": "clinepass", "windows": [{"label": "month", "remaining_percent": left}]}]}}))
        return {"AIUSE_SNAPSHOT": str(path)}

    def cline(self, where: Path, left: float | None, *extra: str, env: dict[str, str] | None = None):
        e = self.base_env("writes", **self.snap(left), **(env or {}))
        full = {**{k: v for k, v in os.environ.items() if k != "ROUTE_SEAT"}, **e}
        return subprocess.run(
            [sys.executable, str(DISPATCH), "cline", "--model", "cline-pass/deepseek-v4.1-flash", "--name", "s1", "-p", "x",
             "-C", str(where), "--out", str(self.out), "--acp-run", str(self.fake), "--kind", "bulk", "--no-model-check",
             "--no-preflight", *extra], check=False, capture_output=True, text=True, env=full)

    def test_another_repo_is_refused_with_and_without_route_override(self):
        for env in ({}, {"ACP_OPERATOR_APPROVED": "route-override"}):
            p = self.cline(self.repo, 100.0, env=env)
            self.assertEqual(p.returncode, 2, p.stderr)
            self.assertIn("clinepass is repo-scoped", p.stderr)
            self.assertFalse((self.out / "jobs" / "s1.json").exists())

    def test_the_scoped_repo_above_the_floor_dispatches_without_any_operator_approval(self):
        p = self.cline(self.te, 55.0)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.record()["kind"], "bulk")

    def test_the_hermes_seat_dispatches_from_another_repo(self):
        self.assertEqual(self.cline(self.repo, 55.0, env={"ROUTE_SEAT": "hermes"}).returncode, 0)

    def test_under_the_floor_and_unmeasured_are_refused_and_route_override_does_not_skip_it(self):
        for left in (39.0, 5.0, None):
            for env in ({}, {"ACP_OPERATOR_APPROVED": "route-override"}):
                p = self.cline(self.te, left, env=env)
                self.assertEqual(p.returncode, 2, (left, p.stderr))
                self.assertIn("lifeline pool", p.stderr)
                self.assertIn("40% floor", p.stderr)
                self.assertFalse((self.out / "jobs" / "s1.json").exists())

    def test_the_floor_is_inclusive(self):
        self.assertEqual(self.cline(self.te, 40.0).returncode, 0)


if __name__ == "__main__":
    unittest.main()
