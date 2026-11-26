"""ade_client_wiring: observe-only check that every current agent TUI is wired.

Two checks per TUI, both report-only (standing order 11: no client config is
ever edited, no fix command is ever run; the fix is printed):

* MCP: each server in ``config/mcp-registry.toml`` x each client in its
  ``expected`` map (``user``, ``user-lazy``, ``on-demand``, ``denied``,
  ``absent``, ``project:<path>``). The client's config FILE is read for key
  names, command/args, enabled flag and URL only (``~/.claude.json`` user/project
  ``mcpServers`` + ``~/.claude/settings.json`` ``deniedMcpServers``;
  ``~/.codex/config.toml`` ``[mcp_servers.<id>]``; ``~/.cursor/mcp.json``
  ``mcpServers``; ``~/.hermes/config.yaml`` ``mcp_servers``). Never prints
  ``env``, ``headers``, ``http_headers`` or raw secret values. A TUI with no
  file-readable MCP config is ``unknown`` with the reason, never a failure.
* Skills: ``bin/skill-everywhere --check --all`` is run (it is read-only) and
  its per-TUI states are mapped to ok / missing / dangling / elsewhere.

The TUI roster is not listed here: it is the ``targets`` table inside
``bin/skill-everywhere`` (docs/skill-everywhere.md), the one place that knows
which TUIs are current. The MCP registry's ``expected`` keys must be a subset
of it.

Statuses: ok | warn | unknown | error. ``error`` = an unreadable registry or
client config, or exactly one of the registry / ``bin/skill-everywhere`` present.
"""
from __future__ import annotations

import json
import math
import os
import re
import shlex
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:  # PyYAML is only needed for Hermes' config.yaml
    import yaml
except ImportError:  # pragma: no cover - exercised by the unknown-reason test
    yaml = None  # type: ignore[assignment]

SKILL_SCRIPT = ("bin", "skill-everywhere")
SKILL_CHECK_TIMEOUT_S = 90
SKILL_ENV_OVERRIDES = ("SKILL_EVERYWHERE_ONLY", "SKILL_EVERYWHERE_NO_COPY", "SKILL_EVERYWHERE_ADE",
                       "SKILL_EVERYWHERE_PRIVATE", "SKILL_EVERYWHERE_SITE", "SKILL_EVERYWHERE_GROKBOT_NOTE")
# Also dropped when the caller pins HOME (fixtures): each one relocates a root the check reads.
SKILL_ENV_HOME_RELATIVE = ("OPS_ROOT", "CODEX_HOME", "HERMES_HOME")
MAX_STDERR_ROWS = 200  # distinct stderr lines kept; the rest are counted, not dropped silently
MAX_DETAIL_LINES = 12

SCHEMA_VERSION = 1
DEFAULT_LAZY_WRAPPER = "~/.local/libexec/ade/mcp-lazy"
DEFAULT_LAZY_IDLE_SECONDS = 600

SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
SAFE_URL = re.compile(r"https?://[A-Za-z0-9.:/_-]+\Z")
SAFE_CMD = re.compile(r"[A-Za-z0-9/_~.-][A-Za-z0-9/_~.-]*\Z")
SAFE_ARG = re.compile(r"[-A-Za-z0-9@~/_][A-Za-z0-9@._=:/~-]*\Z")  # one stdio argv word; no shell metacharacters
SAFE_AUTH_KEY = re.compile(r"[A-Za-z0-9_.:-]{1,64}\Z")
FORBIDDEN_SERVER_KEYS = frozenset({"env", "headers", "http_headers", "env_http_headers", "token", "api_key"})
ALLOWED_SERVER_KEYS = frozenset({
    "id", "transport", "url", "command", "args", "lazy_wrapper", "lazy_idle_seconds",
    "owner", "state", "auth", "capabilities", "expected",
    "doc", "risk", "notes", "on_demand", "instead", "footprint_label", "measured",
})
ALLOWED_AUTH_KEYS = frozenset({"kind", "keys", "store"})
ALLOWED_MEASURED_KEYS = frozenset({"footprint_mb", "measured_at", "usage_30d"})
LAZY_VALUE_FLAGS = frozenset({"--id", "--idle", "--cache-dir", "--start-timeout"})
LAZY_ID_RE = re.compile(r"[a-z0-9-]+\Z")

VALID_TRANSPORTS = frozenset({"stdio", "local-http", "remote-http", "injected"})
VALID_STATES = frozenset({"per-session", "per-repo", "shared-safe", "external-app"})
VALID_AUTH_KINDS = frozenset({"none", "oauth", "bearer", "header", "env", "dialog"})
VALID_AUTH_STORES = frozenset({
    "none", "sudo-secretspec", "client-oauth", "client-literal-pending-2c", "app-env", "paseo",
})
VALID_EXPECTED_EXACT = frozenset({"user", "user-lazy", "on-demand", "denied", "absent"})

CLAUDE_HTTP_TYPES = ("http", "streamable-http")  # alias accepted by Claude Code
CLAUDE_STDIO_TYPES = (None, "stdio")  # an entry without type is read as stdio
FILE_TUIS = frozenset({"claude", "codex", "cursor-agent", "hermes"})

# (kind, id, status, detail)
Row = tuple[str, str, str, str]
Runner = Callable[[list[str], dict[str, str]], "subprocess.CompletedProcess[str]"]

# TUIs whose MCP config is not a file this machine can read, and why.
NO_MCP_FILE = {
    "pi": "Pi is not a separate MCP client here (docs/mcp-servers.md)",
    "gemini": "Gemini / Antigravity MCP config is not checked by doctor here",
    "grokbot": "Grok Bot runs on its own Linux box; its MCP config is not on this machine",
}


# ---------------------------------------------------------------- TUI roster

def tui_roster(root: Path) -> list[str]:
    """TUI ids from the ``targets`` table of bin/skill-everywhere, in its order."""
    text = root.joinpath(*SKILL_SCRIPT).read_text(encoding="utf-8")
    m = re.search(r"^targets='\n(.*?)^'", text, re.S | re.M)
    if not m:
        raise ValueError("skill-everywhere has no targets table")
    ids = [ln.split("|", 1)[0].strip() for ln in m.group(1).splitlines() if "|" in ln]
    if not ids or any(not SAFE_ID.match(i) for i in ids):
        raise ValueError("skill-everywhere targets table is unreadable")
    return ids


# ---------------------------------------------------------------- MCP registry

def default_roster_path(root: Path) -> Path:
    return root / "config" / "mcp-registry.toml"


def _validate_expected_value(sid: str, client: str, state: Any, transport: str) -> None:
    if not isinstance(state, str) or not state:
        raise ValueError(f"server {sid}: expected[{client!r}] must be a non-empty string")
    if state in VALID_EXPECTED_EXACT:
        if state == "user-lazy" and transport != "stdio":
            raise ValueError(f"server {sid}: expected[{client!r}]='user-lazy' requires transport='stdio'")
        if transport == "injected" and state in ("user", "user-lazy"):
            raise ValueError(f"server {sid}: expected[{client!r}]={state!r} is not valid for transport='injected'")
        return
    if state.startswith("project:"):
        if transport == "injected":
            raise ValueError(f"server {sid}: expected[{client!r}]={state!r} is not valid for transport='injected'")
        proj = state[len("project:"):]
        if not proj or any(ord(ch) < 32 for ch in proj):
            raise ValueError(f"server {sid}: expected[{client!r}] has invalid project path {proj!r}")
        return
    raise ValueError(
        f"server {sid}: expected[{client!r}]={state!r} must be one of "
        f"{sorted(VALID_EXPECTED_EXACT)} or 'project:<path>'"
    )


def _validate_auth(sid: str, auth: Any) -> None:
    if not isinstance(auth, dict):
        raise ValueError(f"server {sid}: auth must be a table")
    unknown = set(auth.keys()) - ALLOWED_AUTH_KEYS
    if unknown:
        raise ValueError(f"server {sid}: unknown auth field(s) {sorted(unknown)}")
    kind = auth.get("kind")
    keys = auth.get("keys")
    store = auth.get("store")
    if kind not in VALID_AUTH_KINDS:
        raise ValueError(f"server {sid}: auth.kind {kind!r} must be in {sorted(VALID_AUTH_KINDS)}")
    if not isinstance(keys, list) or any(not isinstance(k, str) or not SAFE_AUTH_KEY.match(k) for k in keys):
        raise ValueError(f"server {sid}: auth.keys must be a list of key names only (no spaces or values)")
    if store not in VALID_AUTH_STORES:
        raise ValueError(f"server {sid}: auth.store {store!r} must be in {sorted(VALID_AUTH_STORES)}")


def validate_registry(data: Any, tuis: list[str] | None = None) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        raise ValueError("registry root must be a TOML table")
    ver = data.get("schema_version")
    if isinstance(ver, bool) or ver != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version {ver!r} (expected {SCHEMA_VERSION})")
    rows = data.get("server")
    if not isinstance(rows, list) or not rows:
        raise ValueError("no [[server]] rows")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("[[server]] row is not a table")
        sid = row.get("id")
        if not isinstance(sid, str) or not SAFE_ID.match(sid) or sid in seen:
            raise ValueError(f"bad or duplicate server id {sid!r}")
        seen.add(sid)
        bad_secret_keys = FORBIDDEN_SERVER_KEYS.intersection(row.keys())
        if bad_secret_keys:
            raise ValueError(f"server {sid}: forbidden secret-bearing field(s) {sorted(bad_secret_keys)}")
        unknown_keys = set(row.keys()) - ALLOWED_SERVER_KEYS
        if unknown_keys:
            raise ValueError(f"server {sid}: unknown field(s) {sorted(unknown_keys)}")
        transport = row.get("transport")
        if transport not in VALID_TRANSPORTS:
            raise ValueError(f"server {sid}: transport {transport!r} must be in {sorted(VALID_TRANSPORTS)}")
        if transport == "stdio":
            if "url" in row:
                raise ValueError(f"server {sid}: stdio server must not set url")
            cmd, args = row.get("command"), row.get("args", [])
            if not isinstance(cmd, str) or not SAFE_CMD.match(cmd) or ".." in cmd.split("/"):
                raise ValueError(f"server {sid}: command must be a safe executable word or path")
            if not isinstance(args, list) or any(not isinstance(a, str) or not SAFE_ARG.match(a) for a in args):
                raise ValueError(f"server {sid}: args must be a list of plain words (no whitespace or shell metachars)")
            if "lazy_wrapper" in row:
                lw = row["lazy_wrapper"]
                if not isinstance(lw, str) or not SAFE_CMD.match(lw) or ".." in lw.split("/"):
                    raise ValueError(f"server {sid}: lazy_wrapper must be a safe path")
            if "lazy_idle_seconds" in row:
                idle = row["lazy_idle_seconds"]
                if isinstance(idle, bool) or not isinstance(idle, int) or idle < 0:
                    raise ValueError(f"server {sid}: lazy_idle_seconds must be a non-negative int")
        elif transport in ("local-http", "remote-http"):
            if "command" in row:
                raise ValueError(f"server {sid}: HTTP server must not set command")
            url = row.get("url")
            if not isinstance(url, str) or not SAFE_URL.match(url):
                raise ValueError(f"server {sid}: url must be plain http(s) (letters, digits, . : / _ -)")
        else:  # injected
            if "url" in row or "command" in row:
                raise ValueError(f"server {sid}: injected server must not set url or command")
        owner = row.get("owner")
        if not isinstance(owner, str) or not owner.strip():
            raise ValueError(f"server {sid}: owner must be a non-empty string")
        state = row.get("state")
        if state not in VALID_STATES:
            raise ValueError(f"server {sid}: state {state!r} must be in {sorted(VALID_STATES)}")
        _validate_auth(sid, row.get("auth"))
        caps = row.get("capabilities")
        if not isinstance(caps, list) or not caps or any(
                not isinstance(c, str) or not c.strip() or any(ord(ch) < 32 for ch in c) for c in caps):
            raise ValueError(f"server {sid}: capabilities must be a non-empty list of printable strings")
        expected = row.get("expected")
        if not isinstance(expected, dict):
            raise ValueError(f"server {sid}: expected must be a table of client -> state")
        for client, exp_state in expected.items():
            if not isinstance(client, str) or not SAFE_ID.match(client):
                raise ValueError(f"server {sid}: bad client id {client!r} in expected")
            if tuis is not None and client not in tuis:
                raise ValueError(f"server {sid}: client {client!r} not in the skill-everywhere roster {tuis}")
            _validate_expected_value(sid, client, exp_state, transport)
        for opt_str in ("doc", "risk", "notes", "on_demand", "instead", "footprint_label"):
            if opt_str in row and not isinstance(row[opt_str], str):
                raise ValueError(f"server {sid}: {opt_str} must be a string")
        if "measured" in row:
            measured = row["measured"]
            if not isinstance(measured, dict):
                raise ValueError(f"server {sid}: measured must be a table")
            unknown_m = set(measured.keys()) - ALLOWED_MEASURED_KEYS
            if unknown_m:
                raise ValueError(f"server {sid}: unknown measured field(s) {sorted(unknown_m)}")
    return rows


def load_registry(path: Path, tuis: list[str] | None = None) -> list[dict[str, Any]]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return validate_registry(data, tuis=tuis)


# Backward-compatible alias used by tests and callers.
load_roster = load_registry


def _expand_home(raw: str, home: Path) -> str:
    if raw == "~":
        return str(home)
    if raw.startswith("~/"):
        return str(home / raw[2:])
    return raw


def safe_url(url: Any, want: str) -> str:
    """Scheme and host:port only; the path is shown only when it equals the
    expected one (some endpoints carry an API key in the path). Never userinfo,
    query or fragment; control characters are dropped."""
    if not isinstance(url, str):
        return "<non-string>"
    if not re.match(r"https?://", url):
        return "<non-http url>"
    try:
        p = urlsplit(url)
        host = p.hostname or ""
        if p.port:
            host += f":{p.port}"
        path = p.path if p.path.rstrip("/") == urlsplit(want).path.rstrip("/") else "/<other path>"
    except ValueError:
        return "<unparseable>"
    shown = f"{p.scheme}://{host}{path}"
    return "".join(c if c.isprintable() else "?" for c in shown)[:120]


def fix_add(tui: str, sid: str, url: str) -> str:
    q = shlex.quote
    if tui == "claude":
        return f"claude mcp add --scope user --transport http {q(sid)} {q(url)}"
    if tui == "codex":
        return f"codex mcp add {q(sid)} --url {q(url)}"
    if tui == "cursor-agent":
        return f'add "{sid}": {{"url": "{url}"}} under mcpServers in ~/.cursor/mcp.json'
    return f"add {sid}: url: {url} under mcp_servers in ~/.hermes/config.yaml"


def fix_remove(tui: str, sid: str) -> str:
    q = shlex.quote
    if tui == "claude":
        return f"claude mcp remove --scope user {q(sid)}"
    if tui == "codex":
        return f"codex mcp remove {q(sid)}"
    if tui == "cursor-agent":
        return f'remove "{sid}" from mcpServers in ~/.cursor/mcp.json'
    return f"remove {sid} from mcp_servers in ~/.hermes/config.yaml"


def fix_swap(tui: str, sid: str, url: str) -> str:
    if tui in ("claude", "codex"):
        return f"{fix_remove(tui, sid)} && {fix_add(tui, sid, url)}"
    return f"correct the {sid} entry: " + fix_add(tui, sid, url)


def _fix_stdio_add(tui: str, sid: str, cmd: str, args: list[str]) -> str:
    q = shlex.quote
    want = " ".join([q(cmd), *(q(a) for a in args)])
    if tui == "claude":
        return f"claude mcp add --scope user {q(sid)} -- {want}"
    if tui == "codex":
        return f"codex mcp add {q(sid)} -- {want}"
    if tui == "cursor-agent":
        return f'set "{sid}": {{"command": "{cmd}", "args": {json.dumps(args)}}} under mcpServers in ~/.cursor/mcp.json'
    return f"set {sid} command={cmd} under mcp_servers in ~/.hermes/config.yaml"


def _fix_stdio_swap(tui: str, sid: str, cmd: str, args: list[str]) -> str:
    add = _fix_stdio_add(tui, sid, cmd, args)
    if tui in ("claude", "codex"):
        return f"{fix_remove(tui, sid)} && {add}"
    return f"correct the {sid} entry: {add}"


# Loaders return (path, servers-dict-or-None-when-file-absent).
def _load_claude_data(home: Path) -> tuple[Path, dict[str, Any] | None, dict[str, dict[str, Any]]]:
    """Read ~/.claude.json once, returning (path, user_mcpServers_or_None, projects_mcp)."""
    path = home / ".claude.json"
    if not path.is_file():
        return path, None, {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return path, {}, {}
    raw_servers = data.get("mcpServers")
    servers = raw_servers if isinstance(raw_servers, dict) else {}
    projects_mcp: dict[str, dict[str, Any]] = {}
    projs = data.get("projects")
    if isinstance(projs, dict):
        for proj_path, pdata in projs.items():
            if isinstance(proj_path, str) and isinstance(pdata, dict):
                ms = pdata.get("mcpServers")
                if isinstance(ms, dict):
                    projects_mcp[proj_path] = ms
    return path, servers, projects_mcp


def _load_claude(home: Path) -> tuple[Path, dict[str, Any] | None]:
    path, servers, _ = _load_claude_data(home)
    return path, servers


def _load_claude_denied(home: Path) -> tuple[set[str], str | None]:
    """(denied_set, settings_error) from ~/.claude/settings.json only."""
    denied: set[str] = set()
    settings_path = home / ".claude" / "settings.json"
    if not settings_path.is_file():
        return denied, None
    try:
        sdata = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError, RecursionError) as e:
        return denied, f"claude settings unreadable: {type(e).__name__}"
    raw_denied = sdata.get("deniedMcpServers") if isinstance(sdata, dict) else None
    if isinstance(raw_denied, list):
        for item in raw_denied:
            if isinstance(item, str):
                denied.add(item)
            elif isinstance(item, dict) and isinstance(item.get("serverName"), str):
                denied.add(item["serverName"])
    return denied, None


def _load_codex(home: Path) -> tuple[Path, dict[str, Any] | None]:
    path = home / ".codex" / "config.toml"
    if not path.is_file():
        return path, None
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    servers = data.get("mcp_servers")
    return path, servers if isinstance(servers, dict) else {}


def _load_cursor(home: Path) -> tuple[Path, dict[str, Any] | None]:
    path = home / ".cursor" / "mcp.json"
    if not path.is_file():
        return path, None
    data = json.loads(path.read_text(encoding="utf-8"))
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    return path, servers if isinstance(servers, dict) else {}


def _load_hermes(home: Path) -> tuple[Path, dict[str, Any] | None]:
    path = home / ".hermes" / "config.yaml"
    if not path.is_file():
        return path, None
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    servers = data.get("mcp_servers") if isinstance(data, dict) else None
    return path, servers if isinstance(servers, dict) else {}


_LOADERS: dict[str, Callable[[Path], tuple[Path, dict[str, Any] | None]]] = {
    "claude": _load_claude,
    "codex": _load_codex,
    "cursor-agent": _load_cursor,
    "hermes": _load_hermes,
}


def _judge_stdio(tui: str, sid: str, cmd: str, args: list[str], entry: Any, *, home: Path) -> tuple[str, str]:
    """Stdio entry check; states: ok | missing | wrong-type | disabled | wrong-command."""
    q = shlex.quote
    expanded_cmd = _expand_home(cmd, home)
    want = " ".join([q(cmd), *(q(a) for a in args)])
    add = _fix_stdio_add(tui, sid, cmd, args)
    swap = _fix_stdio_swap(tui, sid, cmd, args)
    if entry is None:
        return "missing", f"not registered; run: {add}"
    if not isinstance(entry, dict):
        return "wrong-type", f"entry is not a table/object; run: {swap}"
    if tui == "claude" and entry.get("type") not in CLAUDE_STDIO_TYPES:
        t = entry.get("type")
        shown = repr(t) if isinstance(t, str) and len(t) <= 32 else "<odd>"
        return "wrong-type", f"entry type is {shown}, want 'stdio'; run: {swap}"
    if tui in ("codex", "cursor-agent") and "url" in entry:
        return "wrong-type", f"entry has url, want a stdio command; run: {swap}"
    if entry.get("enabled") is False:
        return "disabled", f"present but enabled = false; set enabled = true for {sid}"
    got_cmd = entry.get("command")
    raw_args = entry.get("args")
    got_args = [] if raw_args is None else raw_args
    cmd_ok = isinstance(got_cmd, str) and (got_cmd == expanded_cmd or got_cmd == cmd)
    if not cmd_ok or not isinstance(got_args, list) or got_args != args:
        # Command and args only: never print env or differing args (they can hold secrets).
        note = "; the entry has env, re-add it" if "env" in entry and entry["env"] else ""
        return "wrong-command", f"command or args differ from the registry{note}; run: {swap}"
    return "ok", f"registered: {want}"


def _parse_lazy_head(before_sep: list[Any], sid: str, want_idle: int) -> str | None:
    """Validate mcp-lazy options before `--` against bin/mcp-lazy's grammar.

    Returns None when valid, else a secret-free diagnostic reason.
    Supported flags (both `--flag val` and `--flag=val`): --id, --idle, --cache-dir, --start-timeout.
    """
    if not all(isinstance(tok, str) for tok in before_sep):
        return "mcp-lazy args contain non-string token"
    seen: dict[str, str] = {}
    i = 0
    n = len(before_sep)
    while i < n:
        tok = before_sep[i]
        if "=" in tok and tok.startswith("--"):
            flag, val = tok.split("=", 1)
            if flag not in LAZY_VALUE_FLAGS:
                return "mcp-lazy args contain unknown option"
            if flag in seen:
                return f"mcp-lazy args repeat {flag}"
            seen[flag] = val
            i += 1
            continue
        if tok in LAZY_VALUE_FLAGS:
            if tok in seen:
                return f"mcp-lazy args repeat {tok}"
            if i + 1 >= n:
                return f"mcp-lazy option {tok} is missing its value"
            val = before_sep[i + 1]
            # Match argparse: a separated value starting with '-' (unless a negative number
            # for numeric flags, which will still fail range validation below) is rejected as a missing value.
            if val.startswith("--") or (val.startswith("-") and tok not in ("--idle", "--start-timeout")):
                return f"mcp-lazy option {tok} is missing its value"
            seen[tok] = val
            i += 2
            continue
        return "mcp-lazy args contain unknown option or stray argument"

    got_id = seen.get("--id")
    if got_id != sid or not LAZY_ID_RE.match(got_id):
        return f"mcp-lazy args missing '--id {sid}'"

    if "--cache-dir" in seen and not seen["--cache-dir"]:
        return "mcp-lazy --cache-dir must be non-empty"

    if "--start-timeout" in seen:
        try:
            st = float(seen["--start-timeout"])
        except ValueError:
            return "mcp-lazy --start-timeout must be a finite number > 0"
        if not math.isfinite(st) or st <= 0:
            return "mcp-lazy --start-timeout must be a finite number > 0"

    if "--idle" in seen:
        try:
            effective_idle = float(seen["--idle"])
        except ValueError:
            return "mcp-lazy --idle must be a finite number >= 0"
        if not math.isfinite(effective_idle) or effective_idle < 0:
            return "mcp-lazy --idle must be a finite number >= 0"
    else:
        effective_idle = float(DEFAULT_LAZY_IDLE_SECONDS)

    if effective_idle != float(want_idle):
        return f"mcp-lazy effective --idle differs from registry lazy_idle_seconds ({want_idle})"
    return None


def _judge_stdio_lazy(
    tui: str,
    sid: str,
    cmd: str,
    args: list[str],
    entry: Any,
    *,
    home: Path,
    wrapper: str = DEFAULT_LAZY_WRAPPER,
    idle_seconds: int = DEFAULT_LAZY_IDLE_SECONDS,
) -> tuple[str, str]:
    """Validate a `user-lazy` stdio entry wrapped in `mcp-lazy`."""
    expanded_wrapper = _expand_home(wrapper, home)
    expanded_cmd = _expand_home(cmd, home)
    example_child = expanded_cmd if os.path.isabs(expanded_cmd) else f"/opt/homebrew/bin/{cmd}"
    lazy_args = ["--id", sid, "--idle", str(idle_seconds), "--", example_child, *args]
    add = _fix_stdio_add(tui, sid, wrapper, lazy_args)
    swap = _fix_stdio_swap(tui, sid, wrapper, lazy_args)
    if entry is None:
        return "missing", f"not registered (expected lazy wrapper); run: {add}"
    if not isinstance(entry, dict):
        return "wrong-type", f"entry is not a table/object; run: {swap}"
    if tui == "claude" and entry.get("type") not in CLAUDE_STDIO_TYPES:
        t = entry.get("type")
        shown = repr(t) if isinstance(t, str) and len(t) <= 32 else "<odd>"
        return "wrong-type", f"entry type is {shown}, want 'stdio'; run: {swap}"
    if tui in ("codex", "cursor-agent") and "url" in entry:
        return "wrong-type", f"entry has url, want a lazy stdio wrapper; run: {swap}"
    if entry.get("enabled") is False:
        return "disabled", f"present but enabled = false; set enabled = true for {sid}"
    got_cmd = entry.get("command")
    got_args = entry.get("args")
    note = "; the entry has env, re-add it" if "env" in entry and entry["env"] else ""
    if got_cmd not in (expanded_wrapper, wrapper):
        if isinstance(got_cmd, str) and (got_cmd == expanded_cmd or got_cmd == cmd or Path(got_cmd).name == Path(cmd).name):
            return "unwrapped", f"registered directly without mcp-lazy wrapper{note}; run: {swap}"
        return "wrong-command", f"command is not {wrapper}{note}; run: {swap}"
    if not isinstance(got_args, list) or "--" not in got_args:
        return "wrong-command", f"mcp-lazy args missing '--' separator{note}; run: {swap}"
    sep = got_args.index("--")
    before, after = got_args[:sep], got_args[sep + 1:]
    head_err = _parse_lazy_head(before, sid, idle_seconds)
    if head_err is not None:
        return "wrong-command", f"{head_err}{note}; run: {swap}"
    if not after or not isinstance(after[0], str):
        return "wrong-command", f"mcp-lazy args missing wrapped child command{note}; run: {swap}"
    child_cmd, child_args = after[0], after[1:]
    if not os.path.isabs(child_cmd) or ".." in child_cmd.split("/"):
        return "wrong-command", f"mcp-lazy wrapped child command must be an absolute path without '..'{note}; run: {swap}"
    child_matches = (
        child_cmd == expanded_cmd if os.path.isabs(expanded_cmd) else Path(child_cmd).name == cmd
    )
    if not child_matches or child_args != args:
        return "wrong-command", f"mcp-lazy wrapped command or args differ from the registry{note}; run: {swap}"
    return "ok", f"registered (lazy): {wrapper} --id {sid} -- {cmd}"


def _judge(tui: str, sid: str, want: str, entry: Any) -> tuple[str, str]:
    """(state, detail): state is ok | missing | wrong-url | wrong-type | disabled."""
    add = fix_add(tui, sid, want)
    swap = fix_swap(tui, sid, want)
    if entry is None:
        return "missing", f"not registered; run: {add}"
    if not isinstance(entry, dict):
        return "wrong-type", f"entry is not a table/object; run: {swap}"
    if tui == "claude" and entry.get("type") not in CLAUDE_HTTP_TYPES:
        # An entry without type is read as stdio, so its url is ignored.
        t = entry.get("type")
        shown = repr(t) if isinstance(t, str) and len(t) <= 32 else "<missing or odd>"
        return "wrong-type", f"entry type is {shown}, want 'http'; run: {swap}"
    if entry.get("enabled") is False:
        return "disabled", f"present but enabled = false; set enabled = true for {sid}"
    got = entry.get("url")
    if not isinstance(got, str) or got.rstrip("/") != want.rstrip("/"):
        return "wrong-url", f"url is {safe_url(got, want)}, want {want}; run: {swap}"
    return "ok", f"registered at {want}"


def _judge_absent(tui: str, sid: str, entry: Any) -> tuple[str, str]:
    if entry is None:
        return "ok", "absent from user scope (expected)"
    return "drift", f"expected absent, but present in user scope; run: {fix_remove(tui, sid)}"


def _judge_on_demand(tui: str, sid: str, entry: Any) -> tuple[str, str]:
    if entry is None:
        return "ok", "on-demand (absent from user scope)"
    # Only Codex and Hermes honor enabled = false on an entry; Claude Code and Cursor ignore it.
    if tui in ("codex", "hermes") and isinstance(entry, dict) and entry.get("enabled") is False:
        return "ok", "on-demand (disabled in user scope)"
    return "drift", f"expected on-demand, but active in user scope; run: {fix_remove(tui, sid)}"


def _judge_denied(
    tui: str,
    sid: str,
    entry: Any,
    *,
    claude_denied: set[str],
    claude_settings_error: str | None,
) -> tuple[str, str]:
    if tui == "claude":
        if claude_settings_error is not None:
            return "error", claude_settings_error
        if sid in claude_denied:
            if entry is not None:
                return "ok", "denied in ~/.claude/settings.json (overrides ~/.claude.json entry)"
            return "ok", "denied in ~/.claude/settings.json"
        if entry is not None:
            return (
                "drift",
                f'expected denied, but active in user scope and not in deniedMcpServers; '
                f'add {{"serverName": "{sid}"}} to ~/.claude/settings.json and run: {fix_remove(tui, sid)}',
            )
        return (
            "drift",
            f'not listed in deniedMcpServers in ~/.claude/settings.json; '
            f'add {{"serverName": "{sid}"}} to deniedMcpServers',
        )
    if entry is None or (tui in ("codex", "hermes") and isinstance(entry, dict) and entry.get("enabled") is False):
        return "ok", "denied (absent/disabled in user scope)"
    return "drift", f"expected denied, but active in user scope; run: {fix_remove(tui, sid)}"


def observe_mcp(roster: list[dict[str, Any]], tuis: list[str], *, home: Path) -> dict[str, list[Row]]:
    """Per TUI, one row per expected server (``mcp`` kind; status ok|warn|unknown|error).
    Reads at most five config files; writes nothing."""
    out: dict[str, list[Row]] = {t: [] for t in tuis}
    for tui in tuis:
        wanted = [r for r in roster if tui in r.get("expected", {})]
        if not wanted:
            continue
        loader = _LOADERS.get(tui)
        reason = NO_MCP_FILE.get(tui, "no file-readable MCP config known for this TUI")
        if tui == "hermes" and yaml is None:
            loader, reason = None, "PyYAML is not importable here, so ~/.hermes/config.yaml is not read"
        if loader is None:
            out[tui].append(("mcp", f"{tui}/*", "unknown", reason))
            continue
        claude_projects: dict[str, dict[str, Any]] = {}
        claude_denied: set[str] = set()
        claude_settings_error: str | None = None
        try:
            if tui == "claude":
                path, servers, claude_projects = _load_claude_data(home)
            else:
                path, servers = loader(home)
        except (OSError, ValueError, UnicodeDecodeError, RecursionError) as e:
            out[tui].append(("mcp", f"{tui}/*", "error", f"{tui} MCP config unreadable: {type(e).__name__}"))
            continue
        except Exception as e:  # noqa: BLE001 - yaml.YAMLError is not a ValueError
            if yaml is not None and isinstance(e, yaml.YAMLError):
                out[tui].append(("mcp", f"{tui}/*", "error", f"{tui} MCP config unreadable: YAMLError"))
                continue
            raise
        if tui == "claude":
            claude_denied, claude_settings_error = _load_claude_denied(home)

        for r in wanted:
            sid = r["id"]
            exp = r["expected"][tui]
            entry = servers.get(sid) if servers is not None else None

            if exp == "absent":
                state, detail = _judge_absent(tui, sid, entry)
                out[tui].append(("mcp", f"{tui}/{sid}", "ok" if state == "ok" else "warn",
                                 detail if state == "ok" else f"{state}: {detail}"))
                continue

            if exp == "on-demand":
                state, detail = _judge_on_demand(tui, sid, entry)
                out[tui].append(("mcp", f"{tui}/{sid}", "ok" if state == "ok" else "warn",
                                 detail if state == "ok" else f"{state}: {detail}"))
                continue

            if exp == "denied":
                state, detail = _judge_denied(
                    tui, sid, entry,
                    claude_denied=claude_denied,
                    claude_settings_error=claude_settings_error,
                )
                status = "ok" if state == "ok" else ("error" if state == "error" else "warn")
                out[tui].append(("mcp", f"{tui}/{sid}", status,
                                 detail if status in ("ok", "error") else f"{state}: {detail}"))
                continue

            if exp.startswith("project:"):
                proj_raw = exp[len("project:"):]
                if tui != "claude":
                    out[tui].append(("mcp", f"{tui}/{sid}", "unknown",
                                     f"project-scoped MCP ({proj_raw}) is not checked for {tui}"))
                    continue
                proj_path = _expand_home(proj_raw, home)
                proj_entry = claude_projects.get(proj_path, {}).get(sid)
                if r["transport"] == "stdio":
                    state, detail = _judge_stdio(tui, sid, r["command"], r.get("args", []), proj_entry, home=home)
                else:
                    state, detail = _judge(tui, sid, r["url"], proj_entry)
                if servers is None:
                    detail = f"{path} absent (TUI not set up?); {detail}"
                out[tui].append(("mcp", f"{tui}/{sid}", "ok" if state == "ok" else "warn",
                                 f"project {proj_raw}: {detail}" if state == "ok" else f"{state} (project {proj_raw}): {detail}"))
                continue

            if exp == "user-lazy":
                state, detail = _judge_stdio_lazy(
                    tui,
                    sid,
                    r["command"],
                    r.get("args", []),
                    entry,
                    home=home,
                    wrapper=r.get("lazy_wrapper", DEFAULT_LAZY_WRAPPER),
                    idle_seconds=r.get("lazy_idle_seconds", DEFAULT_LAZY_IDLE_SECONDS),
                )
                if servers is None:
                    detail = f"{path} absent (TUI not set up?); {detail}"
                out[tui].append(("mcp", f"{tui}/{sid}", "ok" if state == "ok" else "warn",
                                 detail if state == "ok" else f"{state}: {detail}"))
                continue

            # exp == "user"
            if r["transport"] == "stdio":
                state, detail = _judge_stdio(tui, sid, r["command"], r.get("args", []), entry, home=home)
                if servers is None:
                    detail = f"{path} absent (TUI not set up?); {detail}"
                out[tui].append(("mcp", f"{tui}/{sid}", "ok" if state == "ok" else "warn",
                                 detail if state == "ok" else f"{state}: {detail}"))
                continue
            want = r["url"]
            if servers is None:
                out[tui].append(("mcp", f"{tui}/{sid}", "warn",
                                 f"missing: {path} absent (TUI not set up?); {fix_add(tui, sid, want)}"))
                continue
            state, detail = _judge(tui, sid, want, entry)
            out[tui].append(("mcp", f"{tui}/{sid}", "ok" if state == "ok" else "warn",
                             detail if state == "ok" else f"{state}: {detail}"))
    return out


# -------------------------------------------------------------------- skills

def _default_runner(argv: list[str], env: dict[str, str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(  # noqa: S603 - argv list; the script is read-only under --check
        argv, capture_output=True, text=True, check=False, env=env,
        timeout=SKILL_CHECK_TIMEOUT_S, errors="replace",
    )


def classify_skill_state(state: str) -> str:
    """ok | unknown | missing | dangling | elsewhere | other. Copy-target rows carry a
    trailing ``(<dest>)`` (``copied (/x)``), stripped first."""
    state = re.sub(r" \(.*\)$", "", state)
    if state in ("linked", "copied", "present") or state.startswith("via "):
        return "ok"
    if state.startswith("not installed"):
        return "unknown"
    if state == "missing":
        return "missing"
    if state.startswith("dangling"):
        return "dangling"
    if state.startswith(("other link", "chained", "real", "stale copy")):
        return "elsewhere"
    return "other"


def parse_skill_check(text: str) -> tuple[dict[str, dict[str, str]], bool]:
    """(tui -> skill -> state, complete). Complete = the last non-empty line is the
    ``== end`` sentinel and every skill header has at least one row."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    complete = bool(lines) and lines[-1] == "== end"
    table: dict[str, dict[str, str]] = {}
    skill = None
    rowed: set[str] = set()
    headers: list[str] = []
    for line in lines[:-1] if complete else lines:
        if line.startswith("== "):
            skill = line[3:].strip()
            headers.append(skill)
        elif line.startswith("  ") and skill is not None:
            parts = line.split(None, 1)
            if len(parts) == 2:
                table.setdefault(parts[0], {})[skill] = parts[1].strip()
                rowed.add(skill)
    if any(h not in rowed for h in headers):
        complete = False
    return table, complete


def observe_skills(
    root: Path,
    tuis: list[str],
    *,
    home: Path | None = None,
    runner: Runner | None = None,
) -> tuple[dict[str, list[Row]], list[Row]]:
    """Per-TUI ``skill`` rows (ok summary or per-skill warns) plus global rows.
    Runs ``skill-everywhere --check --all`` and nothing else."""
    script = root.joinpath(*SKILL_SCRIPT)
    fix = f"{script} --all"
    # An inherited ONLY/NO_COPY/root override would narrow or redirect the check and still print a
    # complete-looking report (bin/ade-update helper_env, round 15): drop them all.
    drop = SKILL_ENV_OVERRIDES + (SKILL_ENV_HOME_RELATIVE if home is not None else ())
    env = {k: v for k, v in os.environ.items() if k not in drop}
    if home is not None:
        env["HOME"] = str(home)
    run = runner or _default_runner
    glob: list[Row] = []
    out: dict[str, list[Row]] = {t: [] for t in tuis}
    try:
        cp = run([str(script), "--check", "--all"], env)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        glob.append(("skill", "skill-everywhere", "warn", f"check could not run ({type(e).__name__})"))
        return out, glob
    table, complete = parse_skill_check(cp.stdout or "")
    if not complete:
        glob.append(("skill", "skill-everywhere", "warn",
                     f"check ended early (rc {cp.returncode}, no '== end'); no skill result trusted"))
        return out, glob
    attached: dict[str, list[Row]] = {t: [] for t in tuis}
    counts: dict[str, int] = {}
    dropped = 0
    for line in (cp.stderr or "").splitlines():
        if line.strip():
            text = "".join(c if c.isprintable() else "?" for c in line)[:200]
            counts[text] = counts.get(text, 0) + 1
    for text, times in counts.items():
        shown = text + (f" (x{times})" if times > 1 else "")
        # The script's own TUI-specific warnings start `warning: <tui-id> ` (the mandatory space rejects the
        # per-skill form `warning: <skill>: ...`, so a skill named like a TUI stays global). Every line is
        # attributed; only the GLOBAL rows are capped, so a late Hermes warning is never lost.
        m = re.match(r"warning: ([A-Za-z0-9][A-Za-z0-9._-]*) ", text)
        owner = m.group(1) if m and m.group(1) in attached else None
        if owner:
            attached[owner].append(("skill", f"{owner}/warning", "warn", shown))
        elif sum(1 for g in glob if g[1] == "skill-everywhere") < MAX_STDERR_ROWS:
            glob.append(("skill", "skill-everywhere", "warn", shown))
        else:
            dropped += 1
    if dropped:
        glob.append(("skill", "skill-everywhere", "warn", f"(+{dropped} more distinct stderr lines)"))
    if cp.returncode not in (0, 1):
        glob.append(("skill", "skill-everywhere", "warn", f"check exited rc {cp.returncode}"))
    # cursor-agent-style TUIs read ~/.claude/skills: judge claude first, independent of table order.
    claude_states = table.get("claude") or {}
    claude_gaps = any(classify_skill_state(st) not in ("ok", "unknown") for st in claude_states.values())
    claude_unchecked = bool(claude_states) and all(
        classify_skill_state(st) == "unknown" for st in claude_states.values())
    for tui in tuis:
        out[tui].extend(attached[tui])
        states = table.get(tui)
        if not states:
            out[tui].append(("skill", f"{tui}/*", "unknown", "skill-everywhere reported nothing for this TUI"))
            continue
        if all(st.startswith("via ") and "claude" in st for st in states.values()):
            if claude_gaps:
                out[tui].append(("skill", f"{tui}/via-claude", "warn",
                                 "reads ~/.claude/skills, which has gaps (see claude/* rows)"))
                continue
            if claude_unchecked or not claude_states:
                out[tui].append(("skill", f"{tui}/*", "unknown",
                                 "reads ~/.claude/skills, which was not checked (claude not installed or not reported)"))
                continue
        groups: dict[str, list[str]] = {}
        for skill, state in sorted(states.items()):
            groups.setdefault(classify_skill_state(state), []).append(skill)
        n = len(states)
        if len(groups.get("unknown", [])) == n:
            reason = next(iter(states.values()))
            out[tui].append(("skill", f"{tui}/*", "unknown", reason[:160]))
            continue
        bad = {k: v for k, v in groups.items() if k not in ("ok", "unknown")}
        if not bad:
            out[tui].append(("skill", f"{tui}/*", "ok", f"{len(groups.get('ok', []))}/{n} skills linked"))
            continue
        for kind in ("missing", "dangling", "elsewhere", "other"):
            names = bad.get(kind)
            if not names:
                continue
            shown = ", ".join(names[:MAX_DETAIL_LINES]) + (f" (+{len(names) - MAX_DETAIL_LINES} more)" if len(names) > MAX_DETAIL_LINES else "")
            label = {"elsewhere": "points elsewhere or not our link"}.get(kind, kind)
            out[tui].append(("skill", f"{tui}/{kind}", "warn", f"{len(names)} {label}: {shown}; run: {fix}"))
    return out, glob


# ------------------------------------------------------------------- combine

def observe(
    root: Path,
    *,
    home: Path | None = None,
    roster_path: Path | None = None,
    runner: Runner | None = None,
) -> list[Row]:
    """All rows: per TUI one ``tui`` summary then its ``mcp``/``skill`` detail rows
    (non-ok only, plus ok MCP rows), then global rows. ``[]`` when both the registry and
    skill-everywhere are absent (fixture catalogs); exactly one of them is an error row."""
    path = roster_path if roster_path is not None else default_roster_path(root)
    has_script = root.joinpath(*SKILL_SCRIPT).is_file()
    if not has_script and not path.is_file():
        return []
    if has_script and not path.is_file():
        return [("tui", "roster", "error", f"MCP roster missing ({path}); skill-everywhere is present")]
    if not has_script:
        return [("tui", "roster", "error", f"{root.joinpath(*SKILL_SCRIPT)} missing; the TUI roster cannot be read")]
    home_dir = home if home is not None else Path.home()
    try:
        tuis = tui_roster(root)
        roster = load_registry(path, tuis)
    except (OSError, ValueError, UnicodeDecodeError) as e:
        return [("tui", "roster", "error", f"TUI/MCP roster unreadable ({path}): {e}")]
    mcp = observe_mcp(roster, tuis, home=home_dir)
    skills, glob = observe_skills(root, tuis, home=home, runner=runner)
    rows: list[Row] = []
    for tui in tuis:
        det = mcp[tui] + skills[tui]
        statuses = {r[2] for r in det}
        if "error" in statuses:
            status = "error"
        elif "warn" in statuses:
            status = "warn"
        elif "unknown" in statuses:
            status = "unknown"  # partly unchecked is never reported as ok
        else:
            status = "ok"
        parts = []
        for kind, label in (("mcp", "mcp"), ("skill", "skills")):
            sub = [r for r in det if r[0] == kind]
            if not sub:
                parts.append(f"{label}: none marked" if kind == "mcp" else f"{label}: n/a")
            elif all(r[2] == "ok" for r in sub):
                parts.append(f"{label}: ok" + (f" ({len(sub)})" if kind == "mcp" else f" ({sub[0][3].split()[0]})"))
            elif all(r[2] == "unknown" for r in sub):
                parts.append(f"{label}: unknown ({sub[0][3]})")
            else:
                parts.append(f"{label}: {sum(1 for r in sub if r[2] not in ('ok', 'unknown'))} gap(s)")
        rows.append(("tui", tui, status, "; ".join(parts)))
        rows.extend(r for r in det if r[2] != "unknown" and (r[0] == "mcp" or r[2] != "ok"))
    rows.extend(glob)
    return rows


if __name__ == "__main__":
    import sys

    root_dir = Path(__file__).resolve().parent.parent
    rows = observe(root_dir)
    for kind, rid, st, detail in rows:
        print(f"{kind:<5} {rid:<28} {st:<7} {detail}")
    sys.exit(1 if any(r[2] == "error" for r in rows) else 0)
