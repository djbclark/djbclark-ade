#!/usr/bin/env python3
"""ade_claims: the workspace claim library and the git-guard rules (isolation slice W1, 2026-10-24).

One claim per workspace (a cow pasture or a linked worktree): who owns it, which branch, which base.
Design: design-isolation-report.md 3.4 (schema), 3.5.4 (guard), 4.2.1 (gate). `bin/ade-git-guard` is
the bash front door; it runs `ade_claims.py guard -- GIT_ARGS...` only for a git call that is not
plainly read-only. W2 (cow-pasture), W3 (acp-dispatch), W4 (acp-run) and W5 (Claude hook) consume
this module, so the names below are the contract.

Claim file, `<state>/claims/<id>.json` (state = $ADE_STATE_DIR, default ~/.local/state/ade), JSON,
written atomically (temp file beside, then os.replace), every field read with .get:

    {"v": 1, "id": str, "path": str (realpath of the workspace root), "repo_origin": str,
     "branch": str, "base_sha": str,
     "owner": {"record": str|None, "session": str|None, "agent": str, "model": str},
     "lead": str|None, "allow": [ids], "role": "lead"|"worker"|"builder", "purpose": str,
     "created_at": ISO-8601 UTC, "created_by": str, "state": "active"|"released"|"merged",
     "released_at": ISO-8601 UTC|None, "inherited_dirt_patch": str|None}

Pointer: `<git-dir>/ade-claim` holds the claim id (git-dir is per-worktree, so a linked worktree has
its own; the file is never tracked). cow clones `.git`, so a pasture copied from a claimed checkout
inherits its source's pointer: `find_claim` therefore trusts a pointer only when the claim's `path`
is this workspace, and otherwise falls back to a registry scan by path. `write_pointer` overwrites.

Who is "mine" (`is_mine`): the caller identity (ADE_CLAIM_ID, else a harness session id) equals the
claim id, owner.record, owner.session, or is in `allow`. `lead` is NOT implied: a lead that should
write in a worker's workspace or push its branch goes into `allow`.

Guard rules (agents only: ACP_RUN_AGENT=1 or ADE_CLAIM_ID set; a human shell is never touched):
  1. A workspace with an ACTIVE claim that is not mine: git is read-only (READONLY set plus the
     read forms of branch/config/worktree/remote/tag/stash/reflog/submodule).
  2. A workspace with no active claim (shared or primary checkout): refuse stash (except list/show),
     reset --hard|--merge|--keep, checkout -f|-- <paths>|., restore without --staged, switch
     -f|--discard-changes, clean -f, commit -a, add -A/--all with no pathspec or add ., and
     pull|rebase|merge --autostash (or -c rebase.autoStash/merge.autoStash=true).
  3. A linked worktree of any owner: stash is refused (refs/stash is shared).
  4. push: refused when a destination branch has an active claim that is not mine (any workspace).
  5. In my own claimed workspace everything else is allowed.
Refusal = exit 77 (EX_NOPERM), a message naming the owner and the safe alternative, one JSON line in
`<state>/guard.log` (flags and branch names only: no positional values, so no URL credentials).
Operator override: ACP_OPERATOR_APPROVED containing `git-guard` allows the call and logs it.
git's own hooks (GIT_INDEX_FILE set) and pre-commit (PRE_COMMIT set) are never refused: their `git
checkout -- .` stash dance is git's, not the agent's.

CLI (also the bash-facing API; every subcommand exits 0 ok, 1 not found, 2 usage, 77 refused):
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


def atomic_write(path: Path, text: str) -> None:
    """Temp file beside the target, fsync, os.replace: a reader sees the old or the new file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def _claims_lock() -> Iterator[None]:
    """Serialises read-modify-write of claim files (update_claim); readers need no lock."""
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
    """Atomically write `claim` to its registry file; returns the file."""
    target = claim_file(str(claim.get("id") or ""))
    atomic_write(target, json.dumps(claim, indent=2, sort_keys=True) + "\n")
    return target


def read_claim(claim_id: str) -> Optional[dict[str, Any]]:
    """The claim dict, or None when the id is invalid, the file is missing or is not a JSON object."""
    if not valid_id(claim_id):
        return None
    try:
        data = json.loads((claims_dir() / f"{claim_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
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
    owner = claim.get("owner") if isinstance(claim.get("owner"), dict) else {}
    ids = {claim.get("id"), owner.get("record"), owner.get("session")}
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


def _same_dir(a: Any, b: Path) -> bool:
    try:
        return isinstance(a, str) and bool(a) and Path(a).resolve() == b
    except OSError:
        return False


def find_claim(ws: Workspace, active_only: bool = True) -> Optional[dict[str, Any]]:
    """The claim of workspace `ws`. The pointer is trusted only when the claim's path IS this workspace
    (cow copies `.git`, pointer included, into a new pasture); otherwise the registry is scanned by path."""
    pid = read_pointer(ws)
    cands: list[dict[str, Any]] = []
    if pid:
        c = read_claim(pid)
        if c is not None and _same_dir(c.get("path"), ws.root):
            cands.append(c)
    if not cands:
        cands = [c for c in list_claims() if _same_dir(c.get("path"), ws.root)]
    if active_only:
        cands = [c for c in cands if claim_state_active(c)]
    if not cands:
        return None
    cands.sort(key=lambda c: str(c.get("created_at") or ""))
    return cands[-1]


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

    def display(self) -> str:
        return f"git {self.sub}".rstrip()


def parse_git_argv(argv: Sequence[str], cwd: str) -> GitCall:
    """Split git's global options from `<subcommand> <args>`; -C is cumulative, -c collected."""
    cur = cwd
    gitdir: Optional[str] = None
    config: dict[str, str] = {}
    i, n = 0, len(argv)
    while i < n:
        a = argv[i]
        if a in ("-C",) and i + 1 < n:
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
                gitdir = argv[i + 1]
            else:
                cur = os.path.join(cur, argv[i + 1])
            i += 2
        elif a.startswith("--git-dir="):
            gitdir = a.split("=", 1)[1]
            i += 1
        elif a.startswith("--work-tree="):
            cur = os.path.join(cur, a.split("=", 1)[1])
            i += 1
        elif a in GLOBAL_VALUE and i + 1 < n:
            i += 2
        elif a in GLOBAL_FLAG or (a.startswith("--") and "=" in a and a.split("=", 1)[0] in GLOBAL_VALUE) \
                or a.startswith("--exec-path") or a in ("--version", "--help", "-h", "--html-path", "--man-path", "--info-path"):
            i += 1
        elif a.startswith("-"):
            i += 1  # unknown global flag: ignore it, never mistake it for the subcommand
        else:
            break
    sub = argv[i] if i < n else ""
    return GitCall(cur, gitdir, sub, list(argv[i + 1:]), config)


@dataclasses.dataclass
class Scan:
    shorts: set[str]
    longs: set[str]
    pos: list[str]
    after: list[str]   # everything after a bare `--`


def scan(args: Sequence[str], value_short: str = "", value_long: Iterable[str] = (), attached_short: str = "") -> Scan:
    """Classify option tokens. A short in `value_short` takes the rest of its cluster or the next token
    (so `-m "text -a"` never reads as -a); one in `attached_short` takes only an attached value."""
    vl = set(value_long)
    shorts: set[str] = set()
    longs: set[str] = set()
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
            longs.add(name)
            if not eq and name in vl:
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
    return Scan(shorts, longs, pos, after)


def _truthy(v: Optional[str]) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


# --------------------------------------------------------------------------------------------
# guard: classification
# --------------------------------------------------------------------------------------------

def is_readonly(call: GitCall) -> bool:
    """True when this git call cannot change the repository or its working tree."""
    sub, args = call.sub, call.args
    if sub == "" or sub in READONLY:
        return True
    if sub == "branch":
        s = scan(args, value_long={"contains", "no-contains", "merged", "no-merged", "points-at", "format",
                                   "sort", "abbrev"})
        write_l = {"delete", "move", "copy", "set-upstream-to", "unset-upstream", "edit-description", "force",
                   "track", "no-track", "create-reflog", "set-upstream"}
        if s.shorts & set("dDmMcCuft") or s.longs & write_l:
            return False
        listing = s.shorts & set("lavr") or s.longs & {"list", "contains", "no-contains", "merged", "no-merged",
                                                       "points-at", "show-current", "all", "remotes", "verbose"}
        return not s.pos or bool(listing)
    if sub == "config":
        s = scan(args, value_short="f", value_long={"file", "blob", "type", "default"})
        if s.shorts & {"e"} or s.longs & {"add", "unset", "unset-all", "replace-all", "rename-section",
                                           "remove-section", "edit", "set"}:
            return False
        if s.pos and s.pos[0] in ("set", "unset", "edit", "rename-section", "remove-section", "add"):
            return False
        if (s.pos and s.pos[0] in ("get", "list")) or s.shorts & {"l"} or \
                s.longs & {"get", "get-all", "get-regexp", "list", "get-urlmatch", "get-color", "get-colorbool"}:
            return True
        return len(s.pos) < 2
    if sub == "worktree":
        return bool(args) and args[0] == "list"
    if sub == "remote":
        s = scan(args)
        return not s.pos or s.pos[0] in ("show", "get-url")
    if sub == "tag":
        s = scan(args, value_short="umF", value_long={"contains", "no-contains", "merged", "no-merged", "points-at",
                                                       "format", "sort", "message", "file", "local-user"})
        if s.shorts & set("dasf") or s.longs & {"delete", "annotate", "sign", "force", "message", "file",
                                                 "local-user"}:
            return False
        listing = s.shorts & set("ln") or s.longs & {"list", "contains", "no-contains", "merged", "no-merged",
                                                     "points-at"}
        return not s.pos or bool(listing)
    if sub == "stash":
        return bool(args) and args[0] in ("list", "show")
    if sub == "reflog":
        return not args or args[0] not in ("expire", "delete")
    if sub == "submodule":
        return bool(args) and args[0] in ("status", "summary")
    if sub == "symbolic-ref":
        return len(scan(args).pos) < 2 and "d" not in scan(args).shorts
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


def shared_destructive(call: GitCall) -> Optional[Rule]:
    """The destructive forms refused in a shared (no active claim) checkout (stash: see stash_rule)."""
    sub, args = call.sub, call.args
    rule = stash_rule(call)
    if rule is not None:
        return rule
    if sub == "reset":
        s = scan(args, value_long={"source"})
        if s.longs & {"hard", "merge", "keep"}:
            return Rule("reset --hard", "`git reset --soft`, or `git restore --staged <path>`; to discard work, "
                                        "do it in your own workspace")
    elif sub == "checkout":
        s = scan(args, value_short="bB", value_long={"orphan", "conflict", "pathspec-from-file"})
        if s.shorts & {"f"} or s.longs & {"force"} or s.after or "." in s.pos:
            return Rule("checkout --", "`git switch <branch>` in your own workspace; `git diff` to inspect; "
                                       "never overwrite paths in a shared checkout")
    elif sub == "restore":
        s = scan(args, value_short="s", value_long={"source", "pathspec-from-file"})
        if not (s.longs & {"staged"} or s.shorts & {"S"}) or s.longs & {"worktree"} or s.shorts & {"W"}:
            return Rule("restore", "`git restore --staged <path>` only unstages; to discard work, do it in your "
                                   "own workspace")
    elif sub == "switch":
        s = scan(args, value_short="cCt", value_long={"create", "force-create", "track", "orphan"})
        if s.shorts & {"f"} or s.longs & {"force", "discard-changes"}:
            return Rule("switch -f", "`git switch <branch>` without -f, or commit first, in your own workspace")
    elif sub == "clean":
        s = scan(args, value_short="e", value_long={"exclude"})
        if (s.shorts & {"f"} or s.longs & {"force"}) and not (s.shorts & {"n"} or s.longs & {"dry-run"}):
            return Rule("clean -f", "`git clean -n` (dry run) and delete the named files yourself, in your own workspace")
    elif sub == "commit":
        s = scan(args, value_short="mFCct", attached_short="Su",
                 value_long={"message", "file", "author", "date", "reuse-message", "reedit-message", "fixup",
                             "squash", "template", "cleanup"})
        if s.shorts & {"a"} or s.longs & {"all"}:
            return Rule("commit -a", "`git add <explicit paths>` then `git commit`; -a would commit a peer's "
                                     "uncommitted hunks")
    elif sub == "add":
        s = scan(args, value_long={"pathspec-from-file", "chmod"})
        paths = s.pos + s.after
        sweep = (s.shorts & {"A"} or s.longs & {"all"}) and not paths
        if sweep or any(p in (".", "./", ":/", ":/.") for p in paths):
            return Rule("add -A/.", "`git add <explicit paths>`; a sweep stages a peer's uncommitted hunks")
    elif sub in ("pull", "rebase", "merge"):
        s = scan(args, value_short="sXmFx", value_long={"strategy", "strategy-option", "onto", "exec", "message", "file"})
        auto = bool(s.longs & {"autostash"}) and "no-autostash" not in s.longs
        if not auto:
            for key in ("rebase.autostash", "merge.autostash"):
                if key in call.config and _truthy(call.config[key]):
                    auto = True
        if auto:
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


def _git_out(root: Path, *args: str) -> str:
    try:
        import subprocess
        r = subprocess.run([real_git(), "-C", str(root), *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def _current_branch(ws: Workspace) -> str:
    try:
        head = (ws.gitdir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return head[len("ref: refs/heads/"):] if head.startswith("ref: refs/heads/") else ""


def push_branches(call: GitCall, ws: Optional[Workspace]) -> tuple[list[str], str]:
    """(destination branch names, remote url) of a `git push` call. --all/--mirror cover every local branch."""
    # --force-with-lease, --signed and --recurse-submodules take only an attached value: no value_long entry
    s = scan(call.args, value_short="o", value_long={"repo", "push-option", "receive-pack", "exec"})
    pos = s.pos + s.after
    remote = pos[0] if pos else ""
    refspecs = pos[1:]
    root = ws.root if ws else Path(call.cwd)
    url = ""
    if remote:
        url = _git_out(root, "config", "--get", f"remote.{remote}.url") or (remote if "/" in remote or ":" in remote else "")
    else:
        url = _git_out(root, "config", "--get", "remote.origin.url")
    names: list[str] = []
    if s.longs & {"all", "mirror", "branches"}:
        out = _git_out(root, "for-each-ref", "--format=%(refname:short)", "refs/heads")
        names += [x for x in out.splitlines() if x]
    for spec in refspecs:
        spec = spec.lstrip("+")
        dst = spec.split(":", 1)[1] if ":" in spec else spec
        if dst in ("HEAD", ""):
            dst = _current_branch(ws) if ws else ""
        if dst.startswith("refs/heads/"):
            dst = dst[len("refs/heads/"):]
        elif dst.startswith("refs/"):
            continue
        if dst:
            names.append(dst)
    if not refspecs and not (s.longs & {"all", "mirror", "branches", "tags"}) and ws:
        cur = _current_branch(ws)
        if cur:
            names.append(cur)
    return names, url


def evaluate(call: GitCall, env: Optional[dict[str, str]] = None, *, assume_agent: bool = False,
             _depth: int = 0) -> Decision:
    """Decide one git call. Reads claims; asks real git only for an alias or a push."""
    env = os.environ if env is None else env
    if not assume_agent and not is_agent_env(env):
        return ALLOW
    ident = caller_ident(env)
    approved = {x.strip() for x in env.get("ACP_OPERATOR_APPROVED", "").split(",") if x.strip()}
    ws = find_workspace(call.cwd, call.gitdir or env.get("GIT_DIR"))
    claim = find_claim(ws) if ws else None
    sub = call.sub
    if sub and sub not in READONLY and sub not in KNOWN_WRITE and ws is not None and _depth < 3:
        alias = _git_out(ws.root, "config", "--get", f"alias.{sub}")
        if alias and not alias.startswith("!"):
            try:
                return evaluate(dataclasses.replace(parse_git_argv(shlex.split(alias) + call.args, call.cwd),
                                                    config=call.config, gitdir=call.gitdir), env,
                                assume_agent=assume_agent, _depth=_depth + 1)
            except ValueError:
                pass
    deny: Optional[Decision] = None
    if claim is not None and not is_mine(claim, ident):
        if not is_readonly(call):
            deny = Decision(False, "foreign-claim", FOREIGN_ALT, str(claim.get("id") or ""), owner_label(claim))
    if deny is None and sub == "push":
        names, url = push_branches(call, ws)
        for nm in dict.fromkeys(names):
            for c in claims_for_branch(nm, url):
                if not is_mine(c, ident):
                    deny = Decision(False, "push-foreign-branch",
                                    f"push only your own branch; ask the owner to push (or to add you to the claim's "
                                    f"allow list); branch {nm!r} is claimed", str(c.get("id") or ""), owner_label(c))
                    break
            if deny:
                break
    if deny is None and (claim is None or is_mine(claim, ident)):
        linked = bool(ws and ws.linked)
        rule: Optional[Rule] = None
        if claim is None:
            rule = shared_destructive(call)
        elif linked:
            rule = stash_rule(call)
        if rule is not None:
            where = "a shared checkout (no active claim)" if claim is None else "a linked worktree (shared refs/stash)"
            deny = Decision(False, rule.name, rule.alt, str((claim or {}).get("id") or ""),
                            owner_label(claim) if claim else f"nobody; {where}")
    if deny is None:
        return ALLOW
    deny.detail = {"sub": sub, "cwd": str(ws.root if ws else call.cwd), "ident": ident or ""}
    if OVERRIDE in approved:
        deny.override = True
        deny.allowed = True
    return deny


def log_event(decision: Decision, call: GitCall, extra: Optional[dict[str, Any]] = None) -> None:
    """One JSON line per refusal or override in guard.log. Flags and the subcommand only, never positional
    values (URLs, messages, paths): a credential in argv must not reach a log."""
    flags = [a.split("=", 1)[0] for a in call.args if a.startswith("-")][:12]
    rec = {"ts": utc_now(), "outcome": "override" if decision.override else "refused", "rule": decision.rule,
           "cmd": call.display(), "flags": flags, "claim": decision.claim_id, "owner": decision.owner,
           "ident": decision.detail.get("ident", ""), "cwd": decision.detail.get("cwd", ""), "pid": os.getpid()}
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
    return (f"ade-git-guard: REFUSED `{call.display()}` [{decision.rule}] in {decision.detail.get('cwd', call.cwd)}\n"
            + (f"  claim {decision.claim_id}: {decision.owner}; you are {me}.\n" if decision.claim_id
               else f"  {decision.owner}; you are {me}.\n") +
            f"  Safe alternative: {decision.message}.\n"
            f"  Ask the owner through session-finder/relay.py; exit 77 is an answer, not an obstacle to route around. "
            f"Logged in {guard_log_path()}.\n")


def guard_argv(argv: Sequence[str], env: Optional[dict[str, str]] = None, cwd: Optional[str] = None) -> int:
    """What ade-git-guard runs for a git call that was not plainly read-only. 0 = run real git, 77 = refused."""
    env = os.environ if env is None else env
    if env.get("GIT_INDEX_FILE") or env.get("PRE_COMMIT"):
        return 0
    call = parse_git_argv(argv, cwd or os.getcwd())
    d = evaluate(call, env)
    if d.allowed and not d.override:
        return 0
    log_event(d, call)
    if d.override:
        sys.stderr.write(f"ade-git-guard: ACP_OPERATOR_APPROVED={OVERRIDE}: allowed `{call.display()}` [{d.rule}] (logged)\n")
        return 0
    sys.stderr.write(refusal_text(d, call))
    return EXIT_REFUSED


# --------------------------------------------------------------------------------------------
# guard: shell command strings (the Claude PreToolUse hook, W5)
# --------------------------------------------------------------------------------------------

_WRAPPERS = {"command", "builtin", "exec", "time", "nohup", "sudo", "env", "noglob", "nice"}
_SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}


def shell_git_calls(cmd: str, cwd: str, _depth: int = 0) -> list[tuple[list[str], str]]:
    """(git argv, cwd) for each `git ...` segment of a shell command. `cd DIR &&` moves later segments;
    `bash -c STR` is read recursively (two levels). A command that does not tokenize yields nothing."""
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        return []
    segs: list[list[str]] = [[]]
    for t in toks:
        if t and set(t) <= set(";&|()") or t in ("\n",):
            segs.append([])
        else:
            segs[-1].append(t)
    out: list[tuple[list[str], str]] = []
    cur = cwd
    for seg in segs:
        i = 0
        while i < len(seg) and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", seg[i]) or seg[i] in _WRAPPERS):
            i += 1
        seg = seg[i:]
        if not seg:
            continue
        head = os.path.basename(seg[0])
        if head in ("cd", "pushd") and len(seg) > 1 and "$" not in seg[1]:
            cur = os.path.normpath(os.path.join(cur, os.path.expanduser(seg[1])))
        elif head == "git":
            out.append((seg[1:], cur))
        elif head in _SHELLS and _depth < 2 and "-c" in seg[1:-1]:
            out += shell_git_calls(seg[seg.index("-c") + 1], cur, _depth + 1)
    return out


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


def check_command(cmd: str, cwd: str, env: Optional[dict[str, str]] = None) -> int:
    """Decide every git call inside a shell command as an agent (the hook decides when to call this).
    Adds the row-3 rule: `git apply --cached` then `git commit ... -- <paths>` in one command."""
    env = os.environ if env is None else env
    applied_cached = False
    for argv, ccwd in shell_git_calls(cmd, cwd):
        call = parse_git_argv(argv, ccwd)
        d = evaluate(call, env, assume_agent=True)
        if d.allowed and not d.override:
            if call.sub == "apply" and "--cached" in call.args:
                applied_cached = True
            elif applied_cached:
                d = _pathspec_commit_after_apply(call, env) or d
        if d.allowed and not d.override:
            continue
        log_event(d, call, {"via": "check"})
        if d.override:
            sys.stderr.write(f"ade-git-guard: ACP_OPERATOR_APPROVED={OVERRIDE}: allowed `{call.display()}` [{d.rule}] (logged)\n")
            continue
        sys.stderr.write(refusal_text(d, call))
        return EXIT_REFUSED
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
    n = sp.add_parser("new", help="write a claim and its pointer")
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
            if not a.no_pointer:
                write_pointer(a.path, a.id)
            print(write_claim(c))
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
    except ValueError as e:
        print(f"ade_claims: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
