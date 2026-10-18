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


def test_a_finished_or_ambiguous_report_path_is_never_reused(tmp_path):
    done = tmp_path / "slice-report.md"
    done.write_text("STATUS: done\n")
    (tmp_path / "slice-report.md.done").write_text("")
    env = fake_dispatch(tmp_path)
    # The 2026-10-18 case: background names the slice's finished report, the label names the review's own.
    out = run({"description": "Review", "prompt": f"Background: {done}.\nReport path: /abs/review-report.md"}, env=env)
    assert "report: /abs/review-report.md" in out["updatedInput"]["prompt"]
    out = run({"description": "Review", "prompt": f"Background: {done}."}, env=env)
    assert f"report: {tmp_path / 'reports' / 's1' / 'review-report.md'}" in out["updatedInput"]["prompt"]
    out = run({"description": "Two", "prompt": "see /a/x-report.md and /b/y-report.md"}, env=env)
    assert f"report: {tmp_path / 'reports' / 's1' / 'two-report.md'}" in out["updatedInput"]["prompt"]


def test_footer_that_cannot_be_built_still_denies(tmp_path):
    assert run({"prompt": "research X"}, env=fake_dispatch(tmp_path, ok=False))["permissionDecision"] == "deny"


def test_footer_present_or_exempt_or_other_tool_passes():
    assert run({"subagent_type": "Explore", "prompt": "x\n## Delivery contract (shared footer)"}) is None
    assert run({"subagent_type": "claude-code-guide", "prompt": "q"}) is None
    assert run({"command": "ls"}, tool="Bash") is None


def test_off_switch():
    assert run({"prompt": "x"}, env=dict(os.environ, AGENT_FOOTER_GATE_OFF="1")) is None
