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
    """aiuse --available JSON: {"<pool_id>": (headroom_percent, usable_now, stale)}.

    A sub-account pool_id may carry an account after a "#" ("opencode:go#t-e"),
    which becomes the aiuse `account` field. Without one, no account is set.
    """
    pools = []
    for key, (headroom, usable, stale) in headroom.items():
        pool_id, _, account = key.partition("#")
        entry = {"pool_id": pool_id, "headroom_percent": headroom, "usable_now": usable, "stale": stale}
        if account:
            entry["account"] = account
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
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", ADE_PASEO_TRANSPORT="cli")
    env.pop("ADE_PASEO_URL", None)
    r = subprocess.run([str(CLI), "--json"], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _stuck_ids(report) -> list[str]:
    return sorted(s["id"] for s in report["stuck"])


def test_a_zero_headroom_account_makes_its_agent_stuck_with_an_alternative(tmp_path: Path) -> None:
    report = _run(tmp_path, _pools(**{"openai:openai_api": (0.0, True, False),
                                      "opencode:go#t-e": (40.0, True, False)}))
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
    report = _run(tmp_path, _pools(**{"opencode:go#t-e": (0.0, True, False)}))
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
    report = _run(tmp_path, _pools(**{"opencode:go#t-e": (0.0, True, False)}))
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
    assert report["unmapped"] == []           # an unread quota is one alert, not one "no mapping" per account
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
    """A zero or unusable pool is fail-closed (the account is exhausted) and is never offered as a re-handoff target."""
    raw = {"fresh": False, "available": [
        {"pool_id": "openai:openai_api", "headroom_percent": 0.0, "usable_now": True, "stale": True},
        {"pool_id": "opencode:go", "account": "t-e", "headroom_percent": 0.0, "usable_now": True, "stale": True},
    ]}
    stuck = [s for s in _run(tmp_path, raw)["stuck"] if s["id"] == "a1"]
    assert stuck and not (stuck[0]["alternative"] or "").startswith("pi/opencode-go-t-e/")


def test_closed_and_archived_agents_are_not_flagged_but_an_errored_one_is(tmp_path: Path) -> None:
    """Closed and archived agents have nothing to re-hand. A hard `error` is stuck, Pi included (queue item 82)."""
    agents = [{"id": "x1", "provider": "pi/openai/gpt-6.1-sol", "status": "error"},
              {"id": "x2", "provider": "pi/openai/gpt-6.1-sol", "status": "archived"},
              {"id": "x3", "provider": "pi/openai/gpt-6.1-sol", "status": "closed"}]
    report = _run(tmp_path, _pools(**{"openai:openai_api": (0.0, True, False)}), agents=agents)
    assert _stuck_ids(report) == ["x1"]


def test_a_pi_agent_in_error_on_a_healthy_account_is_stuck_with_a_pi_alternative(tmp_path: Path) -> None:
    """Queue item 82: a Pi agent on xai-oauth/grok-4.7 that a 402 left in `error` was invisible. It is flagged, and
    its alternative stays inside the Pi family."""
    agents = [{"id": "p1", "name": "grok lead", "provider": "pi/xai-oauth/grok-4.7", "status": "error"},
              {"id": "p2", "provider": "pi/xai-oauth/grok-4.7", "status": "running"}]
    report = _run(tmp_path, _pools(**{"opencode:go": (80.0, True, False)}), agents=agents)
    assert _stuck_ids(report) == ["p1"]
    stuck = report["stuck"][0]
    assert stuck["family"] == "pi" and stuck["status"] == "error"
    assert stuck["alternative"] == "pi/opencode-go-t-e/deepseek-v4-pro"


def test_an_errored_codex_or_claude_agent_gets_no_pi_alternative(tmp_path: Path) -> None:
    """The Pi candidates are DeepSeek models on other vendors' accounts: never offered to a Codex or Claude agent,
    even when plenty of Pi headroom exists (a quality downgrade and a cross-vendor data move)."""
    agents = [{"id": "c1", "provider": "codex/gpt-6-astra", "status": "error"},
              {"id": "c2", "provider": "claude/opus-5-5", "status": "error"},
              {"id": "c3", "provider": "pi/openai/gpt-6.1-sol", "status": "error"}]
    pools = _pools(**{"openai:openai_api": (0.0, True, False), "opencode:go": (90.0, True, False)})
    report = _run(tmp_path, pools, agents=agents)
    by_id = {s["id"]: s for s in report["stuck"]}
    assert set(by_id) == {"c1", "c2", "c3"}
    assert by_id["c1"]["alternative"] is None and by_id["c1"]["family"] == "codex"
    assert by_id["c2"]["alternative"] is None and by_id["c2"]["family"] == "claude"
    assert by_id["c3"]["alternative"] == "pi/opencode-go-t-e/deepseek-v4-pro"      # a Pi agent keeps its Pi alternative


def test_the_human_table_says_a_non_pi_agent_has_no_pi_alternative(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    agents = [{"id": "c1", "provider": "codex/gpt-6-astra", "status": "error"}]
    (bin_dir / "paseo").write_text("#!/bin/sh\ncat <<'JSON'\n%s\nJSON\n" % json.dumps(agents))
    (bin_dir / "paseo").chmod(0o755)
    (bin_dir / "aiuse").write_text("#!/bin/sh\nexit 1\n")
    (bin_dir / "aiuse").chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", ADE_PASEO_TRANSPORT="cli")
    env.pop("ADE_PASEO_URL", None)
    r = subprocess.run([str(CLI)], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "STUCK" in r.stdout and "codex agent in error: no Pi alternative" in r.stdout
    assert "switch to" not in r.stdout and "1 stuck (1 in error, any provider)" in r.stdout


def test_an_account_without_a_quota_mapping_is_reported(tmp_path: Path) -> None:
    """A bare `opencode-go/` provider names no billing sub-account: it cannot be judged, so it is not shown as healthy."""
    agents = [{"id": "o1", "provider": "pi/opencode-go/deepseek-v4-pro", "status": "running"}]
    report = _run(tmp_path, _pools(**{"opencode:go#t-e": (40.0, True, False)}), agents=agents)
    assert report["unmapped"] == ["opencode-go"]
    assert report["stuck"] == []


def test_the_listing_asks_for_background_workspaces(tmp_path: Path) -> None:
    """Without `--background` a Pi agent in a background workspace is invisible, and would never be flagged."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    seen = tmp_path / "paseo.args"
    (bin_dir / "paseo").write_text(NL.join(["#!/bin/sh", 'echo "$*" >> ' + str(seen), "echo '[]'"]) + NL)
    (bin_dir / "paseo").chmod(0o755)
    (bin_dir / "aiuse").write_text("#!/bin/sh\nexit 1\n")
    (bin_dir / "aiuse").chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", ADE_PASEO_TRANSPORT="cli")
    env.pop("ADE_PASEO_URL", None)
    r = subprocess.run([str(CLI), "--json"], env=env, capture_output=True, text=True)
    assert r.returncode == 0
    args = seen.read_text()
    assert "-g" in args.split() and "--background" in args.split()


def test_a_pool_with_no_usable_reading_is_fail_closed(tmp_path: Path) -> None:
    pools = {"fresh": True, "available": [{"pool_id": "anthropic:subscription", "headroom_percent": 80.0,
                                           "usable_now": None, "stale": False}]}
    report = _run(tmp_path, pools)
    assert "anthropic" in report["exhausted"]


def test_an_errored_non_pi_agent_is_stuck_but_a_healthy_one_is_not(tmp_path: Path) -> None:
    """A lead in a hard error is stuck on any provider, not just Pi. A healthy non-Pi agent is still ignored
    (Carried 104: the Forks and cfengine leads sat in error on Codex and nothing re-handed them)."""
    agents = [
        {"id": "e1", "name": "forks", "provider": "codex/gpt-6.1-sol", "status": "error"},
        {"id": "e2", "name": "healthy", "provider": "codex/gpt-6.1-sol", "status": "running"},
        {"id": "e3", "name": "closed", "provider": "claude/opus", "status": "closed"},
    ]
    report = _run(tmp_path, _pools(**{"openai:openai_api": (50.0, True, False)}), agents=agents)
    stuck = {o["id"] for o in report["all_pi"] if o["stuck"]}
    assert stuck == {"e1"}
    assert "e2" not in {o["id"] for o in report["all_pi"]}
    assert "e3" not in {o["id"] for o in report["all_pi"]}
    assert [o["alternative"] for o in report["stuck"]] == [None]            # never a Pi alternative for a Codex agent


def test_a_bare_pi_provider_is_not_a_pi_family_agent(tmp_path: Path) -> None:
    """Only `pi/<account>/<model>` is a Pi agent: a provider named just "pi" in error is stuck with no alternative and
    its family is not "pi" (so the scan never plans it)."""
    agents = [{"id": "b1", "provider": "pi", "status": "error"}]
    report = _run(tmp_path, _pools(**{"opencode:go": (90.0, True, False)}), agents=agents)
    assert _stuck_ids(report) == ["b1"]
    assert report["stuck"][0]["family"] == "unknown" and report["stuck"][0]["alternative"] is None



def test_a_sub_account_pool_maps_each_named_account_and_not_the_bare_prefix(tmp_path: Path) -> None:
    """clinepass and opencode-go bill several accounts under one pool_id. Each named account is judged on
    its own reading, so a funded sub-account is not reported unmapped (Carried 79)."""
    agents = [
        {"id": "c1", "name": "cline base", "provider": "pi/clinepass/cline-pass/deepseek-v4-pro", "status": "running"},
        {"id": "c2", "name": "cline te", "provider": "pi/clinepass-t-e/cline-pass/deepseek-v4-pro", "status": "running"},
        {"id": "g1", "name": "go base", "provider": "pi/opencode-go/deepseek-v4-pro", "status": "idle"},
        {"id": "g2", "name": "go te", "provider": "pi/opencode-go-t-e/deepseek-v4-pro", "status": "idle"},
    ]
    report = _run(tmp_path, _pools(**{
        "clinepass:default#djbclark": (6.0, True, False),
        "clinepass:default#t-e": (80.0, True, False),
        "opencode:go#djbclark": (40.0, True, False),
        "opencode:go#t-e": (4.0, True, False),
    }), agents=agents)
    # The bare `clinepass` and `opencode-go` providers name no sub-account, and aiuse reports this pool only
    # per named account, so the base provider stays unmapped while each named sub-account is judged.
    assert report["unmapped"] == ["clinepass", "opencode-go"]
    by_id = {a["id"]: a for a in report["all_pi"]}
    assert by_id["c2"]["account"] == "clinepass-t-e" and by_id["c2"]["headroom_percent"] == 80.0
    assert by_id["c1"]["headroom_percent"] is None
    assert by_id["g2"]["account"] == "opencode-go-t-e" and by_id["g2"]["headroom_percent"] == 4.0
    assert by_id["g1"]["headroom_percent"] is None
    assert by_id["c1"]["stuck"] is False and by_id["c2"]["stuck"] is False


def test_an_unlisted_pool_stays_unmapped(tmp_path: Path) -> None:
    """A provider aiuse has no pool for cannot be judged, and is still reported rather than assumed healthy."""
    agents = [{"id": "x1", "name": "xai", "provider": "pi/xai-oauth/grok-4.7", "status": "running"}]
    report = _run(tmp_path, _pools(**{"openai:openai_api": (50.0, True, False)}), agents=agents)
    assert report["unmapped"] == ["xai-oauth"]
    assert report["all_pi"][0]["headroom_percent"] is None


def _load_pi_stuck_module():
    """Import bin/ade-pi-stuck directly without mutating PATH (Code Review Rule 2)."""
    import importlib.machinery
    import importlib.util

    loader = importlib.machinery.SourceFileLoader("ade_pi_stuck_mod", str(CLI))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_venice_and_rfab_pools_map_without_becoming_auto_alternatives() -> None:
    """Operator-gated venice and rfab pools map for quota judgement and never become auto alt() targets."""
    mod = _load_pi_stuck_module()
    assert mod.account_of("venice/openai-gpt-62-sol") == "venice"
    assert mod.account_of("rfab/openai:gpt-6.2-sol") == "rfab"

    avail = _pools(**{
        "venice:default": (100.0, True, False),
        "rfab:default": (100.0, True, False),
        "openai:openai_api": (0.0, True, False),
    })
    accounts = mod.quota_by_account(avail)
    assert accounts["venice"] == {"headroom": 100.0, "usable": True, "stale": False, "pool": "venice:default"}
    assert accounts["rfab"] == {"headroom": 100.0, "usable": True, "stale": False, "pool": "rfab:default"}

    # Even with venice and rfab at 100% headroom, alt() must never recommend them.
    alt_choice = mod.alt("openai/gpt-6.1-sol", "openai", {"openai"}, accounts)
    assert alt_choice is None or (not alt_choice.startswith("pi/venice/") and not alt_choice.startswith("pi/rfab/"))


def test_venice_and_rfab_unusable_pool_marks_account_exhausted_without_path_mutation(monkeypatch) -> None:
    """In-process main() check with explicit monkeypatched seams (no PATH reordering)."""
    mod = _load_pi_stuck_module()
    agents = [
        {"id": "v1", "name": "venice tab", "provider": "pi/venice/openai-gpt-62-sol", "status": "idle"},
        {"id": "r1", "name": "rfab tab", "provider": "pi/rfab/openai:gpt-6.2-sol", "status": "idle"},
    ]
    avail = _pools(**{
        "venice:default": (100.0, True, False),
        "rfab:default": (0.0, False, False),
    })
    monkeypatch.setattr(mod, "list_agents_rows", lambda timeout=30: agents)
    monkeypatch.setattr(mod, "j", lambda cmd, timeout=30, ok=(0,): avail)
    monkeypatch.setattr(mod.sys, "argv", ["ade-pi-stuck", "--json"])

    import io
    buf = io.StringIO()
    monkeypatch.setattr(mod.sys, "stdout", buf)
    assert mod.main() == 0
    report = json.loads(buf.getvalue())
    assert report["unmapped"] == []
    assert "venice" in report["accounts"] and "venice" not in report["exhausted"]
    assert "rfab" in report["accounts"] and "rfab" in report["exhausted"]
    assert [s["id"] for s in report["stuck"]] == ["r1"]


def test_unavailable_array_marks_subaccount_exhausted_not_unmapped(monkeypatch) -> None:
    """aiuse schema 1.8 puts exhausted/near-empty pools in `unavailable` without `usable_now` (Carried 88)."""
    import io

    mod = _load_pi_stuck_module()
    agents = [
        {"id": "g1", "name": "go te", "provider": "pi/opencode-go-t-e/deepseek-v4-pro", "status": "idle"},
        {"id": "g2", "name": "go djb", "provider": "pi/opencode-go-djbclark/deepseek-v4-pro", "status": "idle"},
    ]
    avail = {
        "fresh": True,
        "available": [
            {"pool_id": "opencode:go", "account": "djbclark", "headroom_percent": 50.0, "usable_now": True, "stale": False},
        ],
        "unavailable": [
            {"pool_id": "opencode:go", "account": "t-e", "headroom_percent": 0.0, "reason": "exhausted"},
        ],
    }
    monkeypatch.setattr(mod, "list_agents_rows", lambda timeout=30: agents)
    monkeypatch.setattr(mod, "j", lambda cmd, timeout=30, ok=(0,): avail)
    monkeypatch.setattr(mod.sys, "argv", ["ade-pi-stuck", "--json"])
    buf = io.StringIO()
    monkeypatch.setattr(mod.sys, "stdout", buf)

    assert mod.main() == 0
    report = json.loads(buf.getvalue())
    assert report["unmapped"] == []
    assert "opencode-go-t-e" in report["exhausted"]
    assert report["accounts"]["opencode-go-t-e"]["usable"] is False
    assert report["accounts"]["opencode-go-t-e"]["headroom"] == 0.0
    assert "opencode-go-djbclark" not in report["exhausted"]
    assert [s["id"] for s in report["stuck"]] == ["g1"]
    assert report["stuck"][0]["alternative"] == "pi/opencode-go-djbclark/deepseek-v4-pro"


def test_unavailable_near_empty_and_worst_pool_precedence() -> None:
    """A near_empty `unavailable` row forces usable=False and beats an `available` row for the same account."""
    mod = _load_pi_stuck_module()
    avail = {
        "fresh": True,
        "available": [
            {"pool_id": "anthropic:subscription", "headroom_percent": 60.0, "usable_now": True, "stale": False},
        ],
        "unavailable": [
            {"pool_id": "anthropic:fable", "headroom_percent": 3.0, "reason": "near_empty"},
        ],
    }
    accounts = mod.quota_by_account(avail)
    assert accounts["anthropic"]["usable"] is False
    assert accounts["anthropic"]["headroom"] == 3.0
    assert accounts["anthropic"]["pool"] == "anthropic:fable"


def test_clinepass_subaccounts_map_individually_across_available_and_unavailable(monkeypatch) -> None:
    """Each clinepass sub-account maps to `clinepass-<account>` across available/unavailable and bare fallback (Carried 80)."""
    import io

    mod = _load_pi_stuck_module()
    assert mod.account_of("clinepass-djbclark/cline-pass/deepseek-v4-pro") == "clinepass-djbclark"
    assert mod.account_of("clinepass-t-e/cline-pass/deepseek-v4-pro") == "clinepass-t-e"
    assert mod.account_of("clinepass/cline-pass/deepseek-v4-pro") == "clinepass"

    # Account-less clinepass:default still vouches for bare `clinepass`.
    bare_accounts = mod.quota_by_account({
        "fresh": True,
        "available": [{"pool_id": "clinepass:default", "headroom_percent": 75.0, "usable_now": True, "stale": False}],
    })
    assert bare_accounts["clinepass"]["headroom"] == 75.0 and bare_accounts["clinepass"]["usable"] is True

    agents = [
        {"id": "cp1", "name": "cp djb", "provider": "pi/clinepass-djbclark/cline-pass/deepseek-v4-pro", "status": "running"},
        {"id": "cp2", "name": "cp te", "provider": "pi/clinepass-t-e/cline-pass/deepseek-v4-pro", "status": "idle"},
    ]
    avail = {
        "fresh": True,
        "available": [
            {"pool_id": "clinepass:default", "account": "djbclark", "headroom_percent": 50.0, "usable_now": True, "stale": False},
        ],
        "unavailable": [
            {"pool_id": "clinepass:default", "account": "t-e", "headroom_percent": 0.0, "reason": "exhausted"},
        ],
    }
    monkeypatch.setattr(mod, "list_agents_rows", lambda timeout=30: agents)
    monkeypatch.setattr(mod, "j", lambda cmd, timeout=30, ok=(0,): avail)
    monkeypatch.setattr(mod.sys, "argv", ["ade-pi-stuck", "--json"])
    buf = io.StringIO()
    monkeypatch.setattr(mod.sys, "stdout", buf)

    assert mod.main() == 0
    report = json.loads(buf.getvalue())
    assert report["unmapped"] == []
    assert "clinepass-djbclark" in report["accounts"] and "clinepass-djbclark" not in report["exhausted"]
    assert "clinepass-t-e" in report["exhausted"]
    assert [s["id"] for s in report["stuck"]] == ["cp2"]


def test_aiuse_timeout_falls_back_to_stale_snapshot_without_path_mutation(tmp_path: Path, monkeypatch) -> None:
    """When `aiuse --available --json` times out, fall back to latest.json marked stale (Carried 93)."""
    import io

    mod = _load_pi_stuck_module()
    snap = tmp_path / "latest.json"
    snap.write_text(json.dumps({
        "schema_version": "1.8",
        "accounts": [
            {"pool_id": "opencode:go", "account": "t-e", "usable_now": False, "binding_headroom_percent": 0.0},
            {"pool_id": "opencode:go", "account": "djbclark", "usable_now": True, "binding_headroom_percent": 50.0},
            {"pool_id": "clinepass:default", "account": "t-e", "usable_now": True, "binding_headroom_percent": 100.0},
            {"pool_id": "openai:openai_api", "account": "djbclark@gmail.com", "usable_now": True, "binding_headroom_percent": 28.8},
        ],
    }), encoding="utf-8")
    snap.chmod(0o600)

    agents = [
        {"id": "o1", "name": "openai", "provider": "pi/openai/gpt-6.1-sol", "status": "running"},
        {"id": "g1", "name": "go te", "provider": "pi/opencode-go-t-e/deepseek-v4-pro", "status": "idle"},
        {"id": "g2", "name": "go djb", "provider": "pi/opencode-go-djbclark/deepseek-v4-pro", "status": "idle"},
        {"id": "c1", "name": "cp te", "provider": "pi/clinepass-t-e/cline-pass/deepseek-v4-pro", "status": "idle"},
    ]

    def _timeout(cmd, timeout=30, ok=(0,)):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setenv("AIUSE_SNAPSHOT", str(snap))
    monkeypatch.setattr(mod, "list_agents_rows", lambda timeout=30: agents)
    monkeypatch.setattr(mod, "j", _timeout)
    monkeypatch.setattr(mod.sys, "argv", ["ade-pi-stuck", "--json"])
    out_buf, err_buf = io.StringIO(), io.StringIO()
    monkeypatch.setattr(mod.sys, "stdout", out_buf)
    monkeypatch.setattr(mod.sys, "stderr", err_buf)

    assert mod.main() == 0
    report = json.loads(out_buf.getvalue())
    assert report["quota_error"] is None
    assert report["quota_source"] == "snapshot-stale"
    assert report["unmapped"] == []
    assert "stale snapshot fallback" in err_buf.getvalue()
    assert all(rec["stale"] is True for rec in report["accounts"].values())
    # KNOWN_EMPTY (`openai`) stays fail-closed on a stale fallback even with 28.8% in the snapshot.
    assert "openai" in report["exhausted"]
    assert "opencode-go-t-e" in report["exhausted"]
    assert "opencode-go-djbclark" not in report["exhausted"]
    assert "clinepass-t-e" not in report["exhausted"]
    assert _stuck_ids(report) == ["g1", "o1"]


def test_aiuse_timeout_refuses_missing_symlink_world_writable_or_empty_snapshot(tmp_path: Path, monkeypatch) -> None:
    """Snapshot fallback fails closed to quota_error when the snapshot is missing, a symlink, world-writable, or empty."""
    import io

    mod = _load_pi_stuck_module()
    valid = tmp_path / "real.json"
    valid.write_text(json.dumps({
        "accounts": [{"pool_id": "opencode:go", "account": "djbclark", "usable_now": True, "binding_headroom_percent": 50.0}],
    }), encoding="utf-8")
    valid.chmod(0o600)

    sym = tmp_path / "link.json"
    sym.symlink_to(valid)

    ww = tmp_path / "world-writable.json"
    ww.write_text(valid.read_text(encoding="utf-8"), encoding="utf-8")
    ww.chmod(0o666)

    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"accounts": []}), encoding="utf-8")
    empty.chmod(0o600)

    def _timeout(cmd, timeout=30, ok=(0,)):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(mod, "list_agents_rows", lambda timeout=30: AGENTS)
    monkeypatch.setattr(mod, "j", _timeout)
    monkeypatch.setattr(mod.sys, "argv", ["ade-pi-stuck", "--json"])

    for bad_path in (tmp_path / "missing.json", sym, ww, empty):
        monkeypatch.setenv("AIUSE_SNAPSHOT", str(bad_path))
        buf = io.StringIO()
        monkeypatch.setattr(mod.sys, "stdout", buf)
        assert mod.main() == 0
        report = json.loads(buf.getvalue())
        assert report["quota_source"] == "error"
        assert report["quota_error"] and "timed out" in report["quota_error"]
        assert report["accounts"] == {}
        assert report["exhausted"] == ["openai"]


def test_non_timeout_aiuse_error_does_not_read_snapshot(tmp_path: Path, monkeypatch) -> None:
    """Only TimeoutExpired triggers snapshot fallback; a non-zero aiuse exit still reports quota_error."""
    import io

    mod = _load_pi_stuck_module()
    snap = tmp_path / "latest.json"
    snap.write_text(json.dumps({
        "accounts": [{"pool_id": "opencode:go", "account": "djbclark", "usable_now": True, "binding_headroom_percent": 50.0}],
    }), encoding="utf-8")
    snap.chmod(0o600)

    def _fail(cmd, timeout=30, ok=(0,)):
        raise RuntimeError("aiuse exited 1: broken config")

    monkeypatch.setenv("AIUSE_SNAPSHOT", str(snap))
    monkeypatch.setattr(mod, "list_agents_rows", lambda timeout=30: AGENTS)
    monkeypatch.setattr(mod, "j", _fail)
    monkeypatch.setattr(mod.sys, "argv", ["ade-pi-stuck", "--json"])
    buf = io.StringIO()
    monkeypatch.setattr(mod.sys, "stdout", buf)

    assert mod.main() == 0
    report = json.loads(buf.getvalue())
    assert report["quota_source"] == "error"
    assert "aiuse exited 1" in (report["quota_error"] or "")
    assert report["accounts"] == {}


def test_aiuse_timeout_env_validation(monkeypatch) -> None:
    mod = _load_pi_stuck_module()
    monkeypatch.delenv("ADE_PI_STUCK_AIUSE_TIMEOUT", raising=False)
    assert mod.aiuse_timeout() == 30.0
    monkeypatch.setenv("ADE_PI_STUCK_AIUSE_TIMEOUT", "45.5")
    assert mod.aiuse_timeout() == 45.5
    for bad in ("0", "-5", "nan", "inf", "999", "not-a-number"):
        monkeypatch.setenv("ADE_PI_STUCK_AIUSE_TIMEOUT", bad)
        assert mod.aiuse_timeout() == 30.0
