"""fleet.py lists every Paseo agent of any provider, not only Claude Code TUIs (2026-10-23).

A cline agent (`paseo ls` showed it, `fleet.py list` and `relay.py <id>` did not) looked offline to its peers.
These tests drive `fleet._paseo_rows` / `fleet.sessions` against a fake `paseo` CLI that records its argv; every id is
plainly fake.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
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
case " $* " in *" permit "*) cat "$FAKE_PERMITS" ;; *" -a "*) cat "$FAKE_ALL" ;; *) cat "$FAKE_LIVE" ;; esac
exit "${FAKE_RC_AFTER:-0}"
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
    live, everything, permits = tmp_path / "live.json", tmp_path / "all.json", tmp_path / "permits.json"
    live.write_text(json.dumps(LIVE))
    everything.write_text(json.dumps(LIVE + ARCHIVED))
    permits.write_text("[]")
    for k in ("FAKE_SLEEP", "FAKE_RC", "FAKE_RC_AFTER", "PASEO_AGENT_ID"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PASEO_CLI", str(cli))
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("FAKE_LIVE", str(live))
    monkeypatch.setenv("FAKE_ALL", str(everything))
    monkeypatch.setenv("FAKE_PERMITS", str(permits))
    herald_file = tmp_path / "herald" / "attention.json"    # never the real ~/.paseo file; absent until a test writes it
    monkeypatch.setenv("HERALD_ATTENTION_FILE", str(herald_file))
    monkeypatch.setattr(fleet, "_paseo_hosting", lambda anc: set())    # hermetic: the runner's ancestry is not under test
    return type("P", (), {"log": log, "live": live, "all": everything, "permits": permits, "herald": herald_file})


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
    assert paseo.log.read_text().splitlines() == ["ls -g --json --background", "permit ls --json"]


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


# ---- the queued lows of 2026-10-23 (paseo-listing adversary) ----

def card(agent_id: str, name: str = "AskUserQuestion", description: str = "1. yes / 2. no", req: str = "permission-1") -> dict[str, str]:
    return {"id": req, "agentId": agent_id, "agentShortId": agent_id[:7], "name": name, "description": description}


def test_helm_keeps_a_claude_on_paseo_agent_in_the_attention_queue(monkeypatch):
    """L1: a Claude agent Paseo hosts has a transcript (a sid): its question reaches helm like any Claude TUI's."""
    s = fleet._rec(id="deadbeef", agent="claude", host="paseo", chan=("paseo", CLAUDE), paseo=CLAUDE, sid="s" * 36,
                   status="blocked", cwd="/x/y")
    ask = {"questions": [{"question": "Which?", "options": [{"label": "a"}, {"label": "b"}]}]}
    monkeypatch.setattr(helm, "transcript", lambda sid: Path("t.jsonl"))
    monkeypatch.setattr(helm, "parse", lambda p: {"last_text": "", "pending": [("toolu_1", "AskUserQuestion", ask)]})
    it = helm.classify(s, {})
    assert (it["kind"], it["open"]) == ("question", True)


def test_a_slow_cli_is_cut_off_at_the_timeout_even_when_it_would_list_agents(paseo, monkeypatch, tmp_path):
    """L1: a hung daemon must not stall every fleet.sessions() call: the call is killed, not waited for."""
    slow = tmp_path / "slow"
    slow.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(5)\nprint(open({str(paseo.live)!r}).read())\n")
    slow.chmod(0o755)
    monkeypatch.setenv("PASEO_CLI", str(slow))
    monkeypatch.setattr(fleet, "PASEO_LS_TIMEOUT", 0.3)
    t0 = time.time()
    assert rows() == []
    assert time.time() - t0 < 3


def test_a_cli_that_prints_a_list_and_exits_nonzero_lists_nothing(paseo, monkeypatch):
    """L1: the exit code decides, not what reached stdout."""
    monkeypatch.setenv("FAKE_RC_AFTER", "3")
    assert rows() == []


def test_fleet_all_adds_the_archived_agents_and_the_plain_listing_does_not(paseo, monkeypatch, capsys):
    """L1: `fleet.py --all` is what puts archived Paseo agents in the listing (as `ended`)."""
    for name in ("_launched", "_other_herdr", "_proc_scan", "_hermes_gateway", "_claude_sessions"):
        monkeypatch.setattr(fleet, name, lambda *a, **k: [])
    monkeypatch.setattr(fleet, "_pane_only", lambda *a: ([], []))
    monkeypatch.setattr(fleet, "herdr_json", lambda *a: {})
    monkeypatch.setattr(fleet, "ancestors", lambda: set())
    monkeypatch.setattr(fleet, "proc_table", lambda: {})
    monkeypatch.setattr(fleet, "messaging_warning", lambda *a, **k: None)
    listed = {}
    for argv in (["fleet.py", "--json"], ["fleet.py", "--all", "--json"]):
        monkeypatch.setattr(sys, "argv", argv)
        assert fleet.main() == 0
        listed[len(argv)] = {s["paseo"]: s["status"] for s in json.loads(capsys.readouterr().out)}
    assert OLD not in listed[2] and listed[3][OLD] == "ended"


def test_a_running_agent_with_a_pending_card_is_blocked_and_the_others_are_not(paseo):
    """L2: `paseo ls` has no pending-permission field; one `paseo permit ls` names the agents with a card."""
    paseo.permits.write_text(json.dumps([card(OMP), card(CLINE, "bash", "rm -rf /tmp/x\x1b[31m")]))
    got = {r["paseo"]: r for r in rows()}
    assert (got[OMP]["status"], got[OMP]["paseo_state"]) == ("blocked", "running")
    assert got[OMP]["paseo_pending"] == "AskUserQuestion: 1. yes / 2. no"
    assert got[CLINE]["status"] == "idle"    # idle agents are not asked about
    assert got[CLAUDE]["status"] == "working" and "paseo_pending" not in got[CLAUDE]
    assert "permit ls --json" in paseo.log.read_text().splitlines()


def test_the_card_text_is_the_agents_own_so_control_characters_are_stripped(paseo):
    paseo.permits.write_text(json.dumps([card(OMP, "bash", "rm -rf /tmp/x\x1b[31m\n\x07ok")]))
    assert fleet._paseo_waiting() == {OMP: [{"id": "permission-1", "text": "bash: rm -rf /tmp/x ok"}]}


def test_the_card_text_loses_bidi_overrides_and_zero_width_characters_too(paseo):
    """L1 (adversary): a card is printed where the operator decides allow or deny; U+202E and friends reorder or hide text."""
    paseo.permits.write_text(json.dumps([card(OMP, "Bash", "echo safe \u202e\u2066 txt.exe \u200b\u2069\u3164\ufe0f done")]))
    text = fleet._paseo_waiting()[OMP][0]["text"]
    assert text == "Bash: echo safe txt.exe done"
    assert not any(unicodedata.category(ch) == "Cf" for ch in text)


def test_a_failed_card_listing_leaves_the_rows_as_they_were(paseo, monkeypatch):
    paseo.permits.write_text("garbage")
    assert {r["paseo"]: r["status"] for r in rows()} == {CLINE: "idle", CLAUDE: "working", OMP: "working"}
    paseo.live.write_text(json.dumps([agent(CLINE, "cline")]))    # nothing running: no card listing is asked for
    paseo.log.write_text("")
    rows()
    assert paseo.log.read_text().splitlines() == ["ls -g --json --background"]


def test_helm_shows_a_blocked_paseo_agent_as_an_open_permission_item_it_cannot_press_keys_for(paseo):
    paseo.permits.write_text(json.dumps([card(OMP)]))
    r = next(r for r in rows() if r["paseo"] == OMP)
    it = helm.classify(r, {})
    assert (it["kind"], it["open"], it["reachable"]) == ("permission", True, False)
    text = helm.render(it)
    assert "AskUserQuestion: 1. yes / 2. no" in text and "paseo permit" in text and "helm.py keys" not in text
    with pytest.raises(SystemExit) as e:
        helm.cmd_keys(type("A", (), {"id": it["id"], "key": ["1"]}), {})
    assert "allow|deny <agent> -- <request id>" in str(e.value)    # the same `--` the card text carries: an id read as an option is "approve every card"


def test_relay_refuses_a_paseo_agent_with_a_pending_card_and_names_the_paseo_ui(paseo):
    import relay  # noqa: PLC0415
    paseo.permits.write_text(json.dumps([card(OMP)]))
    r = next(r for r in rows() if r["paseo"] == OMP)
    why = relay.hard_stop(r)
    assert why and "Paseo UI" in why and "helm.py" not in why and "allow|deny <agent> -- <request id>" in why


def test_every_pending_card_is_kept_with_its_request_id_and_helm_prints_a_command_per_card(paseo):
    """M1 (adversary): `paseo permit allow AGENT` with no request id approves ALL cards and `deny` without one fails."""
    paseo.permits.write_text(json.dumps([card(OMP, "Bash", "echo safe", "req-a"), card(CLINE, "x", "y", "other"),
                                         card(OMP, "Bash", "rm -rf ~", "req-b")]))
    r = next(r for r in rows() if r["paseo"] == OMP)
    assert [c["id"] for c in r["paseo_cards"]] == ["req-a", "req-b"]
    assert r["paseo_pending"] == "2 cards, the first: Bash: echo safe"
    text = helm.render(helm.classify(r, {}))
    for req in ("req-a", "req-b"):
        assert f"`paseo permit allow {OMP} -- {req}`" in text and f"`paseo permit deny {OMP} -- {req}`" in text
    assert "Bash: rm -rf ~" in text
    assert re.findall(rf"paseo permit (?:allow|deny)(?! {OMP} -- req-)", text) == []    # never a command without its request id


def test_a_new_card_reopens_a_skipped_paseo_item(paseo):
    paseo.permits.write_text(json.dumps([card(OMP, "Bash", "echo safe", "req-a")]))
    one = helm.classify(next(r for r in rows() if r["paseo"] == OMP), {})
    paseo.permits.write_text(json.dumps([card(OMP, "Bash", "echo safe", "req-a"), card(OMP, "Bash", "rm -rf ~", "req-b")]))
    two = helm.classify(next(r for r in rows() if r["paseo"] == OMP), {})
    assert one["fp"] != two["fp"]
    assert helm.classify(next(r for r in rows() if r["paseo"] == OMP), {})["fp"] == two["fp"]    # stable while nothing changes
    paseo.permits.write_text(json.dumps([card(OMP, "Bash", "echo safe", "req-a"), card(OMP, "Bash", "rm -rf ~", "req-c")]))
    assert helm.classify(next(r for r in rows() if r["paseo"] == OMP), {})["fp"] not in (one["fp"], two["fp"])    # same texts as `two`, new request id


def test_helm_lists_up_to_eight_cards_and_points_at_paseo_permit_ls_for_the_rest(paseo):
    paseo.permits.write_text(json.dumps([card(OMP, "Bash", f"cmd {n}", f"req-{n}") for n in range(10)]))
    text = helm.render(helm.classify(next(r for r in rows() if r["paseo"] == OMP), {}))
    assert f"paseo permit allow {OMP} -- req-7`" in text and "req-8" not in text
    assert "and 2 more cards: `paseo permit ls`" in text


def test_a_request_id_that_is_not_a_plain_token_gets_no_command(paseo):
    paseo.permits.write_text(json.dumps([card(OMP, "Bash", "echo", "x; rm -rf ~")]))
    r = next(r for r in rows() if r["paseo"] == OMP)
    assert r["paseo_cards"][0]["id"] is None
    text = helm.render(helm.classify(r, {}))
    assert "paseo permit allow" not in text and "Paseo UI" in text


@pytest.mark.parametrize("rid", ["--all", "-h", "-", "-x", "--input", ".hidden", ":x", "a" * 81])
def test_a_request_id_the_paseo_cli_would_read_as_an_option_gets_no_command(paseo, rid):
    """L-A (adversary 2): `permit allow AGENT --all` approves every card; an id must start alphanumeric and be at most 80 characters."""
    paseo.permits.write_text(json.dumps([card(OMP, "Bash", "echo", rid)]))
    r = next(r for r in rows() if r["paseo"] == OMP)
    assert r["paseo_cards"][0]["id"] is None
    text = helm.render(helm.classify(r, {}))
    assert "paseo permit allow" not in text and "Paseo UI" in text


def test_the_printed_command_ends_option_parsing_before_the_request_id(paseo):
    paseo.permits.write_text(json.dumps([card(OMP, "Bash", "echo", "0-ok.id:1")]))
    text = helm.render(helm.classify(next(r for r in rows() if r["paseo"] == OMP), {}))
    assert f"`paseo permit allow {OMP} -- 0-ok.id:1`" in text


def test_a_paseo_agent_with_no_claude_row_is_not_found_by_its_workspace_title(paseo):
    """L3: titles come from the first prompt ("/baton", "say hi"); an id or a Paseo id names the agent, a title does not."""
    import relay  # noqa: PLC0415
    ss = rows() + [fleet._rec(id="cafe0001", agent="claude", name="Dann", sid="s" * 36)]    # a registry session called Dann too
    assert [s["id"] for s in relay.find("Dann", ss)] == ["cafe0001"]
    assert [s["paseo"] for s in relay.find(CLINE, ss)] == [CLINE] and [s["paseo"] for s in relay.find(OMP[:8], ss)] == [OMP]
    on_paseo = fleet._rec(id="cafe0002", agent="claude", name="peer-1", sid="t" * 36, host="paseo", paseo=CLAUDE)
    assert relay.find("peer-1", [on_paseo]) == [on_paseo]    # a Claude agent Paseo hosts keeps its session name


# ---- Herald's attention file (issue 135, 2026-10-30): synthetic entries only, never a live headline ----

HEAD = "SYNTHETIC-HEADLINE pick a branch"


def attn(agent_id: str, reason: str, **kw) -> dict:
    return {"agentId": agent_id, "reason": reason, "eventId": "ev-1", "requestId": "rq-1" if reason in ("question", "plan", "permission") else None,
            "createdAt": "2026-10-30T00:00:00.000Z", "headline": HEAD, "detail": "SYNTHETIC-DETAIL body", "summary": {"status": "idle"}, **kw}


def write_herald(paseo, *entries, raw=None) -> None:
    paseo.herald.parent.mkdir(parents=True, exist_ok=True)
    paseo.herald.write_text(raw if raw is not None else json.dumps(list(entries)))


def test_a_missing_herald_file_leaves_the_rows_as_they_were(paseo):
    assert fleet.herald_entries() == {}
    got = {r["paseo"]: r for r in rows()}
    assert [r["status"] for r in got.values()] == ["idle", "working", "working"]
    assert all("herald" not in r for r in got.values())


@pytest.mark.parametrize("raw", ["", "garbage", "null", '{"agentId": "x"}', '"question"', "7"])
def test_an_unreadable_or_non_array_herald_file_is_an_empty_list(paseo, raw):
    write_herald(paseo, raw=raw)
    assert fleet.herald_entries() == {}
    assert [r["status"] for r in rows()] == ["idle", "working", "working"]


def test_a_herald_path_that_is_a_directory_or_oversized_is_an_empty_list(paseo, monkeypatch):
    paseo.herald.mkdir(parents=True)
    assert fleet.herald_entries() == {}
    paseo.herald.rmdir()
    write_herald(paseo, attn(OMP, "question"))
    monkeypatch.setattr(fleet, "HERALD_MAX_BYTES", 10)
    assert fleet.herald_entries() == {}


def test_one_bad_herald_entry_does_not_drop_the_good_ones(paseo):
    write_herald(paseo, "junk", 5, None, ["x"], {"agentId": OMP}, {"agentId": 3, "reason": "question"}, {"agentId": "../../x", "reason": "question"},
                 {"agentId": CLINE, "reason": "bogus"}, attn(OMP, "question"))
    assert list(fleet.herald_entries()) == [OMP]
    got = {r["paseo"]: r for r in rows()}
    assert got[OMP]["status"] == "blocked" and got[CLINE]["status"] == "idle"


def test_a_herald_question_blocks_a_running_row_and_keeps_only_a_small_payload(paseo):
    write_herald(paseo, attn(OMP, "question", requestId="rq-9"))
    r = {r["paseo"]: r for r in rows()}[OMP]
    assert r["status"] == "blocked"
    assert r["herald"] == {"reason": "question", "eventId": "ev-1", "requestId": "rq-9", "createdAt": "2026-10-30T00:00:00.000Z", "status": "idle"}
    assert "SYNTHETIC" not in json.dumps(r)    # the headline and detail never reach a row


@pytest.mark.parametrize("reason", ["question", "plan", "permission"])
def test_a_leftover_herald_input_entry_on_an_idle_agent_blocks_nothing(paseo, reason):
    """Herald keeps entries across a daemon restart or a lost permission_resolved: Paseo says WHO waits, Herald only WHY."""
    write_herald(paseo, attn(CLINE, reason))
    r = {r["paseo"]: r for r in rows()}[CLINE]    # `paseo ls`: idle, and `permit ls` lists no card
    assert (r["status"], r["herald"]["reason"], "herald_waits" in r) == ("idle", reason, False)
    assert helm.classify(r, {})["kind"] not in ("question", "plan", "permission", "error")


@pytest.mark.parametrize("reason", ["question", "plan", "permission"])
def test_a_herald_input_entry_blocks_a_running_agent_without_a_card(paseo, reason):
    write_herald(paseo, attn(OMP, reason))
    r = {r["paseo"]: r for r in rows()}[OMP]
    assert (r["status"], r["herald_waits"]) == ("blocked", True)


@pytest.mark.parametrize("reason", ["finished", "canceled", "error"])
def test_finished_canceled_and_error_do_not_block_a_row(paseo, reason):
    write_herald(paseo, attn(CLINE, reason))
    r = {r["paseo"]: r for r in rows()}[CLINE]
    assert (r["status"], r["herald"]["reason"]) == ("idle", reason)


def test_the_herald_payload_is_sanitised(paseo):
    write_herald(paseo, attn(OMP, "question", requestId="--all", eventId="e\x1b[31m1\u202e", createdAt=1761782400000, summary="x"))
    h = fleet.herald_entries()[OMP]
    assert (h["requestId"], h["eventId"], h["createdAt"], h["status"]) == (None, "e1", "1761782400000", "")


def test_the_headline_is_read_only_on_request_and_cleaned(paseo):
    write_herald(paseo, attn(OMP, "question", headline="pick \x1b[31mone\x07 now", detail=7))
    assert "headline" not in fleet.herald_entries()[OMP]
    e = fleet.herald_entries(detail=True)[OMP]
    assert (e["headline"], e["detail"]) == ("pick one now", "")


def test_the_later_entry_for_an_agent_replaces_the_earlier(paseo):
    write_herald(paseo, attn(OMP, "question"), attn(OMP, "finished", eventId="ev-2"))
    assert fleet.herald_entries()[OMP]["eventId"] == "ev-2"
    assert {r["paseo"]: r for r in rows()}[OMP]["status"] == "working"


def test_herald_and_permit_ls_are_both_kept_when_they_agree(paseo):
    paseo.permits.write_text(json.dumps([card(OMP)]))
    write_herald(paseo, attn(OMP, "question"))
    r = {r["paseo"]: r for r in rows()}[OMP]
    assert r["status"] == "blocked" and r["paseo_pending"] and r["herald"]["reason"] == "question"


def test_an_archived_row_ignores_a_leftover_herald_entry(paseo):
    write_herald(paseo, attn(OLD, "question"))
    old = {r["paseo"]: r for r in rows(archived=True)}[OLD]
    assert (old["status"], "herald" not in old) == ("ended", True)


def claude_row_on_paseo(monkeypatch, tmp_path, registry_status="busy"):
    sid = "5" * 8 + "-1111-4000-8000-" + "0" * 12
    reg = tmp_path / "claude"
    (reg / "sessions").mkdir(parents=True, exist_ok=True)
    (reg / "sessions" / "a.json").write_text(json.dumps({"pid": 4242, "sessionId": sid, "cwd": "/x/y", "status": registry_status}))
    monkeypatch.setattr(fleet, "CLAUDE", reg)
    monkeypatch.setattr(fleet, "alive", lambda pid: True)
    monkeypatch.setattr(fleet, "transcript", lambda s: None)
    monkeypatch.setattr(fleet, "dispatch_record", lambda s: None)
    monkeypatch.setattr(fleet, "_where", type("W", (), {"lookup": staticmethod(lambda pid, start: {"paseo_agent": CLAUDE}),
                                                         "env_of": staticmethod(lambda pid: {})}))
    [s] = fleet._claude_sessions({}, set(), set())
    return sid, s


def test_a_claude_row_that_already_has_its_sid_gets_the_herald_status(paseo, monkeypatch, tmp_path):
    """The blind spot: `_claude_sessions` builds a Paseo-hosted Claude row with a sid, which `_paseo_rows` never sees."""
    write_herald(paseo, attn(CLAUDE, "question"))
    sid, s = claude_row_on_paseo(monkeypatch, tmp_path)
    assert (s["host"], s["sid"], s["paseo"], s["status"]) == ("paseo", sid, CLAUDE, "blocked")
    assert s["herald"]["reason"] == "question" and "SYNTHETIC" not in json.dumps(s)


def test_a_leftover_herald_question_on_an_idle_claude_row_blocks_nothing(paseo, monkeypatch, tmp_path):
    write_herald(paseo, attn(CLAUDE, "question"))
    _sid, s = claude_row_on_paseo(monkeypatch, tmp_path, registry_status="idle")
    assert (s["status"], s["herald"]["reason"], "herald_waits" in s) == ("idle", "question", False)


def test_a_claude_row_waiting_on_herald_with_a_dev_server_child_stays_a_blocked_helm_item(paseo, monkeypatch, tmp_path):
    """mark_busy turns a blocked row with children into busy-background, which hid the item: a Herald wait stays blocked."""
    write_herald(paseo, attn(CLAUDE, "permission"))
    _sid, s = claude_row_on_paseo(monkeypatch, tmp_path)
    monkeypatch.setattr(fleet, "background_work", lambda pid, table: ["99 npm run build"])
    fleet.mark_busy(s, {})
    assert (s["status"], s["busy"]) == ("blocked", ["99 npm run build"])
    assert helm.classify(s, {})["kind"] == "permission"
    other = fleet._rec(id="x", agent="claude", status="blocked", pid=1)    # a transcript-blocked row keeps its old behaviour
    fleet.mark_busy(other, {})
    assert other["status"] == "busy-background"


def test_helm_names_a_claude_paseo_question_from_herald_without_the_transcript(paseo):
    s = fleet._rec(id="deadbeef", agent="claude", host="paseo", chan=("paseo", CLAUDE), paseo=CLAUDE, sid="s" * 36, status="working", cwd="/x/y")
    write_herald(paseo, attn(CLAUDE, "question"))
    fleet.herald_overlay([s])
    it = helm.classify(s, {})    # no transcript for that sid: the kind is Herald's
    assert (it["kind"], it["open"], it["herald"], it["reachable"]) == ("question", True, "question", False)
    text = helm.render(it)
    assert "WAITS ON A QUESTION" in text and "relay.py --why deadbeef" in text and "SYNTHETIC" not in text


@pytest.mark.parametrize("reason,kind", [("question", "question"), ("plan", "plan"), ("permission", "permission"), ("error", "error")])
def test_helm_gives_each_herald_reason_its_own_kind(paseo, reason, kind):
    s = fleet._rec(id="deadbeef", agent="claude", host="paseo", chan=("paseo", CLAUDE), paseo=CLAUDE, sid="s" * 36,
                   status="idle" if reason == "error" else "working", cwd="/x/y")
    write_herald(paseo, attn(CLAUDE, reason))
    fleet.herald_overlay([s])
    it = helm.classify(s, {})
    assert (it["kind"], it["open"]) == (kind, True)


@pytest.mark.parametrize("reason", ["question", "plan", "permission", "error"])
def test_a_pending_transcript_question_stays_the_answerable_item_whatever_herald_says(paseo, monkeypatch, reason):
    """Herald's kind must neither replace nor drop a pending AskUserQuestion the transcript still holds: it carries the options helm can answer."""
    s = fleet._rec(id="deadbeef", agent="claude", host="paseo", chan=("paseo", CLAUDE), paseo=CLAUDE, sid="s" * 36, status="working", cwd="/x/y")
    write_herald(paseo, attn(CLAUDE, reason))
    fleet.herald_overlay([s])
    ask = {"questions": [{"question": "Which?", "options": [{"label": "a"}, {"label": "b"}]}]}
    monkeypatch.setattr(helm, "transcript", lambda sid: Path("t.jsonl"))
    monkeypatch.setattr(helm, "parse", lambda p: {"last_text": "", "pending": [("toolu_1", "AskUserQuestion", ask)]})
    s["status"] = "blocked"    # a live question: the registry says blocked (an error is read as the item only while no turn is blocked)
    it = helm.classify(s, {})
    assert (it["kind"], it["open"], it["tool_use_id"], it["questions"]) == ("question", True, "toolu_1", ask["questions"])
    assert "herald" not in it and "paseo" not in it


def test_a_new_herald_event_reopens_a_skipped_item(paseo):
    s = fleet._rec(id="deadbeef", agent="claude", host="paseo", chan=("paseo", CLAUDE), paseo=CLAUDE, sid="s" * 36, status="working", cwd="/x/y")
    write_herald(paseo, attn(CLAUDE, "question"))
    fleet.herald_overlay([s])
    st = {"skipped": helm.classify(s, {})["fp"]}
    assert helm.classify(s, st)["open"] is False
    write_herald(paseo, attn(CLAUDE, "question", eventId="ev-2"))
    fleet.herald_overlay([s])
    assert helm.classify(s, st)["open"] is True


def test_helm_shows_finished_as_an_announcement_and_leaves_the_row_alone(paseo):
    s = fleet._rec(id="deadbeef", agent="claude", host="paseo", chan=("paseo", CLAUDE), paseo=CLAUDE, sid="s" * 36, status="idle", cwd="/x/y")
    write_herald(paseo, attn(CLAUDE, "finished"))
    fleet.herald_overlay([s])
    assert s["status"] == "idle"
    assert helm.classify(s, {})["kind"] not in ("question", "plan", "permission", "error")


def test_helm_reports_an_error_as_needs_you_and_offers_no_permit_allow(paseo):
    write_herald(paseo, attn(CLINE, "error"))
    r = {r["paseo"]: r for r in rows()}[CLINE]    # idle, no card
    it = helm.classify(r, {})
    assert (it["kind"], it["open"], it["cards"]) == ("error", True, [])
    text = helm.render(it)
    assert "ENDED IN AN ERROR" in text and "paseo permit allow" not in text.replace("no card to allow or deny", "")


def test_a_real_permit_ls_card_stays_the_permission_item_over_a_herald_error(paseo):
    paseo.permits.write_text(json.dumps([card(OMP)]))    # the second source lists a pending card: it wins, and it is the only source of a command
    write_herald(paseo, attn(OMP, "error"))
    it = helm.classify({r["paseo"]: r for r in rows()}[OMP], {})
    assert (it["kind"], len(it["cards"])) == ("permission", 1)


def test_a_working_row_with_an_old_herald_error_is_not_a_need(paseo):
    write_herald(paseo, attn(CLAUDE, "error"))
    r = {r["paseo"]: r for r in rows()}[CLAUDE]    # running: a new turn started after the error
    assert helm.classify(r, {})["kind"] == "remote"


def test_helm_brief_carries_a_herald_wait(paseo, monkeypatch, capsys):
    write_herald(paseo, attn(OMP, "question"))
    monkeypatch.setattr(helm, "sessions", lambda: rows())
    monkeypatch.setattr(helm, "save", lambda state: None)
    helm.cmd_brief(None, {})
    out = capsys.readouterr().out.strip()
    assert out.startswith("1:") and OMP[:8] in out


# ---- repair of the adversary's BLOCK on head 8c69637c (2026-10-30) ----

def test_deeply_nested_json_is_an_empty_list_not_a_crash(paseo):
    write_herald(paseo, raw="[" * 200000 + "]" * 200000)    # well under HERALD_MAX_BYTES: json.loads raises RecursionError
    assert fleet.herald_entries() == {}
    assert [r["status"] for r in rows()] == ["idle", "working", "working"]


def test_a_fifo_at_the_herald_path_does_not_hang(paseo):
    paseo.herald.parent.mkdir(parents=True)
    os.mkfifo(paseo.herald)
    assert fleet.herald_entries() == {}    # O_NONBLOCK open, then fstat: not a regular file


def test_a_device_symlink_at_the_herald_path_is_not_read(paseo):
    paseo.herald.parent.mkdir(parents=True)
    paseo.herald.symlink_to("/dev/zero")    # size 0, reads forever
    assert fleet.herald_entries() == {}


def test_the_herald_read_is_capped_whatever_stat_says(paseo, monkeypatch):
    write_herald(paseo, attn(OMP, "question"))
    monkeypatch.setattr(fleet, "HERALD_MAX_BYTES", 10)
    assert fleet._herald_read() is None
    monkeypatch.setattr(fleet, "HERALD_MAX_BYTES", 10_000)
    assert fleet._herald_read()[0]["agentId"] == OMP


def test_one_scan_reads_the_herald_file_once_for_every_row(paseo, monkeypatch):
    write_herald(paseo, attn(OMP, "question"))
    reads = []
    real = fleet._herald_read
    monkeypatch.setattr(fleet, "_herald_read", lambda: reads.append(1) or real())
    many = [fleet._rec(id=f"r{i}", agent="claude", host="paseo", chan=("paseo", OMP), paseo=OMP, status="working") for i in range(3)]
    fleet.herald_overlay(many)
    assert len(reads) == 1 and all(s["status"] == "blocked" for s in many)
    reads.clear()
    fleet.herald_overlay(many, fleet.herald_entries())    # entries passed in: the overlay reads nothing itself
    assert len(reads) == 1    # only the herald_entries() call above


def test_sessions_reads_the_herald_file_once_and_shares_it(paseo, monkeypatch):
    seen = []
    shared = {}
    monkeypatch.setattr(fleet, "herald_entries", lambda detail=False: shared)
    monkeypatch.setattr(fleet, "ancestors", lambda: set())
    monkeypatch.setattr(fleet, "ancestor_pane", lambda anc: None)
    monkeypatch.setattr(fleet, "herdr_json", lambda *a, **k: {})
    monkeypatch.setattr(fleet, "_launched", lambda used: [])
    monkeypatch.setattr(fleet, "_claude_sessions", lambda *a, **k: seen.append(a[-1]) or [])
    monkeypatch.setattr(fleet, "_other_herdr", lambda agents, used: [])
    monkeypatch.setattr(fleet, "_pane_only", lambda panes, used: ([], []))
    monkeypatch.setattr(fleet, "_proc_scan", lambda *a, **k: [])
    monkeypatch.setattr(fleet, "_hermes_gateway", lambda: [])
    monkeypatch.setattr(fleet, "_paseo_rows", lambda have, anc, archived=False, herald=None: seen.append(herald) or [])
    monkeypatch.setattr(fleet, "proc_table", lambda: {})
    fleet.sessions()
    assert len(seen) == 2 and seen[0] is shared and seen[1] is shared


def test_helm_answer_on_a_herald_question_refuses_cleanly(paseo, monkeypatch, capsys):
    s = fleet._rec(id="deadbeef", agent="claude", host="paseo", chan=("paseo", CLAUDE), paseo=CLAUDE, sid="s" * 36, status="working", cwd="/x/y")
    write_herald(paseo, attn(CLAUDE, "question"))
    fleet.herald_overlay([s])
    it = helm.classify(s, {})
    assert (it["kind"], "questions" in it) == ("question", False)
    monkeypatch.setattr(helm, "find", lambda ident, state: (s, it))
    with pytest.raises(SystemExit) as e:
        helm.cmd_answer(type("A", (), {"id": "deadbeef", "fp": None, "text": None, "choice": [1]}), {})
    assert "Paseo agent" in str(e.value) and "nothing sent" in str(e.value) and "KeyError" not in repr(e.value)
