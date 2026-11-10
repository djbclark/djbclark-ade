"""config/pi-pool-acceptance.toml + bin/ade_pi_pools: auto-routing acceptance gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
sys.path.insert(0, str(BIN))
import ade_pi_pools as pools  # noqa: E402
import pi_defaults as defaults  # noqa: E402
import route_agent as router  # noqa: E402

MODELS = ["zai/glm-5.3-flash", "cursor/composer-2.5"]


def reading(left):
    return {"remaining": left, "age_s": 0, "windows": {"weekly": left}}


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("ADE_PI_DEFAULTS_BLOCKS", str(tmp_path / "blocks.json"))
    monkeypatch.setattr(router, "AIUSE_CONFIG", tmp_path / "no-config.toml")
    monkeypatch.setattr(router, "paseo_providers", lambda: {"pi", "claude", "codex", "cursor"})
    monkeypatch.setattr(router, "kind_rows", lambda *_: [])


def write_acceptance(tmp_path, text: str) -> Path:
    path = tmp_path / "pi-pool-acceptance.toml"
    path.write_text(text)
    return path


def test_shipped_file_accepts_only_the_live_cursor_and_zai_shortlist():
    rows = pools.load_acceptance(REPO / "config" / "pi-pool-acceptance.toml")
    assert rows["cursor"]["accepted"] is True and rows["zai"]["accepted"] is True
    for name in ("grok", "antigravity", "sipb", "go"):
        assert rows[name]["accepted"] is False
    code, _, blocking = pools.check_auto(REPO / "config" / "pi-pool-acceptance.toml")
    assert code == 0 and blocking == []
    assert set(pools.routing_pi_services()) == {"cursor", "zai"}


def test_unaccepted_routing_pi_service_blocks_check_and_auto_choose(monkeypatch, tmp_path):
    path = write_acceptance(tmp_path, """
[pools.cursor]
accepted = false
note = "revoked for test"

[pools.zai]
accepted = true
""")
    monkeypatch.setenv("PI_POOL_ACCEPTANCE", str(path))
    assert pools.unaccepted_auto_services() == {"cursor"}
    code, _, blocking = pools.check_auto()
    assert code == 2 and blocking == ["cursor"]
    result = defaults.choose("code", MODELS, quota={"cursor": reading(90), "zai": reading(80)})
    assert result["service"] == "zai"
    result = defaults.choose("code", MODELS, quota={"cursor": reading(90), "zai": reading(90)},
                             excluded={"zai"})
    assert result["service"] is None
    assert "unaccepted pool(s): cursor" in result["reason"]
    assert "pi-pool-acceptance.toml" in result["reason"]


def test_missing_acceptance_row_for_a_routing_pi_service_fails_closed(monkeypatch, tmp_path):
    path = write_acceptance(tmp_path, """
[pools.zai]
accepted = true
""")
    monkeypatch.setenv("PI_POOL_ACCEPTANCE", str(path))
    assert pools.unaccepted_auto_services() == {"cursor"}
    assert pools.check_auto()[0] == 2


def test_missing_acceptance_file_blocks_every_routing_pi_service(monkeypatch, tmp_path):
    monkeypatch.setenv("PI_POOL_ACCEPTANCE", str(tmp_path / "absent.toml"))
    assert pools.unaccepted_auto_services() == {"cursor", "zai"}
    assert pools.check_auto()[0] == 2
    assert defaults.choose("code", MODELS, quota={"cursor": reading(90), "zai": reading(90)})["service"] is None


def test_cli_check_and_ls_exit_codes(tmp_path):
    import os
    path = write_acceptance(tmp_path, """
[pools.cursor]
accepted = true

[pools.zai]
accepted = false
""")
    env = {**os.environ, "PI_POOL_ACCEPTANCE": str(path), "PYTHONPATH": str(BIN)}
    check = subprocess.run([sys.executable, str(BIN / "ade-pi-pools"), "check", "--json"],
                           capture_output=True, text=True, env=env, cwd=str(REPO))
    assert check.returncode == 2, check.stderr
    payload = json.loads(check.stdout)
    assert payload["ready"] is False and "zai" in payload["blocking"]
    ls = subprocess.run([sys.executable, str(BIN / "ade-pi-pools"), "ls", "--json"],
                        capture_output=True, text=True, env=env, cwd=str(REPO))
    assert ls.returncode == 0
    assert {r["pool"] for r in json.loads(ls.stdout)["pools"]} >= {"cursor", "zai"}
