#!/usr/bin/env python3
"""Rename the current Claude Code or zcode session, the way /rename does.

A skill cannot invoke the built-in /rename, so this writes what it writes:

- Claude Code: a `custom-title` record appended to the session transcript (the
  running process watches the transcript for these) plus the custom-title.json
  sidecar.
- zcode: the same store the TUI's own rename writes — `title` and
  `title_source='custom'` in the session db (default ~/.zcode/cli/db/db.sqlite).
  Upstream never lets a generated title overwrite a custom one, so one write
  sticks. The running TUI keeps its in-memory title until it restarts; the
  /resume picker and anything else reading the db see the new title at once.

The session id comes from CLAUDE_CODE_SESSION_ID (Claude Code) or is discovered
from this process's own file descriptors, which zcode points at its exec-log
path ~/.zcode/cli/exec/<sess-id>/call-*.log (zcode sets no session id env var).
In any other TUI neither exists and the script exits 2.

    autorename.py "Title words here"            # always rename
    autorename.py --auto "Title words here"     # skip if the operator renamed it by hand
    autorename.py --show                        # print the current title
    autorename.py --session-id <id> "Title"     # explicit id (another session)

Exit 0 = renamed or deliberately skipped (stdout says which); 2 = cannot run.
"""

from __future__ import annotations
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
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


# ----------------------------------------------------------------- both backs

def session_id() -> str | None:
    """This session's id: CLAUDE_CODE_SESSION_ID if set, else the discovered zcode id."""
    env = os.environ.get("CLAUDE_CODE_SESSION_ID")
    return env or discover_session_id()


def read_title(sid: str) -> str | None:
    """Current title for a session id, whichever backend the id belongs to."""
    if sid.startswith("sess_"):
        row = zcode_current_title(sid)
        return row[0] if row else None
    transcript = find_transcript(sid)
    return current_title(transcript) if transcript else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("title", nargs="?")
    ap.add_argument("--auto", action="store_true", help="do not overwrite a title the operator set")
    ap.add_argument("--show", action="store_true", help="print the current title and exit")
    ap.add_argument("--session-id", default=os.environ.get("CLAUDE_CODE_SESSION_ID"),
                    help="session id (Claude Code uuid or zcode sess_…); default: this session")
    args = ap.parse_args()

    sid = args.session_id or discover_session_id()
    if not sid:
        print("autorename: no CLAUDE_CODE_SESSION_ID and no zcode exec-log fd found"
              " (not a Claude Code or zcode session); nothing renamed", file=sys.stderr)
        return 2

    transcript = None
    if sid.startswith("sess_"):
        row = zcode_current_title(sid)
        if row is None:
            print(f"autorename: no session {sid} in {zcode_db()}", file=sys.stderr)
            return 2
        current, source = row
    else:
        transcript = find_transcript(sid)
        if transcript is None:
            print(f"autorename: no transcript for session {sid}", file=sys.stderr)
            return 2
        current = current_title(transcript)
        source = "custom" if current else None

    if args.show:
        if sid.startswith("sess_"):
            print(f"{current or '(no custom title)'} ({source})")
        else:
            print(current or "(no custom title)")
        return 0
    if not args.title or not (title := clean(args.title)):
        ap.error("a non-empty title is required")

    state = Path.home() / ".local/state/autorename" / f"{sid}.txt"
    last_written = state.read_text(encoding="utf-8").strip() if state.exists() else None

    if current == title:
        print(f"unchanged: {title}")
        return 0
    if args.auto and source == "custom" and current != last_written:
        print(f"skipped: operator-set title kept ({current!r})")
        return 0

    if sid.startswith("sess_"):
        if not zcode_set_title(sid, title):
            print(f"autorename: session {sid} vanished from {zcode_db()}", file=sys.stderr)
            return 2
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
            json.dumps({"customTitle": title}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(title + "\n", encoding="utf-8")
    print(f"renamed: {title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
