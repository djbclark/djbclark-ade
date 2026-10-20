"""Operator gates in acp-run and acp-dispatch: hermes and cline are refused unless
ACP_OPERATOR_APPROVED names them; omp left the gate on 2026-10-19 (operator)."""
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


class OmpIsNotGatedTest(unittest.TestCase):
    """omp (the Claude API credits) was gated 2026-10-15 and is an ordinary tier since
    2026-10-19 (operator): neither acp-run nor acp-dispatch asks for ACP_OPERATOR_APPROVED."""

    def test_acp_run_does_not_gate_omp(self):
        # No --model: acp-run's own omp check (default would spend the Copilot reserve) answers.
        r = run([ACP_RUN, "omp", "-p", "hi"], None)
        self.assertEqual(r.returncode, 2)
        self.assertNotIn(GATE_MSG, r.stderr)
        self.assertIn("omp needs --model anthropic/", r.stderr)

    def test_acp_run_omp_refuses_a_non_claude_model(self):
        r = run([ACP_RUN, "omp", "-p", "hi", "--model", "github-copilot/gpt-5.6-luna"], None)
        self.assertEqual(r.returncode, 2)
        self.assertIn("omp needs --model anthropic/", r.stderr)

    def test_acp_run_omp_passes_the_model_check_for_claude(self):
        # The bad --perm stops the run at the check after the omp one.
        r = run([ACP_RUN, "omp", "-p", "hi", "--model", "anthropic/claude-sonnet-5-5",
                 "--perm", "bogus"], None)
        self.assertNotIn(GATE_MSG, r.stderr)
        self.assertNotIn("omp needs --model", r.stderr)
        self.assertIn("--perm must be", r.stderr)

    def test_acp_dispatch_does_not_gate_omp(self):
        # The invalid --name makes dispatch stop at the check right after the gate.
        r = run([ACP_DISPATCH, "omp", "--model", "m", "--name", "bad name!", "-p", "hi"], None)
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


class ClineGateTest(unittest.TestCase):
    """cline was uninstalled (operator 2026-10-17); the machinery stays but is gated the same way."""

    def test_acp_run_refuses_cline_without_approval(self):
        r = run([ACP_RUN, "cline", "-p", "hi"], None)
        self.assertEqual(r.returncode, 2)
        self.assertIn(GATE_MSG, r.stderr)

    def test_acp_run_omp_approval_does_not_unlock_cline(self):
        r = run([ACP_RUN, "cline", "-p", "hi"], "omp,hermes")
        self.assertIn(GATE_MSG, r.stderr)

    def test_acp_run_passes_the_cline_gate_with_approval(self):
        # cline has an AGENTS entry; the bad --perm stops the run at the check after the gate.
        r = run([ACP_RUN, "cline", "-p", "hi", "--perm", "bogus"], "cline")
        self.assertNotIn(GATE_MSG, r.stderr)
        self.assertIn("--perm must be", r.stderr)

    def test_acp_dispatch_refuses_cline_without_approval(self):
        r = run([ACP_DISPATCH, "cline", "--model", "m", "--name", "bad name!", "-p", "hi"], None)
        self.assertEqual(r.returncode, 2)
        self.assertIn(GATE_MSG, r.stderr)

    def test_acp_dispatch_passes_the_cline_gate_with_approval(self):
        r = run([ACP_DISPATCH, "cline", "--model", "m", "--name", "bad name!", "-p", "hi"], "cline")
        self.assertNotIn(GATE_MSG, r.stderr)
        self.assertIn("--name must be", r.stderr)


if __name__ == "__main__":
    unittest.main()
