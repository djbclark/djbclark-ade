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
     sender (its `to` equals the header's ID or `aka` name), and
  3. the text asks for an answer (SKILL item 4: a question or a request for action): it carries relay's own
     `[reply through relay.py to ID: ack X]` footer or `[first contact from ID: ...]` footer, or has a `?` outside a URL
     (relay.py `asks_for_reply`'s detector),
it prints `{"decision": "block", "reason": "<nudge>"}`, which is how a Stop hook hands text to the model: the session
continues one more step; the nudge names the route and says to end the turn if the text needs no answer.

Never nudged: a statement, "noted, thanks" or "received" (no question, no footer); a relayed text that asks for no reply
(`ack <ID>`, a text starting with FYI, one starting or ending `no reply needed`; relay's reply footer overrides these), so
acks and acks of acks never provoke more messages; a header with no usable ID (a declared label such as `load watch`);
a second Stop for the same relayed message (a state file per session remembers the turn's key, and Claude Code's own
`stop_hook_active` flag also ends it); anything unreadable.

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

# The header skills/session-finder/relay.py `sender_label` writes: `[relay from KIND ID (aka NAME)? ((DIR))?]`. Every part is
# in relay's own sanitised charset, so a declared label with spaces (`load watch`), a hand-typed `Dann 5 (lead, x)` or an id
# with shell characters never parses; the id is copied into the model's instructions, so its charset is the safe one.
HEADER = re.compile(
    r"^\s*(?:<cross-session-message\b[^>]*>\s*)?(?:\[queued [^\]]*\]\s*)?"
    r"\[relay from (?P<kind>[A-Za-z0-9._-]{1,16}) (?P<id>[A-Za-z0-9:._-]{1,40})"
    r"(?: aka (?P<aka>[A-Za-z0-9._ -]{1,40}))?(?: \((?P<dir>[A-Za-z0-9._-]{1,48})\))?\]\s*(?P<body>.*)$",
    re.S)
# A header names an answerable sender only with a `(DIR)` suffix (only `sender_label` writes one) or an ID shape: a herdr pane
# id, a session-id hex prefix or uuid (a Paseo agent id, `hermes SID8`).
ID_SHAPE = re.compile(r"w[A-Za-z0-9]+:p\d+|[0-9a-fA-F]{6,}(?:-[0-9a-fA-F]+)*")
# relay.py appends these to the texts that want an answer (relay.py main(): `--expect-ack`, first contact).
REPLY_FOOTER = re.compile(r"\[reply through relay\.py to [^\s\]]+: ack (?P<tok>[^\s\]]+)\]")
FIRST_CONTACT = re.compile(r"\[first contact from (?P<id>[A-Za-z0-9:._-]+): reply `ack ")
FIRST_CONTACT_TAIL = re.compile(r"\s*\[first contact from [^\]]*\]\s*$")
# Copied from skills/session-finder/relay.py (URL_RE, asks_for_reply: relay.py is a heavy import for a hook with a 2 s deadline).
URL_RE = re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.I)
# Exemptions: a text that is itself an `ack <ID>`, starts with FYI, or starts or ends with `no reply needed`. Anchored, so a
# quote of one inside a real question ("you wrote `no reply needed`, but ...?") or `fyi-digest` exempts nothing.
NO_REPLY_PHRASE = r"no[ -]reply[ -](?:needed|required|necessary|expected)"
NO_REPLY = re.compile(rf"^\W*{NO_REPLY_PHRASE}|{NO_REPLY_PHRASE}\W*$|^\W*FYI\b(?![-_])", re.I)
ACK = re.compile(r"^\s*ack\s+\S+\s*(?:$|[,.;]|\[)", re.I)


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


def block_text(c):
    """A content list's text blocks joined, or None when it carries a tool result (that is no prompt)."""
    if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
        return None
    return " ".join(str(b.get("text") or "") for b in c if isinstance(b, dict) and b.get("type") == "text")


def user_text(o):
    """The text of a transcript entry that is a user prompt (including a queued one, whose prompt is a string or a list of
    text blocks), else None: a tool result is no prompt, and a `<task-notification>` (a background task finished) is no new
    turn start, so the relayed message before it stays the turn's start."""
    if o.get("isMeta") or o.get("isCompactSummary") or o.get("isVisibleInTranscriptOnly"):
        return None
    text = None
    if o.get("type") == "user":
        m = o.get("message")
        c = m.get("content") if isinstance(m, dict) else None
        text = c if isinstance(c, str) else block_text(c) if isinstance(c, list) else None
    elif isinstance(o.get("attachment"), dict) and o["attachment"].get("type") == "queued_command":
        p = o["attachment"].get("prompt")
        text = p if isinstance(p, str) else block_text(p) if isinstance(p, list) else None
    if text is not None and text.lstrip().startswith("<task-notification"):
        return None
    return text


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


def reply_token(body, sender_id):
    """The `ack` token the sender expects when BODY wants an answer (a question or request for action, SKILL item 4), else None.
    Wants one: relay's own `[reply through relay.py to ID: ack X]` footer (X), its `[first contact from ID: ...]` footer
    (the sender's ID), or a `?` outside a URL (the header ID). The reply footer overrides every exemption; the exemptions
    (an `ack <ID>` text, `no reply needed`, FYI) silence the other two, so acks and acks of acks never provoke messages."""
    r = REPLY_FOOTER.search(body)
    if r:
        return r["tok"]
    plain = FIRST_CONTACT_TAIL.sub("", body)
    if ACK.match(plain) or NO_REPLY.search(plain):
        return None
    f = FIRST_CONTACT.search(body)
    if f:
        return f["id"]
    return sender_id if "?" in URL_RE.sub(" ", body) else None


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
    if not m or not (m["dir"] or ID_SHAPE.fullmatch(m["id"])):
        return None
    token = reply_token(m["body"], m["id"])
    if not token:
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
        f'Reply with relay.py {m["id"]} "<text>" (the header names the route). '
        f"If it needs no answer, end the turn; if it asks for one, start your relay reply with `ack {token}`.")


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
