"""ade-install doctor: observe-only TUI wiring check (MCP registrations + skill links), fixture HOME."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))
import ade_client_wiring as cw
import ade_install as ai

FC = "http://127.0.0.1:18804/mcp"
BM = "http://127.0.0.1:18796/mcp"
TUIS = cw.tui_roster(REPO)


def write_claude(home, servers):
    (home / ".claude.json").write_text(json.dumps({"mcpServers": servers}))


def write_codex(home, body):
    (home / ".codex").mkdir(exist_ok=True)
    (home / ".codex" / "config.toml").write_text(body)


def write_cursor(home, servers):
    (home / ".cursor").mkdir(exist_ok=True)
    (home / ".cursor" / "mcp.json").write_text(json.dumps({"mcpServers": servers}))


def write_hermes(home, body):
    (home / ".hermes").mkdir(exist_ok=True)
    (home / ".hermes" / "config.yaml").write_text(body)


GOOD_CODEX = f'[mcp_servers.firecrawl]\nurl = "{FC}"\n[mcp_servers.basic-memory]\nurl = "{BM}"\n'
GOOD_HERMES = f"mcp_servers:\n  basic-memory:\n    url: {BM}\n    enabled: true\n"


def good_home(home):
    write_claude(home, {"firecrawl": {"type": "http", "url": FC},
                        "basic-memory": {"type": "http", "url": BM + "/"}})
    write_codex(home, GOOD_CODEX)
    write_cursor(home, {"basic-memory": {"url": BM}})
    write_hermes(home, GOOD_HERMES)


@pytest.fixture
def roster():
    return cw.load_roster(REPO / "config" / "mcp-clients.toml", TUIS)


def mcp(home, roster):
    return {r[1]: (r[2], r[3]) for rows in cw.observe_mcp(roster, TUIS, home=home).values() for r in rows}


# ---- TUI roster comes from skill-everywhere, not a second list ----------------

def test_tui_roster_is_the_skill_everywhere_table():
    assert TUIS[:3] == ["claude", "codex", "pi"] and "cursor-agent" in TUIS and "hermes" in TUIS
    for retired in ("opencode", "omp", "crush", "kiro", "tuios", "antigravity", "agy"):
        assert retired not in TUIS


def test_roster_matches_docs_scope_column_exactly():
    docs = (REPO / "docs" / "mcp-servers.md").read_text()
    names = {"claude": "Claude Code", "codex": "Codex", "cursor-agent": "Cursor", "hermes": "Hermes"}
    for row in cw.load_roster(REPO / "config" / "mcp-clients.toml", TUIS):
        line = next(l for l in docs.splitlines() if l.startswith(f"| `{row['id']}`"))
        cells = [c.strip() for c in line.strip("|").split("|")]
        assert row["url"] in cells[1], row["id"]
        scope = cells[2].split("(")[0]
        assert {c for c, n in names.items() if n in scope} == set(row["clients"]), row["id"]


@pytest.mark.parametrize("sid,url,clients", [
    ("a b", "http://x/mcp", ["codex"]), ("a;rm", "http://x/mcp", ["codex"]),
    ("a", "http://x/mcp; rm -rf ~", ["codex"]), ("a", "http://x/$(id)", ["codex"]),
    ("a", "ftp://x", ["codex"]), ("a", "http://x", ["vim"]), ("a", "http://x", []),
])
def test_roster_validation(tmp_path, sid, url, clients):
    p = tmp_path / "r.toml"
    p.write_text(f'[[server]]\nid="{sid}"\nurl="{url}"\nclients={json.dumps(clients)}\n')
    with pytest.raises(ValueError):
        cw.load_roster(p, TUIS)


# ---- MCP -----------------------------------------------------------------------

def test_mcp_all_ok(tmp_path, roster):
    good_home(tmp_path)
    got = mcp(tmp_path, roster)
    assert {k: v[0] for k, v in got.items()} == {
        "claude/firecrawl": "ok", "claude/basic-memory": "ok", "codex/firecrawl": "ok",
        "codex/basic-memory": "ok", "cursor-agent/basic-memory": "ok", "hermes/basic-memory": "ok"}


def test_mcp_missing_gives_exact_fix_and_runs_nothing(tmp_path, roster, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("ran a command"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("ran a command"))
    good_home(tmp_path)
    write_claude(tmp_path, {"graft": {"command": "graft"}})
    st, detail = mcp(tmp_path, roster)["claude/firecrawl"]
    assert st == "warn" and "missing" in detail
    assert f"claude mcp add --scope user --transport http firecrawl {FC}" in detail


def test_mcp_wrong_url_wrong_type_disabled(tmp_path, roster):
    good_home(tmp_path)
    write_claude(tmp_path, {"firecrawl": {"type": "http", "url": "http://127.0.0.1:9/mcp"},
                            "basic-memory": {"url": BM}})  # no type: read as stdio
    write_codex(tmp_path, GOOD_CODEX.replace(BM, BM + '"\nenabled = false\n#'))
    write_cursor(tmp_path, {"basic-memory": {"url": "http://127.0.0.1:1/mcp"}})
    write_hermes(tmp_path, GOOD_HERMES.replace("true", "false"))
    got = mcp(tmp_path, roster)
    assert "wrong-url" in got["claude/firecrawl"][1] and "127.0.0.1:9" in got["claude/firecrawl"][1]
    assert "wrong-type" in got["claude/basic-memory"][1]
    assert "disabled" in got["codex/basic-memory"][1]
    assert "wrong-url" in got["cursor-agent/basic-memory"][1]
    assert "disabled" in got["hermes/basic-memory"][1]
    assert all(v[0] == "warn" for k, v in got.items() if k != "codex/firecrawl")


def test_mcp_never_prints_values(tmp_path, roster):
    secret = "SEKRET-TOKEN-123"
    good_home(tmp_path)
    write_claude(tmp_path, {"firecrawl": {
        "type": "http", "url": f"http://user:{secret}@127.0.0.1:9/x?key={secret}",
        "headers": {"Authorization": f"Bearer {secret}"}, "env": {"K": secret}}})
    write_codex(tmp_path, f'[mcp_servers.firecrawl]\nurl = "{FC}"\nhttp_headers = {{ A = "{secret}" }}\n')
    assert secret not in json.dumps(cw.observe_mcp(roster, TUIS, home=tmp_path))


def test_mcp_path_secret_control_chars_and_schemeless_url_not_printed(tmp_path, roster):
    good_home(tmp_path)
    for bad in ("https://mcp.example.dev/PATHSECRET/v2/mcp\x1b[31m", "LEAKME:pw@host/path"):
        write_claude(tmp_path, {"firecrawl": {"type": "http", "url": bad}})
        st, detail = mcp(tmp_path, roster)["claude/firecrawl"]
        assert st == "warn" and "PATHSECRET" not in detail and "LEAKME" not in detail and "\x1b" not in detail


def test_mcp_absent_files_warn_not_crash(tmp_path, roster):
    assert {s for s, _ in mcp(tmp_path, roster).values()} == {"warn"}


def test_mcp_corrupt_and_deeply_nested_config_is_error_without_content(tmp_path, roster):
    good_home(tmp_path)
    (tmp_path / ".claude.json").write_text("{not json SEKRET")
    (tmp_path / ".cursor" / "mcp.json").write_text("[" * 100000)
    got = mcp(tmp_path, roster)
    assert got["claude/*"][0] == "error" and "SEKRET" not in got["claude/*"][1]
    assert got["cursor-agent/*"][0] == "error"


def test_mcp_non_table_entry_is_wrong_type_with_swap_fix(tmp_path, roster):
    good_home(tmp_path)
    write_claude(tmp_path, {"firecrawl": "oops", "basic-memory": {"type": "http", "url": BM}})
    st, detail = mcp(tmp_path, roster)["claude/firecrawl"]
    assert st == "warn" and "claude mcp remove --scope user firecrawl && claude mcp add" in detail


def test_mcp_client_without_readable_config_is_unknown_never_failure(tmp_path):
    roster = [{"id": "x", "url": "http://127.0.0.1:1/mcp", "clients": ["pi", "grokbot"]}]
    got = cw.observe_mcp(roster, TUIS, home=tmp_path)
    for tui in ("pi", "grokbot"):
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
    assert len(glob) == 2 and "does not exist" in glob[0][3] and glob[1][3] == "noise"  # unexplained stderr is kept


@pytest.mark.parametrize("state,want", [
    ("linked", "ok"), ("via ~/.claude/skills", "ok"), ("copied", "ok"), ("not installed", "unknown"),
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
    env = {"SKILL_EVERYWHERE_ADE": str(ade), "SKILL_EVERYWHERE_PRIVATE": str(tmp_path / "p"),
           "SKILL_EVERYWHERE_SITE": str(tmp_path / "s")}
    (home / "agent-data" / "workflows").mkdir(parents=True)  # Grok Bot copy target present, copy absent
    import os

    def run(argv, e):
        full = {**os.environ, **e, **env, "PATH": f"{bindir}:{e['PATH']}"}
        return subprocess.run(argv, capture_output=True, text=True, env=full, timeout=60)
    out, _ = cw.observe_skills(REPO, TUIS, home=home, runner=run)
    assert out["claude"][0][:3] == ("skill", "claude/*", "ok")
    assert {r[1] for r in out["codex"]} == {"codex/missing"}
    # copy-target rows really print `missing (<dest>)`: classified, not "other"
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
    shutil.copy(REPO / "config" / "mcp-clients.toml", root / "config" / "mcp-clients.toml")
    return root


def test_observe_one_summary_line_per_tui_then_details(tmp_path):
    root = make_root(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    good_home(home)
    write_claude(home, {})
    rows = cw.observe(root, home=home, runner=runner_for(check_text({"a": ALL_OK})))
    summaries = [r for r in rows if r[0] == "tui"]
    assert [r[1] for r in summaries] == TUIS
    by = {r[1]: r for r in summaries}
    assert by["claude"][2] == "warn" and "2 gap(s)" in by["claude"][3]
    assert by["codex"][2] == "ok" and by["pi"][2] == "ok" and by["grokbot"][2] == "unknown"
    assert by["hermes"][2] == "ok" and by["cursor-agent"][2] == "ok"


def test_observe_silent_without_roster_or_script(tmp_path):
    assert cw.observe(tmp_path, home=tmp_path) == []


def test_observe_bad_client_in_roster_is_error(tmp_path):
    root = make_root(tmp_path)
    (root / "config" / "mcp-clients.toml").write_text(
        '[[server]]\nid="a"\nurl="http://x/mcp"\nclients=["opencode"]\n')
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
    write_claude(home, {})
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
    assert not any(k in seen for k in literal) and all(k in seen for k in relative)  # live: real roots kept
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
    cp = cw._default_runner([str(script)], dict(__import__("os").environ))
    assert "\ufffd" in cp.stdout


def stderr_rows(err, rc=0):
    out, glob = skills({"a": ALL_OK}, stderr=err, rc=rc)
    return out, glob


def test_stderr_attribution_is_structural_not_a_word_match():
    # a codex line whose target mentions claude belongs to codex only (it used to land on claude)
    out, glob = stderr_rows("warning: codex global instructions dangling: /h/.codex/AGENTS.md -> /h/.claude/CLAUDE.md\n")
    assert [r[1] for r in out["codex"] if r[0] == "skill" and r[2] == "warn"] == ["codex/warning"]
    assert not [r for r in out["claude"] if r[2] == "warn"] and out["cursor-agent"][0][2] == "ok"
    assert glob == []
    # a TUI token inside a path, or a skill that shares a TUI's name, stays global
    out, glob = stderr_rows("warning: skill root /private/tmp/claude-502/x does not exist\n"
                            "warning: claude: render for /d failed; treating as stale copy\n")
    assert len(glob) == 2 and not any(r[2] == "warn" for rows in out.values() for r in rows)
    out, glob = stderr_rows("error: x warning: hermes y\n")  # mid-line prefix must not attach
    assert [r[3] for r in glob] == ["error: x warning: hermes y"] and out["hermes"][0][2] == "ok"
    out, glob = stderr_rows("error: boom\n", rc=1)
    assert [r[3] for r in glob] == ["error: boom"]


def test_stderr_every_line_scanned_deduped_and_capped():
    lines = [f"warning: skill root /r{i} does not exist" for i in range(40)]
    out, glob = stderr_rows("\n".join(lines + ["warning: hermes no longer lists its skills dir"]))
    assert any("hermes no longer" in r[3] for r in out["hermes"])  # last of 41 lines still attached
    assert len(glob) == 40
    out, glob = stderr_rows("warning: x\n" * 5)
    assert [r[3] for r in glob] == ["warning: x (x5)"]
    n = cw.MAX_STDERR_ROWS
    many = [f"warning: n{i}" for i in range(n + 7)] + ["warning: hermes no longer lists its skills dir"]
    out, glob = stderr_rows("\n".join(many))
    assert len(glob) == n + 1 and "7 more distinct" in glob[-1][3]
    assert any("hermes no longer" in r[3] for r in out["hermes"])  # past the cap, still attributed
    _, glob = skills({"a": ALL_OK}, rc=127)
    assert any("rc 127" in r[3] for r in glob)


def test_sentinel_must_be_last_and_every_skill_needs_rows():
    ok = "== a\n  claude linked\n== end\n"
    assert cw.parse_skill_check(ok)[1] is True
    assert cw.parse_skill_check("== end\n== a\n  claude linked\n")[1] is False  # skill named like the sentinel
    assert cw.parse_skill_check("== a\n  claude linked\n== b\n== end\n")[1] is False  # header without rows
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
    monkeypatch.setattr(cw, "yaml", None)  # hermes MCP unreadable, skills fine
    rows = cw.observe(root, home=home, runner=runner_for(check_text({"a": ALL_OK})))
    assert {r[1]: r[2] for r in rows if r[0] == "tui"}["hermes"] == "unknown"


def test_roster_missing_beside_skill_everywhere_is_error(tmp_path):
    root = make_root(tmp_path)
    (root / "config" / "mcp-clients.toml").unlink()
    rows = cw.observe(root, home=tmp_path, runner=runner_for(check_text({"a": ALL_OK})))
    assert rows[0][2] == "error" and "roster missing" in rows[0][3]
