"""grok adapter: ~/.grok/sessions/<url-encoded cwd>/<id>/chat_history.jsonl (added 2026-10-31).

`chat_history.jsonl` holds `user`/`assistant` records (content is a list of text blocks; a user
record with `synthetic_reason` is a harness reminder, not the operator); `summary.json` has the
cwd (`info.cwd`) and `session_summary`. `<cwd>/prompt_history.jsonl` keeps every typed prompt,
including ones a compaction dropped from chat_history, so those are added when missing.
"""
import json
import re
from pathlib import Path
from urllib.parse import unquote

AGENT = "grok"
RESUME = "grok --resume {sid}"
ROOT = Path.home() / ".grok" / "sessions"


def _text(content):
    if isinstance(content, str):
        return content.strip()
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") in (None, "text")).strip()


def _user(content):
    text = _text(content)
    queries = re.findall(r"<user_query>\s*([\s\S]*?)\s*</user_query>", text)
    return "\n".join(queries) if queries else text


def _jsonl(path):
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    yield d
    except OSError:
        return


def _read(sdir):
    try:
        summary = json.loads((sdir / "summary.json").read_text())
    except (OSError, ValueError):
        summary = {}
    info = summary.get("info") if isinstance(summary.get("info"), dict) else {}
    cwd = info.get("cwd") or unquote(sdir.parent.name)
    users, replies = [], []
    for d in _jsonl(sdir / "chat_history.jsonl"):
        if d.get("type") == "user" and not d.get("synthetic_reason"):
            users.append(_user(d.get("content")))
        elif d.get("type") == "assistant":
            replies.append(_text(d.get("content")))
    seen = {" ".join(u.split()) for u in users}
    typed = [d["prompt"] for d in _jsonl(sdir.parent / "prompt_history.jsonl")
             if d.get("session_id") == sdir.name and not d.get("is_bash") and isinstance(d.get("prompt"), str)]
    msgs = [("user", p) for p in typed if " ".join(p.split()) not in seen]
    msgs += [("user", u) for u in users] + [("assistant", r) for r in replies]
    msgs = [(r, t) for r, t in msgs if len(t) > 3]
    title = (summary.get("session_summary") or "").strip() or " ".join(next((t for r, t in msgs if r == "user"), "").split())[:80]
    return cwd, title, msgs


def sessions():
    for chat in ROOT.glob("*/*/chat_history.jsonl"):
        sdir = chat.parent
        try:
            st = chat.stat()
        except OSError:
            continue
        sfp, mtime = "", st.st_mtime
        # summary.json and the cwd's prompt_history.jsonl feed the indexed text too: a change to either re-indexes
        for extra in (sdir / "summary.json", sdir.parent / "prompt_history.jsonl"):
            try:
                x = extra.stat()
            except OSError:
                continue
            sfp += f"{extra.name[:3]}{x.st_size}:{int(x.st_mtime)}:"
            mtime = max(mtime, x.st_mtime)
        yield {"key": f"grok:{sdir.name}", "sid": sdir.name, "fp": f"{st.st_size}:{int(st.st_mtime)}:{sfp}",
               "mtime": mtime, "load": lambda d=sdir: _read(d)}
