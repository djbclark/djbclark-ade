"""ade_mcp_clients: observe-only check that agent clients register the shared MCP servers.

Roster: ``config/mcp-clients.toml`` (server id, expected URL, clients). For each
(server, client) the client's config FILE is read (``~/.claude.json`` user-scope
``mcpServers``; ``~/.codex/config.toml`` ``[mcp_servers.<id>]``) and compared on
key names and the URL only. Env, headers and every other value are never read
into output; the URL is printed without userinfo or query. A finding carries the
exact fix command for the operator to run; this module never runs it and never
writes any client config (standing order 11).

Statuses: ok | missing | wrong-url | wrong-type | disabled | error.
"""
from __future__ import annotations

import json
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

CLIENTS = ("claude-code", "codex")
# Claude Code accepts "streamable-http" as an alias of "http".
CLAUDE_HTTP_TYPES = ("http", "streamable-http")

Finding = tuple[str, str, str]  # (id, status, detail)


def default_roster_path(root: Path) -> Path:
    return root / "config" / "mcp-clients.toml"


def load_roster(path: Path) -> list[dict[str, Any]]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    rows = data.get("server")
    if not isinstance(rows, list) or not rows:
        raise ValueError("no [[server]] rows")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("[[server]] row is not a table")
        sid, url, clients = row.get("id"), row.get("url"), row.get("clients")
        if not isinstance(sid, str) or not sid or sid in seen:
            raise ValueError(f"bad or duplicate server id {sid!r}")
        seen.add(sid)
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise ValueError(f"server {sid}: url must be http(s)")
        if (not isinstance(clients, list) or not clients
                or any(c not in CLIENTS for c in clients)):
            raise ValueError(f"server {sid}: clients must be a subset of {list(CLIENTS)}")
    return rows


def safe_url(url: Any) -> str:
    """Scheme, host and path only: never userinfo, query or fragment."""
    if not isinstance(url, str):
        return "<non-string>"
    try:
        p = urlsplit(url)
        host = p.hostname or ""
        if p.port:
            host += f":{p.port}"
    except ValueError:
        return "<unparseable>"
    return f"{p.scheme}://{host}{p.path}"


def fix_add(client: str, sid: str, url: str) -> str:
    if client == "claude-code":
        return f"claude mcp add --scope user --transport http {sid} {url}"
    return f"codex mcp add {sid} --url {url}"


def fix_remove(client: str, sid: str) -> str:
    if client == "claude-code":
        return f"claude mcp remove --scope user {sid}"
    return f"codex mcp remove {sid}"


def _load_claude(home: Path) -> tuple[Path, dict[str, Any] | None]:
    path = home / ".claude.json"
    if not path.is_file():
        return path, None
    data = json.loads(path.read_text(encoding="utf-8"))
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    return path, servers if isinstance(servers, dict) else {}


def _load_codex(home: Path) -> tuple[Path, dict[str, Any] | None]:
    path = home / ".codex" / "config.toml"
    if not path.is_file():
        return path, None
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    servers = data.get("mcp_servers")
    return path, servers if isinstance(servers, dict) else {}


_LOADERS: dict[str, Callable[[Path], tuple[Path, dict[str, Any] | None]]] = {
    "claude-code": _load_claude,
    "codex": _load_codex,
}


def _judge(client: str, sid: str, want: str, entry: Any) -> tuple[str, str]:
    add = fix_add(client, sid, want)
    swap = f"{fix_remove(client, sid)} && {add}"
    if not isinstance(entry, dict):
        return "missing", f"not registered; run: {add}"
    if client == "claude-code" and entry.get("type") not in CLAUDE_HTTP_TYPES:
        # An entry without type is read as stdio, so its url is ignored.
        t = entry.get("type")
        shown = repr(t) if isinstance(t, str) and len(t) <= 32 else "<missing or odd>"
        return "wrong-type", f"entry type is {shown}, want 'http'; run: {swap}"
    if client == "codex" and entry.get("enabled") is False:
        return "disabled", f"present but enabled = false; set enabled = true in [mcp_servers.{sid}]"
    got = entry.get("url")
    if not isinstance(got, str) or got.rstrip("/") != want.rstrip("/"):
        return "wrong-url", f"url is {safe_url(got)}, want {want}; run: {swap}"
    return "ok", f"registered at {want}"


def observe(roster: list[dict[str, Any]], *, home: Path) -> list[Finding]:
    """One finding per (server, client). Reads two config files; writes nothing."""
    out: list[Finding] = []
    for client in CLIENTS:
        wanted = [r for r in roster if client in r["clients"]]
        if not wanted:
            continue
        try:
            path, servers = _LOADERS[client](home)
        except (OSError, ValueError, UnicodeDecodeError) as e:  # JSON/TOML errors ⊂ ValueError
            out.append((f"{client}/*", "error", f"{client} config unreadable: {type(e).__name__}"))
            continue
        for r in wanted:
            sid, want = r["id"], r["url"]
            if servers is None:
                add = fix_add(client, sid, want)
                out.append((f"{client}/{sid}", "missing",
                            f"{path} absent (client not set up?); run: {add}"))
                continue
            status, detail = _judge(client, sid, want, servers.get(sid))
            out.append((f"{client}/{sid}", status, detail))
    return out
