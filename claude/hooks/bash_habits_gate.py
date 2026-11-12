#!/usr/bin/env python3
"""PreToolUse (Bash): deny five shell mistakes that recur, and warn on a sixth (2026-10-18).

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
4. A recursive grep (deny). On 2026-10-22 `/usr/bin/grep -rl` walked `~/src` and `~/ops`
   for 38 minutes at one core while the machine was swapping. BSD `grep` and `ggrep` both
   walk every file; content search is `rg -n -l PAT PATH` with a real scope (setup-modern-cli).
   A filename uses `plocate -i NAME` when `/opt/homebrew/var/lib/plocate/plocate.db` is fresh
   enough (nightly 03:30). `ggrep` stays for one file that needs a GNU flag. A pipe or a
   single file with no `-r`/`-R` passes.
5. `sudo -n` without `-k` (warning only). A cached ticket (sudoers.d/10-timestamp-global makes
   it machine-wide) lets `sudo -n` run anything, so it proves nothing about a NOPASSWD rule:
   on 2026-10-18 a "narrow rule" check passed for a command the rule never allowed.
   `sudo -k -n CMD` ignores the cache without clearing it (man sudo, -k with a command).
6. Bare `open` (deny, 2026-11-02). macOS `open` hands the caller's whole environment to the app
   it starts: an agent's `open -a` left CLAUDE_CODE_CHILD_SESSION in Quicksilver, then Ghostty and
   every shell in it. The command word `open` or `/usr/bin/open` (any pipeline segment, past
   VAR=x, `env`, `sudo`, `xargs`, `timeout`) is denied and bin/open-clean is named. `env -i ...
   open` and `open-clean` pass; so do `xdg-open`, `opencode`, `open` as an argument or in quotes.

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
# Long xargs options that take a separate operand (GNU; macOS xargs is BSD but agents
# often write GNU forms). Equals-attached forms (`--max-args=1`) are one word already.
XARGS_LONG_ARG = frozenset({
    "--max-args", "--max-chars", "--max-procs", "--arg-file", "--delimiter",
    "--replace", "--eof",
})
# Recursive grep/ggrep (2026-10-22). A leading -H/-L/-P on find is unrelated and is left alone.
TREE_GREP = frozenset({"grep", "ggrep", "egrep", "fgrep", "gegrep", "gfgrep"})
TREE_GREP_REASON = (
    "A recursive grep walks every file. Scope it, or use `rg -n -l PAT PATH` "
    "(always a path; site-djbclark skill setup-modern-cli). A filename uses "
    "`plocate -i NAME` when `/opt/homebrew/var/lib/plocate/plocate.db` is fresh enough "
    "(nightly 03:30; it does not search contents). `ggrep` is for one file that needs a "
    "GNU flag. On 2026-10-22 `grep -rl` over `~/src` and `~/ops` ran 38 min at one core."
)


def tree_grep(tool: str, args: list[str]) -> bool:
    """True when grep/ggrep is asked to walk a tree. A pipe or one file is not one."""
    if os.path.basename(tool) not in TREE_GREP:
        return False
    for a in option_words(args):
        if a in ("--recursive", "--dereference-recursive"):
            return True
        if len(a) > 1 and a.startswith("-") and not a.startswith("--") and re.search(r"[rR]", a[1:]):
            return True
    return False


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


def command_views(plain: str) -> list[str]:
    """The command line as separate commands: the outer one with each `$(...)`, `<(...)` and
    `>(...)` replaced by a placeholder word, then the body of every substitution (nested ones
    included, each replaced in its parent the same way).

    `gh api x $(echo $r | cut -d/ -f1):master --jq .y` must not give `cut` the text after the `)`
    (2026-11-02: that made the gate deny `cut --jq`), and `cut -d$(printf , | cut -c1) --complement`
    must still give the outer `cut` its `--complement`, so each command is checked on its own
    text. A bare `(` group, a regex group (`=~ ^(awk|sed)$`) and an extended glob (`@(awk|sed)`)
    stay inline: they are argument text, not a command. An arithmetic expansion `$((...))` runs
    no command, so its expression is dropped (`echo $((sed + 1))`, `$((1<(sed)))`), except for
    the backtick and `$(` substitutions inside it, which do run. `$((a); b)` is a substitution
    around a subshell, not arithmetic: bash reads `$((` as arithmetic only when its closing `)`
    is directly followed by another `)`. A backslash-escaped character is filename or argument
    content (`find . -name foo\\)`, `\\$(`), never a delimiter. An unclosed substitution is
    still checked, as its own view."""
    views: list[str] = []
    # open groups: (kind, text collected so far); kind is "sub" (`$(`, `<(`, `>(`), "arith"
    # (`$((`) or "group" (a bare `(`); the bottom entry is the outer command
    stack: list[tuple[str, list[str]]] = [("group", [])]
    i = 0
    while i < len(plain):
        ch = plain[i]
        if ch == "\\":
            stack[-1][1].append(plain[i:i + 2])
            i += 2
        elif plain.startswith("$((", i):
            stack.append(("arith", []))
            i += 3
        elif ch == "$" and plain[i + 1:i + 2] == "(":
            stack.append(("sub", []))
            i += 2
        elif ch in "<>" and plain[i + 1:i + 2] == "(" and not any(k == "arith" for k, _ in stack):
            stack.append(("sub", []))  # a process substitution; inside arithmetic `<(` compares
            i += 2
        elif ch == "(":
            stack.append(("group", []))
            i += 1
        elif ch == ")" and len(stack) > 1:
            kind, body = stack.pop()
            text = "".join(body)
            if kind == "sub":
                views.append(text)
                stack[-1][1].append("X")
            elif kind == "arith" and plain[i + 1:i + 2] != ")":
                # `$((a); b)`: a subshell inside a substitution; the `(` was a group all along
                stack.append(("sub", ["(" + text + ")"]))
            elif kind == "arith":
                views.extend(_backtick_bodies(text))
                stack[-1][1].append("X")
                i += 1  # the closing `))`
            else:
                stack[-1][1].append("(" + text + ")")
            i += 1
        else:
            stack[-1][1].append(ch)
            i += 1
    while len(stack) > 1:  # unclosed: a substitution is its own command, a bare `(` stays inline
        kind, body = stack.pop()
        text = "".join(body)
        if kind == "sub":
            views.append(text)
        elif kind == "arith":
            views.extend(_backtick_bodies(text))
        else:
            stack[-1][1].append("(" + text)
    return ["".join(stack[0][1])] + views


def _backtick_bodies(text: str) -> list[str]:
    """Backtick command bodies, including escaped nested substitutions inside arithmetic.

    A backslash protects a backtick from closing the current pair. Bash removes
    that escape when executing its body, where the nested pair becomes active.
    Use a worklist rather than recursion for arbitrarily nested input.
    """
    bodies: list[str] = []
    pending = [text]
    while pending:
        source = pending.pop()
        body: list[str] | None = None
        i = 0
        while i < len(source):
            ch = source[i]
            if ch == "\\" and i + 1 < len(source):
                nxt = source[i + 1]
                if body is not None:
                    # Backtick substitution removes escapes only for these chars.
                    body.append(nxt if nxt in "\\$`" else ch + nxt)
                i += 2
                continue
            if ch == "`":
                if body is None:
                    body = []
                else:
                    command = "".join(body)
                    bodies.append(command)
                    pending.append(command)
                    body = None
            elif body is not None:
                body.append(ch)
            i += 1
    return bodies


def words(stage: str) -> list[str]:
    """A stage's words; `$(`, backticks and `(`/`{` start a command, so they split too."""
    return [w for w in re.split(r"\s+|\$\(|`|\(|\{", stage) if w]


def _skip_xargs_opts(w: list[str]) -> list[str]:
    """Drop xargs option words (and their operands) so the command is not mistaken for a flag value.

    Codex P2 on #522: `xargs -n 1 open` must not leave `1` as the command word (that would
    miss a bare `open` and let the agent environment leak into the launched app).
    """
    while w:
        a = w[0]
        if a == "--":
            return w[1:]
        if not a.startswith("-") or a == "-":
            break
        if a in XARGS_ARG or a in XARGS_LONG_ARG:
            w = w[2:] if len(w) > 1 else []
            continue
        # Combined short opts that end in a takes-arg letter (`-n1` is one word; `-n` alone
        # is handled above). `--max-args=1` is also one word.
        w = w[1:]
    return w


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
            if head == "xargs":
                w = _skip_xargs_opts(w)
            else:
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


OPEN_REASON = ("Launch apps and URLs with `~/src/djbclark-ade/bin/open-clean`, not bare `open`: "
               "macOS `open` hands your whole environment to the app it starts. On 2026-11-02 an "
               "agent's `open -a` left CLAUDE_CODE_CHILD_SESSION and CLAUDE_CODE_SESSION_ID in "
               "Quicksilver, then in Ghostty and every shell in it, so each `claude` there lost "
               "its transcript and relay took those shells for the agent. `open-clean` takes the "
               "same arguments and runs `/usr/bin/open` with HOME, USER, LOGNAME, a fixed PATH, "
               "LANG/LC_* and TMPDIR only. `env -i HOME=\"$HOME\" /usr/bin/open ...` also passes.")


def bare_open(stage: str) -> bool:
    """True when the stage's command word is `open` or `/usr/bin/open` (past VAR=x, wrappers,
    sudo/xargs/timeout) and nothing scrubs the environment first: `env -i`, `env -` or
    `env --ignore-environment` before it make it a clean launch. `xdg-open`, `opencode` and
    `open` as an argument never match: only the command word does."""
    w = words(stage)
    scrubbed = False
    while w:
        head = w[0]
        if head == "env":
            w = w[1:]
            while w and w[0].startswith("-") and w[0] != "--":
                if w[0] in ("-i", "-", "--ignore-environment") or (
                        not w[0].startswith("--") and "i" in w[0][1:]):
                    scrubbed = True
                w = w[2:] if w[0] in ("-u", "-C", "-S", "-P") else w[1:]
        elif re.fullmatch(r"\w+=\S*", head) or head in WRAPPERS:
            w = w[1:]
        elif head in ("sudo", "xargs", "timeout", "gtimeout"):
            w = w[1:]
            if head == "xargs":
                w = _skip_xargs_opts(w)
            else:
                while w and w[0].startswith("-"):
                    w = w[1:]
            if head.endswith("timeout") and w:
                w = w[1:]
        else:
            return head in ("open", "/usr/bin/open") and not scrubbed
    return False


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


def unterminated_heredoc_reason(cmd: str) -> str | None:
    """An unterminated heredoc: bash writes the PARTIAL body and still exits 0.

    Probed on this Mac 2026-10-24: `cat > f <<'EOF'` with no `EOF` line creates `f` holding
    everything up to the end of input, prints only a *warning* on stderr
    (`here-document at line N delimited by end-of-file`), and exits **0**. So a message, brief or
    file written this way is silently truncated and the caller sees success — which is exactly what
    happened to a sibling handoff message on 2026-10-24 (a long peer_mail body arrived cut off
    mid-sentence, 632 bytes of a 3178-byte message, and nothing reported an error).

    Deliberately NOT a `strip_literals` check: that function skips the body to avoid false
    positives from words inside it, so it cannot see the missing terminator. This scans the RAW
    command for each heredoc introducer and requires a matching delimiter line after it.

    Quoted and unquoted introducers both count (`<<'EOF'`, `<<"EOF"`, `<<EOF`, `<<-EOF`); an
    escaped `<<` is a literal and does not introduce one. Fails open: any oddity that makes the
    scan uncertain returns None rather than denying a legitimate command.
    """
    lines = cmd.split("\n")
    i = 0
    while i < len(lines):
        # An introducer INSIDE a quoted string is not a heredoc (`rg -n '<<EOF' file` must pass).
        # Do not blank quoted runs: the delimiter of `<<'EOF'` is itself quoted, so blanking would
        # hide the very introducer being sought. Instead compute the quoted spans and skip a match
        # whose start falls inside one.
        quoted: list[tuple[int, int]] = []
        for q in re.finditer(r"'[^']*'|\"[^\"]*\"", lines[i]):
            quoted.append((q.start(), q.end()))
        for m in re.finditer(r"(?<!\\)<<(-?)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2", lines[i]):
            if any(a <= m.start() < b for a, b in quoted):
                continue  # this `<<` is inside a string, not an introducer
            delim = m.group(3)
            strip_tabs = m.group(1) == "-"
            j = i + 1
            found = False
            while j < len(lines):
                line = lines[j].lstrip("\t") if strip_tabs else lines[j]
                if line.strip() == delim:
                    found = True
                    break
                j += 1
            if not found:
                return (f"Unterminated heredoc: `<<{m.group(1)}{m.group(2)}{delim}{m.group(2)}` "
                        f"on line {i + 1} has no `{delim}` line after it. bash does NOT fail on "
                        f"this — it writes the PARTIAL body, warns on stderr and exits 0, so the "
                        f"file is silently truncated (2026-10-24: a peer message arrived cut off "
                        f"mid-sentence). Close the heredoc, or write the text to a file and pass "
                        f"the path (`--file`/`-f`) instead of inlining a long body.")
            i = j  # continue after the delimiter
        i += 1
    return None


def check(cmd: str) -> tuple[str | None, str | None]:
    """(deny reason, warning) for a Bash command line."""
    # Raw-command check first: strip_literals skips heredoc bodies, so this cannot live in the
    # per-stage loop below (it must see the body to notice a missing terminator).
    hd = unterminated_heredoc_reason(cmd)
    if hd:
        return hd, None
    plain = strip_literals(cmd)
    warn = None
    for view in command_views(plain):
        # control operators split pipelines; the pipe splits stages
        for pipeline in re.split(r"&&|\|\||;|\n|&", view):
            for stage in re.split(r"\|&?", pipeline):
                if command_word(stage)[0] == "sed":
                    return ("Use `gsed`, not bare `sed`: this Mac's `sed` is BSD sed and GNU flags "
                            "differ (2026-10-15: a BSD `sed -i` broke an edit). To read lines use "
                            "the Read tool or `gsed -n A,Bp`; a deliberate BSD call writes "
                            "`/usr/bin/sed`."), None
                tool, args = command_word(stage)
                if tree_grep(tool, args):
                    return TREE_GREP_REASON, None
                if bare_open(stage):
                    return OPEN_REASON, None
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
    # the pipe-status check reads the whole command, substitutions and all, as it always did
    # (2026-11-02, Codex review of PR 254: no exemption and no trimming here)
    # control operators split pipelines; keep each operator to know what reads the status
    parts = re.split(r"(&&|\|\||;|\n|&)", plain)
    pipelines = [(parts[i], parts[i + 1] if i + 1 < len(parts) else "")
                 for i in range(0, len(parts), 2)]
    if re.search(r"pipefail|PIPESTATUS", plain):
        return None, warn
    for n, (pipeline, op) in enumerate(pipelines):
        stages = re.split(r"\|&?", pipeline)
        if len(stages) < 2:
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
    if reason:
        reason = ("NOTHING in this command ran; no earlier part executed. "
                  "Fix the command and re-run the whole command. " + reason)
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
