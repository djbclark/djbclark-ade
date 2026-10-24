#!/usr/bin/env python3
"""ade_claims: the workspace claim library and the git-guard rules (isolation slice W1, 2026-10-24).

One claim per workspace (a cow pasture or a linked worktree): who owns it, which branch, which base.
Design: design-isolation-report.md 3.4 (schema), 3.5.4 (guard), 4.2.1 (gate). `bin/ade-git-guard` is
the bash front door; it runs `ade_claims.py guard -- GIT_ARGS...` only for a git call that is not
plainly read-only. W2 (cow-pasture), W3 (acp-dispatch), W4 (acp-run) and W5 (Claude hook) consume
this module, so the names below are the contract.

THIS IS A SEATBELT, NOT A SANDBOX (design 5.7). It stops an agent's accidental or careless git; it does not
stop one that works at it. Out of reach by design: an absolute path to the real git, unsetting
ACP_RUN_AGENT/ADE_CLAIM_ID, another agent's ADE_CLAIM_ID, editing the claim registry (same uid), and
EVERYTHING GIT ITSELF SPAWNS (hooks, `bisect run`, `submodule foreach`, pagers, core.fsmonitor, diff.external,
core.sshCommand, `fetch --upload-pack`, and any `git` a `!` alias runs), because git puts its own exec-path first
on the PATH of its children, so those children reach the real git, not the shim.

Claim file, `<state>/claims/<id>.json` (state = $ADE_STATE_DIR, default ~/.local/state/ade), JSON,
written atomically (temp file beside, then os.replace), every field read with .get:

    {"v": 1, "id": str, "path": str (realpath of the workspace root), "repo_origin": str,
     "branch": str, "base_sha": str,
     "owner": {"record": str|None, "session": str|None, "agent": str, "model": str},
     "lead": str|None, "allow": [ids], "role": "lead"|"worker"|"builder", "purpose": str,
     "created_at": ISO-8601 UTC, "created_by": str, "state": "active"|"released"|"merged",
     "released_at": ISO-8601 UTC|None, "inherited_dirt_patch": str|None}

`create_claim` (CLI `new`) is exclusive: it refuses an existing id (ClaimExists, exit 3) and a path that
already has another owner's active claim (PathClaimed, exit 4). `write_claim` overwrites (update paths only).

Pointer: `<git-dir>/ade-claim` holds the claim id (git-dir is per-worktree, so a linked worktree has
its own; the file is never tracked). cow clones `.git`, so a pasture copied from a claimed checkout
inherits its source's pointer: `find_claim` therefore trusts a pointer only when the claim's `path`
is this workspace (compared with os.path.samefile, so a differently cased path on APFS still matches),
and otherwise falls back to a registry scan by path. `write_pointer` overwrites.

Who is "mine" (`is_mine`): the caller identity (ADE_CLAIM_ID, else a harness session id) equals the
claim id, owner.record, owner.session, or is in `allow`. `lead` is NOT implied: a lead that should
write in a worker's workspace or push its branch goes into `allow`.

Guard rules (agents only: ACP_RUN_AGENT=1 or ADE_CLAIM_ID set; a human shell is never touched; the design's
other markers CLAUDECODE/OMPCODE/CODEX_* are NOT used: interactive Claude is covered by `check`, W5):
  1. A workspace with an ACTIVE claim that is not mine: git is read-only (READONLY set plus the read forms of
     branch/config/worktree/remote/tag/stash/reflog/submodule). A "read-only" command that writes a file
     (`--output`, format-patch -o, archive -o, grep -O) is not read-only there.
  2. A workspace with no active claim (shared or primary checkout): refuse stash (except list/show),
     reset --hard|--merge|--keep, checkout -f|-p|--|<path>|<2+ args>, restore without --staged, switch
     -f|--discard-changes, clean unless -n/-i, rm -f, commit -a, add -A/-u/--all/--update with no pathspec
     or add ., pull|rebase|merge --autostash (also -c or repo config rebase/merge.autoStash), rebase -x,
     and `!` aliases. Long options match as git does: any unique prefix (`--har`) counts.
  3. A linked worktree of any owner: stash, rebase -x and `!` aliases are refused (refs/stash is shared).
  4. push: refused when a destination branch has an active claim that is not mine (any workspace). The
     destination of a bare `git push` comes from `git push --dry-run --porcelain` (config included); a
     destination that cannot be resolved is refused.
  5. The TARGET counts, not only the cwd: `worktree remove|move|prune`, `branch -d|-D|-m|-f`, `update-ref` and
     an output file are checked against the claim of the workspace they hit; GIT_WORK_TREE/--work-tree
     selects that workspace too; `worktree remove --force` needs ownership of the target.
  6. In my own claimed workspace everything else is allowed.
Refusal = exit 77 (EX_NOPERM), a message naming the owner and the safe alternative, one JSON line in
`<state>/guard.log` (option NAMES only, no values: no URL credentials, no messages).
Operator override: ACP_OPERATOR_APPROVED containing `git-guard` allows the call and logs it (design 5.6's
ADE_GIT_GUARD_BYPASS was not built; this is the convention bin/acp-dispatch already uses).
git's own hooks (GIT_INDEX_FILE set) and pre-commit (PRE_COMMIT set) are never refused: their `git
checkout -- .` stash dance is git's, not the agent's.

`check CMD` reads a shell command string: newlines, `;` `&&` `||` `|` `( )`, `$(...)`, backticks, double
quotes, `bash -lc '...'`, `eval`, `watch`, env/sudo/nice/timeout/xargs wrappers, inline GIT_DIR=/GIT_WORK_TREE=,
`cd X &&`. It FAILS CLOSED (exit 77, "spell it out") for a git call whose global options or subcommand are
unexpanded variables, a `cd`/`-C` into an unknown directory before a non-read-only call, or an unterminated
quote in a command that mentions git. Unquoted `echo git reset --hard` is judged as a git call (a false
refusal is cheaper than a miss); quoted text such as `echo 'git reset --hard'` is data.

CLI (also the bash-facing API; every subcommand exits 0 ok, 1 not found, 2 usage, 3 id exists, 4 path
owned by another owner's active claim, 77 refused):
    ade_claims.py new --id ID --path DIR --branch B --base-sha S [--repo-origin U]
        [--owner-record R] [--owner-session S] [--owner-agent A] [--owner-model M] [--lead L]
        [--allow ID]... [--role lead|worker|builder] [--purpose T] [--created-by X]
        [--inherited-dirt-patch P] [--no-pointer]     writes the claim and the pointer; prints the claim file
    ade_claims.py show ID [--field F]       print the claim JSON (or one field)
    ade_claims.py find [DIR]                print the active claim of the workspace holding DIR (cwd)
    ade_claims.py list [--state S] [--json] one line per claim (or a JSON array)
    ade_claims.py set-state ID active|released|merged
    ade_claims.py guard -- GIT_ARGS...      decide one git call (what ade-git-guard runs)
    ade_claims.py check CMD [--cwd DIR]     decide every git call inside a shell command (Claude hook)
"""
from __future__ import annotations

# argparse, subprocess and tempfile are imported where used: the `guard` path of a plain `git add`/`commit`
# runs once per git call of an agent and must start fast.
import contextlib
import dataclasses
import fcntl
import json
import os
import re
import shlex
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional, Sequence

SCHEMA_VERSION = 1
EXIT_REFUSED = 77
EXIT_EXISTS = 3
EXIT_PATH_OWNED = 4
STATES = ("active", "released", "merged")
ROLES = ("lead", "worker", "builder")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
IDENT_ENV = ("ADE_CLAIM_ID", "CLAUDE_CODE_SESSION_ID", "PASEO_AGENT_ID")
OVERRIDE = "git-guard"  # ACP_OPERATOR_APPROVED value, the convention of bin/acp-dispatch


# --------------------------------------------------------------------------------------------
# paths and atomic IO
# --------------------------------------------------------------------------------------------

def state_dir() -> Path:
    return Path(os.environ.get("ADE_STATE_DIR") or (Path.home() / ".local/state/ade"))


def claims_dir() -> Path:
    return state_dir() / "claims"


def guard_log_path() -> Path:
    return state_dir() / "guard.log"


def valid_id(claim_id: Any) -> bool:
    return isinstance(claim_id, str) and bool(ID_RE.match(claim_id))


def claim_file(claim_id: str) -> Path:
    if not valid_id(claim_id):
        raise ValueError(f"invalid claim id {claim_id!r}: use letters, digits, . _ - (max 128)")
    return claims_dir() / f"{claim_id}.json"


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _write_temp(path: Path, text: str) -> str:
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return tmp


def atomic_write(path: Path, text: str) -> None:
    """Temp file beside the target, fsync, os.replace: a reader sees the old or the new file."""
    tmp = _write_temp(path, text)
    try:
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def _claims_lock() -> Iterator[None]:
    """Serialises create_claim and update_claim; readers need no lock."""
    claims_dir().mkdir(parents=True, exist_ok=True)
    with open(claims_dir() / ".lock", "a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


# --------------------------------------------------------------------------------------------
# claim records
# --------------------------------------------------------------------------------------------

class ClaimExists(Exception):
    """create_claim: a claim with this id already exists (CLI exit 3)."""


class PathClaimed(Exception):
    """create_claim: the path already has another owner's active claim (CLI exit 4)."""


def make_claim(*, id: str, path: str | os.PathLike[str], branch: str, base_sha: str, repo_origin: str = "",
               owner_record: Optional[str] = None, owner_session: Optional[str] = None,
               owner_agent: str = "", owner_model: str = "", lead: Optional[str] = None,
               allow: Iterable[str] = (), role: str = "worker", purpose: str = "", created_by: str = "",
               inherited_dirt_patch: Optional[str] = None) -> dict[str, Any]:
    """A complete, schema-v1 claim dict (state active). Does not write it."""
    if not valid_id(id):
        raise ValueError(f"invalid claim id {id!r}")
    if role not in ROLES:
        raise ValueError(f"invalid role {role!r}; one of {', '.join(ROLES)}")
    allow_ids = [a for a in allow]
    for a in allow_ids:
        if not valid_id(a):
            raise ValueError(f"invalid id {a!r} in allow")
    return {
        "v": SCHEMA_VERSION, "id": id, "path": str(Path(path).resolve()), "repo_origin": repo_origin,
        "branch": branch, "base_sha": base_sha,
        "owner": {"record": owner_record, "session": owner_session, "agent": owner_agent, "model": owner_model},
        "lead": lead, "allow": allow_ids, "role": role, "purpose": purpose,
        "created_at": utc_now(), "created_by": created_by, "state": "active", "released_at": None,
        "inherited_dirt_patch": inherited_dirt_patch,
    }


def write_claim(claim: dict[str, Any]) -> Path:
    """Atomically OVERWRITE `claim`'s registry file (no exclusivity: use create_claim to make a new claim)."""
    target = claim_file(str(claim.get("id") or ""))
    atomic_write(target, json.dumps(claim, indent=2, sort_keys=True) + "\n")
    return target


def _owner_keys(claim: dict[str, Any]) -> set[str]:
    owner = claim.get("owner") if isinstance(claim.get("owner"), dict) else {}
    return {k for k in (owner.get("record"), owner.get("session")) if isinstance(k, str) and k}


def create_claim(claim: dict[str, Any]) -> Path:
    """Create a NEW claim exclusively, under the registry lock. Raises ClaimExists when the id is taken and
    PathClaimed when `claim["path"]` already has another owner's active claim (two active claims on one path
    would let the newer one take the workspace over). The file appears atomically and never replaces another."""
    target = claim_file(str(claim.get("id") or ""))
    with _claims_lock():
        if target.exists():
            raise ClaimExists(f"claim {claim.get('id')!r} already exists ({target})")
        mine = _owner_keys(claim)
        for c in list_claims("active"):
            if _same_path(c.get("path"), Path(str(claim.get("path") or ""))) and not (mine and mine & _owner_keys(c)):
                raise PathClaimed(f"{claim.get('path')} is already claimed by {c.get('id')!r} ({owner_label(c)})")
        tmp = _write_temp(target, json.dumps(claim, indent=2, sort_keys=True) + "\n")
        try:
            os.link(tmp, target)  # fails with EEXIST rather than replacing
        except FileExistsError:
            raise ClaimExists(f"claim {claim.get('id')!r} already exists ({target})") from None
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
    return target


def read_claim(claim_id: str) -> Optional[dict[str, Any]]:
    """The claim dict, or None when the id is invalid, the file is missing, unreadable, hostile (deeply
    nested JSON raises RecursionError) or not a JSON object."""
    if not valid_id(claim_id):
        return None
    try:
        data = json.loads((claims_dir() / f"{claim_id}.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - one bad file must not blind the guard to every other claim
        return None
    return data if isinstance(data, dict) else None


def list_claims(state: Optional[str] = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        names = sorted(p for p in claims_dir().iterdir() if p.suffix == ".json" and not p.name.startswith("."))
    except OSError:
        return out
    for p in names:
        c = read_claim(p.stem)
        if c is not None and (state is None or c.get("state") == state):
            out.append(c)
    return out


def update_claim(claim_id: str, **fields: Any) -> Optional[dict[str, Any]]:
    """Read-modify-write under the registry lock. None when the claim does not exist."""
    with _claims_lock():
        c = read_claim(claim_id)
        if c is None:
            return None
        c.update(fields)
        write_claim(c)
        return c


def set_state(claim_id: str, state: str) -> Optional[dict[str, Any]]:
    """active|released|merged; released and merged stamp released_at, active clears it."""
    if state not in STATES:
        raise ValueError(f"invalid state {state!r}; one of {', '.join(STATES)}")
    return update_claim(claim_id, state=state, released_at=None if state == "active" else utc_now())


def claim_state_active(claim: Optional[dict[str, Any]]) -> bool:
    return bool(claim) and (claim or {}).get("state", "active") == "active"


def owner_ids(claim: dict[str, Any]) -> set[str]:
    """Every id that is the claim's owner: its id, owner.record, owner.session."""
    ids = {claim.get("id")} | _owner_keys(claim)
    return {i for i in ids if isinstance(i, str) and i}


def is_mine(claim: dict[str, Any], ident: Optional[str]) -> bool:
    if not ident:
        return False
    allow = claim.get("allow") if isinstance(claim.get("allow"), list) else []
    return ident in owner_ids(claim) or ident in allow


def owner_label(claim: dict[str, Any]) -> str:
    owner = claim.get("owner") if isinstance(claim.get("owner"), dict) else {}
    who = " ".join(x for x in (owner.get("agent"), owner.get("model")) if x)
    ref = owner.get("record") or owner.get("session") or claim.get("id") or "?"
    return f"{who} ({ref})" if who else str(ref)


def caller_ident(env: Optional[dict[str, str]] = None) -> Optional[str]:
    """ADE_CLAIM_ID first (acp-dispatch exports it); harness ids leak from a lead into its slices, so they
    are only the fallback for an interactive session (design 3.4.3)."""
    env = os.environ if env is None else env
    for name in IDENT_ENV:
        v = env.get(name)
        if v:
            return v
    return None


def is_agent_env(env: Optional[dict[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    return env.get("ACP_RUN_AGENT", "") not in ("", "0") or bool(env.get("ADE_CLAIM_ID"))


def normalize_origin(url: str) -> str:
    """https://h/a/b.git, ssh://git@h/a/b and git@h:a/b.git all become h/a/b (lower case)."""
    u = (url or "").strip()
    u = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", u)
    u = re.sub(r"^[^@/]*@", "", u)
    u = re.sub(r"^([^/:]+):(?!\d+/)", r"\1/", u)
    return re.sub(r"(\.git)?/*$", "", u).lower()


# --------------------------------------------------------------------------------------------
# workspace <-> claim
# --------------------------------------------------------------------------------------------

@dataclasses.dataclass
class Workspace:
    root: Path          # working tree root
    gitdir: Path        # per-worktree git dir (holds ade-claim, HEAD, index)
    linked: bool        # a linked worktree (has `commondir`): refs/stash is shared with its siblings

    @property
    def pointer(self) -> Path:
        return self.gitdir / "ade-claim"


def _same_path(a: Any, b: Any) -> bool:
    """True when two paths are one file: samefile (st_dev, st_ino) first, so a differently cased path on a
    case-insensitive volume matches; a path that does not exist falls back to normalised real paths."""
    if not isinstance(a, (str, os.PathLike)) or not isinstance(b, (str, os.PathLike)) or not str(a) or not str(b):
        return False
    try:
        return os.path.samefile(a, b)
    except OSError:
        pass
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except OSError:
        return False


def find_workspace(start: str | os.PathLike[str], gitdir_override: Optional[str] = None) -> Optional[Workspace]:
    """Walk up from `start` to the first `.git` (directory, or a `gitdir:` file of a linked worktree)."""
    try:
        p = Path(start).resolve()
    except OSError:
        return None
    if gitdir_override:
        g = Path(gitdir_override)
        g = (p / g) if not g.is_absolute() else g
        g = g.resolve()
        return Workspace(g.parent if g.name == ".git" else p, g, (g / "commondir").exists())
    for d in (p, *p.parents):
        g = d / ".git"
        try:
            if g.is_dir():
                return Workspace(d, g, (g / "commondir").exists())
            if g.is_file():
                line = g.read_text(encoding="utf-8", errors="replace").strip()
                if line.startswith("gitdir:"):
                    gd = Path(line[len("gitdir:"):].strip())
                    gd = (gd if gd.is_absolute() else d / gd).resolve()
                    return Workspace(d, gd, (gd / "commondir").exists())
        except OSError:
            continue
    return None


def read_pointer(ws: Workspace) -> Optional[str]:
    try:
        v = ws.pointer.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return v if valid_id(v) else None


def write_pointer(workdir: str | os.PathLike[str], claim_id: str) -> Path:
    """Write `<git-dir>/ade-claim` for the workspace holding `workdir` (overwrites an inherited one)."""
    ws = find_workspace(workdir)
    if ws is None:
        raise ValueError(f"{workdir} is not inside a git workspace")
    if not valid_id(claim_id):
        raise ValueError(f"invalid claim id {claim_id!r}")
    atomic_write(ws.pointer, claim_id + "\n")
    return ws.pointer


def find_claim(ws: Workspace, active_only: bool = True) -> Optional[dict[str, Any]]:
    """The claim of workspace `ws`. The pointer is trusted only when the claim's path IS this workspace
    (cow copies `.git`, pointer included, into a new pasture); otherwise the registry is scanned by path."""
    pid = read_pointer(ws)
    cands: list[dict[str, Any]] = []
    if pid:
        c = read_claim(pid)
        if c is not None and _same_path(c.get("path"), ws.root):
            cands.append(c)
    if not cands:
        cands = [c for c in list_claims() if _same_path(c.get("path"), ws.root)]
    if active_only:
        cands = [c for c in cands if claim_state_active(c)]
    if not cands:
        return None
    cands.sort(key=lambda c: str(c.get("created_at") or ""))
    return cands[-1]


def claim_at(path: str | os.PathLike[str]) -> Optional[dict[str, Any]]:
    """The active claim of the workspace whose ROOT is `path` (even when the directory is already gone)."""
    p = Path(path)
    if p.exists():
        ws = find_workspace(p)
        if ws is not None and _same_path(ws.root, p):
            return find_claim(ws)
    for c in list_claims("active"):
        if _same_path(c.get("path"), p):
            return c
    return None


def claims_for_branch(branch: str, origin: str = "") -> list[dict[str, Any]]:
    """Active claims on `branch`; with `origin`, only claims of that repository (or of unknown origin)."""
    want = normalize_origin(origin)
    out = []
    for c in list_claims("active"):
        if c.get("branch") != branch:
            continue
        co = normalize_origin(str(c.get("repo_origin") or ""))
        if want and co and co != want:
            continue
        out.append(c)
    return out


def repo_worktrees(ws: Workspace) -> list[tuple[Path, Path]]:
    """(root, git-dir) of the main worktree and every registered linked worktree of ws's repository."""
    common = ws.gitdir
    try:
        common = (ws.gitdir / (ws.gitdir / "commondir").read_text().strip()).resolve()
    except OSError:
        pass
    out: list[tuple[Path, Path]] = []
    if common.name == ".git":
        out.append((common.parent, common))
    try:
        entries = sorted((common / "worktrees").iterdir())
    except OSError:
        entries = []
    for e in entries:
        try:
            out.append((Path((e / "gitdir").read_text().strip()).parent, e))
        except OSError:
            continue
    return out


def _head_branch(gitdir: Path) -> str:
    try:
        head = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return head[len("ref: refs/heads/"):] if head.startswith("ref: refs/heads/") else ""


# --------------------------------------------------------------------------------------------
# guard: argv parsing
# --------------------------------------------------------------------------------------------

READONLY = frozenset("""status diff log show ls-files ls-tree rev-parse cat-file blame grep fetch ls-remote describe
merge-base version help rev-list show-ref for-each-ref shortlog whatchanged diff-tree diff-index diff-files name-rev
check-ignore check-attr check-ref-format var cherry range-diff count-objects show-branch merge-tree archive
format-patch verify-commit verify-tag""".split())
# The write commands the rules know by name; anything else is looked up as an alias first.
KNOWN_WRITE = frozenset("""commit add rm mv merge rebase pull push cherry-pick revert am apply checkout switch restore reset
clean stash tag branch config remote worktree init clone submodule gc prune update-ref symbolic-ref notes bisect
reflog sparse-checkout maintenance bundle replace filter-branch""".split())
GLOBAL_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env"}
GLOBAL_FLAG = {"--no-pager", "-p", "--paginate", "--no-optional-locks", "--no-replace-objects",
               "--literal-pathspecs", "--glob-pathspecs", "--noglob-pathspecs", "--icase-pathspecs", "--bare",
               "--no-lazy-fetch", "--no-advice"}


@dataclasses.dataclass
class GitCall:
    cwd: str
    gitdir: Optional[str]
    sub: str
    args: list[str]
    config: dict[str, str]
    worktree: Optional[str] = None   # --work-tree / GIT_WORK_TREE: the tree whose files change
    nglobal: int = 0                 # index of the subcommand in the original argv

    def display(self) -> str:
        return f"git {self.sub}".rstrip()


def parse_git_argv(argv: Sequence[str], cwd: str, env: Optional[dict[str, str]] = None) -> GitCall:
    """Split git's global options from `<subcommand> <args>`; -C is cumulative, -c and --config-env collected,
    --work-tree/--git-dir (and GIT_WORK_TREE/GIT_DIR from `env`) recorded."""
    env = os.environ if env is None else env
    cur = cwd
    gitdir: Optional[str] = os.path.join(cwd, env["GIT_DIR"]) if env.get("GIT_DIR") else None
    worktree: Optional[str] = os.path.join(cwd, env["GIT_WORK_TREE"]) if env.get("GIT_WORK_TREE") else None
    config: dict[str, str] = {}
    i, n = 0, len(argv)
    while i < n:
        a = argv[i]
        if a == "-C" and i + 1 < n:
            cur = os.path.join(cur, argv[i + 1])
            i += 2
        elif a == "-c" and i + 1 < n:
            k, _, v = argv[i + 1].partition("=")
            config[k.lower()] = v
            i += 2
        elif a.startswith("-c") and len(a) > 2 and a[2] != "-":
            k, _, v = a[2:].partition("=")
            config[k.lower()] = v
            i += 1
        elif a.startswith("-C") and len(a) > 2 and a[2] != "-":
            cur = os.path.join(cur, a[2:])
            i += 1
        elif a in ("--git-dir", "--work-tree") and i + 1 < n:
            if a == "--git-dir":
                gitdir = os.path.join(cur, argv[i + 1])
            else:
                worktree = os.path.join(cur, argv[i + 1])
            i += 2
        elif a.startswith("--git-dir="):
            gitdir = os.path.join(cur, a.split("=", 1)[1])
            i += 1
        elif a.startswith("--work-tree="):
            worktree = os.path.join(cur, a.split("=", 1)[1])
            i += 1
        elif a == "--config-env" and i + 1 < n or a.startswith("--config-env="):
            spec = argv[i + 1] if a == "--config-env" else a.split("=", 1)[1]
            k, _, var = spec.partition("=")
            config[k.lower()] = env.get(var, "")
            i += 2 if a == "--config-env" else 1
        elif a in GLOBAL_VALUE and i + 1 < n:
            i += 2
        elif a in GLOBAL_FLAG or a.startswith("--exec-path") or \
                a in ("--version", "--help", "-h", "--html-path", "--man-path", "--info-path"):
            i += 1
        elif a.startswith("-"):
            i += 1  # unknown global flag: ignore it, never mistake it for the subcommand
        else:
            break
    sub = argv[i] if i < n else ""
    return GitCall(cur, gitdir, sub, list(argv[i + 1:]), config, worktree, i)


@dataclasses.dataclass
class Scan:
    shorts: set[str]
    longs: set[str]     # expanded: an abbreviated option contributes the option(s) it may stand for
    pos: list[str]
    after: list[str]    # everything after a bare `--`
    seq: list[set[str]]  # the expanded long options in command-line order (later wins for --x/--no-x)


def expand_long(name: str, danger: Iterable[str] = (), table: Iterable[str] = ()) -> set[str]:
    """git accepts any unique prefix of a long option. The names a command-line `--name` may stand for:
    itself; every DANGER name it prefixes (fail closed: an ambiguous prefix counts as the dangerous option);
    and the one `table` option it prefixes when that is unique (so `--stag` is `--staged`, `--dry` is
    `--dry-run`, but `--s` stays ambiguous and never counts as a safe option)."""
    names = {name}
    table = tuple(table)
    if name in table or name in tuple(danger):
        return names
    names.update(d for d in danger if d.startswith(name))
    cands = [t for t in table if t.startswith(name)]
    if len(cands) == 1:
        names.add(cands[0])
    return names


def scan(args: Sequence[str], value_short: str = "", value_long: Iterable[str] = (), attached_short: str = "",
         danger: Iterable[str] = (), table: Iterable[str] = ()) -> Scan:
    """Classify option tokens. A short in `value_short` takes the rest of its cluster or the next token
    (so `-m "text -a"` never reads as -a); one in `attached_short` takes only an attached value. Long names
    are expanded with expand_long (`danger`, `table`)."""
    vl = set(value_long)
    danger = tuple(danger)
    table = tuple(table)
    shorts: set[str] = set()
    longs: set[str] = set()
    seq: list[set[str]] = []
    pos: list[str] = []
    after: list[str] = []
    i, n = 0, len(args)
    while i < n:
        a = args[i]
        if a == "--":
            after = list(args[i + 1:])
            break
        if a.startswith("--"):
            name, eq, _ = a[2:].partition("=")
            names = expand_long(name, danger, table)
            longs |= names
            seq.append(names)
            if not eq and names & vl:
                i += 1
        elif a.startswith("-") and len(a) > 1:
            cl = a[1:]
            for j, ch in enumerate(cl):
                if ch in value_short:
                    if j == len(cl) - 1:
                        i += 1
                    break
                if ch in attached_short:
                    break
                shorts.add(ch)
        else:
            pos.append(a)
        i += 1
    return Scan(shorts, longs, pos, after, seq)


def _last_wins(s: Scan, on: str, off: str) -> bool:
    """True when `--on` is in effect: it occurs and no `--off` follows its last occurrence."""
    state = False
    for names in s.seq:
        if on in names:
            state = True
        elif off in names:
            state = False
    return state


def _truthy(v: Optional[str]) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


# option tables for the "safe" names a rule lets through (a unique prefix of one counts as it)
T_CLEAN = {"dry-run", "exclude", "force", "interactive", "quiet"}
T_RESTORE = {"conflict", "ignore-skip-worktree-bits", "ignore-unmerged", "inter-hunk-context", "merge", "ours", "overlay",
             "no-overlay", "patch", "pathspec-file-nul", "pathspec-from-file", "progress", "no-progress", "quiet",
             "recurse-submodules", "no-recurse-submodules", "source", "staged", "theirs", "unified", "worktree"}
T_RM = {"cached", "dry-run", "force", "ignore-unmatch", "pathspec-file-nul", "pathspec-from-file", "quiet", "sparse"}
T_STASHING = {"abort", "all", "allow-unrelated-histories", "append", "apply", "autosquash", "autostash", "cleanup",
              "commit", "continue", "dry-run", "edit", "edit-todo", "empty", "exec", "ff", "ff-only", "file", "force",
              "force-rebase", "fork-point", "gpg-sign", "interactive", "keep-base", "log", "merge", "message",
              "no-autostash", "no-ff", "no-stat", "no-verify", "onto", "quiet", "quit", "rebase", "rebase-merges",
              "recurse-submodules", "reschedule-failed-exec", "root", "signoff", "skip", "squash", "stat",
              "strategy", "strategy-option", "summary", "tags", "update-refs", "verbose", "verify"}
D_WRITE_BRANCH = {"delete", "move", "copy", "set-upstream-to", "unset-upstream", "edit-description", "force",
                  "track", "no-track", "create-reflog", "set-upstream"}


# --------------------------------------------------------------------------------------------
# guard: classification
# --------------------------------------------------------------------------------------------

def output_targets(call: GitCall) -> Optional[list[str]]:
    """None when the call writes no file of its own choosing; else the file/dir paths it writes (may be
    empty when the path cannot be read from the arguments). `git log --output=f` truncates f."""
    sub, args = call.sub, call.args
    short = ""
    if sub in ("diff", "log", "show", "whatchanged", "diff-tree", "diff-index", "diff-files", "range-diff", "shortlog"):
        long_name = "output"
    elif sub == "format-patch":
        long_name, short = "output-directory", "o"
    elif sub == "archive":
        long_name, short = "output", "o"
    elif sub == "grep":
        long_name, short = "open-files-in-pager", "O"
    else:
        return None
    found: Optional[list[str]] = None
    i, n = 0, len(args)
    while i < n:
        a = args[i]
        if a == "--":
            break
        val: Optional[str] = None
        hit = False
        if a.startswith("--"):
            name, eq, v = a[2:].partition("=")
            if name and long_name.startswith(name):   # any prefix, as git parses it (inclusive: fail closed)
                hit = True
                val = v if eq else None
        elif short and len(a) > 1 and a[0] == "-" and a[1] == short:
            hit = True
            val = a[2:] or None
        if hit:
            if val is None and sub != "grep" and i + 1 < n:
                val = args[i + 1]
                i += 1
            found = (found or []) + ([val] if val else [])
        i += 1
    return found


def is_readonly(call: GitCall) -> bool:
    """True when this git call cannot change the repository or its working tree."""
    sub, args = call.sub, call.args
    if sub == "":
        return True
    if sub in READONLY:
        return output_targets(call) is None
    if sub == "branch":
        s = scan(args, value_long={"contains", "no-contains", "merged", "no-merged", "points-at", "format", "sort",
                                   "abbrev"}, danger=D_WRITE_BRANCH)
        if s.shorts & set("dDmMcCuft") or s.longs & D_WRITE_BRANCH:
            return False
        listing = s.shorts & set("lavr") or s.longs & {"list", "contains", "no-contains", "merged", "no-merged",
                                                       "points-at", "show-current", "all", "remotes", "verbose"}
        return not s.pos or bool(listing)
    if sub == "config":
        wr = {"add", "unset", "unset-all", "replace-all", "rename-section", "remove-section", "edit", "set"}
        rd = {"get", "get-all", "get-regexp", "list", "get-urlmatch", "get-color", "get-colorbool"}
        s = scan(args, value_short="f", value_long={"file", "blob", "type", "default"}, danger=wr)
        if s.shorts & {"e"} or s.longs & wr:
            return False
        if s.pos and s.pos[0] in ("set", "unset", "edit", "rename-section", "remove-section", "add"):
            return False
        if (s.pos and s.pos[0] in ("get", "list")) or s.shorts & {"l"} or s.longs & rd:
            return True
        return len(s.pos) < 2
    if sub == "worktree":
        return bool(args) and args[0] == "list"
    if sub == "remote":
        s = scan(args)
        return not s.pos or s.pos[0] in ("show", "get-url")
    if sub == "tag":
        wr = {"delete", "annotate", "sign", "force", "message", "file", "local-user"}
        ls = {"list", "contains", "no-contains", "merged", "no-merged", "points-at"}
        s = scan(args, value_short="umF", value_long={"contains", "no-contains", "merged", "no-merged", "points-at",
                                                       "format", "sort", "message", "file", "local-user"}, danger=wr)
        if s.shorts & set("dasf") or s.longs & wr:
            return False
        return not s.pos or bool(s.shorts & set("ln") or s.longs & ls)
    if sub == "stash":
        return bool(args) and args[0] in ("list", "show")
    if sub == "reflog":
        return not args or args[0] not in ("expire", "delete")
    if sub == "submodule":
        return bool(args) and args[0] in ("status", "summary")
    if sub == "symbolic-ref":
        s = scan(args)
        return len(s.pos) < 2 and "d" not in s.shorts
    return False


@dataclasses.dataclass
class Rule:
    name: str
    alt: str


def stash_rule(call: GitCall) -> Optional[Rule]:
    """`stash` (push, save, pop, apply, drop, clear...) except the read forms list and show."""
    if call.sub != "stash" or (call.args and call.args[0] in ("list", "show")):
        return None
    return Rule("stash", "commit to a WIP branch in your own workspace, or save `git diff > file`; "
                         "refs/stash is shared by every workspace of this repository")


def _rebase_exec_rule(call: GitCall) -> Optional[Rule]:
    if call.sub == "rebase":
        s = scan(call.args, value_short="sXC", value_long={"strategy", "strategy-option", "onto", "exec"},
                 danger={"exec"}, table=T_STASHING)
        if s.shorts & {"x"} or "exec" in s.longs:
            return Rule("rebase -x", "`git rebase <base>` without --exec; `rebase -x` runs a command that reaches "
                                     "the real git past this guard")
    return None


def _autostash(call: GitCall, root: Optional[Path]) -> bool:
    s = scan(call.args, value_short="sXmFxC", value_long={"strategy", "strategy-option", "onto", "exec", "message", "file"},
             danger={"autostash"}, table=T_STASHING)
    if _last_wins(s, "autostash", "no-autostash"):
        return True
    if any(k in call.config and _truthy(call.config[k]) for k in ("rebase.autostash", "merge.autostash")):
        return True
    if root is not None and not any(k in call.config for k in ("rebase.autostash", "merge.autostash")):
        out = _git_out(root, "config", "--get-regexp", r"^(rebase|merge)\.autostash$")
        return any(_truthy(line.split(None, 1)[1]) for line in out.splitlines() if len(line.split(None, 1)) == 2)
    return False


def _is_pathspec(arg: str, cwd: str) -> bool:
    return arg in (".", "./", ":/") or arg.startswith(":") or any(c in arg for c in "*?[") or \
        os.path.exists(os.path.join(cwd, arg))


def shared_destructive(call: GitCall, root: Optional[Path] = None) -> Optional[Rule]:
    """The destructive forms refused in a shared (no active claim) checkout."""
    sub, args = call.sub, call.args
    rule = stash_rule(call) or _rebase_exec_rule(call)
    if rule is not None:
        return rule
    if sub == "reset":
        s = scan(args, value_long={"source"}, danger={"hard", "merge", "keep"})
        if s.longs & {"hard", "merge", "keep"}:
            return Rule("reset --hard", "`git reset --soft`, or `git restore --staged <path>`; to discard work, "
                                        "do it in your own workspace")
    elif sub == "checkout":
        s = scan(args, value_short="bB", value_long={"orphan", "conflict", "pathspec-from-file"},
                 danger={"force", "patch"})
        if s.shorts & set("fp") or s.longs & {"force", "patch"} or s.after or len(s.pos) >= 2 or \
                any(_is_pathspec(p, call.cwd) for p in s.pos):
            return Rule("checkout <path>", "`git switch <branch>` to change branch; `git diff` to inspect; never "
                                           "overwrite paths in a shared checkout (`git checkout <file>` discards a "
                                           "peer's edit of it)")
    elif sub == "restore":
        s = scan(args, value_short="s", value_long={"source", "pathspec-from-file"}, danger={"worktree"}, table=T_RESTORE)
        if not (s.longs & {"staged"} or s.shorts & {"S"}) or s.longs & {"worktree"} or s.shorts & {"W"}:
            return Rule("restore", "`git restore --staged <path>` only unstages; to discard work, do it in your "
                                   "own workspace")
    elif sub == "switch":
        s = scan(args, value_short="cCt", value_long={"create", "force-create", "track", "orphan"},
                 danger={"force", "discard-changes"})
        if s.shorts & {"f"} or s.longs & {"force", "discard-changes"}:
            return Rule("switch -f", "`git switch <branch>` without -f, or commit first, in your own workspace")
    elif sub == "clean":
        s = scan(args, value_short="e", value_long={"exclude"}, table=T_CLEAN)
        if not (s.shorts & {"n", "i"} or s.longs & {"dry-run", "interactive"}):
            return Rule("clean", "`git clean -n` (dry run) and delete the named files yourself, in your own workspace")
    elif sub == "rm":
        s = scan(args, value_long={"pathspec-from-file"}, danger={"force"}, table=T_RM)
        if (s.shorts & {"f"} or s.longs & {"force"}) and not (s.shorts & {"n"} or s.longs & {"dry-run", "cached"}):
            return Rule("rm -f", "`git rm <path>` without -f (git then refuses a modified file), or `git rm --cached`")
    elif sub == "commit":
        s = scan(args, value_short="mFCct", attached_short="Su",
                 value_long={"message", "file", "author", "date", "reuse-message", "reedit-message", "fixup",
                             "squash", "template", "cleanup"}, danger={"all"})
        if s.shorts & {"a"} or s.longs & {"all"}:
            return Rule("commit -a", "`git add <explicit paths>` then `git commit`; -a would commit a peer's "
                                     "uncommitted hunks")
    elif sub == "add":
        s = scan(args, value_long={"pathspec-from-file", "chmod"}, danger={"all", "update"}, table={"no-all", "dry-run"})
        paths = s.pos + s.after
        sweep = (s.shorts & {"A", "u"} or s.longs & {"all", "update"}) and not paths
        if sweep or any(p in (".", "./", ":/", ":/.", ":(top)") for p in paths):
            return Rule("add -A/-u/.", "`git add <explicit paths>`; a sweep stages a peer's uncommitted hunks")
    elif sub in ("pull", "rebase", "merge"):
        if _autostash(call, root):
            return Rule("autostash", "`git pull --ff-only` (or `git fetch` then merge) from a clean tree in your own "
                                     "workspace; autostash hides a peer's edits")
    return None


FOREIGN_ALT = ("use read-only git here (status, diff, log, show, fetch); to edit, make your own workspace "
               "(`bin/cow-pasture create`, or `acp-dispatch --workspace auto`)")


@dataclasses.dataclass
class Decision:
    allowed: bool
    rule: str = ""
    message: str = ""
    claim_id: str = ""
    owner: str = ""
    override: bool = False
    detail: dict[str, Any] = dataclasses.field(default_factory=dict)


ALLOW = Decision(True)


def real_git(env: Optional[dict[str, str]] = None) -> str:
    """The real git: $ADE_REAL_GIT, else the first PATH entry whose `git` is not this guard, else /usr/bin/git."""
    env = os.environ if env is None else env
    if env.get("ADE_REAL_GIT"):
        return env["ADE_REAL_GIT"]
    for d in (env.get("PATH") or "").split(os.pathsep):
        cand = Path(d or ".") / "git"
        try:
            if cand.is_file() and os.access(cand, os.X_OK) and cand.resolve().name != "ade-git-guard":
                return str(cand)
        except OSError:
            continue
    return "/usr/bin/git"


def _run_git(args: Sequence[str], timeout: int = 10) -> tuple[int, str]:
    try:
        import subprocess
        r = subprocess.run([real_git(), *args], capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return r.returncode, r.stdout


def _git_out(root: Path, *args: str) -> str:
    rc, out = _run_git(["-C", str(root), *args])
    return out.strip() if rc == 0 else ""


def _globals(call: GitCall) -> list[str]:
    g = ["-C", call.cwd]
    for k, v in call.config.items():
        g += ["-c", f"{k}={v}"]
    if call.gitdir:
        g += ["--git-dir", call.gitdir]
    if call.worktree:
        g += ["--work-tree", call.worktree]
    return g


# --------------------------------------------------------------------------------------------
# guard: push destinations
# --------------------------------------------------------------------------------------------

def push_destinations(call: GitCall, ws: Optional[Workspace]) -> tuple[Optional[list[str]], str]:
    """(destination branch names or None when unresolvable, remote url) of a `git push` call. --all, --mirror
    and glob refspecs cover every local branch. With no refspec on the command line the destination comes from
    config (remote.<r>.push, push.default, branch.<b>.merge), so ask git: `push --dry-run --porcelain`, then
    `for-each-ref %(push)`; None when neither resolves."""
    s = scan(call.args, value_short="o", value_long={"repo", "push-option", "receive-pack", "exec"},
             danger={"all", "mirror", "branches"})
    pos = s.pos + s.after
    remote = pos[0] if pos else ""
    refspecs = pos[1:]
    root = ws.root if ws else Path(call.cwd)
    if remote:
        url = _git_out(root, "config", "--get", f"remote.{remote}.url") or (remote if "/" in remote or ":" in remote else "")
    else:
        url = _git_out(root, "config", "--get", "remote.origin.url")
    names: list[str] = []

    def all_local() -> list[str]:
        out = _git_out(root, "for-each-ref", "--format=%(refname:short)", "refs/heads")
        return [x for x in out.splitlines() if x]

    if s.longs & {"all", "mirror", "branches"}:
        names += all_local()
    cur = _head_branch(ws.gitdir) if ws else ""
    for spec in refspecs:
        if spec == "tag":
            continue
        spec = spec.lstrip("+")
        dst = spec.split(":", 1)[1] if ":" in spec else spec
        if "*" in dst:
            names += all_local()
            continue
        if dst in ("HEAD", ""):
            dst = cur
        if dst.startswith("refs/heads/"):
            dst = dst[len("refs/heads/"):]
        elif dst.startswith("refs/"):
            continue
        if dst:
            names.append(dst)
    if refspecs or s.longs & {"all", "mirror", "branches"}:
        return names, url
    # no refspec: config decides
    rc, out = _run_git([*_globals(call), "push", "--dry-run", "--porcelain", *call.args], timeout=20)
    dests = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and ":" in parts[1]:
            dst = parts[1].split(":", 1)[1]
            if dst.startswith("refs/heads/"):
                dests.append(dst[len("refs/heads/"):])
    if dests:
        return names + dests, url
    if rc == 0 and "To " in out:
        return names, url           # git resolved it: nothing but tags or nothing to push
    if s.longs & {"tags"} and rc == 0:
        return names, url
    if cur:
        cfg = [x for k, v in call.config.items() for x in ("-c", f"{k}={v}")]
        out = _git_out(root, *cfg, "for-each-ref", "--format=%(push:short)", f"refs/heads/{cur}")
        if out and "/" in out:
            return names + [out.split("/", 1)[1]], url
    return None, url


# --------------------------------------------------------------------------------------------
# guard: decisions
# --------------------------------------------------------------------------------------------

def call_workspaces(call: GitCall) -> list[Optional[Workspace]]:
    """The workspace(s) a call can change: the work tree named by --work-tree/GIT_WORK_TREE first, then the
    one holding cwd (or the --git-dir). [None] when git would not find a repository at all."""
    out: list[Workspace] = []
    if call.worktree:
        w = find_workspace(call.worktree)
        if w is not None:
            out.append(w)
    b = find_workspace(call.cwd, call.gitdir)
    if b is not None and not any(_same_path(b.root, x.root) for x in out):
        out.append(b)
    return list(out) if out else [None]


def _foreign(claim: dict[str, Any], rule: str, alt: str) -> Decision:
    return Decision(False, rule, alt, str(claim.get("id") or ""), owner_label(claim))


def _ws_decision(call: GitCall, ws: Optional[Workspace], ident: Optional[str], bang: bool) -> Optional[Decision]:
    claim = find_claim(ws) if ws else None
    if claim is not None and not is_mine(claim, ident):
        if not is_readonly(call):
            return _foreign(claim, "foreign-claim", FOREIGN_ALT)
        return None
    linked = bool(ws and ws.linked)
    rule: Optional[Rule] = None
    if claim is None:
        rule = shared_destructive(call, ws.root if ws else None)
    elif linked:
        rule = stash_rule(call) or _rebase_exec_rule(call)
    if rule is None and bang and (claim is None or linked):
        rule = Rule("shell alias", "a `!` alias runs a shell that reaches the real git past this guard; spell the git "
                                   "commands out")
    if rule is None:
        return None
    where = "a shared checkout (no active claim)" if claim is None else "a linked worktree (shared refs/stash)"
    return Decision(False, rule.name, rule.alt, str((claim or {}).get("id") or ""),
                    owner_label(claim) if claim else f"nobody; {where}")


def _target_decision(call: GitCall, wss: list[Optional[Workspace]], ident: Optional[str]) -> Optional[Decision]:
    """Rule 5: the claim of what the call HITS, not of where it runs."""
    sub, args = call.sub, call.args
    ws0 = next((w for w in wss if w is not None), None)
    if sub == "worktree" and args and args[0] in ("remove", "move", "prune"):
        verb = args[0]
        s = scan(args[1:], value_long={"expire", "reason"}, danger={"force"})
        force = bool(s.shorts & {"f"} or s.longs & {"force"})
        targets: list[str] = []
        if verb in ("remove", "move") and s.pos:
            targets = [s.pos[0]]
        elif verb == "prune" and ws0 is not None:
            targets = [str(r) for r, _ in repo_worktrees(ws0) if not r.exists()]
        for t in targets:
            c = claim_at(os.path.join(call.cwd, t))
            if c is not None and not is_mine(c, ident):
                return _foreign(c, f"worktree {verb} of a claimed workspace",
                                "ask the owner (session-finder/relay.py) to remove it; read-only `git worktree list` is fine")
            if verb == "remove" and force and c is None:
                return Decision(False, "worktree remove --force",
                                "`git worktree remove <path>` without --force (git then refuses a dirty tree), or claim it first",
                                "", "nobody; the target has no active claim of yours")
    names: list[str] = []
    if sub == "branch":
        s = scan(args, value_long={"contains", "no-contains", "merged", "no-merged", "points-at", "format", "sort",
                                   "abbrev"}, danger=D_WRITE_BRANCH)
        if s.shorts & set("dDmMf") or s.longs & {"delete", "move", "force"}:
            names = [p for p in s.pos]
    elif sub == "update-ref":
        s = scan(args, value_short="m", value_long={"stdin"})
        if s.pos and s.pos[0].startswith("refs/heads/"):
            names = [s.pos[0][len("refs/heads/"):]]
    if names and ws0 is not None:
        origin = _git_out(ws0.root, "config", "--get", "remote.origin.url")
        for nm in names:
            for c in claims_for_branch(nm, origin):
                if not is_mine(c, ident):
                    return _foreign(c, f"{sub} of a claimed branch", "message the owner; never move or delete another agent's branch")
            for root, gd in repo_worktrees(ws0):
                if _head_branch(gd) == nm:
                    c = claim_at(root)
                    if c is not None and not is_mine(c, ident):
                        return _foreign(c, f"{sub} of a branch checked out in a claimed workspace",
                                        "message the owner; the branch is checked out in their workspace")
    outs = output_targets(call)
    if outs:
        for o in outs:
            p = os.path.join(call.cwd, o)
            tws = find_workspace(os.path.dirname(p) if not os.path.isdir(p) else p)
            c = find_claim(tws) if tws else None
            if c is not None and not is_mine(c, ident):
                return _foreign(c, "output into a claimed workspace", "write the file outside the other agent's workspace")
    return None


def evaluate(call: GitCall, env: Optional[dict[str, str]] = None, *, assume_agent: bool = False,
             _depth: int = 0) -> Decision:
    """Decide one git call. Reads claims; asks real git for an alias, a push destination or a branch's origin."""
    env = os.environ if env is None else env
    if not assume_agent and not is_agent_env(env):
        return ALLOW
    ident = caller_ident(env)
    approved = {x.strip() for x in env.get("ACP_OPERATOR_APPROVED", "").split(",") if x.strip()}
    wss = call_workspaces(call)
    sub = call.sub
    bang = False
    if sub and sub not in READONLY and sub not in KNOWN_WRITE and _depth < 3:
        alias = call.config.get(f"alias.{sub.lower()}")
        ws0 = next((w for w in wss if w is not None), None)
        if alias is None and ws0 is not None:
            alias = _git_out(ws0.root, "config", "--get", f"alias.{sub}")
        if alias and alias.startswith("!"):
            bang = True
        elif alias:
            try:
                expanded = parse_git_argv(shlex.split(alias) + call.args, call.cwd, env)
                return evaluate(dataclasses.replace(expanded, config={**call.config, **expanded.config},
                                                    gitdir=call.gitdir or expanded.gitdir,
                                                    worktree=call.worktree or expanded.worktree),
                                env, assume_agent=assume_agent, _depth=_depth + 1)
            except ValueError:
                pass
    deny: Optional[Decision] = None
    for ws in wss:
        deny = _ws_decision(call, ws, ident, bang)
        if deny is not None:
            break
    if deny is None:
        deny = _target_decision(call, wss, ident)
    if deny is None and sub == "push":
        ws0 = next((w for w in wss if w is not None), None)
        names, url = push_destinations(call, ws0)
        if names is None:
            deny = Decision(False, "push-destination-unresolved",
                            "give an explicit refspec (`git push origin HEAD:<your-branch>`); the guard could not "
                            "resolve where a bare push goes", "", "nobody; destination unknown")
        else:
            for nm in dict.fromkeys(names):
                for c in claims_for_branch(nm, url):
                    if not is_mine(c, ident):
                        deny = _foreign(c, "push-foreign-branch",
                                        f"push only your own branch; ask the owner to push (or to add you to the "
                                        f"claim's allow list); branch {nm!r} is claimed")
                        break
                if deny:
                    break
    if deny is None:
        return ALLOW
    ws_any = next((w for w in wss if w is not None), None)
    deny.detail = {"sub": sub, "cwd": str(ws_any.root if ws_any else call.cwd), "ident": ident or ""}
    if OVERRIDE in approved:
        deny.override = True
        deny.allowed = True
    return deny


def _log_flags(args: Sequence[str]) -> list[str]:
    out = []
    for a in args:
        if a == "--":
            break
        if a.startswith("--"):
            out.append(a.split("=", 1)[0])
        elif a.startswith("-") and len(a) > 1:
            out.append(a[:2])
    return out[:12]


def log_event(decision: Decision, call: GitCall, extra: Optional[dict[str, Any]] = None) -> None:
    """One JSON line per refusal or override in guard.log: the subcommand and option NAMES only, never an
    option's value or a positional (URLs, messages, paths): a credential in argv must not reach a log."""
    rec = {"ts": utc_now(), "outcome": "override" if decision.override else "refused", "rule": decision.rule,
           "cmd": call.display(), "flags": _log_flags(call.args), "claim": decision.claim_id,
           "owner": decision.owner, "ident": decision.detail.get("ident", ""),
           "cwd": decision.detail.get("cwd", ""), "pid": os.getpid()}
    if extra:
        rec.update(extra)
    try:
        path = guard_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, (json.dumps(rec, sort_keys=True) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        pass  # a full disk never turns a refusal into a crash; the refusal still exits 77


def refusal_text(decision: Decision, call: GitCall) -> str:
    me = decision.detail.get("ident") or "no claim id"
    who = (f"  claim {decision.claim_id}: {decision.owner}; you are {me}.\n" if decision.claim_id
           else f"  {decision.owner}; you are {me}.\n")
    return (f"ade-git-guard: REFUSED `{call.display()}` [{decision.rule}] in {decision.detail.get('cwd', call.cwd)}\n"
            + who +
            f"  Safe alternative: {decision.message}.\n"
            f"  Ask the owner through session-finder/relay.py; exit 77 is an answer, not an obstacle to route around. "
            f"Logged in {guard_log_path()}.\n")


def _report(d: Decision, call: GitCall, extra: Optional[dict[str, Any]] = None) -> int:
    """Log and print a non-plain decision; returns 0 (override) or EXIT_REFUSED."""
    log_event(d, call, extra)
    if d.override:
        sys.stderr.write(f"ade-git-guard: ACP_OPERATOR_APPROVED={OVERRIDE}: allowed `{call.display()}` [{d.rule}] (logged)\n")
        return 0
    sys.stderr.write(refusal_text(d, call))
    return EXIT_REFUSED


def guard_argv(argv: Sequence[str], env: Optional[dict[str, str]] = None, cwd: Optional[str] = None) -> int:
    """What ade-git-guard runs for a git call that was not plainly read-only. 0 = run real git, 77 = refused."""
    env = os.environ if env is None else env
    if env.get("GIT_INDEX_FILE") or env.get("PRE_COMMIT"):
        return 0
    call = parse_git_argv(argv, cwd or os.getcwd(), env)
    d = evaluate(call, env)
    if d.allowed and not d.override:
        return 0
    return _report(d, call)


# --------------------------------------------------------------------------------------------
# guard: shell command strings (the Claude PreToolUse hook, W5)
# --------------------------------------------------------------------------------------------

# commands that run their arguments: a `git` after one of them is a real invocation
_WRAPPERS = {"command", "builtin", "exec", "time", "nohup", "sudo", "doas", "env", "noglob", "nice", "ionice", "timeout",
             "xargs", "watch", "stdbuf", "caffeinate", "setsid", "then", "do", "else", "elif", "if", "while", "until",
             "!", "{", "}", "exec", "unbuffer", "chronic", "parallel"}
_SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish", "ash"}
_ENV_ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
_DYN = re.compile(r"\$[A-Za-z_{(@*#?!0-9]|`")


@dataclasses.dataclass
class Word:
    text: str
    dyn: bool = False   # holds an unexpanded variable, $(...) or backtick: its value is unknown


def _match_paren(s: str, i: int) -> int:
    """Index of the `)` closing the `(` at s[i], skipping quoted text; len(s) when unclosed."""
    depth, j, n = 0, i, len(s)
    while j < n:
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "'":
            k = s.find("'", j + 1)
            j = n if k < 0 else k + 1
            continue
        if c == '"':
            j += 1
            while j < n and s[j] != '"':
                j += 2 if s[j] == "\\" else 1
            j += 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return n


def lex_shell(cmd: str) -> tuple[list[list[Word]], list[str]]:
    """(segments of words, bodies of $(...) and backtick substitutions). A segment ends at an unquoted newline,
    ; & | ( ). Raises ValueError on an unterminated quote. Heredoc bodies are data and skipped."""
    segs: list[list[Word]] = [[]]
    subs: list[str] = []
    buf: list[str] = []
    state = {"in": False, "dyn": False}
    heredocs: list[tuple[str, bool]] = []
    i, n = 0, len(cmd)

    def end_word() -> None:
        if state["in"]:
            segs[-1].append(Word("".join(buf), state["dyn"]))
        buf.clear()
        state["in"] = state["dyn"] = False

    def end_seg() -> None:
        end_word()
        if segs[-1]:
            segs.append([])

    while i < n:
        c = cmd[i]
        if c == "\\":
            if i + 1 < n:
                if cmd[i + 1] != "\n":
                    buf.append(cmd[i + 1])
                    state["in"] = True
            i += 2
        elif c == "'":
            j = cmd.find("'", i + 1)
            if j < 0:
                raise ValueError("unterminated single quote")
            buf.append(cmd[i + 1:j])
            state["in"] = True
            i = j + 1
        elif c == '"':
            state["in"] = True
            i += 1
            closed = False
            while i < n:
                d = cmd[i]
                if d == '"':
                    closed = True
                    i += 1
                    break
                if d == "\\" and i + 1 < n:
                    buf.append(cmd[i + 1] if cmd[i + 1] in '$`"\\' else "\\" + cmd[i + 1])
                    i += 2
                elif d == "$" and cmd[i + 1:i + 2] == "(":
                    j = _match_paren(cmd, i + 1)
                    subs.append(cmd[i + 2:j])
                    buf.append("$()")
                    state["dyn"] = True
                    i = j + 1
                elif d == "`":
                    j = cmd.find("`", i + 1)
                    j = n if j < 0 else j
                    subs.append(cmd[i + 1:j])
                    buf.append("``")
                    state["dyn"] = True
                    i = j + 1
                else:
                    if d == "$" and _DYN.match(cmd[i:i + 2]):
                        state["dyn"] = True
                    buf.append(d)
                    i += 1
            if not closed:
                raise ValueError("unterminated double quote")
        elif c == "$" and cmd[i + 1:i + 2] == "(":
            j = _match_paren(cmd, i + 1)
            subs.append(cmd[i + 2:j])
            buf.append("$()")
            state["in"] = state["dyn"] = True
            i = j + 1
        elif c == "`":
            j = cmd.find("`", i + 1)
            j = n if j < 0 else j
            subs.append(cmd[i + 1:j])
            buf.append("``")
            state["in"] = state["dyn"] = True
            i = j + 1
        elif c in " \t\r":
            end_word()
            i += 1
        elif c == "\n":
            end_seg()
            i += 1
            while heredocs:                      # skip the body of each pending heredoc
                delim, strip = heredocs.pop(0)
                while i < n:
                    j = cmd.find("\n", i)
                    line = cmd[i:n if j < 0 else j]
                    i = n if j < 0 else j + 1
                    if (line.lstrip("\t") if strip else line) == delim:
                        break
        elif c == "#" and not state["in"]:
            j = cmd.find("\n", i)
            i = n if j < 0 else j
        elif c in ";&|()":
            end_seg()
            i += 1
        elif c == "<" and cmd.startswith("<<", i) and not cmd.startswith("<<<", i):
            m = re.match(r"<<(-?)\s*(?:'([^']*)'|\"([^\"]*)\"|\\?([A-Za-z0-9_.-]+))", cmd[i:])
            if m:
                heredocs.append((m.group(2) or m.group(3) or m.group(4) or "", bool(m.group(1))))
                i += m.end()
                end_word()
            else:
                buf.append(c)
                state["in"] = True
                i += 1
        else:
            if c == "$" and _DYN.match(cmd[i:i + 2]):
                state["dyn"] = True
            buf.append(c)
            state["in"] = True
            i += 1
    end_word()
    return [s for s in segs if s], subs


@dataclasses.dataclass
class ShellCall:
    argv: list[str]
    cwd: Optional[str]          # None: unknown (a `cd` into an unexpanded or `-` path)
    env: dict[str, str]         # inline GIT_DIR= / GIT_WORK_TREE= assignments in force
    headlike: bool              # `git` is the command word (after wrappers), not an argument of another command
    nglobal: int = 0            # index of the subcommand in argv


def _basename(t: str) -> str:
    return os.path.basename(t) if "/" in t else t


def shell_git_calls(cmd: str, cwd: str, _depth: int = 0) -> tuple[list[ShellCall], list[str]]:
    """(git calls found in a shell command, problems that call for a fail-closed answer). See the module
    docstring for what is followed."""
    problems: list[str] = []
    try:
        segs, subs = lex_shell(cmd)
    except ValueError as e:
        return [], ([f"cannot parse the command ({e}); spell it out"] if re.search(r"(^|[^A-Za-z0-9_-])git\b", cmd) else [])
    out: list[ShellCall] = []
    cur: Optional[str] = cwd
    if _depth < 3:
        for body in subs:
            c2, p2 = shell_git_calls(body, cwd, _depth + 1)
            out += c2
            problems += p2
    for seg in segs:
        texts = [w.text for w in seg]
        head = 0
        while head < len(texts) and (_ENV_ASSIGN.match(texts[head]) or texts[head] in _WRAPPERS):
            head += 1
        if head < len(seg) and _basename(texts[head]) in ("cd", "pushd"):
            args = [w for w in seg[head + 1:] if not w.text.startswith("-") or w.text == "-"]
            if not args or args[0].dyn or args[0].text == "-" or re.match(r"^~[^/]", args[0].text) or cur is None:
                cur = None
            else:
                cur = os.path.normpath(os.path.join(cur, os.path.expanduser(args[0].text)))
            continue
        for idx, w in enumerate(seg):
            base = _basename(w.text)
            if base in _SHELLS and _depth < 3:
                for k in range(idx + 1, min(idx + 6, len(seg))):
                    if re.match(r"^-[A-Za-z]*c[A-Za-z]*$", seg[k].text) and k + 1 < len(seg):
                        c2, p2 = shell_git_calls(seg[k + 1].text, cur if cur is not None else cwd, _depth + 1)
                        out += c2
                        problems += p2
                        break
            elif base in ("eval", "watch") and _depth < 3:
                c2, p2 = shell_git_calls(" ".join(x.text for x in seg[idx + 1:]), cur if cur is not None else cwd, _depth + 1)
                out += c2
                problems += p2
            if base != "git":
                continue
            inline: dict[str, str] = {}
            for t in texts[:idx]:
                m = _ENV_ASSIGN.match(t)
                if m and m.group(1) in ("GIT_DIR", "GIT_WORK_TREE"):
                    inline[m.group(1)] = m.group(2)
            headlike = all(_ENV_ASSIGN.match(t) or t in _WRAPPERS or t.startswith("-") or t.isdigit() or
                           _basename(t) in ("env",) for t in texts[:idx])
            rest = seg[idx + 1:]
            call = parse_git_argv([x.text for x in rest], cur if cur is not None else cwd, {})
            if headlike:
                if any(x.dyn for x in rest[:call.nglobal + 1]):
                    problems.append("a git global option or subcommand is an unexpanded variable or substitution")
                elif any(_DYN.search(v) or (v.startswith("~") and not v.startswith("~/") and v != "~") for v in inline.values()):
                    problems.append("GIT_DIR/GIT_WORK_TREE is an unexpanded variable")
            out.append(ShellCall([x.text for x in rest], cur, inline, headlike, call.nglobal))
    return out, problems


def _pathspec_commit_after_apply(call: GitCall, env: dict[str, str]) -> Optional[Decision]:
    """Row 3 of the collision table: a `commit -- <paths>` after `apply --cached` in a shared checkout."""
    if call.sub != "commit" or "--" not in call.args or not call.args[call.args.index("--") + 1:]:
        return None
    ws = find_workspace(call.cwd)
    if ws is not None and find_claim(ws) is not None:
        return None
    d = Decision(False, "commit-pathspec-after-apply-cached",
                 "commit the index only (`git commit -m MSG`, no `-- <paths>`) or use `git-commit-own --staged`; a "
                 "pathspec commit takes the working tree's version of each path, peer hunks included",
                 "", "nobody; a shared checkout (no active claim)")
    d.detail = {"cwd": str(ws.root if ws else call.cwd), "ident": caller_ident(env) or ""}
    if OVERRIDE in {x.strip() for x in env.get("ACP_OPERATOR_APPROVED", "").split(",")}:
        d.override = d.allowed = True
    return d


def _closed(reason: str, env: dict[str, str], cwd: str) -> tuple[Decision, GitCall]:
    d = Decision(False, "unclassifiable", f"{reason}; spell the path and the git command out so the guard can read them",
                 "", "nobody; the call cannot be classified")
    d.detail = {"cwd": cwd, "ident": caller_ident(env) or ""}
    if OVERRIDE in {x.strip() for x in env.get("ACP_OPERATOR_APPROVED", "").split(",")}:
        d.override = d.allowed = True
    return d, GitCall(cwd, None, "", [], {})


def check_command(cmd: str, cwd: str, env: Optional[dict[str, str]] = None) -> int:
    """Decide every git call inside a shell command as an agent (the hook decides when to call this).
    Adds the row-3 rule: `git apply --cached` then `git commit ... -- <paths>` in one command. Fails closed
    (77) on a call it cannot classify."""
    env = os.environ if env is None else env
    calls, problems = shell_git_calls(cmd, cwd)
    for reason in problems:
        d, c = _closed(reason, env, cwd)
        if not (d.allowed and not d.override):
            rc = _report(d, c, {"via": "check"})
            if rc:
                return rc
    applied_cached = False
    for sc in calls:
        ecwd = sc.cwd if sc.cwd is not None else cwd
        cenv = {**env, **sc.env}
        call = parse_git_argv(sc.argv, ecwd, cenv)
        if not sc.headlike and call.sub not in READONLY and call.sub not in KNOWN_WRITE:
            continue  # `echo git foo`, `which git`: an argument, not a command
        if sc.cwd is None and not is_readonly(call):
            d, c = _closed("an earlier `cd`/`pushd` went to an unknown directory", cenv, ecwd)
        else:
            c = call
            d = evaluate(call, cenv, assume_agent=True)
            if d.allowed and not d.override:
                if call.sub == "apply" and "--cached" in call.args:
                    applied_cached = True
                elif applied_cached:
                    d = _pathspec_commit_after_apply(call, cenv) or d
        if d.allowed and not d.override:
            continue
        rc = _report(d, c, {"via": "check"})
        if rc:
            return rc
    return 0


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------

def _cli(argv: Sequence[str]) -> int:
    if argv and argv[0] == "guard":
        rest = list(argv[1:])
        if rest and rest[0] == "--":
            rest = rest[1:]
        return guard_argv(rest)
    import argparse
    p = argparse.ArgumentParser(prog="ade_claims.py", description=__doc__.split("\n\n")[0])
    sp = p.add_subparsers(dest="cmd", required=True)
    n = sp.add_parser("new", help="create a claim and its pointer; exit 3 id exists, 4 path owned by another owner")
    n.add_argument("--id", required=True)
    n.add_argument("--path", required=True)
    n.add_argument("--branch", required=True)
    n.add_argument("--base-sha", required=True)
    n.add_argument("--repo-origin", default="")
    n.add_argument("--owner-record")
    n.add_argument("--owner-session")
    n.add_argument("--owner-agent", default="")
    n.add_argument("--owner-model", default="")
    n.add_argument("--lead")
    n.add_argument("--allow", action="append", default=[])
    n.add_argument("--role", default="worker", choices=ROLES)
    n.add_argument("--purpose", default="")
    n.add_argument("--created-by", default="")
    n.add_argument("--inherited-dirt-patch")
    n.add_argument("--no-pointer", action="store_true", help="write the registry file only")
    s = sp.add_parser("show")
    s.add_argument("id")
    s.add_argument("--field")
    f = sp.add_parser("find")
    f.add_argument("dir", nargs="?", default=".")
    ls = sp.add_parser("list")
    ls.add_argument("--state", choices=STATES)
    ls.add_argument("--json", action="store_true")
    ss = sp.add_parser("set-state")
    ss.add_argument("id")
    ss.add_argument("state", choices=STATES)
    ck = sp.add_parser("check")
    ck.add_argument("command")
    ck.add_argument("--cwd", default=None)
    a = p.parse_args(list(argv))
    try:
        if a.cmd == "new":
            c = make_claim(id=a.id, path=a.path, branch=a.branch, base_sha=a.base_sha, repo_origin=a.repo_origin,
                           owner_record=a.owner_record, owner_session=a.owner_session, owner_agent=a.owner_agent,
                           owner_model=a.owner_model, lead=a.lead, allow=a.allow, role=a.role, purpose=a.purpose,
                           created_by=a.created_by, inherited_dirt_patch=a.inherited_dirt_patch)
            if not a.no_pointer and find_workspace(a.path) is None:
                raise ValueError(f"{a.path} is not inside a git workspace")
            target = create_claim(c)
            if not a.no_pointer:
                write_pointer(a.path, a.id)
            print(target)
        elif a.cmd == "show":
            c = read_claim(a.id)
            if c is None:
                print(f"ade_claims: no claim {a.id!r}", file=sys.stderr)
                return 1
            if a.field:
                v = c.get(a.field)
                print(v if isinstance(v, str) else json.dumps(v))
            else:
                print(json.dumps(c, indent=2, sort_keys=True))
        elif a.cmd == "find":
            ws = find_workspace(a.dir)
            c = find_claim(ws) if ws else None
            if c is None:
                return 1
            print(json.dumps(c, indent=2, sort_keys=True))
        elif a.cmd == "list":
            cs = list_claims(a.state)
            if a.json:
                print(json.dumps(cs, indent=2, sort_keys=True))
            else:
                for c in cs:
                    print(f"{c.get('id')}\t{c.get('state')}\t{c.get('branch')}\t{owner_label(c)}\t{c.get('path')}")
        elif a.cmd == "set-state":
            if set_state(a.id, a.state) is None:
                print(f"ade_claims: no claim {a.id!r}", file=sys.stderr)
                return 1
        elif a.cmd == "check":
            return check_command(a.command, a.cwd or os.getcwd())
    except ClaimExists as e:
        print(f"ade_claims: {e}", file=sys.stderr)
        return EXIT_EXISTS
    except PathClaimed as e:
        print(f"ade_claims: {e}", file=sys.stderr)
        return EXIT_PATH_OWNED
    except ValueError as e:
        print(f"ade_claims: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
