#!/usr/bin/env python3
"""prior_art_nudge.py — SHADOW telemetry for the "web prior art before code spelunking" question.

Registered under PostToolUse, PostToolUseFailure and UserPromptSubmit (agents/claude/settings.json.tmpl).
It RECORDS, one JSON line per event, when an agent reads or searches code in a way a prior-art web
search might have answered, and what happened next. It NEVER prints to the model, never blocks and never
changes a prompt: stdout and stderr stay empty and the exit status is always 0. Nothing about agent
behaviour changes until these numbers exist (djbclark, 2026-10-25, "approve, but measure first",
docs/queue.md "Research: web prior art ..." decision C1; slice D2 of
research-web-python-lsp-report.md).

Record  ~/.claude/state/prior-art-shadow/<session id>.jsonl   (dir `PRIOR_ART_STATE` overrides;
dir mode 0700, file mode 0600, one O_APPEND write per line, capped at 5 MB with one last
`{"capped":true}` line). Per-session carry-over (previous timestamp, run counters, a salt, recent call
hashes) lives in <session id>.state.json beside it, replaced atomically under <session id>.lock.

Fields: ts (UTC ISO), session (first 12 hex of sha256 of the session id), event, client (the payload's
`model`, else "claude-code"), tool, category, failed, bytes (UTF-8 length of the tool response or error
text), tokens_est (bytes // 4, an estimate), web_or_memory_before (a web or memory event earlier in the
same task), run_length (consecutive external-tree reads without a web, memory or own-code event between;
`external_run` is run_length >= 3), duplicate, retry, quoting_failure, task_seq, elapsed_ms since the
previous event, plus `host` for a fetched URL and `path_top` (first 8 hex of sha256 of the first path
segment below $HOME or /).

PRIVACY: the raw command, path, query, URL and output are never written. The only derived values are
the category, the host name of a fetched URL (never the URL or its query), a short hash of a path's
top-level segment, and booleans. Call hashes kept in the state file are salted with a per-session random
value and never reach the record.

Categories: own_code, external_code, memory, web, private_other, task_change (UserPromptSubmit).
A new UserPromptSubmit, or an idle gap over PRIOR_ART_IDLE_S (default 1800 s), starts a new task and
resets the run counters. `PRIOR_ART_SHADOW=0` disables recording.

MUST exit 0 silently on every failure (malformed event, deep JSON, unwritable state dir, bad UTF-8)
and stay within the hook-deadline wrapper. Python 3 stdlib only.
"""
# Every failure is swallowed on purpose: a telemetry hook must never block or annoy a session.
# ruff: noqa: BLE001, S110
import contextlib
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

CAP_BYTES = 5 * 1024 * 1024
MAX_STDIN = 32 * 1024 * 1024
MAX_WALK_NODES = 200_000
MAX_WALK_DEPTH = 12
SCAN_CHARS = 200_000
RECENT_CALLS = 30
EXTERNAL_RUN = 3
LOCK_RETRIES = 25
LOCK_WAIT_S = 0.02
DEFAULT_IDLE_S = 1800

WEB_TOOLS = {"WebSearch", "WebFetch"}
# Normalised prefixes (lower case, "-" -> "_"); includes the paid cloud Firecrawl on purpose: it is a web event.
WEB_PREFIXES = ("mcp__firecrawl__", "mcp__exa__", "mcp__jina__", "mcp__parallel_search__",
                "mcp__parallel__", "mcp__claude_ai_firecrawl__")
MEMORY_PREFIXES = ("mcp__basic_memory__",)
OWN_CODE_MCP_PREFIXES = ("mcp__graft__", "mcp__trail__")
READ_TOOLS = {"Read", "Grep", "Glob", "NotebookRead", "LSP"}
SHELL_TOOLS = {"Bash", "shell", "shell_command", "exec_command"}
READ_CMDS = {"rg", "grep", "egrep", "fgrep", "cat", "head", "tail", "sed", "gsed", "awk", "gawk",
             "bat", "find", "fd", "ls", "less", "more", "tree", "wc", "ggrep", "graft"}
EXTERNAL_PARTS = ("node_modules", "site-packages", "dist-packages", ".venv", "venv/lib",
                  "vendor", "third_party", "third-party", ".cargo/registry", ".cargo/git",
                  "go/pkg/mod", ".gradle", ".m2", ".npm", ".pnpm-store", ".cache", "nix/store")
QUOTING_MARKERS = ("syntax error", "unexpected eof", "unterminated")
PATH_KEYS = ("file_path", "path", "notebook_path", "filePath")
URL_RE = re.compile(r"https?://[^\s'\"`<>)]+", re.I)
WORD_SPLIT_RE = re.compile(r"[\s'\"`;|&<>()=]+")
SEG_SPLIT_RE = re.compile(r"&&|\|\||[;|\n]")
SID_BAD_RE = re.compile(r"[^A-Za-z0-9._-]")


def _state_dir() -> Path:
    return Path(os.environ.get("PRIOR_ART_STATE") or Path.home() / ".claude/state/prior-art-shadow")


def _idle_s() -> float:
    try:
        return float(os.environ.get("PRIOR_ART_IDLE_S", DEFAULT_IDLE_S))
    except ValueError:
        return float(DEFAULT_IDLE_S)


def _now() -> float:
    try:
        return float(os.environ["PRIOR_ART_NOW"])      # tests only
    except (KeyError, ValueError):
        return time.time()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def safe_session_id(sid: object) -> str:
    s = SID_BAD_RE.sub("_", str(sid or ""))[:100].lstrip(".")
    return s or "unknown"


def read_event() -> dict | None:
    """Normalize the hook payload (same tolerant parse as bash_habits_gate.main: one JSON object on
    stdin, anything else ignored). Bytes are decoded leniently and trailing junk after the first
    JSON value is dropped, so a bad UTF-8 tail or a second document never loses the event."""
    raw = sys.stdin.buffer.read(MAX_STDIN)
    text = raw.decode("utf-8", "replace").lstrip()
    try:
        data, _ = json.JSONDecoder().raw_decode(text)
    except (ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def walk_text(obj: object) -> int:
    """UTF-8 byte length of every string leaf in a tool response, iteratively and bounded."""
    total, nodes = 0, 0
    stack = [(obj, 0)]
    while stack and nodes < MAX_WALK_NODES:
        cur, depth = stack.pop()
        nodes += 1
        if isinstance(cur, str):
            total += len(cur.encode("utf-8", "replace"))
        elif depth < MAX_WALK_DEPTH:
            if isinstance(cur, dict):
                stack.extend((v, depth + 1) for k, v in cur.items() if k != "type")   # content-block labels
            elif isinstance(cur, list):
                stack.extend((v, depth + 1) for v in cur)
    return total


def scan_text(obj: object) -> str:
    """Up to SCAN_CHARS of string leaves, lower-cased, for marker matching only (never stored)."""
    parts, size, nodes = [], 0, 0
    stack = [(obj, 0)]
    while stack and nodes < MAX_WALK_NODES and size < SCAN_CHARS:
        cur, depth = stack.pop()
        nodes += 1
        if isinstance(cur, str):
            parts.append(cur[:SCAN_CHARS])
            size += len(parts[-1])
        elif depth < MAX_WALK_DEPTH:
            if isinstance(cur, dict):
                stack.extend((v, depth + 1) for v in cur.values())
            elif isinstance(cur, list):
                stack.extend((v, depth + 1) for v in cur)
    return "\n".join(parts).lower()


def _expand(p: str, cwd: str) -> str:
    if p.startswith("~"):
        p = str(Path.home()) + p[1:]
    elif not p.startswith("/"):
        p = os.path.join(cwd or "/", p)
    return os.path.normpath(p)


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def is_external(path: str) -> bool:
    home = str(Path.home())
    if _under(path, "/nix/store"):
        return True
    if _under(path, home + "/.cache"):
        return True
    parts = "/" + "/".join(p for p in path.split("/") if p) + "/"
    return any(f"/{m}/" in parts for m in EXTERNAL_PARTS if m != ".cache" and m != "nix/store")


def is_own(path: str, cwd: str) -> bool:
    home = str(Path.home())
    roots = [home + "/src", home + "/ops"]
    if cwd and cwd not in ("/", home):
        roots.append(os.path.normpath(cwd))
    return any(_under(path, r) for r in roots)


def path_top(path: str) -> str:
    home = str(Path.home())
    rel = path[len(home):] if _under(path, home) else path
    seg = next((s for s in rel.split("/") if s), "")
    return _sha(seg)[:8] if seg else ""


def _paths(tool: str, tin: dict, cwd: str) -> list[str]:
    out = [v for k in PATH_KEYS if isinstance(v := tin.get(k), str) and v]
    pat = tin.get("pattern")
    if tool == "Glob" and isinstance(pat, str) and pat[:1] in ("/", "~"):
        out.append(pat)
    if tool in SHELL_TOOLS:
        out.extend(w for w in WORD_SPLIT_RE.split(_command(tin))
                   if w and not w.startswith("-") and "://" not in w
                   and ("/" in w or w.startswith("~")))
    return [_expand(p, cwd) for p in out[:50]]


def _command(tin: dict) -> str:
    cmd = tin.get("command") or tin.get("cmd")
    if isinstance(cmd, list):
        cmd = cmd[-1] if cmd else ""
    return cmd if isinstance(cmd, str) else ""


def _first_word(seg: str) -> str:
    for w in seg.split():
        if "=" in w and not w.startswith(("/", "-", "~", ".")) and re.match(r"[A-Za-z_]\w*=", w):
            continue                                   # FOO=bar cmd
        if w in ("sudo", "env", "command", "time", "nice", "rtk"):
            continue
        return os.path.basename(w.strip("\"'("))
    return ""


def host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "")[:100].lower()
    except ValueError:
        return ""


def classify(tool: str, tin: dict, cwd: str) -> tuple[str, str, str]:
    """(category, host, path_top) from the tool name and input; heuristic, no I/O."""
    norm = tool.lower().replace("-", "_")
    if tool in WEB_TOOLS or norm.startswith(WEB_PREFIXES):
        url = tin.get("url") if isinstance(tin.get("url"), str) else ""
        return "web", host_of(url) if url else "", ""
    if norm.startswith(MEMORY_PREFIXES):
        return "memory", "", ""
    if norm.startswith(OWN_CODE_MCP_PREFIXES):
        return "own_code", "", ""
    if tool in SHELL_TOOLS:
        cmd = _command(tin)
        segs = [s for s in SEG_SPLIT_RE.split(cmd) if s.strip()]
        words = [_first_word(s) for s in segs]
        if "web-get" in words or "web_get" in words:
            m = URL_RE.search(cmd)
            return "web", host_of(m.group(0)) if m else "", ""
        if not any(w in READ_CMDS for w in words):
            return "private_other", "", ""
        paths = _paths(tool, tin, cwd)
        top = path_top(paths[0]) if paths else ""
        if any(is_external(p) for p in paths):
            return "external_code", "", top
        if not paths or all(is_own(p, cwd) for p in paths):
            return "own_code", "", top
        return "private_other", "", top
    if tool in READ_TOOLS:
        paths = _paths(tool, tin, cwd) or ([os.path.normpath(cwd)] if cwd else [])
        top = path_top(paths[0]) if paths else ""
        if any(is_external(p) for p in paths):
            return "external_code", "", top
        if not paths or all(is_own(p, cwd) for p in paths):
            return "own_code", "", top
        return "private_other", "", top
    return "private_other", "", ""


def is_failed(data: dict, resp: object) -> bool:
    if data.get("hook_event_name") == "PostToolUseFailure" or "error" in data:
        return True
    if data.get("is_error") is True:
        return True
    if isinstance(resp, dict):
        if resp.get("is_error") is True or resp.get("isError") is True:
            return True
        for k in ("exit_code", "exitCode", "returncode", "returnCode"):
            v = resp.get(k)
            if isinstance(v, int) and not isinstance(v, bool) and v != 0:
                return True
    return False


def _load_state(path: Path) -> dict:
    try:
        st = json.loads(path.read_text())
        return st if isinstance(st, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(path: Path, st: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".st-")
    try:
        os.write(fd, json.dumps(st, separators=(",", ":")).encode())
        os.close(fd)
        fd = -1
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _ensure_dir(d: Path) -> None:
    if d.is_dir():
        return
    d.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(FileExistsError):
        d.mkdir(mode=0o700)
    os.chmod(d, 0o700)


def _lock(path: Path):
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    for _ in range(LOCK_RETRIES):
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            time.sleep(LOCK_WAIT_S)
    os.close(fd)
    return -1


def build_record(data: dict, st: dict, now: float) -> dict:
    event = str(data.get("hook_event_name") or "PostToolUse")
    tool = str(data.get("tool_name") or "")
    tin = data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {}
    resp = data.get("tool_response") if "tool_response" in data else data.get("error")
    cwd = data.get("cwd") if isinstance(data.get("cwd"), str) else ""
    sid = str(data.get("session_id") or "")

    last_ts = st.get("last_ts")
    elapsed = int((now - last_ts) * 1000) if isinstance(last_ts, (int, float)) and now >= last_ts else None
    new_task = event == "UserPromptSubmit" or (
        isinstance(last_ts, (int, float)) and now - last_ts > _idle_s())
    if new_task:
        st.update(task_seq=int(st.get("task_seq", 0)) + 1, web_or_memory=False, run=0,
                  recent=[], last_failed_call="")
    st.setdefault("salt", os.urandom(8).hex())

    rec: dict = {
        "ts": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="milliseconds"),
        "session": _sha(sid)[:12],
        "event": event,
        "client": str(data.get("model") or "claude-code")[:60],
    }
    if event == "UserPromptSubmit":
        rec.update(tool="", category="task_change", failed=False, bytes=0, tokens_est=0,
                   web_or_memory_before=False, run_length=0, external_run=False, duplicate=False,
                   retry=False, quoting_failure=False)
    else:
        category, host, top = classify(tool, tin, cwd)
        failed = is_failed(data, resp)
        nbytes = walk_text(resp)
        call = _sha(st["salt"] + tool + json.dumps(tin, sort_keys=True, default=str)[:200_000])[:12]
        recent = st.get("recent") if isinstance(st.get("recent"), list) else []
        duplicate = call in recent
        retry = bool(call) and call == st.get("last_failed_call")
        quoting = (failed and tool in SHELL_TOOLS
                   and any(m in scan_text(resp) for m in QUOTING_MARKERS))
        before = bool(st.get("web_or_memory"))
        run = int(st.get("run", 0))
        if category == "external_code":
            run += 1
        elif category in ("web", "memory", "own_code"):
            run = 0
        if category in ("web", "memory"):
            st["web_or_memory"] = True
        st["run"] = run
        st["recent"] = (recent + [call])[-RECENT_CALLS:]
        st["last_failed_call"] = call if failed else ""
        rec.update(tool=re.sub(r"[^A-Za-z0-9_.:-]", "_", tool)[:80], category=category, failed=failed,
                   bytes=nbytes, tokens_est=nbytes // 4, web_or_memory_before=before,
                   run_length=run, external_run=run >= EXTERNAL_RUN, duplicate=duplicate,
                   retry=retry, quoting_failure=quoting)
        if host:
            rec["host"] = host
        if top:
            rec["path_top"] = top
    rec["task_seq"] = int(st.get("task_seq", 0))
    rec["elapsed_ms"] = elapsed
    st["last_ts"] = now
    return rec


def record(data: dict) -> None:
    sid = safe_session_id(data.get("session_id"))
    d = _state_dir()
    _ensure_dir(d)
    lock_fd = _lock(d / f"{sid}.lock")
    if lock_fd < 0:
        return
    try:
        st_path = d / f"{sid}.state.json"
        st = _load_state(st_path)
        out = d / f"{sid}.jsonl"
        fd = os.open(out, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            if st.get("capped"):
                return
            rec = build_record(data, st, _now())
            line = (json.dumps(rec, separators=(",", ":")) + "\n").encode()
            tail = b'{"capped":true}\n'
            if os.fstat(fd).st_size + len(line) + len(tail) > CAP_BYTES:
                os.write(fd, tail)
                st["capped"] = True
            else:
                os.write(fd, line)
        finally:
            os.close(fd)
        _save_state(st_path, st)
    finally:
        os.close(lock_fd)


def main() -> None:
    with contextlib.suppress(Exception):
        sys.stderr = open(os.devnull, "w")             # noqa: SIM115 - shadow mode is silent
    try:
        if os.environ.get("PRIOR_ART_SHADOW") == "0":
            return
        data = read_event()
        if data is not None:
            record(data)
    except BaseException:                              # noqa: BLE001 - incl. RecursionError, MemoryError
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
