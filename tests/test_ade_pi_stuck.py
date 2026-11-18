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
    aiuse = "#!/bin/sh\nexit %d\n" % aiuse_rc
    if pools is not None:
        aiuse = "#!/bin/sh\ncat <<'JSON'\n%s\nJSON\n" % json.dumps(pools)
    (bin_dir / "aiuse").write_text(aiuse)
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
