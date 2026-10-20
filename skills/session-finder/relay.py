#!/usr/bin/env python3
"""relay — type a one-line message into a running agent's terminal, when SendMessage cannot reach it. No model.

    relay.py <id|name|sid|pane|paseo-agent-id> "<text>" [--wait S] [--idle S] [--json]
                                           (pane: a herdr pane id such as w34:p4; a Paseo agent id is the
                                           PASEO_AGENT_ID uuid, as `paseo ls -g` and where.py show it)

The fallback for session-finder's rung 3a (2026-10-11): a workflow sub-agent's ListAgents often lists only
its teammates, so `SendMessage({to: "<name>"})` to a running Claude TUI fails with "No agent named … is
reachable" (q-shizuku relay). This types the text into the session's own pane instead (herdr `pane
send-text` + `agent send-keys enter`, Orca `terminal send`, tmux `send-keys`), the same channel helm uses.

  * Claude Code queues text typed while it works ("Press up to edit queued messages") and takes it at its
    next tool round, so a working Claude session is fine; an idle one gets it as its next prompt.
  * Other TUIs: idle only (keys into a working codex/opencode/... are not reliably queued).
  * A Paseo-hosted agent (where: `host=paseo agent=<id>`; Paseo's daemon spawns it, so it has no pane) is
    reached with `paseo send --behavior steer -- <id> <text>`. The caller's own PASEO_AGENT_ID stays in
    the child's environment, so Paseo labels the message `kind="agent-message"` with the sender: the
    receiving agent sees a peer, never the operator's turn. A caller that is not a Paseo agent prefixes
    the text with `[relay from <name>] ` (Paseo can label only an agent sender). Steer queues the text
    for the next tool round on Claude; when a provider cannot steer, Paseo replaces the running turn.
    Right before sending (and again after an `--idle` wait) `paseo agent inspect` must show the agent
    unarchived, with no pending permission or question (helm or the Paseo UI answers those), idle or
    running, with the id asked for. Text starting with `/` is refused (exit 2): peers do not run another
    session's built-ins. `--idle S` (finite, > 0) waits up to S seconds for it to go idle first
    (`paseo wait`); another TUI that is working is refused without it. Delivery is what the daemon
    acknowledges ("accepted"), upgraded to "delivered" once a Claude transcript shows the text
    (2026-10-20).
  * Refused: this session; an ACP launch (`launch.py reply` is its channel); a finished session (`/handoff`
    or `/quit`: start a /baton session instead); one blocked on a question or permission (`helm.py answer`);
    one with no channel (Ghostty/iTerm/headless: say its `where:` line); and any input box that already
    holds a draft (someone is typing there; Claude Code's dim/grey suggested prompt is not one: prompt_line.py).
  * Verified, never assumed: a Claude session counts as delivered once the text shows up in its transcript
    (a queued message is recorded as a queue-operation at once), else as queued once the pane shows it.
  * Enter goes in ENTER_DELAY after the text, and again (up to ENTER_RETRIES times) while the text still
    sits in a Claude input box: sent in one burst it reads as a paste and does not submit (2026-10-18).
  * One line: newlines are folded to spaces (an Enter would submit half the message). For a long brief,
    write it to a file and relay one line that names the file's absolute path.

Exit: 0 delivered or queued (verified in the transcript or pane) or, for a Paseo agent, accepted (the daemon's
acknowledgement, not a verified delivery); 1 refused or unverified; 2 usage.
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fleet  # noqa: E402
import prompt_line  # noqa: E402
import where  # noqa: E402

HERDR = fleet.HERDR
# Pause between the text and its Enter (2026-10-18): sent back to back, Claude Code reads the burst as a
# paste and the Enter inside it does not submit, so the message sat in the input box until the operator
# pressed Enter by hand. ENTER_RETRIES more Enters go in when the text is still in the box after RETRY_AFTER s.
ENTER_DELAY = 0.5
ENTER_RETRIES = 2
RETRY_AFTER = 2.0
# Messages this relay typed whose Enter never landed, per session id. A later relay to that session finds the
# text in the input box and used to refuse it as someone's draft (2026-10-18: a proposal to djbclark-ade-87
# sat unsent there and blocked the next relay); now it submits its own leftover first.
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# Paseo XML-escapes a message's text inside its <paseo-system> label (agent-messages/index.js escapeXml)
XML_ESCAPES = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;"}
UNSENT = Path(os.environ.get("RELAY_UNSENT", Path.home() / ".local/state/session-finder/relay-unsent.json"))


def paseo_run(*args, timeout=30):
    """(rc, stdout, stderr) of the paseo CLI ($PASEO_CLI, else PATH). The caller's own PASEO_AGENT_ID and
    PASEO_AGENT_CWD stay in the child's environment on purpose: `paseo send` turns PASEO_AGENT_ID into the
    sender, and the daemon then labels the message kind="agent-message" with that agent's id, so the
    receiver sees a peer's message, not the operator's (adversary, 2026-10-20). stdin is closed: the CLI
    must never prompt on an inherited terminal."""
    cli = os.environ.get("PASEO_CLI") or shutil.which("paseo")
    if not cli:
        return 127, "", "no paseo CLI (PASEO_CLI unset, none on PATH)"
    if not os.access(cli, os.X_OK):
        return 127, "", f"paseo CLI {cli} is not executable"
    try:
        p = subprocess.run([cli, *args], capture_output=True, text=True, timeout=timeout, check=False,
                           stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, "", str(e)


def paseo_inspect(agent_id):
    """`paseo agent inspect` of AGENT_ID as a dict, or None when Paseo does not know it (or the id differs:
    the reply must name exactly the agent asked for). `--` ends the options: an id is never an option."""
    if not UUID.fullmatch(agent_id or ""):
        return None
    rc, out, _ = paseo_run("agent", "inspect", "--json", "--", agent_id)
    try:
        info = json.loads(out) if rc == 0 else None
    except ValueError:
        info = None
    if not isinstance(info, dict) or info.get("Id") != agent_id:
        return None
    return info


def paseo_blocker(info):
    """Why a Paseo agent whose `inspect` is INFO must not be sent text, or None. A send unarchives an archived
    agent, and on a steer Paseo denies every pending permission card with the sent text as the answer."""
    state = info.get("Status") or "unknown"
    if info.get("Archived"):
        return "its Paseo agent is archived (a send would unarchive it and start a turn)"
    if info.get("PendingPermissions"):
        return "blocked on a permission or question: typed text would answer it (helm / the Paseo UI answers it)"
    if state not in ("idle", "running"):
        return f"its Paseo agent is {state}, not idle or running"
    return None


def paseo_cwd_mismatch(s, info):
    """True when session S's process (pid known) runs in a different directory than Paseo's agent says: the
    PASEO_AGENT_ID -> pid mapping is then not trusted (an env a same-user process can forge)."""
    if not s.get("pid") or not info.get("Cwd"):
        return False
    proc = where.real_cwd(s["pid"])
    if not proc:
        return False    # lsof could not read it: nothing to compare
    return os.path.realpath(proc) != os.path.realpath(os.path.expanduser(info["Cwd"]))


def paseo_gate(s):
    """Re-inspect Paseo agent S right before a send. Refreshes S's status; returns the refusal or None."""
    agent = s["chan"][1] if s.get("chan") else s.get("paseo")
    info = paseo_inspect(agent)
    if info is None:
        return f"`paseo agent inspect` does not confirm Paseo agent {agent}"
    why = paseo_blocker(info)
    if why:
        s["paseo_state"] = info.get("Status") or "unknown"
        return why
    if paseo_cwd_mismatch(s, info):
        return f"its process directory differs from Paseo agent {agent}'s ({info.get('Cwd')}): mapping not trusted"
    state = info["Status"]
    s["paseo_state"], s["status"] = state, {"idle": "idle", "running": "working"}[state]
    return None


def paseo_is_self(agent_id):
    """True when AGENT_ID is the Paseo agent this process runs in: the PASEO_AGENT_ID it was handed, or
    (a child env scrubbed of it) the agent hosting one of its ancestors."""
    if agent_id == os.environ.get("PASEO_AGENT_ID"):
        return True
    return any(where.paseo_agent(pid, where.env_of(pid)) == agent_id for pid in fleet.ancestors())


def paseo_session(agent_id):
    """A session record for Paseo agent AGENT_ID straight from `paseo agent inspect`, or None when Paseo does
    not know it. For an agent fleet.sessions() does not list (not a Claude Code TUI, or no registry entry)."""
    info = paseo_inspect(agent_id)
    if info is None:
        return None
    state = info.get("Status") or "unknown"
    return fleet._rec(id=agent_id[:8], agent=info.get("Provider") or "paseo", name=info.get("Name") or "",
                      cwd=info.get("Cwd") or "", host="paseo", chan=("paseo", agent_id), paseo=agent_id,
                      paseo_state=state, status={"idle": "idle", "running": "working"}.get(state, state),
                      self=paseo_is_self(agent_id), where=f"host=paseo agent={agent_id}")


def paseo_idle(s, seconds):
    """Wait up to SECONDS for Paseo agent S to go idle (`paseo wait`); True when it is."""
    if s.get("status") == "idle":
        return True
    rc = paseo_run("wait", "--timeout", str(max(1, int(seconds))), "--json", "--", s["chan"][1],
                   timeout=seconds + 15)[0]
    if rc == 0:
        s["status"] = "idle"
    return rc == 0


def sender_tag(listed):
    """'[relay from NAME] ' for a caller that is not a Paseo agent (Paseo labels only an agent sender): the
    caller's session name, else the first 8 characters of its session id."""
    if UUID.fullmatch((os.environ.get("PASEO_AGENT_ID") or "").strip()):
        return ""    # a real agent id: Paseo labels the message itself (an empty or junk value does not count)
    me = next((x for x in listed if x.get("self")), None) or {}
    name = me.get("name") or me.get("id") or (os.environ.get("CLAUDE_CODE_SESSION_ID") or "")[:8] or "unknown"
    return f"[relay from {fleet.clip(re.sub(r'[^A-Za-z0-9._ -]', '', name), 40) or 'unknown'}] "


def send_paseo(s, text, wait):
    """Send TEXT to Paseo agent S: 'delivered' (seen in its Claude transcript), 'accepted' (the daemon took
    it; not a verified delivery) or None (send failed; the reason is printed). --behavior steer queues the text
    for the next tool round on Claude; a provider that cannot steer has its running turn replaced by
    Paseo, so the caller already refused anything that starts a built-in. --no-wait so this returns at once
    (the transcript poll below is the verification); `--` keeps TEXT, whatever it starts with, out of the options."""
    agent = s["chan"][1]
    tx = Path(s["transcript"]) if s.get("transcript") else None
    mark = tx.stat().st_size if tx and tx.is_file() else 0
    rc, out, err = paseo_run("send", "--no-wait", "--behavior", "steer", "--json", "--", agent, text)
    if rc != 0:
        print(f"relay: [{s['id']}] paseo send to {agent} failed (rc={rc}): {fleet.clip((err or out).strip(), 200)}",
              file=sys.stderr)
        return None
    # the daemon XML-escapes the text inside its label and the transcript stores that JSON-escaped
    escaped = "".join(XML_ESCAPES.get(c, c) for c in text[:40])
    probe = json.dumps(escaped, ensure_ascii=False)[1:-1]
    deadline = time.time() + wait
    while tx and tx.is_file() and time.time() < deadline:
        with tx.open("rb") as fh:
            fh.seek(mark)
            if probe in fh.read().decode("utf-8", "replace"):
                return "delivered"
        time.sleep(1)
    return "accepted"


def screen(chan, lines=20):
    kind, target = chan
    if kind == "herdr":
        out = fleet.run(HERDR, "pane", "read", target, "--source", "visible", "--lines", str(lines))[1]
    elif kind == "orca":
        out = fleet.run("orca", "terminal", "read", "--terminal", target)[1]
    elif kind == "tmux":
        out = fleet.run("tmux", "capture-pane", "-p", "-t", target)[1]
    else:
        return ""
    rows = [ln.rstrip() for ln in out.splitlines() if ln.strip()]
    return "\n".join(rows[-lines:])


def draft(chan):
    """Text typed but not sent in a Claude Code input box (its prompt line starts with ❯).

    Read with ANSI codes where the channel has them: Claude Code's suggested next prompt (ghost text that
    anything typed replaces) and its hints are dim or grey, not a draft (prompt_line.py; 2026-10-16 a dim
    suggestion was refused as a draft)."""
    kind, target = chan
    if kind == "herdr":
        out = fleet.run(HERDR, "agent", "read", target, "--source", "visible", "--lines", "14", "--format", "ansi")[1]
    elif kind == "tmux":
        out = fleet.run("tmux", "capture-pane", "-p", "-e", "-t", target)[1]
    else:
        out = screen(chan, 14)
    return prompt_line.classify("\n".join(out.splitlines()[-14:])) or ""


def press_enter(chan):
    kind, target = chan
    if kind == "herdr":
        return fleet.run(HERDR, "agent", "send-keys", target, "enter")[0] == 0
    if kind == "tmux":
        return fleet.run("tmux", "send-keys", "-t", target, "Enter")[0] == 0
    return False


def type_line(chan, text):
    kind, target = chan
    if kind == "herdr":
        if fleet.run(HERDR, "pane", "send-text", target, text)[0] != 0:
            return False
    elif kind == "orca":
        return fleet.run("orca", "terminal", "send", "--terminal", target, "--text", text, "--enter", timeout=20)[0] == 0
    elif kind == "tmux":
        if fleet.run("tmux", "send-keys", "-t", target, "-l", text)[0] != 0:
            return False
    else:
        return False
    time.sleep(ENTER_DELAY)
    return press_enter(chan)


def stuck_in_box(chan, text):
    """True while TEXT still sits unsent in a Claude Code input box: its Enter did not land."""
    d = " ".join(draft(chan).split())
    # A long burst can be collapsed into a "[Pasted text #N +M lines]" placeholder, which never matches
    # the text itself; with no other draft possible right after our own typing, it is ours (2026-10-18).
    return bool(d) and (d[:30] == text[:30] or d.startswith("[Pasted text"))


def _unsent():
    try:
        return json.loads(UNSENT.read_text())
    except (OSError, ValueError):
        return {}


def note_unsent(sid, text):
    """Remember TEXT as left unsent in session SID's box (None forgets it)."""
    rows = _unsent()
    if text is None:
        if rows.pop(sid, None) is None:
            return
    else:
        rows[sid] = text
    UNSENT.parent.mkdir(parents=True, exist_ok=True)
    tmp = UNSENT.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False))
    tmp.replace(UNSENT)


def ours(d, text):
    """True when draft D is (the visible part of) TEXT, which this relay typed earlier."""
    d, t = " ".join(d.split()), " ".join((text or "").split())
    if not d or not t:
        return False
    return d[:30] == t[:30] or d[-30:] in t or d.startswith("[Pasted text")


def find(ident, ss):
    hits = [s for s in ss if ident in (s["id"], s["name"], s.get("sid"), s.get("pane"), s.get("paseo"))]
    if not hits and len(ident) >= 8:
        hits = [s for s in ss if (s.get("sid") or "").startswith(ident)]
    return hits


def refusal(s):
    """Why text must not be typed into session S, or None."""
    if s.get("self"):
        return "that is this session"
    if s.get("host") == "acp":
        return f"an ACP launch: use launch.py reply {s['id']} \"<text>\" (its inbox), never keys"
    if s.get("finished"):
        return (f"finished ({s['finished']}): never continue there; start a fresh session from its handoff "
                "(session-finder rung 3b, launch.py --baton)")
    if s.get("host") == "paseo" and s.get("paseo_state") not in (None, "idle", "running"):
        return f"its Paseo agent is {s['paseo_state']}, not idle or running"
    if not s.get("chan"):
        rec = fleet.dispatch_record(s.get("sid"))
        if rec:
            return f"a headless acp-dispatch slice (no pane): acp-dispatch tell {rec} \"<text>\""
        return (f"no terminal channel ({s.get('where') or 'unknown terminal'}); tell the operator its where: line. "
                "If it runs under Paseo (a PASEO_AGENT_ID it was handed, or `paseo ls -g`), pass that agent id as the ident")
    st = s.get("status")
    if st == "blocked":
        return "blocked on a question or permission prompt: typed text would land in that dialog (helm.py answer)"
    if s["agent"] != "claude" and st != "idle":
        return f"a {s['agent']} TUI that is {st}: only idle ones take typed text reliably"
    return None


def main():
    ap = argparse.ArgumentParser(prog="relay.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ident")
    ap.add_argument("text")
    ap.add_argument("--wait", type=float, default=20, help="seconds to verify delivery (default 20)")
    ap.add_argument("--idle", type=float, metavar="S", help="Paseo agents: wait up to S seconds for it to go idle first")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.idle is not None and not (math.isfinite(a.idle) and a.idle > 0):
        print("relay: --idle must be a finite number of seconds > 0", file=sys.stderr)
        return 2
    text = " ".join(a.text.split())
    if not text:
        print("relay: empty text", file=sys.stderr)
        return 2
    listed = fleet.sessions()
    hits = find(a.ident, listed)
    if not hits and UUID.fullmatch(a.ident):
        hits = [s for s in [paseo_session(a.ident)] if s]    # a PASEO_AGENT_ID fleet does not list
    if len(hits) != 1:
        print(f"relay: {'no' if not hits else len(hits)} session(s) match {a.ident!r} (fleet.py list shows ids and names)",
              file=sys.stderr)
        return 1
    s = hits[0]
    is_paseo = s.get("host") == "paseo" or (s.get("chan") or (None,))[0] == "paseo"
    if is_paseo:
        if text.lstrip(" \t\r\n\u00a0\u200b\u200c\u200d\u2060\ufeff").startswith(("/", "\uff0f")):
            # Paseo trims the prompt (JS trim, which drops U+FEFF) before its slash-command parser: strip the same
            # and the zero-width characters first, and refuse the full-width slash too (adversary round 2)
            print(f"relay: [{s['id']}] not sent: text starting with '/' would run a built-in; peers do not run another "
                  "session's built-ins", file=sys.stderr)
            return 2
        if not s.get("self"):
            why = paseo_gate(s)
            if not why and a.idle and s["status"] != "idle":
                if not paseo_idle(s, a.idle):
                    print(f"relay: [{s['id']}] not sent: its Paseo agent is still running after {a.idle:g}s", file=sys.stderr)
                    return 1
                why = paseo_gate(s)    # it can have been archived or asked a question while we waited
            if why:
                print(f"relay: [{s['id']}] not sent: {why}", file=sys.stderr)
                return 1
    why = refusal(s)
    if why:
        print(f"relay: [{s['id']}] not sent: {why}", file=sys.stderr)
        return 1
    chan = tuple(s["chan"])
    if chan[0] == "paseo":
        text = sender_tag(listed) + text
        seen = send_paseo(s, text, a.wait)
        if not seen:
            return 1
        out = {"id": s["id"], "name": s["name"], "status": s["status"], "via": f"paseo {chan[1]}", "result": seen,
               "text": text}
        if a.json:
            print(json.dumps(out, ensure_ascii=False))
        else:
            when = "now" if s["status"] == "idle" else "steered into its running turn"
            print(f"relayed to [{s['id']}] {s['name']} via {out['via']}: {seen}; it takes the message {when}")
        return 0
    d = draft(chan) if s["agent"] == "claude" else ""
    left = _unsent().get(s["id"])
    if d and ours(d, left):
        press_enter(chan)
        for _ in range(10):
            time.sleep(1)
            d = draft(chan)
            if not d:
                break
        if not d:
            note_unsent(s["id"], None)
            print(f"relay: [{s['id']}] submitted our earlier message left unsent in its box", file=sys.stderr)
    if d:
        print(f"relay: [{s['id']}] not sent: its input box holds a draft ({fleet.clip(d, 60)!r})", file=sys.stderr)
        return 1
    tx = Path(s["transcript"]) if s.get("transcript") else None
    mark = tx.stat().st_size if tx and tx.is_file() else 0
    if not type_line(chan, text):
        print(f"relay: [{s['id']}] typing into {chan[0]} {chan[1]} failed", file=sys.stderr)
        return 1
    # the transcript stores the text JSON-escaped; match on a prefix of it
    probe = json.dumps(text[:40], ensure_ascii=False)[1:-1]
    seen, deadline = None, time.time() + a.wait
    typed_at, retries = time.time(), 0
    while time.time() < deadline:
        if tx and tx.is_file():
            with tx.open("rb") as fh:
                fh.seek(mark)
                if probe in fh.read().decode("utf-8", "replace"):
                    seen = "delivered"
                    break
        stuck = s["agent"] == "claude" and stuck_in_box(chan, text)
        if stuck and retries < ENTER_RETRIES and time.time() - typed_at >= RETRY_AFTER:
            press_enter(chan)
            typed_at, retries = time.time(), retries + 1
        scr = screen(chan, 30)
        # Claude Code's queue hint (not while our text is still in its input box: the hint may be for an
        # earlier message); for other TUIs the text on a line that is not the input prompt
        # (still on the ❯ line means Enter did not land)
        if (not stuck and "queued messages" in scr) or (s["agent"] != "claude" and any(
                text[:30] in ln and not ln.lstrip().startswith(("❯", ">")) for ln in scr.splitlines())):
            seen = seen or "queued"
            if not tx:
                break
        time.sleep(1)
    out = {"id": s["id"], "name": s["name"], "status": s["status"], "via": f"{chan[0]} {chan[1]}",
           "result": seen or "unverified", "text": text}
    if s["agent"] == "claude":
        note_unsent(s["id"], None if seen or not stuck_in_box(chan, text) else text)
    if a.json:
        print(json.dumps(out, ensure_ascii=False))
    elif seen:
        when = "now" if s["status"] == "idle" else "at its next tool round (it is working)"
        print(f"relayed to [{s['id']}] {s['name']} via {out['via']}: {seen}; it takes the message {when}")
    else:
        print(f"relay: [{s['id']}] text typed via {out['via']} but not seen in its transcript or pane within "
              f"{a.wait:g}s; check: {s.get('focus') or s.get('where')}", file=sys.stderr)
    return 0 if seen else 1


if __name__ == "__main__":
    sys.exit(main())
