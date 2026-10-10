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

The session id comes from GROK_SESSION_ID when this process is a Grok agent
(`GROK_AGENT=1`), else CLAUDE_CODE_SESSION_ID, else this process's own file
descriptors, which zcode points at its exec-log path
~/.zcode/cli/exec/<sess-id>/call-*.log (zcode sets no session id env var).
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


# ----------------------------------------------------------------- all backs

def session_id() -> str | None:
    """This session's id: Grok when this process is one, else Claude Code, else zcode."""
    grok = os.environ.get("GROK_SESSION_ID")
    claude = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if grok and (os.environ.get("GROK_AGENT") == "1" or not claude):
        return grok
    if claude:
        return claude
    if grok:
        return grok
    return discover_session_id()


def backend_for(sid: str) -> str:
    """Which store owns this id: 'zcode', 'grok', or 'claude'."""
    if sid.startswith("sess_"):
        return "zcode"
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
                    help="session id (Claude Code uuid, Grok session id, or zcode sess_…); default: this session")
    args = ap.parse_args()

    sid = args.session_id or session_id()
    if not sid:
        print("autorename: no GROK_SESSION_ID, CLAUDE_CODE_SESSION_ID, or zcode exec-log fd found"
              " (not a Grok, Claude Code, or zcode session); nothing renamed", file=sys.stderr)
        return 2

    kind = backend_for(sid)
    transcript = None
    summary = None
    try:
        if kind == "zcode":
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

    state = Path.home() / ".local/state/autorename" / f"{sid}.txt"
    last_written = state.read_text(encoding="utf-8").strip() if state.exists() else None

    # An auto title whose text already matches still gets pinned, so a later
    # Grok title refresh cannot replace it. A manual pin of the same text does not.
    if current == title and _operator_pinned(source):
        print(f"unchanged: {title}")
        return 0
    if args.auto and _operator_pinned(source) and current != last_written:
        print(f"skipped: operator-set title kept ({current!r})")
        return 0

    try:
        if kind == "zcode":
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
    print(f"renamed: {title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
