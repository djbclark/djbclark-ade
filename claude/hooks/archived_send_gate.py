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
SHELL_BUILT = "$`*?[{~"  # a target containing one of these is built by the shell: judge() skips it


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


RUNNERS = {"eval", "watch", "su", "fish", "script", "parallel", "ssh", "at", "tmux", "osascript"}  # words that run a string argument
RUN_FLAG = re.compile(r"-[A-Za-z]*[ce][A-Za-z]*|--command|--run(=.*)?")  # `-c`, `-lc`, `-e`, `--run`: the next word is a command string
SHELL_WORD = re.compile(r"(?<![\w.-])(?:\S*/)?(?:" + "|".join(sorted(SHELLS)) + r")(?![\w.-])")  # a shell anywhere may read a string from stdin


def mask_literals(text: str) -> str:
    """`text` (already through strip_comments) with each quoted string that is message text blanked to `''`. A string stays when
    it is a lone id (a quoted id), contains a `$(` or backtick (a real substitution), or follows a word that runs a
    string (`eval`, `watch`, `-c`, `--run`: `eval 'paseo send A hi'` is a send), or the command names a shell anywhere. An unbalanced quote means the structure is
    unclear: nothing is masked. `$'...'` is read with its backslash escapes."""
    out, words, word = [], [], []
    i, n = 0, len(text)
    shell_anywhere = bool(SHELL_WORD.search(text))  # `echo 'paseo send A' | sh`, `bash <<< '...'`: any string may be a script
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
            runs = any(Path(w).name in RUNNERS or RUN_FLAG.fullmatch(w) for w in words + ["".join(word)])
            keep = (runs or shell_anywhere or UUID.fullmatch(body) is not None
                    or (q == '"' and ("$(" in body or "`" in body)))  # a lone quoted id is a target, not message text
            out.append(text[start:j + 1] if keep else "''")
            word.append("Q")
            i = j + 1
        elif c == "\\" and i + 1 < n:
            out.append(text[i:i + 2])
            word.append("Q")
            i += 2
        else:
            if c.isspace() or c in ";&|()":
                if word:
                    words.append("".join(word))
                    word.clear()
                if c in ";&|()":
                    words.clear()
            else:
                word.append(c)
            out.append(c)
            i += 1
    return "".join(out)


def targets_in_command(command: str, depth: int = 0) -> list[tuple[str, str | None]]:
    """[(target, allow)] for every `paseo [agent] send` found in a shell command line. `allow` is the value of an
    ADE_ALLOW_ARCHIVED_SEND=... assignment seen before it (the agent id the operator allowed), else None."""
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


SEND_WORD = re.compile(r"\bpaseo\b(?:\s+[^\s;&|]+){0,4}?\s+send\b")
UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")


def backstop_targets(command: str, found: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
    """The parser cannot follow every shell form (a lone trailing backslash, an ANSI-C quote, a target the shell builds, a string
    run by `eval` or `watch`). When the command text (heredoc bodies and quoted message text aside) names more `paseo ... send`
    than the parser found judgeable targets for, every full agent id written in the command is judged too (at most 5): a false
    denial needs an archived agent's id in a command that mentions `paseo send` outside quotes, a missed send needs a form
    nobody listed."""
    text = strip_heredocs(command)
    judged = [t for t, _ in found if t and not any(c in t for c in SHELL_BUILT)]  # `$LEAD`, `{}`, `$id` are never judged
    bare = mask_literals(strip_comments(text))  # a `paseo send` or an id inside a quoted message (a `code span`) is text
    if len(SEND_WORD.findall(bare)) <= len(judged):
        return []
    seen = {t for t, _ in found}
    out: list[tuple[str, str | None]] = []
    for u in dict.fromkeys(UUID.findall(bare)):
        if u not in seen and len(out) < 5:
            out.append((u, u if f"{ALLOW_VAR}={u}" in text else None))
    return out


def judge(target: str, allow: str | None, backstop: bool = False) -> str | None:
    """A denial reason, or None to allow. `backstop`: the id was only found written in a command the parser could not follow,
    so the reason says that (the command may already send to the successor, and `Re-send to X` would loop)."""
    if not target or any(c in target for c in SHELL_BUILT):
        return None
    sys.path.insert(0, str(BIN))
    import ade_send_guard as guard  # noqa: PLC0415 - lazy: any import problem must fail open
    env = {guard.ALLOW_ENV: allow} if allow else {}
    d = guard.guard(target, env=env)
    if d.action not in (guard.REDIRECT, guard.REFUSE):
        return None
    if backstop:
        return (f"Blocked by archived_send_gate: this command mentions `paseo send` in a form the hook could not parse and "
                f"writes the id {target}, which is not a live agent ({d.reason}). If no send to {target} is meant, leave its "
                f"id out of the command or split the command; if one is, send to " +
                (f"{d.target}." if d.action == guard.REDIRECT else "a live agent (it would un-archive and run it)."))
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
            extra = backstop_targets(tin["command"], found)
        elif tool.startswith("mcp__") and tool.endswith("send_agent_prompt"):
            ident = next((tin[k] for k in MCP_ID_KEYS if isinstance(tin.get(k), str)), "")
            found = [(ident, None)] if ident else []  # another host's agent id is unknown here: decide() passes it
        for target, allow, back in [(t, a, False) for t, a in found] + [(t, a, True) for t, a in extra]:
            reason = judge(target, allow, back)
            if reason:
                deny(reason)
                return 0
    except Exception as exc:  # noqa: BLE001 - a guard must never block on its own bug
        print(f"archived_send_gate: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
