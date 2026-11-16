"""Provider contract and real Pi error-path tests; no external inference."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "pi-extensions/clinepass/index.mjs"


def test_subscription_catalog_and_registration():
    script = """
import provider from './pi-extensions/clinepass/index.mjs';
let registration;
provider({registerProvider:(name,config)=>registration={name,config}});
console.log(JSON.stringify(registration));
"""
    data = json.loads(subprocess.check_output(["node", "--input-type=module", "-e", script], cwd=ROOT))
    config = data["config"]
    assert data["name"] == "clinepass"
    assert config["baseUrl"] == "https://api.cline.bot/api/v1"
    assert config["api"] == "openai-completions"
    assert config["apiKey"] == "!sudo-secretspec get CLINE_API_KEY --reason pi-clinepass-request"
    assert config["headers"]["X-Response-Format"] == "openai"
    assert len(config["models"]) == 15
    assert len({m["id"] for m in config["models"]}) == 15
    assert all(m["id"].startswith("cline-pass/") and m["contextWindow"] > m["maxTokens"] > 0
               for m in config["models"])
    assert all(m["compat"]["maxTokensField"] == "max_tokens" for m in config["models"])


@pytest.mark.parametrize("failure", ["missing", 401, 402])
def test_pi_reports_credential_and_provider_failures(tmp_path, failure):
    pi = shutil.which("pi")
    if not pi:
        pytest.skip("real Pi CLI installed by pi-clinepass CI")
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(self.headers.get("Authorization"))
            self.send_response(failure if isinstance(failure, int) else 500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": {"message": "fixture authentication failure" if failure == 401
                                                 else "fixture subscription balance exhausted"}}).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    broker = bindir / "sudo-secretspec"
    broker.write_text("#!/bin/sh\n" + ("exit 1\n" if failure == "missing" else "printf fixture-key\n"))
    broker.chmod(0o700)
    wrapper = tmp_path / "provider.mjs"
    wrapper.write_text(f"import provider from {json.dumps(EXTENSION.as_uri())};\n"
                       f"export default pi => provider({{registerProvider:(name,config)=>pi.registerProvider(name,"
                       f"{{...config,baseUrl:'http://127.0.0.1:{server.server_port}/v1'}})}});\n")
    agent = tmp_path / "agent"
    agent.mkdir()
    settings = agent / "settings.json"
    before = '{"defaultProvider":"retain","extensions":[],"customSetting":"retain"}\n'
    settings.write_text(before)
    env = {**os.environ, "PI_CODING_AGENT_DIR": str(agent), "PATH": str(bindir) + os.pathsep + os.environ["PATH"]}
    env.pop("CLINE_API_KEY", None)
    try:
        result = subprocess.run([pi, "--no-extensions", "-e", str(wrapper), "--no-skills", "--no-context-files",
                                 "--no-mcp", "--no-tools", "--no-session", "--provider", "clinepass",
                                 "--model", "cline-pass/deepseek-v4.1-flash", "--mode", "json", "-p", "Reply OK"],
                                cwd=tmp_path, env=env, capture_output=True, text=True, timeout=45)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    output = result.stdout + result.stderr
    assert "fixture-key" not in output
    if failure == "missing":
        assert not calls
        assert "Failed to resolve" in output or "No API key" in output
    else:
        assert calls and all(key == "Bearer fixture-key" for key in calls)
        assert "fixture authentication failure" in output if failure == 401 else "fixture subscription balance exhausted" in output
    assert settings.read_text() == before
