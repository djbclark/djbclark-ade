#!/usr/bin/env python3
"""skillopt_sources — SessionDigest adapters for transcript stores SkillOpt-Sleep cannot read.

Upstream's harvester (skillopt_sleep/harvest_sources.py) is a fixed if-chain over
claude, codex, copilot, copilot_cli, cursor, pi and opencode. This module reads
three more local stores read-only and prints SessionDigest-shaped JSON. The
runner (bin/skillopt-night) writes that list as `digests.json` into the
source's handoff dir before the first round: upstream's handoff path loads a
pinned `digests.json` instead of harvesting, then mines it like any other
source. Verified against the stores on this Mac on 2026-10-12.

    skillopt_sources.py zcode|agy|crush [--since ISO] [--limit N] [--out FILE] [--stats]

Adapters (each reads a temporary copy of every SQLite file, WAL included, so a
live writer is never locked or modified):

1. **zcode**: `~/.zcode/cli/db/db.sqlite`, OpenCode's schema without the
   `agent`/`metadata` columns upstream's opencode harvester requires (so it
   finds 0 sessions there). Root sessions (`parent_id` null); user and
   assistant `text` parts that are not synthetic or ignored; tool names from
   `tool` parts. `~/.zcode/v2` holds only a task index, config and
   credentials, `~/.zcode/workspace` is empty, `~/.zcode/cli/rollout` holds
   raw model I/O (not used); `~/.zcode/runtime` does not exist.
2. **agy**: one SQLite file per conversation in
   `~/.gemini/antigravity-cli/conversations`, `~/.gemini/antigravity-acp/conversations`
   and `~/.gemini/antigravity/conversations` (`~/.local/share/agy-acp-home`
   links to the same dirs). Steps are protobuf blobs, decoded schema-free:
   step_type 14 is user input (text at field 19.2); step_type 15 is a model
   step (visible reply at 20.1, tool name at 20.7.2; thinking at 20.3 and tool
   arguments at 20.7.3 are dropped). The project comes from
   `conversation_summaries.db` workspace URIs. `~/.gemini/history` holds only
   `.project_root` markers and `~/.gemini/tmp/*/chats` two legacy Gemini CLI
   chats from July/August 2026: neither is read.
3. **crush**: every project in `~/.local/share/crush-acp/projects.json` and
   `~/.local/share/crush/projects.json`, each `<data_dir>/crush.db`. Root
   sessions; user and assistant `text` parts, tool names from `tool_call`
   parts. `reasoning` parts and `tool` role messages (tool outputs) are dropped.

Every adapter keeps: session id, project directory, start/end time, user
prompts, the last five assistant replies, tool names, feedback signals and turn
counts. It drops: tool arguments and outputs, thinking, attachments, file
contents, model/provider metadata and costs. Every kept string goes through
upstream's `redact_secrets` (or the fallback patterns below) and is capped at
4000 characters. Sessions are skipped when their project is an ephemeral or
benchmark directory (EXCLUDED_ROOTS: /tmp, /private/tmp, /var/folders, which
also holds failover's answer dirs, and ~/.local/state) or when upstream's
`_is_headless_replay`/`_is_agent_session` call them headless replays.

Run it with the skillopt tool's own Python so the upstream helpers import;
under another interpreter it falls back to local redaction and no replay filter.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HOME = Path.home()
MAX_CHARS = 4000
MAX_FINALS = 5
EXCLUDED_ROOTS = ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/",
                  str(HOME / ".local" / "state") + "/")
AGY_DIRS = (HOME / ".gemini" / "antigravity-cli" / "conversations",
            HOME / ".gemini" / "antigravity-acp" / "conversations",
            HOME / ".gemini" / "antigravity" / "conversations")
AGY_SUMMARIES = (HOME / ".gemini" / "antigravity-cli" / "conversation_summaries.db",
                 HOME / ".gemini" / "antigravity" / "conversation_summaries.db")
ZCODE_DB = HOME / ".zcode" / "cli" / "db" / "db.sqlite"
CRUSH_PROJECTS = (HOME / ".local" / "share" / "crush-acp" / "projects.json",
                  HOME / ".local" / "share" / "crush" / "projects.json")

_FALLBACK_SECRETS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)(\s*[:=]\s*)\S+"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
]


def _fallback_redact(text: str) -> str:
    for pat in _FALLBACK_SECRETS:
        text = pat.sub(lambda m: (m.group(1) + m.group(2) if m.lastindex else "") + "[REDACTED]", text)
    return text


def _never(_digest: Any) -> bool:
    return False


try:  # upstream helpers: same redaction and replay filters as the native harvesters
    from skillopt_sleep.harvest import (  # pyright: ignore[reportMissingImports]
        _detect_feedback,
        _is_agent_session,
        _is_headless_replay,
        _is_meta_prompt,
    )
    from skillopt_sleep.staging import redact_secrets  # pyright: ignore[reportMissingImports]
    from skillopt_sleep.types import SessionDigest  # pyright: ignore[reportMissingImports]
    have_upstream = True
except ImportError:  # pragma: no cover - exercised only outside the uv tool venv
    have_upstream = False
    SessionDigest = None
    _is_agent_session = _is_headless_replay = _never

    def _detect_feedback(_text: str) -> list[str]:
        return []

    def _is_meta_prompt(_text: str) -> bool:
        return False

    def redact_secrets(text: str) -> str:
        return _fallback_redact(text)


def clean(text: str) -> str:
    return str(redact_secrets(text or "")).replace("\x00", "").strip()[:MAX_CHARS]


def iso(epoch: float | None) -> str:
    if not epoch or epoch <= 0:
        return ""
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat().replace("+00:00", "Z")


def to_epoch(value: str | None) -> float | None:
    """ISO to epoch; a naive value is local time (SkillOpt's checkpoints are)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    return dt.timestamp()


def excluded(project: str) -> bool:
    p = (project or "").rstrip("/") + "/"
    return any(p.startswith(root) for root in EXCLUDED_ROOTS)


class Builder:
    """Accumulate one session's turns into a SessionDigest-shaped dict."""

    def __init__(self, session_id: str, project: str, raw_path: str) -> None:
        self.d: dict[str, Any] = {
            "session_id": session_id, "project": project, "git_branch": "",
            "started_at": "", "ended_at": "", "user_prompts": [], "assistant_finals": [],
            "tools_used": [], "skills_used": [], "files_touched": [], "feedback_signals": [],
            "n_user_turns": 0, "n_assistant_turns": 0, "raw_path": raw_path}

    def user(self, text: str) -> None:
        text = clean(text)
        if text and not _is_meta_prompt(text):
            self.d["n_user_turns"] += 1
            self.d["user_prompts"].append(text)
            self.d["feedback_signals"].extend(_detect_feedback(text))

    def assistant(self, text: str, tools: list[str]) -> None:
        self.d["n_assistant_turns"] += 1
        for t in tools:
            name = re.sub(r"[^A-Za-z0-9_.:-]+", "_", t.strip())[:80]
            if name and name not in self.d["tools_used"]:
                self.d["tools_used"].append(name)
        text = clean(text)
        if text:
            self.d["assistant_finals"] = (self.d["assistant_finals"] + [text])[-MAX_FINALS:]

    def finish(self, start: float | None, end: float | None) -> dict[str, Any] | None:
        self.d["started_at"], self.d["ended_at"] = iso(start), iso(end)
        self.d["feedback_signals"] = list(dict.fromkeys(self.d["feedback_signals"]))
        if not self.d["user_prompts"]:
            return None
        if have_upstream and SessionDigest is not None:
            known = set(SessionDigest.__dataclass_fields__)
            digest = SessionDigest(**{k: v for k, v in self.d.items() if k in known})
            if _is_headless_replay(digest) or _is_agent_session(digest):
                return None
        return self.d


def snapshot(db: Path, tmp: Path) -> Path:
    """Copy a SQLite file and its -wal/-shm into tmp; read the copy."""
    dest = tmp / db.name
    for suffix in ("", "-wal", "-shm"):
        src = Path(str(db) + suffix)
        if src.exists():
            shutil.copyfile(src, Path(str(dest) + suffix))
    return dest


def connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def _json(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw) if isinstance(raw, str | bytes) else None
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


# ── zcode ────────────────────────────────────────────────────────────────────

def harvest_zcode(since: float | None, tmp: Path, db: Path = ZCODE_DB) -> Iterator[dict[str, Any]]:
    if not db.exists():
        return
    con = connect(snapshot(db, tmp))
    sessions = con.execute("SELECT id, directory, time_created, time_updated FROM session "
                           "WHERE parent_id IS NULL ORDER BY time_updated DESC").fetchall()
    for s in sessions:
        if since and (s["time_updated"] or 0) / 1000 < since:
            continue
        if excluded(s["directory"] or ""):
            continue
        b = Builder(str(s["id"]), str(s["directory"] or ""), f"zcode://{s['id']}")
        parts: dict[str, list[dict[str, Any]]] = {}
        for p in con.execute("SELECT message_id, data FROM part WHERE session_id = ? "
                             "ORDER BY time_created, id", (s["id"],)):
            parts.setdefault(p["message_id"], []).append(_json(p["data"]))
        for m in con.execute("SELECT id, data FROM message WHERE session_id = ? "
                             "ORDER BY time_created, id", (s["id"],)):
            role = _json(m["data"]).get("role")
            ps = parts.get(m["id"], [])
            text = "\n".join(p.get("text", "") for p in ps if p.get("type") == "text"
                             and not p.get("synthetic") and not p.get("ignored")
                             and isinstance(p.get("text"), str))
            if role == "user":
                b.user(text)
            elif role == "assistant":
                b.assistant(text, [str(p.get("tool")) for p in ps
                                   if p.get("type") == "tool" and isinstance(p.get("tool"), str)])
        d = b.finish((s["time_created"] or 0) / 1000, (s["time_updated"] or 0) / 1000)
        if d:
            yield d
    con.close()


# ── agy (protobuf steps) ────────────────────────────────────────────────────

def _varint(b: bytes, i: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        c = b[i]
        i += 1
        result |= (c & 0x7F) << shift
        shift += 7
        if c < 0x80:
            return result, i


def pb_fields(b: bytes) -> list[tuple[int, int, Any]]:
    """Top-level (field, wire type, value) of one protobuf message; [] if malformed."""
    out: list[tuple[int, int, Any]] = []
    i = 0
    try:
        while i < len(b):
            key, i = _varint(b, i)
            field, wt = key >> 3, key & 7
            if field == 0:
                return []
            if wt == 0:
                v, i = _varint(b, i)
            elif wt == 1:
                v, i = b[i:i + 8], i + 8
            elif wt == 5:
                v, i = b[i:i + 4], i + 4
            elif wt == 2:
                n, i = _varint(b, i)
                v, i = b[i:i + n], i + n
            else:
                return []
            out.append((field, wt, v))
    except IndexError:
        return []
    return out if i == len(b) else []


def pb_get(b: bytes, path: tuple[int, ...]) -> list[Any]:
    """Every value at a field path (repeated fields fan out)."""
    vals: list[Any] = [b]
    for field in path:
        nxt = []
        for v in vals:
            if isinstance(v, bytes):
                nxt.extend(val for f, _wt, val in pb_fields(v) if f == field)
        vals = nxt
    return vals


def pb_text(b: bytes, path: tuple[int, ...]) -> list[str]:
    out = []
    for v in pb_get(b, path):
        if isinstance(v, bytes):
            try:
                out.append(v.decode("utf-8"))
            except UnicodeDecodeError:
                continue
    return out


def _agy_step_time(meta: bytes | None) -> float | None:
    secs = pb_get(meta or b"", (1, 1))
    return float(secs[0]) if secs and isinstance(secs[0], int) else None


def agy_projects(tmp: Path) -> dict[str, str]:
    projects: dict[str, str] = {}
    for db in AGY_SUMMARIES:
        if not db.exists():
            continue
        sub = tmp / f"sum-{len(projects)}-{db.parent.name}"
        sub.mkdir(exist_ok=True)
        con = connect(snapshot(db, sub))
        try:
            for row in con.execute("SELECT conversation_id, workspace_uris FROM conversation_summaries"):
                m = re.search(r"file://(/[^\s\",\]]+)", row["workspace_uris"] or "")
                if m:
                    projects[row["conversation_id"]] = m.group(1)
        except sqlite3.Error:
            pass
        con.close()
    return projects


def harvest_agy(since: float | None, tmp: Path) -> Iterator[dict[str, Any]]:
    projects = agy_projects(tmp)
    seen: set[Path] = set()
    files: list[Path] = []
    for d in AGY_DIRS:
        if d.is_dir():
            files.extend(p for p in d.glob("*.db") if p.resolve() not in seen)
            seen.update(p.resolve() for p in d.glob("*.db"))
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files:
        mtime = f.stat().st_mtime
        if since and mtime < since:
            continue
        conv = f.stem
        project = projects.get(conv, "")
        if excluded(project):
            continue
        sub = tmp / f"agy-{conv}"
        sub.mkdir(exist_ok=True)
        try:
            con = connect(snapshot(f, sub))
            steps = con.execute("SELECT step_type, metadata, step_payload FROM steps "
                                "WHERE step_type IN (14, 15) ORDER BY idx").fetchall()
            con.close()
        except sqlite3.Error:
            continue
        finally:
            shutil.rmtree(sub, ignore_errors=True)
        b = Builder(conv, project, f"agy://{conv}")
        times = []
        for st in steps:
            payload = st["step_payload"] or b""
            t = _agy_step_time(st["metadata"])
            if t:
                times.append(t)
            if st["step_type"] == 14:
                b.user("\n".join(pb_text(payload, (19, 2))))
            else:
                text = "\n".join(pb_text(payload, (20, 1)))
                tools = pb_text(payload, (20, 7, 2))
                if text or tools:
                    b.assistant(text, tools)
        d = b.finish(min(times) if times else mtime, max(times) if times else mtime)
        if d:
            yield d


# ── crush ────────────────────────────────────────────────────────────────────

def crush_dbs(projects_files: tuple[Path, ...] = CRUSH_PROJECTS) -> list[tuple[str, Path]]:
    out, seen = [], set()
    for pf in projects_files:
        try:
            rows = json.loads(pf.read_text()).get("projects") or []
        except (OSError, ValueError):
            continue
        for row in rows:
            path, data_dir = str(row.get("path") or ""), str(row.get("data_dir") or "")
            db = Path(data_dir) / "crush.db"
            if not path or excluded(path) or not db.exists() or db.resolve() in seen:
                continue
            seen.add(db.resolve())
            out.append((path, db))
    return out


def harvest_crush(since: float | None, tmp: Path,
                  projects_files: tuple[Path, ...] = CRUSH_PROJECTS) -> Iterator[dict[str, Any]]:
    for n, (project, db) in enumerate(crush_dbs(projects_files)):
        sub = tmp / f"crush-{n}"
        sub.mkdir(exist_ok=True)
        con = connect(snapshot(db, sub))
        for s in con.execute("SELECT id, created_at, updated_at FROM sessions "
                             "WHERE parent_session_id IS NULL OR parent_session_id = '' "
                             "ORDER BY updated_at DESC").fetchall():
            if since and (s["updated_at"] or 0) < since:
                continue
            b = Builder(str(s["id"]), project, f"crush://{db}#{s['id']}")
            for m in con.execute("SELECT role, parts FROM messages WHERE session_id = ? "
                                 "ORDER BY created_at, id", (s["id"],)):
                try:
                    parts = json.loads(m["parts"] or "[]")
                except ValueError:
                    continue
                parts = [p for p in parts if isinstance(p, dict)]
                text = "\n".join(str((p.get("data") or {}).get("text") or "")
                                 for p in parts if p.get("type") == "text")
                if m["role"] == "user":
                    b.user(text)
                elif m["role"] == "assistant":
                    b.assistant(text, [str((p.get("data") or {}).get("name") or "")
                                       for p in parts if p.get("type") == "tool_call"])
            d = b.finish(float(s["created_at"] or 0), float(s["updated_at"] or 0))
            if d:
                yield d
        con.close()


ADAPTERS: dict[str, Callable[[float | None, Path], Iterator[dict[str, Any]]]] = {
    "zcode": harvest_zcode, "agy": harvest_agy, "crush": harvest_crush}


def store_present(name: str) -> bool:
    if name == "zcode":
        return ZCODE_DB.exists()
    if name == "agy":
        return any(d.is_dir() and any(d.glob("*.db")) for d in AGY_DIRS)
    if name == "crush":
        return bool(crush_dbs())
    return False


def harvest(name: str, since: str | None = None, limit: int = 0) -> list[dict[str, Any]]:
    since_epoch = to_epoch(since)
    out = []
    with tempfile.TemporaryDirectory(prefix=f"skillopt-src-{name}-") as tmp:
        for d in ADAPTERS[name](since_epoch, Path(tmp)):
            out.append(d)
            if limit and len(out) >= limit:
                break
    out.sort(key=lambda d: d["ended_at"], reverse=True)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="skillopt_sources", description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("source", choices=sorted(ADAPTERS))
    p.add_argument("--since", help="ISO time; sessions that ended earlier are skipped")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--out", type=Path, help="write the digest list here (default stdout)")
    p.add_argument("--stats", action="store_true", help="print counts only")
    a = p.parse_args(argv)
    digests = harvest(a.source, a.since, a.limit)
    if a.stats:
        print(json.dumps({"source": a.source, "upstream_helpers": have_upstream, "digests": len(digests),
                          "user_prompts": sum(len(d["user_prompts"]) for d in digests),
                          "newest": digests[0]["ended_at"] if digests else None}))
        return 0
    text = json.dumps(digests, ensure_ascii=False, indent=1)
    if a.out:
        tmp = a.out.with_name(a.out.name + ".tmp")
        tmp.write_text(text)
        os.replace(tmp, a.out)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
