#!/usr/bin/env python3
"""fleet — every running agent session on this machine, any TUI, no model.

    fleet.py [--all] [--json]        running sessions (--all: sleeper and plain shell panes, archived Paseo agents too)
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
sessions active in the last day (~/.hermes/state.db, read-only), the sessions launch.py
started over ACP (~/.local/state/session-finder/launches.jsonl), every other non-archived Paseo agent
(`paseo ls -g --background --json`, any provider; rows are matched on the Paseo agent id; a running one with a pending
permission or question card is `blocked`, from one `paseo permit ls --json`), plus herdr panes whose TUI herdr
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
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    import where as _where
except (ImportError, SyntaxError):   # SyntaxError: an older python (3.9) that cannot parse it; locate nothing
    _where = None
import nested_pty as _nested

HOME = str(Path.home())
CLAUDE = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
CLAUDE_JSON = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home())) / ".claude.json"
# Claude Code's cross-session messaging gate (2.1.296): the server flag below, overridden by the env var.
# With the flag false a long-running session drops ListAgents and peer SendMessage at its next flag
# refresh (2026-10-13; anthropics/claude-code#100760). The env var lives in ~/.claude/settings.json `env`.
MSG_FLAG, MSG_ENV = "tengu_harbor_kite", "CLAUDE_CODE_HARBOR_KITE"
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
                "muse": "muse resume {sid}", "cline": "cline --id {sid}"}
# claude launch flags a resume may replay (the allow-list herdr-sleeper uses); everything else is dropped
REPLAY_BOOL = {"--dangerously-skip-permissions", "--verbose"}
REPLAY_VALUE = {"--model", "--permission-mode", "--add-dir", "--effort"}
TAIL = 600_000          # bytes read from the end of a Claude transcript
HERMES_ACTIVE = 24 * 3600
REG_STATUS = {"busy": "working", "shell": "working", "waiting": "blocked", "idle": "idle"}
# Paseo providers whose agent can take a message into a RUNNING turn (`paseo send --behavior steer` queues it).
# Read from the Paseo 0.x daemon bundle on 2026-10-23: ClaudeAgentSession, CodexAppServerAgentSession, OmpAgentSession,
# OpenCodeAgentSession and PiRpcAgentSession implement steerActiveTurn. Every provider that `extends: acp` in
# ~/.paseo/config.json (cline, grok, copilot, ...) runs ACPAgentSession, which has none: Paseo then INTERRUPTS the
# running turn and starts the sent text as a new one (agent-manager steerOrReplaceActiveTurn: "replaced"). Plugin
# providers (antigravity, muse, hoplite) steer only when they negotiate "prompt.steer": unknown, so not listed.
PASEO_STEER_PROVIDERS = frozenset({"claude", "codex", "omp", "opencode", "pi"})
# Of those, the ones relay.py steers into a WORKING agent without `--steer`: peers relay to working Claude agents all
# the time. Each of the others (codex: a review turn, a server without turn/steer; omp: a steer error) can decline a
# steer where relay cannot see it, and Paseo then replaces the running turn: they need `--steer` (adversary, 2026-10-23).
PASEO_STEER_DEFAULT = frozenset({"claude"})
PASEO_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
PASEO_LS_TIMEOUT = 20
PASEO_STATUS = {"running": "working", "idle": "idle"}
# binary name -> agent label, for TUIs running outside herdr (herdr panes are taken from herdr itself)
PROC_AGENTS = {"claude": "claude", "codex": "codex", "cursor-agent": "cursor", "opencode": "opencode",
               "zcode": "zcode", "copilot": "copilot", "qwen": "qwen", "agy": "agy",
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


def ancestry():
    """This process's ancestors as an ORDER, NEAREST FIRST: the direct parent is `[0]`. `ancestors()` is the same set; a
    caller that must tell an agent's own process from one a nested agent started underneath it needs the order."""
    pids, pid = [], os.getpid()
    for _ in range(15):
        try:
            pid = int(run("ps", "-o", "ppid=", "-p", str(pid))[1].strip())
        except ValueError:
            break
        if pid <= 1:
            break
        pids.append(pid)
    return pids


def ancestors():
    return set(ancestry())


ANCESTOR_SELF = [True]   # relay.as_caller(scrub=True) sets False: a notice sender hides every id of the session, ancestry included
_ANC_PANE = [None]       # set by sessions(): the herdr pane an ancestor of this process runs in, when HERDR_PANE_ID is unset


def ancestor_pane(anc):
    """The herdr pane this process runs in, read from an ancestor's environment, or None. Codex's `shell_environment_policy
    inherit = "core"` (this machine's ~/.codex/config.toml) strips HERDR_PANE_ID from the shell Codex runs a command in, but
    the `codex` TUI process above that shell keeps it. Used only when this process's own HERDR_PANE_ID is unset; ancestors
    naming two different panes name none (nothing is guessed)."""
    if os.environ.get("HERDR_PANE_ID") or not ANCESTOR_SELF[0] or not _where:
        return None
    panes = {_where.env_of(pid).get("HERDR_PANE_ID") for pid in anc} - {None, ""}
    return panes.pop() if len(panes) == 1 else None


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
    if a["pane_id"] == (os.environ.get("HERDR_PANE_ID") or _ANC_PANE[0]):
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


RELAY = 'relay.py {id} "<text>" (types it into its pane; queued if it is working)'


_DISPATCH = None


def dispatch_record(sid):
    """The open acp-dispatch job record whose session is SID, or None. A headless slice has no pane to
    relay into, but `acp-dispatch tell RECORD MESSAGE` reaches it (2026-10-18: relay.py told a lead to
    "tell the operator" about a running merge worker that tell could reach)."""
    global _DISPATCH
    if not sid:
        return None
    if _DISPATCH is None:
        _DISPATCH = {}
        for f in [*BIGTEAM.glob("*/jobs/*.json"), *STATE_DIR.glob("launch-*/jobs/*.json")]:
            try:
                rec = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(rec, dict) and rec.get("session_id") and "closed" not in rec:
                _DISPATCH[rec["session_id"]] = str(f)
    return _DISPATCH.get(sid)


def _same_process(rec):
    """True when the record's pid is alive and, if the record stored `pid_start` (`ps -o lstart=`), still the process that
    started it: a pid reused after a reboot is not the slice. A `ps` that fails proves nothing, so the pid alone stands."""
    pid = rec.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1 or not alive(pid):    # pid 0 and -1 would signal a group
        return False
    want = rec.get("pid_start")
    if not want:
        return True
    rc, out = run("ps", "-o", "lstart=", "-p", str(pid))
    return rc != 0 or not out.strip() or out.strip() == want


def dispatch_target(path):
    """(row, None) for the acp-dispatch job record at the exact PATH, or (None, why) when relay must not send to it. For a
    record that `dispatch_record` cannot find: a slice started with `--out` somewhere else (a /tmp work tree) or a headless
    omp/codex slice that has no fleet row (2026-10-25: relay.py could not reach a running Collie worker whose record was
    /private/tmp/.../jobs/collie-native.json). Nothing is searched: the caller names the file. Only an unfinished, unclosed
    record whose process is still the one that launched it is a target; a finished one is refused, never resumed."""
    p = Path(path).expanduser().resolve()
    try:
        rec = json.loads(p.read_text())
    except (OSError, ValueError) as e:
        return None, f"unreadable acp-dispatch record {p}: {e}"
    if not isinstance(rec, dict) or not all(isinstance(rec.get(k), str) and rec[k] for k in ("agent", "dir")):
        return None, f"{p} is not an acp-dispatch job record (it needs string `agent` and `dir` fields)"
    name = rec.get("name") if isinstance(rec.get("name"), str) and rec["name"] else p.stem
    done = rec.get("done")
    if rec.get("closed") or rec.get("finished") or rec.get("status") != "running" or (isinstance(done, str) and done and Path(done).exists()):
        state = "closed" if rec.get("closed") else f"finished ({rec.get('status') or 'no status'})"
        return None, (f"slice {name} is {state}: a message would never be read, and relay never resumes a finished slice; "
                      f"give it to the next run with `acp-dispatch resume {p} -p '<message>'`")
    if rec.get("pid") is not None and not _same_process(rec):
        return None, f"slice {name}: its process (pid {rec.get('pid')}) is gone or is another process now; it is not running"
    sid = rec["session_id"] if isinstance(rec.get("session_id"), str) else None
    pid = rec["pid"] if isinstance(rec.get("pid"), int) else None
    return _rec(id=name, agent=rec["agent"], host="dispatch", sid=sid, name=name, cwd=rec["dir"], status="working", pid=pid,
                self=pid in ancestors(), dispatch_rec=str(p),
                reach=f'acp-dispatch tell {p} "<text>" (a headless acp-dispatch slice: no pane to relay into)'), None


def claude_reach(d, sid):
    """How to message a running Claude TUI. SendMessage needs the session's messaging socket (the
    registry's messagingSocketPath) and a caller whose ListAgents lists it: a workflow sub-agent's often
    does not (2026-10-11, q-shizuku relay), so the pane relay is named as the fallback. A headless
    acp-dispatch slice is reached with `acp-dispatch tell` instead."""
    rec = dispatch_record(sid)
    if rec:
        return f'acp-dispatch tell {rec} "<text>" (a headless acp-dispatch slice: no pane to relay into)'
    name = d.get("name") or sid[:8]
    sock = d.get("messagingSocketPath")
    if sock and os.path.exists(sock):
        return f"SendMessage to {name}; not in your ListAgents: " + RELAY.format(id=sid[:8])
    return RELAY.format(id=sid[:8]) + " (no messaging socket: SendMessage cannot reach it)"


def _merge_inner(launch, d, sid, pid):
    """The Claude Code that claude-agent-acp runs inside one of our ACP launches: one session, not two."""
    launch["sid"], launch["transcript"], launch["pid"] = sid, str(transcript(sid) or ""), pid
    launch["underlying"] = {"name": d.get("name") or "", "status": REG_STATUS.get(d.get("status"), "unknown")}
    if launch["status"] == "working" and REG_STATUS.get(d.get("status")) == "blocked":
        launch["status"] = "blocked"    # e.g. an AskUserQuestion inside the ACP session


def _claude_sessions(agents_by_sid, used, anc, launch_panes=None, launch_sids=None):
    me = os.environ.get("CLAUDE_CODE_SESSION_ID")
    launch_panes = launch_panes or {}
    launch_sids = launch_sids or {}
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
                 reach=claude_reach(d, sid))
        if sid in launch_sids:
            # a launch's ACP session id is Claude's own id (claude-agent-acp passes it as --session-id), so a
            # detached (--host none) launch, which has no pane to match on, is still recognised
            _merge_inner(launch_sids[sid], d, sid, pid)
            continue
        a = agents_by_sid.get(sid)
        env = _where.env_of(pid) if (_where and not a) else {}
        pane = a["pane_id"] if a else env.get("HERDR_PANE_ID")   # the sdk-ts entrypoint has no herdr hook: use its env
        if not pane and not a and launch_panes:
            pane = _acp_pane_of(pid)   # claude-agent-acp scrubs the env; the acp-run ancestor still has the pane id
        if pane in launch_panes:
            _merge_inner(launch_panes[pane], d, sid, pid)
            continue
        if a:
            used.add(a["pane_id"])
            _from_herdr(s, a)
        elif _where:
            w = _where.lookup(pid, d.get("procStart", "")) or {}
            s.update(where=w.get("where", ""), focus=w.get("focus", ""), title=w.get("title", ""), host="terminal")
            if w.get("paseo_agent"):
                # the Paseo daemon spawned it: no terminal, `paseo send` is its channel (relay.py; 2026-10-20)
                s.update(host="paseo", chan=("paseo", w["paseo_agent"]), paseo=w["paseo_agent"],
                         reach=s["reach"].replace("types it into its pane", "`paseo send --behavior steer` into its Paseo agent"))
            elif _in_orca(env):
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


def _paseo_json(*args):
    """Parsed JSON of `paseo ARGS` (the CLI is $PASEO_CLI, else PATH): a list, or None when there is no CLI, it
    failed or timed out, or it printed anything but a JSON list. argv list, stdin closed, nothing cached."""
    cli = os.environ.get("PASEO_CLI") or shutil.which("paseo")
    if not cli or not os.access(cli, os.X_OK):
        return None
    try:
        p = subprocess.run([cli, *args], capture_output=True, text=True,
                           timeout=PASEO_LS_TIMEOUT, check=False, stdin=subprocess.DEVNULL)
        data = json.loads(p.stdout) if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    return data if isinstance(data, list) else None


def _paseo_ls(*flags):
    """Parsed `paseo ls -g --json FLAGS`: a list of agents, or None (see `_paseo_json`)."""
    return _paseo_json("ls", "-g", "--json", *flags)


HIDDEN = "\u115f\u1160\u3164\uffa0\u2800"    # fillers and blanks that render as nothing
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b.?")
PASEO_REQ = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}")    # alphanumeric first: an id of `--all` or `-h` would be read as an option


def clean_text(text):
    """Text from another agent or process as plain data: escape sequences, control characters (C0 bar newline and tab, DEL,
    C1), Unicode format characters (bidi overrides and isolates, zero-width), blank fillers and variation selectors removed."""
    return "".join(ch for ch in ANSI.sub("", text)
                   if ch in "\n\t" or not (ch < " " or "\x7f" <= ch <= "\x9f" or unicodedata.category(ch) in ("Cf", "Zl", "Zp")
                                           or ch in HIDDEN or "\ufe00" <= ch <= "\ufe0f" or "\U000e0100" <= ch <= "\U000e01ef")).strip()


def _paseo_waiting():
    """{Paseo agent id: [{"id": request id or None, "text": "TOOL: description"}, ...]} for every agent with a pending
    permission or question card, one entry per card in the order `paseo permit ls --json` lists them (`paseo ls` carries
    no pending-permission field). The request id is what `paseo permit allow|deny AGENT -- ID` takes (without one, allow
    approves every card of the agent); an id that is not a plain token (alphanumeric first) is None. Empty when the call fails: a row is then
    listed as it was before, `running`. The text is the agent's own, control characters stripped."""
    out = {}
    for d in _paseo_json("permit", "ls", "--json") or []:
        pid = d.get("agentId") if isinstance(d, dict) else None
        if isinstance(pid, str):
            rid = d.get("id")
            out.setdefault(pid, []).append({
                "id": rid if isinstance(rid, str) and PASEO_REQ.fullmatch(rid) else None,
                "text": " ".join(clean_text(f"{d.get('name') or 'permission'}: {d.get('description') or ''}").split())[:300]})
    return out


def paseo_reach(sid, provider, archived=False):
    if archived:
        return "archived Paseo agent: relay.py refuses it (a send would unarchive it); unarchive it in Paseo first"
    base = f'relay.py {sid} "<text>" (`paseo send` into its Paseo agent; '
    if provider in PASEO_STEER_DEFAULT:
        return base + "queued at its next tool round if it is working, unless Paseo replaces the turn, e.g. while it compacts)"
    if provider in PASEO_STEER_PROVIDERS:
        return base + ("queued at its next tool round if it is working and the provider takes the steer; if it declines "
                       "(a Codex review turn, a steer error) Paseo replaces the turn, so a send while it works needs "
                       "--steer; otherwise relay queues it for delivery when the agent is idle (`queued: <id>`, exit 0) and --idle S waits for idle instead)")
    return base + (f"a {provider} agent cannot steer, so a send while it works would replace its turn: relay queues it "
                   "for delivery when the agent is idle (`queued: <id>`, exit 0; --idle S waits for idle instead, --no-defer refuses)")


def _paseo_hosting_pids(anc):
    """{agent id: pid} for the Paseo agents hosting this process or one of its ancestors (the pid's own parent is titled
    Paseo Daemon and carries the id: `where.paseo_agent`). The pid is the agent's OWN process, the one Paseo launched, so it
    tells that agent's row apart from a different agent's process started underneath it (see `sender_row`)."""
    if not _where:
        return {}
    out: dict[str, int] = {}
    for p in anc:
        a = _where.paseo_agent(p, _where.env_of(p))
        if a:
            out.setdefault(a, p)
    return out


def _paseo_hosting(anc):
    """Paseo agent ids hosting this process or one of its ancestors (parent titled Paseo Daemon, id in its env)."""
    return set(_paseo_hosting_pids(anc))


def _paseo_rows(have, anc, include_archived=False):
    """A row for every non-archived Paseo agent of any provider whose id is not in HAVE (the Paseo ids other rows
    already stand for; matched on the agent id, never on the directory), from `paseo ls -g --background --json`.
    INCLUDE_ARCHIVED adds the archived ones (`paseo ls -g -a`, minus the live list) as status `ended`.
    No CLI or a failed call: no rows, exactly as before this source existed. Ids are checked against the uuid
    pattern before they can reach an argv or a chan; the provider label is the part before the first `/`."""
    live = _paseo_ls("--background")
    if live is None:
        return []
    everything = (_paseo_ls("-a") or []) if include_archived else []
    live_ids = {d.get("id") for d in live if isinstance(d, dict)}
    todo = [(d, False) for d in live] + [(d, True) for d in everything
                                         if isinstance(d, dict) and d.get("id") not in live_ids]
    me, hosting, out, seen = os.environ.get("PASEO_AGENT_ID"), None, [], set(have)
    for d, archived in todo:
        pid = d.get("id") if isinstance(d, dict) else None
        if not isinstance(pid, str) or not PASEO_ID.fullmatch(pid) or pid in seen:
            continue
        seen.add(pid)
        raw = str(d.get("status") or "unknown").lower()
        prov = str(d.get("provider") or "").split("/", 1)[0].lower()
        if not re.fullmatch(r"[a-z0-9_.-]{1,40}", prov):
            prov = "paseo"
        cwd = str(d.get("cwd") or "")
        if cwd == "~" or cwd.startswith("~/"):
            cwd = HOME + cwd[1:]
        if hosting is None:
            hosting = _paseo_hosting(anc)
        name = clip(str(d.get("name") or ""), 80)
        out.append(_rec(id=pid[:8], agent=prov, host="paseo", sid=None, name=name, cwd=cwd,
                        status="ended" if archived else PASEO_STATUS.get(raw, raw), chan=("paseo", pid), paseo=pid,
                        paseo_state="archived" if archived else raw, archived=archived, ended=archived,
                        self=(pid == me or pid in hosting), where=f"host=paseo agent={pid}",
                        reach=paseo_reach(pid[:8], prov, archived)))
    if any(s["paseo_state"] == "running" for s in out):    # only a running agent can wait on a card
        waiting = _paseo_waiting()
        for s in out:
            if s["paseo_state"] == "running" and s["paseo"] in waiting:
                cards = waiting[s["paseo"]]
                s.update(status="blocked", paseo_cards=cards,
                         paseo_pending=cards[0]["text"] if len(cards) == 1 else f"{len(cards)} cards, the first: {cards[0]['text']}")
    return out


def pane_procs(pane):
    """Foreground processes of a herdr pane (`pane process-info`): [{pid, name, argv, cwd}], shell pid.
    None when herdr could not read them (unknown is not empty). A pane whose only foreground process is Kiro's terminal shim is
    answered with the foreground processes of its inner PTY when `nested_pty` can prove them (the cwd is then '': ps has none)."""
    info = herdr_json("pane", "process-info", "--pane", pane).get("process_info")
    if not isinstance(info, dict):
        return None, None
    procs = []
    for pr in info.get("foreground_processes") or []:
        argv = pr.get("argv") or ([pr["cmdline"]] if pr.get("cmdline") else [])
        procs.append({"pid": pr.get("pid"), "name": pr.get("name") or pr.get("argv0") or "", "argv": argv,
                      "argv0": pr.get("argv0") or "", "cwd": pr.get("cwd") or ""})
    inner = _kiro_inner(procs, info.get("shell_pid"))
    if inner is _KIRO_UNKNOWN:      # a confirmed shim whose inner side could not be read: unknown, not a plain shell
        return None, info.get("shell_pid")
    return inner or procs, info.get("shell_pid")


class _KiroUnknown:
    """Sentinel result of `_kiro_inner`: the pane IS a Kiro shim but its inner foreground could not be read (ps failed, empty or
    a live process's argv unreadable). Distinct from None (not a shim, or the chain is absent/ambiguous: herdr's answer stands)
    and from a list (proven)."""
    def __repr__(self):
        return "<kiro inner unknown>"


_KIRO_UNKNOWN = _KiroUnknown()


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:      # EPERM: it exists
        return True
    return True


def _kiro_inner(procs, shell_pid):
    """The inner-PTY foreground processes behind a Kiro shim in `pane_procs` shape (proven: a non-empty list, its group leader
    included), None (not a shim, or no/ambiguous nested chain), or `_KIRO_UNKNOWN` (a shim that could not be read). A member that
    exited after the ps snapshot is skipped; if the leader itself exited the foreground job is gone and herdr's answer stands."""
    if not isinstance(shell_pid, int) or len(procs) != 1 or procs[0].get("argv0") != _nested.OUTER_ARGV0:
        return None
    rc, text = run(*_nested.PS_ARGS, timeout=5)
    table = _nested.parse_ps(text) if rc == 0 else {}
    if not table:      # ps failed, timed out, or printed nothing: `ps -ax` never legitimately does
        return _KIRO_UNKNOWN
    rows = _nested.inner_foreground(procs, shell_pid, table)
    if not rows:
        return None
    command = lambda pid: run("ps", "-ww", "-o", "command=", "-p", str(pid), timeout=5)[1].strip()
    out = []
    for r in rows:
        argv = _nested.argv_of(r, command)
        if not argv:
            if _pid_alive(r["pid"]):
                return _KIRO_UNKNOWN
            continue
        out.append({"pid": r["pid"], "name": os.path.basename(r["comm"]), "argv": argv, "argv0": argv[0], "cwd": ""})
    leader = rows[0]["pgid"]
    return out if any(p["pid"] == leader for p in out) else None


SID_IN_ARGV = re.compile(r"(?:--resume|--session|--conversation|--id|-s|-r)(?:=|$)")


# The installed Hermes entry is a shell shim that `exec`s one Python process: `python3 -I -c <bootstrap> ARGS...`, with no `hermes` in
# argv at all (2026-10-25: a native Hermes TUI in a herdr pane, which herdr does not detect, was "no session match" to relay). The
# bootstrap is recognised by its own three lines, never by the word "hermes" somewhere in a `-c` string: its path insert of the
# `hermes-agent` checkout, its import of the CLI's `main`, and the exit through it.
_HERMES_SHIM = tuple(re.compile(p) for p in (r"(?m)^sys\.path\.insert\(0, '[^'\n]*/hermes-agent'\)$",
                                             r"(?m)^from hermes_cli\.main import main$", r"(?m)^sys\.exit\(main\(\)\)$"))
# top-level flags that end the run without a chat (one query, help, version) or that take a value (so it is not the subcommand)
_HERMES_ONESHOT = {"-z", "--oneshot", "-q", "--query", "-h", "--help", "-V", "--version", "--print-runtime-command", "--run-module"}
_HERMES_VALUE_FLAGS = {"-m", "--model", "--provider", "-r", "--resume", "-p", "--profile", "-t", "--toolsets", "-s", "--skills"}


def _hermes_native(argv):
    """True when ARGV is the installed Hermes entry shim running the interactive chat: `<python> -I -c <bootstrap> [flags]` whose
    bootstrap carries all three marks, and whose arguments name no subcommand other than `chat` (gateway, acp, mcp, cron, serve ...
    are services or tools, not a TUI) and no single-shot flag. Hermes decides the same way: its first positional being None or
    "chat" is the chat. An unknown flag's value taken as the subcommand errs to "not a TUI" (the row is then simply not listed)."""
    if len(argv) < 4 or not os.path.basename(argv[0]).startswith("python") or argv[1:3] != ["-I", "-c"]:
        return False
    if not all(m.search(argv[3]) for m in _HERMES_SHIM):
        return False
    if any(tok in _HERMES_ONESHOT or tok.startswith("--oneshot") for tok in argv[4:]):
        return False
    first, it = None, iter(argv[4:])
    for tok in it:
        if tok == "--":
            first = next(it, None)
            break
        if tok in _HERMES_VALUE_FLAGS:
            next(it, None)
        elif not tok.startswith("-"):
            first = tok
            break
    return first in (None, "chat")


# Native TUIs herdr does not detect that PROC_AGENTS (which `_proc_scan` also reads) must not take: recognised by exact argv only.
def _native_extra(argv):
    """Exact native interactive entries, excluding service and one-shot commands."""
    base = [os.path.basename(a) for a in argv[:2]]
    if base and base[0] == ".cline" and "--tui" in argv[1:] and not {"--acp", "--headless", "--zen", "hub", "core"}.intersection(argv[1:]):
        return "cline"
    if len(base) == 2 and base[0] == "goose" and base[1] == "session":
        return "goose"
    if len(base) == 2 and base[0] == "node" and base[1] == "mastracode":
        return "mastra"
    return None


def _tui_of(procs):
    """(agent label, pid, session id, argv) of the TUI running in a pane, from its foreground processes."""
    procs = list(procs or [])
    # npm's Cline launcher waits for its cached native TUI. Select that actual
    # TUI, rather than treating it as background work below the Node launcher.
    # Restrict this preference to the exact sibling cache used by that launcher.
    for pr in procs:
        argv = pr["argv"]
        if _native_extra(argv) != "cline":
            continue
        launcher = str(Path(argv[0]).with_name("cline"))
        if any(len(p["argv"]) >= 2 and os.path.basename(p["argv"][0]) == "node"
               and os.path.realpath(p["argv"][1]) == os.path.realpath(launcher) for p in procs):
            procs = [pr] + [p for p in procs if p is not pr]
            break
    for pr in procs:
        argv = pr["argv"]
        names = [os.path.basename(pr["argv0"] or "")] + [os.path.basename(a) for a in argv[:2]]
        agent = (next((PROC_AGENTS[n] for n in names if n in PROC_AGENTS), None) or ("hermes" if _hermes_native(argv) else None)
                 or _native_extra(argv))
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
        # A `hermes --resume -z` turn (relay.py's hermes route) ends its row with `agent_close`, and the gateway
        # reopens it by session_key a few minutes later (gateway.session: "reopened ended session ...; keeping route",
        # 2026-10-23). Hermes counts agent_close as recoverable, so such a row is still the live conversation unless
        # a newer row for the same session_key replaced it (a /new or reset). Only a keyed, non-subagent row can be
        # reopened: every finished delegated child (source subagent, and desktop children) ends with agent_close and a
        # NULL session_key, and is not a conversation to message (adversary, 2026-10-23). Not filtered on
        # parent_session_id: the live Telegram conversation has a parent.
        rows = db.execute(
            "SELECT s.id, s.source, s.session_key, s.chat_id, s.thread_id, s.title, s.cwd, "
            "COALESCE(s.last_activity_at, s.started_at) last, s.last_activity_description FROM sessions s "
            "WHERE (s.ended_at IS NULL OR (s.end_reason = 'agent_close' AND s.session_key IS NOT NULL "
            "AND s.source <> 'subagent')) AND s.source NOT IN ('cli','oneshot') "
            "AND COALESCE(s.last_activity_at, s.started_at) > ? "
            "AND NOT EXISTS (SELECT 1 FROM sessions n WHERE n.session_key = s.session_key AND n.started_at > s.started_at "
            "AND n.source NOT IN ('cli','oneshot')) ORDER BY last DESC", (time.time() - HERMES_ACTIVE,)
        ).fetchall()
        db.close()
    except sqlite3.Error:
        return out
    for r in rows:
        target = f"telegram:{r['chat_id']}" + (f":{r['thread_id']}" if r["thread_id"] else "") if r["source"] == "telegram" else r["source"]
        out.append(_rec(id=f"hermes:{r['id'][-8:]}", agent="hermes", host="hermes-gw", sid=r["id"], cwd=r["cwd"] or "",
                        title=(r["title"] or "").strip(), status="idle", where=f"Hermes {r['source']} · {target}",
                        reach=f"ask_hermes, or messages_send target={target} (MCP hermes)",
                        focus=f"hermes --resume {r['id']}", hermes_chat=(r["source"], r["chat_id"], r["thread_id"]),
                        hermes_key=r["session_key"] or ""))
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
    if d.get("log") and log.is_file():
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
            elif k in ("load_session", "resume_session"):
                d["acp_session"] = data.get("sessionId") or d.get("resumed") or d.get("acp_session")
                d["load_session"] = True   # it loaded once, so it can load again
                cur = []   # acp-run logs the replayed history before this record: not this launch's text
            elif k == "initialize":
                d["load_session"] = bool((data.get("agentCapabilities") or {}).get("loadSession"))
            elif k == "turn":
                turns.append({**data, "text": "".join(cur)})
                cur = []
            elif k == "result":
                result = data
    final = turns[-1]["text"] if turns and not "".join(cur).strip() else "".join(cur)
    exited = result is not None or d.get("exit") is not None
    if d.get("dispatch"):
        # A headless launch dispatched through acp-dispatch (2026-10-08): the turn is over once the
        # .done marker exists, the recorded exit is acp-dispatch's (3 = no report, 4 = BLOCKED), and
        # the deliverable is the report file, not the stream. Its first line decides what helm shows.
        report, done = Path(d.get("report") or ""), Path(d.get("done") or "")
        exited = exited or done.exists()
        head = report.read_text(errors="replace").strip() if report.exists() else ""
        first = head.splitlines()[0].strip() if head else ""
        if exited:
            result = {**(result or {}), "exit": d.get("exit", (result or {}).get("exit"))}
            if first.upper().startswith("BLOCKED:"):
                d["turns"] = len(turns)
                return "blocked", first, result       # helm: a `reply` item carrying the question
            if not head or result.get("exit") == 3:
                final = (f"DELIVERY FAILURE: launch {d.get('id')} finished with no report "
                         f"(acp-dispatch exit {result.get('exit')}); re-task it, never reconstruct")
            else:
                final = head
            d["turns"] = len(turns)
            return "idle", final, result
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
                 mark=d.get("mark"),
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


def sessions(include_shell=False, include_marked=True, include_archived=False):
    """Every running session. include_marked=False leaves out launches started with `launch.py --mark`
    (test/trial launches their starter drives; helm should ignore them, hcom trial 6g). include_archived adds
    the archived Paseo agents as `ended` rows (fleet.py --all)."""
    anc = ancestors()
    _ANC_PANE[0] = ancestor_pane(anc)
    agents = herdr_json("agent", "list").get("agents") or []
    panes = herdr_json("pane", "list").get("panes") or []
    by_sid = {(a.get("agent_session") or {}).get("value"): a for a in agents if a.get("agent_session")}
    used = set()
    launched = _launched(used)
    launch_panes = {s["chan"][1]: s for s in launched if s.get("chan") and s["chan"][0] == "herdr"}
    launch_sids = {s["launch"]["acp_session"]: s for s in launched if (s.get("launch") or {}).get("acp_session")}
    out = _claude_sessions(by_sid, used, anc, launch_panes, launch_sids)
    out += _other_herdr(agents, used)
    out += launched
    tuis, shells = _pane_only(panes, used)
    out += tuis
    known_pids = {s["pid"] for s in out if s.get("pid")}
    out += _proc_scan(known_pids, used | {a["pane_id"] for a in panes}, anc)
    out += _hermes_gateway()
    have = {s["paseo"] for s in out if s.get("paseo")} | {s["chan"][1] for s in out if (s.get("chan") or ("",))[0] == "paseo"}
    out += _paseo_rows(have, anc, include_archived)
    if include_shell:
        out += shells
    if not include_marked:
        out = [s for s in out if not s.get("mark")]
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

BIGTEAM = Path(os.environ.get("BIGTEAM_STATE") or Path.home() / ".local/state/bigteam")   # env: tests
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
    # the caller itself is live by definition, never a second copy (2026-10-18: a broadcast told every session
    # to pass its own --sid, and each one was told not to resume itself)
    sid_live = [s for s in live if sid and s.get("sid") == sid and not s.get("self")]
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


# Who has messaged whom, and who ever answered (2026-10-25, queue.md "Verified peer messaging"): relay.py writes
# the ledger (under its own flock, atomically); fleet only reads it, so a one-way link shows in `fleet.py list`.
LINKS_FILE = Path(os.environ.get("RELAY_LINKS_FILE") or Path.home() / ".local/state/relay/links.json")


def link_key(sender, target):
    return f"{sender}>{target}"


def link_get(links, me, s):
    """The link record sender ME -> target S in LINKS, or None. A herdr pane id is reused by the next session in the pane, so a record that
    stored a session id (`sender_sid`, `target_sid`) for either end counts only while that end still has it (adversary r1 A11, 2026-10-25):
    the new occupant starts as a first contact. A record or an end without a session id is matched by the pane id alone, as before."""
    ln = links.get(link_key(me["id"], s["id"]))
    if not isinstance(ln, dict):
        return None
    for stored, now in ((ln.get("sender_sid"), me.get("sid")), (ln.get("target_sid"), s.get("sid"))):
        if stored and now and stored != now:
            return None
    return ln


def links_read():
    """The link ledger as {"links": {"<sender>><target>": {sent, first_sent, last_sent, acked, ...}}}; empty when missing or unreadable.
    Every field is read with .get: an older record may lack a newer one."""
    try:
        d = json.loads(LINKS_FILE.read_text())
    except (OSError, ValueError):
        d = None
    if not isinstance(d, dict) or not isinstance(d.get("links"), dict):
        return {"links": {}}
    return d


def sender_row(ss):
    """The `self` row of the session this process runs in, or None for a caller with no session: a launchd script, whose
    messages nobody can be held to an ack for.

    Among several `self` rows, take the one that can PROVE an ack (2026-10-30). `sessions()` runs `_proc_scan` before
    `_paseo_rows`, and a process-scan row is `self = pid in ancestors` (`_proc_scan`): a Paseo-hosted agent whose tools run
    under a process fleet recognises (a transcript-less TUI such as `agy`, `codex` or `opencode`) gets a `pid*` row for that
    ancestor, host terminal, with no transcript and no Paseo id, listed BEFORE its own Paseo row. Taking the first `self` row
    then named a pid as the sender: relay wrote `sender: pidNNNN`, `sender_paseo: ""`, `tl_base: null`, so its
    `--expect-ack` could never close (nothing watches a pid: `--ack` wants a transcript, `resolve_acks` a keeping route) and its
    footer told a peer to `ack pidNNNN` (live 2026-10-29, an Antigravity agent).

    Preference, in this order: the NEAREST process of ours, counting a Paseo row as the process PASEO LAUNCHED for that
    agent (`_paseo_hosting_pids`), a transcript row as its own `pid` and any other row as its own `pid`, against
    `ancestry()` (nearest first); at one depth (rows that stand for the same process), the row that can prove the ack: a
    transcript (`--ack` watches it), then a Paseo id (a keeping route for `resolve_acks`), then neither. The depth comes first because the
    caller's identity decides who an answer goes to, and an outer Claude that started this Codex is not the caller
    (review F1, 2026-10-30; the first version let any transcript outrank any depth, so a reply, its footer and the retirement
    self-check named the parent). Two consequences this rule exists for: an inherited or exported `PASEO_AGENT_ID` marks a
    row `self` on its own (`_paseo_rows`: `pid == me or pid in hosting`) and claims no process of ours, so it cannot beat
    a row that does while one competes (adversary B1; rows that all claim none tie and keep fleet's order, a transcript row
    that claims none ahead of the rest, and a lone `self` row never reaches this rule); and a Paseo agent that started
    ANOTHER agent (`omp` running `codex`) is an ancestor of this process, so its row is `self` too — naming it would
    substitute the parent's identity for the caller's and route replies to the wrong session, while the nested agent's own
    row is nearer (local review of 2026-10-30). A row fleet scans for the very process Paseo launched is at that same depth
    as its Paseo row, so the Paseo row wins there and the old `pid*` sender cannot come back.

    A transcript-backed row gets no second vote for also carrying a Paseo id: `_claude_sessions` gives a daemon-spawned
    Claude both (`_where.lookup` -> `paseo_agent`, fleet.py:525-530), but a transcript already proves the ack and
    `ack_proof_note` does not use that id for a transcript row, so it adds nothing to the proof
    (adversary 4 F1, 2026-10-30). Exact ties keep fleet's order (`max` returns the first of equal keys)."""
    selfs = [x for x in ss if isinstance(x, dict) and x.get("self")]
    if len(selfs) < 2:
        return selfs[0] if selfs else None
    anc = ancestry()
    depth = {pid: i for i, pid in enumerate(anc)}
    hosted: dict[str, int] | None = None

    def hosting() -> dict[str, int]:
        nonlocal hosted
        if hosted is None:
            hosted = _paseo_hosting_pids(anc)
        return hosted

    def row_depth(x):
        """The row's process as seen from here: 0 for this process's direct parent, larger further up, None when the row
        stands for no process of ours (an id an inherited `PASEO_AGENT_ID` merely stamps on it). A transcript row is placed by
        its own `pid` (a daemon-spawned Claude also carries a Paseo id, which is no second process)."""
        pid = hosting().get(x["paseo"]) if x.get("paseo") and not x.get("transcript") else x.get("pid")
        try:
            return depth.get(int(pid))
        except (TypeError, ValueError):
            return None

    def key(x):
        """Which SESSION is the caller comes first (the nearest process of ours: an outer Claude that started this Codex is
        not the caller, review F1 2026-10-30); how it proves an ack only breaks a tie between rows of that same process."""
        d = row_depth(x)
        if d is None and x.get("transcript") and x.get("sid") and x["sid"] == os.environ.get("CLAUDE_CODE_SESSION_ID"):
            # The registry's pid for this session is no ancestor of ours (a wrapper or exec'd launcher), but its session id IS the one
            # exported to this process: the session of the nearest same-agent process-scan row that names no Paseo agent and no
            # transcript, so that the old `pid*` sender (`ack pidNNNN`, 2026-10-29) does not come back (PR 173 adversary B5).
            near = [n for y in selfs if y is not x and not y.get("transcript") and not y.get("paseo") and y.get("agent") == x.get("agent")
                    for n in [row_depth(y)] if n is not None]
            d = min(near) if near else None
        if d is None:
            return (1 if x.get("transcript") else 0, 0, 0)    # a claim on no process of ours: only when nothing better exists
        return (2, -d, 2 if x.get("transcript") else 1 if x.get("paseo") else 0)    # nearest process; at one depth, the row that can prove the ack

    return max(selfs, key=key)


def nearer_than_paseo_host(row, agent_id):
    """True when ROW (a `self` row) stands for a process of ours strictly NEARER than the one Paseo launched for AGENT_ID: a
    nested agent (Codex started by an `omp` Paseo agent) that inherited the parent's `PASEO_AGENT_ID`. False for the row of
    AGENT_ID itself, or when either depth is unknown."""
    if not isinstance(row, dict) or row.get("paseo") == agent_id:
        return False
    anc = ancestry()
    depth = {pid: i for i, pid in enumerate(anc)}
    hosting = _paseo_hosting_pids(anc)
    try:
        own = hosting.get(row["paseo"]) if row.get("paseo") and not row.get("transcript") else row.get("pid")
        mine, host = depth.get(int(own)), depth.get(int(hosting.get(agent_id)))
    except (TypeError, ValueError):
        return False
    return mine is not None and host is not None and mine < host


def annotate_links(ss):
    """Set `link` on every row THIS session (the `self` row) has messaged: {"sent": N, "acked": epoch|None}. A link whose peer
    never answered with `ack <our id>` is one-way: sent, never proven read."""
    me = sender_row(ss)
    if not me:
        return ss
    links = links_read()["links"]
    for s in ss:
        ln = link_get(links, me, s)
        if ln is not None:
            try:
                sent = int(ln.get("sent") or 0)
            except (TypeError, ValueError):    # a hand-edited ledger must not stop `fleet.py list`
                sent = 0
            s["link"] = {"sent": sent, "acked": ln.get("acked") or None}
    return ss



def render(s):
    who = s["agent"] + (f" {s['name']}" if s["name"] else "")
    head = f"[{s['id']}] {who}  {s['status']}  {short(s['cwd'])}"
    if s["self"]:
        head += "  (this session)"
    if s["finished"]:
        head += f"  FINISHED ({s['finished']})"
    if s.get("mark"):
        head += f"  mark={s['mark']}"
    lines = [head]
    if s.get("busy"):
        lines.append(f"    busy: {len(s['busy'])} child process(es) in flight: {'; '.join(s['busy'][:3])}")
    if s["title"]:
        lines.append(f"    title: {s['title']}")
    if s["where"]:
        lines.append(f"    where: {s['where']}" + (f"   focus: {s['focus']}" if s["focus"] else ""))
    if s.get("link"):
        ln = s["link"]
        lines.append(f"    link: acked {ago(ln['acked'])} ago" if ln.get("acked") else
                     f"    link: ONE-WAY, we sent {ln.get('sent', 0)} message(s) and it never answered `ack <our id>` through relay.py: delivered at best, never proven read")
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


def _read_json(p):
    try:
        return json.loads(Path(p).read_text())
    except (OSError, ValueError):
        return {}


def _binary_has(path, needle, cache=None):
    """Whether the file at `path` contains `needle`, cached by path and mtime (a Claude binary is ~240 MB)."""
    cache = Path(cache or STATE_DIR / "messaging-binary-check.json")
    try:
        st = os.stat(path)
    except OSError:
        return None
    prefix = f"{os.path.realpath(path)}:{int(st.st_mtime)}:"
    key = prefix + needle
    seen = {k: v for k, v in _read_json(cache).items() if k.startswith(prefix)}   # drop older binaries
    if key in seen:
        return seen[key]
    import mmap
    try:
        with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
            found = m.find(needle.encode()) >= 0
    except (OSError, ValueError):
        return None
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps({**seen, key: found}))
        os.replace(tmp, cache)
    except OSError:
        pass
    return found


def messaging_warning(claude_json=CLAUDE_JSON, settings=CLAUDE / "settings.json", binary=None, cache=None):
    """A one-line warning when Claude sessions can lose cross-session messaging, else None.

    The server flag flips between true and false (2026-10-12/13), so its current value proves nothing:
    the override must be in settings `env`, and while the installed binary still has the flag, it must
    also still have the variable's name (a release could rename it). A binary with neither has no gate."""
    note = "(memory/reference_cross_session_messaging_flag_override.md)"
    env = (_read_json(settings).get("env") or {}).get(MSG_ENV, "")
    if str(env).lower() not in ("1", "true", "yes", "on"):
        flag = (_read_json(claude_json).get("cachedGrowthBookFeatures") or {}).get(MSG_FLAG)
        return (f"WARNING: {settings} has no env {MSG_ENV}=1 (server flag {MSG_FLAG} is cached as {flag}): "
                f"when the flag reads false, running sessions lose ListAgents and peer SendMessage {note}")
    binary = binary or shutil.which("claude")
    if binary and _binary_has(binary, MSG_ENV, cache) is False and _binary_has(binary, MSG_FLAG, cache):
        return (f"WARNING: {os.path.realpath(binary)} still has {MSG_FLAG} but no longer reads {MSG_ENV}: "
                f"the messaging override is dead; find its new name {note}")
    return None


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
    ss = sessions(include_shell=a.all or a.cmd == "show", include_archived=a.all)
    warn = messaging_warning()
    annotate_links(ss)
    if warn:
        print(warn, file=sys.stderr)
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
