#!/usr/bin/env python3
"""Say where a running agent process lives: herdr ws/tab/pane, Orca worktree, tmux, Ghostty...

    where.py <pid>            # one line + focus command
    where.py --json <pid>

Same set of facts as ~/.local/bin/hermes-ping, but for ANOTHER process: reads that
pid's environment with `ps eww` (same user only) instead of our own. Every lookup
has a short timeout. Exit 0 = found something, 1 = pid gone/unreadable.

A Paseo-hosted agent (2026-10-20) has no terminal: the Paseo daemon spawns the agent process
itself. It is recognised by PASEO_AGENT_ID in its environment AND the daemon being its direct
parent (process title exactly "Paseo Daemon"; "Paseo Supervisor" and "Paseo Voice" do not count), since
a claude started from a Paseo agent's shell inherits the variable without being the agent. The variable
is read only from the environment part of `ps eww` (after the process's own argv; on Linux from
/proc/<pid>/environ), first occurrence wins. The line reads `host=paseo agent=<id>` and the JSON
carries `paseo_agent`.
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

KEYS = ("HERDR_ENV", "HERDR_PANE_ID", "HERDR_TAB_ID", "HERDR_WORKSPACE_ID", "HERDR_BIN_PATH", "HERDR_SESSION",
        "ORCA_PANE_KEY", "ORCA_TAB_ID", "ORCA_WORKSPACE_ROOT", "ORCA_TERMINAL_HANDLE", "TERM_PROGRAM", "TMUX",
        "TMUX_PANE", "ITERM_SESSION_ID", "SSH_CONNECTION", "PASEO_AGENT_ID")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def run(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def env_of(pid):
    """The KEYS found in PID's environment. Linux: /proc/<pid>/environ, exact. Elsewhere `ps eww` prints the
    argv and then the environment on one line, so PASEO_AGENT_ID is taken only from after the argv (the
    process's own `ps -o command=`), first occurrence: an argv word or a later value that contains
    ` PASEO_AGENT_ID=<other>` cannot override it (adversary, 2026-10-20)."""
    try:
        raw = Path(f"/proc/{int(pid)}/environ").read_bytes()
    except (OSError, ValueError):
        raw = None
    if raw is not None:
        env = {}
        for item in raw.decode("utf-8", "replace").split("\0"):
            k, sep, v = item.partition("=")
            if sep and k in KEYS and k not in env:
                env[k] = v.strip()
        return env
    out = run("ps", "eww", "-o", "command=", "-p", str(pid))
    args = run("ps", "-ww", "-o", "command=", "-p", str(pid)).strip()
    env_part = out.strip()[len(args):] if args and out.strip().startswith(args) else None
    env = {}
    for tok in out.split(" "):
        k, sep, v = tok.partition("=")
        if sep and k in KEYS and k != "PASEO_AGENT_ID":
            env[k] = v.strip()
    for tok in (env_part or "").split(" "):
        k, sep, v = tok.partition("=")
        if sep and k == "PASEO_AGENT_ID":
            env[k] = v.strip()
            break
    return env


def jget(text, *path):
    try:
        d = json.loads(text)
    except ValueError:
        return None
    for p in path:
        d = d.get(p) if isinstance(d, dict) else None
    return d


def lab(text, kind):
    o = jget(text, "result", kind)
    return f"{o.get('label') or '?'}#{o.get('number') or '?'}" if isinstance(o, dict) else None


def real_cwd(pid):
    """PID's working directory as an absolute path ('' when unreadable)."""
    for line in run("lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn").splitlines():
        if line.startswith("n"):
            return line[1:]
    return ""


def cwd_of(pid):
    p = real_cwd(pid)
    home = str(os.path.expanduser("~"))
    return "~" + p[len(home):] if p.startswith(home) else p


def paseo_agent(pid, env):
    """The Paseo agent id hosting PID, or None: PASEO_AGENT_ID in its environment and the Paseo daemon as
    its direct parent (the process title Paseo gives the daemon is exactly "Paseo Daemon": its supervisor,
    "Paseo Supervisor", and the voice process, "Paseo Voice", are not agent parents)."""
    agent = env.get("PASEO_AGENT_ID", "")
    if not UUID.match(agent):
        return None
    ppid = run("ps", "-o", "ppid=", "-p", str(pid)).strip()
    if not ppid.isdigit() or run("ps", "-o", "command=", "-p", ppid).strip() != "Paseo Daemon":
        return None
    return agent


def where(pid):
    env = env_of(pid)
    if not env and not run("ps", "-p", str(pid), "-o", "pid="):
        return None
    focus = ""
    title = ""
    paseo = paseo_agent(pid, env)
    if paseo:
        text = f"host=paseo agent={paseo}"
    elif env.get("HERDR_ENV") and env.get("HERDR_PANE_ID"):
        hb = env.get("HERDR_BIN_PATH") or "herdr"
        ws = lab(run(hb, "workspace", "get", env.get("HERDR_WORKSPACE_ID", "")), "workspace")
        tab = lab(run(hb, "tab", "get", env.get("HERDR_TAB_ID", "")), "tab")
        pj = run(hb, "pane", "get", env["HERDR_PANE_ID"])
        pane = jget(pj, "result", "pane") or {}
        title = pane.get("terminal_title_stripped") or ""
        sess = env.get("HERDR_SESSION", "")
        text = (f"herdr{' session ' + sess if sess else ''} · ws {ws or env.get('HERDR_WORKSPACE_ID')} · "
                f"tab {tab or env.get('HERDR_TAB_ID')} · pane {pane.get('label') or pane.get('agent') or env['HERDR_PANE_ID']}")
        focus = f"herdr tab focus {env.get('HERDR_TAB_ID')}"
    elif env.get("ORCA_PANE_KEY") or env.get("TERM_PROGRAM") == "Orca":
        wt = os.path.basename(env.get("ORCA_WORKSPACE_ROOT", "")) or "?"
        text = f"Orca · worktree {wt}" + (f" · tab {env['ORCA_TAB_ID']}" if env.get("ORCA_TAB_ID") else "")
        if env.get("ORCA_TERMINAL_HANDLE"):
            focus = f"orca terminal switch --terminal {env['ORCA_TERMINAL_HANDLE']}"
    elif env.get("TMUX"):
        tp = run("tmux", "display", "-p", "-t", env.get("TMUX_PANE", ""), "#S:#I.#P #W").strip()
        text = f"tmux {tp or '?'}"
        if env.get("TMUX_PANE"):
            focus = f"tmux switch-client -t {env['TMUX_PANE']}"
    else:
        tp = env.get("TERM_PROGRAM", "")
        text = {"ghostty": "Ghostty", "iTerm.app": "iTerm2", "Apple_Terminal": "Terminal.app",
                "vscode": "VS Code/Cursor"}.get(tp, tp or "unknown terminal")
    if env.get("SSH_CONNECTION"):
        text += " · ssh"
    out = {"pid": pid, "where": text, "title": title, "cwd": cwd_of(pid), "focus": focus}
    if paseo:
        out["paseo_agent"] = paseo
    return out


DB = Path.home() / ".local/state/session-index/history.v2.sqlite"
TTL = 3600
# Cached rows carry "v": ROW_VERSION. v2 (2026-10-20) knows the Paseo host; a row without it predates that and
# is looked up again once (an "unknown terminal" row may really be a Paseo agent).
ROW_VERSION = 2


def lookup(pid, proc_start=""):
    """where(pid), cached in the history DB per (pid, procStart) for an hour, so repeat
    queries cost nothing. Returns None when the pid is gone."""
    try:
        db = sqlite3.connect(DB, timeout=60)
        db.execute("CREATE TABLE IF NOT EXISTS locations(pid INTEGER PRIMARY KEY, proc_start TEXT, ts REAL, data TEXT)")
        row = db.execute("SELECT proc_start, ts, data FROM locations WHERE pid=?", (pid,)).fetchone()
        if row and row[0] == proc_start and time.time() - row[1] < TTL:
            cached = json.loads(row[2])
            if cached.get("v") == ROW_VERSION:
                return cached
    except sqlite3.Error:
        db = None
    w = where(pid)
    if w and db:
        try:
            db.execute("INSERT OR REPLACE INTO locations VALUES (?,?,?,?)", (pid, proc_start, time.time(), json.dumps({**w, "v": ROW_VERSION})))
            db.commit()
        except sqlite3.Error:
            pass
    return w


def main():
    args = [a for a in sys.argv[1:] if a != "--json"]
    if len(args) != 1 or not args[0].isdigit():
        print(__doc__, file=sys.stderr)
        return 2
    w = where(int(args[0]))
    if not w:
        return 1
    if "--json" in sys.argv:
        print(json.dumps(w))
    else:
        title = f' · "{w["title"]}"' if w["title"] else ""
        print(f"{w['where']}{title} · {w['cwd']}")
        if w["focus"]:
            print(f"focus: {w['focus']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
