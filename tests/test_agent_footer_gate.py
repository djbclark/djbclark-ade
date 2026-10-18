"""claude/hooks/agent_footer_gate.py: deny an Agent-tool prompt without the delivery footer."""
import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "claude" / "hooks" / "agent_footer_gate.py"


def decide(tool_input, tool="Agent", env=None):
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"tool_name": tool, "tool_input": tool_input}),
                       capture_output=True, text=True, timeout=10, env=env)
    return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] if r.stdout.strip() else None


def test_missing_footer_is_denied():
    assert decide({"subagent_type": "general-purpose", "prompt": "research X"}) == "deny"


def test_footer_present_or_exempt_or_other_tool_passes():
    assert decide({"subagent_type": "Explore", "prompt": "x\n## Delivery contract (shared footer)"}) is None
    assert decide({"subagent_type": "claude-code-guide", "prompt": "q"}) is None
    assert decide({"command": "ls"}, tool="Bash") is None


def test_off_switch():
    import os
    assert decide({"prompt": "x"}, env=dict(os.environ, AGENT_FOOTER_GATE_OFF="1")) is None
