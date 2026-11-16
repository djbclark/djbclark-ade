#!/usr/bin/env python3
"""archived_send_gate: PreToolUse hook, a message to an archived or replaced agent is denied, never delivered (ls-02).

Paseo un-archives and runs an archived agent that is sent a message (2026-11-14: the ex-lead 994234ba came back running and
could act as a stale lead). This hook checks the target of a Bash `paseo send` / `paseo agent send` and of the MCP tool
`send_agent_prompt` with `bin/ade_send_guard.py` (which reads `ade-self-session`'s completed-handoff records, #669):

  replaced by a completed handoff (or an acknowledged one still finishing, rq-38)   deny, naming the successor (a hook cannot safely rewrite the target; re-send to it)
  archived, nothing replaced it     deny; `ADE_ALLOW_ARCHIVED_SEND=<its full id> paseo send ...` resumes it on purpose
  replaced but still live           `ADE_ALLOW_REPLACED_SEND=<its full id> paseo send ...` sends to it anyway (logged)
  live, unknown to Paseo, anything this hook cannot parse or reach   allow silently (fails open)

Only the target is judged, never the message. A target built by the shell (`$VAR`, a substitution, a glob) is not parsed.
Block form: stdout JSON permissionDecision "deny" and exit 0 (same as upstream_review_gate). Other TUIs without hooks rely on
`bin/ade_send_guard.py` (called by the in-repo senders) and AGENTS.md. Design and limits: docs/archived-send-guard.md.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import sys

BIN = Path(__file__).resolve().parent.parent.parent / "bin"
VALUE_FLAGS = {"--prompt", "--prompt-file", "--image", "--behavior", "-o", "--format"}  # the value options of `paseo send`; Paseo's
# program options (-o/--format, --json, -q, --no-headers, --no-color, --host, --home) are accepted before AND after the verb, and `agent`
# takes them before its own `send` too (adversary r1 on #696)
OTHER_DAEMON = {"--host", "--home"}  # an explicit daemon selector: not judged (it may name the local daemon or another; the ledger is not consulted)
SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "\n"}
MCP_ID_KEYS = ("agentId", "agent_id", "id", "target")
ALLOW_VAR = "ADE_ALLOW_ARCHIVED_SEND"
REPLACED_VAR = "ADE_ALLOW_REPLACED_SEND"
SHELL_BUILT = "$`*?[{~"  # a target containing one of these is built by the shell: judge() skips it


def deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                              "permissionDecisionReason": reason}}))


HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
NO_RUN = {"echo", "printf", "grep", "rg"}  # words after these are text, not a command; their `-e`/`-c` flags take text too: `echo -e "old: paseo send A"`. Read by `_one` and by `_mask`


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
    """The command as one logical line per simple command, without shell comments, and with command substitutions turned into
    separators. A `#` that starts a word outside quotes runs to the end of its line; a `#` inside a word (a URL fragment, or
    glued to the end of a `$(...)`/backtick) or a quote is text. `\\`+newline is a line continuation (removed outside quotes and
    inside double quotes, as the shell does). A newline outside quotes becomes ` ; ` (a command separator); inside quotes it
    stays. `$(` and a backtick start a command outside quotes and inside double quotes, where the quote is closed around the
    body and reopened after it (`"a $(b) c"` -> `"a " ; b ; " c"`); inside single quotes they are text (a markdown `code span`
    in a message is not a command). (shlex's own comment handling cuts at any `#`, so it is switched off.)"""
    out, quote, i, n = [], None, 0, len(text)
    word_start = True  # the last thing emitted ended a word (blank, separator, newline), so a `#` here starts a comment
    # open substitutions and groups: "p" a bare `(`; "s" a `$(` outside quotes; "a" each `(` of `$((`; "u" a backtick outside quotes; "d" a `$(` and "b" a
    # backtick opened inside double quotes (the quote is reopened when they close)
    stack: list[str] = []
    while i < n:
        c = text[i]
        if quote == "'":
            out.append(c)
            if c == "'":
                quote, word_start = None, False
        elif quote == '"':
            if c == "\\" and i + 1 < n:
                i += 1
                if text[i] != "\n":  # a continuation vanishes; any other escaped pair stays
                    out.append(c + text[i])
            elif (c == "$" and text.startswith("$(", i) and not text.startswith("$((", i)) or c == "`":
                out.append('" ; ')  # close the quote around the substitution body
                stack.append("b" if c == "`" else "d")
                quote, word_start = None, True
                i += c == "$"  # skip the `(`
            else:
                out.append(c)
                if c == '"':
                    quote, word_start = None, False
        elif c == "\\" and i + 1 < n:
            i += 1
            if text[i] != "\n":  # a continuation leaves word_start as it was
                out.append(c + text[i])
                word_start = False  # an escaped blank or separator is text: `echo a\ #x` has no comment
        elif c in "'\"":
            quote = c
            out.append(c)
        elif c == "#" and word_start:
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif c == "\n":
            out.append(" ; ")
            word_start = True
        elif c == "`":
            if stack and stack[-1] == "b":  # the end of a backtick body that began inside double quotes: reopen the quote
                stack.pop()
                out.append(' ; "')
                quote, word_start = '"', False
            elif stack and stack[-1] == "u":  # the end of a backtick body outside quotes: the next `#` is glued to its word
                stack.pop()
                out.append(" ; ")
                word_start = False
            else:
                stack.append("u")
                out.append(" ; ")
                word_start = True
        elif c == "$" and text.startswith("$(", i) and not text.startswith("$((", i):
            out.append(" ; ")
            stack.append("s")
            word_start = True
            i += 1
        elif c == "$" and text.startswith("$((", i):  # arithmetic: `$((1+2))#x` is one word
            out.append("$((")
            stack += ["a", "a"]
            word_start = False
            i += 2
        elif c == "(":
            stack.append("p")
            out.append(c)
            word_start = True
        elif c == ")":
            top = stack.pop() if stack else "p"
            if top == "d":  # the `)` that ends a `$(` begun inside double quotes: reopen the quote
                out.append(' ; "')
                quote, word_start = '"', False
            else:
                out.append(c)
                word_start = top not in ("s", "a")  # after `$(...)` or `$((...))` a `#` is part of the same word; after `( )` it starts a comment
        else:
            out.append(c)
            word_start = c in " \t;&|()"
        i += 1
    return "".join(out)


RUNNERS = {"eval", "watch", "su", "fish", "script", "parallel", "ssh", "at", "tmux", "osascript", "awk", "gawk", "mawk"}  # words that run a string argument (awk: `system("...")`)
RUN_FLAG = re.compile(r"-[A-Za-z]*[ce][A-Za-z]*|--command(=.*)?|--run(=.*)?")  # `-c`, `-lc`, `-e`, `--run=`: the next word is a command string
# A shell in the (already masked) text may read a script from stdin: `| sh`, `bash <<<`, `| $SHELL`, `source <(...)`. No `\S*/` prefix:
# the lookbehind already matches after a `/`, and the prefix made the scan quadratic on a long blob without blanks.
SHELL_WORD = re.compile(r"(?<![\w.-])(?:" + "|".join(sorted(SHELLS)) + r")(?![\w.-])|\$\{?SHELL\b\}?|(?<![\w.-])(?:source|\.)\s+<\(")
SHELL_BODY = re.compile(r"(?:\S*/)?(?:" + "|".join(sorted(SHELLS)) + r")")  # a quoted shell name: `| "sh"`, `| '/bin/bash'`
IDS_ONLY = re.compile(r"\s*(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\s*)+")


ANSI_ESCAPE = re.compile(r"\\(?:(?P<bs>\\)|(?P<name>[ntrvf])|x(?P<x>[0-9A-Fa-f]{1,2})|u(?P<u>[0-9A-Fa-f]{1,4})|U(?P<U>[0-9A-Fa-f]{1,8})"
                         r"|(?P<o>[0-7]{1,3})|c(?P<c>[\x00-\x7f]))", re.S)  # `\c` + a non-ASCII character is no escape bash turns into a blank
BLANKS = " \t\n\r\v\f"  # what splits a word list in a shell (not every character `str.isspace` knows)


def ansi_blanks(body: str) -> str:
    """`body` of a `$'...'` with each escape that bash turns into a blank (`\\n`, `\\t`, `\\x0a`, `\\u000a`, `\\012`, `\\cJ`, ...) replaced by
    a space; `\\\\` stays a backslash, so `\\\\n` is no blank."""
    def blank(m: re.Match) -> str:
        g = m.groupdict()
        if g["bs"]:
            return m.group(0)
        if g["name"]:
            return " "
        if g["c"]:  # `\\cJ`: a control character
            code = ord(g["c"]) & 0x1F  # no .upper(): `ß`.upper() is two characters; `j` and `J` give the same low five bits
        elif g["o"]:
            code = int(g["o"], 8) % 256  # bash keeps the low 8 bits of an octal escape
        else:
            code = int(g["x"] or g["u"] or g["U"], 16)
        return " " if code < 0x110000 and chr(code) in BLANKS else m.group(0)
    return ANSI_ESCAPE.sub(blank, body)


def _mask(text: str) -> str:
    out, word = [], []
    first, runner = "", False  # the first word of this simple command; has a runner word or flag come before the string?
    quoted_word = False  # the word being read holds a quote or an escape: never a runner name (and `'a''b''c'...` stays linear)
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in "'\"" or (c == "$" and text.startswith("$'", i)):
            start, ansi = i, c == "$"
            i += ansi
            q, j = text[i], i + 1
            while j < n and text[j] != q:
                j += 2 if text[j] == "\\" and (q == '"' or ansi) else 1
            if j >= n:
                return text
            body = text[i + 1:j]
            ids_body = ansi_blanks(body) if ansi else body  # a backslash-n, `\\x0a` or `\\012` in `$'...'` is a blank
            cur = "" if quoted_word else "".join(word)
            runs = ((runner or Path(cur).name in RUNNERS or RUN_FLAG.fullmatch(cur) is not None)
                    and Path(first or cur).name not in NO_RUN)
            keep = (runs or SHELL_BODY.fullmatch(body) is not None  # `| "sh"` is still a shell reading stdin
                    or IDS_ONLY.fullmatch(ids_body) is not None  # a quoted id or list of ids (also `$'A<backslash>nB'`)
                    or (q == '"' and (("$(" in body or "`" in body)  # a real substitution
                                      or ("$" in body and not re.search(r"\s", body)))))  # `"${LEAD:-<id>}"`, `"$SHELL"`
            out.append(("$'" + ids_body + "'" if ansi and ids_body != body and IDS_ONLY.fullmatch(ids_body) else text[start:j + 1]) if keep else "''")
            word.append("Q")
            quoted_word = True
            i = j + 1
        elif c == "\\" and i + 1 < n:
            out.append(text[i:i + 2])
            word.append("Q")
            quoted_word = True
            i += 2
        else:
            if c.isspace() or c in ";&|()":
                if word:
                    w = "".join(word)
                    first = first or w
                    runner = runner or Path(w).name in RUNNERS or RUN_FLAG.fullmatch(w) is not None
                    word.clear()
                quoted_word = False
                if c in ";&|()":
                    first, runner = "", False
            else:
                word.append(c)
            out.append(c)
            i += 1
    return "".join(out)


def mask_literals(text: str) -> str:
    """`text` (already through strip_comments) with each quoted string that is message text blanked to `''`. A string stays when
    it is a quoted id or list of ids, a `"${VAR:-id}"` expansion, a `$(` or backtick body, or the argument of a word that runs a
    string (`eval`, `watch`, `-c`, `--run=`: `eval 'paseo send A hi'` is a send). When a shell word is left outside quotes
    (`echo '...' | sh`, `bash <<< '...'`) every string may be a script, so nothing is masked; a shell word inside message text
    does not count. An unbalanced quote means the structure is unclear: nothing is masked. `$'...'` is read with its escapes."""
    masked = _mask(text)
    return text if SHELL_WORD.search(masked) else masked


class Hit(tuple):
    """`(target, allow)`, the pair every caller unpacks, with the ADE_ALLOW_REPLACED_SEND value riding along as `.replaced`
    (an attribute, so a Hit still compares equal to its two-element tuple)."""
    replaced: str | None

    def __new__(cls, target: str, allow: str | None, replaced: str | None = None):
        self = super().__new__(cls, (target, allow))
        self.replaced = replaced
        return self


def targets_in_command(command: str, depth: int = 0) -> list[tuple[str, str | None]]:
    """[(target, allow)] for every `paseo [agent] send` found in a shell command line. `allow` is the value of an
    ADE_ALLOW_ARCHIVED_SEND=... assignment seen before it (the agent id the operator allowed), else None; the value of an
    ADE_ALLOW_REPLACED_SEND=... assignment is the hit's `.replaced`."""
    text = strip_comments(strip_heredocs(command))
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
        kind, j = locate_send(words[i + 1:])
        if kind == "other":
            return found
        if kind != "send":
            continue
        target = words[i + 1 + j] if j is not None else None
        if target:  # an override counts only as an assignment before the command, never as a word of the message
            allow = next((x.split("=", 1)[1] for x in words[:i] if x.startswith(ALLOW_VAR + "=")), None)
            replaced = next((x.split("=", 1)[1] for x in words[:i] if x.startswith(REPLACED_VAR + "=")), None)
            found.append(Hit(target, allow, replaced))
        break
    return found


def _takes_value(word: str) -> bool:
    """`-o` or a short-option cluster that ends in it (`-qo`): the next word is its value. `-ojson` carries its value."""
    return re.fullmatch(r"-[A-Za-z]*o", word) is not None


def _daemon_option(word: str) -> bool:
    return word in OTHER_DAEMON or word.startswith(("--host=", "--home="))


REDIRECT = re.compile(r"&?[<>]+[&|]?")  # `>`, `>>`, `<<<`, `>&`, `&>`, `>|`: the lexer splits them from their operand


def _after_redirect(args: list[str], j: int, shell: bool = True) -> int | None:
    """Index after the redirect that starts at `args[j]` (an optional one or two digit fd number, the operator and its operand: the
    operand is a file or text, never an option or the agent); None when none starts there. `shell=False`: `args` is a real argv (the
    shell has removed its redirects), so `>` and `2` are plain words."""
    if not shell:
        return None
    k = j + 1 if re.fullmatch(r"\d{1,2}", args[j]) and j + 1 < len(args) and REDIRECT.fullmatch(args[j + 1]) else j  # `2>x`: the lexer leaves the fd number behind
    return k + 2 if REDIRECT.fullmatch(args[k]) else None


def _scan(args: list[str], shell: bool = True) -> tuple[int | None, bool]:
    """(index of the agent word, whether a daemon selector was seen) in the arguments after `send`. Value options are skipped with
    their values; the first word after `--` is the agent when none came before it and the rest is message text. The whole option
    list is read, so `send A --host X` is seen too (an option word after the agent is still an option to Paseo)."""
    target, j = None, 0
    while j < len(args):
        a = args[j]
        after = _after_redirect(args, j, shell)  # `paseo send A >--home=x.log`, `xargs paseo send <<< "A B"`, `paseo send 2>x A`
        if after is not None:
            j = after
            continue
        if _daemon_option(a):
            return None, True
        if a == "--":
            k = j + 1  # the shell still takes redirects after `--` (`paseo send -- 2>x A`): the first word that is none is the agent
            while target is None and k < len(args):
                after = _after_redirect(args, k, shell)
                if after is None:
                    target = k
                k = k + 1 if after is None else after
            break
        if a in VALUE_FLAGS or _takes_value(a):
            j += 2
        else:
            if (not a.startswith("-") or a == "-") and target is None:  # a lone `-` is an operand for Commander
                target = j
            j += 1
    return target, False


def _target_index(args: list[str]) -> int | None:
    """Where the agent word of `paseo send` arguments is; None when a daemon selector is present or nothing is found."""
    target, other = _scan(args)
    return None if other else target


def locate_send(args: list[str], shell: bool = True) -> tuple[str, int | None]:
    """Classify the arguments that follow the word `paseo`: ("send", index of the agent word or None), ("other", None) for an
    explicit daemon selector, ("none", None) for anything else. Global options may stand before `agent`, between `agent` and
    `send`, and after `send`: `paseo -o json send A`, `paseo agent --json send A`, `paseo agent -q send A`."""
    i, agent = 0, False
    while i < len(args):
        a = args[i]
        if _daemon_option(a):
            return "other", None
        if a == "send":
            break
        if a == "agent" and not agent:
            agent = True
            i += 1
        elif a.startswith("-"):
            i += 2 if (_takes_value(a) or a == "--format") else 1
        else:
            return "none", None
    else:
        return "none", None
    j, other = _scan(args[i + 1:], shell)
    if other:
        return "other", None
    return "send", None if j is None else i + 1 + j


def _target(args: list[str]) -> str | None:
    """The agent word of `paseo send` arguments (see `_target_index`), or None."""
    j = _target_index(args)
    return args[j] if j is not None else None


SEND_WORD = re.compile(r"\bpaseo\b(?:\s+[^\s;&|]+){0,4}?\s+send\b")
UUID = re.compile(r"(?<!/)\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")


def backstop_targets(command: str, found: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
    """The parser cannot follow every shell form (a lone trailing backslash, an ANSI-C quote, a target the shell builds, a string
    run by `eval` or `watch`). When the command text (heredoc bodies and quoted message text aside) names more `paseo ... send`
    than the parser found judgeable targets for, every full agent id written in the command (not one right after a `/`, a path component such as `agent-reports/<id>/`) is judged too (at most 5): a false
    denial needs an archived agent's id in a command that mentions `paseo send` outside quotes, a missed send needs a form
    nobody listed."""
    if "paseo" not in command:
        return []
    text = strip_heredocs(command)
    judged = [t for t, _ in found if t and not any(c in t for c in SHELL_BUILT)]  # `$LEAD`, `{}`, `$id` are never judged
    bare = mask_literals(strip_comments(text))  # a `paseo send` or an id inside a quoted message (a `code span`) is text
    if len(SEND_WORD.findall(bare)) <= len(judged):
        return []
    seen = {t for t, _ in found}
    out: list[tuple[str, str | None]] = []
    for u in dict.fromkeys(UUID.findall(bare)):
        if u not in seen and len(out) < 5:
            out.append(Hit(u, u if f"{ALLOW_VAR}={u}" in text else None))  # never ADE_ALLOW_REPLACED_SEND: this is text of a form the parser could not follow (adversary L3)
    return out


def judge(target: str, allow: str | None, backstop: bool = False, replaced: str | None = None) -> str | None:
    """A denial reason, or None to allow. `backstop`: the id was only found written in a command the parser could not follow,
    so the reason says that (the command may already send to the successor, and `Re-send to X` would loop)."""
    if not target or any(c in target for c in SHELL_BUILT):
        return None
    sys.path.insert(0, str(BIN))
    import ade_send_guard as guard  # noqa: PLC0415 - lazy: any import problem must fail open
    env = {k: v for k, v in ((guard.ALLOW_ENV, allow), (guard.ALLOW_REPLACED_ENV, replaced)) if v}
    d = guard.guard(target, env=env, source="hook-precheck")
    if d.action not in (guard.REDIRECT, guard.REFUSE):
        return None
    me = (os.environ.get("PASEO_AGENT_ID") or "").strip()
    if backstop and d.action == guard.REDIRECT and d.target == me:
        return (f"Blocked by archived_send_gate: this command writes the id {target}, which {d.reason}; that is you, so nothing "
                f"is to be sent (a message to oneself queues a spurious turn). Only the operator messages the replaced agent "
                f"({guard.ALLOW_REPLACED_ENV}=<its full id> while it is live).")
    if backstop:
        return (f"Blocked by archived_send_gate: this command mentions `paseo send` in a form the hook could not parse and "
                f"writes the id {target}, which is not a live agent ({d.reason}). If no send to {target} is meant, leave its "
                f"id out of the command or split the command; if one is, send to " +
                (f"{d.target}." if d.action == guard.REDIRECT else "a live agent (it would un-archive and run it)."))
    if d.action == guard.REDIRECT and d.target == me:
        return (f"Blocked by archived_send_gate: {d.reason}. {d.target} is you: nothing was sent (a message to oneself queues a "
                f"spurious turn). Only the operator messages the replaced agent ({guard.ALLOW_REPLACED_ENV}=<its full id> while it is live).")
    if d.action == guard.REDIRECT:
        return (f"Blocked by archived_send_gate: {d.reason}. Re-send to {d.target} (a send to the replaced agent would "
                f"un-archive and run it as a stale lead).")
    return f"Blocked by archived_send_gate: {d.reason}."


def main() -> int:
    try:
        event = json.load(sys.stdin)
        tool, tin = event.get("tool_name", ""), event.get("tool_input") or {}
        found: list[tuple[str, str | None]] = []
        extra: list[tuple[str, str | None]] = []  # ids the backstop picked out of text the parser could not follow
        if tool == "Bash" and isinstance(tin.get("command"), str):
            found = targets_in_command(tin["command"])
            try:
                extra = backstop_targets(tin["command"], found)
            except Exception as exc:  # noqa: BLE001 - a backstop bug must not un-judge a send the parser found
                print(f"archived_send_gate: backstop {type(exc).__name__}: {exc}", file=sys.stderr)
        elif tool.startswith("mcp__") and tool.endswith("send_agent_prompt"):
            ident = next((tin[k] for k in MCP_ID_KEYS if isinstance(tin.get(k), str)), "")
            found = [(ident, None)] if ident else []  # another host's agent id is unknown here: decide() passes it
        for hit, back in [(h, False) for h in found] + [(h, True) for h in extra]:
            reason = judge(hit[0], hit[1], back, getattr(hit, "replaced", None))
            if reason:
                deny(reason)
                return 0
    except Exception as exc:  # noqa: BLE001 - a guard must never block on its own bug
        print(f"archived_send_gate: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
