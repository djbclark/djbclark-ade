"""bin/wave6-delete-check refuses shim deletion until Wave 6 gates pass."""
from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin" / "wave6-delete-check"

CALLER_SKILLS = (
    "skills/fan-out/SKILL.md",
    "skills/model-routing/SKILL.md",
    "skills/session-handoff/SKILL.md",
    "skills/old-handoff-use-paseo-handoff/SKILL.md",
    "skills/oc-go-key/SKILL.md",
    "skills/baton/SKILL.md",
    "skills/research/SKILL.md",
    "skills/dialogue/SKILL.md",
)


def run(*args: str, root: Path | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-I", str(SCRIPT), *args]
    if root is not None:
        cmd.extend(["--root", str(root)])
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


CALLER_BINS = (
    "bin/deadline",
    "bin/load-watch",
    "bin/instruction-lint",
    "bin/ade_claims.py",
)

C3_KEYS = (
    "tendcf",
    "nix2cf",
    "cfengine",
    "paseo_upstream",
    "plektra",
    "paseo4herdr",
    "pi",
    "sudo_secretspec",
    "aiuse",
    "paseo_runner",
    "site_public_home_agents",
    "aiuse_config_opencode_go",
)
MAC_FLAGS = (
    "relay_idle",
    "acp_dispatch_idle",
    "acp_run_idle",
    "paseo_smoke_ok",
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


def _write_proofs(bundle: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Create non-empty proof files beside evidence.json; return relative maps."""
    proofs_dir = bundle / "proofs"
    proofs_dir.mkdir(parents=True, exist_ok=True)
    c3_proofs: dict[str, str] = {}
    for key in C3_KEYS:
        rel = f"proofs/c3-{key}.txt"
        (bundle / rel).write_text(f"probe for {key}: no live shim names\n", encoding="utf-8")
        c3_proofs[key] = rel
    mac_proofs: dict[str, str] = {}
    for flag in MAC_FLAGS:
        rel = f"proofs/mac-{flag}.txt"
        (bundle / rel).write_text(f"mac capture for {flag}: idle/ok\n", encoding="utf-8")
        mac_proofs[flag] = rel
    return c3_proofs, mac_proofs


def _good_evidence(tmp: Path) -> Path:
    """Evidence bundle with status ticks AND non-empty proof files (fail-closed)."""
    bundle = tmp / "evidence-bundle"
    bundle.mkdir(parents=True, exist_ok=True)
    c3_proofs, mac_proofs = _write_proofs(bundle)
    path = bundle / "evidence.json"
    path.write_text(
        json.dumps(
            {
                "recorded": "2026-11-20",
                "c3": {
                    "tendcf": "migrated",
                    "nix2cf": "migrated",
                    "cfengine": "waived",
                    "paseo_upstream": "waived",
                    "plektra": "migrated",
                    "paseo4herdr": "migrated",
                    "pi": "migrated",
                    "sudo_secretspec": "migrated",
                    "aiuse": "migrated",
                    "paseo_runner": "migrated",
                    "site_public_home_agents": "waived",
                    "aiuse_config_opencode_go": "waived",
                },
                "c3_proofs": c3_proofs,
                "mac": {
                    "relay_idle": True,
                    "acp_dispatch_idle": True,
                    "acp_run_idle": True,
                    "paseo_smoke_ok": True,
                },
                "mac_proofs": mac_proofs,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_script_is_executable() -> None:
    mode = SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR, "bin/wave6-delete-check must be executable"


def test_refuses_without_evidence_on_clean_tree(tmp_path: Path) -> None:
    tree = _write_clean_tree(tmp_path)
    r = run("--json", root=tree)
    assert r.returncode == 1, r.stderr
    data = json.loads(r.stdout)
    assert data["ready"] is False
    assert any(x.startswith("evidence_missing:") for x in data["reasons"])


def test_refuses_when_fan_out_still_names_acp_dispatch(tmp_path: Path) -> None:
    tree = _write_clean_tree(tmp_path)
    (tree / "skills/fan-out/SKILL.md").write_text(
        "Launch with:\n"
        "    ~/src/djbclark-ade/bin/acp-dispatch claude --model sonnet --kind code\n",
        encoding="utf-8",
    )
    ev = _good_evidence(tmp_path)
    r = run("--json", "--evidence", str(ev), "--allow-early", root=tree)
    assert r.returncode == 1, r.stderr
    data = json.loads(r.stdout)
    assert any(x.startswith("callers_skills:") for x in data["reasons"])


def test_refuses_when_deadline_still_invokes_relay(tmp_path: Path) -> None:
    # Codex P2: executable callers (bin/deadline) must block ready, not only skills.
    tree = _write_clean_tree(tmp_path)
    (tree / "bin/deadline").write_text(
        'argv = tool("DEADLINE_RELAY", "skills/session-finder/relay.py") + [owner]\n',
        encoding="utf-8",
    )
    ev = _good_evidence(tmp_path)
    r = run("--json", "--evidence", str(ev), "--allow-early", root=tree)
    assert r.returncode == 1, r.stderr
    data = json.loads(r.stdout)
    assert any(x.startswith("callers_bins:") for x in data["reasons"])


def test_refuses_when_loose_still_names_acp_run(tmp_path: Path) -> None:
    tree = _write_clean_tree(tmp_path)
    (tree / "skills/loose/SKILL.md").write_text(
        'rc = subprocess.run(["acp-run", agent, "--perm", "deny"])\n',
        encoding="utf-8",
    )
    ev = _good_evidence(tmp_path)
    r = run("--json", "--evidence", str(ev), "--allow-early", root=tree)
    assert r.returncode == 1, r.stderr
    data = json.loads(r.stdout)
    assert any(x.startswith("callers_loose:") for x in data["reasons"])


def test_refuses_incomplete_c3(tmp_path: Path) -> None:
    tree = _write_clean_tree(tmp_path)
    ev = _good_evidence(tmp_path / "incomplete")
    data = json.loads(ev.read_text(encoding="utf-8"))
    data["c3"]["tendcf"] = "todo"
    ev.write_text(json.dumps(data), encoding="utf-8")
    r = run("--json", "--evidence", str(ev), "--allow-early", root=tree)
    assert r.returncode == 1, r.stderr
    out = json.loads(r.stdout)
    assert any(x.startswith("c3_tendcf:") for x in out["reasons"])


def test_refuses_missing_c3_proof_file(tmp_path: Path) -> None:
    """Status ticks without proof files FAILCLOSED (do not invent captures)."""
    tree = _write_clean_tree(tmp_path)
    ev = _good_evidence(tmp_path)
    data = json.loads(ev.read_text(encoding="utf-8"))
    # Drop the proof path and delete the file for tendcf.
    proof_rel = data["c3_proofs"]["tendcf"]
    (ev.parent / proof_rel).unlink()
    del data["c3_proofs"]["tendcf"]
    ev.write_text(json.dumps(data), encoding="utf-8")
    r = run("--json", "--evidence", str(ev), "--allow-early", root=tree)
    assert r.returncode == 1, r.stderr
    out = json.loads(r.stdout)
    assert any(x.startswith("c3_tendcf_proof_missing:") for x in out["reasons"])


def test_refuses_empty_mac_proof_file(tmp_path: Path) -> None:
    tree = _write_clean_tree(tmp_path)
    ev = _good_evidence(tmp_path)
    data = json.loads(ev.read_text(encoding="utf-8"))
    proof_rel = data["mac_proofs"]["relay_idle"]
    (ev.parent / proof_rel).write_text("", encoding="utf-8")
    r = run("--json", "--evidence", str(ev), "--allow-early", root=tree)
    assert r.returncode == 1, r.stderr
    out = json.loads(r.stdout)
    assert any(x.startswith("mac_relay_idle_proof_missing:") for x in out["reasons"])


def test_refuses_evidence_without_proof_maps(tmp_path: Path) -> None:
    """Legacy status-only evidence (no c3_proofs/mac_proofs) is not ready."""
    tree = _write_clean_tree(tmp_path)
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            {
                "recorded": "2026-11-20",
                "c3": {k: "migrated" for k in C3_KEYS},
                "mac": {f: True for f in MAC_FLAGS},
            }
        ),
        encoding="utf-8",
    )
    r = run("--json", "--evidence", str(path), "--allow-early", root=tree)
    assert r.returncode == 1, r.stderr
    out = json.loads(r.stdout)
    joined = "\n".join(out["reasons"])
    assert "evidence_invalid: missing c3_proofs object" in joined
    assert "evidence_invalid: missing mac_proofs object" in joined


def test_ready_with_evidence_and_allow_early(tmp_path: Path) -> None:
    tree = _write_clean_tree(tmp_path)
    ev = _good_evidence(tmp_path)
    r = run("--json", "--evidence", str(ev), "--allow-early", root=tree)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["ready"] is True
    assert data["reasons"] == []


def test_repo_root_not_ready_today() -> None:
    """Against this checkout the shims' skill callers still exist → not ready."""
    r = run("--json", root=ROOT)
    assert r.returncode == 1, r.stderr
    data = json.loads(r.stdout)
    assert data["ready"] is False
    joined = "\n".join(data["reasons"])
    assert "evidence_missing:" in joined or "callers_skills:" in joined
