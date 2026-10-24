"""fleet.py lists every Paseo agent of any provider, not only Claude Code TUIs (2026-10-23).

A cline agent (`paseo ls` showed it, `fleet.py list` and `relay.py <id>` did not) looked offline to its peers.
These tests drive `fleet._paseo_rows` / `fleet.sessions` against a fake `paseo` CLI that records its argv; every id is
plainly fake.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "session-finder"))
sys.path.insert(0, str(ROOT / "skills" / "helm"))

import fleet  # noqa: E402  # pyright: ignore[reportMissingImports]
import helm  # noqa: E402  # pyright: ignore[reportMissingImports]

CLINE = "aaaaaaaa-1111-4000-8000-000000000001"
CLAUDE = "aaaaaaaa-1111-4000-8000-000000000002"
OMP = "bbbbbbbb-1111-4000-8000-000000000003"
OLD = "cccccccc-1111-4000-8000-000000000004"      # archived

FAKE = """#!/bin/bash
echo "$*" >> "$FAKE_LOG"
[ -n "$FAKE_SLEEP" ] && exec sleep "$FAKE_SLEEP"
[ -n "$FAKE_RC" ] && exit "$FAKE_RC"
case " $* " in *" -a "*) cat "$FAKE_ALL" ;; *) cat "$FAKE_LIVE" ;; esac
"""


def agent(pid: str, provider: str, status: str = "idle", name: str = "n", cwd: str = "~/src/x") -> dict[str, str]:
    return {"id": pid, "shortId": pid[:7], "name": name, "provider": provider, "thinking": "auto", "status": status,
            "cwd": cwd, "created": "1 hour ago"}


LIVE = [agent(CLINE, "cline/cline-pass/deepseek-v4-pro", name="Dann", cwd="~/src/techno-euphora"),
        agent(CLAUDE, "claude/claude-opus-5-5", "running"),
        agent(OMP, "omp/anthropic/claude-sonnet-5-5", "running")]
ARCHIVED = [agent(OLD, "cline/cline-pass/kimi-k3", "closed")]


@pytest.fixture
def paseo(tmp_path, monkeypatch):
    cli = tmp_path / "paseo"
    cli.write_text(FAKE)
    cli.chmod(0o755)
    log = tmp_path / "log"
    live, everything = tmp_path / "live.json", tmp_path / "all.json"
    live.write_text(json.dumps(LIVE))
    everything.write_text(json.dumps(LIVE + ARCHIVED))
    for k in ("FAKE_SLEEP", "FAKE_RC", "PASEO_AGENT_ID"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PASEO_CLI", str(cli))
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("FAKE_LIVE", str(live))
    monkeypatch.setenv("FAKE_ALL", str(everything))
    monkeypatch.setattr(fleet, "_paseo_hosting", lambda anc: set())    # hermetic: the runner's ancestry is not under test
    return type("P", (), {"log": log, "live": live, "all": everything})


def rows(have=(), archived=False):
    return fleet._paseo_rows(set(have), set(), archived)


def test_every_provider_is_listed_as_a_paseo_row(paseo):
    got = {r["paseo"]: r for r in rows()}
    assert set(got) == {CLINE, CLAUDE, OMP}
    r = got[CLINE]
    assert (r["agent"], r["host"], r["chan"], r["id"], r["name"]) == ("cline", "paseo", ("paseo", CLINE), CLINE[:8], "Dann")
    assert (r["status"], r["paseo_state"], r["cwd"]) == ("idle", "idle", fleet.HOME + "/src/techno-euphora")
    assert r["where"] == f"host=paseo agent={CLINE}" and "relay.py" in r["reach"]
    assert got[OMP]["status"] == "working" and got[OMP]["agent"] == "omp"


def test_argv_is_a_list_with_global_background_json(paseo):
    rows()
    assert paseo.log.read_text().splitlines() == ["ls -g --json --background"]


def test_archived_agents_only_with_the_all_mode_and_marked_ended(paseo):
    assert OLD not in {r["paseo"] for r in rows()}
    got = {r["paseo"]: r for r in rows(archived=True)}
    assert set(got) == {CLINE, CLAUDE, OMP, OLD}
    old = got[OLD]
    assert (old["status"], old["paseo_state"], old["ended"], old["archived"]) == ("ended", "archived", True, True)
    assert "refuses" in old["reach"]
    assert "ls -g --json -a" in paseo.log.read_text()


def test_dedupe_is_by_paseo_id_never_by_directory(paseo):
    # the same Paseo id in HAVE hides the agent; a row in the same directory under another id (HAVE holds ids only) does not
    assert {r["paseo"] for r in rows(have={CLAUDE})} == {CLINE, OMP}
    assert {r["paseo"] for r in rows(have={"dddddddd-1111-4000-8000-000000000009"})} == {CLINE, CLAUDE, OMP}


def test_sessions_skips_a_paseo_agent_another_row_already_stands_for(paseo, monkeypatch):
    known = fleet._rec(id="deadbeef", agent="claude", host="paseo", chan=("paseo", CLAUDE), paseo=CLAUDE, sid="s" * 36)
    for name in ("_launched", "_other_herdr", "_proc_scan", "_hermes_gateway"):
        monkeypatch.setattr(fleet, name, lambda *a, **k: [])
    monkeypatch.setattr(fleet, "_claude_sessions", lambda *a, **k: [known])
    monkeypatch.setattr(fleet, "_pane_only", lambda *a: ([], []))
    monkeypatch.setattr(fleet, "herdr_json", lambda *a: {})
    monkeypatch.setattr(fleet, "ancestors", lambda: set())
    monkeypatch.setattr(fleet, "proc_table", lambda: {})
    out = fleet.sessions()
    assert sorted(s["paseo"] for s in out if s.get("paseo")) == sorted([CLAUDE, CLINE, OMP])
    assert sum(1 for s in out if s.get("paseo") == CLAUDE) == 1


@pytest.mark.parametrize("bad", ["--help", "../x", "AAAAAAAA-1111-4000-8000-000000000009", "short", "", None, 7,
                                 CLINE + "\n--x"])
def test_an_id_that_is_not_a_lowercase_uuid_never_becomes_a_row(paseo, bad):
    paseo.live.write_text(json.dumps([agent("x", "cline"), {**agent(CLINE, "cline"), "id": bad}, "junk", 5, None]))
    assert rows() == []


def test_provider_label_is_sanitised(paseo):
    paseo.live.write_text(json.dumps([{**agent(CLINE, "cline"), "provider": "evil label;rm"},
                                      {**agent(OMP, "omp"), "provider": None}]))
    assert {r["paseo"]: r["agent"] for r in rows()} == {CLINE: "paseo", OMP: "paseo"}


def test_status_is_mapped_and_unknown_ones_keep_their_raw_name(paseo):
    paseo.live.write_text(json.dumps([agent(CLINE, "cline", "running"), agent(OMP, "omp", "error")]))
    got = {r["paseo"]: r for r in rows()}
    assert (got[CLINE]["status"], got[CLINE]["paseo_state"]) == ("working", "running")
    assert (got[OMP]["status"], got[OMP]["paseo_state"]) == ("error", "error")


def test_the_callers_own_agent_row_is_self(paseo, monkeypatch):
    monkeypatch.setenv("PASEO_AGENT_ID", CLINE)
    assert {r["paseo"]: r["self"] for r in rows()} == {CLINE: True, CLAUDE: False, OMP: False}
    monkeypatch.delenv("PASEO_AGENT_ID")
    monkeypatch.setattr(fleet, "_paseo_hosting", lambda anc: {OMP})    # an ancestor the daemon hosts for OMP
    assert {r["paseo"]: r["self"] for r in rows()} == {CLINE: False, CLAUDE: False, OMP: True}


def test_missing_failing_slow_or_garbled_cli_lists_nothing(paseo, monkeypatch, tmp_path):
    monkeypatch.setenv("PASEO_CLI", str(tmp_path / "nope"))
    assert rows() == []
    monkeypatch.setenv("PASEO_CLI", str(tmp_path / "paseo"))
    monkeypatch.setenv("FAKE_RC", "3")
    assert rows() == []
    monkeypatch.delenv("FAKE_RC")
    paseo.live.write_text("not json")
    assert rows() == []
    paseo.live.write_text('{"id": "x"}')
    assert rows() == []
    monkeypatch.setenv("FAKE_SLEEP", "5")
    monkeypatch.setattr(fleet, "PASEO_LS_TIMEOUT", 0.3)
    assert rows() == []


def test_a_failed_archived_call_still_lists_the_live_agents(paseo, monkeypatch):
    paseo.all.write_text("garbage")
    assert {r["paseo"] for r in rows(archived=True)} == {CLINE, CLAUDE, OMP}


def test_nothing_is_cached_between_calls(paseo):
    assert {r["paseo"] for r in rows()} == {CLINE, CLAUDE, OMP}
    paseo.live.write_text(json.dumps([agent(OMP, "omp")]))
    assert {r["paseo"] for r in rows()} == {OMP}


def test_reach_text_tells_a_non_steering_agent_from_a_steering_one(paseo):
    got = {r["paseo"]: r["reach"] for r in rows()}
    assert "cannot steer" in got[CLINE] and "queued at its next tool round" not in got[CLINE]
    assert "queued at its next tool round" in got[OMP] and "cannot steer" not in got[OMP]


def test_helm_keeps_a_listed_paseo_agent_out_of_the_attention_queue(paseo):
    r = rows()[0]
    assert r["status"] == "idle" and not r["sid"]
    it = helm.classify(r, {})
    assert (it["kind"], it["open"]) == ("remote", False)
