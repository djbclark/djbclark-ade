"""Unit and integration tests for bin/mcp-lazy (docs/mcp-on-demand.md §11.3)."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import select
import signal
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
import signal
import subprocess
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
    if os.environ.get("FIXTURE_SLOW_EXIT") == "1":
        def _slow_term(_signum, _frame):
            time.sleep(0.35)
            os._exit(0)
        signal.signal(signal.SIGTERM, _slow_term)

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
    caps_file = os.environ.get("FIXTURE_CAPS_FILE")
    proto_file = os.environ.get("FIXTURE_PROTO_FILE")
    cursor_file = os.environ.get("FIXTURE_CURSOR_FILE")
    fail_init_file = os.environ.get("FIXTURE_FAIL_INIT_FILE")
    roots_flag = os.environ.get("FIXTURE_ASK_ROOTS_ON_TOOLS_LIST") == "1"
    roots_on_init_flag = os.environ.get("FIXTURE_ASK_ROOTS_ON_INITIALIZED") == "1"
    pre_init_noise = os.environ.get("FIXTURE_PRE_INIT_NOISE") == "1"
    descendant_pid_file = os.environ.get("FIXTURE_DESCENDANT_PID_FILE")
    init_started_file = os.environ.get("FIXTURE_INIT_STARTED_FILE")
    init_release_file = os.environ.get("FIXTURE_INIT_RELEASE_FILE")
    call_log_file = os.environ.get("FIXTURE_CALL_LOG")
    cancel_log_file = os.environ.get("FIXTURE_CANCEL_LOG")
    nan_tools_file = os.environ.get("FIXTURE_NAN_TOOLS_FILE")
    init_roots_err_file = os.environ.get("FIXTURE_INIT_ROOTS_ERR_FILE")

    def current_tools():
        if tools_file and os.path.exists(tools_file):
            with open(tools_file, encoding="utf-8") as f:
                return json.load(f)
        return [
            {"name": "echo", "description": "Echo back input with child pid", "inputSchema": {"type": "object"}},
            {"name": "slow", "description": "Sleep before replying", "inputSchema": {"type": "object"}},
            {"name": "crash", "description": "Crash mid-call", "inputSchema": {"type": "object"}},
            {"name": "crash_with_descendant", "description": "Spawn descendant holding stdout then crash", "inputSchema": {"type": "object"}},
            {"name": "stall_stdin", "description": "Stop reading stdin forever", "inputSchema": {"type": "object"}},
            {"name": "noisy", "description": "Write non-JSON line to stdout before replying", "inputSchema": {"type": "object"}},
            {"name": "json_noise", "description": "Write valid JSON without JSON-RPC envelope", "inputSchema": {"type": "object"}},
            {"name": "nan_result", "description": "Write non-finite NaN in JSON-RPC result", "inputSchema": {"type": "object"}},
            {"name": "oversized", "description": "Write oversized NDJSON frame", "inputSchema": {"type": "object"}},
            {"name": "ask_client", "description": "Send a server-to-client request", "inputSchema": {"type": "object"}},
        ]

    def current_caps():
        if caps_file and os.path.exists(caps_file):
            with open(caps_file, encoding="utf-8") as f:
                return json.load(f)
        return {
            "tools": {"listChanged": True},
            "prompts": {},
            "resources": {"subscribe": True},
        }

    def current_proto(offered):
        if proto_file and os.path.exists(proto_file):
            val = open(proto_file, encoding="utf-8").read().strip()
            if val:
                return val
        return offered

    framing = "ndjson"
    buffered_msgs = []

    def next_msg():
        if buffered_msgs:
            return buffered_msgs.pop(0)
        return read_msg()

    while True:
        msg, seen_framing = next_msg()
        if msg is None:
            if os.environ.get("FIXTURE_SLOW_EXIT") == "1":
                time.sleep(0.45)
            break
        if seen_framing == "content-length":
            framing = "content-length"
        method = msg.get("method")
        mid = msg.get("id")
        params = msg.get("params") or {}

        if method is None:
            continue
        if "id" not in msg:
            if method == "notifications/cancelled" and cancel_log_file:
                with open(cancel_log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(params) + "\n")
                    f.flush()
            elif method == "notifications/initialized" and roots_on_init_flag:
                req_id = f"srv-on-init-{os.getpid()}"
                send_msg({"jsonrpc": "2.0", "id": req_id, "method": "roots/list", "params": {}}, framing)
                while True:
                    reply, r_fr = read_msg()
                    if reply is None:
                        return
                    if reply.get("method") is None and reply.get("id") == req_id:
                        if "error" in reply and init_roots_err_file:
                            with open(init_roots_err_file, "w", encoding="utf-8") as f:
                                json.dump(reply["error"], f)
                        break
                    buffered_msgs.append((reply, r_fr))
            continue

        if method == "initialize":
            if init_started_file and init_release_file:
                with open(init_started_file, "w", encoding="utf-8") as f:
                    f.write(f"{os.getpid()}\n")
                    f.flush()
                while not os.path.exists(init_release_file):
                    time.sleep(0.02)
            if pre_init_noise:
                send_msg({"jsonrpc": "2.0", "method": "notifications/message", "params": {"data": "too-early"}}, framing)
                send_msg({"jsonrpc": "2.0", "id": "early-req", "method": "roots/list", "params": {}}, framing)
                # Consume proxy's -32600 rejection of early-req
                _early_reply, _ = read_msg()
            if fail_init_file and os.path.exists(fail_init_file):
                secret_blob = open(fail_init_file, encoding="utf-8").read()
                send_msg({"jsonrpc": "2.0", "id": mid, "error": {"code": -32001, "message": secret_blob}}, framing)
                continue
            offered = params.get("protocolVersion", "2025-11-25")
            send_msg({
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "protocolVersion": current_proto(offered),
                    "capabilities": current_caps(),
                    "serverInfo": {"name": "fixture-mcp", "version": "1.0.0"},
                },
            }, framing)
        elif method == "tools/list":
            if nan_tools_file and os.path.exists(nan_tools_file):
                raw_line = ('{"jsonrpc":"2.0","id":' + json.dumps(mid) + ',"result":{"tools":[{"name":"bad","x":Infinity}]}}\n').encode("utf-8")
                sys.stdout.buffer.write(raw_line)
                sys.stdout.buffer.flush()
                continue
            if roots_flag:
                req_id = f"srv-roots-{os.getpid()}"
                send_msg({"jsonrpc": "2.0", "id": req_id, "method": "roots/list", "params": {}}, framing)
                while True:
                    reply, _ = read_msg()
                    if reply is None:
                        return
                    if reply.get("method") is None and reply.get("id") == req_id:
                        break
            res = {"tools": current_tools()}
            if cursor_file and os.path.exists(cursor_file):
                cursor = open(cursor_file, encoding="utf-8").read().strip()
                if cursor and not params.get("cursor"):
                    res["nextCursor"] = cursor
            send_msg({"jsonrpc": "2.0", "id": mid, "result": res}, framing)
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
            if call_log_file:
                with open(call_log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"id": mid, "name": name, "args": args}) + "\n")
                    f.flush()
            if name == "echo":
                send_msg({
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {"content": [{"type": "text", "text": f"pid={os.getpid()} msg={args.get('msg', '')}"}]},
                }, framing)
            elif name == "slow":
                # Support interruptible slow loop so we can observe notifications/cancelled on stdin if desired.
                end_t = time.monotonic() + float(args.get("seconds", 1.5))
                while time.monotonic() < end_t:
                    time.sleep(0.05)
                send_msg({
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {"content": [{"type": "text", "text": f"pid={os.getpid()} slow=done"}]},
                }, framing)
            elif name == "nan_result":
                raw_line = ('{"jsonrpc":"2.0","id":' + json.dumps(mid) + ',"result":{"value":NaN}}\n').encode("utf-8")
                sys.stdout.buffer.write(raw_line)
                sys.stdout.buffer.flush()
            elif name == "crash":
                os._exit(42)
            elif name == "crash_with_descendant":
                # Spawn a descendant inheriting stdout FD, then crash parent immediately.
                child = subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(60)"],
                    stdin=subprocess.DEVNULL,
                    stdout=sys.stdout.fileno(),
                    stderr=subprocess.DEVNULL,
                )
                if descendant_pid_file:
                    with open(descendant_pid_file, "w", encoding="utf-8") as f:
                        f.write(f"{child.pid}\n")
                        f.flush()
                os._exit(43)
            elif name == "stall_stdin":
                # Reply to trigger call, then stop reading stdin forever.
                send_msg({
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {"content": [{"type": "text", "text": f"pid={os.getpid()} stalling"}]},
                }, framing)
                time.sleep(60)
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
            elif name == "json_noise":
                # Valid JSON objects/arrays that are NOT valid JSON-RPC 2.0 envelopes.
                for junk in (
                    {"level": "info", "msg": "diagnostic json"},
                    {"jsonrpc": "1.0", "id": 999, "result": {}},
                    {"jsonrpc": "2.0", "id": True, "result": {}},
                    [1, 2, 3],
                ):
                    send_msg(junk, framing)
                send_msg({
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {"content": [{"type": "text", "text": f"pid={os.getpid()} json_noise=ok"}]},
                }, framing)
            elif name == "oversized":
                # Emit an NDJSON line larger than the test's MCP_LAZY_MAX_FRAME_BYTES cap.
                huge = {"jsonrpc": "2.0", "id": mid, "result": {"blob": "x" * 4096}}
                send_msg(huge, framing)
            elif name == "ask_client":
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


def _load_mcp_lazy_module():
    loader = importlib.machinery.SourceFileLoader("mcp_lazy_mod", str(SCRIPT))
    spec = importlib.util.spec_from_loader("mcp_lazy_mod", loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


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

    def handshake(self, protocol_version: str = "2025-11-25") -> tuple[dict[str, Any], dict[str, Any]]:
        self.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": protocol_version,
                "capabilities": {"roots": {}},
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
            self.proc.wait(timeout=6.0)
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
    caps_file = tmp_path / "caps.json"
    proto_file = tmp_path / "proto.txt"
    cursor_file = tmp_path / "cursor.txt"
    fail_init_file = tmp_path / "fail_init.txt"
    descendant_pid_file = tmp_path / "descendant.pid"
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
        cache_dir_override: Optional[Path] = None,
        via_python: bool = False,
    ) -> ProxyClient:
        env = dict(os.environ)
        env["HOME"] = str(fake_home)
        env["FIXTURE_PID_LOG"] = str(pid_log)
        env["FIXTURE_ENV_LOG"] = str(env_log)
        env["FIXTURE_DESCENDANT_PID_FILE"] = str(descendant_pid_file)
        if tools_file.exists():
            env["FIXTURE_TOOLS_FILE"] = str(tools_file)
        if caps_file.exists():
            env["FIXTURE_CAPS_FILE"] = str(caps_file)
        if proto_file.exists():
            env["FIXTURE_PROTO_FILE"] = str(proto_file)
        if cursor_file.exists():
            env["FIXTURE_CURSOR_FILE"] = str(cursor_file)
        if fail_init_file.exists():
            env["FIXTURE_FAIL_INIT_FILE"] = str(fail_init_file)
        if extra_env:
            env.update(extra_env)
        prefix = [sys.executable, str(SCRIPT)] if via_python else [str(SCRIPT)]
        argv = [
            *prefix,
            "--id", server_id,
            "--idle", str(idle),
            "--cache-dir", str(cache_dir_override or cache_dir),
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
        "caps_file": caps_file,
        "proto_file": proto_file,
        "cursor_file": cursor_file,
        "fail_init_file": fail_init_file,
        "descendant_pid_file": descendant_pid_file,
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

    cache_dir: Path = fixture_env["cache_dir"]
    cache_file = cache_dir / "fixture-srv.json"
    assert cache_file.is_file() and not cache_file.is_symlink()
    assert stat.S_IMODE(cache_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(cache_file.stat().st_mode) == 0o600
    cached = json.loads(cache_file.read_text(encoding="utf-8"))
    assert "command" not in cached and "argv" not in cached
    assert set(cached.keys()) <= {
        "version", "clientProtocolVersion", "initialize", "tools", "prompts", "resources", "resourceTemplates"
    }

    # Warm start: ZERO child spawned for initialize, notifications/initialized, tools/list, prompts/list, resources/list, ping.
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


def test_discovery_awaits_client_roots_reply_on_cold_and_on_demand_start(fixture_env):
    """HIGH #1: client reader stays unblocked during cold warm-up & on-demand discovery; pre-init traffic is gated."""
    extra = {
        "FIXTURE_ASK_ROOTS_ON_TOOLS_LIST": "1",
        "FIXTURE_PRE_INIT_NOISE": "1",
    }
    # 1. Cold warm-up: server emits pre-init noise (must be gated!), then asks roots/list during warm-up tools/list.
    c1 = fixture_env["start"](extra_env=extra)
    try:
        c1.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {"roots": {}},
                "clientInfo": {"name": "roots-client", "version": "1"},
            },
        })
        # First message MUST be the initialize response (pre-init notification & early-req were gated!).
        first = c1.recv(timeout=5.0)
        assert first.get("id") == 1 and "result" in first, f"pre-init traffic leaked before initialize: {first!r}"
        c1.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        # Next, server asks roots/list while constructing warm-up tools/list; client replies while proxy is warming!
        roots_req = c1.recv(timeout=5.0)
        assert roots_req.get("method") == "roots/list" and "id" in roots_req
        c1.send({"jsonrpc": "2.0", "id": roots_req["id"], "result": {"roots": [{"uri": "file:///ws"}]}})

        # Now client requests tools/list -> served from the freshly warmed cache after warm-up completes!
        c1.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools_r = c1.recv(timeout=5.0)
        assert tools_r["id"] == 2 and any(t["name"] == "echo" for t in tools_r["result"]["tools"])
    finally:
        rc, stderr = c1.close()
        assert rc == 0
        assert "dropping pre-initialization child message" in stderr

    # 2. On-demand startup: warm handshake spawns 0 children; tools/call triggers on-demand spawn + discovery refresh
    #    which again asks roots/list and MUST receive the client's reply without stalling!
    fixture_env["pid_log"].unlink()
    c2 = fixture_env["start"](extra_env=extra)
    try:
        init_r, tools_r = c2.handshake()
        assert init_r["result"]["serverInfo"]["name"] == "fixture-mcp"
        assert fixture_env["read_pids"]() == []

        c2.send({
            "jsonrpc": "2.0",
            "id": 25,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "after-roots"}},
        })
        # Expect server's roots/list during on-demand discovery; reply to it, then receive tools/call response!
        roots_req2 = c2.recv(timeout=5.0)
        assert roots_req2.get("method") == "roots/list" and "id" in roots_req2
        c2.send({"jsonrpc": "2.0", "id": roots_req2["id"], "result": {"roots": [{"uri": "file:///ws"}]}})

        call_r = c2.recv(timeout=5.0)
        assert call_r["id"] == 25
        assert "msg=after-roots" in call_r["result"]["content"][0]["text"]
    finally:
        assert c2.close()[0] == 0


def test_idle_reap_fires_and_never_while_call_in_flight(fixture_env):
    c0 = fixture_env["start"]()
    c0.handshake()
    c0.close()
    fixture_env["pid_log"].unlink()

    client = fixture_env["start"](idle=1.0)
    try:
        client.handshake()
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

        assert _wait_pid_dead(first_pid, timeout=4.0), "idle child was not reaped"

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
    c0 = fixture_env["start"]()
    c0.handshake()
    c0.close()
    fixture_env["pid_log"].unlink()

    client = fixture_env["start"](idle=0.6)
    try:
        client.handshake()

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

        client.send({
            "jsonrpc": "2.0",
            "id": 41,
            "method": "resources/unsubscribe",
            "params": {"uri": "mem://item"},
        })
        unsub_r = client.recv()
        assert unsub_r["result"]["unsubscribed"] == "mem://item"
        assert _wait_pid_dead(pid1, timeout=3.0), "child should reap after unsubscribe"

        client.send({
            "jsonrpc": "2.0",
            "id": 42,
            "method": "tools/call",
            "params": {"name": "ask_client", "arguments": {}},
        })
        msgs = [client.recv(), client.recv()]
        assert any(m.get("id") == 42 for m in msgs)
        assert any(m.get("id") == "srv-req-1" and m.get("method") == "roots/list" for m in msgs)
        pid2 = fixture_env["read_pids"]()[1]

        time.sleep(1.1)
        assert _pid_alive(pid2), "child with unanswered server-to-client request must not be reaped"

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


def test_child_crash_with_descendant_holding_stdout_open(fixture_env):
    """HIGH #2a: child dies while descendant keeps stdout open; proxy must not hang and must kill pgid."""
    c0 = fixture_env["start"]()
    c0.handshake()
    c0.close()
    fixture_env["pid_log"].unlink()

    client = fixture_env["start"]()
    try:
        client.handshake()
        client.send({
            "jsonrpc": "2.0",
            "id": 52,
            "method": "tools/call",
            "params": {"name": "crash_with_descendant", "arguments": {}},
        })
        err_resp = client.recv(timeout=4.0)
        assert err_resp["id"] == 52 and err_resp["error"]["code"] == -32603

        desc_pid = int(fixture_env["descendant_pid_file"].read_text(encoding="utf-8").strip())
        assert _wait_pid_dead(desc_pid, timeout=3.0), "descendant holding stdout open must be killed with process group"

        # Next call respawns cleanly.
        client.send({
            "jsonrpc": "2.0",
            "id": 53,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "post-desc"}},
        })
        ok_r = client.recv(timeout=5.0)
        assert ok_r["id"] == 53 and "msg=post-desc" in ok_r["result"]["content"][0]["text"]
    finally:
        assert client.close()[0] == 0


def test_stalled_stdin_consumer_retires_child_without_hanging(fixture_env):
    """HIGH #2b: non-reading child fills stdin pipe buffer; bounded write times out, retires child, and respawns."""
    c0 = fixture_env["start"]()
    c0.handshake()
    c0.close()
    fixture_env["pid_log"].unlink()

    client = fixture_env["start"](extra_env={"MCP_LAZY_WRITE_TIMEOUT": "0.5"})
    try:
        client.handshake()
        # Put child into non-reading stall mode.
        client.send({
            "jsonrpc": "2.0",
            "id": 54,
            "method": "tools/call",
            "params": {"name": "stall_stdin", "arguments": {}},
        })
        r_stall = client.recv(timeout=5.0)
        assert "stalling" in r_stall["result"]["content"][0]["text"]
        stalled_pid = fixture_env["read_pids"]()[0]

        # Send a large payload (>512 KB, exceeding OS pipe buffer) so stdin write blocks and hits write timeout.
        client.send({
            "jsonrpc": "2.0",
            "id": 55,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "A" * (512 * 1024)}},
        })
        err_r = client.recv(timeout=5.0)
        assert err_r["id"] == 55 and err_r["error"]["code"] == -32603
        assert _wait_pid_dead(stalled_pid, timeout=3.0), "stalled child must be terminated"

        # Next call respawns cleanly.
        client.send({
            "jsonrpc": "2.0",
            "id": 56,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "after-stall"}},
        })
        ok_r = client.recv(timeout=5.0)
        assert ok_r["id"] == 56 and "msg=after-stall" in ok_r["result"]["content"][0]["text"]
    finally:
        assert client.close()[0] == 0


def test_eof_racing_idle_reap_leaves_no_orphan_child(fixture_env):
    """HIGH #2c: client EOF arriving while idle reaper is mid-teardown must wait for teardown (no orphan)."""
    c0 = fixture_env["start"]()
    c0.handshake()
    c0.close()
    fixture_env["pid_log"].unlink()

    client = fixture_env["start"](idle=0.25, extra_env={"FIXTURE_SLOW_EXIT": "1"})
    client.handshake()
    client.send({
        "jsonrpc": "2.0",
        "id": 57,
        "method": "tools/call",
        "params": {"name": "echo", "arguments": {"msg": "race"}},
    })
    assert "msg=race" in client.recv(timeout=5.0)["result"]["content"][0]["text"]
    child_pid = fixture_env["read_pids"]()[0]

    # Sleep right into the idle reap window (idle=0.25s, child takes ~0.45s to exit), then send EOF!
    time.sleep(0.32)
    rc, _err = client.close()
    assert rc == 0
    # By the time proxy exits, the child MUST already be dead (no detached orphan).
    assert not _pid_alive(child_pid), f"orphan child pid={child_pid} survived EOF racing idle reap"


def test_tools_list_changed_emitted_when_fresh_list_differs_from_cache(fixture_env):
    tools_file: Path = fixture_env["tools_file"]
    tools_file.write_text(json.dumps([
        {"name": "echo", "description": "v1", "inputSchema": {"type": "object"}},
    ]), encoding="utf-8")

    c0 = fixture_env["start"]()
    c0.handshake()
    c0.close()
    fixture_env["pid_log"].unlink()

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
        msgs = [client.recv(), client.recv()]
        assert any(m.get("method") == "notifications/tools/list_changed" and "id" not in m for m in msgs)
        call_r = next(m for m in msgs if m.get("id") == 60)
        assert "msg=trigger" in call_r["result"]["content"][0]["text"]

        cached = json.loads((fixture_env["cache_dir"] / "fixture-srv.json").read_text(encoding="utf-8"))
        assert [t["name"] for t in cached["tools"]["tools"]] == ["echo", "new_tool"]
    finally:
        rc, _err = client.close()
        assert rc == 0


def test_protocol_version_change_rewarms_and_fails_closed_on_live_mismatch(fixture_env):
    """MEDIUM #2: cached initialize validates protocolVersion compatibility and live mismatch fails closed."""
    proto_file: Path = fixture_env["proto_file"]
    # 1. Warm cache with client offering 2025-06-18 (server agrees on 2025-06-18).
    c0 = fixture_env["start"]()
    init0, _ = c0.handshake(protocol_version="2025-06-18")
    assert init0["result"]["protocolVersion"] == "2025-06-18"
    assert c0.close()[0] == 0

    # 2. Next client offers 2025-11-25 -> cache mismatch -> re-warms from child (1 spawn) and negotiates 2025-11-25.
    fixture_env["pid_log"].unlink()
    c1 = fixture_env["start"]()
    try:
        init1, _ = c1.handshake(protocol_version="2025-11-25")
        assert init1["result"]["protocolVersion"] == "2025-11-25"
        assert len(fixture_env["read_pids"]()) == 1
    finally:
        assert c1.close()[0] == 0

    # 3. Now live server switches to 2024-11-05 while cache still says 2025-11-25.
    #    Client gets cached 2025-11-25 on initialize, then on tools/call the live child negotiates 2024-11-05
    #    -> proxy MUST fail closed with JSON-RPC -32603 error and invalidate the stale cache!
    proto_file.write_text("2024-11-05\n", encoding="utf-8")
    fixture_env["pid_log"].unlink()
    c2 = fixture_env["start"]()
    try:
        init2, _ = c2.handshake(protocol_version="2025-11-25")
        assert init2["result"]["protocolVersion"] == "2025-11-25"
        assert fixture_env["read_pids"]() == []

        c2.send({
            "jsonrpc": "2.0",
            "id": 65,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "should-fail"}},
        })
        err_r = c2.recv(timeout=5.0)
        assert err_r["id"] == 65
        assert "error" in err_r and err_r["error"]["code"] == -32603
        assert "protocol version" in err_r["error"]["message"].lower()
        assert not (fixture_env["cache_dir"] / "fixture-srv.json").exists(), "stale cache must be invalidated"
    finally:
        assert c2.close()[0] == 0


def test_refresh_drops_stale_cache_on_pagination_and_capability_removal(fixture_env):
    """MEDIUM #3: refresh drops stale cached lists and emits list_changed when paginated or capability removed."""
    # Warm cache with full tools + prompts + resources.
    c0 = fixture_env["start"]()
    c0.handshake()
    c0.close()
    fixture_env["pid_log"].unlink()

    cache_file = fixture_env["cache_dir"] / "fixture-srv.json"
    before = json.loads(cache_file.read_text(encoding="utf-8"))
    assert "tools" in before and "prompts" in before

    # Transition: tools/list becomes paginated (nextCursor) AND prompts capability is removed.
    fixture_env["cursor_file"].write_text("page-2\n", encoding="utf-8")
    fixture_env["caps_file"].write_text(json.dumps({"tools": {"listChanged": True}}), encoding="utf-8")

    c1 = fixture_env["start"]()
    try:
        c1.handshake()
        c1.send({"jsonrpc": "2.0", "id": 66, "method": "prompts/list", "params": {}})
        assert c1.recv()["result"]["prompts"] == [{"name": "hello"}]
        assert fixture_env["read_pids"]() == []

        # Trigger on-demand spawn & refresh.
        c1.send({
            "jsonrpc": "2.0",
            "id": 67,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "refresh-inval"}},
        })
        # Expect list_changed notifications for tools, prompts, and resources + tools/call reply.
        received = []
        while not any(m.get("id") == 67 for m in received):
            received.append(c1.recv(timeout=5.0))
        notif_methods = {m.get("method") for m in received if "id" not in m}
        assert "notifications/tools/list_changed" in notif_methods
        assert "notifications/prompts/list_changed" in notif_methods
        assert "notifications/resources/list_changed" in notif_methods
    finally:
        assert c1.close()[0] == 0

    after = json.loads(cache_file.read_text(encoding="utf-8"))
    assert "tools" not in after, "paginated tools list must drop stale cache entry"
    assert "prompts" not in after, "removed prompts capability must drop stale cache entry"
    assert "resources" not in after, "removed resources capability must drop stale cache entry"

    # Subsequent session must NOT serve stale tools from cache: tools/list spawns child and returns nextCursor.
    fixture_env["pid_log"].unlink()
    c2 = fixture_env["start"]()
    try:
        _init2, tools2 = c2.handshake()
        assert tools2["result"].get("nextCursor") == "page-2"
        assert len(fixture_env["read_pids"]()) == 1
    finally:
        assert c2.close()[0] == 0


def test_stdout_strict_jsonrpc_filtering_bounded_frames_and_bounded_error_logs(fixture_env):
    """MEDIUM #4: filter non-JSON-RPC JSON, bound NDJSON frames, retire on framing error, bound startup error logs."""
    # 1. Noisy text + valid JSON lacking JSON-RPC 2.0 envelope must be dropped; stdout stays pure JSON-RPC 2.0.
    client = fixture_env["start"]()
    try:
        client.handshake()
        client.send({
            "jsonrpc": "2.0",
            "id": 70,
            "method": "tools/call",
            "params": {"name": "noisy", "arguments": {}},
        })
        assert "noisy=ok" in client.recv()["result"]["content"][0]["text"]

        client.send({
            "jsonrpc": "2.0",
            "id": 71,
            "method": "tools/call",
            "params": {"name": "json_noise", "arguments": {}},
        })
        assert "json_noise=ok" in client.recv()["result"]["content"][0]["text"]

        for raw_line in client.raw_stdout_lines:
            parsed = json.loads(raw_line.decode("utf-8"))
            assert isinstance(parsed, dict) and parsed.get("jsonrpc") == "2.0"
            assert "level" not in parsed
    finally:
        rc, stderr = client.close()
        assert rc == 0
        assert "dropping non-JSON stdout line" in stderr
        assert "dropping non-JSON-RPC message" in stderr

    # 2. Oversized NDJSON frame from child retires child and resolves pending call with -32603, then respawns.
    fixture_env["pid_log"].unlink()
    c_cap = fixture_env["start"](extra_env={"MCP_LAZY_MAX_FRAME_BYTES": "2048"})
    try:
        c_cap.handshake()
        c_cap.send({
            "jsonrpc": "2.0",
            "id": 72,
            "method": "tools/call",
            "params": {"name": "oversized", "arguments": {}},
        })
        err_r = c_cap.recv(timeout=5.0)
        assert err_r["id"] == 72 and err_r["error"]["code"] == -32603

        c_cap.send({
            "jsonrpc": "2.0",
            "id": 73,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "after-oversized"}},
        })
        ok_r = c_cap.recv(timeout=5.0)
        assert ok_r["id"] == 73 and "msg=after-oversized" in ok_r["result"]["content"][0]["text"]
    finally:
        assert c_cap.close()[0] == 0

    # 3. Startup failure must NOT dump arbitrary server-supplied error payloads to stderr.
    (fixture_env["cache_dir"] / "fixture-srv.json").unlink(missing_ok=True)
    sentinel_secret = "ARBITRARY-SERVER-ERROR-PAYLOAD-DO-NOT-LOG-" + ("Z" * 200)
    fixture_env["fail_init_file"].write_text(sentinel_secret, encoding="utf-8")
    c_fail = fixture_env["start"]()
    try:
        c_fail.send({
            "jsonrpc": "2.0",
            "id": 74,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
        })
        err_init = c_fail.recv(timeout=5.0)
        assert err_init["id"] == 74 and err_init["error"]["code"] == -32603
    finally:
        rc, stderr = c_fail.close()
        assert rc == 0
        assert "jsonrpc error code=-32001" in stderr
        assert sentinel_secret not in stderr
    fixture_env["fail_init_file"].unlink()

    # 4. Content-Length framing works seamlessly over cached handshake + live tools/call.
    c_warm = fixture_env["start"]()
    c_warm.handshake()
    c_warm.close()
    fixture_env["pid_log"].unlink()
    client_cl = fixture_env["start"](framing="content-length")
    try:
        init_r, tools_r = client_cl.handshake()
        assert init_r["result"]["serverInfo"]["name"] == "fixture-mcp"
        assert any(t["name"] == "echo" for t in tools_r["result"]["tools"])
        assert fixture_env["read_pids"]() == []
        client_cl.send({
            "jsonrpc": "2.0",
            "id": 75,
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


def test_hardening_rejects_symlink_fifo_bad_mode_and_untrusted_ancestor_cache(fixture_env):
    """MEDIUM #1 + L3: symlink, FIFO (no hang!), bad perms, untrusted ancestor, and ignored cached command."""
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

    # Case 1: FIFO at cache file path must NOT hang initialize; ignored and atomically replaced with 0600 file.
    os.mkfifo(cache_file, 0o600)
    c_fifo = fixture_env["start"]()
    try:
        init_r, _ = c_fifo.handshake()
        assert init_r["result"]["serverInfo"]["name"] == "fixture-mcp"
        assert len(fixture_env["read_pids"]()) == 1
    finally:
        assert c_fifo.close()[0] == 0
    st = os.lstat(cache_file)
    assert stat.S_ISREG(st.st_mode) and stat.S_IMODE(st.st_mode) == 0o600

    # Case 2: Symlink cache file -> ignored and rebuilt atomically as a real 0600 file.
    fixture_env["pid_log"].unlink(missing_ok=True)
    cache_file.unlink()
    target = fixture_env["tmp"] / "symlink-target.json"
    target.write_text(json.dumps(fake_payload), encoding="utf-8")
    target.chmod(0o600)
    cache_file.symlink_to(target)

    c1 = fixture_env["start"]()
    try:
        init_r, _ = c1.handshake()
        assert init_r["result"]["serverInfo"]["name"] == "fixture-mcp"
        assert len(fixture_env["read_pids"]()) == 1
    finally:
        assert c1.close()[0] == 0
    assert not cache_file.is_symlink() and stat.S_IMODE(cache_file.stat().st_mode) == 0o600

    # Case 3: World-writable / group-readable cache files -> ignored and rebuilt.
    for bad_mode in (0o666, 0o644, 0o640, 0o620):
        fixture_env["pid_log"].unlink(missing_ok=True)
        cache_file.write_text(json.dumps(fake_payload), encoding="utf-8")
        cache_file.chmod(bad_mode)
        c2 = fixture_env["start"]()
        try:
            init_r, _ = c2.handshake()
            assert init_r["result"]["serverInfo"]["name"] == "fixture-mcp"
            assert len(fixture_env["read_pids"]()) == 1
        finally:
            assert c2.close()[0] == 0
        assert stat.S_IMODE(cache_file.stat().st_mode) == 0o600

    # Case 4: World-writable cache dir (0777) -> ignored on load, tightened to 0700 on rebuild.
    fixture_env["pid_log"].unlink(missing_ok=True)
    cache_file.write_text(json.dumps(fake_payload), encoding="utf-8")
    cache_file.chmod(0o600)
    cache_dir.chmod(0o777)
    c3 = fixture_env["start"]()
    try:
        init_r, _ = c3.handshake()
        assert init_r["result"]["serverInfo"]["name"] == "fixture-mcp"
        assert len(fixture_env["read_pids"]()) == 1
    finally:
        assert c3.close()[0] == 0
    assert stat.S_IMODE(cache_dir.stat().st_mode) == 0o700

    # Case 5: User-owned symlink ancestor -> untrusted, ignored on load and never written through.
    fixture_env["pid_log"].unlink(missing_ok=True)
    real_parent = fixture_env["tmp"] / "real-parent"
    real_parent.mkdir(mode=0o700)
    (real_parent / "sub").mkdir(mode=0o700)
    (real_parent / "sub" / "fixture-srv.json").write_text(json.dumps(fake_payload), encoding="utf-8")
    (real_parent / "sub" / "fixture-srv.json").chmod(0o600)
    sym_parent = fixture_env["tmp"] / "sym-parent"
    sym_parent.symlink_to(real_parent)
    c_sym_anc = fixture_env["start"](cache_dir_override=sym_parent / "sub")
    try:
        init_r, _ = c_sym_anc.handshake()
        assert init_r["result"]["serverInfo"]["name"] == "fixture-mcp"
        assert len(fixture_env["read_pids"]()) == 1
    finally:
        assert c_sym_anc.close()[0] == 0

    # Case 6: Valid 0600 cache containing extra "command"/"argv" keys -> ignored/stripped, never executed.
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
        msgs = [c4.recv(), c4.recv()]
        call_r = next(m for m in msgs if m.get("id") == 80)
        assert "msg=cli-cmd-used" in call_r["result"]["content"][0]["text"]
    finally:
        assert c4.close()[0] == 0
    rebuilt = json.loads(cache_file.read_text(encoding="utf-8"))
    assert "command" not in rebuilt and "argv" not in rebuilt


def test_hardening_sanitize_path_unit():
    """LOW #1: unit test PATH sanitization directly without touching any launcher PATH."""
    mod = _load_mcp_lazy_module()
    dirty = os.pathsep.join(["", ".", "./node_modules/.bin", "relative/dir", "/usr/bin", "/bin", "/opt/../etc"])
    assert mod.sanitize_path(dirty) == os.pathsep.join(["/usr/bin", "/bin"])


def test_hardening_child_cwd_is_home_and_relative_path_stripped(fixture_env):
    """LOW #1: invoke via fixed sys.executable while preserving real PATH entries alongside dirty entries."""
    base_path = os.environ.get("PATH", "/usr/bin:/bin")
    dirty_path = os.pathsep.join(["", ".", "./node_modules/.bin", "relative/dir", base_path, "/opt/../etc"])
    client = fixture_env["start"](
        extra_env={"PATH": dirty_path},
        cwd=fixture_env["session_cwd"],
        via_python=True,
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
    assert "" not in observed["PATH"].split(os.pathsep)
    assert "." not in path_entries
    assert "./node_modules/.bin" not in path_entries
    assert "relative/dir" not in path_entries
    assert "/opt/../etc" not in path_entries
    assert all(os.path.isabs(p) and ".." not in p.split("/") for p in path_entries)


# --- Round 3 Adversary Regression Tests ---


def test_cancellation_during_lazy_startup_never_reaches_server(fixture_env):
    """Round 3 HIGH #1: call cancelled while lazy startup is held at a barrier never reaches the server."""
    c0 = fixture_env["start"]()
    c0.handshake()
    c0.close()
    fixture_env["pid_log"].unlink()

    init_started = fixture_env["tmp"] / "init_started.flag"
    init_release = fixture_env["tmp"] / "init_release.flag"
    call_log = fixture_env["tmp"] / "calls.jsonl"
    cancel_log = fixture_env["tmp"] / "cancels.jsonl"

    client = fixture_env["start"](extra_env={
        "FIXTURE_INIT_STARTED_FILE": str(init_started),
        "FIXTURE_INIT_RELEASE_FILE": str(init_release),
        "FIXTURE_CALL_LOG": str(call_log),
        "FIXTURE_CANCEL_LOG": str(cancel_log),
    })
    try:
        client.handshake()
        assert fixture_env["read_pids"]() == []

        # Trigger lazy startup with call id=200; server holds at init_started barrier.
        client.send({
            "jsonrpc": "2.0",
            "id": 200,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "cancelled-before-dispatch"}},
        })
        deadline = time.monotonic() + 5.0
        while not init_started.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert init_started.exists(), "child did not reach initialize barrier"

        # Cancel id=200 while startup is blocked at the barrier!
        client.send({
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": 200, "reason": "user cancelled"},
        })
        # Give reader thread a moment to record cancellation, then release the startup barrier.
        time.sleep(0.1)
        init_release.write_text("go\n", encoding="utf-8")

        # Send a second live call id=201 to prove child started cleanly and serves subsequent calls.
        client.send({
            "jsonrpc": "2.0",
            "id": 201,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "live-after-cancel"}},
        })
        resp = client.recv(timeout=5.0)
        assert resp["id"] == 201
        assert "msg=live-after-cancel" in resp["result"]["content"][0]["text"]

        # Verify cancelled call id=200 NEVER reached the server!
        logged_calls = [json.loads(ln) for ln in call_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert [c["id"] for c in logged_calls] == [201], f"cancelled call reached server: {logged_calls}"

        # Also verify in-flight cancellation forwards directly on the control path.
        client.send({
            "jsonrpc": "2.0",
            "id": 202,
            "method": "tools/call",
            "params": {"name": "slow", "arguments": {"seconds": 0.4}},
        })
        # Wait until server logs receipt of slow call 202, then send cancellation on control path.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            logged = [json.loads(ln) for ln in call_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if any(c["id"] == 202 for c in logged):
                break
            time.sleep(0.02)
        client.send({
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": 202},
        })
        # Wait for slow to reply, then verify server received the cancellation notification.
        _ = client.recv(timeout=5.0)
        # Send one more echo to flush stdin ordering before reading cancel_log.
        client.send({
            "jsonrpc": "2.0",
            "id": 203,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "flush"}},
        })
        assert client.recv(timeout=5.0)["id"] == 203
        cancels = [json.loads(ln) for ln in cancel_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert any(c.get("requestId") == 202 for c in cancels), f"in-flight cancel not forwarded: {cancels}"
    finally:
        assert client.close()[0] == 0


def test_eof_racing_child_spawn_before_publication_leaves_no_orphan(fixture_env):
    """Round 3 HIGH #2: shutdown racing between ChildProcess Popen and publication retires child cleanly."""
    import threading

    mod = _load_mcp_lazy_module()
    spawned_ev = threading.Event()
    release_ev = threading.Event()
    spawned_pids: list[int] = []

    class BarrierProxy(mod.LazyProxy):
        def _after_child_popen(self, child):
            spawned_pids.append(child.pid)
            spawned_ev.set()
            release_ev.wait(timeout=5.0)

    proxy = BarrierProxy(
        server_id="barrier-srv",
        child_argv=[sys.executable, str(fixture_env["server"])],
        idle_seconds=60.0,
        cache_dir=fixture_env["cache_dir"],
    )

    spawn_result: list[Any] = []
    t_spawn = threading.Thread(target=lambda: spawn_result.append(proxy._spawn_child_raw()))
    t_spawn.start()
    assert spawned_ev.wait(timeout=5.0), "spawn did not reach post-popen barrier"
    child_pid = spawned_pids[0]
    assert _pid_alive(child_pid)

    # Start shutdown while _spawn_child_raw is paused BEFORE publishing child!
    t_shut = threading.Thread(target=proxy.shutdown)
    t_shut.start()
    time.sleep(0.1)
    assert t_shut.is_alive(), "shutdown must wait for in-flight spawn instead of returning early"

    # Release spawn barrier: _spawn_child_raw must see self.stopping and immediately terminate child.
    release_ev.set()
    t_spawn.join(timeout=5.0)
    t_shut.join(timeout=5.0)
    assert not t_spawn.is_alive() and not t_shut.is_alive()
    assert spawn_result == [None]
    assert proxy.child is None
    assert not proxy.tearing_down
    assert not _pid_alive(child_pid), f"orphan child pid={child_pid} leaked when EOF raced spawn"


def test_nonfinite_json_in_tool_and_discovery_responses_never_strands_requests(fixture_env):
    """Round 3 HIGH #3: non-finite NaN/Infinity in tool or discovery responses returns -32603 and recovers."""
    c0 = fixture_env["start"]()
    c0.handshake()
    c0.close()
    fixture_env["pid_log"].unlink()

    # 1. Tool response containing NaN: must NOT strand id=300; returns -32603, retires child, next call succeeds.
    client = fixture_env["start"]()
    try:
        client.handshake()
        client.send({
            "jsonrpc": "2.0",
            "id": 300,
            "method": "tools/call",
            "params": {"name": "nan_result", "arguments": {}},
        })
        err_r = client.recv(timeout=5.0)
        assert err_r["id"] == 300 and err_r["error"]["code"] == -32603

        # Subsequent call respawns cleanly and works.
        client.send({
            "jsonrpc": "2.0",
            "id": 301,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "after-nan-tool"}},
        })
        ok_r = client.recv(timeout=5.0)
        assert ok_r["id"] == 301 and "msg=after-nan-tool" in ok_r["result"]["content"][0]["text"]

        # Client sending non-finite NaN on stdin gets -32700 Parse error and connection stays usable.
        assert client.proc.stdin is not None
        client.proc.stdin.write(b'{"jsonrpc":"2.0","id":302,"method":"ping","params":{"x":NaN}}\n')
        client.proc.stdin.flush()
        parse_err = client.recv(timeout=5.0)
        assert parse_err["error"]["code"] == -32700
    finally:
        assert client.close()[0] == 0

    # 2. Discovery response containing Infinity during on-demand startup: fails startup cleanly with -32603,
    #    retires child, and after fixing the server the next call succeeds cleanly!
    nan_tools_flag = fixture_env["tmp"] / "nan_tools.flag"
    nan_tools_flag.write_text("1\n", encoding="utf-8")
    c2 = fixture_env["start"](extra_env={"FIXTURE_NAN_TOOLS_FILE": str(nan_tools_flag)})
    try:
        c2.handshake()
        c2.send({
            "jsonrpc": "2.0",
            "id": 303,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "during-bad-discovery"}},
        })
        err_disc = c2.recv(timeout=5.0)
        assert err_disc["id"] == 303 and err_disc["error"]["code"] == -32603

        # Fix server discovery and verify next call succeeds cleanly.
        nan_tools_flag.unlink()
        c2.send({
            "jsonrpc": "2.0",
            "id": 304,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "recovered-discovery"}},
        })
        ok_disc = c2.recv(timeout=5.0)
        assert ok_disc["id"] == 304 and "msg=recovered-discovery" in ok_disc["result"]["content"][0]["text"]
    finally:
        assert c2.close()[0] == 0


def test_immediate_server_request_on_notifications_initialized_accepted(fixture_env):
    """Round 3 MEDIUM #1: gate tracks client's real notifications/initialized and opens before child write."""
    err_file = fixture_env["tmp"] / "init_roots_err.json"
    extra = {
        "FIXTURE_ASK_ROOTS_ON_INITIALIZED": "1",
        "FIXTURE_INIT_ROOTS_ERR_FILE": str(err_file),
    }

    # 1. Cold warm-up: child must NOT receive notifications/initialized or send roots/list until
    #    the client sends its real notifications/initialized!
    c1 = fixture_env["start"](extra_env=extra)
    try:
        c1.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {"roots": {}},
                "clientInfo": {"name": "lifecycle-client", "version": "1"},
            },
        })
        init_r = c1.recv(timeout=5.0)
        assert init_r["id"] == 1 and "result" in init_r

        # Pause briefly BEFORE sending notifications/initialized: proxy must NOT leak child traffic yet!
        assert c1.proc.stdout is not None
        ready, _, _ = select.select([c1.proc.stdout.fileno()], [], [], 0.25)
        assert not ready, "proxy leaked child message before client sent notifications/initialized"

        # Now client sends its real notifications/initialized -> child immediately sends roots/list!
        c1.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        roots_req = c1.recv(timeout=5.0)
        assert roots_req.get("method") == "roots/list" and str(roots_req.get("id", "")).startswith("srv-on-init-")
        c1.send({"jsonrpc": "2.0", "id": roots_req["id"], "result": {"roots": [{"uri": "file:///ws"}]}})

        c1.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools_r = c1.recv(timeout=5.0)
        assert tools_r["id"] == 2 and any(t["name"] == "echo" for t in tools_r["result"]["tools"])
        assert not err_file.exists(), f"child request on initialized was rejected: {err_file.read_text()}"
    finally:
        assert c1.close()[0] == 0

    # 2. On-demand startup: allow_upstream flips BEFORE writing notifications/initialized to child,
    #    so child's immediate roots/list is forwarded cleanly and never rejected with -32600!
    fixture_env["pid_log"].unlink()
    c2 = fixture_env["start"](extra_env=extra)
    try:
        c2.handshake()
        assert fixture_env["read_pids"]() == []
        c2.send({
            "jsonrpc": "2.0",
            "id": 400,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"msg": "init-gate-ok"}},
        })
        roots_req2 = c2.recv(timeout=5.0)
        assert roots_req2.get("method") == "roots/list" and str(roots_req2.get("id", "")).startswith("srv-on-init-")
        c2.send({"jsonrpc": "2.0", "id": roots_req2["id"], "result": {"roots": [{"uri": "file:///ws"}]}})
        call_r = c2.recv(timeout=5.0)
        assert call_r["id"] == 400 and "msg=init-gate-ok" in call_r["result"]["content"][0]["text"]
        assert not err_file.exists(), f"on-demand request on initialized was rejected: {err_file.read_text()}"
    finally:
        assert c2.close()[0] == 0


def test_cache_store_step_by_step_dir_fd_ancestry_validation(tmp_path: Path):
    """Round 3 MEDIUM #2: CacheStore pins every ancestor via dir_fd during creation and rejects untrusted parents."""
    mod = _load_mcp_lazy_module()
    payload = {
        "version": 1,
        "clientProtocolVersion": "2025-11-25",
        "initialize": {
            "protocolVersion": "2025-11-25",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "s", "version": "1"},
        },
        "tools": {"tools": []},
    }

    # 1. Nested non-existent dirs created via dir_fd with 0700 perms.
    nested = tmp_path / "deep_a" / "deep_b" / "mcp-lazy"
    store = mod.CacheStore(nested, "nested-srv")
    assert store.save(payload) is True
    assert stat.S_IMODE((tmp_path / "deep_a").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "deep_a" / "deep_b").stat().st_mode) == 0o700
    assert stat.S_IMODE(nested.stat().st_mode) == 0o700
    assert stat.S_IMODE((nested / "nested-srv.json").stat().st_mode) == 0o600
    assert store.load() == payload

    # 2. World-writable non-sticky ancestor rejected on both load and save.
    bad_parent = tmp_path / "world-parent"
    bad_parent.mkdir(mode=0o777)
    bad_parent.chmod(0o777)
    store_bad = mod.CacheStore(bad_parent / "sub", "bad-srv")
    assert store_bad.save(payload) is False
    assert store_bad.load() is None

    # 3. Symlink ancestor rejected on both load and save.
    real_dir = tmp_path / "real-target"
    real_dir.mkdir(mode=0o700)
    sym_dir = tmp_path / "sym-ancestor"
    sym_dir.symlink_to(real_dir)
    store_sym = mod.CacheStore(sym_dir / "sub", "sym-srv")
    assert store_sym.save(payload) is False
    assert store_sym.load() is None

    # 4. Path with '..' segment rejected.
    store_dotdot = mod.CacheStore(tmp_path / "deep_a" / ".." / "deep_a", "dot-srv")
    assert store_dotdot.save(payload) is False
    assert store_dotdot.load() is None
