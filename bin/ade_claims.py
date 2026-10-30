#!/usr/bin/env python3
"""ade_claims: the workspace claim library, the git-guard rules and the ref hooks (isolation slice W1, 2026-10-24; O2 redesign
2026-10-25).

One claim per workspace (a cow pasture or a linked worktree): who owns it, which branch, which base.
Design: design-isolation-report.md 3.4 (schema), 3.5.4 (guard); frontier-pr59-design-report.md (O2). TWO ENFORCEMENT POINTS:
  1. git's own hooks guard REFS: `libexec/git-hooks/reference-transaction` and `pre-push` (installed per repository by
     `install`, run through `hook-ref` / `hook-push` below). git resolves every option, refspec, mapping and alias to the
     final ref name before it calls the hook, so no argv spelling gets round it.
  2. `bin/ade-git-guard`, the PATH shim, runs `ade_claims.py guard -- GIT_ARGS...` for what hooks cannot see (a foreign
     workspace, the shared checkout's destructive forms, worktree verbs, rename/copy destinations) and FAILS CLOSED on what it
     cannot read.
Integration stage as of 2026-10-25: W1 (this file, the shim and the hooks) exists; W2 (cow-pasture installs the hooks into a new
pasture), W3 (acp-dispatch exports ADE_CLAIM_ID) and W4 (acp-run puts the shim on agents' PATH) are NOT wired yet, so nothing
calls the guard in a live session. Repositories get the hooks from `ade-git-guard install` or lazily from the shim.

THIS IS A SEATBELT, NOT A SANDBOX (design 5.7). It stops an agent's accidental or careless git; it does not
stop one that works at it. Out of reach by design: an absolute path to the real git (the hooks still run), unsetting
ACP_RUN_AGENT/ADE_CLAIM_ID (`env -i`), another agent's ADE_CLAIM_ID, editing the claim registry (same uid), repositories
without the hooks, writers that never run git's hooks (libgit2, gitoxide), a harness that turns repository hooks off, and
EVERYTHING GIT ITSELF SPAWNS for the shim's rules (`bisect run`, `submodule foreach`, pagers, core.fsmonitor, diff.external,
core.sshCommand, `fetch --upload-pack`, any `git` a `!` alias runs), because git puts its own exec-path first on its
children's PATH, so those children reach the real git, not the shim.

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

Who is guarded. The shim and its rules: agents only (ACP_RUN_AGENT=1 or ADE_CLAIM_ID set; a human shell is never touched).
The hooks: those two, plus a caller with CLAUDECODE, OMPCODE or CODEX_* set and no claim identity (an agent that may write
nothing claimed). git's own hooks (GIT_INDEX_FILE set) and pre-commit (PRE_COMMIT set) are never refused.

HOOKS (the ref enforcement). `hook-ref STATE` (stdin: `<old> <new> <ref>` lines) refuses in `prepared` only, which aborts git's
transaction ("aborted by the reference-transaction hook"): (a) an update (deletion and a `0 0` line included) of
`refs/heads/<b>` while another owner's active claim, of a repository whose origin matches (`git config --get
remote.origin.url`, as git answers it: comments, quotes, includes), names `<b>` or has `<b>` checked out; (b) a `HEAD` or `refs/heads/*` update while the hook runs in a workspace another agent claims (`checkout`, `switch`,
`commit` there, however it was reached: -C, --git-dir, GIT_DIR); (c) a `refs/stash` update in a linked worktree (refs/stash is
shared). `pack-refs` (and so `gc`, `maintenance`), whose transactions report packing and pruning as `0 new` and `old 0`
without changing a value, is exempt (the stub exports the git pid; the parent's real executable name and exact argv decide, never its argv[0]). In `committed` it appends
one line to guard.log per change to a claimed branch (actor, ref, old, new) and never fails. `hook-push REMOTE URL` (stdin:
`<local ref> <local oid> <remote ref> <remote oid>`) refuses a push to `refs/heads/<b>` claimed by another owner of the
repository the URL names. FAIL OPEN:
the installed stub runs the checkout's hook as a child and passes on only its exit 77; any other outcome (exit 1, 3, 126, a
signal, a missing file, no python, a traceback, the 10 s alarm, git not answering the origin question) lets git proceed,
for agents and humans alike. A hook never runs a ref-writing git. `install [DIR]` writes chain-preserving stubs into
`$(git rev-parse --git-common-dir)/hooks` (an existing hook of the same name is kept as NAME.pre-ade and runs after ours;
exit 78 while `git config --get-all core.hooksPath` says it is set, an empty value included, or when git does not say; 73 when
NAME.pre-ade is in the way; 2 outside a repository). The shim installs them lazily, in the same cases.

SHIM RULES (`guard`), evaluated in order. Git is read the way git reads it: option state in order (`restore --staged
--no-staged` is not staged), long options match by any unique prefix, config is the call's own ordered -c / --config-env /
GIT_CONFIG_* plus the repository's, relative --git-dir/--work-tree/GIT_DIR/GIT_WORK_TREE are relative to the cwd after every -C.
  0. FAIL CLOSED (config is asked of git, not parsed, 2026-10-25): a leading option git does not define (or one missing its
     value) -> `unknown-option`; a subcommand that is not a git builtin, not an alias and not in KNOWN_SUBS ->
     `unknown-subcommand` (an external program too: `git commit-own` is refused, run `git-commit-own` directly); command-line or
     environment config whose key, after normalisation, is `core.hookspath` or starts with `hook.`, `include.` or
     `includeif.` (the environment's GIT_CONFIG_COUNT is read in full: the pairs are bounded by the environment's own size,
     never by a cap), a `git config` that writes such a key (or `--edit`), and `core.hooksPath` set (any value, an empty one
     too) in the command, global or system scope, as `git config --null --show-scope --get-all core.hooksPath` says under the
     call's own options and the CALLER's environment (HOME, XDG_CONFIG_HOME, GIT_CONFIG_*, includes) -> `hook-config`; a
     repository's own (local/worktree) hooksPath is not refused (husky and the like; the hooks do not run there, see
     docs/git-guard.md). When git answers neither 0 (set) nor 1 (unset): timeout, cannot start, a config it cannot read ->
     `hook-config-unknown`, refused with that reason. `push --no-verify` (any `--no-v` prefix) and `send-pack`/`http-push`,
     which skip the pre-push hook -> `push-no-verify`/`push-plumbing`.
  1. A workspace with an ACTIVE claim that is not mine (the cwd, or ANY -C, --git-dir, --work-tree, GIT_DIR or GIT_WORK_TREE
     value the call types, even one a later option moves git away from): only the read allowlist runs (FOREIGN_READ: status,
     log, show, diff, rev-parse, ls-files, ls-tree, cat-file, blame, describe, rev-list, for-each-ref, grep, shortlog,
     name-rev, merge-base, version, help; plus `branch` listings, `remote -v|get-url`, `config --get*|--list`, `worktree
     list`, `symbolic-ref` reads). `--output` of diff/log/show/shortlog and `grep -O` are refused there; everything else is.
  2. A workspace with no active claim (shared or primary checkout): refuse stash (except list/show),
     reset --hard|--merge|--keep, checkout -f|-p|--pathspec-from-file|--|<path>|<2+ args>, restore unless
     --staged is in force and --worktree is not, switch -f|--discard-changes, clean unless -n (also -i), rm -f
     unless --cached or -n is in force, commit -a, add -A/-u/--all/--update with no pathspec or add ., pull|
     rebase|merge with autostash in force (--autostash/--no-autostash, else rebase.autoStash for a rebase or a
     pull that rebases, merge.autoStash for a merge or a pull that merges), rebase -x, `!` aliases and an
     alias chain deeper than MAX_ALIAS_DEPTH. Abbreviated options are read as the dangerous option they may stand for.
     Not covered (plumbing and object-store maintenance stay the operator's call): checkout-index, update-index, read-tree,
     fast-import, gc/prune/repack, tag -f|-d, notes, replace, mv -f, `add '*'`.
  3. A linked worktree, even its own claimed owner's: stash, rebase -x and `!` aliases are refused (refs/stash
     is shared with the other worktrees); everything else the owner does there is allowed.
  4. The TARGET counts for what no hook sees: `worktree remove|move|prune` (selectors resolved against git's registered
     worktree list, unique-suffix form included; `remove --force` needs ownership of the target) and `branch -m|-M` (every
     name) and `-c|-C|--copy` (the destination): the files backend reports a rename's source deletion to the hook but not its
     destination, and a copy not at all (measured on git 2.56, 2026-10-25). The git dir and work tree the call lands on are
     asked of git itself (`rev-parse --absolute-git-dir --show-toplevel` under the call's own -C, -c, --git-dir, --work-tree and
     environment); when git cannot answer at all (timeout), the typed values are used and a call that is not read-only is
     refused while another agent holds a claim (rule workspace-unresolved).
  5. In my own claimed workspace everything else is allowed.
Removed in O2 (the hooks replace them): the fetch/pull/remote-update and push dry-run preflights, the `update-ref`, `branch -d|-D|-f`,
`checkout -B`, `switch -C` and `worktree add -B` target rules, the output-file rules (`--output`, `bundle create`, `format-patch -o`,
`config --file`, `bugreport -o`), and the shell-string `check` analyser with its Claude hook.
Refusal = exit 77 (EX_NOPERM), a message naming the owner and the safe alternative (control characters escaped),
one JSON line in `<state>/guard.log` (flag NAMES from an allowlist only; an option's value is never logged). A refused
hook shows git's `fatal: ... aborted by the reference-transaction hook` (exit 128) after the same message.
Operator override: ACP_OPERATOR_APPROVED containing `git-guard` allows the call and logs it (design 5.6's
ADE_GIT_GUARD_BYPASS was not built; this is the convention bin/acp-dispatch already uses), in the shim and in the hooks.
A shim crash fails OPEN (design 5.7, bin/ade-git-guard).

CLI (also the bash-facing API; every subcommand exits 0 ok, 1 not found, 2 usage, 3 id exists, 4 path
owned by another owner's active claim, 77 refused; `install` also 73 and 78, above):
    ade_claims.py new --id ID --path DIR --branch B --base-sha S [--repo-origin U]
        [--owner-record R] [--owner-session S] [--owner-agent A] [--owner-model M] [--lead L]
        [--allow ID]... [--role lead|worker|builder] [--purpose T] [--created-by X]
        [--inherited-dirt-patch P] [--no-pointer]     writes the claim and the pointer; prints the claim file
    ade_claims.py show ID [--field F]       print the claim JSON (or one field)
    ade_claims.py find [DIR]                print the active claim of the workspace holding DIR (cwd)
    ade_claims.py list [--state S] [--json] one line per claim (or a JSON array)
    ade_claims.py set-state ID active|released|merged
    ade_claims.py guard -- GIT_ARGS...      decide one git call (what ade-git-guard runs)
    ade_claims.py install [DIR]             install the ref hooks into DIR's repository
    ade_claims.py hook-ref STATE | hook-push REMOTE URL    what libexec/git-hooks/* run (stdin is git's)
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

# Every subcommand git 2.56 lists (`git --list-cmds=builtins,main,nohelpers,list-complete`, 2026-10-25). One that is not
# here is an alias (looked up), else an external `git-foo` program, which the guard cannot read: refused.
KNOWN_SUBS = frozenset("""add am annotate apply archimport archive backfill bisect blame branch bugreport bundle cat-file
check-attr check-ignore check-mailmap check-ref-format checkout checkout-index cherry cherry-pick clean clone column commit
commit-graph commit-tree config count-objects credential credential-cache credential-netrc credential-osxkeychain
credential-store cvsexportcommit cvsimport cvsserver daemon describe diagnose diff diff-files diff-index diff-pairs
diff-tree difftool fast-export fast-import fetch fetch-pack filter-branch fmt-merge-msg for-each-ref for-each-repo
format-patch format-rev fsck fsck-objects gc get-tar-commit-id grep hash-object help history hook http-backend http-fetch
http-push imap-send index-pack init init-db instaweb interpret-trailers jump last-modified log ls-files ls-remote ls-tree
mailinfo mailsplit maintenance merge merge-base merge-file merge-index merge-octopus merge-one-file merge-ours
merge-recursive merge-recursive-ours merge-recursive-theirs merge-resolve merge-subtree merge-tree mergetool mktag mktree
multi-pack-index mv name-rev notes p4 pack-objects pack-redundant pack-refs patch-id pickaxe prune prune-packed pull push
quiltimport range-diff read-tree rebase receive-pack reflog refs remote remote-ext remote-fd remote-ftp remote-ftps
remote-http remote-https repack replace replay repo request-pull rerere reset restore rev-list rev-parse revert rm
send-email send-pack shell shortlog show show-branch show-index show-ref sparse-checkout stage stash status stripspace
submodule subtree switch symbolic-ref tag unpack-file unpack-objects update-index update-ref update-server-info
upload-archive upload-pack url-parse var verify-commit verify-pack verify-tag version whatchanged worktree
write-tree""".split())
# The subcommands that are read-only in a workspace another agent's active claim covers (the rest of the call decides
# for `branch`, `remote`, `config`, `worktree` and `symbolic-ref`: only their read forms).
FOREIGN_READ = frozenset("""status log show diff rev-parse ls-files ls-tree cat-file blame describe rev-list for-each-ref
grep shortlog name-rev merge-base version help""".split())
FOREIGN_READ_FORMS = frozenset("branch remote config worktree symbolic-ref".split())
# git's global options (git.c, 2.56). A leading option that is not here is refused: `-c`-style tricks the guard cannot
# read must not be mistaken for the subcommand.
GLOBAL_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env", "--attr-source",
                "--shallow-file"}
GLOBAL_FLAG = {"--no-pager", "-P", "-p", "--paginate", "--no-optional-locks", "--no-replace-objects",
               "--literal-pathspecs", "--glob-pathspecs", "--noglob-pathspecs", "--icase-pathspecs", "--bare",
               "--no-lazy-fetch", "--no-advice"}
GLOBAL_INFO = {"--version", "-v", "--help", "-h", "--html-path", "--man-path", "--info-path", "--exec-path"}
# The global options a helper git run (dry run, rev-parse, config) must carry because they change what git sees:
# the namespace and super-prefix, the exec path (which upload-pack, remote helpers and hooks run), --bare, object
# replacement and the like. Everything in GLOBAL_FLAG but the pager choice (git runs with its output piped).
GLOBAL_CARRIED_VALUE = frozenset({"--namespace", "--super-prefix"})
GLOBAL_CARRIED_FLAG = frozenset(GLOBAL_FLAG - {"--no-pager", "-P", "-p", "--paginate"})


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
    gopts: list[str] = dataclasses.field(default_factory=list)      # the other global options git sees (GLOBAL_CARRIED_*)
    problem: str = ""                   # a leading option git does not know, or one with no value: the call is refused
    touched: list[str] = dataclasses.field(default_factory=list)   # the cwd after each -C, in order (every -C counts)
    ws: Optional["Workspace"] = None    # the workspace the guard decided on (set by evaluate; the lazy hook install uses it)

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


def _env_count_config(env: dict[str, str]) -> list[tuple[str, str]]:
    """Config git reads from GIT_CONFIG_COUNT/KEY_n/VALUE_n."""
    out: list[tuple[str, str]] = []
    try:
        count = int(env.get("GIT_CONFIG_COUNT", "0") or 0)
    except ValueError:
        count = 0
    for n in range(max(0, min(count, len(env)))):      # every KEY_n is a variable of `env`: len(env) bounds the pairs exactly
        k = env.get(f"GIT_CONFIG_KEY_{n}")
        if k:
            out.append((_ckey(k), env.get(f"GIT_CONFIG_VALUE_{n}", "")))
    return out


_GIT_SPACE = frozenset(" \t\n\v\f\r")     # C isspace() in the C locale, which is what git's parser uses


def _sq_dequote(src: str, i: int) -> Optional[tuple[str, int]]:
    """Git's sq_dequote_step (quote.c): the single-quoted string starting at `src[i]`, and the index just past it.
    A closing quote followed by `\\'` and then a reopening quote continues the SAME string — that is how git's own
    sq_quote writes `it's` as `'it'\\''s'`. Any other character after a closing quote is a bogus format (None), as is
    a string that ends inside the quotes; measured against git 2.56, `''`, `\\\\` and a trailing escape are all bogus."""
    if i >= len(src) or src[i] != "'":
        return None
    out: list[str] = []
    i += 1
    while True:
        if i >= len(src):
            return None
        c = src[i]
        if c != "'":
            out.append(c)
            i += 1
            continue
        i += 1
        if i >= len(src):
            return "".join(out), i
        # Only the `\'` + reopening-quote form continues the same string; `''`, `\\` and a bare
        # trailing escape are all git's bogus format (measured: `'x''y'`, `'x'\\''y'`, `'x'\'`).
        if src[i] == "\\" and i + 2 < len(src) and src[i + 1] == "'" and src[i + 2] == "'":
            out.append("'")
            i += 3
            continue
        return "".join(out), i


def _parse_config_parameters(params: str) -> Optional[list[tuple[str, str]]]:
    """Git's parse_config_env_list (config.c), the grammar GIT_CONFIG_PARAMETERS actually carries: entries separated
    by whitespace, each a single-quoted string with an optional `=` and a single-quoted value. In the new-style
    `'key'='value'` form the quoted key is literal; in the old-style `'key=value'` form (no quoted value follows) git
    splits the dequoted string at the FIRST `=` and keeps later ones in the value. `key`, `key=`, and `key=` followed
    by whitespace are the same implicit boolean, and what follows the whitespace is a NEW entry — never the previous
    entry's value (`'ade.flag'= 'ade.x'='foo'` is two entries, measured against git 2.56). Unquoted keys or values,
    adjacent quoted strings and trailing junk are git's `bogus format`, after which git runs nothing at all. None
    means bogus. Key VALIDITY is deliberately not ported: git refuses a run whose key has no section (`a b`) or an
    invalid one (`a.b=c`) and this returns the entry anyway, exactly as the `-c` path has always done (measured
    2026-10-30; filed as djbclark-ade#158 M2). It cannot hide config from the guard — git runs nothing in that case."""
    out: list[tuple[str, str]] = []
    i, n = 0, len(params)
    while True:
        while i < n and params[i] in _GIT_SPACE:
            i += 1
        if i >= n:
            return out
        step = _sq_dequote(params, i)
        if step is None:
            return None
        key, i = step
        if i < n and params[i] == "=":
            # new-style `'key'='value'`: the quoted key is literal (a `=` in it belongs to the name/subsection)
            i += 1
            if i < n and params[i] not in _GIT_SPACE:
                step = _sq_dequote(params, i)
                if step is None:
                    return None
                value, i = step
            else:
                value = "true"                      # implicit bool: `'key'=`
        else:
            # old-style `'key=value'`: git hands the dequoted string to git_config_parse_parameter, which splits it
            # at the FIRST `=` and keeps every later one in the value (`'ade.old=value=with=equals'`)
            key, sep, value = key.partition("=")
            if not sep:
                value = "true"
            if not key:
                return None                          # git: "bogus config parameter" for an empty key
        if i < n and params[i] not in _GIT_SPACE:      # entries are separated by whitespace: `'a'='1''b'='2'` is bogus
            return None
        out.append((_ckey(key), value))


def _env_config(env: dict[str, str]) -> list[tuple[str, str]]:
    """Config git reads from the environment: GIT_CONFIG_COUNT/KEY_n/VALUE_n, then GIT_CONFIG_PARAMETERS."""
    out = _env_count_config(env)
    params = env.get("GIT_CONFIG_PARAMETERS", "")
    if params:
        out.extend(_parse_config_parameters(params) or [])
    return out


def parse_git_argv(argv: Sequence[str], cwd: str, env: Optional[dict[str, str]] = None) -> GitCall:
    """Split git's global options from `<subcommand> <args>`, in order: `-C` is cumulative, `-c` and --config-env
    append to an ordered multi-valued list (after GIT_CONFIG_* from `env`), --git-dir/--work-tree override
    GIT_DIR/GIT_WORK_TREE from `env` (last wins). A leading option git does not know (or one missing its value) sets
    `problem`: the call is refused, never read as something else (2026-10-25, O2: a parser miss is a false refusal)."""
    env = os.environ if env is None else env
    cur = cwd
    gitdir: Optional[str] = env.get("GIT_DIR") or None
    worktree: Optional[str] = env.get("GIT_WORK_TREE") or None
    config = _env_config(env)
    gopts: list[str] = []
    touched: list[str] = []
    problem = ""
    i, n = 0, len(argv)
    while i < n:
        a = argv[i]
        name, eq, val = a.partition("=") if a.startswith("--") else (a, "", "")
        if a in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env", "--attr-source",
                 "--shallow-file") and i + 1 >= n:
            problem = f"global option `{a}` has no value"
            i += 1
            break
        if a == "-C":
            cur = os.path.join(cur, argv[i + 1])
            touched.append(cur)
            i += 2
        elif a == "-c":
            k, e, v = argv[i + 1].partition("=")
            config.append((_ckey(k), v if e else "true"))
            i += 2
        elif a in ("--git-dir", "--work-tree") or name in ("--git-dir", "--work-tree") and eq:
            v = val if eq else argv[i + 1]
            if name == "--git-dir":
                gitdir = v
            else:
                worktree = v
            i += 1 if eq else 2
        elif a == "--config-env" or name == "--config-env" and eq:
            spec = val if eq else argv[i + 1]
            k, _, var = spec.partition("=")
            config.append((_ckey(k), env.get(var, "")))
            i += 1 if eq else 2
        elif a in GLOBAL_CARRIED_VALUE and i + 1 < n:
            gopts += [a, argv[i + 1]]
            i += 2
        elif name in GLOBAL_CARRIED_VALUE and eq:
            gopts.append(a)
            i += 1
        elif a in GLOBAL_VALUE:
            i += 2                                      # --attr-source X, --shallow-file X
        elif name == "--attr-source" and eq:
            i += 1
        elif a in GLOBAL_CARRIED_FLAG or a.startswith("--exec-path="):
            gopts.append(a)
            i += 1
        elif a in GLOBAL_FLAG or a in GLOBAL_INFO or a.startswith("--list-cmds="):
            i += 1
        elif a.startswith("-"):
            problem = f"unknown global option `{a}`"
            i += 1
            break
        else:
            break
    sub = argv[i] if i < n and not problem else ""
    rest = list(argv[i + 1:]) if sub else []
    call = GitCall(cur, gitdir, sub, rest, config, worktree, i,
                   {k: v for k, v in env.items() if k in _CONFIG_FILE_ENV}, gopts)
    call.problem = problem
    call.touched = touched
    return call


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

def _writes_a_file(call: GitCall) -> bool:
    """An allowlisted read that can still write a file of the caller's choosing: `--output` of the diff/log family
    (any prefix of the name, as git parses it: inclusive), `grep -O|--open-files-in-pager` (runs a program on the
    files). A stray file in another agent's tree is a nuisance, not lost work, so this is the whole of the rule."""
    sub, args = call.sub, call.args
    for a in args:
        if a == "--":
            break
        if a.startswith("--"):
            name = a[2:].partition("=")[0]
            if name and (("output".startswith(name) and sub in ("diff", "log", "show", "shortlog")) or
                         ("open-files-in-pager".startswith(name) and sub == "grep")):
                return True
        elif sub == "grep" and a.startswith("-") and "O" in a[1:]:
            return True
    return False


def is_readonly(call: GitCall) -> bool:
    """True when this call may run in a workspace another agent's active claim covers (O2, 2026-10-25): the small
    allowlist FOREIGN_READ, plus the read forms of `branch` (a listing), `remote` (`-v`, `get-url`), `config`
    (`--get*`, `--list`), `worktree list` and `symbolic-ref` (no value, no -d). Everything else, a subcommand the
    allowlist does not name included, is not read-only there. `--output`-style flags make an allowlisted call a write."""
    sub, args = call.sub, call.args
    if sub == "":
        return True
    if sub in FOREIGN_READ:
        return not _writes_a_file(call)
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
        return not s.pos or s.pos[0] == "get-url"
    if sub == "symbolic-ref":
        s = scan(args, value_short="m", danger={"delete"})
        return len(s.pos) < 2 and "d" not in s.shorts and "delete" not in s.longs and "m" not in s.shorts
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


FOREIGN_ALT = ("only read-only git runs here (status, log, show, diff, rev-parse, ls-files, grep, `branch --list`, ...); to edit, "
               "make your own workspace (`bin/cow-pasture create`, or `acp-dispatch --workspace auto`)")


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


def _run_git(args: Sequence[str], timeout: float = 10, env_extra: Optional[dict[str, Optional[str]]] = None,
             err_out: Optional[list[str]] = None) -> tuple[int, str]:
    """Run the real git with stdout captured (decoded with replacement, so a hostile byte never raises), its own
    stdin closed and its own process group: on timeout the WHOLE group (hooks, credential helpers, ssh) is killed.
    stderr is discarded, or with `err_out` appended to it (decoded the same way). An `env_extra` value of None removes
    the variable.
    (127, "") when it cannot start, (124, partial output) on timeout."""
    import signal
    import subprocess
    env = {**os.environ, **(env_extra or {}), "GIT_TERMINAL_PROMPT": "0"}
    env = {k: v for k, v in env.items() if v is not None and not k.startswith("GIT_TRACE")}   # a helper run never writes a trace file
    try:
        p = subprocess.Popen([real_git(), *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL if err_out is None else subprocess.PIPE, env=env,
                             start_new_session=True)
    except (OSError, ValueError):
        return 127, ""
    rc = 124
    try:
        out, err = p.communicate(timeout=timeout)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            os.killpg(p.pid, signal.SIGKILL)
        try:
            out, err = p.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            out = err = b""
    if err_out is not None:
        err_out.append((err or b"").decode("utf-8", "replace"))
    return rc, (out or b"").decode("utf-8", "replace")


def _git_out(root: Path, *args: str) -> str:
    rc, out = _run_git(["-C", str(root), *args])
    return out.strip() if rc == 0 else ""


def _call_git(call: GitCall, *args: str, timeout: int = 10) -> tuple[int, str]:
    """A helper git run under the call's own global options, config and config-file environment."""
    return _run_git([*_globals(call), *args], timeout, call.env)


def _globals(call: GitCall) -> list[str]:
    """The call's own global options in git's order, for a helper git run: `-C` the final cwd, every -c in order
    (repeats kept), the other global options that change what git sees (`call.gopts`: --namespace, --exec-path=,
    --bare, --no-replace-objects, ...), --git-dir and --work-tree as typed (relative to that cwd, as git reads them)."""
    g = ["-C", call.cwd, *call.cfg_argv(), *call.gopts]
    if call.gitdir:
        g += ["--git-dir", call.gitdir]
    if call.worktree:
        g += ["--work-tree", call.worktree]
    return g


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
    # every path the call TYPES counts as well (O2 coarse rule): each cumulative -C, --git-dir and --work-tree, even when
    # a later option moves git elsewhere (`-C /their/tree -C /mine` still named their tree)
    for p in call.touched:
        cands.append(find_workspace(p))
    for p, is_gitdir in ((call.gitdir_path(), True), (call.worktree_path(), False)):
        if p:
            cands.append(workspace_for_gitdir(p, call.cwd) if is_gitdir else find_workspace(p))
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
        # Only a rename's or copy's DESTINATION: the files backend never tells the reference-transaction hook about it (a
        # rename reports its source's deletion, a copy nothing: measured on git 2.56, 2026-10-25). Deleting, forcing and
        # every other ref write reach the hook, which does not care how the call was spelled.
        s = scan(args, value_long={"contains", "no-contains", "merged", "no-merged", "points-at", "format", "sort",
                                   "abbrev"}, danger=D_WRITE_BRANCH)
        if s.shorts & set("mM") or s.longs & {"move"}:
            names = [p for p in s.pos]                    # the old name goes away and the new one is overwritten
        elif s.shorts & set("cC") or s.longs & {"copy"}:
            names = s.pos[-1:]                            # a copy only writes its destination (`-c SRC DST`, `-c DST`)
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
    return None


MAX_ALIAS_DEPTH = 10

# Config that turns the hooks off, moves them or pulls in more config (O2, 2026-10-25): `core.hooksPath`, anything under
# `hook.` (git 2.54+ config hooks, `hook.<event>.enabled=false`), `include.*` and `includeIf.*`. No agent has a reason to
# set one, so a match is refused whatever the call is.
def _hook_key(key: str) -> bool:
    k = _ckey(key.strip())
    return k == "core.hookspath" or k.startswith(("hook.", "include.", "includeif."))


def _config_scopes(call: GitCall, env: dict[str, str], key: str = "core.hooksPath") -> tuple[str, list[tuple[str, str]]]:
    """Ask git whether `key` (`core.hooksPath`, or `init.templateDir`) is set, under the call's own -c / --git-dir / -C and the CALLER's environment
    (HOME, XDG_CONFIG_HOME, GIT_CONFIG_GLOBAL/SYSTEM/COUNT/KEY_n/PARAMETERS, includes: git reads them, never us):
    `git config --null --show-scope --get-all KEY` exits 0 when it is set, even to an empty value, 1 when it is
    not (measured 2026-10-25, git 2.56). ("set", [(scope, value)...]), ("unset", []), or ("unknown", []) when git did not
    answer 0/1 (timeout, cannot start, a broken config file)."""
    extra = {k: v for k, v in env.items() if k in ("HOME", "XDG_CONFIG_HOME") or k.startswith("GIT_CONFIG")}
    rc, out = _run_git([*_globals(call), "config", "--null", "--show-scope", "--get-all", key], 5,
                       {**call.env, **extra})
    if rc == 1:
        return "unset", []
    if rc != 0:
        return "unknown", []
    f = out.split("\0")
    return "set", [(f[i], f[i + 1]) for i in range(0, len(f) - 1, 2)]


def _closed(rule: str, alt: str) -> Decision:
    return Decision(False, rule, alt, "", "nobody; the call cannot be classified safely")


def _clone_config_keys(args: Sequence[str]) -> list[str]:
    """The keys of every `clone -c KEY[=VALUE]` / `--config KEY[=VALUE]` (git takes any unique prefix of `--config`, a
    value attached or in the next word, a short `-c` at the end of a cluster like `-qcKEY=V`)."""
    keys: list[str] = []
    i, n = 0, len(args)
    while i < n:
        a = args[i]
        if a == "--":
            break
        if a.startswith("--"):
            name, eq, val = a[2:].partition("=")
            if "config" in expand_long(name, danger={"config"}):
                if not eq:
                    i += 1
                    val = args[i] if i < n else ""
                keys.append(val.partition("=")[0])
            elif not eq and name in ("branch", "origin", "upload-pack", "reference", "reference-if-able", "depth", "jobs",
                                    "separate-git-dir", "shallow-since", "shallow-exclude", "filter", "server-option",
                                    "bundle-uri", "ref-format", "revision", "template"):
                i += 1                                 # a value in the next word: it is not a key
        elif a.startswith("-") and len(a) > 1:
            cl = a[1:]
            for j, ch in enumerate(cl):
                if ch == "c":
                    val = cl[j + 1:]
                    if not val:
                        i += 1
                        val = args[i] if i < n else ""
                    keys.append(val.partition("=")[0])
                    break
                if ch in "bouj":                       # these take the rest of the cluster or the next word
                    if j == len(cl) - 1:
                        i += 1
                    break
        i += 1
    return keys


def _template_decision(call: GitCall, env: dict[str, str], alt: str) -> Optional[Decision]:
    """`clone` and `init` copy a template directory into the new repository, hooks and `config` included: a template
    that holds `core.hooksPath = /dev/null` makes the NEW repository's hooks vanish (round 11, 2026-10-25). Refuse every
    non-default template source (djbclark, 2026-10-25): `--template` (any abbreviation), `GIT_TEMPLATE_DIR`,
    `init.templateDir` (asked of git: command line, environment, or any config scope but the repository's own), and, for
    `clone`, a `-c`/`--config` that writes a hook key or `init.templateDir` into the clone."""
    if scan(call.args, value_short="b" if call.sub == "clone" else "", danger={"template"}).longs & {"template"}:
        return _closed("hook-config", f"`{call.sub} --template` copies a template (hooks, config) into the new repository: {alt}")
    if env.get("GIT_TEMPLATE_DIR") is not None:
        return _closed("hook-config", f"`GIT_TEMPLATE_DIR` is set, so `{call.sub}` would copy that template into the new "
                                      f"repository: {alt}")
    if call.sub == "clone":
        for k in _clone_config_keys(call.args):
            if _hook_key(k) or _ckey(k.strip()) == "init.templatedir":
                return _closed("hook-config", f"`clone --config {_esc(k)}` writes a key that moves, disables or extends the "
                                              f"new repository's hooks: {alt}")
    state, scoped = _config_scopes(call, env, "init.templateDir")
    if state == "unknown":
        return _closed("hook-config-unknown", f"git did not say whether init.templateDir is set; `{call.sub}` is refused "
                                              f"rather than guessed: {alt}")
    for scope, value in scoped:
        if scope not in ("local", "worktree"):
            return _closed("hook-config", f"init.templateDir is set ({scope} config, value `{_esc(value)}`), so `{call.sub}` "
                                          f"would copy that template into the new repository: {alt}")
    return None


# The two config pairs acp-run adds to every agent's environment (GIT_CONFIG_PARAMETERS; legacy COUNT pairs also accepted;
# tools/acp-run/acp-run,
# git_identity_guard): a `reference-transaction` config hook that refuses an agent's branch update with the wrong git identity.
# A config hook only ADDS a hook (measured 2026-10-25, git 2.56: `hook.<name>.enabled=false` does not stop the hooks
# directory's hook), so these two cannot switch the ref guard off. Exempt exactly this (key, value) shape, from the
# environment's config only: never `-c` or `--config-env`, and no other `hook.*` key.
ACP_RUN_IDENTITY_EVENT = ("hook.acp-run-identity.event", "reference-transaction")
ACP_RUN_IDENTITY_COMMAND_KEY = "hook.acp-run-identity.command"


def _acp_run_guard_path() -> str:
    return os.path.realpath(str(Path.home() / ".cache/acp-run/git-identity-guard.sh"))


def _acp_run_pair(k: str, v: str) -> bool:
    return (k, v) == ACP_RUN_IDENTITY_EVENT or (k == ACP_RUN_IDENTITY_COMMAND_KEY and os.path.realpath(v) == _acp_run_guard_path())


def _unexempted_config(call: GitCall, env: dict[str, str]) -> list[tuple[str, str]]:
    """Spend exact ACP pairs from environment config once; command-line copies stay judged."""
    budget: dict[tuple[str, str], int] = {}
    for k, v in _env_config(env):
        if _acp_run_pair(k, v):
            budget[(k, v)] = budget.get((k, v), 0) + 1
    out: list[tuple[str, str]] = []
    for k, v in call.config:
        if budget.get((k, v), 0) > 0:
            budget[(k, v)] -= 1
        else:
            out.append((k, v))
    return out


def _redirect_decision(call: GitCall, env: dict[str, str]) -> Optional[Decision]:
    """Rule (ii): the call, its environment or a `git config` write would disable, move or extend the hooks. git answers
    for `core.hooksPath` (any value, empty included) in the scopes a call or its environment controls: command (-c,
    GIT_CONFIG_COUNT/PARAMETERS), global, system (HOME, XDG_CONFIG_HOME, GIT_CONFIG_GLOBAL/SYSTEM, includes). A
    repository's own (local/worktree) hooksPath is a choice of the repository, not of the call: not refused (the hooks do not
    run there; `install` says so, exit 78). When git cannot answer, the call is refused with that reason (fail closed)."""
    alt = "the ref guard lives in git hooks; nothing may redirect or switch them off. Ask the operator"
    for k, _ in _unexempted_config(call, env):
        if _hook_key(k):
            return _closed("hook-config", f"`{_esc(k)}` set on the command line or in the environment: {alt}")
    state, scoped = _config_scopes(call, env)
    if state == "unknown":
        return _closed("hook-config-unknown", "git did not say whether core.hooksPath is set (it timed out, could not run, or "
                                              f"a config file is broken); the call is refused rather than guessed: {alt}")
    for scope, value in scoped:
        if scope not in ("local", "worktree"):
            return _closed("hook-config", f"core.hooksPath is set ({scope} config, value `{_esc(value)}`): {alt}")
    if call.sub in ("clone", "init"):
        d = _template_decision(call, env, alt)
        if d is not None:
            return d
    if call.sub == "config":
        s = scan(call.args, value_short="f", value_long={"file", "blob", "type", "default"}, danger={"edit"})
        if s.shorts & {"e"} or "edit" in s.longs:
            return _closed("hook-config", f"`git config --edit` can write any key: {alt}")
        if not is_readonly(call):
            for t in s.pos + s.after:
                low = t.lower()
                if _hook_key(t) or low.partition(".")[0] in ("hook", "include", "includeif"):
                    return _closed("hook-config", f"`git config` writes `{_esc(t)}`: {alt}")
    return None


def _push_decision(call: GitCall) -> Optional[Decision]:
    """`push --no-verify` (or any `--no-v` prefix) skips the pre-push hook; so does `send-pack`/`http-push`."""
    if call.sub in ("send-pack", "http-push"):
        return _closed("push-plumbing", f"`git {call.sub}` pushes without running the pre-push hook; use `git push`")
    if call.sub == "push":
        for a in call.args:
            if a == "--":
                break
            if a.startswith("--no-v"):
                return _closed("push-no-verify", "`git push --no-verify` skips the pre-push hook that protects other "
                                                 "agents' branches; push without it")
    return None


def evaluate(call: GitCall, env: Optional[dict[str, str]] = None, *, _depth: int = 0) -> Decision:
    """Decide one git call. Reads claims; asks real git (with the call's own config) for an alias or a branch's origin.
    Order: the fail-closed rules first (an option or subcommand the guard cannot read, hook-redirecting config, a push that
    skips its hook), then the workspace rules, then the targets the hooks cannot see."""
    env = os.environ if env is None else env
    if not is_agent_env(env):
        return ALLOW
    ident = caller_ident(env)
    approved = {x.strip() for x in env.get("ACP_OPERATOR_APPROVED", "").split(",") if x.strip()}
    sub = call.sub
    wss: list[Optional[Workspace]] = [None]
    deny: Optional[Decision] = None
    bang = ""
    unresolved = False
    if call.problem:
        deny = _closed("unknown-option", f"{call.problem}: the guard reads only options git itself defines; spell the "
                                          "call with the plain global options (-C, -c, --git-dir, --work-tree ...)")
    unknown: Optional[Decision] = None
    if deny is None:
        deny = _redirect_decision(call, env) or _push_decision(call)
        if deny is not None and deny.rule == "hook-config-unknown":
            # git could not answer a config question (a `-C` into a place that does not exist, a broken file): the call is
            # still refused, but a foreign claim its path names comes first, so the refusal names the owner (round 11)
            unknown, deny = deny, None
    if deny is None and sub and sub not in KNOWN_SUBS:
        rc, alias = _call_git(call, "config", "--get", f"alias.{sub}") if _depth < MAX_ALIAS_DEPTH else (1, "")
        alias = alias.strip() if rc == 0 else ""
        if _depth >= MAX_ALIAS_DEPTH:
            bang = "alias chain"          # fail closed: an unresolved name is treated as the worst alias
        elif alias.startswith("!"):
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
                nc = GitCall(x.cwd, x.gitdir or call.gitdir, x.sub, x.args, [*call.config, *x.config],
                             x.worktree or call.worktree, call.nglobal, call.env, [*call.gopts, *x.gopts])
                nc.problem = x.problem
                nc.touched = [*call.touched, *x.touched]
                d = evaluate(nc, env, _depth=_depth + 1)
                call.ws = nc.ws
                return d
        else:
            deny = _closed("unknown-subcommand", f"`git {_esc(sub)}` is not a git subcommand the guard knows (an external "
                           "`git-foo` program, or a typo); run the program directly "
                           "(`git-commit-own MSG <paths>`, not `git commit-own`; `git-lfs`, not `git lfs`); or ask the operator")
    if deny is None:
        wss, unresolved = call_workspaces(call)
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
    if deny is None and unknown is not None:
        deny = unknown
    ws_any = next((w for w in wss if w is not None), None)
    call.ws = ws_any
    if deny is None:
        return ALLOW
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


def append_guard_log(rec: dict[str, Any]) -> None:
    """One JSON line appended to guard.log (O_APPEND: concurrent writers do not interleave a line)."""
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


def log_event(decision: Decision, call: GitCall, extra: Optional[dict[str, Any]] = None) -> None:
    """One JSON line per refusal or override in guard.log: the subcommand and option NAMES only, never an
    option's value or a positional (URLs, messages, paths): a credential in argv must not reach a log."""
    rec = {"ts": utc_now(), "outcome": "override" if decision.override else "refused", "rule": decision.rule,
           "cmd": call.display(), "flags": _log_flags(call.args), "claim": decision.claim_id,
           "owner": decision.owner, "ident": decision.detail.get("ident", ""),
           "cwd": decision.detail.get("cwd", ""), "pid": os.getpid()}
    if extra:
        rec.update(extra)
    append_guard_log(rec)


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
    """What ade-git-guard runs for a git call that was not plainly read-only. 0 = run real git, 77 = refused. An allowed
    call also installs the ref hooks into its repository when they are missing (lazy install; never fails the call)."""
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
        _lazy_install(call, env)
        return 0
    rc = _report(d, call)
    if rc == 0:
        _lazy_install(call, env)
    return rc


# --------------------------------------------------------------------------------------------
# hooks: reference-transaction and pre-push (O2, 2026-10-25), and their install
# --------------------------------------------------------------------------------------------

HOOK_NAMES = ("reference-transaction", "pre-push")
STUB_MARK = "# ade-git-guard hook stub"
HOOKS_SRC = Path(__file__).resolve().parent.parent / "libexec" / "git-hooks"
EXIT_HOOKSPATH = 78     # install: core.hooksPath is set, git would never run the stubs (EX_CONFIG)
EXIT_PRE_ADE = 73       # install: NAME.pre-ade already exists, so the existing hook cannot be kept (EX_CANTCREAT)


def hook_is_agent(env: dict[str, str]) -> bool:
    """The caller of a hook is an agent: the shim's markers (ACP_RUN_AGENT, ADE_CLAIM_ID), or a harness marker
    (CLAUDECODE, OMPCODE, CODEX_*) that names no claim: such an agent may write nothing that is claimed. A human, git's
    own hooks (GIT_INDEX_FILE) and pre-commit (PRE_COMMIT) are never refused."""
    if env.get("GIT_INDEX_FILE") or env.get("PRE_COMMIT"):
        return False
    return is_agent_env(env) or bool(env.get("CLAUDECODE") or env.get("OMPCODE")) or any(k.startswith("CODEX_") for k in env)


def _common_dir(gitdir: Path) -> Path:
    try:
        return (gitdir / _slurp(gitdir / "commondir").strip()).resolve()
    except OSError:
        return gitdir


# What the origin question must not inherit: every config scope but the repository's own file (round 11, 2026-10-25: the
# caller's -c / GIT_CONFIG_COUNT / GIT_CONFIG_PARAMETERS rewrote `remote.origin.url` for the question while the claim kept
# the real one), plus the variables that point git at another git dir or common dir. `--local` already ignores the
# global, system and command scopes; this is the belt to those braces.
_ORIGIN_QUESTION_DROP = ("HOME", "XDG_CONFIG_HOME", "GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE", "GIT_CONFIG")


def _config_origin(common: Path) -> str:
    """`remote.origin.url` as git answers for the REPOSITORY'S OWN config file and the files it includes (`git config
    --local --includes --get`: comments, quotes and escapes are git's to read; the caller's command-line, environment,
    global, system, HOME and XDG scopes are not read at all, so no caller can change the answer): the URL, or "" when it
    is unset (exit 1) or git did not answer (timeout, cannot start, a repository config or include that fails only for this
    question, e.g. an `includeIf "gitdir:<common dir>"` that is false for the caller's own git dir in a linked worktree).
    "" matches a claim of any origin (`claims_for_branch`): an unanswered question never switches the claim rule off, it
    widens it to every claim of the branch's name (round 11, 2026-10-25: a failure that was read as "no claim rule can be
    judged" let a hostile include turn the rule off). `git config` takes no ref lock, so a hook may run it. Asked of the
    COMMON dir: a linked worktree's own git dir has no `remote.*` (measured 2026-10-25)."""
    drop = {k: None for k in os.environ if k in _ORIGIN_QUESTION_DROP or k.startswith("GIT_CONFIG")}
    rc, out = _run_git(["--git-dir", str(common), "config", "--local", "--includes", "--get", "remote.origin.url"], 3, drop)
    return out.rstrip("\n") if rc == 0 else ""


def _hook_workspace(env: dict[str, str], cwd: str) -> Optional[Workspace]:
    """The workspace the hook runs in: git runs a hook with GIT_DIR exported in a linked worktree and with the cwd at the
    work tree's root (the git dir in a bare repository)."""
    gd = env.get("GIT_DIR")
    if gd:
        return workspace_for_gitdir(os.path.join(cwd, gd), cwd)
    ws = find_workspace(cwd)
    if ws is None and os.path.isfile(os.path.join(cwd, "HEAD")) and os.path.isdir(os.path.join(cwd, "objects")):
        ws = workspace_for_gitdir(cwd, cwd)
    return ws


def _proc_args(pid: int) -> Optional[tuple[str, list[str]]]:
    """(executable path, argv) of process `pid`, exact: /proc/PID/{exe,cmdline} on Linux, sysctl KERN_PROCARGS2 on macOS
    (NUL-separated, so an argv[0] holding spaces stays one word; `ps` joins argv with spaces and cannot tell)."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        exe = os.readlink(f"/proc/{pid}/exe")
        parts = raw[:-1].split(b"\0") if raw.endswith(b"\0") else raw.split(b"\0")
        return exe, [x.decode("utf-8", "replace") for x in parts]
    except OSError:
        pass
    if sys.platform != "darwin":
        return None
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        mib = (ctypes.c_int * 3)(1, 49, pid)            # CTL_KERN, KERN_PROCARGS2, pid
        size = ctypes.c_size_t(0)
        if libc.sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0:
            return None
        buf = ctypes.create_string_buffer(size.value)
        if libc.sysctl(mib, 3, buf, ctypes.byref(size), None, 0) != 0:
            return None
        data = buf.raw[:size.value]
        argc = int.from_bytes(data[:4], sys.byteorder)
        exe_b, _, rest = data[4:].partition(b"\0")
        # the kernel pads the exec path to a multiple of 8 bytes (measured on arm64, 2026-10-25: pad = -(len+1) mod 8 NULs
        # beyond its terminator); every NUL beyond that is the terminator of an EMPTY leading argument, which an `lstrip`
        # alone would eat (the argv would shift by one word and its first environment string would join it)
        padded = len(rest) - len(rest.lstrip(b"\0"))
        empty = padded - (-(len(exe_b) + 1)) % 8
        if empty < 0:
            return None                                # a layout this parse does not know: no answer, no exemption
        parts = ([b""] * empty + rest.lstrip(b"\0").split(b"\0"))[:argc]
        return exe_b.decode("utf-8", "replace"), [x.decode("utf-8", "replace") for x in parts]
    except (OSError, ValueError, AttributeError):
        return None


def _parent_is_pack_refs(env: dict[str, str]) -> bool:
    """Whether the git process that runs this hook is `git pack-refs` (which `gc` and `maintenance` spawn). pack-refs
    reports every ref it packs as `0 new` and every loose ref it prunes as `old 0`, but changes no value: measured
    2026-10-25, git 2.56. The stub exports the git process's pid in ADE_HOOK_GIT_PID. The process must be an executable
    named `git` (its real path, not its argv[0]) whose argv, parsed word by word, names `pack-refs`, and whose argv[0] is
    non-empty and also named `git` (round 11: an EMPTY argv[0] used to shift the macOS parse by one word, see `_proc_args`; a
    shifted argv would otherwise name `git` itself); a forged argv[0] ("git pack-refs") is skipped by the parse and exempts
    nothing. Same-uid residual: a program named `git` that sets a
    pack-refs argv, then runs the hook, or one that sets ADE_HOOK_GIT_PID itself, is believed (docs/git-guard.md)."""
    pid = env.get("ADE_HOOK_GIT_PID", "")
    if not pid.isdigit():
        return False
    got = _proc_args(int(pid))
    if got is None:
        return False
    exe, argv = got
    return (os.path.basename(exe) == "git" and len(argv) > 1 and bool(argv[0]) and os.path.basename(argv[0]) == "git"
            and parse_git_argv(argv[1:], os.sep, {}).sub == "pack-refs")


def _hook_refusal(rule: str, d: Decision, via: str, what: str, env: dict[str, str], cwd: str, extra: dict[str, Any]) -> int:
    """Log and print a hook refusal (or, under ACP_OPERATOR_APPROVED=git-guard, the override); the exit code is the guard's
    (77 refused, 0 override). The text names the owner, the claim id and the safe alternative, like the shim's."""
    ident = caller_ident(env) or ""
    approved = {x.strip() for x in env.get("ACP_OPERATOR_APPROVED", "").split(",") if x.strip()}
    override = OVERRIDE in approved
    append_guard_log({"ts": utc_now(), "outcome": "override" if override else "refused", "rule": rule, "via": via,
                      "claim": d.claim_id, "owner": d.owner, "ident": ident, "cwd": cwd, "pid": os.getpid(), **extra})
    if override:
        sys.stderr.write(f"ade-git-guard: ACP_OPERATOR_APPROVED={OVERRIDE}: allowed {_esc(what)} [{_esc(rule)}] (logged)\n")
        return 0
    me = _esc(ident or "no claim id")
    sys.stderr.write(f"ade-git-guard: REFUSED {_esc(what)} [{_esc(rule)}] by the {via} hook in {_esc(cwd)}\n"
                     + (f"  claim {_esc(d.claim_id)}: {_esc(d.owner)}; you are {me}.\n" if d.claim_id else
                        f"  {_esc(d.owner)}; you are {me}.\n")
                     + f"  Safe alternative: {_esc(d.message)}.\n"
                     "  Ask the owner through session-finder/relay.py; exit 77 is an answer, not an obstacle to route "
                     f"around. Logged in {_esc(guard_log_path())}.\n")
    return EXIT_REFUSED


def hook_ref(state: str, text: str, env: Optional[dict[str, str]] = None, cwd: Optional[str] = None) -> int:
    """`reference-transaction` (STATE, then lines `<old> <new> <ref>` on stdin). Refuses (77) only in `prepared`, which
    aborts git's transaction for every caller: a ref update that reaches `refs/heads/<b>` while another owner's active claim
    names `<b>` (or has it checked out), a `HEAD` or branch update while the hook runs in a workspace another agent
    claims, a `refs/stash` update in a linked worktree. Whatever argv wrote it (the grammar is git's, already resolved).
    In `committed` it logs every change to a claimed branch and never fails."""
    env = os.environ if env is None else env
    if state not in ("prepared", "committed") or not hook_is_agent(env):
        return 0
    cwd = cwd or os.getcwd()
    updates = [p for p in (ln.split(" ", 2) for ln in text.splitlines()) if len(p) == 3]
    if not updates:
        return 0
    ident = caller_ident(env)
    ws = _hook_workspace(env, cwd)
    origin = _config_origin(_common_dir(ws.gitdir)) if ws else ""
    if state == "committed":
        for old, new, ref in updates:
            if ref.startswith("refs/heads/"):
                cs = claims_for_branch(ref[len("refs/heads/"):], origin)
                if cs:
                    append_guard_log({"ts": utc_now(), "outcome": "ref-change", "via": "reference-transaction",
                                      "ref": ref, "old": old, "new": new, "ident": ident or "", "pid": os.getpid(),
                                      "claim": ",".join(str(c.get("id")) for c in cs), "cwd": str(ws.root if ws else cwd)})
        return 0
    wclaim = find_claim(ws) if ws else None
    foreign_ws = wclaim is not None and not is_mine(wclaim, ident)
    for old, new, ref in updates:
        d: Optional[Decision] = None
        rule = ""
        if ref.startswith("refs/heads/"):
            b = ref[len("refs/heads/"):]
            for c in claims_for_branch(b, origin):
                if not is_mine(c, ident):
                    rule = "ref-claimed-branch"
                    d = _foreign(c, rule, "message the owner; never move, delete or write another agent's branch "
                                          "(write your own branch instead)")
                    break
            if d is None and ws is not None:
                for root, gd in repo_worktrees(ws):
                    if _head_branch(gd) == b:
                        c = claim_at(root)
                        if c is not None and not is_mine(c, ident):
                            rule = "ref-checked-out-branch"
                            d = _foreign(c, rule, "message the owner; the branch is checked out in their workspace")
                            break
        if d is None and foreign_ws and wclaim is not None and (ref == "HEAD" or ref.startswith("refs/heads/")):
            rule = "ref-in-foreign-workspace"
            d = _foreign(wclaim, rule, FOREIGN_ALT)
        if d is None and ref == "refs/stash" and ws is not None and ws.linked:
            rule = "ref-stash-in-linked-worktree"
            d = Decision(False, rule, "commit to a WIP branch in your own workspace, or save `git diff > file`; refs/stash is "
                         "shared by every workspace of this repository", str((wclaim or {}).get("id") or ""),
                         owner_label(wclaim) if wclaim else "nobody; a linked worktree (shared refs/stash)")
        if d is not None:
            if _parent_is_pack_refs(env):
                return 0
            return _hook_refusal(rule, d, "reference-transaction", f"the update of `{ref}`", env, str(ws.root if ws else cwd),
                                 {"ref": ref, "old": old, "new": new})
    return 0


def hook_push(remote: str, url: str, text: str, env: Optional[dict[str, str]] = None, cwd: Optional[str] = None) -> int:
    """`pre-push` (REMOTE URL, then lines `<local ref> <local oid> <remote ref> <remote oid>` on stdin): refuses (77) a
    push whose remote ref is `refs/heads/<b>` while another owner's active claim, of the repository the URL names, claims
    `<b>` (deletion included). `push --no-verify` skips it; the shim refuses that."""
    env = os.environ if env is None else env
    if not hook_is_agent(env):
        return 0
    ident = caller_ident(env)
    cwd = cwd or os.getcwd()
    for ln in text.splitlines():
        parts = ln.split(" ")
        if len(parts) >= 3 and parts[2].startswith("refs/heads/"):
            b = parts[2][len("refs/heads/"):]
            for c in claims_for_branch(b, url):
                if not is_mine(c, ident):
                    d = _foreign(c, "push-foreign-branch", "push only your own branch; ask the owner to push (or to add you "
                                 f"to the claim's allow list); branch {b!r} is claimed")
                    ws = _hook_workspace(env, cwd)
                    return _hook_refusal("push-foreign-branch", d, "pre-push", f"the push of `{parts[2]}`", env,
                                         str(ws.root if ws else cwd), {"ref": parts[2]})
    return 0


def _stub_text(name: str) -> str:
    lines = [
        "#!/bin/bash",
        f"{STUB_MARK} (installed by `ade-git-guard install`, 2026-10-25). The logic is the ade checkout's own hook, run by",
        f"# absolute path: one copy. An older hook of this name was kept as {name}.pre-ade and runs after ours.",
        "# A missing checkout fails open (exit 0).",
        f"hook={shlex.quote(str(HOOKS_SRC / name))}",
        'case "$0" in */*) d="${0%/*}" ;; *) d=. ;; esac',
        f'pre="$d/{name}.pre-ade"',
        "export ADE_HOOK_GIT_PID=$PPID",
        "# The checkout's hook runs as a child, never exec'd: only its documented refusal code (77) refuses; any other",
        "# outcome (exit 1, 3, 126, a signal, no such file) lets git proceed, for agents and humans alike.",
        'if [ ! -x "$pre" ]; then',
        '  [ -x "$hook" ] || exit 0',
        '  "$hook" "$@"',
        '  [ $? -eq 77 ] && exit 77',
        "  exit 0",
        "fi",
        "input=$(cat)",
        'if [ -x "$hook" ]; then',
        "  printf '%s\\n' \"$input\" | \"$hook\" \"$@\"",
        '  [ $? -eq 77 ] && exit 77',
        "fi",
        "printf '%s\\n' \"$input\" | \"$pre\" \"$@\"",
        "exit $?",
    ]
    return "\n".join(lines) + "\n"


def _stubs_present(common: Path) -> bool:
    for name in HOOK_NAMES:
        try:
            with open(common / "hooks" / name, "r", encoding="utf-8", errors="replace") as f:
                if STUB_MARK not in f.read(400):
                    return False
        except OSError:
            return False
    return True


def _install_common(common: Path) -> tuple[int, list[str]]:
    """Write the chain-preserving stubs into `<common>/hooks` (atomic; idempotent; an existing hook of the same name that
    is not ours becomes NAME.pre-ade). Returns (exit code, one line per action)."""
    hooks = common / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    notes: list[str] = []
    for name in HOOK_NAMES:
        dest = hooks / name
        pre = hooks / f"{name}.pre-ade"
        want = _stub_text(name)
        have: Optional[str] = None
        if dest.is_file() and not dest.is_symlink():
            have = _slurp(dest)
        if have == want:
            notes.append(f"{name}: already installed")
            continue
        if (dest.exists() or dest.is_symlink()) and not (have is not None and STUB_MARK in have[:400]):
            if pre.exists() or pre.is_symlink():
                return EXIT_PRE_ADE, notes + [f"{name}: {dest} exists and is not ours, and {pre} exists too; not installed"]
            os.rename(dest, pre)
            notes.append(f"{name}: existing hook kept as {pre.name}")
        tmp = _write_temp(dest, want)
        os.chmod(tmp, 0o755)
        os.replace(tmp, dest)
        notes.append(f"{name}: installed")
    return 0, notes


def install_hooks(start: str = ".") -> tuple[int, list[str]]:
    """`ade-git-guard install [DIR]`: stubs into `$(git rev-parse --git-common-dir)/hooks` (one install covers every linked
    worktree). Refused (78) while core.hooksPath is set, because git would never run them; 2 when DIR is no repository."""
    rc, out = _run_git(["-C", start, "rev-parse", "--path-format=absolute", "--git-common-dir"])
    if rc != 0 or not out.strip():
        return 2, [f"{start} is not inside a git repository"]
    rc, hp = _run_git(["-C", start, "config", "--null", "--get-all", "core.hooksPath"])
    if rc == 0:                    # set, even to an empty value: git then looks there (or nowhere), never in <common>/hooks
        shown = hp.split("\0")[-2] if hp.count("\0") else hp
        return EXIT_HOOKSPATH, [f"core.hooksPath is set (`{shown}`): git would never run the stubs in {out.strip()}/hooks; "
                                "not installed. Unset it, or call the stubs from the hooks directory it names"]
    if rc != 1:
        return EXIT_HOOKSPATH, [f"git did not say whether core.hooksPath is set (exit {rc}); not installed"]
    return _install_common(Path(out.strip()))


def _lazy_install(call: GitCall, env: dict[str, str]) -> None:
    """The shim's slow path installs the hooks the first time it meets a repository without them. Never raises, never in
    a directory that is not a git repository, never while core.hooksPath is set (git would not run them)."""
    try:
        ws = call.ws
        if ws is None or not (ws.gitdir / "HEAD").exists():
            return
        common = _common_dir(ws.gitdir)
        if _stubs_present(common):
            return
        rc, _ = _call_git(call, "config", "--null", "--get-all", "core.hooksPath")
        if rc != 1:        # 0: set (even to an empty value), git would not run the stubs; anything else: git did not answer
            return
        _install_common(common)
    except Exception:   # noqa: BLE001 - a failed install must never fail the user's git command
        pass


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------

def _hook_cli(argv: Sequence[str]) -> int:
    """`hook-ref STATE` and `hook-push REMOTE URL` (run by libexec/git-hooks/*; stdin is git's). The stub maps exit 77 to a
    refusal and everything else to success, so a crash or the 10 s alarm lets git proceed."""
    import signal
    signal.signal(signal.SIGALRM, lambda *_: os._exit(3))
    signal.alarm(10)
    text = sys.stdin.read()
    if argv[0] == "hook-ref" and len(argv) == 2:
        return hook_ref(argv[1], text)
    if argv[0] == "hook-push" and len(argv) == 3:
        return hook_push(argv[1], argv[2], text)
    print("usage: ade_claims.py hook-ref STATE | hook-push REMOTE URL", file=sys.stderr)
    return 2


def _cli(argv: Sequence[str]) -> int:
    if argv and argv[0] == "guard":
        rest = list(argv[1:])
        if rest and rest[0] == "--":
            rest = rest[1:]
        return guard_argv(rest)
    if argv and argv[0] in ("hook-ref", "hook-push"):
        return _hook_cli(argv)
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
    ins = sp.add_parser("install", help="install the ref hooks into the repository of DIR (exit 2 not a repository, "
                                         "78 core.hooksPath is set, 73 a .pre-ade file is in the way)")
    ins.add_argument("dir", nargs="?", default=".")
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
        elif a.cmd == "install":
            rc, notes = install_hooks(a.dir)
            for line in notes:
                print(f"ade_claims: {line}", file=sys.stderr if rc else sys.stdout)
            return rc
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
