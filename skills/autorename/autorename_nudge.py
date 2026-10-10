#!/usr/bin/env python3
"""UserPromptSubmit hook: ask the agent to title an untitled session, once.

Built 2026-10-08 for Claude Code (where /autorename only ran when asked), and
extended 2026-10-10 to zcode and Grok. It hands the agent a note telling it to
run the autorename skill in --auto mode, herdr placement step included, as the
last step of that turn.

The backend is chosen by the hook event, then by session-id shape: a Grok
`Stop` event, else zcode ids (`sess_<uuid>`), else Claude Code.

- Claude Code (registered in ~/.claude/settings.json): UserPromptSubmit stdout is
  surfaced to the model, so the note is printed as plain text; the title check
  reads custom-title records off the session transcript.
- zcode (registered in ~/.zcode/cli/config.json → hooks.events.UserPromptSubmit;
  config-file hooks need `hooks.enabled: true` there): stdout must be exactly one
  JSON object, so the same note goes out as hookSpecificOutput.additionalContext;
  the title check is a session-db lookup, since zcode keeps no transcript
  sidecar. `default` and `first_input` titles (placeholder / raw prompt echo)
  count as untitled — `generated` and `custom` do not.
- Grok (registered in ~/.grok/hooks/autorename.json): UserPromptSubmit stdout is
  discarded, including additionalContext (user-guide 10-hooks.md), so this
  registers on Stop instead. Stop additionalContext is fed back and keeps the
  turn open for one continuation. Once per session. A manual title
  (`title_is_manual`) is left alone. `stopHookActive`, a subagent stop, and any
  Stop whose reason is not `end_turn` produce no output, so the continuation
  and session teardown are allowed to finish.

Fires at most once per session (state in ~/.local/state/autorename/), skips
slash commands and very short prompts, skips Claude non-interactive entrypoints
(SDK, `claude -p`, acp-run) where nobody can answer the placement question, and
skips when a title is already set. MUST always exit 0 quickly; stdlib only.
"""

from __future__ import annotations
import json
import os
import signal
import sys
from pathlib import Path

DEADLINE_SECONDS = 2
MIN_PROMPT_CHARS = 20
SKILL_DIR = Path(__file__).resolve().parent
PY = "/opt/homebrew/opt/python@3.14/bin/python3.14"


def claude_has_title(transcript: str | None) -> bool:
    if not transcript or not Path(transcript).is_file():
        return False
    sys.path.insert(0, str(SKILL_DIR))
    from autorename import current_title  # noqa: E402  (sibling script)
    return current_title(Path(transcript)) is not None


def zcode_has_title(sid: str) -> bool:
    sys.path.insert(0, str(SKILL_DIR))
    from autorename import zcode_current_title  # noqa: E402  (sibling script)
    row = zcode_current_title(sid)
    if row is None:
        return True  # unknown session: never nag about it
    return row[1] in ("generated", "custom")


def grok_is_manual(sid: str) -> bool:
    """True when this Grok session should not be nudged (missing, or already pinned)."""
    sys.path.insert(0, str(SKILL_DIR))
    from autorename import find_grok_summary, grok_read  # noqa: E402  (sibling script)
    summary = find_grok_summary(sid)
    if summary is None:
        return True
    try:
        _data, _title, source = grok_read(summary)
    except (OSError, ValueError):
        return True
    return source == "manual"


def note_text() -> str:
    py = PY if Path(PY).is_file() else "python3"
    return (
        "[autorename] This session has no title yet. As the LAST step of this turn, after "
        "the requested work, follow the autorename skill in --auto mode: pick a title, run "
        f"`{py} {SKILL_DIR}/autorename.py --auto \"<title>\"`, THEN run "
        f"`{py} {SKILL_DIR}/herdr_place.py check --auto` (prints JSON; no-op outside herdr). "
        "If it says `\"ask\": true`, the tab sits in a generic workspace: follow the skill's "
        "step 3 and ask the operator with one AskUserQuestion (matching existing workspace / "
        "new workspace / leave it), then run `herdr_place.py move ...` or `herdr_place.py decline`. Skip that "
        "question only if you are a dispatched worker no human is watching. "
        "Mention the result in one line; don't otherwise discuss this note."
    )


def emit(kind: str) -> None:
    if kind == "claude":
        print(note_text())
        return
    event = "Stop" if kind == "grok" else "UserPromptSubmit"
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": note_text(),
        }
    }, ensure_ascii=False))


def main() -> None:
    signal.signal(signal.SIGALRM, lambda *_: os._exit(0))
    signal.alarm(DEADLINE_SECONDS)

    data = json.load(sys.stdin)
    event = data.get("hook_event_name") or ""
    event_snake = data.get("hookEventName") or ""
    grok = event == "Stop" or event_snake == "stop"
    sid = data.get("session_id") or data.get("sessionId") or ""
    zcode = (not grok) and sid.startswith("sess_")

    if grok:
        # A continuation, a subagent, or session teardown must be allowed to stop.
        if data.get("stopHookActive") or data.get("subagentType"):
            return
        reason = data.get("reason")
        if reason not in (None, "", "end_turn"):
            return
    elif not zcode and os.environ.get("CLAUDE_CODE_ENTRYPOINT", "cli") != "cli":
        return

    if not grok:
        prompt = data.get("prompt")
        if not isinstance(prompt, str) and data.get("transcript_path"):
            try:  # zcode's hook transcript is one user-message JSONL line
                with open(data["transcript_path"], encoding="utf-8", errors="replace") as fh:
                    first = json.loads(fh.readline())
                prompt = first["message"]["content"][0]["text"]
            except (OSError, ValueError, KeyError, IndexError, TypeError):
                prompt = None
        prompt = (prompt or "").strip()
        if not sid or len(prompt) < MIN_PROMPT_CHARS or (prompt.startswith("/") and " " not in prompt):
            return
    elif not sid:
        return
    # The id becomes a filename. Grok and Claude ids are uuids; reject a path.
    if "/" in sid or "\\" in sid or sid in {".", ".."}:
        return

    state = Path.home() / ".local/state/autorename" / f"{sid}.nudged"
    if state.exists():
        return
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text("1\n", encoding="utf-8")

    if grok:
        if grok_is_manual(sid):
            return
        emit("grok")
    elif zcode:
        if zcode_has_title(sid):
            return
        emit("zcode")
    else:
        if claude_has_title(data.get("transcript_path")):
            return
        emit("claude")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # never fail or delay a prompt
        pass
    sys.exit(0)
