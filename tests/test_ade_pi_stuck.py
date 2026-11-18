"""bin/ade-pi-stuck (2026-11-18): which live Pi agents sit on a quota-exhausted billing account.

`paseo ls -g --json` and `aiuse --available --json` are faked on PATH, so nothing reaches Paseo, aiuse or the network.
The rules under test are the ones that decide a re-handoff: a fresh zero, a stale reading of a known-empty account
(fail closed: only a fresh positive balance clears it), the opencode:go account mapping, and an aiuse that fails
altogether."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "bin" / "ade-pi-stuck"
NL = chr(10)

AGENTS = [
    {"id": "a1", "name": "openai agent", "provider": "pi/openai/gpt-6.1-sol", "status": "running"},
    {"id": "b2", "name": "go agent", "provider": "pi/opencode-go-t-e/deepseek-v4-pro", "status": "idle"},
    {"id": "c3", "name": "flash agent", "provider": "pi/anthropic/claude-haiku-4-5", "status": "closed"},
    {"id": "d4", "name": "not pi", "provider": "pipeline/whatever/1", "status": "running"},
]


def _pools(**headroom):
    """aiuse --available JSON: {"<pool_id>": (headroom_percent, usable_now, stale)}."""
    pools = []
    for pool_id, (headroom, usable, stale) in headroom.items():
        entry = {"pool_id": pool_id, "headroom_percent": headroom, "usable_now": usable, "stale": stale}
        if pool_id == "opencode:go":
            entry["account"] = "t-e"
        pools.append(entry)
    return {"fresh": True, "available": pools}


def _run(tmp_path: Path, pools=None, aiuse_rc: int = 0, agents=None):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "paseo").write_text(
        "#!/bin/sh\ncat <<'JSON'\n%s\nJSON\n" % json.dumps(agents if agents is not None else AGENTS))
    (bin_dir / "paseo").chmod(0o755)
    lines = ["#!/bin/sh"]
    if pools is not None:
        lines.append("cat <<'JSON'")
        lines.append(json.dumps(pools))
        lines.append("JSON")
    lines.append("exit %d" % aiuse_rc)                       # the exit code is honoured with or without a reading
    (bin_dir / "aiuse").write_text(NL.join(lines) + NL)
    (bin_dir / "aiuse").chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
    r = subprocess.run([str(CLI), "--json"], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _stuck_ids(report) -> list[str]:
    return sorted(s["id"] for s in report["stuck"])


def test_a_zero_headroom_account_makes_its_agent_stuck_with_an_alternative(tmp_path: Path) -> None:
    report = _run(tmp_path, _pools(**{"openai:openai_api": (0.0, True, False),
                                      "opencode:go": (40.0, True, False)}))
    assert _stuck_ids(report) == ["a1"]
    stuck = report["stuck"][0]
    assert stuck["account"] == "openai" and stuck["headroom_percent"] == 0.0
    assert stuck["alternative"] == "pi/opencode-go-t-e/deepseek-v4-pro"      # not a low-effort model


def test_a_low_effort_model_gets_a_low_effort_alternative(tmp_path: Path) -> None:
    agents = [{"id": "f1", "provider": "pi/openai/gpt-4o-mini", "status": "running"}]
    report = _run(tmp_path, _pools(**{"openai:openai_api": (0.0, True, False)}), agents=agents)
    assert report["stuck"][0]["alternative"] == "pi/opencode-go-t-e/deepseek-v4.1-flash"


def test_a_stale_reading_never_clears_a_known_empty_account(tmp_path: Path) -> None:
    pools = _pools(**{"openai:openai_api": (28.8, True, True)})      # 2026-11-17: 28.8% from a 21 h old reading, $0 real
    pools["fresh"] = False
    assert _stuck_ids(_run(tmp_path, pools)) == ["a1"]


def test_a_fresh_positive_balance_clears_the_known_empty_account(tmp_path: Path) -> None:
    assert _stuck_ids(_run(tmp_path, _pools(**{"openai:openai_api": (5.0, True, False)}))) == []


def test_an_unusable_pool_marks_the_account_exhausted(tmp_path: Path) -> None:
    report = _run(tmp_path, _pools(**{"anthropic:subscription": (80.0, False, False)}))
    assert "c3" not in _stuck_ids(report)                            # c3 is closed
    assert set(report["exhausted"]) == {"anthropic", "openai"}        # openai is unread here, so it stays fail-closed


def test_an_aiuse_failure_falls_back_to_the_known_empty_accounts(tmp_path: Path) -> None:
    report = _run(tmp_path, aiuse_rc=1)
    assert _stuck_ids(report) == ["a1"]                              # fail closed, never "all fine"
    assert report["exhausted"] == ["openai"] and report["accounts"] == {}


def test_the_opencode_go_pool_maps_its_sub_account(tmp_path: Path) -> None:
    report = _run(tmp_path, _pools(**{"opencode:go": (0.0, True, False)}))
    by_id = {o["id"]: o for o in report["all_pi"]}
    assert by_id["b2"]["account"] == "opencode-go-t-e" and by_id["b2"]["stuck"] is True


def test_the_worst_pool_for_an_account_wins(tmp_path: Path) -> None:
    report = _run(tmp_path, _pools(**{"anthropic:subscription": (60.0, True, False),
                                      "anthropic:fable": (4.0, True, False)}))
    assert report["accounts"]["anthropic"]["headroom"] == 4.0
    assert report["low"] == ["anthropic"]                            # 4% is thin: flag it before it hits zero


def test_only_pi_prefixed_providers_are_listed(tmp_path: Path) -> None:
    report = _run(tmp_path, _pools(**{"openai:openai_api": (0.0, True, False)}))
    assert "d4" not in {o["id"] for o in report["all_pi"]}           # provider "pipeline/…" is not a Pi account


def test_aiuse_exit_3_still_reads_its_pools(tmp_path: Path) -> None:
    """aiuse exits 3 when no pool is usable, but prints the JSON: refusing the read would fail open."""
    pools = _pools(**{"openai:openai_api": (0.0, True, False), "anthropic:subscription": (0.0, False, False)})
    assert set(_run(tmp_path, pools, aiuse_rc=3)["exhausted"]) == {"openai", "anthropic"}


def test_an_unusable_pool_outranks_a_usable_one_with_less_headroom(tmp_path: Path) -> None:
    raw = {"fresh": True, "available": [
        {"pool_id": "anthropic:subscription", "headroom_percent": 10.0, "usable_now": True, "stale": False},
        {"pool_id": "anthropic:fable", "headroom_percent": 90.0, "usable_now": False, "stale": False},
    ]}
    report = _run(tmp_path, raw)
    assert report["accounts"]["anthropic"]["usable"] is False
    assert "anthropic" in report["exhausted"]


def test_the_alternative_is_never_the_agents_own_exhausted_account(tmp_path: Path) -> None:
    report = _run(tmp_path, _pools(**{"opencode:go": (0.0, True, False)}))
    stuck = [s for s in report["stuck"] if s["id"] == "b2"][0]
    assert stuck["account"] == "opencode-go-t-e"
    assert stuck["alternative"] and not stuck["alternative"].startswith("pi/opencode-go-t-e/")


def test_a_gemini_model_is_not_mistaken_for_a_low_effort_tier(tmp_path: Path) -> None:
    agents = [{"id": "g1", "provider": "pi/google/gemini-2.5-pro", "status": "running"}]
    report = _run(tmp_path, _pools(**{"google:gemini": (0.0, True, False)}), agents=agents)
    assert report["stuck"][0]["alternative"] == "pi/opencode-go-t-e/deepseek-v4-pro"   # not the flash tier
    agents = [{"id": "g2", "provider": "pi/google/gemini-2.5-flash", "status": "running"}]
    report = _run(tmp_path, _pools(**{"google:gemini": (0.0, True, False)}), agents=agents)
    assert report["stuck"][0]["alternative"] == "pi/opencode-go-t-e/deepseek-v4.1-flash"


def test_no_healthy_candidate_means_no_alternative(tmp_path: Path) -> None:
    raw = {"fresh": True, "available": [
        {"pool_id": "openai:openai_api", "headroom_percent": 0.0, "usable_now": True, "stale": False},
        {"pool_id": "opencode:go", "account": "t-e", "headroom_percent": 0.0, "usable_now": True, "stale": False},
        {"pool_id": "opencode:go", "account": "djbclark", "headroom_percent": 0.0, "usable_now": True, "stale": False},
    ]}
    report = _run(tmp_path, raw)
    assert [s["alternative"] for s in report["stuck"] if s["id"] == "a1"] == [None]


def test_an_absent_fresh_flag_does_not_clear_a_known_empty_account(tmp_path: Path) -> None:
    """aiuse >= 1.6 emits `fresh`; when it is missing the reading is not trusted to clear a known-empty account."""
    pools = _pools(**{"openai:openai_api": (28.8, True, False)})
    del pools["fresh"]
    assert _stuck_ids(_run(tmp_path, pools)) == ["a1"]


def test_a_readable_healthy_account_beats_an_unread_one(tmp_path: Path) -> None:
    """The alternative prefers an account with a fresh reading above the thin line over one nothing is known about."""
    raw = {"fresh": True, "available": [
        {"pool_id": "openai:openai_api", "headroom_percent": 0.0, "usable_now": True, "stale": False},
        {"pool_id": "opencode:go", "account": "t-e", "headroom_percent": 0.0, "usable_now": True, "stale": False},
        {"pool_id": "opencode:go", "account": "djbclark", "headroom_percent": 55.0, "usable_now": True, "stale": False},
    ]}
    stuck = [s for s in _run(tmp_path, raw)["stuck"] if s["id"] == "a1"]
    assert stuck and stuck[0]["alternative"].startswith("pi/opencode-go-djbclark/")


def test_an_aiuse_failure_is_reported_not_hidden(tmp_path: Path) -> None:
    """A caller must be able to tell "every account is healthy" from "the quota read failed"."""
    report = _run(tmp_path, aiuse_rc=1)
    assert report["quota_error"] and "exited 1" in report["quota_error"]
    assert _run(tmp_path, _pools(**{"openai:openai_api": (5.0, True, False)}))["quota_error"] is None


def test_a_stale_thin_reading_is_never_offered_as_an_alternative(tmp_path: Path) -> None:
    raw = {"fresh": True, "available": [
        {"pool_id": "openai:openai_api", "headroom_percent": 0.0, "usable_now": True, "stale": False},
        {"pool_id": "opencode:go", "account": "t-e", "headroom_percent": 3.0, "usable_now": True, "stale": True},
        {"pool_id": "opencode:go", "account": "djbclark", "headroom_percent": 9.0, "usable_now": True, "stale": True},
    ]}
    stuck = [s for s in _run(tmp_path, raw)["stuck"] if s["id"] == "a1"]
    assert stuck and stuck[0]["alternative"] is None    # both candidates are thin, so offer nothing


def test_a_stale_zero_reading_is_never_offered_as_an_alternative(tmp_path: Path) -> None:
    """A stale 0% is not in `exhausted` when the reading is not fresh, but it is still no re-handoff target."""
    raw = {"fresh": False, "available": [
        {"pool_id": "openai:openai_api", "headroom_percent": 0.0, "usable_now": True, "stale": True},
        {"pool_id": "opencode:go", "account": "t-e", "headroom_percent": 0.0, "usable_now": True, "stale": True},
    ]}
    stuck = [s for s in _run(tmp_path, raw)["stuck"] if s["id"] == "a1"]
    assert stuck and not (stuck[0]["alternative"] or "").startswith("pi/opencode-go-t-e/")


def test_closed_archived_and_errored_agents_are_not_flagged(tmp_path: Path) -> None:
    """`error` is dead for ade-progress, so it is not "stuck on an exhausted account" either."""
    agents = [{"id": "x1", "provider": "pi/openai/gpt-6.1-sol", "status": "error"},
              {"id": "x2", "provider": "pi/openai/gpt-6.1-sol", "status": "archived"},
              {"id": "x3", "provider": "pi/openai/gpt-6.1-sol", "status": "closed"}]
    report = _run(tmp_path, _pools(**{"openai:openai_api": (0.0, True, False)}), agents=agents)
    assert report["stuck"] == []


def test_an_account_without_a_quota_mapping_is_reported(tmp_path: Path) -> None:
    """A bare `opencode-go/` provider names no billing sub-account: it cannot be judged, so it is not shown as healthy."""
    agents = [{"id": "o1", "provider": "pi/opencode-go/deepseek-v4-pro", "status": "running"}]
    report = _run(tmp_path, _pools(**{"opencode:go": (40.0, True, False)}), agents=agents)
    assert report["unmapped"] == ["opencode-go"]
    assert report["stuck"] == []
