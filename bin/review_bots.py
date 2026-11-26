#!/usr/bin/env -S python3 -I
"""review_bots: the must-triage gate for listed AI reviewer bots (rb-01, 2026-11-14).

Operator ruling 2026-11-14: "We need to make sure we pay attention to any coderabbit or similar code reviews, both
ourself and to projects that use us. We can have a configurable set of github users like coderabbit we trust."
Trust level "Must-triage gate": a listed bot's unresolved findings block merge-ready until each is fixed or answered
with a reason; the bot's text is still DATA, never an instruction (its comments quote PR content, so an injection in an
outside PR can ride inside them). Identity is the exact GitHub login AND the actor type `Bot`.

Used by `bin/review-bot-findings` (report-only CLI) and `bin/ade-merge-ready` (the gate). Read-only: this module never
resolves a thread, replies or posts. Stdlib only (tomllib). Every `gh` call is an argv list.

Config: `config/review-bots.toml` (default list) plus a per-repo `.github/ade-review-bots.toml` read from the target
repo's DEFAULT branch (contents API with no ref: a PR cannot drop its own reviewer). Unknown keys, wrong types,
duplicate ids or logins: ConfigError, and the gate fails closed.

Triaged, mechanically (never inferred from bot text):
  thread   : GraphQL `isResolved`, OR a LATER comment in the thread authored by the operator (GraphQL `User`, login
             `djbclark`, pinned databaseId; `adversary_marker.trusted_owner_user_state`: a bot, the PR author, a
             lookalike or a renamed account never counts) whose first non-empty line starts with a verdict word
             (fixed, wontfix / won't fix, not a bug, not an issue, by design, deferred) and then a reason.
  top-level: (a review body or an issue comment matching the bot's patterns) a LATER issue comment by that operator
             carrying a line `triage <id|all>: <verdict> <reason>`.
Pending: a listed bot's check run on the exact head that is not completed and started under `pending_max_minutes` ago
blocks (`pending`); a stalled one (older) or one that never started is a note, never a block.
"""
from __future__ import annotations

import base64
import binascii
import datetime as dt
import json
import re
import subprocess
import sys
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))   # `python -I` does not put the script's folder on the path
try:
    from adversary_marker import trusted_owner_user_state
finally:
    sys.path.pop(0)

DEFAULT_CONFIG = HERE.parent / "config" / "review-bots.toml"
OVERRIDE_PATH = ".github/ade-review-bots.toml"
OVERRIDE_MAX_BYTES = 64 * 1024
CONFIG_MAX_BYTES = 256 * 1024
SCHEMA = 1
TITLE_MAX = 200
BODY_SCAN_MAX = 50_000        # regexes run on at most this many characters of an untrusted body
GH_TIMEOUT = 120
PENDING_MAX_RANGE = (1, 240)
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
REPO_RE = re.compile(r"^(?!\.{1,2}/)[\w.-]+/(?!\.{1,2}$)[\w.-]+$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")

VERDICT = (
    r"(?:fixed|won['’]?t[ -]?fix|wontfix|not an? (?:bug|issue)|by design|deferred)"
)
# the first non-empty line of an owner reply in a thread: a verdict word, then a reason of at least three characters
THREAD_TRIAGE_RE = re.compile(rf"^\s*{VERDICT}\b[\s:.,;()\-]*([^\s?!:.,;()\-].{{2,}})$", re.IGNORECASE)
# a line of an owner issue comment: `triage 123456: fixed in abc1234`, `triage all: wontfix <reason>`
TOP_TRIAGE_RE = re.compile(
    rf"^\s*triage\s+(#?\d+|all)\s*:\s*{VERDICT}\b[\s:.,;()\-]*([^\s?!:.,;()\-].{{2,}})$", re.IGNORECASE | re.MULTILINE
)

_FORBIDDEN_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
GhRunner = Callable[..., str]


class ConfigError(Exception):
    """A review-bot config or override file is unusable (fail closed)."""


class GhError(Exception):
    """A gh/API failure or an unusable answer (fail closed)."""


# ---------------------------------------------------------------- config

@dataclass(frozen=True)
class Bot:
    id: str
    name: str
    rest_login: str
    graphql_login: str
    thread_markers: tuple[str, ...]
    review_body_patterns: tuple[re.Pattern[str], ...]
    issue_comment_patterns: tuple[re.Pattern[str], ...]
    check_names: tuple[str, ...]
    check_apps: tuple[str, ...]
    status_contexts: tuple[str, ...]
    source: str
    check_runs: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Config:
    bots: tuple[Bot, ...]
    pending_max_minutes: int


BOT_REQUIRED = frozenset({"id", "name", "rest_login", "graphql_login"})
BOT_OPTIONAL = frozenset({
    "thread_markers", "review_body_patterns", "issue_comment_patterns", "check_names", "check_apps", "check_runs",
    "status_contexts", "source",
})
CHECK_RUN_KEYS = frozenset({"name", "app"})


def _table(value: Any, allowed: frozenset[str], required: frozenset[str], where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{where}: expected a table, got {type(value).__name__}")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {', '.join(map(repr, unknown))}")
    missing = sorted(required - set(value))
    if missing:
        raise ConfigError(f"{where}: missing key(s) {', '.join(map(repr, missing))}")
    return value


def _str(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 600 or _CTRL_RE.search(value):
        raise ConfigError(f"{where}: expected a non-empty printable string (max 600 chars)")
    return value


def _strs(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 50:
        raise ConfigError(f"{where}: expected a list of at most 50 strings")
    return tuple(_str(v, f"{where}[{i}]") for i, v in enumerate(value))


def _check_runs(value: Any, where: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list) or len(value) > 50:
        raise ConfigError(f"{where}: expected a list of at most 50 tables")
    out: list[tuple[str, str]] = []
    for i, item in enumerate(value):
        t = _table(item, CHECK_RUN_KEYS, CHECK_RUN_KEYS, f"{where}[{i}]")
        out.append((_str(t["name"], f"{where}[{i}].name"), _str(t["app"], f"{where}[{i}].app")))
    return tuple(out)


_QUANTIFIED_GROUP = re.compile(r"\)\s*[*+?{]")


def _patterns(value: Any, where: str, strict: bool = False) -> tuple[re.Pattern[str], ...]:
    """Compile regexes. `strict` (a per-repo override, text we do not control) refuses a quantified group,
    the shape of catastrophic backtracking, because the pattern runs on up to 50k characters of bot text."""
    out = []
    for i, s in enumerate(_strs(value, where)):
        if len(s) > 300:
            raise ConfigError(f"{where}[{i}]: pattern longer than 300 characters")
        if strict and len(re.findall(r"\.[*+]", s)) > 1:
            raise ConfigError(f"{where}[{i}]: more than one `.*`/`.+` is refused in an override pattern (backtracking)")
        if strict and _QUANTIFIED_GROUP.search(s):
            raise ConfigError(f"{where}[{i}]: a quantified group is refused in an override pattern (backtracking)")
        try:
            out.append(re.compile(s))
        except re.error as e:
            raise ConfigError(f"{where}[{i}]: bad regex: {e}") from e
    return tuple(out)


def _parse_bot(raw: Any, where: str, strict: bool = False) -> Bot:
    t = _table(raw, BOT_REQUIRED | BOT_OPTIONAL, BOT_REQUIRED, where)
    bid = _str(t["id"], f"{where}.id")
    if not ID_RE.fullmatch(bid):
        raise ConfigError(f"{where}.id: {bid!r} is not a lowercase slug")
    rest = _str(t["rest_login"], f"{where}.rest_login")
    gql = _str(t["graphql_login"], f"{where}.graphql_login")
    if rest != f"{gql}[bot]" or "[" in gql or "]" in gql:
        raise ConfigError(f"{where}: rest_login must be graphql_login + '[bot]' (got {rest!r} / {gql!r})")
    return Bot(
        id=bid,
        name=_str(t["name"], f"{where}.name"),
        rest_login=rest,
        graphql_login=gql,
        thread_markers=_strs(t.get("thread_markers", []), f"{where}.thread_markers"),
        review_body_patterns=_patterns(t.get("review_body_patterns", []), f"{where}.review_body_patterns", strict),
        issue_comment_patterns=_patterns(t.get("issue_comment_patterns", []), f"{where}.issue_comment_patterns", strict),
        check_names=_strs(t.get("check_names", []), f"{where}.check_names"),
        check_apps=_strs(t.get("check_apps", []), f"{where}.check_apps"),
        status_contexts=_strs(t.get("status_contexts", []), f"{where}.status_contexts"),
        source=_str(t["source"], f"{where}.source") if "source" in t else "",
        check_runs=_check_runs(t.get("check_runs", []), f"{where}.check_runs"),
    )


def _load_toml(text: str, where: str, max_bytes: int) -> dict[str, Any]:
    if len(text.encode("utf-8", "replace")) > max_bytes:
        raise ConfigError(f"{where}: larger than {max_bytes} bytes")
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{where}: not valid TOML: {e}") from e
    meta = _table(doc.get("meta"), frozenset({"schema"}), frozenset({"schema"}), f"{where} [meta]")
    if meta["schema"] != SCHEMA or isinstance(meta["schema"], bool):
        raise ConfigError(f"{where}: [meta] schema must be {SCHEMA}")
    return doc


def _unique(bots: list[Bot] | tuple[Bot, ...], where: str) -> None:
    seen_ids: set[str] = set()
    seen_logins: set[str] = set()
    for b in bots:
        if b.id in seen_ids:
            raise ConfigError(f"{where}: duplicate bot id {b.id!r}")
        if b.graphql_login in seen_logins:
            raise ConfigError(f"{where}: duplicate bot login {b.graphql_login!r}")
        seen_ids.add(b.id)
        seen_logins.add(b.graphql_login)


def parse_config(text: str, where: str = "review-bots.toml") -> Config:
    doc = _load_toml(text, where, CONFIG_MAX_BYTES)
    _table(doc, frozenset({"meta", "defaults", "bot"}), frozenset({"meta", "bot"}), where)
    defaults = _table(
        doc.get("defaults", {}), frozenset({"pending_max_minutes"}), frozenset(), f"{where} [defaults]"
    )
    minutes = defaults.get("pending_max_minutes", 15)
    lo, hi = PENDING_MAX_RANGE
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not lo <= minutes <= hi:
        raise ConfigError(f"{where}: pending_max_minutes must be an integer {lo}..{hi}")
    raw_bots = doc["bot"]
    if not isinstance(raw_bots, list):
        raise ConfigError(f"{where}: [[bot]] must be an array of tables")
    bots = tuple(_parse_bot(b, f"{where} bot[{i}]") for i, b in enumerate(raw_bots))
    _unique(bots, where)
    return Config(bots=bots, pending_max_minutes=minutes)


def apply_override(cfg: Config, text: str, where: str = OVERRIDE_PATH) -> Config:
    """Apply a per-repo override: `[bots] drop = [ids]` removes default bots, `[[add]]` appends full entries."""
    doc = _load_toml(text, where, OVERRIDE_MAX_BYTES)
    _table(doc, frozenset({"meta", "bots", "add"}), frozenset({"meta"}), where)
    bots_tbl = _table(doc.get("bots", {}), frozenset({"drop"}), frozenset(), f"{where} [bots]")
    drop = _strs(bots_tbl.get("drop", []), f"{where} [bots].drop")
    have = {b.id for b in cfg.bots}
    unknown = sorted(set(drop) - have)
    if unknown:
        raise ConfigError(f"{where}: drop names no listed bot: {', '.join(map(repr, unknown))}")
    raw_add = doc.get("add", [])
    if not isinstance(raw_add, list):
        raise ConfigError(f"{where}: [[add]] must be an array of tables")
    added = [_parse_bot(b, f"{where} add[{i}]", True) for i, b in enumerate(raw_add)]
    kept = [b for b in cfg.bots if b.id not in set(drop)]
    merged = tuple(kept + added)
    _unique(merged, where)
    return Config(bots=merged, pending_max_minutes=cfg.pending_max_minutes)


def load_default_config(path: Path | str | None = None) -> Config:
    p = Path(path) if path else DEFAULT_CONFIG
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as e:
        raise ConfigError(f"{p}: cannot read: {type(e).__name__}") from e
    return parse_config(text, str(p))


def fetch_override_text(gh: GhRunner, repo: str) -> str | None:
    """The repo's override file on its default branch, or None when it has none (HTTP 404)."""
    try:
        out = gh("api", f"repos/{repo}/contents/{OVERRIDE_PATH}")
    except GhError as e:
        if "HTTP 404" in str(e):
            return None
        raise
    try:
        doc = json.loads(out)
    except ValueError as e:
        raise ConfigError(f"{repo} {OVERRIDE_PATH}: unusable contents answer") from e
    if not isinstance(doc, dict) or doc.get("type") != "file" or doc.get("encoding") != "base64":
        raise ConfigError(f"{repo} {OVERRIDE_PATH}: not a plain base64 file")
    size = doc.get("size")
    if not isinstance(size, int) or size > OVERRIDE_MAX_BYTES:
        raise ConfigError(f"{repo} {OVERRIDE_PATH}: larger than {OVERRIDE_MAX_BYTES} bytes")
    try:
        return base64.b64decode(doc.get("content") or "", validate=False).decode("utf-8")
    except (binascii.Error, UnicodeError) as e:
        raise ConfigError(f"{repo} {OVERRIDE_PATH}: undecodable content") from e


def effective_config(
    gh: GhRunner, repo: str, config_path: Path | str | None = None, *, use_override: bool = True
) -> Config:
    cfg = load_default_config(config_path)
    if not use_override:
        return cfg
    text = fetch_override_text(gh, repo)
    return cfg if text is None else apply_override(cfg, text, f"{repo} {OVERRIDE_PATH}")


# ---------------------------------------------------------------- identity

def actor_bot(actor: Any, bots: tuple[Bot, ...] | list[Bot]) -> Bot | None:
    """GraphQL actor ({__typename, login}) -> the listed bot it is, exact login AND type Bot, else None."""
    if not isinstance(actor, dict) or actor.get("__typename") != "Bot":
        return None
    login = actor.get("login")
    if not isinstance(login, str):
        return None
    return next((b for b in bots if login == b.graphql_login), None)


def rest_user_bot(user: Any, bots: tuple[Bot, ...] | list[Bot]) -> Bot | None:
    """REST user ({type, login}) -> the listed bot it is, exact login AND type Bot, else None."""
    if not isinstance(user, dict) or user.get("type") != "Bot":
        return None
    login = user.get("login")
    if not isinstance(login, str):
        return None
    return next((b for b in bots if login == b.rest_login), None)


def is_owner_actor(actor: Any) -> bool:
    """A GraphQL `User` that is the operator: trusted login AND the pinned numeric id (a bot, an App or a renamed
    account named `djbclark` never counts)."""
    if not isinstance(actor, dict) or actor.get("__typename") != "User":
        return False
    return trusted_owner_user_state(actor.get("login"), actor.get("databaseId")) == "owner"


# ---------------------------------------------------------------- text helpers (bot text is data)

def clean(text: str) -> str:
    """Drop every control and format character (ANSI escapes, bidi marks, zero-width): Unicode categories Cc and Cf."""
    return "".join(ch for ch in text if unicodedata.category(ch) not in ("Cc", "Cf"))


def title_of(body: str) -> str:
    """First non-empty line, control characters stripped, truncated; never the full bot text."""
    for line in (body or "").splitlines():
        s = clean(line).strip()
        if s:
            return s[:TITLE_MAX]
    return ""


def owner_triage_author(c: dict[str, Any]) -> bool:
    """The comment is the operator's AND was never edited: a writer or an App can edit another user's comment, and the
    last editor alone does not show who edited before (a later owner touch-up would launder it), so an edited comment is
    never a triage; the operator posts a new one."""
    return is_owner_actor(c.get("author")) and not c.get("lastEditedAt")


def _triage_line(body: str) -> bool:
    for line in (body or "").splitlines():
        if line.strip():
            return bool(THREAD_TRIAGE_RE.match(line[:2000]))
    return False


def _top_triage_refs(body: str) -> set[str]:
    refs: set[str] = set()
    for m in TOP_TRIAGE_RE.finditer((body or "")[:BODY_SCAN_MAX]):
        refs.add(m.group(1).lstrip("#").lower())
    return refs


def _ts(value: Any, where: str) -> dt.datetime:
    if not isinstance(value, str):
        raise GhError(f"{where}: missing timestamp")
    try:
        d = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as e:
        raise GhError(f"{where}: bad timestamp") from e
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def _edited(node: dict[str, Any], where: str) -> dt.datetime:
    base = _ts(node.get("createdAt"), where)
    if node.get("lastEditedAt"):
        return max(base, _ts(node["lastEditedAt"], where))
    return base


# ---------------------------------------------------------------- gh (read-only)

def assert_read_only_gh_argv(args: tuple[str, ...] | list[str]) -> None:
    """Refuse argv that could mutate GitHub (defence in depth for this report-only module): only `gh api`, only GET
    (`-f`/`-F` make gh POST, so they are allowed for `graphql` queries only), no `--input`, no `@file` values."""
    if not args or args[0] != "api":
        raise GhError("refusing a gh command that is not `gh api`")
    graphql = len(args) > 1 and args[1] == "graphql"
    for i, a in enumerate(args):
        if not isinstance(a, str):
            raise GhError("refusing a non-string gh argument")
        low = a.lower()
        if low in ("-x", "--method") and i + 1 < len(args) and str(args[i + 1]).upper() != "GET":
            raise GhError(f"refusing non-GET HTTP method in gh argv: {args[i + 1]}")
        if (low.startswith("-x") and low != "-x" and low[2:].upper() != "GET") or (
            low.startswith("--method=") and low[9:].upper() != "GET"
        ):
            raise GhError(f"refusing non-GET HTTP method in gh argv: {a}")
        if low == "--input" or low.startswith("--input="):
            raise GhError("refusing --input in gh argv")
        if not graphql and (
            low in ("-f", "--field", "--raw-field") or low.startswith(("--field=", "--raw-field="))
            or (a.startswith(("-f", "-F")) and len(a) > 2 and not a.startswith("--"))
        ):
            raise GhError("refusing a request body field on a non-graphql gh api call (it would POST)")
        if a.startswith("query=") and re.search(r"(?i)\bmutation\b", a):
            raise GhError("refusing GraphQL mutation in gh argv")
        if "=@" in a and (i > 0 and args[i - 1] in ("-f", "-F", "--field", "--raw-field")):
            raise GhError("refusing an @file request value in gh argv")


def make_gh(gh_bin: str = "gh") -> GhRunner:
    def run(*args: str) -> str:
        assert_read_only_gh_argv(args)
        try:
            p = subprocess.run(
                [gh_bin, *args], check=False, capture_output=True, text=True, errors="replace",
                timeout=GH_TIMEOUT, stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise GhError(f"gh {args[1] if len(args) > 1 else ''}: {type(e).__name__}") from e
        if p.returncode != 0:
            err = (p.stderr or p.stdout).strip().replace("\n", " ")[:300]
            raise GhError(f"gh api {args[1] if len(args) > 1 else ''}: rc={p.returncode} {err}")
        return p.stdout
    return run


def parse_pages(text: str) -> list[Any]:
    """`gh api --paginate` prints one JSON document per page, concatenated."""
    dec = json.JSONDecoder()
    docs: list[Any] = []
    i, n = 0, len(text)
    while True:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            return docs
        try:
            doc, i = dec.raw_decode(text, i)
        except ValueError as e:
            raise GhError(f"unparsable gh output at byte {i}: {e}") from e
        docs.append(doc)


ACTOR = "author{__typename login ... on User{databaseId}}"
EDITOR = ""   # an edited owner comment is never a triage, so who edited it is not read
THREAD_FIELDS = (
    f"isResolved isOutdated resolvedBy{{__typename login ... on User{{databaseId}}}} "
    "comments(first:100){pageInfo{hasNextPage} nodes{databaseId createdAt lastEditedAt "
    f"body path line url originalCommit{{oid}} {EDITOR} {ACTOR}}}}}"
)
REVIEW_FIELDS = f"databaseId state body createdAt lastEditedAt url commit{{oid}} {ACTOR}"
COMMENT_FIELDS = f"databaseId createdAt lastEditedAt body url {EDITOR} {ACTOR}"
PR_QUERY = (
    "query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){"
    "pullRequest(number:$number){number title state merged headRefOid baseRefName url}}}"
)


def _connection_query(field: str, node_fields: str) -> str:
    return (
        "query($owner:String!,$name:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$name){"
        f"pullRequest(number:$number){{{field}(first:100,after:$cursor){{pageInfo{{hasNextPage endCursor}} "
        f"nodes{{{node_fields}}}}}}}}}}}"
    )


def _graphql(gh: GhRunner, repo: str, pr: int, query: str, cursor: str | None = None) -> dict[str, Any]:
    owner, name = repo.split("/", 1)
    args = ["api", "graphql", "-f", f"owner={owner}", "-f", f"name={name}", "-F", f"number={pr}",
            "-f", f"query={query}"]
    if cursor is not None:
        args += ["-f", f"cursor={cursor}"]
    try:
        doc = json.loads(gh(*args))
    except ValueError as e:
        raise GhError(f"graphql PR#{pr}: unusable answer: {e}") from e
    if not isinstance(doc, dict) or doc.get("errors"):
        raise GhError(f"graphql PR#{pr}: errors: {str((doc or {}).get('errors'))[:200]}")
    try:
        pr_node = doc["data"]["repository"]["pullRequest"]
    except (KeyError, TypeError) as e:
        raise GhError(f"graphql PR#{pr}: unusable answer: {e}") from e
    if not isinstance(pr_node, dict):
        raise GhError(f"graphql PR#{pr}: no such pull request")
    return pr_node


def fetch_pr(gh: GhRunner, repo: str, pr: int) -> dict[str, Any]:
    node = _graphql(gh, repo, pr, PR_QUERY)
    head = node.get("headRefOid")
    if not isinstance(head, str) or not SHA40.fullmatch(head):
        raise GhError(f"PR#{pr}: no 40-hex head")
    return {
        "number": pr, "title": (node.get("title") or "")[:TITLE_MAX], "state": node.get("state"),
        "merged": bool(node.get("merged")), "head": head, "url": node.get("url") or f"https://github.com/{repo}/pull/{pr}",
    }


def fetch_connection(gh: GhRunner, repo: str, pr: int, field: str, node_fields: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    seen: set[str] = set()
    query = _connection_query(field, node_fields)
    while True:
        conn = _graphql(gh, repo, pr, query, cursor).get(field)
        if not isinstance(conn, dict) or not isinstance(conn.get("nodes"), list):
            raise GhError(f"graphql PR#{pr} {field}: unusable answer")
        out.extend(n for n in conn["nodes"] if isinstance(n, dict))
        info = conn.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            return out
        cursor = info.get("endCursor")
        if not cursor or cursor in seen:
            raise GhError(f"graphql PR#{pr} {field}: hasNextPage without a new endCursor")
        seen.add(cursor)


def fetch_check_runs(gh: GhRunner, repo: str, head: str) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for doc in parse_pages(gh("api", "--paginate", f"repos/{repo}/commits/{head}/check-runs?per_page=100")):
        part = doc.get("check_runs") if isinstance(doc, dict) else None
        if not isinstance(part, list):
            raise GhError(f"check-runs {head[:12]}: unexpected page shape")
        runs.extend(r for r in part if isinstance(r, dict))
    return runs


def fetch_statuses(gh: GhRunner, repo: str, head: str) -> list[dict[str, Any]]:
    """The commit statuses (not check runs) on the exact head: `GET commits/<head>/status`, read-only."""
    out: list[dict[str, Any]] = []
    for doc in parse_pages(gh("api", "--paginate", f"repos/{repo}/commits/{head}/status?per_page=100")):
        part = doc.get("statuses") if isinstance(doc, dict) else None
        if not isinstance(part, list):
            raise GhError(f"commit status {head[:12]}: unexpected page shape")
        out.extend(r for r in part if isinstance(r, dict))
    return out


# ---------------------------------------------------------------- findings

def _thread_findings(threads: list[dict[str, Any]], bots: tuple[Bot, ...], repo: str, pr: int) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for t in threads:
        conn = t.get("comments") or {}
        if (conn.get("pageInfo") or {}).get("hasNextPage"):
            raise GhError(f"PR#{pr}: a review thread has more than 100 comments (cannot read it whole; fail closed)")
        cs = [c for c in (conn.get("nodes") or []) if isinstance(c, dict)]
        if not cs:
            continue
        hit: tuple[Bot, int] | None = None
        for b in bots:
            if b.thread_markers:
                idx = [
                    i for i, c in enumerate(cs)
                    if actor_bot(c.get("author"), [b]) and any(m in (c.get("body") or "") for m in b.thread_markers)
                ]
                if idx:
                    hit = (b, idx[-1])
                    break
            elif actor_bot(cs[0].get("author"), [b]):
                hit = (b, 0)
                break
        if hit is None:
            continue
        bot, ai = hit
        anchor = cs[ai]
        # `isResolved` counts only when the operator resolved it: a PR author, a writer or the bot itself (which
        # auto-resolves from model output that can carry injected PR text) can click Resolve too.
        resolved = bool(t.get("isResolved")) and is_owner_actor(t.get("resolvedBy"))
        floor = _edited(anchor, f"PR#{pr} thread")
        reply = next(
            (
                c for c in cs[ai + 1:]
                if owner_triage_author(c) and _triage_line(c.get("body") or "")
                and _ts(c.get("createdAt"), f"PR#{pr} reply") > floor
            ),
            None,
        )
        status = "resolved" if resolved else ("triaged" if reply is not None else "untriaged")
        cid = anchor.get("databaseId")
        found.append({
            "bot": bot.id, "kind": "thread", "id": cid, "status": status,
            "path": clean(str(anchor.get("path") or "")) or None, "line": anchor.get("line"),
            "commit": (anchor.get("originalCommit") or {}).get("oid"),
            "outdated": bool(t.get("isOutdated")),
            "title": title_of(anchor.get("body") or ""),
            "url": anchor.get("url") or f"https://github.com/{repo}/pull/{pr}#discussion_r{cid}",
        })
    return found


def _top_findings(
    kind: str, nodes: list[dict[str, Any]], bots: tuple[Bot, ...], issue_comments: list[dict[str, Any]],
    repo: str, pr: int,
) -> list[dict[str, Any]]:
    """Top-level findings. Reviews: EVERY non-pending review of a bot that matches a pattern is its own finding (a later
    `Actionable comments posted: 0` review does not erase an earlier body-only, outside-the-diff finding); each is
    triaged by its own id or `triage all`. Issue comments: only the bot's LATEST one counts (a status comment is edited
    or re-posted in place)."""
    found: list[dict[str, Any]] = []
    for b in bots:
        pats = b.review_body_patterns if kind == "review" else b.issue_comment_patterns
        if not pats:
            continue
        mine = [
            n for n in nodes
            if actor_bot(n.get("author"), [b]) and (kind != "review" or n.get("state") != "PENDING")
        ]
        if not mine:
            continue
        picked = mine if kind == "review" else [max(mine, key=lambda n: _edited(n, f"PR#{pr} {kind}"))]
        for item in picked:
            body = (item.get("body") or "")[:BODY_SCAN_MAX]
            if not any(p.search(body) for p in pats):
                continue
            at = _edited(item, f"PR#{pr} {kind}")
            cid = item.get("databaseId")
            triaged = False
            for c in issue_comments:
                if not owner_triage_author(c) or _ts(c.get("createdAt"), f"PR#{pr} comment") <= at:
                    continue
                refs = _top_triage_refs(c.get("body") or "")
                if "all" in refs or str(cid) in refs:
                    triaged = True
                    break
            found.append({
                "bot": b.id, "kind": kind, "id": cid, "status": "triaged" if triaged else "untriaged",
                "path": None, "line": None, "commit": (item.get("commit") or {}).get("oid"), "outdated": False,
                "title": title_of(item.get("body") or ""),
                "url": item.get("url") or f"https://github.com/{repo}/pull/{pr}",
            })
    return found


_RANK = {"completed": 0, "not_started": 1, "stalled": 2, "pending": 3}


def _running_state(started: Any, label: str, max_minutes: int, now: dt.datetime) -> str:
    try:
        age = now - _ts(started, label)
    except GhError:
        return "pending"       # a running check we cannot date: block rather than guess
    return "pending" if age < dt.timedelta(minutes=max_minutes) else "stalled"


def bot_check_states(
    runs: list[dict[str, Any]], bots: tuple[Bot, ...], max_minutes: int, now: dt.datetime,
    statuses: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
) -> dict[str, str]:
    """Per bot: not_started | pending | stalled | completed, from check runs and commit statuses on the exact head."""
    states: dict[str, str] = {}
    for b in bots:
        mine = [
            r for r in runs
            if r.get("name") in b.check_names
            or (r.get("app") or {}).get("slug") in b.check_apps
            or (r.get("name"), (r.get("app") or {}).get("slug")) in b.check_runs
        ]
        mine_st = [s for s in statuses if b.status_contexts and s.get("context") in b.status_contexts]
        if not mine and not mine_st:
            states[b.id] = "not_started"
            continue
        parts: list[str] = []
        for r in mine:
            if r.get("status") == "completed":
                parts.append("completed")
            else:
                parts.append(_running_state(
                    r.get("started_at") or r.get("created_at"), f"check run {r.get('name')}", max_minutes, now))
        for st in mine_st:
            if st.get("state") != "pending":
                parts.append("completed")
            else:
                parts.append(_running_state(
                    st.get("updated_at") or st.get("created_at"), f"status {st.get('context')}", max_minutes, now))
        states[b.id] = max(parts, key=lambda x: _RANK[x])
    return states


def evaluate(
    gh: GhRunner,
    repo: str,
    pr: int,
    *,
    config: Config | None = None,
    config_path: Path | str | None = None,
    use_override: bool = True,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """The gate verdict for one PR: state is `untriaged` | `pending` | `clear`. Raises ConfigError / GhError (fail closed)."""
    if not REPO_RE.fullmatch(repo):
        raise GhError(f"bad repo {repo!r}")
    meta = fetch_pr(gh, repo, pr)       # first: a repo we cannot read must fail here, not read as "no override" (404)
    cfg = config or effective_config(gh, repo, config_path, use_override=use_override)
    bots = cfg.bots
    findings: list[dict[str, Any]] = []
    if bots:
        threads = fetch_connection(gh, repo, pr, "reviewThreads", THREAD_FIELDS)
        reviews = fetch_connection(gh, repo, pr, "reviews", REVIEW_FIELDS)
        comments = fetch_connection(gh, repo, pr, "comments", COMMENT_FIELDS)
        findings += _thread_findings(threads, bots, repo, pr)
        findings += _top_findings("review", reviews, bots, comments, repo, pr)
        findings += _top_findings("issue_comment", comments, bots, comments, repo, pr)
    checks: dict[str, str] = {}
    if bots and meta["state"] == "OPEN":
        runs = fetch_check_runs(gh, repo, meta["head"])
        stat = fetch_statuses(gh, repo, meta["head"]) if any(b.status_contexts for b in bots) else []
        checks = bot_check_states(runs, bots, cfg.pending_max_minutes, now or dt.datetime.now(dt.timezone.utc), stat)
    untriaged = [f for f in findings if f["status"] == "untriaged"]
    pending = sorted(b for b, s in checks.items() if s == "pending")
    state = "untriaged" if untriaged else ("pending" if pending else "clear")
    notes = [f"{b}: check {s}" for b, s in sorted(checks.items()) if s in ("stalled",)]
    return {
        "tool": "review-bot-findings", "repo": repo, "pr": pr, "title": meta["title"], "state": state,
        "pr_state": meta["state"], "merged": meta["merged"], "head": meta["head"], "url": meta["url"],
        "bots": [b.id for b in bots], "checks": checks, "pending": pending, "notes": notes,
        "findings": findings,
        "summary": {
            "untriaged": len(untriaged),
            "triaged": sum(1 for f in findings if f["status"] == "triaged"),
            "resolved": sum(1 for f in findings if f["status"] == "resolved"),
        },
    }


def gate_summary(verdict: dict[str, Any]) -> dict[str, Any]:
    """The compact form ade-merge-ready puts in a row (titles only, never bodies)."""
    return {
        "state": verdict["state"], "head": verdict["head"], "pending": verdict["pending"], "notes": verdict["notes"],
        "untriaged": [
            {k: f[k] for k in ("bot", "kind", "id", "title", "url")} for f in verdict["findings"]
            if f["status"] == "untriaged"
        ],
    }
