"""Foreground processes of a pane whose shell is Kiro's terminal shim (2026-10-25).

Kiro's shell integration runs the pane's shell as `bash (kiro-cli-term)` on the pane's PTY and starts the user's real shell on a
second, nested PTY. herdr (`pane process-info`) sees only the outer shim as the foreground process, so a TUI running in the
inner shell (goose, mastracode ...) looked like a plain shell to every session-finder consumer. `inner_foreground` finds the real
foreground processes from one `ps` snapshot, and only when every link is certain; anything else returns None and the caller keeps
herdr's answer (unknown is never promoted to a TUI).

Accepted chain: herdr's only foreground process is the shim, which is also the pane's shell; the shim has exactly ONE child that
owns a distinct controlling tty (the inner shell, itself a shell binary leading its own group); the foreground group of that tty
(`tpgid`) is not the shell's own group, its leader is alive, and the leader descends from the inner shell. The result is the
members of that group on that tty. No descendant or daemon is taken unless it is in that foreground group. Never prints or
returns environment; argv is returned in the shape `fleet.pane_procs` already uses and is never logged.
"""
import os
from pathlib import Path

OUTER_ARGV0 = "bash (kiro-cli-term)"
SHELLS = frozenset({"bash", "zsh", "sh", "dash", "fish", "ksh"})
NO_TTY = frozenset({"", "?", "??", "-"})
PS_ARGS = ("ps", "-axo", "pid=,ppid=,pgid=,tpgid=,tty=,comm=")
PROC_ROOT = "/proc"      # patched by tests so a fixture pid never reads a real process


def parse_ps(text):
    """{pid: {pid, ppid, pgid, tpgid, tty, comm}} from `ps -axo pid=,ppid=,pgid=,tpgid=,tty=,comm=`; malformed lines are skipped."""
    rows = {}
    for line in (text or "").splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        try:
            pid, ppid, pgid, tpgid = (int(p) for p in parts[:4])
        except ValueError:
            continue
        rows[pid] = {"pid": pid, "ppid": ppid, "pgid": pgid, "tpgid": tpgid, "tty": parts[4], "comm": parts[5].strip()}
    return rows


def _descends(rows, pid, ancestor):
    seen = set()
    while pid in rows and pid not in seen:
        if pid == ancestor:
            return True
        seen.add(pid)
        pid = rows[pid]["ppid"]
    return False


def inner_foreground(procs, shell_pid, rows):
    """Rows (the `parse_ps` dicts) of the foreground processes of the inner PTY behind a Kiro shim, or None when PROCS (herdr's
    foreground processes) is not exactly that shim or any link of the chain is missing, stale or ambiguous."""
    if not isinstance(shell_pid, int) or isinstance(shell_pid, bool) or not isinstance(procs, list) or len(procs) != 1:
        return None
    outer = procs[0]
    if outer.get("pid") != shell_pid or outer.get("argv0") != OUTER_ARGV0:
        return None
    shim = rows.get(shell_pid)
    if not shim or shim["tty"] in NO_TTY or shim["pgid"] != shell_pid or shim["tpgid"] != shell_pid:
        return None
    nested = [r for r in rows.values() if r["ppid"] == shell_pid and r["tty"] not in NO_TTY and r["tty"] != shim["tty"]]
    if len(nested) != 1:
        return None
    inner = nested[0]
    if os.path.basename(inner["comm"]) not in SHELLS or inner["pgid"] != inner["pid"]:
        return None
    fg = inner["tpgid"]
    if fg <= 0 or fg == inner["pgid"] or fg not in rows:
        return None
    leader = rows[fg]
    if leader["pgid"] != fg or leader["tty"] != inner["tty"] or not _descends(rows, leader["ppid"], inner["pid"]):
        return None
    group = [r for r in rows.values() if r["pgid"] == fg and r["tty"] == inner["tty"]]
    if not group or any(not _descends(rows, r["pid"], inner["pid"]) for r in group):
        return None
    return sorted(group, key=lambda r: -r["pid"])


def argv_of(row, ps_command):
    """argv of ROW: exact from /proc on Linux; elsewhere `ps -ww -o command=` split on blanks, the only form macOS gives.
    PS_COMMAND(pid) returns that text ('' when unreadable)."""
    try:
        raw = Path(f"{PROC_ROOT}/{row['pid']}/cmdline").read_bytes()
    except OSError:
        raw = b""
    if raw:
        return [a.decode("utf-8", "replace") for a in raw.rstrip(b"\0").split(b"\0")]
    return (ps_command(row["pid"]) or "").split()
