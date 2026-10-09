#!/usr/bin/env python3
"""fleet — every running agent session on this machine, any TUI, no model.

    fleet.py [--all] [--json]        running sessions (--all: sleeper and plain shell panes too)
    fleet.py ended [--days N] [--json]
                                     ended sessions that still hold open items: a handoff whose
                                     next steps nobody picked up, a last reply that asked a question,
                                     a pane herdr-tidy closed (its ledger carries the resume command),
                                     or a herdr-sleeper journal entry whose pane is gone
    fleet.py show <id> [--json]      one session with its transcript tail
    fleet.py conflicts --cwd DIR [--sid ID]
                                     who else works in that repo: working sessions (exit 1: do not start
                                     a second one, message it instead), live bigteam claims, dirty files,
                                     and whether SID is already live somewhere (never resume it twice)

Sources, merged by pane and session id: herdr `agent list` (any agent kind), the Claude Code
registry (~/.claude/sessions), a process scan for TUIs running outside herdr, Hermes gateway
sessions active in the last day (~/.hermes/state.db, read-only), and the sessions launch.py
started over ACP (~/.local/state/session-finder/launches.jsonl), plus herdr panes whose TUI herdr
did not detect (`pane process-info`). Each record says how to reach the session (`reach`), whether
it already finished with /handoff or /quit (`finished`), and whether an idle-looking session still
has work in flight (`busy`: live child processes that are not its MCP/LSP servers -> status
`busy-background`, never audited, never closed).

Shared by session-find.py, helm.py and launch.py. Exit 0 = something listed, 1 = nothing, 2 = usage.
"""
import argparse
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    import where as _where
except (ImportError, SyntaxError):   # SyntaxError: an older python (3.9) that cannot parse it; locate nothing
    _where = None

HOME = str(Path.home())
CLAUDE = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
HERDR = os.environ.get("HERDR_BIN_PATH") or shutil.which("herdr") or str(Path.home() / ".local/bin/herdr")
STATE_DIR = Path(os.environ.get("SESSION_FINDER_STATE", Path.home() / ".local/state/session-finder"))
LAUNCHES = STATE_DIR / "launches.jsonl"
CLOSED = STATE_DIR / "closed.jsonl"      # herdr-tidy's close ledger (skills/herdr-tidy/tidy.py appends, this reads)
HANDOFFS = Path.home() / ".local/state/handoffs"
HERMES_DB = Path.home() / ".hermes" / "state.db"
_XDG_STATE = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
# herdr-sleeper's journal (pane -> entry), read-only: the plugin's state dir first, the legacy standalone dir second
SLEEPER_JOURNALS = [Path(os.environ.get("HERDR_PLUGIN_STATE_DIR") or _XDG_STATE / "herdr/plugins/djbclark.herdr-sleeper") / "sleeping.json",
                    Path(os.environ.get("HERDR_SLEEPER_STATE") or _XDG_STATE / "herdr-sleeper") / "sleeping.json"]
# a session's own servers: children that are not work in flight (MCP servers, language servers, keep-awake)
SERVER_PROCS = re.compile(r"(\bmcp\b|-mcp\b|langserver|language-server|\blsp\b|marksman|token-savior|caffeinate|"
                          r"maestro\.cli|1password|extrabar|zcode-node-repl|zcode-cli)", re.IGNORECASE)
# how each TUI resumes a session by id (verified against `<tui> --help` on this machine, 2026-10-08; herdr-sleeper's
# KINDS table agrees). {flags} are the launch flags worth replaying, {sid} the session id.
RESUME_FORMS = {"claude": "claude{flags} --resume {sid}", "opencode": "opencode{flags} -s {sid}",
                "codex": "codex{flags} resume {sid}", "cursor": "cursor-agent{flags} --resume {sid}",
                "copilot": "copilot{flags} --resume={sid}", "hermes": "hermes{flags} --resume {sid}",
                "qwen": "qwen{flags} --resume {sid}", "agy": "agy{flags} --conversation {sid}",
                "omp": "omp{flags} --resume={sid}", "zcode": "zcode{flags} --resume {sid}",
                "crush": "crush{flags} --session {sid}", "muse": "muse resume {sid}", "cline": "cline --id {sid}"}
# claude launch flags a resume may replay (the allow-list herdr-sleeper uses); everything else is dropped
REPLAY_BOOL = {"--dangerously-skip-permissions", "--verbose"}
REPLAY_VALUE = {"--model", "--permission-mode", "--add-dir", "--effort"}
TAIL = 600_000          # bytes read from the end of a Claude transcript
HERMES_ACTIVE = 24 * 3600
REG_STATUS = {"busy": "working", "shell": "working", "waiting": "blocked", "idle": "idle"}
# binary name -> agent label, for TUIs running outside herdr (herdr panes are taken from herdr itself)
PROC_AGENTS = {"claude": "claude", "codex": "codex", "cursor-agent": "cursor", "opencode": "opencode",
               "zcode": "zcode", "crush": "crush", "copilot": "copilot", "qwen": "qwen", "agy": "agy",
               "muse": "muse", "cline": "cline", "hermes": "hermes", "grok": "grok", "devin": "devin"}
PROC_SKIP = re.compile(r"(acp|mcp|--acp|gateway|dashboard|language-server|lsp|sleeper|serve\b|Helper|node_modules|"
                       r"claude-agent-acp|codex-acp| -p |--print|exec |run |\bresume-globally\b)")
STRIP = re.compile(r"<(system-reminder|local-command-[a-z]+|command-[a-z]+|pasted_content)\b.*?</\1>", re.DOTALL)
CMD = re.compile(r"<command-name>\s*(/\S+)")
FINISHERS = ("/handoff", "/quit", "/exit")


# ---- small helpers --------------------------------------------------------------------------

def run(*cmd, timeout=10):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return p.returncode, p.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""


def herdr_json(*args):
    try:
        return json.loads(run(HERDR, *args)[1]).get("result") or {}
    except (ValueError, AttributeError):
        return {}


_ORCA = None
ORCA_STALE = "Orca terminal handle stale: use its focus command"


def _orca_terminals():
    """(pane key -> live handle, set of live handles) from one `orca terminal list`, memoised for the process.

    Orca re-issues terminal handles when its runtime restarts, and a process started before the restart keeps
    the old ORCA_TERMINAL_HANDLE in its environment; ORCA_PANE_KEY (tabId:leafId) is stable. Any failure
    (orca missing, runtime down, bad JSON) gives empty results, so no channel is built from a guess."""
    global _ORCA
    if _ORCA is None:
        by_key, live = {}, set()
        rc, out = run("orca", "terminal", "list", "--json", "--include-visual-layouts", timeout=10)
        try:
            terms = json.loads(out)["result"]["terminals"] if rc == 0 else []
            for t in terms:
                handle = t.get("handle")
                if not handle or t.get("orphaned"):
                    continue
                live.add(handle)
                if t.get("tabId") and t.get("leafId"):
                    by_key[f"{t['tabId']}:{t['leafId']}"] = handle
        except (ValueError, KeyError, TypeError, AttributeError):
            by_key, live = {}, set()
        _ORCA = (by_key, live)
    return _ORCA


def _orca_chan(env):
    """('orca', live handle) for a process's Orca env, or None when neither its pane key nor its handle is live."""
    by_key, live = _orca_terminals()
    handle = by_key.get(env.get("ORCA_PANE_KEY") or "")
    if not handle and env.get("ORCA_TERMINAL_HANDLE") in live:
        handle = env["ORCA_TERMINAL_HANDLE"]
    return ("orca", handle) if handle else None


def _in_orca(env):
    return bool(env.get("ORCA_PANE_KEY") or env.get("ORCA_TERMINAL_HANDLE"))


_LABELS = {}


def herdr_label(kind, ident):
    if (kind, ident) not in _LABELS:
        o = herdr_json(kind, "get", ident).get(kind) or {}
        _LABELS[kind, ident] = f"{o.get('label') or '?'}#{o.get('number') or '?'}" if o else ident
    return _LABELS[kind, ident]


def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def ancestors():
    pids, pid = set(), os.getpid()
    for _ in range(15):
        try:
            pid = int(run("ps", "-o", "ppid=", "-p", str(pid))[1].strip())
        except ValueError:
            break
        if pid <= 1:
            break
        pids.add(pid)
    return pids


def short(path):
    return "~" + path[len(HOME):] if path and path.startswith(HOME) else path or ""


def clip(text, n):
    text = " ".join((text or "").split())
    return text if len(text) <= n else "…" + text[-(n - 1):]


def toplevel(path):
    rc, out = run("git", "-C", path or ".", "rev-parse", "--show-toplevel")
    return out.strip() if rc == 0 and out.strip() else (path or "")


# ---- Claude transcripts ---------------------------------------------------------------------

_TX = {}


def transcript(sid):
    hits = sorted((CLAUDE / "projects").glob(f"*/{sid}.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0] if hits else None


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _ts(rec):
    t = rec.get("timestamp")
    if not t:
        return None
    try:
        return time.mktime(time.strptime(t[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
    except ValueError:
        return None


def parse(path):
    """Tail of a Claude transcript: pending tool calls, last reply, the operator's prompts with
    times, whether the session finished (/handoff, /quit), and its typical unattended work stretch."""
    st = path.stat()
    key = (st.st_size, st.st_mtime_ns)
    hit = _TX.get(path)
    if hit and hit[0] == key:
        return hit[1]
    with open(path, "rb") as fh:
        fh.seek(max(0, st.st_size - TAIL))
        lines = fh.read().decode("utf-8", "replace").splitlines()
    if st.st_size > TAIL:
        lines = lines[1:]
    uses, done, answers = {}, set(), {}
    prompts, stops = [], []     # (epoch, text) per operator prompt; epoch per assistant stop (question or end of turn)
    last_text = last_prompt = ""
    last_ts = None
    for line in lines:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not isinstance(r, dict) or r.get("isSidechain"):
            continue
        m = r.get("message") or {}
        content, role = m.get("content"), m.get("role")
        ts = _ts(r)
        if ts:
            last_ts = ts
        if isinstance(content, str):
            if role == "user" and not r.get("isMeta"):
                last_prompt = content
                prompts.append((ts, content))
            continue
        for b in content if isinstance(content, list) else []:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "tool_use":
                uses[b.get("id")] = (b.get("name"), b.get("input") or {})
                if b.get("name") == "AskUserQuestion" and ts:
                    stops.append(ts)
            elif t == "tool_result":
                done.add(b.get("tool_use_id"))
                tur = r.get("toolUseResult")
                if isinstance(tur, dict) and "answers" in tur:
                    answers[b.get("tool_use_id")] = tur["answers"]
            elif t == "text" and (b.get("text") or "").strip():
                if role == "assistant":
                    last_text = b["text"]
                    if ts:
                        stops.append(ts)
                elif role == "user" and not r.get("isMeta"):
                    last_prompt = b["text"]
                    prompts.append((ts, b["text"]))
    info = {"size": st.st_size, "mtime": st.st_mtime, "last_text": last_text, "last_prompt": last_prompt,
            "pending": [(k, n, i) for k, (n, i) in uses.items() if k not in done], "answers": answers,
            "finished": finished_by(prompts, last_text), "stretch_min": work_stretch(prompts, stops),
            "asks": last_text.rstrip().endswith("?") or any(n == "AskUserQuestion" for k, (n, _) in uses.items()
                                                           if k not in done),
            "last_ts": last_ts}
    _TX[path] = (key, info)
    return info


def _cmd_of(text):
    m = CMD.search(text)
    if m:
        return m.group(1).lower()
    t = STRIP.sub(" ", text).strip()
    return t.split()[0].lower() if t.startswith("/") else ""


def finished_by(prompts, last_text=""):
    """'/handoff' when the last real prompt (ignoring command output echoes) was a handoff or
    quit, else ''. A substantive prompt after the handoff means work resumed."""
    for _, text in reversed(prompts[-6:]):
        if "<local-command-stdout>" in text and "<command-name>" not in text:
            continue
        cmd = _cmd_of(text)
        if cmd in FINISHERS:
            return "/handoff" if cmd == "/handoff" or "handoff" in last_text.lower() else cmd
        if len(STRIP.sub(" ", text).strip()) > 40:
            return ""
    return ""


def work_stretch(prompts, stops):
    """Median minutes the session worked after an operator prompt before it next needed one
    (next question or end of turn). None when there is too little history."""
    stops = sorted(s for s in stops if s)
    spans = []
    for ts, _ in prompts:
        if not ts:
            continue
        nxt = next((s for s in stops if s > ts), None)
        if nxt:
            spans.append((nxt - ts) / 60)
    spans = spans[-8:]
    if len(spans) < 2:
        return None
    spans.sort()
    return round(spans[len(spans) // 2], 1)


# ---- sources --------------------------------------------------------------------------------

def _rec(**kw) -> dict:
    base: dict = {"id": "", "agent": "?", "host": "", "sid": None, "name": "", "title": "", "cwd": "", "status": "unknown",
            "where": "", "focus": "", "chan": None, "reach": "", "self": False, "focused": False, "finished": "",
            "pid": None, "transcript": None, "launch": None}
    base.update(kw)
    return base


def _from_herdr(s, a):
    s.update(host="herdr", chan=("herdr", a["pane_id"]), focused=bool(a.get("focused")),
             title=a.get("terminal_title_stripped") or s.get("title") or "",
             focus=f"herdr tab focus {a['tab_id']}", cwd=s.get("cwd") or a.get("cwd") or "",
             where=f"herdr · ws {herdr_label('workspace', a['workspace_id'])} · tab {herdr_label('tab', a['tab_id'])}")
    s.update(pane=a["pane_id"], tab=a["tab_id"], workspace=a["workspace_id"], label=a.get("label") or "",
             herdr_status=a.get("agent_status") or "unknown")
    if a["pane_id"] == os.environ.get("HERDR_PANE_ID"):
        s["self"] = True
    if a.get("agent_status") in ("idle", "working", "blocked", "done"):
        s["status"] = "idle" if a["agent_status"] == "done" else a["agent_status"]


def _acp_pane_of(pid):
    """Walk up from PID to an acp-run process and return the HERDR_PANE_ID it inherited, if any."""
    for _ in range(5):
        _rc, out = run("ps", "-o", "ppid=,command=", "-p", str(pid))
        parts = out.split(None, 1)
        if len(parts) < 2:
            return None
        ppid, cmd = parts[0], parts[1]
        if "acp-run" in cmd:
            return (_where.env_of(pid) if _where else {}).get("HERDR_PANE_ID")
        try:
            pid = int(ppid)
        except ValueError:
            return None
        if pid <= 1:
            return None
    return None


def _claude_sessions(agents_by_sid, used, anc, launch_panes=None):
    me = os.environ.get("CLAUDE_CODE_SESSION_ID")
    launch_panes = launch_panes or {}
    out = []
    for f in sorted((CLAUDE / "sessions").glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        pid, sid = d.get("pid"), d.get("sessionId")
        if not sid or not alive(pid):
            continue
        s = _rec(id=sid[:8], agent="claude", sid=sid, name=d.get("name") or "", cwd=d.get("cwd") or "",
                 status=REG_STATUS.get(d.get("status"), "unknown"), self=(pid in anc or sid == me), pid=pid,
                 reach=f"SendMessage to {d.get('name') or sid[:8]}")
        a = agents_by_sid.get(sid)
        env = _where.env_of(pid) if (_where and not a) else {}
        pane = a["pane_id"] if a else env.get("HERDR_PANE_ID")   # the sdk-ts entrypoint has no herdr hook: use its env
        if not pane and not a and launch_panes:
            pane = _acp_pane_of(pid)   # claude-agent-acp scrubs the env; the acp-run ancestor still has the pane id
        if pane in launch_panes:
            # the Claude Code that claude-agent-acp runs inside one of our ACP launches: one session, not two
            launch = launch_panes[pane]
            launch["sid"], launch["transcript"], launch["pid"] = sid, str(transcript(sid) or ""), pid
            launch["underlying"] = {"name": d.get("name") or "", "status": REG_STATUS.get(d.get("status"), "unknown")}
            if launch["status"] == "working" and REG_STATUS.get(d.get("status")) == "blocked":
                launch["status"] = "blocked"    # e.g. an AskUserQuestion inside the ACP session
            continue
        if a:
            used.add(a["pane_id"])
            _from_herdr(s, a)
        elif _where:
            w = _where.lookup(pid, d.get("procStart", "")) or {}
            s.update(where=w.get("where", ""), focus=w.get("focus", ""), title=w.get("title", ""), host="terminal")
            if _in_orca(env):
                chan = _orca_chan(env)
                s.update(host="orca", **({"chan": chan} if chan else {"reach": ORCA_STALE}))
            elif env.get("TMUX_PANE"):
                s.update(chan=("tmux", env["TMUX_PANE"]), host="tmux")
        path = transcript(sid)
        if path:
            s["transcript"] = str(path)
            tx = parse(path)
            s["finished"] = tx["finished"]
            if not s["title"] and tx["last_prompt"]:
                s["title"] = clip(STRIP.sub(" ", tx["last_prompt"]), 70)
        out.append(s)
    return out


def _other_herdr(agents, used):
    out = []
    for a in agents:
        if a["pane_id"] in used or a.get("agent") in (None, "", "sleeper"):
            continue
        sess = (a.get("agent_session") or {}).get("value")
        s = _rec(id=a["pane_id"], agent=a.get("agent") or "?", sid=sess, cwd=a.get("cwd") or "",
                 reach=f"helm.py send {a['pane_id']} (keys into the pane)")
        _from_herdr(s, a)
        if s["agent"] == "hermes":
            s["reach"] = "ask_hermes (MCP) or helm.py send into the pane"
        out.append(s)
        used.add(a["pane_id"])
    return out


def pane_procs(pane):
    """Foreground processes of a herdr pane (`pane process-info`): [{pid, name, argv, cwd}], shell pid.
    None when herdr could not read them (unknown is not empty)."""
    info = herdr_json("pane", "process-info", "--pane", pane).get("process_info")
    if not isinstance(info, dict):
        return None, None
    procs = []
    for pr in info.get("foreground_processes") or []:
        argv = pr.get("argv") or ([pr["cmdline"]] if pr.get("cmdline") else [])
        procs.append({"pid": pr.get("pid"), "name": pr.get("name") or pr.get("argv0") or "", "argv": argv,
                      "argv0": pr.get("argv0") or "", "cwd": pr.get("cwd") or ""})
    return procs, info.get("shell_pid")


SID_IN_ARGV = re.compile(r"(?:--resume|--session|--conversation|--id|-s|-r)(?:=|$)")


def _tui_of(procs):
    """(agent label, pid, session id, argv) of the TUI running in a pane, from its foreground processes."""
    for pr in procs or []:
        argv = pr["argv"]
        names = [os.path.basename(pr["argv0"] or "")] + [os.path.basename(a) for a in argv[:2]]
        agent = next((PROC_AGENTS[n] for n in names if n in PROC_AGENTS), None)
        if not agent or "stub" in argv[:4] and "herdr-sleeper" in " ".join(argv):
            continue
        sid = None
        for i, tok in enumerate(argv):
            if SID_IN_ARGV.match(tok):
                val = tok.split("=", 1)[1] if "=" in tok else (argv[i + 1] if i + 1 < len(argv) else "")
                if re.fullmatch(r"[0-9A-Za-z_.-]{6,}", val or ""):
                    sid = val
        return agent, pr["pid"], sid, argv
    return None, None, None, None


def _pane_only(panes, used):
    """Panes herdr lists but did not classify as an agent: a TUI it does not detect (zcode, muse, a TUI started
    oddly) becomes a session with status unknown; the rest are plain shells (status `shell`)."""
    tuis, shells = [], []
    for a in panes:
        if a["pane_id"] in used or a.get("agent"):
            continue
        procs, shell_pid = pane_procs(a["pane_id"])
        agent, pid, sid, argv = _tui_of(procs)
        if agent:
            s = _rec(id=a["pane_id"], agent=agent, sid=sid, pid=pid, cwd=a.get("cwd") or "", status="unknown",
                     reach=f"helm.py send {a['pane_id']} (keys into the pane; herdr does not detect this TUI)")
            _from_herdr(s, a)
            s.update(argv=argv, status="unknown", undetected=True)
            tuis.append(s)
        else:
            s = _rec(id=a["pane_id"], agent="shell", cwd=a.get("cwd") or "", status="shell", pid=shell_pid,
                     reach="free pane: launch.py --pane " + a["pane_id"])
            _from_herdr(s, a)
            s.update(status="shell", procs=procs)
            shells.append(s)
        used.add(a["pane_id"])
    return tuis, shells


def _proc_scan(known_pids, known_panes, anc):
    """TUIs running outside herdr (Ghostty, Orca, tmux, ssh). Only the user's own processes."""
    out = []
    _rc, text = run("ps", "-axo", "pid=,ppid=,lstart=,command=", timeout=5)
    for line in text.splitlines():
        parts = line.split(None, 7)
        if len(parts) < 8:
            continue
        pid, cmd = int(parts[0]), parts[7]
        if pid in known_pids or pid == os.getpid() or PROC_SKIP.search(cmd):
            continue
        exe = os.path.basename(cmd.split()[0])
        agent = PROC_AGENTS.get(exe)
        if not agent and len(cmd.split()) > 1:
            agent = PROC_AGENTS.get(os.path.basename(cmd.split()[1]))  # `python … hermes`, `node … cursor-agent`
        if not agent:
            continue
        env = _where.env_of(pid) if _where else {}
        if env.get("HERDR_PANE_ID") in known_panes:
            continue
        if env.get("HERDR_PANE_ID"):
            continue  # a herdr pane herdr did not classify: its agent list is the authority there
        w = (_where.lookup(pid, " ".join(parts[2:7])) or {}) if _where else {}
        sid = None
        m = re.search(r"--(?:resume|session)[= ]([0-9a-f-]{8,})", cmd)
        if m:
            sid = m.group(1)
        s = _rec(id=f"pid{pid}", agent=agent, sid=sid, pid=pid, cwd=w.get("cwd", ""), where=w.get("where", ""),
                 focus=w.get("focus", ""), title=w.get("title", ""), self=pid in anc, host="terminal",
                 reach="no channel: use its focus command", status="unknown")
        if _in_orca(env):
            chan = _orca_chan(env)
            s.update(host="orca", **({"chan": chan, "reach": f"helm.py send pid{pid} (Orca terminal)"} if chan
                                     else {"reach": ORCA_STALE}))
        elif env.get("TMUX_PANE"):
            s.update(chan=("tmux", env["TMUX_PANE"]), host="tmux", reach=f"helm.py send pid{pid} (tmux)")
        out.append(s)
    return out


def _hermes_gateway():
    """Hermes conversations active in the last day (Telegram, desktop, Discord…): not a terminal,
    reached through the hermes MCP server. CLI sessions in herdr panes come from herdr instead."""
    out = []
    if not HERMES_DB.exists():
        return out
    try:
        db = sqlite3.connect(f"file:{HERMES_DB}?mode=ro", uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT id, source, chat_id, thread_id, title, cwd, COALESCE(last_activity_at, started_at) last, "
            "last_activity_description FROM sessions WHERE ended_at IS NULL AND source NOT IN ('cli','oneshot') "
            "AND COALESCE(last_activity_at, started_at) > ? ORDER BY last DESC", (time.time() - HERMES_ACTIVE,)
        ).fetchall()
        db.close()
    except sqlite3.Error:
        return out
    for r in rows:
        target = f"telegram:{r['chat_id']}" + (f":{r['thread_id']}" if r["thread_id"] else "") if r["source"] == "telegram" else r["source"]
        out.append(_rec(id=f"hermes:{r['id'][-8:]}", agent="hermes", host="hermes-gw", sid=r["id"], cwd=r["cwd"] or "",
                        title=(r["title"] or "").strip(), status="idle", where=f"Hermes {r['source']} · {target}",
                        reach=f"ask_hermes, or messages_send target={target} (MCP hermes)",
                        focus=f"hermes --resume {r['id']}"))
    return out


def launches():
    if not LAUNCHES.exists():
        return []
    out = {}
    for line in LAUNCHES.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("id"):
            out[d["id"]] = {**out.get(d["id"], {}), **d}   # later lines update earlier ones
    return list(out.values())


POST_TURN_QUIET = 600   # seconds of no agent activity before post-turn text counts as idle
_ACTIVITY = {"agent_message_chunk", "agent_thought_chunk", "tool_call", "tool_call_update", "plan"}


def _post_turn_quiet(d, last_act):
    """True when an interactive launch's post-turn output has stopped: no agent activity for
    POST_TURN_QUIET seconds and herdr (when it hosts the pane) does not show a new turn running."""
    if not last_act or time.time() - last_act < POST_TURN_QUIET:
        return False
    host = d.get("host") or {}
    if host.get("kind") in ("herdr", "herdr-tui") and host.get("pane"):
        ag = herdr_json("agent", "get", host["pane"]).get("agent") or {}
        if ag.get("agent_status") == "working":
            return False
    return True


def launch_state(d):
    """State of an ACP session launch.py started, from its acp-run log. Non-interactive: working
    until the result record, then idle (exited) with the final text. Interactive (acp-run
    --interactive): a `turn` record ends each turn; after one the process waits for input, so
    the session is idle-and-alive until the runner appends its exit line. An agent can keep
    going after its turn ends with no new prompt (a background task's notification, a /loose
    it runs on itself): that text gets no closing `turn` record, so it counts as idle once the
    agent has been quiet for POST_TURN_QUIET seconds, unless herdr shows the pane working (a
    new prompt; acp-run reports working only at a turn's start). Text ending in a
    question -> blocked (needs an answer). Returns (status, last turn's text, result or None)."""
    log = Path(d.get("log") or "")
    cur, turns, result, last_act = [], [], None, 0.0
    if log.exists():
        for line in log.read_text(errors="replace").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            k, data = r.get("kind"), r.get("data") or {}
            if k == "update" and data.get("sessionUpdate") in _ACTIVITY:
                last_act = r.get("t") or last_act
            if k == "update" and data.get("sessionUpdate") == "agent_message_chunk":
                cur.append((data.get("content") or {}).get("text") or "")
            elif k == "new_session" and data.get("sessionId"):
                d["acp_session"] = data["sessionId"]
            elif k == "load_session":
                d["acp_session"] = data.get("sessionId") or d.get("resumed") or d.get("acp_session")
                d["load_session"] = True   # it loaded once, so it can load again
            elif k == "initialize":
                d["load_session"] = bool((data.get("agentCapabilities") or {}).get("loadSession"))
            elif k == "turn":
                turns.append({**data, "text": "".join(cur)})
                cur = []
            elif k == "result":
                result = data
    final = turns[-1]["text"] if turns and not "".join(cur).strip() else "".join(cur)
    exited = result is not None or d.get("exit") is not None
    if exited:
        status = "blocked" if final.rstrip().endswith("?") else "idle"
        result = result or {"exit": d.get("exit")}
    elif turns and not "".join(cur).strip():
        status = "blocked" if final.rstrip().endswith("?") else "idle"   # between turns, waiting for input
    elif turns and d.get("interactive") and _post_turn_quiet(d, last_act):
        status = "blocked" if final.rstrip().endswith("?") else "idle"   # unprompted post-turn text, now quiet
    else:
        status = "working"
    d["turns"] = len(turns)
    return status, final, result


def _launched(used_panes):
    out = []
    for d in launches():
        if d.get("closed"):
            continue
        status, final, result = launch_state(d)
        host = d.get("host") or {}
        alive_interactive = d.get("interactive") and result is None
        s = _rec(id=d["id"], agent=d.get("agent", "?"), host="acp", sid=d.get("acp_session") or d["id"], name=d.get("name", ""),
                 title=d.get("name") or clip(d.get("prompt_head", ""), 60), cwd=d.get("cwd", ""), status=status,
                 launch={**d, "final": clip(final, 600), "result": result, "alive": result is None}, pid=d.get("pid"),
                 reach=(f"launch.py reply {d['id']} \"<text>\" (next turn in the live ACP session, via its inbox)"
                        if alive_interactive else f"launch.py reply {d['id']} \"<text>\" (new ACP turn, same cwd and brief)"))
        if host.get("kind") == "herdr" and host.get("pane"):
            s.update(chan=("herdr", host["pane"]), focus=f"herdr tab focus {host.get('tab', '')}".strip(),
                     where=f"herdr · ws {herdr_label('workspace', host.get('workspace', ''))} · tab {herdr_label('tab', host.get('tab', ''))} (acp)")
            used_panes.add(host["pane"])
        elif host.get("kind") == "orca":
            term = host.get("terminal")
            if term and term in _orca_terminals()[1]:
                s.update(chan=("orca", term), where=f"Orca · terminal {term} (acp)",
                         focus=f"orca terminal switch --terminal {term}")
            else:
                s["where"] = f"Orca · terminal {term} (acp, handle stale)"
        else:
            s["where"] = "acp (no terminal)"
        if result is not None and status == "idle":
            s["finished"] = "done"
        if d.get("audited_turn") is not None and d.get("turns", 0) > d["audited_turn"]:
            s["audited"] = True         # the /loose turn has completed
        out.append(s)
    return out


def sessions(include_shell=False):
    anc = ancestors()
    agents = herdr_json("agent", "list").get("agents") or []
    panes = herdr_json("pane", "list").get("panes") or []
    by_sid = {(a.get("agent_session") or {}).get("value"): a for a in agents if a.get("agent_session")}
    used = set()
    launched = _launched(used)
    launch_panes = {s["chan"][1]: s for s in launched if s.get("chan") and s["chan"][0] == "herdr"}
    out = _claude_sessions(by_sid, used, anc, launch_panes)
    out += _other_herdr(agents, used)
    out += launched
    tuis, shells = _pane_only(panes, used)
    out += tuis
    known_pids = {s["pid"] for s in out if s.get("pid")}
    out += _proc_scan(known_pids, used | {a["pane_id"] for a in panes}, anc)
    out += _hermes_gateway()
    if include_shell:
        out += shells
    table = proc_table()
    for s in out:
        mark_busy(s, table)
    return out


# ---- work in flight behind an idle-looking session ----------------------------------------------

def proc_table():
    """pid -> (ppid, command) for every process of this user, one `ps` call."""
    table = {}
    for line in run("ps", "-axo", "pid=,ppid=,command=", timeout=5)[1].splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            table[int(parts[0])] = (int(parts[1]), parts[2] if len(parts) > 2 else "")
    return table


def descendants(pid, table):
    """Every process below PID, depth first."""
    kids = {}
    for p, (pp, _) in table.items():
        kids.setdefault(pp, []).append(p)
    out, stack = [], list(kids.get(int(pid), []))
    while stack:
        p = stack.pop()
        out.append(p)
        stack += kids.get(p, [])
    return out


def background_work(pid, table=None):
    """Child processes of PID that are work, not its servers: a Bash tool run in the background, an acp-run or
    Workflow a session started, a build. Claude Code's background tasks live under
    /private/tmp/claude-<uid>/<project>/<session>/tasks/*.output and run as children of the session's process,
    so a live descendant is the test; an .output file alone is history. Empty list = nothing in flight; None =
    could not tell (no pid)."""
    if not pid:
        return None
    table = table if table is not None else proc_table()
    work = []
    for p in descendants(pid, table):
        cmd = table[p][1]
        if cmd and not SERVER_PROCS.search(cmd):
            work.append(f"{p} {clip(cmd, 90)}")
    return work


def mark_busy(s, table):
    """Set `busy` and, for a session that looks idle, status `busy-background` (helm never audits it, herdr-tidy
    never closes it). Shells, sleeper stubs and ACP launches are judged elsewhere."""
    if s.get("host") in ("acp", "hermes-gw") or s.get("status") in ("shell", "working"):
        s.setdefault("busy", [])
        return
    s["busy"] = background_work(s.get("pid"), table) or []
    if s["busy"] and s.get("status") in ("idle", "unknown", "blocked"):
        s["status"] = "busy-background"


# ---- ended sessions with open items ---------------------------------------------------------

def _chain_logs(days):
    out = []
    for log in (HANDOFFS / "chains").glob("*/SESSION_LOG.md"):
        try:
            text = log.read_text(errors="replace")
        except OSError:
            continue
        if time.time() - log.stat().st_mtime > days * 86400:
            continue
        fm = text.split("---", 2)[1] if text.startswith("---") else ""
        dirs = re.findall(r"^\s+dir:\s*(\S+)", fm, re.MULTILINE)
        active = re.search(r"Active work:\s*(.+)", text)
        nxt = re.search(r"Next steps:\s*(.*?)(?:\n##|\Z)", text, re.DOTALL)
        steps = [ln.strip(" -*") for ln in (nxt.group(1) if nxt else "").splitlines() if ln.strip(" -*")]
        if not steps or all(s.lower() in ("none", "none.") for s in steps):
            continue
        out.append({"chain": log.parent.name, "path": str(log), "dirs": dirs, "updated": log.stat().st_mtime,
                    "active": (active.group(1).strip() if active else ""), "steps": steps[:6]})
    return out


def replay_flags(argv, kind="claude"):
    """Launch flags worth replaying on a resume: claude's allow-list (herdr-sleeper's); nothing for other kinds,
    whose resume tokens carry everything we can vouch for."""
    if kind != "claude":
        return []
    out, it = [], iter(argv or [])
    for tok in it:
        if tok in REPLAY_BOOL:
            out.append(tok)
        elif tok in REPLAY_VALUE:
            val = next(it, None)
            if val is not None:
                out += [tok, val]
        elif "=" in tok and tok.split("=", 1)[0] in REPLAY_VALUE:
            out.append(tok)
    return out


def resume_command(kind, sid, cwd="", argv=None):
    """`cd <cwd> && <tui> <flags> <resume form>` for a kind with a verified resume form; None otherwise."""
    form = RESUME_FORMS.get(kind)
    if not form or not sid:
        return None
    flags = replay_flags(argv, kind)
    cmd = form.format(flags=(" " + shlex.join(flags)) if flags else "", sid=shlex.quote(str(sid)))
    return f"cd {shlex.quote(cwd)} && {cmd}" if cwd else cmd


def sleeper_journal():
    """herdr-sleeper's journal entries, read-only, newest state dir first: {key: entry} with `journal` set to
    the file each came from. A malformed file is skipped (never repaired here)."""
    out = {}
    for path in SLEEPER_JOURNALS:
        try:
            d = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        for key, e in d.items():
            if isinstance(e, dict) and e.get("uuid") and e["uuid"] not in {x.get("uuid") for x in out.values()}:
                out[key] = {**e, "journal": str(path), "key": key}
    return out


def sleeper_resume(entry):
    """The by-hand resume line for a journal entry, the way herdr-sleeper's manual_command spells it."""
    return resume_command(entry.get("kind") or "claude", entry.get("uuid"), entry.get("cwd") or "", entry.get("argv"))


def closed_ledger(days=None):
    """herdr-tidy's close ledger (closed.jsonl): one record per closed pane; a later line with the same `id`
    updates it (`resumed`: true hides it). Newest first."""
    if not CLOSED.exists():
        return []
    out = {}
    for line in CLOSED.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("id"):
            out[d["id"]] = {**out.get(d["id"], {}), **d}
    cutoff = time.time() - days * 86400 if days else 0
    return sorted((d for d in out.values() if (d.get("t") or 0) >= cutoff), key=lambda d: -(d.get("t") or 0))


def _closed_items(days, live_sids, live_dirs, chain_dirs):
    """Ledger entries as ended items: `closed` (a pane herdr-tidy closed; resume from the ledger). Hidden once
    its session is live again, marked resumed, or its handoff chain is already listed for that directory."""
    items = []
    for d in closed_ledger(days):
        if d.get("resumed") or (d.get("sid") and d["sid"] in live_sids):
            continue
        top = toplevel(d.get("cwd") or "") if d.get("cwd") else ""
        if d.get("handoff") and top and top in chain_dirs:
            continue   # the chain item carries this work
        items.append({"kind": "closed", "id": d["id"], "agent": d.get("agent", "?"), "sid": d.get("sid"),
                      "cwd": d.get("cwd", ""), "title": d.get("title") or d.get("label") or "", "updated": d.get("t") or 0,
                      "resume": d.get("resume") or "", "why": d.get("why", ""), "pane": d.get("pane", ""),
                      "handoff": d.get("handoff"), "mb": d.get("mb"), "ledger": str(CLOSED),
                      "action": d.get("resume") or f"(no resume recipe recorded; see {CLOSED})"})
    return items


def _sleeping_items(days, live_sids, ledger_uuids):
    """Journal entries whose pane no longer exists (or that herdr-sleeper re-keyed as orphans): auto-wake can
    never reach them, only the manual resume line can. Entries already in the close ledger are listed there."""
    panes = {p["pane_id"] for p in herdr_json("pane", "list").get("panes") or []}
    cutoff = time.time() - days * 86400
    items = []
    for key, e in sleeper_journal().items():
        uuid = e["uuid"]
        gone = key.startswith("orphan:") or e.get("phase") == "orphaned" or (e.get("pane_id") or key) not in panes
        if not gone or uuid in live_sids or uuid in ledger_uuids:
            continue
        try:
            slept = time.mktime(time.strptime((e.get("slept_at") or "")[:19], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            slept = 0
        if slept < cutoff:
            continue
        cmd = sleeper_resume(e)
        tx = transcript(uuid) if (e.get("kind") or "claude") == "claude" else None
        items.append({"kind": "sleeping", "id": f"sleep:{uuid[:8]}", "agent": e.get("kind") or "claude", "sid": uuid,
                      "cwd": e.get("cwd", ""), "title": e.get("title") or e.get("name") or "", "updated": slept,
                      "resume": cmd or "", "pane": e.get("pane_id") or key, "journal": e.get("journal"),
                      "mb": round(tx.stat().st_size / 1e6, 1) if tx else None,
                      "action": cmd or f"(no resume recipe for {e.get('kind')}; journal {e.get('journal')})"})
    return items


def ended_open(days=14, live=None):
    """Ended sessions that still need someone: handoff chains with next steps and no live session
    in their directory (-> start a /baton session there), Claude transcripts whose last reply
    was a question nobody answered (-> resume, or answer in a fresh session), panes herdr-tidy
    closed (-> resume with the ledger's command), and herdr-sleeper entries whose pane is gone
    (-> the manual resume line). Closed Claude sessions with no handoff and no question are listed
    only when the ledger says the recipe closed them: every old transcript would otherwise qualify."""
    live = sessions() if live is None else live
    live_dirs = {toplevel(s["cwd"]) for s in live if s.get("cwd")}
    live_sids = {s["sid"] for s in live if s.get("sid")}
    items = []
    for c in _chain_logs(days):
        tops = {toplevel(d) for d in c["dirs"]}
        if tops & live_dirs:
            continue
        items.append({"kind": "handoff", "id": f"chain:{c['chain']}", "agent": "any", "cwd": c["dirs"][0] if c["dirs"] else "",
                      "title": c["active"], "updated": c["updated"], "steps": c["steps"], "path": c["path"],
                      "action": f"launch.py --baton --cwd {c['dirs'][0] if c['dirs'] else '<dir>'}"})
    cutoff = time.time() - days * 86400
    for path in (CLAUDE / "projects").glob("*/*.jsonl"):
        try:
            st = path.stat()
        except OSError:
            continue
        if st.st_mtime < cutoff or path.stem in live_sids or st.st_size < 2000:
            continue
        tx = parse(path)
        if tx["finished"] or not tx["asks"]:
            continue
        if not tx["last_text"].rstrip().endswith("?"):
            continue
        cwd = path.parent.name.replace("-", "/")
        items.append({"kind": "ended-question", "id": path.stem[:8], "agent": "claude", "sid": path.stem,
                      "cwd": cwd if cwd.startswith("/") else "/" + cwd, "title": clip(STRIP.sub(" ", tx["last_prompt"]), 60),
                      "updated": st.st_mtime, "question": clip(tx["last_text"], 300), "mb": round(st.st_size / 1e6, 1),
                      "action": f"claude --resume {path.stem} (transcript {round(st.st_size / 1e6, 1)} MB) "
                                f"or launch.py --agent claude --cwd <dir> with the answer"})
    chain_dirs = {toplevel(it["cwd"]) for it in items if it["kind"] == "handoff" and it["cwd"]}
    closed = _closed_items(days, live_sids, live_dirs, chain_dirs)
    items += closed
    items += _sleeping_items(days, live_sids, {d.get("sid") for d in closed})
    # handoffs and unanswered questions first (open work), then what was merely closed, newest first within each
    items.sort(key=lambda it: (it["kind"] in ("closed", "sleeping"), -it["updated"]))
    return items


# ---- conflicts: who else works where I am about to work --------------------------------------

BIGTEAM = Path.home() / ".local/state/bigteam"
CLAIM_LIVE = 6 * 3600


def claims():
    """bigteam Step 0 claims: ~/.local/state/bigteam/<task>/CLAIM, live unless it ends with DONE
    or is older than six hours. Free text; a `files:`/`owned:` line lists paths, `repo:` the repo."""
    out = []
    if not BIGTEAM.is_dir():
        return out
    for c in BIGTEAM.glob("*/CLAIM"):
        try:
            st, text = c.stat(), c.read_text(errors="replace")
        except OSError:
            continue
        if time.time() - st.st_mtime > CLAIM_LIVE or re.search(r"^\s*DONE\b", text, re.MULTILINE | re.IGNORECASE):
            continue
        files = []
        for m in re.finditer(r"^\s*(?:files|owned|owns|paths)\s*:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE):
            files += [f.strip() for f in re.split(r"[,\s]+", m.group(1)) if f.strip()]
        repo = re.search(r"^\s*repo\s*:\s*(\S+)", text, re.MULTILINE | re.IGNORECASE)
        sess = re.search(r"^\s*session\s*:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
        out.append({"task": c.parent.name, "path": str(c), "repo": repo.group(1) if repo else "", "files": files,
                    "session": sess.group(1).strip() if sess else "", "age": time.time() - st.st_mtime})
    return out


def write_claim(task, session, repo, files, note=""):
    d = BIGTEAM / task
    d.mkdir(parents=True, exist_ok=True)
    (d / "CLAIM").write_text(f"session: {session}\nrepo: {repo}\nfiles: {' '.join(files) or '(whole repo, unspecified)'}\n"
                             f"start: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n{note}\n")
    return str(d / "CLAIM")


def release_claim(task):
    c = BIGTEAM / task / "CLAIM"
    if c.exists():
        with c.open("a") as fh:
            fh.write(f"DONE {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n")


def conflicts(cwd, live=None, sid=None):
    """What would collide with new work in CWD's repo: live sessions there (working ones block,
    finished ones do not), live claims naming that repo or files under it, the worktree's dirty
    files (another session's uncommitted work), and whether SID is already live somewhere."""
    top = toplevel(cwd)
    live = sessions() if live is None else live
    here = [s for s in live if s.get("cwd") and toplevel(s["cwd"]) == top and not s.get("self")]
    blocking = [s for s in here if not s.get("finished") and s.get("status") in ("working", "blocked")]
    idle = [s for s in here if not s.get("finished") and s.get("status") not in ("working", "blocked")]
    repo = os.path.basename(top)
    mine = [c for c in claims() if c["repo"] in (repo, top) or any(f.startswith(top) for f in c["files"])]
    rc, out = run("git", "-C", top, "status", "--porcelain", timeout=15)
    dirty = [ln[3:] for ln in out.splitlines() if ln.strip()] if rc == 0 else []
    sid_live = [s for s in live if sid and s.get("sid") == sid]
    return {"repo": top, "blocking": blocking, "idle": idle, "finished": [s for s in here if s.get("finished")],
            "claims": mine, "dirty": dirty[:40], "sid_live": sid_live}


def render_conflicts(c):
    lines = [f"repo {short(c['repo'])}:"]
    for s in c["blocking"]:
        lines.append(f"  BLOCKING: [{s['id']}] {s['agent']} {s.get('name') or ''} is {s['status']} here — {s['where'] or s['reach']}")
    for s in c["idle"]:
        lines.append(f"  idle here: [{s['id']}] {s['agent']} {s.get('name') or ''} — reach: {s['reach']}")
    for s in c["finished"]:
        lines.append(f"  finished ({s['finished']}): [{s['id']}] {s['agent']} — its pane is free to reuse")
    for cl in c["claims"]:
        lines.append(f"  claim {cl['task']} ({int(cl['age'] // 60)} min old, session {cl['session'] or '?'}): files {', '.join(cl['files']) or '(unspecified)'}")
    if c["dirty"]:
        lines.append(f"  dirty in worktree ({len(c['dirty'])}): {', '.join(c['dirty'][:12])}{' …' if len(c['dirty']) > 12 else ''}")
    for s in c["sid_live"]:
        lines.append(f"  SESSION ALREADY LIVE: [{s['id']}] in {s['where']} — never resume it a second time")
    if len(lines) == 1:
        lines.append("  nothing else works here")
    return "\n".join(lines)


# ---- output ---------------------------------------------------------------------------------

def ago(ts):
    if not ts:
        return "?"
    sec = int(time.time() - ts)
    return f"{sec // 86400}d" if sec >= 86400 else (f"{sec // 3600}h{sec % 3600 // 60:02d}m" if sec >= 3600 else f"{sec // 60}m")


def render(s):
    who = s["agent"] + (f" {s['name']}" if s["name"] else "")
    head = f"[{s['id']}] {who}  {s['status']}  {short(s['cwd'])}"
    if s["self"]:
        head += "  (this session)"
    if s["finished"]:
        head += f"  FINISHED ({s['finished']})"
    lines = [head]
    if s.get("busy"):
        lines.append(f"    busy: {len(s['busy'])} child process(es) in flight: {'; '.join(s['busy'][:3])}")
    if s["title"]:
        lines.append(f"    title: {s['title']}")
    if s["where"]:
        lines.append(f"    where: {s['where']}" + (f"   focus: {s['focus']}" if s["focus"] else ""))
    lines.append(f"    reach: {s['reach']}")
    if s.get("launch") and s["launch"].get("final"):
        lines.append(f"    last: {clip(s['launch']['final'], 200)}")
    return "\n".join(lines)


def render_ended(it):
    lines = [f"[{it['id']}] {it['kind']}  {short(it['cwd'])}  updated {ago(it['updated'])} ago"]
    if it.get("title"):
        lines.append(f"    {it['title']}")
    for s in it.get("steps", []):
        lines.append(f"    - {s}")
    if it.get("question"):
        lines.append(f"    asked: {it['question']}")
    if it["kind"] == "closed":
        lines.append(f"    closed pane {it.get('pane')}: {it.get('why') or '?'}" + (f"  (handoff: {it['handoff']})" if it.get("handoff") else ""))
    if it["kind"] == "sleeping":
        lines.append(f"    sleeping pane {it.get('pane')} is gone (journal {short(it.get('journal') or '')})")
    lines.append(f"    next: {it['action']}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="list", choices=["list", "ended", "show", "conflicts"])
    ap.add_argument("ident", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--cwd", help="conflicts: the directory new work would run in")
    ap.add_argument("--sid", help="conflicts: a session id you intend to resume")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.cmd == "conflicts":
        c = conflicts(a.cwd or os.getcwd(), sid=a.sid)
        print(json.dumps(c, ensure_ascii=False, default=str) if a.json else render_conflicts(c))
        return 1 if (c["blocking"] or c["sid_live"]) else 0
    if a.cmd == "ended":
        items = ended_open(a.days)
        print(json.dumps(items, ensure_ascii=False) if a.json else "\n\n".join(render_ended(it) for it in items))
        return 0 if items else 1
    ss = sessions(include_shell=a.all or a.cmd == "show")
    if a.cmd == "show":
        ss = [s for s in ss if a.ident in (s["id"], s["name"], s["sid"])]
        for s in ss:
            if s.get("transcript"):
                s["tail"] = {k: v for k, v in parse(Path(s["transcript"])).items() if k != "answers"}
                s["tail"]["pending"] = [(n, clip(json.dumps(i), 200)) for _, n, i in s["tail"]["pending"]]
    if a.json:
        print(json.dumps(ss, ensure_ascii=False, default=str))
    else:
        print("\n".join(render(s) for s in ss))
        if a.cmd == "show":
            for s in ss:
                t = s.get("tail") or {}
                la = s.get("launch") or {}
                if la:
                    print(f"    acp: {la.get('turns', 0)} turn(s) · {'alive' if la.get('alive') else 'exited'} · brief: {la.get('brief')}")
                    print(f"    last reply (acp log): {clip(la.get('final', ''), 500)}")
                if t or not la:
                    print(f"    last prompt: {clip(STRIP.sub(' ', t.get('last_prompt', '')), 300)}")
                    print(f"    last reply: {clip(t.get('last_text', ''), 400)}")
                    print(f"    work stretch: {t.get('stretch_min')} min · pending: {t.get('pending')}")
    return 0 if ss else 1


if __name__ == "__main__":
    sys.exit(main())
