"""Model-family resolution (bin/model_family.py, route_agent integration; operator 2026-11-21: newest version always)."""
from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

import model_family as mf  # noqa: E402
import route_agent as r  # noqa: E402

AGY = {"antigravity": ["gemini-4-neon-high", "gemini-4-argon-high"]}
CODEX = ["gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol", "gpt-6.2-sol", "gpt-6.2-astra", "gpt-6.1-terra", "gpt-5.6-sol",
         "gpt-6-luna"]


class TestVersionOrdering:
    def test_newer_minor_wins_not_lexical(self):
        assert mf.newest("gpt-*-sol", ["gpt-6-sol", "gpt-6.1-sol", "gpt-6.2-sol"]) == "gpt-6.2-sol"
        assert mf.newest("gpt-*-astra", ["gpt-6-astra", "gpt-6.2-astra"]) == "gpt-6.2-astra"

    def test_two_digit_minor_beats_one_digit(self):
        assert mf.newest("gpt-*-sol", ["gpt-6.9-sol", "gpt-6.10-sol"]) == "gpt-6.10-sol"

    def test_major_beats_minor_and_bare_beats_older_major(self):
        assert mf.newest("gemini-*-flash", ["gemini-3.8-flash", "gemini-4-flash"]) == "gemini-4-flash"
        assert mf.newest("gpt-*-sol", ["gpt-5.6-sol", "gpt-6-sol"]) == "gpt-6-sol"

    def test_bare_major_is_older_than_its_minor(self):
        assert mf.version_key(("6",)) < mf.version_key(("6.1",)) < mf.version_key(("6.2",))

    def test_family_does_not_match_other_families_or_suffixes(self):
        assert mf.newest("gpt-*-sol", CODEX) == "gpt-6.2-sol"
        assert mf.newest("gpt-*-sol", ["gpt-6.1-terra", "gpt-6.2-sol-mini"]) is None
        ids = ["gemini-4-neon-high", "gemini-4-neon-xhigh", "gemini-pro-orchestrator-neon"]
        assert mf.newest("gemini-*-neon-high", ids) == "gemini-4-neon-high"

    def test_literal_is_not_a_family(self):
        assert not mf.is_family("gpt-6-astra")
        assert mf.resolve("gpt-6-astra", ["gpt-6.2-astra"]) == mf.Resolution("gpt-6-astra", "gpt-6-astra", "literal")

    def test_tie_is_deterministic(self):
        assert mf.newest("gpt-*-sol", ["gpt-6-sol", "gpt-06-sol"]) == "gpt-6-sol"


class TestResolve:
    def test_catalog_newest(self):
        res = mf.resolve("gpt-*-astra", CODEX)
        assert (res.model, res.source, res.newest) == ("gpt-6.2-astra", "catalog", "gpt-6.2-astra")

    def test_hold_honoured_until_its_last_day(self):
        hold = mf.Hold("gpt-6.1-sol", date(2026, 12, 1), "regression in 6.2")
        for today in (date(2026, 11, 21), date(2026, 12, 1)):
            res = mf.resolve("gpt-*-sol", CODEX, holds={"gpt-*-sol": hold}, today=today)
            assert (res.model, res.source, res.newest) == ("gpt-6.1-sol", "hold", "gpt-6.2-sol")
            assert "until 2026-12-01" in res.note
            assert "regression in 6.2" in res.note
            assert "newest catalog id is gpt-6.2-sol" in res.note

    def test_hold_expired_returns_newest_and_says_so(self):
        hold = mf.Hold("gpt-6.1-sol", date(2026, 12, 1))
        res = mf.resolve("gpt-*-sol", CODEX, holds={"gpt-*-sol": hold}, today=date(2026, 12, 2))
        assert (res.model, res.source) == ("gpt-6.2-sol", "catalog")
        assert "expired 2026-12-01" in res.note

    def test_hold_for_another_family_is_ignored(self):
        hold = mf.Hold("gpt-6.1-sol", date(2999, 1, 1))
        assert mf.resolve("gpt-*-astra", CODEX, holds={"gpt-*-sol": hold}).model == "gpt-6.2-astra"

    def test_catalog_missing_falls_back_to_state(self):
        res = mf.resolve("gpt-*-astra", None, last="gpt-6.2-astra")
        assert (res.model, res.source) == ("gpt-6.2-astra", "state")
        assert "catalog unreadable" in res.note
        assert "last resolved id gpt-6.2-astra from state" in res.note

    def test_no_match_falls_back_to_state(self):
        res = mf.resolve("gpt-*-astra", ["gpt-6-luna"], last="gpt-6-astra")
        assert (res.model, res.source) == ("gpt-6-astra", "state")
        assert "no catalog id matches" in res.note

    def test_catalog_missing_and_no_state_is_unresolved(self):
        res = mf.resolve("gpt-*-astra", None)
        assert (res.model, res.source, res.resolved) == ("gpt-*-astra", "unresolved", False)
        assert "no id recorded in state" in res.note

    def test_a_hold_applies_even_with_the_catalog_unreadable(self):
        hold = mf.Hold("gpt-6.1-sol", date(2999, 1, 1))
        res = mf.resolve("gpt-*-sol", None, holds={"gpt-*-sol": hold})
        assert (res.model, res.source) == ("gpt-6.1-sol", "hold")


class TestHoldParsing:
    def test_parse(self):
        holds = mf.parse_holds({"gpt-*-sol": {"model": "gpt-6.1-sol", "until": "2026-12-01", "reason": "why"}})
        assert holds == {"gpt-*-sol": mf.Hold("gpt-6.1-sol", date(2026, 12, 1), "why")}

    def test_toml_date_value(self):
        assert mf.parse_holds({"f-*": {"model": "f-1", "until": date(2026, 1, 2)}})["f-*"].until == date(2026, 1, 2)

    @pytest.mark.parametrize("row", [{"until": "2026-12-01"}, {"model": "x"}, {"model": "x", "until": "soon"}, "x"])
    def test_malformed_rows_are_refused(self, row):
        with pytest.raises(ValueError, match="gpt-"):
            mf.parse_holds({"gpt-*-sol": row})

    def test_empty_is_no_hold(self):
        assert mf.parse_holds(None) == {} == mf.parse_holds({})


class TestState:
    def test_first_sighting_is_not_a_change_then_a_newer_id_is(self, tmp_path):
        path = tmp_path / "state.json"
        t0 = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)
        assert mf.record("codex", "gpt-*-astra", "gpt-6-astra", now=t0, path=path) is False
        assert mf.record("codex", "gpt-*-astra", "gpt-6-astra", now=t0, path=path) is False
        assert mf.record("codex", "gpt-*-astra", "gpt-6.2-astra", now=t0, path=path) is True
        row = mf.load_state(path)["codex:gpt-*-astra"]
        assert (row["id"], row["previous"], row["changed_at"]) == ("gpt-6.2-astra", "gpt-6-astra", "2026-11-21T12:00:00Z")
        assert mf.last_id("codex", "gpt-*-astra", path) == "gpt-6.2-astra"

    def test_unreadable_or_garbage_state_reads_empty(self, tmp_path):
        assert mf.load_state(tmp_path / "missing.json") == {}
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        assert mf.load_state(bad) == {}

    def test_unwritable_state_directory_is_ignored(self, tmp_path):
        blocker = tmp_path / "file"
        blocker.write_text("x")
        assert mf.record("codex", "f-*", "f-1", path=blocker / "state.json") is False


# --- route_agent integration ------------------------------------------------------------------------------------------

@pytest.fixture
def catalog(tmp_path, monkeypatch):
    """Point route_agent at a per-test catalog and state file; returns a setter for the catalog."""
    path = tmp_path / "catalog.json"
    monkeypatch.setenv("ROUTE_AGENT_MODEL_CATALOG_JSON", str(path))
    monkeypatch.setenv("ROUTE_AGENT_MODEL_STATE", str(tmp_path / "state.json"))

    def put(data):
        path.write_text(json.dumps(data))
        r.MODEL_RESOLUTIONS.clear()

    r.reload_policy()           # config/ade.toml: earlier tests may leave the legacy fixture policy loaded
    r.MODEL_RESOLUTIONS.clear()
    yield put
    r.MODEL_RESOLUTIONS.clear()


def svc(name):
    return r.BY_NAME[name]


class TestRouteAgentResolution:
    def test_roster_families_resolve_to_the_newest_catalog_id(self, catalog):
        catalog({"codex": CODEX, "antigravity": ["gemini-4-neon-high", "gemini-4-argon-high"]})
        assert r.suggest_model(svc("codex"), "frontier", {}) == "gpt-6.2-astra --effort high"
        assert r.suggest_model(svc("codex"), "judgment", {}) == "gpt-6.2-sol --effort high"
        assert r.suggest_model(svc("codex"), "code", {}) == "gpt-6.2-sol --effort medium"
        assert r.suggest_model(svc("codex-subscription"), "bulk", {}) == "gpt-6-luna --effort low"
        assert r.suggest_model(svc("antigravity-neon"), "frontier", {}) == "gemini-4-neon-high"

    def test_a_release_during_a_wave_needs_no_config_edit(self, catalog):
        catalog({"codex": ["gpt-6-astra", "gpt-6.1-sol"]})
        assert r.suggest_model(svc("codex"), "frontier", {}).startswith("gpt-6-astra ")
        catalog({"codex": ["gpt-6-astra", "gpt-6.2-astra", "gpt-6.1-sol"]})
        assert r.suggest_model(svc("codex"), "frontier", {}).startswith("gpt-6.2-astra ")

    def test_literal_ids_pass_through(self, catalog):
        catalog({"codex": CODEX})
        assert r.suggest_model(svc("zai"), "mechanical", {}) == "zai/glm-5.3-flash --effort low"
        assert r.suggest_model(svc("claude"), "judgment", {}) == "opus --effort high"

    def test_dispatch_line_carries_the_resolved_id(self, catalog):
        catalog({"codex": CODEX})
        c = r.Choice(svc("codex"), 50.0, 0.0, model=r.suggest_model(svc("codex"), "frontier", {}), kind="frontier")
        assert "--provider codex/gpt-6.2-astra --thinking high" in c.dispatch

    def test_catalog_missing_uses_state_and_the_note_says_so(self, catalog, tmp_path):
        catalog({"codex": CODEX})
        assert r.suggest_model(svc("codex"), "frontier", {}).startswith("gpt-6.2-astra")
        catalog({})                                           # the provider key is gone: the catalog cannot say
        assert r.suggest_model(svc("codex"), "frontier", {}).startswith("gpt-6.2-astra")
        note = r.model_note(svc("codex"), "frontier")
        assert "catalog unreadable" in note and "from state" in note

    def test_unresolved_family_is_a_dispatch_warning(self, catalog):
        catalog({})
        model = r.suggest_model(svc("codex"), "frontier", {})
        assert model.startswith("gpt-*-astra")
        c = r.Choice(svc("codex"), 50.0, 0.0, model=model, kind="frontier",
                     placement=r.Placement(lead="cad27907-8a41-4216-bd80-7851fb86aca6", slice="s", cwd="/tmp/x"))
        assert any("did not resolve" in w for w in c.dispatch_warnings)

    def test_hold_in_policy_is_honoured_then_expires(self, catalog, monkeypatch):
        catalog({"codex": CODEX})
        routing = dict(r.POLICY["routing"])
        monkeypatch.setitem(r.POLICY, "routing", routing)
        routing["model_holds"] = {"gpt-*-sol": {"model": "gpt-6.1-sol", "until": "2999-01-01", "reason": "test"}}
        assert r.suggest_model(svc("codex"), "judgment", {}) == "gpt-6.1-sol --effort high"
        assert "held at gpt-6.1-sol" in r.model_note(svc("codex"), "judgment")
        r.MODEL_RESOLUTIONS.clear()
        routing["model_holds"] = {"gpt-*-sol": {"model": "gpt-6.1-sol", "until": "2000-01-01", "reason": "test"}}
        assert r.suggest_model(svc("codex"), "judgment", {}) == "gpt-6.2-sol --effort high"
        assert "expired 2000-01-01" in r.model_note(svc("codex"), "judgment")

    def test_models_command_reports_a_changed_family(self, catalog, capsys):
        catalog({"codex": ["gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna"], "cursor": ["grok-4.7"], **AGY})
        assert r.main(["models"]) == 0
        assert "CHANGED" not in capsys.readouterr().out
        catalog({"codex": ["gpt-6-astra", "gpt-6.2-astra", "gpt-6.1-sol", "gpt-6-luna"], "cursor": ["grok-4.7"], **AGY})
        assert r.main(["models"]) == 0
        out = capsys.readouterr().out
        assert "gpt-*-astra" in out and "gpt-6.2-astra" in out
        assert "CHANGED from gpt-6-astra" in out

    def test_models_json_and_unresolved_exit(self, catalog, capsys):
        catalog({})
        assert r.main(["models", "--json"]) == 1
        fams = {f["family"]: f for f in json.loads(capsys.readouterr().out)["families"]}
        assert fams["gpt-*-astra"]["source"] == "unresolved"

    def test_frontier_token_family_matches_a_newer_release(self, catalog):
        assert r.is_frontier_model("gpt-6.2-astra")
        assert r.is_frontier_model("gpt-6-astra")
        assert not r.is_frontier_model("gpt-6.2-sol")
        assert r.is_frontier_model("gemini-4-argon-high")
    def test_a_newer_frontier_family_token_does_not_match_a_variant_line(self, catalog):
        assert not r.is_frontier_model("gpt-7-mini-astra")


# --- repair round 1 (adversary 2026-11-21): version-only wildcards, adjust vs Neon, state lock ------------------------------

class TestWildcardIsVersionOnly:
    """MED-2: a `*` stands for a version, so a different line of the family never wins as 'newest'."""

    def test_sol_ignores_mini_lite_flash_and_preview_lines(self):
        ids = ["gpt-6.1-sol", "gpt-7-mini-sol", "gpt-9-lite-sol", "gpt-8-flash-sol", "gpt-9-preview-sol"]
        assert mf.newest("gpt-*-sol", ids) == "gpt-6.1-sol"

    def test_neon_ignores_variant_lines_and_dates(self):
        ids = ["gemini-4-neon-high", "gemini-4.5-flash-lite-neon-high", "gemini-5-preview-neon-high",
               "gemini-20261121-neon-high", "gemini-4-neon-high-preview"]
        assert mf.newest("gemini-*-neon-high", ids) == "gemini-4-neon-high"

    def test_a_variant_alone_is_no_match_so_state_is_used(self):
        res = mf.resolve("gpt-*-sol", ["gpt-7-mini-sol"], last="gpt-6.1-sol")
        assert (res.source, res.model) == ("state", "gpt-6.1-sol")

    def test_real_versions_still_order_numerically(self):
        ids = ["gpt-6.9-sol", "gpt-6.10-sol", "gpt-7-mini-sol"]
        assert mf.newest("gpt-*-sol", ids) == "gpt-6.10-sol"
        assert mf.newest("gpt-*-sol", [*ids, "gpt-7-sol"]) == "gpt-7-sol"

    def test_question_mark_is_one_digit(self):
        assert mf.newest("gpt-?-sol", ["gpt-6-sol", "gpt-x-sol", "gpt-7-sol", "gpt-6.2-sol"]) == "gpt-7-sol"

    def test_family_ids_in_the_roster_resolve_the_same_way(self, catalog):
        catalog({"codex": [*CODEX, "gpt-7-mini-sol", "gpt-8-mini-astra"]})
        assert r.suggest_model(svc("codex"), "judgment", {}).startswith("gpt-6.2-sol")
        assert r.suggest_model(svc("codex"), "frontier", {}).startswith("gpt-6.2-astra")


class TestAdjustAcceptsAServiceOwnFrontierModel:
    """MED-1: Neon is frontier r3 (ruling 2026-11-21) but not a `[dispatch].frontier_models` token; adjust must not refuse it."""

    CFG = {"never_target": ["omp"]}

    def refusal(self, name, model):
        import route_adjust as ra
        choice = r.Choice(svc(name), 50.0, 0.0, model=model, kind="frontier")
        return ra._refusal(r, "frontier", choice, self.CFG)

    def test_neon_frontier_slice_is_not_refused(self, catalog):
        catalog(AGY)
        assert self.refusal("antigravity-neon", "gemini-4-neon-high --effort high") is None
        assert self.refusal("antigravity-neon", "gemini-5-neon-high") is None          # a newer release, still its own model

    def test_other_frontier_models_still_pass(self, catalog):
        catalog({"codex": CODEX})
        assert self.refusal("codex", "gpt-6.2-astra --effort high") is None
        assert self.refusal("antigravity-argon", "gemini-4-argon-high") is None

    def test_a_cheaper_model_on_a_frontier_ranked_pool_is_still_refused(self, catalog):
        catalog({"codex": CODEX})
        assert "cheaper tier" in (self.refusal("codex", "gpt-6.2-sol --effort high") or "")
        assert "cheaper tier" in (self.refusal("claude", "opus --effort high") or "")
        assert "cheaper tier" in (self.refusal("antigravity-neon", "gemini-4-flash-high") or "")

    def test_a_pool_that_does_not_rank_frontier_is_refused_even_on_its_own_model(self, catalog):
        assert "frontier" not in svc("zai").good_at
        assert "cheaper tier" in (self.refusal("zai", svc("zai").models.get("research", "glm-5").split()[0]) or "")

    def test_is_frontier_slice_model(self, catalog):
        assert r.is_frontier_slice_model("gemini-4.1-neon-high --effort high")
        assert r.is_frontier_slice_model("gpt-6.2-astra")
        assert not r.is_frontier_slice_model("gemini-4-flash-high")
        assert not r.is_frontier_slice_model("gemini-4.5-flash-lite-neon-high")
        assert not r.is_frontier_slice_model("")

    def test_neon_is_not_a_frontier_model_for_floors_and_gates(self, catalog):
        """Putting it in `frontier_models` would floor and gate every Neon judgment/code slice as a frontier one."""
        assert not r.is_frontier_model("gemini-4-neon-high")
        assert r.is_frontier_model("gemini-4-argon-high")


class TestLowRepairs:
    def test_provider_map_follows_the_version(self):
        for model, want in (("gemini-4-argon-high", "gemini_argon"), ("gemini-5-argon-high", "gemini_argon"),
                            ("gemini-4.1-neon-high", "gemini"), ("gemini-5-neon-high", "gemini")):
            assert r.map_agent_to_provider("antigravity", model) == ("antigravity", want), model
        assert r.map_agent_to_provider("antigravity", "gemini-5-flash-high") is None

    def test_unresolved_family_warns_on_a_placement_less_route_too(self, catalog):
        catalog({})
        model = r.suggest_model(svc("codex"), "frontier", {})
        c = r.Choice(svc("codex"), 50.0, 0.0, model=model, kind="frontier")      # `route`: no placement
        warns = c.dispatch_warnings
        assert any("did not resolve" in w for w in warns)
        assert any("no placement" in w for w in warns)

    def test_resolved_family_adds_no_family_warning(self, catalog):
        catalog({"codex": CODEX})
        model = r.suggest_model(svc("codex"), "frontier", {})
        c = r.Choice(svc("codex"), 50.0, 0.0, model=model, kind="frontier")
        assert not any("did not resolve" in w for w in c.dispatch_warnings)


class TestStateLock:
    def test_record_waits_for_the_lock_then_keeps_both_rows(self, tmp_path):
        import threading
        import time
        path = tmp_path / "state.json"
        assert mf.record("codex", "a-*", "a-1", path=path) is False
        done = threading.Event()
        result: list[bool] = []

        def other():
            result.append(mf.record("codex", "b-*", "b-1", path=path))
            done.set()

        with mf._locked(path):
            t = threading.Thread(target=other)
            t.start()
            assert not done.wait(0.4), "record() wrote while another writer held the state lock"
        assert done.wait(5)
        t.join()
        assert result == [False]
        assert set(mf.load_state(path)) == {"codex:a-*", "codex:b-*"}

    def test_many_writers_lose_no_family(self, tmp_path):
        import threading
        path = tmp_path / "state.json"
        fams = [f"f{i}-*" for i in range(24)]
        threads = [threading.Thread(target=mf.record, args=("p", f, f"{f[:-1]}1"), kwargs={"path": path}) for f in fams]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert set(mf.load_state(path)) == {f"p:{f}" for f in fams}

    def test_failed_write_leaves_no_temp_file(self, tmp_path, monkeypatch):
        path = tmp_path / "state.json"

        def boom(*_a, **_k):
            raise OSError("disk full")

        monkeypatch.setattr(mf.os, "replace", boom)
        assert mf.record("p", "f-*", "f-1", path=path) is False
        assert [p.name for p in tmp_path.iterdir() if p.name != "state.json.lock"] == []


class TestUnresolvedFamilyStaysFrontier:
    """PR 881 r2 LOW-1: with no catalog and no state the family string stays in the line; it keeps its frontier floor/refusal."""

    def test_unresolved_family_string_is_still_frontier(self, catalog):
        assert r.is_frontier_model("gpt-*-astra --effort high")
        assert r.is_frontier_model("gemini-*-argon-high")
        assert not r.is_frontier_model("gpt-*-sol --effort high")
        assert not r.is_frontier_model("gemini-*-neon-high")

    def test_unresolved_neon_and_astra_slices_are_not_refused_by_adjust(self, catalog):
        import route_adjust as ra
        catalog({})
        for name, model in (("antigravity-neon", "gemini-*-neon-high"), ("codex", "gpt-*-astra --effort high")):
            choice = r.Choice(svc(name), 50.0, 0.0, model=model, kind="frontier")
            assert ra._refusal(r, "frontier", choice, {"never_target": ["omp"]}) is None, name

    def test_frontier_floor_survives_an_unresolved_family(self, catalog):
        frontier = r.is_frontier_model("gpt-*-astra")
        assert r.floor_lookup({"codex": 10.0, "codex:frontier": 60.0}, "codex", "frontier", frontier) == 60.0


class TestNoPiToAntigravityInstruction:
    """PR 881 r2 MED-1: no instruction tells an agent to switch a Pi agent onto an antigravity/* model."""

    ROOT = Path(__file__).resolve().parent.parent

    def test_model_routing_skill_names_no_antigravity_pi_switch_target(self):
        text = (self.ROOT / "skills" / "model-routing" / "SKILL.md").read_text()
        e1b = text[text.index("E1b."):text.index("E1c.")]
        assert "never an `antigravity/*` model" in e1b
        # every `antigravity/` left in E1b is the prohibition or the new-native-agent route, never a switch target
        rest = e1b.replace("never an `antigravity/*` model", "").replace("--provider antigravity/<newest gemini family id>", "")
        assert "antigravity/" not in rest, rest


class TestCursorGrokRoute:
    """Operator 2026-11-21 (skills/research 1b): the newest Grok on Cursor's native provider, as a family, never pinned."""

    CURSOR = ["default", "grok-4.5", "grok-4.7", "grok-4.6", "grok-4.7-fast", "composer-2.5", "kimi-k3"]

    def test_the_newest_grok_resolves_from_the_native_cursor_catalog(self, catalog):
        catalog({"cursor": self.CURSOR})
        for kind in ("research", "frontier"):
            assert r.suggest_model(svc("cursor-grok"), kind, {}) == "grok-4.7", kind
        catalog({"cursor": [*self.CURSOR, "grok-4.10", "grok-5"]})
        assert r.suggest_model(svc("cursor-grok"), "research", {}) == "grok-5"          # no config edit for a release

    def test_no_grok_listed_is_unresolved_not_invented(self, catalog):
        catalog({"cursor": ["default", "composer-2.5"]})
        res = r.resolve_family("cursor", "grok-*")
        assert res.source == "unresolved" and res.model == "grok-*"

    def test_the_service_is_the_cursor_third_party_pool_not_grok_bot(self, catalog):
        s = svc("cursor-grok")
        assert (s.acp_agent, s.pool, s.shares_pool) == ("cursor", None, "cursor")
        assert set(s.good_at) == {"frontier", "research"}
        assert not s.retired and s.max_parallel == 1
        assert r.map_agent_to_provider("cursor", "grok-4.7") == ("cursor", "third_party")
        for name in ("grok", "grok-bot"):
            assert name not in r.BY_NAME
            assert name in r.POLICY["routing"]["never_route"]

    def test_it_is_a_frontier_slice_model_but_not_a_frontier_model(self, catalog):
        assert r.is_frontier_slice_model("grok-4.7")
        assert not r.is_frontier_model("grok-4.7")           # no frontier floor/gate on it, like Neon
        assert not r.is_frontier_slice_model("grok-code-fast-1x-mini")

    def test_slice_tokens_match_the_whole_model_id(self, catalog):
        """Adversary PR 899 LOW-2: `grok-*` must not make a fast or mini Grok, or a namespaced one, a frontier-slice model."""
        for model in ("grok-4.7", "grok-4.10", "grok-5 --effort high", "grok-*", "GROK-4.7", "Gemini-4-Neon-High"):    # the id family, the unresolved glob, any case
            assert r.is_frontier_slice_model(model), model
        for model in ("grok-4.7-fast", "grok-3-mini", "cursor/grok-4", "xgrok-4", "grok-4-mini --effort high", "grok-bot"):
            assert not r.is_frontier_slice_model(model), model
        for model in ("gemini-4-neon-high", "gemini-4.1-neon-high --effort high", "gemini-*-neon-high"):
            assert r.is_frontier_slice_model(model), model
        for model in ("gemini-4-neon-xhigh", "gemini-4-neon", "antigravity/gemini-4-neon-high"):
            assert not r.is_frontier_slice_model(model), model

    def test_an_underspent_cursor_pool_does_not_lift_grok_to_the_first_frontier_pick(self, catalog):
        """Adversary PR 899 MED-1: the burn-first bonus (4.0) used to put cursor-grok (r4) ahead of Astra/Fable r1/r2 on a month of
        unspent Cursor quota; a frontier slice is not spent to burn quota on a pool outside `frontier_models`."""
        from datetime import UTC, datetime, timedelta
        catalog({"cursor": self.CURSOR, "codex": CODEX})
        resets = (datetime.now(UTC) + timedelta(days=20)).isoformat()
        month = 30 * 24 * 60
        q = {s.name: {"remaining": 70.0, "age_s": 0, "windows": {"weekly": 70.0}} for s in r.SERVICES}
        q["cursor-grok"] = {"remaining": 85.0, "age_s": 0, "windows": {"monthly": 85.0}, "pace_ratio": 0.3,
                            "resets_at": resets, "window_minutes": month}
        assert r.expected_waste(85.0, 0.3, resets, month) >= r.BURN_FIRST_WASTE_MIN       # the bonus WOULD have applied
        got = r.route("frontier", quota=q)
        assert got is not None and got.service.name in {"codex", "claude"}, got and got.service.name
        # still reachable by rank when the better frontier pools have no room
        for name in ("codex", "claude"):
            q[name] = {"remaining": 0.0, "age_s": 0, "windows": {"weekly": 0.0}}
        assert r.route("frontier", quota=q).service.name == "antigravity-neon"       # r3 before r4 before the Argon fallback r5

    def test_a_hot_astra_pool_still_beats_a_slice_only_frontier_pool(self, catalog):
        """Adversary PR 899 r2 MED-1: the pace penalty (3.0 on frontier) must not carry a frontier slice across the tier line to
        Neon (r3) or cursor-grok (r4) while a `frontier_models` pool has room."""
        catalog({"cursor": self.CURSOR, "codex": CODEX, **AGY})

        def reading(pct, pace=None):
            d = {"remaining": pct, "age_s": 0, "windows": {"weekly": pct}}
            if pace is not None:
                d["pace_ratio"] = pace
            return d
        q = {s.name: reading(0.0) for s in r.SERVICES}
        q.update({"codex": reading(70.0, 1.6), "cursor-grok": reading(95.0)})          # claude and Neon out
        got = r.route("frontier", quota=q)
        assert got is not None and got.service.name == "codex", got and got.service.name
        assert r.plan(["frontier"], quota=q)[0][1].service.name == "codex"
        q.update({"claude": reading(70.0, 1.6), "antigravity-neon": reading(95.0)})      # Neon has room too
        assert r.route("frontier", quota=q).service.name in {"codex", "claude"}
        # the other way round: the slice-only pools still take frontier when no frontier_models pool has room
        q["codex"] = q["claude"] = reading(0.0)
        assert r.route("frontier", quota=q).service.name in {"antigravity-neon", "cursor-grok"}
        q["antigravity-neon"] = reading(0.0)
        assert r.route("frontier", quota=q).service.name == "cursor-grok"
        # and the order only binds kind frontier: research keeps its ranks
        assert r._frontier_slice_only(svc("cursor-grok"), "frontier") and not r._frontier_slice_only(svc("cursor-grok"), "research")
        assert not r._frontier_slice_only(svc("codex"), "frontier") and not r._frontier_slice_only(svc("claude"), "frontier")

    def test_a_repo_frontier_order_overrides_the_slice_only_sort(self, catalog, monkeypatch):
        """Adversary PR 899 r3 note 1: a repo's declared `frontier_order` is an operator override and is checked before the
        slice-only tier term; without it the same quota routes codex."""
        catalog({"cursor": self.CURSOR, "codex": CODEX})
        q = {s.name: {"remaining": 0.0, "age_s": 0, "windows": {"weekly": 0.0}} for s in r.SERVICES}
        q["codex"] = q["cursor-grok"] = {"remaining": 80.0, "age_s": 0, "windows": {"weekly": 80.0}}
        assert r.route("frontier", quota=q, repo="x").service.name == "codex"
        monkeypatch.setattr(r, "repo_frontier_order", lambda repo: ("cursor-grok", "codex") if repo == "x" else ())
        assert r.route("frontier", quota=q, repo="x").service.name == "cursor-grok"
        assert r.route("frontier", quota=q, repo="y").service.name == "codex"

    def test_a_lapsed_login_falls_back_to_the_last_resolved_grok_from_state(self, catalog):
        """A5: an unreadable catalog or one with no match keeps the last good id from state (docs B4a said `unresolved`)."""
        catalog({"cursor": self.CURSOR})
        assert r.suggest_model(svc("cursor-grok"), "research", {}) == "grok-4.7"           # records it in the state file
        catalog({"cursor": ["default", "composer-2.5"]})
        res = r.resolve_family("cursor", "grok-*")
        assert res.model == "grok-4.7" and res.source != "unresolved", res

    def test_the_static_burn_first_flag_does_not_lift_a_non_frontier_model_either(self, catalog, monkeypatch):
        catalog({"cursor": self.CURSOR, "codex": CODEX})
        import dataclasses
        grok = dataclasses.replace(svc("cursor-grok"), burn_first=True)
        monkeypatch.setattr(r, "SERVICES", tuple(grok if s.name == "cursor-grok" else s for s in r.SERVICES))
        q = {s.name: {"remaining": 70.0, "age_s": 0, "windows": {"weekly": 70.0}} for s in r.SERVICES}
        q["cursor-grok"] = {"remaining": 95.0, "age_s": 0, "windows": {"weekly": 95.0}}
        got = r.route("frontier", quota=q)
        assert got is not None and got.service.name != "cursor-grok", got.service.name

    def test_adjust_does_not_refuse_it_for_frontier(self, catalog):
        import route_adjust as ra
        catalog({"cursor": self.CURSOR})
        choice = r.Choice(svc("cursor-grok"), 50.0, 0.0, model="grok-4.7", kind="frontier")
        assert ra._refusal(r, "frontier", choice, {"never_target": ["omp"]}) is None

    def test_routes_for_research_and_frontier_only_when_its_pool_has_room(self, catalog):
        catalog({"cursor": self.CURSOR})
        reading = {"remaining": 80.0, "age_s": 0, "windows": {"weekly": 80.0}}
        q = {s.name: {"remaining": 0.0, "age_s": 0, "windows": {"weekly": 0.0}} for s in r.SERVICES}
        for kind in ("research", "frontier"):
            assert r.route(kind, quota=q) is None or r.route(kind, quota=q).service.name != "cursor-grok"
            q["cursor-grok"] = reading
            got = r.route(kind, quota=q)
            assert got is not None and got.service.name == "cursor-grok", kind
            assert got.model.split()[0] == "grok-4.7"
            q["cursor-grok"] = {"remaining": 0.0, "age_s": 0, "windows": {"weekly": 0.0}}
