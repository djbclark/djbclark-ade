"""W16 (2026-11-12): bounded install array, choice and key-identity writes.

Temporary config roots only; offline. Every successful write is proved against the
whole parsed tree (one changed field) and through the real catalog consumer.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BIN = REPO / "bin"
sys.path.insert(0, str(BIN))
import ade_config as ac  # noqa: E402
import ade_config_edit as edit  # noqa: E402
import ade_install as install  # noqa: E402


@pytest.fixture
def tree(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    for name in ("ade.schema.json", "install.schema.json", "context-budget.toml"):
        shutil.copy2(REPO / "config" / name, root / "config" / name)
    shutil.copy2(REPO / "tests/fixtures/install_catalog/minimal.toml", root / "config/install.toml")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("ROUTING_POLICY", "GATES_TOML", "MODEL_TIERS_TOML"):
        monkeypatch.setenv(name, str(tmp_path / "unreadable-isolated-domain"))
    return root, home


UNIFIED = (
    'schema_version = 1\n'
    '[[install.component]]\nid = "fixture"\nclass = "hard"\nprobe_argv = ["fixture", "--version"]\n\n'
    '[[install.component]]\nid = "extra"\nclass = "offered"\nchosen = false  # keep me\n\n'
    '[[install.jobs]]\nname = "job-a"\nkind = "ade-sched"\nowner = "o"\nclass = "optional"\n'
    'chosen = false\nset = [\n  "a=1", # old\n  "b=2",\n]\n\n'
    '[keys.EXAMPLE_API_KEY]\ncreate_url = "UNKNOWN"\n'
    '[context_budget]\ndirs = ["~"]\n[context_budget.budget]\ntotal = 30000\n'
)


def unified(root: Path) -> Path:
    path = root / "config/ade.toml"
    path.write_text(UNIFIED)
    return path


def put(tree, path, value, **kw):
    root, home = tree
    return edit.set_scalar(path, value, root=root, home=home, **kw)


def catalog(tree):
    root, home = tree
    return install.load_catalog(root=root, home=home)


def component(tree, ident):
    return next(c for c in catalog(tree).components if c["id"] == ident)


def key(tree, name):
    return next(k for k in catalog(tree).keys if k["name"] == name)


def snapshot(root: Path) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in (root / "config").iterdir() if p.suffix != ".lock"}


# --- A. choices and arrays on legacy rows ------------------------------------------------------


def test_legacy_component_choice_changes_exactly_one_line(tree):
    root, _ = tree
    path = root / "config/install.toml"
    before = path.read_text()
    result = put(tree, "install.component.tool-b.chosen", True, target="repo")
    assert result.changed and result.target.kind == "legacy_install"
    assert path.read_text() == before.replace("chosen = false", "chosen = true", 1)
    assert component(tree, "tool-b")["chosen"] is True


def test_legacy_component_array_replace_and_insert_preserve_other_bytes(tree):
    root, _ = tree
    path = root / "config/install.toml"
    before = path.read_text()
    put(tree, "install.component.tool-a.probe_argv", ["python3", "-V"], target="repo")
    put(tree, "install.component.tool-b.install_argv", ["echo", "hi there"], target="repo")
    after = tomllib.loads(path.read_text())
    expected = tomllib.loads(before)
    expected["component"][0]["probe_argv"] = ["python3", "-V"]
    expected["component"][1]["install_argv"] = ["echo", "hi there"]
    assert edit.values_equal(after, expected)
    assert component(tree, "tool-a")["probe_argv"] == ["python3", "-V"]
    assert 'probe_argv = ["python3", "-V"]' in path.read_text()
    assert path.read_text().count("\n[[component]]") == before.count("\n[[component]]")


def test_array_noop_leaves_bytes_and_mtime(tree):
    root, _ = tree
    path = root / "config/install.toml"
    before, mtime = path.read_bytes(), path.stat().st_mtime_ns
    result = put(tree, "install.component.tool-a.probe_argv", ["python3", "--version"], target="repo")
    assert not result.changed
    assert (path.read_bytes(), path.stat().st_mtime_ns) == (before, mtime)


def test_dry_run_writes_nothing(tree):
    root, _ = tree
    before = snapshot(root)
    result = put(tree, "install.component.tool-b.chosen", True, target="repo", dry_run=True)
    assert result.changed and result.dry_run
    assert snapshot(root) == before


@pytest.mark.parametrize("path,value", [
    ("install.component.tool-a.chosen", False),                 # hard cannot be unchosen
    ("install.component.tool-a.probe_argv", []),                # argv must be non-empty
    ("install.component.tool-a.probe_argv", [""]),
    ("install.component.tool-a.probe_argv", ["ok", 1]),
    ("install.component.tool-a.probe_argv", "python3"),         # string where array required
    ("install.component.tool-b.chosen", "true"),
    ("install.component.tool-b.class", "hard"),                 # not an allowlisted field
    ("install.component.tool-b.id", "other"),
    ("install.component.tool-b.install", "curl x | sh"),
    ("install.component.missing.chosen", True),                 # no row creation
    ("install.component.tool-b", True),
    ("install.component.chosen", True),
    ("install.login.example-login.command", "x"),
    ("install.jobs.nope.chosen", True),
    ("install.component[0].chosen", True),
    ("keys.EXAMPLE_API_KEY.verify_argv", []),
    ("keys.EXAMPLE_API_KEY.components", ["ok", 1]),
])
def test_unsupported_install_surfaces_leave_config_unchanged(tree, path, value):
    root, home = tree
    before = snapshot(root)
    with pytest.raises(ac.ConfigError):
        put(tree, path, value, target="repo")
    assert snapshot(root) == before
    assert not ac.default_local_path(home).exists()


def test_install_rows_refuse_local_target(tree):
    root, home = tree
    before = snapshot(root)
    with pytest.raises(ac.ConfigError, match="replace whole"):
        put(tree, "install.component.tool-b.chosen", True, target="local")
    assert snapshot(root) == before and not ac.default_local_path(home).exists()


def test_semantic_error_does_not_publish(tree):
    root, _ = tree
    before = snapshot(root)
    with pytest.raises(ac.ConfigError):
        put(tree, "install.component.tool-a.system_argv", ["apt-get", "bad\nline"], target="repo")
    assert snapshot(root) == before


# --- B. unified rows ---------------------------------------------------------------------------


def test_unified_component_and_job_rows(tree):
    root, _ = tree
    path = unified(root)
    put(tree, "install.component.extra.chosen", True, target="repo")
    put(tree, "install.component.fixture.platforms", ["mac", "linux"], target="repo")
    put(tree, "install.jobs.job-a.chosen", True, target="repo")
    put(tree, "install.jobs.job-a.set", ["x=1", "y=z w"], target="repo")
    text = path.read_text()
    assert "chosen = true  # keep me" in text          # trailing comment survives
    parsed = tomllib.loads(text)
    expected = tomllib.loads(UNIFIED)
    expected["install"]["component"][1]["chosen"] = True
    expected["install"]["component"][0]["platforms"] = ["mac", "linux"]
    expected["install"]["jobs"][0]["chosen"] = True
    expected["install"]["jobs"][0]["set"] = ["x=1", "y=z w"]
    assert edit.values_equal(parsed, expected)
    assert 'set = ["x=1", "y=z w"]' in text and "# old" not in text
    assert component(tree, "extra")["chosen"] is True


def test_real_catalog_job_choice_roundtrip(tree):
    root, home = tree
    shutil.copy2(REPO / "config/install.toml", root / "config/install.toml")
    text = (root / "config/install.toml").read_text()
    job = next(j for j in tomllib.loads(text)["install"]["jobs"] if "chosen" in j)
    flipped = not job["chosen"]
    put(tree, f"install.jobs.{job['name']}.chosen", flipped, target="repo")
    after = tomllib.loads((root / "config/install.toml").read_text())
    expected = tomllib.loads(text)
    next(j for j in expected["install"]["jobs"] if j["name"] == job["name"])["chosen"] = flipped
    assert edit.values_equal(after, expected)
    loaded = ac.load_effective(root=root, home=home, domains=ac.CATALOG_DOMAINS).data
    assert next(j for j in loaded["install"]["jobs"] if j["name"] == job["name"])["chosen"] is flipped


def test_quoted_identity_with_dot(tree):
    root, _ = tree
    path = root / "config/install.toml"
    path.write_text(path.read_text().replace('id = "tool-b"', 'id = "tool.b"'))
    put(tree, 'install.component."tool.b".chosen', True, target="repo")
    assert component(tree, "tool.b")["chosen"] is True


# --- C. key arrays and identities ---------------------------------------------------------------


@pytest.mark.parametrize("base", ["legacy", "unified"])
@pytest.mark.parametrize("target", ["repo"])
def test_key_arrays_all_layers(tree, base, target):
    root, _ = tree
    if base == "unified":
        unified(root)
    put(tree, "keys.EXAMPLE_API_KEY.verify_argv", ["curl", "-fsS", "https://example.invalid"], target=target)
    put(tree, "keys.EXAMPLE_API_KEY.components", ["fixture"] if base == "unified" else ["tool-a", "tool-c"],
        target=target)
    row = key(tree, "EXAMPLE_API_KEY")
    assert row["verify_argv"] == ["curl", "-fsS", "https://example.invalid"]
    assert row["components"] == (["fixture"] if base == "unified" else ["tool-a", "tool-c"])


@pytest.mark.parametrize("base", ["legacy", "unified"])
@pytest.mark.parametrize("target", ["repo", "local"])
def test_new_key_identity_needs_flag_and_is_created(tree, base, target):
    root, _ = tree
    if base == "unified":
        unified(root)
    before = snapshot(root)
    with pytest.raises(ac.ConfigError, match="--create-key"):
        put(tree, "keys.NEW_API_KEY.notes", "n", target=target)
    assert snapshot(root) == before
    put(tree, "keys.NEW_API_KEY.notes", "fresh", target=target, create_key=True)
    if target == "repo":
        put(tree, "keys.NEW_API_KEY.verify_argv", ["probe", "--auth"], target=target)
    row = key(tree, "NEW_API_KEY")
    assert row["notes"] == "fresh" and row.get("verify_argv") == (["probe", "--auth"] if target == "repo" else None)
    assert key(tree, "EXAMPLE_API_KEY")["name"] == "EXAMPLE_API_KEY"


def test_legacy_create_appends_one_row_and_keeps_all_other_bytes(tree):
    root, _ = tree
    path = root / "config/install.toml"
    before = path.read_text()
    put(tree, "keys.NEW_API_KEY.notes", "fresh", target="repo", create_key=True)
    after = path.read_text()
    assert after.startswith(before)
    assert tomllib.loads(after)["key"][-1] == {"name": "NEW_API_KEY", "notes": "fresh"}


@pytest.mark.parametrize("name", ["bad-name", "1ABC", "A B", 'A"B', "", "A.B"])
def test_key_identity_name_is_restricted(tree, name):
    root, _ = tree
    before = snapshot(root)
    with pytest.raises(ac.ConfigError):
        put(tree, f"keys.{json.dumps(name)}.notes", "n", target="repo", create_key=True)
    assert snapshot(root) == before


def test_create_key_flag_rejected_elsewhere(tree):
    with pytest.raises(ac.ConfigError, match="--create-key"):
        put(tree, "install.component.tool-b.chosen", True, target="repo", create_key=True)


# --- D. context_budget.dirs ---------------------------------------------------------------------


@pytest.mark.parametrize("base", ["legacy", "unified"])
@pytest.mark.parametrize("target", ["repo", "local"])
def test_context_dirs_replace(tree, base, target):
    root, home = tree
    if base == "unified":
        unified(root)
    put(tree, "context_budget.dirs", ["~/a", "~/b"], target=target)
    cfg = ac.context_budget_config(
        ac.load_effective(root=root, home=home, domains=ac.CONTEXT_BUDGET_DOMAINS).data)
    assert cfg["dirs"] == ["~/a", "~/b"]


def test_context_dirs_insert_precedes_first_header(tree):
    root, home = tree
    path = root / "config/context-budget.toml"
    path.write_text("# only budgets\n[budget]\ntotal = 1  # [not a header\n")
    put(tree, "context_budget.dirs", ["~/x"], target="repo")
    parsed = tomllib.loads(path.read_text())
    assert parsed == {"dirs": ["~/x"], "budget": {"total": 1}}
    assert path.read_text().startswith("# only budgets\ndirs = ")


def test_context_dirs_collision_with_scalar_budget_row_refused(tree):
    root, _ = tree
    before = snapshot(root)
    with pytest.raises(ac.ConfigError):
        put(tree, "context_budget.dirs", ["total"], target="repo")
    assert snapshot(root) == before


# --- E. CLI --------------------------------------------------------------------------------------


def _cli(tree, *args):
    root, home = tree
    env = {k: v for k, v in os.environ.items() if k not in {"ROUTING_POLICY", "GATES_TOML", "MODEL_TIERS_TOML"}}
    env["HOME"] = str(home)
    return subprocess.run([sys.executable, "-I", "-B", str(BIN / "ade-config"), "--root", str(root), *args],
                          capture_output=True, text=True, env=env, cwd=str(REPO), check=False)


def test_cli_array_choice_and_create_key(tree):
    root, _ = tree
    r = _cli(tree, "set", "install.component.tool-b.install_argv", '["echo", "x"]', "--target", "repo", "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["after"] == ["echo", "x"]
    r = _cli(tree, "set", "install.component.tool-b.chosen", "true", "--target", "repo")
    assert r.returncode == 0, r.stderr
    r = _cli(tree, "set", "keys.CLI_KEY.notes", "n", "--string", "--target", "repo")
    assert r.returncode == 1 and "--create-key" in r.stderr
    r = _cli(tree, "set", "keys.CLI_KEY.notes", "n", "--string", "--target", "repo", "--create-key")
    assert r.returncode == 0, r.stderr
    assert component(tree, "tool-b")["chosen"] is True
    assert key(tree, "CLI_KEY")["notes"] == "n"
    r = _cli(tree, "set", "install.component.tool-b.install_argv", '{a=1}', "--target", "repo")
    assert r.returncode == 1


def test_parse_cli_value_arrays_are_string_arrays_only():
    assert edit.parse_cli_value('["a", "b"]', as_string=False) == ["a", "b"]
    for bad in ("[1]", '[""]', "[[ \"a\" ]]", "{a=1}"):
        with pytest.raises(edit.EditError):
            edit.parse_cli_value(bad, as_string=False)


def test_scalar_path_rejects_array_value(tree):
    root, _ = tree
    before = snapshot(root)
    with pytest.raises(ac.ConfigError):
        put(tree, "keys.EXAMPLE_API_KEY.notes", ["x"], target="repo")
    assert snapshot(root) == before


def test_get_path_selects_catalog_rows_by_identity():
    data = {"install": {"component": [{"id": "a", "chosen": True}, {"id": "b"}]}}
    assert ac.get_path(data, "install.component.a.chosen") is True
    assert ac.get_path(data, "install.component.1.id") == "b"
    with pytest.raises(ac.ConfigError):
        ac.get_path(data, "install.component.zzz.chosen")


# --- F. adversary follow-ups (2026-11-12) ---------------------------------------------------------


def test_key_arrays_refuse_local_target(tree):
    root, home = tree
    before = snapshot(root)
    with pytest.raises(ac.ConfigError, match="repo-reviewed"):
        put(tree, "keys.EXAMPLE_API_KEY.verify_argv", ["sh", "-c", "x"], target="local")
    with pytest.raises(ac.ConfigError, match="repo-reviewed"):
        put(tree, "keys.NEW_KEY.components", ["tool-a"], target="local", create_key=True)
    assert snapshot(root) == before and not ac.default_local_path(home).exists()


@pytest.mark.parametrize("value", [["windows"], ["linux", "darwin"], [""]])
def test_platforms_must_be_known_names(tree, value):
    root, _ = tree
    before = snapshot(root)
    with pytest.raises(ac.ConfigError):
        put(tree, "install.component.tool-a.platforms", value, target="repo")
    assert snapshot(root) == before


@pytest.mark.parametrize("bad", ["a\x1bb", "a\tb", "a b", "a\x7fb", "a\x85b"])
def test_array_values_refuse_all_control_characters(bad):
    with pytest.raises(edit.EditError):
        edit.encode_toml_value([bad])


def test_cli_export_write_race_is_a_clean_error(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    r = subprocess.run([sys.executable, "-I", "-B", str(BIN / "ade-config"), "--root", str(root), "export-unified", "--write"],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 1 and "Traceback" not in r.stderr
