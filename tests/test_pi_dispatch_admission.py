"""Pi API admission regressions: synthetic aiuse and acp-run only; no credentials/probes."""
from __future__ import annotations

import ast
import json
from unittest.mock import patch

from test_acp_dispatch import SCRIPT, run
from test_acp_dispatch_load_gate import LoadGate, OK


MODELS = (("code", "openai/gpt-6.1-sol"),
          ("bulk", "openai/gpt-5.4-mini"),
          ("mechanical", "openai/gpt-5.4-mini"))
UNSUPPORTED = (None, "gpt-6.1-sol", "openai-codex/gpt-6.1-sol",
               "anthropic/claude-sonnet-5-5", "other/gpt-5.4-mini",
               "openai/unknown", "openai/gpt-6.1-sol-extra")


def payload(state: str, codex: float = 100) -> dict:
    rows = [{"provider": "codex", "age_seconds": 0, "headroom_percent": codex}]
    if state != "absent":
        row = {"provider": "pi", "age_seconds": 0, "headroom_percent": 80}
        if state == "zero":
            row["headroom_percent"] = 0
        elif state == "below-floor":
            row["headroom_percent"] = 0.5
        elif state == "stale":
            row["age_seconds"] = 1800
        elif state == "expired":
            row["reading_expired"] = True
        elif state == "unknown":
            row["headroom_percent"] = None
        elif state == "unusable":
            row["usable_now"] = False
        rows.append(row)
    return {"age_seconds": 0, "fresh": True, "available": rows}


class TestPiDispatchAdmission(LoadGate):
    def quota_env(self, state: str, codex: float = 100) -> dict[str, str]:
        path = self.tmp / "pi-available.json"
        path.write_text(json.dumps(payload(state, codex)))
        return {"ROUTE_AGENT_AIUSE_JSON": str(path)}

    def test_both_maps_use_only_the_explicit_independent_api_namespace(self):
        mod = self.load_module()
        router = mod.route_module()
        for _, model in MODELS:
            self.assertEqual(mod.map_agent_to_provider("pi", model), ("pi", None))
            self.assertEqual(router.map_agent_to_provider("pi", model), ("pi", None))
            self.assertEqual(mod.resolve_service("pi", model), "pi")
        for model in UNSUPPORTED:
            self.assertIsNone(mod.map_agent_to_provider("pi", model))
            self.assertIsNone(router.map_agent_to_provider("pi", model))
        # No profile/rank/default model drift, including bulk and mechanical.
        for kind, model in MODELS:
            self.assertEqual(router.BY_NAME["pi"].models[kind].split()[0], model)
        for agent, model, expected in (
            ("codex", "gpt-6.1-sol", ("codex", None)),
            ("cursor", "default", ("cursor", "auto")),
            ("agy", "gemini-4-argon", ("antigravity", "gemini_argon")),
            ("opencode", "opencode-go/glm-5", ("opencode-go", None)),
        ):
            self.assertEqual(mod.map_agent_to_provider(agent, model), expected)
            self.assertEqual(router.map_agent_to_provider(agent, model), expected)

    def test_unmeasured_or_empty_api_capacity_refuses_before_preflight_and_task(self):
        for kind, model in MODELS:
            for state in ("absent", "zero", "below-floor", "stale", "expired", "unknown", "unusable"):
                with self.subTest(kind=kind, state=state):
                    name = f"{kind}-{state}"
                    result = self.dispatch_agent(
                        "pi", model, "--kind", kind, "--no-model-check",
                        "--min-headroom", "0", "--est-pct", "0", name=name,
                        env={**self.quota_env(state), "ACP_OPERATOR_APPROVED": "route-override"})
                    self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
                    self.assertEqual(self.record(name)["unavailable_class"], "headroom")
                    self.assertFalse((self.out / f"{name}.jsonl").exists())
                    self.assertEqual(self.preflight_probes(), 0)

    def test_unsupported_namespace_cannot_spend_a_healthy_pi_or_codex_pool(self):
        for index, model in enumerate(UNSUPPORTED[1:]):
            with self.subTest(model=model):
                result = self.dispatch_agent(
                    "pi", model, "--kind", "bulk", "--no-model-check", name=f"bad-{index}",
                    env=self.quota_env("healthy"))
                self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
                self.assertIn("unsupported Pi billing route", result.stdout)
                self.assertEqual(self.preflight_probes(), 0)

    def test_no_preflight_and_dry_run_cannot_bypass_measurement(self):
        for index, flags in enumerate((("--no-preflight",), ("--dry-run",))):
            result = self.dispatch_agent(
                "pi", MODELS[0][1], "--kind", "code", "--no-model-check", *flags,
                name=f"skip-{index}", env=self.quota_env("absent"))
            self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
            self.assertEqual(self.preflight_probes(), 0)

    def test_healthy_api_capacity_runs_even_with_exhausted_codex_subscription(self):
        for kind, model in MODELS:
            with self.subTest(kind=kind):
                result = self.dispatch_agent(
                    "pi", model, "--kind", kind, "--no-model-check", "--est-pct", "1",
                    name=kind, env=self.quota_env("healthy", codex=0))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.record(kind)["service"], "pi")
                self.assertTrue((self.out / f"{kind}.jsonl").exists())
        self.assertGreater(self.preflight_probes(), 0)  # fake preflight, never a paid prompt

    def test_deferred_runner_rechecks_changed_capacity_after_load_wait(self):
        for state in ("absent", "zero", "stale", "expired"):
            with self.subTest(state=state):
                name = f"runner-{state}"
                env = self.quota_env("healthy", codex=0)
                result = self.dispatch_agent(
                    "pi", MODELS[0][1], "--kind", "code", "--no-model-check",
                    "--no-preflight", "--detach", "--no-wait", "--est-pct", "1", name=name,
                    env={**env, **self.gate_env(0, OK)})
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                record = self.out / "jobs" / f"{name}.json"
                # The fake load wait replaces the formerly healthy measurement.
                result = run(["execute", str(record)], env={
                    **self.base_env(), **env, **self.gate_env(
                        0, OK, FAKE_LW_WRITE=env["ROUTE_AGENT_AIUSE_JSON"],
                        FAKE_LW_BODY=json.dumps(payload(state, codex=100)))})
                self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
                self.assertEqual(self.record(name)["status"], "unavailable")
                self.assertIn("after the load wait", self.record(name)["detail"])
                self.assertFalse((self.out / f"{name}.jsonl").exists())
                self.assertEqual(self.preflight_probes(), 0)

    def test_capacity_wait_rechecks_even_without_pending_load_gate(self):
        mod = self.load_module()
        path = self.tmp / "runner.json"
        rec = {"agent": "pi", "model": MODELS[0][1], "kind": "code", "name": "late",
               "status": "running", "min_headroom": 0, "cmd": f"acp-run pi --model {MODELS[0][1]}"}
        path.write_text(json.dumps(rec))
        with patch.object(mod, "pool_reading", return_value=(None, {})) as reading, \
             patch.object(mod, "adopt_load_reservation"), \
             patch.object(mod, "wait_for_capacity") as wait, \
             patch.object(mod, "release_load_reservation"), \
             patch.object(mod.subprocess, "Popen") as spawn:
            self.assertEqual(mod.execute_record(path), 5)
            wait.assert_called_once_with(path)
            reading.assert_called_once_with("pi", MODELS[0][1], fresh=True)
            spawn.assert_not_called()
        self.assertIn("after the capacity wait", json.loads(path.read_text())["detail"])

    def test_resume_and_legacy_records_cannot_skip_pi_measurement(self):
        mod = self.load_module()
        for rec in ({"resume_count": 1, "kind": "bulk"}, {}, {"min_headroom": 0, "kind": "code"}):
            for remaining in (None, 0, 0.5):
                with self.subTest(rec=rec, remaining=remaining), \
                     patch.object(mod, "pool_reading", return_value=(remaining, {})) as reading:
                    refusal = mod.spawn_refusal({"agent": "pi", "model": MODELS[0][1],
                                                 "cmd": f"acp-run pi --model {MODELS[0][1]}", **rec})
                    self.assertEqual(refusal[:2], ("headroom", 5))
                    reading.assert_called_once_with("pi", MODELS[0][1], fresh=True)

    REPLACEMENTS = (["--model", "openai-codex/gpt-6.1-sol"], ["--model=openai-codex/gpt-6.1-sol"],
                    ["--mod", "x"], ["--mod=x"], ["--m", "x"], ["--model x"], ["--set", "model=x"],
                    ["--set=model=x"], ["--meta", "{}"], ["--agent-arg", "--model"], ["--agent-arg=--provider"],
                    ["--agent-env", "OPENAI_API_KEY=x"], ["--agent-env=PI_CODING_AGENT_DIR=/x"],
                    ["--agent-env=PI_ACP_PI_COMMAND=/bin/x"], ["--agent-e", "A=b"], ["--agent", "x"],
                    ["--auth", "oauth"], ["--auth=oauth"], ["--au", "x"])

    def test_identity_guard_boundaries(self):
        mod = self.load_module()
        for args in self.REPLACEMENTS:
            with self.subTest(args=args):
                self.assertIn("pass-through", mod.pi_identity_override(args))
        for args in ([], None, ["--tripwire-exempt-kinds=read,search"], ["--perm", "all"], ["--mode", "x"], ["-m"]):
            with self.subTest(args=args):
                self.assertIsNone(mod.pi_identity_override(args))
        # a stored command line: exactly the primary pair is the dispatcher's own
        self.assertIsNone(mod.pi_identity_override(["x", "--model", "a", "--perm", "all"], True))
        self.assertIsNotNone(mod.pi_identity_override(["--model", "a", "--model", "b"], True))
        self.assertIsNotNone(mod.pi_identity_override(["--model", "a", "--model=b"], True))

    def test_replacement_model_refuses_before_preflight_and_task(self):
        for index, extra in enumerate(self.REPLACEMENTS):
            for model in (MODELS[0][1], MODELS[1][1]):
                with self.subTest(extra=extra, model=model):
                    name = f"repl-{index}-{model[-4:]}"
                    result = self.dispatch_agent(
                        "pi", model, "--kind", "code", "--no-model-check",
                        *[f"--acp-arg={x}" for x in extra], name=name, env=self.quota_env("healthy"))
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("pass-through", result.stderr)
                    self.assertEqual(self.preflight_probes(), 0)
                    self.assertFalse((self.out / f"{name}.jsonl").exists())
        ok = self.dispatch_agent("pi", MODELS[0][1], "--kind", "code", "--no-model-check", "--est-pct", "1",
                                 "--acp-arg=--tripwire-exempt-kinds=read", name="fine",
                                 env=self.quota_env("healthy"))
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)

    def test_other_agents_keep_their_pass_through(self):
        result = self.dispatch_agent("codex", "gpt-6.1-sol", "--no-model-check", "--est-pct", "1",
                                     "--acp-arg=--meta={}", name="codex-meta", env=self.quota_env("healthy"))
        self.assertNotIn("pass-through", result.stderr)

    def test_deferred_and_legacy_runner_refuse_a_replacement_in_the_stored_command(self):
        mod = self.load_module()
        base = {"agent": "pi", "model": MODELS[0][1], "kind": "code", "min_headroom": 0}
        primary = f"acp-run pi --model {MODELS[0][1]} --perm all"
        cases = ((f"{primary} --model=openai-codex/x", {}),
                 (f"{primary} --model other/x", {}),
                 (f"{primary} --mod x", {}),
                 (f"acp-run pi --model other/x", {}),
                 (f"acp-run pi --perm all", {}), ("", {}),
                 (f"{primary} --agent-env OPENAI_API_KEY=x", {}),
                 (primary, {"acp_arg": ["--agent-env=PI_ACP_PI_COMMAND=x"]}),
                 (primary, {"acp_arg": ["--model=other/x"]}),
                 (primary, {"acp_arg": ["--set", "model=x"], "resume_count": 1}))
        for cmd, extra in cases:
            with self.subTest(cmd=cmd, extra=extra), patch.object(mod, "pool_reading", return_value=(90, {})) as reading:
                refusal = mod.spawn_refusal({**base, "cmd": cmd, **extra})
                self.assertEqual(refusal[:2], ("headroom", 5))
                reading.assert_not_called()
        with patch.object(mod, "pool_reading", return_value=(90, {})):
            self.assertIsNone(mod.spawn_refusal({**base, "cmd": primary, "acp_arg": []}))

    def test_runner_never_spawns_a_replacement_model(self):
        mod = self.load_module()
        path = self.tmp / "replaced.json"
        path.write_text(json.dumps({"agent": "pi", "model": MODELS[0][1], "kind": "code", "name": "r",
                                    "status": "running", "min_headroom": 0, "final": str(self.tmp / "f"),
                                    "stderr": str(self.tmp / "e"),
                                    "cmd": f"acp-run pi --model {MODELS[0][1]} --model other/x"}))
        with patch.object(mod, "pool_reading", return_value=(90, {})), patch.object(mod, "adopt_load_reservation"), \
             patch.object(mod, "wait_for_capacity"), patch.object(mod, "release_load_reservation"), \
             patch.object(mod, "runner_load_gate", return_value=None), \
             patch.object(mod.subprocess, "Popen") as spawn:
            self.assertEqual(mod.execute_record(path), 5)
            spawn.assert_not_called()

    def test_resume_record_persists_and_rechecks_its_admitted_minimum(self):
        name = "resumed"
        result = self.dispatch_agent("pi", MODELS[0][1], "--kind", "code", "--no-model-check", "--est-pct", "1",
                                     "--min-headroom", "0", name=name, env=self.quota_env("healthy"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.record(name)["min_headroom"], 0.0)
        record = self.out / "jobs" / f"{name}.json"
        resumed = run(["resume", str(record), "--timeout", "0"], env=self.base_env(**self.quota_env("healthy")))
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        rec = self.record(name)
        self.assertEqual(rec["resume_count"], 1)
        self.assertEqual(rec["min_headroom"], 10.0)
        mod = self.load_module()
        for remaining, refused in ((5.0, True), (9.9, True), (10.0, False), (12.0, False)):
            with self.subTest(remaining=remaining), patch.object(mod, "pool_reading", return_value=(remaining, {})):
                got = mod.spawn_refusal(rec, "the capacity wait")
                self.assertEqual(got is not None, refused)
        # a higher minimum already on the record survives the resume's own 10 %
        rec_high = {**self.record(name), "min_headroom": 25}
        record.write_text(json.dumps(rec_high))
        again = run(["resume", str(record), "--timeout", "0"], env=self.base_env(**self.quota_env("healthy")))
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertEqual(self.record(name)["min_headroom"], 25.0)

    def test_resume_with_stored_replacement_refuses_before_a_new_slice(self):
        name = "resume-repl"
        result = self.dispatch_agent("pi", MODELS[0][1], "--kind", "code", "--no-model-check", "--est-pct", "1",
                                     name=name, env=self.quota_env("healthy"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = self.out / "jobs" / f"{name}.json"
        rec = self.record(name)
        record.write_text(json.dumps({**rec, "acp_arg": ["--model=openai-codex/gpt-6.1-sol"]}))
        resumed = run(["resume", str(record), "--timeout", "0"], env=self.base_env(**self.quota_env("healthy")))
        self.assertEqual(resumed.returncode, 2, resumed.stdout + resumed.stderr)
        self.assertIn("pass-through", resumed.stderr)
        self.assertEqual(self.record(name).get("resume_count", 0), 0)

    def test_non_pi_legacy_admission_is_unchanged(self):
        mod = self.load_module()
        with patch.object(mod, "pool_reading", return_value=(None, {})) as reading:
            self.assertIsNone(mod.spawn_refusal({"agent": "codex", "model": "m1", "resume_count": 1}))
            self.assertIsNone(mod.spawn_refusal({"agent": "zcode", "model": "m1"}))
            reading.assert_not_called()
        self.assertIsNone(mod.pi_capacity_refusal("codex", "gpt-6.1-sol", None))

    def test_static_dispatch_check_precedes_paid_probe(self):
        tree = ast.parse(SCRIPT.read_text())
        dispatch = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "dispatch")
        calls = {name: sorted(n.lineno for n in ast.walk(dispatch) if isinstance(n, ast.Call)
                             and isinstance(n.func, ast.Name) and n.func.id == name)
                 for name in ("pi_capacity_refusal", "preflight", "execute_record")}
        self.assertTrue(calls["pi_capacity_refusal"])
        self.assertLess(calls["pi_capacity_refusal"][0], calls["preflight"][0])
        self.assertLess(calls["pi_capacity_refusal"][0], calls["execute_record"][0])
