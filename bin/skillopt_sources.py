#!/usr/bin/env python3
"""skillopt_sources — SessionDigest adapters for transcript stores SkillOpt-Sleep cannot read.

Upstream's harvester (skillopt_sleep/harvest_sources.py) is a fixed if-chain over
claude, codex, copilot, copilot_cli, cursor, pi and opencode. This module reads
eight more local stores read-only and prints SessionDigest-shaped JSON. The
runner (bin/skillopt-night) writes that list as `digests.json` into the
source's handoff dir before the first round: upstream's handoff path loads a
pinned `digests.json` instead of harvesting, then mines it like any other
source. Verified against the stores on this Mac on 2026-10-12 (zcode, agy,
crush) and 2026-10-13 (hermes, grok, muse, cline, acp_dispatch).

    skillopt_sources.py SOURCE [--since ISO] [--limit N] [--out FILE] [--stats]

The first three adapters read a temporary copy of every SQLite file, WAL
included, so a live writer is never locked or modified:

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

Added 2026-10-13 (never written to; files read with a size cap, sessions touched
in the last AGE_GUARD_S seconds skipped as still being written):

4. **hermes**: `~/.hermes/state.db` (1.6 GB, WAL), opened in place with
   `mode=ro` + `query_only` instead of copied. Every session source (cli,
   telegram, discord, desktop, cron, oneshot, mcp-ask, acp, ...) except
   `subagent` children. `user`/`assistant` rows, compacted ones included;
   compression summaries and process-complete, model-switch, hidden and failed
   turns dropped; tool names from `tool_calls`. Cron runs repeat one of three
   prompts: only the newest run per distinct prompt is kept. `~/.hermes/sessions`
   holds only `request_dump_*.json` error dumps and a legacy routing mirror.
5. **grok**: `~/.grok/sessions/<url-encoded cwd>/<id>/chat_history.jsonl` +
   `summary.json`, plus `<url-encoded cwd>/prompt_history.jsonl` for prompts a
   compaction dropped. User turns without `synthetic_reason` (the
   `<user_query>` body), assistant text, `tool_calls` names; reasoning, tool
   results and system reminders dropped. `~/.grok/projects` holds only MCP tool
   descriptors.
6. **muse**: `~/.local/share/muse/sessions/YYYY/MM/DD/<id>/session.jsonl`
   (event records): `runtime.user_intent.accepted` on the main surface,
   `assistant_message_committed` text, `assistant_tool_calls_committed` names;
   project from `runtime.session.metadata`. `subagent/` children skipped.
7. **cline**: `~/.cline/data/sessions/<id>/<id>.json` (metadata) and
   `<id>.messages.json`: user `text` parts (the `<user_input>` wrapper
   stripped), assistant `text` parts and `tool_use` names; `thinking` and
   `tool_result` dropped; subagent sessions skipped.
8. **acp_dispatch**: `~/.local/state/bigteam/<task>/jobs/<name>.json`: the
   slice prompt (record `prompt`, else the brief file) as the user turn, the
   report (else the final file) as the reply, tool names from the ACP log's
   `tool_call` titles; project is the job's `dir`. A job still running is skipped.

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
import math
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

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
HERMES_DB = HOME / ".hermes" / "state.db"
GROK_SESSIONS = HOME / ".grok" / "sessions"
MUSE_SESSIONS = HOME / ".local" / "share" / "muse" / "sessions"
CLINE_SESSIONS = HOME / ".cline" / "data" / "sessions"
BIGTEAM_STATE = HOME / ".local" / "state" / "bigteam"
# Bounds for the file and live-DB adapters (2026-10-13).
AGE_GUARD_S = 600                     # skip a store touched this recently (mid-write)
MAX_FILE_BYTES = 32 * 1024 * 1024     # larger transcripts: first and last 16 MiB only
MAX_JSON_BYTES = 4 * 1024 * 1024      # metadata/summary JSON files
MAX_REPORT_BYTES = 256 * 1024         # acp-dispatch briefs and reports
RAW_CHARS = 4 * MAX_CHARS             # raw slice of one string before redaction
HERMES_SKIP_SOURCES = ("subagent",)   # delegated children; their parent session is kept
# Hermes rows that are not a person or a model speaking: tool-process completion
# notices, model-switch notices, hidden turns, failed turns (and compression summaries).
HERMES_SKIP_KINDS = ("process_complete", "model_switch", "hidden", "failed_turn")
HERMES_MAX_USER_ROWS = 2000
HERMES_MAX_REPLY_ROWS = 400

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


# Extra redaction on top of upstream's prefixed-token and name=value patterns
# (adversary review 2026-10-12, M1): PEM blocks, passwords in prose, and bare
# high-entropy tokens such as a `sudo-secretspec get` output line.
_PEM = re.compile(r"-----BEGIN [A-Z0-9 ]+-----[\s\S]*?(?:-----END [A-Z0-9 ]+-----|\Z)")
_PROSE_SECRET = re.compile(r"(?i)\b(password|passphrase|passwd|api key|secret key)\b(\s*(?:is|was|:|=)\s*)\S+")
_BARE_TOKEN = re.compile(r"(?<![A-Za-z0-9+/=_.-])[A-Za-z0-9+/=_-]{24,}(?![A-Za-z0-9+/=_.-])")


def _entropy(s: str) -> float:
    counts = {c: s.count(c) for c in set(s)}
    return -sum(n / len(s) * math.log2(n / len(s)) for n in counts.values())


def _bare(m: re.Match[str]) -> str:
    tok = m.group(0)
    if "/" in tok.strip("/") and tok.count("/") > 2:  # a path, not a key
        return tok
    lower = sum(c.islower() for c in tok)
    upper = sum(c.isupper() for c in tok)
    digits = sum(c.isdigit() for c in tok)
    mixed = lower >= 2 and upper >= 2 and digits >= 2
    need = 4.2 if len(tok) < 40 else 4.0
    return "[REDACTED]" if mixed and _entropy(tok) >= need else tok


def extra_redact(text: str) -> str:
    text = _PEM.sub("[REDACTED PEM]", text)
    text = _PROSE_SECRET.sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]", text)
    return _BARE_TOKEN.sub(_bare, text)


def clean(text: str) -> str:
    return extra_redact(str(redact_secrets(text or ""))).replace("\x00", "").strip()[:MAX_CHARS]


# The first user prompt of sessions the nightly cycle itself creates when it
# answers prompts through agents (adversary review 2026-10-12, H2): upstream's
# attempt, miner and judge templates, and failover's probe and canary. The
# runner also exports the first three as SKILLOPT_SLEEP_AGENT_MARKERS for
# upstream's own harvesters.
ENGINE_MARKERS = (
    "Complete the following task for the user",
    "You are mining a user's past AI-assistant sessions",
    "Score how well the response satisfies the rubric",
    "Reply with exactly: OK",
    "create an empty file named canary",
)


def engine_session(d: dict[str, Any]) -> bool:
    prompts = d.get("user_prompts") or []
    return bool(prompts) and any(m in str(prompts[0]) for m in ENGINE_MARKERS)


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


EXCLUDE_PROJECTS: list[str] = []  # night.json exclude_projects, set by main()


def excluded(project: str) -> bool:
    p = (project or "").rstrip("/") + "/"
    roots = [*EXCLUDED_ROOTS, *(x.rstrip("/") + "/" for x in EXCLUDE_PROJECTS)]
    return any(p.startswith(root) for root in roots)


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
        if not self.d["user_prompts"] or engine_session(self.d):
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


# ── shared helpers for the file and live-DB stores (2026-10-13) ─────────────

def fresh(epoch: float | None) -> bool:
    """Touched within AGE_GUARD_S: probably still being written, so skip it this night
    (it is newer than tonight's cursor, so the next night picks it up)."""
    return bool(epoch) and float(epoch or 0) > time.time() - AGE_GUARD_S


def mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def read_bounded(path: Path, cap: int = MAX_FILE_BYTES) -> str:
    """The whole file, or for one larger than cap its first and last cap/2 bytes cut to
    whole lines (first prompts and latest replies both survive); "" if unreadable."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            if size <= cap:
                data = f.read()
            else:
                half = cap // 2
                head = f.read(half)
                f.seek(size - half)
                tail = f.read(half)
                data = head[:head.rfind(b"\n") + 1] + tail[tail.find(b"\n") + 1:]
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")


def jsonl_records(path: Path, cap: int = MAX_FILE_BYTES) -> Iterator[dict[str, Any]]:
    """Every JSON object line of a bounded read; corrupt or cut lines are skipped."""
    for line in read_bounded(path, cap).splitlines():
        if line.strip():
            rec = _json(line)
            if rec:
                yield rec


def load_json(path: Path, cap: int = MAX_JSON_BYTES) -> Any:
    """A whole JSON file no larger than cap, else None."""
    try:
        if path.stat().st_size > cap:
            return None
        return json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None


def raw(text: Any) -> str:
    """A bounded slice of a raw string before redaction (clean() caps it again)."""
    return text[:RAW_CHARS] if isinstance(text, str) else ""


def parts_text(content: Any, kinds: tuple[str, ...] = ("text",)) -> str:
    """Text of a string content or a list of {type|kind: text, text} parts."""
    if isinstance(content, str):
        return raw(content)
    if not isinstance(content, list):
        return ""
    out = [raw(p.get("text")) for p in content
           if isinstance(p, dict) and (p.get("type") or p.get("kind")) in kinds]
    return raw("\n".join(t for t in out if t))


def ro_connect(path: Path) -> sqlite3.Connection:
    """Open a live SQLite file read-only in place (mode=ro, query_only): used where a
    snapshot copy would be too large (Hermes state.db is 1.6 GB plus its WAL)."""
    con = sqlite3.connect(f"file:{quote(str(path))}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON")
    return con


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(r[1]) for r in con.execute(f"PRAGMA table_info({table})")}


# ── hermes ───────────────────────────────────────────────────────────────────

def _hermes_tools(tool_calls: Any) -> list[str]:
    calls: Any = None
    if isinstance(tool_calls, str):
        try:
            calls = json.loads(tool_calls)
        except ValueError:  # cut by the SQL substr: fall back to the visible names
            return re.findall(r'"name"\s*:\s*"([^"\\]{1,80})"', tool_calls)
    names = []
    for c in calls if isinstance(calls, list) else []:
        if isinstance(c, dict):
            fn = c.get("function") if isinstance(c.get("function"), dict) else {}
            name = fn.get("name") or c.get("name")
            if isinstance(name, str):
                names.append(name)
    return names


def harvest_hermes(since: float | None, tmp: Path, db: Path | None = None) -> Iterator[dict[str, Any]]:
    """Hermes Agent: every conversation (CLI, TUI, desktop, Telegram, Discord, cron,
    oneshot, mcp-ask, acp) lives in ~/.hermes/state.db, read in place read-only."""
    del tmp  # read in place: a copy of 1.6 GB per night is not sane
    db = db or HERMES_DB
    if not db.exists():
        return
    try:
        con = ro_connect(db)
        scols, mcols = _columns(con, "sessions"), _columns(con, "messages")
    except sqlite3.Error:
        return
    last = ("COALESCE(last_activity_at, ended_at, started_at)" if "last_activity_at" in scols
            else "COALESCE(ended_at, started_at)")
    keep = "1"
    if "display_kind" in mcols:
        skip = ",".join(f"'{k}'" for k in HERMES_SKIP_KINDS)
        keep += f" AND (display_kind IS NULL OR display_kind NOT IN ({skip}))"
    if "_compressed_summary" in mcols:
        keep += " AND COALESCE(_compressed_summary, 0) = 0"
    cols = [c if c in scols else f"NULL AS {c}" for c in ("cwd", "git_repo_root", "git_branch", "ended_at")]
    seen_cron: set[str] = set()
    try:
        sessions = con.execute(
            f"SELECT id, source, started_at, {', '.join(cols)}, {last} AS last FROM sessions "
            f"WHERE source NOT IN ({','.join('?' * len(HERMES_SKIP_SOURCES))}) AND {last} >= ? "
            "ORDER BY last DESC", (*HERMES_SKIP_SOURCES, since or 0)).fetchall()
        for s in sessions:
            if fresh(s["last"]) and not s["ended_at"]:
                continue
            project = str(s["cwd"] or s["git_repo_root"] or "")
            if excluded(project):
                continue
            try:
                users = con.execute(
                    f"SELECT substr(content, 1, {RAW_CHARS}) AS content FROM messages "
                    f"WHERE session_id = ? AND role = 'user' AND {keep} ORDER BY id LIMIT ?",
                    (s["id"], HERMES_MAX_USER_ROWS)).fetchall()
                replies = con.execute(
                    f"SELECT substr(content, 1, {RAW_CHARS}) AS content, "
                    f"substr(tool_calls, 1, {RAW_CHARS}) AS tool_calls FROM messages "
                    f"WHERE session_id = ? AND role = 'assistant' AND {keep} ORDER BY id DESC LIMIT ?",
                    (s["id"], HERMES_MAX_REPLY_ROWS)).fetchall()
            except sqlite3.Error:
                continue
            if s["source"] == "cron":  # 586 cron runs share 3 prompts: keep the newest of each
                key = clean(str(users[0]["content"] or ""))[:500] if users else ""
                if key in seen_cron:
                    continue
                seen_cron.add(key)
            b = Builder(str(s["id"]), project, f"hermes://{s['id']}")
            b.d["git_branch"] = str(s["git_branch"] or "")
            for u in users:
                b.user(str(u["content"] or ""))
            for r in reversed(replies):
                b.assistant(str(r["content"] or ""), _hermes_tools(r["tool_calls"]))
            d = b.finish(float(s["started_at"] or 0), float(s["last"] or 0))
            if d:
                yield d
    except sqlite3.Error:
        return
    finally:
        con.close()


# ── grok ─────────────────────────────────────────────────────────────────────

def _grok_user(content: Any) -> str:
    text = parts_text(content)
    queries = re.findall(r"<user_query>\s*([\s\S]*?)\s*</user_query>", text)
    return "\n".join(queries) if queries else text


def _grok_prompt_history(cwd_dir: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for rec in jsonl_records(cwd_dir / "prompt_history.jsonl"):
        if rec.get("is_bash") or not isinstance(rec.get("prompt"), str):
            continue
        out.setdefault(str(rec.get("session_id") or ""), []).append(raw(rec["prompt"]))
    return out


def harvest_grok(since: float | None, tmp: Path, root: Path | None = None) -> Iterator[dict[str, Any]]:
    """Grok CLI: ~/.grok/sessions/<url-encoded cwd>/<session id>/ holds summary.json and
    chat_history.jsonl; <url-encoded cwd>/prompt_history.jsonl keeps every typed prompt,
    including those a compaction dropped from chat_history."""
    del tmp
    root = root or GROK_SESSIONS
    if not root.is_dir():
        return
    cands = []
    for cwd_dir in (p for p in root.iterdir() if p.is_dir()):
        for sdir in (p for p in cwd_dir.iterdir() if p.is_dir()):
            last = max(mtime(sdir / "chat_history.jsonl"), mtime(sdir / "summary.json"), mtime(sdir))
            cands.append((last, sdir, cwd_dir))
    cands.sort(key=lambda c: c[0], reverse=True)
    history: dict[Path, dict[str, list[str]]] = {}
    for last, sdir, cwd_dir in cands:
        if (since and last < since) or fresh(last):
            continue
        summary = load_json(sdir / "summary.json")
        summary = summary if isinstance(summary, dict) else {}
        info = summary.get("info") if isinstance(summary.get("info"), dict) else {}
        project = str(info.get("cwd") or unquote(cwd_dir.name))
        if excluded(project):
            continue
        sid = str(info.get("id") or sdir.name)
        b = Builder(sid, project, f"grok://{sdir}")
        b.d["git_branch"] = str(summary.get("head_branch") or "")
        chat_users, replies = [], []
        for rec in jsonl_records(sdir / "chat_history.jsonl"):
            kind = rec.get("type")
            if kind == "user" and not rec.get("synthetic_reason"):
                chat_users.append(_grok_user(rec.get("content")))
            elif kind == "assistant":
                tools = [str((c.get("function") or {}).get("name") or c.get("name") or "")
                         for c in rec.get("tool_calls") or [] if isinstance(c, dict)]
                replies.append((parts_text(rec.get("content")), tools))
        if cwd_dir not in history:
            history[cwd_dir] = _grok_prompt_history(cwd_dir)
        seen = {" ".join(u.split()) for u in chat_users}
        for p in history[cwd_dir].get(sid, []):  # typed before a compaction dropped them
            if " ".join(p.split()) not in seen:
                b.user(p)
        for u in chat_users:
            b.user(u)
        for text, tools in replies:
            b.assistant(text, tools)
        start = to_epoch(summary.get("created_at")) or mtime(sdir)
        end = to_epoch(summary.get("last_active_at") or summary.get("updated_at")) or last
        d = b.finish(start, end)
        if d:
            yield d


# ── muse ─────────────────────────────────────────────────────────────────────

def harvest_muse(since: float | None, tmp: Path, root: Path | None = None) -> Iterator[dict[str, Any]]:
    """Muse: one event-sourced session.jsonl per root session under
    ~/.local/share/muse/sessions/YYYY/MM/DD/<id>/ (subagent/ children are skipped)."""
    del tmp
    root = root or MUSE_SESSIONS
    files = sorted(root.glob("[0-9]*/*/*/*/session.jsonl"), key=mtime, reverse=True) if root.is_dir() else []
    for f in files:
        last = mtime(f)
        if (since and last < since) or fresh(last):
            continue
        b = Builder(f.parent.name, "", f"muse://{f.parent.name}")
        times: list[float] = []
        project = ""
        for rec in jsonl_records(f):
            ptype, payload = rec.get("payload_type"), rec.get("payload")
            if not isinstance(payload, dict):
                continue
            if isinstance(rec.get("recorded_at"), int | float):
                times.append(float(rec["recorded_at"]) / 1e6)
            if ptype == "runtime.session.metadata":
                project = str((payload.get("record") or {}).get("workspace_root") or project)
            elif ptype == "runtime.user_intent.accepted" and payload.get("surface") in (None, "main"):
                for m in payload.get("model_messages") or []:
                    if isinstance(m, dict):
                        b.user(parts_text(m.get("content")))
            elif ptype == "runtime.session":
                ev = payload.get("event") if isinstance(payload.get("event"), dict) else {}
                if ev.get("kind") == "assistant_message_committed":
                    b.assistant(raw(ev.get("text")), [])
                elif ev.get("kind") == "assistant_tool_calls_committed":
                    b.assistant("", [str(c.get("name") or "") for c in ev.get("tool_calls") or []
                                     if isinstance(c, dict)])
        if excluded(project):
            continue
        b.d["project"] = project
        d = b.finish(min(times) if times else last, max(times) if times else last)
        if d:
            yield d


# ── cline ────────────────────────────────────────────────────────────────────

def harvest_cline(since: float | None, tmp: Path, root: Path | None = None) -> Iterator[dict[str, Any]]:
    """Cline CLI/desktop (cline-code): ~/.cline/data/sessions/<id>/<id>.json (metadata)
    and <id>.messages.json (Anthropic-style messages)."""
    del tmp
    root = root or CLINE_SESSIONS
    dirs = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: mtime(p / f"{p.name}.messages.json"),
                  reverse=True) if root.is_dir() else []
    for sdir in dirs:
        mfile = sdir / f"{sdir.name}.messages.json"
        last = max(mtime(mfile), mtime(sdir / f"{sdir.name}.json"))
        if not last or (since and last < since) or fresh(last):
            continue
        meta = load_json(sdir / f"{sdir.name}.json")
        meta = meta if isinstance(meta, dict) else {}
        if str(meta.get("is_subagent")).lower() in ("1", "true") or meta.get("parent_session_id"):
            continue
        project = str(meta.get("cwd") or meta.get("workspace_root") or "")
        if excluded(project):
            continue
        data = load_json(mfile, MAX_FILE_BYTES)
        msgs = data.get("messages") if isinstance(data, dict) else data
        b = Builder(str(meta.get("session_id") or sdir.name), project, f"cline://{sdir.name}")
        for m in msgs if isinstance(msgs, list) else []:
            if not isinstance(m, dict):
                continue
            if m.get("role") == "user":
                b.user(re.sub(r"</?user_input\b[^>]*>", "", parts_text(m.get("content"))))
            elif m.get("role") == "assistant":
                content = m.get("content")
                tools = [str(p.get("name") or "") for p in content if isinstance(p, dict)
                         and p.get("type") == "tool_use"] if isinstance(content, list) else []
                b.assistant(parts_text(content), tools)
        d = b.finish(to_epoch(meta.get("started_at")) or last, to_epoch(meta.get("ended_at")) or last)
        if d:
            yield d


# ── acp-dispatch job reports ─────────────────────────────────────────────────

def _job_tools(log: Path) -> list[str]:
    tools: list[str] = []
    for rec in jsonl_records(log):
        data = rec.get("data") if isinstance(rec.get("data"), dict) else {}
        if rec.get("kind") == "update" and data.get("sessionUpdate") == "tool_call":
            title = str(data.get("title") or data.get("kind") or "").split()
            if title and title[0] not in tools:
                tools.append(title[0])
    return tools


def harvest_acp_dispatch(since: float | None, tmp: Path, root: Path | None = None) -> Iterator[dict[str, Any]]:
    """acp-dispatch slices: ~/.local/state/bigteam/<task>/jobs/<name>.json names the
    brief (the prompt), the report the agent wrote (the reply) and the ACP event log."""
    del tmp
    root = root or BIGTEAM_STATE
    recs = sorted(root.glob("*/jobs/*.json"), key=mtime, reverse=True) if root.is_dir() else []
    now = time.time()
    for path in recs:
        rec = load_json(path)
        if not isinstance(rec, dict):
            continue
        report = Path(str(rec.get("report") or rec.get("agent_report") or "")) if (
            rec.get("report") or rec.get("agent_report")) else None
        final = Path(str(rec["final"])) if rec.get("final") else None
        finished = rec.get("finished") if isinstance(rec.get("finished"), int | float) else None
        started = rec.get("started") if isinstance(rec.get("started"), int | float) else None
        last = finished or max(mtime(path), mtime(report) if report else 0.0)
        if (since and last < since) or fresh(last):
            continue
        window = float(rec.get("wait_timeout") or rec.get("timeout") or 21600)
        if finished is None and rec.get("status") == "running" and (started or 0) > now - window:
            continue  # still running: the next night reads it finished
        project = str(rec.get("dir") or "")
        if excluded(project):
            continue
        prompt = rec.get("prompt") if isinstance(rec.get("prompt"), str) else ""
        if not prompt and rec.get("brief"):
            prompt = read_bounded(Path(str(rec["brief"])), MAX_REPORT_BYTES)
        reply = ""
        for p in (report, final):
            if p is not None and p.is_file():
                reply = read_bounded(p, MAX_REPORT_BYTES)
                if reply.strip():
                    break
        name = f"{path.parent.parent.name}/{path.stem}"
        b = Builder(str(rec.get("session_id") or name), project, f"acp-dispatch://{path}")
        b.user(raw(prompt))
        b.assistant(raw(reply), _job_tools(Path(str(rec["log"]))) if rec.get("log") else [])
        d = b.finish(started or last, last)
        if d:
            yield d


ADAPTERS: dict[str, Callable[[float | None, Path], Iterator[dict[str, Any]]]] = {
    "zcode": harvest_zcode, "agy": harvest_agy, "crush": harvest_crush,
    "hermes": harvest_hermes, "grok": harvest_grok, "muse": harvest_muse,
    "cline": harvest_cline, "acp_dispatch": harvest_acp_dispatch}


def _any(paths: Iterator[Path]) -> bool:
    return next(paths, None) is not None


def store_present(name: str) -> bool:
    if name == "zcode":
        return ZCODE_DB.exists()
    if name == "agy":
        return any(d.is_dir() and any(d.glob("*.db")) for d in AGY_DIRS)
    if name == "crush":
        return bool(crush_dbs())
    if name == "hermes":
        return HERMES_DB.is_file()
    if name == "grok":
        return GROK_SESSIONS.is_dir() and _any(GROK_SESSIONS.glob("*/*/chat_history.jsonl"))
    if name == "muse":
        return MUSE_SESSIONS.is_dir() and _any(MUSE_SESSIONS.glob("[0-9]*/*/*/*/session.jsonl"))
    if name == "cline":
        return CLINE_SESSIONS.is_dir() and _any(CLINE_SESSIONS.glob("*/*.messages.json"))
    if name == "acp_dispatch":
        return BIGTEAM_STATE.is_dir() and _any(BIGTEAM_STATE.glob("*/jobs/*.json"))
    return False


NATIVE = ("claude", "codex", "cursor", "opencode", "copilot_cli")
TEXT_FIELDS = ("user_prompts", "assistant_finals")


def finalize(d: dict[str, Any]) -> dict[str, Any] | None:
    """The filters every digest passes, native or adapted: project exclusions, the
    engine's own sessions, and redaction of every kept string."""
    if excluded(str(d.get("project") or "")) or engine_session(d):
        return None
    for key in TEXT_FIELDS:
        d[key] = [t for t in (clean(str(x)) for x in d.get(key) or []) if t]
    if not d.get("user_prompts"):
        return None
    d["assistant_finals"] = d["assistant_finals"][-MAX_FINALS:]
    return d


def harvest_native(source: str, since: str | None, limit: int,
                   codex_home: str | None = None) -> list[dict[str, Any]]:
    """Upstream's own harvester for a source it supports, then finalize(): so native
    sources get the same path exclusions, engine filter and redaction as the adapters."""
    if not have_upstream:
        raise SystemExit("skillopt_sources: native sources need the skillopt tool's Python")
    from skillopt_sleep.config import load_config  # pyright: ignore[reportMissingImports]
    from skillopt_sleep.harvest_sources import harvest_for_config  # pyright: ignore[reportMissingImports]
    overrides: dict[str, Any] = {"transcript_source": source, "projects": "all",
                                 "invoked_project": str(HOME)}
    if codex_home:
        overrides["codex_home"] = codex_home
    cfg = load_config(**overrides)
    digests = harvest_for_config(cfg, since_iso=since, limit=limit * 2 if limit else 0)
    out = []
    for dg in digests:
        d = finalize(dg.to_dict() if hasattr(dg, "to_dict") else dict(vars(dg)))
        if d:
            out.append(d)
            if limit and len(out) >= limit:
                break
    return out


def harvest(name: str, since: str | None = None, limit: int = 0,
            codex_home: str | None = None) -> list[dict[str, Any]]:
    if name in NATIVE:
        out = harvest_native(name, since, limit, codex_home)
    else:
        since_epoch = to_epoch(since)
        out = []
        with tempfile.TemporaryDirectory(prefix=f"skillopt-src-{name}-") as tmp:
            for raw in ADAPTERS[name](since_epoch, Path(tmp)):
                d = finalize(raw)
                if d:
                    out.append(d)
                    if limit and len(out) >= limit:
                        break
    out.sort(key=lambda d: str(d.get("ended_at") or ""), reverse=True)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="skillopt_sources", description=(__doc__ or "").split("\n\n")[0])
    p.add_argument("source", choices=sorted([*ADAPTERS, *NATIVE]))
    p.add_argument("--exclude-project", action="append", default=[],
                   help="skip sessions whose project is under this path (repeatable)")
    p.add_argument("--codex-home", help="codex source: the --codex-home shim")
    p.add_argument("--since", help="ISO time; sessions that ended earlier are skipped")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--out", type=Path, help="write the digest list here (default stdout)")
    p.add_argument("--stats", action="store_true", help="print counts only")
    a = p.parse_args(argv)
    os.umask(0o077)  # the digests hold transcript excerpts
    EXCLUDE_PROJECTS[:] = [os.path.expanduser(x) for x in a.exclude_project]
    digests = harvest(a.source, a.since, a.limit, a.codex_home)
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
