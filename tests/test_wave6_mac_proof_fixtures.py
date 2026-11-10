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


def test_dry_run_uses_fixture_bundle_and_never_claims_ready() -> None:
    """CLI --dry-run: FIXTURE FAILCLOSED shape only; exit 0 ≠ deletion-ready."""
    r = _run_delete_check("--json", "--dry-run", root=ROOT)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["dry_run"] is True
    assert out["mode"] == "dry-run-fixture"
    assert out["fixture_shape_ok"] is True
    assert out["ready"] is False
    assert any("NOT deletion-ready" in x for x in out["reasons"])
    assert out["evidence"] and "evidence.FIXTURE.json" in out["evidence"]


def test_dry_run_refuses_evidence_and_allow_early() -> None:
    r = _run_delete_check(
        "--dry-run",
        "--evidence",
        str(FIXTURE_EVIDENCE),
        root=ROOT,
    )
    assert r.returncode == 2
    assert "incompatible" in r.stderr


def test_dry_run_failcloses_when_fixture_unlabeled(tmp_path: Path) -> None:
    """Invented 'live' labels under the fixture path must not green --dry-run."""
    import shutil

    dest_root = tmp_path / "repo"
    bundle = dest_root / "tests/fixtures/wave6-mac-proofs"
    shutil.copytree(FIXTURE_DIR, bundle)
    ev = bundle / "evidence.FIXTURE.json"
    data = json.loads(ev.read_text(encoding="utf-8"))
    data["recorded"] = "2026-11-10-live-Mac"  # pretend live
    data["note"] = "live capture"
    ev.write_text(json.dumps(data), encoding="utf-8")
    # Also strip FIXTURE label from one mac proof (invented live stdout).
    mac = bundle / data["mac_proofs"]["relay_idle"]
    mac.write_text("cmd: pgrep\nverified: no match\n", encoding="utf-8")
    r = _run_delete_check("--json", "--dry-run", root=dest_root)
    assert r.returncode == 1, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["fixture_shape_ok"] is False
    assert out["ready"] is False
    joined = "\n".join(out["reasons"])
    assert "fixture_invalid:" in joined
    assert "FIXTURE-not-live-Mac" in joined or "FIXTURE" in joined

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


def _load_capture_mod():
    import types

    # bin/wave6-mac-proof-capture has no .py suffix; load by exec (stdlib only).
    mod = types.ModuleType("wave6_mac_proof_capture")
    code = CAPTURE.read_text(encoding="utf-8")
    exec(compile(code, str(CAPTURE), "exec"), mod.__dict__)  # noqa: S102
    return mod


def _with_stub_path(tmp_path: Path, names: tuple[str, ...]):
    """Context: PATH with stub binaries so shutil.which finds them."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        for name in names:
            path = bin_dir / name
            path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            path.chmod(0o755)
        env_path = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
        old = os.environ.get("PATH")
        os.environ["PATH"] = env_path
        try:
            yield
        finally:
            if old is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = old

    return _ctx()


def test_fixture_harness_write_live_proofs_with_injected_runner(tmp_path: Path) -> None:
    """Unit-level: capture helpers write non-empty idle proofs without claiming Darwin."""
    import shutil

    mod = _load_capture_mod()

    def run_path(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        name = Path(argv[0]).name
        if name == "pgrep":
            return subprocess.CompletedProcess(argv, 1, "", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    out = tmp_path / "evidence"
    with _with_stub_path(tmp_path, ("pgrep", "launchctl", "paseo")):
        assert shutil.which("paseo") is not None
        assert shutil.which("launchctl") is not None
        rel, ok = mod.write_live_proofs(out, run=run_path, home=tmp_path / "home")

    assert ok is True
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
        assert "verified: FAILED" not in text
        assert (out / rel_path).stat().st_size > 0

    dispatch = (out / rel["acp_dispatch_idle"]).read_text(encoding="utf-8")
    assert "cmd: pgrep -lf 'acp-dispatch'" in dispatch
    assert "cmd: launchctl list | grep -E 'acp-dispatch'" in dispatch
    assert "verified: no match pgrep" in dispatch
    assert "verified: no match launchctl" in dispatch


def test_fixture_harness_marks_launchctl_failure_not_idle(tmp_path: Path) -> None:
    """Failed launchctl must be FAILED (with stderr), not verified no-match idle."""
    mod = _load_capture_mod()

    def run_path(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        name = Path(argv[0]).name
        if name == "pgrep":
            return subprocess.CompletedProcess(argv, 1, "", "")
        if name == "launchctl":
            return subprocess.CompletedProcess(
                argv, 70, "", "Bootstrap failed: 5: Input/output error\n"
            )
        return subprocess.CompletedProcess(argv, 0, "", "")

    out = tmp_path / "evidence"
    with _with_stub_path(tmp_path, ("pgrep", "launchctl", "paseo")):
        rel, ok = mod.write_live_proofs(out, run=run_path, home=tmp_path / "home")

    assert ok is False
    acp_run = (out / rel["acp_run_idle"]).read_text(encoding="utf-8")
    assert "stderr: Bootstrap failed: 5: Input/output error" in acp_run
    assert "verified: FAILED launchctl (exit 70)" in acp_run
    assert "verified: no match launchctl" not in acp_run
    dispatch = (out / rel["acp_dispatch_idle"]).read_text(encoding="utf-8")
    assert "verified: FAILED launchctl (exit 70)" in dispatch


def test_fixture_harness_marks_pgrep_probe_failure_not_idle(tmp_path: Path) -> None:
    """Empty pgrep stdout with a non-1 exit is FAILED, not verified idle."""
    mod = _load_capture_mod()

    def run_path(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        name = Path(argv[0]).name
        if name == "pgrep":
            return subprocess.CompletedProcess(argv, 3, "", "pgrep: invalid option\n")
        return subprocess.CompletedProcess(argv, 0, "", "")

    out = tmp_path / "evidence"
    with _with_stub_path(tmp_path, ("pgrep", "launchctl", "paseo")):
        rel, ok = mod.write_live_proofs(out, run=run_path, home=tmp_path / "home")

    assert ok is False
    relay = (out / rel["relay_idle"]).read_text(encoding="utf-8")
    assert "stderr: pgrep: invalid option" in relay
    assert "verified: FAILED pgrep" in relay
    assert "verified: no match" not in relay


def test_fixture_follow_up_doc_explains_live_replaces_fixtures() -> None:
    doc = (ROOT / "docs/slim/wave6-follow-up.md").read_text(encoding="utf-8")
    assert "tests/fixtures/wave6-mac-proofs" in doc
    assert "wave6-mac-proof-capture" in doc
    assert "FIXTURE" in doc
    assert "replace" in doc.lower()
    # Must not claim fixtures are live Mac captures.
    assert "NOT live Mac" in doc or "not live Mac" in doc
