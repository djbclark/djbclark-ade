"""Unit and integration tests for bin/mcp-lazy (docs/mcp-on-demand.md §11.3)."""
from __future__ import annotations

import json
import os
import select
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "mcp-lazy"

# Inline fixture stdio MCP server (no Chrome, no network, no PATH replacement).
FIXTURE_SERVER = r'''#!/usr/bin/env python3
import json
import os
import sys
import time


def read_msg():
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None, "ndjson"
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith(b"content-length:"):
            length = int(stripped.split(b":", 1)[1].strip())
            while True:
                hdr = sys.stdin.buffer.readline()
                if not hdr or hdr in (b"\r\n", b"\n"):
                    break
            body = b""
            while len(body) < length:
                chunk = sys.stdin.buffer.read(length - len(body))
                if not chunk:
                    return None, "content-length"
                body += chunk
            return json.loads(body.decode("utf-8")), "content-length"
        return json.loads(stripped.decode("utf-8")), "ndjson"


def send_msg(obj, framing="ndjson"):
    data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    if framing == "content-length":
        sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii") + data)
    else:
        sys.stdout.buffer.write(data + b"\n")
    sys.stdout.buffer.flush()


def main():
    pid_log = os.environ.get("FIXTURE_PID_LOG")
    if pid_log:
        with open(pid_log, "a", encoding="utf-8") as f:
            f.write(f"{os.getpid()}\n")
            f.flush()
    env_log = os.environ.get("FIXTURE_ENV_LOG")
    if env_log:
        with open(env_log, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "cwd": os.getcwd(), "PATH": os.environ.get("PATH", "")}, f)
            f.flush()

    tools_file = os.environ.get("FIXTURE_TOOLS_FILE")

    def current_tools():
        if tools_file and os.path.exists(tools_file):
            with open(tools_file, encoding="utf-8") as f:
                return json.load(f)
        return [
            {"name": "echo", "description": "Echo back input with child pid", "inputSchema": {"type": "object"}},
            {"name": "slow", "description": "Sleep before replying", "inputSchema": {"type": "object"}},
            {"name": "crash", "description": "Crash mid-call", "inputSchema": {"type": "object"}},
            {"name": "noisy", "description": "Write non-JSON line to stdout before replying", "inputSchema": {"type": "object"}},
            {"name": "ask_client", "description": "Send a server-to-client request", "inputSchema": {"type": "object"}},
        ]

    framing = "ndjson"
    while True:
        msg, seen_framing = read_msg()
        if msg is None:
            break
        if seen_framing == "content-length":
            framing = "content-length"
        method = msg.get("method")
        mid = msg.get("id")
        params = msg.get("params") or {}

        if method is None:
            # Client response to a server-initiated request
            continue
        if "id" not in msg:
            # Notification
            continue

        if method == "initialize":
            send_msg({
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "protocolVersion": params.get("protocolVersion", "2025-11-25"),
                    "capabilities": {
                        "tools": {"listChanged": True},
                        "prompts": {},
                        "resources": {"subscribe": True},
                    },
                    "serverInfo": {"name": "fixture-mcp", "version": "1.0.0"},
                },
            }, framing)
        elif method == "tools/list":
            send_msg({"jsonrpc": "2.0", "id": mid, "result": {"tools": current_tools()}}, framing)
        elif method == "prompts/list":
            send_msg({"jsonrpc": "2.0", "id": mid, "result": {"prompts": [{"name": "hello"}]}}, framing)
        elif method == "resources/list":
            send_msg({"jsonrpc": "2.0", "id": mid, "result": {"resources": [{"uri": "mem://item", "name": "item"}]}}, framing)
        elif method == "resources/templates/list":
            send_msg({"jsonrpc": "2.0", "id": mid, "result": {"resourceTemplates": []}}, framing)
        elif method == "resources/subscribe":
            send_msg({"jsonrpc": "2.0", "id": mid, "result": {"subscribed": params.get("uri")}}, framing)
        elif method == "resources/unsubscribe":
            send_msg({"jsonrpc": "2.0", "id": mid, "result": {"unsubscribed": params.get("uri")}}, framing)
        elif method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            if name == "echo":
                send_msg({
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {"content": [{"type": "text", "text": f"pid={os.getpid()} msg={args.get('msg', '')}"}]},
                }, framing)
            elif name == "slow":
                time.sleep(float(args.get("seconds", 1.5)))
                send_msg({
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {"content": [{"type": "text", "text": f"pid={os.getpid()} slow=done"}]},
                }, framing)
            elif name == "crash":
                os._exit(42)
            elif name == "noisy":
                sys.stderr.write("fixture stderr diagnostic\n")
                sys.stderr.flush()
                sys.stdout.buffer.write(b"NOT VALID JSON FROM CHILD\n")
                sys.stdout.buffer.flush()
                send_msg({
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {"content": [{"type": "text", "text": f"pid={os.getpid()} noisy=ok"}]},
                }, framing)
            elif name == "ask_client":
                # Reply to tool call, then emit a server-initiated request to the client.
                send_msg({
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {"content": [{"type": "text", "text": f"pid={os.getpid()} asked=1"}]},
                }, framing)
                send_msg({
                    "jsonrpc": "2.0",
                    "id": "srv-req-1",
                    "method": "roots/list",
                    "params": {},
                }, framing)
            else:
                send_msg({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "unknown tool"}}, framing)
        else:
            send_msg({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown {method}"}}, framing)


if __name__ == "__main__":
    main()
'''


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_pid_dead(pid: int, timeout: float = 4.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.05)
    return not _pid_alive(pid)


class ProxyClient:
    """Test harness speaking newline-delimited or Content-Length JSON-RPC to bin/mcp-lazy."""

    def __init__(
        self,
        proc: subprocess.Popen[bytes],
        framing: str = "ndjson",
    ) -> None:
        self.proc = proc
        self.framing = framing
        self.raw_stdout_lines: list[bytes] = []

    def send(self, obj: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        if self.framing == "content-length":
            frame = f"Content-Length: {len(data)}\r\n\r\n".encode("ascii") + data
        else:
            frame = data + b"\n"
        self.proc.stdin.write(frame)
        self.proc.stdin.flush()

    def recv(self, timeout: float = 10.0) -> dict[str, Any]:
        assert self.proc.stdout is not None
        fd = self.proc.stdout.fileno()
        deadline = time.monotonic() + timeout
        if self.framing == "content-length":
            hdr = self._readline(fd, deadline)
            assert hdr.lower().startswith(b"content-length:"), f"unexpected header: {hdr!r}"
            length = int(hdr.split(b":", 1)[1].strip())
            while True:
                sep = self._readline(fd, deadline)
                if sep in (b"\r\n", b"\n"):
                    break
            body = self._readexact(fd, length, deadline)
            self.raw_stdout_lines.append(body)
            return json.loads(body.decode("utf-8"))
        line = self._readline(fd, deadline)
        self.raw_stdout_lines.append(line)
        return json.loads(line.decode("utf-8"))

    def _readline(self, fd: int, deadline: float) -> bytes:
        buf = bytearray()
        while True:
            rem = deadline - time.monotonic()
            if rem <= 0:
                raise TimeoutError(f"timed out waiting for stdout line (partial={bytes(buf)!r})")
            ready, _, _ = select.select([fd], [], [], rem)
            if not ready:
                raise TimeoutError(f"timed out waiting for stdout line (partial={bytes(buf)!r})")
            ch = os.read(fd, 1)
            if not ch:
                raise EOFError(f"EOF from mcp-lazy stdout (partial={bytes(buf)!r})")
            buf.extend(ch)
            if ch == b"\n":
                return bytes(buf)

    def _readexact(self, fd: int, n: int, deadline: float) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            rem = deadline - time.monotonic()
            if rem <= 0:
                raise TimeoutError("timed out reading Content-Length body")
            ready, _, _ = select.select([fd], [], [], rem)
            if not ready:
                raise TimeoutError("timed out reading Content-Length body")
            chunk = os.read(fd, n - len(buf))
            if not chunk:
                raise EOFError("EOF while reading Content-Length body")
            buf.extend(chunk)
        return bytes(buf)

    def handshake(self) -> tuple[dict[str, Any], dict[str, Any]]:
        self.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "pytest-client", "version": "1"},
            },
        })
        init_resp = self.recv()
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools_resp = self.recv()
        return init_resp, tools_resp

    def close(self) -> tuple[int, str]:
        if self.proc.stdin is not None:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
        try:
            self.proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5.0)
        stderr = ""
        if self.proc.stderr is not None:
            stderr = self.proc.stderr.read().decode("utf-8", errors="replace")
            self.proc.stderr.close()
        if self.proc.stdout is not None:
            self.proc.stdout.close()
        return self.proc.returncode, stderr


@pytest.fixture
def fixture_env(tmp_path: Path):
    server_script = tmp_path / "fixture_server.py"
    server_script.write_text(FIXTURE_SERVER, encoding="utf-8")
    server_script.chmod(0o755)
    cache_dir = tmp_path / "cache" / "mcp-lazy"
    pid_log = tmp_path / "pids.log"
    env_log = tmp_path / "env.json"
    tools_file = tmp_path / "tools.json"
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir(mode=0o700)
    session_cwd = tmp_path / "session-checkout"
    session_cwd.mkdir()

    def start(
        *,
        server_id: str = "fixture-srv",
        idle: float = 60.0,
        framing: str = "ndjson",
        extra_env: Optional[dict[str, str]] = None,
        cwd: Optional[Path] = None,
    ) -> ProxyClient:
        env = dict(os.environ)
        env["HOME"] = str(fake_home)
        env["FIXTURE_PID_LOG"] = str(pid_log)
        env["FIXTURE_ENV_LOG"] = str(env_log)
        if tools_file.exists():
            env["FIXTURE_TOOLS_FILE"] = str(tools_file)
        if extra_env:
            env.update(extra_env)
        argv = [
            str(SCRIPT),
            "--id", server_id,
            "--idle", str(idle),
            "--cache-dir", str(cache_dir),
            "--",
            sys.executable, str(server_script),
        ]
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd or session_cwd),
            env=env,
        )
        return ProxyClient(proc, framing=framing)

    def read_pids() -> list[int]:
        if not pid_log.exists():
            return []
        return [int(line) for line in pid_log.read_text(encoding="utf-8").splitlines() if line.strip()]

    return {
        "tmp": tmp_path,
        "server": server_script,
        "cache_dir": cache_dir,
        "pid_log": pid_log,
        "env_log": env_log,
        "tools_file": tools_file,
        "home": fake_home,
        "session_cwd": session_cwd,
        "start": start,
        "read_pids": read_pids,
    }


def test_cold_cache_warms_and_reaps_then_warm_handshake_spawns_no_child(fixture_env):
    # Cold start: spawns once to warm cache, writes 0600 cache in 0700 dir, reaps child.
    client1 = fixture_env["start"]()
    try:
        init_r, tools_r = client1.handshake()
        assert init_r["result"]["serverInfo"]["name"] == "fixture-mcp"
        tool_names = [t["name"] for t in tools_r["result"]["tools"]]
        assert "echo" in tool_names

        # Also check prompts/list and resources/list served from freshly warmed cache.
        client1.send({"jsonrpc": "2.0", "id": 3, "method": "prompts/list", "params": {}})
        prompts_r = client1.recv()
        assert prompts_r["result"]["prompts"] == [{"name": "hello"}]

        client1.send({"jsonrpc": "2.0", "id": 4, "method": "resources/list", "params": {}})
        res_r = client1.recv()
        assert res_r["result"]["resources"][0]["uri"] == "mem://item"

        pids = fixture_env["read_pids"]()
        assert len(pids) == 1, f"expected 1 warm-up spawn, got {pids}"
        assert _wait_pid_dead(pids[0]), "warm-up child should be reaped immediately"
    finally:
        rc, _err = client1.close()
        assert rc == 0

    # Verify hardened cache permissions and schema (no command/argv stored).
    cache_dir: Path = fixture_env["cache_dir"]
    cache_file = cache_dir / "fixture-srv.json"
    assert cache_file.is_file() and not cache_file.is_symlink()
    assert stat.S_IMODE(cache_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(cache_file.stat().st_mode) == 0o600
    cached = json.loads(cache_file.read_text(encoding="utf-8"))
    assert "command" not in cached and "argv" not in cached
    assert set(cached.keys()) <= {"version", "initialize", "tools", "prompts", "resources", "resourceTemplates"}

    # Warm start: ZERO child spawned for initialize, notifications/initialized, tools/list, prompts/list, resources/list, ping!
    fixture_env["pid_log"].unlink()
    client2 = fixture_env["start"]()
    try:
        init_r2, tools_r2 = client2.handshake()
        assert init_r2["result"] == init_r["result"]
        assert tools_r2["result"] == tools_r["result"]

        client2.send({"jsonrpc": "2.0", "id": 10, "method": "prompts/list", "params": {}})
        assert client2.recv()["result"]["prompts"] == [{"name": "hello"}]
        client2.send({"jsonrpc": "2.0", "id": 11, "method": "resources/list", "params": {}})
        assert client2.recv()["result"]["resources"][0]["uri"] == "mem://item"
        client2.send({"jsonrpc": "2.0", "id": 12, "method": "ping", "params": {}})
        assert client2.recv()["result"] == {}

        assert fixture_env["read_pids"]() == [], "warm cache must spawn ZERO child processes"
    finally:
        rc, _err = client2.close()
        assert rc == 0


def test_first_tools_call_spawns_child_and_returns_real_result(fixture_env):
    # Warm cache first
    c0 = fixture_env["start"]()
    c0.handshake()
    c0.close()
    fixture_env["pid_log"].unlink()

    client = fixture_env["start"]()
    try:
        client.handshake()
        assert fixture_env["read_pids"]() == []

        client.send({
            "jsonrpc": "2.0",
            "id": 20,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "hello"}},
        })
        resp = client.recv()
        assert resp["id"] == 20
        pids = fixture_env["read_pids"]()
        assert len(pids) == 1
        assert resp["result"]["content"][0]["text"] == f"pid={pids[0]} msg=hello"

        # Second call reuses the same live child.
        client.send({
            "jsonrpc": "2.0",
            "id": 21,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "again"}},
        })
        resp2 = client.recv()
        assert resp2["result"]["content"][0]["text"] == f"pid={pids[0]} msg=again"
        assert len(fixture_env["read_pids"]()) == 1
    finally:
        rc, _err = client.close()
        assert rc == 0


def test_idle_reap_fires_and_never_while_call_in_flight(fixture_env):
    # Warm cache first
    c0 = fixture_env["start"]()
    c0.handshake()
    c0.close()
    fixture_env["pid_log"].unlink()

    client = fixture_env["start"](idle=1.0)
    try:
        client.handshake()
        # Start a slow call (2.0s) exceeding idle=1.0s: must NOT reap while in flight.
        client.send({
            "jsonrpc": "2.0",
            "id": 30,
            "method": "tools/call",
            "params": {"name": "slow", "arguments": {"seconds": 2.0}},
        })
        resp = client.recv(timeout=8.0)
        assert "error" not in resp
        pids = fixture_env["read_pids"]()
        assert len(pids) == 1
        first_pid = pids[0]
        assert f"pid={first_pid} slow=done" == resp["result"]["content"][0]["text"]
        assert _pid_alive(first_pid), "child should still be alive right after slow call completes"

        # Now wait past idle=1.0s with nothing in flight: reaper must kill first_pid.
        assert _wait_pid_dead(first_pid, timeout=4.0), "idle child was not reaped"

        # Next call transparently respawns a new child with a new pid.
        client.send({
            "jsonrpc": "2.0",
            "id": 31,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "respawned"}},
        })
        resp2 = client.recv()
        pids2 = fixture_env["read_pids"]()
        assert len(pids2) == 2
        assert pids2[1] != first_pid
        assert resp2["result"]["content"][0]["text"] == f"pid={pids2[1]} msg=respawned"
    finally:
        rc, _err = client.close()
        assert rc == 0


def test_idle_reap_blocked_by_subscription_and_server_request(fixture_env):
    # Warm cache first
    c0 = fixture_env["start"]()
    c0.handshake()
    c0.close()
    fixture_env["pid_log"].unlink()

    client = fixture_env["start"](idle=0.6)
    try:
        client.handshake()

        # 1. Open resource subscription must prevent idle reaping.
        client.send({
            "jsonrpc": "2.0",
            "id": 40,
            "method": "resources/subscribe",
            "params": {"uri": "mem://item"},
        })
        sub_r = client.recv()
        assert sub_r["result"]["subscribed"] == "mem://item"
        pid1 = fixture_env["read_pids"]()[0]

        time.sleep(1.1)
        assert _pid_alive(pid1), "child with open resource subscription must not be reaped"

        # Unsubscribe -> child becomes eligible and gets reaped.
        client.send({
            "jsonrpc": "2.0",
            "id": 41,
            "method": "resources/unsubscribe",
            "params": {"uri": "mem://item"},
        })
        unsub_r = client.recv()
        assert unsub_r["result"]["unsubscribed"] == "mem://item"
        assert _wait_pid_dead(pid1, timeout=3.0), "child should reap after unsubscribe"

        # 2. Unanswered server-to-client request must prevent idle reaping.
        client.send({
            "jsonrpc": "2.0",
            "id": 42,
            "method": "tools/call",
            "params": {"name": "ask_client", "arguments": {}},
        })
        r1 = client.recv()
        r2 = client.recv()
        msgs = [r1, r2]
        assert any(m.get("id") == 42 for m in msgs)
        assert any(m.get("id") == "srv-req-1" and m.get("method") == "roots/list" for m in msgs)
        pid2 = fixture_env["read_pids"]()[1]

        time.sleep(1.1)
        assert _pid_alive(pid2), "child with unanswered server-to-client request must not be reaped"

        # Answer server-to-client request -> child becomes eligible and gets reaped.
        client.send({"jsonrpc": "2.0", "id": "srv-req-1", "result": {"roots": []}})
        assert _wait_pid_dead(pid2, timeout=3.0), "child should reap after server request is answered"
    finally:
        rc, _err = client.close()
        assert rc == 0


def test_child_crash_mid_call_returns_error_and_next_call_respawns(fixture_env):
    c0 = fixture_env["start"]()
    c0.handshake()
    c0.close()
    fixture_env["pid_log"].unlink()

    client = fixture_env["start"]()
    try:
        client.handshake()
        client.send({
            "jsonrpc": "2.0",
            "id": 50,
            "method": "tools/call",
            "params": {"name": "crash", "arguments": {}},
        })
        err_resp = client.recv(timeout=5.0)
        assert err_resp["id"] == 50
        assert "error" in err_resp and err_resp["error"]["code"] == -32603
        pids1 = fixture_env["read_pids"]()
        assert len(pids1) == 1

        # Next call respawns cleanly with a new pid.
        client.send({
            "jsonrpc": "2.0",
            "id": 51,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "recovered"}},
        })
        ok_resp = client.recv(timeout=5.0)
        pids2 = fixture_env["read_pids"]()
        assert len(pids2) == 2 and pids2[1] != pids1[0]
        assert ok_resp["id"] == 51
        assert ok_resp["result"]["content"][0]["text"] == f"pid={pids2[1]} msg=recovered"
    finally:
        rc, _err = client.close()
        assert rc == 0


def test_tools_list_changed_emitted_when_fresh_list_differs_from_cache(fixture_env):
    tools_file: Path = fixture_env["tools_file"]
    tools_file.write_text(json.dumps([
        {"name": "echo", "description": "v1", "inputSchema": {"type": "object"}},
    ]), encoding="utf-8")

    # Warm cache with v1 tools.
    c0 = fixture_env["start"]()
    c0.handshake()
    c0.close()
    fixture_env["pid_log"].unlink()

    # Mutate server's tool list to v2 before next session.
    tools_file.write_text(json.dumps([
        {"name": "echo", "description": "v1", "inputSchema": {"type": "object"}},
        {"name": "new_tool", "description": "v2", "inputSchema": {"type": "object"}},
    ]), encoding="utf-8")

    client = fixture_env["start"]()
    try:
        _init_r, tools_r = client.handshake()
        assert [t["name"] for t in tools_r["result"]["tools"]] == ["echo"]
        assert fixture_env["read_pids"]() == []

        client.send({
            "jsonrpc": "2.0",
            "id": 60,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "trigger"}},
        })
        m1 = client.recv()
        m2 = client.recv()
        msgs = [m1, m2]
        assert any(m.get("method") == "notifications/tools/list_changed" and "id" not in m for m in msgs)
        call_r = next(m for m in msgs if m.get("id") == 60)
        assert "msg=trigger" in call_r["result"]["content"][0]["text"]

        # Cache file on disk must now carry the refreshed tool list.
        cached = json.loads((fixture_env["cache_dir"] / "fixture-srv.json").read_text(encoding="utf-8"))
        assert [t["name"] for t in cached["tools"]["tools"]] == ["echo", "new_tool"]
    finally:
        rc, _err = client.close()
        assert rc == 0


def test_stdout_only_valid_jsonrpc_and_content_length_framing(fixture_env):
    # 1. Noisy child writes garbage to stdout and logs to stderr; proxy stdout must stay pure JSON-RPC.
    client = fixture_env["start"]()
    try:
        client.handshake()
        client.send({
            "jsonrpc": "2.0",
            "id": 70,
            "method": "tools/call",
            "params": {"name": "noisy", "arguments": {}},
        })
        resp = client.recv()
        assert resp["id"] == 70
        assert "noisy=ok" in resp["result"]["content"][0]["text"]
        assert len(client.raw_stdout_lines) >= 3
        for raw_line in client.raw_stdout_lines:
            parsed = json.loads(raw_line.decode("utf-8"))
            assert isinstance(parsed, dict) and parsed.get("jsonrpc") == "2.0"
    finally:
        rc, stderr = client.close()
        assert rc == 0
        assert "dropping non-JSON stdout line" in stderr

    # 2. Content-Length framing works seamlessly over cached handshake + live tools/call.
    fixture_env["pid_log"].unlink()
    client_cl = fixture_env["start"](framing="content-length")
    try:
        init_r, tools_r = client_cl.handshake()
        assert init_r["result"]["serverInfo"]["name"] == "fixture-mcp"
        assert any(t["name"] == "echo" for t in tools_r["result"]["tools"])
        assert fixture_env["read_pids"]() == []
        client_cl.send({
            "jsonrpc": "2.0",
            "id": 71,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "cl"}},
        })
        resp_cl = client_cl.recv()
        assert "msg=cl" in resp_cl["result"]["content"][0]["text"]
    finally:
        rc, _err = client_cl.close()
        assert rc == 0


# --- Adversary L3 Hardening Tests ---


@pytest.mark.parametrize("bad_id", ["", "../evil", "Upper", "under_score", "a/b", "a.b", "a b", "ok\n"])
def test_hardening_rejects_invalid_id(fixture_env, bad_id: str):
    r = subprocess.run(
        [str(SCRIPT), "--id", bad_id, "--cache-dir", str(fixture_env["cache_dir"]), "--", sys.executable, str(fixture_env["server"])],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2
    assert r.stdout == ""
    assert "mcp-lazy:" in r.stderr


@pytest.mark.parametrize("bad_cmd", ["python3", "./fixture_server.py", "bin/python3", "/usr/bin/../bin/python3", "/tmp/"])
def test_hardening_rejects_relative_or_dotdot_command(fixture_env, bad_cmd: str):
    r = subprocess.run(
        [str(SCRIPT), "--id", "good-id", "--cache-dir", str(fixture_env["cache_dir"]), "--", bad_cmd],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2
    assert r.stdout == ""
    assert "mcp-lazy:" in r.stderr


def test_hardening_rejects_symlink_and_bad_mode_cache_and_ignores_cached_command(fixture_env):
    cache_dir: Path = fixture_env["cache_dir"]
    cache_dir.mkdir(parents=True, mode=0o700)
    cache_file = cache_dir / "fixture-srv.json"

    fake_payload = {
        "version": 1,
        "command": ["/bin/false", "should-never-run"],
        "argv": ["/bin/false"],
        "initialize": {
            "protocolVersion": "2025-11-25",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "poisoned-cache", "version": "0"},
        },
        "tools": {"tools": [{"name": "poisoned_tool"}]},
    }

    # Case 1: Symlink cache file -> ignored and rebuilt atomically as a real 0600 file.
    target = fixture_env["tmp"] / "symlink-target.json"
    target.write_text(json.dumps(fake_payload), encoding="utf-8")
    target.chmod(0o600)
    cache_file.symlink_to(target)

    c1 = fixture_env["start"]()
    try:
        init_r, _tools_r = c1.handshake()
        assert init_r["result"]["serverInfo"]["name"] == "fixture-mcp"
        assert len(fixture_env["read_pids"]()) == 1
    finally:
        assert c1.close()[0] == 0
    assert not cache_file.is_symlink() and stat.S_IMODE(cache_file.stat().st_mode) == 0o600

    # Case 2: World-writable (0666) and group-readable (0640) cache files -> ignored and rebuilt.
    for bad_mode in (0o666, 0o644, 0o640, 0o620):
        fixture_env["pid_log"].unlink(missing_ok=True)
        cache_file.write_text(json.dumps(fake_payload), encoding="utf-8")
        cache_file.chmod(bad_mode)
        c2 = fixture_env["start"]()
        try:
            init_r, _tools_r = c2.handshake()
            assert init_r["result"]["serverInfo"]["name"] == "fixture-mcp"
            assert len(fixture_env["read_pids"]()) == 1
        finally:
            assert c2.close()[0] == 0
        assert stat.S_IMODE(cache_file.stat().st_mode) == 0o600

    # Case 3: World-writable cache dir (0777) -> ignored on load, tightened to 0700 on rebuild.
    fixture_env["pid_log"].unlink(missing_ok=True)
    cache_file.write_text(json.dumps(fake_payload), encoding="utf-8")
    cache_file.chmod(0o600)
    cache_dir.chmod(0o777)
    c3 = fixture_env["start"]()
    try:
        init_r, _tools_r = c3.handshake()
        assert init_r["result"]["serverInfo"]["name"] == "fixture-mcp"
        assert len(fixture_env["read_pids"]()) == 1
    finally:
        assert c3.close()[0] == 0
    assert stat.S_IMODE(cache_dir.stat().st_mode) == 0o700

    # Case 4: Valid 0600 cache containing extra "command"/"argv" keys -> those keys are stripped/never executed.
    fixture_env["pid_log"].unlink(missing_ok=True)
    cache_file.write_text(json.dumps(fake_payload), encoding="utf-8")
    cache_file.chmod(0o600)
    c4 = fixture_env["start"]()
    try:
        c4.handshake()
        c4.send({
            "jsonrpc": "2.0",
            "id": 80,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "cli-cmd-used"}},
        })
        msgs = [c4.recv(), c4.recv()]  # list_changed + tools/call result
        call_r = next(m for m in msgs if m.get("id") == 80)
        assert "msg=cli-cmd-used" in call_r["result"]["content"][0]["text"]
    finally:
        assert c4.close()[0] == 0
    rebuilt = json.loads(cache_file.read_text(encoding="utf-8"))
    assert "command" not in rebuilt and "argv" not in rebuilt


def test_hardening_child_cwd_is_home_and_relative_path_stripped(fixture_env):
    dirty_path = os.pathsep.join(["", ".", "./node_modules/.bin", "relative/dir", "/usr/bin", "/bin", "/opt/../etc"])
    client = fixture_env["start"](
        extra_env={"PATH": dirty_path},
        cwd=fixture_env["session_cwd"],
    )
    try:
        client.handshake()
        client.send({
            "jsonrpc": "2.0",
            "id": 90,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "env-check"}},
        })
        resp = client.recv()
        assert "msg=env-check" in resp["result"]["content"][0]["text"]
    finally:
        assert client.close()[0] == 0

    observed = json.loads(fixture_env["env_log"].read_text(encoding="utf-8"))
    assert Path(observed["cwd"]).resolve() == fixture_env["home"].resolve()
    assert Path(observed["cwd"]).resolve() != fixture_env["session_cwd"].resolve()
    path_entries = [p for p in observed["PATH"].split(os.pathsep) if p != ""]
    assert observed["PATH"] == os.pathsep.join(["/usr/bin", "/bin"])
    assert all(os.path.isabs(p) and ".." not in p.split("/") for p in path_entries)
