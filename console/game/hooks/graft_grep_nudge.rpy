## Port of claude/hooks/graft_grep_nudge.py (PreToolUse on Grep|Glob|Bash).
## Entry label: hook_graft_grep_nudge. Once per session, in a graft-indexed repo, remind the
## model to try graft first. Non-blocking (additionalContext only); silent no-op when the repo
## has no graft/INDEX.md or the nudge already fired this session. Hook JSON on stdin,
## decision JSON on stdout, exit status in ade_exit_code (always 0 here, as in the original).

init python:
    import json, os, re, sys, tempfile

    def _graft_strip_literals(cmd):
        """Drop heredoc bodies and quoted strings so search words inside text
        (commit messages, file contents, echo args) don't count as a search."""
        out, lines, i = [], cmd.split("\n"), 0
        while i < len(lines):
            line = lines[i]
            out.append(line)
            m = re.search(r"<<-?\s*['\"]?(\w+)['\"]?", line)
            if m:
                delim, i = m.group(1), i + 1
                while i < len(lines) and lines[i].strip() != delim:
                    i += 1
            i += 1
        s = "\n".join(out)
        s = re.sub(r"'[^']*'", "''", s)
        s = re.sub(r'"[^"]*"', '""', s)
        return s

    def _graft_nudge_main(stdin_text):
        try:
            data = json.loads(stdin_text)
        except Exception:
            return 0

        root = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        if not os.path.isfile(os.path.join(root, "graft", "INDEX.md")):
            return 0

        # Bash only counts when it is a code search (grep/rg/ag/find/fd), not any command.
        if data.get("tool_name") == "Bash":
            cmd = _graft_strip_literals(str((data.get("tool_input") or {}).get("command") or ""))
            if not re.search(r"(?:^|[|;&(]\s*|\s)(?:grep|egrep|rg|ag|ack|find|fd)\s", cmd):
                return 0

        sid = str(data.get("session_id") or "default")
        marker = os.path.join(tempfile.gettempdir(), f"graft-nudge-{sid}")
        if os.path.exists(marker):
            return 0
        try:
            open(marker, "w").close()
        except Exception:
            pass

        sys.stdout.write(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                "This repo is indexed by graft. Before grepping/globbing for code, try "
                "`graft ask` (how/where), `graft grep` (every occurrence), "
                "`graft callers` (callers/blast radius) or `graft skeleton` (a file's API). "
                "Fall back to Grep/Glob for non-code text or when graft misses."
            ),
        }}) + "\n")
        return 0

label hook_graft_grep_nudge:
    $ ade_exit_code = 0
    $ ade_exit_code = _graft_nudge_main(sys.stdin.read())
    return
