#!/usr/bin/env python3
"""mcp_call_as.py SOCKET PASSWORD_FILE TOOL JSON_ARGS [CALLER_AGENT_ID]: call one tool on a Paseo daemon's agent MCP endpoint (/mcp/agents)
over its Unix socket (streamable HTTP, JSON-RPC), the way an agent's injected `paseo` MCP server would. With CALLER_AGENT_ID the request goes to
/mcp/agents?callerAgentId=ID, the URL the daemon injects into that agent (checked 2026-11-02, bootstrap's `${mcpBaseUrl}?callerAgentId=${agentId}`),
so the call is agent-scoped: create_agent sets lineage and notifyOnFinish registers a finish subscription for that caller.
(Superset of lib/mcp_call.py from branch d1-t5-card; kept as its own file so the two branches merge without a conflict.)

Why it exists (checked 2026-11-02, paseo 0.15.0-beta.1, bootstrap.js createAgentMcpBaseUrl): the daemon injects the `paseo`
MCP server into its agents ONLY when its listener is TCP. The isolated test daemon listens on a Unix socket (decision 1),
so its agents never see paseo MCP tools; this script reaches the same endpoint directly instead. Auth is the test
daemon's own password as a bearer token (the endpoint accepts it); the file is read here, never put on argv.

Prints one JSON object: {"isError": bool, "structuredContent": ..., "text": ...}. Exit 0 if the call returned, 1 on a
transport/protocol error (message on stderr), 2 on usage.
"""
import http.client
import json
import socket
import sys


class UnixConn(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost", timeout=30)
        self._path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(30)
        self.sock.connect(self._path)


def post(sock, headers, body, path="/mcp/agents"):
    conn = UnixConn(sock)
    conn.request("POST", path, body=json.dumps(body), headers=headers)
    resp = conn.getresponse()
    raw = resp.read().decode("utf-8", "replace")
    sid = resp.getheader("mcp-session-id")
    status = resp.status
    conn.close()
    payload = None
    if "event-stream" in (resp.getheader("content-type") or ""):
        for line in raw.splitlines():
            if line.startswith("data:"):
                payload = json.loads(line[5:].strip())
    elif raw.strip():
        payload = json.loads(raw)
    return status, sid, payload, raw


def main(argv):
    if len(argv) not in (5, 6):
        print(__doc__, file=sys.stderr)
        return 2
    sock, pwfile, tool, args_json = argv[1:5]
    path = "/mcp/agents" + ("?callerAgentId=" + argv[5] if len(argv) == 6 else "")
    args = json.loads(args_json)
    password = open(pwfile).read().strip()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": "Bearer " + password,
    }
    status, sid, payload, raw = post(sock, headers, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "d1-05-probe", "version": "1"}}}, path)
    if status != 200 or not payload or "result" not in payload:
        print("initialize failed: http %s %s" % (status, raw[:300]), file=sys.stderr)
        return 1
    if sid:
        headers["Mcp-Session-Id"] = sid
    post(sock, headers, {"jsonrpc": "2.0", "method": "notifications/initialized"}, path)
    status, _, payload, raw = post(sock, headers, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool, "arguments": args}}, path)
    if status != 200 or payload is None:
        print("tools/call failed: http %s %s" % (status, raw[:300]), file=sys.stderr)
        return 1
    if "error" in payload:
        print(json.dumps({"isError": True, "rpcError": payload["error"]}))
        return 0
    result = payload.get("result", {})
    text = " ".join(c.get("text", "") for c in result.get("content", []) if isinstance(c, dict))
    print(json.dumps({"isError": bool(result.get("isError")), "structuredContent": result.get("structuredContent"), "text": text[:500]}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
