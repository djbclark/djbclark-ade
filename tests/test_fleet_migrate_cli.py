"""CLI tests never have access to the operator's HOME or live transports."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "libexec"))
from fleet_migrate.cli import main

FIXTURE = ROOT / "tests/fixtures/fleet_migrate/inventory.json"


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("PASEO_AGENT_ID", raising=False)
    monkeypatch.delenv("HERDR_PANE_ID", raising=False)


def draft(tmp_path, capsys):
    out = tmp_path / "plans" / "example.json"
    rc = main(["plan", "--inventory", str(FIXTURE), "--from-tui", "omp", "--from-vendor", "anthropic",
               "--to-tui", "pi", "--to-vendor", "openai", "--include-herdr", "--output", str(out)])
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    return out, summary


def test_plan_validate_and_dry_run_without_live_actions(tmp_path, capsys):
    out, summary = draft(tmp_path, capsys)
    assert summary["selected"] == 1
    assert summary["recipients"] == 2
    assert summary["execution_authorized"] is False
    assert main(["validate", str(out), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["runtime_ready"] is False
    assert main(["apply", str(out), "--approved-digest", summary["digest"]]) == 4
    run = json.loads(capsys.readouterr().out)
    assert run["state"] == "BLOCKED"
    assert run["journal"][0]["external_actions"] == 0
    assert main(["reconcile", run["run_id"], "--dry-run"]) == 0
    capsys.readouterr()
    assert main(["notify", run["run_id"], "--retry-due"]) == 4
    assert json.loads(capsys.readouterr().out)["messages_sent"] == 0


def test_default_discovery_is_explicit_refusal_not_invented_live_inventory(tmp_path, capsys):
    assert main(["plan", "--from-tui", "omp", "--to-tui", "pi", "--to-vendor", "openai",
                 "--output", str(tmp_path / "plan.json")]) == 4
    assert json.loads(capsys.readouterr().out)["reason"] == "authoritative-live-inventory-adapter-not-admitted"
    assert not (tmp_path / "plan.json").exists()


def test_invalid_approval_cannot_create_state(tmp_path, capsys):
    out, _ = draft(tmp_path, capsys)
    assert main(["apply", str(out), "--approved-digest", "wrong"]) == 2
    assert not (tmp_path / ".local/state/ade/fleet-migrate").exists()


def test_repeat_apply_reuses_same_blocked_receipt(tmp_path, capsys):
    out, summary = draft(tmp_path, capsys)
    argv = ["apply", str(out), "--approved-digest", summary["digest"]]
    assert main(argv) == 4
    first = json.loads(capsys.readouterr().out)
    assert main(argv) == 4
    assert json.loads(capsys.readouterr().out) == first
    assert main(["reconcile", first["run_id"], "--apply", "--approved-digest", "wrong"]) == 2


def test_plan_output_never_clobbers_existing_artifacts(tmp_path, capsys):
    out, _ = draft(tmp_path, capsys)
    old = out.read_bytes()
    assert main(["plan", "--inventory", str(FIXTURE), "--from-tui", "omp", "--to-tui", "pi",
                 "--to-vendor", "openai", "--output", str(out)]) == 2
    assert out.read_bytes() == old


def test_untrusted_artifact_errors_do_not_echo_contents_or_paths(tmp_path, capsys):
    p = tmp_path / "credential-in-filename"
    p.write_text("credential-in-json")
    assert main(["validate", str(p)]) == 2
    assert "credential" not in capsys.readouterr().out
