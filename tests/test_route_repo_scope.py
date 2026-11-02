#!/usr/bin/env python3
"""Per-repo / per-seat scope of a routing pool (djbclark 2026-11-02): opencode-go routes only for the
techno-euphora project and the Hermes seat. `[[service]] allow_repos` / `allow_seats`; a scoped
service is skipped as repo-scoped everywhere else (no primary, no alternative), and acp-dispatch
refuses it there whatever ACP_OPERATOR_APPROVED says."""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import override
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import route_agent as r
from test_acp_dispatch import Base, run
from test_route_agent import IDLE

OTHER_REPO = "djbclark-ade"
SCOPED_REPO = "techno-euphora"
ONLY_GO = {name: {"remaining": 0.0} for name in IDLE} | {"opencode-go": {"remaining": 100.0}}
# every pool measured and idle, opencode-go the most idle: out of scope it must still not appear
GO_BEST = dict(IDLE, **{"opencode-go": {"remaining": 100.0}})
SCOPED_KINDS = ("bulk", "mechanical")


def names(choice: r.Choice | None) -> list[str]:
    return [] if choice is None else [choice.service.name, *choice.alternatives]


def only_go() -> contextlib.AbstractContextManager[object]:
    return mock.patch.object(r, "discover", side_effect=lambda quota=None: [r.BY_NAME["opencode-go"]])


class TestRouteScope(unittest.TestCase):
    def test_opencode_go_is_scoped_by_the_policy(self):
        go = r.BY_NAME["opencode-go"]
        self.assertEqual((go.allow_repos, go.allow_seats), ((SCOPED_REPO,), ("hermes",)))

    def test_never_service_or_alternative_for_another_repo(self):
        for kind in SCOPED_KINDS:
            for quota in (GO_BEST, ONLY_GO):
                self.assertNotIn("opencode-go", names(r.route(kind, quota=quota, repo=OTHER_REPO)), kind)
                self.assertNotIn("opencode-go", names(r.route(kind, quota=quota)), kind)   # unknown repo, no seat
        for quota in (GO_BEST, ONLY_GO):
            for _, c in r.plan(["bulk", "mechanical", "bulk", "mechanical"], quota=quota, repo=OTHER_REPO):
                self.assertNotIn("opencode-go", names(c))

    def test_a_scoped_pool_alone_leaves_the_slice_unrouted_elsewhere(self):
        with only_go():   # discovery also surfaces whatever TUIs this machine has installed (goose, muse): leave them out
            self.assertIsNone(r.route("bulk", quota=ONLY_GO, repo=OTHER_REPO))
            self.assertIn("no pool", r.unrouted_why("bulk", ONLY_GO, repo=OTHER_REPO))

    def test_the_scoped_repo_can_route_it(self):
        for kind in SCOPED_KINDS:
            self.assertEqual(r.route(kind, quota=ONLY_GO, repo=SCOPED_REPO).service.name, "opencode-go")
        self.assertEqual(r.route("mechanical", quota=GO_BEST, repo=SCOPED_REPO).service.name, "opencode-go")
        self.assertEqual(r.plan(["bulk"], quota=ONLY_GO, repo=SCOPED_REPO)[0][1].service.name, "opencode-go")

    def test_the_hermes_seat_can_route_it_from_any_repo(self):
        for repo in (OTHER_REPO, None):
            self.assertEqual(r.route("bulk", quota=ONLY_GO, repo=repo, seat="hermes").service.name, "opencode-go")
        with only_go():
            self.assertIsNone(r.route("bulk", quota=ONLY_GO, repo=OTHER_REPO, seat="dann"))

    def test_the_match_ignores_case(self):
        self.assertEqual(r.route("bulk", quota=ONLY_GO, repo="Techno-Euphora").service.name, "opencode-go")
        self.assertEqual(r.route("bulk", quota=ONLY_GO, seat="HERMES").service.name, "opencode-go")

    def test_code_still_never_goes_to_opencode_go_in_the_scoped_repo(self):
        for quota in (GO_BEST, ONLY_GO):
            self.assertNotIn("opencode-go", names(r.route("code", quota=quota, repo=SCOPED_REPO, seat="hermes")))

    def test_services_without_an_allow_list_are_unaffected(self):
        without_go = {k: v for k, v in GO_BEST.items() if k != "opencode-go"}
        for kind in ("bulk", "mechanical", "code", "research"):
            ref = r.route(kind, quota=without_go, repo=OTHER_REPO)
            for repo, seat in ((SCOPED_REPO, None), (None, None), (OTHER_REPO, "hermes")):
                got = r.route(kind, quota=without_go, repo=repo, seat=seat)
                self.assertEqual(names(got), names(ref), (kind, repo, seat))

    def test_scope_is_config_alone_for_any_service(self):
        zai = replace(r.BY_NAME["zai"], allow_repos=("someproj",), allow_seats=())
        self.assertIsNone(zai.scope_block("someproj"))
        self.assertIsNone(zai.scope_block("SomeProj"))
        self.assertIn("repo-scoped", zai.scope_block("other", "hermes"))
        self.assertEqual([s.name for s in r.in_scope([zai, r.BY_NAME["codex"]], "other", None)], ["codex"])


class TestPolicyFile(unittest.TestCase):
    def policy_with(self, allow: str) -> Path:
        text = Path(r.POLICY_PATH).read_text().replace(
            'allow_repos = ["techno-euphora"]', allow, 1)
        tmp = Path(tempfile.mkdtemp(prefix="route-scope-")) / "routing.toml"
        tmp.write_text(text)
        return tmp

    def test_a_malformed_allow_list_is_rejected(self):
        for bad in ('allow_repos = "techno-euphora"', 'allow_repos = [1]', 'allow_repos = [""]'):
            with self.assertRaisesRegex(ValueError, "allow_repos must be an array"):
                r.load_policy(self.policy_with(bad))

    def test_the_effective_policy_shows_the_scope(self):
        row = next(s for s in r.policy_public()["services"] if s["name"] == "opencode-go")
        self.assertEqual((row["allow_repos"], row["allow_seats"]), ([SCOPED_REPO], ["hermes"]))
        self.assertRegex(r.policy_markdown(), r"opencode-go: repos techno-euphora seats hermes")


class TestPlanCli(unittest.TestCase):
    def plan_names(self, *argv: str, env: dict[str, str] | None = None) -> list[str | None]:
        out = io.StringIO()
        with (only_go(), mock.patch.object(r, "load_snapshot", return_value=(ONLY_GO, 5.0)),
              mock.patch.object(r, "operator_disabled", return_value=set()),
              mock.patch.object(r, "repo_of", return_value=OTHER_REPO),
              mock.patch.dict(os.environ, {**{k: v for k, v in os.environ.items() if k != "ROUTE_SEAT"}, **(env or {})},
                              clear=True),
              contextlib.redirect_stdout(out)):
            self.assertEqual(r.main(["plan", "--kinds", "bulk", "--json", *argv]), 0)
        return [s["service"] for s in json.loads(out.getvalue())["slices"]]

    def test_default_caller_is_out_of_scope(self):
        self.assertEqual(self.plan_names(), [None])

    def test_repo_flag_and_seat_flag_and_env_admit_it(self):
        self.assertEqual(self.plan_names("--repo", SCOPED_REPO), ["opencode-go"])
        self.assertEqual(self.plan_names("--seat", "hermes"), ["opencode-go"])
        self.assertEqual(self.plan_names(env={"ROUTE_SEAT": "hermes"}), ["opencode-go"])
        self.assertEqual(self.plan_names(env={"ROUTE_SEAT": "dann"}), [None])


class TestDispatchScope(Base):
    @override
    def setUp(self) -> None:
        super().setUp()
        self.te = self.tmp / SCOPED_REPO
        for d in (self.repo, self.te):
            d.mkdir(exist_ok=True)
            subprocess.run(["git", "init", "-q", str(d)], check=True, capture_output=True)

    def go(self, where: Path, *extra: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        e = self.base_env("writes", **(env or {}))
        full = {**{k: v for k, v in os.environ.items() if k != "ROUTE_SEAT"}, **e}
        return subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent.parent / "bin" / "acp-dispatch"), "opencode",
             "--model", "opencode-go/minimax-m3", "--name", "s1", "-p", "do the thing", "-C", str(where),
             "--out", str(self.out), "--acp-run", str(self.fake), "--kind", "bulk", "--no-model-check",
             "--no-preflight", *extra],
            check=False, capture_output=True, text=True, env=full)

    def test_another_repo_is_refused_and_route_override_does_not_skip_it(self):
        for env in ({}, {"ACP_OPERATOR_APPROVED": "route-override"}):
            r_ = self.go(self.repo, env=env)
            self.assertEqual(r_.returncode, 2, r_.stderr)
            self.assertIn("opencode-go is repo-scoped", r_.stderr)
            self.assertIn("route-override does not skip this", r_.stderr)
            self.assertFalse((self.out / "jobs" / "s1.json").exists())

    def test_a_go_advisory_does_not_skip_the_scope_either(self):
        r_ = self.go(self.repo, "--go-advisory", "--perm", "read-only", "--timeout", "600",
                     env={"ACP_OPERATOR_APPROVED": "route-override"})
        self.assertEqual(r_.returncode, 2, r_.stderr)
        self.assertFalse((self.out / "jobs" / "s1.json").exists())

    def test_the_scoped_repo_dispatches(self):
        r_ = self.go(self.te)
        self.assertEqual(r_.returncode, 0, r_.stderr)
        self.assertEqual(self.record()["kind"], "bulk")

    def test_the_hermes_seat_dispatches_from_any_repo(self):
        r_ = self.go(self.repo, env={"ROUTE_SEAT": "hermes"})
        self.assertEqual(r_.returncode, 0, r_.stderr)

    def test_a_service_without_an_allow_list_is_unaffected(self):
        r_ = run(["zcode", "--model", "m1", "--name", "s1", "-p", "x", "-C", str(self.repo), "--out", str(self.out),
                  "--acp-run", str(self.fake), "--kind", "bulk", "--no-model-check", "--no-preflight"],
                 env=self.base_env())
        self.assertEqual(r_.returncode, 0, r_.stderr)


if __name__ == "__main__":
    unittest.main()
