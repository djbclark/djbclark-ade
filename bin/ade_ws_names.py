"""Paseo window (workspace) display names: `<KIND> <repo-name> (<current work>)`, concise tab names, and structured window registry helpers.

Operator ruling 2026-11-25 (docs/workspace-layout.md): display names of workspaces, windows and tabs are human-facing UI labels ONLY —
keep their beginnings clear and up to date (`LEAD <repo> (<work>)`, `WORKER <repo> (<work>)`, `OTHER <repo> (<work>)`,
`worker <slice> [wt: ...]`), and NEVER use display names as a resource for metadata exchange between agents because a human may rename
any workspace, window or tab at any time. Authoritative machine metadata lives in structured Paseo agent labels (`ade.lead`, `ade.box`,
`ade.repo`, `ade.placement`, `ade.role`, `ade.chain`, `ade.retired`, `slice`, ...) and durable state records
(`$ADE_WORKER_RUN_STATE/<lead>.windows.json`, `self-session/handoff-*.json`).

Operator ruling 2026-11-14: per lead and repo at most three windows ("boxes"), named `<KIND> <repo> (<work>)`, KIND one of LEAD,
WORKER or OTHER. The 2026-11-13 kinds MAIN, WORKERS and USER are still recognised by `parse` for display-name migration (`Name.box`
maps them onto LEAD, WORKER and OTHER); `build` only makes the current kinds.

Importable (no side effects): `build`, `parse`, `parse_legacy`, `migrated_name`, `current_name`, `repo_of`, `normalize_work`,
`tab_name`, `read_window_registry`, `write_window_registry`, `all_registered_windows`, `KINDS`, `LEGACY_KINDS`, `BOX_OF`,
`NAME_LIMIT`, `WKS_RE`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import NamedTuple

KINDS = ("LEAD", "WORKER", "OTHER")
LEGACY_KINDS = ("MAIN", "WORKERS", "USER")  # the 2026-11-13 names of the same three boxes
BOX_OF = {"LEAD": "LEAD", "WORKER": "WORKER", "OTHER": "OTHER", "MAIN": "LEAD", "WORKERS": "WORKER", "USER": "OTHER"}
NAME_LIMIT = 100  # docs/workspace-layout.md: keep a window or tab name under ~100 characters
MAX_REGISTRY_BYTES = 1_048_576  # bounded regular-file read for window registries
REPO_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
UUID_PAT = re.compile(UUID_RE)
WKS_RE = re.compile(r"wks_[A-Za-z0-9]+")
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


def tab_name(box: str, slice_name: str, lead: str | None = None, worktree: str | None = None) -> str:
    """Concise, human-understandable tab name: `worker <slice>` (or `other <slice>` in the OTHER box), with
    ` [wt: <worktree dir basename>]` when the launch names a worktree.

    Operator ruling 2026-11-25: lead ownership lives in the structured `ade.lead` label, never in the display tab name;
    the optional `lead` parameter is accepted for call-site compatibility and ignored. The worktree part is a display hint,
    so a name over NAME_LIMIT shortens it (with `~`) rather than failing."""
    _ = lead  # ownership is carried by --label ade.lead=<lead>, not the tab title
    base = f"{TAB_PREFIX[box]} {slice_name}"
    if not worktree:
        return base
    d = os.path.basename(os.path.realpath(worktree).rstrip("/")) or worktree
    d = "".join(c for c in d if c.isprintable() and c not in "[]\n")
    room = NAME_LIMIT - len(base) - len(" [wt: ]")
    if not d or room < 1:
        return base
    return f"{base} [wt: {d if len(d) <= room else d[:room - 1] + '~'}]"


def _read_regular_file(path: Path, *, max_bytes: int = MAX_REGISTRY_BYTES, anchor_dir: Path | None = None) -> str:
    """Bounded regular-file read (no symlinks, no FIFOs/devices/dirs, optional anchor dir)."""
    if anchor_dir is not None:
        try:
            ast = os.lstat(anchor_dir)
        except FileNotFoundError:
            raise FileNotFoundError(str(path)) from None
        if not (stat.S_ISDIR(ast.st_mode) or (stat.S_ISLNK(ast.st_mode) and anchor_dir.is_dir())):
            raise OSError(f"state dir is not a directory: {anchor_dir}")
        anchor_real = Path(os.path.realpath(anchor_dir))
        parent_real = Path(os.path.realpath(path.parent))
        if parent_real != anchor_real:
            raise ValueError(f"registry path {path} escapes anchor directory {anchor_dir}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(os.fspath(path), flags)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ValueError(f"registry path is not a regular file: {path}")
        if st.st_size > max_bytes:
            raise ValueError(f"registry file exceeds {max_bytes} bytes: {path}")
        chunks: list[bytes] = []
        total = 0
        while True:
            buf = os.read(fd, min(65536, max_bytes - total + 1))
            if not buf:
                break
            total += len(buf)
            if total > max_bytes:
                raise ValueError(f"registry file exceeds {max_bytes} bytes: {path}")
            chunks.append(buf)
    finally:
        os.close(fd)
    try:
        return b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"registry file is not valid UTF-8: {path}") from exc


def normalize_window_entry(wks: str, raw: object) -> dict:
    """Validate and normalize one structured window metadata record.

    Raises ValueError on malformed authority (non-dict, mismatched windowId, invalid explicit box,
    or invalid typed metadata fields) so mutators fail closed rather than degrading to display titles.
    """
    if not isinstance(wks, str) or not WKS_RE.fullmatch(wks):
        raise ValueError(f"bad window id: {wks!r}")
    if not isinstance(raw, dict):
        raise ValueError(f"bad entry for {wks}")
    out: dict[str, str] = {"windowId": wks}
    if "windowId" in raw:
        if raw["windowId"] != wks:
            raise ValueError(f"mismatched windowId for {wks}: {raw['windowId']!r}")
    if "box" in raw:
        raw_box = raw["box"]
        if not isinstance(raw_box, str) or "\n" in raw_box or "\r" in raw_box or raw_box.strip().upper() not in BOX_OF:
            raise ValueError(f"invalid box for {wks}: {raw_box!r}")
        out["box"] = BOX_OF[raw_box.strip().upper()]
    if "repo" in raw:
        raw_repo = raw["repo"]
        if not isinstance(raw_repo, str) or "\n" in raw_repo or "\r" in raw_repo or not REPO_RE.fullmatch(raw_repo.strip()):
            raise ValueError(f"invalid repo for {wks}: {raw_repo!r}")
        out["repo"] = raw_repo.strip()
    if "lead" in raw:
        raw_lead = raw["lead"]
        if not isinstance(raw_lead, str) or "\n" in raw_lead or "\r" in raw_lead or not UUID_PAT.fullmatch(raw_lead.strip()):
            raise ValueError(f"invalid lead for {wks}: {raw_lead!r}")
        out["lead"] = raw_lead.strip()
    for key in ("cwd", "work"):
        if key in raw:
            val = raw[key]
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"invalid {key} for {wks}: {val!r}")
            out[key] = val
    return out


def read_window_registry(path: Path, *, anchor_dir: Path | None = None) -> tuple[set[str], dict[str, dict]]:
    """Read `<lead>.windows.json` -> `(window_ids, entries)`.

    Older records with only `{"windows": [...]}` (no `"entries"` key) load cleanly with empty `entries`.
    Corrupt JSON, symlinks/FIFOs, an explicit `"entries": null`, orphan entries absent from `"windows"`,
    or invalid explicit field values raise ValueError/OSError (callers fail closed).
    """
    try:
        text = _read_regular_file(path, anchor_dir=anchor_dir)
    except FileNotFoundError:
        return set(), {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("registry root must be an object")
    if "windows" not in data:
        raise ValueError("missing windows list")
    ids = data["windows"]
    if not isinstance(ids, list) or not all(isinstance(i, str) and WKS_RE.fullmatch(i) for i in ids):
        raise ValueError("bad window id")
    id_set = set(ids)
    if "entries" not in data:
        return id_set, {}
    raw_entries = data["entries"]
    if not isinstance(raw_entries, dict):
        raise ValueError("bad entries map")
    entries: dict[str, dict] = {}
    for wks, raw in raw_entries.items():
        if not isinstance(wks, str) or not WKS_RE.fullmatch(wks) or wks not in id_set:
            raise ValueError(f"entry {wks!r} is not in windows list")
        entries[wks] = normalize_window_entry(wks, raw)
    return id_set, entries


def write_window_registry(path: Path, ids: set[str], entries: dict[str, dict] | None = None) -> None:
    """Atomically write `<lead>.windows.json` with both `"windows"` (backward compatible) and structured `"entries"`."""
    if not all(isinstance(i, str) and WKS_RE.fullmatch(i) for i in ids):
        raise ValueError("bad window id")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {"windows": sorted(ids)}
    if entries:
        clean_entries = {w: normalize_window_entry(w, entries[w]) for w in sorted(ids) if w in entries and entries[w]}
        if clean_entries:
            payload["entries"] = clean_entries
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def default_worker_run_state_dir() -> Path:
    return Path(os.environ.get("ADE_WORKER_RUN_STATE") or Path.home() / ".local/state/ade/worker-run")


def all_registered_windows(state_dir: Path | None = None) -> dict[str, dict]:
    """Best-effort map of `workspaceId -> structured metadata` across all `<lead>.windows.json` files.

    Used by read-only classifiers (such as `ade-pin-workspaces`) so a human-renamed WORKER or OTHER box keeps
    its structured classification. Unreadable or malformed files are skipped (callers that mutate use
    `read_window_registry` directly and fail closed).
    """
    base = state_dir or default_worker_run_state_dir()
    if not base.is_dir():
        return {}
    out: dict[str, dict] = {}
    for path in sorted(base.glob("*.windows.json")):
        owner = path.name[:-len(".windows.json")]
        if not UUID_PAT.fullmatch(owner):
            continue
        try:
            ids, entries = read_window_registry(path, anchor_dir=base)
        except (OSError, ValueError, KeyError, TypeError):
            continue
        for wks in ids:
            meta = dict(entries.get(wks) or {"windowId": wks})
            meta.setdefault("lead", owner)
            out.setdefault(wks, meta)
    return out


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
