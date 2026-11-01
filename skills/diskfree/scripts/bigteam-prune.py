#!/usr/bin/env python3
"""bigteam-prune.py: remove finished fan-out checkouts under ~/.local/state/bigteam without losing work or reports
(skills/diskfree step 7; operator's go first).

This script DELETES directories, so every check fails closed: any error, timeout or doubt keeps the checkout.

Only task dirs (real directories directly under the root, never symlinks, never resolving outside it) at least 7 days
old, with no CLAIM file (a CLAIM that records DONE still blocks) and no unfinished job record (jobs/*.json without
`finished`). Inside them, a git checkout is removed only when ALL of this holds:
  - git itself says the checkout's top level is that directory (a broken `.git` never falls through to an enclosing
    repository), with every GIT_* environment variable cleared for every git call;
  - nothing in the checkout changed in the last 7 days (newest mtime of the directory, index, HEAD, HEAD reflog,
    FETCH_HEAD), and no rebase, merge, cherry-pick, revert, bisect or sequencer is in progress;
  - `git status --porcelain=v1 -z --ignored=matching` run with untracked files forced on and submodules never ignored
    lists nothing but ignored paths; no tracked file is marked assume-unchanged or skip-worktree; no submodule;
  - at least one remote is configured, and no remote URL (fetch or push, insteadOf applied) is, or might be, a path
    inside the bigteam root (sibling checkouts that fetch each other would count each other's unpushed commits as "on
    a remote"): `file://` URLs are percent-decoded as git does, scp-like `host:path` and ssh hosts are resolved with
    `ssh -G` for the URL's own user and port; only a host that resolves to addresses none of which is this machine's (loopback, or an interface
    address, tested by binding) counts as another machine; anything else (a local name, an alias `ssh -G` cannot
    resolve, a name that does not resolve, `x::y` helper transports, odd schemes, `file://otherhost/...`) keeps the
    checkout;
  - an IGNORED path is only allowed when it is a known generated directory (node_modules .venv venv __pycache__
    .pytest_cache .mypy_cache .ruff_cache) holding no nested git repository and no unreadable subdirectory and no bare repository (HEAD+objects+refs) anywhere inside; any other
    ignored file or directory (a report, an `out.rc`, a database, a scratch repo, anything under `.cache`) keeps the
    checkout;
  - the git dir holds only git's standard entries (a note, a custom hook, an LFS store, a customised info/exclude in
    `.git` keeps the checkout); `.git/config` content is not preserved or judged;
  - a linked worktree: a standard `<main>/.git/worktrees/NAME` worktree whose HEAD is on a remote-tracking branch, with no
    refs/worktree, refs/bisect or refs/rewritten ref and nothing in its HEAD reflog that is missing from the remote,
    branch and tag refs (`git worktree remove` deletes both); it is removed with `git worktree remove` (no --force)
    from its main repository, so its branch stays there;
  - a clone: `git worktree list` lists only itself, no stash, and nothing in ANY ref (branches, tags, notes, HEAD, so a
    detached HEAD too) or reflog is missing from the remote-tracking refs.
"On a remote" means the local remote-tracking refs; they are never fetched or verified, so a branch deleted upstream, or
a remote that is a local path outside the root, still counts. A repository borrowing objects from a clone
(`git clone --shared`, objects/info/alternates) cannot be detected from the clone's side. Right before each deletion (and again after the safety scan) the task
dir is re-judged (still a real dir under the root, mtime unchanged since planning apart from our own removals, no
CLAIM, no unfinished or unreadable job record; the 7-day age is qualified once, at planning) and the checkout's safety is re-checked; a clone that fails part way through rmtree is left half deleted (it was clean and pushed).
`--apply` takes an exclusive lock (`bigteam-prune.lock` beside the root) and exits 3 when another run holds it.
Every commit named by a root pseudo-ref in the git dir (ORIG_HEAD, FETCH_HEAD, REBASE_HEAD, ...) must also be on a
remote (a linked worktree: or a branch or tag), and no directory below the checkout may be a git repository of its own
(a `.git` entry or a bare repository), tracked or not.
Everything kept is printed with its reason.

bigteam-prune.py [--apply]     (without --apply: dry run, prints the plan)
"""
import errno
import json
import os
import ipaddress
import shutil
import socket
import fcntl
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

B = Path.home() / ".local/state/bigteam"
MIN_AGE = 7 * 86400
GENERATED = {"node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
STATE_PATHS = ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "sequencer")


def git_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def git(d, *a, timeout=120, stdin=None):
    """(returncode, stdout); 124 on timeout, 127 when git cannot run. Never raises."""
    cmd = ["git", "-c", "status.showUntrackedFiles=all", "-c", "core.fsmonitor=false", "-C", str(d), *a]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="surrogateescape", timeout=timeout, env=git_env(),
                           input=stdin, stdin=None if stdin is not None else subprocess.DEVNULL)
        return r.returncode, r.stdout
    except subprocess.TimeoutExpired:
        return 124, ""
    except OSError:
        return 127, ""


def root_resolved():
    return B.resolve()


def inside_root(p):
    try:
        return p.resolve().is_relative_to(root_resolved())
    except (OSError, RuntimeError):
        return False


def task_dirs():
    """Real directories directly under B: a symlink, or anything resolving elsewhere, is skipped."""
    root = root_resolved()
    out = []
    for p in sorted(B.iterdir()):
        if p.is_symlink() or not p.is_dir():
            continue
        try:
            if p.resolve().parent != root:
                continue
        except (OSError, RuntimeError):
            continue
        out.append(p)
    return out


def finished_dir(d):
    try:
        if time.time() - d.stat().st_mtime < MIN_AGE:
            return False
    except OSError:
        return False
    return unclaimed_and_jobs_done(d)


def unclaimed_and_jobs_done(d):
    """No CLAIM and every jobs/*.json finished. Directory-read errors propagate to the except and keep the task."""
    try:
        if os.path.lexists(d / "CLAIM"):
            return False
        jobs = d / "jobs"
        if jobs.is_symlink():
            return False
        if os.path.lexists(jobs):
            for j in sorted(os.listdir(jobs)):
                if j.endswith(".json") and not json.loads((jobs / j).read_text()).get("finished"):
                    return False
    except (OSError, ValueError, AttributeError):
        return False
    return True


def checkouts(d):
    """Top-most directories under d that are git checkouts (a .git dir, file or link), not descending into them.
    os.walk never follows a symlinked directory."""
    out = []
    for root, dirs, _files in os.walk(d):
        if os.path.lexists(Path(root) / ".git") and Path(root) != d:
            out.append(Path(root))
            dirs[:] = []
            continue
        dirs[:] = [x for x in dirs if x != ".git"]
    return out


def scan(c):
    """(dirty, ignored_paths) from `git status`, or None when it cannot be read. Untracked files are forced on and
    submodules never ignored, whatever the repository's config says; -z gives raw, unquoted paths."""
    rc, out = git(c, "status", "--porcelain=v1", "-z", "--ignored=matching", "--untracked-files=all", "--ignore-submodules=none")
    if rc:
        return None
    ignored = []
    for e in out.split("\0"):
        if not e:
            continue
        if e.startswith("!! "):
            ignored.append(e[3:])
        else:
            return True, ignored
    return False, ignored


def nested_repo(c):
    """A reason when anything below checkout c (tracked, ignored or otherwise) is a git repository of its own: a `.git`
    entry or a bare repository's HEAD+objects+refs. `git status` never reports a nested repo that sits in an already
    tracked directory, so the whole tree is walked. c's own `.git` is skipped; links are not followed; any read error
    keeps the checkout."""
    def fail(e):
        raise e

    try:
        for root, dirs, files in os.walk(c, onerror=fail):
            here = Path(root)
            if here == c:
                dirs[:] = [x for x in dirs if x != ".git"]
            elif ".git" in dirs or ".git" in files:
                return f"nested git repository at {here.relative_to(c)}"
            if "HEAD" in files and "objects" in dirs and "refs" in dirs:
                return f"nested bare repository at {here.relative_to(c)}"
    except OSError as e:
        return f"checkout tree unreadable ({e})"
    return None


def pseudo_ref_commits(gitdir):
    """The object ids held by root pseudo-refs in a git dir (ORIG_HEAD, FETCH_HEAD, REBASE_HEAD, ... any `*_HEAD`
    file; not HEAD itself), or None when one cannot be read. They survive a reflog expiry and a `reset`."""
    out = []
    try:
        for e in Path(gitdir).iterdir():
            if e.name != "HEAD" and re.fullmatch(r"[A-Z][A-Z_]*HEAD", e.name) and e.is_file():
                for ln in e.read_text(errors="replace").splitlines():
                    tok = ln.split(None, 1)[0] if ln.strip() else ""
                    if tok:
                        out.append(tok)
    except OSError:
        return None
    return out


def ignored_ok(c, rel):
    """An ignored path is expendable only when it is a real generated directory with no nested git repository (a `.git`
    entry, or a bare repository's HEAD+objects+refs) and no unreadable subdirectory (a nested repo could hide there).
    Generic names like .cache are not on the list: an agent may write a report under them."""
    rel = rel.rstrip("/")
    if rel.rsplit("/", 1)[-1] not in GENERATED:
        return False
    p = c / rel
    if p.is_symlink() or not p.is_dir():
        return False

    def fail(e):
        raise e

    try:
        for root, dirs, files in os.walk(p, onerror=fail):
            if ".git" in dirs or ".git" in files:
                return False
            if "HEAD" in files and "objects" in dirs and "refs" in dirs:
                return False  # a bare repository: its commits are invisible to the outer checkout's checks
    except OSError:
        return False
    return True


LOCAL_HOSTS = {"", "localhost", "localhost.localdomain", "0.0.0.0", "::", "::1"}
SSH_SCHEMES = {"ssh", "git+ssh", "ssh+git"}
NET_SCHEMES = {"http", "https", "ftp", "ftps", "git"} | SSH_SCHEMES


def resolve_addrs(host):
    """[(family, sockaddr)] for host, or None when it does not resolve (the caller then cannot call it external)."""
    try:
        return [(f, sa) for f, _t, _p, _c, sa in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)] or None
    except (OSError, UnicodeError):
        return None


def is_local_address(family, sockaddr):
    """True when the address belongs to one of this machine's interfaces: loopback, unspecified, or one a socket can
    bind to (only a local address binds). An unexpected error counts as local (fail closed)."""
    try:
        ip = ipaddress.ip_address(str(sockaddr[0]).split("%")[0])
        if ip.is_loopback or ip.is_unspecified:
            return True
    except ValueError:
        return True
    try:
        with socket.socket(family, socket.SOCK_STREAM) as s:
            s.bind((sockaddr[0], 0) + tuple(sockaddr[2:]))
    except OSError as e:
        return e.errno != errno.EADDRNOTAVAIL
    return True


def ssh_real_host(host, user=None, port=None):
    """The HostName `ssh -G` resolves an alias to (config only, no connection), for the remote user and port the URL
    names (a `Match user git` block can route the same host elsewhere); None when it cannot be established (ssh
    missing, failing, timing out or printing no hostname), which keeps the checkout."""
    cmd = ["ssh", "-G"] + (["-l", user] if user else []) + (["-p", str(port)] if port else []) + ["--", host]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, env=git_env(), stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode:
        return None
    for ln in r.stdout.splitlines():
        if ln.lower().startswith("hostname ") and ln.split(None, 1)[1].strip():
            return ln.split(None, 1)[1].strip()
    return None


def host_is_external(host, via_ssh, user=None, port=None):
    """True only when host is positively another machine: not empty, not a local name, (for ssh) the alias resolved,
    the name resolves, and no resolved address is one of this machine's. Anything else is not 'external'."""
    host = host.strip("[]").lower()
    if not host:
        return False
    if via_ssh:
        host = ssh_real_host(host, user, port)
        if host is None:
            return False
        host = host.strip("[]").lower()
    mine = {socket.gethostname().lower(), socket.getfqdn().lower()}
    mine |= {m.split(".")[0] for m in mine}
    if host in LOCAL_HOSTS or host in mine:
        return False
    addrs = resolve_addrs(host)
    if not addrs:
        return False
    return not any(is_local_address(f, sa) for f, sa in addrs)


def classify_url(url):
    """('remote', None) for a network URL positively to another host; ('path', [raw paths]) for something git reads from
    this machine (a plain path, `file://` with git's percent-decoding); ('unknown', None) for anything else: helper
    transports `x::y`, odd schemes, unparsable URLs, a host that is this machine or does not resolve. The caller keeps
    the clone on 'unknown'."""
    if not url:
        return "unknown", None
    try:
        if "://" in url:
            parts = urlsplit(url)
            scheme = parts.scheme.lower()
            if scheme == "file":
                if parts.netloc.lower() not in ("", "localhost"):
                    return "unknown", None
                return "path", [parts.path, unquote(parts.path)]
            if scheme in NET_SCHEMES:
                ssh = scheme in SSH_SCHEMES
                user, port = (unquote(parts.username), parts.port) if ssh and parts.username else (None, parts.port if ssh else None)
                return ("remote", None) if host_is_external(parts.hostname or "", ssh, user, port) else ("unknown", None)
            return "unknown", None
        head = url.split("/", 1)[0]
        if "::" in head and not head.startswith("["):
            return "unknown", None
        if ":" in head:  # scp-like [user@]host:path
            userhost = head.rsplit(":", 1)[0]
            user, _at, host = userhost.rpartition("@")
            host = host.strip("[]")
            if len(host) <= 1:
                return "unknown", None  # a drive letter or nonsense
            return ("remote", None) if host_is_external(host, True, user or None) else ("unknown", None)
        return "path", [url]
    except ValueError:
        return "unknown", None


def local_remote_inside_root(c):
    """A reason when a remote of c (fetch or push URL, insteadOf applied) is, or might be, a path inside the bigteam
    root, else None. Sibling checkouts that fetch each other would otherwise each count the other's unpushed commits as
    'on a remote'. git's own URL rules are followed (`file://` percent-decoding, scp-like `host:path`); a URL the
    script cannot fully resolve counts as local. Fails closed: an unreadable remote list counts as local."""
    rc, names = git(c, "remote")
    if rc:
        return "unreadable"
    root = str(root_resolved())
    for name in names.split():
        for extra in ((), ("--push",)):
            rc, urls = git(c, "remote", "get-url", "--all", *extra, name)
            if rc:
                return "unreadable"
            for url in urls.splitlines():
                url = url.strip()
                kind, paths = classify_url(url)
                if kind == "remote":
                    continue
                if kind == "unknown":
                    return f"{url or '(empty)'} (cannot be resolved)"
                for path in paths:
                    try:
                        path = os.path.expanduser(path)
                        cands = {os.path.realpath(path), os.path.realpath(os.path.join(str(c), path))}
                    except (OSError, ValueError):
                        return f"{url} (cannot be resolved)"
                    if any(cand == root or cand.startswith(root + os.sep) for cand in cands):
                        return url
    return None


def git_path(c, name):
    rc, out = git(c, "rev-parse", "--path-format=absolute", "--git-path", name)
    return Path(out.strip()) if rc == 0 and out.strip() else None


def newest_activity(c):
    t = c.stat().st_mtime
    for name in ("index", "HEAD", "logs/HEAD", "FETCH_HEAD"):
        p = git_path(c, name)
        if p is None:
            raise OSError(name)
        try:
            t = max(t, p.stat().st_mtime)
        except FileNotFoundError:
            pass
    return t


# What a plain clone or linked worktree's git dir may hold: anything else (a note, a custom hook, an LFS store, ...) is
# invisible to `git status` and would go with the directory, so it keeps the checkout.
GITDIR_CLONE = {"HEAD", "config", "description", "hooks", "info", "objects", "refs", "logs", "packed-refs", "index",
                "FETCH_HEAD", "ORIG_HEAD", "COMMIT_EDITMSG", "branches", "shallow", "AUTO_MERGE", "worktrees"}
GITDIR_LINKED = {"HEAD", "commondir", "gitdir", "index", "logs", "ORIG_HEAD", "refs", "FETCH_HEAD", "COMMIT_EDITMSG", "AUTO_MERGE"}
OBJECTS_OK = re.compile(r"^([0-9a-f]{2}|info|pack)$")


def odd_gitdir(gitdir):
    """A reason when the git dir holds something git status cannot see, else None. Fails closed on any read error."""
    g = Path(gitdir)
    allowed = GITDIR_CLONE if (g / "objects").is_dir() else GITDIR_LINKED
    try:
        for e in g.iterdir():
            if e.name not in allowed:
                return f"git dir holds a non-standard entry ({e.name!r})"
        if g.name == ".git":
            for e in (g / "objects").iterdir():
                if not OBJECTS_OK.match(e.name):
                    return f"git dir holds a non-standard objects entry ({e.name!r})"
            for e in (g / "hooks").iterdir():
                if not e.name.endswith(".sample"):
                    return f"git dir holds a custom hook ({e.name!r})"
            for e in (g / "info").iterdir():
                if e.name not in ("exclude", "refs"):
                    return f"git dir holds a non-standard info entry ({e.name!r})"
            ex = g / "info/exclude"
            if ex.exists() and any(ln.strip() and not ln.lstrip().startswith("#") for ln in ex.read_text(errors="replace").splitlines()):
                return "git dir has a customised info/exclude"
    except OSError as e:
        return f"git dir unreadable ({e})"
    return None


def identity(c):
    """(None, 'linked'|'clone', gitdir) when c is a standard checkout git agrees about, else (reason, None, None)."""
    gp = c / ".git"
    if c.is_symlink() or gp.is_symlink() or not inside_root(c):
        return "symlink or outside the bigteam root", None, None
    if not (gp.is_file() or gp.is_dir()):
        return ".git is neither a file nor a directory", None, None
    rc, top = git(c, "rev-parse", "--show-toplevel")
    if rc or not top.strip() or os.path.realpath(top.strip()) != os.path.realpath(c):
        return "git does not report this directory as its own top level (unreadable)", None, None
    rc1, gitdir = git(c, "rev-parse", "--path-format=absolute", "--absolute-git-dir")
    rc2, common = git(c, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if rc1 or rc2:
        return "git dir unreadable", None, None
    gitdir, common = os.path.realpath(gitdir.strip()), os.path.realpath(common.strip())
    if gp.is_dir():
        if gitdir != common or gitdir != os.path.realpath(gp):
            return "unexpected git dir layout", None, None
        return None, "clone", gitdir
    if Path(common).name != ".git" or Path(gitdir).parent != Path(common) / "worktrees":
        return "not a standard linked worktree (submodule, bare main repository or odd layout)", None, None
    return None, "linked", gitdir


def safe(c):
    why, kind, gitdir = identity(c)
    if why:
        return False, why
    linked = kind == "linked"
    try:
        if time.time() - newest_activity(c) < MIN_AGE:
            return False, "changed within the last 7 days"
    except OSError:
        return False, "activity unreadable"
    for name in STATE_PATHS:
        p = git_path(c, name)
        if p is None or os.path.lexists(p):
            return False, f"{name} in progress or unreadable"
    rc, flags = git(c, "ls-files", "-v", "-z")
    if rc:
        return False, "index unreadable"
    for e in flags.split("\0"):
        if e and (e[0].islower() or e[0] == "S"):
            return False, "a tracked file is assume-unchanged or skip-worktree (status cannot see its changes)"
    rc, staged = git(c, "ls-files", "--stage", "-z")
    if rc:
        return False, "index unreadable"
    if any(e.startswith("160000 ") for e in staged.split("\0")):
        return False, "has submodules (their unpushed commits live inside the checkout)"
    res = scan(c)
    if res is None:
        return False, "status unreadable"
    dirty, ignored = res
    if dirty:
        return False, "uncommitted or untracked files"
    odd = [i for i in ignored if not ignored_ok(c, i)]
    if odd:
        return False, f"holds ignored files of its own ({odd[0]!r}...)" if len(odd) > 1 else f"holds an ignored file of its own ({odd[0]!r})"
    why = odd_gitdir(gitdir)
    if why:
        return False, why
    why = nested_repo(c)
    if why:
        return False, why
    rc, rem = git(c, "remote")
    if rc or not rem.split():
        return False, "no remote"
    local = local_remote_inside_root(c)
    if local:
        return False, f"a remote is a local path inside the bigteam root ({local}): its remote-tracking refs may be a sibling's copy"
    detached = False
    if linked:
        # a linked worktree's branches and tags live in its main repository and survive `git worktree remove`;
        # its HEAD reflog and its per-worktree refs do not, and its checked-out commit must exist on a remote
        rc, on = git(c, "branch", "-r", "--contains", "HEAD")
        if rc or not on.strip():
            return False, "HEAD is on no remote branch"
        rc, pw = git(c, "for-each-ref", "refs/worktree", "refs/bisect", "refs/rewritten")
        if rc or pw.strip():
            return False, "has per-worktree refs (refs/worktree, refs/bisect, refs/rewritten) or they are unreadable"
        rc, hs = git(c, "log", "-g", "--format=%H", "HEAD")
        if rc:
            return False, "HEAD reflog unreadable"
        if hs.split():
            rc, un = git(c, "rev-list", "--stdin", "--not", "--remotes", "--branches", "--tags", stdin=hs)
            if rc or un.strip():
                return False, f"{len(un.split())} commit(s) only in this worktree's HEAD reflog, on no remote, branch or tag (or unreadable)"
        rc, _sym = git(c, "symbolic-ref", "-q", "HEAD")
        detached = rc != 0
    else:
        rc, wl = git(c, "worktree", "list", "--porcelain")
        trees = [ln[len("worktree "):] for ln in wl.splitlines() if ln.startswith("worktree ")]
        if rc or len(trees) != 1 or os.path.realpath(trees[0]) != os.path.realpath(c):
            return False, "other linked worktrees are attached to this clone (or the list is unreadable)"
        rc, stash = git(c, "stash", "list")
        if rc or stash.strip():
            return False, "has stashes (or unreadable)"
        rc, un = git(c, "log", "--oneline", "--all", "--not", "--remotes")
        if rc or un.strip():
            return False, f"{len(un.splitlines())} commit(s) on a branch, tag, HEAD or other ref not on a remote (or unreadable)"
        rc, un = git(c, "rev-list", "--reflog", "--not", "--remotes")
        if rc or un.strip():
            return False, f"{len(un.split())} reflog-only commit(s) not on a remote (or unreadable)"
    pseudo = pseudo_ref_commits(gitdir)
    if pseudo is None:
        return False, "root pseudo-refs (ORIG_HEAD, FETCH_HEAD, ...) unreadable"
    if pseudo:
        # a linked worktree's branches and tags survive its removal; a clone keeps only what a remote has
        keep_refs = ["--remotes", "--branches", "--tags"] if linked else ["--remotes"]
        rc, un = git(c, "rev-list", "--stdin", "--not", *keep_refs, stdin="\n".join(pseudo) + "\n")
        if rc or un.strip():
            return False, "a root pseudo-ref (ORIG_HEAD, FETCH_HEAD, ...) holds a commit on no remote (or is unreadable)"
    note = ("; detached, no branch to keep" if detached else "; branch kept in main repo") if linked else ""
    return True, "clean; commits on a remote" + note


def task_still_eligible(c, task, baseline):
    """(ok, why): the task dir that held c at planning time is still a real, unclaimed, finished task dir nobody has
    touched since. Its mtime must equal the planning-time value (our own earlier removals update it through
    `baseline`), so a new CLAIM, job record or any new entry makes it differ. Fails closed."""
    try:
        if task.is_symlink() or not task.is_dir() or task.resolve().parent != root_resolved():
            return False, "task dir is no longer a real directory under the root"
        if not c.resolve().is_relative_to(task.resolve()):
            return False, "checkout is not inside its task dir"
        if task not in baseline or task.stat().st_mtime != baseline[task]:
            return False, "task dir changed since planning"
    except (OSError, RuntimeError):
        return False, "task dir unreadable"
    if not unclaimed_and_jobs_done(task):  # the age was qualified at planning; the mtime check above guards it since
        return False, "task dir is claimed or has an unfinished or unreadable job record"
    return True, ""


def remove(c, task, baseline):
    """(removed, message). Re-checks the task's eligibility and the checkout's safety right before deleting. A clone
    that fails part way through rmtree is left half deleted, but it passed safe(), so every commit in it is on a
    remote and nothing in it was a report."""
    ok, why = task_still_eligible(c, task, baseline)
    if not ok:
        return False, f"no longer eligible: {why}"
    ok, why = safe(c)
    if not ok:
        return False, f"no longer safe: {why}"
    ok, why = task_still_eligible(c, task, baseline)  # safe() runs many subprocesses: a CLAIM may have appeared meanwhile
    if not ok:
        return False, f"no longer eligible: {why}"
    try:
        res = _remove(c)
    finally:
        try:
            baseline[task] = task.stat().st_mtime  # our own removal changes the task dir's mtime
        except OSError:
            baseline.pop(task, None)
    return res


def _remove(c):
    if (c / ".git").is_file():  # a linked worktree: remove through its main repository
        rc, common = git(c, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if rc:
            return False, "git worktree remove not run: common dir unreadable"
        common = Path(os.path.realpath(common.strip()))
        main = common.parent
        rc, mc = git(main, "rev-parse", "--path-format=absolute", "--git-common-dir")
        if rc or os.path.realpath(mc.strip()) != str(common):
            return False, f"git worktree remove not run: {main} is not the main repository"
        rc, _ = git(main, "worktree", "remove", str(c))
        return (True, "worktree removed") if rc == 0 else (False, "git worktree remove failed")
    try:
        shutil.rmtree(c)
    except OSError as e:
        return False, f"rmtree failed part way (left half deleted; it was clean and pushed): {e}"
    return True, "clone deleted"


def take_lock():
    """An exclusive, non-blocking flock on a file beside the root, held until the process ends; None when not taken."""
    try:
        fd = os.open(str(B.parent / "bigteam-prune.lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def size_kb(c):
    try:
        r = subprocess.run(["du", "-sk", str(c)], capture_output=True, text=True, timeout=300)
        return int(r.stdout.split()[0])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return 0


def main():
    apply = "--apply" in sys.argv
    lock = None
    if apply:
        lock = take_lock()
        if lock is None:
            print("another bigteam-prune --apply holds the lock (or it cannot be taken); nothing done", file=sys.stderr)
            sys.exit(3)
    plan, kept, freed = [], [], 0
    baseline = {}  # task dir -> its mtime when it was judged finished
    for d in task_dirs():
        if not finished_dir(d):
            continue
        try:
            baseline[d] = d.stat().st_mtime
        except OSError:
            continue
        for c in checkouts(d):
            ok, why = safe(c)
            (plan if ok else kept).append((c, d, size_kb(c), why))
    for c, d, size, why in plan:
        ok, res = remove(c, d, baseline) if apply else (True, "would remove")
        if ok and apply:
            freed += size
        print(f"{'REMOVED' if apply and ok else ('KEPT' if apply else 'PLAN')} {size/1024:7.1f} MB {c} ({res})")
    for c, d, size, why in kept:
        print(f"KEEP    {size/1024:7.1f} MB {c} ({why})")
    print(f"{'freed' if apply else 'would free'}: {freed/1048576 if apply else sum(p[2] for p in plan)/1048576:.2f} GB; kept {len(kept)} checkout(s)")
    if lock is not None:
        os.close(lock)


if __name__ == "__main__":
    main()
