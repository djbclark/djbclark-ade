#!/usr/bin/env python3
"""PreToolUse (Agent): give an Agent-tool sub-agent the delivery footer when its prompt lacks it.

~/CLAUDE.md rule 25: every Agent-tool sub-agent gets the filled `docs/dispatch-footer.md` pasted into
its prompt, because the harness cuts a sub-agent's final message at 4,000 characters and the footer is
what makes it write a report file, a `.done` marker and `BLOCKED:` instead of a question. On 2026-10-18
a lead launched a research sub-agent without it and had to SendMessage the contract afterwards. The
footer's own heading is the check. A prompt without it is no longer denied (2026-10-18, djbclark: the
deny cost a relaunch for a step the hook can do itself): the hook appends the footer through
`updatedInput`. The report path is the one the prompt labels ("Report path: /abs/x-report.md") or the
only absolute `*-report.md` path it names, never one whose `.done` exists, else
`~/.local/state/agent-reports/<session>/<name>-report.md`; the sub-agent's `written: <path>` final line
and the hook's `additionalContext` both name it. If the footer cannot be built, the old deny stands.
Exempt: claude-code-guide and statusline-setup (short answers by design). AGENT_FOOTER_GATE_OFF=1
disables it. Resume guard (2026-11-14, rs-01): a report path that exists without its `.done` marker
means an earlier sub-agent of this session did not finish (2026-11-14: a lead's process restarted, the
harness said to resume the stopped adversary with SendMessage, the lead launched a new Agent with the same
description instead and ~20 minutes of paid review were redone). That launch is denied with the order to
SendMessage the earlier agent (its id is in the spawn result / task notification) "resume from where you
stopped"; a deliberate fresh start carries a prompt line `Relaunch-reason: <why>`, which the hook allows and
logs to `<report dir>/<session>/relaunch.log`. The guard covers the path the hook would use and, for a prompt that
already has the footer, the path the prompt labels ("Report path: ...") or its footer's delivery line names; it skips on any error (fail open).
Fills `docs/dispatch-footer.md` inline (2026-11-09: no longer shells out to
`acp-dispatch footer`, which Wave 6 deletes). Fails open on any other error.
"""

import json
import os
import re
import sys
from pathlib import Path

MARK = "Delivery contract"
EXEMPT = {"claude-code-guide", "statusline-setup"}
DEFAULT_LEAD = "main"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_FOOTER = _REPO_ROOT / "docs" / "dispatch-footer.md"
_HOME_FOOTER = Path.home() / "src/djbclark-ade/docs/dispatch-footer.md"
_END = r"(?!\w|\.(?:done|inbox|replies)\b)"      # not the middle of `X-report.md.done`
_LEFT = r"(?<![\w.~$@+/-])"                          # a `~/x`, `$HOME/x` or relative path is not an absolute one
REPORT_IN_PROMPT = re.compile(_LEFT + r"(/[\w.@~+/-]+-report\.md)" + _END)
REPORT_LABELLED = re.compile(r"(?i)report(?: path| file)?\s*(?:is|:|=)\s*`?" + _LEFT + r"(/[\w.@~+/-]+-report\.md)" + _END)
# the prompt's OWN `Report path:` / `Report file:` line (at the start of a line), as opposed to a peer's `Worker report: ...`
REPORT_OWN = re.compile(r"(?im)^[ \t>*-]*report (?:path|file)[ \t]*(?:is|:|=)[ \t]*`?" + _LEFT
                        + r"(/[\w.@~+/-]+-report\.md)" + _END)
# the footer's own delivery line ("Write the full deliverable to `{report}`"): the path a filled footer carries
FOOTER_DELIVERY = re.compile(r"deliverable to `" + _LEFT + r"(/[\w.@~+/-]+-report\.md)`")
# Same rule as acp-dispatch check_report_name: Claude Code refuses Write on these basenames.
CLAUDE_REFUSED_BASENAME = re.compile(r"^(REPORT|SUMMARY|FINDINGS|ANALYSIS).*\.md$", re.IGNORECASE)
DENY_REASON = (
    "This sub-agent prompt has no delivery footer (~/CLAUDE.md rule 25) and the hook could not build one. "
    "Paste the filled delivery contract from docs/dispatch-footer.md (it starts with '## Delivery "
    "contract') at the end of the prompt with {report} set to <scratchpad>/<name>-report.md, and launch "
    "again; then read that report file, not the final message.")


RELAUNCH_TOKEN = re.compile(r"(?m)^Relaunch-reason:[ \t]*(\S.*)$")    # column 0: an indented line is quoted or pasted text
RESUME_REASON = (
    "{report} already exists and {report}.done does not: an earlier sub-agent of this session with this report "
    "path did not finish (its process stopped or it is still running). Do not start a new one: resume it with "
    "SendMessage to its agent id (the agentId in its spawn result or task notification; ListAgents shows it) "
    "and the text \"resume from where you stopped\". Not an earlier agent of yours? If the path is another "
    "agent's report named only as background, or two long descriptions cut to the same name, give this agent "
    "its own `Report path: /abs/<name>-report.md` (or a distinct description). If you deliberately want a fresh "
    "start, add a line `Relaunch-reason: <why>` to the prompt and launch again (the hook logs it, and the "
    "earlier report is overwritten). Create `{report}.done` only for your own agent whose report is complete, "
    "never for one still running.")


def check_report_name(report: str) -> bool:
    """False when Claude Code would refuse Write on this report basename (acp-dispatch parity)."""
    return CLAUDE_REFUSED_BASENAME.match(Path(report).name) is None


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-")
    return s or "subagent"


def named_report(prompt):
    """The report path the prompt itself gives: its own `Report path:` line, else the only labelled one, else the only one
    it mentions; two different labelled paths with no `Report path:` of its own give None (lw-01, #691 review B1: a
    peer's `Worker report:` listed first was taken as this launch's report). A path whose
    .done exists is someone's finished report (2026-10-18: a review prompt that named the slice's report as
    background got that path), so it is never reused."""
    own = list(dict.fromkeys(REPORT_OWN.findall(prompt)))       # the prompt's own `Report path:` beats a peer's labelled one
    labelled = own or list(dict.fromkeys(REPORT_LABELLED.findall(prompt)))
    paths = labelled or sorted(set(REPORT_IN_PROMPT.findall(prompt)))
    if len(paths) != 1:
        return None         # none, or two different ones with no `Report path:` of its own: the hook derives its own path
    return None if Path(paths[0] + ".done").exists() else paths[0]


def report_path(data, tool_input):
    named = named_report(str(tool_input.get("prompt") or ""))
    if named:
        return named
    session = slug(str(data.get("session_id") or "session"))
    name = slug(str(tool_input.get("name") or tool_input.get("description") or ""))
    d = Path(os.environ.get("AGENT_FOOTER_REPORT_DIR") or Path.home() / ".local/state/agent-reports") / session
    d.mkdir(parents=True, exist_ok=True)
    return str(d / f"{name}-report.md")


def relaunch_reason(prompt):
    m = RELAUNCH_TOKEN.search(prompt)
    why = m.group(1).strip() if m else ""
    return None if re.fullmatch(r"(?i)(?:<\s*why\s*>)?", why) else why    # the template's placeholder is not a reason


def unfinished_report(data, tool_input, has_footer):
    """The report path of an earlier sub-agent that did not finish, else None. A prompt without the footer is
    checked on the path the hook would use; one with it only on the path it labels or its footer's delivery line
    names (a background mention of someone else's report must not block the launch). Any error means no finding (fail open)."""
    try:
        prompt = str(tool_input.get("prompt") or "")
        if has_footer:
            labelled = {x for x in set(REPORT_LABELLED.findall(prompt))
                        if not Path(x + ".done").exists()}      # a finished background report is not this launch's
            paths = labelled | set(FOOTER_DELIVERY.findall(prompt))   # the delivery line is always this launch's
            path = next(iter(paths)) if len(paths) == 1 else None      # two different paths: ambiguous, skip
        else:
            path = report_path(data, tool_input)
        if path and Path(path).exists() and not Path(path + ".done").exists():
            return path
    except Exception:  # noqa: BLE001 - the guard never blocks on its own failure
        pass
    return None


def log_relaunch(data, tool_input, path, why):
    try:
        session = slug(str(data.get("session_id") or "session"))
        d = Path(os.environ.get("AGENT_FOOTER_REPORT_DIR") or Path.home() / ".local/state/agent-reports") / session
        d.mkdir(parents=True, exist_ok=True)
        entry = {"report": path, "why": why, "description": str(tool_input.get("description") or "")}
        with open(d / "relaunch.log", "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:  # noqa: BLE001
        pass


def footer_file():
    override = os.environ.get("AGENT_FOOTER_FILE")
    if override:
        return Path(override)
    if _DEFAULT_FOOTER.is_file():
        return _DEFAULT_FOOTER
    return _HOME_FOOTER


def footer(report):
    """Fill docs/dispatch-footer.md placeholders; same substitutions as acp-dispatch footer once did."""
    if not check_report_name(report):
        return None
    path = footer_file()
    try:
        text = path.read_text()
    except OSError:
        return None
    lead = os.environ.get("AGENT_FOOTER_LEAD") or DEFAULT_LEAD
    report_p = Path(report)
    done = str(report_p.with_name(report_p.name + ".done"))
    inbox = str(report_p.with_name(report_p.name + ".inbox.md"))
    replies = str(report_p.with_name(report_p.name + ".replies.md"))
    out = (text.replace("{report}", report).replace("{done}", done)
           .replace("{inbox}", inbox).replace("{replies}", replies)
           .replace("{lead}", lead)).strip()
    return out if MARK in out else None


try:
    data = json.load(sys.stdin)
    if data.get("tool_name") not in ("Agent", "Task") or os.environ.get("AGENT_FOOTER_GATE_OFF"):
        sys.exit(0)
    tool_input = data.get("tool_input") or {}
    if str(tool_input.get("subagent_type") or "") in EXEMPT:
        sys.exit(0)
    prompt_text = str(tool_input.get("prompt") or "")
    has_footer = MARK in prompt_text
    stale = unfinished_report(data, tool_input, has_footer)
    note = ""
    if stale:
        why = relaunch_reason(prompt_text)
        if not why:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "deny",
                "permissionDecisionReason": RESUME_REASON.format(report=stale)}}))
            sys.exit(0)
        log_relaunch(data, tool_input, stale, why)
        note = f" Relaunch honoured and logged (Relaunch-reason: {why}); the earlier report {stale} will be overwritten."
    if has_footer:
        if note:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": note.strip()}}))
        sys.exit(0)
    report = ""
    try:
        report = report_path(data, tool_input)
        text = footer(report)
    except OSError:
        text = None
    if text is None:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": DENY_REASON}}))
        sys.exit(0)
    updated = dict(tool_input, prompt=str(tool_input.get("prompt") or "").rstrip() + "\n\n" + text + "\n")
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "updatedInput": updated,
        "additionalContext": (
            f"agent_footer_gate appended the delivery footer to this sub-agent's prompt. Its report is {report} "
            f"(done marker {report}.done): read that file, not the final message.{note}")}}))
except Exception:  # noqa: BLE001 - a gate must never break the tool
    sys.exit(0)
