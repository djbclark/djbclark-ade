#!/usr/bin/env python3
"""tidy — close idle herdr panes or Orca terminals without losing anything helm cannot find again. Runs no model.

    tidy.py [--host herdr|orca|auto] scan [--json]
                                            every pane: class, verdict (close / handoff-then-close / leave / never)
                                            and the reason, with the resume command the ledger would record
    tidy.py handoff <pane> [--timeout S]    send /handoff to an idle Claude pane (empty composer verified on
                                            screen) and wait until its transcript shows the handoff finished
    tidy.py close <pane> [--why TEXT] [--resume CMD] [--dry-run]
                                            re-check every precondition right before acting, append the close
                                            ledger (resume command, screen tail, journal entry), then close the
                                            tab when the pane is its only pane, else the pane
    tidy.py ledger [--days N] [--json]      the close ledger, newest first
    tidy.py resumed <ledger-id>             mark an entry resumed so helm stops listing it

Hosts: `herdr` (panes; the default outside Orca) and `orca` (terminals, `/orca-tidy`); `auto` picks orca when
this process runs inside an Orca terminal (ORCA_PANE_KEY), else herdr; TIDY_HOST overrides. A <pane> is a herdr
pane id, or an Orca terminal handle, pane key (tabId:leafId) or unique handle prefix.

Pane classes and the rule for each are in SKILL.md next to this file. Every "close" is fail-closed: a pane
whose state cannot be verified (composer not on screen, the host cannot tell idle from working, a draft in the
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
HOST = "herdr"                                            # set by main() / detect_host(); tests set it directly
SCREEN_LINES = 60
HANDOFF_TIMEOUT = 900
PROTECTED_TABS = re.compile(r"^(helm|coord)(\b|[-_])", re.IGNORECASE)
POPUP_PROCS = re.compile(r"(collie|drovr|herdr-jump|herdr-navigator)", re.IGNORECASE)
SHELLS = {"bash", "zsh", "fish", "sh", "-bash", "-zsh", "-fish", "-sh"}
SHELL_PROMPT = re.compile(r"[$%#>]\s*$")                  # bash/zsh/fish prompt with nothing typed after it
STUB_PROMPT = "press Enter to resume"                     # herdr-sleeper's in-pane stub
PLACEHOLDER = re.compile(r'^Try "[^"]*"$')                # Claude Code's dim hint in an empty composer, not a draft
TUI_WAITING = re.compile(r"(\[y/N\]|\[Y/n\]|Enter to (select|submit|confirm)|Question \d+ of \d+|\(y/n\)|to select)", re.IGNORECASE)
VERIFIED_RESUME = set(fleet.RESUME_FORMS)                 # kinds whose resume form was read from `<tui> --help`

# ---- Orca ---------------------------------------------------------------------------------------
# Orca (stablyai/orca, 1.4.219 on 2026-10-08) has no pane API like herdr's; the adapter joins `terminal list
# --include-visual-layouts` (live terminals, tab topology) with `worktree ps` (hook-fed agent state per pane key
# tabId:leafId), reads screens with `terminal read --screen`, and finds a terminal's processes through the
# ORCA_PANE_KEY their environment carries (one `ps eww -ax`). Hazards designed around, all open upstream:
# #14719 close --tab may leave the TUI running (re-list after every close); #23865 close skips Claude Code's
# SessionEnd hooks (/exit first); #23833 closing a Codex pane can kill a shared `codex app-server`; #14561 `wait
# --for tui-idle` lies (never used); #23921 `worktree ps` rows lack agentWait (`terminal show` per terminal).
ORCA_GLYPHS = re.compile(r"^[\s✳◐◑◒◓●○◌⏺✻\U0001f4a4⚠️]+")
ORCA_STATE = {"working": "working", "done": "idle", "idle": "idle", "waiting": "blocked", "blocked": "blocked",
              "permission": "blocked"}
ORCA_LAST_STATUS = Path.home() / "Library/Application Support/orca/agent-hooks/last-status.json"
ORCA_KEY_ENV = re.compile(r"(?:^|\s)ORCA_PANE_KEY=(\S+)")
COMPOSER_GLYPHS = ("❯", "›", "»")          # ❯ › »: the prompts Orca's draft detector knows


def detect_host(explicit="auto"):
    if explicit in ("herdr", "orca"):
        return explicit
    env = os.environ.get("TIDY_HOST", "")
    if env in ("herdr", "orca"):
        return env
    if os.environ.get("ORCA_PANE_KEY") or os.environ.get("TERM_PROGRAM") == "Orca":
        return "orca"
    return "herdr"


def orca_call(*args, timeout=15):
    """(ok, result-or-error) of one `orca … --json` call. A missing binary, a dead runtime or bad JSON is
    (False, {code: 'no-json', …}): callers fail closed on it."""
    rc, out = run("orca", *args, "--json", timeout=timeout)
    try:
        d = json.loads(out)
    except (ValueError, TypeError):
        return False, {"code": "no-json", "message": clip(out or "", 200), "rc": rc}
    if not isinstance(d, dict):
        return False, {"code": "no-json", "message": clip(out, 200), "rc": rc}
    return bool(d.get("ok")), (d.get("result") if d.get("ok") else d.get("error")) or {}


def _orca_tabs(layouts):
    """tabId -> {title, n (terminal leaves), active_leaf, is_active_tab, worktree} from visualLayouts; walks the
    tree generically so split groups and nested pane trees count every terminal leaf."""
    tabs = {}

    def leaves(node):
        if isinstance(node, dict):
            if node.get("type") == "terminal":
                return [node]
            return [x for v in node.values() for x in leaves(v)]
        if isinstance(node, list):
            return [x for v in node for x in leaves(v)]
        return []

    def walk(node, active, worktree):
        if isinstance(node, dict):
            if "activeTabId" in node:
                active = node["activeTabId"]
            if "tabId" in node and "panes" in node:
                tabs[node["tabId"]] = {"title": node.get("title") or "", "n": len(leaves(node["panes"])),
                                       "active_leaf": node.get("activeLeafId"), "is_active_tab": node["tabId"] == active,
                                       "worktree": worktree}
                return
            for v in node.values():
                walk(v, active, worktree)
        elif isinstance(node, list):
            for v in node:
                walk(v, active, worktree)

    for lay in layouts or []:
        if isinstance(lay, dict):
            walk(lay.get("root") or lay, None, lay.get("worktreeId"))
    return tabs


def orca_env_map():
    """pane key -> [pid] for every process whose environment carries ORCA_PANE_KEY (one `ps eww -ax`; BSD ps
    shows other processes' environments only in this spelling). Empty when ps fails: callers fail closed."""
    m = {}
    for line in run("ps", "eww", "-ax", "-o", "pid=,command=", timeout=10)[1].splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            hits = ORCA_KEY_ENV.findall(parts[1])        # argv comes first: the LAST hit is the environment's
            if hits:
                m.setdefault(hits[-1], []).append(int(parts[0]))
    return m


def orca_last_status():
    """Orca's hook ledger, pane key -> latest entry (providerSession.id, transcriptPath, payload.state). Entries
    outlive the agent, so a reader must join on a live agent row before trusting one."""
    try:
        d = json.loads(ORCA_LAST_STATUS.read_text())
        entries = d.get("entries") if isinstance(d, dict) else None
        return entries if isinstance(entries, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def orca_terminals():
    """handle -> pane record for every live Orca terminal: `terminal list` ⋈ layouts ⋈ `worktree ps` agents ⋈
    hook ledger ⋈ process environments. None when Orca cannot be listed (fail closed, nothing to act on)."""
    ok, r = orca_call("terminal", "list", "--include-visual-layouts")
    if not ok:
        return None
    tabs = _orca_tabs(r.get("visualLayouts"))
    ok2, ps = orca_call("worktree", "ps")
    agents, active_wt = {}, set()
    by_tab = {}
    for t in r.get("terminals") or []:
        if isinstance(t, dict) and t.get("handle") and not t.get("orphaned"):
            by_tab[t.get("tabId")] = by_tab.get(t.get("tabId"), 0) + 1
    rank = {"working": 3, "waiting": 2, "blocked": 2, "permission": 2, "done": 1, "idle": 1}
    for w in (ps.get("worktrees") or []) if ok2 else []:
        if not isinstance(w, dict):
            continue
        if w.get("isActive"):
            active_wt.add(w.get("worktreeId"))
        for a in w.get("agents") or []:
            if isinstance(a, dict) and a.get("paneKey"):
                prev = agents.get(a["paneKey"])      # two rows for one pane (teammates): the busiest state wins
                if prev is None or rank.get(a.get("state") or "", 0) >= rank.get(prev.get("state") or "", 0):
                    agents[a["paneKey"]] = a
    status, env = orca_last_status(), orca_env_map()
    out = {}
    for t in r.get("terminals") or []:
        if not isinstance(t, dict) or not t.get("handle") or t.get("orphaned"):
            continue
        key = f"{t.get('tabId')}:{t.get('leafId')}"
        tab = tabs.get(t.get("tabId")) or {}
        a = agents.get(key) or {}
        ls = status.get(key) if a else None
        ls = ls if isinstance(ls, dict) else {}
        sess = ls.get("providerSession")
        sess = sess if isinstance(sess, dict) else {}
        # focus is a derived fact: None (unknown → never closed) unless `worktree ps` answered, exactly one worktree
        # is active and this tab is in the layouts; else active leaf of the active tab of the active worktree
        if not ok2 or len(active_wt) != 1 or not tab:
            focused = None
        else:
            focused = bool(tab.get("is_active_tab") and tab.get("active_leaf") == t.get("leafId")
                           and t.get("worktreeId") in active_wt)
        n_layout, n_list = tab.get("n") or 0, by_tab.get(t.get("tabId"), 0)
        tab_panes = 1 if n_layout == 1 and n_list == 1 else max(n_layout, n_list, 2)   # --tab only when both agree on 1
        out[t["handle"]] = {
            "pane_id": t["handle"], "tab_id": t.get("tabId") or "", "leaf_id": t.get("leafId") or "", "pane_key": key,
            "workspace_id": t.get("worktreeId") or "", "cwd": t.get("worktreePath") or "", "label": "",
            "tab_label": ORCA_GLYPHS.sub("", tab.get("title") or t.get("title") or ""),
            "terminal_title_stripped": ORCA_GLYPHS.sub("", t.get("title") or ""), "focused": focused,
            "tab_panes": tab_panes, "agent": a.get("agentType") or None,
            "agent_status": ORCA_STATE.get(a.get("state") or "", "unknown") if a else None,
            "agent_session": {"value": sess["id"]} if sess.get("id") else None, "transcript": sess.get("transcriptPath"),
            "self": bool(key) and key == os.environ.get("ORCA_PANE_KEY"), "pids": env.get(key) or [], "host": "orca"}
    return out


def orca_live_handles():
    ok, r = orca_call("terminal", "list")
    return {t["handle"] for t in (r.get("terminals") or []) if isinstance(t, dict) and t.get("handle")} if ok else None


def orca_read(handle, lines=SCREEN_LINES):
    """(screen rows, draft): the rendered screen and Orca's own reading of the composer (`draft`, present only
    when its detector found text after a ❯ › » prompt). (None, None) when the screen could not be read."""
    ok, r = orca_call("terminal", "read", "--terminal", handle, "--screen", "--limit", str(lines))
    t = (r.get("terminal") or {}) if ok else {}
    if not ok or t.get("source") == "screen-unavailable":
        return None, None
    return [ln.rstrip() for ln in t.get("tail") or []], t.get("draft")


def orca_agent_wait(handle):
    """`terminal show`'s agentWait: a prompt the TUI is waiting on (stablyai/orca#23921: not in `worktree ps`).
    'unknown' when the call fails."""
    ok, r = orca_call("terminal", "show", "--terminal", handle)
    t = r.get("terminal") if ok and isinstance(r, dict) else None
    if not isinstance(t, dict) or "agentWait" not in t:
        return "unknown"
    return t.get("agentWait")


def orca_agent_status(key):
    """Current hook state for a pane key from `worktree ps`, mapped to idle/working/blocked; None = no agent row."""
    ok, ps = orca_call("worktree", "ps")
    if not ok:
        return "unknown"
    for w in ps.get("worktrees") or []:
        for a in w.get("agents") or []:
            if a.get("paneKey") == key:
                return ORCA_STATE.get(a.get("state") or "", "unknown")
    return None


def orca_send(handle, text, wait=15):
    """Send TEXT + Enter as an agent prompt; True when Orca's receipt says the input was accepted."""
    ok, r = orca_call("terminal", "send", "--terminal", handle, "--text", text, "--enter", "--wait-submit", str(wait),
                      timeout=wait + 20)
    send = (r.get("send") or {}) if ok else {}
    return bool(ok and send.get("accepted")), r


def orca_status_merge(p, s):
    """One status for an Orca pane from Orca's hook state and fleet's (registry / process scan): any 'working',
    'busy-background' or 'blocked' wins; 'idle' needs both to agree or the other to be silent."""
    a, b = p.get("agent_status") or "unknown", s.get("status") or "unknown"
    for st in ("working", "busy-background", "blocked"):
        if st in (a, b):
            return st
    if "idle" in (a, b) and {a, b} <= {"idle", "unknown"}:
        return "idle"
    return b if b != "unknown" else a


# ---- reading a pane (host dispatch) ------------------------------------------------------------

def screen(pane, lines=SCREEN_LINES):
    if HOST == "orca":
        rows, _draft = orca_read(pane, lines)
        return rows if rows is not None else []
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
            if PLACEHOLDER.match(text):
                return "empty", ""
            return ("draft" if text else "empty"), text
    return "unknown", ""


def pane_exists(pane):
    if HOST == "orca":
        live = orca_live_handles()
        return True if live is None else pane in live          # cannot list → assume it is still there
    return bool(herdr_json("pane", "get", pane).get("pane"))


def pane_now(pane):
    """The pane's current record (focused flag included), or None when it is gone."""
    if HOST == "orca":
        terms = orca_terminals()
        return None if terms is None else terms.get(pane)
    return herdr_json("pane", "get", pane).get("pane") or None


def tab_label_of(p):
    if "tab_label" in p:
        return p["tab_label"]
    return fleet.herdr_label("tab", p["tab_id"]).split("#", 1)[0]


def procs_of(p, table):
    """[{pid, name, argv, argv0, cwd}], shell pid for a pane: herdr's `pane process-info`, or for Orca the shell
    whose environment carries the pane key plus everything under it. (None, None) = could not read."""
    if HOST != "orca":
        return fleet.pane_procs(p["pane_id"])
    pids = [pid for pid in p.get("pids") or [] if pid in table]
    if not pids:
        return None, None
    mine = set(pids)
    roots = [pid for pid in pids if table[pid][0] not in mine]
    if len(roots) != 1:
        return None, None            # two unrelated trees claim one pane key (an impostor argv?): cannot tell whose
    shell = next((pid for pid in roots if os.path.basename((table[pid][1].split() or [""])[0]) in SHELLS), None)
    shell = shell or (roots[0] if roots else pids[0])
    out = []
    for pid in [shell] + fleet.descendants(shell, table):
        cmd = table.get(pid, (0, ""))[1]
        argv = cmd.split()
        out.append({"pid": pid, "name": os.path.basename(argv[0]) if argv else "", "argv": argv,
                    "argv0": argv[0] if argv else "", "cwd": ""})
    return out, shell


def focus_hint(p):
    if HOST == "orca":
        return f"orca terminal switch --terminal {p['pane_id']}"
    return f"herdr tab focus {p['tab_id']}"


# ---- classification ----------------------------------------------------------------------------

def _live_claims():
    return [c for c in fleet.claims()]


def _claimed_by(c_list, pane, tab, sid, name, key=""):
    for c in c_list:
        hay = c.get("session", "")
        for needle in (pane, tab, (sid or "")[:8], name, key):
            if needle and needle in hay:
                return c["task"]
    return ""


def classify(p, sess, journal, claims, table):
    """One pane -> {pane, tab, workspace, label, agent, cls, verdict, reason, resume, ...}.
    verdict: 'never' (structural), 'leave' (not now, reason says what would change it),
    'handoff-then-close' (idle Claude with no handoff yet), 'close' (every precondition holds)."""
    pane, tab = p["pane_id"], p["tab_id"]
    tab_label = tab_label_of(p)
    s = dict(sess.get(pane) or {})
    sid = s.get("sid") or (p.get("agent_session") or {}).get("value")
    orca = HOST == "orca"
    if orca and s and s.get("host") != "acp":
        s["status"] = orca_status_merge(p, s)
        if not s.get("transcript") and p.get("transcript"):
            s["transcript"] = p["transcript"]
    it = {"pane": pane, "tab": tab, "workspace": p["workspace_id"], "label": p.get("label") or "", "tab_label": tab_label,
          "agent": s.get("agent") or p.get("agent") or "shell", "title": s.get("title") or p.get("terminal_title_stripped") or "",
          "cwd": s.get("cwd") or p.get("cwd") or "", "sid": sid, "status": s.get("status") or p.get("agent_status") or "unknown",
          "cls": "", "verdict": "leave", "reason": "", "resume": "", "handoff": None, "busy": s.get("busy") or [],
          "host": HOST, "pid": s.get("pid"), "shell_pid": None}
    if orca:
        it.update(pane_key=p.get("pane_key"), tab_panes=p.get("tab_panes") or 1)

    def leave(cls, reason, verdict="leave"):
        it.update(cls=cls, verdict=verdict, reason=reason)
        return it

    if p.get("focused"):
        return leave("focused", "the operator is in this pane", "never")
    if orca and p.get("focused") is None:
        return leave("focused", "cannot tell which terminal the operator is in (worktree ps failed, no single active "
                                "worktree, or this tab is missing from the layouts)", "never")
    if p.get("self") or s.get("self") or (not orca and pane == os.environ.get("HERDR_PANE_ID")):
        return leave("self", "this session", "never")
    if PROTECTED_TABS.match(tab_label) or PROTECTED_TABS.match(it["title"] or "") or PROTECTED_TABS.match(p.get("label") or ""):
        return leave("orchestrator", f"helm/coord pane (tab {tab_label!r}): never closed", "never")
    task = _claimed_by(claims, pane, tab, sid, s.get("name", ""), p.get("pane_key") or "")
    if task:
        return leave("claimed", f"live bigteam claim {task} names this session", "never")
    procs, shell_pid = procs_of(p, table)
    it["shell_pid"] = shell_pid
    names = " ".join((pr.get("name") or "") + " " + " ".join(pr.get("argv") or []) for pr in procs or [])
    if any(POPUP_PROCS.search(os.path.basename(pr.get("argv0") or pr.get("name") or "")) for pr in procs or []):
        return leave("popup", "a tool's popup pane (collie/drovr/herdr-jump): close it through the tool", "never")

    # --- ACP launch hosted here
    if s.get("host") == "acp":
        if s["status"] == "working":
            return leave("acp", f"ACP launch {s['id']} is working")
        if orca:
            return leave("acp", f"ACP launch {s['id']} is {s['status']} in an Orca terminal: launch.py close does not close "
                                f"Orca terminals (unverified); by hand: launch.py close {s['id']}, then orca terminal close "
                                f"--terminal {pane}")
        it.update(cls="acp", verdict="close", reason=f"ACP launch {s['id']} is {s['status']}: close with launch.py close {s['id']}",
                  resume=f"python3 -I {HERE.parent / 'session-finder' / 'launch.py'} reply {s['id']} \"<text>\"", launch=s["id"],
                  close_cmd=[sys.executable, "-I", str(HERE.parent / "session-finder" / "launch.py"), "close", s["id"]])
        return it

    # --- herdr-sleeper stub (herdr only; Orca hibernates whole worktrees, which then have no live terminal)
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

    # --- a session fleet knows (claude, hermes, any TUI herdr/Orca detected or process-info revealed)
    if s and s.get("status") != "shell":
        kind = s["agent"]
        if s["status"] == "working":
            return leave(kind, "working")
        if s["status"] == "busy-background":
            return leave(kind, "idle to the host but child processes are in flight: " + "; ".join(s["busy"][:2]))
        if s["status"] == "blocked":
            return leave(kind, "waiting on a prompt: answer it through helm first")
        if s["status"] not in ("idle",):
            return leave(kind, f"{'Orca' if orca else 'herdr'} cannot tell idle from working for this pane (status {s['status']}); decide by hand")
        if orca and kind == "codex" and procs is None:
            return leave(kind, "processes of this Codex pane are not readable: cannot rule out a shared `codex app-server` (stablyai/orca#23833)")
        if orca and kind == "codex" and any("app-server" in " ".join(pr.get("argv") or []) for pr in procs or []):
            return leave(kind, "Codex pane hosts a `codex app-server` daemon other sessions may share (stablyai/orca#23833): close by hand")
        draft = None
        if orca:
            rows, draft = orca_read(pane)
            if rows is None:
                return leave(kind, "Orca could not render this terminal's screen (screen-unavailable): cannot verify an empty input box")
            wait = orca_agent_wait(pane)
            if wait:
                return leave(kind, "waiting on a prompt (terminal show agentWait): answer it through helm first"
                                   if wait != "unknown" else "terminal show failed: cannot rule out a pending prompt")
            if (draft or "").strip() and not PLACEHOLDER.match(draft.strip()):
                return leave(kind, f"unsent draft in the input box (Orca draft): {clip(draft.strip(), 60)!r}")
        else:
            rows = screen(pane)
        if kind == "claude":
            state, text = claude_composer(rows)
            if state == "draft":
                return leave(kind, f"unsent draft in the input box: {clip(text, 60)!r}")
            if state == "unknown":
                return leave(kind, "composer line not visible on screen: cannot verify an empty input box "
                                   f"(focus it: {focus_hint(p)}, let it redraw, rerun)")
            tx = fleet.parse(Path(s["transcript"])) if s.get("transcript") else None
            if not sid or not tx:
                return leave(kind, "no transcript on disk for this session")
            it["mb"] = round(tx["size"] / 1e6, 1)
            it["resume"] = fleet.resume_command("claude", sid, s.get("cwd") or "", s.get("argv"))
            if not tx["last_prompt"].strip():
                return leave(kind, "fresh session, no prompt yet: nothing to hand off (close it by hand if unwanted)")
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
        if orca and not any(ln.lstrip().startswith(COMPOSER_GLYPHS) for ln in last_lines(rows, 6)):
            return leave(kind, f"no ❯ › » prompt line on screen, so Orca cannot read a draft for this {kind}: "
                               "close by hand after a look")
        if kind not in VERIFIED_RESUME:
            return leave(kind, f"no verified resume form for {kind}: record by hand or leave")
        if not sid:
            return leave(kind, f"{kind} session id unknown (host reports none, none in argv): resume could not be recorded")
        it.update(cls=kind, verdict="close", resume=fleet.resume_command(kind, sid, s.get("cwd") or "", s.get("argv")),
                  reason=f"idle {kind} with a verified resume; the ledger records it "
                         + ("(Orca reported no draft; its detector covers \u276f \u203a \u00bb prompts)" if orca
                            else "(no draft check exists for this TUI)"))
        return it

    # --- Orca says an agent runs here, but no session matched this terminal (a teammate / agent-teams terminal,
    #     a TUI fleet does not detect, or a stale agent row): never a shell, never closed
    if orca and p.get("agent") and not s:
        return leave(p["agent"], f"Orca reports a {p['agent']} agent here (state {p.get('agent_status') or 'unknown'}) but fleet "
                                 "matched no session to this terminal: decide by hand")

    # --- plain shell
    if procs is None:
        return leave("shell", ("ps shows no process carrying this pane key" if orca else "herdr could not read the pane's processes"))
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
    """(panes, sessions by pane, sleeper journal by pane, live claims, process table) for the current host."""
    if HOST == "orca":
        terms = orca_terminals()
        if terms is None:
            sys.exit("tidy: orca terminal list failed (Orca not running, or its runtime is down): nothing to act on")
        table = fleet.proc_table()
        key_of_pid = {pid: p["pane_key"] for p in terms.values() for pid in p["pids"]}
        by_key = {p["pane_key"]: h for h, p in terms.items()}
        sess = {}
        for s in fleet.sessions(include_shell=True):
            handle = None
            if s.get("chan") and s["chan"][0] == "orca":
                handle = s["chan"][1]
            elif s.get("host") == "orca" and s.get("pid") in key_of_pid:
                handle = by_key.get(key_of_pid[s["pid"]])       # stale handle in its env; the pane key is stable
            if handle:
                prev = sess.get(handle)
                busy = {"working": 3, "busy-background": 3, "blocked": 2, "idle": 1}
                if prev is None or busy.get(s.get("status") or "", 0) >= busy.get(prev.get("status") or "", 0):
                    sess[handle] = s
        return list(terms.values()), sess, {}, fleet.claims(), table
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
    where = os.environ.get("HERDR_PANE_ID") or os.environ.get("ORCA_PANE_KEY") or "?"
    return f"{(os.environ.get('CLAUDE_CODE_SESSION_ID') or '')[:8] or 'cli'} {HOST} pane {where}"


def show_pane(pane):
    return pane[:18] if HOST == "orca" and pane.startswith("term_") else pane


def cmd_scan(a):
    items = scan()
    if a.json:
        print(json.dumps(items, ensure_ascii=False, default=str))
        return 0
    for it in items:
        head = f"{show_pane(it['pane']):18} {clip(it['tab_label'], 22):22} {it['agent']:9} {it['cls'] or '?':16} {it['verdict']:19} {it['reason']}"
        print(head)
        if it.get("resume"):
            print(f"{'':18} resume: {it['resume']}")
    n = {v: sum(1 for it in items if it["verdict"] == v) for v in ("close", "handoff-then-close", "leave", "never")}
    print(f"\n{len(items)} {HOST} panes · {n['close']} close · {n['handoff-then-close']} handoff-then-close · {n['leave']} leave · {n['never']} never")
    return 0


def resolve(pane, panes):
    """The pane record PANE names: a herdr pane id, or an Orca handle, pane key or unique handle prefix."""
    hit = next((x for x in panes if x["pane_id"] == pane), None)
    if hit or HOST != "orca":
        return hit
    hits = [x for x in panes if x.get("pane_key") == pane or (len(pane) >= 6 and x["pane_id"].startswith(pane))]
    if len(hits) > 1:
        sys.exit(f"tidy: {pane} matches {len(hits)} terminals; give the full handle")
    return hits[0] if hits else None


def find(pane):
    panes, sess, journal, claims, table = inventory()
    p = resolve(pane, panes)
    if not p:
        sys.exit(f"tidy: pane {pane} not found")
    return classify(p, sess, journal, claims, table), sess.get(p["pane_id"]) or {}


def send_prompt(it, text):
    """Submit TEXT as a prompt to the pane's TUI; True when the host confirms it was accepted."""
    if HOST == "orca":
        ok, r = orca_send(it["pane"], text)
        return ok
    return run(HERDR, "agent", "prompt", it["pane"], text, timeout=20)[0] == 0


def agent_idle_now(it):
    if HOST == "orca":
        st = orca_agent_status(it.get("pane_key") or "")
        return st == "idle"
    ag = herdr_json("agent", "get", it["pane"]).get("agent") or {}
    return ag.get("agent_status") in ("idle", "done")


def cmd_handoff(a):
    it, s = find(a.pane)
    if it["verdict"] != "handoff-then-close":
        sys.exit(f"tidy: {a.pane} is {it['cls']} / {it['verdict']}: {it['reason']}; nothing sent")
    start = time.time()
    if not send_prompt(it, "/handoff"):
        sys.exit(f"tidy: could not submit /handoff to {a.pane}")
    print(f"sent /handoff to {it['pane']} ({it['title']!r}); waiting up to {a.timeout}s for the transcript to show it finished")
    path = Path(s["transcript"])
    while time.time() - start < a.timeout:
        time.sleep(5)
        tx = fleet.parse(path)
        if tx["finished"] == "/handoff" and agent_idle_now(it):
            chain = chain_for(s.get("cwd") or "")
            fresh = chain and Path(chain).stat().st_mtime >= start
            print(f"handoff finished after {int(time.time() - start)}s; chain log {chain or 'not found'}"
                  f"{' (updated)' if fresh else ' (NOT updated since the handoff started)' if chain else ''}")
            print(f"last reply: {clip(tx['last_text'], 300)}")
            return 0 if fresh else 1
    sys.exit(f"tidy: {it['pane']} has not finished its /handoff after {a.timeout}s; check: {focus_hint({'pane_id': it['pane'], 'tab_id': it['tab']})}")


def close_pane(it, only_pane, tab_panes):
    """Close the pane (its tab when it is the tab's only pane). (rc, message); the caller verifies it is gone."""
    if it.get("close_cmd"):
        return run(*it["close_cmd"], timeout=120)
    if HOST == "orca":
        if it["cls"] in ("claude-finished", "claude-question") and it.get("pid"):
            # stablyai/orca#23865: closing the terminal skips Claude Code's SessionEnd hooks; /exit runs them
            ok, r = orca_send(it["pane"], "/exit", wait=5)
            if not ok:
                return 1, f"/exit was not accepted ({(r or {}).get('code') or (r or {}).get('refusedReason') or r}); terminal left open"
            for _ in range(60):
                time.sleep(0.5)
                if not fleet.alive(it["pid"]):
                    break
            else:
                return 1, f"/exit sent but pid {it['pid']} is still alive after 30s; terminal left open"
        ok, r = orca_call("terminal", "close", "--terminal", it["pane"], *(["--tab"] if only_pane else []), timeout=60)
        return (0 if ok else 1), (f"{'tab' if only_pane else 'terminal'} closed" if ok else f"{r.get('code')}: {r.get('message')}")
    if only_pane:
        return run(HERDR, "tab", "close", it["tab"])
    return run(HERDR, "pane", "close", it["pane"])


def cmd_close(a):
    it, _s = find(a.pane)
    pane = it["pane"]
    if it["verdict"] != "close":
        sys.exit(f"tidy: refused: {pane} is {it['cls']} / {it['verdict']}: {it['reason']}")
    rows = screen(pane)
    if it["cls"] in ("claude-finished", "claude-question") and claude_composer(rows)[0] != "empty":
        sys.exit(f"tidy: refused: {pane} composer changed (now {claude_composer(rows)[0]}); re-run scan")
    p = pane_now(pane)
    if not p or p.get("focused") is not False:
        sys.exit(f"tidy: refused: {pane} is focused, gone, or its focus cannot be told")
    if HOST == "orca":
        tab_panes = p.get("tab_panes") or 1
    else:
        tab_panes = len([x for x in (herdr_json("pane", "list").get("panes") or []) if x.get("tab_id") == it["tab"]])
    only_pane = tab_panes == 1
    resume = a.resume or it.get("resume") or ""
    ts = time.strftime("%Y%m%d-%H%M%S")
    entry = {"id": f"closed:{ts}-{show_pane(pane)}", "t": time.time(), "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
             "host": HOST, "pane": pane, "tab": it["tab"], "workspace": it["workspace"], "label": it["label"], "tab_label": it["tab_label"],
             "agent": it["agent"], "cls": it["cls"], "title": it["title"], "cwd": it["cwd"], "sid": it.get("sid"),
             "resume": resume, "why": (a.why + "; " if a.why else "") + it["reason"], "by": who(),
             "handoff": it.get("handoff"), "mb": it.get("mb"), "launch": it.get("launch"),
             "journal": it.get("journal"), "screen": [r for r in rows if r.strip()][-SCREEN_LINES:]}
    if HOST == "orca":
        entry["pane_key"] = it.get("pane_key")
    if a.dry_run:
        print(json.dumps({k: v for k, v in entry.items() if k != "screen"}, ensure_ascii=False, default=str))
        print(f"dry run: would close {'tab ' + it['tab'] if only_pane else 'pane ' + pane}"
              + (" (after /exit)" if HOST == "orca" and it["cls"].startswith("claude") else ""))
        return 0
    ledger_append(entry)
    rc, out = close_pane(it, only_pane, tab_panes)
    if it.get("close_cmd"):
        print(out.strip())
    time.sleep(1)
    survivors = [x for x in (it.get("pid"), it.get("shell_pid")) if x and fleet.alive(x)]
    if pane_exists(pane) or survivors:
        print(f"tidy: ledger written ({entry['id']}) but {pane} still exists{' (pids alive: ' + ' '.join(map(str, survivors)) + ')' if survivors else ''} (rc {rc}): {clip(out, 160)}"
              + (" — stablyai/orca#14719 shape: close reported but the terminal survived" if HOST == "orca" and rc == 0 else ""))
        return 1
    print(f"closed {pane} ({it['cls']}, {'tab ' + it['tab_label'] if only_pane else 'pane only'}) → ledger {entry['id']}"
          + (f"; resume: {resume}" if resume else ""))
    return 0


def cmd_ledger(a):
    rows = fleet.closed_ledger(a.days)
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, default=str))
        return 0
    for d in rows:
        flag = " (resumed)" if d.get("resumed") else ""
        host = f" [{d['host']}]" if d.get("host") and d["host"] != "herdr" else ""
        print(f"[{d['id']}]{host} {d.get('agent')} {d.get('cls')}  {short(d.get('cwd', ''))}  {d.get('when')}{flag}")
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
    global HOST
    ap = argparse.ArgumentParser(prog="tidy.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", choices=["herdr", "orca", "auto"], default="auto",
                    help="herdr panes or Orca terminals; auto = orca inside an Orca terminal, else herdr (TIDY_HOST overrides)")
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
    HOST = detect_host(a.host)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
