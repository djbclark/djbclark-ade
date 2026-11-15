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
`acp-dispatch footer`, deleted 2026-11-14). Fails open on any other error.
"""

import json
import os
import re
import sys
from pathlib import Path

MARK = "Delivery contract"
# The footer's own heading at the start of a line (`## Delivery contract (...)`): a mention of the words in prose, or a peer's
# whole footer pasted in a fence or quote, is not this prompt's footer (lead review 14760b15 B3: fail closed = append ours).
FOOTER_HEADING = re.compile(r"(?m)^ {0,3}#{1,6}[ \t]+" + MARK)
EXEMPT = {"claude-code-guide", "statusline-setup"}
DEFAULT_LEAD = "main"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_FOOTER = _REPO_ROOT / "docs" / "dispatch-footer.md"
_HOME_FOOTER = Path.home() / "src/djbclark-ade/docs/dispatch-footer.md"
_END = r"(?!\w|\.(?:done|inbox|replies)\b)"      # not the middle of `X-report.md.done`
_LEFT = r"(?<![\w.~$@+/-])"                          # a `~/x`, `$HOME/x` or relative path is not an absolute one
REPORT_IN_PROMPT = re.compile(_LEFT + r"(/[\w.@~+/-]+-report\.md)" + _END)
_MD = r"[*_`]*"                                      # markdown around a label: `**Report path:** /x`, `` `Report path:` /x ``
REPORT_LABELLED = re.compile(r"(?i)report(?: path| file)?" + _MD + r"\s*(?:is|:|=)" + _MD + r"\s*`?" + _LEFT
                             + r"(/[\w.@~+/-]+-report\.md)" + _END)
# the prompt's OWN `Report path:` / `Report file:` line (at the start of a line), as opposed to a peer's `Worker report: ...`
# At most 3 spaces of indent: 4+ spaces or a tab is a markdown code block, i.e. pasted text, not this prompt's own label
# (accepted trade-off, adversary r1 B3: a `Report path:` line indented as a list continuation falls to the labelled tier). A list
# marker may be `1.`, `1)`, `-`, `*` or the operator's own `A1.` / `A1a.` / `B2)` labels (lw-01 follow-up, ec-01 E2b).
# `Report:` alone at the start of a line is the own label too, and a quote prefix is allowed (the outside-text pass has quotes
# removed; the whole-prompt pass finds a quoted own line): adversary r2 B1.
REPORT_OWN = re.compile(r"(?im)^ {0,3}(?:>[ \t]*)*(?:(?:[A-Za-z]?\d+[a-z]?[.)]|[-*])[ \t]+)?" + _MD + r"report(?:[ \t]+(?:path|file))?" + _MD + r"[ \t]*(?:is|:|=)"
                        + _MD + r"[ \t]*`?" + _LEFT + r"(/[\w.@~+/-]+-report\.md)" + _END)
# The strict own label: `Report path:` / `Report file:` at the start of a line, no quote prefix, no bare `Report:`: what a
# prompt writes about ITSELF. Only a unique hit of it is taken on sight (adversary r3 B1).
REPORT_OWN_STRICT = re.compile(r"(?im)^ {0,3}(?:(?:[A-Za-z]?\d+[a-z]?[.)]|[-*])[ \t]+)?" + _MD + r"report[ \t]+(?:path|file)" + _MD
                               + r"[ \t]*(?:is|:|=)" + _MD + r"[ \t]*`?" + _LEFT + r"(/[\w.@~+/-]+-report\.md)" + _END)
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
    "start, add a line `Relaunch-reason: <why>` (at the start of the line) to the prompt and launch again (the hook logs it, and the "
    "earlier report is overwritten). Create `{report}.done` only for your own agent whose report is complete, "
    "never for one still running.")


def check_report_name(report: str) -> bool:
    """False when Claude Code would refuse Write on this report basename (acp-dispatch parity)."""
    return CLAUDE_REFUSED_BASENAME.match(Path(report).name) is None


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-")
    return s or "subagent"


_FENCE_LINE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")          # a CommonMark code fence line (opener or closer)
_QUOTE_LINE = re.compile(r"^[ \t]*>")                            # a quoted line


def _outside_pasted(prompt):
    """The prompt without its closed fenced code blocks and `>` quoted lines (CommonMark fences: a backtick fence's info
    string has no backtick; the closer is the same character, at least as long, with nothing after it). An opener with no
    closer is plain text and the scan resumes on the line after it. Linear (adversary r3 B2): every line is matched once; one
    backward pass records, per fence character, the longest closer at or after each line, so "does this opener have a
    closer?" is one lookup and a failed opener costs nothing; a successful one searches forward to its first closer and
    jumps past it."""
    lines = prompt.split("\n")
    info = [_FENCE_LINE.match(ln) for ln in lines]
    best = {"`": [0] * (len(lines) + 1), "~": [0] * (len(lines) + 1)}
    for k in range(len(lines) - 1, -1, -1):
        for ch in best:
            best[ch][k] = best[ch][k + 1]
        m = info[k]
        if m and not m.group(2).strip():
            best[m.group(1)[0]][k] = max(best[m.group(1)[0]][k], len(m.group(1)))
    out, i = [], 0
    while i < len(lines):
        m = info[i]
        if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            ch, n = m.group(1)[0], len(m.group(1))
            if best[ch][i + 1] >= n:
                i = next(k for k in range(i + 1, len(lines)) if (c := info[k]) and c.group(1)[0] == ch
                         and len(c.group(1)) >= n and not c.group(2).strip()) + 1      # the block, opener to closer, is pasted
                continue
        if not _QUOTE_LINE.match(lines[i]):
            out.append(lines[i])
        i += 1
    return "\n".join(out)


def _uniq(*lists):
    return list(dict.fromkeys(x for xs in lists for x in xs))


def named_report(prompt):
    """The report path the prompt itself gives, or None (the hook then derives its own path, which never touches a peer's
    file). Confidence levels, each tried only when the previous found nothing; a CONFLICT inside a level is ambiguous, never
    a ranking, because mirror-image prompts (`Worker report: peer` outside + own `Report path:` fenced, vs `Your report:
    own` outside + peer `Report path:` fenced) differ only in a qualifier word, so no fixed order is right for both
    (adversary r3 B1; lw-01 #691 B1 and ec-01 E2c). The levels:
      1. the strict own label (`Report path:` / `Report file:` at line start) in the text outside pasted blocks;
      2. a bare own label (`Report:`) outside, merged with every labelled report outside;
      3. the own and labelled reports of the whole prompt (a brief that names its report only inside pasted text);
      4. a bare path mention anywhere (never outside-first: an unlabelled own path pasted in a fence against a peer's path in
         prose, and its mirror image, are a conflict like any other; adversary r4 B1).
    A path whose .done exists is someone's finished report (2026-10-18), so it is never reused."""
    outside = _outside_pasted(prompt)
    strict = _uniq(REPORT_OWN_STRICT.findall(outside))
    if strict:
        paths = strict
    else:
        bare = _uniq(REPORT_OWN.findall(outside))
        if bare:
            paths = _uniq(bare, REPORT_LABELLED.findall(outside))
        else:
            # a pasted peer footer's delivery line is the peer's report, not this prompt's (lead review B3)
            theirs = set(FOOTER_DELIVERY.findall(prompt))      # no footer heading of its own outside pasted text: any delivery line is a peer's (fenced, quoted or indented)
            paths = (_uniq([x for x in REPORT_OWN.findall(prompt) if x not in theirs],
                           [x for x in REPORT_LABELLED.findall(prompt) if x not in theirs])
                     or _uniq([x for x in REPORT_IN_PROMPT.findall(prompt) if x not in theirs]))
    if len(paths) != 1:
        return None
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
            outside = _outside_pasted(prompt)        # a peer's pasted brief or footer is not this launch's
            labelled = {x for x in set(REPORT_LABELLED.findall(outside))
                        if not Path(x + ".done").exists()}      # a finished background report is not this launch's
            paths = labelled | set(FOOTER_DELIVERY.findall(outside))   # the delivery line is always this launch's
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
    has_footer = bool(FOOTER_HEADING.search(_outside_pasted(prompt_text)))
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
