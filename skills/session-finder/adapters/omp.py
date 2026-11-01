"""omp adapter: ~/.omp/agent/sessions/<slug>/<timestamp>_<id>.jsonl (added 2026-10-31).

Line 1 is a `title` record, then a `session` record (id, cwd), then `message` records whose
`message.role` is user/assistant and whose content is a list of blocks (`text`, `thinking`,
`toolCall`). Tool results, thinking and custom records are not indexed.
"""
import json
from pathlib import Path

AGENT = "omp"
RESUME = "omp --resume={sid}"
ROOT = Path.home() / ".omp" / "agent" / "sessions"


def _text(content):
    if isinstance(content, str):
        return content.strip()
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text").strip()


def _read(path):
    cwd, title, msgs = "", "", []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            kind = d.get("type")
            if kind == "title":
                title = (d.get("title") or "").strip()
            elif kind == "session":
                cwd = d.get("cwd") or cwd
            elif kind == "message":
                m = d.get("message") or {}
                if m.get("role") in ("user", "assistant"):
                    text = _text(m.get("content"))
                    if len(text) > 3:
                        msgs.append((m["role"], text))
    if not title:
        title = " ".join(next((t for r, t in msgs if r == "user"), "").split())[:80]
    return cwd, title, msgs


def sessions():
    for path in ROOT.glob("*/*.jsonl"):
        try:
            st = path.stat()
        except OSError:  # deleted mid-scan, or a broken link
            continue
        sid = path.stem.split("_", 1)[-1]
        yield {"key": f"omp:{sid}", "sid": sid, "fp": f"{st.st_size}:{int(st.st_mtime)}", "mtime": st.st_mtime,
               "load": lambda p=path: _read(p)}
