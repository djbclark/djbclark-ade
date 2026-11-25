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
def test_provider_registration(tmp_path, provider, domain):
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
await load({
  registerProvider: (provider, config) =>
    console.log(JSON.stringify({ provider, config, hasRefresh: typeof config.refreshModels === "function" })),
});
"""
    extension = ROOT / "pi-extensions" / provider / "index.mjs"
    env = {**os.environ, "PI_CODING_AGENT_DIR": str(tmp_path), "PI_VENICE_DISABLE_DISCOVERY": "1"}
    result = subprocess.run(["node", "--input-type=module", "-e", script, extension.as_uri()],
                            cwd=ROOT, env=env, capture_output=True, check=True, text=True, timeout=20)
    registration = json.loads(result.stdout)
    config = registration["config"]
    assert registration["provider"] == provider
    assert registration["hasRefresh"] is False
    assert "operator-gated" in config["name"]
    assert config["baseUrl"] == f"https://api.{domain}/api/v1"
    assert config["api"] == "openai-completions"
    assert config["apiKey"] == f"!sudo-secretspec get {provider.upper()}_API_KEY --reason pi-{provider}-request"
    assert len({m["id"] for m in config["models"]}) == len(config["models"]) == 5
    for model in config["models"]:
        assert model["contextWindow"] > model["maxTokens"] > 0
        assert set(model["cost"]) == {"input", "output", "cacheRead", "cacheWrite"}
        assert model["compat"]["maxTokensField"] == ("max_tokens" if provider == "venice" else "max_completion_tokens")


def test_venice_offline_factory_skips_network_discovery(tmp_path):
    extension = ROOT / "pi-extensions/venice/index.mjs"
    script = """
import assert from "node:assert/strict";
let fetchCalls = 0;
globalThis.fetch = async () => {
  fetchCalls += 1;
  throw new Error("network should not be called when PI_OFFLINE=1");
};
const { default: load } = await import(process.argv[1]);
let registered = null;
await load({ registerProvider: (provider, config) => { registered = { provider, config }; } });
assert.equal(fetchCalls, 0);
assert.equal(registered.provider, "venice");
assert.equal(registered.config.models.length, 5);
assert.equal("refreshModels" in registered.config, false);
console.log("ok");
"""
    env = {**os.environ, "PI_CODING_AGENT_DIR": str(tmp_path), "PI_OFFLINE": "1"}
    env.pop("PI_VENICE_DISABLE_DISCOVERY", None)
    result = subprocess.run(["node", "--input-type=module", "-e", script, extension.as_uri()],
                            cwd=ROOT, env=env, capture_output=True, check=True, text=True, timeout=20)
    assert result.stdout.strip() == "ok"


def test_venice_pi_list_models_never_invokes_broker(tmp_path, broker):
    pi = shutil.which("pi")
    if not pi:
        pytest.skip("real Pi CLI is installed by the Pi provider CI job")
    marker = tmp_path / "broker-called"
    broker.write_text(f"#!/bin/sh\ntouch '{marker}'\nprintf '%s' '{FIXTURE_KEY}'\n")
    extension = ROOT / "pi-extensions/venice/index.mjs"
    wrapper = tmp_path / "venice-wrapper.mjs"
    broker_command = json.dumps("!" + shlex.quote(str(broker)))
    wrapper.write_text(
        f"import load from {json.dumps(extension.as_uri())};\n"
        "export default pi => load({ registerProvider(name, config) {\n"
        f"  pi.registerProvider(name, {{ ...config, apiKey: {broker_command} + config.apiKey.slice('!sudo-secretspec'.length) }});\n"
        "} });\n"
    )
    agent = tmp_path / "agent"
    agent.mkdir()
    env = {**os.environ, "PI_CODING_AGENT_DIR": str(agent), "PI_OFFLINE": "1"}
    result = subprocess.run([pi, "--no-extensions", "-e", str(wrapper), "--list-models"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, check=True, timeout=30)
    assert "openai-gpt-62-sol" in result.stdout
    assert not marker.exists()


def test_venice_dynamic_catalog_cache_and_fallback(tmp_path):
    catalog_mod = ROOT / "pi-extensions/venice/catalog.mjs"
    fallback_path = ROOT / "pi-extensions/venice/models.json"
    script = r"""
import assert from "node:assert/strict";
import { lstat, readFile, symlink, writeFile } from "node:fs/promises";
import { join } from "node:path";

const mod = await import(process.argv[1]);
const fallback = JSON.parse(await readFile(process.argv[2], "utf8"));
const tmpDir = process.argv[3];
const cachePath = join(tmpDir, "cache", "venice-models.json");

// Tilde expansion in PI_CODING_AGENT_DIR matches Pi's getAgentDir().
assert.equal(
  mod.resolveCachePath({ PI_CODING_AGENT_DIR: "~/custom-pi" }, "/Users/example"),
  "/Users/example/custom-pi/cache/venice-models.json",
);
assert.equal(
  mod.resolveCachePath({ PI_CODING_AGENT_DIR: "~" }, "/Users/example"),
  "/Users/example/cache/venice-models.json",
);

const samplePayload = {
  data: [
    {
      id: "abliteration-abliterated-model-large-v2",
      type: "text",
      context_length: 1000000,
      model_spec: {
        name: "Abliterated \u202eLarge V2\n",
        offline: false,
        availableContextTokens: 1000000,
        maxCompletionTokens: 32768,
        capabilities: {
          supportsReasoning: true,
          supportsReasoningEffort: "false",
          supportsVision: "true",
        },
        pricing: {
          input: { usd: 3 },
          output: { usd: 5 },
          cache_input: { usd: 0.3 },
        },
      },
    },
    {
      id: "alpha-vision",
      type: "text",
      model_spec: {
        name: "Alpha Vision",
        availableContextTokens: 65536,
        maxCompletionTokens: 999999,
        capabilities: {
          supportsReasoning: false,
          supportsReasoningEffort: true,
          supportsVision: true,
        },
        pricing: {
          input: { usd: 1.5 },
          output: { usd: 4.5 },
          cache_input: { usd: 0.1 },
          cache_write: { usd: 0.2 },
        },
      },
    },
    { id: "alpha-vision", type: "text", context_length: 8192 },
    { id: "offline-model", type: "text", context_length: 8192, model_spec: { offline: true } },
    { id: "image-gen", type: "image", context_length: 8192 },
    { id: "bad id with space", type: "text", context_length: 8192 },
    { id: "zero-ctx", type: "text", context_length: 0 },
    { id: "unsafe-ctx", type: "text", context_length: 1e30 },
    { id: "x".repeat(129), type: "text", context_length: 8192 },
  ],
};

// 1. Live fetch normalizes, enforces exact booleans, strips bidi/controls, clamps, sorts,
// sends no Authorization, and writes cache atomically (0600).
const calls = [];
const okFetch = async (url, init) => {
  calls.push({ url, headers: init?.headers ?? {} });
  return new Response(JSON.stringify(samplePayload), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
};
const t0 = 1_700_000_000_000;
const loaded = await mod.loadVeniceModels({
  fallbackModels: fallback,
  cachePath,
  fetchImpl: okFetch,
  now: t0,
  env: {},
});
assert.equal(calls.length, 1);
assert.equal(calls[0].url, mod.VENICE_MODELS_URL);
assert.equal("Authorization" in calls[0].headers, false);
assert.deepEqual(
  loaded.map((m) => m.id),
  ["abliteration-abliterated-model-large-v2", "alpha-vision"],
);
const ablit = loaded[0];
assert.equal(ablit.name, "Abliterated Large V2");
assert.equal(ablit.reasoning, true);
assert.deepEqual(ablit.input, ["text"]);
assert.equal(ablit.contextWindow, 1000000);
assert.equal(ablit.maxTokens, 32768);
assert.deepEqual(ablit.cost, { input: 3, output: 5, cacheRead: 0.3, cacheWrite: 0 });
assert.deepEqual(ablit.compat, {
  maxTokensField: "max_tokens",
  supportsDeveloperRole: false,
  supportsReasoningEffort: false,
});
const alpha = loaded[1];
assert.equal(alpha.maxTokens, 65535);
assert.deepEqual(alpha.input, ["text", "image"]);
assert.equal(alpha.compat.supportsReasoningEffort, true);
const st = await lstat(cachePath);
assert.equal(st.mode & 0o777, 0o600);

// 2. Fresh cache hit performs zero network calls (explicit counter, not swallowed throw).
let freshFetchCount = 0;
const fromFreshCache = await mod.loadVeniceModels({
  fallbackModels: fallback,
  cachePath,
  fetchImpl: async () => {
    freshFetchCount += 1;
    return new Response("{}", { status: 500 });
  },
  now: t0 + mod.CACHE_FRESH_TTL_MS - 1000,
  env: {},
});
assert.equal(freshFetchCount, 0);
assert.deepEqual(fromFreshCache, loaded);

// 3. forceRefresh bypasses fresh cache TTL when allowNetwork=true; respects allowNetwork=false.
let refreshCount = 0;
const refreshed = await mod.loadVeniceModels({
  fallbackModels: fallback,
  cachePath,
  forceRefresh: true,
  allowNetwork: true,
  fetchImpl: async () => {
    refreshCount += 1;
    return new Response(
      JSON.stringify({ data: [samplePayload.data[0]] }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  },
  now: t0 + 1000,
  env: {},
});
assert.equal(refreshCount, 1);
assert.deepEqual(refreshed.map((m) => m.id), ["abliteration-abliterated-model-large-v2"]);

let offlineRefreshCount = 0;
const offlineRefresh = await mod.loadVeniceModels({
  fallbackModels: fallback,
  cachePath,
  forceRefresh: true,
  allowNetwork: false,
  fetchImpl: async () => {
    offlineRefreshCount += 1;
    return new Response("{}", { status: 500 });
  },
  now: t0 + 2000,
  env: {},
});
assert.equal(offlineRefreshCount, 0);
assert.deepEqual(offlineRefresh.map((m) => m.id), ["abliteration-abliterated-model-large-v2"]);

// 4. Stale cache (> TTL, <= max stale) falls back to stale cache on HTTP error and cancels error body.
let staleFetchCount = 0;
const fromStaleFallback = await mod.loadVeniceModels({
  fallbackModels: fallback,
  cachePath,
  fetchImpl: async () => {
    staleFetchCount += 1;
    return new Response("err", { status: 503 });
  },
  now: t0 + mod.CACHE_FRESH_TTL_MS + 60_000,
  env: {},
});
assert.equal(staleFetchCount, 1);
assert.deepEqual(fromStaleFallback.map((m) => m.id), ["abliteration-abliterated-model-large-v2"]);

// 5. Future-dated cache (> 60 s ahead) is rejected, and slightly future (< 60 s) is not fresh.
const futurePath = join(tmpDir, "cache", "future.json");
await mod.writeCachedCatalog(futurePath, samplePayload, t0 + 120_000);
assert.equal(await mod.readCachedCatalog(futurePath, { now: t0 }), null);
await mod.writeCachedCatalog(futurePath, samplePayload, t0 + 5_000);
const slightFuture = await mod.readCachedCatalog(futurePath, { now: t0 });
assert.equal(slightFuture?.fresh, false);

// 6. Expired cache (> 7 days) falls back to static fallback when offline.
const fromStaticAfterExpiry = await mod.loadVeniceModels({
  fallbackModels: fallback,
  cachePath,
  fetchImpl: async () => {
    throw new Error("offline");
  },
  now: t0 + mod.CACHE_MAX_STALE_MS + 60_000,
  env: {},
});
assert.deepEqual(fromStaticAfterExpiry, fallback);

// 7. Oversized response is rejected and falls back cleanly without writing cache.
const oversizedCache = join(tmpDir, "cache", "oversized.json");
const fromOversized = await mod.loadVeniceModels({
  fallbackModels: fallback,
  cachePath: oversizedCache,
  maxBytes: 128,
  fetchImpl: async () => new Response(JSON.stringify(samplePayload), { status: 200 }),
  now: t0,
  env: {},
});
assert.deepEqual(fromOversized, fallback);

// 8. Symlink cache file is rejected via O_NOFOLLOW.
const targetFile = join(tmpDir, "target.json");
const linkPath = join(tmpDir, "link-cache.json");
await writeFile(targetFile, JSON.stringify({ schemaVersion: 1, fetchedAt: t0, body: samplePayload }));
await symlink(targetFile, linkPath);
assert.equal(await mod.readCachedCatalog(linkPath, { now: t0 }), null);

console.log("ok");
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, catalog_mod.as_uri(), str(fallback_path), str(tmp_path)],
        cwd=ROOT, capture_output=True, check=True, text=True, timeout=20,
    )
    assert result.stdout.strip() == "ok"


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
    env = {**os.environ, "PI_CODING_AGENT_DIR": str(agent), "PI_VENICE_DISABLE_DISCOVERY": "1"}
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
