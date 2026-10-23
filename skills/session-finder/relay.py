#!/usr/bin/env python3
"""relay — message a running agent session by the best route for it, falling back before it fails. No model.

    relay.py <id|name|sid|pane|paseo-agent-id> "<text>" [--wait S] [--idle S] [--via ROUTE] [--plan] [--json]
                                           (pane: a herdr pane id such as w34:p4; a Paseo agent id is the
                                           PASEO_AGENT_ID uuid, as `paseo ls -g` and where.py show it)

The one way for an agent to message a peer (2026-10-23, djbclark: "automatically uses the best messaging option
for any given situation, and tries to fall back itself before returning an error"). It picks the routes that fit
the session, best first, and tries the next when one fails BEFORE sending anything (`--plan` prints the order):

  1. paseo     a Paseo-hosted agent (where: `host=paseo agent=<id>`; the only route for it): `paseo send
               --behavior steer -- <id> <text>`. The caller's own PASEO_AGENT_ID stays in the child's
               environment, so Paseo labels the message `kind="agent-message"` with the sender; a caller that is
               not a Paseo agent prefixes the text with `[relay from <name>] `. Steer queues the text for the next
               tool round on Claude; a provider that cannot steer has its running turn replaced. Before any send
               `paseo agent inspect` must show the agent unarchived, with no pending permission or question, idle
               or running, in the directory its process runs in; any refusal ends the run, whatever `--via` says.
               Delivery is what the daemon acknowledges ("accepted"), upgraded to "delivered" once a Claude
               transcript shows the text.
  2. dispatch  a headless acp-dispatch slice (no pane): `acp-dispatch tell RECORD` (its inbox plus its live Claude).
  3. launch    a live interactive ACP launch: its inbox (`launch.py reply`'s live path, under its turn lock). An
               ended launch is never replied to here: that would start a new, full-price turn.
  4. pane      keys into its pane (herdr `pane send-text` + `agent send-keys enter`, Orca `terminal send`, tmux
               `send-keys`). Claude Code queues text typed while it works; other TUIs take it only when idle
               (`--idle S` waits up to S seconds for that). Skipped while the input box holds a draft (Claude
               Code's dim/grey suggested prompt is not one: prompt_line.py). Verified in the transcript.
  5. socket    a Claude Code TUI with a live messaging socket (registry ~/.claude/sessions/<pid>.json, the pid
               the fleet knows, a socket we own in a directory only we can write): one `cross-session-message`
               frame, XML-escaped, queued for its next tool round. No keys, so it cannot collide with a draft or
               sit in a dialog. It is the fallback when the pane cannot take the text, and the only route to a
               Claude with no terminal. A working session is "accepted" at once (Claude Code logs the frame
               only when it absorbs it at a tool round); any other status is verified in its transcript within
               --wait, since a frame to an idle session is not proven to wake it, else "unverified".

  6. hermes    a Hermes gateway conversation (Telegram, Discord, desktop: a `hermes-gw` fleet row with a session id;
               its only route): `hermes --resume <sid> -z <text>` runs one turn on that session's stored transcript,
               text prefixed `[relay from <name>] `, stdin closed, in its own process group. The child gets the
               caller's environment without its session, Paseo, ACP-approval and Hermes routing variables, plus
               RELAY_HOPS and RELAY_SENDER (a relay made inside that turn is tagged as Hermes, not as the original
               caller; only nested `hermes -z` turns are counted, a fourth is refused). Hermes's reply goes to a
               0600 file under RELAY_HERMES_DIR (default ~/.local/state/session-finder/relay-hermes, pruned after 7
               days) and is printed here as untrusted data: control, format and escape characters stripped, at most
               4000 characters (a cut reply's cleaned text is kept in the file, whose path is printed).
               "delivered" (exit 0) means the turn ran on the stored transcript: it is NOT posted in the chat, and a
               gateway agent that is mid-turn or cached may not see it until it reloads. It never targets Hermes's
               own conversation (HERMES_SESSION_ID, or the same session key, or platform, chat and thread, for a delegated
               subagent).
               Only rc 1, an empty stdout and the single stderr line `hermes -z: agent failed: session not found:
               <sid>` (or `cannot resume session <sid>: ...`) mean nothing was written ("not sent"); every other
               failure is "unverified" (the turn may have started: do not resend). A "hermes turn started" line goes
               to stderr first, with the reply file, because the caller's own tool timeout (Claude Code 120 s,
               Hermes 180 s) can end this process before its verdict: if you are cut off, the message WAS sent. Give the
               command a timeout of at least max(100, --wait) + 50 seconds, or run it in the background: a tool timeout
               that kills the whole process tree (Claude Code's and Hermes's both do) also kills the turn, mid-way.
               relay.py itself never kills it: a turn still running after max(100, --wait) seconds from relay.py's start
               is left running (the exit is "unverified" and names the reply file); until it ends a second relay to that
               conversation is refused (a per-session flock the child holds). A profile Hermes (HERMES_HOME) sees only its own sessions: "not sent" for another
               profile's. RELAY_HERMES overrides the `hermes` binary. ACP cannot load a gateway session and
               messages_send only posts outward, so neither is a route. Checked 2026-10-23 on a throwaway `oneshot`
               session and end to end on a real Telegram topic (delivered; tagged user row and reply in its stored
               transcript; 0600 lock free afterwards).

Text starting with `/` or `!` is never typed into a pane (a built-in or a shell command there); only a socket
frame carries it, as a plain message. Never falls back (exit 1 with the reason, or 2): this session; a finished one (`/handoff` or `/quit`: start a
/baton session instead); one blocked on a question or permission (`helm.py answer`); a Paseo agent Paseo cannot
confirm; text starting with `/` to a Paseo agent (exit 2: peers do not run another session's built-ins; the pane
route skips such text too, and a socket frame carries it as a plain message). Never
falls back after a send it cannot rule out (exit 1, "unverified"): text typed into a pane but not seen or whose
Enter failed, a `paseo send` that failed for any reason but a missing CLI, an `acp-dispatch tell` that timed out, an idle
session whose socket frame never showed in its transcript. A second route there would deliver the message twice;
a retry of text left in a box submits it and types nothing. A socket frame to a working session is final (exit 0,
"accepted").

  * Verified where it can be: typed text counts as delivered once it shows up in the transcript (a typed message
    is recorded as a queue-operation at once), else as queued once the pane shows it.
  * Enter goes in ENTER_DELAY after the text, and again (up to ENTER_RETRIES times) while the text still
    sits in a Claude input box: sent in one burst it reads as a paste and does not submit (2026-10-18).
  * One line: newlines are folded to spaces. For a long brief, write it to a file and relay one line that
    names the file's absolute path.

Exit: 0 delivered or queued (verified in the transcript or pane, or for paseo/dispatch/launch, or a socket frame to a working session, the route's
acknowledgement; an idle session's socket frame is verified in its transcript; for hermes, the turn ran on the stored transcript); 1 not sent (every route failed, listed) or sent but unverified; 2 usage.
"""
import argparse
import fcntl
import json
import math
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
import unicodedata
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fleet  # noqa: E402
import prompt_line  # noqa: E402
import where  # noqa: E402

HERDR = fleet.HERDR
HERMES_BIN = os.environ.get("RELAY_HERMES") or shutil.which("hermes") or str(Path.home() / ".local/bin/hermes")
HERMES_MIN_WAIT = 100    # below the shortest caller tool timeout seen (Claude Code Bash 120 s, Hermes terminal 180 s)
HERMES_READ_CAP = 65536
HERMES_KEEP_S = 7 * 86400
HERMES_REPLY_CAP = 4000
HERMES_HOPS_MAX = 3
HERMES_DIR = Path(os.environ.get("RELAY_HERMES_DIR", Path.home() / ".local/state/session-finder/relay-hermes"))
# Variables a relayed Hermes turn must not inherit: they would let it pose as the caller (a relay it makes is tagged
# with the caller's name or labelled by Paseo as the caller's own message) or route replies to the caller's chat.
HERMES_SCRUB = ("CLAUDE_CODE_SESSION_ID", "PASEO_AGENT_ID", "PASEO_AGENT_CWD", "ACP_RUN_AGENT", "ACP_OPERATOR_APPROVED",
               "HERMES_UI_SESSION_ID")
HERMES_SCRUB_PREFIXES = ("HERMES_SESSION_", "HERMES_CRON_")
HIDDEN = "\u115f\u1160\u3164\uffa0\u2800"    # fillers and blanks that render as nothing
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b.?")
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
    except subprocess.TimeoutExpired as e:
        return 124, "", str(e)    # the CLI may have got its request to the daemon: not a provable non-send
    except OSError as e:
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


def hosted_by(agent_id):
    """True when this process, or one of its ancestors, is the process Paseo's daemon hosts for AGENT_ID
    (parent titled Paseo Daemon, the id in its environment): an inherited PASEO_AGENT_ID alone does not count."""
    return any(where.paseo_agent(pid, where.env_of(pid)) == agent_id for pid in (os.getpid(), *fleet.ancestors()))


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
    own = (os.environ.get("PASEO_AGENT_ID") or "").strip()
    if UUID.fullmatch(own) and not os.environ.get("ACP_RUN_AGENT") and hosted_by(own):
        return ""    # genuinely this agent: Paseo labels the message itself. An empty or junk value, an acp-run
                     # slice, or an inherited id with no Paseo-hosted ancestor (Codex, PR 25) gets the tag
    return f"[relay from {sender_name(listed)}] "


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
    s["send_rc"] = rc
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
    """Text typed but not sent in a Claude Code input box (its prompt line starts with ❯); None when the box is not
    in the rows read (its ❯ row or bottom border scrolled out: unknown, which is not the same as empty).

    Read with ANSI codes where the channel has them: Claude Code's suggested next prompt (ghost text that
    anything typed replaces) and its hints are dim or grey, not a draft (prompt_line.py; 2026-10-16 a dim
    suggestion was refused as a draft)."""
    p = box_parse(box_read(chan))
    return None if p is None else p[0]


def box_read(chan):
    """The last 14 rows of the pane (with ANSI codes where the channel has them)."""
    kind, target = chan
    if kind == "herdr":
        out = fleet.run(HERDR, "agent", "read", target, "--source", "visible", "--lines", "14", "--format", "ansi")[1]
    elif kind == "tmux":
        out = fleet.run("tmux", "capture-pane", "-p", "-e", "-t", target)[1]
    else:
        out = screen(chan, 14)
    rows = [ln for ln in out.splitlines() if ln.strip()]    # tmux prints the blank rows under a short screen too
    return "\n".join(rows[-14:])


BORDER = set("─━═╭╮╰╯┌┐└┘")


def _plain(ln):
    return re.sub(r"\x1b\[[0-9;:?]*[A-Za-z]", "", ln).strip().strip("│┃").strip()


def _is_border(ln):
    """A box rule is a long run of line-drawing characters; an operator's "---" or "--" is not one."""
    t = _plain(ln)
    return len(t) >= 10 and set(t) <= BORDER


def box_parse(raw):
    """(draft, rows below it) of the Claude Code input box in screen text RAW, or None when the box is not plainly
    in it. The box is the ONE rule row that is immediately followed by a ❯ row, with the bottom rule (the last rule
    read) after it and no other rule or ❯ row between. Anything else is unknown, never empty: a rule or ❯ the
    operator typed or pasted into a draft would otherwise pose as a smaller, empty box, and a prompt row that
    scrolled out of the 14 rows read leaves nothing to find (adversary rounds 7 and 8)."""
    rows = raw.splitlines()
    borders = [i for i, ln in enumerate(rows) if _is_border(ln)]
    if not borders:
        return None
    bottom = borders[-1]
    tops = [i for i in borders if i + 1 < len(rows) and "❯" in rows[i + 1]]
    if len(tops) != 1 or tops[0] + 1 >= bottom:
        return None
    mark = tops[0] + 1
    if any("❯" in ln or _is_border(ln) for ln in rows[mark + 1:bottom]):
        return None
    return (prompt_line.classify(rows[mark]) or "",
            " ".join(t for t in (_plain(ln) for ln in rows[mark + 1:bottom]) if t))


def rows_below(chan):
    """The input box's rows under its ❯ line (a Shift+Enter line, a wrapped long text), as one string, up to the
    box's bottom border; None when the box is not plainly in view. `draft` reads only the ❯ row, so words the
    operator added on a second row are invisible to it; an Enter decision must see them."""
    p = box_parse(box_read(chan))
    return None if p is None else p[1]


def box_text(chan):
    """What the input box holds: the ❯ row and the rows below it, whitespace-folded; None when the box is not
    plainly in view (unknown, not empty)."""
    p = box_parse(box_read(chan))    # one read: the ❯ row and the rows under it must be the same screen
    return None if p is None else " ".join((p[0] + " " + p[1]).split())


def press_enter(chan):
    kind, target = chan
    if kind == "herdr":
        return fleet.run(HERDR, "agent", "send-keys", target, "enter")[0] == 0
    if kind == "tmux":
        return fleet.run("tmux", "send-keys", "-t", target, "Enter")[0] == 0
    return False


def keys_run(*cmd, timeout=10):
    """Run a typing CLI: 'ok'; 'absent' (it could not start, so nothing was typed); or 'failed' (it ran and
    exited non-zero or timed out, so the text may have gone in: fleet.run folds a timeout into rc 127, the same
    as a missing binary, which is why this does not use it)."""
    try:
        p = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout, check=False,
                           stdin=subprocess.DEVNULL)
    except (FileNotFoundError, PermissionError):
        return "absent"
    except (OSError, subprocess.TimeoutExpired):
        return "failed"
    return "ok" if p.returncode == 0 else "failed"


def type_line(chan, text):
    """Type TEXT and Enter. False when either failed; `type_line.typed` says whether the text may have gone in
    (then it can sit in the input box, and a second route would deliver it twice). Only a typing CLI that could
    not start leaves it False."""
    kind, target = chan
    type_line.typed = False
    if kind == "herdr":
        step = keys_run(HERDR, "pane", "send-text", target, text)
    elif kind == "orca":
        step = keys_run("orca", "terminal", "send", "--terminal", target, "--text", text, "--enter", timeout=20)
        type_line.typed = step == "failed"
        return step == "ok"
    elif kind == "tmux":
        step = keys_run("tmux", "send-keys", "-t", target, "-l", text)
    else:
        return False
    type_line.typed = step != "absent"
    if step != "ok":
        return False
    time.sleep(ENTER_DELAY)
    return press_enter(chan)


def box_state(chan, text, pin="*"):
    """(stuck, ours, box) from one read of the input box. STUCK: TEXT still sits unsent in a Claude Code input box,
    its Enter did not land (loose: the first 30 characters agree, so arming is the safe direction). OURS: the box
    shows our text, a piece of it or our collapsed paste (PIN: see `ours_paste`), nothing more; only then may a
    relay press Enter on it. A box that is not in view is neither."""
    d = box_text(chan)
    mine_ = bool(d) and (ours_paste(d, text, pin) or holds(d, text))
    return mine_ or (bool(d) and d[:30] == text[:30]), mine_, d


def stuck_in_box(chan, text, pin="*"):
    return box_state(chan, text, pin)[0]


PASTE_MIN = 800     # Claude Code collapses only a paste longer than this into a placeholder
PASTE_RE = re.compile(r"\[Pasted text #\d+\]")


def ours_paste(d, text, pin="*"):
    """True when draft D is the collapsed "[Pasted text #N]" placeholder of a TEXT long enough to be collapsed.
    A long burst typed by send-text collapses and never matches the text (2026-10-18); a placeholder beside a
    short text is the operator's own paste, and a "+M lines" placeholder is a multi-line paste, which a one-line
    relay text never is (2026-10-23). PIN is which placeholder is ours: "*" any (the box was empty when we typed,
    so the first one seen is ours), a string only that exact one, "" none (a later number is the operator's own
    paste: adversary round 7)."""
    dn = " ".join(d.split())
    return bool(PASTE_RE.fullmatch(dn)) and len(" ".join((text or "").split())) > PASTE_MIN and pin in ("*", dn)


UNSENT_TTL = 3600    # an hour: a leftover from days ago must not claim a draft
UNSENT_KEEP = 86400  # an expired entry is still evidence of whose placeholder this is, for a day


def _unsent():
    try:
        return json.loads(UNSENT.read_text())
    except (OSError, ValueError):
        return {}


def note_unsent(sid, text, draft="", mark=0):
    """Remember TEXT as left unsent in session SID's box, with the draft the box showed then and the transcript size
    before it was typed (None forgets it). Entries older than UNSENT_TTL are dropped by `leftover`."""
    rows = {k: v for k, v in _unsent().items()
            if isinstance(v, dict) and time.time() - float(v.get("at") or 0) <= UNSENT_KEEP}
    if text is None:
        if rows.pop(sid, None) is None:
            return
    else:
        rows[sid] = {"text": text, "draft": " ".join(draft.split()), "mark": mark, "at": time.time()}
    UNSENT.parent.mkdir(parents=True, exist_ok=True)
    tmp = UNSENT.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False))
    tmp.replace(UNSENT)


def leftover(sid):
    """The unsent-message entry for session SID, or None (none, expired, or in the old bare-text format)."""
    e = _unsent().get(sid)
    if not isinstance(e, dict) or not e.get("text") or time.time() - float(e.get("at") or 0) > UNSENT_TTL:
        return None
    return e


def ours(d, text):
    """True when draft D is (the visible part of) TEXT, which this relay typed earlier. A short draft that merely
    occurs inside the text ("ok") and any collapsed paste are someone else's here; a collapsed paste of ours is
    recognised by the exact draft recorded when the leftover was noted (`mine`)."""
    d, t = " ".join(d.split()), " ".join((text or "").split())
    if not d or not t:
        return False
    return d[:30] == t[:30] or (len(d) >= 12 and t.startswith(d)) or (len(d) >= min(30, len(t)) and d[-30:] in t)


def holds(d, text):
    """True when the box D shows TEXT, its visible beginning, or (after the TUI's "…" clipping mark) its tail:
    never a piece from the middle, which the operator can type on their own (a PR URL out of the text)."""
    raw = " ".join(d.split())
    dn, tn = raw.lstrip("…").strip(), " ".join((text or "").split())
    return bool(dn) and bool(tn) and (dn == tn or (len(dn) >= 12 and (tn.startswith(dn) or (raw.startswith("…") and tn.endswith(dn)))))


def mine(d, entry):
    """True when draft D in the box is the leftover ENTRY's and nothing else: the exact draft recorded then, or
    (part of) its text. Words the operator added after our text make it theirs."""
    dn = " ".join(d.split())
    return bool(dn) and bool(entry) and (dn == entry.get("draft") or holds(dn, entry["text"]))


def arm(s, chan, text, mark, pin="*"):
    """Record TEXT as sitting unsent in session S's box (Claude Code only). The draft is kept for `mine` only when
    it is our text or our collapsed paste, never whatever else the box shows."""
    if s["agent"] == "claude":
        d = box_text(chan) or ""
        note_unsent(s["id"], text, d if holds(d, text) or ours_paste(d, text, pin) else "", mark)


PASTED_RE = re.compile(r'<pasted_content id="([^"]+)">\s*(.*?)\s*</pasted_content id="\1">', re.S)


def sent_in(tx, mark, text):
    """True when the transcript file TX holds, after byte MARK, a user message (or a queued one) that IS TEXT, whole
    and whitespace-folded. Never a substring: "continue" appears in any assistant line (adversary round 8). Claude
    Code records a collapsed paste (a text over 800 characters) wrapped in `<pasted_content id="N">...</pasted_content
    id="N">`, in the user line and in the enqueue alike (seen in real transcripts, round 9); hook-injected (isMeta)
    and compact-summary lines are not messages anyone sent."""
    want = " ".join((text or "").split())
    if not (tx and Path(tx).is_file()) or mark is None or not want:
        return False
    with Path(tx).open("rb") as fh:
        fh.seek(mark)
        lines = fh.read().decode("utf-8", "replace").splitlines()
    for ln in lines:
        try:
            o = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(o, dict):
            continue
        if o.get("isMeta") or o.get("isCompactSummary"):
            continue
        if o.get("type") == "queue-operation" and o.get("operation") == "enqueue":
            got = [o.get("content")]
        elif o.get("type") == "user":
            c = (o.get("message") or {}).get("content")
            got = [" ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
                   if isinstance(c, list) else c]
        else:
            continue
        for g in got:
            if isinstance(g, str):
                m = PASTED_RE.fullmatch(g.strip())
                if " ".join((m.group(2) if m else g).split()) == want:
                    return True
    return False


def in_transcript(s, entry):
    """True when the leftover ENTRY's whole text is already in session S's transcript after the entry's mark: it was
    delivered, so a copy in the box now is the operator's (Up-arrow history, a rewind), not an unsent one."""
    return sent_in(s.get("transcript"), entry.get("mark"), entry.get("text"))


def forget(sid, text):
    """Drop session SID's leftover entry when it is for TEXT (another text's entry is still owed its proof)."""
    e = leftover(sid)
    if e and " ".join(e["text"].split()) == " ".join(text.split()):
        note_unsent(sid, None)


def find(ident, ss):
    hits = [s for s in ss if ident in (s["id"], s["name"], s.get("sid"), s.get("pane"), s.get("paseo"))]
    if not hits and len(ident) >= 8:
        hits = [s for s in ss if (s.get("sid") or "").startswith(ident)]
    return hits


def own_hermes_conversation(s):
    """True when gateway row S is the Hermes conversation this process runs in: its session id, or (a delegated
    subagent has its own id) the same session key, or the same platform, chat and thread, which Hermes keeps in the
    environment."""
    if s.get("sid") and s["sid"] == os.environ.get("HERMES_SESSION_ID"):
        return True
    if s.get("hermes_key") and s["hermes_key"] == os.environ.get("HERMES_SESSION_KEY"):
        return True    # a desktop conversation binds no chat id; a delegated child keeps the parent's session key
    src, chat, thread = (s.get("hermes_chat") or (None, None, None))
    env = os.environ
    return bool(chat and str(chat) == env.get("HERMES_SESSION_CHAT_ID") and src == env.get("HERMES_SESSION_PLATFORM")
                and str(thread or "") == env.get("HERMES_SESSION_THREAD_ID", ""))


def hard_stop(s):
    """Why session S must get no message by ANY route, or None. These never fall back: the next route would
    deliver the same message into the same dialog, a finished conversation or this very session."""
    if s.get("self") or (s.get("host") == "hermes-gw" and own_hermes_conversation(s)):
        return "that is this session"
    if s.get("finished"):
        return (f"finished ({s['finished']}): never continue there; start a fresh session from its handoff "
                "(session-finder rung 3b, launch.py --baton)")
    if s.get("host") == "paseo" and s.get("paseo_state") not in (None, "idle", "running"):
        return f"its Paseo agent is {s['paseo_state']}, not idle or running"
    if s.get("status") == "blocked":
        return "blocked on a question or permission prompt: a message would land in or behind that dialog (helm.py answer)"
    return None


def refusal(s):
    """Why text must not be typed into session S's pane, or None."""
    why = hard_stop(s)
    if why:
        return why
    if s.get("host") == "acp":
        return f"an ACP launch: use launch.py reply {s['id']} \"<text>\" (its inbox), never keys"
    if s.get("host") == "hermes-gw":
        return "a Hermes gateway conversation without a session id: nothing to resume"
    if not s.get("chan"):
        rec = fleet.dispatch_record(s.get("sid"))
        if rec:
            return f"a headless acp-dispatch slice (no pane): acp-dispatch tell {rec} \"<text>\""
        return (f"no terminal channel ({s.get('where') or 'unknown terminal'}); tell the operator its where: line. "
                "If it runs under Paseo (a PASEO_AGENT_ID it was handed, or `paseo ls -g`), pass that agent id as the ident")
    if s["agent"] != "claude" and s.get("status") != "idle":
        return f"a {s['agent']} TUI that is {s.get('status')}: only idle ones take typed text reliably"
    return None


# ---- routes ---------------------------------------------------------------------------------------------
# A route returns one of: ("ok", via, seen) delivered or queued; ("skip", why) nothing was sent, try the next
# route; ("stop", why, rc) nothing was sent and no other route may be tried; ("unverified", out) the text was
# sent but never seen, so a second route would risk a duplicate.

SLASH_STRIP = " \t\r\n\u00a0\u200b\u200c\u200d\u2060\ufeff"


def is_slash(text):
    """True when TEXT would start a built-in command: Paseo trims the prompt (JS trim, which drops U+FEFF) before its
    slash-command parser, so strip the same and the zero-width characters first, and count the full-width slash too
    (adversary round 2)."""
    return text.lstrip(SLASH_STRIP).startswith(("/", "\uff0f"))


def sender_name(listed):
    """Who is relaying: this session's name, else its id, as one safe label."""
    if hermes_hops() and os.environ.get("RELAY_SENDER"):
        name = os.environ["RELAY_SENDER"]    # a relay made inside a relayed Hermes turn: Hermes, not the original caller
        return fleet.clip(re.sub(r"[^A-Za-z0-9._ -]", "", name), 40) or "unknown"
    me = next((x for x in listed if x.get("self")), None) or {}
    name = me.get("name") or me.get("id") or (os.environ.get("CLAUDE_CODE_SESSION_ID") or "")[:8] or "unknown"
    return fleet.clip(re.sub(r"[^A-Za-z0-9._ -]", "", name), 40) or "unknown"


def claude_socket(s):
    """The messaging socket of the live Claude Code that runs session S, or None: the registry entry
    (~/.claude/sessions/<pid>.json) for S's session id, its pid alive, and a socket this user owns."""
    sid = s.get("sid")
    if s.get("agent") != "claude" or not sid:
        return None
    for path in sorted((fleet.CLAUDE / "sessions").glob("*.json")):
        try:
            entry = json.loads(path.read_text())
            pid = int(entry["pid"])
            if entry.get("sessionId") != sid:
                continue
            if s.get("pid") and int(s["pid"]) != pid:
                continue    # a second process holding the same session id
            os.kill(pid, 0)
            sock = entry.get("messagingSocketPath")
            st = os.stat(sock) if sock else None
            dst = os.stat(os.path.dirname(sock)) if sock else None
        except PermissionError:
            continue
        except (OSError, ValueError, TypeError, KeyError):
            continue
        if (st and dst and stat.S_ISSOCK(st.st_mode) and st.st_uid == os.getuid() and dst.st_uid == os.getuid()
                and not dst.st_mode & 0o022):    # ours, in a directory nobody else can write to
            return sock
    return None


def xml_body(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def socket_send(sock, sender, text):
    """One JSON line to a Claude Code messaging socket, then SHUT_WR (the frame acp-dispatch tell sends; the
    protocol is undocumented, verified on this machine 2026-10-18 and 2026-10-23). False on any failure to
    connect or write. The body is XML-escaped (& < >) so it cannot close or reopen the wrapper."""
    body = xml_body(text)
    wrap = (f'<cross-session-message from="relay.py" from-name="relay.py ({sender})" '
            f'from-mode="bypass">\n{body}\n</cross-session-message>')
    frame = {"msgV": 1, "msg_id": str(uuid.uuid4()), "type": "user",
             "message": {"role": "user", "content": wrap}, "priority": "next", "from": "relay.py"}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
            c.settimeout(10)
            c.connect(str(sock))
            c.sendall(json.dumps(frame).encode() + b"\n")
            c.shutdown(socket.SHUT_WR)
    except OSError:
        return False
    return True


def route_paseo(c):
    """The gate (main) has passed. `paseo send` that failed for a reason other than a missing CLI may still have
    reached the daemon, so it ends the run rather than risk a second copy over another route."""
    s = c["s"]
    text = c["text_sent"] = sender_tag(c["listed"]) + c["text"]
    seen = send_paseo(s, text, c["a"].wait)
    if not seen:
        if s.get("send_rc") == 127:
            return ("skip", "no usable paseo CLI")
        return ("unverified", f"`paseo send` failed (rc={s.get('send_rc')}); it may have reached the daemon, so no other "
                              "route was tried")
    return ("ok", f"paseo {s['chan'][1]}", seen)


def route_socket(c):
    """A frame the socket took is final: there is no second route after it. Claude Code logs it in the transcript
    only when it absorbs it (the user-role content keeps the `<cross-session-message ...>` envelope; a working
    session shows it as a `queued_command` attachment), so a WORKING session is "accepted" at once. Any other
    status (idle, busy-background, unknown) is verified: the enveloped text must show up in the transcript within
    --wait, else the run is "unverified" (exit 1, do not resend) rather than a success a caller would act on."""
    s = c["s"]
    sock = claude_socket(s)
    if not sock:
        return ("skip", "no live Claude messaging socket for it")
    tx = Path(s["transcript"]) if s.get("transcript") else None
    mark = tx.stat().st_size if tx and tx.is_file() else 0
    if not socket_send(sock, sender_name(c["listed"]), c["text"]):
        return ("skip", f"could not write to its messaging socket {sock}")
    if s.get("status") == "working":
        return ("ok", "claude socket", "accepted")
    if not (tx and tx.is_file()):
        return ("unverified", f"its socket took the text but the {s.get('status')} session has no transcript to confirm it. "
                              "Do not resend; check its pane")
    probe = json.dumps('from-mode="bypass">\n' + xml_body(c["text"]) + "\n</cross-session-message>", ensure_ascii=False)[1:-1]
    deadline = time.time() + c["a"].wait
    while True:
        with tx.open("rb") as fh:
            fh.seek(mark)
            if probe in fh.read().decode("utf-8", "replace"):
                return ("ok", "claude socket", "delivered")
        if time.time() >= deadline:
            return ("unverified", f"its socket took the text but the {s.get('status')} session has not read it within "
                                  f"{c['a'].wait:g}s (an idle session may not wake on a socket frame). Do not resend; check its pane")
        time.sleep(1)


def pane_idle(s, seconds):
    """Wait up to SECONDS for pane TUI S to go idle, re-reading the fleet every few seconds; True when it is."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        time.sleep(min(3, max(0.1, deadline - time.time())))
        now = next((x for x in fleet.sessions() if x["id"] == s["id"]), None)
        if now and any(now.get(k) != s.get(k) for k in ("agent", "pid", "sid")):
            return False    # another session now holds that pane: never type into it
        if now and now.get("status") == "idle":
            s["status"] = "idle"
            return True
    return False


def retry_leftover(c, chan, d, left):
    """A retry of the message an earlier relay left unsent: type nothing. Submit it if it is still in the box, then
    prove it reached the transcript (searched from where it was typed, whole text) or report unverified."""
    s, text = c["s"], c["text"]
    if d and not mine(d, left):
        return ("unverified", f"its input box holds someone else's draft ({fleet.clip(d, 60)!r}); an earlier copy of this "
                              "message may or may not have landed. Do not resend; check its pane")
    if d and in_transcript(s, left):    # delivered already: the copy in the box is a recalled one, not ours to submit
        note_unsent(s["id"], None)
        return ("ok", f"{chan[0]} {chan[1]}", "delivered")
    pressed = bool(d)
    if d:
        press_enter(chan)
        for _ in range(10):
            time.sleep(1)
            d = box_text(chan)
            if d == "":
                break
    if d != "":
        return ("unverified", f"your earlier copy of this message is still in its input box, or the box is out of view "
                              f"({fleet.clip(d or '', 60)!r}). Do not resend; check its pane")
    tx = Path(s["transcript"]) if s.get("transcript") else None
    deadline = time.time() + (c["a"].wait if pressed else 0)
    while tx and tx.is_file() and left.get("mark") is not None:
        if sent_in(tx, left["mark"], text):
            note_unsent(s["id"], None)
            return ("ok", f"{chan[0]} {chan[1]}", "delivered")
        if time.time() >= deadline:
            break
        time.sleep(1)
    return ("unverified", "an earlier copy of this message was typed and is no longer in its input box, but it is not in "
                          "its transcript; do not resend, check its pane (a retry within the hour stays blocked)")


def route_pane(c):
    s, a, text = c["s"], c["a"], c["text"]
    why = refusal(s)
    if why and a.idle and s.get("agent") != "claude" and s.get("status") == "working" and not s.get("host") == "acp":
        if pane_idle(s, a.idle):
            why = refusal(s)
    if why:
        return ("skip", why)
    if is_slash(text) or text.lstrip(SLASH_STRIP).startswith("!"):
        return ("skip", "text starting with '/' or '!' typed into a pane would run a built-in or a shell command "
                        "there; peers do not run another session's built-ins")
    chan = tuple(s["chan"])
    d = box_text(chan) if s["agent"] == "claude" else ""
    left = leftover(s["id"])
    tx = Path(s["transcript"]) if s.get("transcript") else None
    if d is None:    # its ❯ row or bottom border is outside the rows read: nothing may be typed or submitted blind
        if left and " ".join(left["text"].split()) == text:
            return ("unverified", "an earlier copy of this message may sit in its input box, which is out of view. "
                                  "Do not resend; check its pane")
        return ("skip", "cannot see its input box (its ❯ row or bottom border is outside the screen read)")
    if left and " ".join(left["text"].split()) == text:    # a retry of the message an earlier relay left unsent
        return retry_leftover(c, chan, d, left)
    if d and left and in_transcript(s, left):    # that message was delivered: the box holds a recalled copy
        note_unsent(s["id"], None)
        left = None
    if d and mine(d, left):
        press_enter(chan)
        for _ in range(10):
            time.sleep(1)
            d = box_text(chan)
            if d == "":
                break
        if d is None:
            return ("unverified", "pressed Enter on an earlier message of ours, then its input box went out of view. "
                                  "Do not resend; check its pane")
        if not d:    # the entry stays: a retry of that text proves it from its mark, and the TTL expires it
            print(f"relay: [{s['id']}] submitted our earlier message left unsent in its box", file=sys.stderr)
    stale = _unsent().get(s["id"])    # an entry past its TTL is still evidence of whose paste placeholder this is
    if d and (holds(d, text) or (isinstance(stale, dict) and " ".join(str(stale.get("text")).split()) == text
                                 and stale.get("draft") and d == stale["draft"])):
        # our own text from an earlier relay whose entry expired or never existed
        return ("unverified", "this very text already sits in its input box from an earlier relay. "
                              "Do not resend; check its pane")
    if d:
        return ("skip", f"its input box holds a draft ({fleet.clip(d, 60)!r})")
    mark = tx.stat().st_size if tx and tx.is_file() else 0
    if not type_line(chan, text):
        if getattr(type_line, "typed", False):    # the text may be in the box, only its Enter failed
            arm(s, chan, text, mark)
            return ("unverified", f"text typed into {chan[0]} {chan[1]} (or not: the typing CLI did not finish) but its "
                                  "Enter failed; it may sit in the input box. Do not resend; check its pane")
        return ("skip", f"typing into {chan[0]} {chan[1]} failed")
    seen, deadline = None, time.time() + a.wait
    typed_at, retries, stuck, pin, was_ours, gone = time.time(), 0, False, "*", False, False
    while time.time() < deadline:
        if sent_in(tx, mark, text):
            seen = "delivered"
            break
        stuck, ours_now, seen_box = box_state(chan, text, pin) if s["agent"] == "claude" else (False, False, "")
        if pin == "*":    # the box was empty before we typed: the placeholder in the FIRST read is ours, a later one is not
            pin = seen_box if ours_now and PASTE_RE.fullmatch(seen_box or "") else ""
        if ours_now:
            was_ours = True
        elif seen_box == "" and was_ours:
            gone = True    # our copy left the box (submitted): a copy that shows up again is a recall, never ours to submit
        if ours_now and not gone and retries < ENTER_RETRIES and time.time() - typed_at >= RETRY_AFTER:
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
    if s["agent"] == "claude":
        if seen or box_text(chan) == "":    # forget only on proof: an unseen or foreign box may still hold our copy
            forget(s["id"], text)
        else:
            arm(s, chan, text, mark, pin)
    if seen:
        return ("ok", f"{chan[0]} {chan[1]}", seen)
    return ("unverified", f"text typed via {chan[0]} {chan[1]} but not seen in its transcript or pane within "
                          f"{a.wait:g}s; check: {s.get('focus') or s.get('where')}")


def route_launch(c):
    """A live interactive ACP launch takes the text in its inbox as the next prompt (what `launch.py reply` does
    for one). An ended launch is not touched: its reply would start a new, full-price turn."""
    s = c["s"]
    d = s.get("launch") or {}
    if not d.get("id"):
        return ("skip", "not an ACP launch this tooling started")
    if not d.get("interactive") or fleet.launch_state(d)[2] is not None:
        return ("skip", f"launch {d['id']} has ended or is headless: `launch.py reply {d['id']} \"<text>\"` would start "
                        "a new turn, which a relay does not do")
    try:
        import launch  # noqa: PLC0415
    except ImportError as e:
        return ("skip", f"launch.py not importable: {e}")
    with launch.turn_lock():    # the check and the write are one step, as in `launch.py reply`
        why = launch.reply_refusal(d["id"])
        if why:
            return ("skip", why)
        if not launch.inbox_send(d, c["text"]):
            return ("skip", f"inbox {d.get('inbox')} is gone")
    return ("ok", f"launch inbox {d['id']}", "queued")


def route_dispatch(c):
    """`acp-dispatch tell RECORD`: the slice's inbox, plus its live Claude's socket. A finished slice refuses."""
    s = c["s"]
    rec = c.get("dispatch_rec") or fleet.dispatch_record(s.get("sid"))
    cli = HERE.parent.parent / "bin" / "acp-dispatch"
    if not rec or not cli.is_file():
        return ("skip", "no open acp-dispatch record for it")
    try:
        p = subprocess.run([str(cli), "tell", "--from", f"relay {sender_name(c['listed'])}", "--", rec, c["text"]],
                           capture_output=True, text=True, timeout=30, check=False, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return ("unverified", "acp-dispatch tell timed out; it may already have written the slice's inbox. Do not resend")
    except OSError as e:
        return ("skip", f"acp-dispatch tell failed: {e}")
    if p.returncode != 0:
        return ("skip", f"acp-dispatch tell refused: {fleet.clip((p.stderr or p.stdout).strip(), 160)}")
    return ("ok", f"acp-dispatch {Path(rec).name}", "queued")


def hermes_hops():
    try:
        return max(0, int(os.environ.get("RELAY_HOPS", "0")))
    except ValueError:
        return HERMES_HOPS_MAX


def hermes_env(sid):
    env = {k: v for k, v in os.environ.items() if k not in HERMES_SCRUB and not k.startswith(HERMES_SCRUB_PREFIXES)}
    env["RELAY_HOPS"] = str(hermes_hops() + 1)
    env["RELAY_SENDER"] = f"hermes {sid[-8:]}"
    return env


def clean_reply(text):
    """Hermes's reply as plain data: escape sequences and control characters (C0 bar newline and tab, DEL, C1) removed."""
    return "".join(ch for ch in ANSI.sub("", text)
                   if ch in "\n\t" or not (ch < " " or "\x7f" <= ch <= "\x9f" or unicodedata.category(ch) in ("Cf", "Zl", "Zp")
                                                                       or ch in HIDDEN or "\ufe00" <= ch <= "\ufe0f" or "\U000e0100" <= ch <= "\U000e01ef")).strip()


def read_capped(path):
    with path.open("rb") as fh:
        return fh.read(HERMES_READ_CAP).decode("utf-8", "replace")


def hermes_private_file(path):
    """A new 0600 file that never follows a symlink and never reuses an existing path."""
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb")


def hermes_prune():
    cutoff = time.time() - HERMES_KEEP_S
    for f in HERMES_DIR.glob("[0-9]*-*.out"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                f.with_suffix(".err").unlink(missing_ok=True)
        except OSError:
            pass


def route_hermes(c):
    """One turn on a Hermes gateway session's stored transcript: `hermes --resume SID -z TEXT`, reply to a file.
    The store refuses an unknown session before writing anything: rc 1, nothing on stdout, and that exact single
    stderr line, never matched anywhere else (a turn that ran can quote the words). Every other failure may follow
    a written user message, so it is "unverified" and no other route runs. A turn that outlives the wait is left
    running, not killed, and holds the session's lock so a second relay cannot write beside it; the started line is
    printed first because the caller's own tool timeout (Claude Code 120 s, Hermes 180 s) can end this process
    before the verdict, and a timeout that kills the process tree takes the turn with it. The text always carries the `[relay from NAME] ` tag, which also keeps it from reading as an option."""
    s = c["s"]
    if hermes_hops() >= HERMES_HOPS_MAX:
        return ("stop", f"{hermes_hops()} nested hermes relays already (RELAY_HOPS): not relaying into Hermes again", 1)
    text = c["text_sent"] = (sender_tag(c["listed"]) or f"[relay from {sender_name(c['listed'])}] ") + c["text"]
    HERMES_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(HERMES_DIR, 0o700)
    hermes_prune()
    sid8 = s["sid"][-8:]
    lock = os.open(HERMES_DIR / f"{re.sub(r'[^A-Za-z0-9_-]', '_', s['sid'])}.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return ("stop", f"a relayed turn is still running in that conversation (lock {HERMES_DIR}): not writing beside it", 1)
        base = HERMES_DIR / f"{time.time_ns()}-{sid8}"
        out_p, err_p = base.with_suffix(".out"), base.with_suffix(".err")
        try:
            with hermes_private_file(out_p) as fo, hermes_private_file(err_p) as fe:
                proc = subprocess.Popen([HERMES_BIN, "--resume", s["sid"], "-z", text], stdin=subprocess.DEVNULL, stdout=fo,
                                        stderr=fe, env=hermes_env(s["sid"]), start_new_session=True, pass_fds=(lock,))
        except OSError as e:
            out_p.unlink(missing_ok=True)
            err_p.unlink(missing_ok=True)
            return ("skip", f"hermes CLI not usable: {e}")
    finally:
        os.close(lock)    # the child holds its own copy of the locked file: the lock lasts as long as its turn
    note = (f"relay: [{s['id']}] hermes turn started (pid {proc.pid}). If this command is cut off or times out, the message "
            f"WAS sent: do not resend. Reply file: {out_p}")
    print(note, file=sys.stderr, flush=True)
    def on_signal(n, f):
        print(f"relay: [{s['id']}] stopped by a signal; the message WAS sent: do not resend. The hermes turn (pid {proc.pid}) "
              "keeps running unless the signal came from a tool timeout that kills the whole process tree", file=sys.stderr,
              flush=True)
        os._exit(1)
    old = {sig: signal.signal(sig, on_signal) for sig in (signal.SIGTERM, signal.SIGHUP)}
    try:
        rc = proc.wait(timeout=max(1.0, c["t0"] + max(HERMES_MIN_WAIT, c["a"].wait) - time.time()))
    except subprocess.TimeoutExpired:
        return ("unverified", f"`hermes --resume -z` is still running (pid {proc.pid}, left running, not killed); its raw "
                              f"reply will land in {out_p} (escape sequences are not stripped there). The text may already "
                              "be in the conversation. Do not resend")
    finally:
        for sig, h in old.items():
            signal.signal(sig, h)
    err = read_capped(err_p)
    out = read_capped(out_p)
    sid = re.escape(s["sid"])
    if (rc == 1 and not out.strip() and re.fullmatch(
            rf"hermes -z: agent failed: (?:session not found: {sid}|cannot resume session {sid}: [^\n]*)", clean_reply(err))):
        out_p.unlink(missing_ok=True)
        err_p.unlink(missing_ok=True)
        return ("skip", f"Hermes does not know session {s['sid']}: {fleet.clip(clean_reply(err), 160)}")
    if rc != 0:
        return ("unverified", f"`hermes --resume -z` failed (rc={rc}: {fleet.clip(clean_reply(err).splitlines()[-1] if err.strip() else '', 160)}); "
                              f"the turn may have started, so no other route was tried. Output kept in {out_p} and {err_p} "
                              "(raw). Do not resend")
    reply = clean_reply(out)
    if len(reply) > HERMES_REPLY_CAP:
        out_p.write_text(reply)    # the kept file holds the cleaned text, never the raw
        c["reply"] = reply[:HERMES_REPLY_CAP] + f"\n[cut at {HERMES_REPLY_CAP} characters; the cleaned first {HERMES_READ_CAP // 1024} KB of the reply: {out_p}]"
        c["reply_file"] = str(out_p)
        err_p.unlink(missing_ok=True)
    else:
        c["reply"] = reply
        out_p.unlink(missing_ok=True)
        err_p.unlink(missing_ok=True)
    return ("ok", f"hermes --resume {sid8}", "delivered")


ROUTES = {"paseo": route_paseo, "dispatch": route_dispatch, "launch": route_launch, "socket": route_socket,
          "pane": route_pane, "hermes": route_hermes}


def plan(s):
    """Route names for session S, best first: a Paseo-hosted agent by `paseo send` alone (labelled as a peer's
    message); a headless acp-dispatch slice by `acp-dispatch tell`; a live ACP launch by its inbox; a Claude TUI
    by keys into its pane, whose delivery is verified in the transcript, then by its messaging socket when the
    pane cannot take the text (a typed draft, no terminal): a socket frame to a working session is only
    acknowledged and to an idle one unproven to wake it, so it never goes first. A Hermes gateway conversation
    (`hermes-gw`, with a session id) is resumed with `hermes --resume SID -z` and nothing else."""
    if s.get("host") == "paseo" or (s.get("chan") or (None,))[0] == "paseo":
        return ["paseo"]
    if s.get("host") == "hermes-gw":
        return ["hermes"] if s.get("sid") else []
    if s.get("host") == "acp":
        return ["launch"]
    if fleet.dispatch_record(s.get("sid")) and not s.get("chan"):
        return ["dispatch"]
    names = ["pane"] if s.get("chan") else []
    if claude_socket(s):
        names.append("socket")
    return names


def main():
    ap = argparse.ArgumentParser(prog="relay.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ident")
    ap.add_argument("text")
    ap.add_argument("--wait", type=float, default=20, help="seconds to verify delivery (default 20; a hermes turn gets max(100, S))")
    ap.add_argument("--idle", type=float, metavar="S", help="a working Paseo agent or non-Claude pane TUI: wait up to S seconds for it to go idle first")
    ap.add_argument("--via", choices=sorted(ROUTES), help="use only this route (default: the best, then fall back)")
    ap.add_argument("--plan", action="store_true", help="print the routes in order and send nothing")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    if a.idle is not None and not (math.isfinite(a.idle) and a.idle > 0):
        print("relay: --idle must be a finite number of seconds > 0", file=sys.stderr)
        return 2
    if not (math.isfinite(a.wait) and a.wait >= 0):
        print("relay: --wait must be a finite number of seconds >= 0", file=sys.stderr)
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
    if is_paseo and is_slash(text):
        print(f"relay: [{s['id']}] not sent: text starting with '/' would run a built-in; peers do not run another "
              "session's built-ins", file=sys.stderr)
        return 2
    why = hard_stop(s)    # on the fleet's own snapshot, before the Paseo gate overwrites its status
    if why:
        print(f"relay: [{s['id']}] not sent: {why}", file=sys.stderr)
        return 1
    if is_paseo and not s.get("self") and not a.plan:
        # The gate runs for every Paseo target whatever --via says, and each refusal ends the run: no other route
        # may send to an agent Paseo cannot confirm, one that is archived or asking, or whose process mapping
        # is untrusted (adversary, 2026-10-23)
        why = paseo_gate(s)
        if not why and a.idle and s["status"] != "idle":
            if not paseo_idle(s, a.idle):
                print(f"relay: [{s['id']}] not sent: its Paseo agent is still running after {a.idle:g}s", file=sys.stderr)
                return 1
            why = paseo_gate(s)    # it can have been archived or asked a question while we waited
        if why:
            print(f"relay: [{s['id']}] not sent: {why}", file=sys.stderr)
            return 1
    why = hard_stop(s)
    if why:
        print(f"relay: [{s['id']}] not sent: {why}", file=sys.stderr)
        return 1
    if is_paseo and s["agent"] != "claude" and s.get("status") != "idle":
        print(f"relay: [{s['id']}] not sent: a {s['agent']} TUI that is {s.get('status')}: only idle ones take typed "
              "text reliably (--idle S waits for it)", file=sys.stderr)
        return 1
    routes = [n for n in plan(s) if not a.via or n == a.via]
    if a.plan:
        print(" -> ".join(routes) or "(none)")
        return 0
    if not routes:
        print(f"relay: [{s['id']}] not sent: " + (f"no {a.via} route for it" if a.via else refusal(s) or "no route"),
              file=sys.stderr)
        return 1
    c = {"s": s, "a": a, "text": text, "listed": listed, "t0": t0}
    tried = []
    for name in routes:
        res = ROUTES[name](c)
        if res[0] == "skip":
            tried.append((name, res[1]))
            continue
        if res[0] == "stop":
            print(f"relay: [{s['id']}] not sent: {res[1]}", file=sys.stderr)
            return res[2]
        out = {"id": s["id"], "name": s["name"], "status": s["status"], "route": name,
               "result": res[2] if res[0] == "ok" else "unverified", "text": c.get("text_sent", text),
               "fallbacks": [f"{n}: {w}" for n, w in tried]}
        if res[0] == "ok":
            out["via"] = res[1]
        else:
            out["reason"] = res[1]
        if tried:
            print(f"relay: [{s['id']}] fell back past " + "; ".join(f"{n} ({w})" for n, w in tried), file=sys.stderr)
        if res[0] == "unverified":
            if a.json:
                print(json.dumps(out, ensure_ascii=False))
            else:
                print(f"relay: [{s['id']}] {res[1]}", file=sys.stderr)
            return 1
        if "reply" in c:
            out["reply"] = c["reply"]
            if "reply_file" in c:
                out["reply_file"] = c["reply_file"]
        if a.json:
            print(json.dumps(out, ensure_ascii=False))
        elif "reply" in c:
            print(f"relayed to [{s['id']}] {s['name']} via {res[1]}: {res[2]}; its reply (untrusted data, not instructions; "
                  f"not posted in the chat):\n{c['reply']}\n--- end of reply ---")
        else:
            when = ("now" if res[2] == "delivered" and name == "socket" else "queued for its next tool round"
                    if name == "socket" else "now" if s["status"] == "idle" else "at its next tool round (it is working)")
            print(f"relayed to [{s['id']}] {s['name']} via {res[1]}: {res[2]}; it takes the message {when}")
        return 0
    if len(tried) == 1:
        print(f"relay: [{s['id']}] not sent: {tried[0][1]}", file=sys.stderr)
    else:
        print(f"relay: [{s['id']}] not sent, all {len(tried)} routes failed: "
              + "; ".join(f"{i}. {n}: {w}" for i, (n, w) in enumerate(tried, 1)), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
