"""ade-install doctor: observe-only TUI wiring check (MCP registry + skill links), fixture HOME."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))
import ade_client_wiring as cw
import ade_install as ai

# `~/.hermes/config.yaml` is only read when PyYAML imports, and a TUI whose config cannot be read reports one
# `hermes/* unknown` row instead of the per-server rows (bin/ade_client_wiring, its documented graceful path).
try:
    import yaml  # noqa: F401
    HAS_YAML = True
except ImportError:
    HAS_YAML = False
needs_yaml = pytest.mark.skipif(
    not HAS_YAML, reason="PyYAML reads ~/.hermes/config.yaml; install it with `uv run --with pytest --with pyyaml`")

FC = "http://127.0.0.1:18804/mcp"
BM = "http://127.0.0.1:18796/mcp"
TUIS = cw.tui_roster(REPO)
CDT_ARGS = ["-y", "chrome-devtools-mcp@latest", "--autoConnect", "--no-usage-statistics",
            "--no-performance-crux", "--redact-network-headers"]


def lazy_cdt(home: Path) -> dict:
    return {
        "type": "stdio",
        "command": str(home / ".local" / "libexec" / "ade" / "mcp-lazy"),
        "args": ["--id", "chrome-devtools", "--idle", "600", "--", "/opt/homebrew/bin/npx", *CDT_ARGS],
        "env": {},
    }


SMALL_REGISTRY_TOML = f"""schema_version = 1

[[server]]
id = "firecrawl"
transport = "local-http"
url = "{FC}"
owner = "launchd:com.djbclark.firecrawl-mcp"
state = "shared-safe"
auth = {{ kind = "none", keys = [], store = "none" }}
capabilities = ["web-search"]
expected = {{ claude = "user", codex = "user" }}

[[server]]
id = "basic-memory"
transport = "local-http"
url = "{BM}"
owner = "launchd:com.djbclark.basic-memory-mcp"
state = "shared-safe"
auth = {{ kind = "none", keys = [], store = "none" }}
capabilities = ["memory"]
expected = {{ claude = "user", codex = "user", cursor-agent = "user", hermes = "user" }}

[[server]]
id = "chrome-devtools"
transport = "stdio"
command = "npx"
args = {json.dumps(CDT_ARGS)}
lazy_wrapper = "~/.local/libexec/ade/mcp-lazy"
lazy_idle_seconds = 600
owner = "per-session"
state = "per-session"
auth = {{ kind = "dialog", keys = [], store = "none" }}
capabilities = ["browser"]
expected = {{ claude = "user-lazy", codex = "user-lazy" }}

[[server]]
id = "graft"
transport = "stdio"
command = "graft"
args = ["mcp"]
owner = "per-session"
state = "per-repo"
auth = {{ kind = "none", keys = [], store = "none" }}
capabilities = ["code-graph"]
expected = {{ claude = "absent", codex = "absent" }}

[[server]]
id = "rfab"
transport = "stdio"
command = "ade-mcp-rfab"
args = []
owner = "per-session"
state = "per-session"
auth = {{ kind = "env", keys = ["RFAB_API_KEY"], store = "sudo-secretspec" }}
capabilities = ["image-generation"]
expected = {{ claude = "on-demand", codex = "on-demand" }}

[[server]]
id = "bezalel"
transport = "remote-http"
url = "https://mcp.bezalel.sh/mcp"
owner = "remote:bezalel"
state = "external-app"
auth = {{ kind = "bearer", keys = ["Authorization"], store = "none" }}
capabilities = ["finance", "photos:app-created-only"]
expected = {{ claude = "denied", codex = "user", hermes = "user" }}
"""


def write_claude(home: Path, servers: dict, *, projects: dict | None = None, denied: list | None = None):
    payload: dict = {"mcpServers": servers}
    if projects is not None:
        payload["projects"] = projects
    (home / ".claude.json").write_text(json.dumps(payload), encoding="utf-8")
    if denied is not None:
        (home / ".claude").mkdir(exist_ok=True)
        (home / ".claude" / "settings.json").write_text(
            json.dumps({"deniedMcpServers": [{"serverName": d} for d in denied]}),
            encoding="utf-8",
        )


def write_codex(home: Path, body: str):
    (home / ".codex").mkdir(exist_ok=True)
    (home / ".codex" / "config.toml").write_text(body, encoding="utf-8")


def write_cursor(home: Path, servers: dict):
    (home / ".cursor").mkdir(exist_ok=True)
    (home / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")


def write_hermes(home: Path, body: str):
    (home / ".hermes").mkdir(exist_ok=True)
    (home / ".hermes" / "config.yaml").write_text(body, encoding="utf-8")


def good_codex_text(home: Path) -> str:
    lazy_cmd = str(home / ".local" / "libexec" / "ade" / "mcp-lazy")
    lazy_args = ["--id", "chrome-devtools", "--idle", "600", "--", "/opt/homebrew/bin/npx", *CDT_ARGS]
    return (
        f'[mcp_servers.firecrawl]\nurl = "{FC}"\n'
        f'[mcp_servers.basic-memory]\nurl = "{BM}"\n'
        f'[mcp_servers.chrome-devtools]\ncommand = "{lazy_cmd}"\nargs = {json.dumps(lazy_args)}\n'
        f'[mcp_servers.bezalel]\nurl = "https://mcp.bezalel.sh/mcp"\n'
    )


GOOD_HERMES = (
    f"mcp_servers:\n"
    f"  basic-memory:\n    url: {BM}\n    enabled: true\n"
    f"  bezalel:\n    url: https://mcp.bezalel.sh/mcp\n    enabled: true\n"
)


def good_home(home: Path):
    write_claude(
        home,
        {
            "firecrawl": {"type": "http", "url": FC},
            "basic-memory": {"type": "http", "url": BM + "/"},
            "chrome-devtools": lazy_cdt(home),
        },
        denied=["bezalel"],
    )
    write_codex(home, good_codex_text(home))
    write_cursor(home, {"basic-memory": {"url": BM}})
    write_hermes(home, GOOD_HERMES)


@pytest.fixture
def roster(tmp_path):
    p = tmp_path / "mcp-registry.toml"
    p.write_text(SMALL_REGISTRY_TOML, encoding="utf-8")
    return cw.load_roster(p, TUIS)


def mcp(home, roster):
    return {r[1]: (r[2], r[3]) for rows in cw.observe_mcp(roster, TUIS, home=home).values() for r in rows}


# ---- TUI roster comes from skill-everywhere, not a second list ----------------

def test_tui_roster_is_the_skill_everywhere_table():
    assert TUIS[:3] == ["claude", "codex", "pi"] and "cursor-agent" in TUIS and "hermes" in TUIS
    for retired in ("opencode", "omp", "crush", "kiro", "tuios", "antigravity", "agy"):
        assert retired not in TUIS


def test_repo_registry_loads_cleanly_against_tuis():
    rows = cw.load_registry(REPO / "config" / "mcp-registry.toml", TUIS)
    assert len(rows) >= 20
    assert cw.default_roster_path(REPO) == REPO / "config" / "mcp-registry.toml"


@pytest.mark.parametrize("sid,url,expected", [
    ("a b", "http://x/mcp", {"codex": "user"}),
    ("a;rm", "http://x/mcp", {"codex": "user"}),
    ("a", "http://x/mcp; rm -rf ~", {"codex": "user"}),
    ("a", "http://x/$(id)", {"codex": "user"}),
    ("a", "ftp://x", {"codex": "user"}),
    ("a", "http://x", {"vim": "user"}),
    ("a", "http://x", {"codex": "nope"}),
])
def test_roster_validation(tmp_path, sid, url, expected):
    p = tmp_path / "r.toml"
    exp_toml = ", ".join(f'{k} = "{v}"' for k, v in expected.items())
    p.write_text(
        f'schema_version = 1\n[[server]]\nid="{sid}"\ntransport="local-http"\nurl="{url}"\n'
        f'owner="local"\nstate="shared-safe"\nauth={{kind="none",keys=[],store="none"}}\n'
        f'capabilities=["cap"]\nexpected={{ {exp_toml} }}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        cw.load_roster(p, TUIS)


# ---- MCP -----------------------------------------------------------------------

@needs_yaml
def test_mcp_all_ok(tmp_path, roster):
    good_home(tmp_path)
    got = mcp(tmp_path, roster)
    assert {k: v[0] for k, v in got.items()} == {
        "claude/firecrawl": "ok",
        "claude/basic-memory": "ok",
        "claude/chrome-devtools": "ok",
        "claude/graft": "ok",
        "claude/rfab": "ok",
        "claude/bezalel": "ok",
        "codex/firecrawl": "ok",
        "codex/basic-memory": "ok",
        "codex/chrome-devtools": "ok",
        "codex/graft": "ok",
        "codex/rfab": "ok",
        "codex/bezalel": "ok",
        "cursor-agent/basic-memory": "ok",
        "hermes/basic-memory": "ok",
        "hermes/bezalel": "ok",
    }


def test_mcp_missing_gives_exact_fix_and_runs_nothing(tmp_path, roster, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("ran a command"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("ran a command"))
    good_home(tmp_path)
    write_claude(tmp_path, {"graft": {"command": "graft", "args": ["mcp"]}}, denied=["bezalel"])
    got = mcp(tmp_path, roster)
    st, detail = got["claude/firecrawl"]
    assert st == "warn" and "missing" in detail
    assert f"claude mcp add --scope user --transport http firecrawl {FC}" in detail
    # graft returning in Claude user scope must warn as drift!
    gst, gdetail = got["claude/graft"]
    assert gst == "warn" and "drift" in gdetail and "claude mcp remove --scope user graft" in gdetail


def test_graft_drift_warns_in_codex_too(tmp_path, roster):
    good_home(tmp_path)
    write_codex(tmp_path, good_codex_text(tmp_path) + '[mcp_servers.graft]\ncommand = "graft"\nargs = ["mcp"]\n')
    st, detail = mcp(tmp_path, roster)["codex/graft"]
    assert st == "warn" and "drift" in detail and "codex mcp remove graft" in detail


def test_on_demand_accepts_absent_or_disabled_and_warns_when_active(tmp_path, roster):
    good_home(tmp_path)
    # Disabled in Codex is ok for on-demand
    write_codex(tmp_path, good_codex_text(tmp_path) + '[mcp_servers.rfab]\ncommand = "ade-mcp-rfab"\nenabled = false\n')
    assert mcp(tmp_path, roster)["codex/rfab"][0] == "ok"
    # Active in Claude warns as drift
    write_claude(
        tmp_path,
        {
            "firecrawl": {"type": "http", "url": FC},
            "basic-memory": {"type": "http", "url": BM},
            "chrome-devtools": lazy_cdt(tmp_path),
            "rfab": {"type": "stdio", "command": "ade-mcp-rfab", "args": []},
        },
        denied=["bezalel"],
    )
    st, detail = mcp(tmp_path, roster)["claude/rfab"]
    assert st == "warn" and "drift" in detail and "on-demand" in detail


def test_denied_checks_claude_settings_and_catches_drift(tmp_path, roster):
    good_home(tmp_path)
    # Remove bezalel from deniedMcpServers -> warns even if absent from ~/.claude.json
    write_claude(
        tmp_path,
        {"firecrawl": {"type": "http", "url": FC}, "basic-memory": {"type": "http", "url": BM},
         "chrome-devtools": lazy_cdt(tmp_path)},
        denied=[],
    )
    st, detail = mcp(tmp_path, roster)["claude/bezalel"]
    assert st == "warn" and "deniedMcpServers" in detail
    # Corrupt settings.json -> error without leaking content
    (tmp_path / ".claude" / "settings.json").write_text("{corrupt SECRET_VAL", encoding="utf-8")
    st, detail = mcp(tmp_path, roster)["claude/bezalel"]
    assert st == "error" and "SECRET_VAL" not in detail


def test_project_scoped_expected_state_in_claude(tmp_path):
    p = tmp_path / "r.toml"
    p.write_text(
        'schema_version = 1\n[[server]]\nid="extrabar"\ntransport="stdio"\n'
        'command="/Applications/ExtraBar.app/Contents/Helpers/extrabar-mcp"\nargs=[]\n'
        'owner="app:ExtraBar"\nstate="external-app"\nauth={kind="none",keys=[],store="none"}\n'
        'capabilities=["macos-menubar"]\nexpected={ claude = "project:~" }\n',
        encoding="utf-8",
    )
    reg = cw.load_registry(p, TUIS)
    write_claude(
        tmp_path,
        {},
        projects={
            str(tmp_path): {
                "mcpServers": {
                    "extrabar": {
                        "type": "stdio",
                        "command": "/Applications/ExtraBar.app/Contents/Helpers/extrabar-mcp",
                        "args": [],
                    }
                }
            }
        },
    )
    assert mcp(tmp_path, reg)["claude/extrabar"][0] == "ok"
    write_claude(tmp_path, {}, projects={})
    st, detail = mcp(tmp_path, reg)["claude/extrabar"]
    assert st == "warn" and "project ~" in detail


@needs_yaml
def test_mcp_wrong_url_wrong_type_disabled(tmp_path, roster):
    good_home(tmp_path)
    write_claude(
        tmp_path,
        {"firecrawl": {"type": "http", "url": "http://127.0.0.1:9/mcp"},
         "basic-memory": {"url": BM}},  # no type: read as stdio
        denied=["bezalel"],
    )
    write_codex(tmp_path, good_codex_text(tmp_path).replace(BM, BM + '"\nenabled = false\n#'))
    write_cursor(tmp_path, {"basic-memory": {"url": "http://127.0.0.1:1/mcp"}})
    write_hermes(tmp_path, GOOD_HERMES.replace("true", "false", 1))
    got = mcp(tmp_path, roster)
    assert "wrong-url" in got["claude/firecrawl"][1] and "127.0.0.1:9" in got["claude/firecrawl"][1]
    assert "wrong-type" in got["claude/basic-memory"][1]
    assert "disabled" in got["codex/basic-memory"][1]
    assert "wrong-url" in got["cursor-agent/basic-memory"][1]
    assert "disabled" in got["hermes/basic-memory"][1]


def test_mcp_never_prints_values(tmp_path, roster):
    secret = "SEKRET-TOKEN-123"
    good_home(tmp_path)
    write_claude(
        tmp_path,
        {"firecrawl": {
            "type": "http", "url": f"http://user:{secret}@127.0.0.1:9/x?key={secret}",
            "headers": {"Authorization": f"Bearer {secret}"}, "env": {"K": secret}}},
        denied=["bezalel"],
    )
    write_codex(tmp_path, f'[mcp_servers.firecrawl]\nurl = "{FC}"\nhttp_headers = {{ A = "{secret}" }}\n')
    assert secret not in json.dumps(cw.observe_mcp(roster, TUIS, home=tmp_path))


def test_mcp_path_secret_control_chars_and_schemeless_url_not_printed(tmp_path, roster):
    good_home(tmp_path)
    for bad in ("https://mcp.example.dev/PATHSECRET/v2/mcp\x1b[31m", "LEAKME:pw@host/path"):
        write_claude(tmp_path, {"firecrawl": {"type": "http", "url": bad}}, denied=["bezalel"])
        st, detail = mcp(tmp_path, roster)["claude/firecrawl"]
        assert st == "warn" and "PATHSECRET" not in detail and "LEAKME" not in detail and "\x1b" not in detail


@needs_yaml
def test_mcp_absent_files_warn_for_user_and_ok_for_absent_ondemand(tmp_path, roster):
    got = mcp(tmp_path, roster)
    assert got["claude/firecrawl"][0] == "warn"
    assert got["claude/chrome-devtools"][0] == "warn"
    assert got["claude/graft"][0] == "ok"
    assert got["claude/rfab"][0] == "ok"
    assert got["codex/graft"][0] == "ok"
    assert got["codex/rfab"][0] == "ok"


def test_mcp_corrupt_and_deeply_nested_config_is_error_without_content(tmp_path, roster):
    good_home(tmp_path)
    (tmp_path / ".claude.json").write_text("{not json SEKRET", encoding="utf-8")
    (tmp_path / ".cursor" / "mcp.json").write_text("[" * 100000, encoding="utf-8")
    got = mcp(tmp_path, roster)
    assert got["claude/*"][0] == "error" and "SEKRET" not in got["claude/*"][1]
    assert got["cursor-agent/*"][0] == "error"


def test_mcp_non_table_entry_is_wrong_type_with_swap_fix(tmp_path, roster):
    good_home(tmp_path)
    write_claude(tmp_path, {"firecrawl": "oops", "basic-memory": {"type": "http", "url": BM}}, denied=["bezalel"])
    st, detail = mcp(tmp_path, roster)["claude/firecrawl"]
    assert st == "warn" and "claude mcp remove --scope user firecrawl && claude mcp add" in detail


def test_mcp_client_without_readable_config_is_unknown_never_failure(tmp_path):
    roster = [{
        "id": "x", "transport": "local-http", "url": "http://127.0.0.1:1/mcp",
        "owner": "local", "state": "shared-safe",
        "auth": {"kind": "none", "keys": [], "store": "none"},
        "capabilities": ["cap"],
        "expected": {"pi": "user", "grokbot": "user", "gemini": "user"},
    }]
    got = cw.observe_mcp(roster, TUIS, home=tmp_path)
    for tui in ("pi", "grokbot", "gemini"):
        assert [r[2] for r in got[tui]] == ["unknown"] and got[tui][0][3]


def test_mcp_hermes_unknown_without_pyyaml(tmp_path, roster, monkeypatch):
    monkeypatch.setattr(cw, "yaml", None)
    good_home(tmp_path)
    assert [r[2] for r in cw.observe_mcp(roster, TUIS, home=tmp_path)["hermes"]] == ["unknown"]


# ---- skills --------------------------------------------------------------------

def check_text(per_skill):
    """per_skill: {skill: {tui: state}} -> skill-everywhere --check --all stdout."""
    out = []
    for skill, states in per_skill.items():
        out.append(f"== {skill}")
        out += [f"  {tui:<13} {state}" for tui, state in states.items()]
    out.append("== end")
    return "\n".join(out) + "\n"


def runner_for(text, stderr="", rc=0):
    return lambda argv, env: subprocess.CompletedProcess(argv, rc, text, stderr)


ALL_OK = {t: "linked" for t in TUIS}
ALL_OK["cursor-agent"] = "via ~/.claude/skills"
ALL_OK["grokbot"] = "not installed (no /x/agent-data/workflows)"


def skills(per_skill, **kw):
    out, glob = cw.observe_skills(REPO, TUIS, runner=runner_for(check_text(per_skill), **kw))
    return out, glob


def test_skills_all_ok_and_unknown_tui():
    out, glob = skills({"a": ALL_OK, "b": ALL_OK})
    assert out["claude"] == [("skill", "claude/*", "ok", "2/2 skills linked")]
    assert out["cursor-agent"][0][2] == "ok"
    assert out["grokbot"][0][2] == "unknown" and "not installed" in out["grokbot"][0][3]
    assert glob == []


def test_skills_missing_dangling_elsewhere_with_fix_command():
    out, _ = skills({
        "a": {**ALL_OK, "claude": "missing", "codex": "dangling -> /gone", "pi": "other link -> /x"},
        "b": {**ALL_OK, "claude": "chained via /y", "codex": "real dir/file (not ours)"},
    })
    claude = {r[1]: r for r in out["claude"]}
    assert "1 missing: a" in claude["claude/missing"][3] and claude["claude/missing"][2] == "warn"
    assert "1 points elsewhere or not our link: b" in claude["claude/elsewhere"][3]
    assert "bin/skill-everywhere --all" in claude["claude/missing"][3]
    assert "1 dangling: a" in {r[1]: r for r in out["codex"]}["codex/dangling"][3]
    assert {r[1] for r in out["pi"]} == {"pi/elsewhere"}


def test_skills_incomplete_check_is_warn_not_trusted():
    out, glob = cw.observe_skills(REPO, TUIS, runner=runner_for("== a\n  claude linked\n", rc=2))
    assert all(v == [] for v in out.values())
    assert glob[0][2] == "warn" and "ended early" in glob[0][3]


def test_skills_runner_crash_is_warn():
    def boom(argv, env):
        raise subprocess.TimeoutExpired(argv, 1)
    _, glob = cw.observe_skills(REPO, TUIS, runner=boom)
    assert glob[0][2] == "warn"


def test_skills_stderr_warnings_surface():
    _, glob = skills({"a": ALL_OK}, stderr="warning: skill root /x does not exist; its skills are not checked\nnoise\n")
    assert len(glob) == 2 and "does not exist" in glob[0][3] and glob[1][3] == "noise"


@pytest.mark.parametrize("state,want", [
    ("linked", "ok"), ("via ~/.claude/skills", "ok"), ("copied", "ok"), ("present", "ok"), ("not installed", "unknown"),
    ("copied (/x/ade-demo)", "ok"), ("missing (/x/ade-demo)", "missing"), ("stale copy (/x)", "elsewhere"),
    ("not installed (no /x/agent-data/workflows)", "unknown"),
    ("missing", "missing"), ("dangling -> /x", "dangling"), ("other link -> /x", "elsewhere"),
    ("chained via /x", "elsewhere"), ("real dir/file (not ours)", "elsewhere"), ("stale copy", "elsewhere"),
    ("weird", "other")])
def test_classify(state, want):
    assert cw.classify_skill_state(state) == want


@pytest.mark.skipif(not all(shutil.which(t) for t in ("ggrep", "gsed", "greadlink", "grealpath")),
                    reason="skill-everywhere needs GNU tools")
def test_skills_real_script_against_fixture_home(tmp_path):
    """The real read-only script, fixture HOME/roots/stub binaries: linked, then a dangling link."""
    home, ade, bindir = tmp_path / "home", tmp_path / "skills", tmp_path / "bin"
    for d in (home, ade, bindir, home / ".claude" / "skills"):
        d.mkdir(parents=True, exist_ok=True)
    (ade / "demo").mkdir()
    (ade / "demo" / "SKILL.md").write_text("---\nname: demo\n---\n")
    for b in ("claude", "codex", "pi", "hermes", "cursor-agent"):
        (bindir / b).write_text("#!/bin/sh\n")
        (bindir / b).chmod(0o755)
    (home / ".claude" / "skills" / "demo").symlink_to(ade / "demo")
    (home / ".claude" / "skills" / "paseo").mkdir()  # Paseo-managed skill present on Claude
    env = {"SKILL_EVERYWHERE_ADE": str(ade), "SKILL_EVERYWHERE_PRIVATE": str(tmp_path / "p"),
           "SKILL_EVERYWHERE_SITE": str(tmp_path / "s"), "SKILL_EVERYWHERE_CHROME": str(tmp_path / "c")}
    (home / "agent-data" / "workflows").mkdir(parents=True)

    def run(argv, e):
        full = {**os.environ, **e, **env, "PATH": f"{bindir}:{e['PATH']}"}
        return subprocess.run(argv, capture_output=True, text=True, env=full, timeout=60)
    out, _ = cw.observe_skills(REPO, TUIS, home=home, runner=run)
    assert out["claude"][0][:3] == ("skill", "claude/*", "ok")
    assert {r[1] for r in out["codex"]} == {"codex/missing"}
    assert {r[1] for r in out["grokbot"]} == {"grokbot/missing"}
    (home / ".claude" / "skills" / "demo").unlink()
    (home / ".claude" / "skills" / "demo").symlink_to(tmp_path / "gone")
    out, _ = cw.observe_skills(REPO, TUIS, home=home, runner=run)
    assert {r[1] for r in out["claude"]} == {"claude/dangling"}


# ---- combined + doctor ---------------------------------------------------------

def make_root(tmp_path):
    root = tmp_path / "root"
    (root / "bin").mkdir(parents=True)
    (root / "config").mkdir()
    shutil.copy(REPO / "bin" / "skill-everywhere", root / "bin" / "skill-everywhere")
    (root / "config" / "mcp-registry.toml").write_text(SMALL_REGISTRY_TOML, encoding="utf-8")
    return root


@needs_yaml
def test_observe_one_summary_line_per_tui_then_details(tmp_path):
    root = make_root(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    good_home(home)
    write_claude(home, {}, denied=["bezalel"])
    rows = cw.observe(root, home=home, runner=runner_for(check_text({"a": ALL_OK})))
    summaries = [r for r in rows if r[0] == "tui"]
    assert [r[1] for r in summaries] == TUIS
    by = {r[1]: r for r in summaries}
    assert by["claude"][2] == "warn" and "3 gap(s)" in by["claude"][3]
    assert by["codex"][2] == "ok" and by["pi"][2] == "ok" and by["grokbot"][2] == "unknown"
    assert by["hermes"][2] == "ok" and by["cursor-agent"][2] == "ok"


def test_observe_silent_without_roster_or_script(tmp_path):
    assert cw.observe(tmp_path, home=tmp_path) == []


def test_observe_bad_client_in_roster_is_error(tmp_path):
    root = make_root(tmp_path)
    (root / "config" / "mcp-registry.toml").write_text(
        'schema_version = 1\n[[server]]\nid="a"\ntransport="local-http"\nurl="http://x/mcp"\n'
        'owner="local"\nstate="shared-safe"\nauth={kind="none",keys=[],store="none"}\n'
        'capabilities=["c"]\nexpected={ opencode = "user" }\n',
        encoding="utf-8",
    )
    rows = cw.observe(root, home=tmp_path, runner=runner_for(check_text({"a": ALL_OK})))
    assert rows[0][2] == "error" and "opencode" in rows[0][3]


def _catalog(root):
    return ai.Catalog(data={"component": []}, path=root / "install.toml", root=root)


def _doctor(root, home, text):
    return ai.doctor(_catalog(root), skip_jobs=True, skip_credential_bak=True,
                     pi_pool_acceptance_path=root / "none.toml",
                     wiring_home=home, skill_check_runner=runner_for(text))


def test_doctor_gaps_warn_but_exit_zero(tmp_path):
    root = make_root(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    good_home(home)
    write_claude(home, {}, denied=["bezalel"])
    obs, rc = _doctor(root, home, check_text({"a": {**ALL_OK, "claude": "missing"}}))
    kinds = {o.kind for o in obs}
    assert {"tui", "mcp", "skill"} <= kinds
    assert {o.id: o.status for o in obs if o.kind == "tui"}["claude"] == "warn"
    assert rc == 0


def test_doctor_unreadable_config_fails(tmp_path):
    root = make_root(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    good_home(home)
    (home / ".claude.json").write_text("nope")
    _, rc = _doctor(root, home, check_text({"a": ALL_OK}))
    assert rc == 1


def test_doctor_silent_without_roster(tmp_path):
    obs, _ = _doctor(tmp_path, tmp_path, "")
    assert not any(o.kind in ("tui", "mcp", "skill") for o in obs)


# ---- adversary round 3 -----------------------------------------------------------

def test_skill_env_overrides_are_scrubbed(monkeypatch, tmp_path):
    literal = ("SKILL_EVERYWHERE_ONLY", "SKILL_EVERYWHERE_NO_COPY", "SKILL_EVERYWHERE_ADE",
               "SKILL_EVERYWHERE_PRIVATE", "SKILL_EVERYWHERE_SITE", "SKILL_EVERYWHERE_GROKBOT_NOTE")
    relative = ("OPS_ROOT", "CODEX_HOME", "HERMES_HOME")
    for k in literal + relative:
        monkeypatch.setenv(k, "grokbot")

    def capture(**kw):
        seen = {}

        def run(argv, env):
            seen.update(env)
            return subprocess.CompletedProcess(argv, 0, check_text({"a": ALL_OK}), "")
        cw.observe_skills(REPO, TUIS, runner=run, **kw)
        return seen
    seen = capture()
    assert not any(k in seen for k in literal) and all(k in seen for k in relative)
    seen = capture(home=tmp_path)
    assert not any(k in seen for k in literal + relative) and seen["HOME"] == str(tmp_path)


def test_skills_undecodable_output_is_warn_not_crash():
    def bad(argv, env):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")
    _, glob = cw.observe_skills(REPO, TUIS, runner=bad)
    assert glob[0][2] == "warn"


def test_default_runner_decodes_with_replace(tmp_path):
    script = tmp_path / "s"
    script.write_bytes(b"#!/bin/sh\nprintf '\\377\\n'\n")
    script.chmod(0o755)
    cp = cw._default_runner([str(script)], dict(os.environ))
    assert "\ufffd" in cp.stdout


def stderr_rows(err, rc=0):
    out, glob = skills({"a": ALL_OK}, stderr=err, rc=rc)
    return out, glob


def test_stderr_attribution_is_structural_not_a_word_match():
    out, glob = stderr_rows("warning: codex global instructions dangling: /h/.codex/AGENTS.md -> /h/.claude/CLAUDE.md\n")
    assert [r[1] for r in out["codex"] if r[0] == "skill" and r[2] == "warn"] == ["codex/warning"]
    assert not [r for r in out["claude"] if r[2] == "warn"] and out["cursor-agent"][0][2] == "ok"
    assert glob == []
    out, glob = stderr_rows("warning: skill root /private/tmp/claude-502/x does not exist\n"
                            "warning: claude: render for /d failed; treating as stale copy\n")
    assert len(glob) == 2 and not any(r[2] == "warn" for rows in out.values() for r in rows)
    out, glob = stderr_rows("error: x warning: hermes y\n")
    assert [r[3] for r in glob] == ["error: x warning: hermes y"] and out["hermes"][0][2] == "ok"
    out, glob = stderr_rows("error: boom\n", rc=1)
    assert [r[3] for r in glob] == ["error: boom"]


def test_stderr_every_line_scanned_deduped_and_capped():
    lines = [f"warning: skill root /r{i} does not exist" for i in range(40)]
    out, glob = stderr_rows("\n".join(lines + ["warning: hermes no longer lists its skills dir"]))
    assert any("hermes no longer" in r[3] for r in out["hermes"])
    assert len(glob) == 40
    out, glob = stderr_rows("warning: x\n" * 5)
    assert [r[3] for r in glob] == ["warning: x (x5)"]
    n = cw.MAX_STDERR_ROWS
    many = [f"warning: n{i}" for i in range(n + 7)] + ["warning: hermes no longer lists its skills dir"]
    out, glob = stderr_rows("\n".join(many))
    assert len(glob) == n + 1 and "7 more distinct" in glob[-1][3]
    assert any("hermes no longer" in r[3] for r in out["hermes"])
    _, glob = skills({"a": ALL_OK}, rc=127)
    assert any("rc 127" in r[3] for r in glob)


def test_sentinel_must_be_last_and_every_skill_needs_rows():
    ok = "== a\n  claude linked\n== end\n"
    assert cw.parse_skill_check(ok)[1] is True
    assert cw.parse_skill_check("== end\n== a\n  claude linked\n")[1] is False
    assert cw.parse_skill_check("== a\n  claude linked\n== b\n== end\n")[1] is False
    assert cw.parse_skill_check("== a\n  claude linked\n")[1] is False


def test_cursor_agent_inherits_claude_skill_gaps():
    out, _ = skills({"a": {**ALL_OK, "claude": "missing"}})
    assert [r[1:3] for r in out["cursor-agent"]] == [("cursor-agent/via-claude", "warn")]


def test_cursor_agent_unknown_when_claude_unchecked_and_order_independent():
    unchecked = {**ALL_OK, "claude": "not installed"}
    for order in (TUIS, list(reversed(TUIS))):
        out, _ = cw.observe_skills(REPO, order, runner=runner_for(check_text({"a": unchecked})))
        assert out["cursor-agent"][0][2] == "unknown" and "not checked" in out["cursor-agent"][0][3]
        out, _ = cw.observe_skills(REPO, order, runner=runner_for(check_text({"a": {**ALL_OK, "claude": "missing"}})))
        assert out["cursor-agent"][0][1] == "cursor-agent/via-claude"


def test_cursor_agent_unknown_when_claude_absent_from_report():
    text = check_text({"a": {k: v for k, v in ALL_OK.items() if k != "claude"}})
    out, _ = cw.observe_skills(REPO, TUIS, runner=runner_for(text))
    assert out["claude"][0][2] == "unknown" and out["cursor-agent"][0][2] == "unknown"


def test_partly_unchecked_tui_is_unknown_not_ok(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    good_home(home)
    monkeypatch.setattr(cw, "yaml", None)
    rows = cw.observe(root, home=home, runner=runner_for(check_text({"a": ALL_OK})))
    assert {r[1]: r[2] for r in rows if r[0] == "tui"}["hermes"] == "unknown"


def test_roster_missing_beside_skill_everywhere_is_error(tmp_path):
    root = make_root(tmp_path)
    (root / "config" / "mcp-registry.toml").unlink()
    rows = cw.observe(root, home=tmp_path, runner=runner_for(check_text({"a": ALL_OK})))
    assert rows[0][2] == "error" and "roster missing" in rows[0][3]


# ---- stdio + user-lazy servers (chrome-devtools) ---------------------------------

def test_user_lazy_validates_wrapper_unwrapped_wrong_args_and_secrets(tmp_path, roster):
    good_home(tmp_path)
    # Direct unwrapped npx warns as unwrapped
    write_claude(tmp_path, {"chrome-devtools": {"type": "stdio", "command": "npx", "args": CDT_ARGS}}, denied=["bezalel"])
    st, detail = mcp(tmp_path, roster)["claude/chrome-devtools"]
    assert st == "warn" and "unwrapped" in detail and "mcp-lazy" in detail

    # Wrong wrapped args with secret env -> warns without leaking secrets
    write_claude(
        tmp_path,
        {"chrome-devtools": {
            "type": "stdio",
            "command": str(tmp_path / ".local" / "libexec" / "ade" / "mcp-lazy"),
            "args": ["--id", "chrome-devtools", "--", "/opt/homebrew/bin/npx", "--token=s3cret"],
            "env": {"TOKEN": "s3cret"},
        }},
        denied=["bezalel"],
    )
    st, detail = mcp(tmp_path, roster)["claude/chrome-devtools"]
    assert st == "warn" and "wrong-command" in detail and "s3cret" not in detail and "re-add it" in detail

    # Relative child command rejected (violates mcp-lazy hardening)
    write_claude(
        tmp_path,
        {"chrome-devtools": {
            "type": "stdio",
            "command": str(tmp_path / ".local" / "libexec" / "ade" / "mcp-lazy"),
            "args": ["--id", "chrome-devtools", "--", "npx", *CDT_ARGS],
        }},
        denied=["bezalel"],
    )
    st, detail = mcp(tmp_path, roster)["claude/chrome-devtools"]
    assert st == "warn" and "absolute path" in detail

    # Missing --id
    write_claude(
        tmp_path,
        {"chrome-devtools": {
            "type": "stdio",
            "command": str(tmp_path / ".local" / "libexec" / "ade" / "mcp-lazy"),
            "args": ["--idle", "600", "--", "/opt/homebrew/bin/npx", *CDT_ARGS],
        }},
        denied=["bezalel"],
    )
    assert "missing '--id chrome-devtools'" in mcp(tmp_path, roster)["claude/chrome-devtools"][1]

    # Disabled
    write_claude(tmp_path, {"chrome-devtools": {**lazy_cdt(tmp_path), "enabled": False}}, denied=["bezalel"])
    assert "disabled" in mcp(tmp_path, roster)["claude/chrome-devtools"][1]

    # Non-table / http type / missing
    write_claude(tmp_path, {"chrome-devtools": "nope"}, denied=["bezalel"])
    assert "wrong-type" in mcp(tmp_path, roster)["claude/chrome-devtools"][1]
    write_claude(tmp_path, {"chrome-devtools": {"type": "http", "url": "http://x/mcp"}}, denied=["bezalel"])
    assert "wrong-type" in mcp(tmp_path, roster)["claude/chrome-devtools"][1]
    write_claude(tmp_path, {}, denied=["bezalel"])
    assert "missing" in mcp(tmp_path, roster)["claude/chrome-devtools"][1]

    # Valid without explicit type (defaults to stdio)
    valid_no_type = {k: v for k, v in lazy_cdt(tmp_path).items() if k != "type"}
    write_claude(tmp_path, {"chrome-devtools": valid_no_type}, denied=["bezalel"])
    assert mcp(tmp_path, roster)["claude/chrome-devtools"][0] == "ok"


@pytest.mark.parametrize("entry,reason", [
    (None, "missing"),
    ({"command": "npx", "args": CDT_ARGS}, "unwrapped"),
    ({"command": "node", "args": CDT_ARGS}, "wrong-command"),
    ({"command": "npx", "args": ["--secret=DO-NOT-PRINT"], "env": {"TOKEN": "DO-NOT-PRINT"}}, "unwrapped"),
    ({"url": "https://example.com/DO-NOT-PRINT", "command": "npx", "args": CDT_ARGS}, "wrong-type"),
    ({"command": "npx", "args": CDT_ARGS, "enabled": False}, "disabled"),
])
def test_codex_user_lazy_detects_drift_without_printing_values(tmp_path, roster, entry, reason):
    body = '[mcp_servers.chrome-devtools]\n' if entry is not None else ''
    for key, value in (entry or {}).items():
        if key == "env":
            body += 'env = { TOKEN = "DO-NOT-PRINT" }\n'
        else:
            body += f'{key} = {json.dumps(value)}\n'
    write_codex(tmp_path, body)
    st, detail = mcp(tmp_path, roster)["codex/chrome-devtools"]
    assert st == "warn" and reason in detail and "DO-NOT-PRINT" not in detail
    if reason != "disabled":
        assert "codex mcp add chrome-devtools --" in detail
        assert "claude" not in detail and "--scope" not in detail


def test_stdio_tilde_expansion_and_cursor_stdio(tmp_path):
    p = tmp_path / "r.toml"
    p.write_text(
        'schema_version = 1\n[[server]]\nid="aws-mcp"\ntransport="stdio"\n'
        'command="~/.local/bin/mcp-proxy-for-aws"\nargs=["https://aws-mcp.us-east-1.api.aws/mcp"]\n'
        'owner="per-session"\nstate="shared-safe"\nauth={kind="env",keys=["AWS_MCP_PROXY_PROFILES"],store="none"}\n'
        'capabilities=["aws"]\nexpected={ codex = "user", cursor-agent = "user" }\n',
        encoding="utf-8",
    )
    reg = cw.load_registry(p, TUIS)
    expanded = str(tmp_path / ".local" / "bin" / "mcp-proxy-for-aws")
    write_codex(
        tmp_path,
        f'[mcp_servers.aws-mcp]\ncommand = "{expanded}"\nargs = ["https://aws-mcp.us-east-1.api.aws/mcp"]\n',
    )
    write_cursor(
        tmp_path,
        {"aws-mcp": {"command": expanded, "args": ["https://aws-mcp.us-east-1.api.aws/mcp"]}},
    )
    got = mcp(tmp_path, reg)
    assert got["codex/aws-mcp"][0] == "ok"
    assert got["cursor-agent/aws-mcp"][0] == "ok"


@pytest.mark.parametrize("body", [
    'command="npx; rm"\nargs=[]\nexpected={ claude = "user" }\n',
    'command="npx"\nargs=["$(id)"]\nexpected={ claude = "user" }\n',
    'command="npx"\nargs=[1]\nexpected={ claude = "user" }\n',
    'command="../npx"\nargs=[]\nexpected={ claude = "user" }\n',
    'command="npx"\nargs="x"\nexpected={ claude = "user" }\n',
    'command="npx"\nargs={a=1}\nexpected={ claude = "user" }\n',
    'command=1\nargs=[]\nexpected={ claude = "user" }\n',
    'command="npx"\nargs=["x\\n"]\nexpected={ claude = "user" }\n',
    'command="npx"\nurl="http://x/mcp"\nexpected={ claude = "user" }\n',
])
def test_stdio_roster_validation(tmp_path, body):
    p = tmp_path / "r.toml"
    p.write_text(
        'schema_version = 1\n[[server]]\nid="a"\ntransport="stdio"\n'
        'owner="per-session"\nstate="per-session"\nauth={kind="none",keys=[],store="none"}\n'
        'capabilities=["cap"]\n' + body,
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        cw.load_roster(p, TUIS)
