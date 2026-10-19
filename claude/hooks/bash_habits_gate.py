#!/usr/bin/env python3
"""PreToolUse (Bash): deny three shell mistakes that recur, and warn on a fourth (2026-10-18).

1. Bare `sed` (deny). On this Mac it is BSD sed; GNU `gsed` is the rule (2026-10-15: a BSD
   `sed -i` broke an edit; home CLAUDE.md item 1). An explicit `/usr/bin/sed` is a deliberate
   BSD choice (root/NOPASSWD scripts) and passes.
2. A display filter's exit status read as the command's (deny). `cmd | tail -2 && next` hands
   `&&` tail's status, which is always 0: on 2026-10-18 a refused `git merge --ff-only ... |
   tail -2 && git push` still pushed. Same for `||`, and for `$?` read right after the pipeline.
   Filters whose status is the point (rg, grep, jq, awk) pass, as does any command that sets
   `pipefail` or reads PIPESTATUS.
3. A GNU-only option on a bare BSD tool (deny). `chmod --reference=a b; mv -f b a` on 2026-10-18:
   BSD chmod rejected the option, the `mv` still ran and a live hook lost its execute bit. The
   table below lists only options probed to fail on this Mac (chmod, chown, cp, mv, rm, mkdir,
   touch, ln, wc, cut, tr, du, df, stat, date, readlink, realpath take no long option at all; ls,
   head, tail, xargs, grep and find have a short list); `--help`/`--version` and anything not
   probed pass. The reason names the g-prefixed tool (`gchmod`); `/bin/chmod` also passes.
4. `sudo -n` without `-k` (warning only). A cached ticket (sudoers.d/10-timestamp-global makes
   it machine-wide) lets `sudo -n` run anything, so it proves nothing about a NOPASSWD rule:
   on 2026-10-18 a "narrow rule" check passed for a command the rule never allowed.
   `sudo -k -n CMD` ignores the cache without clearing it (man sudo, -k with a command).

Words inside quotes, heredoc bodies and comments do not count. Fails open on any parse error.
The tool table is separate from bin/gnu-tools-check's, which flags every long option on its
basics (its job is to find code to review); a hook that blocks a live command must not guess.
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

# GNU-only options on bare BSD tools, each probed on this Mac (2026-10-18; macOS 27, BSD
# userland). A tool left out (sort, cat, env, ...) accepted its GNU options when probed.
# Tools whose BSD version rejects every long option:
NO_LONG = frozenset("chmod chown cp mv rm mkdir touch ln wc cut tr du df stat date readlink "
                    "realpath".split())
LONG_OK = frozenset({"help", "version", ""})        # a usage probe, not a GNU-only habit
# Tools that take only some long options: the one BSD accepts (ls) or the ones it rejects.
LONG_ONLY = {"ls": {"color"}}
LONG_BAD = {
    "head": {"quiet", "silent", "verbose", "zero-terminated"},
    "tail": {"follow", "retry", "pid", "max-unchanged-stats", "sleep-interval"},
    "xargs": {"delimiter", "replace", "max-lines", "arg-file", "show-limits", "open-tty",
              "process-slot-var", "eof", "exit"},
    "grep": {"perl-regexp", "dereference-recursive", "initial-tab", "no-ignore-case",
             "exclude-from", "group-separator", "no-group-separator"},
}
# Short options BSD rejects, matched against an option word (a cluster's leading letters are
# only those BSD itself accepts, so `-Lc` is caught and a pattern like `-eP` is not).
SHORT_BAD = {
    "cp": r"-[tTu]", "mv": r"-[tTub]", "ln": r"-[rTtbS]", "date": r"-[jnRu]*d", "tr": r"-t",
    "cut": r"-z", "df": r"-[xB]", "du": r"-[AHLPIacghkmnsx]*b",
    "stat": r"-[FLnqrstx]*c", "readlink": r"-[nf]*[emqsvz]", "realpath": r"-q*[LPesmz]",
    "xargs": r"-[0oprtx]*[daiel]", "grep": r"-[abcEFGHhIiJLlMnOopqRrSsUVvwXxZz]*P",
}
# `xargs` options that take the next word, so it is not mistaken for the command.
XARGS_ARG = frozenset({"-E", "-I", "-J", "-L", "-n", "-P", "-R", "-S", "-s"})
# find primaries BSD does not know (a leading -H/-L/-P is BSD's own and is left alone).
FIND_BAD = frozenset({"-printf", "-fprint", "-fprint0", "-fprintf", "-fls", "-regextype",
                      "-xtype", "-executable", "-readable", "-writable", "-files0-from",
                      "-daystart", "-warn", "-nowarn", "-context", "-used"})


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


def option_words(args: list[str], takes: frozenset = frozenset()) -> list[str]:
    """The leading option words of a command's arguments, up to `--` or the first operand;
    an option in `takes` also consumes the word after it (its value)."""
    out, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a == "--" or not a.startswith("-") or a == "-":
            break
        else:
            out.append(a)
            skip = a in takes
    return out


def gnu_only(tool: str, args: list[str]) -> str | None:
    """The first GNU-only option `tool` is given, or None (see the table above)."""
    if tool == "find":
        for i, a in enumerate(args):
            if a in ("-exec", "-execdir", "-ok", "-okdir"):
                break
            if a in FIND_BAD:
                return a
            if a == "-perm" and i + 1 < len(args) and args[i + 1].startswith("/"):
                return f"-perm {args[i + 1]}"
        return None
    opts = option_words(args, XARGS_ARG if tool == "xargs" else frozenset())
    for i, a in enumerate(opts):
        if a.startswith("--"):
            name, _, value = a[2:].partition("=")
            if name in LONG_OK:
                continue
            if tool in NO_LONG or (tool in LONG_ONLY and name not in LONG_ONLY[tool]) \
                    or name in LONG_BAD.get(tool, ()):
                return "--" + name
            if tool in ("head", "tail") and name in ("lines", "bytes") and re.match(r"-\d", value):
                return a
        elif a in ("-n", "-c") and tool == "head" and i + 1 < len(args):
            if re.fullmatch(r"-\d+", opts[i + 1] if i + 1 < len(opts) else ""):
                return f"{a} {opts[i + 1]}"
        elif tool == "head" and re.fullmatch(r"-[nc]-\d+", a):
            return a
        elif tool in SHORT_BAD and re.match(SHORT_BAD[tool], a):
            return a
    return None


def xargs_args(stage: str) -> list[str]:
    """The words after an `xargs` that starts this stage (past VAR=x, wrappers, sudo), else []."""
    w = words(stage)
    while w:
        if re.fullmatch(r"\w+=\S*", w[0]) or w[0] in WRAPPERS:
            w = w[1:]
        elif w[0] == "sudo":
            w = w[1:]
            while w and w[0].startswith("-"):
                w = w[1:]
        else:
            return w[1:] if w[0] == "xargs" else []
    return []


def gnu_reason(tool: str, flag: str, via_xargs: bool = False) -> str:
    where = f"xargs {tool}" if via_xargs else tool
    g = "gxargs" if tool == "xargs" else f"g{tool}"
    return (f"`{tool} {flag}` is GNU-only and this Mac's `{tool}` is BSD: it fails with a usage "
            f"error, and whatever follows `;` or `&&` still runs (2026-10-18: `chmod --reference` "
            f"failed, the `mv -f` after it ran, and a live hook lost its execute bit). Use "
            f"`{('xargs ' if via_xargs else '') + g}` (brew; `{g} {flag}`), or drop the option. "
            f"A deliberate BSD call writes `/bin/{tool}` or `/usr/bin/{tool}`.")


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
            tool, args = command_word(stage)
            flag = gnu_only(tool, args)
            if flag:
                return gnu_reason(tool, flag, bool(re.search(r"\bxargs\b", stage))
                                  and tool != "xargs"), None
            xa = xargs_args(stage)
            flag = gnu_only("xargs", xa) if xa else None
            if flag:
                return gnu_reason("xargs", flag), None
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
