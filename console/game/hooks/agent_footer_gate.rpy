## Port of claude/hooks/agent_footer_gate.py (PreToolUse on Agent|Task).
## Entry label: hook_agent_footer_gate. Gives an Agent-tool sub-agent the acp-dispatch delivery
## footer when its prompt lacks it (~/CLAUDE.md rule 25). A prompt without the footer is not
## denied: the footer is appended through updatedInput. If the footer cannot be built, the old
## deny stands. Exempt: claude-code-guide and statusline-setup. AGENT_FOOTER_GATE_OFF=1 disables
## it. Fails open on any other error. Hook JSON on stdin, decision on stdout, exit status in
## ade_exit_code (0 on every path).

init python:
    import json, os, re, subprocess, sys
    from pathlib import Path

    _AFG_MARK = "Delivery contract"
    _AFG_EXEMPT = {"claude-code-guide", "statusline-setup"}
    _AFG_ACP_DISPATCH = (os.environ.get("AGENT_FOOTER_ACP_DISPATCH")
                         or str(Path.home() / "src/djbclark-ade/bin/acp-dispatch"))
    _AFG_REPORT_IN_PROMPT = re.compile(r"(/[\w.@~+/-]+-report\.md)\b")
    _AFG_REPORT_LABELLED = re.compile(r"(?i)report(?: path| file)?\s*(?:is|:|=)\s*`?(/[\w.@~+/-]+-report\.md)\b")
    _AFG_DENY_REASON = (
        "This sub-agent prompt has no delivery footer (~/CLAUDE.md rule 25) and the hook could not build one. Run "
        "`~/src/djbclark-ade/bin/acp-dispatch footer --report <scratchpad>/<name>-report.md`, paste its "
        "output (it starts with '## Delivery contract') at the end of the prompt, and launch again; then "
        "read that report file, not the final message.")

    def _afg_slug(text):
        s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-")
        return s or "subagent"

    def _afg_named_report(prompt):
        """The report path the prompt itself gives: a labelled one, else the only one it mentions. A path whose
        .done exists is someone's finished report, so it is never reused."""
        labelled = _AFG_REPORT_LABELLED.findall(prompt)
        paths = labelled or sorted(set(_AFG_REPORT_IN_PROMPT.findall(prompt)))
        if len(paths) != 1 and not labelled:
            return None
        return None if Path(paths[0] + ".done").exists() else paths[0]

    def _afg_report_path(data, tool_input):
        named = _afg_named_report(str(tool_input.get("prompt") or ""))
        if named:
            return named
        session = _afg_slug(str(data.get("session_id") or "session"))
        name = _afg_slug(str(tool_input.get("name") or tool_input.get("description") or ""))
        d = Path(os.environ.get("AGENT_FOOTER_REPORT_DIR") or Path.home() / ".local/state/agent-reports") / session
        d.mkdir(parents=True, exist_ok=True)
        return str(d / f"{name}-report.md")

    def _afg_footer(report):
        r = subprocess.run([_AFG_ACP_DISPATCH, "footer", "--report", report],
                           capture_output=True, text=True, timeout=15)
        out = r.stdout.strip()
        return out if r.returncode == 0 and _AFG_MARK in out else None

    def _afg_emit(payload):
        sys.stdout.write(json.dumps(payload) + "\n")

    def _afg_main(stdin_text):
        try:
            data = json.loads(stdin_text)
            if data.get("tool_name") not in ("Agent", "Task") or os.environ.get("AGENT_FOOTER_GATE_OFF"):
                return 0
            tool_input = data.get("tool_input") or {}
            if str(tool_input.get("subagent_type") or "") in _AFG_EXEMPT or _AFG_MARK in str(tool_input.get("prompt") or ""):
                return 0
            report = ""
            try:
                report = _afg_report_path(data, tool_input)
                text = _afg_footer(report)
            except (OSError, subprocess.SubprocessError):
                text = None
            if text is None:
                _afg_emit({"hookSpecificOutput": {
                    "hookEventName": "PreToolUse", "permissionDecision": "deny",
                    "permissionDecisionReason": _AFG_DENY_REASON}})
                return 0
            updated = dict(tool_input, prompt=str(tool_input.get("prompt") or "").rstrip() + "\n\n" + text + "\n")
            _afg_emit({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "updatedInput": updated,
                "additionalContext": (
                    f"agent_footer_gate appended the delivery footer to this sub-agent's prompt. Its report is {report} "
                    f"(done marker {report}.done): read that file, not the final message.")}})
        except Exception:  # a gate must never break the tool
            return 0
        return 0

label hook_agent_footer_gate:
    $ ade_exit_code = 0
    $ ade_exit_code = _afg_main(sys.stdin.read())
    return
