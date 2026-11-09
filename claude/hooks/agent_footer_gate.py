#!/usr/bin/env python3
"""PreToolUse (Agent): give an Agent-tool sub-agent the delivery footer when its prompt lacks it.

~/CLAUDE.md rule 25: every Agent-tool sub-agent gets the filled `docs/dispatch-footer.md` pasted into
its prompt, because the harness cuts a sub-agent's final message at 4,000 characters and the footer is
what makes it write a report file, a `.done` marker and `BLOCKED:` instead of a question. On 2026-10-18
a lead launched a research sub-agent without it and had to SendMessage the contract afterwards. The
footer's own heading is the check. A prompt without it is no longer denied (2026-10-18, djbclark: the
deny cost a relaunch for a step the hook can do itself): the hook appends the footer through
`updatedInput`. The report path is the one the prompt labels ("Report path: /abs/x-report.md") or the
only absolute `*-report.md` path it names, never one whose `.done` exists, else
`~/.local/state/agent-reports/<session>/<name>-report.md`; the sub-agent's `written: <path>` final line
and the hook's `additionalContext` both name it. If the footer cannot be built, the old deny stands.
Exempt: claude-code-guide and statusline-setup (short answers by design). AGENT_FOOTER_GATE_OFF=1
disables it. Fills `docs/dispatch-footer.md` inline (2026-11-09: no longer shells out to
`acp-dispatch footer`, which Wave 6 deletes). Fails open on any other error.
"""

import json
import os
import re
import sys
from pathlib import Path

MARK = "Delivery contract"
EXEMPT = {"claude-code-guide", "statusline-setup"}
DEFAULT_LEAD = "main"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_FOOTER = _REPO_ROOT / "docs" / "dispatch-footer.md"
_HOME_FOOTER = Path.home() / "src/djbclark-ade/docs/dispatch-footer.md"
REPORT_IN_PROMPT = re.compile(r"(/[\w.@~+/-]+-report\.md)\b")
REPORT_LABELLED = re.compile(r"(?i)report(?: path| file)?\s*(?:is|:|=)\s*`?(/[\w.@~+/-]+-report\.md)\b")
DENY_REASON = (
    "This sub-agent prompt has no delivery footer (~/CLAUDE.md rule 25) and the hook could not build one. "
    "Paste the filled delivery contract from docs/dispatch-footer.md (it starts with '## Delivery "
    "contract') at the end of the prompt with {report} set to <scratchpad>/<name>-report.md, and launch "
    "again; then read that report file, not the final message.")


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-")
    return s or "subagent"


def named_report(prompt):
    """The report path the prompt itself gives: a labelled one, else the only one it mentions. A path whose
    .done exists is someone's finished report (2026-10-18: a review prompt that named the slice's report as
    background got that path), so it is never reused."""
    labelled = REPORT_LABELLED.findall(prompt)
    paths = labelled or sorted(set(REPORT_IN_PROMPT.findall(prompt)))
    if len(paths) != 1 and not labelled:
        return None
    return None if Path(paths[0] + ".done").exists() else paths[0]


def report_path(data, tool_input):
    named = named_report(str(tool_input.get("prompt") or ""))
    if named:
        return named
    session = slug(str(data.get("session_id") or "session"))
    name = slug(str(tool_input.get("name") or tool_input.get("description") or ""))
    d = Path(os.environ.get("AGENT_FOOTER_REPORT_DIR") or Path.home() / ".local/state/agent-reports") / session
    d.mkdir(parents=True, exist_ok=True)
    return str(d / f"{name}-report.md")


def footer_file():
    override = os.environ.get("AGENT_FOOTER_FILE")
    if override:
        return Path(override)
    if _DEFAULT_FOOTER.is_file():
        return _DEFAULT_FOOTER
    return _HOME_FOOTER


def footer(report):
    """Fill docs/dispatch-footer.md placeholders; same substitutions as acp-dispatch footer once did."""
    path = footer_file()
    try:
        text = path.read_text()
    except OSError:
        return None
    lead = os.environ.get("AGENT_FOOTER_LEAD") or DEFAULT_LEAD
    report_p = Path(report)
    done = str(report_p.with_name(report_p.name + ".done"))
    inbox = str(report_p.with_name(report_p.name + ".inbox.md"))
    replies = str(report_p.with_name(report_p.name + ".replies.md"))
    out = (text.replace("{report}", report).replace("{done}", done)
           .replace("{inbox}", inbox).replace("{replies}", replies)
           .replace("{lead}", lead)).strip()
    return out if MARK in out else None


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
    except OSError:
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
