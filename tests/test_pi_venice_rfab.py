"""Manual Pi registration, provider wire behavior and task-scoped RFab MCP."""
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import ade_mcp_on_demand as on_demand  # noqa: E402
import ade_mcp_rfab as mcp  # noqa: E402

FIXTURE_KEY = "fixture-credential-for-this-test"
BRIDGE = ROOT / "bin/ade-mcp-rfab"


@pytest.mark.parametrize(("provider", "domain"), [("venice", "venice.ai"), ("rfab", "rfab.ai")])
def test_provider_registration(provider, domain):
    script = """
import { registerHooks } from "node:module";
registerHooks({
  resolve(specifier, context, next) {
    if (specifier === "@earendil-works/pi-ai") {
      return { url: "data:text/javascript,export function openAICompletionsApi() {}", shortCircuit: true };
    }
    return next(specifier, context);
  },
});
const { default: load } = await import(process.argv[1]);
load({ registerProvider: (provider, config) => console.log(JSON.stringify({ provider, config })) });
"""
    extension = ROOT / "pi-extensions" / provider / "index.mjs"
    result = subprocess.run(["node", "--input-type=module", "-e", script, extension.as_uri()],
                            cwd=ROOT, capture_output=True, check=True, text=True, timeout=20)
    registration = json.loads(result.stdout)
    config = registration["config"]
    assert registration["provider"] == provider
    assert "operator-gated" in config["name"]
    assert config["baseUrl"] == f"https://api.{domain}/api/v1"
    assert config["api"] == "openai-completions"
    assert config["apiKey"] == f"!sudo-secretspec get {provider.upper()}_API_KEY --reason pi-{provider}-request"
    assert len({m["id"] for m in config["models"]}) == len(config["models"]) == 5
    for model in config["models"]:
        assert model["contextWindow"] > model["maxTokens"] > 0
        assert set(model["cost"]) == {"input", "output", "cacheRead", "cacheWrite"}
        assert model["compat"]["maxTokensField"] == ("max_tokens" if provider == "venice" else "max_completion_tokens")


@pytest.fixture
def broker(tmp_path, monkeypatch):
    exe = tmp_path / "sudo-secretspec"
    exe.write_text(f"#!/bin/sh\nprintf '%s' '{FIXTURE_KEY}'\n")
    exe.chmod(0o700)
    for key in ("RFAB_API_KEY", "VENICE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    return exe


def write_fake_broker_error(broker):
    broker.write_text(f"#!/bin/sh\nprintf '%s' '{FIXTURE_KEY}' >&2\nexit 1\n")


@pytest.mark.parametrize(("provider", "model"), [
    ("venice", "openai-gpt-62-sol"),
    ("rfab", "openai:gpt-6.2-sol"),
])
@pytest.mark.parametrize("failure", ["missing", 401, 402])
def test_pi_error_paths(tmp_path, broker, provider, model, failure):
    output, calls = run_pi(tmp_path, broker, provider, model, failure)
    if failure == "missing":
        assert not calls
        assert "Failed to resolve" in output or "No API key" in output
    else:
        assert calls and all(row["auth"] and row["model"] == model for row in calls), output[-1800:]
        expected = f"RFab HTTP {failure}" if provider == "rfab" else f"fixture HTTP {failure}"
        assert expected in output


def test_rfab_pi_consumes_buffered_completion(tmp_path, broker):
    model = "openai:gpt-6.2-sol"
    output, calls = run_pi(tmp_path, broker, "rfab", model, 200)
    assert calls == [{"auth": True, "model": model, "stream": False, "streamOptions": False}], output[-1800:]
    assert "buffered fixture answer [redacted]" in output


def test_rfab_pi_completes_a_buffered_tool_round_trip(tmp_path, broker):
    (tmp_path / "data.txt").write_text("fixture-tool-nonce")
    output, calls = run_pi(tmp_path, broker, "rfab", "openai:gpt-6.2-sol", 200, use_tool=True)
    assert len(calls) == 2, output[-1800:]
    assert calls[1]["toolResult"] is True
    assert "buffered fixture answer [redacted]" in output


def run_pi(tmp_path, broker, provider, model, status, *, use_tool=False):
    pi = shutil.which("pi")
    if not pi:
        pytest.skip("real Pi CLI is installed by the Pi provider CI job")
    if status == "missing":
        broker.write_text("#!/bin/sh\nexit 1\n")
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.path == "/v1/chat/completions"
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append({
                "auth": self.headers.get("Authorization") == "Bearer " + FIXTURE_KEY,
                "model": body["model"], "stream": body["stream"], "streamOptions": "stream_options" in body,
            })
            code = status if isinstance(status, int) else 500
            if code == 200:
                message = {"role": "assistant", "content": "buffered fixture answer " + FIXTURE_KEY}
                finish = "stop"
                if use_tool and len(calls) == 1 and any(t["function"]["name"] == "read" for t in body.get("tools", [])):
                    message = {"role": "assistant", "content": None, "tool_calls": [{
                        "id": "call_fixture", "type": "function",
                        "function": {"name": "read", "arguments": '{"path":"data.txt"}'},
                    }]}
                    finish = "tool_calls"
                if use_tool and len(calls) == 2:
                    calls[-1]["toolResult"] = any(
                        m["role"] == "tool" and m["tool_call_id"] == "call_fixture"
                        and "fixture-tool-nonce" in str(m["content"]) for m in body["messages"]
                    )
                reply = {
                    "id": "fixture", "model": body["model"], "created": 1, "object": "chat.completion",
                    "choices": [{"index": 0, "finish_reason": finish, "message": message}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                }
            else:
                message = f"fixture HTTP {code}"
                if provider == "rfab":
                    message += " " + FIXTURE_KEY
                reply = {"error": {"message": message}}
            # Simulate a JSON representation that escapes one character of the echoed token.
            data = json.dumps(reply).replace(FIXTURE_KEY, r"\u0066" + FIXTURE_KEY[1:]).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    extension = ROOT / "pi-extensions" / provider / "index.mjs"
    wrapper = tmp_path / "fixture.mjs"
    agent = tmp_path / "agent"
    agent.mkdir()
    settings = agent / "settings.json"
    before = '{"extensions":[],"customSetting":"retain"}\n'
    settings.write_text(before)
    env = {**os.environ, "PI_CODING_AGENT_DIR": str(agent)}
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="pi-http-") as directory:
        if sys.platform == "darwin":
            # HTTP over an owned Unix socket keeps the Mac's TCP registry untouched.
            socket_path = str(Path(directory) / "http.sock")
            server = socketserver.UnixStreamServer(socket_path, Handler)
            transport = """
import { request as httpRequest } from "node:http";
import { openAICompletionsApi } from "@earendil-works/pi-ai";
async function socketFetch(input, init) {
  const req = new Request(input, init);
  const body = await req.text();
  return new Promise((resolve, reject) => {
    const call = httpRequest({
      socketPath: SOCKET_PATH, path: new URL(req.url).pathname, method: req.method,
      headers: { ...Object.fromEntries(req.headers), "content-length": Buffer.byteLength(body) },
      signal: req.signal,
    }, (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(chunk));
      response.on("error", reject);
      response.on("end", () => resolve(new Response(Buffer.concat(chunks),
        { status: response.statusCode, headers: response.headers })));
    });
    call.on("error", reject);
    call.end(body);
  });
}
const stream = (config) => (model, context, options) =>
  (config.streamSimple ?? openAICompletionsApi().streamSimple)(model, context, { ...options, fetch: socketFetch });
""".replace("SOCKET_PATH", json.dumps(socket_path))
            base_url = "http://127.0.0.1:1/v1"
        else:
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            transport = "const stream = (config) => config.streamSimple;\n"
            base_url = f"http://127.0.0.1:{server.server_port}/v1"
        broker_command = json.dumps("!" + shlex.quote(str(broker)))
        wrapper.write_text(
            f"import load from {json.dumps(extension.as_uri())};\n" + transport +
            """export default pi => load({ registerProvider(name, config) {
  if (!config.apiKey.startsWith("!sudo-secretspec ")) {
    throw new Error("fixture expected a sudo-secretspec command");
  }
""" + f"""  pi.registerProvider(name, {{
    ...config, baseUrl: {json.dumps(base_url)}, streamSimple: stream(config),
    apiKey: {broker_command} + config.apiKey.slice("!sudo-secretspec".length),
  }});
}} }});
"""
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            tool_args = ["--tools", "read"] if use_tool else ["--no-tools"]
            result = subprocess.run([pi, "--no-extensions", "-e", str(wrapper), "--no-skills", "--no-context-files",
                                     "--no-mcp", *tool_args, "--no-session", "--provider", provider,
                                     "--model", model, "--mode", "json", "-p", "Reply OK"],
                                    cwd=tmp_path, env=env, capture_output=True, text=True, timeout=45)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
    output = result.stdout + result.stderr
    assert FIXTURE_KEY not in output
    assert settings.read_text() == before
    return output, calls


def test_rfab_is_only_attached_by_explicit_worker_selection():
    registry = on_demand.load_registry()
    original = ["--provider", "codex"]
    assert on_demand.apply(original, [], lambda: None) == original
    profiles = [{"provider": "codex-mcp-rfab", "enabled": True, "status": "ready"}]
    result = on_demand.apply(original, ["rfab"], lambda: profiles, user_has=lambda *_: False)
    assert result == ["--provider", "codex-mcp-rfab"]
    assert on_demand.claude_config(registry, ["rfab"]) == {
        "mcpServers": {"rfab": {"type": "stdio", "command": "ade-mcp-rfab", "args": []}}
    }


@pytest.mark.parametrize("eof", [True, False])
def test_bridge_exits_on_eof_or_after_idle_without_resolving_secret(tmp_path, broker, eof):
    marker = tmp_path / "called"
    broker.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
    with subprocess.Popen([str(BRIDGE), "--secretspec-bin", str(broker), "--idle-timeout", "0.2"], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        try:
            if eof:
                process.stdin.close()
            assert process.wait(timeout=5) == 0
            assert process.stdout.read() == process.stderr.read() == b""
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    assert not marker.exists()


def test_bridge_broker_error_is_redacted(broker):
    write_fake_broker_error(broker)
    result = subprocess.run([str(BRIDGE), "--secretspec-bin", str(broker)],
                            input='{"jsonrpc":"2.0","id":7,"method":"initialize"}\n',
                            capture_output=True, text=True, check=True, timeout=20)
    reply = json.loads(result.stdout)
    assert reply["id"] == 7
    assert reply["error"]["message"] == "RFAB_API_KEY could not be resolved"
    assert FIXTURE_KEY not in result.stdout + result.stderr


def test_bridge_forwards_json_sse_and_closes_its_remote_session(broker):
    from email.message import Message

    requests = []
    closed = []
    output = io.StringIO()

    class Response(io.BytesIO):
        def __init__(self, status, content=b"", media="application/json", session=None):
            super().__init__(content)
            self.status = status
            self.headers = Message()
            self.headers["Content-Type"] = media
            if session:
                self.headers["Mcp-Session-Id"] = session

    class Connection:
        def __init__(self, host, timeout):
            assert host == "api.rfab.ai"

        def request(self, method, path, body, headers):
            assert path == "/api/mcp"
            assert headers["Authorization"] == "Bearer " + FIXTURE_KEY
            requests.append((method, json.loads(body) if body else None, headers))

        def getresponse(self):
            method, body, headers = requests[-1]
            if method == "DELETE":
                assert headers["Mcp-Session-Id"] == "test-session"
                return Response(204)
            if body["method"] == "initialize":
                assert "MCP-Protocol-Version" not in headers
                return Response(200, b'{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-11-25"}}',
                                session="test-session")
            assert headers["MCP-Protocol-Version"] == "2025-11-25"
            assert headers["Mcp-Session-Id"] == "test-session"
            if body["method"] == "notifications/initialized":
                return Response(202)
            if body["id"] == 3:
                return Response(401, FIXTURE_KEY.encode())
            event = {"jsonrpc": "2.0", "id": 2, "result": {"text": FIXTURE_KEY}}
            request = {"jsonrpc": "2.0", "id": "untrusted", "method": "roots/list"}
            data = f"data: {json.dumps(request)}\n\ndata: {json.dumps(event)}\n\n"
            return Response(200, data.encode(), "text/event-stream")

        def close(self):
            closed.append(True)

    bridge = mcp.Bridge(connect=Connection, output=output, read_key=lambda: mcp.read_key(broker))
    bridge.forward({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"capabilities": {"roots": {}, "sampling": {}, "elicitation": {}}}})
    bridge.forward({"jsonrpc": "2.0", "method": "notifications/initialized"})
    bridge.forward({"jsonrpc": "2.0", "id": "untrusted", "result": {"roots": ["file:///private"]}})
    bridge.forward({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    bridge.forward({"jsonrpc": "2.0", "id": 3, "method": "tools/call"})
    bridge.close()
    assert len(closed) == len(requests) == 5
    assert [req[0] for req in requests] == ["POST", "POST", "POST", "POST", "DELETE"]
    assert requests[0][1]["params"]["capabilities"] == {}
    assert bridge.key is None
    assert FIXTURE_KEY not in output.getvalue()
    init, listed, failed = map(json.loads, output.getvalue().splitlines())
    assert init["id"] == 1
    assert listed["result"]["text"] == "[redacted]"
    assert failed["error"]["message"] == "RFab MCP HTTP 401"


@pytest.mark.parametrize(("status", "reply"), [
    (401, {}),
    (200, {"error": {"code": -32000, "message": FIXTURE_KEY}}),
    (200, {"result": {"protocolVersion": "2025-11-25", "capabilities": None}}),
])
def test_failed_initialize_drops_key_and_blocks_tools_list(monkeypatch, status, reply):
    from contextlib import contextmanager
    from email.message import Message

    requests = []
    output = io.StringIO()

    @contextmanager
    def request(method, body):
        requests.append((method, json.loads(body)))
        response = io.BytesIO(json.dumps({"jsonrpc": "2.0", "id": 1, **reply}).encode())
        response.status = status
        response.headers = Message()
        with response:
            yield response

    bridge = mcp.Bridge(output=output, read_key=lambda: FIXTURE_KEY)
    monkeypatch.setattr(bridge, "request", request)
    bridge.forward({"jsonrpc": "2.0", "method": "initialize", "id": 1})
    assert bridge.key is None and bridge.protocol is None and bridge.session is None
    bridge.forward({"jsonrpc": "2.0", "method": "tools/list", "id": 2})
    assert len(requests) == 1
    assert FIXTURE_KEY not in output.getvalue()
    failed, refused = map(json.loads, output.getvalue().splitlines())
    assert "error" in failed
    assert refused["error"]["message"] == "Initialize the RFab MCP session first"
