"""§J: opt-in, proven absence, confirmed-start cooldown; no network or real agents."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path

import pytest

NOW = 1_800_000_000.0
OLD = "old-seat"
NEW = "new-seat"
SECRET = "DISTINCTIVE OTHER CHAIN SLICE DO NOT COPY"
QUIET = {"mail": [], "jobs": [], "prs": [], "stale": None}


def load(monkeypatch, tmp_path, switch="1"):
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
    rw.confirm = True

    def run(argv, timeout=20):
        rw.calls.append((argv, timeout))
        # The successful-start stamp must not exist during either the start OR confirmation call.
        assert rw.load_state().get("seated", {}).get(rw.ROLE) != NOW
        if argv[:2] == ["paseo", "run"]:
            return rw.run_rc, json.dumps({"agentId": NEW}), "stub failure" if rw.run_rc else ""
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


@pytest.mark.parametrize("word", ["card:question", "card:unknown", "working", "idle", "unknown", ""])
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


def test_7_failed_run_does_not_stamp_and_retries_next_pass(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    rw.run_rc = 1
    run_pass(rw)
    assert not rw.load_state().get("seated")
    run_pass(rw)
    assert len(rw.calls) == 2
    assert not rw.load_state().get("seated")
    assert rw.LOG.read_text().count("auto-seat: not started") == 1
    assert "gone" in rw.pages[0] and NEW not in rw.pages[0]


def test_8_unconfirmed_start_does_not_stamp(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    rw.confirm = False
    run_pass(rw)
    assert len(rw.calls) == 2
    assert not rw.load_state().get("seated")


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
    assert len(rw.calls) == 2
    assert rw.auto_seat_candidate(rw.load_state()) == NEW
    if not confirmed:
        assert not rw.load_state().get("seated")


def test_17_saved_candidate_is_considered_by_real_owner_resolution(monkeypatch, tmp_path):
    rw = load(monkeypatch, tmp_path)
    run_pass(rw)
    monkeypatch.delenv("RW_SESSION", raising=False)
    monkeypatch.delenv("PASEO_AGENT_ID", raising=False)
    assert next(rw.owner_candidates()) == ("auto-seat", NEW)


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
    monkeypatch.setattr(rw, "owner_session", lambda: ("successor", "registry"))
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
