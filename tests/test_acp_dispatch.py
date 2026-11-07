#!/usr/bin/env python3
"""Tests for the bin/acp-dispatch Paseo shim (slim-down E6, 2026-11-06).

Seeded from the old suite (R2-9): the exit codes and the record (test_acp_dispatch.py), the admit gate and the agent
cap (test_acp_dispatch_load_gate.py), one assertion each from _classify, _outcome and _brief_footer, the frontier
guards (_frontier_reason, _gate), plus what the shim adds: the provider map, the --perm boundaries (review-launch for
Claude, a verified provider mode or a refusal for the rest) and the `paseo wait` status map.

No Paseo daemon, no Claude login: `paseo`, `load-watch` and `review-launch` are the fakes in tests/fakes/ on PATH
(review-launch is E8's; this suite only stubs its interface)."""
from __future__ import annotations

import concurrent.futures
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = Path(os.environ.get("ACP_DISPATCH_SCRIPT", str(ROOT / "bin" / "acp-dispatch")))
FAKES = ROOT / "tests" / "fakes"
FABLE = "claude-fable-5-1[1m]"
REASON = "the cross-file invariant needs frontier-level adjudication"


def load_module():
    loader = importlib.machinery.SourceFileLoader("acp_dispatch_shim", str(SCRIPT))
    spec = importlib.util.spec_from_loader("acp_dispatch_shim", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="acpd-shim-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for name in ("paseo", "load-watch", "review-launch"):
            (self.bin / name).symlink_to(FAKES / name)
        self.out, self.repo, self.state = self.tmp / "out", self.tmp / "repo", self.tmp / "paseo-state"
        self.repo.mkdir()
        self.no_quota = self.tmp / "no-quota.json"
        self.no_quota.write_text(json.dumps({"collected_at": "2099-01-01T00:00:00+00:00", "snapshot": {"accounts": []}}))

    def env(self, **extra: str) -> dict[str, str]:
        e = {k: v for k, v in os.environ.items() if not k.startswith(("LW_", "FAKE_", "ACP_DISPATCH_", "ACP_OPERATOR"))}
        e.update({"PATH": f"{self.bin}{os.pathsep}{e.get('PATH', '')}", "FAKE_PASEO_STATE": str(self.state),
                  "FAKE_LW_LOG": str(self.tmp / "lw.log"), "FAKE_RL_LOG": str(self.tmp / "rl.log"),
                  "ACP_DISPATCH_STATE": str(self.tmp / "state"), "ACP_DISPATCH_LOCK_DIR": str(self.tmp / "lock"),
                  "ACP_DISPATCH_LOAD_WATCH": str(self.bin / "load-watch"),
                  "ACP_DISPATCH_REVIEW_LAUNCH": str(self.bin / "review-launch"),
                  "AIUSE_SNAPSHOT": str(self.no_quota), "ROUTE_AGENT_AIUSE": "off", "ACP_DISPATCH_NO_LOAD_GATE": "1"})
        e.update(extra)
        return e

    def run_cli(self, args: list[str], **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False,
                              env=self.env(**env), timeout=120)

    def dispatch(self, agent: str = "claude", model: str = "sonnet", *extra: str, kind: str | None = None,
                 name: str = "s1", **env: str) -> subprocess.CompletedProcess[str]:
        kind = kind or ("frontier" if "fable" in model or "astra" in model or agent == "codex" else "code")
        return self.run_cli([agent, "--model", model, "--kind", kind, "--name", name, "-p", "do the thing",
                             "-C", str(self.repo), "--out", str(self.out), *extra], **env)

    def record(self, name: str = "s1") -> dict[str, Any]:
        return json.loads((self.out / "jobs" / f"{name}.json").read_text())

    def calls(self) -> list[list[str]]:
        p = self.state / "calls.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def verbs(self) -> list[str]:
        return [c[0] if c[0] != "agent" else c[1] for c in self.calls()]

    def lw(self) -> list[dict]:
        p = self.tmp / "lw.log"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def rl(self) -> list[list[str]]:
        p = self.tmp / "rl.log"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


class TestSurface(Base):
    def test_model_is_mandatory(self):
        r = self.run_cli(["codex", "--kind", "code", "--name", "x", "-p", "hi", "--out", str(self.out)])
        self.assertEqual(r.returncode, 2)
        self.assertIn("--model is required", r.stderr)

    def test_an_unknown_agent_exits_2_with_the_provider_list(self):
        for agent in ("agy", "grok"):                                         # grok CLI retired 2026-11-07
            r = self.dispatch(agent, "m-1")
            self.assertEqual(r.returncode, 2)
            self.assertIn("one of claude, codex, antigravity, cursor, opencode, hermes, omp\n", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_retired_verbs_exit_2_naming_the_replacement(self):
        for verb in ("resume", "reroute", "auto-resume", "extend", "finalize", "reap", "cursor-cloud"):
            with self.subTest(verb=verb):
                r = self.run_cli([verb, str(self.tmp / "x.json")])
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("retired with the Paseo shim", r.stderr)
        self.assertIn("bin/cursor-cloud", self.run_cli(["cursor-cloud", "--model", "x"]).stderr)

    def test_retired_flags_are_usage_errors(self):
        for flag in ("--checkpoint", "--no-preflight", "--no-auto-resume", "--acp-arg=--model=x", "--context=1m"):
            with self.subTest(flag=flag):
                self.assertEqual(self.dispatch("claude", "sonnet", flag).returncode, 2)

    def test_footer_fills_placeholders_and_refuses_bad_paths(self):
        r = self.run_cli(["footer", "--report", "/abs/x-report.md", "--lead", "main"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("/abs/x-report.md.done", r.stdout)
        self.assertIn("SendMessage that same line to `main`", r.stdout)
        self.assertNotIn("{report}", r.stdout)
        self.assertEqual(self.run_cli(["footer", "--report", "rel-report.md"]).returncode, 2)
        self.assertIn("refuses", self.run_cli(["footer", "--report", "/tmp/a/REPORT.md"]).stderr)

    def test_a_footed_brief_is_redispatched_with_one_contract(self):          # from _brief_footer
        brief = self.tmp / "src.md"
        brief.write_text("Do the thing.\n")
        args = ["claude", "--model", "sonnet", "--kind", "code", "-C", str(self.repo), "--out", str(self.out)]
        self.assertEqual(self.run_cli([*args, "--name", "first", "-f", str(brief)]).returncode, 0)
        r = self.run_cli([*args, "--name", "second", "-f", str(self.out / "first-brief.md")])
        self.assertEqual(r.returncode, 0, r.stderr)
        second = (self.out / "second-brief.md").read_text()
        self.assertEqual(second.count("## Delivery contract (shared footer"), 1, second)
        self.assertIn("second-report.md", second)
        self.assertNotIn("first-report.md", second)
        self.assertIn("stripped", r.stderr)


class TestProviderMapAndArgv(Base):
    def dry(self, agent: str, model: str = "m-1", *extra: str, **env: str) -> dict:
        r = self.dispatch(agent, model, "--dry-run", "--json", *extra, **env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_every_agent_maps_to_its_provider_with_its_default_mode(self):
        for agent in ("claude", "codex", "antigravity", "cursor", "opencode", "hermes", "omp"):
            with self.subTest(agent=agent):
                extra = {"ACP_OPERATOR_APPROVED": "hermes,route-override"}
                model = {"opencode": "opencode-go/minimax-m3", "claude": "sonnet"}.get(agent, "m-1")
                rec = self.dry(agent, model, **extra)
                argv = rec["argv"]
                self.assertEqual(argv[1], "run")
                self.assertEqual(argv[argv.index("--provider") + 1], f"{agent}/{model}")
                self.assertEqual(argv[argv.index("--mode") + 1], {"claude": "auto", "codex": "auto"}.get(agent, "default"))
                for flag in ("--no-wait", "--json", "--title", "--cwd"):
                    self.assertIn(flag, argv)
                for label in ("ade.via=acp-dispatch", f"ade.kind={'frontier' if agent == 'codex' else 'code'}",
                              "ade.name=s1", "ade.lead=main"):
                    self.assertIn(label, argv)
                self.assertNotIn("--output-schema", argv)
                self.assertNotIn("--prompt-file", argv)
                self.assertEqual(argv[-2], "--")
                self.assertIn(str(self.out / "s1-brief.md"), argv[-1])
                self.assertIn(str(self.out / "s1-report.md"), argv[-1])
                self.assertIn("## Delivery contract (shared footer", argv[-1])
                self.assertEqual((rec["provider"], rec["boundary"]), (agent, "paseo"))
        self.assertFalse((self.out / "jobs").exists())                          # a dry run writes nothing

    def test_effort_becomes_thinking(self):
        argv = self.dry("claude", "sonnet", "--effort", "high")["argv"]
        self.assertEqual(argv[argv.index("--thinking") + 1], "high")

    def test_a_provider_that_is_not_available_is_refused(self):
        rows = [{"provider": "claude", "status": "unavailable", "enabled": "Enabled", "defaultMode": "auto"}]
        r = self.dispatch(FAKE_PASEO_PROVIDERS=json.dumps(rows))
        self.assertEqual(r.returncode, 2)
        self.assertIn("not Enabled/available", r.stderr)
        self.assertNotIn("run", self.verbs())

    def test_the_identity_guard_pins_exactly_the_admitted_model(self):
        mod = load_module()
        ok = ["paseo", "run", "--provider", "claude/sonnet", "--mode", "auto", "--", "p"]
        self.assertIsNone(mod.identity_refusal("claude", ok, "sonnet"))
        for bad in (ok[:4] + ["--provider", "claude/fable"] + ok[4:], ok[:2] + ["--provider", "claude/fable"] + ok[4:],
                    ok + ["--env", "ANTHROPIC_API_KEY=x"]):
            self.assertIn("agent_guard", mod.identity_refusal("claude", bad, "sonnet"))
        self.assertIsNone(mod.identity_refusal("cursor", ok[:2] + ["--provider", "cursor/other"], "m"))   # unreviewed row
        rl = ["review-launch", "--mode", "review", "-C", "/w", "--model", "sonnet", "--json"]
        self.assertIsNone(mod.identity_refusal("claude", rl, "sonnet"))


class TestPermBoundaries(Base):
    def test_claude_read_only_and_deny_go_through_review_launch(self):
        for perm, mode in (("read-only", "read-only"), ("deny", "review")):
            with self.subTest(perm=perm):
                rec = json.loads(self.dispatch("claude", "sonnet", "--perm", perm, "--dry-run", "--json").stdout)
                self.assertEqual(rec["boundary"], "review-launch")
                argv = rec["argv"]
                self.assertEqual(argv[:3], [str(self.bin / "review-launch"), "--mode", mode])
                for flag, value in (("-C", str(self.repo)), ("--model", "sonnet"),
                                    ("--schema", str(ROOT / "config" / "acp-dispatch-report-schema.json")),
                                    ("-f", str(self.out / "s1-brief.md"))):
                    self.assertEqual(argv[argv.index(flag) + 1], value)
        self.assertEqual(self.calls(), [])                                       # no paseo call at all

    def test_a_review_launch_run_writes_its_structured_report_and_the_done_marker(self):
        r = self.dispatch("claude", "sonnet", "--perm", "read-only")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.rl()), 1)
        self.assertEqual((self.out / "s1-report.md").read_text(), "STATUS: reviewed\nno findings\nDONE\n")
        self.assertTrue((self.out / "s1-report.md.done").exists())
        rec = self.record()
        self.assertEqual((rec["status"], rec["exit"], rec["report_source"], rec["boundary"]),
                         ("done", 0, "review-launch", "review-launch"))
        brief = (self.out / "s1-brief.md").read_text()
        self.assertIn("structured output", brief)
        self.assertEqual(list(self.repo.iterdir()), [])                          # nothing written into the repo

    def test_review_launch_exits_map_to_the_contract(self):
        for mode, code in (("tripwire", 77), ("refused", 2), ("noout", 3), ("timeout", 124), ("blocked", 4),
                           ("garbage", 3)):
            with self.subTest(mode=mode):
                r = self.dispatch("claude", "sonnet", "--perm", "deny", "--force", name=f"rl-{mode}", FAKE_RL_MODE=mode)
                self.assertEqual(r.returncode, code, r.stdout + r.stderr)
                self.assertTrue((self.out / f"rl-{mode}-report.md.done").exists())

    def test_other_providers_run_read_only_and_deny_best_effort_with_a_note(self):
        # operator ruling 2026-11-07: internal agents trust each other; --perm is enforced only for Claude (review-launch)
        for agent, perm in (("codex", "read-only"), ("codex", "deny"), ("opencode", "read-only"), ("cursor", "deny"),
                            ("antigravity", "read-only")):
            with self.subTest(agent=agent, perm=perm):
                model = "opencode-go/minimax-m3" if agent == "opencode" else "m-1"
                name = f"be-{agent}-{perm}"
                r = self.dispatch(agent, model, "--perm", perm, name=name, ACP_OPERATOR_APPROVED="route-override")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                rec = self.record(name)
                self.assertEqual(rec["boundary"], "paseo")
                self.assertEqual(rec["mode"], "auto" if agent == "codex" else "default")
                self.assertIn(f"--perm {perm} is best effort for {agent}", rec["perm_note"])
                self.assertIn("best effort", r.stderr)
                self.assertIn("was asked to be read-only", (self.out / f"{name}-brief.md").read_text())
        self.assertNotIn("stop", self.verbs())
        self.assertIsNone(self.record("be-codex-read-only").get("pending_permissions"))
        self.assertNotIn("mode", self.verbs())                                   # no mode verification any more


class TestLaunchAndWait(Base):
    def test_happy_path_writes_brief_record_and_done_and_exits_0(self):
        r = self.dispatch()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("done\ts1\t"))
        rec = self.record()
        for key in ("paseo_agent_id", "provider", "mode", "boundary", "started", "wait_timeout"):
            self.assertIsNotNone(rec.get(key), key)
        self.assertEqual((rec["status"], rec["exit"], rec["wait_timeout"]), ("done", 0, 2400 + 300))
        self.assertTrue((self.out / "s1-report.md.done").exists())
        self.assertIn("## Delivery contract", (self.out / "s1-brief.md").read_text())
        self.assertIn("## Time budget (acp-dispatch)", (self.out / "s1-brief.md").read_text())
        self.assertEqual(list(self.repo.iterdir()), [])
        self.assertEqual(self.verbs()[-1], "wait")

    def test_report_shapes_map_to_exit_codes(self):
        for mode, code, status in (("blocked", 4, "blocked"), ("partial", 1, "partial"), ("nothing", 3, "no-report")):
            with self.subTest(mode=mode):
                r = self.dispatch(name=f"r-{mode}", FAKE_PASEO_AGENT=mode)
                self.assertEqual(r.returncode, code, r.stdout + r.stderr)
                self.assertEqual(self.record(f"r-{mode}")["status"], status)
        self.assertIn("NO-REPORT: idle without a report", (self.out / "r-nothing-report.md").read_text())

    def test_the_wait_status_field_maps_to_the_contract(self):
        pending = json.dumps([{"id": "p1", "tool": "Bash"}, {"id": "p2", "tool": "Edit"}])
        for status, code, extra in (("timeout", 124, {}), ("permission", 4, {"FAKE_PASEO_PENDING": pending}),
                                    ("error", 3, {})):
            with self.subTest(status=status):
                r = self.dispatch(name=f"w-{status}", FAKE_PASEO_AGENT="running", FAKE_PASEO_WAIT=status, **extra)
                self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        self.assertEqual(self.record("w-permission")["pending_permissions"], ["Bash", "Edit"])
        self.assertIn("Bash, Edit", self.record("w-permission")["detail"])
        self.assertIsNone(self.record("w-timeout")["finished"])                  # still running: not finalized
        self.assertIn("NO-REPORT: error", (self.out / "w-error-report.md").read_text())

    def test_detach_no_wait_returns_the_agent_id_and_wait_finishes_it(self):
        r = self.dispatch("claude", "sonnet", "--detach", "--no-wait")
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = self.record()
        self.assertIn(f"agent: {rec['paseo_agent_id']}", r.stdout)
        self.assertNotIn("wait", self.verbs())
        w = self.run_cli(["wait", str(self.out / "jobs" / "s1.json")])
        self.assertEqual(w.returncode, 0, w.stdout + w.stderr)
        self.assertEqual(self.record()["status"], "done")
        self.assertEqual(self.run_cli(["wait", "--once", str(self.out / "jobs" / "s1.json")]).returncode, 0)
        self.assertEqual(self.dispatch().returncode, 2)                          # a finished name is refused
        self.assertEqual(self.dispatch("claude", "sonnet", "--force").returncode, 0)

    def test_wait_once_is_75_while_running_and_the_verdict_once_done(self):
        self.assertEqual(self.dispatch("claude", "sonnet", "--detach", "--no-wait", name="run",
                                       FAKE_PASEO_AGENT="running").returncode, 0)
        rec = str(self.out / "jobs" / "run.json")
        t0 = time.monotonic()
        self.assertEqual(self.run_cli(["wait", "--once", rec]).returncode, 75)
        self.assertLess(time.monotonic() - t0, 30)                              # non-blocking
        self.assertNotIn("wait", self.verbs())                                  # it never calls a blocking paseo wait
        self.assertEqual(self.dispatch("claude", "sonnet", "--detach", "--no-wait", name="blk",
                                       FAKE_PASEO_AGENT="blocked").returncode, 0)
        self.assertEqual(self.run_cli(["wait", "--once", str(self.out / "jobs" / "blk.json")]).returncode, 4)
        self.assertEqual(self.record("blk")["status"], "blocked")

    def test_a_failed_paseo_run_is_a_refused_launch(self):
        r = self.dispatch(FAKE_PASEO_RUN_FAIL="1")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("Cannot connect to daemon", r.stdout)
        self.assertEqual(self.record()["status"], "refused")

    def test_no_wait_needs_detach(self):
        self.assertEqual(self.dispatch("claude", "sonnet", "--no-wait").returncode, 2)


class TestLoadGateAndCap(Base):
    def gated(self, *extra: str, name: str = "s1", **env: str) -> subprocess.CompletedProcess[str]:
        return self.dispatch("claude", "sonnet", "--load-wait", "0", *extra, name=name,
                             ACP_DISPATCH_NO_LOAD_GATE="0", **env)

    def test_hot_exits_75_and_launches_nothing(self):
        for mode in ("hot", "usage"):
            with self.subTest(mode=mode):
                r = self.gated(name=f"hot-{mode}", FAKE_LW_MODE=mode)
                self.assertEqual(r.returncode, 75, r.stdout + r.stderr)
                self.assertEqual(self.record(f"hot-{mode}")["unavailable_class"], "load")
        self.assertNotIn("run", self.verbs())
        c = self.run_cli(["check", str(self.out / "jobs" / "hot-hot.json")])
        self.assertEqual(c.returncode, 75)
        self.assertIn("machine too hot; retry later", c.stdout)

    def test_the_knobs_reach_admit_and_the_lw_hooks_do_not(self):
        r = self.gated(LW_MIN_FREE_MB="500", LW_MAX_PAGEINS_S="0", LW_FAKE_LOAD1="99", LW_BOOST_CALM_S="5")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        admit = next(x for x in self.lw() if x["argv"][0] == "admit")
        self.assertEqual(admit["argv"], ["admit", "--wait", "0", "--json", "--min-free-mb=500.0", "--max-agents"])
        self.assertEqual(admit["lw_vars"], ["LW_BOOST_CALM_S"])
        self.assertIn("ignoring LW_MAX_PAGEINS_S", r.stderr)

    def test_the_reservation_is_released_once_the_agent_is_countable(self):
        self.assertEqual(self.gated().returncode, 0)
        calls = self.lw()
        self.assertEqual([c["argv"][0] for c in calls], ["admit", "release"])
        ls_after_run = self.verbs().index("run") + 1
        self.assertEqual(self.verbs()[ls_after_run], "ls")                       # countable before the release

    def test_a_burst_of_twenty_launches_still_hits_the_fourteen_agent_cap(self):
        def one(i: int) -> int:
            return self.gated("--detach", "--no-wait", name=f"b{i:02d}", FAKE_PASEO_AGENT="running").returncode

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            codes = list(pool.map(one, range(20)))
        self.assertEqual(sorted(codes), [0] * 14 + [75] * 6, codes)
        self.assertEqual(self.verbs().count("run"), 14)
        refused = [self.record(f"b{i:02d}") for i, c in enumerate(codes) if c == 75]
        self.assertTrue(all("refused=agents" in r["detail"] for r in refused))
        self.assertEqual(sum(c["argv"][0] == "release" for c in self.lw()), 20)  # every admission handed back

    def test_a_burst_under_an_in_flight_cap_of_one_starts_exactly_one(self):
        def one(i: int) -> int:
            return self.gated("--detach", "--no-wait", name=f"i{i}", FAKE_PASEO_AGENT="running",
                              ACP_DISPATCH_INFLIGHT="claude=1").returncode

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            codes = list(pool.map(one, range(6)))
        self.assertEqual(sorted(codes), [0] + [5] * 5, codes)
        self.assertEqual(self.verbs().count("run"), 1)
        refused = [self.record(f"i{i}") for i, c in enumerate(codes) if c == 5]
        self.assertTrue(all(r["status"] == "unavailable" and r["unavailable_class"] == "inflight" for r in refused))

    def test_the_cap_follows_lw_max_agents_and_zero_turns_it_off(self):
        self.assertEqual(self.gated("--detach", "--no-wait", name="c1", FAKE_PASEO_AGENT="running").returncode, 0)
        self.assertEqual(self.gated("--detach", "--no-wait", name="c2", FAKE_PASEO_AGENT="running",
                                    LW_MAX_AGENTS="1").returncode, 75)
        self.assertEqual(self.gated("--detach", "--no-wait", name="c3", FAKE_PASEO_AGENT="running",
                                    LW_MAX_AGENTS="0").returncode, 0)


class TestFrontierGuards(Base):
    def gates_env(self, closed: bool = False, **guard: Any) -> dict[str, str]:
        st = {"level": "ok", "reasons": [], "stale": False, "fable_left": 60.0,
              "checked_at": _ts(datetime.now(UTC) - timedelta(minutes=5)), **guard}
        (self.tmp / "guard.json").write_text(json.dumps(st))
        env = {"GATE_PROFILE_STATE": str(self.tmp / "no-profile.json"), "CLAUDE_QUOTA_GUARD_STATE": str(self.tmp / "guard.json")}
        if closed:
            sys.path.insert(0, str(ROOT / "tests"))
            from test_gates import close_frontier_baseline
            (self.tmp / "closed.toml").write_text(close_frontier_baseline((ROOT / "config/gates.toml").read_text()))
            env["GATES_TOML"] = str(self.tmp / "closed.toml")
        return env

    def test_frontier_model_kind_and_role_gates(self):
        self.assertIn("is a frontier model", self.dispatch("claude", FABLE, kind="judgment").stderr)
        r = self.dispatch("claude", FABLE, "--role", "exec")
        self.assertEqual(r.returncode, 2)
        self.assertIn("frontier-exec", r.stderr)
        r = self.dispatch("claude", FABLE, "--effort", "xhigh")
        self.assertEqual(r.returncode, 2)
        self.assertIn("fable-xhigh", r.stderr)
        self.assertEqual(self.dispatch("hermes", "m-1", ACP_OPERATOR_APPROVED="route-override").returncode, 2)

    def test_the_allowance_is_granted_recorded_and_closed_by_a_closed_baseline(self):
        r = self.dispatch("claude", FABLE, "--frontier-reason", REASON, **self.gates_env())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rec = self.record()
        self.assertEqual((rec["frontier_reason"], rec["frontier_judged"]["family"], rec["role"]), (REASON, 1, "advise"))
        self.assertIn(f"frontier judged use: {REASON}", r.stderr)
        self.assertIn("## Advisor role", (self.out / "s1-brief.md").read_text())
        r = self.dispatch("claude", FABLE, "--frontier-reason", REASON, "--force", **self.gates_env(closed=True))
        self.assertIsNone(self.record()["frontier_judged"])
        self.assertIn("no frontier allowance is in force", self.record()["frontier_judged_note"])
        self.assertEqual(self.dispatch("claude", "sonnet", "--frontier-reason", REASON, name="x").returncode, 2)

    def test_the_per_wave_cap_counts_frontier_slices_in_flight(self):
        mod = load_module()
        mod.route_module()
        busy = []
        for i in range(2):
            p = self.tmp / f"f{i}.json"
            p.write_text(json.dumps({"kind": "frontier"}))
            busy.append(p)
        env = self.gates_env()
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            judged, note = mod.frontier_judged(REASON, "claude", FABLE, 50.0, busy)
            self.assertIsNone(judged)
            self.assertIn("already in flight on claude (cap 2 per wave)", note)
            judged, _ = mod.frontier_judged(REASON, "claude", FABLE, 50.0, busy[:1])
            self.assertEqual(judged["in_flight"], 1)
        finally:
            for k, v in old.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_the_estimate_floor_and_the_in_flight_reservation_refuse_before_launch(self):
        payload = {"age_seconds": 0, "fresh": True, "available": [
            {"provider": "codex", "pool_family": None, "age_seconds": 0, "headroom_percent": 80.0}]}
        (self.tmp / "aiuse.json").write_text(json.dumps(payload))
        quota = {"ROUTE_AGENT_AIUSE_JSON": str(self.tmp / "aiuse.json"), "ROUTE_AGENT_AIUSE": "on"}
        rec = json.loads(self.dispatch("codex", "gpt-6-astra", "--dry-run", "--json", **quota).stdout)
        self.assertGreaterEqual(rec["estimated_usage_pct"], 60.0)                # [dispatch.estimate_floor] codex:frontier
        jobs = self.tmp / "state" / "t" / "jobs"
        jobs.mkdir(parents=True)
        (jobs / "busy.json").write_text(json.dumps({"name": "busy", "agent": "codex", "model": "gpt-6-astra",
                                                    "kind": "frontier", "status": "running", "started": time.time(),
                                                    "estimated_usage_pct": 60.0}))
        r = self.dispatch("codex", "gpt-6-astra", **quota)
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertEqual(self.record()["unavailable_class"], "inflight")
        self.assertIn("busy", self.record()["detail"])
        self.assertNotIn("run", self.verbs())
        r = self.dispatch("codex", "gpt-6-astra", "--min-headroom", "90", "--force", **quota)
        self.assertEqual((r.returncode, self.record()["unavailable_class"]), (5, "headroom"))


class TestCheckOutcomeTell(Base):
    def finished(self) -> Path:
        self.assertEqual(self.dispatch().returncode, 0)
        return self.out / "jobs" / "s1.json"

    def test_a_done_line_followed_by_a_verdict_line_is_done(self):                # from _classify
        mod = load_module()
        report = self.tmp / "v-report.md"
        report.write_text("STATUS: complete\nDONE\nAC_DONE: slice APPROVE\n")
        self.assertEqual(mod.classify(report, finished=True)[0], "done")
        report.write_text("STATUS: complete\nDONE\nmore prose\n")
        self.assertEqual(mod.classify(report, finished=True)[0], "partial")

    def test_check_classifies_records_dirs_and_bare_reports(self):
        rec = self.finished()
        self.assertEqual(self.run_cli(["check", str(rec)]).returncode, 0)
        self.assertEqual(self.run_cli(["check", str(self.out)]).returncode, 0)
        bare = self.tmp / "x-report.md"
        bare.write_text("BLOCKED: which branch?\n")
        self.assertEqual(self.run_cli(["check", str(bare)]).returncode, 4)
        self.assertEqual(self.run_cli(["check"]).returncode, 2)

    def test_outcome_flags_merge_in_calibrates_schema(self):                     # from _outcome
        rec = self.finished()
        self.assertEqual(self.run_cli(["outcome", str(rec), "--ci", "pass"]).returncode, 0)
        self.assertEqual(self.run_cli(["outcome", str(rec), "--not-merged"]).returncode, 0)
        out = self.record()["outcome"]
        self.assertEqual((out["ci"], out["merged"]), ("pass", False))
        self.assertEqual(self.run_cli(["outcome", str(rec)]).returncode, 2)

    def test_tell_writes_the_inbox_and_reads_the_send_status(self):
        self.assertEqual(self.dispatch("claude", "sonnet", "--detach", "--no-wait",
                                       FAKE_PASEO_AGENT="running").returncode, 0)
        rec = self.out / "jobs" / "s1.json"
        r = self.run_cli(["tell", str(rec), "please also check X"])
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("accepted", r.stdout)
        self.assertEqual(self.run_cli(["tell", str(rec), "and Y"], FAKE_PASEO_SEND="sent").returncode, 0)
        inbox = rec.with_suffix(".inbox.md").read_text()
        self.assertIn("## MSG 1 from lead", inbox)
        self.assertIn("## MSG 2 from lead", inbox)
        send = [c for c in self.calls() if c[0] == "send"][-1]
        self.assertTrue(any(x.startswith("--prompt=MSG 2 from lead") for x in send))
        self.assertEqual(send[send.index("--behavior") + 1], "steer")          # a sourceless send would interrupt
        pending = json.dumps([{"id": "p", "tool": "Bash"}])
        r = self.run_cli(["tell", str(rec), "z"], FAKE_PASEO_PENDING=pending)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(sum(c[0] == "send" for c in self.calls()), 2)          # no send into a permission card
        self.assertEqual(self.run_cli(["tell", str(rec), "/clear"]).returncode, 2)

    def test_tell_refuses_a_finished_or_review_launch_slice(self):
        rec = self.finished()
        self.assertEqual(self.run_cli(["tell", str(rec), "late"]).returncode, 2)
        self.assertEqual(self.dispatch("claude", "sonnet", "--perm", "read-only", "--detach", "--no-wait",
                                       name="rl", FAKE_RL_MODE="ok").returncode, 0)
        self.assertEqual(self.run_cli(["tell", str(self.out / "jobs" / "rl.json"), "x"]).returncode, 2)

    def test_a_detached_review_launch_run_is_finished_by_wait(self):
        r = self.dispatch("claude", "sonnet", "--perm", "deny", "--detach", "--no-wait")
        self.assertEqual(r.returncode, 0, r.stderr)
        w = self.run_cli(["wait", str(self.out / "jobs" / "s1.json"), "--timeout", "60"])
        self.assertEqual(w.returncode, 0, w.stdout + w.stderr)
        self.assertEqual(self.record()["status"], "done")


if __name__ == "__main__":
    unittest.main()
