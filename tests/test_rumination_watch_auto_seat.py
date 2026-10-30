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

    def run(argv, timeout=20):
        rw.calls.append((argv, timeout))
        if argv == ["paseo", "ls", "--json", "--background"]:
            assert timeout <= 20
            return rw.enum_rc, rw.enum_body, "listing failure" if rw.enum_rc else ""
        # The successful-start stamp must not exist during either the start OR confirmation call.
        assert rw.load_state().get("seated", {}).get(rw.ROLE) != NOW
        if argv[:2] == ["paseo", "run"]:
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
    assert argv[:-1] == ["paseo", "run", "--provider", "opencode/opencode-go", "--no-wait", "--json",
                        "--cwd", str(rw.REPO), "--title", "test-role (auto-seat)", "--"]
    assert str(rw.pointer.resolve()) in argv[-1]
    assert rw.ROLE in argv[-1] and str(rw.REPO) in argv[-1]
    assert SECRET not in argv[-1]
    assert "## Current State" in argv[-1] and "- Next steps:" in argv[-1]
    assert "gone" in argv[-1] and "automatically" in argv[-1]
    assert len(argv[-1].splitlines()) < 15
    assert timeout <= 120 and rw.calls[1][1] <= 20
    assert rw.load_state()["seated"] == {rw.ROLE: NOW}


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
    assert sum(argv[:2] == ["paseo", "run"] for argv, _ in rw.calls) == 1
    assert rw.LOG.read_text().count("auto-seat: attempted paseo run") == 1
    monkeypatch.setattr(rw.time, "time", lambda: NOW + rw.AUTO_SEAT_S)
    run_pass(rw)
    assert sum(argv[:2] == ["paseo", "run"] for argv, _ in rw.calls) == 1
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
    assert sum(argv[:2] == ["paseo", "run"] for argv, _ in rw.calls) == 1
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
    assert sum(argv[:2] == ["paseo", "run"] for argv, _ in rw.calls) == 1
    text = rw.LOG.read_text()
    assert text.count("auto-seat: not started") == 1
    assert text.count("auto-seat: attempted paseo run rc=127; stderr='stub failure'; id=none; failed") == 1
    monkeypatch.setattr(rw.time, "time", lambda: NOW + rw.AUTO_SEAT_S)
    run_pass(rw)
    assert sum(argv[:2] == ["paseo", "run"] for argv, _ in rw.calls) == 1
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
        if argv[:2] == ["paseo", "run"]:
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
    return sum(argv[:2] == ["paseo", "run"] for argv, _ in rw.calls)


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
        assert argv[:2] == ["paseo", "run"]
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
