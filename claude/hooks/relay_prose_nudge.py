#!/usr/bin/env python3
"""relay_prose_nudge.py: Stop hook. A relayed message answered only in prose reaches nobody.

Standing order 10 (AGENTS.md, 2026-10-25): a message from a peer, tagged `[relay from KIND ID (DIR)]`, is answered with
`relay.py ID "<text>"`, never in the receiver's own prose; the sender sees only what relay.py sends. The skill text
(skills/session-finder/SKILL.md, "Verified peer messaging") says so and nothing enforced it. This hook does, softly.

When a turn ends (Stop) and
  1. the turn began with a user message whose text starts with the relay header (optionally behind a `[queued Nm ago] `
     tag and the `<cross-session-message ...>` wrapper relay.py's socket route adds; the header text is exactly what
     skills/session-finder/relay.py `sender_tag` / `forced_tag` write, `[relay from KIND ID (DIR)]` or
     `[relay from KIND ID aka NAME (DIR)]`), and
  2. the turn made no relay.py call (a Bash tool call whose command contains `relay.py`) and no SendMessage call to that
     sender (its `to` equals the header's ID or `aka` name),
it prints `{"decision": "block", "reason": "<nudge>"}`, which is how a Stop hook hands text to the model: the session
continues one more step and the nudge names the route.

Never nudged: a relayed text that asks for no reply (`no reply needed`, `FYI`, or one that is itself an `ack <ID>`),
so acks and acks of acks never provoke more messages; a second Stop for the same relayed message (a state file per
session remembers the turn's key, and Claude Code's own `stop_hook_active` flag also ends it); anything unreadable.

Bounded: reads only the last TAIL_KB (256) KB of the transcript; a turn that began further back is not seen and is not
nudged. No network, never calls relay.py. Fails open: any error is exit 0 with no output. RELAY_PROSE_NUDGE_OFF=1
disables it; RELAY_PROSE_NUDGE_STATE overrides the state directory (default ~/.claude/state/relay-prose-nudges).
"""
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

TAIL_KB = 256
MAX_STATES = 200

HEADER = re.compile(
    r"^\s*(?:<cross-session-message\b[^>]*>\s*)?(?:\[queued [^\]]*\]\s*)?"
    r"\[relay from (?P<kind>[^\s\]]+) (?P<id>[^\s\]]+)(?: aka (?P<aka>[^()\]]+?))?(?= \(|\])[^\]]*\]\s*(?P<body>.*)$",
    re.S)
NO_REPLY = re.compile(r"no[ -]reply[ -](?:needed|required|necessary|expected)|\bFYI\b", re.I)
ACK = re.compile(r"^\W*ack\b[ :=]*\S", re.I)


def state_dir():
    return Path(os.environ.get("RELAY_PROSE_NUDGE_STATE") or Path.home() / ".claude/state/relay-prose-nudges")


def tail_lines(path):
    """The complete JSON lines in the last TAIL_KB KB of PATH (a cut first line is dropped)."""
    with open(path, "rb") as fh:
        size = fh.seek(0, os.SEEK_END)
        start = max(0, size - TAIL_KB * 1024)
        fh.seek(start)
        data = fh.read()
    lines = data.split(b"\n")
    if start:
        lines = lines[1:]
    return [ln for ln in lines if ln.strip()]


def user_text(o):
    """The text of a transcript entry that is a user prompt (including a queued one), else None (a tool result is no prompt)."""
    if o.get("isMeta") or o.get("isCompactSummary") or o.get("isVisibleInTranscriptOnly"):
        return None
    if o.get("type") == "user":
        m = o.get("message")
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
                return None
            return " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    elif isinstance(o.get("attachment"), dict) and o["attachment"].get("type") == "queued_command":
        p = o["attachment"].get("prompt")
        return p if isinstance(p, str) else None
    return None


def tool_calls(o):
    """(name, input) of each tool_use block of an assistant entry."""
    m = o.get("message")
    c = m.get("content") if isinstance(m, dict) and o.get("type") == "assistant" else None
    if not isinstance(c, list):
        return
    for b in c:
        if isinstance(b, dict) and b.get("type") == "tool_use":
            yield str(b.get("name") or ""), b.get("input") if isinstance(b.get("input"), dict) else {}


def answered_by_relay(calls, names):
    for name, inp in calls:
        if name == "Bash" and "relay.py" in str(inp.get("command") or ""):
            return True
        if name == "SendMessage" and str(inp.get("to") or inp.get("recipient") or "").strip().lower() in names:
            return True
    return False


def turn_key(raw):
    try:
        uid = json.loads(raw).get("uuid")
    except ValueError:
        uid = None
    return str(uid) if uid else hashlib.sha1(raw).hexdigest()


def already_nudged(session, key):
    try:
        return json.loads((state_dir() / f"{session}.json").read_text()).get("key") == key
    except (OSError, ValueError, AttributeError):
        return False


def remember(session, key):
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    with os.fdopen(fd, "w") as fh:
        json.dump({"key": key}, fh)
    os.replace(tmp, d / f"{session}.json")
    old = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime)[:-MAX_STATES]
    for p in old:
        p.unlink(missing_ok=True)


def decide(data):
    """The nudge text for this Stop event, a session/key pair to remember, or None."""
    tx = data.get("transcript_path")
    if data.get("stop_hook_active") or not isinstance(tx, str) or not Path(tx).is_file():
        return None
    start, start_raw, after = None, None, []
    for raw in tail_lines(tx):
        try:
            o = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(o, dict):
            continue
        if user_text(o) is not None:
            start, start_raw, after = user_text(o), raw, []
        elif start is not None:
            after.extend(tool_calls(o))
    if start is None:
        return None
    m = HEADER.match(start)
    if not m:
        return None
    body = m["body"]
    if ACK.match(body) or NO_REPLY.search(body):
        return None
    names = {m["id"].lower(), (m["aka"] or "").strip().lower()} - {""}
    if answered_by_relay(after, names):
        return None
    session = re.sub(r"[^\w.-]", "_", str(data.get("session_id") or "default"))[:80]
    key = turn_key(start_raw)
    if already_nudged(session, key):
        return None
    return session, key, (
        "You answered a relayed message in prose; the sender does not see it. "
        f'Reply with relay.py {m["id"]} "<text>" (the header names the route).')


def main():
    if os.environ.get("RELAY_PROSE_NUDGE_OFF"):
        return
    try:
        res = decide(json.load(sys.stdin))
        if res:
            session, key, text = res
            try:
                remember(session, key)
            except OSError:
                return    # a nudge we cannot record would repeat on every Stop: stay silent
            print(json.dumps({"decision": "block", "reason": text}))
    except Exception:  # noqa: BLE001 - a hook must never break a turn
        return


if __name__ == "__main__":
    main()
    sys.exit(0)
