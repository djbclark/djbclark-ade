"""ade-worker-run --mcp (docs/mcp-on-demand.md 11.2 part 1): registry, generated config, profile rewrite, conflict rule."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
import ade_mcp_on_demand as m  # noqa: E402

REG = {"chrome-devtools": {"command": "npx", "args": ["-y", "chrome-devtools-mcp@latest"]}}


def ready(*ids: str) -> Any:
    return lambda: [{"provider": i, "enabled": True, "status": "ready"} for i in ids]


def apply(rest: list[str], names: list[str], cat: Any, tmp: Path, has: bool = False) -> list[str]:
    return m.apply(rest, names, cat, reg=REG, user_has=lambda _p, _n: has, directory=tmp, note=lambda _s: None)


def test_registry_ships_chrome_devtools_without_env() -> None:
    reg = m.load_registry()
    assert reg["chrome-devtools"]["command"] == "npx" and "--autoConnect" in reg["chrome-devtools"]["args"]
    assert "env" not in json.dumps(m.claude_config(reg, ["chrome-devtools"]))


def test_registry_rejects_env_and_bad_entries(tmp_path: Path) -> None:
    bad = tmp_path / "r.toml"
    _ = bad.write_text('[servers.x]\ncommand = "c"\nenv = { K = "v" }\n')
    with pytest.raises(m.McpError):
        m.load_registry(bad)
    _ = bad.write_text("[servers.x]\nargs = []\n")
    with pytest.raises(m.McpError):
        m.load_registry(bad)


def test_generated_claude_config_is_mode_600_and_atomic(tmp_path: Path) -> None:
    path = m.write_claude_config(REG, ["chrome-devtools"], tmp_path / "mcp")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    data = json.loads(path.read_text())
    assert data == {"mcpServers": {"chrome-devtools": {"type": "stdio", "command": "npx", "args": REG["chrome-devtools"]["args"]}}}
    assert [p.name for p in path.parent.iterdir()] == ["chrome-devtools.json"]  # no temp file left


def test_provider_is_rewritten_to_the_profile_keeping_the_model(tmp_path: Path) -> None:
    rest = ["--provider", "claude/claude-sonnet-5-5", "--thinking", "high", "brief"]
    out = apply(rest, ["chrome-devtools"], ready("claude-mcp-chrome-devtools"), tmp_path)
    assert out == ["--provider", "claude-mcp-chrome-devtools/claude-sonnet-5-5", "--thinking", "high", "brief"]
    out = apply(["--provider=codex", "brief"], ["chrome-devtools"], ready("codex-mcp-chrome-devtools"), tmp_path)
    assert out == ["--provider=codex-mcp-chrome-devtools", "brief"]


def test_missing_profile_refuses_with_a_snippet_and_writes_the_config(tmp_path: Path) -> None:
    with pytest.raises(m.McpError) as e:
        apply(["--provider", "claude", "brief"], ["chrome-devtools"], ready(), tmp_path)
    msg = str(e.value)
    assert "claude-mcp-chrome-devtools" in msg and "--mcp-config" in msg and "agents.providers" in msg
    assert (tmp_path / "chrome-devtools.json").is_file()
    for row in ({"status": "error"}, {"status": "ready", "error": "x"}, {"status": "ready", "enabled": False}):  # listed but not usable
        with pytest.raises(m.McpError):
            apply(["--provider", "claude", "b"], ["chrome-devtools"],
                  lambda row=row: [{"provider": "claude-mcp-chrome-devtools", "enabled": True, **row}], tmp_path)


def test_codex_profile_carries_the_whole_server() -> None:
    """898 LOW 3: with no [mcp_servers.NAME] table the profile still defines command and args, not just enabled."""
    entry = m.profile_entry("codex", ["chrome-devtools"], Path("-"), REG)
    cmd = entry["command"]
    assert entry["extends"] == "codex" and cmd[0] == "codex"
    assert 'mcp_servers.chrome-devtools.command="npx"' in cmd and "mcp_servers.chrome-devtools.enabled=true" in cmd
    assert 'mcp_servers.chrome-devtools.args=["-y", "chrome-devtools-mcp@latest"]' in cmd


def test_server_already_in_user_scope_adds_nothing(tmp_path: Path) -> None:
    seen: list[str] = []
    rest = ["--provider", "claude", "brief"]
    out = m.apply(rest, ["chrome-devtools"], ready(), reg=REG, user_has=lambda _p, _n: True, directory=tmp_path, note=seen.append)
    assert out == rest and "user scope" in seen[0]


def test_usage_errors(tmp_path: Path) -> None:
    with pytest.raises(m.McpError):
        apply(["--provider", "claude", "b"], ["nope"], ready(), tmp_path)  # unknown name
    with pytest.raises(m.McpError):
        apply(["b"], ["chrome-devtools"], ready(), tmp_path)  # no --provider
    with pytest.raises(m.McpError):
        apply(["--provider", "hermes", "b"], ["chrome-devtools"], ready(), tmp_path)  # unsupported provider
    assert apply(["--provider", "claude", "b"], [], ready(), tmp_path) == ["--provider", "claude", "b"]  # no --mcp: untouched


def test_user_scope_reads_key_names_only(tmp_path: Path) -> None:
    cj, tj = tmp_path / "c.json", tmp_path / "c.toml"
    _ = cj.write_text(json.dumps({"mcpServers": {"chrome-devtools": {"command": "npx", "env": {"K": "secret"}}}}))
    _ = tj.write_text('[mcp_servers.chrome-devtools]\ncommand = "npx"\nenabled = false\n[mcp_servers.other]\ncommand = "x"\n')
    assert m.user_scope_has("claude", "chrome-devtools", cj, tj) and not m.user_scope_has("claude", "nope", cj, tj)
    assert not m.user_scope_has("codex", "chrome-devtools", cj, tj)  # enabled = false is on demand, not present
    assert m.user_scope_has("codex", "other", cj, tj)
    assert not m.user_scope_has("claude", "x", tmp_path / "missing.json", tj)


def test_worker_run_rejects_an_unknown_mcp_name_with_exit_2() -> None:
    r = subprocess.run([sys.executable, str(ROOT / "bin" / "ade-worker-run"), "--lead", "00000000-0000-4000-8000-000000000000",
                        "--slice", "s", "--mcp", "no-such-server", "--", "--provider", "claude", "brief"],
                       capture_output=True, text=True, env=dict(os.environ))
    assert r.returncode == 2 and "unknown --mcp name" in r.stderr


def test_registry_names_are_kebab_and_a_set_never_collides_with_one_name(tmp_path: Path) -> None:
    """898 LOW 2: {"chrome", "devtools"} used to share the id and file of "chrome-devtools"; odd keys escaped the state dir."""
    for key in ("../x", "a/b", "A", "a=b", "a_b", "a--b"):
        bad = tmp_path / "r.toml"
        _ = bad.write_text(f'[servers."{key}"]\ncommand = "c"\n')
        with pytest.raises(m.McpError):
            m.load_registry(bad)
    assert m.profile_id("claude", ["chrome", "devtools"]) != m.profile_id("claude", ["chrome-devtools"])
    assert m.config_path(["chrome", "devtools"], tmp_path) != m.config_path(["chrome-devtools"], tmp_path)


def test_a_refused_launch_never_overwrites_the_live_config(tmp_path: Path) -> None:
    """898 LOW 4: workers read the generated file; only `snippet --write` replaces it."""
    live = tmp_path / "chrome-devtools.json"
    _ = live.write_text('{"mcpServers": {"chrome-devtools": {"command": "other"}}}\n')
    with pytest.raises(m.McpError) as e:
        apply(["--provider", "claude", "b"], ["chrome-devtools"], ready(), tmp_path)
    assert "other" in live.read_text() and "differs" in str(e.value)
    ok = tmp_path / "ok"
    with pytest.raises(m.McpError):
        apply(["--provider", "claude", "b"], ["chrome-devtools"], ready(), ok)
    assert (ok / "chrome-devtools.json").is_file()  # an absent file is created, so the printed profile points at something
