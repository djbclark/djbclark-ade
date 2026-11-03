"""Pass-through `--acp-arg` cannot change what an admitted slice bills, for ANY agent (2026-11-03 omp audit, A1/A3).

The frontier, fable-xhigh, plenty and pool gates all judge `--model`; an acp-run option that replaces it (or the
credentials) after admission made every gate advisory. Synthetic aiuse and a fake acp-run only: no credentials,
no probes, no paid prompts."""
from __future__ import annotations

import json
from unittest.mock import patch

from test_acp_dispatch import run
from test_acp_dispatch_load_gate import LoadGate

OMP = "anthropic/claude-sonnet-5-5"

REPLACEMENTS = (["--model", "x/y"], ["--model=x/y"], ["--mod", "x/y"], ["--mod=x/y"], ["--m", "x"], ["--model x/y"],
                ["--set", "model=x/y"], ["--set=model=x/y"], ["--set", "provider=x"], ["--set", "model"], ["--set"],
                ["--se", "effort=high"], ["--meta", "{}"], ["--meta={}"], ["--agent-arg", "--model"],
                ["--agent-arg=--model", "--agent-arg=x"], ["--agent-arg=--provider"], ["--agent-arg=--profile=x"],
                ["--agent-env", "ANTHROPIC_API_KEY=x"], ["--agent-env=ANTHROPIC_BASE_URL=http://x"],
                ["--agent-env=PI_CODING_AGENT_DIR=/x"], ["--agent-e", "A=b"], ["--agent", "x"],
                ["--auth", "oauth"], ["--auth=oauth"], ["--au", "x"])


def payload(**headroom: float) -> dict:
    rows = [{"provider": name, "age_seconds": 0, "headroom_percent": pct} for name, pct in headroom.items()]
    return {"age_seconds": 0, "fresh": True, "available": rows}


class IdentityGuard(LoadGate):
    def quota_env(self, **headroom: float) -> dict[str, str]:
        path = self.tmp / "available.json"
        path.write_text(json.dumps(payload(**headroom)))
        return {"ROUTE_AGENT_AIUSE_JSON": str(path)}

    def test_guard_boundaries_for_every_agent(self):
        mod = self.load_module()
        for agent in ("omp", "codex", "claude", "agy", "opencode", "pi"):
            for args in REPLACEMENTS:
                with self.subTest(agent=agent, args=args):
                    why = mod.identity_override(agent, args)
                    self.assertIn("pass-through", why)
                    self.assertTrue(why.startswith(f"{agent}:"))
            for args in ([], None, ["--tripwire-exempt-kinds=read,search"], ["--perm", "all"], ["--mode", "x"],
                         ["--resume", "abc"], ["--session-id", "abc"], ["--set", "effort=high"],
                         ["--set=reasoning_effort=low"], ["--set", "thought_level=high", "--perm", "all"], ["-m"]):
                with self.subTest(agent=agent, ok=args):
                    self.assertIsNone(mod.identity_override(agent, args))
        # a stored command line: exactly the primary pair is the dispatcher's own
        self.assertIsNone(mod.identity_override("omp", ["x", "--model", "a", "--perm", "all"], True))
        self.assertIsNotNone(mod.identity_override("omp", ["--model", "a", "--model", "b"], True))
        self.assertIsNotNone(mod.identity_override("omp", ["--model", "a", "--model=b"], True))

    def test_replacement_refuses_before_any_gate_probe_or_record_for_every_agent(self):
        for agent, model, kind in (("omp", OMP, "code"), ("codex", "gpt-6.1-sol", "frontier"),
                                   ("claude", "sonnet", "code"), ("agy", "claude-sonnet-5-5", "code")):
            for index, extra in enumerate(REPLACEMENTS):
                with self.subTest(agent=agent, extra=extra):
                    name = f"{agent}-{index}"
                    r = self.dispatch_agent(agent, model, "--kind", kind, "--no-model-check",
                                            *[f"--acp-arg={x}" for x in extra], name=name,
                                            env=self.quota_env(codex=100, claude=100, omp=100, antigravity=100))
                    self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                    self.assertIn("pass-through", r.stderr)
                    self.assertEqual(self.preflight_probes(), 0)
                    self.assertFalse((self.out / "jobs" / f"{name}.json").exists())

    def test_the_audit_bypasses_of_the_frontier_and_model_gates_are_closed(self):
        # claude sonnet at --kind code passes every gate; the replacement was the frontier/fable model
        r = self.dispatch_agent("claude", "sonnet", "--kind", "code", "--no-model-check", "--dry-run",
                                "--acp-arg=--model=fable", "--effort", "xhigh")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("pass-through", r.stderr)
        # codex dry run: the replacement model is refused by acp-run directly, so dispatch must not exit 0 either
        r = self.dispatch_agent("codex", "gpt-6.1-sol", "--kind", "code", "--no-model-check", "--dry-run",
                                "--acp-arg=--model=gpt-6-astra", env=self.quota_env(codex=100))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("pass-through", r.stderr)

    def test_legitimate_pass_through_still_reaches_acp_run(self):
        for agent, model, kind in (("omp", OMP, "code"), ("codex", "gpt-6.1-sol", "frontier")):
            with self.subTest(agent=agent):
                r = self.dispatch_agent(agent, model, "--kind", kind, "--no-model-check", "--dry-run",
                                        "--acp-arg=--tripwire-exempt-kinds=read", "--acp-arg=--set",
                                        "--acp-arg=effort=high", name=f"ok-{agent}",
                                        env=self.quota_env(codex=100, omp=100))
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("--tripwire-exempt-kinds=read --set effort=high", r.stdout)

    def test_a_set_option_no_longer_skips_the_model_check(self):
        r = self.dispatch_agent("codex", "m1", "--kind", "frontier", "--dry-run", "--acp-arg=--set",
                                "--acp-arg=effort=high", env={"FAKE_INFO_FAIL": "1"})
        self.assertIn("could not check --model 'm1'", r.stderr)   # the probe ran (the fake agent is down)

    def spawn(self, **rec):
        mod = self.load_module()
        base = {"agent": "omp", "model": OMP, "kind": "code", "min_headroom": 0,
                "cmd": f"acp-run omp --model {OMP} --perm all"}
        with patch.object(mod, "pool_reading", return_value=(90, {})):
            return mod.spawn_refusal({**base, **rec})

    def test_stored_command_and_acp_arg_refuse_a_replacement_for_every_agent(self):
        for agent in ("omp", "codex", "claude"):
            primary = f"acp-run {agent} --model {OMP} --perm all"
            for rec in ({"cmd": f"{primary} --model=other/x"}, {"cmd": f"{primary} --model other/x"},
                        {"cmd": f"{primary} --mod x"}, {"cmd": f"{primary} --agent-env ANTHROPIC_API_KEY=x"},
                        {"cmd": f"{primary} --agent-arg=--model --agent-arg=x"},
                        {"cmd": f"acp-run {agent} --model other/x"},
                        {"acp_arg": ["--model=other/x"]}, {"acp_arg": ["--set", "model=x"]},
                        {"acp_arg": ["--meta={}"]}, {"acp_arg": ["--agent-env=PI_CODING_AGENT_DIR=/x"]},
                        {"acp_arg": ["--auth", "x"], "resume_count": 1},       # a resumed record
                        {"acp_arg": ["--model=other/x"], "kind": None},        # a legacy kind-less record
                        {"acp_arg": ["--model=other/x"], "min_headroom": None}):
                with self.subTest(agent=agent, rec=rec):
                    refusal = self.spawn(agent=agent, **{"cmd": primary, **rec})
                    self.assertEqual(refusal[:2], ("headroom", 5))
                    self.assertRegex(refusal[2], "pass-through|differs from the admitted model")
            self.assertIsNone(self.spawn(agent=agent, cmd=primary, acp_arg=["--resume", "abc", "--set", "effort=low"]))

    def test_resume_with_a_stored_replacement_refuses_before_a_new_slice(self):
        name = "resume-repl"
        r = self.dispatch_agent("codex", "gpt-6.1-sol", "--no-model-check", "--est-pct", "1", name=name,
                                env=self.quota_env(codex=100))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        record = self.out / "jobs" / f"{name}.json"
        rec = self.record(name)
        record.write_text(json.dumps({**rec, "acp_arg": ["--model=gpt-6-astra"]}))
        resumed = run(["resume", str(record), "--timeout", "0"], env=self.base_env(**self.quota_env(codex=100)))
        self.assertEqual(resumed.returncode, 2, resumed.stdout + resumed.stderr)
        self.assertIn("pass-through", resumed.stderr)
        self.assertEqual(self.record(name).get("resume_count", 0), 0)

    def test_the_runner_never_spawns_a_replacement_model_for_a_billed_agent(self):
        mod = self.load_module()
        path = self.tmp / "replaced.json"
        path.write_text(json.dumps({"agent": "omp", "model": OMP, "kind": "code", "name": "r", "status": "running",
                                    "min_headroom": 0, "final": str(self.tmp / "f"), "stderr": str(self.tmp / "e"),
                                    "cmd": f"acp-run omp --model {OMP} --model github-copilot/gpt-5.6-luna"}))
        with patch.object(mod, "pool_reading", return_value=(90, {})), patch.object(mod, "adopt_load_reservation"), \
             patch.object(mod, "wait_for_capacity"), patch.object(mod, "release_load_reservation"), \
             patch.object(mod, "runner_load_gate", return_value=None), patch.object(mod.subprocess, "Popen") as spawn:
            self.assertEqual(mod.execute_record(path), 5)
            spawn.assert_not_called()


class OmpPoolAdmission(LoadGate):
    """A3: omp had no pool admission: no service on the record, --min-headroom never checked, and a reroute could
    suggest retrying the same pool."""

    def quota_env(self, **headroom: float) -> dict[str, str]:
        path = self.tmp / "available.json"
        path.write_text(json.dumps(payload(**headroom)))
        return {"ROUTE_AGENT_AIUSE_JSON": str(path)}

    def test_both_maps_name_the_omp_credits_pool(self):
        mod = self.load_module()
        router = mod.route_module()
        for model in (OMP, "anthropic/claude-opus-5-5", None):
            self.assertEqual(mod.map_agent_to_provider("omp", model), ("omp", None))
            self.assertEqual(router.map_agent_to_provider("omp", model), ("omp", None))
            self.assertEqual(mod.resolve_service("omp", model), "omp")
            self.assertEqual(router.dispatch_service_name("omp", model), "omp")

    def test_the_record_carries_the_service_and_min_headroom_is_enforced(self):
        r = self.dispatch_agent("omp", OMP, "--kind", "code", "--no-model-check", "--no-preflight", "--est-pct", "1",
                                name="roomy", env=self.quota_env(omp=80))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.record("roomy")["service"], "omp")
        r = self.dispatch_agent("omp", OMP, "--kind", "code", "--no-model-check", "--no-preflight", "--est-pct", "1",
                                "--min-headroom", "50", name="tight", env=self.quota_env(omp=20))
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertEqual(self.record("tight")["unavailable_class"], "headroom")
        self.assertFalse((self.out / "tight.jsonl").exists())

    def test_no_fresh_reading_fails_open_like_any_ordinary_pool(self):
        # omp is neither a reserve (reserve_floor) nor a fallback-only pool, the only pools that fail closed
        r = self.dispatch_agent("omp", OMP, "--kind", "code", "--no-model-check", "--no-preflight", "--est-pct", "1",
                                name="blind", env=self.quota_env(codex=100))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_the_runner_rechecks_the_minimum_for_a_resumed_or_legacy_omp_record(self):
        mod = self.load_module()
        base = {"agent": "omp", "model": OMP, "cmd": f"acp-run omp --model {OMP}", "min_headroom": 10}
        for rec in ({"resume_count": 1, "kind": "code"}, {}):
            for remaining, refused in ((5.0, True), (9.9, True), (10.0, False), (None, False)):
                with self.subTest(rec=rec, remaining=remaining), \
                     patch.object(mod, "pool_reading", return_value=(remaining, {})):
                    got = mod.spawn_refusal({**base, **rec}, "the capacity wait")
                    self.assertEqual(got is not None, refused, got)
                    if got:
                        self.assertEqual(got[:2], ("headroom", 5))
        with patch.object(mod, "pool_reading", return_value=(0.0, {})) as reading:
            self.assertIsNone(mod.spawn_refusal({**base, "resume_count": 1, "min_headroom": 0}))
            reading.assert_not_called()

    def test_a_reroute_excludes_the_omp_pool_that_just_failed(self):
        mod = self.load_module()
        router = mod.route_module()
        quota = {"omp": {"remaining": 100.0}, "claude": {"remaining": 100.0}}
        svc = mod.resolve_service("omp", OMP)
        choice = router.route("code", quota=quota, exclude={svc})
        self.assertTrue(choice is None or choice.service.name != "omp")
