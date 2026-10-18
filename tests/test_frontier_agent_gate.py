"""claude/hooks/frontier_agent_gate.py: Agent-tool sub-agents on Fable or astra are logged and asked."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "claude/hooks/frontier_agent_gate.py"


class TestFrontierAgentGate(unittest.TestCase):
    def run_hook(self, tool_input: dict, tool: str = "Agent", **env: str) -> tuple[dict | None, Path]:
        home = Path(tempfile.mkdtemp(prefix="fgate-"))
        base = {k: v for k, v in os.environ.items() if k not in ("ACP_OPERATOR_APPROVED", "FRONTIER_GATE_OFF")}
        proc = subprocess.run(["python3", str(HOOK)], input=json.dumps(
            {"tool_name": tool, "tool_input": tool_input, "session_id": "s1", "cwd": "/x"}),
            capture_output=True, text=True, env={**base, "HOME": str(home), **env}, check=True)
        out = json.loads(proc.stdout) if proc.stdout.strip() else None
        return out, home / ".local/state/frontier-gate/agent-calls.jsonl"

    def test_fable_deep_asks_and_logs(self):
        out, log = self.run_hook({"subagent_type": "fable-deep", "description": "adjudicate"})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")
        row = json.loads(log.read_text())
        self.assertEqual(row["subagent_type"], "fable-deep")

    def test_model_fable_and_ocx_agents_ask(self):
        for tool_input in ({"subagent_type": "general-purpose", "model": "fable"},
                           {"subagent_type": "ocx-self"}, {"subagent_type": "ocx-gpt-6-astra"}):
            out, _ = self.run_hook(tool_input)
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask", tool_input)

    def test_ordinary_agents_pass_silently(self):
        for tool_input in ({"subagent_type": "Explore"}, {"subagent_type": "general-purpose", "model": "opus"}):
            out, log = self.run_hook(tool_input)
            self.assertIsNone(out)
            self.assertFalse(log.exists())
        out, _ = self.run_hook({"command": "ls"}, tool="Bash")
        self.assertIsNone(out)

    def test_approval_logs_without_asking(self):
        out, log = self.run_hook({"subagent_type": "fable-deep"}, ACP_OPERATOR_APPROVED="omp,fable-deep")
        self.assertIsNone(out)
        self.assertTrue(json.loads(log.read_text())["approved_env"])


if __name__ == "__main__":
    unittest.main()
