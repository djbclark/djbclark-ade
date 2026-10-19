#!/usr/bin/env python3
"""acp-dispatch load gate: `load-watch admit` runs before a slice launches (operator 2026-10-19).
A fake load-watch stands in (ACP_DISPATCH_LOAD_WATCH); conftest turns the gate off for every other suite."""
from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from typing import override

from test_acp_dispatch_routing import RoutingDispatch

FAKE_LW = textwrap.dedent("""\
    #!/bin/bash
    # fake load-watch: records its arguments, prints FAKE_LW_OUT, exits FAKE_LW_RC
    echo "$@" >> "$FAKE_LW_ARGS"
    [ -n "$FAKE_LW_OUT" ] && echo "$FAKE_LW_OUT"
    exit "${FAKE_LW_RC:-0}"
    """)


class LoadGate(RoutingDispatch):
    lw: Path = Path()
    lw_args: Path = Path()

    @override
    def setUp(self) -> None:
        super().setUp()
        self.lw = self.tmp / "load-watch"
        self.lw.write_text(FAKE_LW)
        self.lw.chmod(0o755)
        self.lw_args = self.tmp / "load-watch.args"

    def gate_env(self, rc: int = 0, out: str = "", **extra: str) -> dict[str, str]:
        # "" overrides conftest's ACP_DISPATCH_NO_LOAD_GATE=1 (only "1" skips the gate)
        return {"ACP_DISPATCH_NO_LOAD_GATE": "", "ACP_DISPATCH_LOAD_WATCH": str(self.lw),
                "FAKE_LW_ARGS": str(self.lw_args), "FAKE_LW_RC": str(rc), "FAKE_LW_OUT": out,
                "ACP_DISPATCH_LOAD_WAIT": "", **extra}

    def calls(self) -> list[str]:
        return self.lw_args.read_text().splitlines() if self.lw_args.exists() else []


HOT = '{"status": "hot", "load1": 31.2, "per_core": 3.9, "cores": 8, "max_per_core": 1.5, "waited_s": 5}'
OK = '{"status": "ok", "load1": 2.4, "per_core": 0.3, "cores": 8, "max_per_core": 1.5, "waited_s": 12}'


class TestLoadGateRefuses(LoadGate):
    def test_hot_exits_75_and_does_not_launch(self):
        r = self.dispatch("--no-model-check", "--load-wait", "5", env=self.gate_env(75, HOT))
        self.assertEqual(r.returncode, 75, r.stderr + r.stdout)
        self.assertIn("load1=31.2", r.stdout)
        self.assertIn("after waiting 5s", r.stdout)
        self.assertEqual(len(r.stdout.strip().splitlines()), 1, r.stdout)
        self.assertEqual(self.calls(), ["admit --wait 5 --json"])
        self.assertFalse((self.out / "s1-report.md").exists())          # acp-run never ran
        self.assertEqual(self.preflight_probes(), 0)                    # the gate sits before the live probe
        rec = self.record()
        self.assertEqual((rec["status"], rec["unavailable_class"], rec["exit"]), ("unavailable", "load", 75))
        self.assertEqual(rec["load_gate"], {"load1": 31.2, "per_core": 3.9, "waited_s": 5})


class TestLoadGateAdmits(LoadGate):
    def test_ok_records_load_gate_and_launches(self):
        r = self.dispatch("--no-model-check", env=self.gate_env(0, OK))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.record()["load_gate"], {"load1": 2.4, "per_core": 0.3, "waited_s": 12})
        self.assertTrue((self.out / "s1-report.md").exists())
        self.assertEqual(self.preflight_probes(), 1)

    def test_default_wait_is_1800(self):
        self.assertEqual(self.dispatch("--no-model-check", env=self.gate_env(0, OK)).returncode, 0)
        self.assertEqual(self.calls(), ["admit --wait 1800 --json"])

    def test_env_overrides_the_default_and_the_flag_overrides_the_env(self):
        env = self.gate_env(0, OK, ACP_DISPATCH_LOAD_WAIT="42")
        self.assertEqual(self.dispatch("--no-model-check", env=env).returncode, 0)
        self.assertEqual(self.dispatch("--no-model-check", "--load-wait", "7", name="s2", env=env).returncode, 0)
        self.assertEqual(self.calls(), ["admit --wait 42 --json", "admit --wait 7 --json"])

    def test_no_load_gate_skips_it(self):
        r = self.dispatch("--no-model-check", "--no-load-gate", env=self.gate_env(75, HOT))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.calls(), [])
        self.assertIsNone(self.record()["load_gate"])

    def test_env_flag_skips_it(self):
        r = self.dispatch("--no-model-check", env=self.gate_env(75, HOT, ACP_DISPATCH_NO_LOAD_GATE="1"))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.calls(), [])

    def test_dry_run_does_not_wait(self):
        r = self.dispatch("--no-model-check", "--dry-run", env=self.gate_env(75, HOT))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.calls(), [])


class TestLoadGateDegrades(LoadGate):
    def test_missing_load_watch_warns_and_continues(self):
        env = self.gate_env(0, OK, ACP_DISPATCH_LOAD_WATCH=str(self.tmp / "no-such-load-watch"))
        r = self.dispatch("--no-model-check", env=env)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("warning", r.stderr)
        self.assertIn("load gate", r.stderr)
        self.assertIsNone(self.record()["load_gate"])

    def test_broken_load_watch_warns_and_continues(self):
        r = self.dispatch("--no-model-check", env=self.gate_env(1, "boom"))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("load-watch admit exited 1", r.stderr)


if __name__ == "__main__":
    unittest.main()
