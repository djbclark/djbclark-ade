#!/usr/bin/env python3
"""PreToolUse (Agent): deny an Agent-tool sub-agent whose prompt lacks the acp-dispatch delivery footer.

~/CLAUDE.md rule 25: every Agent-tool sub-agent gets `acp-dispatch footer --report <scratchpad>/<name>-report.md`
pasted into its prompt, because the harness cuts a sub-agent's final message at 4,000 characters and the
footer is what makes it write a report file, a `.done` marker and `BLOCKED:` instead of a question. On
2026-10-18 a lead launched a research sub-agent without it and had to SendMessage the contract afterwards.
The footer's own heading is the check. Exempt: claude-code-guide and statusline-setup (short answers by
design). AGENT_FOOTER_GATE_OFF=1 disables it. Fails open on any error.
"""

import json
import os
import sys

MARK = "Delivery contract"
EXEMPT = {"claude-code-guide", "statusline-setup"}

try:
    data = json.load(sys.stdin)
    if data.get("tool_name") not in ("Agent", "Task") or os.environ.get("AGENT_FOOTER_GATE_OFF"):
        sys.exit(0)
    tool_input = data.get("tool_input") or {}
    if str(tool_input.get("subagent_type") or "") in EXEMPT or MARK in str(tool_input.get("prompt") or ""):
        sys.exit(0)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": (
            "This sub-agent prompt has no delivery footer (~/CLAUDE.md rule 25). Run "
            "`~/src/djbclark-ade/bin/acp-dispatch footer --report <scratchpad>/<name>-report.md`, paste its "
            "output (it starts with '## Delivery contract') at the end of the prompt, and launch again; then "
            "read that report file, not the final message.")}}))
except Exception:  # noqa: BLE001 - a gate must never break the tool
    sys.exit(0)
