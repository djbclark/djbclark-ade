"""Pi defaults use existing quality/quota policy, not a second ranking engine."""
import io
import json
from pathlib import Path
import stat
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import pi_defaults as defaults
import route_agent as router


MODELS = ["zai/glm-5.3-flash", "cursor/composer-2.5"]


def reading(left):
    return {"remaining": left, "age_s": 0, "windows": {"weekly": left}}


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("ADE_PI_DEFAULTS_BLOCKS", str(tmp_path / "blocks.json"))
    monkeypatch.setattr(router, "AIUSE_CONFIG", tmp_path / "no-config.toml")
    monkeypatch.setattr(router, "paseo_providers", lambda: {"pi", "claude", "codex", "cursor"})
    monkeypatch.setattr(router, "kind_rows", lambda *_: [])


def select(quota, **kwargs):
    return defaults.choose("research", MODELS, quota=quota, age=0, **kwargs)


def test_capacity_changes_the_choice_without_changing_profiles():
    assert select({"cursor": reading(81), "zai": reading(19)})["model_id"] == "cursor/composer-2.5"
    result = select({"cursor": reading(2), "zai": reading(80)})
    assert (result["provider"], result["model"], result["thinking"]) == ("zai", "glm-5.3-flash", "high")


def test_native_tool_requirement_excludes_the_cursor_inner_loop():
    result = select({"cursor": reading(90), "zai": reading(80)}, native_tools=True)
    assert result["service"] == "zai"


def test_disabled_pi_transport_is_not_a_qualified_default(monkeypatch):
    monkeypatch.setattr(router, "paseo_providers", lambda: {"claude", "cursor"})
    assert select({"cursor": reading(90), "zai": reading(80)})["service"] is None


def test_missing_or_explicitly_excluded_model_cannot_be_selected():
    quota = {"cursor": reading(95), "zai": reading(80)}
    assert defaults.choose("research", [MODELS[0]], quota=quota)["service"] == "zai"
    assert select(quota, excluded={"cursor"})["service"] == "zai"
    assert defaults.choose("research", [], quota=quota)["service"] is None


@pytest.mark.parametrize("info", [
    {"remaining": 80},
    {"remaining": 80, "age_s": router.STALE_SOFT + 1},
    {"remaining": None, "age_s": 0},
    {"remaining": True, "age_s": 0},
    {"remaining": 80, "age_s": 0, "requires_operator_approval": True},
    {"remaining": 80, "age_s": 0, "windows": {"weekly": None}},
    reading(0), reading(5),
])
def test_unmeasured_stale_reserved_or_exhausted_capacity_fails_closed(info):
    assert defaults.choose("research", MODELS, quota={"cursor": info, "zai": info})["service"] is None


def test_quality_and_judgment_gates_are_not_bypassed_for_pi():
    quota = {"cursor": reading(100), "zai": reading(100), "claude": reading(100)}
    assert defaults.choose("judgment", MODELS, quota=quota)["service"] is None
    assert router.route("judgment", quota=quota).service.name == "claude"
    # clinepass is a Pi routing service for manual use; the retired transports are not.
    assert all(s.name not in {"omp", "opencode-go", "opencode-zen-free"}
               for s in router.SERVICES if s.acp_agent == "pi")


def test_mechanical_effort_differs_from_substantive_native_work():
    out = defaults.choose("mechanical", MODELS, quota={"zai": reading(90)}, native_tools=True)
    assert out["thinking"] == "low"


def test_physical_pools_remain_distinct():
    assert router.map_agent_to_provider("pi", "openai/gpt-6.1-sol") == ("pi", "codex_api")
    assert router.map_agent_to_provider("codex", "gpt-6.1-sol") == ("codex", "openai_api")
    assert router.map_agent_to_provider("codex", "gpt-6-luna") == ("codex", "default")
    assert router.map_agent_to_provider("pi", MODELS[0]) == ("zai", None)
    # Composer uses the explicit included family retained in routing policy;
    # provider-only or Grok Bot quota must never stand in for this family.
    assert router.map_agent_to_provider("pi", MODELS[1]) == ("cursor", "third_party")
    assert router.pool_service(*router.map_agent_to_provider("pi", MODELS[1])) == "cursor"
    assert router.pool_service("cursor", "grok_bot") is None
    assert router.map_agent_to_provider("pi", "ade/auto") is None


def test_confirmed_failure_latch_survives_fresh_positive_quota_until_cleared():
    quota = {"cursor": reading(90), "zai": reading(80)}
    defaults.update_block("cursor", "quota")
    assert select(quota)["service"] == "zai"
    assert "cursor-cloud" in router.operator_disabled()
    defaults.update_block("zai", "billing")
    assert select(quota)["service"] is None
    defaults.update_block("cursor", None)
    assert select(quota)["service"] == "cursor"
    assert router.pi_blocked_services() == {"zai"}
    p = router.pi_block_state_path()
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    data = json.loads(p.read_text())
    assert set(data["blocked"]["zai"]) == {"reason", "at"}


def test_damaged_block_state_holds_pi_and_is_not_overwritten():
    p = router.pi_block_state_path()
    p.write_text("damaged")
    assert select({"cursor": reading(90), "zai": reading(80)})["service"] is None
    with pytest.raises(ValueError):
        defaults.update_block("cursor", "quota")
    assert p.read_text() == "damaged"


def test_failure_mode_accepts_only_declared_pi_pools():
    with pytest.raises(ValueError):
        defaults.update_block("codex", "quota")
    assert not router.pi_block_state_path().exists()


def test_cli_selection_and_failure_operations_are_separate(monkeypatch, capsys):
    monkeypatch.setattr(router, "load_snapshot", lambda **_: ({"zai": reading(80)}, 0))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(MODELS)))
    assert defaults.main(["--models-json", "-", "--native-tools", "--kind", "research"]) == 0
    assert json.loads(capsys.readouterr().out)["model_id"] == MODELS[0]
    assert defaults.main(["--block-service", "zai", "--reason", "billing"]) == 0
    assert json.loads(capsys.readouterr().out)["blocked"] is True
    assert defaults.main(["--clear-block", "zai"]) == 0
    assert json.loads(capsys.readouterr().out)["blocked"] is False


def test_latched_choice_can_check_another_sessions_failure_without_quota_probe(monkeypatch, capsys):
    def unexpected(**kwargs):
        raise AssertionError("latch checks must not refresh quotas")
    monkeypatch.setattr(router, "load_snapshot", unexpected)
    assert defaults.main(["--check-service", "cursor"]) == 0
    assert json.loads(capsys.readouterr().out)["blocked"] is False
    assert not router.pi_block_state_path().exists()
    defaults.update_block("cursor", "quota")
    assert defaults.main(["--check-service", "cursor"]) == 0
    assert json.loads(capsys.readouterr().out)["blocked"] is True


def test_invalid_model_input_has_fixed_nonsecret_diagnostic(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO('"DO_NOT_ECHO_THIS"'))
    assert defaults.main(["--models-json", "-"]) == 2
    out = capsys.readouterr().out
    assert "DO_NOT_ECHO_THIS" not in out
    assert json.loads(out)["service"] is None


def test_new_profile_does_not_change_hermes_models():
    assert not any(x["provider"] == "zai" for x in router.hermes_chain({"zai": reading(95)}))

@pytest.mark.parametrize("service,model,thinking", [
    ("zai", "zai/glm-5.3-flash --effort high", "high"),
    ("cursor", "cursor/composer-2.5", None),
])
def test_pi_dispatch_is_a_native_paseo_launch(service, model, thinking):
    import shlex
    choice = router.Choice(router.BY_NAME[service], 80, 1, model=model, kind="code")
    expected = ["paseo", "run", "--provider", "pi/" + model.split()[0]]
    if thinking:
        expected += ["--thinking", thinking]
    expected += ["--label", "ade.kind=code", "--no-wait"]
    assert shlex.split(choice.dispatch) == expected


def test_no_pi_pool_resolves_to_an_antigravity_model():
    """Operator 2026-11-21: antigravity work goes only through Paseo's native `antigravity` provider, never Pi."""
    models = [*MODELS, "antigravity/gemini-4-neon", "antigravity/gemini-4-argon"]
    quota = {"cursor": reading(90), "zai": reading(80), "antigravity-neon": reading(99), "antigravity-argon": reading(99)}
    for kind in router.KINDS:
        out = defaults.choose(kind, models, quota=quota, age=0)
        assert not str(out.get("model_id") or "").startswith("antigravity/"), (kind, out)
        assert out.get("service") not in {"antigravity-neon", "antigravity-argon"}, (kind, out)
    for svc in router.SERVICES:
        if svc.acp_agent == "pi":
            for model in svc.models.values():
                assert not router.pi_excluded(model.split()[0]), (svc.name, model)      # the one case-insensitive check
    # the native provider rows are the antigravity pools
    assert {s.name for s in router.SERVICES if s.acp_agent == "antigravity"} == {"antigravity-argon", "antigravity-neon"}


def test_pi_defaults_skips_a_pool_whose_model_is_antigravity_even_when_pi_lists_it(monkeypatch):
    """PR 881 r3 LOW-1: the defensive skip in choose() is exercised, not only the config side. Case does not matter (LOW-2)."""
    zai = next(s for s in router.SERVICES if s.name == "zai")
    for spelled in ("antigravity/gemini-4-neon", "Antigravity/gemini-4-neon"):
        monkeypatch.setitem(zai.models, "research", spelled)
        quota = {"cursor": reading(10), "zai": reading(90)}
        out = defaults.choose("research", [*MODELS, spelled], quota=quota, age=0)
        assert out.get("service") != "zai", out
        assert not str(out.get("model_id") or "").lower().startswith("antigravity/"), out


def test_excluded_namespaces_match_case_insensitively():
    assert router.pi_excluded("antigravity/gemini-4-neon")
    assert router.pi_excluded("Antigravity/x") and router.pi_excluded("ANTIGRAVITY/x --effort high")
    assert not router.pi_excluded("cursor/composer-2.5") and not router.pi_excluded("antigravity-like/x")
    assert router._without_antigravity(["Antigravity/x", "zai/glm-5.3-flash"]) == ["zai/glm-5.3-flash"]
