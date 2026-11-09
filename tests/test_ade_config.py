"""bin/ade_config.py + bin/ade-config: schema_version=1 read-only effective config.

Synthetic fixtures under tests/fixtures/ade_config. Every test isolates HOME/local.toml.
No writes to repo config; no network/auth probes; no secret resolution.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
FIX = REPO / "tests" / "fixtures" / "ade_config"
sys.path.insert(0, str(BIN))
import ade_config as ac  # noqa: E402
import ade_gates as ag  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Temp HOME so ~/.config/djbclark-ade/local.toml never touches the real one."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    # Clear isolated overrides unless a test sets them.
    monkeypatch.delenv("ROUTING_POLICY", raising=False)
    monkeypatch.delenv("GATES_TOML", raising=False)
    return h


def _local_write(home: Path, text: str) -> Path:
    path = home / ".config" / "djbclark-ade" / "local.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _run_cli(*args: str, home: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    e = {**os.environ, "HOME": str(home), "PATH": str(BIN) + os.pathsep + os.environ.get("PATH", "")}
    if env:
        e.update(env)
    return subprocess.run(
        [sys.executable, "-I", "-B", str(BIN / "ade-config"), *args],
        capture_output=True,
        text=True,
        env=e,
        cwd=str(REPO),
        check=False,
    )


def test_shipped_ade_toml_is_repo_base_and_matches_legacy_domains(home):
    import tomllib

    ade_path = REPO / "config" / "ade.toml"
    assert ade_path.is_file()
    eff = ac.load_effective(root=REPO, home=home)
    shipped = tomllib.loads((REPO / "config" / "routing.toml").read_text())
    for key in ("routing", "lead", "dispatch", "substrate", "hermes", "calibrate", "service"):
        assert eff.data.get(key) == shipped.get(key)
    assert eff.data["schema_version"] == 1
    frontier, info = ag.load_frontier()
    assert eff.data["gates"]["frontier"] == frontier
    # Present ade.toml is the repo base for every policy domain.
    assert eff.provenance["new_config"] == str(ade_path.resolve())
    assert eff.provenance["routing_source"].endswith("config/ade.toml")
    assert eff.provenance["gates_source"].endswith("config/ade.toml")
    assert eff.provenance["context_budget_source"].endswith("config/ade.toml")
    assert eff.provenance["secret_deny_source"].endswith("config/ade.toml")
    assert eff.provenance["pr_policy_source"].endswith("config/ade.toml")
    assert eff.provenance["local_config"] is None
    assert info["source"] == "gates.toml"
    cb_shipped = tomllib.loads((REPO / "config" / "context-budget.toml").read_text())
    assert eff.data["context_budget"]["dirs"] == cb_shipped["dirs"]
    assert eff.data["context_budget"]["budget"] == cb_shipped["budget"]
    sd_shipped = tomllib.loads((REPO / "config" / "secret-deny.toml").read_text())
    assert eff.data["secret_deny"]["deny"] == sd_shipped["deny"]
    assert eff.data["secret_deny"]["allow"] == sd_shipped["allow"]
    assert eff.data["secret_deny"]["claude"]["static"] == sd_shipped["claude"]["static"]
    pp_shipped = tomllib.loads((REPO / "config" / "pr-policy.toml").read_text())
    assert eff.data["pr_policy"]["meta"] == pp_shipped["meta"]
    assert eff.data["pr_policy"]["github"] == pp_shipped["github"]
    assert eff.data["pr_policy"]["forgejo"] == pp_shipped["forgejo"]
    # Fold from legacy mirrors still matches the committed file.
    assert ac.fold_legacy_domains(root=REPO) == tomllib.loads(ade_path.read_text())


def test_legacy_fallthrough_when_ade_toml_absent(home, tmp_path):
    """Synthetic root with only legacy files still projects every domain."""
    import shutil

    root = tmp_path / "legacy-only"
    (root / "config").mkdir(parents=True)
    for name in (
        "ade.schema.json",
        "routing.toml",
        "gates.toml",
        "context-budget.toml",
        "secret-deny.toml",
        "pr-policy.toml",
    ):
        shutil.copy(REPO / "config" / name, root / "config" / name)
    assert not (root / "config" / "ade.toml").exists()
    eff = ac.load_effective(root=root, home=home)
    assert eff.provenance["new_config"] is None
    assert eff.provenance["routing_source"].endswith("config/routing.toml")
    assert eff.provenance["gates_source"].endswith("config/gates.toml")
    assert eff.provenance["context_budget_source"].endswith("config/context-budget.toml")
    assert eff.provenance["secret_deny_source"].endswith("config/secret-deny.toml")
    assert eff.provenance["pr_policy_source"].endswith("config/pr-policy.toml")
    shipped = ac.fold_legacy_domains(root=REPO)
    for key in (
        "routing", "lead", "dispatch", "substrate", "hermes", "calibrate", "service",
        "context_budget", "secret_deny", "pr_policy",
    ):
        assert eff.data.get(key) == shipped.get(key)


def test_fold_write_check_cli(home, tmp_path):
    import shutil

    root = tmp_path / "fold-root"
    (root / "config").mkdir(parents=True)
    for name in (
        "ade.schema.json",
        "routing.toml",
        "gates.toml",
        "context-budget.toml",
        "secret-deny.toml",
        "pr-policy.toml",
    ):
        shutil.copy(REPO / "config" / name, root / "config" / name)
    missing = _run_cli("fold", "--check", "--root", str(root), home=home)
    assert missing.returncode == 1
    written = _run_cli("fold", "--write", "--root", str(root), home=home)
    assert written.returncode == 0, written.stderr
    assert (root / "config" / "ade.toml").is_file()
    folded_text = (root / "config" / "ade.toml").read_text()
    # Nested section tables (not inline) so ade-config set can edit scalar leaves.
    assert "[gates.frontier]" in folded_text
    assert "frontier = {" not in folded_text
    assert "[pr_policy.github]" in folded_text
    assert "github = {" not in folded_text
    assert "[context_budget.budget]" in folded_text
    assert 'budget = {' not in folded_text
    assert '"~" = {' in folded_text  # quoted-key override stays inline (set_scalar)
    assert "[secret_deny.claude]" in folded_text
    assert "[gates.floors.frontier]" in folded_text
    assert "frontier1_judged = { bound = 1" in folded_text  # floor records stay inline
    ok = _run_cli("fold", "--check", "--json", "--root", str(root), home=home)
    assert ok.returncode == 0, ok.stderr
    assert json.loads(ok.stdout)["ok"] is True
    # Drift fails --check.
    ade = root / "config" / "ade.toml"
    ade.write_text(ade.read_text() + "\n# drift\n[lead]\nfable_lead = false\n")
    drifted = _run_cli("fold", "--check", "--root", str(root), home=home)
    assert drifted.returncode == 1


def test_local_override_preserves_sibling_lead_leaves(home):
    import tomllib

    shipped_lead = tomllib.loads((REPO / "config" / "routing.toml").read_text())["lead"]
    _local_write(home, (FIX / "local_sibling.toml").read_text())
    eff = ac.load_effective(root=REPO, home=home)
    assert eff.data["lead"]["fable_lead"] is False
    for key, value in shipped_lead.items():
        if key == "fable_lead":
            continue
        assert eff.data["lead"][key] == value


def test_local_service_array_replaces_whole_not_concat(home):
    _local_write(home, (FIX / "local_services_replace.toml").read_text())
    eff = ac.load_effective(root=REPO, home=home)
    names = [e["name"] for e in eff.data["service"]]
    assert names == ["only-local"]


def test_duplicate_service_identity_rejected(home, monkeypatch):
    monkeypatch.setenv("ROUTING_POLICY", str(FIX / "routing_dup_service.toml"))
    with pytest.raises(ac.ConfigError, match="duplicate service identity"):
        ac.load_effective(root=REPO, home=home, environ=dict(os.environ))


def test_unknown_schema_version_rejected(home):
    with pytest.raises(ac.ConfigError, match="unsupported schema_version"):
        ac.load_effective(
            root=REPO,
            home=home,
            new_config=FIX / "ade_unknown_version.toml",
        )


def test_invalid_new_config_rejected_no_legacy_fallback(home):
    with pytest.raises(ac.ConfigError, match="not valid TOML"):
        ac.load_effective(
            root=REPO,
            home=home,
            new_config=FIX / "ade_invalid.toml",
        )


def test_local_type_conflict_rejected(home):
    _local_write(home, (FIX / "local_type_conflict.toml").read_text())
    with pytest.raises(ac.ConfigError, match="type conflict"):
        ac.load_effective(root=REPO, home=home)


def test_routing_policy_isolates_domain_from_local(home, monkeypatch):
    import tomllib

    # Point routing at shipped file via env; local tries to flip fable_lead.
    monkeypatch.setenv("ROUTING_POLICY", str(REPO / "config" / "routing.toml"))
    _local_write(home, (FIX / "local_sibling.toml").read_text())
    eff = ac.load_effective(root=REPO, home=home, environ=dict(os.environ))
    shipped = tomllib.loads((REPO / "config" / "routing.toml").read_text())
    assert eff.data["lead"] == shipped["lead"]
    assert eff.data["lead"]["fable_lead"] is True
    assert eff.provenance["routing_env"] == str(REPO / "config" / "routing.toml")


def test_gates_toml_isolates_and_bad_frontier_is_closed(home, monkeypatch):
    monkeypatch.setenv("GATES_TOML", str(FIX / "gates_bad_frontier.toml"))
    # Also try a local gates widen that must be ignored under isolation.
    _local_write(
        home,
        "[gates.frontier]\nfrontier1_per_wave = 2\nfrontier1_judged = 1\n",
    )
    eff = ac.load_effective(root=REPO, home=home, environ=dict(os.environ))
    assert eff.data["gates"]["frontier"] == ac.FRONTIER_DEFAULTS
    assert eff.provenance["gates_info"]["source"] == "code"
    assert eff.provenance["gates_env"] == str(FIX / "gates_bad_frontier.toml")


def test_context_budget_toml_isolates_domain_from_local(home, tmp_path, monkeypatch):
    selected = tmp_path / "cb.toml"
    selected.write_text(
        'dirs = ["~/only-selected"]\n[budget]\ntotal = 11111\nmemory = 2222\n'
    )
    monkeypatch.setenv("CONTEXT_BUDGET_TOML", str(selected))
    _local_write(
        home,
        '[context_budget]\ndirs = ["~/from-local"]\n'
        "[context_budget.budget]\ntotal = 99999\n",
    )
    eff = ac.load_effective(root=REPO, home=home, environ=dict(os.environ))
    assert eff.data["context_budget"]["dirs"] == ["~/only-selected"]
    assert eff.data["context_budget"]["budget"]["total"] == 11111
    assert eff.provenance["context_budget_env"] == str(selected)


def test_missing_selected_context_budget_toml_errors(home, monkeypatch):
    missing = home / "no-such-context-budget.toml"
    monkeypatch.setenv("CONTEXT_BUDGET_TOML", str(missing))
    with pytest.raises(ac.ConfigError, match="not a regular file"):
        ac.load_effective(root=REPO, home=home, environ=dict(os.environ))


def test_secret_deny_toml_isolates_domain_from_local(home, tmp_path, monkeypatch):
    selected = tmp_path / "sd.toml"
    selected.write_text(
        'version = 1\ndeny = [".only-selected"]\nallow = []\n[claude]\nstatic = []\n'
    )
    monkeypatch.setenv("SECRET_DENY_TOML", str(selected))
    _local_write(
        home,
        '[secret_deny]\nversion = 1\ndeny = [".from-local"]\nallow = []\n'
        "[secret_deny.claude]\nstatic = []\n",
    )
    eff = ac.load_effective(root=REPO, home=home, environ=dict(os.environ))
    assert eff.data["secret_deny"]["deny"] == [".only-selected"]
    assert eff.provenance["secret_deny_env"] == str(selected)


def test_missing_selected_secret_deny_toml_errors(home, monkeypatch):
    missing = home / "no-such-secret-deny.toml"
    monkeypatch.setenv("SECRET_DENY_TOML", str(missing))
    with pytest.raises(ac.ConfigError, match="not a regular file"):
        ac.load_effective(root=REPO, home=home, environ=dict(os.environ))


def test_pr_policy_toml_isolates_domain_from_local(home, tmp_path, monkeypatch):
    selected = tmp_path / "pp.toml"
    selected.write_text(
        '[meta]\nschema = 1\n[github]\npolicy = "selected-only"\nowners = ["sel"]\n'
        'token_secret = "T"\n'
    )
    monkeypatch.setenv("PR_POLICY_TOML", str(selected))
    _local_write(
        home,
        '[pr_policy.meta]\nschema = 1\n[pr_policy.github]\npolicy = "from-local"\n',
    )
    eff = ac.load_effective(root=REPO, home=home, environ=dict(os.environ))
    assert eff.data["pr_policy"]["github"]["policy"] == "selected-only"
    assert eff.data["pr_policy"]["github"]["owners"] == ["sel"]
    assert "forgejo" not in eff.data["pr_policy"]
    assert eff.provenance["pr_policy_env"] == str(selected)


def test_missing_selected_pr_policy_toml_errors(home, monkeypatch):
    missing = home / "no-such-pr-policy.toml"
    monkeypatch.setenv("PR_POLICY_TOML", str(missing))
    with pytest.raises(ac.ConfigError, match="not a regular file"):
        ac.load_effective(root=REPO, home=home, environ=dict(os.environ))


def test_gate_loosen_clamped_to_code_defaults(home):
    eff = ac.load_effective(
        root=REPO,
        home=home,
        new_config=FIX / "ade_loose_gate.toml",
    )
    # 99 > bound 2 → code default 1; min_left 1.0 < 15 → code default 15
    assert eff.data["gates"]["frontier"]["frontier1_per_wave"] == 1.0
    assert eff.data["gates"]["frontier"]["frontier1_min_left"] == 15.0


def test_missing_selected_routing_policy_errors(home, monkeypatch):
    missing = home / "no-such-routing.toml"
    monkeypatch.setenv("ROUTING_POLICY", str(missing))
    with pytest.raises(ac.ConfigError, match="not a regular file"):
        ac.load_effective(root=REPO, home=home, environ=dict(os.environ))


def test_check_ok_and_cli_makes_no_writes(home, tmp_path):
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("x")
    before = {
        "sentinel": sentinel.stat().st_mtime_ns,
        "routing": (REPO / "config" / "routing.toml").stat().st_mtime_ns,
        "gates": (REPO / "config" / "gates.toml").stat().st_mtime_ns,
    }
    errors, eff = ac.check(root=REPO, home=home)
    assert errors == []
    assert eff is not None
    proc = _run_cli("check", "--root", str(REPO), "--home", str(home), home=home)
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout
    assert sentinel.stat().st_mtime_ns == before["sentinel"]
    assert (REPO / "config" / "routing.toml").stat().st_mtime_ns == before["routing"]
    assert (REPO / "config" / "gates.toml").stat().st_mtime_ns == before["gates"]
    assert not (home / ".config" / "djbclark-ade" / "local.toml").exists()


def test_cli_get_and_diff_json(home):
    _local_write(home, (FIX / "local_sibling.toml").read_text())
    got = _run_cli(
        "get", "lead.fable_lead", "--root", str(REPO), "--home", str(home), "--json",
        home=home,
    )
    assert got.returncode == 0, got.stderr
    payload = json.loads(got.stdout)
    assert payload["value"] is False
    diff = _run_cli(
        "diff", "--root", str(REPO), "--home", str(home), "--json",
        home=home,
    )
    assert diff.returncode == 0, diff.stderr
    changes = json.loads(diff.stdout)["changes"]
    assert any(c["path"] == "lead.fable_lead" and c["after"] is False for c in changes)


def test_schema_file_present_and_check_sees_it(home):
    schema = REPO / "config" / "ade.schema.json"
    assert schema.is_file()
    data = json.loads(schema.read_text())
    assert data["title"] == "djbclark-ade effective config"
    assert data["properties"]["schema_version"]["const"] == 1
    errs = ac.validate_schema_file(schema)
    assert errs == []


def test_new_minimal_ade_toml_loads(home):
    eff = ac.load_effective(
        root=REPO,
        home=home,
        new_config=FIX / "ade_minimal.toml",
    )
    assert eff.data["lead"]["fable_lead"] is True
    assert eff.data["service"][0]["name"] == "claude"
    assert eff.data["gates"]["frontier"]["frontier1_per_wave"] == 2.0


def test_mapping_table_covers_routing_gates_context_budget_secret_deny_pr_policy():
    targets = {row[2] for row in ac.LEGACY_PROJECTION}
    assert "[routing]" in targets
    assert "[[service]]" in targets
    assert "[gates.frontier]" in targets
    assert "[gates.floors.frontier]" in targets
    assert "[context_budget].dirs" in targets
    assert "[context_budget].budget" in targets
    assert "[secret_deny].deny" in targets
    assert "[secret_deny].claude" in targets
    assert "[pr_policy].meta" in targets
    assert "[pr_policy].github" in targets
    assert "[pr_policy].forgejo" in targets


@pytest.fixture
def synthetic_root(tmp_path):
    """Only public tracked schema/legacy policy copied; no machine-local input."""
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    for name in ("ade.schema.json", "routing.toml", "gates.toml"):
        (root / "config" / name).write_bytes((REPO / "config" / name).read_bytes())
    return root


@pytest.mark.parametrize("text", [
    'routing = 1', 'lead = "bad"', 'dispatch = []', 'substrate = 1',
    'hermes = false', 'calibrate = 2', 'service = [1]',
    '[[service]]\nname = 1',
    '[gates]\nunknown = 1', '[gates]\nfrontier = 1',
    '[gates.frontier]\nfrontier1_per_wave = "oops"',
    '[gates.frontier]\nmisspelled = 1',
    '[gates.frontier]\nfrontier1_per_wave = true',
    '[gates.frontier]\nfrontier1_per_wave = inf',
    '[gates.floors.frontier]\nfrontier1_per_wave = 2',
    '[gates.floors.frontier.frontier1_per_wave]\nbound = "oops"',
    '[gates.floors.frontier.frontier1_per_wave]\nmisspelled = 1',
    '[context_budget]\nunknown = 1',
    '[context_budget]\ndirs = 1',
    '[context_budget]\nbudget = 1',
    '[secret_deny]\nunknown = 1',
    '[secret_deny]\ndeny = 1',
    '[secret_deny]\nversion = 2',
    '[pr_policy]\nunknown = 1',
    '[pr_policy.meta]\nschema = 2',
])
@pytest.mark.parametrize("location", ["new", "local"])
def test_raw_schema_failures_all_commands(home, synthetic_root, text, location):
    if location == "new":
        (synthetic_root / "config/ade.toml").write_text('schema_version = 1\n' + text)
    else:
        _local_write(home, text)
    errors, effective = ac.check(root=synthetic_root, home=home, environ={})
    assert errors and effective is None
    for command in (("check",), ("get", "schema_version"), ("diff",)):
        result = _run_cli(*command, "--root", str(synthetic_root), "--home", str(home), home=home)
        assert result.returncode == 1, (command, result.stdout, result.stderr)


@pytest.mark.parametrize("domain", ["routing", "gates"])
@pytest.mark.parametrize("location", ["new", "local"])
def test_invalid_raw_input_rejected_even_in_env_isolated_domain(home, synthetic_root, domain, location):
    text = 'routing = 1' if domain == "routing" else '[gates.frontier]\nmisspelled = "oops"'
    if location == "new":
        (synthetic_root / "config/ade.toml").write_text('schema_version = 1\n' + text)
    else:
        _local_write(home, text)
    env = {"ROUTING_POLICY" if domain == "routing" else "GATES_TOML":
           str(synthetic_root / "config" / ("routing.toml" if domain == "routing" else "gates.toml"))}
    with pytest.raises(ac.ConfigError):
        ac.load_effective(root=synthetic_root, home=home, environ=env)


@pytest.mark.parametrize("location", ["new", "local"])
@pytest.mark.parametrize("shape", ["directory", "dangling", "fifo", "unreadable"])
def test_present_unusable_input_never_falls_back(home, synthetic_root, monkeypatch, location, shape):
    path = synthetic_root / "config/ade.toml" if location == "new" else ac.default_local_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    if shape == "directory":
        path.mkdir()
    elif shape == "dangling":
        path.symlink_to(path.parent / "absent.toml")
    elif shape == "fifo":
        os.mkfifo(path)
    else:
        path.write_text('schema_version = 1\n')
        original_open = ac.os.open
        def denied(target, *args, **kwargs):
            if Path(target) == path:
                raise PermissionError(13, "Permission denied", str(path))
            return original_open(target, *args, **kwargs)
        monkeypatch.setattr(ac.os, "open", denied)
    errors, effective = ac.check(root=synthetic_root, home=home, environ={})
    assert errors and effective is None
    with pytest.raises(ac.ConfigError):
        ac.local_diff(root=synthetic_root, home=home, environ={})


def _pure_legacy_reader():
    """Compile only load_policy and its literal constants; no routing initialization."""
    import ast
    import tomllib
    tree = ast.parse((BIN / "route_agent.py").read_text())
    service = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Service")
    fields = {n.target.id for n in service.body if isinstance(n, ast.AnnAssign)}
    names = {"_SERVICE_REQUIRED", "LEAD_KEYS", "LEAD_ALL_KEYS", "LEAD_SWITCHES",
             "LEAD_PIPELINE_EFFORT_DEFAULT", "CLAUDE_EFFORT_LEVELS"}
    nodes = [n for n in tree.body if (
        isinstance(n, ast.FunctionDef) and n.name == "load_policy"
    ) or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in n.targets))]
    namespace = {"Path": Path, "tomllib": tomllib, "Any": object, "SERVICE_KEYS": fields}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "pure_load_policy", "exec"), namespace)
    return namespace["load_policy"]


_LEGACY_BASE = '[routing]\n[dispatch]\n[hermes]\n[calibrate]\n'
_LEGACY_SERVICE = '[[service]]\nname="x"\ncli="x"\ngood_at={}\nbilling="free"\n'


@pytest.mark.parametrize("tail", [
    '[[service]]\nname="x"\n',
    _LEGACY_SERVICE + 'unknown = 1\n',
    _LEGACY_SERVICE + 'pool = ["one"]\n',
    _LEGACY_SERVICE + 'pool = ["one", 2]\n',
    _LEGACY_SERVICE + '[substrate]\nlifeline = 1\n',
    _LEGACY_SERVICE + '[lead]\nmodel = "opus"\n',
    _LEGACY_SERVICE + '[lead]\nmodel="opus"\neffort="ultra"\npipeline_model="sonnet"\n',
    _LEGACY_SERVICE + '[lead]\nmodel="opus"\neffort="high"\npipeline_model="sonnet"\nfable_lead=1\n',
    _LEGACY_SERVICE + '[lead]\nmodel="opus"\neffort="high"\npipeline_model="sonnet"\nunknown=1\n',
    'substrate = 1\n' + _LEGACY_SERVICE,
    'lead = 1\n' + _LEGACY_SERVICE,
])
def test_selected_legacy_failure_parity(home, synthetic_root, tmp_path, tail):
    # Root scalars must precede sections, rather than becoming calibrate leaves.
    prefix = ''
    if tail.startswith(('lead =', 'substrate =')):
        prefix, tail = tail.split('\n', 1)
        prefix += '\n'
    path = tmp_path / "routing-bad.toml"
    path.write_text(prefix + _LEGACY_BASE + tail)
    with pytest.raises(ValueError) as old:
        _pure_legacy_reader()(path)
    with pytest.raises(ac.ConfigError) as new:
        ac.load_effective(root=synthetic_root, home=home, environ={"ROUTING_POLICY": str(path)})
    assert str(new.value) == str(old.value)


@pytest.mark.parametrize("lead", ['', '[lead]\nmodel="opus"\neffort="high"\npipeline_model="sonnet"\n'])
def test_selected_legacy_defaults_parity(home, synthetic_root, tmp_path, lead):
    path = tmp_path / "routing-valid.toml"
    path.write_text(_LEGACY_BASE + _LEGACY_SERVICE + lead)
    old = _pure_legacy_reader()(path)
    eff = ac.load_effective(root=synthetic_root, home=home, environ={"ROUTING_POLICY": str(path)})
    for key in ac.ROUTING_DOMAIN_KEYS:
        assert eff.data.get(key) == old.get(key)
    if lead:
        assert eff.data['lead']['pipeline_effort'] == 'high'
        assert 'fable_lead' not in eff.data['lead']


@pytest.mark.parametrize("mode", ["new", "legacy", "isolated"])
def test_floor_only_local_merges_raw_request_before_clamp(home, synthetic_root, mode):
    frontier = {'frontier1_per_wave': 2}
    gates = {'frontier': frontier, 'floors': {'frontier': {'frontier1_per_wave': {'bound': 1}}}}
    overlay = {'floors': {'frontier': {'frontier1_per_wave': {'bound': 2}}}}
    local = '[gates.floors.frontier.frontier1_per_wave]\nbound = 2\n'
    _local_write(home, local)
    prefix = 'gates.' if mode == "new" else ''
    text = (f'[{prefix}frontier]\nfrontier1_per_wave=2\n'
            f'[{prefix}floors.frontier.frontier1_per_wave]\nbound=1\n')
    env = {}
    if mode == "new":
        (synthetic_root / 'config/ade.toml').write_text('schema_version=1\n' + text)
    else:
        path = synthetic_root / 'config/gates.toml'
        path.write_text(text)
        if mode == "isolated":
            env['GATES_TOML'] = str(path)
    raw = gates if mode == "isolated" else ac.merge_maps(gates, overlay, path='gates')
    expected, _ = ac.clamp_frontier(raw['frontier'], raw['floors']['frontier'], source_label='test')
    eff = ac.load_effective(root=synthetic_root, home=home, environ=env)
    assert eff.data['gates']['frontier'] == expected
    assert expected['frontier1_per_wave'] == (1 if mode == "isolated" else 2)


def test_schema_changes_are_enforced_and_unknown_assertions_fail(home, synthetic_root):
    path = synthetic_root / 'config/ade.schema.json'
    schema = json.loads(path.read_text())
    schema['properties']['routing']['additionalProperties'] = False
    path.write_text(json.dumps(schema))
    errors, _ = ac.check(root=synthetic_root, home=home, environ={})
    assert errors and 'unknown key' in errors[0]
    schema['properties']['routing']['additionalProperties'] = True
    schema['properties']['routing']['minProperties'] = 1
    path.write_text(json.dumps(schema))
    with pytest.raises(ac.ConfigError, match='unsupported schema keywords'):
        ac.load_effective(root=synthetic_root, home=home, environ={})


@pytest.mark.parametrize("text", [
    None, '', '[frontier]\nfrontier1_per_wave="oops"',
    '[frontier]\nfrontier1_per_wave=inf',
    '[frontier]\nunknown=1',
    '[frontier]\nfrontier1_per_wave=2\n[floors.frontier]\nfrontier1_per_wave="bad"',
    '[frontier]\nfrontier1_per_wave=2\n[floors.frontier.frontier1_per_wave]\nbound="bad"',
    '[frontier]\nfrontier1_per_wave=2\n[floors.frontier.frontier1_per_wave]\nbound=2',
])
def test_selected_legacy_gate_fallback_parity(home, synthetic_root, tmp_path, monkeypatch, text):
    path = tmp_path / 'legacy-gates.toml'
    if text is not None:
        path.write_text(text)
    monkeypatch.setenv('GATES_TOML', str(path))
    old, old_info = ag.load_frontier()
    new = ac.load_effective(root=synthetic_root, home=home, environ={'GATES_TOML': str(path)})
    assert new.data['gates']['frontier'] == old
    assert new.provenance['gates_info']['source'] == old_info['source']
    assert bool(new.provenance['gates_info']['toml_error']) == bool(old_info['toml_error'])


@pytest.mark.parametrize("location", ["new", "local"])
def test_r3_raw_duplicates_reject_before_routing_isolation(home, synthetic_root, location):
    duplicate = '[[service]]\nname="same"\n[[service]]\nname="same"\n'
    if location == "new":
        (synthetic_root / 'config/ade.toml').write_text('schema_version=1\n' + duplicate)
    else:
        _local_write(home, duplicate)
    env = {'ROUTING_POLICY': str(synthetic_root / 'config/routing.toml')}
    with pytest.raises(ac.ConfigError, match='duplicate service identity'):
        ac.load_effective(root=synthetic_root, home=home, environ=env)
    errors, eff = ac.check(root=synthetic_root, home=home, environ=env)
    assert eff is None and 'duplicate service identity' in errors[0]
    with pytest.raises(ac.ConfigError, match='duplicate service identity'):
        ac.local_diff(root=synthetic_root, home=home, environ=env)
    for command in [('check',), ('get', 'schema_version'), ('diff',)]:
        result = _run_cli(*command, '--root', str(synthetic_root), '--home', str(home),
                          home=home, env=env)
        assert result.returncode == 1, (result.stdout, result.stderr)
        assert 'duplicate service identity' in result.stdout + result.stderr


def _r3_cli_targets(command, root, home, placement):
    # All paths are explicit and synthetic, including deliberate decoy targets.
    root_flags = ['--root', str(root)]
    home_flags = ['--home', str(home)]
    tail = ['get', 'lead.model'] if command == 'get' else [command]
    if placement == 'before':
        return root_flags + home_flags + tail
    if placement == 'after':
        return tail + root_flags + home_flags
    if placement == 'mixed_root':
        return root_flags + tail + home_flags
    if placement == 'mixed_home':
        return home_flags + tail + root_flags
    if placement == 'repeated':
        return ['--root', str(root / 'decoy'), '--home', str(home / 'decoy')] + tail + root_flags + home_flags
    raise AssertionError(placement)


@pytest.mark.parametrize('command', ['check', 'get', 'diff'])
@pytest.mark.parametrize('placement', ['before', 'after', 'mixed_root', 'mixed_home', 'repeated'])
def test_r3_main_preserves_explicit_targets(home, synthetic_root, command, placement):
    import argparse
    import ast
    node = next(n for n in ast.parse((BIN / 'ade-config').read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == 'main')
    seen = {}
    def handler(args):
        seen.update(root=args.root, home=args.home)
        return 0
    namespace = {
        'argparse': argparse,
        'cmd_check': handler,
        'cmd_get': handler,
        'cmd_diff': handler,
        'cmd_set': handler,
        'cmd_fold': handler,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'actual ade-config.main', 'exec'), namespace)
    assert namespace['main'](_r3_cli_targets(command, synthetic_root, home, placement)) == 0
    assert seen == {'root': str(synthetic_root), 'home': str(home)}
    # Defaults remain compatible; stub handlers guarantee no default-home read.
    assert namespace['main'](['get', 'schema_version'] if command == 'get' else [command]) == 0
    assert seen == {'root': None, 'home': None}


@pytest.mark.parametrize('command', ['check', 'get', 'diff'])
@pytest.mark.parametrize('placement', ['before', 'after', 'mixed_root', 'mixed_home', 'repeated'])
def test_r3_cli_targets_hermetic(home, synthetic_root, command, placement):
    (synthetic_root / 'config/ade.toml').write_text('schema_version=1\n[lead]\nmodel="repo-target"\n')
    local = _local_write(home, '[lead]\nmodel="local-target"\n')
    # A missing --home must hit this synthetic decoy rather than the operator HOME.
    decoy_home = home / 'environment-home'
    decoy_home.mkdir()
    _local_write(decoy_home, 'invalid = [')
    args = _r3_cli_targets(command, synthetic_root, home, placement)
    proc = _run_cli(*args, '--json', home=decoy_home)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    payload = json.loads(proc.stdout)
    if command == 'check':
        assert payload['ok'] is True
        assert payload['provenance']['root'] == str(synthetic_root.resolve())
        assert payload['provenance']['local_config'] == str(local)
    elif command == 'get':
        assert payload['value'] == 'local-target'
    else:
        assert {'path': 'lead.model', 'before': 'repo-target', 'after': 'local-target'} in payload['changes']


@pytest.mark.parametrize('stray', ['[lead]\nfable_lead=false\n', 'not valid TOML ['])
def test_r3_diff_ignores_existing_supposedly_missing_baseline(home, synthetic_root, stray):
    new = synthetic_root / 'config/ade.toml'
    new.write_text('schema_version=1\n[lead]\nfable_lead=true\n')
    local = _local_write(home, '[lead]\nfable_lead=false\n')
    extra = local.with_name('local-missing-for-diff.toml')
    extra.write_text(stray)
    paths = (new, local, extra)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}
    baseline = ac.load_without_local(root=synthetic_root, home=home, environ={})
    assert baseline.data['lead']['fable_lead'] is True
    assert baseline.provenance['local_config'] is None
    assert ac.Change('lead.fable_lead', True, False) in ac.local_diff(root=synthetic_root, home=home, environ={})
    result = _run_cli('diff', '--root', str(synthetic_root), '--home', str(home), '--json', home=home)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert {'path': 'lead.fable_lead', 'before': True, 'after': False} in json.loads(result.stdout)['changes']
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}


def test_r3_disabled_local_never_resolves_probes_or_reads_local_paths(home, synthetic_root, monkeypatch):
    (synthetic_root / 'config/ade.toml').write_text('schema_version=1\n')
    # Includes an explicit existing unusable override, which must not be probed.
    explicit_local = home / 'directory-override'
    explicit_local.mkdir()
    original_present, original_read = ac.input_present, ac.read_toml
    def no_resolution(*args, **kwargs):
        raise AssertionError('local path resolution attempted')
    def guarded_present(path):
        assert path != home and home not in path.parents, 'local path probed'
        return original_present(path)
    def guarded_read(path):
        assert path != home and home not in path.parents, 'local path read'
        return original_read(path)
    monkeypatch.setattr(ac, 'default_local_path', no_resolution)
    monkeypatch.setattr(ac, 'input_present', guarded_present)
    monkeypatch.setattr(ac, 'read_toml', guarded_read)
    baseline = ac.load_without_local(root=synthetic_root, home=home, environ={})
    disabled = ac.load_effective(root=synthetic_root, home=home, local_config=explicit_local,
                                 include_local=False, environ={})
    assert baseline.data == disabled.data
    assert disabled.provenance['local_config'] is None
