#!/usr/bin/env python3
"""PreToolUse (Agent): give an Agent-tool sub-agent the acp-dispatch delivery footer when its prompt lacks it.

~/CLAUDE.md rule 25: every Agent-tool sub-agent gets `acp-dispatch footer --report <scratchpad>/<name>-report.md`
pasted into its prompt, because the harness cuts a sub-agent's final message at 4,000 characters and the
footer is what makes it write a report file, a `.done` marker and `BLOCKED:` instead of a question. On
2026-10-18 a lead launched a research sub-agent without it and had to SendMessage the contract afterwards.
The footer's own heading is the check. A prompt without it is no longer denied (2026-10-18, djbclark: the
deny cost a relaunch for a step the hook can do itself): the hook appends the footer through `updatedInput`.
The report path is the first absolute `*-report.md` path the prompt names, else
`~/.local/state/agent-reports/<session>/<name>-report.md`; the sub-agent's `written: <path>` final line and
the hook's `additionalContext` both name it. If the footer cannot be built, the old deny stands. Exempt:
claude-code-guide and statusline-setup (short answers by design). AGENT_FOOTER_GATE_OFF=1 disables it.
Fails open on any other error.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

MARK = "Delivery contract"
EXEMPT = {"claude-code-guide", "statusline-setup"}
ACP_DISPATCH = os.environ.get("AGENT_FOOTER_ACP_DISPATCH") or str(Path.home() / "src/djbclark-ade/bin/acp-dispatch")
REPORT_IN_PROMPT = re.compile(r"(/[\w.@~+/-]+-report\.md)\b")
DENY_REASON = (
    "This sub-agent prompt has no delivery footer (~/CLAUDE.md rule 25) and the hook could not build one. Run "
    "`~/src/djbclark-ade/bin/acp-dispatch footer --report <scratchpad>/<name>-report.md`, paste its "
    "output (it starts with '## Delivery contract') at the end of the prompt, and launch again; then "
    "read that report file, not the final message.")


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-")
    return s or "subagent"


def report_path(data, tool_input):
    m = REPORT_IN_PROMPT.search(str(tool_input.get("prompt") or ""))
    if m:
        return m.group(1)
    session = slug(str(data.get("session_id") or "session"))
    name = slug(str(tool_input.get("name") or tool_input.get("description") or ""))
    d = Path(os.environ.get("AGENT_FOOTER_REPORT_DIR") or Path.home() / ".local/state/agent-reports") / session
    d.mkdir(parents=True, exist_ok=True)
    return str(d / f"{name}-report.md")


def footer(report):
    r = subprocess.run([ACP_DISPATCH, "footer", "--report", report], capture_output=True, text=True, timeout=15)
    out = r.stdout.strip()
    return out if r.returncode == 0 and MARK in out else None


try:
    data = json.load(sys.stdin)
    if data.get("tool_name") not in ("Agent", "Task") or os.environ.get("AGENT_FOOTER_GATE_OFF"):
        sys.exit(0)
    tool_input = data.get("tool_input") or {}
    if str(tool_input.get("subagent_type") or "") in EXEMPT or MARK in str(tool_input.get("prompt") or ""):
        sys.exit(0)
    report = ""
    try:
        report = report_path(data, tool_input)
        text = footer(report)
    except (OSError, subprocess.SubprocessError):
        text = None
    if text is None:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": DENY_REASON}}))
        sys.exit(0)
    updated = dict(tool_input, prompt=str(tool_input.get("prompt") or "").rstrip() + "\n\n" + text + "\n")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "updatedInput": updated,
        "additionalContext": (
            f"agent_footer_gate appended the delivery footer to this sub-agent's prompt. Its report is {report} "
            f"(done marker {report}.done): read that file, not the final message.")}}))
except Exception:  # noqa: BLE001 - a gate must never break the tool
    sys.exit(0)
