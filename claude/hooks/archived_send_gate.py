#!/usr/bin/env python3
"""archived_send_gate: PreToolUse hook, a message to an archived or replaced agent is denied, never delivered (ls-02).

Paseo un-archives and runs an archived agent that is sent a message (2026-11-14: the ex-lead 994234ba came back running and
could act as a stale lead). This hook checks the target of a Bash `paseo send` / `paseo agent send` and of the MCP tool
`send_agent_prompt` with `bin/ade_send_guard.py` (which reads `ade-self-session`'s completed-handoff records, #669):

  replaced by a completed handoff   deny, naming the successor (a hook cannot safely rewrite the target; re-send to it)
  archived, nothing replaced it     deny; `ADE_ALLOW_ARCHIVED_SEND=<its full id> paseo send ...` resumes it on purpose
  live, unknown to Paseo, anything this hook cannot parse or reach   allow silently (fails open)

Only the target is judged, never the message. A target built by the shell (`$VAR`, a substitution, a glob) is not parsed.
Block form: stdout JSON permissionDecision "deny" and exit 0 (same as upstream_review_gate). Other TUIs without hooks rely on
`bin/ade_send_guard.py` (called by the in-repo senders) and AGENTS.md. Design and limits: docs/archived-send-guard.md.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shlex
import sys

BIN = Path(__file__).resolve().parent.parent.parent / "bin"
VALUE_FLAGS = {"--prompt", "--prompt-file", "--image", "--behavior"}  # the value options of `paseo send`
OTHER_DAEMON = {"--host", "--home"}  # another daemon: its agents are not in this ledger, so not judged
SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "\n"}
MCP_ID_KEYS = ("agentId", "agent_id", "id", "target")
ALLOW_VAR = "ADE_ALLOW_ARCHIVED_SEND"


def deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                              "permissionDecisionReason": reason}}))


HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
NO_RUN = {"echo", "printf"}  # words after these are text, not a command


def strip_heredocs(command: str) -> str:
    """The command without heredoc bodies (a brief that merely quotes a send is not a send)."""
    lines, out, end = command.split("\n"), [], None
    for line in lines:
        if end is not None:
            if line.strip() == end:
                end = None
            continue
        out.append(line)
        m = HEREDOC.search(line)
        if m:
            end = m.group(2)
    if end is not None:  # no terminator line: `<<` was not a heredoc (quoted, arithmetic): judge the whole command
        return command
    return "\n".join(out)


def strip_comments(text: str) -> str:
    """The command as one logical line per simple command, without shell comments. A `#` that starts a word outside quotes
    runs to the end of its line; a `#` inside a word (a URL fragment) or a quote is text. `\\`+newline is a line continuation
    (removed outside quotes and inside double quotes, as the shell does). A newline outside quotes becomes ` ; ` (a command
    separator); inside quotes it stays. (shlex's own comment handling cuts at any `#`, so it is switched off.)"""
    out, quote, i, n = [], None, 0, len(text)
    while i < n:
        c = text[i]
        if quote == "'":
            out.append(c)
            if c == "'":
                quote = None
        elif quote == '"':
            if c == "\\" and i + 1 < n:
                i += 1
                if text[i] != "\n":  # a continuation vanishes; any other escaped pair stays
                    out.append(c + text[i])
            else:
                out.append(c)
                if c == '"':
                    quote = None
        elif c == "\\" and i + 1 < n:
            i += 1
            if text[i] != "\n":
                out.append(c + text[i])
        elif c in "'\"":
            quote = c
            out.append(c)
        elif c == "#" and (i == 0 or text[i - 1] in " \t\n;&|()"):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif c == "\n":
            out.append(" ; ")
        else:
            out.append(c)
        i += 1
    return "".join(out)


def targets_in_command(command: str, depth: int = 0) -> list[tuple[str, str | None]]:
    """[(target, allow)] for every `paseo [agent] send` found in a shell command line. `allow` is the value of an
    ADE_ALLOW_ARCHIVED_SEND=... assignment seen before it (the agent id the operator allowed), else None."""
    text = strip_comments(strip_heredocs(command)).replace("`", " ; ").replace("$(", " ; ")
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""  # comments were removed above, with the shell's rule
    try:
        tokens = list(lexer)
    except ValueError:
        return []
    out: list[tuple[str, str | None]] = []
    simple: list[str] = []
    for tok in tokens + [";"]:
        if tok in SEPARATORS or (tok and set(tok) <= set(";&|()")):
            out.extend(_one(simple, depth))
            simple = []
        else:
            simple.append(tok)
    return out


def _one(words: list[str], depth: int) -> list[tuple[str, str | None]]:
    """One simple command. The `paseo [agent] send` pair is looked for anywhere in it, so wrappers (timeout, env -u, nohup,
    sudo, xargs, `{`, `if`, `!`) need no special case; `sh -c STRING` is parsed again."""
    if not words or Path(words[0]).name in NO_RUN:
        return []
    found: list[tuple[str, str | None]] = []
    shell = next((i for i, w in enumerate(words) if Path(w).name in SHELLS), None)  # behind a wrapper too: timeout 30 bash -c
    if depth < 3 and shell is not None:
        cflag = next((i for i in range(shell + 1, len(words)) if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", words[i])), None)
        if cflag is not None and cflag + 1 < len(words):  # -c, -lc, -ec ...
            found.extend(targets_in_command(words[cflag + 1], depth + 1))
    for i, w in enumerate(words):
        if Path(w).name != "paseo":
            continue
        rest = words[i + 1:]
        while rest and rest[0].startswith("-"):  # a global option before the verb: paseo --json send, paseo -o json send
            if rest[0] in OTHER_DAEMON or rest[0].startswith(("--host=", "--home=")):
                return found
            rest = rest[2:] if rest[0] in {"-o", "--format"} else rest[1:]
        if rest[:1] == ["agent"]:
            rest = rest[1:]
        if rest[:1] != ["send"]:
            continue
        target = _target(rest[1:])
        if target:  # an override counts only as an assignment before the command, never as a word of the message
            allow = next((x.split("=", 1)[1] for x in words[:i] if x.startswith(ALLOW_VAR + "=")), None)
            found.append((target, allow))
        break
    return found


def _target(args: list[str]) -> str | None:
    """The agent word of `paseo send` arguments: skip the value flags; the first word after `--`; None when another daemon
    is addressed (--host/--home) or nothing is found."""
    j = 0
    while j < len(args):
        a = args[j]
        if a in OTHER_DAEMON or a.startswith(("--host=", "--home=")):
            return None
        if a == "--":
            return args[j + 1] if j + 1 < len(args) else None
        if a in VALUE_FLAGS:
            j += 2
        elif a.startswith("-"):
            j += 1
        else:
            return a
    return None


def judge(target: str, allow: str | None) -> str | None:
    """A denial reason, or None to allow."""
    if not target or any(c in target for c in "$`*?[{~"):
        return None
    sys.path.insert(0, str(BIN))
    import ade_send_guard as guard  # noqa: PLC0415 - lazy: any import problem must fail open
    env = {guard.ALLOW_ENV: allow} if allow else {}
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
        found: list[tuple[str, str | None]] = []
        if tool == "Bash" and isinstance(tin.get("command"), str):
            found = targets_in_command(tin["command"])
        elif tool.startswith("mcp__") and tool.endswith("send_agent_prompt"):
            ident = next((tin[k] for k in MCP_ID_KEYS if isinstance(tin.get(k), str)), "")
            found = [(ident, None)] if ident else []  # another host's agent id is unknown here: decide() passes it
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
