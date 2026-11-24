#!/usr/bin/env python3
"""ade_paseo_client: shared zero-subprocess loopback HTTP/MCP and WebSocket client for Paseo.

Queue #90 (2026-11-24, RAM relief 2b): replaces repeated `paseo` CLI subprocesses (~150 MB Node.js
startup per call) in periodic ADE pollers with direct loopback requests to the local Paseo daemon.

Transports (stdlib-only, Python 3.9+, macOS and Linux):
  1. Stateless loopback HTTP / Agent MCP (`POST http://<loopback>:<port>/mcp/agents`,
     `GET /api/health`, `GET /api/status`) — 1 RTT (~2-5 ms), zero persistent daemon session state.
     Used for `list_pending_permissions`, `respond_to_permission`, `get_agent_status`,
     `list_workspaces`, `list_providers`, `list_models`, `list_schedules`, `update_agent`,
     `archive_agent`, and `send_agent_prompt`.
  2. Loopback WebSocket RPC (`ws://<loopback>:<port>/ws`, pure stdlib RFC 6455) — exact wire parity
     with the `paseo` CLI (`hello` -> `server_info`, cursor-paginated `fetch_agents_request` with
     no 50/200-agent or 48h MCP cap, `fetch_agent_request`, `fetch_workspaces_request`,
     `fetch_agent_timeline_request`, `usage.list_reports.request`).

Both transports also support local Unix domain sockets (`unix:///abs/path/to.sock`), which Paseo
supports for IPC daemons and which allows hermetic offline subprocess tests without binding any TCP
port. Non-loopback TCP hosts are always refused, loopback HTTP never routes through proxies, and
credentials (`PASEO_PASSWORD` or `<PASEO_HOME>/local-credential`) are never logged or included in
exceptions.
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import socket
import stat
import struct
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

DEFAULT_LISTEN = "127.0.0.1:7263"
DEFAULT_BASE_URL = f"http://{DEFAULT_LISTEN}"
DEFAULT_MCP_URL = f"{DEFAULT_BASE_URL}/mcp/agents"
DEFAULT_WS_URL = f"ws://{DEFAULT_LISTEN}/ws"

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
WS_MAGIC_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

DEFAULT_TIMEOUT_S = 10.0
MAX_HTTP_BYTES = 8_000_000
MAX_ERROR_BYTES = 65_536
MAX_WS_BYTES = 32_000_000
MAX_CRED_BYTES = 4096
MAX_CONFIG_BYTES = 2_000_000
MAX_CACHE_BYTES = 16_000_000
MAX_FETCH_PAGES = 100
AGENT_PAGE_LIMIT = 200

ENV_DAEMON_URL = "ADE_PASEO_URL"
ENV_TRANSPORT = "ADE_PASEO_TRANSPORT"
ENV_CACHE_TTL = "ADE_PASEO_CACHE_TTL"
ENV_CACHE_DIR = "ADE_PASEO_CACHE_DIR"
PARENT_AGENT_ID_LABEL = "paseo.parent-agent-id"


class DaemonError(Exception):
    """Loopback daemon unreachable, unauthorized, malformed, or refused an operation."""


class _McpUnauthorizedError(DaemonError):
    """Internal marker: `/mcp/agents` returned HTTP 401 (eligible for `/ws` localCredential fallback)."""


class AgentNotFoundError(DaemonError, LookupError):
    """The daemon explicitly reported that the requested agent ID does not exist."""


@dataclass(frozen=True)
class DaemonTarget:
    """Validated local-only Paseo daemon target (loopback TCP or local Unix socket)."""

    kind: str  # "tcp" | "unix"
    host: str = "127.0.0.1"
    port: int = 7263
    socket_path: str = ""
    mcp_only: bool = False
    ws_only: bool = False

    @property
    def http_base_url(self) -> str:
        if self.kind == "unix":
            return f"unix://{self.socket_path}"
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"

    @property
    def mcp_url(self) -> str:
        if self.kind == "unix":
            return f"unix://{self.socket_path}"
        return f"{self.http_base_url}/mcp/agents"

    @property
    def ws_url(self) -> str:
        if self.kind == "unix":
            return f"unix://{self.socket_path}"
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"ws://{host}:{self.port}/ws"

    @property
    def host_header(self) -> str:
        if self.kind == "unix":
            return "localhost"
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.port}"

    @property
    def cache_key_prefix(self) -> str:
        if self.kind == "unix":
            return f"unix:{self.socket_path}"
        return f"tcp:{self.host}:{self.port}"


def _read_bounded_regular(path: Path, max_bytes: int) -> Optional[bytes]:
    """Read a regular non-symlink file with O_NOFOLLOW and a strict byte cap; None if missing."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(str(path), flags)
    except FileNotFoundError:
        return None
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > max_bytes:
            return None
        chunks: List[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, max_bytes + 1 - total)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                return None
        return b"".join(chunks)
    except OSError:
        return None
    finally:
        os.close(fd)


def _normalize_loopback_host(host: Optional[str]) -> str:
    if not host:
        raise DaemonError("daemon URL missing host")
    cleaned = host.strip().lower()
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1]
    if cleaned not in LOOPBACK_HOSTS:
        raise DaemonError(f"daemon host must be loopback (127.0.0.1, localhost, or ::1), got {host!r}")
    return cleaned


def _validate_unix_path_string(sock: str) -> str:
    if not sock.startswith("/") or "\x00" in sock or ".." in Path(sock).parts:
        raise DaemonError("unix daemon target must be a normalized absolute socket path")
    return sock


def _validate_unix_socket(socket_path: str) -> None:
    """Verify `socket_path` exists, is not a symlink, and is an actual Unix socket."""
    _validate_unix_path_string(socket_path)
    try:
        st = os.lstat(socket_path)
    except OSError as exc:
        raise DaemonError(f"unix daemon socket unavailable: {type(exc).__name__}") from exc
    if not stat.S_ISSOCK(st.st_mode):
        raise DaemonError("unix daemon target is not a socket")


def _parse_listen_string(raw: str) -> DaemonTarget:
    text = raw.strip()
    if not text:
        raise DaemonError("empty daemon listen address")
    if text.startswith("unix://") or text.startswith("/"):
        sock = text[len("unix://"):] if text.startswith("unix://") else text
        sock = _validate_unix_path_string(sock.strip())
        return DaemonTarget(kind="unix", socket_path=sock)
    if text.isdigit():
        port = int(text)
        if not (1 <= port <= 65535):
            raise DaemonError("invalid daemon port")
        return DaemonTarget(kind="tcp", host="127.0.0.1", port=port)
    parsed = urllib.parse.urlsplit(f"http://{text}" if "://" not in text else text)
    host = _normalize_loopback_host(parsed.hostname)
    try:
        port = parsed.port
    except ValueError as exc:
        raise DaemonError("invalid daemon port") from exc
    if port is None or not (1 <= port <= 65535):
        raise DaemonError("daemon target must include a valid port")
    return DaemonTarget(kind="tcp", host=host, port=port)


def parse_daemon_url(url: str) -> DaemonTarget:
    """Validate and parse a loopback HTTP/WS or local Unix socket URL."""
    if not isinstance(url, str) or not url.strip():
        raise DaemonError("daemon URL must be a non-empty string")
    raw = url.strip()
    if raw.startswith("unix://"):
        rest = raw[len("unix://"):]
        mcp_only = False
        ws_only = False
        if rest.endswith("#mcp"):
            rest, mcp_only = rest[:-4], True
        elif rest.endswith("#ws"):
            rest, ws_only = rest[:-3], True
        rest = _validate_unix_path_string(rest)
        return DaemonTarget(kind="unix", socket_path=rest, mcp_only=mcp_only, ws_only=ws_only)
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in ("http", "ws"):
        raise DaemonError("daemon URL scheme must be http, ws, or unix")
    if parsed.username is not None or parsed.password is not None:
        raise DaemonError("daemon URL must not embed credentials")
    if parsed.query or parsed.fragment:
        raise DaemonError("daemon URL must not contain query or fragment")
    host = _normalize_loopback_host(parsed.hostname)
    try:
        port = parsed.port
    except ValueError as exc:
        raise DaemonError("invalid daemon port") from exc
    if port is None or not (1 <= port <= 65535):
        raise DaemonError("daemon URL must specify an explicit port")
    path = parsed.path or ""
    if parsed.scheme == "http":
        if path == "/mcp/agents":
            return DaemonTarget(kind="tcp", host=host, port=port, mcp_only=True)
        if path in ("", "/"):
            return DaemonTarget(kind="tcp", host=host, port=port)
        raise DaemonError("HTTP daemon URL path must be empty or /mcp/agents")
    # ws://
    if path in ("", "/", "/ws"):
        return DaemonTarget(kind="tcp", host=host, port=port, ws_only=True)
    raise DaemonError("WebSocket daemon URL path must be empty or /ws")


def resolve_paseo_home(paseo_home: Optional[Path] = None, env: Optional[Mapping[str, str]] = None) -> Path:
    if paseo_home is not None:
        return Path(paseo_home).expanduser()
    e = os.environ if env is None else env
    raw = (e.get("PASEO_HOME") or "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".paseo"


def discover_daemon_target(
    url: Optional[str] = None,
    paseo_home: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
) -> DaemonTarget:
    """Resolve the local Paseo daemon target from explicit URL, ADE_PASEO_URL, or ~/.paseo/config.json."""
    e = os.environ if env is None else env
    explicit = url if url is not None else (e.get(ENV_DAEMON_URL) or "").strip()
    if explicit:
        return parse_daemon_url(explicit)
    home = resolve_paseo_home(paseo_home, e)
    raw_cfg = _read_bounded_regular(home / "config.json", MAX_CONFIG_BYTES)
    if raw_cfg is not None:
        try:
            cfg = json.loads(raw_cfg.decode("utf-8"))
            listen = (cfg.get("daemon") or {}).get("listen") if isinstance(cfg, dict) else None
            if isinstance(listen, str) and listen.strip():
                return _parse_listen_string(listen)
        except (ValueError, UnicodeDecodeError):
            pass
    return _parse_listen_string(DEFAULT_LISTEN)


def read_local_auth(
    paseo_home: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Optional[Tuple[str, str]]:
    """Return ('password', value) or ('localCredential', token) or None. Never logs or prints secrets."""
    e = os.environ if env is None else env
    pw = (e.get("PASEO_PASSWORD") or "").strip()
    if pw:
        return ("password", pw)
    home = resolve_paseo_home(paseo_home, e)
    raw = _read_bounded_regular(home / "local-credential", MAX_CRED_BYTES)
    if raw is not None:
        try:
            tok = raw.decode("utf-8").strip()
            if tok:
                return ("localCredential", tok)
        except UnicodeDecodeError:
            pass
    return None


def transport_mode(
    cli_override: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    *,
    cli_env_vars: Sequence[str] = (),
) -> str:
    """Return 'daemon' (default, zero-subprocess) or 'cli' (explicit opt-in only).

    Priority:
      1. Explicit ADE_PASEO_URL always selects 'daemon'.
      2. Explicit ADE_PASEO_TRANSPORT ('daemon' or 'cli') wins next.
      3. Explicit CLI binary override (flag value or named env var) selects 'cli' for backwards
         compatibility with callers and test fixtures that inject a custom paseo binary path.
      4. Default is always 'daemon' (zero Node.js subprocesses).
    """
    e = os.environ if env is None else env
    if (e.get(ENV_DAEMON_URL) or "").strip():
        return "daemon"
    explicit = (e.get(ENV_TRANSPORT) or "").strip().lower()
    if explicit in ("daemon", "http", "ws"):
        return "daemon"
    if explicit == "cli":
        return "cli"
    if cli_override and str(cli_override).strip() and str(cli_override).strip() != "paseo":
        return "cli"
    for key in cli_env_vars:
        val = (e.get(key) or "").strip()
        if val and val != "paseo":
            return "cli"
    return "daemon"


# ---------------------------------------------------------------- HTTP / MCP transport


Opener = Callable[[str, bytes, Dict[str, str], float], Tuple[int, str, bytes]]


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse all HTTP redirects so loopback requests can never be redirected off-host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise DaemonError(f"daemon redirected (HTTP {code})")

    def http_error_302(self, req, fp, code, msg, headers):  # type: ignore[override]
        raise DaemonError(f"daemon redirected (HTTP {code})")

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _build_loopback_opener() -> urllib.request.OpenerDirector:
    """Strict HTTP-only loopback opener: no proxies, no redirects, no HTTPS/FTP/File/Data handlers."""
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPHandler(),
        _NoRedirectHandler(),
        urllib.request.HTTPErrorProcessor(),
        urllib.request.HTTPDefaultErrorHandler(),
    ):
        opener.add_handler(handler)
    return opener


class _UnixHTTPConnection(http.client.HTTPConnection):
    """HTTP/1.1 connection over a local AF_UNIX stream socket."""

    def __init__(self, socket_path: str, timeout: float = DEFAULT_TIMEOUT_S) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        _validate_unix_socket(self._socket_path)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self._socket_path)
        except OSError:
            sock.close()
            raise
        self.sock = sock


def _read_bounded_http_body(resp: Any, status: int) -> bytes:
    if status == 200:
        data = resp.read(MAX_HTTP_BYTES + 1)
        if len(data) > MAX_HTTP_BYTES:
            raise DaemonError("daemon HTTP response exceeded size limit")
        return data
    return resp.read(MAX_ERROR_BYTES)


def _unix_http_request(
    socket_path: str,
    method: str,
    path: str,
    body: Optional[bytes],
    headers: Dict[str, str],
    timeout: float,
) -> Tuple[int, str, bytes]:
    conn = _UnixHTTPConnection(socket_path, timeout=timeout)
    try:
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        data = _read_bounded_http_body(resp, resp.status)
        return resp.status, resp.getheader("Content-Type", "") or "", data
    finally:
        conn.close()


def urllib_opener(url: str, body: bytes, headers: Dict[str, str], timeout: float) -> Tuple[int, str, bytes]:
    """POST over loopback HTTP (never via proxy or redirect) or local unix:// socket, with bounded reads."""
    if url.startswith("unix://"):
        sock = url[len("unix://"):].split("#", 1)[0]
        return _unix_http_request(sock, "POST", "/mcp/agents", body, headers, timeout)
    no_proxy = _build_loopback_opener()
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with no_proxy.open(request, timeout=timeout) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), _read_bounded_http_body(resp, resp.status)
    except urllib.error.HTTPError as exc:
        ctype = exc.headers.get("Content-Type", "") if exc.headers else ""
        return exc.code, ctype, exc.read(MAX_ERROR_BYTES)


def urllib_get(url: str, headers: Dict[str, str], timeout: float, path: str = "/api/health") -> Tuple[int, str, bytes]:
    """GET over loopback HTTP (never via proxy or redirect) or local unix:// socket, with bounded reads."""
    if url.startswith("unix://"):
        sock = url[len("unix://"):].split("#", 1)[0]
        return _unix_http_request(sock, "GET", path, None, headers, timeout)
    no_proxy = _build_loopback_opener()
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with no_proxy.open(request, timeout=timeout) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), _read_bounded_http_body(resp, resp.status)
    except urllib.error.HTTPError as exc:
        ctype = exc.headers.get("Content-Type", "") if exc.headers else ""
        return exc.code, ctype, exc.read(MAX_ERROR_BYTES)


def _is_not_found_text(text: str) -> bool:
    low = text.lower()
    return "not found" in low or "no agent" in low or "unknown agent" in low


class McpClient:
    """Stateless JSON-RPC 2.0 client over Paseo's loopback Agent MCP route (`/mcp/agents`)."""

    def __init__(
        self,
        url: str = DEFAULT_MCP_URL,
        opener: Opener = urllib_opener,
        timeout: float = DEFAULT_TIMEOUT_S,
        auth: Optional[Tuple[str, str]] = None,
        *,
        strict_mcp_path: bool = False,
    ) -> None:
        target = parse_daemon_url(url)
        if strict_mcp_path and target.kind == "tcp" and not target.mcp_only:
            raise DaemonError("daemon URL must be http://<loopback>:<port>/mcp/agents")
        if target.ws_only:
            raise DaemonError("McpClient requires an http:// or unix:// daemon URL")
        self.target = target
        self.url = target.mcp_url
        self.opener = opener
        self.timeout = timeout
        self._auth = auth
        self._id = 0

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._auth and self._auth[0] == "password" and self._auth[1]:
            headers["Authorization"] = f"Bearer {self._auth[1]}"
        return headers

    def call_tool(self, tool: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Invoke an Agent MCP tool and return its `structuredContent` dict."""
        self._id += 1
        req_id = self._id
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments or {}},
            }
        ).encode("utf-8")
        try:
            status, ctype, raw = self.opener(self.url, body, self._headers(), self.timeout)
        except (OSError, urllib.error.URLError, http.client.HTTPException, ValueError) as exc:
            raise DaemonError(f"daemon unreachable: {type(exc).__name__}") from exc
        if status == 401:
            raise _McpUnauthorizedError("daemon answered HTTP 401")
        if status != 200:
            raise DaemonError(f"daemon answered HTTP {status}")
        text = raw.decode("utf-8", "replace")
        messages: List[Any] = []
        try:
            if "text/event-stream" in ctype.lower():
                messages = [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")]
            else:
                messages = [json.loads(text)]
        except ValueError as exc:
            raise DaemonError("daemon answer is not JSON") from exc
        for msg in messages:
            if isinstance(msg, dict) and msg.get("id") == req_id:
                if "error" in msg:
                    err = msg.get("error")
                    emsg = str(err.get("message", "")) if isinstance(err, dict) else str(err)
                    if _is_not_found_text(emsg):
                        raise AgentNotFoundError(f"{tool}: not found")
                    raise DaemonError(f"daemon refused {tool}")
                result = msg.get("result")
                if not isinstance(result, dict):
                    raise DaemonError(f"{tool} returned malformed result")
                if result.get("isError"):
                    parts = [
                        str(c.get("text", ""))
                        for c in (result.get("content") or [])
                        if isinstance(c, dict)
                    ]
                    joined = " ".join(parts)
                    if _is_not_found_text(joined):
                        raise AgentNotFoundError(f"{tool}: not found")
                    raise DaemonError(f"{tool} failed")
                structured = result.get("structuredContent")
                if not isinstance(structured, dict):
                    raise DaemonError(f"{tool} returned no structured content")
                return structured
        raise DaemonError(f"no answer to {tool}")

    def health(self) -> Dict[str, Any]:
        url = self.target.http_base_url if self.target.kind == "unix" else f"{self.target.http_base_url}/api/health"
        try:
            status, _, raw = urllib_get(url, {"Accept": "application/json"}, self.timeout, path="/api/health")
        except (OSError, urllib.error.URLError, http.client.HTTPException, ValueError) as exc:
            raise DaemonError(f"daemon unreachable: {type(exc).__name__}") from exc
        if status != 200:
            raise DaemonError(f"daemon /api/health answered HTTP {status}")
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except ValueError as exc:
            raise DaemonError("daemon /api/health answer is not JSON") from exc
        if not isinstance(data, dict):
            raise DaemonError("daemon /api/health returned unexpected shape")
        return data

    def status(self) -> Dict[str, Any]:
        headers = {"Accept": "application/json"}
        if self._auth and self._auth[1]:
            headers["Authorization"] = f"Bearer {self._auth[1]}"
        url = self.target.http_base_url if self.target.kind == "unix" else f"{self.target.http_base_url}/api/status"
        try:
            status_code, _, raw = urllib_get(url, headers, self.timeout, path="/api/status")
        except (OSError, urllib.error.URLError, http.client.HTTPException, ValueError) as exc:
            raise DaemonError(f"daemon unreachable: {type(exc).__name__}") from exc
        if status_code != 200:
            raise DaemonError(f"daemon /api/status answered HTTP {status_code}")
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except ValueError as exc:
            raise DaemonError("daemon /api/status answer is not JSON") from exc
        if not isinstance(data, dict):
            raise DaemonError("daemon /api/status returned unexpected shape")
        return data

    def list_pending_permissions(self) -> List[Dict[str, Any]]:
        payload = self.call_tool("list_pending_permissions", {})
        perms = payload.get("permissions")
        if not isinstance(perms, list):
            raise DaemonError("unexpected list_pending_permissions shape")
        return perms

    def respond_to_permission(self, agent_id: str, request_id: str, response: Dict[str, Any]) -> None:
        answer = self.call_tool(
            "respond_to_permission",
            {"agentId": agent_id, "requestId": request_id, "response": response},
        )
        if answer.get("success") is not True:
            raise DaemonError("permission response not confirmed")

    def get_agent_status(self, agent_id: str) -> Dict[str, Any]:
        payload = self.call_tool("get_agent_status", {"agentId": agent_id})
        snap = payload.get("snapshot")
        if not isinstance(snap, dict):
            raise DaemonError("get_agent_status returned no snapshot")
        return snap

    def list_agents(
        self,
        *,
        include_background: bool = True,
        include_archived: bool = False,
        cwd: Optional[str] = None,
        since_hours: int = 24 * 30,
        statuses: Optional[List[str]] = None,
        limit: int = AGENT_PAGE_LIMIT,
    ) -> List[Dict[str, Any]]:
        args: Dict[str, Any] = {
            "includeBackground": bool(include_background),
            "includeArchived": bool(include_archived),
            "sinceHours": max(1, min(int(since_hours), 24 * 30)),
            "limit": max(1, min(int(limit), AGENT_PAGE_LIMIT)),
        }
        if cwd:
            args["cwd"] = cwd
        if statuses:
            args["statuses"] = list(statuses)
        payload = self.call_tool("list_agents", args)
        agents = payload.get("agents")
        if not isinstance(agents, list):
            raise DaemonError("unexpected list_agents shape")
        return agents

    def list_workspaces(self, *, include_background: bool = False) -> List[Dict[str, Any]]:
        payload = self.call_tool("list_workspaces", {"includeBackground": bool(include_background)})
        ws = payload.get("workspaces")
        if not isinstance(ws, list):
            raise DaemonError("unexpected list_workspaces shape")
        return ws

    def list_providers(self) -> List[Dict[str, Any]]:
        payload = self.call_tool("list_providers", {})
        provs = payload.get("providers")
        if not isinstance(provs, list):
            raise DaemonError("unexpected list_providers shape")
        return provs

    def list_models(self, provider: str) -> List[Dict[str, Any]]:
        payload = self.call_tool("list_models", {"provider": provider})
        models = payload.get("models")
        if not isinstance(models, list):
            raise DaemonError("unexpected list_models shape")
        return models

    def list_schedules(self) -> List[Dict[str, Any]]:
        payload = self.call_tool("list_schedules", {})
        scheds = payload.get("schedules")
        if not isinstance(scheds, list):
            raise DaemonError("unexpected list_schedules shape")
        return scheds

    def update_agent(
        self,
        agent_id: str,
        *,
        name: Optional[str] = None,
        labels: Optional[Dict[str, str]] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        args: Dict[str, Any] = {"agentId": agent_id}
        if name is not None:
            args["name"] = name
        if labels is not None:
            args["labels"] = dict(labels)
        if settings is not None:
            args["settings"] = dict(settings)
        answer = self.call_tool("update_agent", args)
        if answer.get("success") is not True:
            raise DaemonError("update_agent not confirmed")
        return answer

    def archive_agent(self, agent_id: str) -> None:
        answer = self.call_tool("archive_agent", {"agentId": agent_id})
        if answer.get("success") is not True:
            raise DaemonError("archive_agent not confirmed")

    def send_agent_prompt(
        self,
        agent_id: str,
        prompt: str,
        *,
        active_turn_behavior: Optional[str] = None,
        notify_on_finish: Optional[bool] = None,
    ) -> Dict[str, Any]:
        args: Dict[str, Any] = {"agentId": agent_id, "prompt": prompt}
        if active_turn_behavior is not None:
            args["activeTurnBehavior"] = active_turn_behavior
        if notify_on_finish is not None:
            args["notifyOnFinish"] = notify_on_finish
        return self.call_tool("send_agent_prompt", args)


# ---------------------------------------------------------------- RFC 6455 loopback WebSocket RPC


class _StdlibWebSocket:
    """Minimal RFC 6455 client over a loopback TCP or AF_UNIX socket (stdlib only)."""

    def __init__(self, target: DaemonTarget, timeout: float = DEFAULT_TIMEOUT_S) -> None:
        self.target = target
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._buf = bytearray()

    def connect(self) -> None:
        deadline = time.monotonic() + self.timeout
        try:
            if self.target.kind == "unix":
                _validate_unix_socket(self.target.socket_path)
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(self.timeout)
                try:
                    sock.connect(self.target.socket_path)
                except OSError:
                    sock.close()
                    raise
            else:
                sock = socket.create_connection((self.target.host, self.target.port), timeout=self.timeout)
                sock.settimeout(self.timeout)
        except DaemonError:
            raise
        except OSError as exc:
            raise DaemonError(f"daemon WebSocket unreachable: {type(exc).__name__}") from exc
        self._sock = sock
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        expected_accept = base64.b64encode(
            hashlib.sha1((key + WS_MAGIC_GUID).encode("ascii")).digest()
        ).decode("ascii")
        req = (
            f"GET /ws HTTP/1.1\r\n"
            f"Host: {self.target.host_header}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        ).encode("ascii")
        try:
            rem = deadline - time.monotonic()
            if rem <= 0:
                raise DaemonError("daemon WebSocket handshake timed out")
            sock.settimeout(min(self.timeout, rem))
            sock.sendall(req)
            raw = bytearray()
            while b"\r\n\r\n" not in raw:
                rem = deadline - time.monotonic()
                if rem <= 0:
                    raise DaemonError("daemon WebSocket handshake timed out")
                sock.settimeout(min(self.timeout, rem))
                chunk = sock.recv(4096)
                if not chunk:
                    raise DaemonError("daemon closed connection during WebSocket handshake")
                raw.extend(chunk)
                if len(raw) > 65_536:
                    raise DaemonError("oversized WebSocket handshake response")
        except DaemonError:
            self.close()
            raise
        except socket.timeout as exc:
            self.close()
            raise DaemonError("daemon WebSocket handshake timed out") from exc
        except OSError as exc:
            self.close()
            raise DaemonError(f"WebSocket handshake failed: {type(exc).__name__}") from exc
        sep = raw.index(b"\r\n\r\n")
        head = raw[:sep].decode("iso-8859-1", "replace")
        self._buf = bytearray(raw[sep + 4:])
        lines = head.split("\r\n")
        status_line = lines[0] if lines else ""
        status_parts = status_line.split(" ", 2)
        if len(status_parts) < 2 or not status_parts[0].startswith("HTTP/") or status_parts[1] != "101":
            self.close()
            raise DaemonError(f"WebSocket upgrade rejected ({status_line[:60]})")
        headers: Dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        if headers.get("sec-websocket-accept") != expected_accept:
            self.close()
            raise DaemonError("WebSocket Sec-WebSocket-Accept mismatch")

    def _recv_exact(self, n: int, deadline: float) -> bytes:
        assert self._sock is not None
        while len(self._buf) < n:
            rem = deadline - time.monotonic()
            if rem <= 0:
                raise DaemonError("daemon WebSocket timed out")
            self._sock.settimeout(min(self.timeout, rem))
            try:
                chunk = self._sock.recv(max(4096, min(65_536, n - len(self._buf))))
            except socket.timeout as exc:
                raise DaemonError("daemon WebSocket timed out") from exc
            except OSError as exc:
                raise DaemonError(f"daemon WebSocket read failed: {type(exc).__name__}") from exc
            if not chunk:
                raise DaemonError("daemon WebSocket closed unexpectedly")
            self._buf.extend(chunk)
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        if self._sock is None:
            raise DaemonError("WebSocket is not connected")
        mask = os.urandom(4)
        header = bytearray([0x80 | (opcode & 0x0F)])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65_536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))
        header.extend(mask)
        masked = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
        try:
            self._sock.sendall(bytes(header) + masked)
        except OSError as exc:
            raise DaemonError(f"daemon WebSocket write failed: {type(exc).__name__}") from exc

    def send_json(self, obj: Dict[str, Any]) -> None:
        self._send_frame(0x1, json.dumps(obj, separators=(",", ":")).encode("utf-8"))

    def recv_json(self, deadline: Optional[float] = None) -> Dict[str, Any]:
        end = deadline if deadline is not None else time.monotonic() + self.timeout
        chunks: List[bytes] = []
        total = 0
        while True:
            b1, b2 = self._recv_exact(2, end)
            fin = bool(b1 & 0x80)
            opcode = b1 & 0x0F
            masked = bool(b2 & 0x80)
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2, end))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8, end))[0]
            if opcode in (0x8, 0x9, 0xA):
                if not fin or length > 125:
                    raise DaemonError("invalid WebSocket control frame")
            elif opcode not in (0x0, 0x1, 0x2):
                raise DaemonError(f"unsupported WebSocket opcode {opcode:#x}")
            if total + length > MAX_WS_BYTES:
                raise DaemonError("daemon WebSocket message exceeded size limit")
            mask = self._recv_exact(4, end) if masked else b""
            payload = self._recv_exact(length, end) if length else b""
            if masked:
                payload = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
            if opcode == 0x9:  # ping -> pong
                rem = end - time.monotonic()
                if rem <= 0:
                    raise DaemonError("daemon WebSocket timed out")
                assert self._sock is not None
                self._sock.settimeout(min(self.timeout, rem))
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:  # pong
                continue
            if opcode == 0x8:  # close
                code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else 1000
                raise DaemonError(f"daemon WebSocket closed (code {code})")
            if opcode == 0x0 and not chunks:
                raise DaemonError("unexpected WebSocket continuation frame")
            if opcode in (0x1, 0x2) and chunks:
                raise DaemonError("unexpected WebSocket data frame during fragmented message")
            chunks.append(payload)
            total += len(payload)
            if fin:
                try:
                    parsed = json.loads(b"".join(chunks).decode("utf-8", "replace"))
                except ValueError as exc:
                    raise DaemonError("daemon WebSocket frame is not JSON") from exc
                if not isinstance(parsed, dict):
                    raise DaemonError("daemon WebSocket message is not a JSON object")
                return parsed

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.settimeout(min(1.0, self.timeout))
                self._send_frame(0x8, struct.pack("!H", 1000))
            except Exception:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None


class WsClient:
    """Loopback WebSocket RPC client matching Paseo's `/ws` session protocol."""

    def __init__(
        self,
        url: str = DEFAULT_WS_URL,
        timeout: float = DEFAULT_TIMEOUT_S,
        auth: Optional[Tuple[str, str]] = None,
        ws_factory: Optional[Callable[[DaemonTarget, float], Any]] = None,
        client_id: Optional[str] = None,
    ) -> None:
        target = parse_daemon_url(url)
        if target.mcp_only:
            raise DaemonError("WsClient cannot connect to an MCP-only URL")
        self.target = target
        self.timeout = timeout
        self._auth = auth
        self._ws_factory = ws_factory or _StdlibWebSocket
        self._client_id = client_id or f"ade-client-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._ws: Any = None
        self.server_info: Dict[str, Any] = {}
        self._seq = 0

    def __enter__(self) -> "WsClient":
        self.connect()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def connect(self) -> Dict[str, Any]:
        if self._ws is not None:
            return self.server_info
        ws = self._ws_factory(self.target, self.timeout)
        ws.connect()
        self._ws = ws
        hello: Dict[str, Any] = {
            "type": "hello",
            "clientId": self._client_id,
            "clientType": "cli",
            "protocolVersion": 1,
            "capabilities": {
                "hello_rejection": True,
                "owned_subscriptions": True,
                "all_providers": True,
                "explicit_event_subscriptions": True,
            },
        }
        if self._auth:
            kind, value = self._auth
            if kind == "password":
                hello["auth"] = {"kind": "password", "password": value}
            elif kind == "localCredential":
                hello["auth"] = {"kind": "localCredential", "token": value}
        deadline = time.monotonic() + self.timeout
        try:
            ws.send_json(hello)
            while True:
                msg = ws.recv_json(deadline)
                mtype = msg.get("type")
                if mtype == "hello_rejected":
                    reason = msg.get("reason") or msg.get("code") or "rejected"
                    raise DaemonError(f"daemon WebSocket hello rejected ({reason})")
                if mtype == "session":
                    inner = msg.get("message")
                    if isinstance(inner, dict) and inner.get("type") == "status":
                        payload = inner.get("payload")
                        if isinstance(payload, dict) and payload.get("status") == "server_info":
                            self.server_info = payload
                            return payload
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            finally:
                self._ws = None

    def _next_request_id(self) -> str:
        self._seq += 1
        return f"ade-{self._seq}-{uuid.uuid4().hex[:6]}"

    def rpc(
        self,
        message: Dict[str, Any],
        *,
        expected_type: Optional[str] = None,
        timeout: Optional[float] = None,
        collect_updates_type: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Send one correlated session request and wait for its matching response."""
        self.connect()
        req_id = message.get("requestId") or self._next_request_id()
        envelope = {"type": "session", "message": {**message, "requestId": req_id}}
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        self._ws.send_json(envelope)
        updates: List[Dict[str, Any]] = []
        while True:
            raw = self._ws.recv_json(deadline)
            inner = raw.get("message") if raw.get("type") == "session" else raw
            if not isinstance(inner, dict):
                continue
            itype = inner.get("type")
            payload = inner.get("payload") if isinstance(inner.get("payload"), dict) else inner
            rid = payload.get("requestId") or inner.get("requestId")
            if rid != req_id:
                continue
            if itype == "rpc_error":
                err = str(payload.get("error") or payload.get("message") or "rpc_error")
                code = str(payload.get("code") or "")
                if code.upper() in ("NOT_FOUND", "AGENT_NOT_FOUND") or _is_not_found_text(err):
                    raise AgentNotFoundError(err)
                raise DaemonError(f"daemon RPC error ({code or itype}): {err[:160]}")
            if collect_updates_type and itype == collect_updates_type:
                updates.append(payload)
                continue
            if expected_type is None or itype == expected_type:
                if payload.get("error"):
                    err = str(payload.get("error"))
                    if _is_not_found_text(err):
                        raise AgentNotFoundError(err)
                    raise DaemonError(f"daemon RPC failed: {err[:160]}")
                return payload, updates

    def fetch_agents(
        self,
        *,
        include_background: bool = False,
        include_archived: bool = False,
        labels: Optional[Mapping[str, str]] = None,
        active_only: bool = False,
        timeout: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Cursor-paginated `fetch_agents_request` (matches Paseo CLI `fetchAllAgents`, no 50/200 cap)."""
        daemon_filter: Dict[str, Any] = {}
        if include_archived:
            daemon_filter["includeArchived"] = True
        if include_background or include_archived:
            daemon_filter["includeBackground"] = True
        if labels:
            daemon_filter["labels"] = dict(labels)
        agents: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        seen_cursors: set = set()
        for _ in range(MAX_FETCH_PAGES):
            page: Dict[str, Any] = {"limit": AGENT_PAGE_LIMIT}
            if cursor:
                page["cursor"] = cursor
            req: Dict[str, Any] = {
                "type": "fetch_agents_request",
                "sort": [{"key": "created_at", "direction": "desc"}],
                "page": page,
            }
            if active_only:
                req["scope"] = "active"
            if daemon_filter:
                req["filter"] = daemon_filter
            payload, _ = self.rpc(req, expected_type="fetch_agents_response", timeout=timeout)
            entries = payload.get("entries")
            if not isinstance(entries, list):
                raise DaemonError("fetch_agents_response missing entries list")
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                agent = entry.get("agent") if isinstance(entry.get("agent"), dict) else entry
                if isinstance(agent, dict):
                    agents.append(agent)
            page_info = payload.get("pageInfo") if isinstance(payload.get("pageInfo"), dict) else {}
            nxt = page_info.get("nextCursor") or payload.get("nextCursor")
            if not isinstance(nxt, str) or not nxt:
                break
            if nxt in seen_cursors:
                raise DaemonError("fetch_agents pagination cursor loop")
            seen_cursors.add(nxt)
            cursor = nxt
        else:
            raise DaemonError(f"fetch_agents exceeded {MAX_FETCH_PAGES} pages")
        if not include_archived:
            agents = [a for a in agents if not a.get("archivedAt")]
        if labels:
            agents = [
                a for a in agents
                if isinstance(a.get("labels"), dict)
                and all(a["labels"].get(k) == v for k, v in labels.items())
            ]
        return agents

    def fetch_agent(self, agent_id: str, *, timeout: Optional[float] = None) -> Dict[str, Any]:
        payload, _ = self.rpc(
            {"type": "fetch_agent_request", "agentId": agent_id},
            expected_type="fetch_agent_response",
            timeout=timeout,
        )
        agent = payload.get("agent")
        if not isinstance(agent, dict):
            raise AgentNotFoundError(f"agent {agent_id} not found")
        return agent

    def fetch_workspaces(
        self, *, include_background: bool = False, timeout: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        req: Dict[str, Any] = {"type": "fetch_workspaces_request"}
        if include_background:
            req["includeBackground"] = True
            req["filter"] = {"includeBackground": True}
        payload, _ = self.rpc(req, expected_type="fetch_workspaces_response", timeout=timeout)
        entries = payload.get("entries")
        if not isinstance(entries, list):
            raise DaemonError("fetch_workspaces_response missing entries list")
        out: List[Dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            ws_item = entry.get("workspace") if isinstance(entry.get("workspace"), dict) else entry
            if isinstance(ws_item, dict):
                out.append(ws_item)
        return out

    def list_pending_permissions(self, *, timeout: Optional[float] = None) -> List[Dict[str, Any]]:
        """Derive pending permission items from `fetch_agents` snapshots (works with localCredential auth)."""
        agents = self.fetch_agents(include_background=True, include_archived=True, timeout=timeout)
        items: List[Dict[str, Any]] = []
        for a in agents:
            for p in a.get("pendingPermissions") or []:
                if isinstance(p, dict):
                    items.append({"agentId": a.get("id"), "status": a.get("status"), "request": p})
        return items

    def respond_to_permission(
        self,
        agent_id: str,
        request_id: str,
        response: Dict[str, Any],
        *,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Respond to a pending permission over `/ws` (`agent_permission_response` -> `agent_permission_resolved`)."""
        payload, _ = self.rpc(
            {
                "type": "agent_permission_response",
                "agentId": agent_id,
                "requestId": request_id,
                "response": dict(response),
            },
            expected_type="agent_permission_resolved",
            timeout=timeout,
        )
        if payload.get("agentId") not in (None, agent_id):
            raise DaemonError("permission resolution agentId mismatch")
        return payload

    def update_agent(
        self,
        agent_id: str,
        *,
        name: Optional[str] = None,
        labels: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Update agent metadata/labels over `/ws` (`update_agent_request` -> `update_agent_response`)."""
        req: Dict[str, Any] = {"type": "update_agent_request", "agentId": agent_id}
        if name is not None:
            req["name"] = name
        if labels is not None:
            req["labels"] = dict(labels)
        payload, _ = self.rpc(req, expected_type="update_agent_response", timeout=timeout)
        if payload.get("accepted") is not True:
            err = str(payload.get("error") or "update_agent rejected")[:160]
            raise DaemonError(f"update_agent not confirmed: {err}")
        return {"success": True, **payload}

    def archive_agent(self, agent_id: str, *, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Archive an agent over `/ws` (`archive_agent_request` -> `agent_archived`)."""
        payload, _ = self.rpc(
            {"type": "archive_agent_request", "agentId": agent_id},
            expected_type="agent_archived",
            timeout=timeout,
        )
        if payload.get("agentId") not in (None, agent_id) or not payload.get("archivedAt"):
            raise DaemonError("archive_agent not confirmed")
        return payload

    def fetch_agent_timeline(
        self,
        agent_id: str,
        *,
        direction: str = "tail",
        limit: int = 200,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        payload, _ = self.rpc(
            {
                "type": "fetch_agent_timeline_request",
                "agentId": agent_id,
                "direction": direction,
                "limit": limit,
            },
            expected_type="fetch_agent_timeline_response",
            timeout=timeout,
        )
        return payload

    def list_usage_reports(
        self,
        *,
        agent_id: Optional[str] = None,
        force_refresh: bool = False,
        timeout: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        req: Dict[str, Any] = {"type": "usage.list_reports.request"}
        if agent_id is not None:
            req["agentId"] = agent_id
        if force_refresh:
            req["forceRefresh"] = True
        payload, updates = self.rpc(
            req,
            expected_type="usage.list_reports.response",
            collect_updates_type="usage.list_reports.update",
            timeout=timeout,
        )
        reports = payload.get("reports")
        if isinstance(reports, list):
            return [r for r in reports if isinstance(r, dict)]
        out = []
        for u in updates:
            rep = u.get("report")
            if isinstance(rep, dict):
                out.append(rep)
        return out


# ---------------------------------------------------------------- CLI-compatible field mappers


def _normalize_model(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() == "default":
        return None
    return cleaned


def _resolve_model(snapshot: Mapping[str, Any]) -> Optional[str]:
    rt = snapshot.get("runtimeInfo")
    rt_model = _normalize_model(rt.get("model")) if isinstance(rt, dict) else None
    return rt_model or _normalize_model(snapshot.get("model"))


def _shorten_path(path: Any) -> str:
    if not isinstance(path, str):
        return ""
    home = os.environ.get("HOME") or ""
    if home and (path == home or path.startswith(home + "/")):
        return "~" + path[len(home):]
    return path


def snapshot_to_ls_row(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Convert a daemon AgentSnapshotPayload / MCP AgentListItem into `paseo ls --json` shape.

    Preserves `labels` and `archivedAt` alongside the standard CLI fields (`id`, `shortId`, `name`,
    `provider`, `thinking`, `status`, `cwd`, `created`, `updatedAt`, `workspaceId`) so callers
    need zero follow-up queries.
    """
    aid = str(snapshot.get("id") or "")
    provider = str(snapshot.get("provider") or "")
    model = _resolve_model(snapshot)
    combined_provider = f"{provider}/{model}" if (provider and model and "/" not in provider) else provider
    title = snapshot.get("title")
    name = title if isinstance(title, str) and title else (snapshot.get("name") or "-")
    row: Dict[str, Any] = {
        "id": aid,
        "shortId": str(snapshot.get("shortId") or aid[:7]),
        "name": str(name),
        "provider": combined_provider,
        "thinking": str(snapshot.get("effectiveThinkingOptionId") or snapshot.get("thinking") or "auto"),
        "status": str(snapshot.get("status") or ""),
        "cwd": _shorten_path(snapshot.get("cwd") or ""),
        "created": str(snapshot.get("createdAt") or snapshot.get("created") or ""),
        "updatedAt": snapshot.get("updatedAt"),
        "archivedAt": snapshot.get("archivedAt"),
        "background": bool(snapshot.get("background", False)),
        "workspaceId": snapshot.get("workspaceId"),
        "labels": dict(snapshot["labels"]) if isinstance(snapshot.get("labels"), dict) else {},
    }
    return row


def snapshot_to_inspect_dict(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Convert a daemon AgentSnapshotPayload into exact `paseo agent inspect --json` shape."""
    aid = str(snapshot.get("id") or "")
    labels = snapshot.get("labels") if isinstance(snapshot.get("labels"), dict) else {}
    parent = labels.get(PARENT_AGENT_ID_LABEL)
    if not isinstance(parent, str) or not parent:
        raw_parent = snapshot.get("parentAgentId")
        parent = raw_parent if isinstance(raw_parent, str) and raw_parent else None
    last_usage = snapshot.get("lastUsage")
    usage_out = None
    if isinstance(last_usage, dict):
        usage_out = {
            "InputTokens": last_usage.get("inputTokens") or 0,
            "OutputTokens": last_usage.get("outputTokens") or 0,
            "CachedTokens": last_usage.get("cachedInputTokens") or 0,
            "CostUsd": last_usage.get("totalCostUsd") or 0,
        }
    caps = snapshot.get("capabilities")
    caps_out = None
    if isinstance(caps, dict):
        caps_out = {
            "Streaming": bool(caps.get("supportsStreaming", False)),
            "Persistence": bool(caps.get("supportsSessionPersistence", False)),
            "DynamicModes": bool(caps.get("supportsDynamicModes", False)),
            "McpServers": bool(caps.get("supportsMcpServers", False)),
        }
        for k, v in caps.items():
            if "steer" in str(k).lower():
                caps_out[k] = v
    modes_raw = snapshot.get("availableModes")
    modes_out = (
        [{"id": m.get("id"), "label": m.get("label")} for m in modes_raw if isinstance(m, dict)]
        if isinstance(modes_raw, list)
        else None
    )
    perms_raw = snapshot.get("pendingPermissions")
    perms_out = [
        {"id": p.get("id"), "tool": p.get("name")}
        for p in (perms_raw if isinstance(perms_raw, list) else [])
        if isinstance(p, dict)
    ]
    archived_at = snapshot.get("archivedAt")
    return {
        "Id": aid,
        "Name": snapshot.get("title") or "-",
        "Provider": snapshot.get("provider") or "",
        "Model": _resolve_model(snapshot) or "-",
        "Thinking": snapshot.get("effectiveThinkingOptionId") or "auto",
        "Status": snapshot.get("status") or "",
        "Archived": archived_at is not None,
        "ArchivedAt": archived_at,
        "Mode": snapshot.get("currentModeId") or "default",
        "Cwd": snapshot.get("cwd") or "",
        "CreatedAt": snapshot.get("createdAt") or "",
        "UpdatedAt": snapshot.get("updatedAt") or "",
        "LastUsage": usage_out,
        "Capabilities": caps_out,
        "AvailableModes": modes_out,
        "PendingPermissions": perms_out,
        "Worktree": labels.get("paseo.worktree") or snapshot.get("worktreePath") or None,
        "ParentAgentId": parent,
        "Labels": dict(labels),
    }


def mcp_permission_to_cli_row(item: Mapping[str, Any]) -> Dict[str, Any]:
    """Convert an MCP `list_pending_permissions` item into `paseo permit ls --json` shape + `kind`."""
    req = item.get("request") if isinstance(item.get("request"), dict) else {}
    aid = str(item.get("agentId") or "")
    row: Dict[str, Any] = {
        "id": req.get("id"),
        "agentId": aid,
        "agentShortId": aid[:7],
        "name": req.get("name"),
        "description": req.get("description") or "-",
    }
    if req.get("kind") is not None:
        row["kind"] = req.get("kind")
    if req.get("provider") is not None:
        row["provider"] = req.get("provider")
    return row


# ---------------------------------------------------------------- Opt-in atomic snapshot cache


def default_cache_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    e = os.environ if env is None else env
    raw = (e.get(ENV_CACHE_DIR) or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".local/state/djbclark-ade/paseo-cache"


class SnapshotCache:
    """Optional short-TTL atomic cache (`0700` dir, `0600` files, `O_NOFOLLOW` reads).

    Opt-in ONLY for read-only polling snapshots (e.g. `ADE_PASEO_CACHE_TTL=5`). Safety-critical
    decisions and pre-mutation re-verifications (permissions, archiving, send guard) MUST pass
    `use_cache=False` and read directly from the daemon.
    """

    def __init__(self, cache_dir: Optional[Path] = None, ttl_s: float = 0.0) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
        self.ttl_s = max(0.0, float(ttl_s))

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return self.cache_dir / f"snap-{digest}.json"

    def get(self, key: str, *, now: Optional[float] = None) -> Optional[Any]:
        if self.ttl_s <= 0:
            return None
        path = self._path(key)
        raw = _read_bounded_regular(path, MAX_CACHE_BYTES)
        if raw is None:
            return None
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        if not isinstance(doc, dict):
            return None
        ts = doc.get("written_at")
        if not isinstance(ts, (int, float)) or isinstance(ts, bool):
            return None
        cur = time.time() if now is None else now
        if cur - ts < 0 or cur - ts > self.ttl_s:
            return None
        if doc.get("key") != key:
            return None
        return doc.get("payload")

    def put(self, key: str, payload: Any, *, now: Optional[float] = None) -> None:
        if self.ttl_s <= 0:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.cache_dir, 0o700)
        except OSError:
            pass
        target = self._path(key)
        doc = {
            "version": 1,
            "key": key,
            "written_at": time.time() if now is None else now,
            "written_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "payload": payload,
        }
        raw = (json.dumps(doc, separators=(",", ":")) + "\n").encode("utf-8")
        fd, tmp = tempfile.mkstemp(prefix=".snap-", suffix=".tmp", dir=str(self.cache_dir))
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(raw)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


# ---------------------------------------------------------------- Unified PaseoClient facade


class PaseoClient:
    """High-level zero-subprocess Paseo loopback daemon client for ADE pollers.

    Combines stateless HTTP/MCP (`/mcp/agents`) and loopback WebSocket RPC (`/ws`) so callers get:
      - Full paginated agent directory listings with no 50/200-agent or 48h cap (via WS `/ws`,
        or MCP `list_agents` when pointed at an MCP-only URL).
      - 1-RTT stateless inspect (`get_agent_status` via MCP, or `fetch_agent` via WS) returning
        exact `paseo agent inspect --json` shape.
      - 1-RTT stateless `list_pending_permissions` and `respond_to_permission` via MCP.
      - `list_workspaces`, `list_providers`, `list_models`, `list_schedules`, `list_usage_reports`.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        *,
        paseo_home: Optional[Path] = None,
        env: Optional[Mapping[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT_S,
        opener: Opener = urllib_opener,
        ws_factory: Optional[Callable[[DaemonTarget, float], Any]] = None,
        cache: Optional[SnapshotCache] = None,
        cache_ttl_s: Optional[float] = None,
    ) -> None:
        self.target = discover_daemon_target(url=url, paseo_home=paseo_home, env=env)
        self.timeout = timeout
        self._auth = read_local_auth(paseo_home=paseo_home, env=env)
        self._opener = opener
        self._ws_factory = ws_factory
        self._mcp_unauthorized = False
        self._mcp: Optional[McpClient] = None
        if not self.target.ws_only:
            self._mcp = McpClient(self.target.mcp_url, opener=opener, timeout=timeout, auth=self._auth)
        if cache is not None:
            self.cache: Optional[SnapshotCache] = cache
        else:
            ttl = cache_ttl_s
            if ttl is None:
                e = os.environ if env is None else env
                raw_ttl = (e.get(ENV_CACHE_TTL) or "").strip()
                if raw_ttl:
                    try:
                        ttl = float(raw_ttl)
                    except ValueError:
                        ttl = 0.0
            self.cache = SnapshotCache(default_cache_dir(env), ttl) if ttl and ttl > 0 else None

    @property
    def mcp(self) -> McpClient:
        if self._mcp is None:
            raise DaemonError("MCP transport unavailable for WebSocket-only daemon URL")
        return self._mcp

    def _ws(self) -> WsClient:
        if self.target.mcp_only:
            raise DaemonError("WebSocket transport unavailable for MCP-only daemon URL")
        return WsClient(
            self.target.ws_url,
            timeout=self.timeout,
            auth=self._auth,
            ws_factory=self._ws_factory,
        )

    def health(self) -> Dict[str, Any]:
        return self.mcp.health()

    def status(self) -> Dict[str, Any]:
        return self.mcp.status()

    def list_agents(
        self,
        *,
        include_background: bool = True,
        include_archived: bool = False,
        labels: Optional[Mapping[str, str]] = None,
        active_only: bool = False,
        cli_rows: bool = False,
        use_cache: bool = False,
    ) -> List[Dict[str, Any]]:
        """List local daemon agents (paginated via `/ws`; falls back to MCP only for MCP-only URLs)."""
        cache_key = ""
        if use_cache and self.cache is not None:
            lbl = sorted((str(k), str(v)) for k, v in (labels or {}).items())
            cache_key = (
                f"{self.target.cache_key_prefix}:agents:"
                f"bg={int(include_background)}:arch={int(include_archived)}:"
                f"act={int(active_only)}:lbl={json.dumps(lbl)}:cli={int(cli_rows)}"
            )
            cached = self.cache.get(cache_key)
            if isinstance(cached, list):
                return cached
        if self.target.mcp_only:
            raw = self.mcp.list_agents(
                include_background=include_background,
                include_archived=include_archived,
                limit=AGENT_PAGE_LIMIT,
            )
            if labels:
                raw = [
                    a for a in raw
                    if isinstance(a, dict)
                    and isinstance(a.get("labels"), dict)
                    and all(a["labels"].get(k) == v for k, v in labels.items())
                ]
            if not include_archived:
                raw = [a for a in raw if isinstance(a, dict) and not a.get("archivedAt")]
        else:
            with self._ws() as ws:
                raw = ws.fetch_agents(
                    include_background=include_background,
                    include_archived=include_archived,
                    labels=labels,
                    active_only=active_only,
                    timeout=self.timeout,
                )
        result = [snapshot_to_ls_row(a) for a in raw] if cli_rows else raw
        if use_cache and self.cache is not None and cache_key:
            try:
                self.cache.put(cache_key, result)
            except OSError:
                pass
        return result

    def _can_ws_local_cred_fallback(self) -> bool:
        return (
            not self.target.mcp_only
            and self._auth is not None
            and self._auth[0] == "localCredential"
        )

    def _prefer_ws(self) -> bool:
        """Use authenticated `/ws` RPC for ws-only targets or after `/mcp/agents` returns HTTP 401
        when authenticating via `<PASEO_HOME>/local-credential` (Paseo's `/mcp/agents` rejects
        `local-credential` with HTTP 401 while `/ws` accepts it)."""
        if self.target.ws_only:
            return True
        return self._mcp_unauthorized and self._can_ws_local_cred_fallback()

    def _mcp_or_ws(self, mcp_fn: Callable[[], Any], ws_fn: Callable[[WsClient], Any]) -> Any:
        if self._prefer_ws():
            with self._ws() as ws:
                return ws_fn(ws)
        try:
            return mcp_fn()
        except _McpUnauthorizedError:
            if not self._can_ws_local_cred_fallback():
                raise
            self._mcp_unauthorized = True
            with self._ws() as ws:
                return ws_fn(ws)

    def inspect_agent(self, agent_id: str, *, cli_shape: bool = True) -> Dict[str, Any]:
        """Inspect one agent (1-RTT MCP `get_agent_status`, falling back to WS `fetch_agent` on MCP 401 + localCredential)."""
        snap = self._mcp_or_ws(
            lambda: self.mcp.get_agent_status(agent_id),
            lambda ws: ws.fetch_agent(agent_id, timeout=self.timeout),
        )
        return snapshot_to_inspect_dict(snap) if cli_shape else snap

    def list_pending_permissions(self, *, cli_rows: bool = False) -> List[Dict[str, Any]]:
        """List all pending permissions via 1-RTT MCP (falling back to WS agents on MCP 401 + localCredential)."""
        items = self._mcp_or_ws(
            lambda: self.mcp.list_pending_permissions(),
            lambda ws: ws.list_pending_permissions(timeout=self.timeout),
        )
        return [mcp_permission_to_cli_row(i) for i in items] if cli_rows else items

    def respond_to_permission(self, agent_id: str, request_id: str, behavior: str = "allow") -> None:
        self._mcp_or_ws(
            lambda: self.mcp.respond_to_permission(agent_id, request_id, {"behavior": behavior}),
            lambda ws: ws.respond_to_permission(agent_id, request_id, {"behavior": behavior}, timeout=self.timeout),
        )

    def list_workspaces(self, *, include_background: bool = False) -> List[Dict[str, Any]]:
        return self._mcp_or_ws(
            lambda: self.mcp.list_workspaces(include_background=include_background),
            lambda ws: ws.fetch_workspaces(include_background=include_background, timeout=self.timeout),
        )

    def list_providers(self) -> List[Dict[str, Any]]:
        return self.mcp.list_providers()

    def list_models(self, provider: str) -> List[Dict[str, Any]]:
        return self.mcp.list_models(provider)

    def list_schedules(self) -> List[Dict[str, Any]]:
        return self.mcp.list_schedules()

    def list_usage_reports(self, *, agent_id: Optional[str] = None, force_refresh: bool = False) -> List[Dict[str, Any]]:
        with self._ws() as ws:
            return ws.list_usage_reports(agent_id=agent_id, force_refresh=force_refresh, timeout=self.timeout)

    def update_agent_labels(self, agent_id: str, labels: Mapping[str, str]) -> Dict[str, Any]:
        lbl = dict(labels)
        return self._mcp_or_ws(
            lambda: self.mcp.update_agent(agent_id, labels=lbl),
            lambda ws: ws.update_agent(agent_id, labels=lbl, timeout=self.timeout),
        )

    def archive_agent(self, agent_id: str, *, force: bool = False) -> None:
        if not force:
            info = self.inspect_agent(agent_id, cli_shape=True)
            if info.get("Archived") is True:
                raise DaemonError(f"agent {agent_id} is already archived")
            if str(info.get("Status") or "").lower() == "running":
                raise DaemonError(f"agent {agent_id} is running (refusing archive without force=True)")
        self._mcp_or_ws(
            lambda: self.mcp.archive_agent(agent_id),
            lambda ws: ws.archive_agent(agent_id, timeout=self.timeout),
        )
