"""Fixture-labeled Mac proof harness tests (NOT live Mac stdout).

Carried #33 residual (2026-11-10): CI proves mac_proofs FAILCLOSED shape and the
capture harness contract using tests/fixtures/wave6-mac-proofs/. Every fixture
file is labeled FIXTURE — these tests must never treat them as a Mac live cycle.
Live replacement: bin/wave6-mac-proof-capture --live (Darwin only).
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "bin" / "wave6-mac-proof-capture"
DELETE_CHECK = ROOT / "bin" / "wave6-delete-check"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "wave6-mac-proofs"
FIXTURE_EVIDENCE = FIXTURE_DIR / "evidence.FIXTURE.json"
FIXTURE_LABEL = "FIXTURE — NOT live Mac stdout"

MAC_FIXTURE_PROOFS = (
    "proofs/mac-b1-relay.FIXTURE.txt",
    "proofs/mac-b1-acp-run.FIXTURE.txt",
    "proofs/mac-b2-acp-dispatch.FIXTURE.txt",
    "proofs/mac-b3-paseo-smoke.FIXTURE.txt",
)

CALLER_SKILLS = (
    "skills/fan-out/SKILL.md",
    "skills/model-routing/SKILL.md",
    "skills/session-handoff/SKILL.md",
    "skills/old-handoff-use-paseo-handoff/SKILL.md",
    "skills/oc-go-key/SKILL.md",
    "skills/baton/SKILL.md",
    "skills/research/SKILL.md",
    "skills/dialogue/SKILL.md",
    "AGENTS.md",
)
CALLER_BINS = (
    "bin/deadline",
    "bin/load-watch",
    "bin/instruction-lint",
    "bin/ade_claims.py",
)


def _run_capture(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(CAPTURE), *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _run_delete_check(*args: str, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(DELETE_CHECK), "--root", str(root), *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _write_clean_tree(tmp: Path) -> Path:
    for rel in CALLER_SKILLS:
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# clean\nUse paseo run and paseo send.\n", encoding="utf-8")
    for rel in CALLER_BINS:
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/usr/bin/env python3\n# clean: paseo send only\n", encoding="utf-8")
    loose = tmp / "skills/loose/SKILL.md"
    loose.parent.mkdir(parents=True, exist_ok=True)
    loose.write_text("# loose\nRead upstream issues via Paseo read-only.\n", encoding="utf-8")
    return tmp


def test_fixture_capture_script_is_executable() -> None:
    mode = CAPTURE.stat().st_mode
    assert mode & stat.S_IXUSR, "bin/wave6-mac-proof-capture must be executable"


def test_fixture_bundle_mac_proofs_are_labeled_not_live() -> None:
    """Every checked-in Mac proof file must declare FIXTURE (not invented live stdout)."""
    assert FIXTURE_EVIDENCE.is_file()
    data = json.loads(FIXTURE_EVIDENCE.read_text(encoding="utf-8"))
    assert data.get("recorded") == "FIXTURE-not-live-Mac"
    assert "FIXTURE" in data.get("note", "")
    assert "NOT" in data.get("note", "")
    for rel in MAC_FIXTURE_PROOFS:
        path = FIXTURE_DIR / rel
        assert path.is_file(), rel
        text = path.read_text(encoding="utf-8")
        assert text.startswith(FIXTURE_LABEL), rel
        assert "kind: fixture" in text
        assert path.stat().st_size > 0
        assert "mac-" in path.name and "FIXTURE" in path.name


def test_fixture_evidence_passes_delete_check_shape_on_clean_tree(tmp_path: Path) -> None:
    """Fixture mac_proofs satisfy FAILCLOSED non-empty shape; not a live Mac claim."""
    tree = _write_clean_tree(tmp_path)
    # Copy fixture bundle so paths resolve beside evidence.FIXTURE.json.
    dest = tmp_path / "fixture-bundle"
    dest.mkdir()
    import shutil

    shutil.copytree(FIXTURE_DIR / "proofs", dest / "proofs")
    shutil.copy2(FIXTURE_EVIDENCE, dest / "evidence.FIXTURE.json")
    r = _run_delete_check(
        "--json",
        "--evidence",
        str(dest / "evidence.FIXTURE.json"),
        "--allow-early",
        root=tree,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["ready"] is True
    assert out["reasons"] == []


def test_fixture_harness_refuses_out_without_live() -> None:
    """Harness must not write invented Mac stdout when --live is absent."""
    r = _run_capture("--out", "/tmp/wave6-mac-proof-should-not-write")
    assert r.returncode == 2
    assert "refusing to invent" in r.stderr or "requires --live" in r.stderr


def test_fixture_harness_refuses_live_on_non_darwin(tmp_path: Path) -> None:
    """On Linux CI, --live must fail closed (never invent Mac stdout)."""
    if sys.platform == "darwin":
        pytest.skip("live Mac capture is allowed on Darwin")
    out = tmp_path / "out"
    r = _run_capture("--live", "--out", str(out))
    assert r.returncode == 2
    assert "refused" in r.stderr
    assert not (out / "proofs").exists()


def test_fixture_harness_default_mentions_fixture_replacement() -> None:
    r = _run_capture()
    assert r.returncode == 0
    joined = r.stderr + r.stdout
    assert "tests/fixtures/wave6-mac-proofs" in joined
    assert "--live" in joined
    assert "wave6-follow-up.md" in joined or "FIXTURE" in joined


def test_fixture_harness_write_live_proofs_with_injected_runner(tmp_path: Path) -> None:
    """Unit-level: capture helpers write non-empty idle proofs without claiming Darwin."""
    import shutil
    import types

    # bin/wave6-mac-proof-capture has no .py suffix; load by exec (stdlib only).
    mod = types.ModuleType("wave6_mac_proof_capture")
    code = CAPTURE.read_text(encoding="utf-8")
    exec(compile(code, str(CAPTURE), "exec"), mod.__dict__)  # noqa: S102

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("pgrep", "launchctl", "paseo"):
        path = bin_dir / name
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        path.chmod(0o755)
    env_path = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")

    def run_path(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        name = Path(argv[0]).name
        if name == "pgrep":
            return subprocess.CompletedProcess(argv, 1, "", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    out = tmp_path / "evidence"
    old = os.environ.get("PATH")
    os.environ["PATH"] = env_path
    try:
        # shutil.which inside the module must see the stubs.
        assert shutil.which("paseo") is not None
        rel = mod.write_live_proofs(out, run=run_path, home=tmp_path / "home")
    finally:
        if old is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = old

    assert set(rel) == {
        "relay_idle",
        "acp_run_idle",
        "acp_dispatch_idle",
        "paseo_smoke_ok",
    }
    for flag, rel_path in rel.items():
        text = (out / rel_path).read_text(encoding="utf-8")
        assert text.startswith("source: wave6-mac-proof-capture --live")
        assert f"flag: {flag}" in text
        assert "verified:" in text
        assert (out / rel_path).stat().st_size > 0


def test_fixture_follow_up_doc_explains_live_replaces_fixtures() -> None:
    doc = (ROOT / "docs/slim/wave6-follow-up.md").read_text(encoding="utf-8")
    assert "tests/fixtures/wave6-mac-proofs" in doc
    assert "wave6-mac-proof-capture" in doc
    assert "FIXTURE" in doc
    assert "replace" in doc.lower()
    # Must not claim fixtures are live Mac captures.
    assert "NOT live Mac" in doc or "not live Mac" in doc
