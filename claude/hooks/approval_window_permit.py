#!/usr/bin/env python3
"""PermissionRequest hook: allow a tool-permission prompt while the sudo-ask approval window is open (2026-11-22).

Operator ruling: "we want our limited-duration token to also avoid prompts such as this" (Claude Code's built-in `rm`
safety card, "Dangerous rm operation on possibly-empty variable path"). This is the route for a Claude Code session that
Paseo does not run; for Paseo's Claude agents `bin/ade-approval-window` answers the card through the daemon (it also reads
the same window and applies the same policy, `bin/ade_approval_window.decide`).

Output: when the window is open and the policy allows the request, the documented allow decision

    {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}

and otherwise NOTHING (exit 0, no stdout: the permission flow is unchanged and the operator is asked as before). The hook
never denies, never rewrites the input (`updatedInput`; AskUserQuestion and ExitPlanMode need it, so they get no decision)
and fails open to "no decision" on any error: bad stdin, an unreadable grant, an unwritable audit log, an import problem.

Every allow and every hold while the window is open writes one line to ~/.local/state/djbclark-ade/approval-window/
permits.jsonl first; a line that cannot be written means no decision.

Not installed live by the PR that added it (registration: agents/claude/settings.json.tmpl, PermissionRequest). Whether
an allow from this hook clears the interactive countdown of a prompt that is already showing is not documented
(https://code.claude.com/docs/en/hooks.md says only that the hook runs "when Claude Code is about to ask you for
permission"; for a call that reaches an Agent SDK canUseTool callback the hooks "run alongside your host, and whichever
decides first applies"): the lead checks that live. docs/approval-window.md. Runs under Python 3.9 (macOS /usr/bin/python3).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent.parent / "bin"


def decision_for(payload: object, grant_path: str | None = None, owner_uid: int = 0, log_path: Path | None = None,
                 home: str | None = None, now: float | None = None) -> dict | None:
    """The hook's stdout object for this stdin payload, or None for no decision. The parameters are for tests: the hook
    itself always runs with the hard-coded grant path, root ownership and the default log."""
    if not isinstance(payload, dict) or payload.get("hook_event_name") != "PermissionRequest":
        return None
    tool = payload.get("tool_name")
    if not isinstance(tool, str) or not tool:
        return None
    sys.path.insert(0, str(BIN))
    import ade_approval_window as window  # noqa: PLC0415 - lazy: any import problem must mean no decision

    if not window.window_open(grant_path or window.GRANT_PATH, now, owner_uid):
        return None
    req = window.claude_hook_request(tool, payload.get("tool_input"))
    agent = os.environ.get("PASEO_AGENT_ID") or str(payload.get("session_id") or "")
    req = window.Request(agent_id=agent, request_id=str(payload.get("tool_use_id") or ""), provider=req.provider,
                         name=req.name, kind=req.kind, title="", description="", input=req.input, detail=None, metadata=None)
    verdict = window.decide(req, home)
    log = window.AuditLog(log_path or window.default_log_path())
    log.decision(req, "allow" if verdict.allow else "hold", verdict.rule, verdict.subject)   # audit first
    if not verdict.allow:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}


def main() -> int:
    try:
        out = decision_for(json.loads(sys.stdin.read()))
    except Exception:  # noqa: BLE001 - a hook that cannot decide leaves the flow unchanged
        return 0
    if out is not None:
        sys.stdout.write(json.dumps(out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
