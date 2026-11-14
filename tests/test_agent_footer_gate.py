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


# ---- resume guard (2026-11-14, rs-01): a report without .done is an unfinished earlier sub-agent ----

def stub_report(tmp_path, name="lead-adversary-review-pr-684-report.md", done=False):
    d = tmp_path / "reports" / "s1"
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text("STATUS: wip\n")
    if done:
        (d / (name + ".done")).write_text("")
    return f


def test_relaunch_over_an_unfinished_report_is_denied_with_resume_instructions(tmp_path):
    stub_report(tmp_path)
    out = run({"description": "Lead adversary review PR 684", "prompt": "review it"}, env=footer_env(tmp_path))
    assert out["permissionDecision"] == "deny"
    reason = out["permissionDecisionReason"]
    assert "SendMessage" in reason and "resume from where you stopped" in reason and "Relaunch-reason:" in reason


def test_a_finished_report_allows_the_launch(tmp_path):
    stub_report(tmp_path, done=True)
    out = run({"description": "Lead adversary review PR 684", "prompt": "review it"}, env=footer_env(tmp_path))
    assert "permissionDecision" not in out and "updatedInput" in out


def test_no_earlier_report_allows_the_launch(tmp_path):
    out = run({"description": "Lead adversary review PR 684", "prompt": "review it"}, env=footer_env(tmp_path))
    assert "permissionDecision" not in out and "updatedInput" in out


def test_relaunch_reason_line_allows_and_logs(tmp_path):
    f = stub_report(tmp_path)
    out = run({"description": "Lead adversary review PR 684",
               "prompt": "review it\nRelaunch-reason: the earlier agent reviewed the wrong head"}, env=footer_env(tmp_path))
    assert "permissionDecision" not in out and "updatedInput" in out
    assert "Relaunch honoured" in out["additionalContext"] and str(f) in out["additionalContext"]
    log = (tmp_path / "reports" / "s1" / "relaunch.log").read_text()
    assert "wrong head" in log and str(f) in log


def test_empty_or_inline_relaunch_reason_does_not_count(tmp_path):
    stub_report(tmp_path)
    env = footer_env(tmp_path)
    for prompt in ("review it\nRelaunch-reason:", "review it\nRelaunch-reason:   \n", "note Relaunch-reason: x"):
        out = run({"description": "Lead adversary review PR 684", "prompt": prompt}, env=env)
        assert out["permissionDecision"] == "deny", prompt


def test_prompt_named_report_without_done_is_denied(tmp_path):
    f = tmp_path / "named-adversary-report.md"
    f.write_text("x")
    env = footer_env(tmp_path)
    out = run({"description": "Adv", "prompt": f"Report path: {f}\nreview it"}, env=env)
    assert out["permissionDecision"] == "deny" and str(f) in out["permissionDecisionReason"]
    (tmp_path / "named-adversary-report.md.done").write_text("")
    assert "permissionDecision" not in run({"description": "Adv", "prompt": f"Report path: {f}\nreview it"}, env=env)


def test_prompt_with_its_own_footer_is_guarded_on_the_labelled_path_only(tmp_path):
    f = tmp_path / "own-report.md"
    f.write_text("x")
    env = footer_env(tmp_path)
    body = "task\n## Delivery contract (shared footer)\n"
    out = run({"description": "Own", "prompt": f"Report path: {f}\n{body}"}, env=env)
    assert out["permissionDecision"] == "deny"
    out = run({"description": "Own", "prompt": f"Report path: {f}\nRelaunch-reason: redo\n{body}"}, env=env)
    assert "permissionDecision" not in out and "Relaunch honoured" in out["additionalContext"]
    # a background mention of an unfinished report in a prompt that already has the footer is not a relaunch
    assert run({"description": "Own", "prompt": f"Background: see {f}\n{body}"}, env=env) is None
    # no earlier report at the labelled path
    assert run({"description": "Own", "prompt": f"Report path: {tmp_path / 'fresh-report.md'}\n{body}"}, env=env) is None


def test_exempt_agent_types_skip_the_resume_guard(tmp_path):
    stub_report(tmp_path, name="guide-report.md")
    assert run({"subagent_type": "claude-code-guide", "description": "guide", "prompt": "q"}, env=footer_env(tmp_path)) is None


def test_resume_guard_fails_open_when_the_report_dir_cannot_be_made(tmp_path):
    """The guard's own mkdir raises PermissionError: it must skip, so the outcome is the pre-guard one
    (the footer build hits the same error and denies with the old reason), never a crash or a resume deny."""
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        if os.access(locked, os.W_OK | os.X_OK):
            return                                    # running as root: chmod does not block
        env = dict(footer_env(tmp_path), AGENT_FOOTER_REPORT_DIR=str(locked / "reports"))
        out = run({"description": "Lead adversary review PR 684", "prompt": "review it"}, env=env)
        assert out["permissionDecision"] == "deny" and "no delivery footer" in out["permissionDecisionReason"]
    finally:
        locked.chmod(0o755)


def test_relaunch_with_the_hook_filled_real_footer_is_denied(tmp_path):
    """adv10 F1: the real docs/dispatch-footer.md names its report only in "Write the full deliverable to `X`"."""
    env = dict(os.environ, AGENT_FOOTER_FILE=str(REPO_FOOTER), AGENT_FOOTER_REPORT_DIR=str(tmp_path / "reports"))
    first = run({"description": "Lead adversary review PR 684", "prompt": "review it"}, env=env)
    filled = first["updatedInput"]["prompt"]
    report = tmp_path / "reports" / "s1" / "lead-adversary-review-pr-684-report.md"
    report.write_text("STATUS: working\n")
    for desc in ("Lead adversary review PR 684", "A different description"):
        out = run({"description": desc, "prompt": filled}, env=env)
        assert out["permissionDecision"] == "deny" and str(report) in out["permissionDecisionReason"], desc
    (tmp_path / "reports" / "s1" / (report.name + ".done")).write_text("")
    assert run({"description": "Lead adversary review PR 684", "prompt": filled}, env=env) is None


def test_two_different_report_paths_in_a_footer_prompt_are_ambiguous_and_skipped(tmp_path):
    a, b = tmp_path / "a-report.md", tmp_path / "b-report.md"
    a.write_text("x")
    b.write_text("x")
    prompt = f"Report path: {a}\nReport path: {b}\n## Delivery contract (shared footer)\n"
    assert run({"description": "Two", "prompt": prompt}, env=footer_env(tmp_path)) is None


def test_done_inbox_and_replies_paths_are_not_taken_as_the_report(tmp_path):
    f = tmp_path / "own-adv-report.md"
    f.write_text("x")
    prompt = (f"Report path: {tmp_path / 'fresh-adv-report.md'}\ndone marker: {f}.done\ninbox: {f}.inbox.md\n"
              "## Delivery contract (shared footer)\n")
    assert run({"description": "Own", "prompt": prompt}, env=footer_env(tmp_path)) is None
    prompt = f"mention {f}.done only\n## Delivery contract (shared footer)\nreport: {f}.done"
    assert run({"description": "Own", "prompt": prompt}, env=footer_env(tmp_path)) is None


def test_the_templates_own_placeholder_is_not_a_relaunch_reason(tmp_path):
    stub_report(tmp_path)
    out = run({"description": "Lead adversary review PR 684", "prompt": "x\nRelaunch-reason: <why>"}, env=footer_env(tmp_path))
    assert out["permissionDecision"] == "deny"


def test_a_finished_background_report_does_not_make_the_footer_prompt_ambiguous(tmp_path):
    """adv12 F1: finished background + the unfinished delivery path = one candidate, so the relaunch is denied."""
    env = dict(os.environ, AGENT_FOOTER_FILE=str(REPO_FOOTER), AGENT_FOOTER_REPORT_DIR=str(tmp_path / "reports"))
    first = run({"description": "Review", "prompt": "review it"}, env=env)
    report = tmp_path / "reports" / "s1" / "review-report.md"
    report.write_text("STATUS: working\n")
    bg = tmp_path / "slice-report.md"
    bg.write_text("done")
    (tmp_path / "slice-report.md.done").write_text("")
    out = run({"description": "Review", "prompt": f"Background report: {bg}\n" + first["updatedInput"]["prompt"]}, env=env)
    assert out["permissionDecision"] == "deny"


def test_inbox_and_replies_suffixes_are_not_the_report_and_relative_paths_are_skipped(tmp_path):
    f = tmp_path / "own-report.md"
    f.write_text("x")
    env = footer_env(tmp_path)
    foot = "## Delivery contract (shared footer)\n"
    for suffix in (".inbox.md", ".replies.md"):
        assert run({"description": "Own", "prompt": f"report: {f}{suffix}\n{foot}"}, env=env) is None, suffix
    assert run({"description": "Own", "prompt": f"Report path: ~/own-report.md\n{foot}"}, env=env) is None
    assert run({"description": "Own", "prompt": f"Report path: ./own-report.md\n{foot}"}, env=env) is None
    for mention in ("~/q-report.md", "$HOME/q-report.md", "./q-report.md"):       # one path each: not `/q-report.md`
        out = run({"description": "Own", "prompt": f"write {mention} please"}, env=env)
        assert f"report: {tmp_path / 'reports' / 's1' / 'own-report.md'}\n" in out["updatedInput"]["prompt"], mention
    # no footer: a punctuation-ended mention still counts as the report path (pre-existing behaviour)
    out = run({"prompt": f"write {tmp_path / 'fresh-report.md'}."}, env=env)
    assert f"report: {tmp_path / 'fresh-report.md'}\n" in out["updatedInput"]["prompt"]


def test_labelled_path_that_differs_from_the_delivery_path_is_ambiguous_and_skipped(tmp_path):
    a, b = tmp_path / "a-report.md", tmp_path / "b-report.md"
    a.write_text("x")
    b.write_text("x")
    prompt = f"Report path: {a}\n## Delivery contract (shared footer)\nWrite the full deliverable to `{b}`.\n"
    assert run({"description": "Two", "prompt": prompt}, env=footer_env(tmp_path)) is None


def test_angle_bracket_placeholder_in_any_case_is_not_a_relaunch_reason(tmp_path):
    stub_report(tmp_path)
    for reason in ("<why>", "<WHY>", "< why >"):
        out = run({"description": "Lead adversary review PR 684", "prompt": f"x\nRelaunch-reason: {reason}"},
                  env=footer_env(tmp_path))
        assert out["permissionDecision"] == "deny", reason


def test_finished_delivery_path_with_an_unfinished_background_report_is_not_denied(tmp_path):
    """adv13 L1: only labelled paths are filtered by `.done`; the footer's own delivery path always counts."""
    env = dict(os.environ, AGENT_FOOTER_FILE=str(REPO_FOOTER), AGENT_FOOTER_REPORT_DIR=str(tmp_path / "reports"))
    first = run({"description": "Review", "prompt": "review it"}, env=env)
    report = tmp_path / "reports" / "s1" / "review-report.md"
    report.write_text("done")
    (tmp_path / "reports" / "s1" / "review-report.md.done").write_text("")
    bg = tmp_path / "other-report.md"
    bg.write_text("STATUS: working\n")                           # another agent's unfinished report, named as background
    out = run({"description": "Review", "prompt": f"Background report: {bg}\n" + first["updatedInput"]["prompt"]}, env=env)
    assert out is None
