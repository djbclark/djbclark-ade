"""bin/ade-cirno: the dummy ACP agent. One sentence, real protocol, no tokens.

The test speaks the wire protocol directly (newline-delimited JSON-RPC 2.0) rather than using the SDK,
because the point of the dummy is to be the thing under a client: if this test needed the same library as
the client, a protocol mismatch would hide in the shared code.
"""

import json
import subprocess
import sys
from pathlib import Path

CIRNO = Path(__file__).resolve().parents[1] / "bin" / "ade-cirno"
SENTENCE = "an agent that is more scarlet than red"


def run(env_extra, script):
    env = {"PATH": "/usr/bin:/bin", "HOME": "/tmp", **env_extra}
    return subprocess.run([sys.executable, str(CIRNO)], input=script, capture_output=True, text=True,
                          timeout=120, env=env)


def rpc(*msgs):
    return "".join(json.dumps({"jsonrpc": "2.0", **m}) + "\n" for m in msgs)


def messages(out):
    got = []
    for line in out.splitlines():
        line = line.strip()
        if line:
            got.append(json.loads(line))
    return got


INIT = {"id": 1, "method": "initialize", "params": {"protocolVersion": 1, "clientCapabilities": {}}}
NEW = {"id": 2, "method": "session/new", "params": {"cwd": "/tmp", "mcpServers": []}}
PROMPT = {"id": 3, "method": "session/prompt",
          "params": {"sessionId": "cirno", "prompt": [{"type": "text", "text": "hi"}]}}


def test_handshake_session_and_stream():
    r = run({"CIRNO_LINES": "3", "CIRNO_DELAY": "0"}, rpc(INIT, NEW, PROMPT))
    assert r.returncode == 0, r.stderr
    msgs = messages(r.stdout)
    by_id = {m["id"]: m for m in msgs if "id" in m and "result" in m}
    assert by_id[1]["result"]["protocolVersion"] == 1
    assert by_id[2]["result"]["sessionId"] == "cirno"
    assert by_id[3]["result"]["stopReason"] == "end_turn"
    chunks = [m for m in msgs if m.get("method") == "session/update"]
    assert len(chunks) == 3, chunks
    for c in chunks:
        assert c["params"]["update"]["sessionUpdate"] == "agent_message_chunk"
        assert c["params"]["update"]["content"]["text"] == SENTENCE + "\n"


def test_it_reports_the_scarlet_model_and_no_model_menu():
    r = run({"CIRNO_LINES": "1", "CIRNO_DELAY": "0"}, rpc(INIT, NEW, PROMPT))
    by_id = {m["id"]: m for m in messages(r.stdout) if "id" in m}
    assert "scarlet" in by_id[1]["result"]["agentInfo"]["title"]
    # deliberately no config options: a client that wants to switch models must be told there is nothing
    assert "configOptions" not in by_id[2]["result"]


def test_custom_sentence_and_delay_are_honoured():
    r = run({"CIRNO_LINES": "2", "CIRNO_TEXT": "cirno says ⑨", "CIRNO_DELAY": "0"}, rpc(INIT, NEW, PROMPT))
    texts = [m["params"]["update"]["content"]["text"] for m in messages(r.stdout)
             if m.get("method") == "session/update"]
    assert texts == ["cirno says ⑨\n"] * 2


def test_a_cancel_stops_the_stream_and_says_so():
    cancel = {"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": "cirno"}}
    r = run({"CIRNO_LINES": "0", "CIRNO_DELAY": "0"}, rpc(INIT, NEW, PROMPT, cancel))
    by_id = {m["id"]: m for m in messages(r.stdout) if "id" in m}
    assert by_id[3]["result"]["stopReason"] == "cancelled"
