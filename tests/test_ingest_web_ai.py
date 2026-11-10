"""Hermetic tests for skills/ingest-web-ai offline normalizer (Carried #23 spike).

No network, no home-dir reads, no S1/CAS writes. Fixtures under
tests/fixtures/ingest-web-ai/ are synthetic only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skills" / "ingest-web-ai" / "scripts" / "normalize_export.py"
FIXTURES = REPO / "tests" / "fixtures" / "ingest-web-ai"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")}
    # Refuse accidental proxy use; the script must not need the network.
    env["NO_PROXY"] = "*"
    cp = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(REPO),
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    if check and cp.returncode != 0:
        raise AssertionError(
            f"rc={cp.returncode}\nstdout:\n{cp.stdout}\nstderr:\n{cp.stderr}"
        )
    return cp


def _events(stdout: str) -> list[dict]:
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


def test_gemini_fixture_normalizes_two_events():
    cp = run(
        "--input",
        str(FIXTURES / "gemini-sample.json"),
        "--producer",
        "gemini-web",
    )
    events = _events(cp.stdout)
    assert len(events) == 2
    assert events[0]["producer"] == "gemini-web"
    assert events[0]["conversation_id"] == "gem-conv-001"
    assert events[0]["role"] == "user"
    assert events[1]["role"] == "assistant"  # model → assistant
    assert events[0]["schema"] == "ade.web-ai.event.v0"
    assert len(events[0]["content_sha256"]) == 64


def test_grok_fixture_normalizes_and_maps_author():
    cp = run(
        "--input",
        str(FIXTURES / "grok-sample.json"),
        "--producer",
        "grok-web",
    )
    events = _events(cp.stdout)
    assert len(events) == 2
    assert events[0]["role"] == "user"
    assert events[1]["role"] == "assistant"
    assert "VESTI" in events[1]["text"] or "Grok" in events[1]["text"]


def test_missing_input_exits_2():
    cp = run("--input", str(FIXTURES / "no-such.json"), check=False)
    assert cp.returncode == 2
    assert "normalize_export:" in cp.stderr


def test_atomic_output_write(tmp_path: Path):
    out = tmp_path / "out.jsonl"
    run(
        "--input",
        str(FIXTURES / "gemini-sample.json"),
        "--producer",
        "gemini-web",
        "--output",
        str(out),
    )
    assert out.is_file()
    assert not (tmp_path / "out.jsonl.tmp").exists()
    events = _events(out.read_text(encoding="utf-8"))
    assert len(events) == 2


def test_multi_conversation_export_without_ids_gets_distinct_locators(tmp_path: Path):
    """Codex P2: missing id/title/timestamp must not collapse sibling conversations.

    Two conversations in one export that lack ids, titles, and timestamps used
    to hash to the same conversation_id (identical producer/title/started/
    source_path), so message_id="{conv_id}:{idx}" collided and a deduping sink
    would drop unrelated turns. Ordinal + content fingerprint must keep the
    (producer, conversation_id, message_id) locators distinct.
    """
    export = {
        "conversations": [
            {
                "messages": [
                    {"role": "user", "text": "alpha-user-turn"},
                    {"role": "assistant", "text": "alpha-assistant-turn"},
                ]
            },
            {
                "messages": [
                    {"role": "user", "text": "beta-user-turn"},
                    {"role": "assistant", "text": "beta-assistant-turn"},
                ]
            },
        ]
    }
    path = tmp_path / "anonymous-multi.json"
    path.write_text(json.dumps(export), encoding="utf-8")
    cp = run("--input", str(path), "--producer", "unknown-web")
    events = _events(cp.stdout)
    assert len(events) == 4

    conv_ids = {ev["conversation_id"] for ev in events}
    assert len(conv_ids) == 2

    locators = {(ev["producer"], ev["conversation_id"], ev["message_id"]) for ev in events}
    assert len(locators) == 4

    texts_by_conv: dict[str, set[str]] = {}
    for ev in events:
        texts_by_conv.setdefault(ev["conversation_id"], set()).add(ev["text"])
    assert texts_by_conv[events[0]["conversation_id"]] == {
        "alpha-user-turn",
        "alpha-assistant-turn",
    }
    assert texts_by_conv[events[2]["conversation_id"]] == {
        "beta-user-turn",
        "beta-assistant-turn",
    }


def test_design_doc_exists():
    doc = REPO / "docs" / "ingest-web-ai.md"
    text = doc.read_text(encoding="utf-8")
    assert "Carried queue item **#23**" in text
    assert "Trust boundary" in text or "## D. Trust boundary" in text
    assert "No production capture" in text or "no production" in text.lower()
