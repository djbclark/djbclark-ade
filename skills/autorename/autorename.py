#!/usr/bin/env python3
"""Rename the current Claude Code, zcode, or Grok session, the way /rename does.

A skill cannot invoke the built-in /rename, so this writes what it writes:

- Claude Code: a `custom-title` record appended to the session transcript (the
  running process watches the transcript for these) plus the custom-title.json
  sidecar.
- zcode: the same store the TUI's own rename writes — `title` and
  `title_source='custom'` in the session db (default ~/.zcode/cli/db/db.sqlite).
  Upstream never lets a generated title overwrite a custom one, so one write
  sticks. The running TUI keeps its in-memory title until it restarts; the
  /resume picker and anything else reading the db see the new title at once.
- Grok: `generated_title` plus `title_is_manual: true` in the session's
  `summary.json`, applied under an exclusive flock on `summary.json.lock`
  (the same lock `x.ai/session/rename` uses, so a racing auto-title cannot
  clobber it). `session_summary` is mirrored only while it is still empty.
  `/resume` and `grok sessions list` see the title at once. The running TUI
  does not get the in-process notification `/rename` sends, so its prompt
  border keeps the old caption until the session is resumed.
- cursor-agent: `name` in the chat's store.db (meta row '0', hex of a JSON
  object) plus the `title` in its meta.json sidecar, which the resume picker
  reads. A running cursor-agent holds that object in memory and rewrites the
  whole row on every metadata change (each turn), so a live chat is renamed
  through its own `/rename`: queued into this herdr pane with self-slash, and
  re-applied to disk after the process exits if that never landed. A title is
  manual when a `/rename <title>` entry in prompt_history.json matches it.

The session id comes from GROK_SESSION_ID when this process is a Grok agent
(`GROK_AGENT=1`), else CLAUDE_CODE_SESSION_ID, else this process's own file
descriptors, which zcode points at its exec-log path
~/.zcode/cli/exec/<sess-id>/call-*.log (zcode sets no session id env var).
CURSOR_CONVERSATION_ID (with `CURSOR_AGENT=1`) wins when cursor-agent is the
nearest agent process above this one; agent env vars are inherited by any agent
started from another's shell, so the process tree breaks the tie.
In any other TUI none of those exist and the script exits 2.

    autorename.py "Title words here"            # always rename
    autorename.py --auto "Title words here"     # skip if the operator renamed it by hand
    autorename.py --show                        # print the current title
    autorename.py --session-id <id> "Title"     # explicit id (another session)

Exit 0 = renamed or deliberately skipped (stdout says which); 2 = cannot run.
"""

from __future__ import annotations
import argparse
import fcntl
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MARK = '"type":"custom-title"'
MAX_LEN = 80
ZCODE_SID_RE = re.compile(r"\.zcode/cli/exec/(sess_[0-9a-fA-F-]+)/")


def clean(title: str) -> str:
    title = re.sub(r"[\x00-\x1f\x7f]+", " ", title)
    title = re.sub(r"\s+", " ", title.replace('"', "")).strip().strip("'`")
    return title[:MAX_LEN].rstrip()


# ---------------------------------------------------------------- Claude Code

def find_transcript(sid: str) -> Path | None:
    root = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "projects"
    hits = sorted(root.glob(f"*/{sid}.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0] if hits else None


def current_title(transcript: Path) -> str | None:
    last = None
    with transcript.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if MARK in line:
                try:
                    last = json.loads(line).get("customTitle")
                except ValueError:
                    pass
    return last or None


# ---------------------------------------------------------------------- zcode

def zcode_db() -> Path:
    env = os.environ.get("AUTORENAME_ZCODE_DB")
    if env:
        return Path(env).expanduser()
    try:
        cfg = json.loads((Path.home() / ".zcode/cli/setting.json").read_text(encoding="utf-8"))
        p = cfg.get("storage", {}).get("sessionDbPath")
        if p:
            return Path(p).expanduser()
    except (OSError, ValueError):
        pass
    return Path.home() / ".zcode/cli/db/db.sqlite"


def discover_session_id() -> str | None:
    """The zcode session this shell belongs to, found via zcode's exec-log fds."""
    try:
        out = subprocess.run(["lsof", "-a", "-p", str(os.getpid()), "-F", "n"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in out.splitlines():
        if line.startswith("n"):
            m = ZCODE_SID_RE.search(line)
            if m:
                return m.group(1)
    return None


def zcode_current_title(sid: str) -> tuple[str, str] | None:
    conn = sqlite3.connect(zcode_db(), timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT title, title_source FROM session WHERE id = ?", (sid,)).fetchone()
    finally:
        conn.close()
    return (row["title"], row["title_source"]) if row else None


def zcode_set_title(sid: str, title: str) -> bool:
    conn = sqlite3.connect(zcode_db(), timeout=5)
    try:
        cur = conn.execute(
            "UPDATE session SET title = ?, title_source = 'custom', title_message_id = NULL,"
            " time_title_updated = ? WHERE id = ?",
            (title, int(time.time() * 1000), sid))
        conn.commit()
    finally:
        conn.close()
    return cur.rowcount > 0


# ----------------------------------------------------------------------- grok
# Same boundary as xai_grok_shell::session::persistence (grok-build 1.0.50):
# drop C0/C1 and bidi overrides, reject a blank result, cap at 100 scalars.
# The skill's clean() already caps at 80, which is inside that limit.

def grok_home() -> Path:
    return Path(os.environ.get("GROK_HOME", Path.home() / ".grok"))


def _sid_is_path_safe(sid: str) -> bool:
    return bool(sid) and "/" not in sid and "\\" not in sid and sid not in {".", ".."}


def find_grok_summary(sid: str) -> Path | None:
    """summary.json for a Grok session id, newest cwd group if several match."""
    root = grok_home() / "sessions"
    if not _sid_is_path_safe(sid) or not root.is_dir():
        return None
    hits: list[Path] = []
    try:
        groups = list(root.iterdir())
    except OSError:
        return None
    for group in groups:
        summary = group / sid / "summary.json"
        if summary.is_file():
            hits.append(summary)
    if not hits:
        return None
    hits.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0]


def grok_display(data: dict) -> tuple[str | None, str]:
    """(display title, 'manual'|'auto'). Display prefers generated_title."""
    generated = str(data.get("generated_title") or "").strip()
    summary = str(data.get("session_summary") or "").strip()
    title = generated or summary or None
    source = "manual" if data.get("title_is_manual") and generated else "auto"
    return title, source


def grok_read(summary: Path) -> tuple[dict, str | None, str]:
    data = json.loads(summary.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{summary} is not a JSON object")
    title, source = grok_display(data)
    return data, title, source


def grok_set_title(summary: Path, title: str) -> None:
    """Pin a manual title the way Summary::apply_patch does for /rename.

    Holds summary.json.lock across the read-modify-write so a concurrent
    persistence actor cannot drop the pin or lose its own counter update.
    """
    lock_path = summary.with_name("summary.json.lock")
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    tmp = summary.with_name(f".summary.json.{os.getpid()}.tmp")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        data = json.loads(summary.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{summary} is not a JSON object")
        data["generated_title"] = title
        # Mirror only while empty. A non-empty session_summary is the auto
        # summary /rename leaves in place; display_title prefers generated_title.
        if data.get("session_summary", "") == "":
            data["session_summary"] = title
        data["title_is_manual"] = True
        data["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, summary)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


# --------------------------------------------------------------- cursor-agent
# Layout (cursor-agent 2026.10.01): ~/.cursor/chats/<md5(cwd)>/<uuid>/ holds
# store.db (tables blobs, meta), meta.json and prompt_history.json.

STATE_DIR = Path.home() / ".local/state/autorename"
AGENT_COMMS = {"cursor-agent": "cursor", "claude": "claude", "grok": "grok"}


def cursor_home() -> Path:
    return Path(os.environ.get("AUTORENAME_CURSOR_HOME", Path.home() / ".cursor"))


def find_cursor_chat(sid: str) -> Path | None:
    root = cursor_home() / "chats"
    if not _sid_is_path_safe(sid) or not root.is_dir():
        return None
    try:
        hits = [g / sid for g in root.iterdir()
                if (g / sid / "store.db").is_file() or (g / sid / "meta.json").is_file()]
    except OSError:
        return None
    if not hits:
        return None
    hits.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return hits[0]


def _cursor_meta_row(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT value FROM meta WHERE key = '0'").fetchone()
    if not row or not row[0]:
        raise ValueError("cursor store.db has no meta row")
    data = json.loads(bytes.fromhex(row[0]).decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("cursor store.db meta row is not a JSON object")
    return data


def _cursor_manual_titles(chat: Path) -> set[str]:
    """Titles set with the TUI's own /rename (built-ins land in prompt history)."""
    try:
        history = json.loads((chat / "prompt_history.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {" ".join(e.split()[1:]) for e in history
            if isinstance(e, str) and e.split()[:1] == ["/rename"]}


def cursor_read(chat: Path) -> tuple[str | None, str]:
    """(title, 'manual'|'auto'). store.db is the truth; meta.json is a sidecar."""
    title = None
    db = chat / "store.db"
    if db.is_file():
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        try:
            title = str(_cursor_meta_row(conn).get("name") or "").strip() or None
        finally:
            conn.close()
    else:
        meta = json.loads((chat / "meta.json").read_text(encoding="utf-8"))
        title = str(meta.get("title") or "").strip() or None
    manual = title is not None and " ".join(title.split()) in _cursor_manual_titles(chat)
    return title, "manual" if manual else "auto"


def cursor_live_pid(chat: Path) -> int | None:
    """Pid of a cursor-agent process that has this chat open, if any."""
    db = chat / "store.db"
    if not db.is_file():
        return None
    try:
        out = subprocess.run(["lsof", "-t", str(db)], capture_output=True, text=True,
                             timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    pids = [int(p) for p in out.split() if p.isdigit()]
    return pids[0] if pids else None


def cursor_set_title(chat: Path, title: str) -> None:
    """Write the title the way /rename persists it. Only safe when no process has the chat open."""
    db = chat / "store.db"
    if db.is_file():
        conn = sqlite3.connect(db, timeout=5, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            data = _cursor_meta_row(conn)
            data["name"] = title
            blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('0', ?)", (blob.hex(),))
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()
    meta_path = chat / "meta.json"
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["title"] = title
        meta["updatedAtMs"] = int(time.time() * 1000)
        tmp = meta_path.with_name(f".meta.json.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, meta_path)


def _self_slash() -> str | None:
    here = Path(__file__).resolve().parents[2] / "bin" / "self-slash"
    return str(here) if here.is_file() else shutil.which("self-slash")


def cursor_rename_live(sid: str, pid: int, title: str, current: str | None) -> str:
    """Rename an open chat: /rename in its own herdr pane, else after the process exits."""
    how = []
    own = (os.environ.get("CURSOR_AGENT") == "1"
           and os.environ.get("CURSOR_CONVERSATION_ID") == sid)
    tool = _self_slash()
    if own and tool and os.environ.get("HERDR_ENV") == "1":
        try:
            r = subprocess.run([tool, f"/rename {title}"], capture_output=True, text=True,
                               timeout=30)
            if r.returncode == 0:
                how.append("/rename queued in this herdr pane")
        except (OSError, subprocess.TimeoutExpired):
            pass
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / "cursor-waiter.log").open("a", encoding="utf-8") as log:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--session-id", sid,
             "--cursor-after-exit", str(pid), "--cursor-expect", current or "", title],
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    how.append(f"written to disk when pid {pid} exits, unless renamed by then")
    return "; ".join(how)


def cursor_apply_after_exit(sid: str, pid: int, expect: str, title: str) -> int:
    """Detached waiter: once no process has the chat open, write the title if still unchanged."""
    stamp = lambda: datetime.now().strftime("%F %T")  # noqa: E731
    while True:
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            except PermissionError:
                pass
            time.sleep(10)
        time.sleep(3)
        chat = find_cursor_chat(sid)
        if chat is None:
            print(f"{stamp()} {sid}: chat gone; not renamed", flush=True)
            return 0
        nxt = cursor_live_pid(chat)
        if nxt is None:
            break
        pid = nxt
    current, _source = cursor_read(chat)
    if current == title:
        print(f"{stamp()} {sid}: already {title!r}", flush=True)
    elif (current or "") != expect:
        print(f"{stamp()} {sid}: renamed to {current!r} meanwhile; left alone", flush=True)
    else:
        cursor_set_title(chat, title)
        print(f"{stamp()} {sid}: renamed to {title!r}", flush=True)
    return 0


def nearest_agent() -> str | None:
    """'cursor', 'claude' or 'grok': the closest agent process above this one."""
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,comm="], capture_output=True,
                             text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    procs = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            procs[int(parts[0])] = (int(parts[1]), Path(parts[2].strip()).name)
    pid = os.getppid()
    for _ in range(64):
        if pid not in procs or pid <= 1:
            return None
        ppid, comm = procs[pid]
        if comm in AGENT_COMMS:
            return AGENT_COMMS[comm]
        pid = ppid
    return None


# ----------------------------------------------------------------- all backs

def session_id() -> str | None:
    """This session's id: cursor-agent or Grok when this process is one, else Claude Code, else zcode."""
    grok = os.environ.get("GROK_SESSION_ID")
    claude = os.environ.get("CLAUDE_CODE_SESSION_ID")
    cursor = (os.environ.get("CURSOR_CONVERSATION_ID")
              if os.environ.get("CURSOR_AGENT") == "1" else None)
    if cursor and (not (grok or claude) or nearest_agent() == "cursor"):
        return cursor
    if grok and (os.environ.get("GROK_AGENT") == "1" or not claude):
        return grok
    if claude:
        return claude
    if grok:
        return grok
    return discover_session_id()


def backend_for(sid: str) -> str:
    """Which store owns this id: 'zcode', 'cursor', 'grok', or 'claude'."""
    if sid.startswith("sess_"):
        return "zcode"
    if find_cursor_chat(sid) is not None:
        return "cursor"
    grok_hit = find_grok_summary(sid) is not None
    claude_hit = find_transcript(sid) is not None
    if grok_hit and not claude_hit:
        return "grok"
    if claude_hit and not grok_hit:
        return "claude"
    if grok_hit and claude_hit:
        if os.environ.get("GROK_AGENT") == "1" and os.environ.get("GROK_SESSION_ID") == sid:
            return "grok"
        if os.environ.get("CLAUDE_CODE_SESSION_ID") == sid:
            return "claude"
        return "grok" if os.environ.get("GROK_AGENT") == "1" else "claude"
    if os.environ.get("GROK_SESSION_ID") == sid or (
        os.environ.get("GROK_AGENT") == "1" and not os.environ.get("CLAUDE_CODE_SESSION_ID")
    ):
        return "grok"
    return "claude"


def read_title(sid: str) -> str | None:
    """Current title for a session id, whichever backend the id belongs to."""
    kind = backend_for(sid)
    if kind == "zcode":
        row = zcode_current_title(sid)
        return row[0] if row else None
    if kind == "cursor":
        chat = find_cursor_chat(sid)
        return cursor_read(chat)[0] if chat else None
    if kind == "grok":
        summary = find_grok_summary(sid)
        if summary is None:
            return None
        _data, title, _source = grok_read(summary)
        return title
    transcript = find_transcript(sid)
    return current_title(transcript) if transcript else None


def _operator_pinned(source: str | None) -> bool:
    return source in {"custom", "manual"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("title", nargs="?")
    ap.add_argument("--auto", action="store_true", help="do not overwrite a title the operator set")
    ap.add_argument("--show", action="store_true", help="print the current title and exit")
    ap.add_argument("--session-id", default=None,
                    help="session id (Claude Code uuid, cursor-agent chat id, Grok session id,"
                         " or zcode sess_…); default: this session")
    ap.add_argument("--cursor-after-exit", type=int, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--cursor-expect", default="", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.cursor_after_exit is not None:
        return cursor_apply_after_exit(args.session_id, args.cursor_after_exit,
                                       args.cursor_expect, args.title)

    sid = args.session_id or session_id()
    if not sid:
        print("autorename: no CURSOR_CONVERSATION_ID, GROK_SESSION_ID, CLAUDE_CODE_SESSION_ID,"
              " or zcode exec-log fd found (not a cursor-agent, Grok, Claude Code, or zcode"
              " session); nothing renamed", file=sys.stderr)
        return 2

    kind = backend_for(sid)
    transcript = None
    summary = None
    chat = None
    try:
        if kind == "cursor":
            chat = find_cursor_chat(sid)
            current, source = cursor_read(chat)
        elif kind == "zcode":
            row = zcode_current_title(sid)
            if row is None:
                print(f"autorename: no session {sid} in {zcode_db()}", file=sys.stderr)
                return 2
            current, source = row
        elif kind == "grok":
            summary = find_grok_summary(sid)
            if summary is None:
                print(f"autorename: no Grok session {sid} under {grok_home() / 'sessions'}",
                      file=sys.stderr)
                return 2
            _data, current, source = grok_read(summary)
        else:
            transcript = find_transcript(sid)
            if transcript is None:
                print(f"autorename: no transcript for session {sid}", file=sys.stderr)
                return 2
            current = current_title(transcript)
            source = "custom" if current else None
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"autorename: {exc}", file=sys.stderr)
        return 2

    if args.show:
        if kind == "claude":
            print(current or "(no custom title)")
        else:
            print(f"{current or '(no custom title)'} ({source})")
        return 0
    if not args.title or not (title := clean(args.title)):
        ap.error("a non-empty title is required")

    state = STATE_DIR / f"{sid}.txt"
    last_written = state.read_text(encoding="utf-8").strip() if state.exists() else None

    # An auto title whose text already matches still gets pinned, so a later
    # Grok title refresh cannot replace it. A manual pin of the same text does not.
    # cursor-agent auto-names only an unnamed chat, so a match there needs no pin.
    if current == title and (_operator_pinned(source) or kind == "cursor"):
        print(f"unchanged: {title}")
        return 0
    if args.auto and _operator_pinned(source) and current != last_written:
        print(f"skipped: operator-set title kept ({current!r})")
        return 0

    live = ""
    try:
        if kind == "cursor":
            pid = cursor_live_pid(chat)
            if pid is None:
                cursor_set_title(chat, title)
            else:
                live = f" (live session: {cursor_rename_live(sid, pid, title, current)})"
        elif kind == "zcode":
            if not zcode_set_title(sid, title):
                print(f"autorename: session {sid} vanished from {zcode_db()}", file=sys.stderr)
                return 2
        elif kind == "grok":
            grok_set_title(summary, title)
        else:
            record = json.dumps(
                {"type": "custom-title", "customTitle": title, "sessionId": sid},
                ensure_ascii=False, separators=(",", ":"),
            )
            with transcript.open("a", encoding="utf-8") as fh:
                fh.write(record + "\n")

            sidecar_dir = transcript.parent / sid
            sidecar_dir.mkdir(mode=0o700, exist_ok=True)
            (sidecar_dir / "custom-title.json").write_text(
                json.dumps({"customTitle": title}, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8")
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"autorename: {exc}", file=sys.stderr)
        return 2

    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(title + "\n", encoding="utf-8")
    print(f"renamed: {title}{live}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
