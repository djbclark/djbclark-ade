"""Tests for bin/mcp-find (Carried #89 Phase 1): match order, verdicts, exit codes, secret safety."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "bin" / "mcp-find"
REGISTRY = REPO / "config" / "mcp-registry.toml"


def _run(*args: str, env_override: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CLAUDE", "CODEX", "CURSOR", "HERMES", "PI_", "GEMINI", "ANTIGRAVITY", "PASEO_PROVIDER"))
    }
    if env_override:
        env.update(env_override)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=30,
    )


def test_photos_matches_bezalel_prefix_with_adb_note():
    cp = _run("photos", "--client", "claude")
    assert cp.returncode == 0, cp.stderr
    assert "bezalel" in cp.stdout
    assert "photos:app-created-only" in cp.stdout
    assert "denied: ask the operator" in cp.stdout
    assert "adb pull" in cp.stdout.lower()


def test_imessage_exact_capability_ranks_before_notes_substring():
    cp = _run("imessage", "--client", "claude", "--json")
    assert cp.returncode == 0, cp.stderr
    data = json.loads(cp.stdout)
    ids = [m["id"] for m in data["matches"]]
    assert ids[0] == "bezalel"
    assert data["matches"][0]["match_tier"] == "exact_capability"
    assert "beeper" in ids
    beeper = next(m for m in data["matches"] if m["id"] == "beeper")
    assert beeper["match_tier"] == "substring"


def test_match_order_exact_then_prefix_then_substring(tmp_path):
    reg = tmp_path / "reg.toml"
    reg.write_text(
        """schema_version = 1

[[server]]
id = "sub-hit"
transport = "local-http"
url = "http://127.0.0.1:1/mcp"
owner = "local"
state = "shared-safe"
auth = { kind = "none", keys = [], store = "none" }
capabilities = ["other"]
expected = { claude = "user" }
notes = "mentions widget in notes"

[[server]]
id = "prefix-hit"
transport = "local-http"
url = "http://127.0.0.1:2/mcp"
owner = "local"
state = "shared-safe"
auth = { kind = "none", keys = [], store = "none" }
capabilities = ["widget:readonly"]
expected = { claude = "user" }

[[server]]
id = "exact-hit"
transport = "local-http"
url = "http://127.0.0.1:3/mcp"
owner = "local"
state = "shared-safe"
auth = { kind = "none", keys = [], store = "none" }
capabilities = ["widget"]
expected = { claude = "user" }
""",
        encoding="utf-8",
    )
    cp = _run("widget", "--registry", str(reg), "--json")
    assert cp.returncode == 0, cp.stderr
    data = json.loads(cp.stdout)
    assert [(m["id"], m["match_tier"]) for m in data["matches"]] == [
        ("exact-hit", "exact_capability"),
        ("prefix-hit", "prefix_capability"),
        ("sub-hit", "substring"),
    ]


def test_reachability_verdicts_all_states():
    # user -> callable
    cp = _run("memory", "--client", "claude", "--json")
    bm = next(m for m in json.loads(cp.stdout)["matches"] if m["id"] == "basic-memory")
    assert bm["verdict"] == "callable"

    # user-lazy -> callable (lazy...)
    cp = _run("browser", "--client", "claude", "--json")
    cdt = next(m for m in json.loads(cp.stdout)["matches"] if m["id"] == "chrome-devtools")
    assert cdt["verdict"].startswith("callable")
    assert "lazy" in cdt["verdict"]

    # on-demand -> on-demand: ...
    cp = _run("sprites", "--client", "claude", "--json")
    rfab = next(m for m in json.loads(cp.stdout)["matches"] if m["id"] == "rfab")
    assert rfab["verdict"].startswith("on-demand:")
    assert "ade-worker-run --mcp rfab" in rfab["verdict"]

    # denied -> denied: ask the operator (...)
    cp = _run("finance", "--client", "claude", "--json")
    bez = next(m for m in json.loads(cp.stdout)["matches"] if m["id"] == "bezalel")
    assert bez["verdict"].startswith("denied: ask the operator")
    assert "codex" in bez["verdict"]

    # absent in this client, present in others -> absent in this client: use ...
    cp = _run("arxiv", "--client", "claude", "--json")
    ax = next(m for m in json.loads(cp.stdout)["matches"] if m["id"] == "arxiv")
    assert ax["verdict"].startswith("absent in this client: use")
    assert "codex" in ax["verdict"]

    # absent everywhere with instead -> absent in this client: use graft CLI ...
    cp = _run("code-graph", "--client", "claude", "--json")
    gr = next(m for m in json.loads(cp.stdout)["matches"] if m["id"] == "graft")
    assert gr["verdict"].startswith("absent in this client: use")
    assert "graft" in gr["verdict"]


def test_client_auto_detection_from_env():
    cp = _run("browser", "--json", env_override={"CLAUDECODE": "1"})
    assert cp.returncode == 0
    assert json.loads(cp.stdout)["client"] == "claude"

    cp = _run("browser", "--json", env_override={"CODEX_THREAD_ID": "t-1"})
    assert cp.returncode == 0
    assert json.loads(cp.stdout)["client"] == "codex"

    cp = _run("browser", "--json", env_override={"PASEO_PROVIDER": "cursor/composer"})
    assert cp.returncode == 0
    assert json.loads(cp.stdout)["client"] == "cursor-agent"

    cp = _run("browser", "--json")
    assert cp.returncode == 0
    assert json.loads(cp.stdout)["client"] is None


def test_no_match_exits_1():
    cp = _run("nonexistent-capability-xyz")
    assert cp.returncode == 1
    assert "no server matches" in cp.stderr

    cp_json = _run("nonexistent-capability-xyz", "--json")
    assert cp_json.returncode == 1
    data = json.loads(cp_json.stdout)
    assert data["matches"] == []


@pytest.mark.parametrize(
    "args",
    [
        ("   ",),
        ("browser", "--client", "bad client!"),
        ("browser", "--registry", "/nonexistent/path/mcp-registry.toml"),
    ],
)
def test_bad_args_or_registry_exits_2(args):
    cp = _run(*args)
    assert cp.returncode == 2


def test_never_reads_client_configs_or_secrets(tmp_path):
    # Point HOME to a directory with corrupt/secret-filled client configs; mcp-find must ignore them.
    secret = "TOP-SECRET-NEVER-READ-999"
    (tmp_path / ".claude.json").write_text("{corrupt " + secret, encoding="utf-8")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text("bad = " + secret, encoding="utf-8")
    cp = _run("browser", "--client", "claude", "--json", env_override={"HOME": str(tmp_path)})
    assert cp.returncode == 0, cp.stderr
    assert secret not in cp.stdout and secret not in cp.stderr
