"""claude/hooks/agent_footer_gate.py: append the delivery footer to an Agent-tool prompt that lacks it."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "claude" / "hooks" / "agent_footer_gate.py"
REPO_FOOTER = Path(__file__).resolve().parent.parent / "docs" / "dispatch-footer.md"


def run(tool_input, tool="Agent", env=None, session="s1", cwd=None, timeout=30):
    payload = {"tool_name": tool, "tool_input": tool_input, "session_id": session}
    if cwd is not None:
        payload["cwd"] = str(cwd)
    r = subprocess.run([sys.executable, str(HOOK)],
                       input=json.dumps(payload),
                       capture_output=True, text=True, timeout=timeout, env=env)
    return json.loads(r.stdout)["hookSpecificOutput"] if r.stdout.strip() else None


def footer_env(tmp_path, body=None, missing=False):
    """AGENT_FOOTER_* overrides: point the hook at a fixture footer (or a missing path)."""
    env = dict(os.environ, AGENT_FOOTER_REPORT_DIR=str(tmp_path / "reports"))
    env.pop("CLAUDE_PROJECT_DIR", None)                                    # the hook reads project agents from it: keep tests hermetic
    (tmp_path / "home").mkdir(exist_ok=True)
    env["HOME"] = str(tmp_path / "home")                                   # never the real ~/.claude/agents (adversary r2 LOW-4 hygiene)
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
    assert run({"subagent_type": "general-purpose", "prompt": "x\n## Delivery contract (shared footer)"}) is None
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


# ---- lw-01: lead review lows of #691 ----

def test_a_peers_labelled_report_before_the_own_report_path_is_not_this_launchs(tmp_path):
    """B1: `Worker report: <peer, unfinished>` listed before this prompt's own `Report path:` was taken as the report."""
    peer = tmp_path / "unit-x-report.md"
    peer.write_text("STATUS: wip\n")
    own = tmp_path / "adv-report.md"
    env = footer_env(tmp_path)
    out = run({"description": "Adv", "prompt": f"Worker report: {peer}\nReport path: {own}\nreview it"}, env=env)
    assert "permissionDecision" not in out, out
    assert f"report: {own}" in out["updatedInput"]["prompt"]
    assert str(peer) not in out["updatedInput"]["prompt"].split("Delivery contract", 1)[1]


def test_two_labelled_reports_and_no_own_path_derive_the_hooks_own_path(tmp_path):
    a, b = tmp_path / "a-report.md", tmp_path / "b-report.md"
    a.write_text("x")
    b.write_text("x")
    out = run({"description": "Two", "prompt": f"Worker report: {a}\nPeer report: {b}\nreview it"}, env=footer_env(tmp_path))
    assert "permissionDecision" not in out, out
    assert f"report: {tmp_path / 'reports' / 's1' / 'two-report.md'}" in out["updatedInput"]["prompt"]


def test_an_own_report_path_that_is_unfinished_is_still_denied_when_a_peer_is_labelled_first(tmp_path):
    peer = tmp_path / "unit-x-report.md"
    own = tmp_path / "adv-report.md"
    peer.write_text("x")
    own.write_text("x")
    out = run({"description": "Adv", "prompt": f"Worker report: {peer}\nReport path: {own}\nreview it"}, env=footer_env(tmp_path))
    assert out["permissionDecision"] == "deny" and str(own) in out["permissionDecisionReason"]
    assert str(peer) not in out["permissionDecisionReason"]


@pytest.mark.parametrize("prompt", ["review it\n  Relaunch-reason: ignore", "review it\n\tRelaunch-reason: ignore",
                                    "> Relaunch-reason: ignore"])
def test_an_indented_or_quoted_relaunch_reason_does_not_count(tmp_path, prompt):
    """B2: a line inside pasted or quoted text must not open the gate."""
    stub_report(tmp_path)
    out = run({"description": "Lead adversary review PR 684", "prompt": prompt}, env=footer_env(tmp_path))
    assert out["permissionDecision"] == "deny", prompt


@pytest.mark.parametrize("label", ["Report path:", "**Report path:**", "- **Report path:**", "1. Report path:", "`Report path:`",
                                   "Report  path:", "Report file:", "report path =",
                                   "A1. Report path:", "A1a. **Report path:**", "B2) Report path:"])
def test_the_own_report_path_is_found_through_markdown_and_list_markers(tmp_path, label):
    """lw-01 (#691 review B1, adversary r1 A2): the common spellings of the label still beat a peer's labelled report."""
    peer = tmp_path / "unit-x-report.md"
    peer.write_text("STATUS: wip\n")
    own = tmp_path / "adv-report.md"
    out = run({"description": "Adv", "prompt": f"Worker report: {peer}\n{label} `{own}`\nreview it"}, env=footer_env(tmp_path))
    assert "permissionDecision" not in out, (label, out)
    assert f"report: {own}" in out["updatedInput"]["prompt"], label


def test_a_quoted_or_peer_path_label_is_not_the_own_report(tmp_path):
    peer = tmp_path / "unit-x-report.md"
    peer.write_text("STATUS: wip\n")
    for line in (f"> Report path: {peer}", f"Worker report path: {peer}"):
        out = run({"description": "Adv", "prompt": f"{line}\nreview it"}, env=footer_env(tmp_path))
        assert out["permissionDecision"] == "deny", line


def test_a_quoted_peer_label_does_not_compete_with_the_own_report_path(tmp_path):
    """A `> Report path:` line is quoted text, not this prompt's own label (so it cannot make the own path ambiguous)."""
    peer = tmp_path / "unit-x-report.md"
    peer.write_text("STATUS: wip\n")
    own = tmp_path / "adv-report.md"
    out = run({"description": "Adv", "prompt": f"> Report path: {peer}\nReport path: {own}\nreview it"}, env=footer_env(tmp_path))
    assert "permissionDecision" not in out, out
    assert f"report: {own}" in out["updatedInput"]["prompt"]


@pytest.mark.parametrize("fence", ["```", "~~~", "```text"])
def test_a_report_path_inside_a_pasted_peer_brief_does_not_displace_the_own_one(tmp_path, fence):
    """ec-01 E2c: a peer's brief pasted into this prompt carries its own column-0 `Report path:` line; it must not make the
    prompt's own path ambiguous (the hook then derived a different path) or win over it."""
    peer = tmp_path / "unit-x-report.md"
    peer.write_text("STATUS: wip\n")
    own = tmp_path / "adv-report.md"
    close = fence[:3]
    prompt = f"Report path: {own}\nThe peer's brief, for context:\n{fence}\nReport path: {peer}\nWorker report: {peer}\n{close}\nreview it"
    out = run({"description": "Adv", "prompt": prompt}, env=footer_env(tmp_path))
    assert "permissionDecision" not in out, out
    assert f"report: {own}" in out["updatedInput"]["prompt"]
    assert str(peer) not in out["updatedInput"]["prompt"].split("Delivery contract", 1)[1]


def test_a_pasted_peer_brief_before_a_report_label_that_is_not_report_path_does_not_win(tmp_path):
    """The own path is only `Report: <path>` (a labelled path, not the `Report path:` form): a pasted brief's `Report path:` line must not outrank it."""
    peer = tmp_path / "unit-x-report.md"
    peer.write_text("STATUS: wip\n")
    own = tmp_path / "adv-report.md"
    prompt = f"```\nReport path: {peer}\n```\nReport: {own}\nreview it"
    out = run({"description": "Adv", "prompt": prompt}, env=footer_env(tmp_path))
    assert "permissionDecision" not in out, out
    assert f"report: {own}" in out["updatedInput"]["prompt"]


def test_an_indented_code_block_label_is_not_the_own_report_path(tmp_path):
    peer = tmp_path / "unit-x-report.md"
    peer.write_text("STATUS: wip\n")
    own = tmp_path / "adv-report.md"
    out = run({"description": "Adv", "prompt": f"    Report path: {peer}\nReport path: {own}\nreview it"}, env=footer_env(tmp_path))
    assert "permissionDecision" not in out, out
    assert f"report: {own}" in out["updatedInput"]["prompt"]


def test_a_brief_that_is_wholly_fenced_still_names_its_report(tmp_path):
    """Nothing outside the fence names a report: the path inside it is still taken (the pre-ec-01 behaviour)."""
    own = tmp_path / "adv-report.md"
    own.write_text("x")
    out = run({"description": "Adv", "prompt": f"```\nReport path: {own}\n```\nreview it"}, env=footer_env(tmp_path))
    assert out["permissionDecision"] == "deny" and str(own) in out["permissionDecisionReason"]


def _own_report_of(tmp_path, prompt):
    """The report path the hook puts in the footer of `prompt` (the launch is allowed), or the deny reason."""
    out = run({"description": "Adv", "prompt": prompt}, env=footer_env(tmp_path))
    assert "permissionDecision" not in out, out
    return out["updatedInput"]["prompt"].split("Delivery contract", 1)[1]


def test_a_fenced_own_report_path_beats_a_bare_mention_in_prose(tmp_path):
    """Adversary r1 B1 (P1): the own `Report path:` line inside a fence, a peer's report merely mentioned outside it."""
    peer, own = tmp_path / "unit-x-report.md", tmp_path / "adv-report.md"
    peer.write_text("STATUS: wip\n")
    foot = _own_report_of(tmp_path, f"Review the worker's output at {peer}.\nYour own:\n```\nReport path: {own}\n```\nreview it")
    assert f"report: {own}" in foot and str(peer) not in foot


def test_a_quoted_own_report_path_beats_a_bare_mention_in_prose(tmp_path):
    """Adversary r1 B1 (P2)."""
    peer, own = tmp_path / "unit-x-report.md", tmp_path / "adv-report.md"
    peer.write_text("STATUS: wip\n")
    foot = _own_report_of(tmp_path, f"> Report path: {own}\nThe worker wrote {peer}\nreview it")
    assert f"report: {own}" in foot and str(peer) not in foot


def test_an_inline_triple_backtick_line_does_not_open_a_fence(tmp_path):
    """Adversary r1 B2 (P4): a line of inline code that starts with three backticks is not a fence opener."""
    peer, own = tmp_path / "unit-x-report.md", tmp_path / "adv-report.md"
    peer.write_text("STATUS: wip\n")
    prompt = f"```git``` commands below\nReport path: {own}\n```\npeer brief:\nReport path: {peer}\n```\n"
    # no fence opens at the first line, so the one that opens at the lone ``` closes nothing: both labels stay (ambiguous)
    assert str(peer) not in _own_report_of(tmp_path, prompt)


def test_a_longer_fence_wraps_a_shorter_one_and_the_closer_takes_no_info_string(tmp_path):
    peer, own = tmp_path / "unit-x-report.md", tmp_path / "adv-report.md"
    peer.write_text("STATUS: wip\n")
    wrapped = f"Report path: {own}\n````\n```\nReport path: {peer}\n```\nReport path: {peer}\n````\nreview it"
    assert f"report: {own}" in _own_report_of(tmp_path, wrapped)
    # "```text" is not a closer: the fence never closes, so it is plain text and the two own lines are ambiguous (the hook's own
    # derived path), never the peer's
    unclosed_by_info = f"Report path: {own}\n```\npeer brief\nReport path: {peer}\n```text\nreview it"
    foot = _own_report_of(tmp_path, unclosed_by_info)
    assert str(peer) not in foot and f"report: {tmp_path / 'reports' / 's1' / 'adv-report.md'}" in foot


def test_an_unclosed_fence_is_plain_text(tmp_path):
    """An opener with no closer swallows nothing: the own path after it is still found (and the prompt is scanned once)."""
    own = tmp_path / "adv-report.md"
    assert f"report: {own}" in _own_report_of(tmp_path, f"```\nReport path: {own}\nreview it")


def test_an_unclosed_fence_is_plain_text_even_with_a_peer_label_before_it(tmp_path):
    """The lines after an opener with no closer count as outside text: the own path there beats a peer's labelled report."""
    peer, own = tmp_path / "unit-x-report.md", tmp_path / "adv-report.md"
    peer.write_text("STATUS: wip\n")
    foot = _own_report_of(tmp_path, f"Worker report: {peer}\n```\nReport path: {own}\nreview it")
    assert f"report: {own}" in foot and str(peer) not in foot


def test_a_fenced_own_report_path_against_a_peers_labelled_report_is_a_conflict_never_the_peer(tmp_path):
    """Adversary r2 B1 (Q1) / r3 B1: `Worker report:` outside the fence vs a fenced `Report path:` cannot be told from their mirror
    image (`Your report:` outside, a pasted peer's `Report path:` fenced): the answer is the hook's derived path, never the peer's."""
    peer, own = tmp_path / "unit-x-report.md", tmp_path / "adv-report.md"
    peer.write_text("STATUS: wip\n")
    foot = _own_report_of(tmp_path, f"Worker report: {peer}\n```\nReport path: {own}\n```\nreview it")
    assert str(peer) not in foot and f"report: {tmp_path / 'reports' / 's1' / 'adv-report.md'}" in foot


def test_the_mirror_image_with_a_bare_own_label_outside_is_the_own_path(tmp_path):
    """r3 R6: `Your report: own` outside and a pasted peer's `Report path:` fenced: the own label wins (level 2 outside, fence removed)."""
    peer, own = tmp_path / "unit-x-report.md", tmp_path / "adv-report.md"
    peer.write_text("STATUS: wip\n")
    foot = _own_report_of(tmp_path, f"Report: {own}\n```\nReport path: {peer}\n```\nreview it")
    assert f"report: {own}" in foot and str(peer) not in foot


@pytest.mark.parametrize("prompt", [
    "> Report path: {own}\nWorker report: {peer}\nreview it",                                   # Q2: master gave the derived path
    "Your report path is {own}\n\nFrom the handoff:\n1. report: `{peer}`\nreview it",           # R1
    "Your report: {own}\n> Report path: {peer}\nreview it",                                      # R5
    "Report is {peer} (the worker's).\nYour report path is {own}\n",                             # R8
    "Review the worker's output at {peer}.\n```\nwrite your report to {own}\n```\nreview it",       # M1: unlabelled own, fenced
    "> Write your full report to {own}\nThe worker wrote {peer}\nreview it",                       # M2: unlabelled own, quoted
    "Write your report to {own}\n```\npeer brief: {peer}\n```\nreview it",                       # M3: its mirror image
])
def test_conflicting_report_labels_never_resolve_to_the_peer(tmp_path, prompt):
    """Adversary r3 B1: a prompt that gave the hook's own path on origin/master must not now name a peer's report."""
    peer, own = tmp_path / "unit-x-report.md", tmp_path / "adv-report.md"
    peer.write_text("STATUS: wip\n")
    foot = _own_report_of(tmp_path, prompt.format(own=own, peer=peer))
    assert str(peer) not in foot


def test_a_fence_that_closes_after_an_unclosed_opener_is_still_removed(tmp_path):
    """Adversary r2 B2 (Q7): the lone ``` never closes (plain text); the ~~~ block after it is a pasted peer brief."""
    peer, own = tmp_path / "unit-x-report.md", tmp_path / "adv-report.md"
    peer.write_text("STATUS: wip\n")
    foot = _own_report_of(tmp_path, f"Report path: {own}\n```\nnote\n~~~\nReport path: {peer}\n~~~\nreview it")
    assert f"report: {own}" in foot and str(peer) not in foot


def test_a_long_prompt_of_unclosed_openers_is_fast(tmp_path):
    import time
    own = tmp_path / "adv-report.md"
    prompt = "```a\n" * 60000 + f"Report path: {own}\n"
    t0 = time.monotonic()
    assert f"report: {own}" in _own_report_of(tmp_path, prompt)
    assert time.monotonic() - t0 < 10


def test_a_long_prompt_of_decreasing_length_openers_is_fast(tmp_path):
    """Adversary r3 B2: openers of strictly decreasing length defeat a shortest-failed memo (each scanned to the end)."""
    import time
    own = tmp_path / "adv-report.md"
    prompt = "".join("`" * n + "\n" for n in range(700, 2, -1)) + "x\n" * 200000 + f"Report path: {own}\n"
    t0 = time.monotonic()
    assert f"report: {own}" in _own_report_of(tmp_path, prompt)
    assert time.monotonic() - t0 < 4      # linear: ~0.3 s; a per-opener rescan to the end took ~8 s


def _updated(tmp_path, prompt):
    out = run({"description": "Adv", "prompt": prompt}, env=footer_env(tmp_path))
    assert "permissionDecision" not in out, out
    return out["updatedInput"]["prompt"]


@pytest.mark.parametrize("peer_running", [False, True])
def test_a_peers_footer_pasted_in_a_fence_does_not_suppress_the_hooks_own(tmp_path, peer_running):
    """Lead review 14760b15 B3 (P1, P1b): the pasted footer is the peer's, so the hook appends this launch's own footer on its own
    path (fail closed), and a running peer's report is not a reason to deny: it is not this launch's."""
    peer = tmp_path / "peer-x-report.md"
    if peer_running:
        peer.write_text("STATUS: working\n")
    prompt = f"review the worker's output\n```\nthe peer's brief\n## Delivery contract (shared footer)\nWrite the full deliverable to `{peer}`.\n```\n"
    updated = _updated(tmp_path, prompt)
    own = tmp_path / "reports" / "s1" / "adv-report.md"
    assert updated.count("## Delivery contract") == 2 and f"report: {own}" in updated and f"report: {peer}" not in updated


def test_a_quoted_peer_footer_does_not_suppress_the_hooks_own(tmp_path):
    peer = tmp_path / "peer-x-report.md"
    updated = _updated(tmp_path, f"review it\n> ## Delivery contract (shared footer)\n> Write the full deliverable to `{peer}`.\n")
    assert f"report: {tmp_path / 'reports' / 's1' / 'adv-report.md'}" in updated and f"report: {peer}" not in updated


def test_the_words_delivery_contract_in_prose_do_not_suppress_the_footer(tmp_path):
    updated = _updated(tmp_path, "follow the Delivery contract in docs/dispatch-footer.md when you report")
    assert "## Delivery contract (test)" in updated


def test_a_quoted_peer_label_beside_the_own_bare_label_is_not_a_conflict(tmp_path):
    """Lead review B5 (M7): quoted lines are removed before the own-label levels, so `> Worker report:` does not turn the one
    outside `Report:` into a conflict (the derived path would be safe but wrong)."""
    peer, own = tmp_path / "unit-x-report.md", tmp_path / "adv-report.md"
    peer.write_text("STATUS: wip\n")
    foot = _own_report_of(tmp_path, f"Report: {own}\n> Worker report: {peer}\nreview it")
    assert f"report: {own}" in foot and str(peer) not in foot


def test_a_peers_pasted_report_label_does_not_hide_the_own_unfinished_report_behind_an_own_footer(tmp_path):
    """The footer branch of the resume guard reads the text outside pasted blocks: a running peer's `Report path:` in a fence
    must not turn this launch's own unfinished report into an ambiguous (two-path) case that is let through."""
    own, peer = tmp_path / "own-report.md", tmp_path / "peer-report.md"
    own.write_text("STATUS: wip\n")
    peer.write_text("STATUS: wip\n")
    prompt = f"Report path: {own}\n```\nthe peer's brief\nReport path: {peer}\n```\ntask\n## Delivery contract (shared footer)\n"
    out = run({"description": "Own", "prompt": prompt}, env=footer_env(tmp_path))
    assert out["permissionDecision"] == "deny" and str(own) in out["permissionDecisionReason"]


@pytest.mark.parametrize("indent", ["    ", "\t", "        "])
def test_a_peers_footer_pasted_indented_does_not_become_the_launchs_report_path(tmp_path, indent):
    """Adversary r6 A1: a footer pasted as an indented block (4+ spaces or a tab, or a fence nested in a list item) is not
    seen by the heading check, so the hook appends its own footer; its delivery line must not name the report either."""
    peer = tmp_path / "peer-x-report.md"
    block = "".join(f"{indent}{ln}\n" for ln in ("## Delivery contract (shared footer)", f"Write the full deliverable to `{peer}`."))
    updated = _updated(tmp_path, f"review the worker's brief below\n\n{block}")
    assert f"report: {tmp_path / 'reports' / 's1' / 'adv-report.md'}" in updated and f"report: {peer}" not in updated


def test_a_fence_nested_in_a_list_item_with_a_peer_footer_is_not_the_launchs_report_path(tmp_path):
    peer = tmp_path / "peer-x-report.md"
    prompt = f"steps:\n\n1. paste:\n\n    ```\n    ## Delivery contract (shared footer)\n    Write the full deliverable to `{peer}`.\n    ```\n"
    updated = _updated(tmp_path, prompt)
    assert f"report: {tmp_path / 'reports' / 's1' / 'adv-report.md'}" in updated and f"report: {peer}" not in updated


# ---- read-only sub-agent types (2026-11-21): no Write, no Bash -> the final message is the report ----

RO_REPO_FOOTER = Path(__file__).resolve().parent.parent / "docs" / "dispatch-footer-readonly.md"


def ro_env(tmp_path, agents=None, body=None, missing=False):
    """footer_env plus an isolated agent-definition dir (never the real ~/.claude/agents) and a fixture or missing read-only footer."""
    env = footer_env(tmp_path)
    adir = tmp_path / "agents"
    adir.mkdir(exist_ok=True)
    for name, text in (agents or {}).items():
        (adir / f"{name}.md").write_text(text)
    env["AGENT_FOOTER_AGENT_DIRS"] = str(adir)
    if missing:
        env["AGENT_FOOTER_READONLY_FILE"] = str(tmp_path / "no-such-readonly-footer.md")
    elif body is not None:
        f = tmp_path / "ro-footer.md"
        f.write_text(body)
        env["AGENT_FOOTER_READONLY_FILE"] = str(f)
    return env


def agent_def(tools=None, extra=""):
    tools_line = f"tools: {tools}\n" if tools is not None else ""
    return f"---\nname: x\ndescription: d\nmodel: sonnet\n{tools_line}{extra}---\nbody\n"


def assert_read_only_footer(tmp_path, out):
    assert "permissionDecision" not in out, out
    prompt = out["updatedInput"]["prompt"]
    assert "## Delivery contract (read-only" in prompt
    assert "Delivery contract (test)" not in prompt                       # not the standard (write-a-file) footer
    assert ".done" not in prompt.split("## Delivery contract (read-only", 1)[1].replace("`.done` marker", "")
    assert "final message is the deliverable" in prompt
    ctx = out["additionalContext"]
    assert "READ-ONLY" in ctx and "Save that final message" in ctx and "do not wait" in ctx
    assert not (tmp_path / "reports").exists()                            # no report dir was made: there is no report file
    return prompt


@pytest.mark.parametrize("kind", ["Explore", "Plan", "web-fetch"])
def test_builtin_read_only_types_get_the_final_message_footer(tmp_path, kind):
    out = run({"subagent_type": kind, "description": "Scout X", "prompt": "find X"}, env=ro_env(tmp_path))
    prompt = assert_read_only_footer(tmp_path, out)
    assert prompt.startswith("find X\n\n## Delivery contract (read-only")
    assert "`main`" in prompt and "{lead}" not in prompt                    # SendMessage chunks go to the filled lead
    assert kind in out["additionalContext"]
    assert out["updatedInput"]["subagent_type"] == kind


def test_the_lead_placeholder_follows_agent_footer_lead(tmp_path):
    env = dict(ro_env(tmp_path), AGENT_FOOTER_LEAD="team-lead")
    prompt = assert_read_only_footer(tmp_path, run({"subagent_type": "Explore", "prompt": "find X"}, env=env))
    assert "`team-lead`" in prompt


def test_the_shipped_read_only_footer_fills_and_keeps_its_heading(tmp_path):
    assert RO_REPO_FOOTER.is_file()
    env = dict(ro_env(tmp_path), AGENT_FOOTER_LEAD="team-lead")
    env.pop("AGENT_FOOTER_READONLY_FILE", None)                            # the real docs/dispatch-footer-readonly.md
    out = run({"subagent_type": "Plan", "prompt": "plan X"}, env=env)
    prompt = out["updatedInput"]["prompt"]
    assert "## Delivery contract (read-only" in prompt and "`team-lead`" in prompt
    assert "{lead}" not in prompt and "{report}" not in prompt and "{done}" not in prompt
    assert "Write no report file" in prompt and "last line of your final message is `DONE`" in prompt


@pytest.mark.parametrize("tools", ["Read, Grep, Glob", "Read, WebFetch, WebSearch", "[Read, Grep]", '"Read, Grep"'])
def test_a_definition_without_write_or_bash_is_read_only(tmp_path, tools):
    env = ro_env(tmp_path, {"scout": agent_def(tools)})
    out = run({"subagent_type": "x", "prompt": "find X"}, env=env)               # name: x in the frontmatter
    assert_read_only_footer(tmp_path, out)


def test_a_definition_is_found_by_file_name_and_by_name_field(tmp_path):
    env = ro_env(tmp_path, {"scout": "---\ndescription: d\ntools: Read, Grep\n---\n"})    # no name: the file stem
    assert_read_only_footer(tmp_path, run({"subagent_type": "scout", "prompt": "q"}, env=env))


def test_a_yaml_list_of_tools_is_read(tmp_path):
    read_only = "---\nname: scout\ntools:\n  - Read\n  - Grep\n---\n"
    writer = "---\nname: scribe\ntools:\n  - Read\n  - Write\n---\n"
    env = ro_env(tmp_path, {"scout": read_only, "scribe": writer})
    assert_read_only_footer(tmp_path, run({"subagent_type": "scout", "prompt": "q"}, env=env))
    out = run({"subagent_type": "scribe", "prompt": "q"}, env=env)
    assert "## Delivery contract (test)" in out["updatedInput"]["prompt"]


@pytest.mark.parametrize("tools", ["Read, Grep, Glob, Bash", "Read, Write", "Bash(git:*), Read", "*", "Read, Edit"])   # Edit can create a file (r2 LOW-2)
def test_a_definition_that_can_write_keeps_the_standard_footer(tmp_path, tools):
    """adversary (Read, Grep, Glob, Bash) is the real example: it writes its report with Bash."""
    env = ro_env(tmp_path, {"scribe": "---\nname: scribe\ntools: " + tools + "\n---\n"})
    out = run({"subagent_type": "scribe", "description": "Review", "prompt": "q"}, env=env)
    prompt = out["updatedInput"]["prompt"]
    assert "## Delivery contract (test)" in prompt and "read-only" not in prompt
    assert str(tmp_path / "reports" / "s1" / "review-report.md") in out["additionalContext"]
    assert ".done" in out["additionalContext"] and "READ-ONLY" not in out["additionalContext"]


def test_a_definition_with_no_tools_line_has_all_tools(tmp_path):
    env = ro_env(tmp_path, {"anyone": "---\nname: anyone\n---\n"})
    out = run({"subagent_type": "anyone", "prompt": "q"}, env=env)
    assert "## Delivery contract (test)" in out["updatedInput"]["prompt"]


def test_disallowed_tools_can_make_a_type_read_only(tmp_path):
    both = agent_def(None, "disallowedTools: Write, Edit, Bash\n")
    one = agent_def(None, "disallowedTools: Write\n")                   # Bash is still there
    env = ro_env(tmp_path, {"both": both.replace("name: x", "name: both"), "one": one.replace("name: x", "name: one")})
    assert_read_only_footer(tmp_path, run({"subagent_type": "both", "prompt": "q"}, env=env))
    narrowed = ro_env(tmp_path, {"n": "---\nname: n\ntools: Read, Bash\ndisallowedTools: Bash\n---\n"})
    assert_read_only_footer(tmp_path, run({"subagent_type": "n", "prompt": "q"}, env=narrowed))
    out = run({"subagent_type": "one", "prompt": "q"}, env=env)               # last: a writing type makes the report dir
    assert "## Delivery contract (test)" in out["updatedInput"]["prompt"]


def test_a_project_definition_is_found_through_the_hooks_cwd(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
    (proj / ".claude" / "agents" / "local-scout.md").write_text("---\nname: local-scout\ntools: Read, Grep\n---\n")
    env = footer_env(tmp_path)                                            # no AGENT_FOOTER_AGENT_DIRS: project dir, then ~/.claude/agents
    out = run({"subagent_type": "local-scout", "prompt": "q"}, env=env, cwd=proj)
    assert "## Delivery contract (read-only" in out["updatedInput"]["prompt"]
    out = run({"subagent_type": "local-scout", "prompt": "q"}, env=env, cwd=tmp_path)          # not found from another cwd
    assert "## Delivery contract (test)" in out["updatedInput"]["prompt"]


def test_a_user_definition_of_a_builtin_name_with_write_overrides_the_builtin_list(tmp_path):
    env = ro_env(tmp_path, {"Explore": "---\nname: Explore\ntools: Read, Write\n---\n"})
    out = run({"subagent_type": "Explore", "prompt": "q"}, env=env)
    assert "## Delivery contract (test)" in out["updatedInput"]["prompt"]


@pytest.mark.parametrize("kind", ["general-purpose", "backend", "fable-deep", "", "some-plugin:agent"])
def test_types_that_can_write_or_are_unknown_keep_the_standard_footer(tmp_path, kind):
    tool_input = {"description": "Review X!", "prompt": "do X"}
    if kind:
        tool_input["subagent_type"] = kind
    out = run(tool_input, env=ro_env(tmp_path))
    assert "## Delivery contract (test)" in out["updatedInput"]["prompt"]
    assert str(tmp_path / "reports" / "s1" / "review-x-report.md") in out["additionalContext"]


def test_a_standard_footer_pasted_into_a_read_only_prompt_is_overridden(tmp_path):
    prompt = "find X\n\n## Delivery contract (shared footer)\n1. Write the full deliverable to `/abs/x-report.md`.\n"
    out = run({"subagent_type": "Explore", "prompt": prompt}, env=ro_env(tmp_path))
    new = out["updatedInput"]["prompt"]
    assert new.startswith(prompt.rstrip()) and "## Delivery contract (read-only" in new
    assert "replaces any instruction elsewhere" in new                     # the shipped text supersedes the pasted one


def test_a_read_only_prompt_with_its_own_read_only_footer_passes_untouched(tmp_path):
    prompt = "find X\n\n## Delivery contract (read-only sub-agent: no file tools)\n1. final message\n"
    assert run({"subagent_type": "Explore", "prompt": prompt}, env=ro_env(tmp_path)) is None
    # a peer's read-only footer pasted in a fence is not this prompt's own
    fenced = "find X\n```\n## Delivery contract (read-only sub-agent)\n```\n"
    out = run({"subagent_type": "Explore", "prompt": fenced}, env=ro_env(tmp_path))
    assert out["updatedInput"]["prompt"].count("## Delivery contract (read-only") == 2


def test_the_resume_guard_does_not_apply_to_a_read_only_type(tmp_path):
    """No report file exists for it: an unfinished report of the same description must not deny, and none is created."""
    stub_report(tmp_path, name="scout-x-report.md")
    out = run({"subagent_type": "Explore", "description": "Scout X", "prompt": "find X"}, env=ro_env(tmp_path))
    assert "permissionDecision" not in out and "READ-ONLY" in out["additionalContext"]
    out = run({"subagent_type": "general-purpose", "description": "Scout X", "prompt": "find X"}, env=ro_env(tmp_path))
    assert out["permissionDecision"] == "deny"                            # a writing type keeps the guard


def test_a_read_only_type_with_a_refused_report_basename_is_not_denied(tmp_path):
    """The Write-basename rule (analysis/summary) is about a file; a read-only type writes none."""
    out = run({"subagent_type": "Plan", "description": "Summary", "prompt": "plan it"}, env=ro_env(tmp_path))
    assert "permissionDecision" not in out and "READ-ONLY" in out["additionalContext"]


def test_a_read_only_footer_that_cannot_be_built_denies(tmp_path):
    out = run({"subagent_type": "Explore", "prompt": "q"}, env=ro_env(tmp_path, missing=True))
    assert out["permissionDecision"] == "deny" and "read-only delivery footer" in out["permissionDecisionReason"]
    out = run({"subagent_type": "Explore", "prompt": "q"}, env=ro_env(tmp_path, body="no heading here\n"))
    assert out["permissionDecision"] == "deny"


def test_exempt_types_stay_exempt_and_the_off_switch_covers_read_only(tmp_path):
    env = ro_env(tmp_path)
    assert run({"subagent_type": "claude-code-guide", "prompt": "q"}, env=env) is None
    assert run({"subagent_type": "statusline-setup", "prompt": "q"}, env=env) is None
    assert run({"subagent_type": "Explore", "prompt": "q"}, env=dict(env, AGENT_FOOTER_GATE_OFF="1")) is None


def test_an_unreadable_definition_fails_open_to_the_standard_footer(tmp_path):
    env = ro_env(tmp_path, {"bad": "---\nname: bad\ntools: Read\n---\n"})
    bad = Path(env["AGENT_FOOTER_AGENT_DIRS"]) / "bad.md"
    bad.chmod(0)
    try:
        if os.access(bad, os.R_OK):
            return                                                        # running as root
        out = run({"subagent_type": "bad", "prompt": "q"}, env=env)
        assert "## Delivery contract (test)" in out["updatedInput"]["prompt"]
    finally:
        bad.chmod(0o644)


# ---- round-1 repair of PR 900 (adversary BLOCK): Claude Code's normalized subagent_type match, LOW 1-5 ----

# what Claude Code 2.1.330 accepts after an exact match fails: NFKC, lower-case, then drop White_Space, Pd (dashes) and `_`
@pytest.mark.parametrize("spelling", ["explore", "EXPLORE", "eXpLoRe", "Explore ", "Ｅxplore", " explore"])
def test_other_spellings_of_explore_get_the_read_only_footer(tmp_path, spelling):
    out = run({"subagent_type": spelling, "prompt": "find X"}, env=ro_env(tmp_path))
    assert_read_only_footer(tmp_path, out)
    assert "`Explore`" in out["additionalContext"]                          # reported under the type Claude Code will run
    assert out["updatedInput"]["subagent_type"] == spelling                 # the call itself is not rewritten


@pytest.mark.parametrize("spelling", ["plan", "PLAN", "Plan ", "p_l_a_n"])
def test_other_spellings_of_plan_get_the_read_only_footer(tmp_path, spelling):
    assert_read_only_footer(tmp_path, run({"subagent_type": spelling, "prompt": "plan X"}, env=ro_env(tmp_path)))


@pytest.mark.parametrize("spelling", ["web_fetch", "webfetch", "Web Fetch", "WEB-FETCH", "web‑fetch", "web–fetch", "Web_Fetch", "web  fetch"])
def test_other_spellings_of_web_fetch_get_the_read_only_footer(tmp_path, spelling):
    assert_read_only_footer(tmp_path, run({"subagent_type": spelling, "prompt": "fetch X"}, env=ro_env(tmp_path)))


@pytest.mark.parametrize("spelling", ["my_scout", "My Scout", "MYSCOUT", "my-scout", "my—scout"])
def test_a_definition_is_reached_by_a_normalized_name(tmp_path, spelling):
    env = ro_env(tmp_path, {"my-scout": "---\nname: my-scout\ntools: Read, Grep\n---\n"})
    assert_read_only_footer(tmp_path, run({"subagent_type": spelling, "prompt": "q"}, env=env))


@pytest.mark.parametrize("spelling", ["general_purpose", "General Purpose", "generalpurpose", "claude_code_guide", "back_end", "Fable Deep", "explorer", "explore-x", "plan-b", "exploreplan", "web", "fetch"])
def test_the_looser_match_never_catches_a_type_that_can_write_or_a_different_name(tmp_path, spelling):
    """Only equality of the normalized names counts: neither a writable type nor a name that merely contains `explore`/`plan`."""
    env = ro_env(tmp_path, {"backend": "---\nname: backend\n---\n", "fable-deep": "---\nname: fable-deep\ntools: Read, Write\n---\n"})
    prompt = run({"subagent_type": spelling, "description": "Review X!", "prompt": "do X"}, env=env)
    if prompt is None:                                                        # claude-code-guide, even misspelled, is exempt
        assert spelling == "claude_code_guide"
        return
    assert "read-only" not in prompt["updatedInput"]["prompt"] and "READ-ONLY" not in prompt["additionalContext"]
    assert "## Delivery contract (test)" in prompt["updatedInput"]["prompt"]


def test_a_writable_definition_named_like_a_read_only_builtin_wins_by_exact_name_and_normalized_name(tmp_path):
    env = ro_env(tmp_path, {"Explore": "---\nname: Explore\ntools: Read, Write\n---\n"})
    for spelling in ("Explore", "explore", "EXPLORE"):
        out = run({"subagent_type": spelling, "prompt": "q"}, env=env)
        assert "## Delivery contract (test)" in out["updatedInput"]["prompt"], spelling


def test_an_ambiguous_normalized_name_keeps_the_standard_footer(tmp_path):
    """Claude Code refuses the launch ('ambiguous'); the hook must not pick a side: a writable `explore` beside the built-in `Explore`."""
    env = ro_env(tmp_path, {"explore-lower": "---\nname: explore\ntools: Read, Write\n---\n"})
    assert "## Delivery contract (test)" in run({"subagent_type": "EXPLORE", "prompt": "q"}, env=env)["updatedInput"]["prompt"]
    out = run({"subagent_type": "Explore", "prompt": "q"}, env=env)               # the exact name still picks the built-in
    assert "## Delivery contract (read-only" in out["updatedInput"]["prompt"]


def test_a_misspelled_exempt_type_is_exempt_too(tmp_path):
    env = ro_env(tmp_path)
    assert run({"subagent_type": "Claude_Code_Guide", "prompt": "q"}, env=env) is None
    assert run({"subagent_type": "statusline setup", "prompt": "q"}, env=env) is None


# LOW-1: an Edit-only definition is classed read-only (no report file) but is not told it may change nothing at all
def test_the_read_only_footer_does_not_forbid_an_editors_own_edit():
    text = RO_REPO_FOOTER.read_text()
    assert "Change nothing" not in text and "Create no report, marker or other new file" in text
    assert "edit an existing file only if your own task says to" in text


# LOW-2: one unreadable or undecodable definition must not turn the built-ins off
def test_an_undecodable_unrelated_definition_leaves_the_builtins_read_only(tmp_path):
    env = ro_env(tmp_path)
    (Path(env["AGENT_FOOTER_AGENT_DIRS"]) / "junk.md").write_bytes(b"\xff\xfe\x00bad\xc3\x28")
    assert_read_only_footer(tmp_path, run({"subagent_type": "Explore", "prompt": "q"}, env=env))
    assert_read_only_footer(tmp_path, run({"subagent_type": "explore", "prompt": "q"}, env=env))
    out = run({"subagent_type": "junk", "prompt": "q"}, env=env)                  # the bad file's own type fails open
    assert "## Delivery contract (test)" in out["updatedInput"]["prompt"]


def test_an_unreadable_unrelated_definition_leaves_the_builtins_read_only(tmp_path):
    env = ro_env(tmp_path, {"locked": "---\nname: locked\ntools: Read\n---\n"})
    locked = Path(env["AGENT_FOOTER_AGENT_DIRS"]) / "locked.md"
    locked.chmod(0)
    try:
        if os.access(locked, os.R_OK):
            return                                                            # running as root
        assert_read_only_footer(tmp_path, run({"subagent_type": "Plan", "prompt": "q"}, env=env))
    finally:
        locked.chmod(0o644)


# LOW-3: a writable type whose prompt carries the read-only heading still gets the standard footer
def test_a_writable_type_with_the_read_only_heading_gets_the_standard_footer(tmp_path):
    prompt = "do X\n\n## Delivery contract (read-only sub-agent: no file tools)\n1. final message\n"
    out = run({"subagent_type": "general-purpose", "description": "Do X", "prompt": prompt}, env=ro_env(tmp_path))
    new = out["updatedInput"]["prompt"]
    assert new.startswith(prompt.rstrip()) and new.count("## Delivery contract (test)") == 1
    assert str(tmp_path / "reports" / "s1" / "do-x-report.md") in out["additionalContext"]


# LOW-5: project before user, and the project root from CLAUDE_PROJECT_DIR when the session has cd'd into a subdirectory
def _proj_and_home(tmp_path, project_def, user_def):
    proj, home = tmp_path / "proj", tmp_path / "home"
    (proj / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
    (home / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
    (proj / ".claude" / "agents" / "dup.md").write_text(project_def)
    (home / ".claude" / "agents" / "dup.md").write_text(user_def)
    env = footer_env(tmp_path)                                                    # no AGENT_FOOTER_AGENT_DIRS
    env["HOME"] = str(home)
    return proj, env


def test_a_project_definition_beats_the_user_definition_of_the_same_name(tmp_path):
    ro, rw = "---\nname: dup\ntools: Read\n---\n", "---\nname: dup\ntools: Read, Write\n---\n"
    proj, env = _proj_and_home(tmp_path, ro, rw)
    assert "## Delivery contract (read-only" in run({"subagent_type": "dup", "prompt": "q"}, env=env, cwd=proj)["updatedInput"]["prompt"]
    proj, env = _proj_and_home(tmp_path, rw, ro)
    assert "## Delivery contract (test)" in run({"subagent_type": "dup", "prompt": "q"}, env=env, cwd=proj)["updatedInput"]["prompt"]


def test_claude_project_dir_finds_the_project_definitions_from_a_subdirectory(tmp_path):
    proj, env = _proj_and_home(tmp_path, "---\nname: dup\ntools: Read\n---\n", "---\nname: other\ntools: Read\n---\n")
    sub = proj / "src" / "deep"
    sub.mkdir(parents=True)
    out = run({"subagent_type": "dup", "prompt": "q"}, env=env, cwd=sub)
    assert "## Delivery contract (test)" in out["updatedInput"]["prompt"]          # cwd alone misses it
    out = run({"subagent_type": "dup", "prompt": "q"}, env=dict(env, CLAUDE_PROJECT_DIR=str(proj)), cwd=sub)
    assert "## Delivery contract (read-only" in out["updatedInput"]["prompt"]


# LOW-4: the read-only footer keeps the secrets, graft and closing-search rules that still apply to a Bash-capable Explore/Plan
def test_the_read_only_footer_keeps_secret_graft_and_closing_search_rules():
    text = RO_REPO_FOOTER.read_text()
    assert "never a whole line with a credential" in text
    assert "--no-refresh" in text and "Closing search:" in text


# r2 MED-1: a definition path that is not a regular file is never read (a symlink to /dev/zero grew the hook to 760 MB in 0.4 s,
# a FIFO hung it); it is skipped as if absent, so the built-in classification stands. Each run has a short timeout.
def _agents_dir(env):
    return Path(env["AGENT_FOOTER_AGENT_DIRS"])


def test_a_symlink_to_dev_zero_is_not_read(tmp_path):
    env = ro_env(tmp_path)
    (_agents_dir(env) / "notes.md").symlink_to("/dev/zero")
    assert_read_only_footer(tmp_path, run({"subagent_type": "Explore", "prompt": "q"}, env=env, timeout=10))


def test_a_fifo_definition_returns_promptly(tmp_path):
    env = ro_env(tmp_path)
    os.mkfifo(_agents_dir(env) / "zz.md")
    assert_read_only_footer(tmp_path, run({"subagent_type": "Explore", "prompt": "q"}, env=env, timeout=10))


def test_a_fifo_or_device_named_like_a_builtin_cannot_flip_it(tmp_path):
    env = ro_env(tmp_path)
    os.mkfifo(_agents_dir(env) / "Explore.md")
    (_agents_dir(env) / "Plan.md").symlink_to("/dev/zero")
    assert_read_only_footer(tmp_path, run({"subagent_type": "Explore", "prompt": "q"}, env=env, timeout=10))
    assert_read_only_footer(tmp_path, run({"subagent_type": "Plan", "prompt": "q"}, env=env, timeout=10))


def test_a_directory_named_like_a_definition_is_skipped(tmp_path):
    env = ro_env(tmp_path)
    (_agents_dir(env) / "x.md").mkdir()
    assert_read_only_footer(tmp_path, run({"subagent_type": "Explore", "prompt": "q"}, env=env, timeout=10))


def test_an_oversized_definition_is_read_only_up_to_its_cap(tmp_path):
    big = "---\nname: big\ntools: Read, Grep\n---\n" + "x" * 5_000_000
    env = ro_env(tmp_path, {"big": big})
    assert_read_only_footer(tmp_path, run({"subagent_type": "big", "prompt": "q"}, env=env, timeout=10))
    late = "---\nname: late\n" + ("pad: " + "y" * 100 + "\n") * 1000 + "tools: Read\n---\n"     # `tools:` after 64 KiB: never seen
    env = ro_env(tmp_path, {"late": late})
    out = run({"subagent_type": "late", "prompt": "q"}, env=env, timeout=10)
    assert "## Delivery contract (test)" in out["updatedInput"]["prompt"]
    flat = "---" + "y" * 5_000_000                                         # no newline inside the cap: nothing to parse, standard footer
    env = ro_env(tmp_path, {"flat": flat})
    out = run({"subagent_type": "flat", "prompt": "q"}, env=env, timeout=10)
    assert "## Delivery contract (test)" in out["updatedInput"]["prompt"]


def test_a_symlink_to_a_regular_definition_is_followed(tmp_path):
    real = tmp_path / "real-scout.md"
    real.write_text("---\nname: scout\ntools: Read, Grep\n---\n")
    env = ro_env(tmp_path)
    (_agents_dir(env) / "scout.md").symlink_to(real)
    assert_read_only_footer(tmp_path, run({"subagent_type": "scout", "prompt": "q"}, env=env))


def test_the_number_of_definition_files_read_is_capped(tmp_path):
    env = ro_env(tmp_path)
    for i in range(300):
        (_agents_dir(env) / f"a{i:03d}.md").write_text("---\ntools: Read\n---\n")
    (_agents_dir(env) / "zzz.md").write_text("---\ntools: Read\n---\n")         # sorts after 256 files: never read
    out = run({"subagent_type": "zzz", "prompt": "q"}, env=env)
    assert "## Delivery contract (test)" in out["updatedInput"]["prompt"]


# r2 LOW-1: YAML forms the hook cannot parse keep the standard footer (a writer is never made read-only by a misparse)
@pytest.mark.parametrize("tools_yaml", [
    "tools: >-\n  Read, Write, Bash\n",
    "tools: |\n  Read, Write, Bash\n",
    "tools: [Read,\n  Write, Bash]\n",
    "tools:\n  Read, Write\n",
])
def test_unparsed_tools_yaml_keeps_the_standard_footer(tmp_path, tools_yaml):
    env = ro_env(tmp_path, {"w": "---\nname: w\n" + tools_yaml + "---\n"})
    out = run({"subagent_type": "w", "prompt": "q"}, env=env)
    assert "## Delivery contract (test)" in out["updatedInput"]["prompt"] and "read-only" not in out["updatedInput"]["prompt"]


def test_unparsed_disallowed_tools_yaml_keeps_the_standard_footer(tmp_path):
    env = ro_env(tmp_path, {"w": "---\nname: w\ntools: Read\ndisallowedTools: >-\n  Write\n---\n"})
    out = run({"subagent_type": "w", "prompt": "q"}, env=env)
    assert "## Delivery contract (test)" in out["updatedInput"]["prompt"]


def test_a_wrapped_description_does_not_spoil_a_parsed_tools_line(tmp_path):
    env = ro_env(tmp_path, {"s": "---\nname: s\ndescription: >-\n  long text\ntools: Read, Grep\n---\n"})
    assert_read_only_footer(tmp_path, run({"subagent_type": "s", "prompt": "q"}, env=env))


# r2 LOW-3: a read-only contract pasted into a writable type's prompt does not override the standard one
def test_the_read_only_footer_applies_only_without_write_edit_or_bash():
    first = RO_REPO_FOOTER.read_text().split("\n")[2]
    assert "applies only if you have none of the Write, Edit and Bash tools" in first


def test_a_read_only_heading_without_a_space_does_not_count_as_the_standard_footer(tmp_path):
    prompt = "do X\n\n## Delivery contract(read-only sub-agent)\n1. final message\n"
    out = run({"subagent_type": "general-purpose", "description": "Do X", "prompt": prompt}, env=ro_env(tmp_path))
    assert out["updatedInput"]["prompt"].count("## Delivery contract (test)") == 1


# r2 LOW-4: with CLAUDE_PROJECT_DIR set, the hook's cwd (a checkout the session cd'd into) decides nothing
def test_cwd_is_ignored_when_claude_project_dir_is_set(tmp_path):
    proj, env = _proj_and_home(tmp_path, "---\nname: dup\ntools: Read, Write\n---\n", "---\nname: other\ntools: Read\n---\n")
    clone = tmp_path / "clone"
    (clone / ".claude" / "agents").mkdir(parents=True)
    (clone / ".claude" / "agents" / "dup.md").write_text("---\nname: dup\ntools: Read\n---\n")
    (clone / ".claude" / "agents" / "Explore.md").write_text("---\nname: Explore\ntools: Read, Write, Bash\n---\n")
    env = dict(env, CLAUDE_PROJECT_DIR=str(proj))
    out = run({"subagent_type": "Explore", "prompt": "q"}, env=env, cwd=clone)
    assert "## Delivery contract (read-only" in out["updatedInput"]["prompt"]          # the clone's writer Explore is not used
    out = run({"subagent_type": "dup", "prompt": "q"}, env=env, cwd=clone)
    assert "## Delivery contract (test)" in out["updatedInput"]["prompt"]           # the project's writer, not the clone's reader
