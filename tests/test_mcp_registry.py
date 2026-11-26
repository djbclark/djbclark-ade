"""Tests for config/mcp-registry.toml and bin/mcp-registry (Carried #89 Phase 1)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "bin" / "mcp-registry"
REGISTRY = REPO / "config" / "mcp-registry.toml"
DOC = REPO / "docs" / "mcp-on-demand.md"

sys.path.insert(0, str(REPO / "bin"))
import ade_client_wiring as cw  # noqa: E402


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_canonical_registry_is_valid_against_tui_roster():
    tuis = cw.tui_roster(REPO)
    rows = cw.load_registry(REGISTRY, tuis=tuis)
    ids = {r["id"] for r in rows}
    assert {"basic-memory", "firecrawl", "graft", "chrome-devtools", "rfab", "bezalel", "paseo"} <= ids
    by_id = {r["id"]: r for r in rows}
    assert by_id["graft"]["expected"] == {"claude": "absent", "codex": "absent"}
    assert by_id["chrome-devtools"]["expected"] == {"claude": "user-lazy", "codex": "user-lazy"}
    assert by_id["rfab"]["expected"] == {"claude": "on-demand", "codex": "on-demand"}
    assert by_id["bezalel"]["expected"]["claude"] == "denied"
    assert "photos:app-created-only" in by_id["bezalel"]["capabilities"]
    assert "adb" in by_id["bezalel"].get("instead", "").lower()


def test_legacy_mcp_clients_toml_is_removed():
    assert not (REPO / "config" / "mcp-clients.toml").exists()


def test_registry_contains_no_secret_fields_or_literal_tokens():
    text = REGISTRY.read_text(encoding="utf-8")
    for forbidden in ("Bearer ", "sk-", "fc-", "ghp_", "x-api-key ="):
        assert forbidden not in text
    rows = cw.load_registry(REGISTRY)
    for row in rows:
        assert not cw.FORBIDDEN_SERVER_KEYS.intersection(row.keys())
        for key in row["auth"]["keys"]:
            assert cw.SAFE_AUTH_KEY.match(key)


def test_mcp_registry_md_renders_table_with_markers():
    cp = _run("--md")
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout.startswith("<!-- mcp-registry:start -->\n")
    assert cp.stdout.endswith("<!-- mcp-registry:end -->\n")
    assert "| `basic-memory` |" in cp.stdout
    assert "| `chrome-devtools` |" in cp.stdout
    assert "| `graft` |" in cp.stdout
    assert "| `rfab` |" in cp.stdout
    assert "| `bezalel` |" in cp.stdout
    assert "| lazy | lazy |" in cp.stdout
    assert "| absent | absent |" in cp.stdout


def test_mcp_registry_check_passes_against_repo_doc():
    cp = _run("--check")
    assert cp.returncode == 0, cp.stderr


def test_mcp_registry_check_detects_stale_doc(tmp_path):
    stale = tmp_path / "mcp-on-demand.md"
    stale.write_text(
        "# Doc\n<!-- mcp-registry:start -->\n| stale |\n<!-- mcp-registry:end -->\n",
        encoding="utf-8",
    )
    cp = _run("--check", "--doc", str(stale))
    assert cp.returncode == 1
    assert "differs" in cp.stderr


def test_mcp_registry_check_missing_markers_exits_2(tmp_path):
    doc = tmp_path / "nomarkers.md"
    doc.write_text("# Doc with no markers\n", encoding="utf-8")
    cp = _run("--check", "--doc", str(doc))
    assert cp.returncode == 2
    assert "markers" in cp.stderr


def test_mcp_registry_json_outputs_validated_servers():
    cp = _run("--json")
    assert cp.returncode == 0, cp.stderr
    payload = json.loads(cp.stdout)
    assert payload["schema_version"] == 1
    assert any(s["id"] == "rfab" for s in payload["servers"])


@pytest.mark.parametrize(
    "toml_body,err_sub",
    [
        ('schema_version = 2\n[[server]]\nid = "a"\n', "schema_version"),
        ('schema_version = 1\n', "no [[server]]"),
        (
            'schema_version = 1\n[[server]]\nid = "a"\ntransport = "local-http"\n'
            'url = "http://127.0.0.1:1/mcp"\nowner = "x"\nstate = "shared-safe"\n'
            'auth = { kind = "none", keys = [], store = "none" }\n'
            'capabilities = ["cap"]\nexpected = { claude = "user" }\nenv = { SECRET = "1" }\n',
            "forbidden secret-bearing",
        ),
        (
            'schema_version = 1\n[[server]]\nid = "a"\ntransport = "local-http"\n'
            'url = "http://127.0.0.1:1/mcp"\nowner = "x"\nstate = "shared-safe"\n'
            'auth = { kind = "bearer", keys = ["Bearer secret-val"], store = "none" }\n'
            'capabilities = ["cap"]\nexpected = { claude = "user" }\n',
            "auth.keys",
        ),
        (
            'schema_version = 1\n[[server]]\nid = "a"\ntransport = "local-http"\n'
            'url = "http://127.0.0.1:1/mcp"\nowner = "x"\nstate = "shared-safe"\n'
            'auth = { kind = "none", keys = [], store = "none" }\n'
            'capabilities = ["cap"]\nexpected = { claude = "user-lazy" }\n',
            "user-lazy",
        ),
        (
            'schema_version = 1\n[[server]]\nid = "a"\ntransport = "local-http"\n'
            'url = "http://127.0.0.1:1/mcp"\nowner = "x"\nstate = "shared-safe"\n'
            'auth = { kind = "none", keys = [], store = "none" }\n'
            'capabilities = ["cap"]\nexpected = { claude = "bogus" }\n',
            "expected['claude']",
        ),
        (
            'schema_version = 1\n[[server]]\nid = "a"\ntransport = "local-http"\n'
            'url = "http://127.0.0.1:1/mcp"\nowner = "x"\nstate = "shared-safe"\n'
            'auth = { kind = "none", keys = [], store = "none" }\n'
            'capabilities = ["cap"]\nexpected = { opencode = "user" }\n',
            "skill-everywhere roster",
        ),
    ],
)
def test_mcp_registry_rejects_invalid_schemas(tmp_path, toml_body, err_sub):
    bad = tmp_path / "bad.toml"
    bad.write_text(toml_body, encoding="utf-8")
    cp = _run("--md", "--registry", str(bad))
    assert cp.returncode == 2
    assert err_sub in cp.stderr
