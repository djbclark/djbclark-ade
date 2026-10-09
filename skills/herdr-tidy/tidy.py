#!/usr/bin/env python3
"""tidy — close idle herdr panes without losing anything helm cannot find again. Runs no model.

    tidy.py scan [--json]                   every herdr pane: class, verdict (close / handoff-then-close /
                                            leave / never) and the reason, with the resume command the ledger
                                            would record
    tidy.py handoff <pane> [--timeout S]    send /handoff to an idle Claude pane (empty composer verified on
                                            screen) and wait until its transcript shows the handoff finished
    tidy.py close <pane> [--why TEXT] [--resume CMD] [--dry-run]
                                            re-check every precondition right before acting, append the close
                                            ledger (resume command, screen tail, journal entry), then close the
                                            tab when the pane is its only pane, else the pane
    tidy.py ledger [--days N] [--json]      the close ledger, newest first
    tidy.py resumed <ledger-id>             mark an entry resumed so helm stops listing it

Pane classes and the rule for each are in SKILL.md next to this file. Every "close" is fail-closed: a pane
whose state cannot be verified (composer not on screen, herdr cannot tell idle from working, a draft in the
input box, children in flight, a live bigteam claim, the helm or a coord pane) is left alone with the reason.
Ledger: ~/.local/state/session-finder/closed.jsonl (fleet.CLOSED); fleet.ended_open reads it, so a closed
pane resurfaces through `helm.py scan --ended` with its resume command. Exit 0 ok, 1 refused, 2 usage.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "session-finder"))
import fleet

HERDR = fleet.HERDR
run, herdr_json, short, clip = fleet.run, fleet.herdr_json, fleet.short, fleet.clip
SCREEN_LINES = 60
HANDOFF_TIMEOUT = 900
PROTECTED_TABS = re.compile(r"^(helm|coord)(\b|[-_])", re.IGNORECASE)
POPUP_PROCS = re.compile(r"(collie|drovr|herdr-jump|herdr-navigator)", re.IGNORECASE)
SHELLS = {"bash", "zsh", "fish", "sh", "-bash", "-zsh", "-fish", "-sh"}
SHELL_PROMPT = re.compile(r"[$%#>]\s*$")                  # bash/zsh/fish prompt with nothing typed after it
STUB_PROMPT = "press Enter to resume"                     # herdr-sleeper's in-pane stub
TUI_WAITING = re.compile(r"(\[y/N\]|\[Y/n\]|Enter to (select|submit|confirm)|Question \d+ of \d+|\(y/n\)|to select)", re.IGNORECASE)
VERIFIED_RESUME = set(fleet.RESUME_FORMS)                 # kinds whose resume form was read from `<tui> --help`


# ---- reading a pane ----------------------------------------------------------------------------

def screen(pane, lines=SCREEN_LINES):
    out = run(HERDR, "pane", "read", pane, "--source", "visible", "--lines", str(lines))[1]
    return [ln.rstrip() for ln in out.splitlines()]


def last_lines(rows, n=1):
    rows = [r for r in rows if r.strip()]
    return rows[-n:] if rows else []


def claude_composer(rows):
    """('empty' | 'draft' | 'unknown', draft text): Claude Code's composer line (`❯ …`) on the visible screen.
    Unknown when no composer line is visible: a key would land somewhere we cannot see."""
    for ln in reversed(rows):
        if ln.lstrip().startswith("❯"):
            text = ln.lstrip()[1:].strip()
            return ("draft" if text else "empty"), text
    return "unknown", ""


def pane_exists(pane):
    return bool(herdr_json("pane", "get", pane).get("pane"))


# ---- classification ----------------------------------------------------------------------------

def _live_claims():
    return [c for c in fleet.claims()]


def _claimed_by(c_list, pane, tab, sid, name):
    for c in c_list:
        hay = c.get("session", "")
        for needle in (pane, tab, (sid or "")[:8], name):
            if needle and needle in hay:
                return c["task"]
    return ""


def classify(p, sess, journal, claims, table):
    """One pane -> {pane, tab, workspace, label, agent, cls, verdict, reason, resume, ...}.
    verdict: 'never' (structural), 'leave' (not now, reason says what would change it),
    'handoff-then-close' (idle Claude with no handoff yet), 'close' (every precondition holds)."""
    pane, tab = p["pane_id"], p["tab_id"]
    tab_label = fleet.herdr_label("tab", tab).split("#", 1)[0]
    s = sess.get(pane) or {}
    sid = s.get("sid") or (p.get("agent_session") or {}).get("value")
    it = {"pane": pane, "tab": tab, "workspace": p["workspace_id"], "label": p.get("label") or "", "tab_label": tab_label,
          "agent": s.get("agent") or p.get("agent") or "shell", "title": s.get("title") or p.get("terminal_title_stripped") or "",
          "cwd": s.get("cwd") or p.get("cwd") or "", "sid": sid, "status": s.get("status") or p.get("agent_status") or "unknown",
          "cls": "", "verdict": "leave", "reason": "", "resume": "", "handoff": None, "busy": s.get("busy") or []}

    def leave(cls, reason, verdict="leave"):
        it.update(cls=cls, verdict=verdict, reason=reason)
        return it

    if p.get("focused"):
        return leave("focused", "the operator is in this pane", "never")
    if pane == os.environ.get("HERDR_PANE_ID") or s.get("self"):
        return leave("self", "this session", "never")
    if PROTECTED_TABS.match(tab_label) or PROTECTED_TABS.match(it["title"] or "") or PROTECTED_TABS.match(p.get("label") or ""):
        return leave("orchestrator", f"helm/coord pane (tab {tab_label!r}): never closed", "never")
    task = _claimed_by(claims, pane, tab, sid, s.get("name", ""))
    if task:
        return leave("claimed", f"live bigteam claim {task} names this session", "never")
    procs, shell_pid = fleet.pane_procs(pane)
    names = " ".join((pr.get("name") or "") + " " + " ".join(pr.get("argv") or []) for pr in procs or [])
    if any(POPUP_PROCS.search(os.path.basename(pr.get("argv0") or pr.get("name") or "")) for pr in procs or []):
        return leave("popup", "a tool's popup pane (collie/drovr/herdr-jump): close it through the tool", "never")

    # --- ACP launch hosted here
    if s.get("host") == "acp":
        if s["status"] == "working":
            return leave("acp", f"ACP launch {s['id']} is working")
        it.update(cls="acp", verdict="close", reason=f"ACP launch {s['id']} is {s['status']}: close with launch.py close {s['id']}",
                  resume=f"python3 -I {HERE.parent / 'session-finder' / 'launch.py'} reply {s['id']} \"<text>\"", launch=s["id"],
                  close_cmd=[sys.executable, "-I", str(HERE.parent / "session-finder" / "launch.py"), "close", s["id"]])
        return it

    # --- herdr-sleeper stub
    stub = any("herdr-sleeper" in " ".join(pr.get("argv") or []) and "stub" in (pr.get("argv") or []) for pr in procs or [])
    if p.get("agent") == "sleeper" or stub:
        e = journal.get(pane)
        it["cls"], it["agent"] = "sleeping", (e or {}).get("kind") or "claude"
        if not e:
            return leave("sleeping", "no herdr-sleeper journal entry for this pane: nothing says how to resume it")
        it.update(title=e.get("title") or e.get("name") or "", cwd=e.get("cwd") or "", sid=e.get("uuid"), journal=e)
        if e.get("phase") != "asleep":
            return leave("sleeping", f"journal phase is {e.get('phase')!r}, not asleep (a wake or exit is in progress)")
        cmd = fleet.sleeper_resume(e)
        if not cmd:
            return leave("sleeping", f"no verified resume form for kind {e.get('kind')!r}")
        if (e.get("kind") or "claude") == "claude" and not fleet.transcript(e["uuid"]):
            return leave("sleeping", f"transcript for {e['uuid']} is not on disk: nothing to resume")
        if not stub and procs is not None and procs:
            return leave("sleeping", "pane runs something other than the sleeper stub: " + clip(names, 80))
        if procs is None:
            return leave("sleeping", "herdr could not read the pane's processes")
        if STUB_PROMPT not in "\n".join(screen(pane, 12)) and stub:
            return leave("sleeping", "stub prompt not on screen (a wake may be in progress)")
        it.update(verdict="close", reason="asleep, journal entry replayable; the ledger keeps the entry and the manual resume line",
                  resume=cmd)
        return it

    # --- a session fleet knows (claude, hermes, any TUI herdr detected or process-info revealed)
    if s and s.get("status") != "shell":
        kind = s["agent"]
        if s["status"] == "working":
            return leave(kind, "working")
        if s["status"] == "busy-background":
            return leave(kind, "idle to herdr but child processes are in flight: " + "; ".join(s["busy"][:2]))
        if s["status"] == "blocked":
            return leave(kind, "waiting on a prompt: answer it through helm first")
        if s["status"] not in ("idle",):
            return leave(kind, f"herdr cannot tell idle from working for this pane (status {s['status']}); decide by hand")
        rows = screen(pane)
        if kind == "claude":
            state, text = claude_composer(rows)
            if state == "draft":
                return leave(kind, f"unsent draft in the input box: {clip(text, 60)!r}")
            if state == "unknown":
                return leave(kind, "composer line not visible on screen: cannot verify an empty input box "
                                   f"(focus it: herdr tab focus {tab}, let it redraw, rerun)")
            tx = fleet.parse(Path(s["transcript"])) if s.get("transcript") else None
            if not sid or not tx:
                return leave(kind, "no transcript on disk for this session")
            it["mb"] = round(tx["size"] / 1e6, 1)
            it["resume"] = fleet.resume_command("claude", sid, s.get("cwd") or "", s.get("argv"))
            if tx["finished"]:
                it.update(cls="claude-finished", handoff=chain_for(s.get("cwd") or ""))
                it.update(verdict="close", reason=f"finished with {tx['finished']}; chain log {short(it['handoff'] or '') or 'not found'}")
                return it
            if tx["asks"] and tx["last_text"].rstrip().endswith("?"):
                it.update(cls="claude-question", verdict="close",
                          reason="ended its last turn on a question nobody answered: helm --ended lists it as ended-question")
                return it
            it.update(cls="claude-idle", verdict="handoff-then-close",
                      reason="idle with no /handoff: send /handoff first (tidy.py handoff), then close")
            return it
        # non-Claude TUIs and Hermes CLI panes
        if TUI_WAITING.search("\n".join(last_lines(rows, 16))):
            return leave(kind, "screen shows a prompt or question: it is waiting on an answer, not idle")
        if kind not in VERIFIED_RESUME:
            return leave(kind, f"no verified resume form for {kind}: record by hand or leave")
        if not sid:
            return leave(kind, f"{kind} session id unknown (herdr reports none, none in argv): resume could not be recorded")
        it.update(cls=kind, verdict="close", resume=fleet.resume_command(kind, sid, s.get("cwd") or "", s.get("argv")),
                  reason=f"idle {kind} with a verified resume; the ledger records it (no draft check exists for this TUI)")
        return it

    # --- plain shell
    if procs is None:
        return leave("shell", "herdr could not read the pane's processes")
    fg = [pr for pr in procs if (pr.get("name") or pr.get("argv0") or "") not in SHELLS]
    if fg:
        return leave("shell", "a foreground process is running: " + clip(" ".join(pr.get("name") or "" for pr in fg), 80))
    kids = fleet.background_work(shell_pid, table) if shell_pid else None
    if kids:
        return leave("shell", "the shell has child processes: " + "; ".join(kids[:2]))
    rows = screen(pane, 24)
    tail = last_lines(rows, 1)
    if not tail or not SHELL_PROMPT.search(tail[0]):
        return leave("shell", f"last line is not a bare prompt: {clip(tail[0] if tail else '', 60)!r}")
    it.update(cls="shell", verdict="close", reason="bare prompt, no process; the ledger keeps the screen tail")
    return it


def chain_for(cwd):
    """Newest Tier 1 chain log whose workspaces include CWD's repo, if any."""
    top = fleet.toplevel(cwd) if cwd else ""
    best = None
    for log in (fleet.HANDOFFS / "chains").glob("*/SESSION_LOG.md"):
        try:
            fm = log.read_text(errors="replace").split("---", 2)[1]
        except (OSError, IndexError):
            continue
        dirs = {fleet.toplevel(d) for d in re.findall(r"^\s+dir:\s*(\S+)", fm, re.MULTILINE)}
        if top and top in dirs and (best is None or log.stat().st_mtime > best.stat().st_mtime):
            best = log
    return str(best) if best else None


def inventory():
    panes = herdr_json("pane", "list").get("panes") or []
    sess = {}
    for s in fleet.sessions(include_shell=True):
        if s.get("chan") and s["chan"][0] == "herdr":
            sess[s["chan"][1]] = s
    journal = {}
    for key, e in fleet.sleeper_journal().items():
        journal[e.get("pane_id") or key] = e
    return panes, sess, journal, fleet.claims(), fleet.proc_table()


def scan():
    panes, sess, journal, claims, table = inventory()
    return [classify(p, sess, journal, claims, table) for p in panes]


# ---- actions -----------------------------------------------------------------------------------

def ledger_append(entry):
    fleet.STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(fleet.STATE_DIR, 0o700)
    with fleet.CLOSED.open("a") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    os.chmod(fleet.CLOSED, 0o600)


def who():
    return f"{(os.environ.get('CLAUDE_CODE_SESSION_ID') or '')[:8] or 'cli'} pane {os.environ.get('HERDR_PANE_ID') or '?'}"


def cmd_scan(a):
    items = scan()
    if a.json:
        print(json.dumps(items, ensure_ascii=False, default=str))
        return 0
    for it in items:
        head = f"{it['pane']:8} {it['tab_label']:22} {it['agent']:9} {it['cls'] or '?':16} {it['verdict']:19} {it['reason']}"
        print(head)
        if it.get("resume"):
            print(f"{'':8} resume: {it['resume']}")
    n = {v: sum(1 for it in items if it["verdict"] == v) for v in ("close", "handoff-then-close", "leave", "never")}
    print(f"\n{len(items)} panes · {n['close']} close · {n['handoff-then-close']} handoff-then-close · {n['leave']} leave · {n['never']} never")
    return 0


def find(pane):
    panes, sess, journal, claims, table = inventory()
    p = next((x for x in panes if x["pane_id"] == pane), None)
    if not p:
        sys.exit(f"tidy: pane {pane} not found")
    return classify(p, sess, journal, claims, table), sess.get(pane) or {}


def cmd_handoff(a):
    it, s = find(a.pane)
    if it["verdict"] != "handoff-then-close":
        sys.exit(f"tidy: {a.pane} is {it['cls']} / {it['verdict']}: {it['reason']}; nothing sent")
    start = time.time()
    if run(HERDR, "agent", "prompt", a.pane, "/handoff", timeout=20)[0] != 0:
        sys.exit(f"tidy: could not submit /handoff to {a.pane}")
    print(f"sent /handoff to {a.pane} ({it['title']!r}); waiting up to {a.timeout}s for the transcript to show it finished")
    path = Path(s["transcript"])
    while time.time() - start < a.timeout:
        time.sleep(5)
        tx = fleet.parse(path)
        ag = herdr_json("agent", "get", a.pane).get("agent") or {}
        if tx["finished"] == "/handoff" and ag.get("agent_status") in ("idle", "done"):
            chain = chain_for(s.get("cwd") or "")
            fresh = chain and Path(chain).stat().st_mtime >= start
            print(f"handoff finished after {int(time.time() - start)}s; chain log {chain or 'not found'}"
                  f"{' (updated)' if fresh else ' (NOT updated since the handoff started)' if chain else ''}")
            print(f"last reply: {clip(tx['last_text'], 300)}")
            return 0 if fresh else 1
    sys.exit(f"tidy: {a.pane} has not finished its /handoff after {a.timeout}s; check: herdr tab focus {it['tab']}")


def cmd_close(a):
    it, _s = find(a.pane)
    if it["verdict"] != "close":
        sys.exit(f"tidy: refused: {a.pane} is {it['cls']} / {it['verdict']}: {it['reason']}")
    rows = screen(a.pane)
    if it["cls"] in ("claude-finished", "claude-question") and claude_composer(rows)[0] != "empty":
        sys.exit(f"tidy: refused: {a.pane} composer changed (now {claude_composer(rows)[0]}); re-run scan")
    p = herdr_json("pane", "get", a.pane).get("pane") or {}
    if not p or p.get("focused"):
        sys.exit(f"tidy: refused: {a.pane} is focused or gone")
    tab_panes = [x for x in (herdr_json("pane", "list").get("panes") or []) if x.get("tab_id") == it["tab"]]
    resume = a.resume or it.get("resume") or ""
    ts = time.strftime("%Y%m%d-%H%M%S")
    entry = {"id": f"closed:{ts}-{a.pane}", "t": time.time(), "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
             "pane": a.pane, "tab": it["tab"], "workspace": it["workspace"], "label": it["label"], "tab_label": it["tab_label"],
             "agent": it["agent"], "cls": it["cls"], "title": it["title"], "cwd": it["cwd"], "sid": it.get("sid"),
             "resume": resume, "why": (a.why + "; " if a.why else "") + it["reason"], "by": who(),
             "handoff": it.get("handoff"), "mb": it.get("mb"), "launch": it.get("launch"),
             "journal": it.get("journal"), "screen": [r for r in rows if r.strip()][-SCREEN_LINES:]}
    if a.dry_run:
        print(json.dumps({k: v for k, v in entry.items() if k != "screen"}, ensure_ascii=False, default=str))
        print(f"dry run: would close {'tab ' + it['tab'] if len(tab_panes) == 1 else 'pane ' + a.pane}")
        return 0
    ledger_append(entry)
    if it.get("close_cmd"):
        rc, out = run(*it["close_cmd"], timeout=120)
        print(out.strip())
    elif len(tab_panes) == 1:
        rc, out = run(HERDR, "tab", "close", it["tab"])
    else:
        rc, out = run(HERDR, "pane", "close", a.pane)
    time.sleep(1)
    if pane_exists(a.pane):
        print(f"tidy: ledger written ({entry['id']}) but {a.pane} still exists (rc {rc}): {clip(out, 120)}")
        return 1
    print(f"closed {a.pane} ({it['cls']}, {'tab ' + it['tab_label'] if len(tab_panes) == 1 else 'pane only'}) → ledger {entry['id']}"
          + (f"; resume: {resume}" if resume else ""))
    return 0


def cmd_ledger(a):
    rows = fleet.closed_ledger(a.days)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, default=str))
        return 0
    for d in rows:
        flag = " (resumed)" if d.get("resumed") else ""
        print(f"[{d['id']}] {d.get('agent')} {d.get('cls')}  {short(d.get('cwd', ''))}  {d.get('when')}{flag}")
        if d.get("title"):
            print(f"    {d['title']}")
        print(f"    why: {d.get('why', '')}")
        if d.get("resume"):
            print(f"    resume: {d['resume']}")
    return 0 if rows else 1


def cmd_resumed(a):
    ids = {d["id"] for d in fleet.closed_ledger()}
    if a.id not in ids:
        sys.exit(f"tidy: no ledger entry {a.id}")
    ledger_append({"id": a.id, "resumed": True, "resumed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "by": who()})
    print(f"marked {a.id} resumed")
    return 0


def main():
    ap = argparse.ArgumentParser(prog="tidy.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_scan)
    p = sub.add_parser("handoff")
    p.add_argument("pane")
    p.add_argument("--timeout", type=int, default=HANDOFF_TIMEOUT)
    p.set_defaults(fn=cmd_handoff)
    p = sub.add_parser("close")
    p.add_argument("pane")
    p.add_argument("--why", default="")
    p.add_argument("--resume", default="")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_close)
    p = sub.add_parser("ledger")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_ledger)
    p = sub.add_parser("resumed")
    p.add_argument("id")
    p.set_defaults(fn=cmd_resumed)
    a = ap.parse_args()
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
