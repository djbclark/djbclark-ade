"""ade-install doctor: observe-only shared-MCP client registration check (fixture HOME)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))
import ade_install as ai
import ade_mcp_clients as mc

FC = "http://127.0.0.1:18804/mcp"
BM = "http://127.0.0.1:18796/mcp"


def write_claude(home, servers):
    (home / ".claude.json").write_text(json.dumps({"mcpServers": servers}))


def write_codex(home, body):
    (home / ".codex").mkdir(exist_ok=True)
    (home / ".codex" / "config.toml").write_text(body)


GOOD_CODEX = f'''
[mcp_servers.firecrawl]
url = "{FC}"
[mcp_servers.basic-memory]
url = "{BM}"
'''


@pytest.fixture
def roster():
    return mc.load_roster(REPO / "config" / "mcp-clients.toml")


def by_id(findings):
    return {i: (s, d) for i, s, d in findings}


def test_all_ok(tmp_path, roster):
    write_claude(tmp_path, {"firecrawl": {"type": "http", "url": FC},
                            "basic-memory": {"type": "http", "url": BM + "/"}})
    write_codex(tmp_path, GOOD_CODEX)
    got = by_id(mc.observe(roster, home=tmp_path))
    assert {k: v[0] for k, v in got.items()} == {
        f"{c}/{s}": "ok" for c in mc.CLIENTS for s in ("firecrawl", "basic-memory")}


def test_missing_gives_exact_fix_command_and_runs_nothing(tmp_path, roster, monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("ran a command"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("ran a command"))
    write_claude(tmp_path, {"graft": {"command": "graft", "args": ["mcp"]}})
    write_codex(tmp_path, GOOD_CODEX)
    got = by_id(mc.observe(roster, home=tmp_path))
    st, detail = got["claude-code/firecrawl"]
    assert st == "missing"
    assert f"claude mcp add --scope user --transport http firecrawl {FC}" in detail
    assert got["codex/firecrawl"][0] == "ok"


def test_wrong_url_and_wrong_type_and_disabled(tmp_path, roster):
    write_claude(tmp_path, {"firecrawl": {"type": "http", "url": "http://127.0.0.1:9/mcp"},
                            "basic-memory": {"url": BM}})  # no type = read as stdio
    write_codex(tmp_path, GOOD_CODEX.replace(BM, BM + '"\nenabled = false\n#'))
    got = by_id(mc.observe(roster, home=tmp_path))
    assert got["claude-code/firecrawl"][0] == "wrong-url"
    assert "127.0.0.1:9" in got["claude-code/firecrawl"][1]
    assert got["claude-code/basic-memory"][0] == "wrong-type"
    assert got["codex/basic-memory"][0] == "disabled"


def test_never_prints_values(tmp_path, roster):
    secret = "SEKRET-TOKEN-123"
    write_claude(tmp_path, {
        "firecrawl": {"type": "http", "url": f"http://user:{secret}@127.0.0.1:9/x?key={secret}",
                      "headers": {"Authorization": f"Bearer {secret}"}, "env": {"K": secret}}})
    write_codex(tmp_path, f'[mcp_servers.firecrawl]\nurl = "{FC}"\nhttp_headers = {{ A = "{secret}" }}\n')
    text = json.dumps(mc.observe(roster, home=tmp_path))
    assert secret not in text


def test_absent_config_files_are_missing_not_crash(tmp_path, roster):
    got = mc.observe(roster, home=tmp_path)
    assert len(got) == 4 and {s for _, s, _ in got} == {"missing"}


def test_corrupt_config_is_error_without_content(tmp_path, roster):
    (tmp_path / ".claude.json").write_text("{not json SEKRET")
    write_codex(tmp_path, GOOD_CODEX)
    got = by_id(mc.observe(roster, home=tmp_path))
    assert got["claude-code/*"][0] == "error"
    assert "SEKRET" not in got["claude-code/*"][1]


def test_roster_matches_docs():
    docs = (REPO / "docs" / "mcp-servers.md").read_text()
    for row in mc.load_roster(REPO / "config" / "mcp-clients.toml"):
        assert f"`{row['id']}`" in docs and row["url"] in docs, row["id"]


def test_roster_validation(tmp_path):
    p = tmp_path / "r.toml"
    p.write_text('[[server]]\nid="a"\nurl="ftp://x"\nclients=["codex"]\n')
    with pytest.raises(ValueError):
        mc.load_roster(p)
    p.write_text('[[server]]\nid="a"\nurl="http://x"\nclients=["vim"]\n')
    with pytest.raises(ValueError):
        mc.load_roster(p)


def _catalog(tmp_path, with_roster):
    if with_roster:
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "mcp-clients.toml").write_text(
            (REPO / "config" / "mcp-clients.toml").read_text())
    return ai.Catalog(data={"component": []}, path=tmp_path / "install.toml", root=tmp_path)


def test_doctor_warns_but_exit_zero(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    write_claude(home, {})
    write_codex(home, GOOD_CODEX)
    obs, rc = ai.doctor(_catalog(tmp_path, True), skip_jobs=True, skip_credential_bak=True,
                        pi_pool_acceptance_path=tmp_path / "none.toml", mcp_home=home)
    mcp = {o.id: o for o in obs if o.kind == "mcp"}
    assert mcp["claude-code/firecrawl"].status == "warn"
    assert mcp["codex/firecrawl"].status == "ok"
    assert rc == 0


def test_doctor_error_on_corrupt_fails(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude.json").write_text("nope")
    write_codex(home, GOOD_CODEX)
    obs, rc = ai.doctor(_catalog(tmp_path, True), skip_jobs=True, skip_credential_bak=True,
                        pi_pool_acceptance_path=tmp_path / "none.toml", mcp_home=home)
    assert rc == 1


def test_doctor_silent_without_roster(tmp_path):
    obs, _ = ai.doctor(_catalog(tmp_path, False), skip_jobs=True, skip_credential_bak=True,
                       pi_pool_acceptance_path=tmp_path / "none.toml", mcp_home=tmp_path)
    assert not any(o.kind == "mcp" for o in obs)


def test_path_secret_and_control_chars_never_printed(tmp_path, roster):
    write_claude(tmp_path, {"firecrawl": {"type": "http",
                                          "url": "https://mcp.example.dev/PATHSECRET/v2/mcp\x1b[31m"}})
    write_codex(tmp_path, GOOD_CODEX)
    st, detail = by_id(mc.observe(roster, home=tmp_path))["claude-code/firecrawl"]
    assert st == "wrong-url" and "PATHSECRET" not in detail and "\x1b" not in detail


def test_deep_nesting_is_error_not_crash(tmp_path, roster):
    (tmp_path / ".claude.json").write_text("[" * 100000)
    write_codex(tmp_path, GOOD_CODEX)
    assert by_id(mc.observe(roster, home=tmp_path))["claude-code/*"][0] == "error"


def test_non_table_entry_is_wrong_type_with_swap_fix(tmp_path, roster):
    write_claude(tmp_path, {"firecrawl": "oops", "basic-memory": {"type": "http", "url": BM}})
    write_codex(tmp_path, GOOD_CODEX)
    st, detail = by_id(mc.observe(roster, home=tmp_path))["claude-code/firecrawl"]
    assert st == "wrong-type" and "claude mcp remove --scope user firecrawl && claude mcp add" in detail


@pytest.mark.parametrize("sid,url", [("a b", "http://x/mcp"), ("a;rm", "http://x/mcp"),
                                     ("a", "http://x/mcp; rm -rf ~"), ("a", "http://x/$(id)")])
def test_roster_rejects_shell_metacharacters(tmp_path, sid, url):
    p = tmp_path / "r.toml"
    p.write_text(f'[[server]]\nid="{sid}"\nurl="{url}"\nclients=["codex"]\n')
    with pytest.raises(ValueError):
        mc.load_roster(p)
