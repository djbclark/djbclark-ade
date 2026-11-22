"""Registry of desired future cherry-picks into our patched fork builds.

An operator-driven local build aid (docs/fork-picks.md), not a publication path:
it reads `config/fork-picks.toml`, cherry-picks queued and carried entries onto a
linked worktree's branch, edits an entry's status line, and reports entries the
upstream already carries. It never pushes and never touches a remote beyond
`git fetch`. Every subprocess gets an argv list (no shell).

Exit codes: 0 ok, 1 refused (a precondition failed, nothing changed), 2 error
(bad registry/usage/fetch/tool failure), 3 apply stopped (a conflict, aborted and
tree clean, or an entry's head moved), 4 check-upstream found drop candidates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
REGISTRY_PATH = HERE.parent / "config" / "fork-picks.toml"
FORKS_PATH = HERE.parent / "config" / "forks.toml"
SCHEMA_VERSION = 1
NETWORK_TIMEOUT = 600
LOCAL_TIMEOUT = 120

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}\Z")  # \Z: `$` also accepts a trailing newline, which never matches a commit
OWNER_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)/([A-Za-z0-9._-]+)$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
TARGET_RE = re.compile(r"^[a-z][a-z0-9]*-build-[1-9][0-9]*$")
STATUS_RE = re.compile(r"^(queued|carried|landed:([1-9][0-9]*|main)|upstreamed|dropped)$")
MARK_RE = re.compile(r"^(carried|landed:([1-9][0-9]*|main)|upstreamed|dropped)$")
ACTIVE = ("queued", "carried")
OWN_ORGS = {"frdminc", "djbclark"}  # branches of these owners may be unpinned; every other source must pin
# Unicode categories never allowed in notes and replaced in third-party text: control, format (bidi
# overrides, zero-width, BOM), line and paragraph separators (U+2028/9) and surrogates.
BAD_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp", "Cs"})
PR_RE = re.compile(r"^https://github\.com/[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9._-]+/pull/[0-9]+/?$")
FIELDS = {"id", "component", "repo", "commit", "branch", "pr", "local_path", "expected_head", "intent",
          "target", "targets", "status", "upstream", "order", "notes", "trial_required", "hold", "exclude"}
REQUIRED = {"id", "component", "intent", "status"}
STRING_FIELDS = ("id", "component", "repo", "intent", "target", "status", "commit", "branch", "upstream",
                 "notes", "local_path", "expected_head", "hold")

TRAILER_RE = re.compile(r"^\(cherry picked from commit ([0-9a-f]{40})\)[ \t]*$", re.M)
LARGE_PLAN = 20  # picks per entry above which the text output warns (a stacked or mis-based source)
EXIT_OK, EXIT_REFUSED, EXIT_ERROR, EXIT_STOPPED, EXIT_CANDIDATES = 0, 1, 2, 3, 4


class RegistryError(ValueError):
    """The registry or its inputs are unreadable or invalid (exit 2)."""


class Refused(RuntimeError):
    """A precondition failed; nothing was changed (exit 1)."""


class ToolError(RuntimeError):
    """A git/gh command failed or timed out (exit 2)."""


# --------------------------------------------------------------------------- parsing

def _credential_free_https(value: str, what: str) -> Any:
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username is not None \
            or parts.password is not None or "@" in parts.netloc or parts.query or parts.fragment:
        raise RegistryError(f"{what}: must be a credential-free https URL")
    return parts


def normalize_repo(value: str) -> str:
    """OWNER/NAME or a credential-free GitHub https URL -> https://github.com/O/N.git."""
    match = OWNER_NAME_RE.match(value)
    if match:
        owner, name = match.groups()
    else:
        parts = _credential_free_https(value, "repo")
        if parts.hostname.lower() != "github.com":
            raise RegistryError("repo: only github.com URLs are supported")
        segments = [s for s in parts.path.split("/") if s]
        if len(segments) != 2:
            raise RegistryError("repo: URL must be https://github.com/OWNER/NAME")
        owner, name = segments
        if not OWNER_NAME_RE.match(f"{owner}/{name}"):
            raise RegistryError("repo: invalid owner or name")
    if name.endswith(".git"):
        name = name[:-4]
    if not name or name in {".", ".."} or owner in {".", ".."}:
        raise RegistryError("repo: invalid owner or name")
    return f"https://github.com/{owner}/{name}.git"


def _validate_one(raw: dict[str, Any]) -> list[str]:
    """Field checks for one entry (id and component are checked by the caller); returns targets."""
    if "local_path" in raw:
        if "commit" not in raw or {"branch", "pr"} & set(raw):
            raise RegistryError("local_path requires a commit source (and no branch or pr)")
        if not os.path.isabs(raw["local_path"]) or raw["local_path"].startswith("-"):
            raise RegistryError("local_path must be an absolute path")
    sources = sum(k in raw for k in ("commit", "branch", "pr"))
    if sources == 0:  # placeholder: a reserved slot with no source yet; it must say why
        if "hold" not in raw:
            raise RegistryError("an entry with no source (commit, branch or pr) is a placeholder and requires hold")
        if "expected_head" in raw:
            raise RegistryError("expected_head needs a branch or pr source")
    elif sources != 1:
        raise RegistryError("exactly one of commit, branch or pr is required")
    if "repo" in raw:
        normalize_repo(raw["repo"])
    elif sources and "local_path" not in raw:
        raise RegistryError("repo is required (omit it only with local_path)")
    if "commit" in raw and not COMMIT_RE.match(raw["commit"]):
        raise RegistryError("commit must be a full 40-hex id (lowercase)")
    if "branch" in raw and (not BRANCH_RE.match(raw["branch"]) or ".." in raw["branch"]
                            or raw["branch"].endswith(("/", ".lock"))):
        raise RegistryError("branch has unsupported characters")
    if "pr" in raw and (type(raw["pr"]) is not int or raw["pr"] < 1):
        raise RegistryError("pr must be a positive integer")
    if "exclude" in raw:
        ex = raw["exclude"]
        if "branch" not in raw and "pr" not in raw:
            raise RegistryError("exclude applies to branch or pr sources only")
        if not isinstance(ex, list) or not ex or len(set(map(str, ex))) != len(ex) \
                or not all(isinstance(x, str) and COMMIT_RE.match(x) for x in ex):
            raise RegistryError("exclude must be a non-empty list of unique full 40-hex commit ids")
    if "expected_head" in raw:
        if "commit" in raw:
            raise RegistryError("expected_head applies to branch or pr sources only")
        if not COMMIT_RE.match(raw["expected_head"]):
            raise RegistryError("expected_head must be a full 40-hex id (lowercase)")
    if raw["status"] in ACTIVE and "expected_head" not in raw and (
            "pr" in raw or ("branch" in raw and normalize_repo(raw["repo"]).split("/")[3].lower() not in OWN_ORGS)):
        raise RegistryError("an active pr entry, or a branch of a repo outside our orgs, requires expected_head "
                            "(pin the head you reviewed; `apply --dry-run` prints the current tip)")
    if not raw["intent"].strip() or "\n" in raw["intent"]:
        raise RegistryError("intent must be one non-empty line")
    if ("target" in raw) == ("targets" in raw):
        raise RegistryError("exactly one of target or targets is required")
    targets = [raw["target"]] if "target" in raw else raw["targets"]
    if not isinstance(targets, list) or not targets or len(set(map(str, targets))) != len(targets) \
            or not all(isinstance(x, str) and TARGET_RE.match(x) for x in targets):
        raise RegistryError("target(s) must be unique PLATFORM-build-N strings (e.g. desktop-build-2)")
    if not STATUS_RE.match(raw["status"]):
        raise RegistryError("status must be queued, carried, landed:N, landed:main, upstreamed or dropped")
    if "upstream" in raw:
        _credential_free_https(raw["upstream"], "upstream")
    if "order" in raw and type(raw["order"]) is not int:
        raise RegistryError("order must be an integer")
    if "trial_required" in raw and type(raw["trial_required"]) is not bool:
        raise RegistryError("trial_required must be a boolean")
    if "hold" in raw and not raw["hold"].strip():
        raise RegistryError("hold must be a non-empty reason")
    return list(targets)


def validate_entries(data: dict[str, Any], component_ids: set[str]) -> list[dict[str, Any]]:
    if set(data) - {"schema_version", "pick"} or data.get("schema_version") != 1 \
            or type(data.get("schema_version")) is not int:
        raise RegistryError("registry requires schema_version=1 and [[pick]] entries only")
    picks = data.get("pick", [])
    if not isinstance(picks, list):
        raise RegistryError("pick must be an array of tables")
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for index, raw in enumerate(picks):
        if not isinstance(raw, dict):
            raise RegistryError(f"pick #{index + 1}: not a table")
        label = f"pick #{index + 1}" + (f" ({raw['id']})" if isinstance(raw.get("id"), str) else "")
        unknown = set(raw) - FIELDS
        if unknown:
            raise RegistryError(f"{label}: unknown field(s) {sorted(unknown)}")
        missing = REQUIRED - set(raw)
        if missing:
            raise RegistryError(f"{label}: missing field(s) {sorted(missing)}")
        for key in STRING_FIELDS:
            if key in raw and not isinstance(raw[key], str):
                raise RegistryError(f"{label}: {key} must be a string")
        if not ID_RE.match(raw["id"]):
            raise RegistryError(f"{label}: id must be kebab-case")
        if raw["id"] in seen:
            raise RegistryError(f"{label}: duplicate id")
        seen.add(raw["id"])
        if raw["component"] not in component_ids:
            raise RegistryError(f"{label}: component {raw['component']!r} is not in config/forks.toml")
        try:
            targets = _validate_one(raw)
        except RegistryError as error:
            raise RegistryError(f"{label}: {error}") from None
        entry = dict(raw)
        entry.pop("target", None)
        entry["targets"] = targets
        entry.setdefault("trial_required", False)
        entry["_index"] = index
        out.append(entry)
    return out


def _forks_rows(forks_path: Path) -> list[dict[str, Any]]:
    sys.path.insert(0, str(HERE))
    from ade_forks import PolicyError, load_policy
    try:
        return load_policy(forks_path)
    except PolicyError as error:
        raise RegistryError(str(error)) from error


def component_ids(forks_path: Path) -> set[str]:
    return {row["id"] for row in _forks_rows(forks_path)}


def load_registry(path: Path = REGISTRY_PATH, forks_path: Path = FORKS_PATH) -> list[dict[str, Any]]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise RegistryError(f"cannot read {path}: {type(error).__name__}: {error}") from error
    return validate_entries(data, component_ids(forks_path))


def is_placeholder(entry: dict[str, Any]) -> bool:
    """No commit, branch or pr: a reserved slot (validation requires a hold)."""
    return not any(k in entry for k in ("commit", "branch", "pr"))


def public(entry: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in entry.items() if not k.startswith("_")}


def status_matches(status: str, wanted: str | None) -> bool:
    """None = active (queued and carried); all; an exact status; or a status family (landed)."""
    if wanted is None:
        return status in ACTIVE
    return wanted == "all" or status == wanted or status.split(":", 1)[0] == wanted


def apply_order(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(entries, key=lambda e: (("order" not in e), e.get("order", 0), e["_index"]))


# --------------------------------------------------------------------------- subprocess

def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k not in {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"}}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def run(argv: list[str], *, cwd: Path | None = None, timeout: int = LOCAL_TIMEOUT,
        stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(argv, cwd=cwd, input=stdin, capture_output=True, text=True,
                              timeout=timeout, env=_env(), check=False)
    except subprocess.TimeoutExpired as error:
        raise ToolError(f"timed out after {timeout}s: {' '.join(argv[:4])}") from error
    except OSError as error:
        raise ToolError(f"cannot run {argv[0]}: {error}") from error


def git(wt: Path, *args: str, timeout: int = LOCAL_TIMEOUT, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return run(["git", "-C", str(wt), *args], timeout=timeout, stdin=stdin)


def git_ok(wt: Path, *args: str, timeout: int = LOCAL_TIMEOUT, stdin: str | None = None) -> str:
    result = git(wt, *args, timeout=timeout, stdin=stdin)
    if result.returncode != 0:
        raise ToolError(f"git {' '.join(args[:3])} failed (rc={result.returncode}): {result.stderr.strip()[:300]}")
    return result.stdout


def is_primary_checkout(path: Path) -> bool | None:
    """True for a primary checkout, False for a linked worktree, None if not a work tree."""
    result = git(path, "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir")
    lines = result.stdout.split("\n")
    if result.returncode != 0 or len(lines) < 2:
        return None
    return os.path.realpath(lines[0]) == os.path.realpath(lines[1])


# --------------------------------------------------------------------------- apply

IN_PROGRESS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply",
               "sequencer", "BISECT_LOG")


def check_workspace(wt: Path) -> tuple[str, str]:
    """Refuse unsuitable worktrees; return (branch, head)."""
    if not wt.is_dir():
        raise RegistryError(f"workspace {wt} is not a directory")
    primary = is_primary_checkout(wt)
    if primary is None:
        raise RegistryError(f"workspace {wt} is not a git work tree")
    if primary:
        raise Refused("workspace is a primary checkout; use a linked worktree (AGENTS.md order 9)")
    for name in IN_PROGRESS:
        path = git_ok(wt, "rev-parse", "--git-path", name).strip()
        path = Path(path) if os.path.isabs(path) else wt / path
        if path.exists():
            raise Refused(f"workspace is in the middle of an operation ({name} present)")
    branch = git(wt, "symbolic-ref", "-q", "--short", "HEAD")
    if branch.returncode != 0:
        raise Refused("workspace HEAD is detached; check out a branch first")
    if git_ok(wt, "status", "--porcelain", "--untracked-files=normal").strip():
        raise Refused("workspace tree is dirty (modified or untracked files)")
    return branch.stdout.strip(), git_ok(wt, "rev-parse", "HEAD").strip()


def source_of(entry: dict[str, Any]) -> str:
    """Where the entry's objects come from: local_path, else its GitHub repo URL."""
    return entry["local_path"] if "local_path" in entry else normalize_repo(entry["repo"])


def fetch_entry(wt: Path, entry: dict[str, Any]) -> str:
    """Fetch the entry's commit, branch or PR head into wt's object store; return the tip sha."""
    url = source_of(entry)
    if "commit" in entry:
        git_ok(wt, "fetch", "--no-tags", "--quiet", url, entry["commit"], timeout=NETWORK_TIMEOUT)
        tip = entry["commit"]
    else:
        ref = f"refs/pull/{entry['pr']}/head" if "pr" in entry else f"refs/heads/{entry['branch']}"
        git_ok(wt, "fetch", "--no-tags", "--quiet", url, ref, timeout=NETWORK_TIMEOUT)
        tip = git_ok(wt, "rev-parse", "FETCH_HEAD").strip()
    resolved = git_ok(wt, "rev-parse", "--verify", f"{tip}^{{commit}}").strip()
    if "commit" in entry and resolved != entry["commit"]:
        raise ToolError(f"{entry['id']}: fetched commit does not match {entry['commit']}")
    return resolved


def fetch_upstream_tip(wt: Path, url: str) -> str:
    """The component's upstream default-branch tip, fetched into wt's object store (fetch only)."""
    git_ok(wt, "fetch", "--no-tags", "--quiet", url, "HEAD", timeout=NETWORK_TIMEOUT)
    return git_ok(wt, "rev-parse", "--verify", "FETCH_HEAD^{commit}").strip()


def trailer_sources(wt: Path, tip: str) -> set[str]:
    """Shas named by `(cherry picked from commit X)` trailers (written by `cherry-pick -x`, which
    apply uses) on the commits HEAD has beyond `tip`'s history: the picks an earlier run made, which
    stay recognisable after a rebase changed their context and so their patch-id."""
    log = git_ok(wt, "log", "--format=%B%x00", "--fixed-strings", "--grep=(cherry picked from commit ",
                 "HEAD", "--not", tip)
    found: set[str] = set()
    for message in log.split("\x00"):
        # only the LAST such line of the message's final paragraph counts: `cherry-pick -x` always appends its own
        # line there, so a line copied from a picked commit's body (mid-message) names nothing
        paragraphs = re.split(r"\n[ \t]*\n", message.strip())
        names = TRAILER_RE.findall(paragraphs[-1]) if paragraphs and paragraphs[-1] else []
        if names:
            found.add(names[-1])
    return found


def plan_commits(wt: Path, entry: dict[str, Any], tip: str, upstream_tip: str | None = None) -> dict[str, Any]:
    """The plan for an entry whose tip is fetched: keys `picks`, `present`, `present_by_trailer`,
    `excluded_upstream`, `excluded_by_entry`, `exclude_unused`.

    Candidates are the non-merge commits on the tip that are not on HEAD (HEAD..tip), oldest
    first. Of those, a commit is already present when HEAD's side holds a patch-equivalent
    (`git rev-list --cherry-pick --right-only`, which compares patch-ids) or a commit whose
    `-x` trailer names it (patch-ids differ once a rebase changed the context); it is not picked
    again. A branch or PR entry's own commits are those not reachable from the component's upstream
    default branch (`upstream_tip`): when the source sits on a newer upstream than the workspace,
    the upstream commits in between are excluded and reported, never picked under the entry's name.
    The entry's own `exclude` list drops named commits that would otherwise be picked (a release
    cut, say); each is reported, and an exclude that matches nothing is reported as unused.
    A commit entry is just its one commit."""
    candidates = git_ok(wt, "rev-list", "--reverse", "--topo-order", "--no-merges",
                        f"HEAD..{tip}").split()
    fresh = git_ok(wt, "rev-list", "--reverse", "--topo-order", "--no-merges", "--cherry-pick",
                   "--right-only", f"HEAD...{tip}").split()
    trailers = trailer_sources(wt, tip) if candidates else set()
    plan: dict[str, Any] = {"picks": [], "present": [], "present_by_trailer": [], "excluded_upstream": [],
                            "excluded_by_entry": [], "exclude_unused": []}
    if "commit" in entry:
        if len(git_ok(wt, "rev-list", "--parents", "-n", "1", tip).split()) > 2:
            raise ToolError(f"{entry['id']}: {tip} is a merge commit; register its commits instead")
        if tip in fresh and tip not in trailers:
            plan["picks"] = [tip]
        else:
            plan["present"] = [tip]
            plan["present_by_trailer"] = [tip] if tip in fresh else []
        return plan
    own = set(git_ok(wt, "rev-list", "--no-merges", tip, "--not", upstream_tip).split())
    fresh_set = set(fresh)
    plan["present"] = [c for c in candidates if c not in fresh_set]
    exclude = entry.get("exclude", [])
    for c in fresh:
        if c not in own:
            plan["excluded_upstream"].append(c)
        elif c in trailers:
            plan["present"].append(c)
            plan["present_by_trailer"].append(c)
        elif c in exclude:
            subject = git_ok(wt, "show", "-s", "--format=%s", c).strip()
            plan["excluded_by_entry"].append({"commit": c, "subject": scrub(subject, 100)})
        else:
            plan["picks"].append(c)
    named = {x["commit"] for x in plan["excluded_by_entry"]}
    plan["exclude_unused"] = [c for c in exclude if c not in named]
    return plan


def has_bad_chars(text: str) -> bool:
    return any(unicodedata.category(ch) in BAD_CATEGORIES for ch in text)


def scrub(text: str, limit: int = 300) -> str:
    """Third-party text (git output, file names) as inert data: control, format and separator
    characters (see BAD_CATEGORIES) become '?'."""
    return "".join("?" if unicodedata.category(ch) in BAD_CATEGORIES else ch for ch in text.strip())[:limit]


def abort_pick(wt: Path) -> dict[str, Any]:
    """Abort an interrupted cherry-pick and report, without assuming, whether the tree is clean."""
    result = git(wt, "cherry-pick", "--abort")
    pending = Path(git_ok(wt, "rev-parse", "--path-format=absolute", "--git-path", "CHERRY_PICK_HEAD").strip())
    lock = Path(git_ok(wt, "rev-parse", "--path-format=absolute", "--git-path", "index.lock").strip())
    clean = (not git_ok(wt, "status", "--porcelain", "--untracked-files=normal").strip()
             and not pending.exists() and not lock.exists())
    return {"abort_rc": result.returncode, "tree_clean": clean}


def do_apply(registry: Path, forks: Path, target: str, wt: Path, dry_run: bool,
             include_trial: bool = False, include_held: bool = False) -> tuple[int, dict[str, Any]]:
    if not TARGET_RE.match(target):
        raise RegistryError("target must look like PLATFORM-build-N (e.g. desktop-build-2)")
    matching = apply_order([e for e in load_registry(registry, forks)
                            if e["status"] in ACTIVE and target in e["targets"]])
    entries: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for entry in matching:
        if is_placeholder(entry):
            skipped.append({"id": entry["id"], "why": "placeholder", "hold": entry["hold"]})
        elif entry.get("hold") and not include_held:
            skipped.append({"id": entry["id"], "why": "hold", "hold": entry["hold"]})
        elif entry["trial_required"] and not include_trial:
            skipped.append({"id": entry["id"], "why": "trial_required"})
        else:
            entries.append(entry)
    branch, start = check_workspace(wt)
    report: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "target": target, "workspace": str(wt),
                              "branch": branch, "dry_run": dry_run, "start_head": start,
                              "applied": [], "skipped": skipped, "conflict": None, "head": start}
    tips: list[tuple[dict[str, Any], str]] = []
    upstream_urls = {row["id"]: row["upstream"] for row in _forks_rows(forks)}
    upstream_tips: dict[str, str] = {}
    for entry in entries:  # fetch everything (entries and upstream tips) and check heads before changing anything
        tip = fetch_entry(wt, entry)
        if "expected_head" in entry and tip != entry["expected_head"]:
            report["conflict"] = {"id": entry["id"], "reason": "head-moved", "files": [],
                                  "expected_head": entry["expected_head"], "actual_head": tip}
            return EXIT_STOPPED, report
        if "commit" not in entry and entry["component"] not in upstream_tips:
            upstream_tips[entry["component"]] = fetch_upstream_tip(wt, upstream_urls[entry["component"]])
        tips.append((entry, tip))
    for entry, tip in tips:  # an exclude id outside its source's history is a typo: refuse before any pick (dry run too)
        unknown = [x for x in entry.get("exclude", [])
                   if git(wt, "merge-base", "--is-ancestor", x, tip).returncode != 0]
        if unknown:
            report["conflict"] = {"id": entry["id"], "reason": "exclude-unknown", "files": [], "unknown_excludes": unknown}
            return EXIT_STOPPED, report
    for entry, tip in tips:
        upstream_tip = None if "commit" in entry else upstream_tips[entry["component"]]
        plan = plan_commits(wt, entry, tip, upstream_tip)
        picks = plan["picks"]
        row: dict[str, Any] = {"id": entry["id"], "tip": tip, "commits": picks,
                               "already_present": not picks and not plan["excluded_upstream"],
                               "already_present_commits": plan["present"],
                               "already_present_by_trailer": plan["present_by_trailer"],
                               "excluded_upstream_commits": plan["excluded_upstream"],
                               "excluded_by_entry": plan["excluded_by_entry"],
                               "exclude_unused": plan["exclude_unused"]}
        report["applied"].append(row)
        if dry_run:
            continue
        for sha in picks:
            try:
                result = git(wt, "cherry-pick", "-x", sha, timeout=NETWORK_TIMEOUT)
                reason, message = "conflict", result.stderr
                failed = result.returncode != 0
            except ToolError as error:
                failed, reason, message = True, "cherry-pick-timeout", str(error)
            if failed:
                files = git(wt, "diff", "--name-only", "--diff-filter=U").stdout.split()
                state = abort_pick(wt)
                row["commits"] = picks[:picks.index(sha)]
                report["conflict"] = {"id": entry["id"], "reason": reason, "commit": sha,
                                      "files": sorted(scrub(f, 200) for f in files),
                                      "git_message_untrusted": scrub(message), **state}
                report["head"] = git_ok(wt, "rev-parse", "HEAD").strip()
                return EXIT_STOPPED, report
    report["head"] = git_ok(wt, "rev-parse", "HEAD").strip()
    return EXIT_OK, report


# --------------------------------------------------------------------------- mark

PICK_HEADER = re.compile(r"^\s*\[\[pick\]\]\s*(#.*)?$")
ANY_HEADER = re.compile(r"^\s*\[")


def _entry_block(lines: list[str], pick_id: str) -> tuple[int, int]:
    id_re = re.compile(r'^\s*id\s*=\s*"' + re.escape(pick_id) + r'"\s*(#.*)?$')
    starts = [i for i, line in enumerate(lines) if PICK_HEADER.match(line)]
    for start in starts:
        end = start + 1
        while end < len(lines) and not ANY_HEADER.match(lines[end]):
            end += 1
        if any(id_re.match(line.rstrip("\r\n")) for line in lines[start:end]):
            return start, end
    raise RegistryError(f"no [[pick]] block with id {pick_id!r}")


def edit_status(text: str, pick_id: str, status: str, note: str | None, old_notes: str | None) -> str:
    lines = re.split(r"(?<=\n)", text)  # split on \n only (U+2028 is not a line break in TOML)
    if lines and lines[-1] == "":
        lines.pop()
    start, end = _entry_block(lines, pick_id)
    status_re = re.compile(r'^(\s*status\s*=\s*)"[^"\\\n]*"(.*)$', re.S)
    notes_re = re.compile(r'^(\s*notes\s*=\s*)"(?:[^"\\\n]|\\.)*"(.*)$', re.S)
    status_at = next((i for i in range(start, end) if status_re.match(lines[i])), None)
    if status_at is None:
        raise RegistryError(f"{pick_id}: status must be a single-line basic string to be edited in place")
    lines[status_at] = status_re.sub(lambda m: f'{m.group(1)}"{status}"{m.group(2)}', lines[status_at], count=1)
    if note:
        combined = f"{old_notes} | {note}" if old_notes else note
        value = json.dumps(combined, ensure_ascii=False)
        notes_at = next((i for i in range(start, end) if notes_re.match(lines[i])), None)
        if notes_at is not None:
            lines[notes_at] = notes_re.sub(lambda m: f"{m.group(1)}{value}{m.group(2)}", lines[notes_at], count=1)
        else:
            newline = "\r\n" if lines[status_at].endswith("\r\n") else "\n"
            if not lines[status_at].endswith("\n"):
                lines[status_at] += newline
            lines.insert(status_at + 1, f"notes = {value}{newline}")
    return "".join(lines)


def atomic_write(path: Path, text: str) -> None:
    mode = path.stat().st_mode & 0o7777
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def do_mark(registry: Path, forks: Path, pick_id: str, status: str, note: str | None) -> dict[str, Any]:
    if not MARK_RE.match(status):
        raise RegistryError("status must be carried, landed:N, landed:main, upstreamed or dropped")
    if note is not None and (not note.strip() or has_bad_chars(note)):
        raise RegistryError("note must be one non-empty line without control characters")
    registry = registry.resolve()
    primary = is_primary_checkout(registry.parent)
    if primary is None:
        raise Refused("the registry is not inside a git work tree; edit it in a linked worktree")
    if primary:
        raise Refused("refusing to edit the registry in a primary checkout; use a linked worktree and a PR")
    original = load_registry(registry, forks)
    current = next((e for e in original if e["id"] == pick_id), None)
    if current is None:
        raise RegistryError(f"no pick with id {pick_id!r}")
    text = registry.read_text(encoding="utf-8")
    new_text = edit_status(text, pick_id, status, note, current.get("notes"))
    try:
        updated = validate_entries(tomllib.loads(new_text), component_ids(forks))
    except ValueError as error:  # RegistryError is a ValueError: let it through as is
        raise error if isinstance(error, RegistryError) else RegistryError(
            f"edited registry does not parse ({type(error).__name__}: {error}); nothing written") from error
    expected = [dict(e) for e in original]
    for entry in expected:
        if entry["id"] == pick_id:
            entry["status"] = status
            if note:
                entry["notes"] = f"{entry['notes']} | {note}" if entry.get("notes") else note
    if updated != expected:
        raise RegistryError("edit would change more than the target entry's status/notes; aborted")
    atomic_write(registry, new_text)
    return {"schema_version": SCHEMA_VERSION, "id": pick_id, "previous_status": current["status"],
            "status": status}


# --------------------------------------------------------------------------- check-upstream

def cache_root() -> Path:
    env = os.environ.get("ADE_FORK_PICKS_CACHE")
    return Path(env) if env else Path.home() / ".cache" / "ade-fork-picks"


def cache_clone(component: str, upstream_url: str) -> Path:
    """Bare blobless clone of the component's upstream, fetched to its default branch tip."""
    key = hashlib.sha256(upstream_url.encode()).hexdigest()[:10]
    clone = cache_root() / f"{component}-{key}.git"
    if not clone.is_dir():
        clone.parent.mkdir(parents=True, exist_ok=True)
        result = run(["git", "clone", "--bare", "--filter=blob:none", "--quiet", upstream_url, str(clone)],
                     timeout=NETWORK_TIMEOUT)
        if result.returncode != 0:
            raise ToolError(f"clone of {upstream_url} failed: {result.stderr.strip()[:300]}")
    git_ok(clone, "fetch", "--quiet", "--no-tags", "origin", "+HEAD:refs/ade-upstream/head", timeout=NETWORK_TIMEOUT)
    return clone


def patch_ids(clone: Path, shas: list[str]) -> dict[str, str]:
    """Stable git patch-id per commit: sha -> patch-id."""
    if not shas:
        return {}
    diffs = git_ok(clone, "diff-tree", "--stdin", "-p", "--root", timeout=NETWORK_TIMEOUT,
                   stdin="\n".join(shas) + "\n")
    out = git_ok(clone, "patch-id", "--stable", stdin=diffs, timeout=NETWORK_TIMEOUT)
    result: dict[str, str] = {}
    for line in out.splitlines():
        pid, sha = line.split()[:2]
        result[sha] = pid
    return result


def check_pr(entry: dict[str, Any]) -> dict[str, str] | None:
    url = entry.get("upstream", "")
    if not PR_RE.match(url):
        return None
    result = run(["gh", "pr", "view", url.rstrip("/"), "--json", "state,mergedAt"], timeout=120)
    if result.returncode != 0:
        raise ToolError(f"gh pr view failed: {result.stderr.strip()[:200]}")
    try:
        info = json.loads(result.stdout)
    except ValueError as error:
        raise ToolError("gh pr view returned non-JSON") from error
    if info.get("state") == "MERGED" or info.get("mergedAt"):
        return {"code": "upstream-pr-merged", "detail": f"{url} merged at {info.get('mergedAt')}"}
    return None


def check_patch(entry: dict[str, Any], upstream: str) -> dict[str, str] | None:
    clone = cache_clone(entry["component"], upstream)
    url = source_of(entry)
    sha = entry["commit"]
    if git(clone, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
        git_ok(clone, "fetch", "--quiet", "--no-tags", url, sha, timeout=NETWORK_TIMEOUT)
    head = "refs/ade-upstream/head"
    if git(clone, "merge-base", "--is-ancestor", sha, head).returncode == 0:
        return {"code": "commit-in-upstream", "detail": f"{sha} is reachable from the upstream default branch"}
    if len(git_ok(clone, "rev-list", "--parents", "-n", "1", sha).split()) > 2:
        raise ToolError("pick commit is a merge commit; patch-id comparison unsupported")
    mine = patch_ids(clone, [sha]).get(sha)
    if not mine:
        raise ToolError("pick commit has an empty diff")
    paths = [p for p in git_ok(clone, "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha).split("\n") if p]
    if git(clone, "merge-base", sha, head).returncode != 0:
        raise ToolError("pick commit shares no history with the upstream default branch")
    candidates = git_ok(clone, "rev-list", "--no-merges", "--max-count=5000", f"{sha}..{head}", "--", *paths,
                        timeout=NETWORK_TIMEOUT).split()
    for up_sha, pid in patch_ids(clone, candidates).items():
        if pid == mine:
            return {"code": "equivalent-patch-upstream",
                    "detail": f"upstream commit {up_sha} has the same patch-id as {sha}"}
    return None


def do_check_upstream(registry: Path, forks: Path, component: str | None) -> tuple[int, dict[str, Any]]:
    entries = [e for e in load_registry(registry, forks) if e["status"] in ACTIVE
               and (component is None or e["component"] == component)]
    upstreams = {row["id"]: row["upstream"] for row in _forks_rows(forks)}
    candidates: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for entry in entries:
        reasons: list[dict[str, str]] = []
        try:
            reason = check_pr(entry)
            if reason:
                reasons.append(reason)
        except ToolError as error:
            errors.append({"id": entry["id"], "check": "pr", "error": str(error)})
        if "commit" in entry:
            try:
                reason = check_patch(entry, upstreams[entry["component"]])
                if reason:
                    reasons.append(reason)
            except ToolError as error:
                errors.append({"id": entry["id"], "check": "patch", "error": str(error)})
        if reasons:
            candidates.append({"id": entry["id"], "component": entry["component"], "reasons": reasons})
    report = {"schema_version": SCHEMA_VERSION, "checked": [e["id"] for e in entries],
              "candidates": candidates, "errors": errors}
    code = EXIT_ERROR if errors else (EXIT_CANDIDATES if candidates else EXIT_OK)
    return code, report


# --------------------------------------------------------------------------- CLI

def emit(payload: Any, as_json: bool, text: str) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True) if as_json else text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ade-fork-picks", description=__doc__.split("\n\n")[0])
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH, help="registry file (tests)")
    parser.add_argument("--forks", type=Path, default=FORKS_PATH, help="forks policy file (tests)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="list registry entries (default: queued and carried)")
    p.add_argument("--component")
    p.add_argument("--target")
    p.add_argument("--status", default=None,
                   help="queued, carried, landed, landed:N|main, upstreamed, dropped or all")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("apply", help="cherry-pick queued and carried entries for a target onto a linked worktree")
    p.add_argument("--target", required=True)
    p.add_argument("--workspace", required=True, type=Path)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--include-trial", action="store_true", help="also apply trial_required entries")
    p.add_argument("--include-held", action="store_true", help="also apply entries with a hold reason")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("mark", help="set an entry's status (edit the registry in a linked worktree)")
    p.add_argument("id")
    p.add_argument("--status", required=True)
    p.add_argument("--note")
    p = sub.add_parser("check-upstream", help="report queued and carried entries upstream already carries")
    p.add_argument("--component")
    p.add_argument("--json", action="store_true")
    return parser


def list_line(row: dict[str, Any]) -> str:
    flags = ("  [placeholder (no source yet)]" if is_placeholder(row) else "") \
        + ("  [trial required]" if row["trial_required"] else "") \
        + (f"  [hold: {row['hold']}]" if row.get("hold") else "")
    return f"{row['id']}  {row['component']}  {','.join(row['targets'])}  {row['status']}{flags}  {row['intent']}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "list":
            rows = [public(e) for e in apply_order(load_registry(args.registry, args.forks))
                    if (not args.component or e["component"] == args.component)
                    and (not args.target or args.target in e["targets"])
                    and status_matches(e["status"], args.status)]
            emit({"schema_version": SCHEMA_VERSION, "picks": rows}, args.json,
                 "\n".join(map(list_line, rows)) or "(no matching picks)")
            return EXIT_OK
        if args.cmd == "apply":
            code, report = do_apply(args.registry, args.forks, args.target, args.workspace.resolve(),
                                    args.dry_run, args.include_trial, args.include_held)
            verb = "would apply" if args.dry_run else "applied"
            lines = [f"{verb} {r['id']}: {len(r['commits'])} commit(s)"
                     + (f" (already-present: {len(r['already_present_commits'])})" if r["already_present_commits"] else "")
                     + (f" (EXCLUDED upstream: {len(r['excluded_upstream_commits'])}; the workspace may need a rebase onto"
                        " newer upstream)" if r["excluded_upstream_commits"] else "")
                     + (" (LARGE plan: check this source's base)" if len(r["commits"]) > LARGE_PLAN else "")
                     + "".join(f"; EXCLUDED by entry {x['commit'][:9]} ({x['subject']})" for x in r["excluded_by_entry"])
                     + (f"; exclude not needed (already present or excluded upstream): "
                        f"{', '.join(c[:9] for c in r['exclude_unused'])}" if r["exclude_unused"] else "")
                     for r in report["applied"]]
            lines += [f"skipped {s['id']} ({s['why']}{': ' + s['hold'] if s.get('hold') else ''})"
                      for s in report["skipped"]]
            if report["conflict"]:
                c = report["conflict"]
                lines.append(f"STOPPED {c['reason']} in {c['id']}: "
                             + (("not in the source's history: " + ", ".join(c["unknown_excludes"])
                                 + " (fix the entry's exclude list; nothing was applied)") if c.get("unknown_excludes") else "")
                             + ("" if c.get("unknown_excludes") else
                                ", ".join(c["files"]) or (f"git said (untrusted): {c['git_message_untrusted']}" if c.get("git_message_untrusted") else "") or f"head is {c.get('actual_head')}"))
            lines.append(f"HEAD {report['head']}")
            emit(report, args.json, "\n".join(lines))
            return code
        if args.cmd == "mark":
            result = do_mark(args.registry, args.forks, args.id, args.status, args.note)
            print(f"{result['id']}: {result['previous_status']} -> {result['status']}")
            return EXIT_OK
        code, report = do_check_upstream(args.registry, args.forks, args.component)
        text = "\n".join([f"drop candidate {c['id']}: " + "; ".join(r["detail"] for r in c["reasons"])
                          for c in report["candidates"]]
                         + [f"error {e['id']} ({e['check']}): {e['error']}" for e in report["errors"]]) \
            or "no drop candidates"
        emit(report, args.json, text)
        return code
    except Refused as error:
        print(f"ade-fork-picks: refused: {error}", file=sys.stderr)
        return EXIT_REFUSED
    except (RegistryError, ToolError) as error:
        print(f"ade-fork-picks: error: {error}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
