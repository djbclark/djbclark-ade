#!/usr/bin/env python3
"""PreToolUse (Bash): deny two shell mistakes that recur, and warn on a third (2026-10-18).

1. Bare `sed` (deny). On this Mac it is BSD sed; GNU `gsed` is the rule (2026-10-15: a BSD
   `sed -i` broke an edit; home CLAUDE.md item 1). An explicit `/usr/bin/sed` is a deliberate
   BSD choice (root/NOPASSWD scripts) and passes.
2. A display filter's exit status read as the command's (deny). `cmd | tail -2 && next` hands
   `&&` tail's status, which is always 0: on 2026-10-18 a refused `git merge --ff-only ... |
   tail -2 && git push` still pushed. Same for `||`, and for `$?` read right after the pipeline.
   Filters whose status is the point (rg, grep, jq, awk) pass, as does any command that sets
   `pipefail` or reads PIPESTATUS.
3. `sudo -n` without `-k` (warning only). A cached ticket (sudoers.d/10-timestamp-global makes
   it machine-wide) lets `sudo -n` run anything, so it proves nothing about a NOPASSWD rule:
   on 2026-10-18 a "narrow rule" check passed for a command the rule never allowed.
   `sudo -k -n CMD` ignores the cache without clearing it (man sudo, -k with a command).

Words inside quotes, heredoc bodies and comments do not count. Fails open on any parse error.
Escape hatch for the operator: BASH_HABITS_GATE_OFF=1.
"""

import json
import os
import re
import sys

FILTERS = frozenset({"tail", "head", "cut", "sort", "uniq", "column", "cat", "less", "more",
                     "tee", "tr", "gtr", "fold", "nl", "fmt", "wc", "gsed", "sed"})
WRAPPERS = frozenset({"env", "command", "exec", "time", "nice", "nohup", "builtin", "!"})
RC = "__RC__"


def strip_literals(c: str) -> str:
    """Drop heredoc bodies, quoted strings and comments; a quoted `$?` leaves a marker."""
    out, lines, i = [], c.split("\n"), 0
    while i < len(lines):
        out.append(lines[i])
        m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", lines[i])
        if m:
            i += 1
            while i < len(lines) and lines[i].strip() != m.group(1):
                i += 1
        i += 1
    s = "\n".join(out)
    s = re.sub(r"'[^']*'", "''", s)
    s = re.sub(r'"[^"]*"', lambda m: f'"{RC}"' if "$?" in m.group(0) else '""', s)
    s = s.replace("$?", RC)
    s = re.sub(r"(?m)(^|\s)#.*$", r"\1", s)
    # `|&` is a pipe, and redirections are not control operators
    s = s.replace("|&", "|")
    return re.sub(r"\d*>&\d*-?|&>>?|<&\d*", " ", s)


def words(stage: str) -> list[str]:
    """A stage's words; `$(`, backticks and `(`/`{` start a command, so they split too."""
    return [w for w in re.split(r"\s+|\$\(|`|\(|\{", stage) if w]


def command_word(stage: str) -> tuple[str, list[str]]:
    """The command a pipeline stage runs, past VAR=x prefixes, wrappers, sudo/xargs/timeout and
    their flags; plus the words after it. (`sudo -u USER` would take USER as the command: rare,
    and it only fails open.)"""
    w = words(stage)
    while w:
        head = w[0]
        if re.fullmatch(r"\w+=\S*", head) or head in WRAPPERS:
            w = w[1:]
        elif head in ("sudo", "xargs", "timeout", "gtimeout"):
            w = w[1:]
            while w and w[0].startswith("-"):
                w = w[1:]
            if head.endswith("timeout") and w:
                w = w[1:]                       # the duration
        else:
            return head, w[1:]
    return "", []


def deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    sys.exit(0)


def check(cmd: str) -> tuple[str | None, str | None]:
    """(deny reason, warning) for a Bash command line."""
    plain = strip_literals(cmd)
    # control operators split pipelines; keep each operator to know what reads the status
    parts = re.split(r"(&&|\|\||;|\n|&)", plain)
    pipelines = [(parts[i], parts[i + 1] if i + 1 < len(parts) else "")
                 for i in range(0, len(parts), 2)]
    guarded = bool(re.search(r"pipefail|PIPESTATUS", plain))
    warn = None
    for n, (pipeline, op) in enumerate(pipelines):
        stages = re.split(r"\|&?", pipeline)
        for stage in stages:
            if command_word(stage)[0] == "sed":
                return ("Use `gsed`, not bare `sed`: this Mac's `sed` is BSD sed and GNU flags "
                        "differ (2026-10-15: a BSD `sed -i` broke an edit). To read lines use "
                        "the Read tool or `gsed -n A,Bp`; a deliberate BSD call writes "
                        "`/usr/bin/sed`."), None
            w = words(stage)
            if w and w[0] == "sudo":
                flags = "".join(x.lstrip("-") for x in w[1:] if x.startswith("-") and not x.startswith("--"))
                if "n" in flags and "k" not in flags:
                    warn = ("`sudo -n` succeeds for any command while a sudo ticket is cached "
                            "(this Mac's timestamp is global), so it proves nothing about a "
                            "NOPASSWD rule. To test or rely on a rule, use `sudo -k -n CMD`: "
                            "it ignores the cache without clearing it.")
        if len(stages) < 2 or guarded:
            continue
        last, _ = command_word(stages[-1])
        if last not in FILTERS:
            continue
        nxt = pipelines[n + 1][0] if n + 1 < len(pipelines) else ""
        if op in ("&&", "||") or (op in (";", "\n") and RC in nxt):
            reads = op if op in ("&&", "||") else "$?"
            return (f"`... | {last}` then `{reads}` tests {last}'s exit status, not the "
                    f"command's ({last} exits 0 almost always; 2026-10-18 a refused `git merge "
                    f"--ff-only ... | tail -2 && git push` still pushed). Write `cmd > out.log "
                    f"2>&1; echo \"rc=$?\" > out.rc; tail -5 out.log`, use `;` where the "
                    f"status does not matter, or start with `set -o pipefail`."), warn
    return None, warn


def main() -> None:
    """Claude Code PreToolUse by default; `--codex` (Codex PreToolUse: deny = exit 2, reason on
    stderr, its documented form) and `--cursor` (Cursor beforeShellExecution: stdin `command`,
    stdout `permission`/`agent_message`) wire the same checks into those TUIs."""
    mode = sys.argv[1] if len(sys.argv) > 1 else "--claude"
    try:
        data = json.load(sys.stdin)
    except (ValueError, OSError):
        sys.exit(0)
    if os.environ.get("BASH_HABITS_GATE_OFF"):
        sys.exit(0)
    if mode == "--cursor":
        cmd = data.get("command")
    elif data.get("tool_name") in ("Bash", "shell", "shell_command", "exec_command"):
        cmd = (data.get("tool_input") or {}).get("command")
    else:
        sys.exit(0)
    if isinstance(cmd, list):                    # an argv such as ["bash", "-lc", "<script>"]
        cmd = cmd[-1] if cmd else ""
    try:
        reason, warn = check(str(cmd or ""))
    except (re.error, TypeError, AttributeError, IndexError):
        sys.exit(0)
    if mode == "--cursor":
        msg = reason or warn
        out = {"permission": "deny" if reason else "allow"}
        if msg:
            out.update(user_message=msg, agent_message=msg)
        print(json.dumps(out))
        sys.exit(0)
    if mode == "--codex":
        if reason:
            print(reason, file=sys.stderr)
            sys.exit(2)
        sys.exit(0)
    if reason:
        deny(reason)
    if warn:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "additionalContext": warn}}))
    sys.exit(0)


if __name__ == "__main__":
    main()
