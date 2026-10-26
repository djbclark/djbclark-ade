#!/usr/bin/env python3
"""relay_prose_nudge.py: Stop hook. A relayed message answered only in prose reaches nobody.

Standing order 10 (AGENTS.md, 2026-10-25): a message from a peer is answered with `relay.py ID "<text>"`, never in the
receiver's own prose; the sender sees only what relay.py sends. The skill text (skills/session-finder/SKILL.md, "Verified
peer messaging") says so and nothing enforced it. This hook does, softly.

When a turn ends (Stop) and
  1. the turn began with a user message from a relay sender, in one of the two shapes skills/session-finder/relay.py writes:
     the header at the very start, `[relay from KIND ID (DIR)]` or `[relay from KIND ID aka NAME (DIR)]` (`sender_tag` /
     `forced_tag`: the pane, inbox and Paseo routes); or, on the socket route, NO header but the envelope `socket_send`
     wraps the text in, `<cross-session-message from="relay.py" from-name="relay.py (LABEL)" from-mode=...>`, where LABEL
     is the text the header would carry: the hook reads it as the header (the closing tag is dropped from the end only).
     A deferred send's `[queued Nm ago] ` tag follows the header (or the envelope) and is skipped. A message with neither
     (Paseo's own label for a Paseo-hosted sender, a non-relay envelope) is not read, and
  2. the turn made no relay.py call (a Bash tool call whose command contains `relay.py`) and no SendMessage call to that
     sender (its `to` equals the header's ID or `aka` name), and
  3. the text asks for an answer (SKILL item 4: a question or a request for action): it ends with relay's own
     `[reply through relay.py to ID: ack X]` footer or `[first contact from ID: ...]` footer, or it has a `?` outside a URL
     (relay.py `asks_for_reply`'s detector) and nothing shows relay enforced footers on this sender. relay refuses a `?`
     text without the reply footer or `--fyi` only when it found the sender's own fleet row, and only a herdr pane has one:
     that sender's header has a herdr pane id (`w2F:p45`) and a `(DIR)` suffix, so its footer-less `?` text is a `--fyi`
     text and stays silent. Every other header (a Paseo uuid, a session-id prefix, `hermes TAIL`, a pane id with no
     `(DIR)`) says nothing about footers (`(DIR)` is written whenever the sender's cwd exists, row or not), so its `?` is
     the only signal there is and counts; a `--fyi` question from such a sender is then nudged once (accepted, the ID
     must also be a usable route shape),
it prints `{"decision": "block", "reason": "<nudge>"}`, which is how a Stop hook hands text to the model: the session
continues one more step; the nudge names the route and says to end the turn if the text needs no answer.

Never nudged: a statement, "noted, thanks" or "received" (no question, no footer); a relayed text that asks for no reply
(`ack <ID>` with or without an answer after it as long as the text has no `?` outside a URL, a text starting with FYI, one
starting or ending `no reply needed` or ending `no need to reply` / `no response needed`; relay's reply footer overrides
these), so acks and acks of acks never provoke more messages; a header with no usable ID (a declared label such as
`load watch`); a second Stop for the same relayed message (a state file per session remembers the turn's key, and Claude
Code's own `stop_hook_active` flag also ends it); anything unreadable.

Known limit: an `ack ...` text (or one starting `no reply needed`) that goes on to ask for an action without a `?` (`ack the
status please`, `No reply needed on the log, but please merge PR 14 now`) is read as an ack and is not nudged, also under a
first-contact footer. The fix is one shared definition with relay's `is_terminator` (branch feat/relay-ack-default), after that
merges (docs/queue.md, "Verified peer messaging").

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

# The label skills/session-finder/relay.py `sender_label` writes, in a `[relay from ...]` header and in the socket envelope's
# `from-name="relay.py (LABEL)"`: `KIND ID (aka NAME)? ((DIR))?`. Every part is in relay's own sanitised charset, so a declared
# label with spaces (`load watch`), a hand-typed `Dann 5 (lead, x)` or an id with shell characters never parses; the id is
# copied into the model's instructions, so its charset is the safe one. `aka` and `DIR` also take `…` (U+2026):
# `sender_label` clips a long name with fleet.clip, which prefixes one.
LABEL_CORE = (r"(?P<kind>[A-Za-z0-9._-]{1,16}) (?P<id>[A-Za-z0-9:._-]{1,40})"
              r"(?: aka (?P<aka>[A-Za-z0-9._ …-]{1,40}))?(?: \((?P<dir>[A-Za-z0-9._…-]{1,48})\))?")
LABEL = re.compile(LABEL_CORE)
HEADER = re.compile(rf"^\s*\[relay from {LABEL_CORE}\]\s*(?P<body>.*)$", re.S)
# relay.py `socket_send`: `<cross-session-message from="relay.py" from-name="relay.py ({sender})" from-mode="bypass">\nBODY\n</...>`,
# with NO `[relay from]` header in BODY (`route_socket` passes the bare text).
ENVELOPE = re.compile(r"^\s*<cross-session-message\b(?P<attrs>[^>]*)>\s*(?P<body>.*)$", re.S)
FROM_NAME = re.compile(r'\bfrom-name="relay\.py \((?P<label>[^"]{1,200})\)" from-mode="')
WRAP_END = "</cross-session-message>"
# The deferred deliverer re-runs main with `[queued Nm ago] ` before the stored text (relay.py `--deliver`), so it follows the header.
QUEUED = re.compile(r"\[queued [^\]]*\]\s*")
# A herdr pane id: the only sender kind with a fleet self row, hence the only one relay enforces footers on. A header names an
# answerable sender only with a `(DIR)` suffix or a usable ID shape: a pane id, a session-id hex prefix or uuid (a Paseo agent
# id), or, for kind `hermes`, relay's `HERMES_SENDER` tail (`hermes ` and the last 8 characters of HERMES_SESSION_ID).
PANE_ID = re.compile(r"w[A-Za-z0-9]+:p\d+")
ID_SHAPE = re.compile(r"w[A-Za-z0-9]+:p\d+|[0-9a-fA-F]{6,}(?:-[0-9a-fA-F]+)*")
HERMES_TAIL = re.compile(r"[A-Za-z0-9_-]{1,8}")
# relay.py appends exactly one of these, last, to the texts that want an answer (relay.py main(): `--expect-ack`, first
# contact), so each is read only at the END of the body (a quoted one earlier decides nothing). The charsets are relay's own:
# EXPECT_ID for the `ack` token, the sender id's for the route.
REPLY_MARK = "[reply through relay.py to "
REPLY_FOOTER = re.compile(r"\[reply through relay\.py to [A-Za-z0-9:._-]+: ack (?P<tok>[A-Za-z0-9][A-Za-z0-9._-]{0,39})\]")
FIRST_MARK = "[first contact from "
FIRST_CONTACT = re.compile(r"\[first contact from (?P<id>[A-Za-z0-9:._-]+): reply `ack [^\]]*\]")
# Copied from skills/session-finder/relay.py (URL_RE, asks_for_reply: relay.py is a heavy import for a hook with a 2 s deadline),
# with the scheme bounded: relay's `[a-z0-9+.-]*` is quadratic on `a-a-a-...` (15 KB takes seconds, the hook deadline is 2 s).
URL_RE = re.compile(r"\b[a-z][a-z0-9+.-]{0,31}://\S+", re.I)
# Exemptions: a text that is itself an `ack <ID>`, starts with FYI, or starts or ends with `no reply needed` (or ends `no need to
# reply`, `no response needed`). Anchored, so a quote of one inside a real question ("you wrote `no reply needed`, but ...?") or
# `fyi-digest` exempts nothing.
NO_REPLY_PHRASE = r"no[ -]reply[ -](?:needed|required|necessary|expected)"
NO_REPLY_END = r"no[ -](?:need[ -]to[ -]reply|response[ -](?:needed|required|necessary|expected))"
NO_REPLY = re.compile(rf"^\W*{NO_REPLY_PHRASE}|{NO_REPLY_PHRASE}\W*$|{NO_REPLY_END}\W*$|^\W*FYI\b(?![-_])", re.I)
# `ack TOKEN` ended by end of text, `, . ; : !`, ` - `, ` — ` or a bracket: the shapes of an ack that carries an answer
# (`ack q1: 3a24fdc.`). `Ack the status?`, `ack, but ...?`, `ACK? ...`, `acknowledge ...` are not. (Not relay's `ack_token`,
# whose tail is free: it would exempt `Ack the status?`.) An ack with a `?` outside a URL is never an ack (reply_token).
ACK = re.compile(r"^\s*ack\s+[A-Za-z0-9:._-]+?\s*(?:$|[,.;:!]|\s[-—]|\[)", re.I)
# `ack TOKEN` followed by anything: with the first-contact footer only (see reply_token) and no `?` it is still an ack.
ACK_BARE = re.compile(r"^\s*ack\s+[A-Za-z0-9:._-]+\s", re.I)


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


def split_footer(body):
    """(text before relay's footer, "reply" | "first" | None, the footer's token). relay appends one footer, last: only a footer
    at the very end counts, found with `rfind` and one `fullmatch` (linear, whatever the body holds)."""
    i = body.rfind(REPLY_MARK)
    if i >= 0:
        r = REPLY_FOOTER.fullmatch(body[i:].rstrip())
        if r:
            return body[:i], "reply", r["tok"]
    i = body.rfind(FIRST_MARK)
    if i >= 0:
        f = FIRST_CONTACT.fullmatch(body[i:].rstrip())
        if f:
            return body[:i], "first", f["id"]
    return body, None, None


def usable_id(kind, sid):
    """True when SID is a shape relay writes as a route: a herdr pane id, a session-id hex prefix or uuid, or a Hermes tail."""
    return bool(ID_SHAPE.fullmatch(sid) or (kind == "hermes" and HERMES_TAIL.fullmatch(sid)))


def parse_start(text):
    """(the label's match, the body after it) for a turn-starting TEXT that relay.py sent, else None: a `[relay from ...]` header at
    the start, or the socket envelope's `from-name` label (the body then carries no header)."""
    env = ENVELOPE.match(text)
    if env:
        f = FROM_NAME.search(env["attrs"])
        m = LABEL.fullmatch(f["label"]) if f else None
        body = env["body"].rstrip()
        if body.endswith(WRAP_END):    # the closing tag follows relay's footer; stripped there only, never from the middle
            body = body[:-len(WRAP_END)].rstrip()
        return (m, body) if m else None
    m = HEADER.match(text)
    return (m, m["body"].rstrip()) if m else None


def reply_token(body, sender_id, q_counts):
    """The `ack` token the sender expects when BODY wants an answer (a question or request for action, SKILL item 4), else None.
    Wants one: relay's own `[reply through relay.py to ID: ack X]` footer (X), its `[first contact from ID: ...]` footer
    (the sender's ID), or, when Q_COUNTS, a `?` outside a URL (the header ID). The reply footer overrides every exemption; the
    exemptions (an `ack <ID>` text without a `?`, `no reply needed`, FYI) silence the other two, so acks and acks of acks never
    provoke messages. Q_COUNTS is False only for a herdr pane sender with a `(DIR)` (see the module docstring): relay refuses a
    `?` text there unless it carries the reply footer or `--fyi`, so a footer-less `?` text is a `--fyi` text or a NOTICE."""
    plain, kind, tok = split_footer(body)
    if kind == "reply":
        return tok
    stripped = URL_RE.sub(" ", plain)
    question = "?" in stripped
    if NO_REPLY.search(plain) or (not question and ACK.match(plain)):
        return None
    if kind == "first":
        # `ack q1 3a24fdc`: an ack that answers (a bare space after the token) is exempt only without a `?`, so the question
        # `Ack the status? ...` is not swallowed.
        return None if ACK_BARE.match(plain) and not question else tok
    return sender_id if q_counts and question else None


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
    parsed = parse_start(start)
    if not parsed:
        return None
    m, body = parsed
    has_dir = bool(m["dir"])
    if not (has_dir or usable_id(m["kind"], m["id"])):
        return None
    q = QUEUED.match(body)
    if q:
        body = body[q.end():]
    # `?` counts unless relay enforced footers on this sender: a herdr pane id with a `(DIR)`. Any other ID must be a usable route.
    q_counts = usable_id(m["kind"], m["id"]) and not (has_dir and PANE_ID.fullmatch(m["id"]))
    token = reply_token(body, m["id"], q_counts)
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
