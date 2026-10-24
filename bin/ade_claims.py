#!/usr/bin/env python3
"""ade_claims: the workspace claim library and the git-guard rules (isolation slice W1, 2026-10-24).

One claim per workspace (a cow pasture or a linked worktree): who owns it, which branch, which base.
Design: design-isolation-report.md 3.4 (schema), 3.5.4 (guard), 4.2.1 (gate). `bin/ade-git-guard` is
the bash front door; it runs `ade_claims.py guard -- GIT_ARGS...` only for a git call that is not
plainly read-only. Integration stage as of 2026-10-24: W1 (this file and the guard) exists; W2 (cow-pasture),
W3 (acp-dispatch), W4 (acp-run puts the shim on agents' PATH) and W5 (Claude hook) consume this module and are NOT
installed yet, so the names below are the contract but nothing calls the guard in a live session.

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
already has another owner's active claim (PathClaimed, exit 4). A re-claim of the path by the SAME owner
(shared owner.record/session) releases that owner's older active record inside the same registry lock, so a path
never carries two active records, and publishes the pointer under that lock. `set_state(id, "active")` applies
the same path rule (PathClaimed when another owner holds the path). `write_claim` overwrites (update paths only).
Every record is forced to its schema types on read (`id` = the file name; `owner.agent=7`, `allow=3` and the like
are repaired, never raised), so a hostile record can neither crash nor blind the guard.

Pointer: `<git-dir>/ade-claim` holds the claim id (git-dir is per-worktree, so a linked worktree has
its own; the file is never tracked). cow clones `.git`, so a pasture copied from a claimed checkout
inherits its source's pointer: `find_claim` therefore trusts a pointer only when the claim's `path`
is this workspace (compared with os.path.samefile, so a differently cased path on APFS still matches),
and uses it only while that claim is ACTIVE; otherwise the registry is scanned by path for active claims (a
stale pointer never hides a newer active record). `write_pointer` overwrites.

Who is "mine" (`is_mine`): the caller identity (ADE_CLAIM_ID, else a harness session id) equals the
claim id, owner.record, owner.session, or is in `allow`. `lead` is NOT implied: a lead that should
write in a worker's workspace or push its branch goes into `allow`.

Guard rules (agents only: ACP_RUN_AGENT=1 or ADE_CLAIM_ID set; a human shell is never touched; the design's
other markers CLAUDECODE/OMPCODE/CODEX_* are NOT used: interactive Claude is covered by `check`, W5).
Git is read the way git reads it: option state is evaluated IN ORDER (`restore --staged --no-staged` is not
staged), long options match by any unique prefix, config is the call's own ordered multi-valued -c /
--config-env / GIT_CONFIG_* plus the repository's, and relative --git-dir/--work-tree/GIT_DIR/GIT_WORK_TREE are
relative to the cwd after every -C:
  1. A workspace with an ACTIVE claim that is not mine: git is read-only (READONLY set plus the read forms of
     branch/config/worktree/remote/tag/stash/reflog/submodule/symbolic-ref/fetch). A "read-only" command that
     writes a file (`--output`, format-patch -o, archive -o, grep -O) or a local branch (`fetch --update-head-ok`,
     `fetch . +a:b`, `symbolic-ref -d|--delete`) is not read-only there.
  2. A workspace with no active claim (shared or primary checkout): refuse stash (except list/show),
     reset --hard|--merge|--keep, checkout -f|-p|--pathspec-from-file|--|<path>|<2+ args>, restore unless
     --staged is in force and --worktree is not, switch -f|--discard-changes, clean unless -n (also -i), rm -f
     unless --cached or -n is in force, commit -a, add -A/-u/--all/--update with no pathspec or add ., pull|
     rebase|merge with autostash in force (--autostash/--no-autostash, else rebase.autoStash for a rebase or a
     pull that rebases, merge.autoStash for a merge or a pull that merges), rebase -x, `!` aliases and an
     alias chain deeper than MAX_ALIAS_DEPTH. An output file over a dirty (modified or untracked) file of a
     shared checkout is refused. Not covered (plumbing and wildcard staging stay the operator's call):
     checkout-index, read-tree, mv -f, `add '*'`.
  3. A linked worktree, even its own claimed owner's: stash, rebase -x and `!` aliases are refused (refs/stash
     is shared with the other worktrees); everything else the owner does there is allowed.
  4. push: refused when a destination branch has an active claim that is not mine (any workspace). Destinations
     and push URLs come only from git's own `push --dry-run --porcelain --no-verify` under the call's config
     (so `@`, `heads/x`, wildcard, --mirror, deletion, pushurl, insteadOf all resolve as git resolves them); the
     safety options are forced after every caller option, `--no-dry-run`/`--no-porcelain` or any abbreviation is
     refused, and the group is killed on timeout. The dry run still contacts the remote (transport, credential
     helper and ssh command run; pre-push hooks do not). A destination that cannot be resolved is refused while
     another agent holds an active claim: the dry run timed out or exited other than 0/1, printed no `To` line, or
     its output is incomplete (no closing `Done`, a malformed ref line). A claim matches a URL by normalised origin (scheme default ports and
     ssh.github.com:443 are verified aliases; any other host/port spelling is a different repository).
  5. The TARGET counts, not only the cwd: `worktree remove|move|prune` (selectors resolved against git's
     registered worktree list, unique-suffix form included), `branch -d|-D|-m|-f`, `update-ref` (named ref; with
     --stdin refused while another agent holds a claim in the repository) and an output file (its own symlink
     resolved first) are checked against the claim of the workspace they hit; the git dir and work tree the call
     lands on are asked of git itself (`rev-parse --absolute-git-dir --show-toplevel` under the call's own -C, -c,
     --git-dir, --work-tree and environment: GIT_WORK_TREE, core.worktree and their quoting are git's to read; only
     what git reads is honored, so core.worktree from `-c` or an include is ignored exactly as git ignores it);
     when git cannot answer at all (timeout), the typed values are used and a call that changes anything is refused
     while another agent holds a claim (rule workspace-unresolved); `worktree remove --force` needs ownership of
     the target.
  6. In my own claimed workspace everything else is allowed.
Refusal = exit 77 (EX_NOPERM), a message naming the owner and the safe alternative (control characters escaped),
one JSON line in `<state>/guard.log` (flag NAMES from an allowlist only; an option's value is never logged).
Operator override: ACP_OPERATOR_APPROVED containing `git-guard` allows the call and logs it (design 5.6's
ADE_GIT_GUARD_BYPASS was not built; this is the convention bin/acp-dispatch already uses).
git's own hooks (GIT_INDEX_FILE set) and pre-commit (PRE_COMMIT set) are never refused: their `git
checkout -- .` stash dance is git's, not the agent's. A guard crash fails OPEN (design 5.7, bin/ade-git-guard).

`check CMD` reads a shell command string. Supported syntax: newlines, `;` `&&` `||` `|` `|&` `&`, `( )` subshell
scope (a `cd`/`pushd` inside `( )` does not leak; one in a pipeline or a background job does not take effect;
`popd` pops the `pushd` stack; `{ }` groups share the shell, so a cd inside leaks as in bash), `$(...)` and backticks
(analysed at the directory in force; so is one inside `${X:-$(...)}`), double/single quotes, `$'...'` (decoded
like bash; a bad escape such as `\\x`, `\\u`, `\\xZ` stays literal), `$"..."`, heredocs (`<<`, `<<-`) and here-strings
(`<<<`). The heredoc delimiter is the word after `<<` with shell quote removal applied exactly (`E"OF"`, `E\\OF`,
`'E OF'`); one that cannot be read exactly (`$'..'`, a backtick, no word) or a heredoc with no terminating line is
refused when the command mentions git, never swallowed as data. The consumer is judged: a body or here-string in a
segment with `bash`/`sh`/`zsh`... anywhere (`env -u X bash`, `sudo -u me sh`, `nice -n 5 zsh`) or `source`/`.` as
the command is analysed as shell code, an unquoted body's `$(...)`/backticks are analysed, a quoted body for
anything else is data;
`bash -lc '...'`, `eval`, `watch`, env/sudo/nice/timeout/xargs wrappers (`{}` of xargs counts as unexpanded),
inline GIT_DIR=/GIT_WORK_TREE=/GIT_CONFIG_*=, `cd X &&` (a cd to a directory that does not exist, without a
`mkdir` in the command, is an unknown directory). It FAILS CLOSED (exit 77, "spell it out") for: a git call whose
global options or subcommand are unexpanded variables; a `cd`/`-C` into an unknown directory before a
non-read-only call; an unterminated quote; shell code nested deeper than MAX_SHELL_DEPTH; text that mentions git
piped into a shell; `source`/a shell reading a process substitution or /dev/stdin; `eval` of a computed string;
and a COMPUTED command name (`$G`, `$(which git)`, a glob or brace pattern that can match `git`) in a command
that mentions git (a literal path tail other than `git`, as in `$(pwd)/run.sh`, rules it out). Not followed:
shell functions and aliases, `source file`, `bash script.sh`, `xargs` stdin, variables set outside the command, `case`/
`for` control flow (a cd in a failing branch is judged as if it ran). Unquoted `echo git reset --hard` is judged
as a git call (a false refusal is cheaper than a miss); quoted text such as `echo 'git reset --hard'` is data.

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


def create_claim(claim: dict[str, Any], pointer_for: Optional[str | os.PathLike[str]] = None) -> Path:
    """Create a NEW claim exclusively, under the registry lock. Raises ClaimExists when the id is taken and
    PathClaimed when `claim["path"]` already has another owner's active claim (two active claims on one path
    would let the newer one take the workspace over). The file appears atomically and never replaces another.
    A re-claim by the SAME owner (shared owner.record/session) releases the owner's older active record(s) of that
    path inside the same lock, so one path never carries two active records. `pointer_for` (a directory of the
    workspace) also publishes `<git-dir>/ade-claim` under the lock, so the pointer and the registry change together."""
    target = claim_file(str(claim.get("id") or ""))
    with _claims_lock():
        if target.exists():
            raise ClaimExists(f"claim {claim.get('id')!r} already exists ({target})")
        mine = _owner_keys(claim)
        older: list[str] = []
        for c in list_claims("active"):
            if _same_path(c.get("path"), Path(str(claim.get("path") or ""))):
                if mine and mine & _owner_keys(c):
                    older.append(str(c.get("id")))
                else:
                    raise PathClaimed(f"{claim.get('path')} is already claimed by {c.get('id')!r} ({owner_label(c)})")
        tmp = _write_temp(target, json.dumps(claim, indent=2, sort_keys=True) + "\n")
        try:
            os.link(tmp, target)  # fails with EEXIST rather than replacing
        except FileExistsError:
            raise ClaimExists(f"claim {claim.get('id')!r} already exists ({target})") from None
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
        if claim.get("state", "active") == "active":
            for oid in older:
                _update_unlocked(oid, state="released", released_at=utc_now())
        if pointer_for is not None:
            write_pointer(pointer_for, str(claim.get("id")))
    return target


def _sanitize(data: dict[str, Any], claim_id: str) -> dict[str, Any]:
    """Force every field the guard reads to its schema type: a hostile or corrupt record (`id=[]`,
    `owner.agent=7`, `allow=3`) must neither crash the guard nor blind it. The file name IS the id."""
    def text(v: Any, default: str = "") -> str:
        return v if isinstance(v, str) else default

    c = dict(data)
    c["id"] = claim_id
    owner = data.get("owner") if isinstance(data.get("owner"), dict) else {}
    c["owner"] = {"record": owner.get("record") if isinstance(owner.get("record"), str) else None,
                  "session": owner.get("session") if isinstance(owner.get("session"), str) else None,
                  "agent": text(owner.get("agent")), "model": text(owner.get("model"))}
    c["allow"] = [a for a in data.get("allow", []) if isinstance(a, str)] if isinstance(data.get("allow"), list) else []
    for k in ("path", "branch", "repo_origin", "created_at"):
        c[k] = text(data.get(k))
    c["state"] = text(data.get("state"), "active")   # an unreadable state keeps the protection on
    return c


def read_claim(claim_id: str) -> Optional[dict[str, Any]]:
    """The claim dict (fields forced to their schema types), or None when the id is invalid, the file is
    missing, unreadable, hostile (deeply nested JSON raises RecursionError, bad UTF-8 raises ValueError) or not
    a JSON object."""
    if not valid_id(claim_id):
        return None
    try:
        data = json.loads((claims_dir() / f"{claim_id}.json").read_text(encoding="utf-8"))
        return _sanitize(data, claim_id) if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 - one bad file must not blind the guard to every other claim
        return None


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


def _update_unlocked(claim_id: str, **fields: Any) -> Optional[dict[str, Any]]:
    c = read_claim(claim_id)
    if c is None:
        return None
    c.update(fields)
    write_claim(c)
    return c


def update_claim(claim_id: str, **fields: Any) -> Optional[dict[str, Any]]:
    """Read-modify-write under the registry lock. None when the claim does not exist."""
    with _claims_lock():
        return _update_unlocked(claim_id, **fields)


def set_state(claim_id: str, state: str) -> Optional[dict[str, Any]]:
    """active|released|merged; released and merged stamp released_at, active clears it. Re-activating a claim
    applies the create_claim path rule under the lock: another owner's active claim on the path raises
    PathClaimed; the same owner's older active record of that path is released."""
    if state not in STATES:
        raise ValueError(f"invalid state {state!r}; one of {', '.join(STATES)}")
    with _claims_lock():
        c = read_claim(claim_id)
        if c is None:
            return None
        if state == "active":
            mine = _owner_keys(c)
            older: list[str] = []
            for o in list_claims("active"):
                if o.get("id") != c.get("id") and _same_path(o.get("path"), c.get("path")):
                    if mine and mine & _owner_keys(o):
                        older.append(str(o.get("id")))
                    else:
                        raise PathClaimed(f"{c.get('path')} is already claimed by {o.get('id')!r} ({owner_label(o)})")
            for oid in older:
                _update_unlocked(oid, state="released", released_at=utc_now())
        return _update_unlocked(claim_id, state=state, released_at=None if state == "active" else utc_now())


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


_DEFAULT_PORTS = {"https": "443", "http": "80", "ssh": "22", "git": "9418", "ftp": "21"}
_ORIGIN_ALIASES = {"ssh.github.com:443": "github.com"}   # verified aliases; no other host or port is treated as equal


def normalize_origin(url: str) -> str:
    """https://h/a/b.git, ssh://git@h/a/b and git@h:a/b.git all become h/a/b (lower case). A scheme's default
    port is dropped (https://h:443/x is https://h/x); ssh.github.com:443 is github.com; any other host or port
    spelling stays distinct."""
    u = (url or "").strip()
    scheme = ""
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*)://", u)
    if m:
        scheme, u = m.group(1).lower(), u[m.end():]
    u = re.sub(r"^[^@/]*@", "", u)
    if scheme:
        hostport, sep, rest = u.partition("/")
        port = _DEFAULT_PORTS.get(scheme)
        if port and hostport.endswith(":" + port):
            hostport = hostport[: -len(port) - 1]
        u = _ORIGIN_ALIASES.get(hostport.lower(), hostport) + sep + rest
    else:
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


def _slurp(path: str | os.PathLike[str]) -> str:
    """Text of a small file; undecodable bytes become U+FFFD instead of raising (a poisoned HEAD or pointer must
    never crash the guard into its fail-open path)."""
    return Path(path).read_text(encoding="utf-8", errors="replace")


def workspace_for_gitdir(gitdir: str | os.PathLike[str], fallback_root: Optional[str | os.PathLike[str]] = None) -> Optional[Workspace]:
    """The workspace a git dir belongs to: `<root>/.git`, a linked worktree's `<common>/worktrees/<n>` (root from
    its `gitdir` file), a gitfile (GIT_DIR may name one), else `fallback_root` (a bare repository's cwd)."""
    try:
        g = Path(gitdir).resolve()
        if g.is_file():
            line = _slurp(g).strip()
            if not line.startswith("gitdir:"):
                return None
            t = Path(line[len("gitdir:"):].strip())
            g = (t if t.is_absolute() else g.parent / t).resolve()
    except OSError:
        return None
    linked = (g / "commondir").exists()
    root: Optional[Path] = None
    if g.name == ".git":
        root = g.parent
    elif linked:
        with contextlib.suppress(OSError):
            root = Path(_slurp(g / "gitdir").strip()).parent
    if root is None:
        root = Path(fallback_root).resolve() if fallback_root else g
    return Workspace(root, g, linked)


def find_workspace(start: str | os.PathLike[str], gitdir_override: Optional[str] = None) -> Optional[Workspace]:
    """Walk up from `start` to the first `.git` (directory, or a `gitdir:` file of a linked worktree)."""
    try:
        p = Path(start).resolve()
    except OSError:
        return None
    if gitdir_override:
        g = Path(gitdir_override)
        return workspace_for_gitdir(g if g.is_absolute() else p / g, p)
    for d in (p, *p.parents):
        g = d / ".git"
        try:
            if g.is_dir():
                return Workspace(d, g, (g / "commondir").exists())
            if g.is_file():
                line = _slurp(g).strip()
                if line.startswith("gitdir:"):
                    gd = Path(line[len("gitdir:"):].strip())
                    gd = (gd if gd.is_absolute() else d / gd).resolve()
                    return Workspace(d, gd, (gd / "commondir").exists())
        except OSError:
            continue
    return None


def read_pointer(ws: Workspace) -> Optional[str]:
    try:
        v = _slurp(ws.pointer).strip()
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
    (cow copies `.git`, pointer included, into a new pasture). With `active_only` the pointer's claim wins when it
    is active; otherwise (released, merged, missing, copied) the registry is scanned by path for ACTIVE claims, so
    a stale pointer never hides a newer active record of the same path. The newest active record wins."""
    pid = read_pointer(ws)
    pc: Optional[dict[str, Any]] = None
    if pid:
        c = read_claim(pid)
        if c is not None and _same_path(c.get("path"), ws.root):
            pc = c
    if pc is not None and (not active_only or claim_state_active(pc)):
        return pc
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


def _origin_matches(claim_origin: str, urls: Iterable[str]) -> bool:
    """True when a claim of `claim_origin` can be in the repository the push `urls` reach: either side unknown, or
    the normalised origins are equal. Empty `urls` (nothing known) matches everything."""
    want = [w for w in (normalize_origin(u) for u in urls) if w]
    co = normalize_origin(claim_origin)
    return not want or not co or co in want


def claims_for_branch(branch: str, origin: str | Iterable[str] = "") -> list[dict[str, Any]]:
    """Active claims on `branch`; with `origin` (one URL or several), only claims of that repository (or of
    unknown origin)."""
    urls = [origin] if isinstance(origin, str) else list(origin)
    return [c for c in list_claims("active")
            if c.get("branch") == branch and _origin_matches(str(c.get("repo_origin") or ""), urls)]


def repo_worktrees(ws: Workspace) -> list[tuple[Path, Path]]:
    """(root, git-dir) of the main worktree and every registered linked worktree of ws's repository."""
    common = ws.gitdir
    try:
        common = (ws.gitdir / _slurp(ws.gitdir / "commondir").strip()).resolve()
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
            out.append((Path(_slurp(e / "gitdir").strip()).parent, e))
        except OSError:
            continue
    return out


def _head_branch(gitdir: Path) -> str:
    try:
        head = _slurp(gitdir / "HEAD").strip()
    except OSError:
        return ""
    return head[len("ref: refs/heads/"):] if head.startswith("ref: refs/heads/") else ""


# --------------------------------------------------------------------------------------------
# guard: argv parsing
# --------------------------------------------------------------------------------------------

READONLY = frozenset("""status diff log show ls-files ls-tree rev-parse cat-file blame grep ls-remote describe
merge-base version help rev-list show-ref for-each-ref shortlog whatchanged diff-tree diff-index diff-files name-rev
check-ignore check-attr check-ref-format var cherry range-diff count-objects show-branch merge-tree archive
format-patch verify-commit verify-tag""".split())
# The write commands the rules know by name; anything else is looked up as an alias first.
KNOWN_WRITE = frozenset("""commit add rm mv merge rebase pull push cherry-pick revert am apply checkout switch restore reset
clean stash tag branch config remote worktree init clone submodule gc prune update-ref symbolic-ref notes bisect fetch
reflog sparse-checkout maintenance bundle replace filter-branch""".split())
GLOBAL_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env"}
GLOBAL_FLAG = {"--no-pager", "-p", "--paginate", "--no-optional-locks", "--no-replace-objects",
               "--literal-pathspecs", "--glob-pathspecs", "--noglob-pathspecs", "--icase-pathspecs", "--bare",
               "--no-lazy-fetch", "--no-advice"}


def _ckey(key: str) -> str:
    """git lower-cases a config key's section and variable name, never its subsection."""
    first, dot, rest = key.partition(".")
    if not dot:
        return key.lower()
    mid, dot2, last = rest.rpartition(".")
    return f"{first.lower()}.{mid}.{last.lower()}" if dot2 else f"{first.lower()}.{rest.lower()}"


@dataclasses.dataclass
class GitCall:
    """One parsed git call. Everything git reads late is kept as typed and resolved late, as git does:
    `gitdir` and `worktree` (--git-dir/--work-tree, else GIT_DIR/GIT_WORK_TREE) are relative to `cwd`, the directory
    once EVERY `-C` has been applied, whatever their position on the command line."""
    cwd: str
    gitdir: Optional[str]
    sub: str
    args: list[str]
    config: list[tuple[str, str]]       # every -c / --config-env / GIT_CONFIG_* entry IN ORDER, repeats kept
    worktree: Optional[str] = None
    nglobal: int = 0                    # index of the subcommand in the original argv
    env: dict[str, str] = dataclasses.field(default_factory=dict)   # GIT_CONFIG_GLOBAL/SYSTEM/NOSYSTEM/GIT_CONFIG in force

    def display(self) -> str:
        return f"git {self.sub}".rstrip()

    def cfg_all(self, key: str) -> list[str]:
        k = _ckey(key)
        return [v for kk, v in self.config if kk == k]

    def cfg(self, key: str) -> Optional[str]:
        vals = self.cfg_all(key)
        return vals[-1] if vals else None

    def cfg_argv(self) -> list[str]:
        return [x for k, v in self.config for x in ("-c", f"{k}={v}")]

    def gitdir_path(self) -> Optional[str]:
        return os.path.join(self.cwd, self.gitdir) if self.gitdir else None

    def worktree_path(self) -> Optional[str]:
        return os.path.join(self.cwd, self.worktree) if self.worktree else None


_CONFIG_FILE_ENV = ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG")


def _env_config(env: dict[str, str]) -> list[tuple[str, str]]:
    """Config git reads from the environment: GIT_CONFIG_COUNT/KEY_n/VALUE_n, then GIT_CONFIG_PARAMETERS."""
    out: list[tuple[str, str]] = []
    try:
        count = int(env.get("GIT_CONFIG_COUNT", "0") or 0)
    except ValueError:
        count = 0
    for n in range(max(0, min(count, 256))):
        k = env.get(f"GIT_CONFIG_KEY_{n}")
        if k:
            out.append((_ckey(k), env.get(f"GIT_CONFIG_VALUE_{n}", "")))
    params = env.get("GIT_CONFIG_PARAMETERS", "")
    if params:
        try:
            for item in shlex.split(params):
                k, eq, v = item.partition("=")
                out.append((_ckey(k), v if eq else "true"))
        except ValueError:
            pass
    return out


def parse_git_argv(argv: Sequence[str], cwd: str, env: Optional[dict[str, str]] = None) -> GitCall:
    """Split git's global options from `<subcommand> <args>`, in order: `-C` is cumulative, `-c` and --config-env
    append to an ordered multi-valued list (after GIT_CONFIG_* from `env`), --git-dir/--work-tree override
    GIT_DIR/GIT_WORK_TREE from `env` (last wins)."""
    env = os.environ if env is None else env
    cur = cwd
    gitdir: Optional[str] = env.get("GIT_DIR") or None
    worktree: Optional[str] = env.get("GIT_WORK_TREE") or None
    config = _env_config(env)
    i, n = 0, len(argv)
    while i < n:
        a = argv[i]
        if a == "-C" and i + 1 < n:
            cur = os.path.join(cur, argv[i + 1])
            i += 2
        elif a == "-c" and i + 1 < n:
            k, eq, v = argv[i + 1].partition("=")
            config.append((_ckey(k), v if eq else "true"))
            i += 2
        elif a.startswith("-c") and len(a) > 2 and a[2] != "-":
            k, eq, v = a[2:].partition("=")
            config.append((_ckey(k), v if eq else "true"))
            i += 1
        elif a.startswith("-C") and len(a) > 2 and a[2] != "-":
            cur = os.path.join(cur, a[2:])
            i += 1
        elif a in ("--git-dir", "--work-tree") and i + 1 < n:
            if a == "--git-dir":
                gitdir = argv[i + 1]
            else:
                worktree = argv[i + 1]
            i += 2
        elif a.startswith("--git-dir="):
            gitdir = a.split("=", 1)[1]
            i += 1
        elif a.startswith("--work-tree="):
            worktree = a.split("=", 1)[1]
            i += 1
        elif a == "--config-env" and i + 1 < n or a.startswith("--config-env="):
            spec = argv[i + 1] if a == "--config-env" else a.split("=", 1)[1]
            k, _, var = spec.partition("=")
            config.append((_ckey(k), env.get(var, "")))
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
    return GitCall(cur, gitdir, sub, list(argv[i + 1:]), config, worktree, i,
                   {k: v for k, v in env.items() if k in _CONFIG_FILE_ENV})


@dataclasses.dataclass
class Scan:
    shorts: set[str]
    longs: set[str]     # expanded: an abbreviated option contributes the option(s) it may stand for
    pos: list[str]
    after: list[str]    # everything after a bare `--`
    seq: list[set[str]]  # every option in command-line order: expanded long names, and "-x" for a short x


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
                    seq.append({"-" + ch})
                    if j == len(cl) - 1:
                        i += 1
                    break
                if ch in attached_short:
                    seq.append({"-" + ch})
                    break
                shorts.add(ch)
                seq.append({"-" + ch})
        else:
            pos.append(a)
        i += 1
    return Scan(shorts, longs, pos, after, seq)


def _state(s: Scan, on: Iterable[str], off: Iterable[str], off_wins: bool = True) -> bool:
    """Whether an option is in effect after ALL of the command line, in order: any name in `on` switches it on,
    any in `off` (`--no-x`) switches it off. An abbreviation that may stand for either goes the way `off_wins`
    says (True for a safe flag: unproven means not in effect; False for a dangerous one)."""
    on, off = set(on), set(off)
    state = False
    for names in s.seq:
        hit_on, hit_off = bool(names & on), bool(names & off)
        if hit_on and hit_off:
            state = not off_wins
        elif hit_on:
            state = True
        elif hit_off:
            state = False
    return state


def _with_negations(names: Iterable[str]) -> set[str]:
    """Every `--x` of a table also has `--no-x` in git (a negation must be a known name, or an abbreviation of
    it reads as unknown and the rule treats it as unrelated)."""
    s = set(names)
    return s | {"no-" + n for n in s if not n.startswith("no-")}


# option tables for the "safe" names a rule lets through (a unique prefix of one counts as it)
T_CLEAN = _with_negations({"dry-run", "exclude", "force", "interactive", "quiet"})
T_RESTORE = _with_negations({"conflict", "ignore-skip-worktree-bits", "ignore-unmerged", "inter-hunk-context", "merge",
                             "ours", "overlay", "patch", "pathspec-file-nul", "pathspec-from-file", "progress", "quiet",
                             "recurse-submodules", "source", "staged", "theirs", "unified", "worktree"})
T_RM = _with_negations({"cached", "dry-run", "force", "ignore-unmatch", "pathspec-file-nul", "pathspec-from-file",
                        "quiet", "sparse"})
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


_FETCH_SAFE_DST = ("refs/remotes/", "refs/tags/")


def fetch_local_dsts(call: GitCall) -> Optional[list[str]]:
    """The destinations a `fetch` writes outside refs/remotes/ and refs/tags/ (`origin +main:wbr` -> `wbr`,
    `. +x:refs/heads/y` -> `refs/heads/y`; a `-c remote.<n>.fetch` mapping counts), or None when the call may
    update ANY local branch (`--update-head-ok`/-u also lets it overwrite the checked-out branch, `--refmap`).
    [] means it only updates remote-tracking refs and tags."""
    s = scan(call.args, value_short="oj", value_long={"depth", "deepen", "shallow-since", "shallow-exclude", "upload-pack",
                                                     "server-option", "negotiation-tip", "refmap", "jobs", "filter",
                                                     "submodule-prefix", "recurse-submodules-default", "set-upstream"},
             danger={"update-head-ok", "refmap"})
    if s.shorts & {"u"} or s.longs & {"update-head-ok", "refmap"}:
        return None
    pos = s.pos + s.after
    specs = [] if s.longs & {"all", "multiple"} else pos[1:]
    specs += [v for k, v in call.config if k.startswith("remote.") and k.endswith(".fetch")]
    out: list[str] = []
    for p in specs:
        if ":" in p:
            dst = p.lstrip("+").partition(":")[2]
            if dst and not dst.startswith(_FETCH_SAFE_DST):
                out.append(dst)
    return out


def _fetch_is_readonly(call: GitCall) -> bool:
    """`fetch` is read-only only when it updates nothing but remote-tracking refs and tags."""
    return fetch_local_dsts(call) == []


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
        s = scan(args, value_short="m", danger={"delete"})
        return len(s.pos) < 2 and "d" not in s.shorts and "delete" not in s.longs
    if sub == "fetch":
        return _fetch_is_readonly(call)
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


def _git_cfg_bool(call: GitCall, key: str) -> bool:
    """The call's EFFECTIVE boolean config (its own -c/--config-env/GIT_CONFIG_* and include flags, then the
    repository's and the user's files), as git itself reads it."""
    return _call_git(call, "config", "--type=bool", "--get", key)[1].strip() == "true"


def _pull_rebases(call: GitCall) -> bool:
    """Whether `git pull` rebases instead of merging: the last --rebase/--no-rebase on the command line, else
    pull.rebase, else any branch.<n>.rebase (fail closed: any truthy one counts)."""
    state: Optional[bool] = None
    for a in call.args:
        if a == "--":
            break
        if a == "-r":
            state = True
        elif a.startswith("--"):
            name, eq, val = a[2:].partition("=")
            if len(name) >= 3 and "rebase".startswith(name):
                state = (val.lower() not in ("false", "no", "off", "0")) if eq else True
            elif len(name) >= 4 and "no-rebase".startswith(name):
                state = False
    if state is not None:
        return state
    rc, out = _call_git(call, "config", "--get", "pull.rebase")
    if out.strip():
        return out.strip().lower() not in ("false", "no", "off", "0")
    rc, out = _call_git(call, "config", "--type=bool", "--get-regexp", r"^branch\..*\.rebase$")
    return any(line.split()[-1:] == ["true"] for line in out.splitlines())


def _autostash(call: GitCall) -> bool:
    """Autostash is on for this pull/rebase/merge: the last --autostash/--no-autostash on the command line wins;
    without either, the config key of what the command actually does (rebase.autoStash for a rebase or a
    pull that rebases, merge.autoStash for a merge or a pull that merges)."""
    s = scan(call.args, value_short="sXmFxC", value_long={"strategy", "strategy-option", "onto", "exec", "message", "file"},
             danger={"autostash"}, table=T_STASHING)
    if any(names & {"autostash", "no-autostash"} for names in s.seq):
        return _state(s, {"autostash"}, {"no-autostash"}, off_wins=False)
    if call.sub == "rebase":
        key = "rebase.autostash"
    elif call.sub == "merge":
        key = "merge.autostash"
    else:
        key = "rebase.autostash" if _pull_rebases(call) else "merge.autostash"
    return _git_cfg_bool(call, key)


def _is_pathspec(arg: str, cwd: str) -> bool:
    return arg in (".", "./", ":/") or arg.startswith(":") or any(c in arg for c in "*?[") or \
        os.path.exists(os.path.join(cwd, arg))


def shared_destructive(call: GitCall) -> Optional[Rule]:
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
                 danger={"force", "patch", "pathspec-from-file"})
        if s.shorts & set("fp") or s.longs & {"force", "patch", "pathspec-from-file"} or s.after or len(s.pos) >= 2 or \
                any(_is_pathspec(p, call.cwd) for p in s.pos):
            return Rule("checkout <path>", "`git switch <branch>` to change branch; `git diff` to inspect; never "
                                           "overwrite paths in a shared checkout (`git checkout <file>` discards a "
                                           "peer's edit of it)")
    elif sub == "restore":
        s = scan(args, value_short="s", value_long={"source", "pathspec-from-file"}, danger={"worktree", "no-staged"},
                 table=T_RESTORE)
        staged = _state(s, {"staged", "-S"}, {"no-staged"}, off_wins=True)
        worktree = _state(s, {"worktree", "-W"}, {"no-worktree"}, off_wins=False)
        if not staged or worktree:
            return Rule("restore", "`git restore --staged <path>` only unstages; to discard work, do it in your "
                                   "own workspace")
    elif sub == "switch":
        s = scan(args, value_short="cCt", value_long={"create", "force-create", "track", "orphan"},
                 danger={"force", "discard-changes"})
        if s.shorts & {"f"} or s.longs & {"force", "discard-changes"}:
            return Rule("switch -f", "`git switch <branch>` without -f, or commit first, in your own workspace")
    elif sub == "clean":
        s = scan(args, value_short="e", value_long={"exclude"}, danger={"no-dry-run"}, table=T_CLEAN)
        if not _state(s, {"dry-run", "-n"}, {"no-dry-run"}, off_wins=True):
            return Rule("clean", "`git clean -n` (dry run) and delete the named files yourself, in your own workspace "
                                 "(`clean -i` is refused too: it deletes what a peer left untracked)")
    elif sub == "rm":
        s = scan(args, value_long={"pathspec-from-file"}, danger={"force", "no-cached", "no-dry-run"}, table=T_RM)
        force = _state(s, {"force", "-f"}, {"no-force"}, off_wins=False)
        harmless = _state(s, {"cached"}, {"no-cached"}, off_wins=True) or \
            _state(s, {"dry-run", "-n"}, {"no-dry-run"}, off_wins=True)
        if force and not harmless:
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
        if _autostash(call):
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


def _run_git(args: Sequence[str], timeout: int = 10, env_extra: Optional[dict[str, str]] = None) -> tuple[int, str]:
    """Run the real git with stdout captured (decoded with replacement, so a hostile byte never raises), its own
    stdin closed and its own process group: on timeout the WHOLE group (hooks, credential helpers, ssh) is killed.
    (127, "") when it cannot start, (124, partial output) on timeout."""
    import signal
    import subprocess
    try:
        p = subprocess.Popen([real_git(), *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, env={**os.environ, **(env_extra or {}), "GIT_TERMINAL_PROMPT": "0"},
                             start_new_session=True)
    except (OSError, ValueError):
        return 127, ""
    rc = 124
    try:
        out, _ = p.communicate(timeout=timeout)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            os.killpg(p.pid, signal.SIGKILL)
        try:
            out, _ = p.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            out = b""
    return rc, (out or b"").decode("utf-8", "replace")


def _git_out(root: Path, *args: str) -> str:
    rc, out = _run_git(["-C", str(root), *args])
    return out.strip() if rc == 0 else ""


def _call_git(call: GitCall, *args: str, timeout: int = 10) -> tuple[int, str]:
    """A helper git run under the call's own global options, config and config-file environment."""
    return _run_git([*_globals(call), *args], timeout, call.env)


def _globals(call: GitCall) -> list[str]:
    """The call's own global options in git's order, for a helper git run: `-C` the final cwd, every -c in order
    (repeats kept), --git-dir and --work-tree as typed (relative to that cwd, as git reads them)."""
    g = ["-C", call.cwd, *call.cfg_argv()]
    if call.gitdir:
        g += ["--git-dir", call.gitdir]
    if call.worktree:
        g += ["--work-tree", call.worktree]
    return g


# --------------------------------------------------------------------------------------------
# guard: push destinations
# --------------------------------------------------------------------------------------------

PUSH_SAFETY = ["--dry-run", "--porcelain", "--no-verify", "--no-quiet"]   # --no-quiet: `push -q` prints no ref lines


def push_cancels_preflight(args: Sequence[str]) -> Optional[str]:
    """The first option that is `--no-dry-run`/`--no-porcelain` or any abbreviation of one (git takes any unique
    prefix, `--no-d`; an ambiguous one is an error there but refused here all the same). The preflight must never
    be able to push, so a call carrying one is refused before git runs at all."""
    for a in args:
        if a == "--":
            break
        if a.startswith("--"):
            name = a[2:].partition("=")[0]
            if name and any(t.startswith(name) for t in ("no-dry-run", "no-porcelain")):
                return a
    return None


def push_preflight_argv(call: GitCall) -> list[str]:
    """git's own dry run of this push. The safety options come BEFORE and AFTER every option the caller gave (so no
    caller option can cancel them, and an option of the caller's that lacks its value and swallows the next token
    cannot swallow the first copy) and before the `--` separator. --no-verify keeps pre-push hooks from running."""
    args = list(call.args)
    cut = args.index("--") if "--" in args else len(args)
    return [*_globals(call), "push", *PUSH_SAFETY, *args[:cut], *PUSH_SAFETY, *args[cut:]]


def _porcelain_destinations(out: str) -> Optional[tuple[list[str], list[str]]]:
    """(destination branch names, URLs) of a COMPLETE `push --porcelain` output, or None. Complete = every remote
    block is `To <url>`, ref lines (`<flag>\t<src>:<dst>\t<summary>`, one per mapped ref, rejected ones included)
    and git's closing `Done`; a line outside a block, a tab-separated line that is not a ref line, a block that never
    closed or no block at all means some ref may be missing from what was read (prose inside a block, such as
    `Would set upstream of ...` for -u, names no ref and is skipped)."""
    urls: list[str] = []
    dests: list[str] = []
    open_block, closed = False, 0
    for line in out.splitlines():
        if not line.strip():
            continue
        if line.startswith("To "):
            if open_block:
                return None
            urls.append(line[3:].strip())
            open_block = True
            continue
        if line == "Done":
            if not open_block:
                return None
            open_block = False
            closed += 1
            continue
        if open_block and "\t" not in line:
            continue                      # prose git prints inside a block (`Would set upstream of ...`): no ref
        parts = line.split("\t")
        if not open_block or len(parts) < 3 or parts[0] not in (" ", "+", "-", "*", "=", "!") or ":" not in parts[1]:
            return None
        dst = parts[1].split(":", 1)[1]
        if dst.startswith("refs/heads/"):
            dests.append(dst[len("refs/heads/"):])
    if open_block or not closed:
        return None
    return dests, urls


def push_destinations(call: GitCall) -> tuple[Optional[list[str]], list[str]]:
    """(destination branch names, effective push URLs) of a `git push` call, both from git's own
    `push --dry-run --porcelain` under the call's own config (every -c, repeats and order kept; url.<base>.insteadOf,
    pushurl, pushDefault, branch.<n>.pushRemote, push.default, `@`, `heads/x`, wildcard and --mirror/--all/deletion
    refspecs all resolved by git). (None, []) = UNRESOLVED: the dry run did not finish (a timeout, rc 124, or any
    status other than 0 and 1: no remote, no such repository, usage error), printed no `To` line, or its output is
    not complete (no closing `Done`, a malformed ref line), so a mapped ref may be missing from what was read.
    Status 1 is git's answer for "some ref would be rejected" (non-fast-forward): its porcelain lists EVERY mapped
    ref, the rejected ones with `!`, so a complete listing is read; a partial one is not. The caller decides what
    unresolved means; nothing is guessed from the command line. Contacts the remote like any push (its transport,
    credential helper and ssh command run; pre-push hooks do not)."""
    rc, out = _run_git(push_preflight_argv(call), timeout=20, env_extra=call.env)
    parsed = _porcelain_destinations(out) if rc in (0, 1) else None
    if parsed is None:
        return None, []
    return parsed[0], parsed[1]


# --------------------------------------------------------------------------------------------
# guard: decisions
# --------------------------------------------------------------------------------------------

def _git_says(call: GitCall) -> tuple[str, Optional[str], Optional[str]]:
    """Where git itself says the call lands, under the call's own ordered `-C`/`-c`/--git-dir/--work-tree and
    config-file environment (`rev-parse --absolute-git-dir --show-toplevel`: core.worktree with comments, escapes,
    includes and relative paths, GIT_WORK_TREE after any chain of -C are all git's to read, never ours):
    ("ok", gitdir, toplevel); ("bare", gitdir, None) a repository with no work tree; ("none", None, None) git finds
    no repository; ("unknown", None, None) git could not answer (timeout, cannot start, output not understood)."""
    rc, out = _call_git(call, "rev-parse", "--absolute-git-dir", "--show-toplevel")
    lines = out.splitlines()
    if rc == 0 and len(lines) == 2 and all(os.path.isabs(x) for x in lines):
        return "ok", lines[0], lines[1]
    if rc == 128 and len(lines) == 1 and os.path.isabs(lines[0]):
        return "bare", lines[0], None
    if rc == 128 and not lines:
        return "none", None, None
    return "unknown", None, None


def call_workspaces(call: GitCall) -> tuple[list[Optional[Workspace]], bool]:
    """(every workspace the call can change, unresolved). git is asked (`_git_says`): the work tree it names with
    its git dir first, then the workspace of the directory the files live in and of the repository that owns the
    refs (they differ under GIT_WORK_TREE / core.worktree / --git-dir). Only when git cannot answer or finds no
    repository are the TYPED values used (--git-dir/GIT_DIR, --work-tree/GIT_WORK_TREE, `-c core.worktree`, the cwd
    when a git dir was named, else the one discovered from the cwd), relative to the cwd after every -C; `unresolved`
    is then true only when git could not answer at all, and the caller refuses what changes anything while another
    agent holds a claim. [None] when no repository exists."""
    status, gd, top = _git_says(call)
    cands: list[Optional[Workspace]] = []
    if status == "ok" and gd and top:
        cands = [Workspace(Path(top), Path(gd), (Path(gd) / "commondir").exists()), find_workspace(top),
                 workspace_for_gitdir(gd, top)]
    elif status == "bare" and gd:
        cands = [workspace_for_gitdir(gd, call.cwd)]
    else:
        gd_path = call.gitdir_path()
        gd_ws = workspace_for_gitdir(gd_path, call.cwd) if gd_path else find_workspace(call.cwd)
        wt_path = call.worktree_path()
        if wt_path is None:
            core = call.cfg("core.worktree")
            if core:
                wt_path = os.path.join(str(gd_ws.gitdir) if gd_ws is not None else call.cwd, core)
            elif gd_path:
                wt_path = call.cwd
        cands = [find_workspace(wt_path) if wt_path else None, gd_ws]
    out: list[Workspace] = []
    for w in cands:
        if w is not None and not any(_same_path(w.root, x.root) and _same_path(w.gitdir, x.gitdir) for x in out):
            out.append(w)
    return (list(out) if out else [None]), status == "unknown"


def _foreign(claim: dict[str, Any], rule: str, alt: str) -> Decision:
    return Decision(False, rule, alt, str(claim.get("id") or ""), owner_label(claim))


BANG_ALT = {"shell alias": "a `!` alias runs a shell that reaches the real git past this guard; spell the git "
                           "commands out",
            "alias chain": "the alias chain is too deep (or loops) for the guard to resolve; spell the git command out"}


def _ws_decision(call: GitCall, ws: Optional[Workspace], ident: Optional[str], bang: str) -> Optional[Decision]:
    claim = find_claim(ws) if ws else None
    if claim is not None and not is_mine(claim, ident):
        if not is_readonly(call):
            return _foreign(claim, "foreign-claim", FOREIGN_ALT)
        return None
    linked = bool(ws and ws.linked)
    rule: Optional[Rule] = None
    if claim is None:
        rule = shared_destructive(call)
    elif linked:
        rule = stash_rule(call) or _rebase_exec_rule(call)
    if rule is None and bang and (claim is None or linked):
        rule = Rule(bang, BANG_ALT[bang])
    if rule is None:
        return None
    where = "a shared checkout (no active claim)" if claim is None else "a linked worktree (shared refs/stash)"
    return Decision(False, rule.name, rule.alt, str((claim or {}).get("id") or ""),
                    owner_label(claim) if claim else f"nobody; {where}")


def _worktree_targets(call: GitCall, ws0: Optional[Workspace], token: str) -> list[Path]:
    """The registered worktree(s) a `worktree remove|move <token>` selector can mean. git first takes a trailing run
    of whole path components that is unique in its worktree list (`W` for /x/W, even when ./W does not exist), then
    a path. Every candidate is returned (an ambiguous selector fails closed); an unregistered path stands for
    itself."""
    roots = [r for r, _ in repo_worktrees(ws0)] if ws0 is not None else []
    tok = token.strip("/")
    hits = [r for r in roots if tok and not os.path.isabs(token) and str(r).endswith("/" + tok)]
    p = os.path.join(call.cwd, token)
    hits += [r for r in roots if _same_path(r, p) and r not in hits]
    return hits or [Path(p)]


def _foreign_claim_in_repo(ws0: Optional[Workspace], ident: Optional[str]) -> Optional[dict[str, Any]]:
    """An active claim of someone else in the repository of `ws0` (a claim on one of its worktrees, or one whose
    origin is this repository's or unknown), or None."""
    if ws0 is None:
        return None
    origin = _git_out(ws0.root, "config", "--get", "remote.origin.url")
    roots = [r for r, _ in repo_worktrees(ws0)]
    for c in list_claims("active"):
        if is_mine(c, ident):
            continue
        if _origin_matches(str(c.get("repo_origin") or ""), [origin]) or any(_same_path(c.get("path"), r) for r in roots):
            return c
    return None


def _output_decision(call: GitCall, out: str, ident: Optional[str]) -> Optional[Decision]:
    """An output file (`--output=`, `-o`) is judged by the workspace of the file it REALLY writes: its own symlink
    (even dangling) is resolved before its parent is taken. Into a claimed workspace of someone else: refused;
    over an existing dirty (modified or untracked) file of a shared checkout: refused."""
    tp = Path(os.path.realpath(os.path.join(call.cwd, out)))
    tws = find_workspace(tp if tp.is_dir() else tp.parent)
    if tws is None:
        return None
    c = find_claim(tws)
    if c is not None:
        if not is_mine(c, ident):
            return _foreign(c, "output into a claimed workspace", "write the file outside the other agent's workspace")
        return None
    if tp.is_file() and _git_out(tws.root, "status", "--porcelain", "--", str(tp)):
        return Decision(False, "output over a dirty file", "write the file outside the shared checkout, or to a new "
                        "name; this one holds uncommitted work", "", "nobody; a shared checkout (no active claim)")
    return None


def _target_decision(call: GitCall, wss: list[Optional[Workspace]], ident: Optional[str]) -> Optional[Decision]:
    """Rule 5: the claim of what the call HITS, not of where it runs."""
    sub, args = call.sub, call.args
    ws0 = next((w for w in wss if w is not None), None)
    if sub == "worktree" and args and args[0] in ("remove", "move", "prune"):
        verb = args[0]
        s = scan(args[1:], value_long={"expire", "reason"}, danger={"force"})
        force = bool(s.shorts & {"f"} or s.longs & {"force"})
        targets: list[Path] = []
        if verb in ("remove", "move") and s.pos:
            targets = _worktree_targets(call, ws0, s.pos[0])
        elif verb == "prune" and ws0 is not None:
            targets = [r for r, _ in repo_worktrees(ws0) if not r.exists()]
        for t in targets:
            c = claim_at(t)
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
        s = scan(args, value_short="m", value_long={"stdin"}, danger={"stdin"})
        if "stdin" in s.longs:
            c = _foreign_claim_in_repo(ws0, ident)
            if c is not None:
                return _foreign(c, "update-ref --stdin with claims in this repository",
                                "name the ref on the command line (`git update-ref refs/heads/<your-branch> <sha>`); "
                                "a ref transaction on stdin cannot be inspected, and another agent's branch is claimed")
        elif s.pos and s.pos[0].startswith("refs/heads/"):
            names = [s.pos[0][len("refs/heads/"):]]
    elif sub == "fetch":
        dsts = fetch_local_dsts(call)
        if dsts is None or any("*" in d for d in dsts):
            c = _foreign_claim_in_repo(ws0, ident)       # may update any local branch: judged as a whole
            if c is not None:
                return _foreign(c, "fetch into local branches with claims in this repository",
                                "plain `git fetch <remote>` updates only remote-tracking refs; never force a fetch "
                                "into a local branch while another agent holds a claim here")
        names = [d[len("refs/heads/"):] if d.startswith("refs/heads/") else d for d in dsts or [] if "*" not in d]
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
    for o in output_targets(call) or []:
        d = _output_decision(call, o, ident)
        if d is not None:
            return d
    return None


def _push_decision(call: GitCall, ident: Optional[str]) -> Optional[Decision]:
    """push is refused when a destination branch has an active claim that is not the caller's. The destinations
    and URLs are git's own (push_destinations). Unresolvable: refused while anyone else holds an active claim
    (the claimed branch cannot be ruled out), allowed otherwise (nothing exists to protect; a real push that
    cannot resolve fails by itself)."""
    bad = push_cancels_preflight(call.args)
    if bad:
        return Decision(False, "push-preflight-option", f"drop `{bad}`; the guard's own dry run needs --dry-run and "
                        "--porcelain in force, so a push that cancels them is refused", "", "nobody; not decidable")
    dests, urls = push_destinations(call)
    if dests is None:
        other = next((c for c in list_claims("active") if not is_mine(c, ident)), None)
        if other is None:
            return None
        return Decision(False, "push-destination-unresolved",
                        "git's own `push --dry-run` could not resolve where this push goes (remote unreachable or "
                        "unconfigured, it timed out, exited non-zero, or its output did not cover every ref) and "
                        "another agent holds an active claim, so a claimed branch cannot be ruled out; fix the "
                        "remote or name a refspec that resolves", "",
                        "nobody; destination unknown")
    for nm in dict.fromkeys(dests):
        for c in claims_for_branch(nm, urls):
            if not is_mine(c, ident):
                return _foreign(c, "push-foreign-branch",
                                f"push only your own branch; ask the owner to push (or to add you to the "
                                f"claim's allow list); branch {nm!r} is claimed")
    return None


MAX_ALIAS_DEPTH = 10


def evaluate(call: GitCall, env: Optional[dict[str, str]] = None, *, assume_agent: bool = False,
             _depth: int = 0) -> Decision:
    """Decide one git call. Reads claims; asks real git (with the call's own config) for an alias, a push
    destination or a branch's origin."""
    env = os.environ if env is None else env
    if not assume_agent and not is_agent_env(env):
        return ALLOW
    ident = caller_ident(env)
    approved = {x.strip() for x in env.get("ACP_OPERATOR_APPROVED", "").split(",") if x.strip()}
    wss, unresolved = call_workspaces(call)
    sub = call.sub
    bang = ""
    if sub and sub not in READONLY and sub not in KNOWN_WRITE:
        if _depth >= MAX_ALIAS_DEPTH:
            bang = "alias chain"          # fail closed: an unresolved name is treated as the worst alias
        else:
            rc, alias = _call_git(call, "config", "--get", f"alias.{sub}")
            alias = alias.strip() if rc == 0 else ""
            if alias.startswith("!"):
                bang = "shell alias"
            elif alias:
                try:
                    words = shlex.split(alias)
                except ValueError:
                    words = []
                if not words:
                    bang = "alias chain"
                else:
                    x = parse_git_argv([*words, *call.args], call.cwd, {})
                    return evaluate(GitCall(x.cwd, x.gitdir or call.gitdir, x.sub, x.args, [*call.config, *x.config],
                                            x.worktree or call.worktree, call.nglobal, call.env),
                                    env, assume_agent=assume_agent, _depth=_depth + 1)
    deny: Optional[Decision] = None
    for ws in wss:
        deny = _ws_decision(call, ws, ident, bang)
        if deny is not None:
            break
    if deny is None and unresolved and not is_readonly(call):
        other = next((c for c in list_claims("active") if not is_mine(c, ident)), None)
        if other is not None:      # git could not say where this lands: the target cannot be ruled out
            deny = _foreign(other, "workspace-unresolved",
                            "git could not say which repository and work tree this call changes (it timed out or "
                            "gave no answer) while another agent holds a claim; retry, or run it read-only")
    if deny is None:
        deny = _target_decision(call, wss, ident)
    if deny is None and sub == "push":
        deny = _push_decision(call, ident)
    if deny is None:
        return ALLOW
    ws_any = next((w for w in wss if w is not None), None)
    deny.detail = {"sub": sub, "cwd": str(ws_any.root if ws_any else call.cwd), "ident": ident or ""}
    if OVERRIDE in approved:
        deny.override = True
        deny.allowed = True
    return deny


# Option names that may appear in guard.log. Anything else is logged as `--?`: an option's VALUE (a message that
# starts with `--`, a token after `-m`) must never reach the log, so names are taken from this list only, and the
# token after an option that takes a value is skipped as that value.
_LOG_LONG = frozenset("""abort all allow-empty amend annotate author autosquash autostash branches cached cleanup
continue copy create date delete delete-branch detach discard-changes dry-run edit exec ff ff-only file follow-tags
force force-with-lease fixup hard interactive keep list merge message mirror mixed move no-autostash no-edit no-ff
no-track no-verify onto orphan ours output output-directory patch pathspec-from-file porcelain prune push-option quiet
rebase recurse-submodules reedit-message reset-author reuse-message set-upstream set-upstream-to signoff soft source
squash staged stdin strategy strategy-option tags template theirs track unset-upstream update verbose verify
worktree""".split())
_LOG_VALUE_OPTS = frozenset({"-m", "-F", "-C", "-c", "-t", "-o", "-u", "--message", "--file", "--author", "--date",
                             "--reuse-message", "--reedit-message", "--fixup", "--squash", "--template", "--cleanup",
                             "--exec", "--output", "--output-directory", "--onto", "--strategy", "--strategy-option",
                             "--source", "--pathspec-from-file", "--receive-pack", "--push-option", "--repo",
                             "--format", "--sort", "--upload-pack"})


def _log_flags(args: Sequence[str]) -> list[str]:
    out: list[str] = []
    i, n = 0, len(args)
    while i < n:
        a = args[i]
        if a == "--":
            break
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            out.append(name if name[2:] in _LOG_LONG else "--?")
            if "=" not in a and name in _LOG_VALUE_OPTS:
                i += 1
        elif a.startswith("-") and len(a) > 1:
            out.append(a[:2])
            if a in _LOG_VALUE_OPTS:
                i += 1
        i += 1
    return out[:12]


def _esc(value: Any) -> str:
    """Text safe to print on a terminal: control characters (newline, ESC, C1) become \\xNN."""
    return "".join(c if c.isprintable() else (f"\\x{ord(c):02x}" if ord(c) < 256 else f"\\u{ord(c):04x}")
                   for c in str(value))


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
    me = _esc(decision.detail.get("ident") or "no claim id")
    who = (f"  claim {_esc(decision.claim_id)}: {_esc(decision.owner)}; you are {me}.\n" if decision.claim_id
           else f"  {_esc(decision.owner)}; you are {me}.\n")
    return (f"ade-git-guard: REFUSED `{_esc(call.display())}` [{_esc(decision.rule)}] in "
            f"{_esc(decision.detail.get('cwd', call.cwd))}\n"
            + who +
            f"  Safe alternative: {_esc(decision.message)}.\n"
            f"  Ask the owner through session-finder/relay.py; exit 77 is an answer, not an obstacle to route around. "
            f"Logged in {_esc(guard_log_path())}.\n")


def _report(d: Decision, call: GitCall, extra: Optional[dict[str, Any]] = None) -> int:
    """Log and print a non-plain decision; returns 0 (override) or EXIT_REFUSED."""
    log_event(d, call, extra)
    if d.override:
        sys.stderr.write(f"ade-git-guard: ACP_OPERATOR_APPROVED={OVERRIDE}: allowed `{_esc(call.display())}` "
                         f"[{_esc(d.rule)}] (logged)\n")
        return 0
    sys.stderr.write(refusal_text(d, call))
    return EXIT_REFUSED


def guard_argv(argv: Sequence[str], env: Optional[dict[str, str]] = None, cwd: Optional[str] = None) -> int:
    """What ade-git-guard runs for a git call that was not plainly read-only. 0 = run real git, 77 = refused."""
    env = os.environ if env is None else env
    if env.get("GIT_INDEX_FILE") or env.get("PRE_COMMIT"):
        return 0
    try:
        base = cwd or os.getcwd()
    except OSError:
        base = os.sep     # a deleted cwd: an absolute -C still names the repository, a relative path cannot be judged
    call = parse_git_argv(argv, base, env)
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
_HD_END = " \t\r\n;&|()<>"                      # ends a heredoc delimiter word
_WRAP_VALUE = re.compile(r"^[0-9][0-9.]*[smhd]?$")   # `timeout 5s`, `nice -n 5`: a wrapper's number
_MENTIONS_GIT = re.compile(r"(?<![A-Za-z0-9_-])git(?![A-Za-z0-9_])")
_INLINE_GIT_ENV = re.compile(r"^(GIT_DIR|GIT_WORK_TREE|GIT_CONFIG_COUNT|GIT_CONFIG_PARAMETERS|GIT_CONFIG_KEY_\d+|"
                             r"GIT_CONFIG_VALUE_\d+|GIT_CONFIG_GLOBAL|GIT_CONFIG_SYSTEM|GIT_CONFIG_NOSYSTEM|GIT_CONFIG)$")
MAX_SHELL_DEPTH = 8


@dataclasses.dataclass
class Word:
    text: str
    dyn: bool = False    # holds an unexpanded variable, $(...) or backtick: its value is unknown
    glob: bool = False   # an unquoted * ? [ or {a,b} / {a..b}: the shell may expand it to another name


@dataclasses.dataclass
class Heredoc:
    delim: str
    strip: bool          # <<-
    quoted: bool         # a quoted or backslashed delimiter: the body is literal text, no substitutions
    body: str = ""


@dataclasses.dataclass
class Seg:
    """One simple command: its words, the control operator before and after it, the substitutions in its words,
    and the heredocs / here-strings attached to it."""
    words: list[Word]
    sep_before: str = ""
    sep_after: str = ""
    subs: list[str] = dataclasses.field(default_factory=list)
    heredocs: list[Heredoc] = dataclasses.field(default_factory=list)
    herestrings: list[str] = dataclasses.field(default_factory=list)


def _read_heredoc_op(s: str, j: int) -> tuple[str, bool, bool, int]:
    """The heredoc operator at s[j:] (`<<`, never `<<<`): (delimiter, strip, quoted, index after the word). The
    delimiter is the WORD after the operator with shell quote removal applied exactly as written (`E"OF"`, `E\\OF`,
    `'E OF'`, `"E"'O'F` all read as EOF / E OF), so the body ends where the shell ends it. `quoted` is true when
    any part is quoted or escaped (the body is then literal). ValueError when the word cannot be read exactly: none
    follows, an unterminated quote, `$'..'`, `$".."` or a backtick in it."""
    n = len(s)
    k = j + 2
    strip = k < n and s[k] == "-"
    k += strip
    while k < n and s[k] in " \t":
        k += 1
    start, out, quoted = k, [], False
    while k < n and s[k] not in _HD_END:
        c = s[k]
        if c == "\\":
            if k + 1 >= n or s[k + 1] == "\n":
                raise ValueError("heredoc delimiter ends in a backslash")
            out.append(s[k + 1])
            quoted = True
            k += 2
        elif c == "'":
            e = s.find("'", k + 1)
            if e < 0:
                raise ValueError("unterminated quote in a heredoc delimiter")
            out.append(s[k + 1:e])
            quoted = True
            k = e + 1
        elif c == '"':
            e = k + 1
            while e < n and s[e] != '"':
                if s[e] == "\\" and e + 1 < n and s[e + 1] in '$`"\\':
                    e += 1
                out.append(s[e])
                e += 1
            if e >= n:
                raise ValueError("unterminated quote in a heredoc delimiter")
            quoted = True
            k = e + 1
        elif c == "`" or (c == "$" and s[k + 1:k + 2] in ("'", '"')):
            raise ValueError("heredoc delimiter the guard cannot read exactly ($'..', $\"..\" or a backtick)")
        else:
            out.append(c)
            k += 1
    if k == start:
        raise ValueError("heredoc operator without a delimiter word")
    return "".join(out), strip, quoted, k


def _skip_heredoc_body(s: str, i: int, delim: str, strip: bool) -> tuple[str, int, bool]:
    """(body, index after the delimiter line, delimiter found) of the heredoc whose body starts at s[i]."""
    n = len(s)
    lines: list[str] = []
    while i < n:
        j = s.find("\n", i)
        line = s[i:n if j < 0 else j]
        i = n if j < 0 else j + 1
        if (line.lstrip("\t") if strip else line) == delim:
            return "\n".join(lines), i, True
        lines.append(line)
    return "\n".join(lines), i, False


def _skip_dquote(s: str, j: int) -> int:
    """Index after the double-quoted string that opens at s[j] (len(s) when unterminated); `$(...)` and backticks
    inside it nest, so a quote inside a substitution inside a string does not end the string."""
    n = len(s)
    j += 1
    while j < n:
        c = s[j]
        if c == "\\":
            j += 2
        elif c == '"':
            return j + 1
        elif c == "$" and s.startswith("$(", j):
            j = _match_paren(s, j + 1) + 1
        elif c == "`":
            k = s.find("`", j + 1)
            j = n if k < 0 else k + 1
        else:
            j += 1
    return n


def _match_paren(s: str, i: int) -> int:
    """Index of the `)` closing the `(` at s[i], skipping quoted text, comments and heredoc bodies (an apostrophe
    in a `$(cat <<'EOF' ... EOF)` commit message is not a quote); len(s) when unclosed. A heredoc operator the
    guard cannot read exactly raises ValueError."""
    depth, j, n = 0, i, len(s)
    pending: list[tuple[str, bool]] = []
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
            j = _skip_dquote(s, j)
            continue
        if c == "`":
            k = s.find("`", j + 1)
            j = n if k < 0 else k + 1
            continue
        if c == "#" and (j == 0 or s[j - 1] in " \t\n;&|("):
            k = s.find("\n", j)
            j = n if k < 0 else k
            continue
        if c == "<" and s.startswith("<<<", j):
            j += 3
            continue
        if c == "<" and s.startswith("<<", j):
            delim, strip, _, j = _read_heredoc_op(s, j)
            pending.append((delim, strip))
            continue
        if c == "\n" and pending:
            j += 1
            for delim, strip in pending:
                _, j, _ = _skip_heredoc_body(s, j, delim, strip)
            pending.clear()
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return n


def _match_brace(s: str, i: int) -> int:
    """Index of the `}` closing the `{` of a `${` at s[i] (quotes, `$(...)` and nested `${` skipped). ValueError
    when unclosed."""
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
            j = _skip_dquote(s, j)
            continue
        if c == "`":
            k = s.find("`", j + 1)
            j = n if k < 0 else k + 1
            continue
        if c == "$" and s.startswith("$(", j):
            j = _match_paren(s, j + 1) + 1
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    raise ValueError("unterminated ${...}")


def _body_subs(body: str) -> list[str]:
    """Bodies of the `$(...)` and backtick substitutions in UNQUOTED heredoc text (the outer shell runs them)."""
    subs: list[str] = []
    i, n = 0, len(body)
    while i < n:
        c = body[i]
        if c == "\\":
            i += 2
        elif c == "$" and body.startswith("$(", i):
            j = _match_paren(body, i + 1)
            subs.append(body[i + 2:j])
            i = j + 1
        elif c == "`":
            j = body.find("`", i + 1)
            j = n if j < 0 else j
            subs.append(body[i + 1:j])
            i = j + 1
        else:
            i += 1
    return subs


_ANSI_SIMPLE = {"a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v",
                "\\": "\\", "'": "'", '"': '"', "?": "?"}


def _ansi_c(s: str) -> str:
    """Decode the inside of a bash `$'...'` word (`\\x67it`, `\\147it`, `\\n`, `\\u00e9`, `\\cA`) to the text the shell
    builds. A bad escape stays literal, as in bash: `\\x` or `\\u` with no hex digit, `\\xZ`, an unknown `\\q`."""
    def one(m: "re.Match[str]") -> str:
        g = m.group(1)
        try:
            if g[0] in "xuU" and len(g) > 1:
                return chr(int(g[1:], 16))
            if g[0] in "01234567":
                return chr(int(g, 8) & 0xFF)
            if g[0] == "c" and len(g) == 2:
                return chr(ord(g[1]) & 0x1F)
        except (ValueError, OverflowError):
            pass
        return _ANSI_SIMPLE.get(g, "\\" + g)
    return re.sub(r"\\(x[0-9A-Fa-f]{1,2}|u[0-9A-Fa-f]{1,4}|U[0-9A-Fa-f]{1,8}|[0-7]{1,3}|c.|.)", one, s, flags=re.S)


def lex_shell(cmd: str) -> list["Seg | str"]:
    """The command as an ordered list of Seg (one simple command) and the markers "(" / ")" (subshell scope). A
    segment ends at an unquoted newline, ; & && | || |& ( ). Heredoc bodies are kept on the segment that owns the
    heredoc (judged by the analyzer, never skipped); `<<<` is read as a here-string; `$'...'` is decoded. Raises
    ValueError on an unterminated quote."""
    items: list["Seg | str"] = []
    buf: list[str] = []
    state = {"in": False, "dyn": False, "glob": False}
    holder: dict[str, Any] = {"seg": None, "sep": "", "here": False}
    pending: list[Heredoc] = []
    i, n = 0, len(cmd)

    def seg() -> Seg:
        if holder["seg"] is None:
            holder["seg"] = Seg([], sep_before=holder["sep"])
            items.append(holder["seg"])
        return holder["seg"]

    def end_word() -> None:
        if state["in"]:
            w = Word("".join(buf), state["dyn"], state["glob"])
            s = seg()
            s.words.append(w)
            if holder["here"]:
                s.herestrings.append(w.text)
                holder["here"] = False
        buf.clear()
        state["in"] = state["dyn"] = state["glob"] = False

    def end_seg(sep: str) -> None:
        end_word()
        if holder["seg"] is not None:
            holder["seg"].sep_after = sep
            holder["seg"] = None
        holder["sep"] = sep

    def add_sub(body: str) -> None:
        seg().subs.append(body)

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
        elif c == "$" and cmd[i + 1:i + 2] == "'":
            j = i + 2
            while j < n and cmd[j] != "'":
                j += 2 if cmd[j] == "\\" else 1
            if j >= n:
                raise ValueError("unterminated $'...' quote")
            buf.append(_ansi_c(cmd[i + 2:j]))
            state["in"] = True
            i = j + 1
        elif c == "$" and cmd[i + 1:i + 2] == '"':
            i += 1                                  # $"..." is a double-quoted string
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
                    add_sub(cmd[i + 2:j])
                    buf.append("$()")
                    state["dyn"] = True
                    i = j + 1
                elif d == "`":
                    j = cmd.find("`", i + 1)
                    j = n if j < 0 else j
                    add_sub(cmd[i + 1:j])
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
            add_sub(cmd[i + 2:j])
            buf.append("$()")
            state["in"] = state["dyn"] = True
            i = j + 1
        elif c == "$" and cmd[i + 1:i + 2] == "{":
            j = _match_brace(cmd, i + 1)                # a substitution inside ${X:-$(...)} runs too
            for body in _body_subs(cmd[i + 2:j]):
                add_sub(body)
            buf.append(cmd[i:j + 1])
            state["in"] = state["dyn"] = True
            i = j + 1
        elif c == "`":
            j = cmd.find("`", i + 1)
            j = n if j < 0 else j
            add_sub(cmd[i + 1:j])
            buf.append("``")
            state["in"] = state["dyn"] = True
            i = j + 1
        elif c in " \t\r":
            end_word()
            i += 1
        elif c == "\n":
            end_seg("\n")
            i += 1
            while pending:                       # the bodies of the heredocs opened on this line
                hd = pending.pop(0)
                hd.body, i, done = _skip_heredoc_body(cmd, i, hd.delim, hd.strip)
                if not done:
                    raise ValueError(f"heredoc <<{hd.delim} has no terminating line")
        elif c == "#" and not state["in"]:
            j = cmd.find("\n", i)
            i = n if j < 0 else j
        elif c == ";":
            end_seg(";")
            i += 1
        elif c == "&" and cmd.startswith("&&", i):
            end_seg("&&")
            i += 2
        elif c == "&" and ((i > 0 and cmd[i - 1] in "<>") or cmd[i + 1:i + 2] == ">"):
            buf.append(c)                        # 2>&1 and &> are redirections, not a control operator
            state["in"] = True
            i += 1
        elif c == "&":
            end_seg("&")
            i += 1
        elif c == "|":
            op = "||" if cmd.startswith("||", i) else "|&" if cmd.startswith("|&", i) else "|"
            end_seg(op)
            i += len(op)
        elif c in "()":
            end_seg("")
            items.append(c)
            holder["sep"] = c
            i += 1
        elif c == "<" and cmd.startswith("<<<", i):
            end_word()
            holder["here"] = True
            i += 3
        elif c == "<" and cmd.startswith("<<", i):
            delim, strip, quoted, end = _read_heredoc_op(cmd, i)
            end_word()
            hd = Heredoc(delim, strip, quoted)
            seg().heredocs.append(hd)
            pending.append(hd)
            i = end
        else:
            if c == "$" and _DYN.match(cmd[i:i + 2]):
                state["dyn"] = True
            if c in "*?[" or (c == "{" and re.match(r"\{[^{}\s]*(,|\.\.)", cmd[i:])):
                state["glob"] = True
            buf.append(c)
            state["in"] = True
            i += 1
    end_word()
    if holder["seg"] is not None:
        holder["seg"].sep_after = ""
    return [it for it in items if isinstance(it, str) or it.words or it.heredocs or it.subs]


@dataclasses.dataclass
class ShellCall:
    argv: list[str]
    cwd: Optional[str]          # None: unknown (a `cd` into an unexpanded or `-` path)
    env: dict[str, str]         # inline GIT_DIR= / GIT_WORK_TREE= / GIT_CONFIG_* assignments in force
    headlike: bool              # `git` is the command word (after wrappers), not an argument of another command
    nglobal: int = 0            # index of the subcommand in argv


def _basename(t: str) -> str:
    return os.path.basename(t) if "/" in t else t


def _could_be_git(w: Word) -> bool:
    """A command word the shell computes (an unexpanded variable or substitution, a glob or brace pattern) that
    can still turn out to be `git`. A literal path suffix other than `git` rules it out (`$(pwd)/run.sh`)."""
    text = w.text
    if "/" in text:
        tail = text.rsplit("/", 1)[1]
        if tail and not any(ch in tail for ch in "$`*?[{") and tail != "git":
            return False
    if w.glob and not w.dyn:
        import fnmatch
        alts = [text.rsplit("/", 1)[-1]]
        for _ in range(4):                       # expand {a,b} one level at a time, bounded
            nxt: list[str] = []
            for a in alts:
                m = re.search(r"\{([^{}]*,[^{}]*)\}", a)
                if m:
                    nxt += [a[:m.start()] + part + a[m.end():] for part in m.group(1).split(",")]
                else:
                    nxt.append(a)
            alts = nxt[:64]
        return any(fnmatch.fnmatchcase("git", a) for a in alts) or any("{" in a and ".." in a for a in alts)
    return True


def _stdin_shell(seg: Seg, head: int) -> bool:
    """The segment's command is a shell that reads its script from stdin (no -c, no script file, or -s / -)."""
    for w in seg.words[head + 1:]:
        t = w.text
        if t == "-s" or t == "-":
            return True
        if re.match(r"^-[A-Za-z]*c[A-Za-z]*$", t):
            return False
        if t.startswith("-"):
            continue
        return False                              # the first non-option word is a script file
    return True


def _wrapped_head(texts: list[str], k: int) -> bool:
    """texts[k] can be the command a run of wrappers ends in: `env -u X bash`, `nice -n 5 sh`, `sudo -u me git`,
    `timeout 5s git`, `env A=1 git`, `/usr/bin/env git`. A wrapper's option may take a value, so the word after one
    counts as that value AND as a candidate command (fail closed: `env -u X $G` is a computed name)."""
    j = 0
    while j < k and _ENV_ASSIGN.match(texts[j]):
        j += 1
    if j == k:
        return True
    if _basename(texts[j]) not in _WRAPPERS:
        return False
    after_opt = False
    for t in texts[j + 1:k]:
        if _basename(t) in _WRAPPERS or _ENV_ASSIGN.match(t) or _WRAP_VALUE.match(t):
            after_opt = False
        elif t.startswith("-"):
            after_opt = True
        elif after_opt:
            after_opt = False
        else:
            return False
    return True


def shell_git_calls(cmd: str, cwd: Optional[str], _depth: int = 0) -> tuple[list[ShellCall], list[str]]:
    """(git calls found in a shell command, problems that call for a fail-closed answer). See the module
    docstring for what is followed. `cwd` None means the directory is not known."""
    problems: list[str] = []
    mentions = bool(_MENTIONS_GIT.search(cmd))
    if _depth > MAX_SHELL_DEPTH:
        return [], ([f"shell code nested deeper than {MAX_SHELL_DEPTH} levels; spell the git command out"] if mentions else [])
    try:
        items = lex_shell(cmd)
    except (ValueError, RecursionError) as e:          # RecursionError: `"$("` nested past the interpreter's limit
        return [], ([f"cannot parse the command ({e}); spell it out"] if mentions else [])
    out: list[ShellCall] = []
    cur: Optional[str] = cwd
    scope: list[tuple[Optional[str], list[Optional[str]]]] = []   # (cwd, dir stack) saved at each `(`
    dirs: list[Optional[str]] = []                                 # pushd/popd stack
    pipeline: list[str] = []                                       # text of the pipeline so far

    def rec(text: str, at: Optional[str]) -> None:
        c2, p2 = shell_git_calls(text, at, _depth + 1)
        out.extend(c2)
        problems.extend(p2)

    for item in items:
        if item == "(":
            scope.append((cur, list(dirs)))
            pipeline = []
            continue
        if item == ")":
            if scope:
                cur, dirs = scope.pop()
            pipeline = []
            continue
        assert isinstance(item, Seg)
        seg = item
        words = seg.words
        texts = [w.text for w in words]
        if seg.sep_before not in ("|", "|&"):
            pipeline = []
        pipeline.append(" ".join(texts) + "\n" + "\n".join(h.body for h in seg.heredocs) + "\n" + "\n".join(seg.herestrings))
        for body in seg.subs:
            rec(body, cur)
        for hd in seg.heredocs:
            if not hd.quoted:
                try:
                    bodies = _body_subs(hd.body)
                except (ValueError, RecursionError) as e:   # a heredoc inside the body that cannot be read exactly
                    bodies = []
                    if mentions:
                        problems.append(f"cannot parse a heredoc body ({e}); spell it out")
                for body in bodies:
                    rec(body, cur)
        head = 0
        while head < len(words) and (_ENV_ASSIGN.match(texts[head]) or texts[head] in _WRAPPERS):
            head += 1
        while head < len(words) and head > 0 and (texts[head].startswith("-") or texts[head].isdigit()):
            head += 1                                   # options and numbers of a wrapper: `timeout 5`, `nice -n 5`
        hbase = _basename(texts[head]) if head < len(words) else ""
        shell_like = hbase in _SHELLS or hbase in ("source", ".")
        if hbase in ("cd", "pushd", "popd"):
            piped = seg.sep_before in ("|", "|&") or seg.sep_after in ("|", "|&", "&")
            if not piped:                               # a pipeline member or a background job runs in a subshell
                if hbase == "popd":
                    cur = dirs.pop() if dirs else None
                else:
                    args = [w for w in words[head + 1:] if not w.text.startswith("-") or w.text == "-"]
                    if hbase == "pushd":
                        dirs.append(cur)
                    if not args or args[0].dyn or args[0].text == "-" or re.match(r"^~[^/]", args[0].text) or cur is None:
                        cur = None
                    else:
                        cur = os.path.normpath(os.path.join(cur, os.path.expanduser(args[0].text)))
                        if not os.path.isdir(cur) and "mkdir" not in cmd:
                            cur = None                  # a cd that fails leaves the shell where it was: unknown
            continue
        wrapped = [k for k in range(len(words)) if _wrapped_head(texts, k)]   # words that can BE the command
        shell_k = [k for k in wrapped if _basename(texts[k]) in _SHELLS or _basename(texts[k]) in ("source", ".")]
        if shell_k or any(_basename(t) in _SHELLS for t in texts):
            # a shell anywhere in the segment (`env -u X bash`, `sudo -u me sh`, `nice -n 5 zsh`, `xargs sh`) may read
            # the heredoc / here-string as its script; judged as code (a body of plain text finds no git call)
            body_code = [hd.body for hd in seg.heredocs] + list(seg.herestrings)
            for code in body_code:
                rec(code, cur)
            k0 = next((k for k in shell_k if _basename(texts[k]) in _SHELLS), None)
            if k0 is not None and not body_code and _stdin_shell(seg, k0) and seg.sep_before in ("|", "|&"):
                if _MENTIONS_GIT.search("\n".join(pipeline[:-1])):
                    problems.append("text that mentions git is piped into a shell; spell the git command out")
            if shell_k and any(w.text in ("<", "/dev/stdin") or w.text.startswith("/dev/fd/") for w in words) \
                    and mentions and not body_code:
                problems.append("a shell or `source` reads a process substitution or stdin; spell the git command out")
        for k in wrapped:
            hw = words[k]
            if _ENV_ASSIGN.match(hw.text) or hw.text in _WRAPPERS:
                continue
            if ((hw.dyn and mentions) or (hw.glob and not hw.dyn)) and _could_be_git(hw):
                problems.append("the command name is computed (a variable or substitution in a command that mentions "
                                "git, or a glob / brace pattern that can match `git`); spell the git command out")
                break
        placeholder = any(t in ("xargs", "parallel") for t in texts)
        for idx, w in enumerate(words):
            base = _basename(w.text)
            if base in _SHELLS:
                for k in range(idx + 1, min(idx + 6, len(words))):
                    if re.match(r"^-[A-Za-z]*c[A-Za-z]*$", words[k].text) and k + 1 < len(words):
                        payload = words[k + 1]
                        if (payload.dyn or (placeholder and "{}" in payload.text)) and mentions:
                            problems.append("a shell -c script is computed (variable, substitution or xargs "
                                            "placeholder) and the command mentions git; spell it out")
                        rec(payload.text, cur)
                        break
            elif base in ("eval", "watch"):
                if base == "eval" and mentions and any(x.dyn for x in words[idx + 1:]):
                    problems.append("eval runs a computed string and the command mentions git; spell it out")
                rec(" ".join(x.text for x in words[idx + 1:]), cur)
            if base != "git":
                continue
            inline: dict[str, str] = {}
            for t in texts[:idx]:
                m = _ENV_ASSIGN.match(t)
                if m and _INLINE_GIT_ENV.match(m.group(1)):
                    inline[m.group(1)] = m.group(2)
            headlike = _wrapped_head(texts, idx) or all(
                _ENV_ASSIGN.match(t) or t in _WRAPPERS or t.startswith("-") or t.isdigit() or t == "{}"
                or _basename(t) in ("env",) for t in texts[:idx])
            rest = words[idx + 1:]
            if placeholder:
                rest = [Word(x.text, x.dyn or "{}" in x.text, x.glob) for x in rest]
            call = parse_git_argv([x.text for x in rest], cur if cur is not None else (cwd or os.sep), {})
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
    return d, GitCall(cwd, None, "", [], [])


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
            target = create_claim(c, pointer_for=None if a.no_pointer else a.path)
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
