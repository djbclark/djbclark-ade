"""Bounded stdio bridge for RFab's POST-based Streamable HTTP tool endpoint."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import http.client
import json
import math
import os
import select
import subprocess
import sys
import time

HOST = "api.rfab.ai"
PATH = "/api/mcp"
MAX_BYTES = 8 * 1024 * 1024
REQUEST_TIMEOUT = 120
METHODS = {"initialize", "notifications/initialized", "ping", "tools/list", "tools/call"}


class BridgeError(Exception):
    """A fixed, safe diagnostic. Never use an upstream error body as its text."""


def read_key(broker_bin: str | os.PathLike[str] = "sudo-secretspec") -> str:
    try:
        result = subprocess.run(
            [broker_bin, "get", "RFAB_API_KEY", "--reason", "mcp-rfab-request"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=15,
        )
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        raise BridgeError("RFAB_API_KEY could not be resolved") from None
    key = result.stdout.strip()
    if result.returncode or not key or any(not 33 <= ord(char) < 127 for char in key):
        raise BridgeError("RFAB_API_KEY could not be resolved")
    return key


def messages(fd: int, idle_timeout: float):
    """Yield NDJSON frames. Partial input cannot keep the bridge alive indefinitely."""
    pending = bytearray()
    deadline = time.monotonic() + idle_timeout
    while select.select([fd], [], [], max(0, deadline - time.monotonic()))[0]:
        chunk = os.read(fd, 65536)
        if not chunk:
            return
        pending.extend(chunk)
        while (end := pending.find(b"\n")) >= 0:
            if end > MAX_BYTES:
                raise BridgeError("MCP request exceeded the frame limit")
            yield bytes(pending[:end])
            del pending[:end + 1]
            deadline = time.monotonic() + idle_timeout
        if len(pending) > MAX_BYTES:
            raise BridgeError("MCP request exceeded the frame limit")
        if time.monotonic() >= deadline:
            return


def response_messages(response):
    if response.headers.get_content_type() != "text/event-stream":
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise BridgeError("RFab MCP response exceeded the frame limit")
        yield json.loads(body)
        return

    data = []
    remaining = MAX_BYTES
    while line := response.readline(remaining + 1):
        remaining -= len(line)
        if remaining < 0:
            raise BridgeError("RFab MCP response exceeded the frame limit")
        line = line.rstrip(b"\r\n")
        if not line and data:
            yield json.loads(b"\n".join(data))
            data.clear()
        elif line.startswith(b"data:"):
            data.append(line[5:].removeprefix(b" "))


class Bridge:
    def __init__(self, connect=http.client.HTTPSConnection, output=None, *, read_key=read_key):
        self.connect = connect
        self.read_key = read_key
        self.output = sys.stdout if output is None else output
        self.key = None
        self.session = None
        self.protocol = None

    def emit(self, message):
        encoded = json.dumps(message, ensure_ascii=False)
        if self.key:
            escaped = json.dumps(self.key, ensure_ascii=False)[1:-1]
            encoded = encoded.replace(escaped, "[redacted]")
        print(encoded, file=self.output, flush=True)

    @contextmanager
    def request(self, method, body=None, timeout=REQUEST_TIMEOUT):
        headers = {"Authorization": "Bearer " + self.key, "Accept": "application/json, text/event-stream"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        if self.protocol:
            headers["MCP-Protocol-Version"] = self.protocol
        connection = self.connect(HOST, timeout=timeout)
        try:
            connection.request(method, PATH, body=body, headers=headers)
            yield connection.getresponse()
        finally:
            connection.close()

    def forward(self, message):
        method = message.get("method")
        request_id = message.get("id")
        expects_result = "id" in message
        if not isinstance(method, str) or method not in METHODS:
            if expects_result and method is not None:
                self.emit({"jsonrpc": "2.0", "id": request_id,
                           "error": {"code": -32601, "message": "RFab MCP exposes tools only"}})
            return
        initializing = method == "initialize"
        try:
            if initializing:
                if self.protocol is not None:
                    raise BridgeError("RFab MCP session is already initialized")
                if not expects_result:
                    raise BridgeError("RFab MCP initialize requires a request id")
                # The remote server needs no access to local roots, client sampling or elicitation.
                params = message.get("params", {})
                message = {**message, "params": {**params, "capabilities": {}}}
                self.key = self.read_key()
            elif self.protocol is None:
                raise BridgeError("Initialize the RFab MCP session first")
            with self.request("POST", json.dumps(message).encode()) as response:
                if response.status == 202 and not expects_result:
                    return
                if response.status != 200:
                    raise BridgeError(f"RFab MCP HTTP {response.status}")
                for reply in response_messages(response):
                    if not isinstance(reply, dict) or reply.get("jsonrpc") != "2.0":
                        raise BridgeError("Invalid RFab MCP response")
                    if "method" in reply:
                        if reply["method"] == "notifications/progress" and "id" not in reply:
                            self.emit(reply)
                        continue
                    matching = expects_result and "id" in reply and reply["id"] == request_id
                    if not matching:
                        continue
                    if initializing and "result" in reply and "error" not in reply:
                        result = reply["result"]
                        version = result.get("protocolVersion")
                        if not isinstance(version, str) or not version:
                            raise BridgeError("RFab MCP initialization omitted the protocol version")
                        caps = result.get("capabilities", {})
                        if not isinstance(caps, dict):
                            raise BridgeError("Invalid RFab MCP capabilities")
                        result["capabilities"] = {"tools": caps["tools"]} if "tools" in caps else {}
                        self.session = response.headers.get("Mcp-Session-Id")
                        self.protocol = version
                    self.emit(reply)
                    return
                if expects_result:
                    raise BridgeError("RFab MCP response omitted the requested result")
        except (OSError, ValueError, TypeError, AttributeError, http.client.HTTPException, BridgeError) as exc:
            detail = str(exc) if isinstance(exc, BridgeError) else "RFab MCP transport failed"
            if expects_result:
                self.emit({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": detail}})
            else:
                print(f"ade-mcp-rfab: {detail}", file=sys.stderr)
        finally:
            if initializing and self.protocol is None:
                self.key = None

    def close(self):
        if self.session:
            try:
                with self.request("DELETE", timeout=3):
                    pass
            except (OSError, ValueError, http.client.HTTPException):
                pass
        self.key = self.session = self.protocol = None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--idle-timeout", type=float, default=300, metavar="SECONDS")
    parser.add_argument("--secretspec-bin", default="sudo-secretspec", metavar="PATH",
                        help="absolute path to the credential broker")
    args = parser.parse_args(argv)
    if not math.isfinite(args.idle_timeout) or args.idle_timeout <= 0:
        parser.error("--idle-timeout must be positive and finite")
    if args.secretspec_bin != "sudo-secretspec" and not os.path.isabs(args.secretspec_bin):
        parser.error("--secretspec-bin must be an absolute path")
    bridge = Bridge(read_key=lambda: read_key(args.secretspec_bin))
    try:
        for frame in messages(sys.stdin.fileno(), args.idle_timeout):
            if not frame.strip():
                continue
            try:
                message = json.loads(frame)
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    raise ValueError
            except ValueError:
                bridge.emit({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid MCP frame"}})
                continue
            bridge.forward(message)
    except BrokenPipeError:
        pass
    except BridgeError as exc:
        print(f"ade-mcp-rfab: {exc}", file=sys.stderr)
        return 1
    finally:
        bridge.close()
    return 0
