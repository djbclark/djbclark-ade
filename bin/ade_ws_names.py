"""Paseo window (workspace) names: `<KIND> <repo-name> (<current work>)`, and the legacy forms they replace.

Operator ruling 2026-11-13 (docs/workspace-layout.md): a window is named exactly `<KIND> <repo> (<work>)`, KIND one of
MAIN (a lead's own window, the tab row that includes the lead), WORKERS (the workers the lead starts on its own
initiative), USER (agents the operator started that a lead has connected to). The lead's agent id is not part of a
window name; it stays in the tab name (`worker <slice> <lead id>`) and the `ade.lead` label.

Importable (no side effects): `build`, `parse`, `parse_legacy`, `migrated_name`, `repo_of`, `normalize_work`,
`KINDS`, `NAME_LIMIT`. Used by bin/ade-worker-run; the window tidy skill reuses them.

Legacy forms recognised (`parse_legacy`): `workers <middle> <lead id>` and `WORKERS <middle> <lead id>` (the 2026-11-13
morning scheme) and `MAIN <middle>` (no repo, no parentheses). `migrated_name` turns one into the current form.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
from typing import NamedTuple

KINDS = ("MAIN", "WORKERS", "USER")
NAME_LIMIT = 100  # docs/workspace-layout.md: keep a window or tab name under ~100 characters
REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_NEW_RE = re.compile(rf"^({'|'.join(KINDS)}) ({REPO_RE.pattern}) \((.+)\)$")
_LEGACY_WORKERS_RE = re.compile(rf"^(workers|WORKERS) (.+) ({UUID_RE})$")
_LEGACY_MAIN_RE = re.compile(r"^MAIN (.+)$")


class Name(NamedTuple):
    kind: str
    repo: str
    work: str


class Legacy(NamedTuple):
    kind: str            # "WORKERS" or "MAIN"
    middle: str
    lead: str | None  # the lead id of a workers window, None for MAIN


def check_work(work: str) -> str:
    """The `<current work>` text: nonempty, trimmed, printable, one line. Returns it, or raises ValueError."""
    if not isinstance(work, str) or not work.strip() or work != work.strip() or not work.isprintable():
        raise ValueError("the window's current-work text must be non-empty, trimmed, printable, one line")
    return work


def check_repo(repo: str) -> str:
    if not isinstance(repo, str) or not REPO_RE.fullmatch(repo):
        raise ValueError(f"repo name {repo!r} must match [A-Za-z0-9][A-Za-z0-9._-]*; pass an explicit --repo")
    return repo


def build(kind: str, repo: str, work: str) -> str:
    """`<KIND> <repo> (<work>)`; raises ValueError on a bad part or a name over NAME_LIMIT characters."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, not {kind!r}")
    name = f"{kind} {check_repo(repo)} ({check_work(work)})"
    if len(name) > NAME_LIMIT:
        raise ValueError(f"window name `{name}` exceeds {NAME_LIMIT} characters; shorten the current-work text")
    return name


def parse(name: str) -> Name | None:
    """The current form only, or None (a legacy name, any other name, a wrong-case kind all return None)."""
    m = _NEW_RE.match(name) if isinstance(name, str) else None
    return Name(m.group(1), m.group(2), m.group(3)) if m else None


def parse_legacy(name: str) -> Legacy | None:
    """A pre-2026-11-13-ruling name (see module doc), or None. A name `parse` accepts is never legacy."""
    if not isinstance(name, str) or parse(name):
        return None
    m = _LEGACY_WORKERS_RE.match(name)
    if m and m.group(2).strip() == m.group(2):
        return Legacy("WORKERS", m.group(2), m.group(3))
    m = _LEGACY_MAIN_RE.match(name)
    if m and m.group(1).strip() == m.group(1):
        return Legacy("MAIN", m.group(1), None)
    return None


def normalize_work(middle: str, repo: str) -> str:
    """A legacy middle `<repo> Wave 7` becomes the work `Wave 7` (the repo is now its own field); else unchanged."""
    prefix = f"{repo} "
    rest = middle[len(prefix):].strip() if middle.startswith(prefix) else ""
    return rest or middle.strip()


def migrated_name(legacy: Legacy, repo: str) -> str:
    return build(legacy.kind, repo, normalize_work(legacy.middle, repo))


def _git(path: str, *argv: str) -> str:
    """One `git -C path ARGV` (GIT_* stripped, bounded, no stdin); its stripped stdout, "" on any failure."""
    try:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        out = subprocess.run(["git", "-C", path, *argv], capture_output=True, text=True, timeout=10,
                             stdin=subprocess.DEVNULL, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def primary_checkout_of(cwd: str, _depth: int = 0) -> str:
    """The primary (non-worktree) checkout of the repo `cwd` is in, else `cwd` itself (not a repo, a missing directory, a bare
    repo with no main worktree). A submodule resolves through its superproject's primary checkout (the submodule's own path
    under it, when that exists): its git common dir is `.../modules/<name>`, not a `.git`. A common dir not named `.git`
    takes the first entry of `git worktree list` (the main worktree) unless that is the git dir itself (a bare repo, or a `--separate-git-dir` repo, whose main work tree git does not record: `cwd` comes back and `linked_worktree` says so).
    Never raises."""
    path = os.path.realpath(cwd)
    if _depth > 4:
        return path
    sup = _git(path, "rev-parse", "--show-superproject-working-tree")
    if sup:
        sup = os.path.realpath(sup)
        primary = primary_checkout_of(sup, _depth + 1)
        top = _git(path, "rev-parse", "--show-toplevel")
        if top:
            cand = os.path.join(primary, os.path.relpath(os.path.realpath(top), sup))
            if os.path.isdir(cand):
                return os.path.realpath(cand)
        return path
    common = _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common:
        return path
    if Path(common).name == ".git":
        return os.path.realpath(Path(common).parent) if Path(common).parent.is_dir() else path
    first = _git(path, "worktree", "list", "--porcelain").splitlines()[:3]
    if first and first[0].startswith("worktree ") and "bare" not in first[1:]:
        main = os.path.realpath(first[0][len("worktree "):])
        if os.path.isdir(main) and main != os.path.realpath(common):
            return main
    return path
    sup = _git(path, "rev-parse", "--show-superproject-working-tree")
    if sup:
        sup = os.path.realpath(sup)
        primary = primary_checkout_of(sup, _depth + 1)
        top = _git(path, "rev-parse", "--show-toplevel")
        if top:
            cand = os.path.join(primary, os.path.relpath(os.path.realpath(top), sup))
            if os.path.isdir(cand):
                return os.path.realpath(cand)
        return path
    common = _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not common:
        return path
    if Path(common).name == ".git":
        return os.path.realpath(Path(common).parent) if Path(common).parent.is_dir() else path
    wt = _git(common, "config", "--get", "core.worktree")  # a --separate-git-dir repo records its work tree
    if wt:
        wt = os.path.realpath(os.path.join(common, wt))
        if os.path.isdir(wt):
            return wt
    first = _git(path, "worktree", "list", "--porcelain").splitlines()[:3]
    if first and first[0].startswith("worktree ") and "bare" not in first[1:]:
        main = first[0][len("worktree "):]
        if os.path.isdir(main):
            return os.path.realpath(main)
    return path


def linked_worktree(path: str) -> bool:
    """True when `path` is a linked worktree of a repo (its git dir is not its common dir)."""
    gd = _git(path, "rev-parse", "--path-format=absolute", "--git-dir")
    common = _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return bool(gd and common and os.path.realpath(gd) != os.path.realpath(common))


def repo_of(cwd: str) -> str:
    """The repo name for a directory: the main checkout's name via git (so a linked worktree `repo-x-wt` still reads `repo`),
    else the directory's own basename. Never raises on a non-repo or a missing directory."""
    path = os.path.realpath(cwd)
    try:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}  # GIT_DIR & co. would name the wrong repo
        out = subprocess.run(["git", "-C", path, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                             capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL, env=env)
    except (OSError, subprocess.TimeoutExpired):
        out = None
    if out is not None and out.returncode == 0 and out.stdout.strip():
        common = Path(out.stdout.strip())
        name = common.parent.name if common.name == ".git" else re.sub(r"\.git$", "", common.name)
        if name:
            return name
    return Path(path).name
