"""Namespace-aware claims for skills/research/scripts/research_check.py."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "research" / "scripts" / "research_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("research_check", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_run(path: Path, eid: str, report: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "evidence.jsonl").write_text(
        json.dumps({"id": eid, "claim": "c", "quote": "q", "source_id": "s", "url": "https://ex",
                    "ids": {}, "locator": "", "kind": "primary", "family": "f",
                    "date_fetched": "2026-01-01", "verified_quote": True})
        + "\n",
        encoding="utf-8",
    )
    (path / "report.md").write_text(report, encoding="utf-8")


def test_claims_local_ok(tmp_path: Path) -> None:
    mod = _load()
    run = tmp_path / "alpha"
    _write_run(run, "E0001", "Fact [E0001].\n")
    assert mod.cmd_claims(run) == 0


def test_claims_bare_sibling_resolves(tmp_path: Path) -> None:
    mod = _load()
    a = tmp_path / "alpha"
    b = tmp_path / "beta"
    _write_run(a, "E0001", "Uses sibling [E0002].\n")
    _write_run(b, "E0002", "Own [E0002].\n")
    assert mod.cmd_claims(a) == 0


def test_claims_namespaced_sibling(tmp_path: Path) -> None:
    mod = _load()
    a = tmp_path / "alpha"
    b = tmp_path / "beta"
    _write_run(a, "E0001", "Uses [beta/E0002].\n")
    _write_run(b, "E0002", "Own [E0002].\n")
    assert mod.cmd_claims(a) == 0


def test_claims_unknown_still_fails(tmp_path: Path) -> None:
    mod = _load()
    run = tmp_path / "alpha"
    _write_run(run, "E0001", "Missing [E9999].\n")
    assert mod.cmd_claims(run) == 1


def test_claims_ambiguous_bare_sibling_fails(tmp_path: Path) -> None:
    """Same bare id in two siblings is not unique; bare cite must fail."""
    mod = _load()
    a = tmp_path / "alpha"
    b = tmp_path / "beta"
    c = tmp_path / "gamma"
    _write_run(a, "E0001", "Ambiguous [E0009].\n")
    _write_run(b, "E0009", "b [E0009].\n")
    _write_run(c, "E0009", "c [E0009].\n")
    assert mod.cmd_claims(a) == 1


def test_claims_sibling_internal_dupe_fails(tmp_path: Path) -> None:
    mod = _load()
    a = tmp_path / "alpha"
    b = tmp_path / "beta"
    _write_run(a, "E0001", "Uses [beta/E0002].\n")
    b.mkdir(parents=True, exist_ok=True)
    row = {
        "id": "E0002", "claim": "c", "quote": "q", "source_id": "s", "url": "https://ex",
        "ids": {}, "locator": "", "kind": "primary", "family": "f",
        "date_fetched": "2026-01-01", "verified_quote": True,
    }
    import json
    (b / "evidence.jsonl").write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
    (b / "report.md").write_text("Own [E0002].\n", encoding="utf-8")
    assert mod.cmd_claims(a) == 1


def test_numbers_accepts_sibling_quote(tmp_path: Path) -> None:
    mod = _load()
    a = tmp_path / "alpha"
    b = tmp_path / "beta"
    a.mkdir(parents=True, exist_ok=True)
    b.mkdir(parents=True, exist_ok=True)
    import json
    (a / "evidence.jsonl").write_text(
        json.dumps({"id": "E0001", "claim": "c", "quote": "no figure here", "source_id": "s",
                    "url": "https://ex", "ids": {}, "locator": "", "kind": "primary", "family": "f",
                    "date_fetched": "2026-01-01", "verified_quote": True}) + "\n",
        encoding="utf-8",
    )
    (a / "report.md").write_text("There were 42 participants [beta/E0002].\n", encoding="utf-8")
    (b / "evidence.jsonl").write_text(
        json.dumps({"id": "E0002", "claim": "c", "quote": "42 participants enrolled", "source_id": "s",
                    "url": "https://ex", "ids": {}, "locator": "", "kind": "primary", "family": "f",
                    "date_fetched": "2026-01-01", "verified_quote": True}) + "\n",
        encoding="utf-8",
    )
    (b / "report.md").write_text("Own [E0002].\n", encoding="utf-8")
    assert mod.cmd_numbers(a) == 0
