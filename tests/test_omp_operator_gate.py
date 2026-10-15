"""omp is operator-gated (operator 2026-10-15): acp-run and acp-dispatch refuse it unless
ACP_OPERATOR_APPROVED names it."""
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACP_RUN = ROOT / "tools" / "acp-run" / "acp-run"
ACP_DISPATCH = ROOT / "bin" / "acp-dispatch"
GATE_MSG = "needs specific, explicit operator approval"


def run(argv: list[Path | str], approved: str | None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "ACP_OPERATOR_APPROVED"}
    if approved is not None:
        env["ACP_OPERATOR_APPROVED"] = approved
    return subprocess.run([str(a) for a in argv], env=env, capture_output=True, text=True,
                          timeout=120, stdin=subprocess.DEVNULL)


class OmpGateTest(unittest.TestCase):
    def test_acp_run_refuses_omp_without_approval(self):
        r = run([ACP_RUN, "omp", "-p", "hi"], None)
        self.assertEqual(r.returncode, 2)
        self.assertIn(GATE_MSG, r.stderr)

    def test_acp_run_approval_for_another_agent_does_not_count(self):
        r = run([ACP_RUN, "omp", "-p", "hi"], "grok")
        self.assertIn(GATE_MSG, r.stderr)

    def test_acp_run_passes_the_gate_with_approval(self):
        # omp has no AGENTS entry yet, so the run stops at the next check instead.
        r = run([ACP_RUN, "omp", "-p", "hi"], "grok, omp")
        self.assertNotIn(GATE_MSG, r.stderr)
        self.assertIn("agent must be one of", r.stderr)

    def test_acp_dispatch_refuses_omp_without_approval(self):
        r = run([ACP_DISPATCH, "omp", "--model", "m", "--name", "bad name!", "-p", "hi"], None)
        self.assertEqual(r.returncode, 2)
        self.assertIn(GATE_MSG, r.stderr)

    def test_acp_dispatch_passes_the_gate_with_approval(self):
        # The invalid --name makes dispatch stop at the check right after the gate.
        r = run([ACP_DISPATCH, "omp", "--model", "m", "--name", "bad name!", "-p", "hi"], "omp")
        self.assertNotIn(GATE_MSG, r.stderr)
        self.assertIn("--name must be", r.stderr)


class HermesGateTest(unittest.TestCase):
    """hermes is never a delegation target (operator 2026-10-15); the same gate covers it."""

    def test_acp_run_refuses_hermes_without_approval(self):
        r = run([ACP_RUN, "hermes", "-p", "hi"], None)
        self.assertEqual(r.returncode, 2)
        self.assertIn(GATE_MSG, r.stderr)

    def test_acp_run_omp_approval_does_not_unlock_hermes(self):
        r = run([ACP_RUN, "hermes", "-p", "hi"], "omp")
        self.assertIn(GATE_MSG, r.stderr)

    def test_acp_dispatch_refuses_hermes_without_approval(self):
        r = run([ACP_DISPATCH, "hermes", "--model", "m", "--name", "bad name!", "-p", "hi"], None)
        self.assertEqual(r.returncode, 2)
        self.assertIn(GATE_MSG, r.stderr)

    def test_acp_dispatch_passes_the_hermes_gate_with_approval(self):
        r = run([ACP_DISPATCH, "hermes", "--model", "m", "--name", "bad name!", "-p", "hi"], "hermes")
        self.assertNotIn(GATE_MSG, r.stderr)
        self.assertIn("--name must be", r.stderr)


if __name__ == "__main__":
    unittest.main()
