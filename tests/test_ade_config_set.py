"""ade-config set: comment-preserving atomic scalar editor.

All writes use temp HOME / temp roots. Never touches the real operator local.toml
or live lead flags in the checkout's routing.toml (repo-target tests copy fixtures).
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BIN = REPO / "bin"
sys.path.insert(0, str(BIN))
import ade_config as ac  # noqa: E402
import ade_config_edit as ace  # noqa: E402


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("ROUTING_POLICY", raising=False)
    monkeypatch.delenv("GATES_TOML", raising=False)
    return h


def _run_cli(*args: str, home: Path, root: Path | None = None, env: dict | None = None):
    e = {**os.environ, "HOME": str(home), "PATH": str(BIN) + os.pathsep + os.environ.get("PATH", "")}
    if env:
        e.update(env)
    argv = [sys.executable, "-I", "-B", str(BIN / "ade-config"), *args]
    if root is not None and "--root" not in args:
        argv[4:4] = ["--root", str(root)]
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        env=e,
        cwd=str(REPO),
        check=False,
    )


def _local(home: Path) -> Path:
    return home / ".config" / "djbclark-ade" / "local.toml"


def test_parse_cli_value_types_and_string_flag():
    assert ace.parse_cli_value("false", as_string=False) is False
    assert ace.parse_cli_value("true", as_string=False) is True
    assert ace.parse_cli_value("2", as_string=False) == 2
    assert ace.parse_cli_value("1.5", as_string=False) == 1.5
    assert ace.parse_cli_value('"x"', as_string=False) == "x"
    assert ace.parse_cli_value("false", as_string=True) == "false"
    with pytest.raises(ace.EditError):
        ace.parse_cli_value("{a=1}", as_string=False)
    with pytest.raises(ace.EditError):
        ace.parse_cli_value("[1]", as_string=False)


def test_bool_versus_int_equality():
    assert ace.values_equal(True, True)
    assert not ace.values_equal(True, 1)
    assert not ace.values_equal(0, False)
    assert not ace.values_equal(1, 1.0)  # int and float stay distinct
    assert not ace.values_equal({"a": True}, {"a": 1})


def test_int_to_float_is_a_real_change(home):
    path = _local(home)
    path.parent.mkdir(parents=True)
    path.write_text("[gates]\n[gates.frontier]\nfrontier1_judged = 1\n")
    # schema allows gates.frontier numbers; local partial tree OK
    result = ace.set_scalar(
        "gates.frontier.frontier1_judged", 1.0, target="local", root=REPO, home=home
    )
    assert result.changed is True
    assert isinstance(ac.read_toml(path)["gates"]["frontier"]["frontier1_judged"], float)


def test_local_set_creates_file_preserves_comments_and_quotes(home, tmp_path):
    path = _local(home)
    path.parent.mkdir(parents=True)
    path.write_text(
        "# keep me\n"
        "[lead]\n"
        "# switch\n"
        'note = "not # a comment"\n'
        "fable_lead = true\n"
        "\n"
        "[routing]\n"
        'kinds = ["code"]\n'
    )
    before = path.read_text()
    mtime = path.stat().st_mtime_ns
    time.sleep(0.02)
    result = ace.set_scalar("lead.fable_lead", False, target="local", root=REPO, home=home)
    assert result.changed is True
    assert result.adoption == "recorded-only"
    text = path.read_text()
    assert "# keep me" in text
    assert "# switch" in text
    assert 'note = "not # a comment"' in text
    assert "fable_lead = false" in text
    assert 'kinds = ["code"]' in text
    assert text != before
    # comments outside the value span untouched
    assert text.split("fable_lead = ")[0] == before.split("fable_lead = ")[0]


def test_local_noop_preserves_mtime(home):
    path = _local(home)
    path.parent.mkdir(parents=True)
    path.write_text("[lead]\nfable_lead = false\n")
    os.utime(path, (1_700_000_000, 1_700_000_000))
    before = path.stat()
    result = ace.set_scalar("lead.fable_lead", False, target="local", root=REPO, home=home)
    assert result.changed is False
    after = path.stat()
    assert after.st_mtime_ns == before.st_mtime_ns
    assert after.st_size == before.st_size


def test_fake_header_inside_multiline_string_not_a_table(home):
    path = _local(home)
    path.parent.mkdir(parents=True)
    path.write_text(
        "[lead]\n"
        'doc = """\n'
        "[lead]\n"
        "fable_lead = true\n"
        '"""\n'
        "fable_lead = true\n"
    )
    ace.set_scalar("lead.fable_lead", False, target="local", root=REPO, home=home)
    text = path.read_text()
    # The fake header inside the string stays; only the real assignment changes.
    assert '"""\n[lead]\nfable_lead = true\n"""' in text
    assert text.strip().endswith("fable_lead = false")


def test_unrelated_arrays_preserved_on_repo_routing_set(home, tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    shutil.copy(REPO / "config" / "ade.schema.json", root / "config" / "ade.schema.json")
    routing = root / "config" / "routing.toml"
    routing.write_text(
        "# header comment\n"
        "[routing]\n"
        'kinds = ["judgment", "code"]\n'
        "burn_first_min = 40.0\n"
        "\n"
        "[lead]\n"
        'model = "opus"\n'
        'effort = "high"\n'
        'pipeline_model = "sonnet"\n'
        'pipeline_effort = "medium"\n'
        "fable_lead = true\n"
        "\n"
        "[dispatch]\n"
        "x = 1\n"
        "\n"
        "[hermes]\n"
        "y = 1\n"
        "\n"
        "[calibrate]\n"
        "z = 1\n"
        "\n"
        "[[service]]\n"
        'name = "claude"\n'
        'cli = "claude"\n'
        'good_at = ["code"]\n'
        'billing = "sub"\n'
        "\n"
        "[[service]]\n"
        'name = "codex"\n'
        'cli = "codex"\n'
        'good_at = ["code"]\n'
        'billing = "sub"\n'
    )
    # Minimal tables required by validate_legacy_routing_shape — dispatch/hermes/calibrate present.
    result = ace.set_scalar(
        "lead.fable_lead", False, target="repo", root=root, home=home
    )
    assert result.target.kind == "legacy_routing"
    text = routing.read_text()
    assert "# header comment" in text
    assert 'kinds = ["judgment", "code"]' in text
    assert 'name = "claude"' in text
    assert 'name = "codex"' in text
    assert "fable_lead = false" in text
    data = ac.read_toml(routing)
    assert data["lead"]["fable_lead"] is False
    assert len(data["service"]) == 2


def test_repo_gates_scalar_and_refuse_inline_table_leaf(home, tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    shutil.copy(REPO / "config" / "ade.schema.json", root / "config" / "ade.schema.json")
    gates = root / "config" / "gates.toml"
    gates.write_text(
        "[frontier]\n"
        "frontier1_judged = 1\n"
        "\n"
        "[floors.frontier]\n"
        'frontier1_judged = { loosen = "higher", bound = 1 }\n'
    )
    ace.set_scalar(
        "gates.frontier.frontier1_judged", 0, target="repo", root=root, home=home
    )
    assert "frontier1_judged = 0" in gates.read_text()
    with pytest.raises(ace.EditError, match="table|inline|simple"):
        ace.set_scalar(
            "gates.floors.frontier.frontier1_judged.bound",
            2,
            target="repo",
            root=root,
            home=home,
        )


def test_repo_context_budget_scalar_strips_prefix(home, tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    shutil.copy(REPO / "config" / "ade.schema.json", root / "config" / "ade.schema.json")
    cb = root / "config" / "context-budget.toml"
    cb.write_text('dirs = ["~/src/djbclark-ade"]\n[budget]\ntotal = 30000\n')
    result = ace.set_scalar(
        "context_budget.budget.total", 31000, target="repo", root=root, home=home
    )
    assert result.target.kind == "legacy_context_budget"
    assert result.target.path == cb
    text = cb.read_text()
    assert "total = 31000" in text
    assert "dirs = " in text
    data = ac.read_toml(cb)
    assert data["budget"]["total"] == 31000


def test_unified_ade_toml_is_repo_source_when_present(home, tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    shutil.copy(REPO / "config" / "ade.schema.json", root / "config" / "ade.schema.json")
    ade = root / "config" / "ade.toml"
    ade.write_text(
        "schema_version = 1\n"
        "[lead]\n"
        "fable_lead = true\n"
    )
    # Legacy files also exist; unified must win as the set target.
    (root / "config" / "routing.toml").write_text("[routing]\n")
    result = ace.set_scalar(
        "lead.fable_lead", False, target="repo", root=root, home=home
    )
    assert result.target.kind == "unified"
    assert result.target.path == ade
    assert "fable_lead = false" in ade.read_text()


def test_invalid_schema_refused(home):
    path = _local(home)
    path.parent.mkdir(parents=True)
    path.write_text("schema_version = 1\nextra_unknown = 1\n")
    # additionalProperties false at root: unknown key already present — editing another key still validates whole file
    with pytest.raises(ac.ConfigError, match="unknown key"):
        ace.set_scalar("lead.fable_lead", False, target="local", root=REPO, home=home)


def test_duplicate_service_identity_refused_on_local(home):
    path = _local(home)
    path.parent.mkdir(parents=True)
    path.write_text(
        "[[service]]\n"
        'name = "claude"\n'
        "[[service]]\n"
        'name = "claude"\n'
        "[lead]\n"
        "fable_lead = true\n"
    )
    with pytest.raises(ac.ConfigError, match="duplicate"):
        ace.set_scalar("lead.fable_lead", False, target="local", root=REPO, home=home)


def test_symlink_refused(home, tmp_path):
    real = tmp_path / "real.toml"
    real.write_text("[lead]\nfable_lead = true\n")
    path = _local(home)
    path.parent.mkdir(parents=True)
    path.symlink_to(real)
    with pytest.raises(ace.EditError, match="symlink"):
        ace.set_scalar("lead.fable_lead", False, target="local", root=REPO, home=home)
    assert real.read_text() == "[lead]\nfable_lead = true\n"


def test_mode_preserved(home):
    path = _local(home)
    path.parent.mkdir(parents=True)
    path.write_text("[lead]\nfable_lead = true\n")
    os.chmod(path, 0o640)
    ace.set_scalar("lead.fable_lead", False, target="local", root=REPO, home=home)
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_dry_run_writes_nothing(home):
    path = _local(home)
    path.parent.mkdir(parents=True)
    original = "[lead]\nfable_lead = true\n"
    path.write_text(original)
    result = ace.set_scalar(
        "lead.fable_lead", False, target="local", root=REPO, home=home, dry_run=True
    )
    assert result.changed is True
    assert result.dry_run is True
    assert path.read_text() == original
    assert result.text_after is not None
    assert "fable_lead = false" in result.text_after


def test_injected_replace_failure_keeps_original(home, monkeypatch):
    path = _local(home)
    path.parent.mkdir(parents=True)
    original = "[lead]\nfable_lead = true\n"
    path.write_text(original)

    def boom(src, dst):
        raise OSError("injected replace failure")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="injected replace failure"):
        ace.set_scalar("lead.fable_lead", False, target="local", root=REPO, home=home)
    assert path.read_text() == original
    # temp files beside the target cleaned up
    leftovers = list(path.parent.glob(path.name + ".*"))
    leftovers = [p for p in leftovers if p.name != path.name + ".lock"]
    assert leftovers == []


def test_concurrency_serialized(home):
    path = _local(home)
    path.parent.mkdir(parents=True)
    path.write_text("[lead]\nfable_lead = true\n")
    errors: list[BaseException] = []

    def worker(val: bool):
        try:
            for _ in range(8):
                ace.set_scalar("lead.fable_lead", val, target="local", root=REPO, home=home)
                val = not val
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(False,)), threading.Thread(target=worker, args=(True,))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    data = ac.read_toml(path)
    assert isinstance(data["lead"]["fable_lead"], bool)


def test_cli_set_json_and_readonly_commands_unchanged(home, tmp_path):
    # set
    proc = _run_cli(
        "set", "lead.fable_lead", "false", "--json",
        home=home, root=REPO,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["changed"] is True
    assert payload["target"] == "local"
    assert payload["adoption"] == "recorded-only"
    assert payload["after"] is False
    assert _local(home).is_file()

    # check/get/diff remain no-write relative to a sentinel beside local
    sentinel = home / "sentinel"
    sentinel.write_text("x")
    before = sentinel.stat().st_mtime_ns
    assert _run_cli("check", "--json", home=home, root=REPO).returncode == 0
    g = _run_cli("get", "lead.fable_lead", "--json", home=home, root=REPO)
    assert g.returncode == 0
    assert json.loads(g.stdout)["value"] is False
    d = _run_cli("diff", "--json", home=home, root=REPO)
    assert d.returncode == 0
    assert sentinel.stat().st_mtime_ns == before


def test_cli_string_flag_and_dry_run(home):
    proc = _run_cli(
        "set", "lead.model", "false", "--string", "--dry-run", "--json",
        home=home, root=REPO,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["after"] == "false"
    assert payload["dry_run"] is True
    assert not _local(home).exists()


def test_refuses_env_override_as_implicit_target(home, tmp_path, monkeypatch):
    # ROUTING_POLICY must not become a write target or suppress normal local precedence tricks.
    alt = tmp_path / "alt-routing.toml"
    alt.write_text(
        "[routing]\nkinds=[]\n[dispatch]\n[hermes]\n[calibrate]\n"
        "[[service]]\nname='claude'\ncli='c'\ngood_at=['code']\nbilling='sub'\n"
        "[lead]\nmodel='opus'\neffort='high'\npipeline_model='sonnet'\nfable_lead=true\n"
    )
    monkeypatch.setenv("ROUTING_POLICY", str(alt))
    result = ace.set_scalar("lead.fable_lead", False, target="local", root=REPO, home=home)
    assert result.target.path == _local(home)
    assert alt.read_text().endswith("fable_lead=true\n") or "fable_lead = true" in alt.read_text()
    # local file got the write
    assert "fable_lead = false" in _local(home).read_text()


def test_repo_set_does_not_create_ade_toml(home, tmp_path):
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    shutil.copy(REPO / "config" / "ade.schema.json", root / "config" / "ade.schema.json")
    # No routing.toml either → refuse create
    with pytest.raises(ace.EditError, match="refuses to create"):
        ace.set_scalar("lead.fable_lead", False, target="repo", root=root, home=home)
    assert not (root / "config" / "ade.toml").exists()


def test_service_path_refused(home):
    with pytest.raises(ace.EditError, match="service"):
        ace.set_scalar("service.0.name", "x", target="local", root=REPO, home=home)


def test_insert_new_key_in_existing_local_table(home):
    path = _local(home)
    path.parent.mkdir(parents=True)
    path.write_text("[lead]\nmodel = \"opus\"\n")
    ace.set_scalar("lead.fable_lead", True, target="local", root=REPO, home=home)
    text = path.read_text()
    assert 'model = "opus"' in text
    assert "fable_lead = true" in text


def test_real_repo_routing_copy_preserves_complex_bytes(home, tmp_path):
    """Edit a full copy of the live routing.toml; unrelated complex TOML stays intact."""
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    shutil.copy(REPO / "config" / "ade.schema.json", root / "config" / "ade.schema.json")
    shutil.copy(REPO / "config" / "routing.toml", root / "config" / "routing.toml")
    routing = root / "config" / "routing.toml"
    before = routing.read_bytes()
    ace.set_scalar("lead.fable_lead", False, target="repo", root=root, home=home)
    after = routing.read_bytes()
    assert before != after
    # Only the scalar token for fable_lead should change among ASCII lines of that key.
    before_lines = before.decode().splitlines()
    after_lines = after.decode().splitlines()
    diffs = [
        (a, b) for a, b in zip(before_lines, after_lines) if a != b
    ]
    assert len(before_lines) == len(after_lines)
    assert len(diffs) == 1
    assert "fable_lead" in diffs[0][0] and "true" in diffs[0][0]
    assert "fable_lead" in diffs[0][1] and "false" in diffs[0][1]
    # Still validates as legacy routing with all services present.
    data = ac.load_legacy_routing(routing)
    assert data["lead"]["fable_lead"] is False
    assert isinstance(data["service"], list) and len(data["service"]) >= 2
