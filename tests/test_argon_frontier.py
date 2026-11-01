"""Gemini 4 Argon as a fallback-only `frontier` model (operator 2026-10-31), on aiuse schema 1.5.

aiuse 1.5 files the Argon weekly window under its own pool family `gemini_argon` (antigravity/gemini_argon beside
antigravity/gemini), because a tiny Argon call moved only that window. These tests drive acp-dispatch end to end through the
fake acp-run (admission, refusals, dry-run), the readers it shares with the auto-resume (`aiuse_reset_time`,
`pool_headroom_live`, the exhaustion note), route_agent's pool reading and its planner, with 1.5-shaped snapshots in which
Gemini (Flash) weekly is nearly exhausted and Argon is not, and the reverse.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from test_acp_dispatch import SCRIPT
from test_acp_dispatch_routing import RoutingDispatch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import failover  # noqa: E402
import route_agent as ra  # noqa: E402

_loader = importlib.machinery.SourceFileLoader("acp_dispatch_argon", str(SCRIPT))
_spec = importlib.util.spec_from_loader("acp_dispatch_argon", _loader)
acpd = importlib.util.module_from_spec(_spec)
_loader.exec_module(acpd)

ARGON = "gemini-4-argon"
FLASH = "gemini-3.8-flash"
NO_GOVERNOR = {"CLAUDE_GOVERNOR_STATE": "/nonexistent/fleet-governor.json"}


def iso(delta_hours: float) -> str:
    return (datetime.now(UTC) + timedelta(hours=delta_hours)).isoformat()


def window(label: str, left: float, family: str, **extra) -> dict:
    return {"label": label, "remaining_percent": left, "headroom_percent": left, "pool_family": family,
            "state": "exhausted" if left <= 1 else "ok", "resets_at": iso(30), **extra}


def antigravity(gemini_weekly: float = 4.0, argon_weekly: float | None = 57.0, **argon_extra) -> dict:
    """The antigravity account in aiuse 1.5 shape (2026-10-31): Argon is `gemini_argon`, Flash windows are `gemini`."""
    windows = [window("Gemini 5-hour", 96.8, "gemini"), window("Gemini weekly", gemini_weekly, "gemini"),
               window("Claude/GPT 5-hour", 100.0, "claude_gpt"), window("Claude/GPT weekly", 49.0, "claude_gpt")]
    if argon_weekly is not None:
        windows.append(window("Gemini 4 Argon weekly", argon_weekly, "gemini_argon", **argon_extra))
    return {"provider": "antigravity", "windows": windows}


def codex(left: float) -> dict:
    return {"provider": "codex", "windows": [window("5h", left, "") | {"pool_family": None}]}


def claude(left: float) -> dict:
    return {"provider": "claude", "windows": [window("weekly", left, "default")]}


def snapshot_file(path: Path, *accounts: dict) -> str:
    path.write_text(json.dumps({"collected_at": "2099-01-01T00:00:00+00:00", "snapshot": {"accounts": list(accounts)}}))
    return str(path)


class ArgonDispatchBase(RoutingDispatch):
    """acp-dispatch against 1.5 snapshots. codex at 30% is short for frontier (astra reserves 60%), claude at 80% is not."""

    def agy(self, model: str, *extra: str, kind: str = "frontier", accounts: tuple[dict, ...] | None = None,
            env: dict[str, str] | None = None):
        accounts = accounts if accounts is not None else (antigravity(), codex(30.0), claude(80.0))
        snap = snapshot_file(self.tmp / "latest.json", *accounts)
        return self.dispatch_agent("agy", model, "--kind", kind, "--no-model-check", "--no-preflight", "--est-pct", "5",
                                   *extra, env={"AIUSE_SNAPSHOT": snap, **NO_GOVERNOR, **(env or {})})


class ArgonDispatch(ArgonDispatchBase):
    def test_argon_is_admitted_on_its_own_window_although_gemini_weekly_is_4_percent(self):
        r = self.agy(ARGON, "--frontier-reason", "fallback: astra is short of quota this week")
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = self.record()
        self.assertEqual((rec["service"], rec["kind"], rec["role"]), ("antigravity-argon", "frontier", "advise"))
        self.assertIn("--model gemini-4-argon", rec["cmd"])
        # the gate: no claude/codex allowance exists for this pool, and the record says so
        self.assertIsNone(rec["frontier_judged"])
        self.assertIn("the allowance covers those two pools only; this is service antigravity-argon", rec["frontier_judged_note"])

    def test_argon_is_refused_while_codex_and_claude_both_have_quota_and_route_override_allows_it(self):
        accounts = (antigravity(), codex(90.0), claude(80.0))
        r = self.agy(ARGON, accounts=accounts)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("fallback behind codex, claude", r.stderr)
        self.assertFalse((self.out / "jobs/s1.json").exists())
        over = self.agy(ARGON, accounts=accounts, env={"ACP_OPERATOR_APPROVED": "route-override"})
        self.assertEqual(over.returncode, 0, over.stderr)

    def test_one_short_pool_is_enough(self):
        r = self.agy(ARGON, accounts=(antigravity(), codex(90.0), claude(5.0)))      # claude short, codex fine
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_argon_refused_naming_its_window_when_it_is_exhausted_though_flash_has_room(self):
        r = self.agy(ARGON, accounts=(antigravity(gemini_weekly=90.0, argon_weekly=0.0), codex(30.0), claude(80.0)))
        self.assertEqual(r.returncode, 5, r.stderr)
        rec = self.record()
        self.assertEqual(rec["status"], "unavailable")
        self.assertIn("binding window: Gemini 4 Argon weekly", rec["detail"])

    def test_an_argon_estimate_beyond_its_window_is_refused_as_wont_fit_naming_it(self):
        accounts = (antigravity(gemini_weekly=90.0, argon_weekly=15.0), codex(30.0), claude(80.0))
        r = self.agy(ARGON, "--est-pct", "30", accounts=accounts)
        self.assertEqual(r.returncode, 5, r.stderr)
        rec = self.record()
        self.assertEqual(rec["unavailable_class"], "wont-fit")
        self.assertIn("binding window: Gemini 4 Argon weekly, 15.0% left", rec["detail"])

    def test_no_argon_reading_fails_closed_naming_the_window(self):
        accounts = (antigravity(argon_weekly=None), codex(30.0), claude(80.0))
        r = self.agy(ARGON, accounts=accounts)
        self.assertEqual(r.returncode, 5, r.stderr)
        self.assertIn("no fresh quota reading for Gemini 4 Argon weekly", self.record()["detail"])
        dry = self.agy(ARGON, "--dry-run", accounts=accounts)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertIn("would refuse: class=headroom", dry.stdout)
        self.assertIn("no fresh reading for Gemini 4 Argon weekly", dry.stdout)

    def test_a_frozen_argon_window_is_not_routed_on(self):
        accounts = (antigravity(argon_weekly=57.0, measurement_frozen=True, stale=True), codex(30.0), claude(80.0))
        r = self.agy(ARGON, accounts=accounts)
        self.assertEqual(r.returncode, 5, r.stderr)
        self.assertIn("binding window: Gemini 4 Argon weekly, 0.0% left", self.record()["detail"])

    def test_dry_run_passes_the_guard_at_gemini_4_percent_and_prints_the_argon_command(self):
        ok = self.agy(ARGON, "--dry-run")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertIn("--model gemini-4-argon", ok.stdout)
        self.assertNotIn("would refuse", ok.stdout)
        low = self.agy(ARGON, "--dry-run", accounts=(antigravity(argon_weekly=0.0), codex(30.0), claude(80.0)))
        self.assertIn("would refuse: class=headroom (binding window: Gemini 4 Argon weekly, 0.0% left)", low.stdout)

    def test_a_flash_slice_ignores_a_drained_argon_window(self):
        r = self.agy(FLASH, kind="bulk", accounts=(antigravity(gemini_weekly=60.0, argon_weekly=0.0),))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.record()["service"], "antigravity")

    def test_a_flash_slice_is_still_refused_on_its_own_low_window(self):
        r = self.agy(FLASH, kind="bulk", accounts=(antigravity(gemini_weekly=0.0, argon_weekly=90.0),))
        self.assertEqual(r.returncode, 5, r.stderr)

    def test_argon_needs_kind_frontier(self):
        r = self.agy(ARGON, kind="bulk")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("is a frontier model; use --kind frontier", r.stderr)


def git(*argv: str, cwd: Path) -> None:
    subprocess.run(["git", "-C", str(cwd), *argv], check=True, capture_output=True)


def make_repo(path: Path, origin: str | None) -> Path:
    path.mkdir(parents=True)
    git("init", "-q", cwd=path)
    git("config", "user.email", "t@example.com", cwd=path)
    git("config", "user.name", "t", cwd=path)
    (path / "README").write_text("x\n")
    git("add", "README", cwd=path)
    git("commit", "-q", "-m", "i", cwd=path)
    if origin:
        git("remote", "add", "origin", origin, cwd=path)
    return path


class ArgonRepoOverride(ArgonDispatchBase):
    """The 2026-11-01 ruling: in tendcf and nix2cf only, astra may run down to 20% of Codex quota left (config/routing.toml
    [dispatch.repo_overrides]). The repository is resolved from `-C DIR` through the origin remote, so a worktree counts."""

    def setUp(self) -> None:
        super().setUp()
        ra._REPO_MEMO.clear()
        self.addCleanup(ra._REPO_MEMO.clear)
        self.wt = {}
        for name in ("tendcf", "nix2cf", "plektra"):
            main = make_repo(self.tmp / f"{name}-main", f"https://github.com/djbclark/{name}.git")
            wt = self.tmp / f"{name}-foo-wt"
            git("worktree", "add", "-q", "-b", "foo", str(wt), cwd=main)
            self.wt[name] = wt

    def astra(self, repo: str, left: float, *extra: str, env: dict[str, str] | None = None):
        return self.dispatch_agent("codex", "gpt-6-astra", "-C", str(self.wt[repo]), "--kind", "frontier", "--no-model-check",
                                   "--no-preflight", *extra, env={**self.snap_codex(left), **(env or {})})

    def estimate(self, repo: str, left: float) -> float:
        r = self.astra(repo, left, "--effort", "high", "--dry-run", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["estimated_usage_pct"]

    def snap_codex(self, remaining: float) -> dict[str, str]:
        snap = self.tmp / "codex.json"
        snapshot_file(snap, codex(remaining), claude(80.0), antigravity())
        return {"AIUSE_SNAPSHOT": str(snap), **NO_GOVERNOR}

    # repository resolution
    def test_the_repo_is_the_origin_remote_name_in_a_plain_checkout_and_in_a_worktree(self):
        for name in ("tendcf", "nix2cf", "plektra"):
            self.assertEqual(ra.repo_of(self.tmp / f"{name}-main"), name)
            self.assertEqual(ra.repo_of(self.wt[name]), name)

    def test_remote_url_shapes_and_the_no_remote_fallbacks(self):
        for url in ("git@github.com:djbclark/TendCF.git", "ssh://git@host/x/tendcf", "https://forgejo.mit.edu/djbclark/tendcf/"):
            repo = make_repo(self.tmp / f"r{abs(hash(url))}", url)
            self.assertEqual(ra.repo_of(repo), "tendcf", url)
        bare = make_repo(self.tmp / "tendcf", None)                                # no origin: the directory's name
        self.assertEqual(ra.repo_of(bare), "tendcf")
        git("worktree", "add", "-q", "-b", "w", str(self.tmp / "elsewhere-wt"), cwd=bare)
        self.assertEqual(ra.repo_of(self.tmp / "elsewhere-wt"), "tendcf")          # a worktree shares the common dir
        self.assertIsNone(ra.repo_of(self.tmp / "not-a-repo-dir-that-exists-nowhere"))
        self.assertIsNone(ra.repo_of(None))

    def test_the_override_table_names_exactly_tendcf_and_nix2cf(self):
        self.assertEqual(ra.repo_floors("tendcf"), {"codex:frontier": 20.0})
        self.assertEqual(ra.repo_floors("NIX2CF"), {"codex:frontier": 20.0})
        self.assertEqual(ra.repo_floors("plektra"), {})
        self.assertEqual(ra.repo_floors(None), {})

    # acp-dispatch end to end
    def test_astra_at_42_percent_is_admitted_in_a_tendcf_or_nix2cf_worktree_with_the_override_estimate(self):
        for name in ("tendcf", "nix2cf"):
            self.assertEqual(self.estimate(name, 42.0), 20.0, name)
            r = self.astra(name, 42.0, "--name", f"{name}-s")
            self.assertEqual(r.returncode, 0, (name, r.stderr))
            self.assertEqual(self.record(f"{name}-s")["estimated_usage_pct"], 20.0)   # the in-flight reservation follows it

    def test_astra_at_15_percent_is_refused_in_tendcf_naming_the_floor(self):
        r = self.astra("tendcf", 15.0)
        self.assertEqual(r.returncode, 5, r.stderr)
        self.assertIn("estimated use 20.0% > 15.0% left", self.record()["detail"] + r.stderr)

    def test_astra_at_42_percent_is_refused_as_before_in_another_repo(self):
        self.assertEqual(self.estimate("plektra", 42.0), 60.0)
        r = self.astra("plektra", 42.0)
        self.assertEqual(r.returncode, 5, r.stderr)
        self.assertIn("estimated use 60.0% > 42.0% left", self.record()["detail"] + r.stderr)
        plain = self.dispatch_agent("codex", "gpt-6-astra", "--kind", "frontier", "--no-model-check", "--no-preflight",
                                    "--name", "plain", env=self.snap_codex(42.0))          # a repo with no origin and another name
        self.assertEqual(plain.returncode, 5, plain.stderr)

    def test_a_larger_measured_median_is_capped_by_the_override_and_a_smaller_one_stays(self):
        def rec(pct):
            return {"agent": "codex", "model": "gpt-6-astra", "kind": "frontier", "effort": "high", "measured_usage_pct": pct}
        jobs = self.tmp / "state" / "hist" / "jobs"
        jobs.mkdir(parents=True)
        for k in range(3):
            (jobs / f"h{k}.json").write_text(json.dumps(rec(70.0)))
        self.assertEqual(self.estimate("tendcf", 90.0), 20.0)                        # median 70 capped to the repo's 20
        self.assertEqual(self.estimate("plektra", 90.0), 70.0)                       # elsewhere the measurement wins
        for k in range(3):
            (jobs / f"h{k}.json").write_text(json.dumps(rec(8.0)))
        ra._FRONTIER_HISTORY_MEMO.clear()
        self.assertEqual(self.estimate("tendcf", 90.0), 8.0)                         # a smaller median still wins
        self.assertEqual(self.estimate("plektra", 90.0), 8.0)                        # three measured slices beat the default floor everywhere

    def test_reroute_command_passes_the_records_repo_to_the_planner(self):
        seen = []
        rec = {"kind": "frontier", "dir": str(self.wt["tendcf"]), "service": "codex", "agent": "codex", "model": "gpt-6-astra"}
        with mock.patch.object(ra, "route", side_effect=lambda *a, **kw: seen.append(kw.get("repo")) or None):
            acpd.reroute_command(rec, self.tmp / "x.json")
            acpd.reroute_command({**rec, "dir": str(self.wt["plektra"])}, self.tmp / "x.json")
        self.assertEqual(seen, ["tendcf", "plektra"])

    def test_the_per_window_cap_through_dispatch_end_to_end(self):
        wk, fh = "Codex weekly quota (2)", "Codex 5-hour quota (1)"
        row = {"agent": "codex", "model": "gpt-6-astra", "kind": "frontier", "effort": "high", "measured_usage_pct": 2.0,
               "measured_usage_windows": {wk: 2.0, fh: 73.0}}
        jobs = self.tmp / "state" / "hist" / "jobs"
        jobs.mkdir(parents=True)
        for k in range(3):
            (jobs / f"h{k}.json").write_text(json.dumps(row))
        acct = {"provider": "codex", "windows": [window(wk, 42.0, "") | {"pool_family": None},
                                                  window(fh, 50.0, "") | {"pool_family": None}]}
        snap = snapshot_file(self.tmp / "twowin.json", acct, claude(80.0), antigravity())
        env = {"AIUSE_SNAPSHOT": snap, **NO_GOVERNOR}
        ok = self.astra("tendcf", 42.0, "--effort", "high", "--name", "capped", env=env)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        rec = self.record("capped")
        self.assertEqual(rec["estimated_usage_windows"], {wk: 2.0, fh: 20.0})        # 73 capped to 20, the smaller 2 stays
        no = self.astra("plektra", 42.0, "--effort", "high", "--name", "uncapped", env=env)
        self.assertEqual(no.returncode, 5, no.stderr)
        self.assertIn("estimated use 73.0% > 50.0% left on Codex 5-hour quota (1)", self.record("uncapped")["detail"] + no.stderr)

    def test_argon_is_refused_in_tendcf_where_astra_is_usable_and_admitted_elsewhere(self):
        accounts = (antigravity(), codex(42.0), claude(80.0))
        tendcf = self.agy(ARGON, "-C", str(self.wt["tendcf"]), accounts=accounts)
        self.assertEqual(tendcf.returncode, 2, tendcf.stderr)
        self.assertIn("fallback behind codex", tendcf.stderr)
        other = self.agy(ARGON, "-C", str(self.wt["plektra"]), accounts=accounts)
        self.assertEqual(other.returncode, 0, other.stderr)


class ArgonPools(unittest.TestCase):
    """route_agent's pool reading on 1.5 data: the two Gemini families are independent pools."""

    def pools(self, *accounts: dict) -> dict:
        return ra._providers_from_accounts(list(accounts), 0.0)

    def test_the_two_families_are_independent_pools(self):
        p = self.pools(antigravity(4.0, 57.0))
        self.assertEqual((p["antigravity-argon"]["remaining"], p["antigravity"]["remaining"]), (57.0, 4.0))
        p = self.pools(antigravity(60.0, 0.0))
        self.assertEqual((p["antigravity-argon"]["remaining"], p["antigravity"]["remaining"]), (0.0, 60.0))

    def test_a_frozen_window_reads_exhausted_and_only_its_own_pool(self):
        p = self.pools(antigravity(60.0, 57.0, measurement_frozen=True))
        self.assertEqual((p["antigravity-argon"]["remaining"], p["antigravity"]["remaining"]), (0.0, 60.0))

    def load(self, snap_accounts: tuple[dict, ...], available: list[dict]) -> dict:
        d = Path(tempfile.mkdtemp(prefix="argon-pools-"))
        snap = snapshot_file(d / "snap.json", *snap_accounts)
        canned = d / "avail.json"
        canned.write_text(json.dumps({"fresh": True, "age_seconds": 5.0, "available": available, "excluded": []}))
        with mock.patch.dict(os.environ, {"AIUSE_SNAPSHOT": snap, "ROUTE_AGENT_AIUSE_JSON": str(canned)}):
            return ra.load_snapshot()[0]

    @staticmethod
    def row(family: str, left: float) -> dict:
        return {"provider": "antigravity", "pool_family": family, "usable_now": True, "headroom_percent": left,
                "age_seconds": 5.0}

    def test_a_drained_argon_pool_is_absent_from_available_and_reads_zero_while_flash_keeps_its_row(self):
        # the real 1.5 shape: aiuse lists only usable pools, so an exhausted Argon window drops ITS row, not Flash's
        pools = self.load((antigravity(60.0, 0.0),), [self.row("gemini", 60.0)])
        self.assertEqual(pools["antigravity"]["remaining"], 60.0)
        self.assertEqual(pools["antigravity-argon"]["remaining"], 0.0)
        self.assertTrue(pools["antigravity-argon"]["absent_from_available"])

    def test_a_drained_flash_pool_does_not_hide_argon(self):
        pools = self.load((antigravity(0.0, 57.0),), [self.row("gemini_argon", 57.0)])
        self.assertEqual(pools["antigravity-argon"]["remaining"], 57.0)
        self.assertEqual(pools["antigravity"]["remaining"], 0.0)

    def test_the_model_decides_the_family_in_all_three_places(self):
        cases = {ARGON: "gemini_argon", "gemini-4-argon-high": "gemini_argon", FLASH: "gemini",
                 "gemini-3.8-flash-medium": "gemini", "claude-opus-5-5": "claude_gpt", "gpt-oss-120b-medium": "claude_gpt"}
        for model, family in cases.items():
            self.assertEqual(ra.map_agent_to_provider("agy", model), ("antigravity", family), model)
            self.assertEqual(acpd.map_agent_to_provider("agy", model), ("antigravity", family), model)
            tui = failover.REGISTRY["agy"]
            got = next((fam for prefix, _pool, fam in tui.pool_by_model if model.startswith(prefix)), None)
            self.assertEqual(got, family, f"failover.py pool_by_model for {model}")


class ArgonReaders(unittest.TestCase):
    """The readers the auto-resume and the exhaustion note share with the admission path, one test each."""

    def snap_env(self, *accounts: dict) -> dict[str, str]:
        d = Path(tempfile.mkdtemp(prefix="argon-readers-"))
        return {"AIUSE_SNAPSHOT": snapshot_file(d / "snap.json", *accounts)}

    def test_aiuse_reset_time_for_argon_is_its_own_window_not_flash_or_the_account(self):
        flash_reset, argon_reset = iso(5), iso(48)
        acct = antigravity(gemini_weekly=0.0, argon_weekly=0.0)
        for w in acct["windows"]:
            w["resets_at"] = argon_reset if w["pool_family"] == "gemini_argon" else flash_reset
        acct["available_at"] = flash_reset          # the account-level earliest reset, Flash's
        with mock.patch.dict(os.environ, self.snap_env(acct)):
            argon = acpd.aiuse_reset_time("agy", ARGON)
            flash = acpd.aiuse_reset_time("agy", FLASH)
        self.assertAlmostEqual(argon.timestamp(), datetime.fromisoformat(argon_reset).timestamp(), delta=1)
        self.assertAlmostEqual(flash.timestamp(), datetime.fromisoformat(flash_reset).timestamp(), delta=1)

    def fake_aiuse(self, available: list[dict]) -> str:
        d = Path(tempfile.mkdtemp(prefix="argon-fake-aiuse-"))
        path = d / "aiuse"
        path.write_text("#!/bin/sh\ncat <<'EOF'\n" + json.dumps({"available": available, "excluded": []}) + "\nEOF\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return str(path)

    def test_pool_headroom_live_reads_each_family_from_its_own_row(self):
        rows = [{"provider": "antigravity", "pool_family": "gemini", "headroom_percent": 4.0},
                {"provider": "antigravity", "pool_family": "gemini_argon", "headroom_percent": 57.0}]
        with mock.patch.dict(os.environ, {"ACP_DISPATCH_AIUSE": self.fake_aiuse(rows)}):
            self.assertEqual(acpd.pool_headroom_live("agy", ARGON)[0], 57.0)
            self.assertEqual(acpd.pool_headroom_live("agy", FLASH)[0], 4.0)

    def test_an_argon_row_missing_from_available_is_exhausted_not_go_ahead(self):
        rows = [{"provider": "antigravity", "pool_family": "gemini", "headroom_percent": 60.0}]
        with mock.patch.dict(os.environ, {"ACP_DISPATCH_AIUSE": self.fake_aiuse(rows)}):
            self.assertEqual(acpd.pool_headroom_live("agy", ARGON)[0], 0.0)
            self.assertEqual(acpd.pool_headroom_live("agy", FLASH)[0], 60.0)
            self.assertIsNone(acpd.pool_headroom_live("agy", "claude-opus-5-5")[0])     # other pools: unknown stays unknown

    def test_an_argon_quota_stop_notes_the_argon_family_only(self):
        log = Path(tempfile.mkdtemp(prefix="argon-note-")) / "calls"
        fake = Path(log.parent / "aiuse")
        fake.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\n')
        fake.chmod(0o755)
        with mock.patch.dict(os.environ, {"ACP_DISPATCH_AIUSE": str(fake)}):
            status, _ = acpd.record_quota_refusal_in_aiuse(
                "agy", ARGON, "FAILED quota: quotaResetTimeStamp:2099-01-01T00:00:00Z", 1, None)
        self.assertEqual(status, "ok")
        call = log.read_text().split()
        self.assertEqual(call[:2], ["note-exhausted", "antigravity"])
        self.assertEqual(call[call.index("--family") + 1], "gemini_argon")


class ArgonRouting(unittest.TestCase):
    """The planner: Argon is used only while codex OR claude is short for `frontier`, and never unmeasured."""

    def quota(self, codex: float | None = 80.0, claude: float | None = 80.0, argon: float | None = 57.0,
              fable: float | None = None, codex_windows: dict | None = None) -> dict:
        def pool(left: float | None, **extra) -> dict:
            return {"remaining": left, "windows": dict(codex_windows or {}) if extra.get("_codex") else {},
                    "sublimits": {k: v for k, v in extra.items() if k != "_codex"}, "billing_kind": "subscription"}
        q = {"antigravity": pool(4.0)}
        for name, left in (("codex", codex), ("claude", claude), ("antigravity-argon", argon)):
            if left is not None:
                extra = {"fable": fable} if name == "claude" and fable is not None else {}
                q[name] = pool(left, **extra, **({"_codex": True} if name == "codex" else {}))
        return q

    def pick(self, quota: dict, exclude: frozenset[str] = frozenset(), repo: str | None = None):
        with mock.patch.object(ra, "discover", return_value=list(ra.SERVICES)), \
                mock.patch.object(ra, "governor_hold", return_value=None):
            return ra.route("frontier", quota=quota, exclude=exclude, repo=repo)

    def names(self, quota: dict, **kw) -> str | None:
        c = self.pick(quota, **kw)
        return c.service.name if c else None

    def test_argon_is_never_used_while_codex_and_claude_both_have_quota(self):
        q = self.quota()
        self.assertEqual(self.names(q), "codex")
        self.assertEqual(self.names(q, exclude=frozenset({"codex"})), "claude")
        self.assertIsNone(self.pick(q, frozenset({"codex", "claude"})))        # a wave cap is not "short"

    def test_a_wave_of_frontier_slices_does_not_spill_onto_argon_while_both_have_quota(self):
        with mock.patch.object(ra, "discover", return_value=list(ra.SERVICES)), \
                mock.patch.object(ra, "governor_hold", return_value=None):
            rows = ra.plan(["frontier"] * 5, quota=self.quota())
        self.assertNotIn("antigravity-argon", [c.service.name for _, c in rows if c])

    def test_either_pool_being_short_makes_argon_a_candidate(self):
        for q in (self.quota(codex=0.0), self.quota(claude=0.0)):
            other = "claude" if q["codex"]["remaining"] == 0.0 else "codex"
            self.assertEqual(self.names(q), other)                              # still behind the pool that has quota
            self.assertEqual(self.names(q, exclude=frozenset({other})), "antigravity-argon")
        both = self.pick(self.quota(codex=0.0, claude=0.0))
        self.assertEqual(both.service.name, "antigravity-argon")
        self.assertEqual(both.model, "gemini-4-argon --effort high")
        self.assertIn("--kind frontier", both.dispatch)

    def test_codex_between_the_router_floor_and_the_astra_estimate_floor_is_short(self):
        # claude is healthy, so only codex can make a fallback reachable; 40% passes the router's 15% but acp-dispatch needs 60% for astra
        q = self.quota(codex=40.0, claude=80.0)
        self.assertEqual(self.names(q, exclude=frozenset({"codex", "claude"})), "antigravity-argon")
        self.assertEqual(self.names(q), "claude")                                 # and the planner no longer hands codex the slot
        # 70% is not short: Argon stays blocked, codex serves it
        q = self.quota(codex=70.0, claude=80.0)
        self.assertIsNone(self.names(q, exclude=frozenset({"codex", "claude"})))
        self.assertEqual(self.names(q), "codex")

    def test_the_planner_never_schedules_codex_below_the_astra_floor_for_frontier(self):
        with mock.patch.object(ra, "discover", return_value=list(ra.SERVICES)), \
                mock.patch.object(ra, "governor_hold", return_value=None):
            rows = ra.plan(["frontier", "frontier"], quota=self.quota(codex=42.0, claude=64.0))
        self.assertEqual([c.service.name if c else None for _, c in rows], ["claude", "antigravity-argon"])

    def calibrated(self, *rows: float | dict, layout: str = "task"):
        """A temp dispatch state root holding astra frontier job records (a float is a scalar `measured_usage_pct` at effort
        high; a dict is the record itself), the planner's history switched on and pointed at it."""
        tmp = Path(tempfile.mkdtemp(prefix="argon-hist-"))
        jobs = (tmp / "task" / "jobs") if layout == "task" else (tmp / "jobs")
        jobs.mkdir(parents=True)
        for k, row in enumerate(rows):
            rec = {"agent": "codex", "model": "gpt-6-astra", "kind": "frontier", "effort": "high"}
            rec.update({"measured_usage_pct": row} if not isinstance(row, dict) else row)
            (jobs / f"s{k}.json").write_text(json.dumps(rec))
        ra._FRONTIER_HISTORY_MEMO.clear()
        stack = mock.patch.dict(os.environ, {"ROUTE_AGENT_CALIBRATED_FLOOR": "on", "SESSION_FINDER_STATE": str(tmp / "sf")})
        patch = mock.patch.object(ra, "ACP_DISPATCH_STATE", tmp)
        stack.start(); patch.start()
        self.addCleanup(stack.stop); self.addCleanup(patch.stop); self.addCleanup(ra._FRONTIER_HISTORY_MEMO.clear)
        return tmp

    @staticmethod
    def codex_svc():
        return next(s for s in ra.SERVICES if s.name == "codex")

    def fits(self, left: float, windows: dict | None = None, repo: str | None = None) -> bool:
        return ra.pool_fits(self.codex_svc(), "frontier", {"remaining": left, "windows": windows or {}}, repo=repo)

    def dispatch_fits(self, tmp: Path, left: float, windows: dict | None = None, repo: str | None = None) -> bool:
        """acp-dispatch's own admission arithmetic (its estimate_pct, estimate_windows, window_fit) on the same history."""
        windows = {k: v for k, v in (windows or {}).items() if v is not None}
        acpd.load_policy()
        with mock.patch.object(acpd, "STATE_ROOT", tmp), mock.patch.dict(os.environ, {"SESSION_FINDER_STATE": str(tmp / "sf")}), \
                mock.patch.dict(acpd.REPO_FLOORS, ra.repo_floors(repo), clear=True):
            est, _ = acpd.estimate_pct(tmp / "other-task", "codex", "gpt-6-astra", "brief", None, "codex", "frontier", "high")
            per = {k: v for k, v in acpd.estimate_windows(tmp / "other-task", "codex", "gpt-6-astra", "frontier", "high",
                                                           "codex", list(windows)).items() if windows.get(k) is not None}
        if left < 15.0:
            return False
        return acpd.window_fit(per, windows)[0] is None if per else est <= left

    def test_a_calibrated_astra_is_short_only_below_its_measured_median(self):
        tmp = self.calibrated(20.0, 20.0, 20.0)                  # three slices measured at 20% each
        self.assertTrue(self.fits(40.0))
        self.assertFalse(self.fits(19.0))
        q = self.quota(codex=40.0, claude=80.0)                  # short under the static 60, usable under the measured 20
        argon = next(x for x in ra.SERVICES if x.name == "antigravity-argon")
        self.assertIsNotNone(ra.fallback_block(argon, "frontier", q))             # Argon stays blocked
        self.assertEqual(self.names(self.quota(codex=40.0, claude=0.0)), "codex")  # and codex still takes the slot
        self.assertEqual(self.fits(40.0), self.dispatch_fits(tmp, 40.0))

    def test_a_calibrated_astra_with_a_big_median_is_short_where_the_static_floor_says_usable(self):
        self.calibrated(70.0, 70.0, 70.0)
        q = self.quota(codex=65.0, claude=80.0)
        self.assertEqual(self.names(q), "claude")
        self.assertEqual(self.names(q, exclude=frozenset({"codex", "claude"})), "antigravity-argon")

    def test_fewer_than_three_measured_slices_never_beat_the_floor(self):
        self.calibrated(5.0, 5.0)
        self.assertFalse(self.fits(59.0))
        self.assertTrue(self.fits(60.0))

    def test_the_planner_and_dispatch_agree_on_the_same_history_and_reading(self):
        """The planner's pool_fits and acp-dispatch's admission over scalar and per-window histories, including the
        adversary's R1 case (weekly measured, a 5-hour window listed below the floor it inherits) and R3's window-only rows."""
        wk, fh = "Codex weekly quota (2)", "Codex 5-hour quota (1)"
        weekly = {"measured_usage_pct": 2.0, "measured_usage_windows": {wk: 2.0}}
        only = {"measured_usage_windows": {wk: 20.0}}                              # a window-only row (R3)
        cases = [                                                                   # (history, left, windows, admitted)
            ([20.0] * 3, 40.0, {}, True),
            ([5.0, 5.0], 59.0, {}, False),                                          # fewer than 3 never beat the floor
            ([70.0, 80.0, 90.0], 75.0, {}, False),
            ([], 59.0, {}, False),
            ([weekly] * 3, 42.0, {wk: 42.0, fh: 50.0}, False),                      # R1: the 5-hour window inherits the 60% floor
            ([weekly] * 3, 42.0, {wk: 42.0}, True),
            ([only] * 3, 40.0, {wk: 40.0}, True),
            ([only] * 3, 15.0, {wk: 15.0}, False),
        ]
        for rows, left, windows, want in cases:
            tmp = self.calibrated(*rows)
            self.assertEqual(self.fits(left, windows), want, (rows, left, windows))
            self.assertEqual(self.dispatch_fits(tmp, left, windows), want, (rows, left, windows))
            ra._FRONTIER_HISTORY_MEMO.clear()

    def test_r1_a_listed_five_hour_window_below_the_floor_it_inherits_makes_astra_short(self):
        # weekly is measured (3 rows at 2%), the 5-hour window is not: dispatch estimates it at the 60% floor, so 50% left refuses
        weekly = {"measured_usage_pct": 2.0, "measured_usage_windows": {"Codex weekly quota (2)": 2.0}}
        self.calibrated(weekly, weekly, weekly)
        windows = {"Codex weekly quota (2)": 42.0, "Codex 5-hour quota (1)": 50.0}
        self.assertFalse(self.fits(42.0, windows))
        self.assertTrue(self.fits(42.0, {"Codex weekly quota (2)": 42.0}))
        q = self.quota(codex=42.0, claude=80.0, codex_windows=windows)
        self.assertEqual(self.names(q, exclude=frozenset({"codex", "claude"})), "antigravity-argon")   # Argon reachable
        self.assertEqual(self.names(q), "claude")                                                       # codex not scheduled

    def test_r2_history_is_filtered_by_the_configured_effort_like_dispatch(self):
        rows = [{"measured_usage_pct": 70.0, "effort": "high"}] * 3 + [{"measured_usage_pct": 10.0, "effort": "medium"}] * 4
        self.calibrated(*rows)
        self.assertFalse(self.fits(50.0))                         # high rows only: median 70
        self.assertTrue(self.fits(75.0))

    def test_the_planner_and_dispatch_list_the_same_record_files(self):
        """acp-dispatch keeps its own record_paths (reap must not import route_agent); this pins the two to one rule."""
        root = self.calibrated(1.0, 1.0, layout="root")
        (root / "task" / "jobs").mkdir(parents=True)
        (root / "task" / "jobs" / "a.json").write_text("{}")
        (root / "deep" / "x" / "jobs").mkdir(parents=True)
        (root / "deep" / "x" / "jobs" / "b.json").write_text("{}")
        loose = root / "loose.json"
        loose.write_text("{}")
        items = [str(root), str(loose), str(root / "missing")]
        self.assertEqual(ra.record_paths(items), acpd.record_paths(items))
        self.assertEqual(len(ra.record_paths(items)), 4)                            # two ROOT/jobs, ROOT/task/jobs, the loose file

    def test_r3_records_directly_under_the_state_root_are_read_like_dispatch(self):
        self.calibrated(20.0, 20.0, 20.0, layout="root")          # ROOT/jobs/*.json, not ROOT/*/jobs
        self.assertTrue(self.fits(40.0))

    def test_pool_fits_follows_the_repo_and_agrees_with_dispatch(self):
        tmp = self.calibrated()
        for repo, left, want in (("tendcf", 42.0, True), ("tendcf", 15.0, False), ("nix2cf", 42.0, True),
                                 ("plektra", 42.0, False), (None, 42.0, False), (None, 60.0, True)):
            self.assertEqual(self.fits(left, repo=repo), want, (repo, left))
            self.assertEqual(self.dispatch_fits(tmp, left, repo=repo), want, (repo, left))

    def test_a_repo_override_caps_a_larger_median_in_the_planner_too(self):
        tmp = self.calibrated(70.0, 70.0, 70.0)
        self.assertTrue(self.fits(30.0, repo="tendcf"))                             # median 70 capped to the repo's 20
        self.assertFalse(self.fits(30.0, repo="plektra"))
        self.assertEqual(self.dispatch_fits(tmp, 30.0, repo="tendcf"), True)
        self.assertEqual(self.dispatch_fits(tmp, 30.0, repo="plektra"), False)

    def test_the_per_window_cap_admits_a_live_shaped_history_in_tendcf_only(self):
        """Live shape (adversary F1): weekly measured at 2, the 5-hour window at 73. Without the cap tendcf would refuse astra
        at a 50% 5-hour reading, the opposite of the ruling."""
        wk, fh = "Codex weekly quota (2)", "Codex 5-hour quota (1)"
        row = {"measured_usage_pct": 2.0, "measured_usage_windows": {wk: 2.0, fh: 73.0}}
        tmp = self.calibrated(row, row, row)
        windows = {wk: 42.0, fh: 50.0}
        self.assertTrue(self.fits(42.0, windows, repo="tendcf"))
        self.assertFalse(self.fits(42.0, windows, repo="plektra"))
        self.assertTrue(self.dispatch_fits(tmp, 42.0, windows, repo="tendcf"))
        self.assertFalse(self.dispatch_fits(tmp, 42.0, windows, repo="plektra"))

    def test_the_planner_hands_codex_a_frontier_slice_at_42_in_tendcf_only(self):
        q = self.quota(codex=42.0, claude=80.0)
        self.assertEqual(self.names(q, repo="tendcf"), "codex")
        self.assertEqual(self.names(q, repo="plektra"), "claude")
        self.assertEqual(self.names(q), "claude")
        argon = next(x for x in ra.SERVICES if x.name == "antigravity-argon")
        self.assertIsNotNone(ra.fallback_block(argon, "frontier", q, repo="tendcf"))
        self.assertIsNone(ra.fallback_block(argon, "frontier", q, repo="plektra"))

    def test_the_plan_and_route_commands_take_repo_and_default_to_the_cwd(self):
        seen = []
        with mock.patch.object(ra, "load_snapshot", return_value=({}, 0.0)), mock.patch.object(ra, "operator_disabled", return_value=set()), \
                mock.patch.object(ra, "plan", side_effect=lambda *a, **kw: seen.append(kw.get("repo")) or []), \
                mock.patch.object(ra, "route", side_effect=lambda *a, **kw: seen.append(kw.get("repo")) or None):
            ra.main(["plan", "--kinds", "frontier", "--repo", "tendcf"])
            ra.main(["route", "--kind", "frontier", "--repo", "nix2cf"])
            with mock.patch.object(ra, "repo_of", return_value="from-cwd"):
                ra.main(["plan", "--kinds", "frontier"])
        self.assertEqual(seen, ["tendcf", "nix2cf", "from-cwd"])

    def test_a_burn_first_bonus_never_lifts_a_fallback_over_a_usable_pool(self):
        # adversary probe P2: codex usable at 65%, Fable short so Argon is allowed, Argon idle with a day to its reset
        q = self.quota(codex=65.0, claude=80.0, fable=5.0)
        q["antigravity-argon"].update({"pace_ratio": 0.2, "resets_at": iso(24), "window_minutes": 10080})
        q["codex"]["pace_ratio"] = 1.6
        self.assertEqual(self.names(q), "codex")

    def test_a_short_fable_sublimit_makes_claude_short_and_argon_replaces_the_opus_downgrade(self):
        q = self.quota(claude=80.0, fable=5.0)
        self.assertEqual(self.names(q, exclude=frozenset({"codex"})), "antigravity-argon")
        self.assertEqual(self.names(self.quota(claude=80.0, fable=40.0), exclude=frozenset({"codex"})), "claude")
        # with no fallback to hand it to, claude keeps the old Opus downgrade
        no_argon = self.quota(claude=80.0, fable=5.0, argon=0.0)
        c = self.pick(no_argon, frozenset({"codex"}))
        self.assertEqual((c.service.name, c.model), ("claude", "opus --effort high"))

    def test_an_unmeasured_argon_pool_is_never_chosen(self):
        for q in (self.quota(codex=0.0, claude=0.0, argon=None), self.quota(codex=0.0, claude=0.0, argon=0.0)):
            self.assertIsNone(self.pick(q))
        q = self.quota(codex=0.0, claude=0.0)
        q["antigravity-argon"]["remaining"] = None                              # present, but no fresh reading
        self.assertIsNone(self.pick(q))

    def test_the_wave_spills_onto_argon_once_a_pool_is_short_and_stops_at_its_cap(self):
        with mock.patch.object(ra, "discover", return_value=list(ra.SERVICES)), \
                mock.patch.object(ra, "governor_hold", return_value=None):
            rows = ra.plan(["frontier", "frontier"], quota=self.quota(codex=0.0, claude=0.0))
        self.assertEqual([c.service.name if c else None for _, c in rows], ["antigravity-argon", None])   # max_parallel 1


if __name__ == "__main__":
    unittest.main()
