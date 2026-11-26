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
import time
import urllib.request
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
                if self.require_local_cred and auth == {"kind": "localCredential", "token": self.require_local_cred}:
                    pass
                elif self.require_password and auth == {"kind": "password", "password": self.require_password}:
                    pass
                elif self.require_local_cred or self.require_password:
                    self._ws_send_json(conn, {"type": "hello_rejected", "reason": "bad_auth"})
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
            elif mtype == "workspace.pin.set.request":
                wid = inner["workspaceId"]
                accepted = any(w.get("id") == wid for w in self.workspaces)
                self._ws_send_json(
                    conn,
                    {
                        "type": "session",
                        "message": {
                            "type": "workspace.pin.set.response",
                            "payload": {
                                "requestId": rid, "workspaceId": wid, "accepted": accepted,
                                "pinnedAt": "2026-11-24T00:00:00Z" if accepted and inner["pinned"] else None,
                                "error": None if accepted else "Workspace not found",
                            },
                        },
                    },
                )
            elif mtype == "agent_permission_response":
                aid = str(inner.get("agentId") or "")
                response = inner.get("response") or {}
                self.allowed_requests.append((aid, rid, response))
                self._ws_send_json(
                    conn,
                    {
                        "type": "session",
                        "message": {
                            "type": "agent_permission_resolved",
                            "payload": {"agentId": aid, "requestId": rid, "resolution": response},
                        },
                    },
                )
            elif mtype == "update_agent_request":
                aid = str(inner.get("agentId") or "")
                a = self._find_agent(aid)
                if a is None:
                    self._ws_send_json(
                        conn,
                        {
                            "type": "session",
                            "message": {
                                "type": "update_agent_response",
                                "payload": {"requestId": rid, "agentId": aid, "accepted": False, "error": "Agent not found"},
                            },
                        },
                    )
                else:
                    lbl = dict(a.get("labels") or {})
                    lbl.update(inner.get("labels") or {})
                    a["labels"] = lbl
                    self.updated_labels.append((aid, dict(inner.get("labels") or {})))
                    self._ws_send_json(
                        conn,
                        {
                            "type": "session",
                            "message": {
                                "type": "update_agent_response",
                                "payload": {"requestId": rid, "agentId": aid, "accepted": True, "error": None},
                            },
                        },
                    )
            elif mtype == "archive_agent_request":
                aid = str(inner.get("agentId") or "")
                a = self._find_agent(aid)
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
                    a["archivedAt"] = "2026-11-24T12:00:00Z"
                    self.archived_ids.append(aid)
                    self._ws_send_json(
                        conn,
                        {
                            "type": "session",
                            "message": {
                                "type": "agent_archived",
                                "payload": {"requestId": rid, "agentId": aid, "archivedAt": a["archivedAt"]},
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
            labels={"ade.retired": "1"},
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


# ---------------------------------------------------------------- Round 2 adversary regression tests


def test_high1_loopback_opener_blocks_redirects_and_restricts_handlers(monkeypatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    opener = pc._build_loopback_opener()
    handler_types = {type(h).__name__ for h in opener.handlers}
    assert handler_types == {
        "HTTPHandler",
        "_NoRedirectHandler",
        "HTTPErrorProcessor",
        "HTTPDefaultErrorHandler",
    }

    for code in (302, 307):
        followed: List[str] = []

        class _RedirectingHTTPHandler(urllib.request.BaseHandler):
            def http_open(self, req):
                followed.append(req.full_url)
                import io
                from http.client import HTTPMessage

                hdrs = HTTPMessage()
                hdrs["Location"] = "http://evil.example.com/steal"
                resp = urllib.request.addinfourl(io.BytesIO(b""), hdrs, req.full_url, code)
                resp.msg = "Redirect"
                return resp

        def _fake_opener():
            op = urllib.request.OpenerDirector()
            for h in (
                urllib.request.ProxyHandler({}),
                _RedirectingHTTPHandler(),
                pc._NoRedirectHandler(),
                urllib.request.HTTPErrorProcessor(),
                urllib.request.HTTPDefaultErrorHandler(),
            ):
                op.add_handler(h)
            return op

        monkeypatch.setattr(pc, "_build_loopback_opener", _fake_opener)
        with pytest.raises(pc.DaemonError, match=f"redirected \\(HTTP {code}\\)"):
            pc.urllib_opener("http://127.0.0.1:7263/mcp/agents", b"{}", {}, 2.0)
        with pytest.raises(pc.DaemonError, match=f"redirected \\(HTTP {code}\\)"):
            pc.urllib_get("http://127.0.0.1:7263/api/health", {}, 2.0)
        assert all("evil.example.com" not in u for u in followed)


def test_high2_local_credential_routes_all_ops_over_ws_when_mcp_enforces_password(tmp_path: Path) -> None:
    a1 = "11111111-1111-4111-8111-111111111111"
    a2 = "22222222-2222-4222-8222-222222222222"
    perm = {"id": "perm-ws-1", "name": "Bash", "kind": "tool", "provider": "claude", "description": "run"}
    agents = [
        _sample_agent(a1, title="LEAD ws", status="idle", pending=[perm]),
        _sample_agent(a2, title="RETIRED ws", status="idle"),
    ]
    paseo_home = tmp_path / ".paseo"
    paseo_home.mkdir()
    (paseo_home / "local-credential").write_text("local-only-token\n")
    sock = tmp_path / "paseo.sock"
    with FakeUnixPaseoDaemon(
        sock,
        agents=agents,
        workspaces=[{"workspaceId": "wks_ws", "title": "LEAD ws"}],
        require_password="mcp-only-password",
        require_local_cred="local-only-token",
    ) as daemon:
        # No PASEO_PASSWORD in env -> only localCredential is available (MCP returns HTTP 401 -> WS fallback).
        client = pc.PaseoClient(url=daemon.url, paseo_home=paseo_home, env={}, timeout=5.0)
        insp = client.inspect_agent(a1)
        assert insp["Id"] == a1 and insp["Name"] == "LEAD ws"
        assert client._prefer_ws() is True  # memoized after first MCP 401 -> subsequent calls skip MCP
        perms = client.list_pending_permissions(cli_rows=True)
        assert len(perms) == 1 and perms[0]["id"] == "perm-ws-1" and perms[0]["agentId"] == a1
        client.respond_to_permission(a1, "perm-ws-1", "allow")
        assert daemon.allowed_requests == [(a1, "perm-ws-1", {"behavior": "allow"})]
        ws_list = client.list_workspaces()
        assert len(ws_list) == 1 and ws_list[0]["workspaceId"] == "wks_ws"
        client.update_agent_labels(a1, {"ade.interactive": "1"})
        assert daemon.updated_labels == [(a1, {"ade.interactive": "1"})]
        client.archive_agent(a2)
        assert daemon.archived_ids == [a2]
        # Zero MCP calls succeeded (rejected 401 before dispatch); all 6 ops completed over authenticated WS.
        assert daemon.mcp_calls == []
        assert daemon.hellos and daemon.hellos[0]["capabilities"]["owned_subscriptions"] is True


def test_medium1_unix_socket_rejects_traversal_symlinks_and_non_sockets(tmp_path: Path) -> None:
    with pytest.raises(pc.DaemonError):
        pc.parse_daemon_url("unix:///tmp/../etc/passwd")
    with pytest.raises(pc.DaemonError):
        pc._parse_listen_string("unix:///tmp/../paseo.sock")
    with pytest.raises(pc.DaemonError):
        pc._parse_listen_string("/tmp/../paseo.sock")

    # Regular file is not a socket
    plain = tmp_path / "not-a-sock"
    plain.write_text("hi")
    with pytest.raises(pc.DaemonError, match="not a socket"):
        pc.McpClient(f"unix://{plain}").health()
    with pytest.raises(pc.DaemonError, match="not a socket"):
        pc.WsClient(f"unix://{plain}").connect()

    # Symlink pointing to a real Unix socket must be refused
    sock = tmp_path / "real.sock"
    with FakeUnixPaseoDaemon(sock) as daemon:
        link = tmp_path / "link.sock"
        link.symlink_to(daemon.sock_path)
        with pytest.raises(pc.DaemonError, match="not a socket"):
            pc.McpClient(f"unix://{link}").health()
        with pytest.raises(pc.DaemonError, match="not a socket"):
            pc.WsClient(f"unix://{link}").connect()


def _run_raw_unix_server(handler: Callable[[socket.socket], None]):
    d = Path(tempfile.mkdtemp(prefix="ade-ws-", dir="/tmp"))
    os.chmod(str(d), 0o700)
    sp = d / "raw.sock"
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(sp))
    os.chmod(str(sp), 0o600)
    srv.listen(4)
    srv.settimeout(3.0)

    def serve():
        try:
            conn, _ = srv.accept()
            with conn:
                handler(conn)
        except OSError:
            pass
        finally:
            srv.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    return sp, d, t


def _raw_ws_upgrade(conn: socket.socket) -> None:
    buf = bytearray()
    while b"\r\n\r\n" not in buf:
        c = conn.recv(4096)
        if not c:
            return
        buf.extend(c)
    head = bytes(buf).decode("iso-8859-1", "replace")
    key = ""
    for line in head.split("\r\n")[1:]:
        if line.lower().startswith("sec-websocket-key:"):
            key = line.split(":", 1)[1].strip()
    accept = base64.b64encode(hashlib.sha1((key + pc.WS_MAGIC_GUID).encode("ascii")).digest()).decode("ascii")
    conn.sendall(
        (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        ).encode("ascii")
    )


def test_medium2_ws_handshake_deadline_status_line_and_rfc6455_validation() -> None:
    # 1. Slow/stalled handshake hits overall monotonic deadline
    def slow_handshake(conn: socket.socket) -> None:
        conn.recv(4096)
        conn.sendall(b"HTTP/1.1 101 ")
        time.sleep(0.5)

    sp, d, t = _run_raw_unix_server(slow_handshake)
    try:
        ws = pc._StdlibWebSocket(pc.DaemonTarget(kind="unix", socket_path=str(sp)), timeout=0.15)
        t0 = time.monotonic()
        with pytest.raises(pc.DaemonError, match="timed out"):
            ws.connect()
        assert time.monotonic() - t0 < 0.6
    finally:
        t.join(timeout=2.0)
        sp.unlink(missing_ok=True)
        d.rmdir()

    # 2. Malformed status line containing " 101 " in reason phrase is rejected
    def spoofed_status(conn: socket.socket) -> None:
        conn.recv(4096)
        conn.sendall(b"HTTP/1.1 200 OK 101 fake\r\nSec-WebSocket-Accept: x\r\n\r\n")

    sp, d, t = _run_raw_unix_server(spoofed_status)
    try:
        ws = pc._StdlibWebSocket(pc.DaemonTarget(kind="unix", socket_path=str(sp)), timeout=1.0)
        with pytest.raises(pc.DaemonError, match="upgrade rejected"):
            ws.connect()
    finally:
        t.join(timeout=2.0)
        sp.unlink(missing_ok=True)
        d.rmdir()

    # 3. RFC 6455 frame violations: fragmented ping, oversized ping, unknown opcode, bad continuation, nested data
    cases = [
        ("invalid WebSocket control frame", lambda c: _ws_send_frame(c, 0x9, b"hi", fin=False)),
        ("invalid WebSocket control frame", lambda c: _ws_send_frame(c, 0x9, b"x" * 126, fin=True)),
        ("unsupported WebSocket opcode", lambda c: _ws_send_frame(c, 0x3, b"bad", fin=True)),
        ("unexpected WebSocket continuation frame", lambda c: _ws_send_frame(c, 0x0, b"{}", fin=True)),
        (
            "unexpected WebSocket data frame",
            lambda c: (_ws_send_frame(c, 0x1, b'{"a":', fin=False), _ws_send_frame(c, 0x1, b"1}", fin=True)),
        ),
    ]
    for pattern, send_bad in cases:
        def _srv(conn: socket.socket, fn=send_bad) -> None:
            _raw_ws_upgrade(conn)
            fn(conn)

        sp, d, t = _run_raw_unix_server(_srv)
        try:
            ws = pc._StdlibWebSocket(pc.DaemonTarget(kind="unix", socket_path=str(sp)), timeout=1.0)
            ws.connect()
            try:
                with pytest.raises(pc.DaemonError, match=pattern):
                    ws.recv_json()
            finally:
                ws.close()
        finally:
            t.join(timeout=2.0)
            sp.unlink(missing_ok=True)
            d.rmdir()


def test_medium3_send_guard_lazy_client_env_isolation_and_paseo_guard_daemon_mode(tmp_path: Path, monkeypatch) -> None:
    import ade_send_guard as sg

    aid = "11111111-1111-4111-8111-111111111111"
    # Invalid ADE_PASEO_URL must NOT raise DaemonError out of guard() (lazy client -> OSError -> fail-open PASS)
    d = sg.guard(aid, env={"ADE_PASEO_URL": "http://example.com:7263"})
    assert d.action == sg.PASS and "could not inspect" in d.reason

    # Explicit caller env={"ADE_PASEO_TRANSPORT": "cli"} must NOT inherit os.environ["ADE_PASEO_URL"]
    monkeypatch.setenv("ADE_PASEO_URL", "http://example.com:7263")
    fn = sg.paseo_inspect(env={"ADE_PASEO_TRANSPORT": "cli"})
    assert fn.__name__ == "inspect"

    # bin/ade-paseo-guard uses daemon mode by default without spawning ADE_REAL_PASEO for inspect
    marker = tmp_path / "real-paseo-ran"
    fake_real = tmp_path / "fake-paseo"
    fake_real.write_text(f"#!/bin/sh\necho \"$@\" >> {marker}\nexit 0\n")
    fake_real.chmod(0o755)
    archived = _sample_agent(aid, title="OLD", archived_at="2026-11-23T00:00:00Z")
    sock = tmp_path / "guard.sock"
    with FakeUnixPaseoDaemon(sock, agents=[archived]) as daemon:
        env = {
            k: v for k, v in os.environ.items()
            if k not in ("ADE_PASEO_TRANSPORT", "PASEO_AGENT_ID", "ADE_ALLOW_ARCHIVED_SEND", "ADE_ALLOW_REPLACED_SEND")
        }
        env["ADE_REAL_PASEO"] = str(fake_real)
        env["ADE_PASEO_URL"] = daemon.url
        env["ADE_SELF_SESSION_STATE"] = str(tmp_path / "self-state")
        env["PASEO_HOME"] = str(tmp_path / "paseo-home")
        p = subprocess.run(
            [sys.executable, "-I", str(BIN / "ade-paseo-guard"), "send", "--no-wait", aid, "hi"],
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert p.returncode == 4, p.stderr
        assert "archived" in p.stderr
        assert not marker.exists()  # real paseo was NEVER spawned for inspect or send


def test_medium4_auto_permit_and_subagent_stalls_handle_invalid_daemon_url(tmp_path: Path) -> None:
    lead = "11111111-1111-4111-8111-111111111111"
    log_path = tmp_path / "ap.jsonl"
    env = {k: v for k, v in os.environ.items() if k not in ("ADE_PASEO_URL", "ADE_PASEO_TRANSPORT")}
    r = subprocess.run(
        [sys.executable, str(BIN / "ade-auto-permit"), "--lead", lead, "--daemon-url", "http://example.com:7263", "--log", str(log_path)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert r.returncode == 1
    assert "Traceback" not in r.stderr
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert any(e.get("reason") == "enumeration-unavailable" for e in entries)

    import ade_subagent_stalls as ss

    cfg = ss.make_config(tmp_path, paseo=None, paseo_url="http://example.com:7263", use_daemon=True)
    w1: List[str] = []
    rs1 = {"down": False}
    assert ss.parent_idle(cfg, lead, w1, rs1) is False
    assert rs1["down"] is True and w1

    w2: List[str] = []
    rs2 = {"down": False}
    assert ss.handed_off_to(cfg, lead, w2, rs2) is None
    assert rs2["down"] is True and w2


def test_medium5_ade_progress_daemon_mode_with_missing_paseo_binary(tmp_path: Path, monkeypatch) -> None:
    prog_loader = importlib.machinery.SourceFileLoader("ade_progress_mod", str(BIN / "ade-progress"))
    prog_spec = importlib.util.spec_from_loader("ade_progress_mod", prog_loader)
    prog = importlib.util.module_from_spec(prog_spec)
    prog_loader.exec_module(prog)

    aid = "11111111-1111-4111-8111-111111111111"
    idle_agent = _sample_agent(aid, title="LEAD prog", status="idle", updated_at="2020-01-01T00:00:00Z")
    sock = tmp_path / "prog.sock"
    with FakeUnixPaseoDaemon(sock, agents=[idle_agent]) as daemon:
        monkeypatch.setenv("ADE_PASEO_URL", daemon.url)
        monkeypatch.delenv("ADE_PASEO_TRANSPORT", raising=False)
        monkeypatch.setenv("ADE_PROGRESS_STATE_DIR", str(tmp_path / "pstate"))
        monkeypatch.setenv("ADE_PROGRESS_PASEO_PROGRESS", str(tmp_path / "no-pp"))
        st = {"events": {}, "pings": [], "wakes": {}, "last_scan": 0}
        decl = {
            "task": "t1",
            "agent_id": aid,
            "paseo_home": prog.paseo_home(),
            "state": "open",
            "pending_count": 1,
            "generation": 1,
            "summary": "test work",
            "idle_after_min": 1,
            "workspace": None,
        }
        info = prog.classify(None, aid, None)
        assert info["kind"] == "idle"
        cand = {"d": decl, "reason": "idle_with_work", "key": prog.event_key(decl, "idle_with_work"), "info": info}
        rep = {"health": [], "withdrawn": 0}
        rec = prog.process(st, cand, None, rep)
        assert rec is not None
        assert rec["wake"] == "unknown"
        assert rec["state"] == "published-local"
        assert any("cannot send wake" in h for h in rep["health"])
        assert prog.wake(None, decl) == "unknown"


def test_low1_2_3_worktree_label_sse_case_oversize_update_confirm_and_archive_guard(tmp_path: Path, monkeypatch) -> None:
    # LOW-1: Worktree prefers labels["paseo.worktree"] over worktreePath
    snap = _sample_agent("11111111-1111-4111-8111-111111111111", labels={"paseo.worktree": "/wt/from-label"})
    snap["worktreePath"] = "/wt/from-field"
    assert pc.snapshot_to_inspect_dict(snap)["Worktree"] == "/wt/from-label"
    snap["labels"] = {}
    assert pc.snapshot_to_inspect_dict(snap)["Worktree"] == "/wt/from-field"

    # LOW-2a: Case-insensitive Content-Type text/event-stream
    sse_body = b'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"content":[],"structuredContent":{"permissions":[]}}}\n\n'
    mcp = pc.McpClient(opener=lambda u, b, h, t: (200, "Text/Event-Stream; charset=utf-8", sse_body))
    assert mcp.list_pending_permissions() == []

    # LOW-2c: McpClient.update_agent checks success is True
    bad_upd = b'{"jsonrpc":"2.0","id":1,"result":{"content":[],"structuredContent":{"success":false}}}'
    mcp_bad = pc.McpClient(opener=lambda u, b, h, t: (200, "application/json", bad_upd))
    with pytest.raises(pc.DaemonError, match="update_agent not confirmed"):
        mcp_bad.update_agent("11111111-1111-4111-8111-111111111111", labels={"a": "b"})

    # LOW-2b: Oversize HTTP body raises DaemonError instead of silent truncation
    sock = tmp_path / "big.sock"
    with FakeUnixPaseoDaemon(sock, agents=[_sample_agent("11111111-1111-4111-8111-111111111111")]) as daemon:
        with monkeypatch.context() as mp:
            mp.setattr(pc, "MAX_HTTP_BYTES", 32)
            with pytest.raises(pc.DaemonError, match="exceeded size limit"):
                pc.McpClient(daemon.url).list_pending_permissions()

    # LOW-3: PaseoClient.archive_agent refuses running or already-archived agents unless force=True
    running_id = "22222222-2222-4222-8222-222222222222"
    archived_id = "33333333-3333-4333-8333-333333333333"
    sock2 = tmp_path / "arch.sock"
    with FakeUnixPaseoDaemon(
        sock2,
        agents=[
            _sample_agent(running_id, status="running"),
            _sample_agent(archived_id, status="idle", archived_at="2026-11-23T00:00:00Z"),
        ],
    ) as daemon:
        client = pc.PaseoClient(url=daemon.url, timeout=5.0)
        with pytest.raises(pc.DaemonError, match="running"):
            client.archive_agent(running_id)
        with pytest.raises(pc.DaemonError, match="already archived"):
            client.archive_agent(archived_id)
        assert daemon.archived_ids == []
        client.archive_agent(running_id, force=True)
        assert daemon.archived_ids == [running_id]


def test_workspace_pin_ws_requests(tmp_path):
    stamp = "2026-11-24T00:00:00Z"
    workspace = {"id": "wks_1", "title": "LEAD ade", "pinnedAt": stamp}
    with FakeUnixPaseoDaemon(tmp_path / "paseo.sock", workspaces=[workspace]) as daemon:
        client = pc.PaseoClient(url=daemon.url)
        assert client.list_workspaces(include_pin_state=True) == [workspace]
        assert client.set_workspace_pinned("wks_1") == stamp
        assert client.set_workspace_pinned("wks_1", False) is None
        with pytest.raises(pc.DaemonError, match="Workspace not found"):
            client.set_workspace_pinned("missing")

    assert daemon.ws_requests[0]["type"] == "fetch_workspaces_request"
    for frame, workspace_id, pinned in zip(
        daemon.ws_requests[1:], ("wks_1", "wks_1", "missing"), (True, False, True), strict=True
    ):
        assert frame == {
            "type": "workspace.pin.set.request",
            "requestId": frame["requestId"],
            "workspaceId": workspace_id,
            "pinned": pinned,
        }
        assert frame["requestId"]


@pytest.mark.parametrize("reply, message", [
    ({"accepted": False}, "rejected"),
    ({"accepted": 1}, "rejected"),
    ({"accepted": True, "workspaceId": "other", "pinnedAt": "stamp"}, "invalid"),
    ({"accepted": True, "workspaceId": "wks_1"}, "invalid"),
    ({"accepted": True, "workspaceId": "wks_1", "pinnedAt": None}, "invalid"),
])
def test_workspace_pin_rejects_invalid_ack(monkeypatch, reply, message):
    ws = pc.WsClient("ws://127.0.0.1:7263/ws")
    monkeypatch.setattr(ws, "rpc", lambda *args, **kwargs: (reply, []))
    with pytest.raises(pc.DaemonError, match=message):
        ws.set_workspace_pinned("wks_1")
