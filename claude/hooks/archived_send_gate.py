#!/usr/bin/env python3
"""archived_send_gate: PreToolUse hook, a message to an archived or replaced agent is denied, never delivered (ls-02).

Paseo un-archives and runs an archived agent that is sent a message (2026-11-14: the ex-lead 994234ba came back running and
could act as a stale lead). This hook checks the target of a Bash `paseo send` / `paseo agent send` and of the MCP tool
`send_agent_prompt` with `bin/ade_send_guard.py` (which reads `ade-self-session`'s completed-handoff records, #669):

  replaced by a completed handoff   deny, naming the successor (a hook cannot safely rewrite the target; re-send to it)
  archived, nothing replaced it     deny; `ADE_ALLOW_ARCHIVED_SEND=1 paseo send ...` resumes it on purpose
  live, unknown to Paseo, anything this hook cannot parse or reach   allow silently (fails open)

Only the target is judged, never the message. A target built by the shell (`$VAR`, a substitution, a glob) is not parsed.
Block form: stdout JSON permissionDecision "deny" and exit 0 (same as upstream_review_gate). Other TUIs without hooks rely on
`bin/ade_send_guard.py` (called by the in-repo senders) and AGENTS.md. Design and limits: docs/archived-send-guard.md.
"""
from __future__ import annotations

import json
from pathlib import Path
import shlex
import sys

BIN = Path(__file__).resolve().parent.parent.parent / "bin"
VALUE_FLAGS = {"--behavior", "--prompt-file", "--host", "--server", "--timeout", "--image", "--label", "--cwd"}
SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "\n"}
MCP_ID_KEYS = ("agentId", "agent_id", "id", "target")
ALLOW = "ADE_ALLOW_ARCHIVED_SEND=1"


def deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                              "permissionDecisionReason": reason}}))


def targets_in_command(command: str) -> list[tuple[str, bool]]:
    """[(target, allow_archived)] for every `paseo [agent] send` simple command in a shell command line."""
    lexer = shlex.shlex(command.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return []
    out: list[tuple[str, bool]] = []
    simple: list[str] = []
    for tok in tokens + [";"]:
        if tok in SEPARATORS or set(tok) <= set(";&|()"):
            out.extend(_one(simple))
            simple = []
        else:
            simple.append(tok)
    return out


def _one(words: list[str]) -> list[tuple[str, bool]]:
    allow = False
    i = 0
    while i < len(words) and "=" in words[i] and not words[i].startswith("-") and words[i].split("=", 1)[0].isidentifier():
        allow = allow or words[i] == ALLOW
        i += 1
    if i < len(words) and words[i] in ("env", "command", "exec"):
        return _one(words[i + 1:]) if words[i] != "env" else _one_env(words[i + 1:], allow)
    if i >= len(words) or Path(words[i]).name != "paseo":
        return []
    rest = words[i + 1:]
    if rest[:1] == ["agent"]:
        rest = rest[1:]
    if rest[:1] != ["send"]:
        return []
    args = rest[1:]
    j = 0
    while j < len(args):
        if args[j] == "--":  # the target is the first word after it, unless a positional already came before it
            return [(args[j + 1], allow)] if j + 1 < len(args) else []
        if args[j] in VALUE_FLAGS:
            j += 2
        elif args[j].startswith("-"):
            j += 1
        else:
            return [(args[j], allow)]
    return []


def _one_env(words: list[str], allow: bool) -> list[tuple[str, bool]]:
    k = 0
    while k < len(words) and ("=" in words[k] and not words[k].startswith("-")):
        allow = allow or words[k] == ALLOW
        k += 1
    found = _one(words[k:])
    return [(t, a or allow) for t, a in found]


def judge(target: str, allow: bool) -> str | None:
    """A denial reason, or None to allow."""
    if not target or any(c in target for c in "$`*?[{~"):
        return None
    sys.path.insert(0, str(BIN))
    import ade_send_guard as guard  # noqa: PLC0415 - lazy: any import problem must fail open
    env = {guard.ALLOW_ENV: "1"} if allow else {}
    d = guard.guard(target, env=env)
    if d.action == guard.REDIRECT:
        return (f"Blocked by archived_send_gate: {d.reason}. Re-send to {d.target} (a send to the replaced agent would "
                f"un-archive and run it as a stale lead).")
    if d.action == guard.REFUSE:
        return f"Blocked by archived_send_gate: {d.reason}."
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
        tool, tin = event.get("tool_name", ""), event.get("tool_input") or {}
        found: list[tuple[str, bool]] = []
        if tool == "Bash" and isinstance(tin.get("command"), str):
            found = targets_in_command(tin["command"])
        elif tool.startswith("mcp__") and tool.endswith("send_agent_prompt"):
            ident = next((tin[k] for k in MCP_ID_KEYS if isinstance(tin.get(k), str)), "")
            found = [(ident, False)] if ident else []
        for target, allow in found:
            reason = judge(target, allow)
            if reason:
                deny(reason)
                return 0
    except Exception as exc:  # noqa: BLE001 - a guard must never block on its own bug
        print(f"archived_send_gate: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
