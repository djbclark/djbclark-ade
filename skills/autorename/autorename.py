#!/usr/bin/env python3
"""Rename the current Claude Code, zcode, Grok, cursor-agent, OpenCode, Codex, or omp session.

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
- OpenCode: `title` in the session store (`~/.local/share/opencode/opencode.db`,
  table `session_v2`, falling back to `session`) written through the running
  server's `session.update` API — the same path the TUI's own rename uses, so a
  live session sees it at once. There is no manual/auto marker, so every title
  is treated as auto and `--auto` never skips.
- Codex: `CODEX_THREAD_ID` identifies the session and `HERDR_PANE_ID` receives
  the visible title through `herdr pane rename`; Codex exposes no local title
  store to this skill, so `--auto` cannot detect a manual title.
- omp: the running omp renames itself. Its extension `omp-bridge.ts` (next to
  this file, symlinked into ~/.omp/agent/extensions/) registers each omp
  process as STATE_DIR/omp/<pid>.json and applies a `<pid>.request.json` with
  `setSessionName(title, "user")`, so omp's own auto-titling never replaces it.
  The current title and its source are read from the session file's first line
  (omp's fixed-width title slot). Writing that file from outside would make omp
  move the session to a sibling file, so a session not running cannot be renamed.

The session id comes from OPENCODE_SESSION_ID when this process is OpenCode,
GROK_SESSION_ID when it is a Grok agent (`GROK_AGENT=1`), else
CLAUDE_CODE_SESSION_ID, else this process's own file descriptors, which zcode
points at its exec-log path ~/.zcode/cli/exec/<sess-id>/call-*.log (zcode sets
no session id env var). CURSOR_CONVERSATION_ID (with `CURSOR_AGENT=1`) wins
when cursor-agent is the nearest agent process above this one; agent env vars
are inherited by any agent started from another's shell, so the process tree
breaks the tie.
OMPCODE=1 with an `omp` process as the nearest agent above this one selects
omp; its session id comes from the bridge's registration for that process.
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
from collections.abc import Iterable
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
AGENT_COMMS = {"cursor-agent": "cursor", "claude": "claude", "grok": "grok", "opencode": "opencode",
               "codex": "codex", "omp": "omp"}


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


def nearest_agent_proc() -> tuple[str, int] | None:
    """(kind, pid) of the closest agent process above this one; kind is an AGENT_COMMS value."""
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
            return AGENT_COMMS[comm], pid
        pid = ppid
    return None


def nearest_agent() -> str | None:
    """'cursor', 'claude', 'grok', ...: the kind of the closest agent process above this one."""
    hit = nearest_agent_proc()
    return hit[0] if hit else None


# ------------------------------------------------------------------ opencode
# Layout (OpenCode V2): ~/.local/share/opencode/opencode.db (SQLite). New
# sessions live in session_v2, pre-v2 ones in session; `title` is the only name
# field and there is no manual/auto marker, so every title is "auto". The
# running server is the one writer, so a rename goes through
# `opencode api session.update` (the path the TUI's own rename and the
# session_rename tool use) rather than a direct DB write the server would not
# notice until it restarts.

OPENCODE_DB = Path.home() / ".local/share/opencode/opencode.db"


def opencode_bin() -> str | None:
    return shutil.which("opencode") or (
        str(Path.home() / ".local/bin/opencode")
        if (Path.home() / ".local/bin/opencode").is_file() else None)


def opencode_current_title(sid: str) -> str | None:
    db = Path(os.environ.get("AUTORENAME_OPENCODE_DB", OPENCODE_DB))
    if not db.is_file():
        return None
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    try:
        for table in ("session_v2", "session"):
            try:
                row = conn.execute(
                    f"SELECT title FROM {table} WHERE id = ?", (sid,)).fetchone()
            except sqlite3.OperationalError:
                continue
            if row is not None:
                return str(row[0] or "").strip() or None
    finally:
        conn.close()
    return None


def opencode_set_title(sid: str, title: str) -> bool:
    bin_ = opencode_bin()
    if bin_ is None:
        print("autorename: opencode binary not found (expected ~/.local/bin/opencode)",
              file=sys.stderr)
        return False
    try:
        r = subprocess.run(
            [bin_, "api", "session.update", "--param", f"sessionID={sid}",
             "--data", json.dumps({"title": title})],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"autorename: opencode session.update failed: {exc}", file=sys.stderr)
        return False
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "").strip().replace("\n", " ")
        print(f"autorename: opencode session.update failed: {detail}", file=sys.stderr)
        return False
    return True


# ---------------------------------------------------------------------- Codex

def codex_pane_title() -> str | None:
    pane = os.environ.get("HERDR_PANE_ID")
    herdr = shutil.which("herdr")
    if not pane or herdr is None:
        return None
    try:
        data = json.loads(subprocess.run(
            [herdr, "pane", "get", pane], capture_output=True, text=True,
            timeout=5, check=True).stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    value = data.get("label") or data.get("title")
    return str(value).strip() or None


def codex_set_title(title: str) -> bool:
    pane = os.environ.get("HERDR_PANE_ID")
    herdr = shutil.which("herdr")
    if not pane or herdr is None:
        print("autorename: Codex needs HERDR_PANE_ID and the herdr binary", file=sys.stderr)
        return False
    try:
        result = subprocess.run([herdr, "pane", "rename", pane, title],
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"autorename: Codex pane rename failed: {exc}", file=sys.stderr)
        return False
    if result.returncode != 0:
        print(f"autorename: Codex pane rename failed: {(result.stderr or result.stdout).strip()}",
              file=sys.stderr)
        return False
    return True


# ----------------------------------------------------------------------- omp
# A live omp registers through omp-bridge.ts as OMP_DIR/<pid>.json
# ({pid, session_id, session_file}) and serves OMP_DIR/<pid>.request.json by
# calling setSessionName, writing OMP_DIR/<pid>.result.<nonce>.json back. The
# extension polls once a second, so a rename waits up to OMP_WAIT seconds.

OMP_DIR = STATE_DIR / "omp"
OMP_SESSIONS = Path(os.environ.get("PI_CODING_AGENT_DIR", Path.home() / ".omp/agent")) / "sessions"
OMP_WAIT = 15.0
OMP_SID_RE = re.compile(r"[0-9A-Za-z-]+")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def omp_registration(pid: int | None = None, sid: str | None = None) -> dict | None:
    """The bridge's record for a live omp process, looked up by pid or by session id."""
    paths = [OMP_DIR / f"{pid}.json"] if pid is not None else sorted(OMP_DIR.glob("*.json"))
    for path in paths:
        if not path.stem.isdigit() or not _alive(int(path.stem)):
            continue
        try:
            reg = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(reg, dict) or not isinstance(reg.get("session_id"), str):
            continue
        if sid is None or reg["session_id"] == sid:
            reg["pid"] = int(path.stem)
            return reg
    return None


def omp_session_file(sid: str, reg: dict | None) -> Path | None:
    if reg and isinstance(reg.get("session_file"), str) and Path(reg["session_file"]).is_file():
        return Path(reg["session_file"])
    if not OMP_SID_RE.fullmatch(sid):
        return None
    hits = sorted(OMP_SESSIONS.glob(f"*/*_{sid}.jsonl"), key=lambda p: p.stat().st_mtime,
                  reverse=True)
    return hits[0] if hits else None


def omp_read(session_file: Path | None) -> tuple[str | None, str | None]:
    """(title, source) from omp's title slot on line 1, else from the session header."""
    if session_file is None:
        return None, None
    with session_file.open(encoding="utf-8", errors="replace") as fh:
        for _ in range(2):
            try:
                rec = json.loads(fh.readline())
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            if rec.get("type") == "title":
                return rec.get("title") or None, rec.get("source")
            if rec.get("type") == "session":
                return rec.get("title") or None, rec.get("titleSource")
    return None, None


def omp_set_title(reg: dict, title: str) -> bool:
    pid, nonce = reg["pid"], os.urandom(8).hex()
    request = OMP_DIR / f"{pid}.request.json"
    result = OMP_DIR / f"{pid}.result.{nonce}.json"
    tmp = OMP_DIR / f".{pid}.request.{os.getpid()}.tmp"
    tmp.write_text(json.dumps({"title": title, "nonce": nonce}), encoding="utf-8")
    tmp.replace(request)
    deadline = time.monotonic() + OMP_WAIT
    while not result.exists():
        if time.monotonic() > deadline:
            request.unlink(missing_ok=True)
            print(f"autorename: omp (pid {pid}) did not answer within {OMP_WAIT:.0f}s;"
                  " is omp-bridge.ts loaded?", file=sys.stderr)
            return False
        time.sleep(0.2)
    try:
        data = json.loads(result.read_text(encoding="utf-8"))
    finally:
        result.unlink(missing_ok=True)
    if not data.get("accepted"):
        print(f"autorename: omp refused the title: {data.get('error') or 'setSessionName declined'}",
              file=sys.stderr)
        return False
    return True


# ----------------------------------------------------------------- all backs

def session_id() -> str | None:
    """This session's id: omp, cursor-agent, OpenCode, or Grok when this process is one, else Claude Code, else zcode."""
    if os.environ.get("OMPCODE") == "1":
        hit = nearest_agent_proc()
        if hit and hit[0] == "omp":
            # Never fall through to inherited ids: omp started from another
            # agent's shell carries that agent's session env vars.
            reg = omp_registration(pid=hit[1])
            return reg["session_id"] if reg else None
    grok = os.environ.get("GROK_SESSION_ID")
    claude = os.environ.get("CLAUDE_CODE_SESSION_ID")
    cursor = (os.environ.get("CURSOR_CONVERSATION_ID")
              if os.environ.get("CURSOR_AGENT") == "1" else None)
    opencode = os.environ.get("OPENCODE_SESSION_ID")
    codex = os.environ.get("CODEX_THREAD_ID")
    if cursor and (not (grok or claude or opencode) or nearest_agent() == "cursor"):
        return cursor
    if opencode and (not (grok or claude or cursor) or nearest_agent() == "opencode"):
        return opencode
    if codex and (not (grok or claude or cursor or opencode) or nearest_agent() == "codex"):
        return codex
    if grok and (os.environ.get("GROK_AGENT") == "1" or not claude):
        return grok
    if claude:
        return claude
    if opencode:
        return opencode
    if codex:
        return codex
    if grok:
        return grok
    return discover_session_id()


def backend_for(sid: str) -> str:
    """Which store owns this id, including the Herdr-backed Codex session."""
    if sid.startswith("sess_"):
        return "zcode"
    if sid.startswith("ses_"):
        return "opencode"
    if os.environ.get("CODEX_THREAD_ID") == sid:
        return "codex"
    if omp_registration(sid=sid) is not None or omp_session_file(sid, None) is not None:
        return "omp"
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
    if kind == "opencode":
        return opencode_current_title(sid)
    if kind == "codex":
        return codex_pane_title()
    if kind == "omp":
        return omp_read(omp_session_file(sid, omp_registration(sid=sid)))[0]
    transcript = find_transcript(sid)
    return current_title(transcript) if transcript else None


def _operator_pinned(source: str | None) -> bool:
    return source in {"custom", "manual", "user"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("title", nargs="?")
    ap.add_argument("--auto", action="store_true", help="do not overwrite a title the operator set")
    ap.add_argument("--show", action="store_true", help="print the current title and exit")
    ap.add_argument("--session-id", default=None,
                    help="session id (Claude Code uuid, cursor-agent chat id, Grok session id,"
                         " OpenCode ses_…, zcode sess_…, Codex thread id, or omp session id);"
                         " default: this session")
    ap.add_argument("--cursor-after-exit", type=int, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--cursor-expect", default="", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.cursor_after_exit is not None:
        return cursor_apply_after_exit(args.session_id, args.cursor_after_exit,
                                       args.cursor_expect, args.title)

    sid = args.session_id or session_id()
    if not sid:
        if os.environ.get("OMPCODE") == "1" and nearest_agent() == "omp":
            print("autorename: this omp has not registered with the autorename bridge; link"
                  f" {Path(__file__).resolve().parent / 'omp-bridge.ts'} into"
                  " ~/.omp/agent/extensions/ and restart omp; nothing renamed", file=sys.stderr)
            return 2
        print("autorename: no CURSOR_CONVERSATION_ID, OPENCODE_SESSION_ID, GROK_SESSION_ID,"
              " CLAUDE_CODE_SESSION_ID, omp bridge registration, or zcode exec-log fd found"
              " (not a cursor-agent, OpenCode, Grok, Claude Code, omp, or zcode session);"
              " nothing renamed", file=sys.stderr)
        return 2

    kind = backend_for(sid)
    transcript = None
    summary = None
    chat = None
    omp_reg = None
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
        elif kind == "opencode":
            current = opencode_current_title(sid)
            source = "auto"
        elif kind == "codex":
            current = codex_pane_title()
            source = "auto"
        elif kind == "omp":
            omp_reg = omp_registration(sid=sid)
            current, source = omp_read(omp_session_file(sid, omp_reg))
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
        elif kind == "opencode":
            print(current or "(no title)")
        elif kind == "codex":
            print(current or "(no pane title)")
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
        elif kind == "opencode":
            if not opencode_set_title(sid, title):
                return 2
        elif kind == "codex":
            if not codex_set_title(title):
                return 2
        elif kind == "omp":
            if omp_reg is None:
                print(f"autorename: omp session {sid} is not running (or its omp has no bridge);"
                      " resume it and use /rename", file=sys.stderr)
                return 2
            if not omp_set_title(omp_reg, title):
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
                json.dumps({"customTitle": title}, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8")
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"autorename: {exc}", file=sys.stderr)
        return 2

    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(title + "\n", encoding="utf-8")
    live += paseo_set_name(title, auto=args.auto)
    print(f"renamed: {title}{live}")
    return 0


def title_slug(title: str, max_len: int) -> str:
    """'ClaudeHelm night run 2026-10-09 + Collie 1.18.1' -> 'claudehelm-night-run': lower case, hyphens,
    whole words only, number-only words dropped. Empty when nothing is left. The caller adds the suffix:
    -t herdr tab, -p herdr pane, -pw Paseo workspace (djbclark, 2026-10-23)."""
    import re
    words = [w for w in re.sub(r"[^a-z0-9]+", " ", title.lower()).split() if not re.fullmatch(r"[0-9.-]+", w)]
    out = ""
    for w in words:
        cand = f"{out}-{w}" if out else w
        if len(cand) > max_len:
            break
        out = cand
    return out


PASEO_WORKSPACE_SLUG_MAX = 40


def paseo_workspace_name(title: str) -> str:
    """The Paseo workspace name for a session title: 'Paseo skill sync overwrite fix' ->
    'paseo-skill-sync-overwrite-fix-pw'."""
    return (title_slug(title, PASEO_WORKSPACE_SLUG_MAX) or "session") + "-pw"


TAB_SUFFIX = "-pt"
TAB_MAX = 17                          # visible length incl. the suffix (djbclark, 2026-10-23)
TAB_BASE_MAX = TAB_MAX - len(TAB_SUFFIX)
_TAB_PHRASES = {
    ("load", "watcher"): "loadwatch", ("session", "finder"): "sfind", ("herdr", "tidy"): "tidy",
    ("djbclark", "ade"): "ade", ("pull", "request"): "pr",
}
_TAB_PAIRS = {"pr": "pr", "round": "r", "issue": "i", "phase": "p"}   # 'pr 31' -> 'pr31', 'round 3' -> 'r3'
_TAB_STOPWORDS = frozenset("a an and the of for to in on with from via by at is it this that my our into".split())
_TAB_WORDS = {
    "adversary": "adv", "review": "rev", "rework": "rwk", "fallback": "fb", "upstream": "up", "workspace": "ws",
    "navigation": "nav", "plugin": "plug", "plugins": "plug", "coordinator": "coord", "implementation": "impl",
    "documentation": "docs", "config": "cfg", "configuration": "cfg", "backup": "bkp", "backups": "bkp",
    "migration": "mig", "security": "sec", "cfengine": "cfe", "lifecycle": "life", "overwrite": "ovw",
    "autorename": "arn", "orchestration": "orch", "watcher": "watch", "handoff": "hoff", "terminal": "term",
    "shell": "sh", "repository": "repo",
}
_TAB_IDENT = re.compile(r"(?:pr|r|i|p)[0-9]+")


def _tab_tokens(text: str) -> list[str]:
    """Steps 1-3 of the tab shortener: lower-case words, phrase table, identifier pairs joined."""
    raw = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    phrased: list[str] = []
    i = 0
    while i < len(raw):
        pair = tuple(raw[i:i + 2])
        if pair in _TAB_PHRASES:
            phrased.append(_TAB_PHRASES[pair])
            i += 2
        else:
            phrased.append(raw[i])
            i += 1
    out: list[str] = []
    i = 0
    while i < len(phrased):
        w = phrased[i]
        nxt = phrased[i + 1] if i + 1 < len(phrased) else ""
        if w in _TAB_PAIRS and nxt.isdigit():
            out.append(_TAB_PAIRS[w] + nxt)
            i += 2
            continue
        m = re.fullmatch(r"phase([0-9]+)", w)         # 'phase0' -> 'p0'
        out.append(f"p{m.group(1)}" if m else w)
        i += 1
    return out


def paseo_tab_name(title: str, context: Iterable[str] = (), taken: Iterable[str] = ()) -> str:
    """The Paseo tab name for a session title: '<name>-pt', at most TAB_MAX (17) characters including the suffix,
    lower case, hyphenated (design-tabs 2.2, 2026-10-24). A Paseo agent tab's name IS the agent's name.
    `context` = words of the workspace's project/title, never repeated in the tab; `taken` = the names of the
    workspace's other live agents and terminals (with or without '-pt'): a clash gets '-2', '-3', ...
    A context entry that is this title's own workspace slug (what `paseo_set_name` names the workspace from the
    same title) is ignored, so a re-run gives the same name instead of dropping the topic's own words.
    Pure and deterministic."""
    toks = _tab_tokens(title)
    own = paseo_workspace_name(title).removesuffix("-pw")
    skip = {t for c in context if re.sub(r"[^a-z0-9]+", "-", c.lower()).strip("-").removesuffix("-pw") != own
            for t in _tab_tokens(c)}
    words = [_TAB_WORDS.get(t, t) for t in toks if t not in _TAB_STOPWORDS and not t.isdigit() and t not in skip]
    # Two identifier tokens first (so 'pr12' survives), then the rest in title order, skipping what does not fit.
    idents = [i for i, w in enumerate(words) if _TAB_IDENT.fullmatch(w)][:2]
    chosen: list[int] = []
    length = 0
    for i in idents + [i for i in range(len(words)) if i not in idents]:
        new = length + 1 + len(words[i]) if chosen else len(words[i])
        if new <= TAB_BASE_MAX:
            chosen.append(i)
            length = new
    base = "-".join(words[i] for i in sorted(chosen))
    if not base:
        base = (words or [t for t in toks if not t.isdigit()] or ["tab"])[0][:TAB_BASE_MAX]
    used = {t.lower().removesuffix(TAB_SUFFIX) for t in taken}
    name, n = base, 1
    while name in used:
        n += 1
        name = base[:TAB_BASE_MAX - len(str(n)) - 1].rstrip("-") + f"-{n}"
    return name + TAB_SUFFIX


def paseo_agent_record(agent: str) -> dict:
    """An agent's record under $PASEO_HOME/agents/<cwd>/<id>.json ({} when absent, unreadable or when `agent`
    is not a plain id: it is globbed, so `*` or `../x` must not reach the pattern)."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", agent):
        return {}
    home = Path(os.environ.get("PASEO_HOME") or Path.home() / ".paseo")
    for rec in (home / "agents").glob(f"*/{agent}.json"):
        try:
            data = json.loads(rec.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def paseo_workspace_id(agent: str) -> str | None:
    """The workspace an agent lives in, from its record (`paseo agent inspect` does not print it, 2026-10-23)."""
    return paseo_agent_record(agent).get("workspaceId") or None


def _paseo_json(path: Path) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def paseo_tab_context(wks: str, applied: str | None = None) -> list[str]:
    """The workspace's title and its project's displayName: words a tab name never repeats. `applied` = the
    workspace name the same call is about to set: it replaces the recorded title, so a rename of an already-named
    session is not shortened against the old title."""
    home = Path(os.environ.get("PASEO_HOME") or Path.home() / ".paseo") / "projects"
    wk = next((w for w in _paseo_json(home / "workspaces.json")
               if isinstance(w, dict) and w.get("workspaceId") == wks), {})
    prj = next((p for p in _paseo_json(home / "projects.json")
                if isinstance(p, dict) and p.get("projectId") == wk.get("projectId")), {})
    title = str(wk.get("title") or "") if applied is None else applied
    if title.endswith("-pw"):
        title = title[:-len("-pw")]
    return [title, str(prj.get("displayName") or "")]


def paseo_tab_taken(agent: str, wks: str, cli: str) -> list[str]:
    """Names of the workspace's other live agents (records, archived ones skipped) and its terminals
    (`paseo terminal ls`, best effort: its JSON shape is unverified, so a failure only means fewer names)."""
    home = Path(os.environ.get("PASEO_HOME") or Path.home() / ".paseo")
    names: list[str] = []
    for rec in sorted((home / "agents").glob("*/*.json")):
        try:
            data = json.loads(rec.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (isinstance(data, dict) and data.get("workspaceId") == wks and data.get("id") != agent
                and not data.get("archivedAt") and data.get("title")):
            names.append(str(data["title"]))
    try:
        r = subprocess.run([cli, "terminal", "ls", "--workspace", wks, "--json"],
                           capture_output=True, text=True, timeout=20)
        rows = json.loads(r.stdout) if r.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired, ValueError):
        rows = []
    names += [str(t.get(k)) for t in rows if isinstance(t, dict) for k in ("name", "title") if t.get(k)]
    return names


def paseo_set_name(title: str, auto: bool = False) -> str:
    """A session hosted by a Paseo agent ($PASEO_AGENT_ID) also gets its tab name set, through
    `paseo agent update --name` (2026-10-19): for an agent the tab name IS the agent name, so it is
    `paseo_tab_name(...)`, `<topic>-pt` (design-tabs, 2026-10-24); the sentence title stays the provider session's.
    Its workspace is renamed to `<slug>-pw` (2026-10-23). `--auto` never replaces an agent name that already
    ends in -pt, nor a workspace that ends in -pw (a name the operator or an earlier run set); this suffix test is
    the fallback while no name store exists, and can still replace a UI rename that lacks the suffix. Never
    fatal: the provider-side title above is the one every other reader uses."""
    agent = os.environ.get("PASEO_AGENT_ID")
    if not agent:
        return ""
    cli = os.environ.get("PASEO_CLI") or shutil.which("paseo")
    if not cli:
        return " (paseo: no CLI, name not set)"
    wks = paseo_workspace_id(agent)
    cur = str(paseo_agent_record(agent).get("title") or "")
    name = paseo_workspace_name(title)
    kept = ""                    # --auto keeps a workspace that already ends in -pw; else `name` replaces its title
    ws_err: BaseException | None = None
    if wks and auto:
        try:
            ls = subprocess.run([cli, "workspace", "ls", "--json"], capture_output=True, text=True, timeout=20)
            rows = json.loads(ls.stdout) if ls.returncode == 0 else None
            if not isinstance(rows, list):
                raise ValueError(f"workspace ls rc {ls.returncode}" if ls.returncode else "workspace ls: not a list")
            now = next((w.get("name") for w in rows if isinstance(w, dict) and w.get("workspaceId") == wks), "")
            kept = now if isinstance(now, str) and now.endswith("-pw") else ""
        except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError, TypeError) as exc:
            ws_err = exc
    if auto and cur.endswith(TAB_SUFFIX):
        out = f" (paseo tab kept: {cur}) (names store unavailable)"
    else:
        tab = paseo_tab_name(title, paseo_tab_context(wks, kept or name) if wks else [],
                             paseo_tab_taken(agent, wks, cli) if wks else [])
        try:
            r = subprocess.run([cli, "agent", "update", agent, "--name", tab, "--json"],
                               capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f" (paseo: {exc})"
        out = f" (paseo tab {tab})" if r.returncode == 0 else f" (paseo: rc {r.returncode})"
        if auto:
            out += " (names store unavailable)"
    if not wks:
        return out + " (paseo workspace: not found)"
    if ws_err is not None:
        return out + f" (paseo workspace: {ws_err})"
    if kept:
        return out + f" (paseo workspace kept: {kept})"
    try:
        r = subprocess.run([cli, "workspace", "rename", wks, name], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return out + f" (paseo workspace: {exc})"
    return out + (f" (paseo workspace {name})" if r.returncode == 0 else f" (paseo workspace: rc {r.returncode})")


if __name__ == "__main__":
    sys.exit(main())
