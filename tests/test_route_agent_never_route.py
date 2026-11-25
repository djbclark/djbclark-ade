"""route_agent.py never_route, repo scope and Pi acceptance (2026-11-22).

Bug (tendcf lead 7833318b, 2026-11-22): `plan --kinds research --cwd ~/src/tendcf` picked the curated clinepass row although
`[routing].never_route` names it (operator 2026-10-23: lifeline of Hermes and Dann, never a slice target), because only
`discover()` applied never_route and only to discovered services. Operator 2026-11-02: only techno-euphora (and Hermes)
may route to the cline pool, refused under 40% headroom. `config/pi-pool-acceptance.toml` `[pools.clinepass] accepted = false`
did not reach `route`/`plan` either (only `bin/pi-default`).
"""
from __future__ import annotations

import argparse
import contextlib
import dataclasses
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))
sys.path.insert(0, str(ROOT / "tests"))

import route_agent as r  # noqa: E402
from test_route_agent import IDLE  # noqa: E402

ACCEPT_ALL = """
[pools.cursor]
accepted = true
[pools.zai]
accepted = true
[pools.clinepass]
accepted = true
"""
ACCEPT_NO_CLINEPASS = ACCEPT_ALL.replace("[pools.clinepass]\naccepted = true", "[pools.clinepass]\naccepted = false")
ACCEPT_NO_CURSOR = ACCEPT_ALL.replace("[pools.cursor]\naccepted = true", "[pools.cursor]\naccepted = false")


def drained(**open_pools: float) -> dict[str, dict[str, float]]:
    """Every pool of the idle fixture at 0% except the named ones (`open_pools`: remaining percent)."""
    quota = {name: {"remaining": 0.0} for name in IDLE}
    for name, left in open_pools.items():
        quota[name] = {"remaining": left}
    return quota


@pytest.fixture
def accept(monkeypatch, tmp_path):
    """Point the Pi pool acceptance at a temp file with the given text (the live file is never read)."""
    def write(text: str | None) -> Path:
        path = tmp_path / "pi-pool-acceptance.toml"
        path.unlink(missing_ok=True)
        if text is not None:
            path.write_text(text)
        monkeypatch.setenv("PI_POOL_ACCEPTANCE", str(path))
        return path
    write(ACCEPT_ALL)
    return write


def chosen(kind, quota, scope_repo):
    c = r.route(kind, quota=quota, scope_repo=scope_repo)
    return c.service.name if c else None


# -- (a) a curated never_route row is never a candidate -----------------------------------------------------------------

def test_the_curated_clinepass_row_is_in_never_route():
    # the premise of the bug: the curated service and the never_route name are the same string
    assert "clinepass" in r.BY_NAME and "clinepass" in r.NEVER_ROUTE


@pytest.mark.parametrize("kind", ["bulk", "mechanical", "research"])     # `code` is outside the quality band for clinepass anyway
def test_clinepass_is_never_chosen_outside_its_repo_scope(accept, kind):
    quota = drained(clinepass=100.0)                     # the only pool with room: the repro's 100% headroom
    for repo in ("tendcf", "djbclark-ade", "techno-euphora-research", None):
        assert chosen(kind, quota, repo) is None, repo


def test_never_route_reaches_a_curated_row_with_no_repo_scope(accept):
    """The generic rule, not clinepass by name: with the scope removed a never_route curated row is out for every repo."""
    with mock.patch.object(r, "REPO_SCOPED", {}):
        assert chosen("bulk", drained(clinepass=100.0), "techno-euphora") is None
        assert "clinepass" not in {s.name for s in r.discover(drained(clinepass=100.0))}
    assert "clinepass" in {s.name for s in r.discover(drained(clinepass=100.0))}     # scoped: still listed (show, policy)


def test_route_itself_refuses_a_never_route_row_whatever_discover_returns(accept):
    """Defense in depth: `discover` drops the row, and `route` alone (discover patched to hand the curated list back) refuses it too."""
    with mock.patch.object(r, "REPO_SCOPED", {}), mock.patch.object(r, "discover", return_value=list(r.SERVICES)):
        assert chosen("bulk", drained(clinepass=100.0), "techno-euphora") is None
        assert chosen("bulk", drained(clinepass=100.0), "tendcf") is None
        c = r.route("bulk", quota=dict(IDLE, clinepass={"remaining": 100.0}), scope_repo="tendcf")
        assert "clinepass: never_route" in c.barred


def test_the_repro_plan_cwd_tendcf_never_names_clinepass(accept):
    rows = r.plan(["research", "bulk"], quota=drained(clinepass=100.0), repo="tendcf", scope_repo="tendcf")
    assert [(k, c) for k, c in rows] == [("research", None), ("bulk", None)]


def test_a_refused_pool_is_named_in_barred_not_silently_dropped(accept):
    quota = dict(IDLE, clinepass={"remaining": 100.0})
    c = r.route("bulk", quota=quota, scope_repo="tendcf")
    assert c is not None and c.service.name != "clinepass"
    assert any(n.startswith("clinepass: only for techno-euphora") and "tendcf" in n for n in c.barred)


def test_a_barred_pool_does_not_anchor_the_quality_band(accept):
    """A refused pool is not the band's best pool: it cannot pull a worse pool out of (or into) the band by rank."""
    with mock.patch.object(r, "quality_best", wraps=r.quality_best) as qb:
        r.route("code", quota=drained(clinepass=100.0), scope_repo="tendcf")
    assert "clinepass" in qb.call_args.args[2]       # the `exclude` argument of the anchor lookup


# -- (b) the repo scope of the operator's 2026-11-02 ruling ---------------------------------------------------------------

def test_techno_euphora_may_take_clinepass(accept):
    assert chosen("bulk", drained(clinepass=100.0), "techno-euphora") == "clinepass"
    for kind in ("mechanical", "research"):
        assert chosen(kind, drained(clinepass=100.0), "techno-euphora") == "clinepass", kind


def test_the_repo_name_compares_case_insensitively(accept):
    assert chosen("bulk", drained(clinepass=100.0), "Techno-Euphora") == "clinepass"


def test_the_floor_is_40_percent_of_the_tightest_window(accept):
    assert r.REPO_SCOPED["clinepass"].min_headroom == 40.0
    assert chosen("bulk", drained(clinepass=40.0), "techno-euphora") == "clinepass"
    assert chosen("bulk", drained(clinepass=39.9), "techno-euphora") is None
    assert chosen("bulk", drained(clinepass=0.0), "techno-euphora") is None


def test_an_unmeasured_scoped_pool_is_refused(accept):
    quota = drained()
    quota["clinepass"] = {}                               # no `remaining`: the floor cannot be checked
    assert chosen("bulk", quota, "techno-euphora") is None
    del quota["clinepass"]
    assert chosen("bulk", quota, "techno-euphora") is None


def test_an_unknown_repository_is_refused(accept):
    assert chosen("bulk", drained(clinepass=100.0), None) is None
    assert chosen("bulk", drained(clinepass=100.0), "") is None
    # route() without scope_repo is fail closed; `repo` is a name that only selects [dispatch.repo_overrides] and never unlocks
    # a scoped pool (LOW-1 of the PR 945 review, 2026-11-22: it used to be the default scope)
    assert r.route("bulk", quota=drained(clinepass=100.0)) is None
    assert r.route("bulk", quota=drained(clinepass=100.0), repo="techno-euphora") is None
    assert r.plan(["bulk"], quota=drained(clinepass=100.0), repo="techno-euphora") == [("bulk", None)]


def test_the_floor_refusal_says_why(accept):
    c = r.route("bulk", quota=dict(IDLE, clinepass={"remaining": 30.0}), scope_repo="techno-euphora")
    assert any("30% left, under its 40% repo-scope floor" in n for n in c.barred)


# -- the cwd is what scopes: git repo of --cwd, never a directory name or a slice name -------------------------------------

def make_repo(parent: Path, directory: str, origin: str | None) -> Path:
    path = parent / directory
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    if origin:
        subprocess.run(["git", "-C", str(path), "remote", "add", "origin", origin], check=True)
    return path


def plan_cli(*argv, quota):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(r, "load_snapshot", return_value=(quota, 60.0)), \
            mock.patch.object(r, "operator_disabled", return_value=set()), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = r.main(list(argv))
    assert code == 0, err.getvalue()
    return json.loads(out.getvalue())["slices"]


def test_cli_scope_follows_the_repo_of_cwd_not_a_name(accept, tmp_path):
    drained_q = drained(clinepass=100.0)
    te = make_repo(tmp_path, "feature-wt", "https://example.test/frdminc/techno-euphora.git")
    other = make_repo(tmp_path, "techno-euphora", "https://example.test/djbclark/tendcf.git")       # right name, other repo
    bare = make_repo(tmp_path, "plain", None)                                                        # no remote
    gone = tmp_path / "missing"
    base = ["plan", "--kinds", "bulk", "--json"]
    assert plan_cli(*base, "--cwd", str(te), quota=drained_q)[0]["service"] == "clinepass"
    for cwd in (other, bare, gone):
        assert plan_cli(*base, "--cwd", str(cwd), quota=drained_q)[0]["service"] is None, cwd
    # the slice name is never read, and --repo only feeds the repo overrides, not the scope
    row = plan_cli(*base, "--cwd", str(other), "--slice", "techno-euphora", "--repo", "techno-euphora", quota=drained_q)[0]
    assert row["service"] is None


def test_cli_route_and_adjust_apply_the_same_scope(accept, tmp_path):
    te = make_repo(tmp_path, "te", "https://example.test/frdminc/techno-euphora.git")
    other = make_repo(tmp_path, "tc", "https://example.test/djbclark/tendcf.git")
    quota = drained(clinepass=100.0)
    for cwd, expect in ((te, "clinepass"), (other, None)):
        rows = plan_cli("adjust", "--kinds", "bulk", "--dry-run", "--json", "--cwd", str(cwd), quota=quota)
        assert rows[0]["service"] == expect, cwd


def test_scope_refusal_is_in_plan_json_barred(accept, tmp_path):
    other = make_repo(tmp_path, "tc", "https://example.test/djbclark/tendcf.git")
    row = plan_cli("plan", "--kinds", "bulk", "--json", "--cwd", str(other), quota=dict(IDLE, clinepass={"remaining": 100.0}))[0]
    assert any(n.startswith("clinepass: only for techno-euphora") for n in row["barred"])


# -- (c) an unaccepted Pi pool is never chosen ------------------------------------------------------------------------------

@pytest.fixture
def pi_ready():
    """The suite's fake Paseo lists no `pi`/`cursor` provider, so `service_ready` is False for the Pi pools; the acceptance is
    what these tests isolate."""
    with mock.patch.object(r, "service_ready", return_value=True):
        yield


def test_an_unaccepted_pi_pool_is_not_chosen(accept, pi_ready):
    quota = drained(cursor=100.0)
    quota["cursor"].update(windows={}, age_s=10.0)         # cursor is measured_only: needs a fresh reading to be eligible
    assert r.BY_NAME["cursor"].acp_agent == "pi"
    with_row = chosen("mechanical", quota, "any")
    assert with_row == "cursor"
    accept(ACCEPT_NO_CURSOR)
    assert chosen("mechanical", quota, "any") is None


def test_a_missing_or_unreadable_acceptance_file_fails_closed(accept, pi_ready):
    quota = drained(cursor=100.0)
    quota["cursor"].update(windows={}, age_s=10.0)
    assert chosen("mechanical", quota, "any") == "cursor"      # the control: the same quota routes with a good file
    for text in (None, "[pools\nbroken", '[pools.cursor]\naccepted = "yes"\n', "pools = 3\n"):
        accept(text)                                      # None: no file at all
        assert chosen("mechanical", quota, "any") is None, text
    accept('[pools.zai]\naccepted = true\n')              # a file with no cursor row: missing row is unaccepted
    assert chosen("mechanical", quota, "any") is None


def test_clinepass_in_scope_still_needs_the_pi_acceptance(accept):
    """techno-euphora lifts never_route for the pool and nothing else: `accepted = false` keeps it out until the operator flips it."""
    quota = drained(clinepass=100.0)
    assert chosen("bulk", quota, "techno-euphora") == "clinepass"
    accept(ACCEPT_NO_CLINEPASS)
    assert chosen("bulk", quota, "techno-euphora") is None
    c = r.route("bulk", quota=dict(IDLE, clinepass={"remaining": 100.0}), scope_repo="techno-euphora")
    assert any("clinepass: Pi pool not accepted" in n for n in c.barred)


def test_the_live_acceptance_file_keeps_clinepass_off_automatic_routing(monkeypatch):
    monkeypatch.delenv("PI_POOL_ACCEPTANCE", raising=False)
    assert "clinepass" in r.pi_unaccepted_services()
    assert "cursor" not in r.pi_unaccepted_services() and "zai" not in r.pi_unaccepted_services()
    assert chosen("bulk", drained(clinepass=100.0), "techno-euphora") is None


def test_ade_pi_pools_reads_the_acceptance_through_the_routers_loader(accept):
    import ade_pi_pools
    assert ade_pi_pools.load_acceptance() == r.load_pi_acceptance()
    assert ade_pi_pools.unaccepted_auto_services() == r.pi_unaccepted_services()


# -- policy loading ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("table, message", [
    ({"clinepass": {"repos": []}}, "non-empty array"),
    ({"clinepass": {"repos": ["Techno-Euphora"]}}, "lower case"),
    ({"clinepass": {"repos": ["x"], "min_headroom": 140}}, "0 to 100"),
    ({"clinepass": {"repos": ["x"], "min_headroom": True}}, "0 to 100"),
    ({"clinepass": {"repos": ["x"], "floor": 1}}, "only the keys"),
    ({"clinepass": ["x"]}, "only the keys"),
])
def test_a_malformed_repo_scope_fails_the_load(table, message):
    with pytest.raises(ValueError, match="routing.repo_scoped") as err:
        r._parse_repo_scoped({"repo_scoped": table})
    assert message in str(err.value)


def test_policy_output_states_the_scope():
    assert r.policy_public()["routing"]["repo_scoped"] == {"clinepass": {"repos": ["techno-euphora"], "min_headroom": 40.0}}
    assert "| routing.repo_scoped" in r.policy_markdown() and "clinepass: techno-euphora only, >= 40% left" in r.policy_markdown()


# -- LOW-1 (PR 945 review, 2026-11-22): the retry paths keep the --cwd scope, never fall back to a name --------------------------

def test_the_held_pool_retry_in_plan_keeps_the_cwd_scope(accept):
    """Mutant M-C: `plan` drops `scope_repo` in the retry that takes a held pool when nothing else is left. The only pool with room
    is clinepass, held for the kind: the first pass finds nothing, the retry takes it, and only with the scope still passed."""
    quota = drained(clinepass=100.0)
    held = {"bulk": {"clinepass"}}
    kept = r.plan(["bulk"], quota=quota, kind_exclude=held, repo="tendcf", scope_repo="techno-euphora")
    assert kept[0][1] is not None and kept[0][1].service.name == "clinepass"
    for scope in ("tendcf", None):                       # a --repo name of techno-euphora does not stand in for the cwd
        assert r.plan(["bulk"], quota=quota, kind_exclude=held, repo="techno-euphora", scope_repo=scope) == [("bulk", None)]


def test_the_unprofiled_retry_in_route_keeps_the_cwd_scope(accept):
    """Mutant M-B: `route` drops `scope_repo` in the need_profile=False retry. clinepass, the only pool, has no profile for
    bulk, so the first pass skips it and the retry is what routes it: it must still be scoped."""
    bare = [dataclasses.replace(r.BY_NAME["clinepass"], models={})]       # the only pool: no other pool is profiled for bulk
    with mock.patch.object(r, "discover", return_value=bare):
        quota = drained(clinepass=100.0)
        c = r.route("bulk", quota=quota, scope_repo="techno-euphora")
        assert c is not None and c.service.name == "clinepass" and c.model == ""      # the retry ran (the control: a profile-less pool)
        assert r.route("bulk", quota=quota, scope_repo="tendcf", repo="techno-euphora") is None
        assert r.route("bulk", quota=quota, repo="techno-euphora") is None


def test_adjust_defaults_to_no_scope_not_to_the_repo_name(accept):
    """Mutant M-J: `adjust(scope_repo=None)` falling back to `repo`. Programmatic callers pass the cwd's repo or get no scoped pool."""
    import route_adjust
    from datetime import datetime, timezone
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    def served(**kw):
        out = route_adjust.adjust(r, ["bulk"], quota=drained(clinepass=100.0), age=60.0, state=route_adjust.empty_state(),
                                  now=now, repo="techno-euphora", **kw)
        return out["rows"][0][1]
    assert served() is None and served(scope_repo="tendcf") is None
    assert served(scope_repo="techno-euphora").service.name == "clinepass"          # the control: the scope is what admits it


def test_cli_route_and_adjust_ignore_a_repo_name_for_the_scope(accept, tmp_path):
    """`--repo techno-euphora --cwd <other repo>`: the name feeds [dispatch.repo_overrides] only, on every command."""
    other = make_repo(tmp_path, "tc", "https://example.test/djbclark/tendcf.git")
    for argv in (("plan", "--kinds", "bulk"), ("adjust", "--kinds", "bulk", "--dry-run")):
        row = plan_cli(*argv, "--json", "--repo", "techno-euphora", "--cwd", str(other), quota=drained(clinepass=100.0))[0]
        assert row["service"] is None, argv
    code, answer = route_cli("--kind", "bulk", "--repo", "techno-euphora", "--cwd", str(other), quota=drained(clinepass=100.0))
    assert code == 1 and answer["service"] is None


def test_cli_route_scope_follows_cwd(accept, tmp_path):
    te = make_repo(tmp_path, "te", "https://example.test/frdminc/techno-euphora.git")
    code, answer = route_cli("--kind", "bulk", "--cwd", str(te), quota=drained(clinepass=100.0))
    assert code == 0 and answer["service"] == "clinepass"


def test_pi_default_scopes_by_cwd_never_by_the_repo_name(accept, tmp_path):
    import pi_defaults
    other = make_repo(tmp_path, "tc", "https://example.test/djbclark/tendcf.git")
    models = tmp_path / "models.json"
    models.write_text(json.dumps(["clinepass/cline-pass/deepseek-v4.1-flash"]))
    with mock.patch.object(r, "route", return_value=None) as route, \
            mock.patch.object(r, "load_snapshot", return_value=(drained(clinepass=100.0), 60.0)), \
            contextlib.redirect_stdout(io.StringIO()):
        pi_defaults.main(["--models-json", str(models), "--kind", "bulk", "--repo", "techno-euphora", "--cwd", str(other)])
    assert route.call_args.kwargs["scope_repo"] == "tendcf" and route.call_args.kwargs["repo"] == "techno-euphora"


# -- LOW-2: a refusal carries the pools barred for the slice ----------------------------------------------------------------

def route_cli(*argv, quota):
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(r, "load_snapshot", return_value=(quota, 60.0)), \
            mock.patch.object(r, "operator_disabled", return_value=set()), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = r.main(["route", "--json", *argv])
    return code, json.loads(out.getvalue())


def test_a_route_refusal_names_the_barred_pools(accept, tmp_path):
    other = make_repo(tmp_path, "tc", "https://example.test/djbclark/tendcf.git")
    code, answer = route_cli("--kind", "bulk", "--cwd", str(other), quota=drained(clinepass=100.0))
    assert code == 1 and answer["service"] is None
    assert any(n.startswith("clinepass: only for techno-euphora") and "tendcf" in n for n in answer["barred"])
    code, answer = route_cli("--kind", "bulk", "--cwd", str(other), quota=drained())      # no room anywhere: the key is still there
    assert code == 1 and isinstance(answer["barred"], list)


def test_a_plan_row_with_no_pool_names_the_barred_pools(accept, tmp_path):
    other = make_repo(tmp_path, "tc", "https://example.test/djbclark/tendcf.git")
    row = plan_cli("plan", "--kinds", "bulk", "--json", "--cwd", str(other), quota=drained(clinepass=100.0))[0]
    assert row["service"] is None
    assert any(n.startswith("clinepass: only for techno-euphora") for n in row["barred"])


# -- [dispatch.repo_overrides] keys on the --cwd repo too, an explicit --repo overriding it -----------------------------------

OPEN = {"codex": {"remaining": 90.0, "pace_ratio": 2.0}, "claude": {"remaining": 90.0}, "antigravity-argon": {"remaining": 90.0}}


def test_repo_overrides_follow_cwd_and_an_explicit_repo_wins(accept, tmp_path, monkeypatch):
    tendcf = make_repo(tmp_path, "wt-1", "https://example.test/djbclark/tendcf.git")
    other = make_repo(tmp_path, "wt-2", "https://example.test/djbclark/nix2cf.git")
    monkeypatch.chdir(other)                                  # the lead plans from another repository
    first = lambda *extra: plan_cli("plan", "--kinds", "frontier", "--json", *extra, quota=OPEN)[0]["service"]
    assert first() == "claude"                                # no tendcf override: the score decides
    assert first("--cwd", str(tendcf)) == "codex"             # tendcf's frontier_order (astra, fable, argon)
    assert first("--cwd", str(other), "--repo", "tendcf") == "codex"      # an explicit --repo selects the overrides
    assert first("--cwd", str(tendcf), "--repo", "nix2cf") == "claude"    # and replaces the cwd's
    code, answer = route_cli("--kind", "frontier", "--cwd", str(tendcf), quota=OPEN)
    assert code == 0 and answer["service"] == "codex"


def test_estimate_floors_read_the_override_repo(accept, tmp_path, monkeypatch):
    tendcf = make_repo(tmp_path, "wt-1", "https://example.test/djbclark/tendcf.git")
    monkeypatch.chdir(tmp_path)
    with mock.patch.object(r, "repo_floors", wraps=r.repo_floors) as floors:
        plan_cli("plan", "--kinds", "frontier", "--json", "--cwd", str(tendcf), quota=OPEN)
    assert floors.call_args_list and {c.args[0] for c in floors.call_args_list} == {"tendcf"}
    with mock.patch.object(r, "repo_floors", wraps=r.repo_floors) as floors:
        plan_cli("plan", "--kinds", "frontier", "--json", "--cwd", str(tendcf), "--repo", "nix2cf", quota=OPEN)
    assert {c.args[0] for c in floors.call_args_list} == {"nix2cf"}


# -- PR 947 review LOWs (2026-11-22) ---------------------------------------------------------------------------------------

def test_empty_cwd_is_not_the_planner_cwd_and_a_bad_cwd_is_named(accept, tmp_path, monkeypatch, capsys):
    te = make_repo(tmp_path, "te", "https://example.test/frdminc/techno-euphora.git")
    monkeypatch.chdir(te)                                  # the planner runs inside the scoped repo
    monkeypatch.setattr(r, "_WARNED_CWDS", set())
    assert r.repo_of("") is None and r.repo_of("  ") is None
    assert r.scope_repo_of(argparse.Namespace(cwd=None)) == "techno-euphora"
    assert capsys.readouterr().err == ""
    missing = str(tmp_path / "missing")
    for bad in ("", missing):
        ns = argparse.Namespace(cwd=bad, repo=None)
        assert r.scope_repo_of(ns) is None                 # fail closed, not "the planner's repo"
        assert r.override_repo_of(ns) is None
    err = capsys.readouterr().err
    assert "--cwd '' is empty" in err and missing in err
    assert err.count("repo scope fails closed") == 2
    r.scope_repo_of(argparse.Namespace(cwd="", repo=None))
    assert capsys.readouterr().err == ""                   # warned once per value
    assert plan_cli("plan", "--kinds", "bulk", "--json", "--cwd", "", quota=drained(clinepass=100.0))[0]["service"] is None


def test_route_keeps_no_local_named_like_the_module_function():
    import ast
    tree = ast.parse(Path(r.__file__).read_text())
    route = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "route")
    assigned = {n.id for n in ast.walk(route) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    assert "barred_notes" not in assigned and "barred_list" in assigned


@pytest.fixture
def shipped_policy(tmp_path):
    """Exercise current policy even after a test reloads the legacy fixture."""
    previous = r.POLICY
    shipped, _ = r.load_effective_policy(root=ROOT, home=tmp_path, environ={})
    r.apply_policy(shipped)
    try:
        yield
    finally:
        r.apply_policy(previous)


@pytest.mark.parametrize("name", ["venice", "rfab"])
def test_manual_pi_services_never_win_automatic_routes(accept, shipped_policy, name):
    from pi_defaults import choose

    accept(ACCEPT_ALL + f"\n[pools.{name}]\naccepted = true\n")
    svc = r.BY_NAME[name]
    quota = drained(**{name: 100.0})
    assert name in r.NEVER_ROUTE and name in r.OPERATOR_GATED
    assert svc.models["code"] in r.policy_markdown()
    with mock.patch.object(r, "REPO_SCOPED", {name: r.REPO_SCOPED["clinepass"]}):
        assert name not in {s.name for s in r.discover(quota)}
        assert r.candidate_block(svc, quota, "techno-euphora", pi_unaccepted=set()) == (
            f"{name}: operator-gated (manual only)"
        )
        # Exercise the shared candidate guard even if discovery returns only this pool.
        with mock.patch.object(r, "discover", return_value=[svc]):
            assert r.plan(["code", "bulk"], quota=quota, scope_repo="techno-euphora") == [
                ("code", None), ("bulk", None),
            ]
            assert choose("code", [svc.models["code"]], quota=quota, scope_repo="techno-euphora")["service"] is None


@pytest.mark.parametrize("name", ["venice", "rfab"])
def test_manual_model_namespace_cannot_route_under_an_active_pool(shipped_policy, name):
    model = r.BY_NAME[name].models["code"]
    alias = dataclasses.replace(r.BY_NAME["cursor"], models={"code": f"  '{model}' --effort high"})
    assert r.candidate_block(alias, {}, None, pi_unaccepted=set()) == (
        "cursor: operator-gated Pi model profile (manual only)"
    )

def test_automatic_discovery_excludes_explicit_mcp_profiles(monkeypatch):
    profiles = {"claude-mcp-rfab", "codex-mcp-chrome-devtools__rfab"}
    monkeypatch.setattr(r, "paseo_providers", lambda: profiles | {"unrelated"})
    found = {svc.name for svc in r.discover({})}
    assert profiles.isdisjoint(found)
    assert "unrelated" in found


def test_pi_catalog_excludes_operator_gated_models(shipped_policy, monkeypatch):
    allowed = "zai/glm-5.3"
    manual = ["Venice/z-ai-glm-5-3", "rfab/openai:gpt-6.2-sol"]
    ids = [allowed, *manual]
    rows = [{"id": model, "thinkingOptionIds": ["high"]} for model in ids]
    monkeypatch.setattr(r, "_paseo_json", lambda _: (rows, None))
    monkeypatch.setattr(r, "_pi_models", lambda models: models)
    monkeypatch.setattr(r, "_PROVIDER_MODELS", {})
    monkeypatch.setattr(r, "_PROVIDER_THINKING", {})
    assert all(r.pi_excluded(model) for model in manual)
    assert r.provider_models("pi") == [allowed]
    assert r.provider_thinking_options("pi") == {allowed: ("high",)}
