"""claude/hooks/agent_footer_gate.py: append the delivery footer to an Agent-tool prompt that lacks it."""
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "claude" / "hooks" / "agent_footer_gate.py"
REPO_FOOTER = Path(__file__).resolve().parent.parent / "docs" / "dispatch-footer.md"


def run(tool_input, tool="Agent", env=None, session="s1"):
    r = subprocess.run([sys.executable, str(HOOK)],
                       input=json.dumps({"tool_name": tool, "tool_input": tool_input, "session_id": session}),
                       capture_output=True, text=True, timeout=30, env=env)
    return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None


def footer_env(tmp_path, body=None, missing=False):
    """AGENT_FOOTER_* overrides: point the hook at a fixture footer (or a missing path)."""
    env = dict(os.environ, AGENT_FOOTER_REPORT_DIR=str(tmp_path / "reports"))
    path = tmp_path / "dispatch-footer.md"
    if missing:
        env["AGENT_FOOTER_FILE"] = str(tmp_path / "no-such-footer.md")
        return env
    if body is None:
        body = "## Delivery contract (test)\nreport: {report}\ndone: {done}\nlead: {lead}\n"
    path.write_text(body)
    env["AGENT_FOOTER_FILE"] = str(path)
    return env


def test_missing_footer_is_appended_with_a_derived_report_path(tmp_path):
    out = run({"subagent_type": "general-purpose", "description": "Review X!", "prompt": "research X"},
              env=footer_env(tmp_path))
    report = str(tmp_path / "reports" / "s1" / "review-x-report.md")
    assert "permissionDecision" not in out
    prompt = out["updatedInput"]["prompt"]
    assert prompt.startswith("research X\n\n## Delivery contract (test)") and f"report: {report}" in prompt
    assert f"done: {report}.done" in prompt and "lead: main" in prompt
    assert out["updatedInput"]["subagent_type"] == "general-purpose"
    assert report in out["additionalContext"]


def test_report_path_named_in_the_prompt_is_reused(tmp_path):
    out = run({"prompt": "write /abs/dir/toolbox-adversary-report.md please"}, env=footer_env(tmp_path))
    assert "report: /abs/dir/toolbox-adversary-report.md" in out["updatedInput"]["prompt"]


def test_a_finished_or_ambiguous_report_path_is_never_reused(tmp_path):
    done = tmp_path / "slice-report.md"
    done.write_text("STATUS: done\n")
    (tmp_path / "slice-report.md.done").write_text("")
    env = footer_env(tmp_path)
    # The 2026-10-18 case: background names the slice's finished report, the label names the review's own.
    out = run({"description": "Review", "prompt": f"Background: {done}.\nReport path: /abs/review-report.md"}, env=env)
    assert "report: /abs/review-report.md" in out["updatedInput"]["prompt"]
    out = run({"description": "Review", "prompt": f"Background: {done}."}, env=env)
    assert f"report: {tmp_path / 'reports' / 's1' / 'review-report.md'}" in out["updatedInput"]["prompt"]
    out = run({"description": "Two", "prompt": "see /a/x-report.md and /b/y-report.md"}, env=env)
    assert f"report: {tmp_path / 'reports' / 's1' / 'two-report.md'}" in out["updatedInput"]["prompt"]


def test_footer_that_cannot_be_built_still_denies(tmp_path):
    assert run({"prompt": "research X"}, env=footer_env(tmp_path, missing=True))["permissionDecision"] == "deny"
    assert run({"prompt": "research X"},
               env=footer_env(tmp_path, body="no delivery heading here\n"))["permissionDecision"] == "deny"


def test_refused_report_basename_still_denies(tmp_path):
    """Parity with acp-dispatch check_report_name: do not launch an undeliverable Write path."""
    env = footer_env(tmp_path)
    out = run({"prompt": "write /tmp/analysis-report.md please"}, env=env)
    assert out["permissionDecision"] == "deny"
    out = run({"description": "Summary", "prompt": "do the work"}, env=env)
    # derived name is summary-report.md — also refused
    assert out["permissionDecision"] == "deny"


def test_footer_present_or_exempt_or_other_tool_passes():
    assert run({"subagent_type": "Explore", "prompt": "x\n## Delivery contract (shared footer)"}) is None
    assert run({"subagent_type": "claude-code-guide", "prompt": "q"}) is None
    assert run({"command": "ls"}, tool="Bash") is None


def test_off_switch():
    assert run({"prompt": "x"}, env=dict(os.environ, AGENT_FOOTER_GATE_OFF="1")) is None


def test_real_dispatch_footer_template_fills_and_keeps_heading(tmp_path):
    """Regression: the shipped docs/dispatch-footer.md still fills without acp-dispatch."""
    assert REPO_FOOTER.is_file()
    env = dict(os.environ, AGENT_FOOTER_FILE=str(REPO_FOOTER),
               AGENT_FOOTER_REPORT_DIR=str(tmp_path / "reports"), AGENT_FOOTER_LEAD="team-lead")
    out = run({"description": "Real", "prompt": "do the work"}, env=env)
    report = str(tmp_path / "reports" / "s1" / "real-report.md")
    prompt = out["updatedInput"]["prompt"]
    assert "## Delivery contract (shared footer" in prompt
    assert report in prompt and f"{report}.done" in prompt
    assert "team-lead" in prompt
    assert "{report}" not in prompt and "{done}" not in prompt and "{lead}" not in prompt
