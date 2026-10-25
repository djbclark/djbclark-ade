#!/usr/bin/env python3
"""PreToolUse (Agent): log and ask before an Agent-tool sub-agent runs on a frontier model.

Operator 2026-10-18: Fable is scarce. acp-dispatch gates it, but an Agent-tool sub-agent never
passes through acp-dispatch: `fable-deep` and `model: fable` reached it unseen (the opencodex
`ocx-*` sub-agents that also did were retired with the proxy on 2026-10-19). Each such call is appended to ~/.local/state/frontier-gate/agent-calls.jsonl and returns
"ask", so the operator confirms it. Skipped when ACP_OPERATOR_APPROVED names `fable-deep` (any
frontier sub-agent this session) or FRONTIER_GATE_OFF=1. Fails open on any error.
"""

import json
import os
import sys
import time
from pathlib import Path

FRONTIER_AGENTS = {"fable-deep": "Fable"}
LOG = Path.home() / ".local/state/frontier-gate/agent-calls.jsonl"

try:
    data = json.load(sys.stdin)
    if data.get("tool_name") not in ("Agent", "Task") or os.environ.get("FRONTIER_GATE_OFF"):
        sys.exit(0)
    tool_input = data.get("tool_input") or {}
    agent = str(tool_input.get("subagent_type") or "")
    model = str(tool_input.get("model") or "")
    what = FRONTIER_AGENTS.get(agent) or ("Fable" if "fable" in model.lower() else "")
    if not what:
        sys.exit(0)
    approved = "fable-deep" in {x.strip() for x in os.environ.get("ACP_OPERATOR_APPROVED", "").split(",")}
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(json.dumps({"at": time.time(), "session": data.get("session_id"), "cwd": data.get("cwd"),
                             "subagent_type": agent, "model": model, "frontier": what,
                             "description": tool_input.get("description"), "approved_env": approved}) + "\n")
    if approved:
        sys.exit(0)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "ask",
        "permissionDecisionReason": (
            f"Frontier sub-agent: {agent or 'model ' + model} runs on {what}, which is scarce (operator "
            "2026-10-18). Approve only if this really needs it; ordinary judgment is Opus at high first "
            "(model: opus; omp Opus next, and codex gpt-6.1-sol at high through acp-dispatch while "
            "its quota is plentiful, 2026-10-25), everyday work goes through acp-dispatch.")}}))
except Exception:  # noqa: BLE001 - a gate must never break the tool
    sys.exit(0)
