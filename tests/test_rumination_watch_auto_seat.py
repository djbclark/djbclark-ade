"""§J: opt-in, proven absence, attempt window; no network or real agents."""
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

NOW = 1_800_000_000.0
OLD = "old-seat"
NEW = "new-seat"
SECRET = "DISTINCTIVE OTHER CHAIN SLICE DO NOT COPY"
QUIET = {"mail": [], "jobs": [], "prs": [], "stale": None}

# `auto_seat` starts a seat as `env -u PASEO_AGENT_ID paseo run …`: with that variable set the daemon
# parents the new agent to it, so a pass run by hand from inside an agent would make the entity's next
# seat that agent's SUBAGENT (measured 2026-10-30). No test may pin a bare `paseo run`.
RUN = ["env", "-u", "PASEO_AGENT_ID", "paseo", "run"]


def is_start(argv):
    return argv[:len(RUN)] == RUN


def load(monkeypatch, tmp_path, switch="1"):
    monkeypatch.delenv("RW_SESSION", raising=False)
    monkeypatch.delenv("PASEO_AGENT_ID", raising=False)
    if switch is None:
        monkeypatch.delenv("RW_AUTO_SEAT", raising=False)
    else:
        monkeypatch.setenv("RW_AUTO_SEAT", switch)
    monkeypatch.setenv("RW_AUTO_SEAT_PROVIDER", "opencode/opencode-go")
    path = Path(__file__).resolve().parents[1] / "bin/rumination-watch"
    loader = importlib.machinery.SourceFileLoader("rw_auto_seat", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    rw = importlib.util.module_from_spec(spec)
    loader.exec_module(rw)
    rw.real_owner_session = rw.owner_session
    rw.real_why_blocked = rw.why_blocked
    rw.real_run_split = rw.run_split
    rw.real_open_desktop_tab = rw.open_desktop_tab
    monkeypatch.setattr(rw, "HOME", tmp_path)
    monkeypatch.setattr(rw, "REPO", tmp_path / "entity")
    monkeypatch.setattr(rw, "ROLE", "test-role")
    monkeypatch.setattr(rw, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(rw, "STATE", rw.STATE_DIR / "state.json")
    monkeypatch.setattr(rw, "LOG", rw.STATE_DIR / "pass.log")
    monkeypatch.setattr(rw, "DEPLOY_OFF", True)
    monkeypatch.setattr(rw, "NUDGE_ON", False)
    monkeypatch.setattr(rw.time, "time", lambda: NOW)
    monkeypatch.setattr(rw, "survey", lambda: QUIET.copy())
    monkeypatch.setattr(rw, "owner_session", lambda: (OLD, "test"))
    monkeypatch.setattr(rw, "why_blocked", lambda ident: ("gone", "inspect answered not found"))
    monkeypatch.setattr(rw, "to_session", lambda text: "FAILED")
    rw.pages = []
    monkeypatch.setattr(rw, "to_djbclark", lambda text: rw.pages.append(text) or True)
    pointer = tmp_path / ".local/state/handoffs/entity/main/SESSION_LOG.md"
    pointer.parent.mkdir(parents=True)
    pointer.write_text(f"## Current State\n- Next steps:\n  - {SECRET}\n")
    rw.pointer = pointer
    rw.calls = []
    rw.run_rc = 0
    rw.run_body = None
    rw.confirm = True
    rw.enum_rc, rw.enum_body = 1, ""

    # The Desktop tab is its own subprocess (`paseo agent open`). Stubbed so every call-count
    # assertion below stays about the start and its confirmation; the tests at the end restore the
    # real helper (`rw.real_open_desktop_tab`) to pin what it runs and what it logs.
    rw.opened = []
    rw.open_failure = ""

    def open_tab(agent_id):
        # The tab attempt is stamped AFTER the open on BOTH paths, so a kill during the open leaves
        # it unrecorded and the next pass retries an idempotent `agent open` (adversary D4: moving
        # `tab_once`'s stamp above its own open survived every test).
        assert f"auto-seat tab:{agent_id}" not in rw.load_state().get("told", {})
        rw.opened.append(agent_id)
        return rw.open_failure

    monkeypatch.setattr(rw, "open_desktop_tab", open_tab)

    def run(argv, timeout=20):
        rw.calls.append((argv, timeout))
        if argv == ["paseo", "ls", "--json", "--background"]:
            assert timeout <= 20
            return rw.enum_rc, rw.enum_body, "listing failure" if rw.enum_rc else ""
        # The successful-start stamp must not exist during either the start OR confirmation call.
        assert rw.load_state().get("seated", {}).get(rw.ROLE) != NOW
        if is_start(argv):
            assert rw.load_state()["told"][f"auto-seat attempt:{rw.ROLE}"] == rw.time.time()
            body = rw.run_body if rw.run_body is not None else (json.dumps({"agentId": NEW}) if rw.run_rc == 0 else "")
            return rw.run_rc, body, "stub failure" if rw.run_rc else ""
        assert argv == ["paseo", "agent", "inspect", "--json", "--", NEW]
        return (0, json.dumps({"Id": NEW, "Archived": False, "Status": "running"}), "") if rw.confirm else (1, "", "not found")

    monkeypatch.setattr(rw, "run_split", run)
    return rw


def run_pass(rw):
    return rw._pass(rw.argparse.Namespace(dry_run=False, quiet=True))


@pytest.mark.parametrize("switch", ["0", None])
def test_1_off_and_default_never_start_or_stamp(monkeypatch, tmp_path, switch):
    rw = load(monkeypatch, tmp_path, switch)
    run_pass(rw)
    assert not rw.AUTO_SEAT
    assert rw.calls == []
    assert rw.load_state().get("seated", {}) == {}


def test_2_gone_starts_once_with_file_not_slice_and_stamps_after_inspect(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    run_pass(rw)
    assert len(rw.calls) == 2
    argv, timeout = rw.calls[0]
    assert argv[:-1] == RUN + ["--provider", "opencode/opencode-go", "--no-wait", "--json",
                               "--cwd", str(rw.REPO), "--title", "test-role (auto-seat)", "--"]
    assert str(rw.pointer.resolve()) in argv[-1]
    assert rw.ROLE in argv[-1] and str(rw.REPO) in argv[-1]
    assert SECRET not in argv[-1]
    assert "## Current State" in argv[-1] and "- Next steps:" in argv[-1]
    assert "gone" in argv[-1] and "automatically" in argv[-1]
    assert len(argv[-1].splitlines()) < 15
    assert timeout <= 120 and rw.calls[1][1] <= 20
    assert rw.load_state()["seated"] == {rw.ROLE: NOW}
    # The confirmed start is the ONE path that owes the new seat a tab (adversary N7: the calls
    # list cannot see this, so a mutant that opens in the WRONG branch survived).
    assert rw.opened == [NEW]


def test_3_error_is_a_broken_read_not_an_absent_seat(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    monkeypatch.setattr(rw, "why_blocked", lambda ident: ("error", "socket gone"))
    run_pass(rw)
    assert rw.calls == [] and not rw.load_state().get("seated")


def test_4_silent_is_an_existing_seat_and_would_duplicate_it(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    monkeypatch.setattr(rw, "why_blocked", lambda ident: ("silent", "hung"))
    run_pass(rw)
    assert rw.calls == [] and not rw.load_state().get("seated")


@pytest.mark.parametrize("word", ["card:question", "card:unknown", "working", "idle", "refused", "unknown", ""])
def test_5_card_or_other_nonabsence_never_starts(monkeypatch, tmp_path, word):
    rw = load(monkeypatch, tmp_path)
    monkeypatch.setattr(rw, "why_blocked", lambda ident: (word, "test"))
    run_pass(rw)
    assert rw.calls == [] and not rw.load_state().get("seated")


def test_6_cooldown_blocks_second_start_and_logs_refusal_once(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    run_pass(rw)
    run_pass(rw)
    run_pass(rw)
    assert len(rw.calls) == 2
    text = rw.LOG.read_text()
    assert text.count("auto-seat: started") == 1
    assert text.count("auto-seat: not started (cooldown)") == 1


@pytest.mark.parametrize("rc,body", [(1, ""), (127, ""), (0, "not JSON"), (0, "{}")])
def test_7_failed_run_stays_unresolved_after_attempt_window(monkeypatch, tmp_path, rc, body):
    rw = load(monkeypatch, tmp_path)
    rw.run_rc, rw.run_body = rc, body
    run_pass(rw)
    assert not rw.load_state().get("seated")
    assert rw.load_state()["told"][f"auto-seat attempt:{rw.ROLE}"] == NOW
    monkeypatch.setattr(rw.time, "time", lambda: NOW + 300)
    run_pass(rw)
    assert sum(is_start(argv) for argv, _ in rw.calls) == 1
    assert rw.LOG.read_text().count("auto-seat: attempted paseo run") == 1
    monkeypatch.setattr(rw.time, "time", lambda: NOW + rw.AUTO_SEAT_S)
    run_pass(rw)
    assert sum(is_start(argv) for argv, _ in rw.calls) == 1
    assert f"auto-seat unresolved:{rw.ROLE}" in rw.load_state()["told"]
    assert not rw.load_state().get("seated")
    assert rw.LOG.read_text().count("auto-seat: attempted paseo run") == 1
    assert f"rc={rc}; stderr=" in rw.LOG.read_text()
    assert "gone" in rw.pages[0] and NEW not in rw.pages[0]


def test_8_unconfirmed_start_does_not_stamp(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    rw.confirm = False
    run_pass(rw)
    assert len(rw.calls) == 2
    assert not rw.load_state().get("seated")
    assert rw.opened == []          # unconfirmed: no seat to give a tab to (adversary N7)
    assert f"auto-seat: confirmation failed id={NEW}; rc=1; stderr='not found'" in rw.LOG.read_text()


@pytest.mark.parametrize("seated", ["12", {"test-role": "x"}, {"test-role": NOW + 10**9},
                                    {"test-role": NOW - 3600}, {"test-role": float("inf")}])
def test_9_bad_state_and_future_stamps_are_ignored(monkeypatch, tmp_path, seated):
    rw = load(monkeypatch, tmp_path)
    rw.STATE_DIR.mkdir()
    rw.STATE.write_text(json.dumps({"seated": seated}))
    run_pass(rw)
    assert len(rw.calls) == 2
    assert rw.load_state()["seated"] == {rw.ROLE: NOW}


def test_10_success_still_pages_with_new_id(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    run_pass(rw)
    assert len(rw.pages) == 1
    assert NEW in rw.pages[0] and "automatically at" in rw.pages[0]


def test_11_provider_unset_refuses_once_without_starting(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    monkeypatch.setattr(rw, "AUTO_SEAT_PROVIDER", "")
    run_pass(rw)
    run_pass(rw)
    assert rw.calls == [] and not rw.load_state().get("seated")
    assert rw.LOG.read_text().count("auto-seat: not started (RW_AUTO_SEAT_PROVIDER unset)") == 1
    assert len(rw.pages) == 1


@pytest.mark.parametrize("missing", ["none", "dangling"])
def test_12_missing_pointer_still_starts(monkeypatch, tmp_path, missing):
    rw = load(monkeypatch, tmp_path)
    rw.pointer.unlink()
    if missing == "dangling":
        rw.pointer.write_text("redirect: chains/missing/SESSION_LOG.md\n")
    run_pass(rw)
    assert len(rw.calls) == 2
    assert "No Tier 1 pointer file exists" in rw.calls[0][0][-1]
    assert "auto-seat: no pointer" in rw.LOG.read_text()


def test_13_rejected_owner_is_diagnosed_not_inferred_from_empty_fleet(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    monkeypatch.setattr(rw, "owner_session", lambda: ("", "no live session (gone)"))
    monkeypatch.setattr(rw, "owner_candidates", lambda: iter([("registry", OLD)]))
    run_pass(rw)
    assert len(rw.calls) == 2 and NEW in rw.pages[0]


def test_14_broken_fleet_read_never_starts(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    monkeypatch.setattr(rw, "owner_session", lambda: ("", "unreadable"))
    monkeypatch.setattr(rw, "_LIVE_ERR", "broken read")
    monkeypatch.setattr(rw, "owner_candidates", lambda: iter([("registry", OLD)]))
    run_pass(rw)
    assert rw.calls == []


def test_15_dry_run_never_starts(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    rw._pass(rw.argparse.Namespace(dry_run=True, quiet=True))
    assert rw.calls == [] and not rw.STATE.exists()


@pytest.mark.parametrize("confirmed", [True, False])
def test_16_retained_candidate_prevents_duplicates_even_after_cooldown(monkeypatch, tmp_path, confirmed):
    rw = load(monkeypatch, tmp_path)
    rw.confirm = confirmed
    run_pass(rw)
    monkeypatch.setattr(rw.time, "time", lambda: NOW + rw.AUTO_SEAT_S + 1)
    monkeypatch.setattr(rw, "why_blocked", lambda ident: ("idle" if ident == NEW else "gone", "test"))
    run_pass(rw)
    assert sum(is_start(argv) for argv, _ in rw.calls) == 1
    assert rw.auto_seat_candidate(rw.load_state()) == NEW
    if not confirmed:
        assert not rw.load_state().get("seated")


def test_17_saved_candidate_is_considered_by_real_owner_resolution(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    run_pass(rw)
    monkeypatch.delenv("RW_SESSION", raising=False)
    monkeypatch.delenv("PASEO_AGENT_ID", raising=False)
    assert next(rw.owner_candidates()) == ("auto-seat", NEW)
    monkeypatch.setattr(rw, "owner_session", rw.real_owner_session)
    monkeypatch.setattr(rw, "live_sessions", lambda: {NEW[:8]: {"ended": False, "archived": False}})
    assert rw.owner_session() == (NEW, "auto-seat")


@pytest.mark.parametrize("stamp", [NOW, NOW + 10**9, 1e300])
def test_18_status_bounds_future_stamps_without_crashing(monkeypatch, tmp_path, capsys, stamp):
    rw = load(monkeypatch, tmp_path)
    rw.STATE_DIR.mkdir()
    rw.STATE.write_text(json.dumps({"seated": {rw.ROLE: stamp}}))
    monkeypatch.setattr(rw, "_git", lambda *args: (0, "j-auto-seat", ""))
    monkeypatch.setattr(rw, "running_sha", lambda: "fixture")
    assert rw.cmd_status(rw.argparse.Namespace()) == 0
    assert "auto-seat: on (1 role(s) started, last " in capsys.readouterr().out


def test_19_registered_successor_takes_precedence_over_gone_candidate(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    run_pass(rw)
    rw.pages.clear()
    monkeypatch.setattr(rw.time, "time", lambda: NOW + rw.AUTO_SEAT_S + 1)
    registry = rw.REPO / "agents/comm/registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({rw.ROLE: {"paseo": "successor"}}))
    monkeypatch.setattr(rw, "owner_session", rw.real_owner_session)
    monkeypatch.setattr(rw, "live_sessions", lambda: {i[:8]: {"ended": False, "archived": False}
                                                     for i in (NEW, "successor")})
    assert list(rw.owner_candidates()) == [("registry", "successor"), ("auto-seat", NEW)]
    assert rw.owner_session() == ("successor", "registry")
    monkeypatch.setattr(rw, "why_blocked", lambda ident: ("idle" if ident == "successor" else "gone", "test"))
    run_pass(rw)
    assert len(rw.calls) == 2 and rw.pages == []
    assert not rw.auto_seat_candidate(rw.load_state())


def test_20_retained_candidate_with_stale_fleet_does_not_page_as_absent(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    run_pass(rw)
    rw.pages.clear()
    monkeypatch.setattr(rw.time, "time", lambda: NOW + 25000)
    monkeypatch.setattr(rw, "owner_session", lambda: ("", "fleet has not listed candidate"))
    monkeypatch.setattr(rw, "why_blocked", lambda ident: ("idle", "exists"))
    run_pass(rw)
    assert len(rw.calls) == 2 and rw.pages == []


def test_21_broken_fleet_cannot_hide_a_successor_behind_gone_candidate(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    run_pass(rw)
    rw.pages.clear()
    monkeypatch.setattr(rw.time, "time", lambda: NOW + 25000)
    monkeypatch.setattr(rw, "owner_session", lambda: ("", "unreadable"))
    monkeypatch.setattr(rw, "_LIVE_ERR", "broken read")
    monkeypatch.setattr(rw, "owner_candidates", lambda: iter([("auto-seat", NEW), ("registry", "successor")]))
    monkeypatch.setattr(rw, "why_blocked", lambda ident: ("gone", "test"))
    run_pass(rw)
    assert len(rw.calls) == 2
    assert len(rw.pages) == 1 and "cannot READ the fleet" in rw.pages[0]
    assert "(gone)" not in rw.pages[0]


@pytest.mark.parametrize("reason", ["silent", "unknown", "refused", "provider"])
def test_22_prior_refusal_cannot_hide_an_invocation_or_consume_attempt_window(monkeypatch, tmp_path, reason):
    rw = load(monkeypatch, tmp_path)
    word = "gone" if reason == "provider" else reason
    monkeypatch.setattr(rw, "why_blocked", lambda ident: (word, "test"))
    if reason == "provider":
        monkeypatch.setattr(rw, "AUTO_SEAT_PROVIDER", "")
    run_pass(rw)
    assert f"auto-seat attempt:{rw.ROLE}" not in rw.load_state().get("told", {})
    monkeypatch.setattr(rw, "AUTO_SEAT_PROVIDER", "opencode/opencode-go")
    monkeypatch.setattr(rw, "why_blocked", lambda ident: ("gone", "test"))
    rw.run_rc = 127
    run_pass(rw)
    run_pass(rw)
    assert sum(is_start(argv) for argv, _ in rw.calls) == 1
    text = rw.LOG.read_text()
    assert text.count("auto-seat: not started") == 1
    assert text.count("auto-seat: attempted paseo run rc=127; stderr='stub failure'; id=none; failed") == 1
    monkeypatch.setattr(rw.time, "time", lambda: NOW + rw.AUTO_SEAT_S)
    run_pass(rw)
    assert sum(is_start(argv) for argv, _ in rw.calls) == 1
    assert rw.LOG.read_text().count("auto-seat: attempted paseo run") == 1


def test_23_legacy_confirmed_start_cooldown_does_not_consume_an_attempt(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    rw.save_state({"seated": {rw.ROLE: NOW}})
    run_pass(rw)
    assert rw.calls == []
    assert f"auto-seat attempt:{rw.ROLE}" not in rw.load_state()["told"]


@pytest.mark.parametrize("override", ["RW_SESSION", "PASEO_AGENT_ID"])
def test_24_explicit_override_precedes_saved_candidate(monkeypatch, tmp_path, override):
    rw = load(monkeypatch, tmp_path)
    run_pass(rw)
    monkeypatch.setenv(override, "operator-seat")
    monkeypatch.setattr(rw, "owner_session", rw.real_owner_session)
    assert next(rw.owner_candidates()) == (override, "operator-seat")
    assert rw.owner_session() == ("operator-seat", override)


ABSENT = "11111111-2222-4333-8444-555555555555"
CREATED = "66666666-7777-4888-9999-aaaaaaaaaaaa"


def direct_probe_world(monkeypatch, tmp_path, response, ident=ABSENT):
    """Real why_blocked + run_split, with a no-match relay and a fake Paseo executable."""
    rw = load(monkeypatch, tmp_path)
    monkeypatch.setattr(rw, "why_blocked", rw.real_why_blocked)
    monkeypatch.setattr(rw, "open_desktop_tab", rw.real_open_desktop_tab)
    monkeypatch.setattr(rw, "owner_session", lambda: ("", "no live session"))
    monkeypatch.setattr(rw, "owner_candidates", lambda: iter([("registry", ident)]))
    relay = tmp_path / "src/djbclark-ade/skills/session-finder/relay.py"
    relay.parent.mkdir(parents=True)
    relay.write_text("import sys\nprint('no session(s) match', file=sys.stderr)\nsys.exit(2)\n")
    cli = tmp_path / "paseo"
    calls = tmp_path / "paseo.calls"
    cli.write_text(f"""#!{sys.executable}
import json, sys, time
from pathlib import Path
args = sys.argv[1:]
with Path({str(calls)!r}).open('a') as f:
    f.write(json.dumps(args) + '\\n')
if args[0] == 'run':
    print(json.dumps({{'agentId': {CREATED!r}}}))
elif args[:2] == ['agent', 'open']:
    print(json.dumps({{'opened': args[2]}}))
elif args == ['agent', 'inspect', '--json', '--', {CREATED!r}]:
    print(json.dumps({{'Id': {CREATED!r}, 'Archived': False, 'Status': 'running'}}))
elif args == ['agent', 'inspect', '--json', '--', {ident!r}]:
    mode = {response!r}
    if mode == 'timeout':
        time.sleep(3)
    if mode == 'notfound':
        print(json.dumps({{'error': {{'code': 'AGENT_NOT_FOUND'}}}}))
        sys.exit(1)
    if mode == 'stderr-notfound':
        print(json.dumps({{'error': {{'code': 'AGENT_NOT_FOUND'}}}}), file=sys.stderr)
        sys.exit(1)
    if mode == 'error':
        print(json.dumps({{'error': {{'code': 'DAEMON_UNAVAILABLE'}}}}))
        sys.exit(1)
    if mode == 'unreadable':
        print('not JSON')
    if mode == 'unknown-shape':
        print(json.dumps({{'Status': 'unknown'}}))
    if mode == 'wrong-id':
        print(json.dumps({{'Id': {CREATED!r}}}))
else:
    sys.exit(99)
""")
    cli.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])

    def run(argv, timeout=20):
        if response == "timeout" and argv == ["paseo", "agent", "inspect", "--json", "--", ident]:
            timeout = 0.2
        return rw.real_run_split(argv, timeout=timeout)

    monkeypatch.setattr(rw, "run_split", run)
    rw.probe_calls = calls
    return rw


@pytest.mark.parametrize("response", ["notfound", "stderr-notfound"])
def test_25_real_probe_not_found_reaches_gone_and_exactly_one_start(monkeypatch, tmp_path, response):
    rw = direct_probe_world(monkeypatch, tmp_path, response)
    assert rw.why_blocked(ABSENT)[0] == "gone"
    run_pass(rw)
    run_pass(rw)
    calls = [json.loads(line) for line in rw.probe_calls.read_text().splitlines()]
    assert sum(args[0] == "run" for args in calls) == 1
    assert ["agent", "inspect", "--json", "--", ABSENT] in calls
    # Confirmed, then given a tab: a `paseo run` agent has none, and an invisible seat that hits a
    # `card:*` (which §J never answers) is the darkness this file exists to end, one level down.
    assert calls.index(["agent", "open", CREATED, "--json"]) > calls.index(
        ["agent", "inspect", "--json", "--", CREATED])
    assert rw.load_state()["seated"] == {rw.ROLE: NOW}


@pytest.mark.parametrize("response", ["error", "timeout", "unreadable", "unknown-shape", "wrong-id"])
def test_26_real_probe_broken_or_unknown_read_never_starts(monkeypatch, tmp_path, response):
    rw = direct_probe_world(monkeypatch, tmp_path, response)
    assert rw.why_blocked(ABSENT)[0] == "unknown"
    run_pass(rw)
    calls = [json.loads(line) for line in rw.probe_calls.read_text().splitlines()]
    assert all(args[0] != "run" for args in calls)
    assert not rw.load_state().get("seated")
    assert rw.pages  # A blind/dead seat still needs the human.


@pytest.mark.parametrize("ident", ["11111111", "hand-edited-seat"])
def test_27_real_probe_non_uuid_never_trusts_not_found(monkeypatch, tmp_path, ident):
    rw = direct_probe_world(monkeypatch, tmp_path, "notfound", ident)
    assert rw.why_blocked(ident)[0] == "unknown"
    run_pass(rw)
    assert not rw.probe_calls.exists()  # Did not even ask Paseo about an invalid id.
    assert not rw.load_state().get("seated")
    assert rw.pages


def test_28_prior_refusal_does_not_hide_failed_inspect_or_bounded_run_stderr(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    monkeypatch.setattr(rw, "why_blocked", lambda ident: ("silent", "test"))
    run_pass(rw)
    monkeypatch.setattr(rw, "why_blocked", lambda ident: ("gone", "test"))

    def run(argv, timeout=20):
        if is_start(argv):
            return 0, json.dumps({"agentId": NEW}), "R" * 160 + "RUN_TAIL"
        return 127, "", "I" * 160 + "INSPECT_TAIL"

    monkeypatch.setattr(rw, "run_split", run)
    run_pass(rw)
    text = rw.LOG.read_text()
    assert text.count("auto-seat: attempted paseo run rc=0") == 1
    assert f"id={NEW}; id returned" in text
    assert text.count(f"auto-seat: confirmation failed id={NEW}; rc=127") == 1
    assert "R" * 160 in text and "I" * 160 in text
    assert "RUN_TAIL" not in text and "INSPECT_TAIL" not in text


def test_29_non_uuid_gone_from_relay_is_not_absence_proof(monkeypatch, tmp_path):
    rw = direct_probe_world(monkeypatch, tmp_path, "notfound", "truncated")
    relay = rw.HOME / "src/djbclark-ade/skills/session-finder/relay.py"
    relay.write_text("import json, sys\nprint(json.dumps({'state': 'gone'}))\nsys.exit(1)\n")
    assert rw.why_blocked("truncated")[0] == "unknown"
    run_pass(rw)
    assert not rw.probe_calls.exists()


# Recorded 2026-10-30 from installed `paseo ls --json --background` (rc 0):
# plain array, lowercase fields; identities/title/cwd sanitized, extra fields retained.
PASEO_LS_FIXTURE = [{"id": NEW, "shortId": "new-seat", "name": "test-role (auto-seat)",
                     "status": "running", "cwd": "/sanitized/entity", "provider": "codex",
                     "created": "2026-10-30T00:00:00.000Z", "thinking": None}]


def lost_id(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    rw.run_rc = 127
    run_pass(rw)
    monkeypatch.setattr(rw.time, "time", lambda: NOW + rw.AUTO_SEAT_S + 1)
    monkeypatch.setattr(rw, "owner_session", lambda: ("", "old registry seat gone"))
    monkeypatch.setattr(rw, "owner_candidates", lambda: iter([("registry", OLD)]))
    return rw


def starts(rw):
    return sum(is_start(argv) for argv, _ in rw.calls)


def test_30_timeout_and_expired_window_cannot_duplicate_with_old_registry_gone(monkeypatch, tmp_path):
    rw = lost_id(monkeypatch, tmp_path)
    run_pass(rw)
    run_pass(rw)
    assert starts(rw) == 1
    assert f"auto-seat unresolved:{rw.ROLE}" in rw.load_state()["told"]
    assert rw.LOG.read_text().count("unresolved start not reconciled") == 1
    assert "gone" in rw.pages[0]


def test_31_listing_adopts_lost_id_then_next_pass_diagnoses_candidate(monkeypatch, tmp_path):
    rw = lost_id(monkeypatch, tmp_path)
    rw.enum_rc, rw.enum_body = 0, json.dumps(PASEO_LS_FIXTURE)
    run_pass(rw)
    state = rw.load_state()
    assert state["told"][f"auto-seat candidate:{rw.ROLE}:{NEW}"] == rw.time.time()
    assert f"auto-seat unresolved:{rw.ROLE}" not in state["told"]
    assert starts(rw) == 1 and not state.get("seated")
    assert f"auto-seat: recovered lost id {NEW}" in rw.LOG.read_text()
    diagnosed = []
    def why(ident):
        diagnosed.append(ident)
        return ("idle" if ident == NEW else "gone", "fixture")
    monkeypatch.setattr(rw, "why_blocked", why)
    run_pass(rw)
    assert NEW in diagnosed and starts(rw) == 1


def test_32_empty_listing_only_clears_and_following_pass_may_start(monkeypatch, tmp_path):
    rw = lost_id(monkeypatch, tmp_path)
    rw.enum_rc, rw.enum_body = 0, json.dumps([{**PASEO_LS_FIXTURE[0], "name": "other role"}])
    run_pass(rw)
    assert f"auto-seat unresolved:{rw.ROLE}" not in rw.load_state()["told"]
    assert starts(rw) == 1
    assert "auto-seat: unresolved cleared (no live auto-seat agent)" in rw.LOG.read_text()
    assert "unresolved start not reconciled" not in rw.LOG.read_text()
    rw.run_rc = 0
    run_pass(rw)
    assert starts(rw) == 2


@pytest.mark.parametrize("rc,body", [(1, "[]"), (127, ""), (0, "garbage"), (0, "{}"),
    (0, json.dumps(PASEO_LS_FIXTURE * 2)), (0, '[null]'),
    (0, json.dumps([{**PASEO_LS_FIXTURE[0], "id": ""}]))])
def test_33_bad_listing_keeps_marker_and_darkness_page(monkeypatch, tmp_path, rc, body):
    rw = lost_id(monkeypatch, tmp_path)
    rw.enum_rc, rw.enum_body = rc, body
    rw.pages.clear()
    monkeypatch.setattr(rw.time, "time", lambda: NOW + rw.DJB_COOLDOWN_S + 1)
    run_pass(rw)
    run_pass(rw)
    assert f"auto-seat unresolved:{rw.ROLE}" in rw.load_state()["told"]
    assert starts(rw) == 1
    assert rw.LOG.read_text().count("auto-seat: unresolved start not reconciled (") == 1
    assert len(rw.pages) == 1 and "gone" in rw.pages[0]


def test_34_marker_is_durable_before_subprocess_can_crash(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    def crash(argv, timeout):
        assert is_start(argv)
        state = rw.load_state()
        assert state["told"][f"auto-seat unresolved:{rw.ROLE}"] == NOW
        assert state["told"][f"auto-seat attempt:{rw.ROLE}"] == NOW
        raise RuntimeError("crash after invocation")
    monkeypatch.setattr(rw, "run_split", crash)
    with pytest.raises(RuntimeError, match="crash after invocation"):
        run_pass(rw)
    assert f"auto-seat unresolved:{rw.ROLE}" in rw.load_state()["told"]


@pytest.mark.parametrize("switch", ["0", "1"])
def test_35_unresolved_precedes_word_and_seated_but_switch_off_does_not_list(monkeypatch, tmp_path, switch):
    rw = load(monkeypatch, tmp_path, switch)
    state = {"seated": {rw.ROLE: NOW}, "told": {f"auto-seat unresolved:{rw.ROLE}": NOW}}
    rw.save_state(state)
    assert rw.auto_seat("idle", state, NOW) == ""
    assert len(rw.calls) == (1 if switch == "1" else 0)
    assert f"auto-seat unresolved:{rw.ROLE}" in rw.load_state()["told"]


def test_36_confirmed_start_clears_unresolved_marker(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    run_pass(rw)
    assert f"auto-seat unresolved:{rw.ROLE}" not in rw.load_state()["told"]
    assert rw.load_state()["seated"][rw.ROLE] == NOW


@pytest.mark.parametrize("crash_at", ["run", "inspect"])
def test_37_recovery_crash_keeps_mail_discoverable_from_disk(monkeypatch, tmp_path, crash_at):
    rw = load(monkeypatch, tmp_path)
    current = {**QUIET, "mail": ["new-peer-message"]}
    rw.save_state({"last": QUIET, "pending": []})
    monkeypatch.setattr(rw, "survey", lambda: current)
    run = rw.run_split

    def crash(argv, timeout):
        if is_start(argv) if crash_at == "run" else argv[:2] == ["paseo", "agent"]:
            raise RuntimeError("interrupted recovery subprocess")
        return run(argv, timeout)

    monkeypatch.setattr(rw, "run_split", crash)
    with pytest.raises(RuntimeError, match="interrupted recovery subprocess"):
        run_pass(rw)
    disk = json.loads(rw.STATE.read_text())
    assert disk["last"] == QUIET and disk["pending"] == []
    assert disk["told"][f"auto-seat attempt:{rw.ROLE}"] == NOW
    assert disk["told"][f"auto-seat unresolved:{rw.ROLE}"] == NOW
    if crash_at == "inspect":
        assert disk["told"][f"auto-seat candidate:{rw.ROLE}:{NEW}"] == NOW

    # Fresh module, same durable file: no in-memory state from the interrupted pass survives.
    fresh = load(monkeypatch, tmp_path / "fresh-process")
    monkeypatch.setattr(fresh, "STATE_DIR", rw.STATE_DIR)
    monkeypatch.setattr(fresh, "STATE", rw.STATE)
    monkeypatch.setattr(fresh, "LOG", rw.LOG)
    monkeypatch.setattr(fresh, "survey", lambda: current)
    monkeypatch.setattr(fresh, "why_blocked", lambda ident: ("idle", "seat recovered"))
    announced = []
    monkeypatch.setattr(fresh, "to_session", lambda text: announced.append(text) or "delivered")
    run_pass(fresh)
    assert announced == ["rumination: 1 unread peer message(s): new-peer-message"]
    disk = json.loads(fresh.STATE.read_text())
    assert disk["last"] == current and disk["pending"] == []
    assert starts(fresh) == 0


@pytest.mark.parametrize("recovery", ["confirmed", "adopted", "cleared"])
def test_38_recovery_save_before_page_keeps_previous_survey(monkeypatch, tmp_path, recovery):
    rw = load(monkeypatch, tmp_path)
    state = {"last": QUIET, "pending": []}
    if recovery != "confirmed":
        state["told"] = {f"auto-seat unresolved:{rw.ROLE}": NOW}
        rw.enum_rc, rw.enum_body = 0, json.dumps(PASEO_LS_FIXTURE if recovery == "adopted" else [])
    rw.save_state(state)
    current = {**QUIET, "mail": ["new-peer-message"]}
    monkeypatch.setattr(rw, "survey", lambda: current)

    def crash(text):
        raise RuntimeError("interrupted recovery page")

    monkeypatch.setattr(rw, "to_djbclark", crash)
    with pytest.raises(RuntimeError, match="interrupted recovery page"):
        run_pass(rw)
    disk = json.loads(rw.STATE.read_text())
    assert disk["last"] == QUIET and disk["pending"] == []
    assert f"auto-seat unresolved:{rw.ROLE}" not in disk["told"]
    if recovery == "confirmed":
        assert disk["seated"][rw.ROLE] == NOW
    if recovery != "cleared":
        assert disk["told"][f"auto-seat candidate:{rw.ROLE}:{NEW}"] == NOW


def tab_world(monkeypatch, tmp_path, open_rc=0, open_err="", no_open=None):
    """A whole pass with the REAL tab helper and a stub Paseo: what is opened, and what is logged."""
    rw = load(monkeypatch, tmp_path)
    monkeypatch.setattr(rw, "open_desktop_tab", rw.real_open_desktop_tab)
    if no_open is None:
        monkeypatch.delenv("RW_AUTO_SEAT_NO_OPEN", raising=False)
    else:
        monkeypatch.setenv("RW_AUTO_SEAT_NO_OPEN", no_open)

    def run(argv, timeout=20):
        rw.calls.append((argv, timeout))
        if is_start(argv):
            return 0, json.dumps({"agentId": NEW}), ""
        if argv[:3] == ["paseo", "agent", "inspect"]:
            return 0, json.dumps({"Id": NEW, "Archived": False, "Status": "running"}), ""
        if argv[:3] == ["paseo", "agent", "open"]:
            # N3: the seat must already be saved and the unresolved marker gone BEFORE the open
            # runs. A kill during the open then leaves a seated, diagnosable id, never a seat that
            # the next pass cannot find.
            disk = rw.load_state()
            assert disk["seated"] == {rw.ROLE: NOW}
            assert f"auto-seat unresolved:{rw.ROLE}" not in disk["told"]
            return open_rc, "", open_err
        raise AssertionError(f"unexpected call {argv}")

    monkeypatch.setattr(rw, "run_split", run)
    return rw


def test_39_confirmed_start_opens_the_tab_in_paseo_desktop(monkeypatch, tmp_path):
    rw = tab_world(monkeypatch, tmp_path)
    run_pass(rw)
    opened = [(argv, timeout) for argv, timeout in rw.calls if argv[:3] == ["paseo", "agent", "open"]]
    assert [argv for argv, _ in opened] == [["paseo", "agent", "open", NEW, "--json"]]
    assert opened[0][1] <= 20
    assert rw.load_state()["seated"] == {rw.ROLE: NOW}
    # N1: `agent open` exits as soon as the app is launched, so the line must not claim a tab was
    # OBSERVED - only that the deep link was sent.
    assert f"auto-seat: sent {NEW} to Paseo Desktop (a tab is not confirmable from here)" in rw.LOG.read_text()
    assert "opened" not in rw.LOG.read_text()
    assert len(rw.pages) == 1 and NEW in rw.pages[0]


def test_40_a_failed_open_keeps_the_seat_and_tells_djbclark(monkeypatch, tmp_path):
    rw = tab_world(monkeypatch, tmp_path, open_rc=3, open_err="no Desktop process")
    run_pass(rw)
    text = rw.LOG.read_text()
    assert rw.load_state()["seated"] == {rw.ROLE: NOW}
    assert "NOT opened in Paseo Desktop (rc=3: no Desktop process); it is reachable by relay" in text
    assert f"run paseo agent open {NEW}" in text
    # N2: the failure must reach the human, not just the pass log - a card on an unopened seat is
    # exactly the darkness this feature exists to end.
    assert len(rw.pages) == 1 and NEW in rw.pages[0]
    assert "it is reachable by relay but has no tab: run paseo agent open new-seat" in rw.pages[0]
    # A failed tab must never turn into a SECOND seat or a second open on the next pass - including
    # when fleet lists the seat, so `owner_session` resolves it as the owner (adversary D3: with the
    # candidate still diagnosed "gone" the adoption branch was never entered, so dropping the
    # fresh start's own tab stamp survived this test).
    monkeypatch.setattr(rw, "owner_session", lambda: (NEW, "auto-seat"))
    monkeypatch.setattr(rw, "why_blocked", lambda ident: ("idle", "seat recovered"))
    run_pass(rw)
    assert sum(is_start(argv) for argv, _ in rw.calls) == 1
    assert [argv for argv, _ in rw.calls if argv[:3] == ["paseo", "agent", "open"]] == [
        ["paseo", "agent", "open", NEW, "--json"]]
    assert len(rw.pages) == 1


@pytest.mark.parametrize("word", ["1", "true", "yes", "on"])
def test_41_no_open_switch_skips_the_attempt_and_still_seats(monkeypatch, tmp_path, word):
    rw = tab_world(monkeypatch, tmp_path, no_open=word)
    run_pass(rw)
    assert [argv for argv, _ in rw.calls if argv[:3] == ["paseo", "agent", "open"]] == []
    assert rw.load_state()["seated"] == {rw.ROLE: NOW}
    # The reason names the value that was actually set (adversary D5): it reaches djbclark.
    assert f"NOT opened (RW_AUTO_SEAT_NO_OPEN={word}): run paseo agent open {NEW}" in rw.LOG.read_text()
    assert len(rw.pages) == 1 and NEW in rw.pages[0]


@pytest.mark.parametrize("value", ["0", "false", "off", "no", ""])
def test_41b_other_switch_values_still_attempt_the_open(monkeypatch, tmp_path, value):
    """An explicit allowlist: any other value still attempts the open, so a typo cannot silence it."""
    rw = tab_world(monkeypatch, tmp_path, no_open=value)
    run_pass(rw)
    attempted = [argv for argv, _ in rw.calls if argv[:3] == ["paseo", "agent", "open"]]
    assert attempted == [["paseo", "agent", "open", NEW, "--json"]]
    assert rw.load_state()["seated"] == {rw.ROLE: NOW}


def adopted_world(monkeypatch, tmp_path, open_failure=""):
    """An id whose start never confirmed, adopted from the listing, then diagnosed live next pass."""
    rw = lost_id(monkeypatch, tmp_path)
    rw.opened.clear()
    rw.pages.clear()                               # pass 1's "no live session" page is done with
    rw.open_failure = open_failure
    rw.enum_rc, rw.enum_body = 0, json.dumps(PASEO_LS_FIXTURE)
    run_pass(rw)                                   # pass 1: adopt the lost id, diagnose later
    assert rw.opened == []                         # adoption is not a start: it owes no tab yet
    monkeypatch.setattr(rw, "why_blocked", lambda ident: ("idle", "seat recovered"))
    return rw


def test_43_an_adopted_candidate_gets_its_tab_on_the_first_live_pass(monkeypatch, tmp_path):
    """Codex P2 / adversary N4: a seat that reached "live" by RECOVERY was never opened."""
    rw = adopted_world(monkeypatch, tmp_path)
    run_pass(rw)
    assert rw.opened == [NEW]
    assert rw.load_state()["told"][f"auto-seat tab:{NEW}"] == NOW + rw.AUTO_SEAT_S + 1
    assert rw.pages == []                          # the open succeeded: nothing to tell


def test_44_a_failed_open_on_an_adopted_candidate_pages_and_is_not_retried(monkeypatch, tmp_path):
    reason = f"NOT opened in Paseo Desktop (rc=3: no Desktop process); it is reachable by relay but has no tab: run paseo agent open {NEW}"
    rw = adopted_world(monkeypatch, tmp_path, open_failure=reason)
    run_pass(rw)
    assert rw.opened == [NEW]
    assert len(rw.pages) == 1
    assert "has no Paseo Desktop tab" in rw.pages[0] and "run paseo agent open new-seat" in rw.pages[0]
    # One attempt per id: a retry every pass would hammer a headless host and re-page him forever.
    run_pass(rw)
    assert rw.opened == [NEW]
    assert len(rw.pages) == 1


def test_42_a_callers_agent_id_never_reaches_the_started_seat(monkeypatch, tmp_path):
    """Real `env -u` around a real child: a pass run from inside an agent must not parent it."""
    rw = load(monkeypatch, tmp_path)
    monkeypatch.setattr(rw, "open_desktop_tab", rw.real_open_desktop_tab)
    monkeypatch.setattr(rw, "run_split", rw.real_run_split)
    monkeypatch.setenv("PASEO_AGENT_ID", "caller-seat")
    seen = tmp_path / "child-env.txt"
    cli = tmp_path / "paseo"
    cli.write_text(f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args[0] == 'run':
    Path({str(seen)!r}).write_text(repr(os.environ.get('PASEO_AGENT_ID')))
    print(json.dumps({{'agentId': {NEW!r}}}))
elif args[:2] == ['agent', 'inspect']:
    print(json.dumps({{'Id': {NEW!r}, 'Archived': False, 'Status': 'running'}}))
elif args[:2] == ['agent', 'open']:
    print(json.dumps({{'opened': args[3]}}))
else:
    sys.exit(99)
""")
    cli.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    run_pass(rw)
    assert rw.load_state()["seated"] == {rw.ROLE: NOW}
    assert seen.read_text() == "None"  # repr(None): the child never inherited the caller's seat id


def test_45_a_seat_fleet_already_lists_still_gets_its_one_tab(monkeypatch, tmp_path):
    """Adversary D1: once fleet lists the new id, `owner_session` returns it as `ident`, so the
    ADOPTION branch is skipped - and that fleet-listed case is the COMMON one."""
    rw = load(monkeypatch, tmp_path)
    rw.confirm = False                       # the start's confirmation was lost, so it never opened
    run_pass(rw)
    assert rw.opened == []
    monkeypatch.setattr(rw.time, "time", lambda: NOW + rw.AUTO_SEAT_S + 1)
    monkeypatch.setattr(rw, "owner_session", rw.real_owner_session)
    monkeypatch.setattr(rw, "live_sessions", lambda: {NEW[:8]: {"ended": False, "archived": False}})
    monkeypatch.setattr(rw, "why_blocked", lambda ident: ("idle", "seat recovered"))
    rw.pages.clear()
    run_pass(rw)
    assert rw.opened == [NEW]
    assert rw.load_state()["told"][f"auto-seat tab:{NEW}"] == NOW + rw.AUTO_SEAT_S + 1
    assert rw.pages == []                    # it opened: nothing to tell him
    run_pass(rw)
    assert rw.opened == [NEW]                # one attempt per id, ever


def _tab_reason():
    return (f"NOT opened in Paseo Desktop (rc=3: no Desktop process); it is reachable by relay "
            f"but has no tab: run paseo agent open {NEW}")


def test_46_a_tab_page_he_never_received_is_carried_and_retried(monkeypatch, tmp_path):
    """Adversary D2: `tab_once` hands its reason out ONCE, so a failed send must not consume it."""
    rw = adopted_world(monkeypatch, tmp_path, open_failure=_tab_reason())
    rw.pages.clear()
    monkeypatch.setattr(rw, "to_djbclark", lambda text: False)      # one transient `hermes` failure
    run_pass(rw)
    assert rw.pages == []
    carried = rw.load_state()["undisclosed_tab"]
    assert NEW in carried and _tab_reason() in carried
    monkeypatch.setattr(rw, "to_djbclark", lambda text: rw.pages.append(text) or True)
    run_pass(rw)
    assert len(rw.pages) == 1 and "has no Paseo Desktop tab" in rw.pages[0]
    assert "undisclosed_tab" not in rw.load_state()
    run_pass(rw)
    assert len(rw.pages) == 1                # sent once, never again


def test_47_a_page_cooldown_carries_the_reason_instead_of_dropping_it(monkeypatch, tmp_path):
    """D2(b): the cooldown is one key shared by every seat, so a second seat's reason used to be
    thrown away. It waits the cooldown out and is then sent - carried, never dropped."""
    rw = adopted_world(monkeypatch, tmp_path, open_failure=_tab_reason())
    rw.pages.clear()
    state = rw.load_state()
    state["told"]["auto-seat tab"] = NOW                 # another seat paged him just now
    rw.save_state(state)
    run_pass(rw)
    assert rw.pages == []                                # anti-noise still applies
    assert "undisclosed_tab" in rw.load_state()          # ... but the reason is kept
    monkeypatch.setattr(rw.time, "time", lambda: NOW + rw.DJB_COOLDOWN_S + 1)
    run_pass(rw)
    assert len(rw.pages) == 1 and "has no Paseo Desktop tab" in rw.pages[0]
    assert "undisclosed_tab" not in rw.load_state()
