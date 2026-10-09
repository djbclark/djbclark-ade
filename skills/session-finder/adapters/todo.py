"""todo notes: every Basic Memory project's todo/ folder (the `todo` skill's items).

Not a session: each note is one "document" so `session-history.py <words>` (or
`--agent todo`) finds the todo items on a topic next to the sessions that worked
on it. Projects come from ~/.basic-memory/config.json (`main` and the per-agent
pools); any project without a todo/ folder is skipped. Open items print as OPEN,
closed ones as closed (frontmatter `status:`).
"""
import json
import re
from pathlib import Path

AGENT = "todo"
LIVE_LABEL, ENDED_LABEL = "OPEN", "closed"
RESUME = "open {cwd}/{sid}.md"
CONFIG = Path.home() / ".basic-memory/config.json"
FALLBACK = {"main": Path.home() / "ops/site-private/memory"}
_FM = re.compile(r"\A---\n(.*?)\n---\n?", re.S)


def _projects():
    try:
        cfg = json.loads(CONFIG.read_text())
        projects = {n: Path(p["path"] if isinstance(p, dict) else p).expanduser()
                    for n, p in cfg.get("projects", {}).items()}
    except Exception:
        projects = {}
    for n, p in FALLBACK.items():
        projects.setdefault(n, p)
    return projects


def _notes():
    for project, root in sorted(_projects().items()):
        for path in sorted((root / "todo").glob("*.md")):
            if path.is_file():
                yield project, path


def _frontmatter(text):
    m = _FM.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if sep and not line.startswith((" ", "-")):
            meta[k.strip()] = v.strip().strip("'\"")
    return meta, text[m.end():]


def _read(project, path):
    meta, body = _frontmatter(path.read_text(errors="replace"))
    title = meta.get("title") or path.stem
    status = meta.get("status") or "open"
    # One row per section so a long note (the paste-ready ## Prompt) is indexed whole.
    body = re.sub(r"\A\s*# [^\n]*\n", "", body)  # the H1 repeats the title
    chunks = [c.strip() for c in re.split(r"\n(?=## )", body) if c.strip()]
    msgs = [("note", f"{title}\n{c}") for c in chunks] or [("note", title)]
    return str(path.parent), f"[{status}] {project}: {title}", msgs


def sessions():
    for project, path in _notes():
        try:
            st = path.stat()
        except OSError:
            continue
        yield {"key": f"todo:{project}/{path.name}", "sid": path.stem,
               "fp": f"{st.st_size}:{st.st_mtime}", "mtime": st.st_mtime,
               "load": lambda p=project, f=path: _read(p, f)}


def live():
    """Open notes (frontmatter status != closed)."""
    out = set()
    for _project, path in _notes():
        try:
            meta, _ = _frontmatter(path.read_text(errors="replace"))
        except OSError:
            continue
        if (meta.get("status") or "open").lower() != "closed":
            out.add(path.stem)
    return out
