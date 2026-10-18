"""claude/hooks/agent_footer_gate.py: append the delivery footer to an Agent-tool prompt that lacks it."""
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "claude" / "hooks" / "agent_footer_gate.py"


def run(tool_input, tool="Agent", env=None, session="s1"):
    r = subprocess.run([sys.executable, str(HOOK)],
                       input=json.dumps({"tool_name": tool, "tool_input": tool_input, "session_id": session}),
                       capture_output=True, text=True, timeout=30, env=env)
    return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None


def fake_dispatch(tmp_path, ok=True):
    script = tmp_path / "acp-dispatch"
    body = 'echo "## Delivery contract (test)"; echo "report: $3"' if ok else "exit 2"
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(0o755)
    return dict(os.environ, AGENT_FOOTER_ACP_DISPATCH=str(script), AGENT_FOOTER_REPORT_DIR=str(tmp_path / "reports"))


def test_missing_footer_is_appended_with_a_derived_report_path(tmp_path):
    out = run({"subagent_type": "general-purpose", "description": "Review X!", "prompt": "research X"},
              env=fake_dispatch(tmp_path))
    report = str(tmp_path / "reports" / "s1" / "review-x-report.md")
    assert "permissionDecision" not in out
    prompt = out["updatedInput"]["prompt"]
    assert prompt.startswith("research X\n\n## Delivery contract (test)") and f"report: {report}" in prompt
    assert out["updatedInput"]["subagent_type"] == "general-purpose"
    assert report in out["additionalContext"]


def test_report_path_named_in_the_prompt_is_reused(tmp_path):
    out = run({"prompt": "write /abs/dir/toolbox-adversary-report.md please"}, env=fake_dispatch(tmp_path))
    assert "report: /abs/dir/toolbox-adversary-report.md" in out["updatedInput"]["prompt"]


def test_footer_that_cannot_be_built_still_denies(tmp_path):
    assert run({"prompt": "research X"}, env=fake_dispatch(tmp_path, ok=False))["permissionDecision"] == "deny"


def test_footer_present_or_exempt_or_other_tool_passes():
    assert run({"subagent_type": "Explore", "prompt": "x\n## Delivery contract (shared footer)"}) is None
    assert run({"subagent_type": "claude-code-guide", "prompt": "q"}) is None
    assert run({"command": "ls"}, tool="Bash") is None


def test_off_switch():
    assert run({"prompt": "x"}, env=dict(os.environ, AGENT_FOOTER_GATE_OFF="1")) is None
