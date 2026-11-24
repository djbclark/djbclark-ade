#!/usr/bin/env python3
"""precompact_handoff.py — PreCompact safety net + workspace resolver.

Hook mode (default): read Claude Code hook JSON on stdin, write a Tier 1
sidecar checkpoint (precompact-<utc-ts>.md). MUST always exit 0 — never
fail or delay a compaction, no matter what.

Resolve mode: `--resolve <dir>` prints "<repo>/<task>".

Spec: site-private docs/session-handoff-compaction-spec.md §6.
Python 3 stdlib only. No third-party imports.
"""
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATE_ROOT = Path.home() / ".local" / "state" / "handoffs"
NUDGE_STATE_PATH = Path.home() / ".claude" / "state" / "context-nudges.json"
NUDGE_STATE_MAX_BYTES = 1024 * 1024


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _read_pending_hard_handoff(session_id):
    """Best-effort check whether *session_id* already hit hard tier or carries handoff_due.

    Reads NUDGE_STATE_PATH without following symlinks (where O_NOFOLLOW exists) and caps
    read size to NUDGE_STATE_MAX_BYTES. Always fails silent so PreCompact never blocks.
    """
    if not isinstance(session_id, str) or not session_id or session_id == "unknown":
        return False, None
    fd = None
    try:
        fd = os.open(NUDGE_STATE_PATH, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > NUDGE_STATE_MAX_BYTES:
            return False, None
        with os.fdopen(fd, "rb") as stream:
            fd = None
            raw = stream.read(NUDGE_STATE_MAX_BYTES + 1)
        if len(raw) > NUDGE_STATE_MAX_BYTES:
            return False, None
        state = json.loads(raw.decode("utf-8"))
        if not isinstance(state, dict):
            return False, None
        entry = state.get(session_id)
        if not isinstance(entry, dict):
            return False, None
        level = entry.get("level")
        has_hard_level = _is_int(level) and level >= 2
        handoff_due = entry.get("handoff_due")
        has_handoff_due = isinstance(handoff_due, dict)
        if not (has_hard_level or has_handoff_due):
            return False, None
        candidates = [
            v for v in (
                entry.get("peak"),
                entry.get("last"),
                handoff_due.get("peak") if has_handoff_due else None,
            )
            if _is_int(v) and v >= 0
        ]
        return True, (max(candidates) if candidates else 0)
    except Exception:
        return False, None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass


def _safe_slug(value):
    """Return a bounded filesystem-safe path component for *value*."""
    try:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value))
        slug = re.sub(r"-+", "-", slug).strip("-") or "root"
        if len(slug) > 120:
            digest = hashlib.sha1(slug.encode("utf-8")).hexdigest()[:8]
            slug = f"{slug[:80]}-{digest}"
        return slug
    except Exception:
        return "root"


def _git_root(directory):
    """Best-effort upward search for normal, worktree, or bare git roots."""
    current = directory
    for _ in range(64):
        try:
            dot_git = current / ".git"
            if dot_git.is_dir() or dot_git.is_file():
                return current
            if (current / "HEAD").is_file() and (current / "objects").is_dir():
                return current
            parent = current.parent
            if parent == current:
                break
            current = parent
        except Exception:
            break
    return None


def resolve_workspace(directory):
    """Return a safe ``(repo, task)`` tuple for every directory."""
    try:
        d = Path(directory).expanduser().resolve()
        home = Path.home()
        try:
            parts = d.relative_to(home / "src" / "ops-worktrees").parts
            if len(parts) >= 2 and parts[0] != ".store":
                return parts[1], parts[0]  # repo, task
        except ValueError:
            pass
        try:
            parts = d.relative_to(home / "ops").parts
            if parts:
                return parts[0], "ops"
        except ValueError:
            pass

        root = _git_root(d)
        if root is not None:
            task_path = "root" if d == root else str(d.relative_to(root))
            return _safe_slug(root.name), _safe_slug(task_path)
        return "no-git", _safe_slug(str(d))
    except Exception:
        return "no-git", "root"


def run_git(args, cwd):
    try:
        out = subprocess.run(["git", *args], cwd=cwd,
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def hook_main():
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    try:
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    resolved = resolve_workspace(os.getcwd())
    repo, task = resolved

    cwd = os.getcwd()
    branch = run_git(["branch", "--show-current"], cwd) or "(not a git tree)"
    head_sha = run_git(["rev-parse", "HEAD"], cwd)
    dirty_lines = run_git(["status", "--porcelain"], cwd).splitlines()[:40]
    dirty = "\n".join(dirty_lines)

    state_dir = STATE_ROOT / repo / task
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return

    session_id = data.get("session_id", "unknown")
    pending_hard, pending_peak = _read_pending_hard_handoff(session_id)

    now = datetime.now().astimezone()
    ts_file = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    frontmatter = [
        "---",
        "schema_version: 1",
        "compacted: true",
        f"trigger: {data.get('trigger', 'unknown')}",
        f"updated_at: {now.strftime('%Y-%m-%dT%H:%M:%S%z')}",
        f"session_id: {session_id}",
        f"transcript_path: {data.get('transcript_path', '')}",
        f"repo: {repo}",
        f"workspace: {task}",
        f"branch: {branch}",
        f"head_sha: {head_sha}",
    ]
    if pending_hard:
        frontmatter.append("pending_hard_handoff: true")
        frontmatter.append(f"pending_hard_peak: {pending_peak}")
    frontmatter.append("---")

    body_lines = [
        *frontmatter,
        "",
        "## Dirty files at compaction",
        "",
        f"```\n{dirty}\n```" if dirty else "clean",
        "",
        "Unplanned checkpoint written by precompact_handoff.py. Fold into",
        "SESSION_LOG.md Recent History on next owned write, then delete me.",
    ]
    if pending_hard:
        body_lines.append("")
        body_lines.append(
            f"Hard handoff was already pending before compaction (peak {pending_peak:,} tokens); "
            "run `/self-handoff` now instead of continuing in compacted context."
        )
    body_lines.append("")
    body = "\n".join(body_lines)
    sidecar = state_dir / f"precompact-{ts_file}.md"
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=state_dir,
                                   prefix=".precompact.", suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            f.write(body)
        os.replace(tmp, sidecar)
    except Exception:
        if tmp:
            try:
                os.unlink(tmp)
            except Exception:
                pass
        return

    # Best-effort detached enrichment (Agent SDK + Haiku mines the
    # transcript). Single-shot detach; never blocks or fails compaction.
    if os.environ.get("HANDOFF_ENRICH", "1") == "0":
        return
    tools = Path.home() / ".claude" / "hooks" / "handoff-tools"
    venv_py = tools / ".venv" / "bin" / "python"
    enricher = tools / "enrich_checkpoint.py"
    transcript = data.get("transcript_path", "")
    if venv_py.exists() and enricher.exists() and transcript:
        try:
            with open(state_dir / "enrich.log", "a") as log:
                subprocess.Popen(
                    [str(venv_py), str(enricher), str(sidecar), transcript],
                    stdout=log, stderr=log, start_new_session=True)
        except Exception:
            pass


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--resolve":
        repo, task = resolve_workspace(sys.argv[2])
        print(f"{repo}/{task}")
        return
    hook_main()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
