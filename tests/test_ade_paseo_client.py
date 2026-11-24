"""Offline unit and end-to-end local Unix-socket tests for bin/ade_paseo_client.py and converted pollers.

Rules enforced:
- Rule 2: Never mutates PATH; uses explicit ADE_PASEO_URL (unix://...) or injected opener/client.
- Rule 17: Never binds any TCP port; mock HTTP/MCP + RFC 6455 WebSocket server listens on a private
  AF_UNIX socket inside pytest's tmp_path and is torn down cleanly after each test.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import ade_paseo_client as pc  # noqa: E402


# ---------------------------------------------------------------- private AF_UNIX HTTP/MCP + WS mock daemon


def _ws_recv_frame(conn: socket.socket, buf: bytearray):
    def exact(n: int) -> bytes:
        while len(buf) < n:
            chunk = conn.recv(65536)
            if not chunk:
                raise EOFError("eof")
            buf.extend(chunk)
        out = bytes(buf[:n])
        del buf[:n]
        return out

    b1, b2 = exact(2)
    op = b1 & 0x0F
    masked = bool(b2 & 0x80)
    ln = b2 & 0x7F
    if ln == 126:
        ln = struct.unpack("!H", exact(2))[0]
    elif ln == 127:
        ln = struct.unpack("!Q", exact(8))[0]
    mask = exact(4) if masked else b""
    payload = exact(ln) if ln else b""
    if masked:
        payload = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
    return op, payload


def _ws_send_frame(conn: socket.socket, op: int, payload: bytes, *, fin: bool = True) -> None:
    hdr = bytearray([(0x80 if fin else 0x00) | (op & 0x0F)])
    ln = len(payload)
    if ln < 126:
        hdr.append(ln)
    elif ln < 65536:
        hdr.append(126)
        hdr.extend(struct.pack("!H", ln))
    else:
        hdr.append(127)
        hdr.extend(struct.pack("!Q", ln))
    conn.sendall(bytes(hdr) + payload)


class FakeUnixPaseoDaemon:
    """Hermetic mock Paseo daemon speaking HTTP (/api/health, /api/status, /mcp/agents) and RFC 6455 /ws
    over a private AF_UNIX socket in tmp_path (zero TCP ports)."""

    def __init__(
        self,
        sock_path: Path,
        *,
        agents: Optional[List[Dict[str, Any]]] = None,
        permissions: Optional[List[Dict[str, Any]]] = None,
        workspaces: Optional[List[Dict[str, Any]]] = None,
        providers: Optional[List[Dict[str, Any]]] = None,
        models: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        schedules: Optional[List[Dict[str, Any]]] = None,
        usage_reports: Optional[List[Dict[str, Any]]] = None,
        page_size: int = 200,
        sse_mcp: bool = True,
        fragment_ws: bool = False,
        send_ping_before_reply: bool = False,
        require_password: Optional[str] = None,
        require_local_cred: Optional[str] = None,
        fail_http_status: Optional[int] = None,
        bad_json_http: bool = False,
    ) -> None:
        self.sock_path = Path(sock_path)
        self._short_dir: Optional[Path] = None
        # macOS AF_UNIX sun_path is capped at 104 bytes; use a short private 0700 tempdir when tmp_path is longer.
        if len(str(self.sock_path)) > 96:
            d = Path(tempfile.mkdtemp(prefix="ade-p-", dir="/tmp"))
            os.chmod(str(d), 0o700)
            self._short_dir = d
            self.sock_path = d / "p.sock"
        self.agents: List[Dict[str, Any]] = list(agents or [])
        self.permissions: List[Dict[str, Any]] = list(permissions or [])
        self.workspaces: List[Dict[str, Any]] = list(workspaces or [])
        self.providers: List[Dict[str, Any]] = list(providers or [])
        self.models: Dict[str, List[Dict[str, Any]]] = dict(models or {})
        self.schedules: List[Dict[str, Any]] = list(schedules or [])
        self.usage_reports: List[Dict[str, Any]] = list(usage_reports or [])
        self.page_size = page_size
        self.sse_mcp = sse_mcp
        self.fragment_ws = fragment_ws
        self.send_ping_before_reply = send_ping_before_reply
        self.require_password = require_password
        self.require_local_cred = require_local_cred
        self.fail_http_status = fail_http_status
        self.bad_json_http = bad_json_http
        self.mcp_calls: List[Dict[str, Any]] = []
        self.ws_requests: List[Dict[str, Any]] = []
        self.hellos: List[Dict[str, Any]] = []
        self.updated_labels: List[tuple] = []
        self.archived_ids: List[str] = []
        self.allowed_requests: List[tuple] = []
        self._stop = threading.Event()
        self._srv: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        return f"unix://{self.sock_path}"

    def __enter__(self) -> "FakeUnixPaseoDaemon":
        if self.sock_path.exists():
            self.sock_path.unlink()
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(self.sock_path))
        os.chmod(str(self.sock_path), 0o600)
        srv.listen(32)
        srv.settimeout(0.1)
        self._srv = srv
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self._stop.set()
        if self._srv is not None:
            try:
                self._srv.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        if self.sock_path.exists():
            try:
                self.sock_path.unlink()
            except OSError:
                pass
        if self._short_dir is not None:
            try:
                self._short_dir.rmdir()
            except OSError:
                pass

    def _accept_loop(self) -> None:
        assert self._srv is not None
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            t = threading.Thread(target=self._handle, args=(conn,), daemon=True)
            t.start()

    def _handle(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(5.0)
            buf = bytearray()
            while b"\r\n\r\n" not in buf:
                c = conn.recv(4096)
                if not c:
                    return
                buf.extend(c)
            sep = buf.index(b"\r\n\r\n")
            head = bytes(buf[:sep]).decode("iso-8859-1", "replace")
            del buf[: sep + 4]
            lines = head.split("\r\n")
            method, path, _ = lines[0].split(" ", 2)
            headers: Dict[str, str] = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            if headers.get("upgrade", "").lower() == "websocket" and path == "/ws":
                self._handle_ws(conn, headers, buf)
                return
            clen = int(headers.get("content-length") or "0")
            while len(buf) < clen:
                c = conn.recv(65536)
                if not c:
                    break
                buf.extend(c)
            body = bytes(buf[:clen])
            self._handle_http(conn, method, path, headers, body)
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _send_http(self, conn: socket.socket, status: int, ctype: str, body: bytes) -> None:
        reason = {200: "OK", 401: "Unauthorized", 404: "Not Found", 500: "Internal Server Error"}.get(status, "ERR")
        resp = (
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: {ctype}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode("ascii") + body
        conn.sendall(resp)

    def _handle_http(self, conn: socket.socket, method: str, path: str, headers: Dict[str, str], body: bytes) -> None:
        if self.fail_http_status is not None:
            self._send_http(conn, self.fail_http_status, "application/json", b'{"error":"forced"}')
            return
        if self.bad_json_http:
            self._send_http(conn, 200, "application/json", b"not-json")
            return
        if self.require_password and path != "/api/health":
            if headers.get("authorization") != f"Bearer {self.require_password}":
                self._send_http(conn, 401, "application/json", b'{"error":"Unauthorized"}')
                return
        if method == "GET" and path == "/api/health":
            self._send_http(conn, 200, "application/json", json.dumps({"status": "ok"}).encode())
            return
        if method == "GET" and path == "/api/status":
            self._send_http(conn, 200, "application/json", json.dumps({"status": "server_info", "version": "0.17.3"}).encode())
            return
        if method == "POST" and path == "/mcp/agents":
            req = json.loads(body.decode("utf-8"))
            rid = req.get("id")
            params = req.get("params") or {}
            tool = params.get("name")
            args = params.get("arguments") or {}
            self.mcp_calls.append({"tool": tool, "arguments": args})
            reply = self._dispatch_mcp(rid, tool, args)
            if self.sse_mcp:
                payload = (f"event: message\ndata: {json.dumps(reply)}\n\n").encode("utf-8")
                self._send_http(conn, 200, "text/event-stream", payload)
            else:
                self._send_http(conn, 200, "application/json", json.dumps(reply).encode("utf-8"))
            return
        self._send_http(conn, 404, "application/json", b'{"error":"not found"}')

    def _find_agent(self, aid: str) -> Optional[Dict[str, Any]]:
        for a in self.agents:
            if a.get("id") == aid:
                return a
        return None

    def _dispatch_mcp(self, rid: Any, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if tool == "list_pending_permissions":
            return {"jsonrpc": "2.0", "id": rid, "result": {"content": [], "structuredContent": {"permissions": list(self.permissions)}}}
        if tool == "respond_to_permission":
            self.allowed_requests.append((args.get("agentId"), args.get("requestId"), args.get("response")))
            return {"jsonrpc": "2.0", "id": rid, "result": {"content": [], "structuredContent": {"success": True}}}
        if tool == "get_agent_status":
            a = self._find_agent(str(args.get("agentId") or ""))
            if a is None:
                return {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {"isError": True, "content": [{"type": "text", "text": f"Agent {args.get('agentId')} not found"}]},
                }
            return {"jsonrpc": "2.0", "id": rid, "result": {"content": [], "structuredContent": {"status": a.get("status"), "snapshot": a}}}
        if tool == "list_agents":
            inc_arch = bool(args.get("includeArchived", False))
            out = [a for a in self.agents if inc_arch or not a.get("archivedAt")]
            return {"jsonrpc": "2.0", "id": rid, "result": {"content": [], "structuredContent": {"agents": out[: int(args.get("limit") or 50)]}}}
        if tool == "list_workspaces":
            return {"jsonrpc": "2.0", "id": rid, "result": {"content": [], "structuredContent": {"workspaces": list(self.workspaces)}}}
        if tool == "list_providers":
            return {"jsonrpc": "2.0", "id": rid, "result": {"content": [], "structuredContent": {"providers": list(self.providers)}}}
        if tool == "list_models":
            prov = str(args.get("provider") or "")
            return {"jsonrpc": "2.0", "id": rid, "result": {"content": [], "structuredContent": {"models": list(self.models.get(prov, []))}}}
        if tool == "list_schedules":
            return {"jsonrpc": "2.0", "id": rid, "result": {"content": [], "structuredContent": {"schedules": list(self.schedules)}}}
        if tool == "update_agent":
            aid = str(args.get("agentId") or "")
            a = self._find_agent(aid)
            if a is None:
                return {"jsonrpc": "2.0", "id": rid, "result": {"isError": True, "content": [{"type": "text", "text": "Agent not found"}]}}
            lbl = dict(a.get("labels") or {})
            lbl.update(args.get("labels") or {})
            a["labels"] = lbl
            self.updated_labels.append((aid, dict(args.get("labels") or {})))
            return {"jsonrpc": "2.0", "id": rid, "result": {"content": [], "structuredContent": {"success": True}}}
        if tool == "archive_agent":
            aid = str(args.get("agentId") or "")
            a = self._find_agent(aid)
            if a is None:
                return {"jsonrpc": "2.0", "id": rid, "result": {"isError": True, "content": [{"type": "text", "text": "Agent not found"}]}}
            a["archivedAt"] = "2026-11-24T12:00:00Z"
            self.archived_ids.append(aid)
            return {"jsonrpc": "2.0", "id": rid, "result": {"content": [], "structuredContent": {"success": True}}}
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"unknown tool {tool}"}}

    def _ws_send_json(self, conn: socket.socket, obj: Dict[str, Any]) -> None:
        raw = json.dumps(obj).encode("utf-8")
        if self.send_ping_before_reply:
            _ws_send_frame(conn, 0x9, b"hi")
        if self.fragment_ws and len(raw) > 10:
            mid = len(raw) // 2
            _ws_send_frame(conn, 0x1, raw[:mid], fin=False)
            _ws_send_frame(conn, 0x0, raw[mid:], fin=True)
        else:
            _ws_send_frame(conn, 0x1, raw, fin=True)

    def _handle_ws(self, conn: socket.socket, headers: Dict[str, str], buf: bytearray) -> None:
        key = headers.get("sec-websocket-key", "")
        accept = base64.b64encode(hashlib.sha1((key + pc.WS_MAGIC_GUID).encode("ascii")).digest()).decode("ascii")
        conn.sendall(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode("ascii")
        )
        while True:
            try:
                op, payload = _ws_recv_frame(conn, buf)
            except EOFError:
                return
            if op == 0x8:
                return
            if op == 0xA:
                continue
            msg = json.loads(payload.decode("utf-8"))
            if msg.get("type") == "hello":
                self.hellos.append(msg)
                auth = msg.get("auth") or {}
                if self.require_password and auth != {"kind": "password", "password": self.require_password}:
                    self._ws_send_json(conn, {"type": "hello_rejected", "reason": "bad_password"})
                    return
                if self.require_local_cred and auth != {"kind": "localCredential", "token": self.require_local_cred}:
                    self._ws_send_json(conn, {"type": "hello_rejected", "reason": "bad_local_cred"})
                    return
                self._ws_send_json(
                    conn,
                    {
                        "type": "session",
                        "message": {
                            "type": "status",
                            "payload": {"status": "server_info", "protocolVersion": 1, "version": "0.17.3"},
                        },
                    },
                )
                continue
            if msg.get("type") != "session":
                continue
            inner = msg.get("message") or {}
            self.ws_requests.append(inner)
            mtype = inner.get("type")
            rid = inner.get("requestId")
            if mtype == "fetch_agents_request":
                flt = inner.get("filter") or {}
                inc_arch = bool(flt.get("includeArchived", False))
                inc_bg = bool(flt.get("includeBackground", False))
                lbl = flt.get("labels") or {}
                matched = []
                for a in self.agents:
                    if not inc_arch and a.get("archivedAt"):
                        continue
                    if not inc_bg and a.get("background"):
                        continue
                    if lbl:
                        albl = a.get("labels") or {}
                        if not all(albl.get(k) == v for k, v in lbl.items()):
                            continue
                    matched.append({"agent": a, "project": None})
                page = inner.get("page") or {}
                cursor = int(page.get("cursor") or 0)
                limit = min(int(page.get("limit") or self.page_size), self.page_size)
                chunk = matched[cursor : cursor + limit]
                nxt = str(cursor + limit) if (cursor + limit) < len(matched) else None
                self._ws_send_json(
                    conn,
                    {
                        "type": "session",
                        "message": {
                            "type": "fetch_agents_response",
                            "payload": {
                                "requestId": rid,
                                "entries": chunk,
                                "pageInfo": {"nextCursor": nxt},
                            },
                        },
                    },
                )
            elif mtype == "fetch_agent_request":
                a = self._find_agent(str(inner.get("agentId") or ""))
                if a is None:
                    self._ws_send_json(
                        conn,
                        {
                            "type": "session",
                            "message": {
                                "type": "rpc_error",
                                "payload": {"requestId": rid, "code": "NOT_FOUND", "error": "Agent not found"},
                            },
                        },
                    )
                else:
                    self._ws_send_json(
                        conn,
                        {
                            "type": "session",
                            "message": {
                                "type": "fetch_agent_response",
                                "payload": {"requestId": rid, "agent": a},
                            },
                        },
                    )
            elif mtype == "fetch_workspaces_request":
                self._ws_send_json(
                    conn,
                    {
                        "type": "session",
                        "message": {
                            "type": "fetch_workspaces_response",
                            "payload": {"requestId": rid, "entries": list(self.workspaces)},
                        },
                    },
                )
            elif mtype == "usage.list_reports.request":
                for rep in self.usage_reports:
                    self._ws_send_json(
                        conn,
                        {
                            "type": "session",
                            "message": {
                                "type": "usage.list_reports.update",
                                "payload": {"requestId": rid, "report": rep},
                            },
                        },
                    )
                self._ws_send_json(
                    conn,
                    {
                        "type": "session",
                        "message": {
                            "type": "usage.list_reports.response",
                            "payload": {"requestId": rid},
                        },
                    },
                )


def _sample_agent(
    aid: str,
    *,
    title: str = "worker sample",
    provider: str = "claude",
    model: str = "claude-sonnet-5-5",
    status: str = "idle",
    cwd: str = "/tmp/wt",
    archived_at: Optional[str] = None,
    labels: Optional[Dict[str, str]] = None,
    pending: Optional[List[Dict[str, Any]]] = None,
    updated_at: str = "2026-11-24T12:00:00Z",
    background: bool = False,
) -> Dict[str, Any]:
    return {
        "id": aid,
        "shortId": aid[:7],
        "title": title,
        "provider": provider,
        "model": model,
        "status": status,
        "cwd": cwd,
        "createdAt": "2026-11-24T10:00:00Z",
        "updatedAt": updated_at,
        "archivedAt": archived_at,
        "background": background,
        "labels": dict(labels or {}),
        "pendingPermissions": list(pending or []),
        "effectiveThinkingOptionId": "high",
        "currentModeId": "full-access",
    }


# ---------------------------------------------------------------- URL validation, discovery, auth


@pytest.mark.parametrize(
    "bad_url",
    [
        "",
        "https://127.0.0.1:7263/mcp/agents",
        "http://192.168.1.10:7263/mcp/agents",
        "http://example.com:7263/mcp/agents",
        "http://user:pass@127.0.0.1:7263/mcp/agents",
        "http://127.0.0.1:7263/mcp/agents?callerAgentId=x",
        "http://127.0.0.1:7263/other",
        "http://127.0.0.1/mcp/agents",
        "ws://10.0.0.1:7263/ws",
        "unix://relative/path.sock",
    ],
)
def test_parse_daemon_url_rejects_non_loopback_and_malformed(bad_url: str) -> None:
    with pytest.raises(pc.DaemonError):
        pc.parse_daemon_url(bad_url)


def test_parse_daemon_url_accepts_loopback_and_unix() -> None:
    t1 = pc.parse_daemon_url("http://127.0.0.1:7263")
    assert (t1.kind, t1.host, t1.port, t1.mcp_only, t1.ws_only) == ("tcp", "127.0.0.1", 7263, False, False)
    t2 = pc.parse_daemon_url("http://[::1]:7263/mcp/agents")
    assert (t2.host, t2.port, t2.mcp_only) == ("::1", 7263, True)
    t3 = pc.parse_daemon_url("ws://localhost:7263/ws")
    assert (t3.host, t3.port, t3.ws_only) == ("localhost", 7263, True)
    t4 = pc.parse_daemon_url("unix:///tmp/paseo.sock")
    assert (t4.kind, t4.socket_path) == ("unix", "/tmp/paseo.sock")


def test_discover_daemon_target_from_config_and_env(tmp_path: Path) -> None:
    paseo_home = tmp_path / ".paseo"
    paseo_home.mkdir()
    (paseo_home / "config.json").write_text(json.dumps({"daemon": {"listen": "127.0.0.1:8123"}}))
    t = pc.discover_daemon_target(paseo_home=paseo_home, env={})
    assert (t.host, t.port) == ("127.0.0.1", 8123)
    # Explicit ADE_PASEO_URL overrides config.json
    t_env = pc.discover_daemon_target(paseo_home=paseo_home, env={"ADE_PASEO_URL": "unix:///tmp/override.sock"})
    assert (t_env.kind, t_env.socket_path) == ("unix", "/tmp/override.sock")


def test_read_local_auth_ignores_symlinks_and_never_leaks_secret(tmp_path: Path) -> None:
    paseo_home = tmp_path / ".paseo"
    paseo_home.mkdir()
    real = tmp_path / "secret.txt"
    real.write_text("super-secret-token-xyz")
    (paseo_home / "local-credential").symlink_to(real)
    assert pc.read_local_auth(paseo_home=paseo_home, env={}) is None
    (paseo_home / "local-credential").unlink()
    (paseo_home / "local-credential").write_text("local-token-abc\n")
    assert pc.read_local_auth(paseo_home=paseo_home, env={}) == ("localCredential", "local-token-abc")
    assert pc.read_local_auth(paseo_home=paseo_home, env={"PASEO_PASSWORD": "pw-123"}) == ("password", "pw-123")


def test_transport_mode_defaults_daemon_and_honors_explicit_overrides() -> None:
    assert pc.transport_mode(env={}) == "daemon"
    # Paseo exports PASEO_CLI into every agent's environment; without cli_env_vars it must keep daemon mode.
    assert pc.transport_mode(env={"PASEO_CLI": "/Applications/Paseo.app/Contents/Resources/bin/paseo"}) == "daemon"
    assert pc.transport_mode(env={"ADE_PASEO_TRANSPORT": "cli"}) == "cli"
    assert pc.transport_mode(cli_override="/abs/fake/paseo", env={}) == "cli"
    assert pc.transport_mode(cli_override="paseo", env={}) == "daemon"
    assert pc.transport_mode(cli_env_vars=("PASEO_CLI",), env={"PASEO_CLI": "/abs/fake/paseo"}) == "cli"
    # ADE_PASEO_URL always wins over CLI overrides
    assert pc.transport_mode(cli_override="/abs/fake/paseo", env={"ADE_PASEO_URL": "unix:///tmp/p.sock"}) == "daemon"


# ---------------------------------------------------------------- HTTP/MCP + WS over private AF_UNIX


def test_paseo_client_full_mcp_and_ws_flow_with_pagination_and_fragmentation(tmp_path: Path) -> None:
    agents = [
        _sample_agent(f"00000000-0000-4000-8000-{i:012d}", title=f"agent-{i}", provider="pi", model="openai/gpt-6.1-sol",
                      labels={"ade.lead": "11111111-1111-4111-8111-111111111111"} if i % 2 == 0 else {})
        for i in range(5)
    ]
    agents.append(_sample_agent("00000000-0000-4000-8000-000000000099", archived_at="2026-11-23T00:00:00Z"))
    perms = [
        {
            "agentId": agents[0]["id"],
            "status": "running",
            "request": {"id": "req-1", "name": "Bash", "kind": "tool", "provider": "claude", "description": "run"},
        }
    ]
    sock = tmp_path / "paseo.sock"
    with FakeUnixPaseoDaemon(
        sock,
        agents=agents,
        permissions=perms,
        workspaces=[{"workspaceId": "wks_1", "title": "LEAD ade"}],
        providers=[{"id": "claude", "enabled": True}],
        models={"claude": [{"id": "claude-sonnet-5-5"}]},
        schedules=[{"id": "sch1", "name": "daily"}],
        usage_reports=[{"id": "anthropic:sub", "sourceId": "claude"}],
        page_size=2,
        fragment_ws=True,
        send_ping_before_reply=True,
    ) as daemon:
        client = pc.PaseoClient(url=daemon.url, timeout=5.0)
        assert client.health() == {"status": "ok"}
        assert client.status()["version"] == "0.17.3"
        # Paginated across 3 pages (page_size=2 for 5 live agents)
        live = client.list_agents(include_background=True, include_archived=False, cli_rows=True)
        assert len(live) == 5
        assert live[0]["provider"] == "pi/openai/gpt-6.1-sol"
        # Hello advertised snake_case all_providers & hello_rejection
        assert daemon.hellos and daemon.hellos[0]["capabilities"]["all_providers"] is True
        assert daemon.hellos[0]["capabilities"]["hello_rejection"] is True
        # Label filter
        labelled = client.list_agents(
            include_background=True,
            include_archived=True,
            labels={"ade.lead": "11111111-1111-4111-8111-111111111111"},
            cli_rows=True,
        )
        assert len(labelled) == 3
        # Inspect + NotFound
        insp = client.inspect_agent(agents[0]["id"])
        assert insp["Id"] == agents[0]["id"] and insp["Archived"] is False and insp["Provider"] == "pi"
        with pytest.raises(pc.AgentNotFoundError):
            client.inspect_agent("99999999-9999-4999-8999-999999999999")
        # Permissions + allow
        cli_perms = client.list_pending_permissions(cli_rows=True)
        assert len(cli_perms) == 1 and cli_perms[0]["kind"] == "tool"
        client.respond_to_permission(agents[0]["id"], "req-1", "allow")
        assert daemon.allowed_requests == [(agents[0]["id"], "req-1", {"behavior": "allow"})]
        # Workspaces, providers, models, schedules, usage
        assert len(client.list_workspaces()) == 1
        assert client.list_providers()[0]["id"] == "claude"
        assert client.list_models("claude")[0]["id"] == "claude-sonnet-5-5"
        assert client.list_schedules()[0]["id"] == "sch1"
        assert client.list_usage_reports()[0]["id"] == "anthropic:sub"


def test_paseo_client_auth_token_passed_without_leaking_in_error(tmp_path: Path) -> None:
    sock = tmp_path / "paseo.sock"
    paseo_home = tmp_path / ".paseo"
    paseo_home.mkdir()
    (paseo_home / "local-credential").write_text("secret-local-cred-999\n")
    with FakeUnixPaseoDaemon(sock, agents=[_sample_agent("00000000-0000-4000-8000-000000000001")],
                             require_local_cred="secret-local-cred-999") as daemon:
        client = pc.PaseoClient(url=daemon.url, paseo_home=paseo_home, env={})
        assert len(client.list_agents()) == 1
        # Wrong credential -> rejected, token never appears in exception message
        (paseo_home / "local-credential").write_text("wrong-secret-cred-777\n")
        bad = pc.PaseoClient(url=daemon.url, paseo_home=paseo_home, env={})
        with pytest.raises(pc.DaemonError) as exc_info:
            bad.list_agents()
        assert "wrong-secret-cred-777" not in str(exc_info.value)


def test_paseo_client_fails_closed_on_unreachable_or_malformed(tmp_path: Path) -> None:
    missing = f"unix://{tmp_path / 'does-not-exist.sock'}"
    client = pc.PaseoClient(url=missing, timeout=1.0)
    with pytest.raises(pc.DaemonError):
        client.list_agents()
    with pytest.raises(pc.DaemonError):
        client.inspect_agent("00000000-0000-4000-8000-000000000001")

    sock = tmp_path / "bad.sock"
    with FakeUnixPaseoDaemon(sock, bad_json_http=True) as daemon:
        bad = pc.PaseoClient(url=daemon.url, timeout=2.0)
        with pytest.raises(pc.DaemonError):
            bad.list_pending_permissions()


# ---------------------------------------------------------------- SnapshotCache atomic + O_NOFOLLOW


def test_snapshot_cache_atomic_permissions_ttl_and_nofollow(tmp_path: Path) -> None:
    cdir = tmp_path / "cache"
    cache = pc.SnapshotCache(cdir, ttl_s=10.0)
    cache.put("k1", [{"id": "a1"}], now=1000.0)
    assert stat.S_IMODE(cdir.stat().st_mode) == 0o700
    snap_file = cache._path("k1")
    assert stat.S_IMODE(snap_file.stat().st_mode) == 0o600
    assert cache.get("k1", now=1005.0) == [{"id": "a1"}]
    assert cache.get("k1", now=1011.0) is None
    # Symlink must be refused via O_NOFOLLOW
    target = tmp_path / "evil.json"
    target.write_text(snap_file.read_text())
    snap_file.unlink()
    snap_file.symlink_to(target)
    assert cache.get("k1", now=1005.0) is None


# ---------------------------------------------------------------- End-to-end zero-subprocess poller verification


def test_converted_pollers_run_zero_subprocess_against_unix_daemon(tmp_path: Path, monkeypatch) -> None:
    lead = "11111111-1111-4111-8111-111111111111"
    worker = "22222222-2222-4222-8222-222222222222"
    retired = "33333333-3333-4333-8333-333333333333"
    agents = [
        _sample_agent(lead, title="LEAD ade", provider="claude", model="claude-sonnet-5-5", status="idle", cwd=str(tmp_path)),
        _sample_agent(
            worker,
            title="worker slice",
            provider="pi",
            model="openai/gpt-6.1-sol",
            status="running",
            cwd=str(tmp_path),
            labels={"ade.lead": lead, "paseo.parent-agent-id": lead},
            updated_at="2026-11-24T12:00:00Z",
        ),
        _sample_agent(
            retired,
            title="RETIRED old",
            provider="claude",
            model="claude-sonnet-5-5",
            status="idle",
            cwd=str(tmp_path),
            updated_at="2020-01-01T00:00:00Z",
        ),
    ]
    perms = [
        {
            "agentId": worker,
            "status": "running",
            "request": {"id": "perm-1", "name": "Bash", "kind": "tool", "provider": "pi", "description": "ls"},
        }
    ]
    sock = tmp_path / "paseo.sock"
    with FakeUnixPaseoDaemon(sock, agents=agents, permissions=perms) as daemon:
        # 1. ade-auto-permit: approves worker's tool prompt with ZERO paseo CLI spawns
        env_base = {
            k: v for k, v in os.environ.items()
            if k not in ("PASEO_CLI", "ADE_PASEO_BIN", "ADE_PASEO_TRANSPORT", "PASEO_AGENT_ID")
        }
        env_base["ADE_PASEO_URL"] = daemon.url
        log_path = tmp_path / "auto-permit.jsonl"
        r = subprocess.run(
            [sys.executable, str(BIN / "ade-auto-permit"), "--lead", lead, "--log", str(log_path)],
            env=env_base,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert r.returncode == 0, r.stderr
        assert daemon.allowed_requests == [(worker, "perm-1", {"behavior": "allow"})]

        # 2. ade-pin-interactive --check: lists non-worker lead with ZERO paseo CLI spawns
        r2 = subprocess.run(
            [sys.executable, "-I", str(BIN / "ade-pin-interactive"), "--check"],
            env=env_base,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert r2.returncode == 0, r2.stderr
        assert lead in r2.stdout and worker not in r2.stdout and retired not in r2.stdout

        # 3. ade-archive-retired --apply: archives retired tab and verifies readback via daemon API
        r3 = subprocess.run(
            [
                sys.executable,
                "-I",
                str(BIN / "ade-archive-retired"),
                "--apply",
                "--json",
                "--state-dir",
                str(tmp_path / "arch-state"),
                "--watcher-file",
                str(tmp_path / "no-watcher.json"),
                "--exclude-file",
                str(tmp_path / "no-excludes"),
            ],
            env=env_base,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert r3.returncode == 0, r3.stderr
        out3 = json.loads(r3.stdout)
        assert [x["id"] for x in out3["archived"]] == [retired]
        assert daemon.archived_ids == [retired]

        # 4. ade_send_guard: inspects live lead via daemon API without spawning paseo CLI
        import ade_send_guard as sg
        monkeypatch.setenv("ADE_PASEO_URL", daemon.url)
        monkeypatch.delenv("ADE_PASEO_TRANSPORT", raising=False)
        d = sg.guard(lead, env={"ADE_PASEO_URL": daemon.url})
        assert d.action == sg.PASS

        # 5. ade_subagent_stalls.parent_idle: checks idle lead via daemon API without spawning paseo CLI
        import ade_subagent_stalls as ss
        cfg = ss.make_config(tmp_path, paseo=None, paseo_url=daemon.url, use_daemon=True)
        warnings: List[str] = []
        assert ss.parent_idle(cfg, lead, warnings) is True
        assert ss.parent_idle(cfg, worker, warnings) is False
        assert not warnings

        # 6. load-watch count_agents & paseo_agents via daemon API (zero subprocess.run)
        loader = importlib.machinery.SourceFileLoader("lw_mod", str(BIN / "load-watch"))
        spec = importlib.util.spec_from_loader("lw_mod", loader)
        lw = importlib.util.module_from_spec(spec)
        loader.exec_module(lw)
        monkeypatch.delenv("PASEO_CLI", raising=False)
        monkeypatch.setattr(lw.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("subprocess forbidden")))
        assert lw.count_agents() == 1  # worker is running
        lw_agents, why = lw.paseo_agents()
        assert why is None and len(lw_agents) == 2  # retired was archived above!

        # 7. ade-net-resume Scanner: quiet tick runs zero paseo CLI subprocesses
        nr_mod = importlib.machinery.SourceFileLoader("nr_mod", str(BIN / "ade-net-resume"))
        nr_spec = importlib.util.spec_from_loader("nr_mod", nr_mod)
        nr = importlib.util.module_from_spec(nr_spec)
        nr_mod.exec_module(nr)
        scanner = nr.Scanner(lead, tmp_path / "nr-state", apply=False, daemon_url=daemon.url)
        monkeypatch.setattr(nr.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("subprocess forbidden")))
        assert scanner.scan() == 0

        # 8. ade-pi-stuck: lists Pi agents via daemon API with zero paseo CLI subprocesses
        pi_loader = importlib.machinery.SourceFileLoader("pi_mod", str(BIN / "ade-pi-stuck"))
        pi_spec = importlib.util.spec_from_loader("pi_mod", pi_loader)
        pi_mod = importlib.util.module_from_spec(pi_spec)
        pi_loader.exec_module(pi_mod)
        rows = pi_mod.list_agents_rows()
        assert any(row["id"] == worker and row["provider"] == "pi/openai/gpt-6.1-sol" for row in rows)
