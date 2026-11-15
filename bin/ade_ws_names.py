"""Paseo window (workspace) names: `<KIND> <repo-name> (<current work>)`, and the legacy forms they replace.

Operator ruling 2026-11-14 (docs/workspace-layout.md): per lead and repo at most three windows ("boxes"), named exactly
`<KIND> <repo> (<work>)`, KIND one of LEAD (the lead's own window, the tab row that includes the lead), WORKER (every
worker and reviewer the lead starts), OTHER (anything else: probes, side tasks, agents the operator started that the lead
connected). The lead's agent id is not part of a window name; it stays in the tab name (`worker <slice> <lead id>`) and
the `ade.lead` label.

The 2026-11-13 kinds MAIN, WORKERS and USER are still recognised by `parse` (`Name.box` maps them onto LEAD, WORKER and
OTHER) and are renamed to the current kind when a launch reuses the window; `build` only makes the current kinds.

Importable (no side effects): `build`, `parse`, `parse_legacy`, `migrated_name`, `repo_of`, `normalize_work`, `tab_name`,
`KINDS`, `LEGACY_KINDS`, `BOX_OF`, `NAME_LIMIT`. Used by bin/ade-worker-run; the window tidy skill reuses them.

Legacy forms recognised (`parse_legacy`): `workers <middle> <lead id>` and `WORKERS <middle> <lead id>` (the 2026-11-13
morning scheme) and `MAIN <middle>` (no repo, no parentheses). `migrated_name` turns one into the current form.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
from typing import NamedTuple

KINDS = ("LEAD", "WORKER", "OTHER")
LEGACY_KINDS = ("MAIN", "WORKERS", "USER")  # the 2026-11-13 names of the same three boxes
BOX_OF = {"LEAD": "LEAD", "WORKER": "WORKER", "OTHER": "OTHER", "MAIN": "LEAD", "WORKERS": "WORKER", "USER": "OTHER"}
NAME_LIMIT = 100  # docs/workspace-layout.md: keep a window or tab name under ~100 characters
REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_NEW_RE = re.compile(rf"^({'|'.join(KINDS + LEGACY_KINDS)}) ({REPO_RE.pattern}) \((.+)\)$")
_LEGACY_WORKERS_RE = re.compile(rf"^(workers|WORKERS) (.+) ({UUID_RE})$")
_LEGACY_MAIN_RE = re.compile(r"^MAIN (.+)$")


class Name(NamedTuple):
    kind: str   # as written, a current kind or a 2026-11-13 one
    repo: str
    work: str

    @property
    def box(self) -> str:
        """LEAD, WORKER or OTHER, whichever spelling of the kind the name uses."""
        return BOX_OF[self.kind]

    @property
    def current(self) -> bool:
        """True when the kind is one of the current ones (not MAIN, WORKERS or USER)."""
        return self.kind in KINDS


class Legacy(NamedTuple):
    kind: str            # "WORKERS" or "MAIN" (legacy spellings; `migrated_name` maps them onto WORKER and LEAD)
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
    """`<KIND> <repo> (<work>)` with a current or 2026-11-13 kind, or None (a pre-ruling name, any other name, a wrong-case
    kind all return None)."""
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
    return build(BOX_OF[legacy.kind], repo, normalize_work(legacy.middle, repo))


def current_name(name: Name) -> str:
    """The same window under its current kind (`WORKERS r (w)` -> `WORKER r (w)`)."""
    return build(name.box, name.repo, name.work)


TAB_PREFIX = {"LEAD": "worker", "WORKER": "worker", "OTHER": "other"}  # the first word of a tab name, by box


def tab_name(box: str, slice_name: str, lead: str, worktree: str | None = None) -> str:
    """`worker <slice> <lead id>`, with ` [wt: <worktree dir basename>]` when the launch names a worktree; `other ...` in the
    OTHER box. The worktree part is a hint, so a name over NAME_LIMIT shortens it (with `~`) rather than failing."""
    base = f"{TAB_PREFIX[box]} {slice_name} {lead}"
    if not worktree:
        return base
    d = os.path.basename(os.path.realpath(worktree).rstrip("/")) or worktree
    d = "".join(c for c in d if c.isprintable() and c not in "[]\n")
    room = NAME_LIMIT - len(base) - len(" [wt: ]")
    if not d or room < 1:
        return base
    return f"{base} [wt: {d if len(d) <= room else d[:room - 1] + '~'}]"


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
            if os.path.isdir(cand) and _git(cand, "rev-parse", "--show-toplevel") == os.path.realpath(cand):  # not an empty, uninitialised dir
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


def linked_worktree(path: str, _depth: int = 0) -> bool:
    """True when `path` is a linked worktree of a repo (its git dir is not its common dir), or a submodule of one."""
    gd = _git(path, "rev-parse", "--path-format=absolute", "--git-dir")
    common = _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if gd and common and os.path.realpath(gd) != os.path.realpath(common):
        return True
    sup = _git(path, "rev-parse", "--show-superproject-working-tree") if _depth < 4 else ""
    return bool(sup) and linked_worktree(sup, _depth + 1)


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
