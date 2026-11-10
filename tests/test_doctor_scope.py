"""Component doctor selection must not probe the rest of the installation."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "bin"))
import ade_install as ai

loader = importlib.machinery.SourceFileLoader("doctor_cli", str(REPO / "bin/ade-install"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)


@pytest.fixture
def catalog(tmp_path):
    return ai.Catalog(
        data={"component": [
            {"id": "hermes", "class": "offered", "chosen": True,
             "probe_argv": ["hermes", "doctor"]},
            {"id": "other", "class": "hard", "probe_argv": ["other", "--version"]},
            {"id": "unchosen", "class": "offered", "chosen": False,
             "paseo_plugin": "unchosen-plugin"},
        ], "key": [{"name": "EXAMPLE"}], "login": [{"id": "login"}],
           "install": {"jobs": [{"name": "job"}]}},
        path=tmp_path / "install.toml", root=tmp_path,
    )


@pytest.fixture
def no_global_probes(monkeypatch):
    for name in ("observe_key", "observe_login", "observe_context_size_nudge",
                 "observe_credential_bak", "observe_pi_pools", "_paseo_runner"):
        monkeypatch.setattr(ai, name, Mock(side_effect=AssertionError("unrelated probe: " + name)))


@pytest.mark.parametrize("exit_code", [0, 7])
def test_selected_component_uses_only_its_probe(catalog, no_global_probes, monkeypatch, exit_code):
    monkeypatch.setattr(ai, "_probe_executable_missing", lambda _: False)
    runner = Mock(return_value=subprocess.CompletedProcess([], exit_code, "fixture result", ""))
    observations, rc = ai.doctor(catalog, component_ids=["hermes"], runner=runner)
    runner.assert_called_once_with(["hermes", "doctor"], catalog.root)
    assert [o.id for o in observations if o.kind == "component"] == ["hermes"]
    assert rc == (0 if exit_code == 0 else 1)


def test_unchosen_plugin_never_probes(catalog, no_global_probes, monkeypatch):
    observe = Mock(side_effect=AssertionError("unchosen component probed"))
    monkeypatch.setattr(ai, "observe_component", observe)
    observations, rc = ai.doctor(catalog, component_ids=["unchosen"])
    assert rc == 0
    assert observations[-1].status == "unchosen"
    observe.assert_not_called()


@pytest.mark.parametrize("ids", [["hermes", "typo"], []])
def test_invalid_selection_fails_before_any_probe(catalog, no_global_probes, monkeypatch, ids):
    observe = Mock(side_effect=AssertionError("selection was not validated first"))
    monkeypatch.setattr(ai, "observe_component", observe)
    with pytest.raises(ai.InstallError):
        ai.doctor(catalog, component_ids=ids)
    observe.assert_not_called()


@pytest.mark.parametrize("ids", [None, ["hermes"], ["hermes", "hermes", "unchosen"]])
def test_cli_selector_and_json_scope(catalog, monkeypatch, capsys, ids):
    monkeypatch.setattr(ai, "load_catalog", lambda **_: catalog)
    doctor = Mock(return_value=([], 0))
    monkeypatch.setattr(ai, "doctor", doctor)
    args = ["doctor", "--json"]
    for cid in ids or []:
        args += ["--id", cid]
    assert cli.main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    selected = list(dict.fromkeys(ids)) if ids is not None else None
    doctor.assert_called_once_with(catalog, component_ids=selected)
    assert payload["scope"] == ({"kind": "all"} if selected is None else
                                {"kind": "components", "component_ids": selected})
    assert payload["ok"] is True


def test_cli_unknown_selection_reports_failed_scope(catalog, monkeypatch, capsys):
    monkeypatch.setattr(ai, "load_catalog", lambda **_: catalog)
    assert cli.main(["doctor", "--id", "typo", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == {"kind": "components", "component_ids": ["typo"]}
    assert payload["ok"] is False
    assert "unknown doctor component" in payload["errors"][0]


def test_cli_scoped_text_does_not_claim_overall_health(catalog, monkeypatch, capsys):
    monkeypatch.setattr(ai, "load_catalog", lambda **_: catalog)
    monkeypatch.setattr(ai, "doctor", Mock(return_value=([], 0)))
    assert cli.main(["doctor", "--id", "hermes"]) == 0
    text = capsys.readouterr().out
    assert "components: hermes" in text
    assert "not whole-installation health" in text


@pytest.mark.skipif(shutil.which("just") is None, reason="just not on PATH")
@pytest.mark.parametrize("component", [None, "hermes", "name with spaces;echo unsafe"])
def test_just_doctor_forwards_one_literal_component(tmp_path, component):
    # Reuse the actual recipe and a fake CLI, so no live doctor is run.
    recipe = (REPO / "justfile").read_text().split("[positional-arguments]\ndoctor ", 1)[1].split("\ninstall ", 1)[0]
    (tmp_path / "justfile").write_text('root := justfile_directory()\n[positional-arguments]\ndoctor ' + recipe)
    (tmp_path / "bin").mkdir()
    capture = tmp_path / "args.json"
    tool = tmp_path / "bin/ade-install"
    tool.write_text("#!" + sys.executable + "\nimport json, sys\nfrom pathlib import Path\n"
                    + "Path(" + repr(str(capture)) + ").write_text(json.dumps(sys.argv[1:]))\n")
    tool.chmod(0o755)
    result = subprocess.run([shutil.which("just"), "doctor", *([] if component is None else [component])],
                            cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(capture.read_text()) == ["doctor", "--root", str(tmp_path),
                                              *([] if component is None else ["--id", component])]
