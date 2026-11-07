"""bin/ade_gates.py and config/gates.toml: the frontier allowance (2026-10-27; trimmed to the frontier half 2026-11-07, slim-down E7).

The loader is driven with a copy of the shipped gates.toml (GATES_TOML); the Claude reading `read_guard_state` builds comes from
route_agent's merged quota snapshot, fed here with canned `aiuse --available --json` and `paseo usage ls --json` output. Nothing
touches the real ~/.local/state, aiuse or Paseo."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
sys.path.insert(0, str(BIN))
import ade_gates as g  # noqa: E402

NOW = datetime(2026, 10, 26, 16, 0, 0, tzinfo=UTC)      # 12:00 PM EDT, a Monday
STANDING = {"frontier1_judged": 1.0, "frontier2_judged": 1.0, "frontier1_per_wave": 2.0, "frontier2_per_wave": 1.0,
            "frontier1_agent_calls_per_day": 4.0, "frontier1_min_left": 15.0, "frontier1_window_min_left": 30.0,
            "frontier2_min_left": 60.0}     # the 2026-10-27 ruling; the window floor since 2026-11-07


def close_frontier_baseline(text: str) -> str:
    """The shipped file with its `[frontier]` BASELINE set to the all-closed code defaults (floors unchanged)."""
    def close(m):
        body = m.group(0)
        for k, v in g.FRONTIER_DEFAULTS.items():
            body = re.sub(rf"(?m)^{k} = [0-9.]+", f"{k} = {v:g}", body, count=1)
        return body
    out = re.sub(r"(?ms)^\[frontier\]\n.*?(?=^\[|\Z)", close, text, count=1)
    assert out != text
    return out


@pytest.fixture
def fenv(tmp_path, monkeypatch):
    """A copy of the SHIPPED gates.toml; returns its path."""
    toml = tmp_path / "gates.toml"
    toml.write_text((REPO / "config" / "gates.toml").read_text())
    monkeypatch.setenv("GATES_TOML", str(toml))
    g._LOGGED.clear()
    return toml


@pytest.fixture
def fenv_closed(fenv):
    fenv.write_text(close_frontier_baseline(fenv.read_text()))
    return fenv


def front(now=NOW):
    return g.load_frontier(now)


def test_the_shipped_frontier_baseline_is_the_ruled_standing_allowance_and_its_floors_equal_it():
    import tomllib
    cfg = tomllib.loads((REPO / "config" / "gates.toml").read_text())
    assert cfg["frontier"] == pytest.approx(STANDING)
    assert set(cfg) == {"frontier", "floors"} and set(cfg["floors"]) == {"frontier"}      # the quota-gate tables are gone
    for k, v in STANDING.items():
        if not k.endswith("_min_left"):
            assert cfg["floors"]["frontier"][k] == {"loosen": "higher", "bound": v}, k
        else:
            assert cfg["frontier"][k] == g.FRONTIER_DEFAULTS[k], k        # a min_left baseline equals the code default
    assert all(g.FRONTIER_DEFAULTS[k] == 0 for k in ("frontier1_judged", "frontier2_judged", "frontier1_agent_calls_per_day"))


def test_the_shipped_baseline_loads_as_the_standing_allowance(fenv):
    t, info = front()
    assert t == STANDING and info["profile"] is None and info["baseline_guarded"] == {} and info["toml_error"] is None
    assert info["source"] == "gates.toml"


def test_a_closed_frontier_baseline_is_the_code_default(fenv_closed):
    t, info = front()
    assert t == g.FRONTIER_DEFAULTS and info["profile"] is None
    assert (t["frontier1_per_wave"], t["frontier2_per_wave"], t["frontier1_min_left"]) == (1, 1, 15)


def test_a_gates_toml_baseline_past_its_floor_bound_is_replaced_by_the_code_default(fenv):
    fenv.write_text(fenv.read_text().replace("frontier1_agent_calls_per_day = 4 ", "frontier1_agent_calls_per_day = 5 ", 1)
                    .replace("frontier1_per_wave = 2 ", "frontier1_per_wave = 3 ", 1)
                    .replace("frontier1_min_left = 15.0 ", "frontier1_min_left = 1.0 ", 1)
                    .replace("frontier1_window_min_left = 30.0 ", "frontier1_window_min_left = 5.0 ", 1))
    t, info = front()
    assert (t["frontier1_agent_calls_per_day"], t["frontier1_per_wave"], t["frontier1_min_left"]) == (0, 1, 15)
    assert t["frontier1_window_min_left"] == 30
    assert (t["frontier1_judged"], t["frontier2_judged"], t["frontier2_per_wave"]) == (1, 1, 1)
    assert set(info["baseline_guarded"]) == {"frontier1_agent_calls_per_day", "frontier1_per_wave", "frontier1_min_left",
                                             "frontier1_window_min_left"}


def test_a_min_left_baseline_may_tighten(fenv):
    fenv.write_text(fenv.read_text().replace("frontier2_min_left = 60.0 ", "frontier2_min_left = 70.0 ", 1)
                    .replace("frontier1_window_min_left = 30.0 ", "frontier1_window_min_left = 45.0 ", 1))
    t, info = front()
    assert (t["frontier2_min_left"], t["frontier1_window_min_left"]) == (70, 45) and info["baseline_guarded"] == {}


def test_a_missing_frontier_floor_table_still_guards_every_frontier_key(fenv):
    fenv.write_text(fenv.read_text().replace("[floors.frontier]", "[floors.unused]", 1))
    t, info = front()
    assert t == g.FRONTIER_DEFAULTS
    assert set(info["baseline_guarded"]) == {"frontier1_judged", "frontier2_judged", "frontier1_per_wave",
                                             "frontier1_agent_calls_per_day"}


def test_a_flipped_floor_direction_does_not_loosen_the_baseline(fenv):
    """The code direction rules: a floor entry whose `loosen` disagrees changes nothing; its bound (0) still caps the baseline."""
    fenv.write_text(fenv.read_text().replace('frontier1_judged = { loosen = "higher", bound = 1 }',
                                             'frontier1_judged = { loosen = "lower", bound = 0 }'))
    t, info = front()
    assert t["frontier1_judged"] == 0 and set(info["baseline_guarded"]) == {"frontier1_judged"}


@pytest.mark.parametrize("bound", ["nan", "inf", '"4"', "true", "[4]", "{}"])
def test_a_non_numeric_floor_bound_closes_that_key(fenv, bound):
    floor = 'frontier1_agent_calls_per_day = { loosen = "higher", bound = 4 }'
    fenv.write_text(fenv.read_text().replace(floor, f'frontier1_agent_calls_per_day = {{ loosen = "higher", bound = {bound} }}', 1))
    t, info = front()
    assert t["frontier1_agent_calls_per_day"] == 0 and set(info["baseline_guarded"]) == {"frontier1_agent_calls_per_day"}
    assert t["frontier1_per_wave"] == 2


def test_a_gates_toml_that_is_a_fifo_is_unusable_not_a_hang(tmp_path, monkeypatch):
    fifo = tmp_path / "gates.toml"
    os.mkfifo(fifo)
    monkeypatch.setenv("GATES_TOML", str(fifo))
    cfg, err = g.read_toml()
    assert cfg is None and "not a regular file" in err
    assert g.load_frontier()[0] == g.FRONTIER_DEFAULTS


def test_no_environment_variable_changes_the_frontier_gate(fenv_closed, monkeypatch):
    for var in ("CLAUDE_GOVERNOR_THRESHOLDS", "CLAUDE_QUOTA_GUARD_THRESHOLDS", "FRONTIER_GATE_THRESHOLDS"):
        monkeypatch.setenv(var, json.dumps({"frontier1_judged": 1, "frontier1_agent_calls_per_day": 99}))
    assert front()[0] == g.FRONTIER_DEFAULTS


def test_a_missing_gates_toml_is_the_frontier_code_default(monkeypatch):
    monkeypatch.setenv("GATES_TOML", "/nonexistent/gates.toml")
    t, info = front()
    assert t == g.FRONTIER_DEFAULTS and info["source"] == "code" and info["toml_error"]


@pytest.mark.parametrize("text", ["[frontier\n", "[frontier]\nfrontier1_judged = \"1\"\n", "", "[governor]\na = 1\n"])
def test_an_unreadable_or_invalid_gates_toml_leaves_the_frontier_gate_closed(fenv, text):
    fenv.write_text(text)
    t, info = front()
    assert t == g.FRONTIER_DEFAULTS and info["toml_error"] is not None


# -- the Claude reading -------------------------------------------------------------------------------------------

STATE_OK = {"checked_at": g.iso(NOW - timedelta(minutes=1)), "source": "aiuse", "remaining": 55.0, "fable_left": 50.0,
            "windows": {"weekly": 55.0, "5-hour": 80.0}, "unknown": None}


def test_judged_guard_block_passes_a_fresh_reading_above_both_floors():
    assert g.judged_guard_block(STATE_OK, STANDING, NOW) is None


@pytest.mark.parametrize("over, why", [
    ({"unknown": "paseo usage claude: report unavailable (rejected)"}, "unknown (paseo usage claude"),
    ({"remaining": 29.9}, "tightest window"), ({"remaining": None}, "no window percentage"), ({"remaining": True}, "no window"),
    ({"fable_left": 14.99}, "frontier-1 cap has"), ({"fable_left": None}, "missing"),
    ({"checked_at": None}, "no usable time"), ({"checked_at": "2026-10-26T11:59:00"}, "no usable time"),
])
def test_judged_guard_block_refuses(over, why):
    assert why in g.judged_guard_block({**STATE_OK, **over}, STANDING, NOW)


def test_judged_guard_block_age_and_floor_boundaries():
    at = lambda secs: {**STATE_OK, "checked_at": g.iso(NOW - timedelta(seconds=secs))}      # noqa: E731
    assert g.judged_guard_block(at(1800), STANDING, NOW) is None and "min old" in g.judged_guard_block(at(1801), STANDING, NOW)
    assert g.judged_guard_block(at(-60), STANDING, NOW) is None and "min old" in g.judged_guard_block(at(-61), STANDING, NOW)
    assert g.judged_guard_block({**STATE_OK, "remaining": 30.0}, STANDING, NOW) is None
    assert g.judged_guard_block({**STATE_OK, "fable_left": 15.0}, STANDING, NOW) is None
    assert g.judged_guard_block({**STATE_OK, "remaining": 40.0}, {**STANDING, "frontier1_window_min_left": 45.0}, NOW)
    for bad in (None, [], "ok", 7):
        assert "missing or unreadable" in g.judged_guard_block(bad, STANDING, NOW)


def test_judged_pool_block_for_the_codex_family_reads_the_pool_remaining():
    assert g.judged_pool_block(2, STANDING, NOW, None, 60.0) is None
    assert "59.9% left" in g.judged_pool_block(2, STANDING, NOW, None, 59.9)
    assert "no reading" in g.judged_pool_block(2, STANDING, NOW, None, None)
    assert g.judged_pool_block(1, STANDING, NOW, STATE_OK, None) is None


@pytest.mark.parametrize("text, ok", [("a" * 9, False), ("a" * 10, True), ("  " + "a" * 200 + "  ", True), ("a" * 201, False),
                                      ("", None), ("   ", None), (None, None), ("ten chars\nmore", False), ("tab\tin the reason", False),
                                      (12345, False), ("ten chars more", False), ("ten chars\u0085more", False),
                                      ("ten chars\u009bmore", False), ("ten chars‮more", False), ("zero‍width joiner", False)])
def test_frontier_reason_form(text, ok):
    reason, problem = g.frontier_reason(text)
    if ok is None:
        assert (reason, problem) == (None, None)
    elif ok:
        assert reason == text.strip() and problem is None
    else:
        assert reason is None and problem


def _usage(tmp_path: Path, rows: list) -> str:
    path = tmp_path / "usage.json"
    path.write_text(json.dumps(rows))
    return str(path)


def _claude_report(fetched: datetime, status: str = "available", weekly_left: float = 70.0, fable_left: float = 60.0) -> dict:
    report = {"status": status}
    if status == "available":
        report["windows"] = [{"id": "w", "label": "Weekly", "usedPct": 100 - weekly_left, "remainingPct": weekly_left,
                              "resetsAt": "2026-11-10T00:00:00Z"},
                             {"id": "f", "label": "Weekly (Fable)", "usedPct": 100 - fable_left, "remainingPct": fable_left,
                              "resetsAt": "2026-11-10T00:00:00Z"}]
    else:
        report["problem"] = {"kind": "rejected", "status": 403}
    return {"id": "claude:default", "sourceId": "claude", "sourceLabel": "Claude", "icon": "<svg/>", "account": "x",
            "fetchedAt": g.iso(fetched), "report": report, "loginErrors": []}


def _read_guard(env: dict) -> dict:
    """`read_guard_state()` in a child (a fresh module state, a 10 s kill) with only the given quota sources."""
    script = ("import sys, json; sys.path.insert(0, sys.argv[1]); import ade_gates as g; "
              "print(json.dumps(g.read_guard_state()))")
    base = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/"), "ROUTE_AGENT_AIUSE": "off",
            "ROUTE_AGENT_PASEO": "off", "AIUSE_SNAPSHOT": "/nonexistent/aiuse.json"}
    r = subprocess.run([sys.executable, "-I", "-c", script, str(BIN)], env={**base, **env},
                       capture_output=True, text=True, timeout=10, check=True)
    return json.loads(r.stdout)


def test_read_guard_state_is_the_paseo_claude_reading_with_its_fable_cap(tmp_path):
    now = datetime.now(UTC)
    st = _read_guard({"ROUTE_AGENT_PASEO_USAGE_JSON": _usage(tmp_path, [_claude_report(now - timedelta(minutes=2))])})
    assert (st["remaining"], st["fable_left"], st["source"], st["unknown"]) == (70.0, 60.0, "paseo", None)
    assert g.judged_guard_block(st, STANDING, datetime.now(UTC)) is None


def test_read_guard_state_with_an_unavailable_paseo_report_and_no_aiuse_is_unknown_and_blocks(tmp_path):
    st = _read_guard({"ROUTE_AGENT_PASEO_USAGE_JSON": _usage(tmp_path, [_claude_report(datetime.now(UTC), "unavailable")])})
    assert st["remaining"] is None and "report unavailable" in st["unknown"]
    assert "unknown" in g.judged_guard_block(st, STANDING, datetime.now(UTC))


def test_read_guard_state_with_nothing_readable_blocks():
    st = _read_guard({})
    assert "no Claude reading" in st["unknown"]
    assert "unknown" in g.judged_guard_block(st, STANDING, datetime.now(UTC))
