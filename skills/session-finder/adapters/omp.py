"""omp adapter: <agent dir>/sessions/<slug>/<timestamp>_<id>.jsonl (added 2026-10-31; stores, keys and liveness reworked 2026-11-03).

Line 1 is a `title` record, then a `session` record (id, cwd), then `message` records whose
`message.role` is user/assistant and whose content is a list of blocks (`text`, `thinking`,
`toolCall`). Tool results, thinking and custom records are not indexed.

Stores (all indexed, one history): the default agent directory `~/.omp/agent/sessions` (bucketed by project); every named profile,
`~/.omp/profiles/<name>/agent/sessions`; `$PI_CODING_AGENT_DIR/sessions` (omp honours it for the default profile only); and the flat directory
`$PI_CODING_AGENT_SESSION_DIR` (omp's `--session-dir` holds its `.jsonl` files directly). The two directory variables are copied into the launchd job (ROOT_ENV). `PI_CONFIG_DIR` and the
profile variables name a directory or profile rather than a path, so they are not followed: every profile under `~/.omp/profiles` is
indexed anyway, and a `PI_CODING_AGENT_DIR` that omp ignores in a named profile only adds a store that is normally absent.

Keys are `omp:<absolute session file>`: ids repeat across stores and an id taken from a file name collides (`daily.jsonl` in two
projects). The native id comes from a canonical `<ISO timestamp>_<id>` file name, else from the header (`jsonl_session`), and the old
`omp:<id>` row is retired once the file is indexed. The resume hint is `omp --resume=<id>` only for a canonical file of the default
store; any other store gets `omp --resume=<absolute file>`, which needs no profile or directory variable in the caller's environment.

Liveness is exact: `live_among` asks `omp session lease --json -- <ids>` (the lease a running omp holds on every session it writes,
shared by all profiles). A missing `omp`, a failing call or a malformed answer returns every id as unknown, which history prints as
LIVE?; the adapter never reports ended without an answer.
"""
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the shared reader lives beside session-history.py
from jsonl_session import SID, STAMP, native_sid, records  # noqa: E402

AGENT = "omp"
ROOT_ENV = ("PI_CODING_AGENT_DIR", "PI_CODING_AGENT_SESSION_DIR")
RESUME_USES_KEY = True
CONFIG = Path.home() / ".omp"
ROOT = CONFIG / "agent" / "sessions"
LEASE_TIMEOUT = 10
LEASE_BATCH = 200


def RESUME(key, cwd):
    if not key.startswith("omp:/"):
        return ""
    path = Path(key[4:])
    stamp, separator, sid = path.stem.partition("_")
    if separator and STAMP.fullmatch(stamp) and SID.fullmatch(sid) and path.parent.parent == ROOT.resolve():
        return shlex.join(["omp", f"--resume={sid}"])
    return shlex.join(["omp", f"--resume={path}"])


def _text(content):
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    return "\n".join(b["text"] for b in content
                     if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)).strip()


def _read(path):
    cwd, title, msgs = "", "", []
    for d in records(path):
        kind = d.get("type")
        if kind == "title":
            title = (d.get("title") or "").strip() if isinstance(d.get("title"), str) else title
        elif kind == "session":
            cwd = d["cwd"] if isinstance(d.get("cwd"), str) and d["cwd"] else cwd
        elif kind == "message":
            m = d.get("message")
            if isinstance(m, dict) and m.get("role") in ("user", "assistant"):
                text = _text(m.get("content"))
                if len(text) > 3:
                    msgs.append((m["role"], text))
    if not title:
        title = " ".join(next((t for r, t in msgs if r == "user"), "").split())[:80]
    return cwd, title, msgs


def _stores():
    """(directory, flat) pairs: a flat store holds the .jsonl files directly, the others one bucket per project."""
    out = []
    if os.environ.get("PI_CODING_AGENT_SESSION_DIR"):
        out.append((Path(os.environ["PI_CODING_AGENT_SESSION_DIR"]).expanduser(), True))
    if os.environ.get("PI_CODING_AGENT_DIR"):
        out.append((Path(os.environ["PI_CODING_AGENT_DIR"]).expanduser() / "sessions", False))
    out.append((ROOT, False))
    out += [(p, False) for p in sorted((CONFIG / "profiles").glob("*/agent/sessions"))]
    return out


def sessions():
    seen = set()
    for root, flat in _stores():
        files = root.glob("*.jsonl") if flat else root.glob("*/*.jsonl")
        for path in files:
            if path.is_symlink() or path.parent != root and path.parent.is_symlink():
                continue
            try:
                st = path.stat()
                key = f"omp:{path.resolve()}"
            except (OSError, RuntimeError):  # deleted mid-scan, or a broken link
                continue
            if key in seen:  # the same file through overlapping stores
                continue
            sid = native_sid(path, header_lines=4)  # the title record comes first: the session header is line 2
            if not sid:
                continue
            seen.add(key)
            yield {"key": key, "sid": sid,
                   "supersedes": [f"omp:{sid}"],  # retire the old, globally colliding key after a successful load
                   "fp": f"{st.st_size}:{st.st_mtime_ns}", "mtime": st.st_mtime,
                   "load": lambda p=path: _read(p)}


def live_among(sids):
    """(running, unknown) subsets of SIDS from `omp session lease --json`; an id in neither is not running. Any failure of the
    probe (no omp, a timeout, a nonzero exit, an answer that is not {"held": [...], "unknown": [...]}) leaves every id unknown."""
    sids = [s for s in dict.fromkeys(sids) if isinstance(s, str) and s]
    held, unknown = set(), set()
    for i in range(0, len(sids), LEASE_BATCH):
        batch = sids[i:i + LEASE_BATCH]
        try:
            p = subprocess.run(["omp", "session", "lease", "--json", "--", *batch], capture_output=True, text=True,
                               timeout=LEASE_TIMEOUT, check=False, stdin=subprocess.DEVNULL)
            answer = json.loads(p.stdout) if p.returncode == 0 else None
            h, u = answer["held"], answer["unknown"]
            if not all(isinstance(x, str) for x in (*h, *u)):
                raise TypeError("lease ids are strings")
        except (OSError, ValueError, KeyError, TypeError, RecursionError, subprocess.SubprocessError):
            unknown.update(batch)
            continue
        asked = set(batch)
        held |= asked & set(h)
        unknown |= asked & set(u)
    return held, unknown - held
