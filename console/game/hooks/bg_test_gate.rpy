## Port of claude/hooks/bg_test_gate.py (PreToolUse on Bash).
## Entry label: hook_bg_test_gate. Denies a pytest / tox / nox / run_tests*.py / swift build|test|run /
## xcodebuild command that is not run through ~/ops/site-private/bin/bg. Allowed without bg:
## --version/--help/--collect-only, anything already starting with bg, and text that merely
## mentions a test tool inside quotes or a heredoc. Fails open on any parse error.
## Escape hatch: BG_GATE_OFF=1 in the environment. Hook JSON on stdin, decision on stdout,
## exit status in ade_exit_code (0 on every path, as in the original).
## Kept from HEAD: the tool_name check sits outside the try, so a non-object JSON value on stdin
## raises instead of exiting 0 (the original traceback, exit 1, is not "fixed" here).

init python:
    import json, os, re, sys

    _BG_GATE_BG = "~/ops/site-private/bin/bg"

    def _bgg_strip_literals(c):
        """Drop heredoc bodies and quoted strings so words inside text do not count."""
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
        return re.sub(r'"[^"]*"', '""', s)

    _BGG_TEST_WORD = (
        r"(?:pytest|py\.test|tox|nox|run_tests\w*\.py|xcodebuild|swift-(?:test|build)"
        r"|swift\s+(?:-\S+\s+)*(?:test|build|run))"
    )
    # A test command: the word is the command itself, or follows python -m / uv run / env VAR=x /
    # a path, at the start of a pipeline segment.
    _BGG_SEGMENT = re.compile(
        r"(?:^|[;&|(]|&&|\|\|)\s*"
        r"(?:(?:\w+=\S*\s+)*)"  # VAR=value prefixes
        r"(?:(?:env|time|nice|command|exec)\s+(?:\w+=\S*\s+)*)?"
        r"(?:(?:uv|uvx)\s+(?:run\s+)?(?:--?\S+\s+)*)?"
        r"(?:\S*python[\d.]*\s+(?:-\S+\s+)*(?:-m\s+)?)?"
        r"(?:\S*/)?" + _BGG_TEST_WORD + r"(?=\s|$)"
    )
    _BGG_BG_PREFIX = re.compile(r"(?:^|[;&|(]\s*|\s)(?:\S*/)?bgb?\s")
    _BGG_SAFE = re.compile(r"(?:^|\s)(?:--version|-V|--help|-h|--collect-only|--co)(?:\s|$)")

    _BGG_REASON = (
        f"Tests run through bg, not bare: {_BG_GATE_BG} <your command> (bare `bg` is the shell "
        "job-control builtin, so use the full path). bg caps parallelism, runs at utility "
        "QoS and takes one of two machine-wide test slots; a bare run of a full suite sent "
        "the load average to 220 on 2026-10-08. Run the changed files first (--lf -x); run "
        "the full suite only when asked."
    )

    def _bgg_main(stdin_text):
        try:
            data = json.loads(stdin_text)
        except (ValueError, OSError):
            return 0
        if data.get("tool_name") != "Bash" or os.environ.get("BG_GATE_OFF"):
            return 0
        cmd = str((data.get("tool_input") or {}).get("command") or "")
        try:
            plain = _bgg_strip_literals(cmd)
            for seg in re.split(r"\n|;|&&|\|\||\|", plain):
                seg = seg.strip()
                if (
                    not seg
                    or not _BGG_SEGMENT.match(seg)
                    or _BGG_BG_PREFIX.match(seg)
                    or _BGG_SAFE.search(seg)
                ):
                    continue
                sys.stdout.write(json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": _BGG_REASON,
                        }
                    }
                ) + "\n")
                return 0
        except (re.error, TypeError, AttributeError):
            return 0
        return 0

label hook_bg_test_gate:
    $ ade_exit_code = 0
    $ ade_exit_code = _bgg_main(sys.stdin.read())
    return
