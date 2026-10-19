"""bin/context-budget-check on a saved `claude -p "/context"` output (tests/fixtures/context-now.txt)."""
import copy
import importlib.machinery
import importlib.util
import json
import pathlib
import stat

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "context-budget-check"
FIXTURE = ROOT / "tests" / "fixtures" / "context-now.txt"
DIR = "~/src/djbclark-ade"


def load():
    loader = importlib.machinery.SourceFileLoader("context_budget_check", str(BIN))
    spec = importlib.util.spec_from_loader("context_budget_check", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


cbc = load()


@pytest.fixture(autouse=True)
def fixture_home(monkeypatch):
    """The fixture was saved under /Users/djbclark; paths shorten to ~ against this HOME."""
    monkeypatch.setenv("HOME", "/Users/djbclark")


def fixture_entry():
    return cbc.parse_context(FIXTURE.read_text())


def config(tmp_path, **budget):
    lines = ['dirs = ["%s"]' % DIR, "[budget]"] + [f"{k} = {v}" for k, v in budget.items()]
    p = tmp_path / "budget.toml"
    p.write_text("\n".join(lines) + "\n")
    return p


def fake_ping(tmp_path):
    """A hermes-ping stand-in that appends its argument to ping.log."""
    log = tmp_path / "ping.log"
    script = tmp_path / "ping"
    script.write_text(f'#!/bin/sh\nprintf "%s\\n" "$1" >> {log}\n')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script, log


# ---------------------------------------------------------------- parsing

def test_tokens_cells():
    assert cbc.tokens("2.5k") == 2500
    assert cbc.tokens("875") == 875
    assert cbc.tokens("~170") == 170
    assert cbc.tokens("< 20") == 0
    assert cbc.tokens("115.6k") == 115600
    assert cbc.tokens("1.2M") == 1_200_000


def test_parse_fixture_categories():
    e = fixture_entry()
    assert e["model"] == "claude-opus-5-5[1m]"
    assert (e["total"], e["window"]) == (46300, 400000)
    c = e["categories"]
    assert c["system_prompt"] == 2500
    assert c["mcp_tools"] == 11000
    assert c["mcp_instructions"] == 4800
    assert c["mcp_tools_deferred"] == 115600
    assert c["system_tools_deferred"] == 15000
    assert c["custom_agents"] == 875
    assert c["memory"] == 14500
    assert c["skills"] == 10000
    assert c["messages"] == 2700
    assert c["autocompact_buffer"] == 33000


def test_parse_fixture_subtables():
    e = fixture_entry()
    mem = {m["path"]: m["tokens"] for m in e["memory_files"]}
    assert mem["~/.claude/CLAUDE.md"] == 8300
    assert mem["~/src/djbclark-ade/CLAUDE.md"] == 5800
    assert len(mem) == 3
    skills = {s["skill"]: s["tokens"] for s in e["skills"]}
    assert skills["firecrawl"] == 310
    assert skills["reorg-orca"] == 0
    assert skills["dataviz"] == 480
    assert len(e["agents"]) == 8
    servers = {t["server"] for t in e["mcp_tools"]}
    assert {"firecrawl", "claude_ai_Firecrawl", "bezalel", "arxiv"} <= servers
    assert len(e["mcp_tools"]) == 250


def test_rows_are_the_counted_ones():
    r = cbc.rows(fixture_entry())
    assert set(r) == {"system_prompt", "mcp_tools", "mcp_instructions", "custom_agents", "memory",
                      "skills", "total"}
    # The counted rows plus Messages add up to the "Tokens:" figure, give or take rounding.
    assert abs(sum(v for k, v in r.items() if k != "total") + 2700 - r["total"]) < 300


def test_missing_zero_row_reads_as_zero_and_garbage_is_refused():
    text = "\n".join(ln for ln in FIXTURE.read_text().splitlines() if not ln.startswith("| MCP tools |"))
    e = cbc.parse_context(text)
    assert "mcp_tools" not in e["categories"]
    assert cbc.rows(e).get("mcp_tools", 0) == 0
    for bad in ("", "hello", "**Tokens:** 1k / 2k\n"):
        try:
            cbc.parse_context(bad)
        except cbc.ParseError:
            continue
        raise AssertionError(f"parsed {bad!r}")


# ---------------------------------------------------------------- budget

def test_budget_breaches_on_defaults():
    e = fixture_entry()
    alerts = cbc.compare(DIR, e, None, None, cbc.budget_for({"budget": {}}, DIR))
    assert {a["row"] for a in alerts} == {"total", "memory", "skills", "mcp_tools"}
    assert all(a["kind"] == "breach" for a in alerts)
    mem = next(a for a in alerts if a["row"] == "memory")
    assert (mem["value"], mem["budget"], mem["over"]) == (14500, 9000, 5500)


def test_budget_directory_override():
    cfg = {"budget": {"total": 32000, "memory": 9000, "~": {"memory": 20000}}}
    assert cbc.budget_for(cfg, "~")["memory"] == 20000
    assert cbc.budget_for(cfg, "~")["total"] == 32000
    assert cbc.budget_for(cfg, DIR)["memory"] == 9000
    assert cbc.budget_for(cfg, DIR)["grow_alert"] == 2000


def test_no_breach_inside_budget():
    e = fixture_entry()
    b = {"total": 50000, "memory": 20000, "skills": 20000, "mcp_tools": 20000,
         "mcp_instructions": 20000, "grow_alert": 2000}
    assert cbc.compare(DIR, e, None, None, b) == []


def test_real_config_parses_and_overrides_home():
    cfg = cbc.load_config(cbc.CONFIG)
    assert cfg["dirs"] == [DIR, "~"]
    base = cbc.budget_for(cfg, DIR)
    assert (base["total"], base["memory"], base["skills"], base["mcp_tools"],
            base["mcp_instructions"], base["grow_alert"]) == (32000, 9000, 7500, 6500, 5000, 2000)
    assert cbc.budget_for(cfg, "~")["total"] > base["total"]


# ---------------------------------------------------------------- growth

BIG = {"total": 99000, "memory": 99000, "skills": 99000, "mcp_tools": 99000,
       "mcp_instructions": 99000, "grow_alert": 2000}


def grown(entry, row, by, path="~/.claude/CLAUDE.md"):
    """A copy of the previous day: `entry` with `row` smaller by `by` (so today is `by` higher)."""
    prev = copy.deepcopy(entry)
    prev["categories"][row] -= by
    prev["total"] -= by
    for m in prev["memory_files"]:
        if m["path"] == path:
            m["tokens"] -= by
    return prev


def test_growth_at_threshold_alerts_and_below_does_not():
    e = fixture_entry()
    alerts = cbc.compare(DIR, e, grown(e, "memory", 2000), "2026-10-17", BIG)
    assert {(a["row"], a["kind"], a["delta"]) for a in alerts} == {("memory", "growth", 2000),
                                                                  ("total", "growth", 2000)}
    assert cbc.compare(DIR, e, grown(e, "memory", 1999), "2026-10-17", BIG) == []


def test_growth_needs_a_previous_entry_and_ignores_shrinking():
    e = fixture_entry()
    assert cbc.compare(DIR, e, None, None, BIG) == []
    assert cbc.compare(DIR, grown(e, "memory", 5000), e, "2026-10-17", BIG) == []


def test_deferred_and_messages_rows_do_not_alert():
    e = fixture_entry()
    prev = copy.deepcopy(e)
    prev["categories"]["mcp_tools_deferred"] -= 50000
    prev["categories"]["messages"] -= 50000
    assert cbc.compare(DIR, e, prev, "2026-10-17", BIG) == []


def test_top_item_is_the_biggest_riser_else_the_biggest():
    e = fixture_entry()
    assert cbc.top_item(e, grown(e, "memory", 2500, "~/src/djbclark-ade/CLAUDE.md"), "memory") \
        == "~/src/djbclark-ade/CLAUDE.md +2.5k"
    assert cbc.top_item(e, None, "memory") == "~/.claude/CLAUDE.md 8.3k"
    assert cbc.top_item(e, None, "skills") == "dataviz 480"  # largest skill, tokens only


# ---------------------------------------------------------------- ping text and the CLI

def run(capsys, *argv):
    rc = cbc.main(list(argv))
    return rc, capsys.readouterr().out


def test_dry_run_ping_for_a_breach(tmp_path, capsys):
    cfg = config(tmp_path)  # defaults: 32k total, 9k memory, ...
    rc, out = run(capsys, "--from-file", str(FIXTURE), "--config", str(cfg), "--dry-run",
                  "--state-dir", str(tmp_path / "state"), "--date", "2026-10-18")
    assert rc == 1
    assert ("would ping: djbclark-ade: fresh-session context 46.3k (budget 32k) in ~/src/djbclark-ade: "
            "memory 14.5k > 9k, top: ~/.claude/CLAUDE.md 8.3k (+3 more)") in out
    assert not (tmp_path / "state").exists()  # --dry-run writes nothing


def test_ping_text_for_a_rise_names_the_file_and_the_day(tmp_path, capsys):
    cfg = config(tmp_path, total=99000, memory=99000, skills=99000, mcp_tools=99000, mcp_instructions=99000)
    state = tmp_path / "state"
    state.mkdir()
    prev = grown(fixture_entry(), "memory", 3000, "~/src/djbclark-ade/CLAUDE.md")
    (state / "2026-10-17.json").write_text(json.dumps({"date": "2026-10-17", "dirs": {DIR: prev}}))
    rc, out = run(capsys, "--from-file", str(FIXTURE), "--config", str(cfg), "--dry-run",
                  "--state-dir", str(state), "--date", "2026-10-18")
    assert rc == 1
    assert ("would ping: djbclark-ade: fresh-session context 46.3k (budget 99k) in ~/src/djbclark-ade: "
            "memory +3k since 2026-10-17, top: ~/src/djbclark-ade/CLAUDE.md +3k (+1 more)") in out


def test_compares_with_the_latest_earlier_file_not_today_or_later(tmp_path):
    for d in ("2026-10-10", "2026-10-16", "2026-10-18", "2026-10-19"):
        (tmp_path / f"{d}.json").write_text(json.dumps({"date": d, "dirs": {}}))
    assert cbc.previous(tmp_path, "2026-10-18")[0] == "2026-10-16"
    assert cbc.previous(tmp_path / "none", "2026-10-18") == (None, {})


def test_real_run_pings_once_and_writes_state(tmp_path, capsys, monkeypatch):
    ping, log = fake_ping(tmp_path)
    monkeypatch.setenv("CONTEXT_BUDGET_PING", str(ping))
    cfg = config(tmp_path)
    state = tmp_path / "state"
    rc, out = run(capsys, "--from-file", str(FIXTURE), "--config", str(cfg), "--state-dir", str(state),
                  "--date", "2026-10-18")
    assert rc == 1
    assert len(log.read_text().splitlines()) == 1  # one line per run, however many breaches
    saved = json.loads((state / "2026-10-18.json").read_text())
    assert saved["date"] == "2026-10-18"
    assert saved["dirs"][DIR]["categories"]["memory"] == 14500
    assert saved["dirs"][DIR]["total"] == 46300


def test_within_budget_is_quiet_and_exits_zero(tmp_path, capsys, monkeypatch):
    ping, log = fake_ping(tmp_path)
    monkeypatch.setenv("CONTEXT_BUDGET_PING", str(ping))
    cfg = config(tmp_path, total=99000, memory=99000, skills=99000, mcp_tools=99000, mcp_instructions=99000)
    rc, out = run(capsys, "--from-file", str(FIXTURE), "--config", str(cfg),
                  "--state-dir", str(tmp_path / "state"), "--date", "2026-10-18")
    assert rc == 0
    assert not log.exists()


def test_unmeasurable_exits_three_and_pings(tmp_path, capsys, monkeypatch):
    ping, log = fake_ping(tmp_path)
    monkeypatch.setenv("CONTEXT_BUDGET_PING", str(ping))
    junk = tmp_path / "junk.txt"
    junk.write_text("not context output\n")
    rc, out = run(capsys, "--from-file", str(junk), "--config", str(config(tmp_path)),
                  "--state-dir", str(tmp_path / "state"), "--date", "2026-10-18")
    assert rc == 3
    assert "could not measure" in log.read_text()
    assert not (tmp_path / "state").exists()


def test_a_missing_claude_is_unmeasurable_not_a_crash(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CONTEXT_BUDGET_CLAUDE", str(tmp_path / "no-such-claude"))
    cfg = tmp_path / "c.toml"
    cfg.write_text(f'dirs = ["{tmp_path}"]\n')
    rc, _ = run(capsys, "--config", str(cfg), "--dry-run", "--state-dir", str(tmp_path / "s"))
    assert rc == 3


def test_install_plan_changes_nothing(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("CONTEXT_BUDGET_NO_INSTALL", "1")
    monkeypatch.setenv("CONTEXT_BUDGET_LAUNCH_AGENTS", str(tmp_path))
    rc, out = run(capsys, "install")
    assert rc == 0 and "com.djbclark.context-budget.plist" in out and list(tmp_path.iterdir()) == []
    rc, out = run(capsys, "uninstall")
    assert rc == 0 and "bootout" in out
    plist = (ROOT / "launchd" / "com.djbclark.context-budget.plist").read_text()
    assert "<integer>3</integer>" in plist and "<integer>50</integer>" in plist
