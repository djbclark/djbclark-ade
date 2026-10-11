#!/usr/bin/env python3
"""relay — type a one-line message into a running agent's terminal, when SendMessage cannot reach it. No model.

    relay.py <id|name|sid> "<text>" [--wait S] [--json]

The fallback for session-finder's rung 3a (2026-10-11): a workflow sub-agent's ListAgents often lists only
its teammates, so `SendMessage({to: "<name>"})` to a running Claude TUI fails with "No agent named … is
reachable" (q-shizuku relay). This types the text into the session's own pane instead (herdr `pane
send-text` + `agent send-keys enter`, Orca `terminal send`, tmux `send-keys`), the same channel helm uses.

  * Claude Code queues text typed while it works ("Press up to edit queued messages") and takes it at its
    next tool round, so a working Claude session is fine; an idle one gets it as its next prompt.
  * Other TUIs: idle only (keys into a working codex/opencode/... are not reliably queued).
  * Refused: this session; an ACP launch (`launch.py reply` is its channel); a finished session (`/handoff`
    or `/quit`: start a /baton session instead); one blocked on a question or permission (`helm.py answer`);
    one with no channel (Ghostty/iTerm/headless: say its `where:` line); and any input box that already
    holds a draft (someone is typing there).
  * Verified, never assumed: a Claude session counts as delivered once the text shows up in its transcript
    (a queued message is recorded as a queue-operation at once), else as queued once the pane shows it.
  * One line: newlines are folded to spaces (an Enter would submit half the message). For a long brief,
    write it to a file and relay one line that names the file's absolute path.

Exit: 0 delivered or queued (verified), 1 refused or unverified, 2 usage.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fleet  # noqa: E402

HERDR = fleet.HERDR


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
    """Text typed but not sent in a Claude Code input box (its prompt line starts with ❯)."""
    for ln in reversed(screen(chan, 14).splitlines()):
        if ln.startswith("❯"):
            return ln[1:].strip()
    return ""


def type_line(chan, text):
    kind, target = chan
    if kind == "herdr":
        return (fleet.run(HERDR, "pane", "send-text", target, text)[0] == 0
                and fleet.run(HERDR, "agent", "send-keys", target, "enter")[0] == 0)
    if kind == "orca":
        return fleet.run("orca", "terminal", "send", "--terminal", target, "--text", text, "--enter", timeout=20)[0] == 0
    if kind == "tmux":
        return (fleet.run("tmux", "send-keys", "-t", target, "-l", text)[0] == 0
                and fleet.run("tmux", "send-keys", "-t", target, "Enter")[0] == 0)
    return False


def find(ident, ss):
    hits = [s for s in ss if ident in (s["id"], s["name"], s.get("sid"))]
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
    if not s.get("chan"):
        return f"no terminal channel ({s.get('where') or 'unknown terminal'}); tell the operator its where: line"
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
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    text = " ".join(a.text.split())
    if not text:
        print("relay: empty text", file=sys.stderr)
        return 2
    hits = find(a.ident, fleet.sessions())
    if len(hits) != 1:
        print(f"relay: {'no' if not hits else len(hits)} session(s) match {a.ident!r} (fleet.py list shows ids and names)",
              file=sys.stderr)
        return 1
    s = hits[0]
    why = refusal(s)
    if why:
        print(f"relay: [{s['id']}] not sent: {why}", file=sys.stderr)
        return 1
    chan = tuple(s["chan"])
    d = draft(chan) if s["agent"] == "claude" else ""
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
    while time.time() < deadline:
        if tx and tx.is_file():
            with tx.open("rb") as fh:
                fh.seek(mark)
                if probe in fh.read().decode("utf-8", "replace"):
                    seen = "delivered"
                    break
        scr = screen(chan, 30)
        # Claude Code's queue hint; for other TUIs the text on a line that is not the input prompt
        # (still on the ❯ line means Enter did not land)
        if "queued messages" in scr or (s["agent"] != "claude" and any(
                text[:30] in ln and not ln.lstrip().startswith(("❯", ">")) for ln in scr.splitlines())):
            seen = seen or "queued"
            if not tx:
                break
        time.sleep(1)
    out = {"id": s["id"], "name": s["name"], "status": s["status"], "via": f"{chan[0]} {chan[1]}",
           "result": seen or "unverified", "text": text}
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
