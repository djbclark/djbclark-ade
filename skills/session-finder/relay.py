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
    reached with `paseo send <id> --behavior steer`, run without PASEO_AGENT_ID so it is plain text like
    the operator's (bin/self-slash does the same). `--idle S` waits up to S seconds for it to go idle
    first (`paseo wait`); another TUI that is working is refused without it. Delivery is what the daemon
    acknowledges, upgraded to "delivered" once a Claude transcript shows the text (2026-10-20).
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

Exit: 0 delivered or queued (verified), 1 refused or unverified, 2 usage.
"""
import argparse
import json
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
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
PASEO_OWN_ENV = ("PASEO_AGENT_ID", "PASEO_AGENT_CWD")
UNSENT = Path(os.environ.get("RELAY_UNSENT", Path.home() / ".local/state/session-finder/relay-unsent.json"))


def paseo_run(*args, timeout=30):
    """(rc, stdout, stderr) of the paseo CLI ($PASEO_CLI, else PATH) with this agent's own PASEO_AGENT_ID
    unset: an agent-originated send is wrapped in a "[Message received] <parent>" envelope and reaches
    Claude as plain text, so a relay would not read as the operator's message (bin/self-slash, 2026-10-19)."""
    cli = os.environ.get("PASEO_CLI") or shutil.which("paseo")
    if not cli:
        return 127, "", "no paseo CLI (PASEO_CLI unset, none on PATH)"
    env = {k: v for k, v in os.environ.items() if k not in PASEO_OWN_ENV}
    try:
        p = subprocess.run([cli, *args], capture_output=True, text=True, timeout=timeout, env=env, check=False)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, "", str(e)


def paseo_session(agent_id):
    """A session record for Paseo agent AGENT_ID straight from `paseo agent inspect`, or None when Paseo does
    not know it. For an agent fleet.sessions() does not list (not a Claude Code TUI, or no registry entry)."""
    rc, out, _ = paseo_run("agent", "inspect", agent_id, "--json")
    try:
        info = json.loads(out) if rc == 0 else None
    except ValueError:
        info = None
    if not isinstance(info, dict) or info.get("Id") != agent_id:
        return None
    state = info.get("Status") or "unknown"
    return fleet._rec(id=agent_id[:8], agent=info.get("Provider") or "paseo", name=info.get("Name") or "",
                      cwd=info.get("Cwd") or "", host="paseo", chan=("paseo", agent_id), paseo=agent_id,
                      paseo_state=state, status={"idle": "idle", "running": "working"}.get(state, state),
                      self=agent_id == os.environ.get("PASEO_AGENT_ID"), where=f"host=paseo agent={agent_id}")


def paseo_idle(s, seconds):
    """Wait up to SECONDS for Paseo agent S to go idle (`paseo wait`); True when it is."""
    if s.get("status") == "idle":
        return True
    rc = paseo_run("wait", s["chan"][1], "--timeout", str(max(1, int(seconds))), "--json", timeout=seconds + 15)[0]
    if rc == 0:
        s["status"] = "idle"
    return rc == 0


def send_paseo(s, text, wait):
    """Send TEXT to Paseo agent S: 'delivered' (seen in its Claude transcript), 'accepted' (the daemon took
    it) or None (send failed; the reason is printed). --behavior steer so a turn that began meanwhile is
    never torn down; --no-wait so this returns at once (the transcript poll below is the verification)."""
    agent = s["chan"][1]
    tx = Path(s["transcript"]) if s.get("transcript") else None
    mark = tx.stat().st_size if tx and tx.is_file() else 0
    rc, out, err = paseo_run("send", agent, "--no-wait", "--behavior", "steer", "--json", text)
    if rc != 0:
        print(f"relay: [{s['id']}] paseo send to {agent} failed (rc={rc}): {fleet.clip((err or out).strip(), 200)}",
              file=sys.stderr)
        return None
    probe = json.dumps(text[:40], ensure_ascii=False)[1:-1]
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
    text = " ".join(a.text.split())
    if not text:
        print("relay: empty text", file=sys.stderr)
        return 2
    hits = find(a.ident, fleet.sessions())
    if not hits and UUID.match(a.ident):
        hits = [s for s in [paseo_session(a.ident)] if s]    # a PASEO_AGENT_ID fleet does not list
    if len(hits) != 1:
        print(f"relay: {'no' if not hits else len(hits)} session(s) match {a.ident!r} (fleet.py list shows ids and names)",
              file=sys.stderr)
        return 1
    s = hits[0]
    if s.get("host") == "paseo" and a.idle and not s.get("self") and not paseo_idle(s, a.idle):
        print(f"relay: [{s['id']}] not sent: its Paseo agent is still running after {a.idle:g}s", file=sys.stderr)
        return 1
    why = refusal(s)
    if why:
        print(f"relay: [{s['id']}] not sent: {why}", file=sys.stderr)
        return 1
    chan = tuple(s["chan"])
    if chan[0] == "paseo":
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
