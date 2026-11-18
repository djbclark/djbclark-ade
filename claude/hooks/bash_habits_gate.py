#!/usr/bin/env python3
"""PreToolUse (Bash): deny six shell mistakes that recur, and warn on two more (2026-10-18).

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

7. `gh run watch` / `gh pr checks --watch` (deny, 2026-11-14) and a parallel `gh` fan-out
   (warning). Every agent shares one GitHub token with a 5000/h API quota (REST and GraphQL are counted separately); four `gh run watch`
   at gh's default 3 s interval emptied it from 10:22Z to 11:22Z and stopped every agent's gh
   work (docs/dispatch-footer.md item 20 says "never wait on CI" and did not stop it). The
   command word `gh` (past VAR=x, wrappers, `timeout N`, `bg`, `rtk`, `do`/`then`, and the body
   of `bash -c '...'`) with `run watch`, or `pr checks` plus `--watch`, is denied unless
   it carries `--interval`/`-i` of 60 or more (quota-safe: about 2-3 calls a minute; the lead's
   documented CI wait). `xargs -P N` / `parallel` around `gh` calls only warns.

8. An unquoted word that starts with `=` (deny, 2026-11-14). zsh (this Mac's Bash-tool shell) expands `=cmd` to the
   path of `cmd` and fails with `zsh: == not found` when there is none, and that error aborts the rest of a `;`
   chain: `echo ===; next` printed an error and never ran `next` (memory feedback_zsh_triple_equals_separator.md
   did not stop it). Probed: `echo ===`, `echo ==`, `echo =b`, `echo ="x"`, `echo ==$e`, `[ a == a ]`, `test a == a` and a
   `case` pattern `=*)` all fail; `echo =` passes, and so do `=(cmd)` (process substitution), `a=b`, `--x=y`, `\\===`,
   `[[ a == a ]]`, `(( 1 == 1 ))` and `$((1==1))`. Quoted words, heredoc bodies and comments do not count. The reason says
   to quote the word (`'==='`) or use `---`.
9. `paseo send` / `paseo agent send` with a double-quoted argument that holds a backtick or `$(`
   (deny, 2026-11-14). The shell runs that text before paseo sees the message: a worker's `"... the `foo` call ..."`
   ran `foo`, and the message arrived with a hole in it. Single quotes, `--prompt-file FILE` and python argv do not. An
   escaped `\\`` or `\\$(` and arithmetic `$((n*2))` are literal text and pass. A deliberate `"$(cat FILE)"` is denied too
   (assign it first: `ID=$(cat f); paseo send "$ID" ...`).

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


def _blank_quotes(s: str) -> str:
    """Blank quoted strings in one left-to-right scan: an apostrophe inside "..." is text (two
    regexes paired it with the next real `'` and hid every command between them), a backslash
    escapes the next character (and inside `$'...'`), and a comment is dropped. An unterminated
    quote stays as one character and the scan goes on after it, so the text after it is still
    checked (it fails toward denying, as the old regexes did)."""
    out, i, n = [], 0, len(s)
    while i < n:
        ch = s[i]
        if ch == "\\":
            out.append(s[i:i + 2])
            i += 2
        elif ch == "#" and (i == 0 or s[i - 1].isspace() or s[i - 1] in ";&|("):
            j = s.find("\n", i)
            i = n if j < 0 else j
        elif ch == "'":
            j = i + 1
            if out and out[-1] == "$":               # $'...': a backslash escapes the next character
                while j < n and s[j] != "'":
                    j += 2 if s[j] == "\\" else 1
            else:
                k = s.find("'", j)
                j = n if k < 0 else k
            if j >= n:
                out.append("'")
                i += 1
            else:
                out.append("''")
                i = j + 1
        elif ch == '"':
            j = i + 1
            while j < n and s[j] != '"':
                j += 2 if s[j] == "\\" else 1
            if j >= n:
                out.append('"')
                i += 1
            else:
                out.append(f'"{RC}"' if "$?" in s[i:j] else '""')
                i = j + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _heredoc_terminates(line: str, delimiter: str, strip_tabs: bool) -> bool:
    """A delimiter is exact; only <<- removes leading tab characters."""
    return (line.lstrip("\t") if strip_tabs else line) == delimiter


def _heredoc_introducers(line: str, state):
    """Recognize unescaped shell redirects, not quoted/comment delimiter examples."""
    quote, arithmetic = state or (None, 0)
    matches, i = [], 0
    while i < len(line):
        ch = line[i]
        if quote is not None:
            if ch == "\\" and quote != "'":
                i += 2
                continue
            if ch == quote[-1]:
                quote = None
        elif ch == "\\":
            i += 2
            continue
        elif ch == "#" and (i == 0 or line[i - 1].isspace() or line[i - 1] in ";&|("):
            break
        elif ch in "'\"":
            quote = "$'" if ch == "'" and i > 0 and line[i - 1] == "$" else ch
        elif arithmetic:
            arithmetic += (ch == "(") - (ch == ")")
        elif line.startswith("((", i):
            arithmetic = 2
            i += 2
            continue
        elif ch == "<" and (i == 0 or line[i - 1] != "<") and not line.startswith("<<<", i):
            match = re.match(r"<<(-?)\s*(['\"]?)(\w+)\2", line[i:])
            if match:
                matches.append(match)
                i += match.end()
                continue
        i += 1
    return matches, (quote, arithmetic)


def strip_literals(c: str) -> str:
    """Drop heredoc bodies, quoted strings and comments; a quoted `$?` leaves a marker."""
    out, lines, i, quote = [], c.split("\n"), 0, None
    while i < len(lines):
        out.append(lines[i])
        matches, quote = _heredoc_introducers(lines[i], quote)
        for m in matches:
            i += 1
            while i < len(lines) and not _heredoc_terminates(lines[i], m.group(3), m.group(1) == "-"):
                i += 1
        i += 1
    s = "\n".join(out)
    s = _blank_quotes(s)
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


GH_CANDIDATES = 4        # words named gh tried as the command word (see gh_args)
GH_WATCH_MIN_INTERVAL = 60  # seconds; None would make every watcher a denial
# Words that only introduce the next command (or wrap it with options of their own).
SHELL_KW = frozenset({"do", "then", "else", "elif", "if", "while", "until"})
EXTRA_WRAP = frozenset({"rtk", "bg", "setsid", "caffeinate", "stdbuf", "ionice", "chronic",
                        "unbuffer"})
GH_WATCH_REASON = (
    "Never watch CI with `{what}` (docs/dispatch-footer.md item 20: never wait on CI). Every "
    "agent shares one GitHub token with a 5000/h API quota (REST and GraphQL are counted "
    "separately); on 2026-11-14 four `gh run watch` "
    "at gh's default 3 s interval emptied it from 10:22Z to 11:22Z and blocked every agent's gh "
    "work, and a watcher also keeps you busy and deaf to the lead's messages. Instead: report "
    "\"CI running\" with the run URL and end the turn; or one-shot `gh run view RUN --json "
    "status,conclusion`; or a background loop that sleeps 60 s or more between one-shot checks. "
    "The lead's single watcher passes with `--interval 60` (or more)."
)
GH_FANOUT_WARNING = (
    "Parallel `gh` calls (`xargs -P` / `parallel`) draw on the one 5000/h API quota every agent "
    "shares (2026-11-14: it hit 0 for an hour). A script making more than ~200 GitHub API calls "
    "first reads `gh api rate_limit`, paces itself, stops at remaining < 500 and batches with "
    "GraphQL (docs/dispatch-footer.md item 26)."
)
GH_FANOUT_CMD = re.compile(r"\bgh\s+(?:(?:-R|--repo)\s+\S+\s+)?"
                           r"(?:api|pr|run|issue|repo|search|release|workflow)\b")
SHELL_C = re.compile(
    r"""(?:^|[;&|(\n{]|\$\()[ \t]*(?:[\w=./{}%-]+[ \t]+){0,4}(?P<sh>(?:[\w./-]*/)?(?:ba|z|da)?sh)\s+"""
    r"""(?:-{1,2}[A-Za-z0-9][\w-]*(?:\s+\w+)?\s+)*?-[A-Za-z]*c\s+('[^']*'|"(?:[^"\\]|\\.)*")""")
SHELL_HEREDOC = re.compile(
    r"""(?:^|[;&|(]|&&)[ \t]*(?:[\w=./-]+[ \t]+){0,3}(?:[\w./-]*/)?(?:ba|z|da)?sh\b[^<\n]*<<-?\s*"""
    r"""['"]?(\w+)['"]?""")
SHELL_PIPED_HEREDOC = re.compile(
    r"""<<-?\s*['"]?(\w+)['"]?[^\n]*\|\s*(?:[\w./-]*/)?(?:ba|z|da)?sh\b""")
# `""`/`''` is what strip_literals leaves of a quoted `"VAR=$X"` after env/sudo (a quoted assignment is still an assignment);
# an unquoted `VAR=x` between or before them is skipped too (`env -i A=1 "B=$X" gh ...`: lw-01, #694 review C1)
_PLACEHOLDERS = r"(?:(?:\"\"|''|\w+=\S*)\s+)*"
ENV_OPTS = re.compile(r"(?<![\w./-])env\s+(?:(?:-[A-Za-z]*[uCSP]|--(?:unset|chdir|split-string))\s+\S+\s+|-\S+\s+)*"
                      + _PLACEHOLDERS)
NICE_OPTS = re.compile(r"(?<![\w./-])nice\s+(?:-n\s+\S+\s+|--adjustment\s+\S+\s+|-\S+\s+)*")
SUDO_OPTS = re.compile(r"(?<![\w./-])sudo\s+(?:(?:-[A-Za-z]*[ugphCDRTU]|--(?:user|group|host|prompt|chdir|chroot|role|type))"
                       r"\s+\S+\s+|-\S+\s+)*" + _PLACEHOLDERS)
COMMAND_OPTS = re.compile(r"(?<![\w./-])(?:command|builtin)\s+(?:-\S+\s+)*")
EXEC_OPTS = re.compile(r"(?<![\w./-])exec\s+(?:-a\s+\S+\s+|-\S+\s+)*")
REDIRECT_WORD = re.compile(r"\d*(?:>>?|<<?<?|&>>?|>&|<&)")
QUOTED_NUMBER = re.compile(r"""(?<=[\s=])(['"])([0-9]{1,9})\1""")


def quoted_spans(text: str) -> list[tuple[int, int, str]]:
    """(start, end, opener) of each single- or double-quoted span, left to right: a backslash
    escapes the next character outside single quotes, and a `#` at a word start is a comment."""
    spans, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
            i += 2
        elif ch == "#" and (i == 0 or text[i - 1].isspace() or text[i - 1] in ";&|("):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif ch in "'\"":
            j = i + 1
            while j < n and text[j] != ch:
                j += 2 if (ch == '"' and text[j] == "\\") else 1
            spans.append((i, min(j + 1, n), ch))
            i = j + 1
        else:
            i += 1
    return spans


def _in_prose(text: str, spans: list[tuple[int, int, str]], pos: int) -> bool:
    """True when `pos` sits in quoted text that is not run: a double-quoted span holding a
    `$(` or backtick substitution before `pos` does run it."""
    for a, b, q in spans:
        if a <= pos < b:
            seg = re.sub(r"\\.", "", text[a:pos])          # escaped `\`` and `\$(` are text
            seg = re.sub(r"\$\([^()]*\)|`[^`]*`", "", seg)  # a closed substitution already ran
            return not (q == '"' and re.search(r"\$\(|`", seg))
    return False


def _closing_paren(text: str, i: int) -> int:
    """Index of the `)` that closes a `$(` whose body starts at `i`, or len(text) if unclosed."""
    depth, j, n = 1, i, len(text)
    arithmetic = text[i:i + 1] == "("
    pending = []
    while j < n:
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "'":
            k = text.find("'", j + 1)
            j = n if k < 0 else k + 1
            continue
        if c == '"':
            j += 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            j += 1
            continue
        if c == "$" and text[j + 1:j + 2] == "(":
            j = _closing_paren(text, j + 2) + 1
            continue
        if not arithmetic and c == "<" and (j == 0 or text[j - 1] != "<") and not text.startswith("<<<", j):
            match = re.match(r"<<(-?)\s*(['\"]?)(\w+)\2", text[j:])
            if match:
                pending.append((match.group(3), match.group(1) == "-"))
                j += match.end()
                continue
        if c == "\n" and pending:
            j += 1
            for delimiter, strip_tabs in pending:
                while j < n:
                    end = text.find("\n", j)
                    end = n if end < 0 else end
                    line, j = text[j:end], end + 1
                    if _heredoc_terminates(line, delimiter, strip_tabs):
                        break
                else:
                    return n
            pending.clear()
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return n


def live_bodies(text: str) -> list[str]:
    """Bodies of the `$(...)` and backtick substitutions bash runs: in double quotes and out of
    them, not in single quotes, comments or after a backslash. `strip_literals` blanks a double-quoted
    string whole, so command_views never sees a substitution there, and it does not split backticks."""
    out: list[str] = []
    i, n, dq = 0, len(text), False
    while i < n:
        ch = text[i]
        if ch == "\\":
            i += 2
        elif not dq and ch == "'":
            k = text.find("'", i + 1)
            i = n if k < 0 else k + 1
        elif not dq and ch == "#" and (i == 0 or text[i - 1].isspace() or text[i - 1] in ";&|("):
            k = text.find("\n", i)
            i = n if k < 0 else k
        elif ch == '"':
            dq = not dq
            i += 1
        elif ch == "`":
            j, body = i + 1, []
            while j < n and text[j] != "`":
                if text[j] == "\\" and j + 1 < n and text[j + 1] in "\\$`":
                    j += 1
                body.append(text[j])
                j += 1
            out.append("".join(body))
            i = j + 1
        elif ch == "$" and text[i + 1:i + 2] == "(":
            end = _closing_paren(text, i + 2)
            if text.startswith("$((", i):
                # Arithmetic operators are not shell redirections. Only nested
                # command substitutions/backticks inside the expression execute.
                out.extend(live_bodies(text[i + 3:max(i + 3, end - 1)]))
            else:
                out.append(text[i + 2:end])
            i = end + 1                               # its inside is scanned fresh, by the recursion
        else:
            i += 1
    return out


def _join_continuations(c: str) -> str:
    """Join backslash-newline pairs (an odd run of backslashes), outside heredoc bodies."""
    out, lines, i = [], c.split("\n"), 0
    pending: list[str] = []
    while i < len(lines):
        if i + 1 < len(lines) and re.search(r"(?<!\\)(?:\\\\)*\\$", lines[i]):
            pending.append(lines[i][:-1])
            i += 1
            continue
        line = "".join(pending) + lines[i]
        pending = []
        out.append(line)
        m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", line)
        if m:                                         # copy the body untouched, delimiter included
            i += 1
            while i < len(lines) and lines[i].strip() != m.group(1):
                out.append(lines[i])
                i += 1
            if i < len(lines):
                out.append(lines[i])
        i += 1
    if pending:
        out.append("".join(pending))
    return "\n".join(out)


def _drop_heredocs(c: str) -> str:
    """The command without heredoc bodies (their text is data, not commands)."""
    out, lines, i = [], c.split("\n"), 0
    while i < len(lines):
        out.append(lines[i])
        m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", lines[i])
        if m:
            i += 1
            while i < len(lines) and lines[i].strip() != m.group(1):
                i += 1
        i += 1
    return "\n".join(out)


def _drop_redirections(stage: str) -> list[str]:
    """The stage's words without redirections (`gh>log run watch 9` is `gh run watch 9`; `2>&1`, `>f`, `> f`)."""
    w = re.sub(r"(?<=[A-Za-z])(?=[<>])", " ", stage).split()
    out, i = [], 0
    while i < len(w):
        x = w[i]
        if REDIRECT_WORD.fullmatch(x):
            i += 2                                  # the operator and its target
            continue
        if not REDIRECT_WORD.match(x):
            out.append(x)
        i += 1
    return out


def gh_args(stage: str) -> list[list[str]]:
    """The words after `gh` when the stage runs it (past VAR=x, wrappers, `timeout N`, `bg`,
    `rtk`, `do`/`then`), else []. One entry per reading: a wrapper option's value may itself be
    named `gh` (`sudo -u gh gh run watch`), so each of the first GH_CANDIDATES words named `gh`
    or `gh-pr-checks` is tried as the command word and the caller denies when any reading is a watcher."""
    # `sudo -u USER gh`, `env -i VAR=x gh`, `nice -n 10 gh`: only the words before the candidate
    # (an argument such as `-R o/env` or a branch named `env` must not be read as a wrapper)
    w = _drop_redirections(stage)
    stage = " ".join(w)
    cands = [n for n, x in enumerate(w) if os.path.basename(x) in ("gh", "gh-pr-checks")]
    out: list[list[str]] = []
    for k in cands[:GH_CANDIDATES] or [0]:
        st = stage
        if k:
            pre = " ".join(w[:k]) + " "
            pre = SUDO_OPTS.sub("sudo ", pre)
            pre = EXEC_OPTS.sub("exec ", COMMAND_OPTS.sub("command ", pre))
            pre = ENV_OPTS.sub("env ", NICE_OPTS.sub("nice ", pre))
            st = pre + " ".join(w[k:])
        out += _gh_args_one(st)
    return out


def _gh_args_one(stage: str) -> list[list[str]]:
    for _ in range(8):
        head, rest = command_word(stage)
        base = os.path.basename(head)
        if base == "deadline" and "--" in rest:       # `deadline run ... -- gh ...`
            stage = " ".join(rest[rest.index("--") + 1:])      # inner words were normalised by gh_args
            continue
        if base == "gh-pr-checks":                    # bin/gh-pr-checks forwards to `gh pr checks`
            fwd, k = [], 0
            while k < len(rest):
                if rest[k] == "--":                   # everything after goes to gh as is
                    fwd += rest[k + 1:]
                    break
                if rest[k] == "--budget":
                    k += 1
                elif rest[k] != "--no-deadline" and not rest[k].startswith("--budget="):
                    fwd.append(rest[k])
                k += 1
            return [["pr", "checks"] + fwd]
        if base in SHELL_KW or base in EXTRA_WRAP:
            while base in EXTRA_WRAP and rest and rest[0].startswith("-"):
                rest = rest[1:]
            if base == "rtk" and rest and rest[0] == "proxy":   # `rtk proxy CMD` runs CMD unfiltered
                rest = rest[1:]
            stage = " ".join(rest)
            continue
        return [rest] if base == "gh" else []
    return []


def gh_watch(args: list[str]) -> str | None:
    """The command text when `gh ARGS` is `run watch` or `pr checks --watch` without a
    `--interval` of GH_WATCH_MIN_INTERVAL or more, else None."""
    pos: list[str] = []
    i = 0
    while i < len(args) and len(pos) < 2:
        a = args[i]
        if a == "--":
            return None
        if a in ("-R", "--repo"):
            i += 1
        elif not a.startswith("-"):
            pos.append(a)
        i += 1
    rest = args[i:]
    if "--" in rest:
        rest = rest[:rest.index("--")]
    if pos == ["run", "watch"]:
        what = "gh run watch"
    elif pos == ["pr", "checks"] and any(
            a == "--watch" or (a.startswith("--watch=") and a[8:].lower() not in
                               ("false", "f", "0")) for a in rest):
        what = "gh pr checks --watch"
    else:
        return None
    interval = None
    j = 0
    while j < len(rest):
        a = rest[j]
        val = None
        if a in ("-i", "--interval"):
            val = rest[j + 1] if j + 1 < len(rest) else ""
            j += 1
        elif a.startswith("--interval="):
            val = a[11:]
        elif a.startswith("-i") and not a.startswith("--"):
            val = a[2:].lstrip("=")
        if val is not None:
            interval = val
        j += 1
    if GH_WATCH_MIN_INTERVAL is not None and interval is not None and \
            re.fullmatch(r"[1-9][0-9]{0,8}", interval) and \
            int(interval) >= GH_WATCH_MIN_INTERVAL:
        return None
    return GH_WATCH_REASON.format(what=what)


def gh_watch_in(text: str, depth: int = 0) -> str | None:
    """A gh-watch denial for any stage of `text`, looking inside `bash -c '...'` bodies and
    heredocs fed to a shell."""
    orig = QUOTED_NUMBER.sub(r"\2", text)           # `--interval "60"` is 60
    # a backslash-newline joins lines (an odd run of backslashes only), but not inside a heredoc body
    text = _join_continuations(orig)
    plain = strip_literals(text)
    for view in command_views(plain):
        for pipeline in re.split(r"&&|\|\||;|\n|&", view):
            for stage in re.split(r"\|&?", pipeline):
                for args in gh_args(stage):
                    reason = gh_watch(args)
                    if reason:
                        return reason
    raw = _drop_heredocs(text)
    if depth < 4:
        for body in live_bodies(raw):
            reason = gh_watch_in(body, depth + 1)
            if reason:
                return reason
    if depth < 3:
        spans = quoted_spans(raw)
        for m in SHELL_C.finditer(raw):
            if _in_prose(raw, spans, m.start("sh")):
                continue                              # `sh -c` written inside a quoted string
            reason = gh_watch_in(m.group(2)[1:-1], depth + 1)
            if reason:
                return reason
        lines = text.split("\n")                    # joined lines; heredoc bodies untouched
        n = 0
        while n < len(lines):
            fed = (SHELL_HEREDOC.search(lines[n]) or SHELL_PIPED_HEREDOC.search(lines[n])) \
                if "<<" in lines[n] else None
            m = fed or (re.search(r"<<-?\s*['\"]?(\w+)['\"]?", lines[n]) if "<<" in lines[n] else None)
            n += 1
            if not m:
                continue
            body = []                                 # a heredoc not fed to a shell is data
            while n < len(lines) and lines[n].strip() != m.group(1):
                body.append(lines[n])
                n += 1
            n += 1
            reason = gh_watch_in("\n".join(body), depth + 1) if fed else None
            if reason:
                return reason
    return None


def xargs_parallel(xa: list[str]) -> bool:
    """True when xargs options ask for more than one process (`-P 0` is unlimited)."""
    i = 0
    while i < len(xa):
        a = xa[i]
        if a == "--" or not a.startswith("-") or a == "-":
            break
        val = None
        if a in ("-P", "--max-procs"):
            val = xa[i + 1] if i + 1 < len(xa) else None
        elif a.startswith("--max-procs="):
            val = a[12:]
        elif a.startswith("-P") and not a.startswith("--"):
            val = a[2:]
        if val is not None and val != "1":
            return True
        i += 2 if a in XARGS_ARG or a in XARGS_LONG_ARG else 1
    return False


def gnu_reason(tool: str, flag: str, via_xargs: bool = False) -> str:
    where = f"xargs {tool}" if via_xargs else tool
    g = "gxargs" if tool == "xargs" else f"g{tool}"
    return (f"`{tool} {flag}` is GNU-only and this Mac's `{tool}` is BSD: it fails with a usage "
            f"error, and whatever follows `;` or `&&` still runs (2026-10-18: `chmod --reference` "
            f"failed, the `mv -f` after it ran, and a live hook lost its execute bit). Use "
            f"`{('xargs ' if via_xargs else '') + g}` (brew; `{g} {flag}`), or drop the option. "
            f"A deliberate BSD call writes `/bin/{tool}` or `/usr/bin/{tool}`.")


ZSH_EQUALS_REASON = (
    "`{word}` starts with `=`: zsh (this Mac's Bash-tool shell) expands an unquoted `=name` to the path of command `name`, "
    "and when there is none `zsh: {rest} not found` aborts the rest of a `;` chain (2026-11-14: `echo ===; next` never ran `next`). "
    "Quote the word (`'==='`) or use `---` as a separator. `[[ a == b ]]`, `(( a == b ))`, `a=b` and `=(cmd)` are fine; "
    "`[ a == b ]` is not (write `[ a = b ]` or `[[ a == b ]]`).")


def drop_test_blocks(view: str) -> str:
    """`view` with each `[[ ... ]]` and `(( ... ))` (parentheses matched by depth) replaced by a blank. One pass: an opener
    with no closer ends the search for that kind (a second one cannot find a closer either), so `"[[ " * N` is linear."""
    out: list[str] = []
    i, n = 0, len(view)
    no_br = no_pr = False
    while i < n:
        two = view[i:i + 2]
        if two == "[[" and not no_br:
            k = view.find("]]", i + 2)
            if k >= 0:
                out.append(" ")
                i = k + 2
                continue
            no_br = True
        elif two == "((" and not no_pr:
            depth, j = 2, i + 2
            while j < n and depth:
                depth += (view[j] == "(") - (view[j] == ")")
                j += 1
            if depth == 0:
                out.append(" ")
                i = j
                continue
            no_pr = True
        out.append(view[i])
        i += 1
    return "".join(out)


def zsh_equals_word(view: str) -> str | None:
    """The first word of `view` (already through strip_literals) that zsh would expand as `=name`: it starts with `=`
    and is longer than `=` (a lone `=` is plain; `=(` is process substitution). `[[ ]]` and `(( ))` tests are dropped first."""
    for pipeline in re.split(r"&&|\|\||;|\n|&|\|", drop_test_blocks(view)):
        for w in pipeline.split():
            if w.startswith("=") and len(w) > 1 and w[1] != "(":
                return w
    return None


def _skip_dollar_paren(s: str, j: int) -> int:
    """Index just past the `)` that closes the `$(` whose `(` is at s[j - 1]; len(s) when it never closes."""
    depth, n = 1, len(s)
    while j < n and depth:
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c in "'\"":
            k = s.find(c, j + 1)
            while c == '"' and k > 0 and s[k - 1] == "\\":
                k = s.find(c, k + 1)
            j = n if k < 0 else k + 1
            continue
        depth += (c == "(") - (c == ")")
        j += 1
    return j


def _brace_word_end(raw: str, i: int) -> bool:
    """True when the `{` or `}` at raw[i] is a whole word (the reserved word of a group), not part of a word such as the
    `{}` placeholder of `paseo send --json {} "..."` or a brace expansion `{a,b}`."""
    return raw[i + 1:i + 2] in ("", " ", "\t", "\n", ";", "&", "|", ")")


def simple_commands(raw: str, bodies: list[str] | None = None) -> list[list[tuple[str, bool]]]:
    """`raw` split into simple commands; each is a list of (word, risky). `risky` is True for a word with an unescaped
    backtick or `$(` inside double quotes: the shell runs it before the program starts. Heredoc bodies are dropped by the
    caller. An unterminated quote makes the structure unclear: [] (fail open). The text of every `$(...)`, `<(...)`,
    `>(...)` and backtick span (quoted or not) is appended to `bodies`: it is a command line of its own."""
    cmds: list[list[tuple[str, bool]]] = []
    words_: list[tuple[str, bool]] = []
    cur: list[str] = []
    risky = False
    i, n = 0, len(raw)

    def end_word() -> None:
        nonlocal cur, risky
        if cur or risky:
            words_.append(("".join(cur), risky))
        cur, risky = [], False

    def end_cmd() -> None:
        nonlocal words_
        end_word()
        if words_:
            cmds.append(words_)
        words_ = []

    while i < n:
        c = raw[i]
        if c == "\\":
            if raw[i + 1:i + 2] != "\n":
                cur.append(raw[i + 1:i + 2])
            i += 2
        elif c == "'":
            k = raw.find("'", i + 1)
            if k < 0:
                return []
            cur.append(raw[i + 1:k])
            i = k + 1
        elif c == '"':
            j = i + 1
            while j < n and raw[j] != '"':
                if raw[j] == "\\":
                    j += 2
                elif raw[j] == "`":
                    risky = True
                    k = raw.find("`", j + 1)
                    if bodies is not None:
                        bodies.append(raw[j + 1:n if k < 0 else k])
                    j = n if k < 0 else k + 1
                elif raw.startswith("$((", j):          # arithmetic runs no command, unless it holds a substitution
                    k = _skip_dollar_paren(raw, j + 2)
                    risky = risky or "$(" in raw[j + 3:k] or "`" in raw[j + 3:k]
                    j = k
                elif raw.startswith("$(", j):
                    risky = True
                    k = _skip_dollar_paren(raw, j + 2)
                    if bodies is not None:
                        bodies.append(raw[j + 2:k - 1 if raw[k - 1:k] == ")" else k])
                    j = k
                else:
                    j += 1
            if j >= n:
                return []
            cur.append(raw[i + 1:j])
            i = j + 1
        elif c == "#" and not cur and not risky:
            k = raw.find("\n", i)
            i = n if k < 0 else k
        elif c in " \t":
            end_word()
            i += 1
        elif (c == "$" or c in "<>") and raw[i + 1:i + 2] == "(" and not raw.startswith("$((", i):
            k = _skip_dollar_paren(raw, i + 2)            # `$(...)`, `<(...)`, `>(...)`: a command line of its own
            if bodies is not None:
                bodies.append(raw[i + 2:k - 1 if raw[k - 1:k] == ")" else k])
            cur.append(raw[i:k])
            i = k
        elif c == "$" and raw[i + 1:i + 2] in ("(", "{"):
            # an unquoted `$(...)` / `${...}` is part of the word (`paseo send $(cat id) "msg"`): its parentheses and braces
            # must not end the command
            k = _skip_dollar_paren(raw, i + 2) if raw[i + 1] == "(" else raw.find("}", i + 2)
            k = len(raw) if k < 0 else (k if raw[i + 1] == "(" else k + 1)
            cur.append(raw[i:k])
            i = k
        elif c == "`":
            k = raw.find("`", i + 1)
            if bodies is not None:
                bodies.append(raw[i + 1:len(raw) if k < 0 else k])
            k = len(raw) if k < 0 else k + 1
            cur.append(raw[i:k])
            i = k
        elif c in ";&|\n" or (c in "()" and not cur) or (c in "{}" and not cur and _brace_word_end(raw, i)):
            end_cmd()
            i += 1
        else:
            cur.append(c)
            i += 1
    end_cmd()
    return cmds


NOT_A_SENDER = frozenset({"echo", "printf", "print", "rg", "grep", "git", "cat", "gh", "jq"})
# commands that run another command given after their own options (the `paseo` may follow option values: `env -u X paseo`)
SEND_WRAPPERS = frozenset({
    "env", "sudo", "timeout", "gtimeout", "bg", "nice", "rtk", "command", "builtin", "exec", "time", "nohup", "deadline",
    "stdbuf", "ionice", "taskpolicy", "caffeinate", "xargs", "parallel", "run", "--", "noglob", "nocorrect", "coproc",
    "flock", "watch", "script", "direnv", "secretspec", "sudo-secretspec", "op", "ssh", "doas", "genv", "gnohup", "gstdbuf",
    "gnice", "unbuffer", "chronic", "mosh", "uv",     # `ssh host paseo send "`x`"`: the LOCAL shell runs it
    "if", "then", "do", "else", "elif", "while", "until", "!", "case",
})


def risky_send_reason(cmd: str) -> str | None:
    """A denial reason when a `paseo [agent] send` command carries a double-quoted argument with a backtick or `$(` (the
    shell would run it, not send it)."""
    if "send" not in cmd:
        return None
    todo, seen = [_drop_heredocs(cmd)], 0
    while todo and seen < 200:                       # a worklist: a substitution body is a command line too
        seen += 1
        bodies: list[str] = []
        parsed = simple_commands(todo.pop(), bodies)
        todo.extend(b for b in bodies if "send" in b)
        reason = _send_in(parsed)
        if reason:
            return reason
    return None


def _send_in(parsed: list[list[tuple[str, bool]]]) -> str | None:
    for words_ in parsed:
        names = [os.path.basename(w) for w, _ in words_]
        lead = 0                                        # leading `VAR=x` assignments are not the command word
        while lead < len(names) - 1 and re.match(r"[A-Za-z_][A-Za-z0-9_]*=", words_[lead][0]):
            lead += 1
        if names[lead].startswith("{") and len(names[lead]) > 1:
            names[lead] = names[lead][1:]               # `{paseo send ...;}` (no space): zsh reads `{paseo` as the command word
        if names[lead] in NOT_A_SENDER:                 # `echo paseo send "$(date)"` only prints text
            continue
        # `paseo` is the command word, or comes after a wrapper (`env -u X`, `timeout 600`, `bg`): a `paseo` that is data
        # for another command (`ls paseo send "$(date)"`) is not a send
        wrapped = names[lead] in SEND_WRAPPERS or names[lead].endswith(")")      # `x) paseo send ...`: a case-arm pattern
        start = None
        for k, name in enumerate(names):
            if k > lead and not wrapped:
                break
            if name == "paseo":
                rest = names[k + 1:]
                while rest and rest[0].startswith("-"):        # a global option before the verb
                    rest = rest[1:]
                if rest[:1] == ["agent"]:
                    rest = rest[1:]
                if rest[:1] == ["send"]:
                    start = k
                    break
        if start is None:
            continue
        for w, bad in words_[start + 1:]:
            if bad:
                return ("A double-quoted argument of this `paseo send` holds a backtick or `$(`: the shell "
                        "runs it BEFORE paseo starts, so the message arrives with a hole in it and the command may "
                        "run (2026-11-14: a worker's quoted `identifier` ran as a command). Pass the text through "
                        "python argv (`subprocess.run([\"paseo\", \"send\", ..., text])`), or write it with "
                        "`cat > FILE <<'EOF'` and send `paseo send ID --prompt-file FILE`, or use single quotes; drop the "
                        "backticks from prose. A target id taken from a command: `ID=$(cat f); paseo send \"$ID\" ...`.")
    return None


def deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))
    sys.exit(0)


def unterminated_heredoc_reason(cmd: str, depth: int = 0) -> str | None:
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
    if depth > 16:
        return None
    lines = cmd.split("\n")
    headers = []
    i, quote = 0, None
    while i < len(lines):
        headers.append(lines[i])
        # An introducer INSIDE a quoted string is not a heredoc (`rg -n '<<EOF' file` must pass).
        # Do not blank quoted runs: the delimiter of `<<'EOF'` is itself quoted, so blanking would
        # hide the very introducer being sought. Instead compute the quoted spans and skip a match
        # whose start falls inside one.
        matches, quote = _heredoc_introducers(lines[i], quote)
        introduced_at = i + 1
        for m in matches:
            delim = m.group(3)
            strip_tabs = m.group(1) == "-"
            j = i + 1
            found = False
            while j < len(lines):
                if _heredoc_terminates(lines[j], delim, strip_tabs):
                    found = True
                    break
                j += 1
            if not found:
                return (f"Unterminated heredoc: `<<{m.group(1)}{m.group(2)}{delim}{m.group(2)}` "
                        f"on line {introduced_at} has no `{delim}` line after it. bash does NOT fail on "
                        f"this — it writes the PARTIAL body, warns on stderr and exits 0, so the "
                        f"file is silently truncated (2026-10-24: a peer message arrived cut off "
                        f"mid-sentence). Close the heredoc, or write the text to a file and pass "
                        f"the path (`--file`/`-f`) instead of inlining a long body.")
            headers.append(lines[j])  # preserve the verified terminator for substitution scans
            i = j  # continue after the delimiter
        i += 1
    # Double quotes still execute substitutions. Inspect their shell bodies afresh,
    # after removing actual outer heredoc data, which may contain literal examples.
    for body in live_bodies("\n".join(headers)):
        reason = unterminated_heredoc_reason(body, depth + 1)
        if reason:
            return reason
    return None


BG_REASON = (
    "A job-control `&` (`cmd &`, also `nohup cmd &`, `setsid cmd &`, `( cmd & )`) leaves an orphaned, "
    "untracked process (ppid 1) that notifies nobody when it exits (2026-11-15: a `python3 wait_check.py "
    "> out 2>&1 &` was orphaned). Do not background inside the command: set the Bash tool's "
    "`run_in_background: true` parameter instead; it tracks the job and notifies on exit. Set the call's "
    "`timeout` to the run's need, at most 7200000 (2 h): the default 30 min stops the job. Longer jobs: "
    "CI (~/CLAUDE.md item 37), a `bin/ade-sched` one-shot or a Paseo terminal. Parallel work that ends "
    "with `wait` in the same command (`a & b & wait`) is allowed. A sub-agent that is not woken by the "
    "exit notice waits with `bin/wait-file` on its log. Nothing ran.")


def bg_operator(plain: str) -> bool:
    """True when `strip_literals` output holds a lone `&` control operator (a background job).

    Quotes, heredoc bodies, comments and the redirections `2>&1`, `>&2`, `&>`, `&>>`, `<&3`, `|&`
    are already gone from `plain`. Also dropped here: backslash-escaped characters, `${...}`
    (`${x//&/y}`), arithmetic `((...))` (bitwise `&`) and `&&`."""
    s = re.sub(r"\\.", "", plain, flags=re.S)
    s = re.sub(r"\$?\(\([^)]*\)\)", " ", s)
    s = re.sub(r"\$\{[^}]*\}", " ", s)
    s = s.replace(";;&", ";;").replace(";&", ";").replace("&&", "  ")   # case-arm terminators, AND
    if "&" not in s:
        return False
    # bounded fan-out: every `&` is followed later in the same command by a `wait` builtin
    tail = s[s.rindex("&") + 1:]
    return not re.search(r"(?:^|[;&|(){\n]|\b(?:do|then)\b)\s*wait(?=$|[\s;&|)}])", tail)


def check(cmd: str) -> tuple[str | None, str | None]:
    """(deny reason, warning) for a Bash command line."""
    # Raw-command check first: strip_literals skips heredoc bodies, so this cannot live in the
    # per-stage loop below (it must see the body to notice a missing terminator).
    hd = unterminated_heredoc_reason(cmd)
    if hd:
        return hd, None
    gh = gh_watch_in(cmd)
    if gh:
        return gh, None
    send = risky_send_reason(cmd)
    if send:
        return send, None
    plain = strip_literals(cmd)
    warn = None
    fanout = False
    for view in command_views(plain):
        eq = zsh_equals_word(view)
        if eq:
            return ZSH_EQUALS_REASON.format(word=eq, rest=eq[1:]), None
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
                if xargs_parallel(xa) or command_word(stage)[0] in ("parallel", "gparallel"):
                    fanout = True
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
    if bg_operator(plain):          # after the per-stage checks: their specific reasons win
        return BG_REASON, None
    if fanout and GH_FANOUT_CMD.search(_drop_heredocs(cmd)):
        warn = (warn + " " if warn else "") + GH_FANOUT_WARNING
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
