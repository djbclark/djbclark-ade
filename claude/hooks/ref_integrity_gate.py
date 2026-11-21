#!/usr/bin/env python3
"""Stop: check that the last line of the final post, when it is a `Ref:` line, was really issued.

2026-11-21: a session ended several posts with "Ref: youtube-tv-proxy 82118f5", a git short hash
typed by hand, and nothing noticed. A Ref is a unique, script-issued id for one operator-facing
post (docs/ref-labels.md Part B): `ref <BOT>` prints `Ref: <BOT>-<base36>` and logs it in
~/.local/state/djbclark-ade/refs/issued.log (REFS_DIR overrides). This hook is the check.

When the last non-blank line of the final assistant message starts with `Ref:` it must:
  (a) have the form `Ref: <BOT>-<base36>` (BOT has no spaces or hyphens);
  (b) name an id that is in issued.log;
  (c) carry the bot prefix the log recorded for that id;
  (d) not have been used by an earlier post of the same transcript.
Any failure returns {"decision": "block", "reason": ...} telling the model to run `ref <BOT>` and
send the post again with the line replaced. No `Ref:` line: only a non-blocking `systemMessage`
note, and none at all for a short post (under 200 characters, the progress-note exemption of
Part B item 1).

Never loops: nothing is blocked when `stop_hook_active` is set, and a message (by hash) is blocked
at most once per session. Sub-agents (`agent_id` in the payload) are skipped: their final message
goes to the parent, not the operator. Local and fast: it reads issued.log and the transcript tail,
no network. Fails open on any error; REF_GATE_OFF=1 disables it. The ids are looked up by the same
rules as `ref lookup` (bin/ref); tests/test_ref_integrity_gate.py keeps the two in step.

Environment: REFS_DIR (issued.log directory), REF_GATE_STATE_DIR (once-per-message state and the
decisions log, default ~/.local/state/ade/ref-gate).
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import sys
import time

DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
REF_LINE = re.compile(r"^Ref:")
REF_FORM = re.compile(r"^Ref: ([^\s-]+)-([0-9a-z]+)$")
SHORT_POST = 200  # docs/ref-labels.md Part B item 1: a progress note under 200 chars is exempt
TRANSCRIPT_TAIL = 64 * 1024 * 1024
STATE_MAX_AGE = 14 * 86400


def refs_dir() -> str:
    return os.environ.get("REFS_DIR") or os.path.expanduser("~/.local/state/djbclark-ade/refs")


def state_dir() -> str:
    d = os.environ.get("REF_GATE_STATE_DIR") or os.path.expanduser("~/.local/state/ade/ref-gate")
    os.makedirs(d, exist_ok=True)
    return d


def last_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""


def issued_bot(ident: str) -> str:
    """The bot issued.log recorded for `ident`, "" when it was never issued (same rules as
    `ref lookup`: shared flock on an existing .lock, first matching line, nothing created)."""
    d = refs_dir()
    lock_fd = None
    try:
        lock_fd = os.open(os.path.join(d, ".lock"), os.O_RDONLY)
        fcntl.flock(lock_fd, fcntl.LOCK_SH)
    except OSError:
        lock_fd = None
    try:
        with open(os.path.join(d, "issued.log"), encoding="utf-8", errors="replace") as log:
            for line in log:
                cols = line.rstrip("\n").split("\t")
                if cols[0] == ident and len(cols) >= 2:
                    return cols[1]
    except OSError:
        pass
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
    return ""


def assistant_texts(path: str) -> list[tuple[str, str]]:
    """[(message id, text of one block)] for assistant text blocks that contain `Ref:`, oldest
    first, from the tail of the transcript. Prefiltered on bytes so a big transcript stays fast."""
    out: list[tuple[str, str]] = []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - TRANSCRIPT_TAIL))
            raw = fh.read()
    except OSError:
        return out
    for line in raw.split(b"\n"):
        if b"Ref:" not in line or b'"assistant"' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        msg = entry.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        blocks = [content] if isinstance(content, str) else content if isinstance(content, list) else []
        mid = str(msg.get("id") or entry.get("uuid") or "")
        for b in blocks:
            text = b if isinstance(b, str) else b.get("text") if isinstance(b, dict) and b.get("type") == "text" else None
            if isinstance(text, str):
                out.append((mid, text))
    return out


def last_transcript_text(path: str) -> str:
    """Text of the final assistant message in the transcript (fallback when the payload has no
    `last_assistant_message`); only its newest text entry, from the tail."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - 4 * 1024 * 1024))
            raw = fh.read()
    except OSError:
        return ""
    for line in reversed(raw.split(b"\n")):
        if b'"assistant"' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        msg = entry.get("message") if isinstance(entry, dict) and entry.get("type") == "assistant" else None
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = [b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text"
                     and isinstance(b.get("text"), str)]
            if texts:
                return "\n".join(texts)
    return ""


def used_earlier(path: str, ref_line: str, message: str) -> bool:
    """True when an earlier assistant message of this transcript already ended with `ref_line`.
    The current message is normally already in the transcript, so the newest match is dropped
    when its text is the message being checked; a transcript that lags is then not miscounted."""
    ends: list[tuple[str, str]] = []  # (message id, block text) whose last line is the ref line, oldest first
    for mid, text in assistant_texts(path):
        if last_line(text) == ref_line:
            ends.append((mid, text))
    if ends and message.rstrip().endswith(ends[-1][1].rstrip()):
        ends.pop()
    return bool(ends)


def check(message: str, transcript: str) -> tuple[str, str] | None:
    """None when the post is fine; else (problem, bot to show)."""
    line = last_line(message)
    form = REF_FORM.match(line)
    if not form:
        return (f"`{line[:120]}` is not of the form `Ref: <BOT>-<base36 id>`", "<BOT>")
    bot, ident = form.groups()
    issued = issued_bot(ident)
    if not issued:
        return (f"id `{ident}` was never issued by `ref` (a git hash, PR number or hand-typed id is not a Ref)", bot)
    if issued != bot:
        return (f"id `{ident}` was issued to bot `{issued}`, not `{bot}`", bot)
    if transcript and used_earlier(transcript, line, message):
        return (f"`{line}` already ended an earlier post of this session (one Ref per post, never reused)", bot)
    return None


def log_decision(session: str, outcome: str, line: str, problem: str = "") -> None:
    try:
        rec = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "session": session, "outcome": outcome,
               "line": line[:200], "problem": problem[:300]}
        with open(os.path.join(state_dir(), "decisions.log"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def already_blocked(session: str, digest: str) -> bool:
    """Record that this message was blocked; True when it had been (so it is never blocked twice)."""
    root = state_dir()
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session)[:120]
    path = os.path.join(root, safe + ".blocked")
    try:
        with open(path, encoding="utf-8") as fh:
            if digest in fh.read().split():
                return True
    except OSError:
        pass
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(digest + "\n")
    cutoff = time.time() - STATE_MAX_AGE
    try:
        for name in os.listdir(root):
            full = os.path.join(root, name)
            if name.endswith(".blocked") and os.path.getmtime(full) < cutoff:
                os.unlink(full)
    except OSError:
        pass
    return False


def main() -> int:
    if os.environ.get("REF_GATE_OFF"):
        return 0
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(data, dict) or data.get("hook_event_name") != "Stop":
        return 0
    if data.get("agent_id"):
        return 0  # a sub-agent's final message goes to its parent, not the operator
    session = str(data.get("session_id") or "unknown")
    transcript = data.get("transcript_path") if isinstance(data.get("transcript_path"), str) else ""
    message = data.get("last_assistant_message")
    if not isinstance(message, str):
        message = last_transcript_text(transcript) if transcript else ""
    if not message.strip():
        return 0
    line = last_line(message)
    if not REF_LINE.match(line):
        if len(message.strip()) >= SHORT_POST and not data.get("stop_hook_active"):
            print(json.dumps({"systemMessage": (
                "ref-integrity: this post has no `Ref:` last line. Operator-facing posts end with one "
                "from `ref <BOT>` (docs/ref-labels.md Part B); a short progress note is exempt.")}))
        return 0
    problem = check(message, transcript)
    if problem is None:
        return 0
    why, bot = problem
    digest = hashlib.sha256(message.encode("utf-8", "replace")).hexdigest()[:16]
    if data.get("stop_hook_active"):
        log_decision(session, "allowed-stop-hook-active", line, why)
        return 0
    if already_blocked(session, digest):
        log_decision(session, "allowed-already-blocked", line, why)
        return 0
    log_decision(session, "blocked", line, why)
    reason = (
        f"Invalid Ref line: {why}. A Ref is a unique id issued by a script for one operator-facing "
        f"post; never a commit hash, PR number or text you typed. Run `ref {bot}` with Bash (BOT is "
        "your prefix from docs/ref-labels.md, for example CLAUDE), then send the post again with its "
        "last line replaced by the exact line `ref` printed."
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # fail open: a gate bug must never wedge an agent
        sys.exit(0)
