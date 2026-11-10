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


def test_refuses_acp_dispatch_agent_placeholder_and_backtick(tmp_path: Path) -> None:
    """LIVE_RE must catch `acp-dispatch <agent>` / backticked name (rewrite leftovers)."""
    tree = _write_clean_tree(tmp_path)
    (tree / "skills/model-routing/SKILL.md").write_text(
        "Prefer paseo run; legacy `acp-dispatch <agent> --model M --kind K` only while the shim remains.\n",
        encoding="utf-8",
    )
    ev = _good_evidence(tmp_path)
    r = run("--json", "--evidence", str(ev), "--allow-early", root=tree)
    assert r.returncode == 1, r.stderr
    data = json.loads(r.stdout)
    assert any(x.startswith("callers_skills:") for x in data["reasons"])
    assert data["ready"] is False

    tree2 = _write_clean_tree(tmp_path / "bt")
    (tree2 / "skills/model-routing/SKILL.md").write_text(
        "While the Wave 6 shim remains, `acp-dispatch` wraps admit for non-Pi agents.\n",
        encoding="utf-8",
    )
    ev2 = _good_evidence(tmp_path / "bt")
    r2 = run("--json", "--evidence", str(ev2), "--allow-early", root=tree2)
    assert r2.returncode == 1, r2.stderr
    data2 = json.loads(r2.stdout)
    assert any(x.startswith("callers_skills:") for x in data2["reasons"])
    assert data2["ready"] is False


def test_inventory_lists_agent_placeholder_hits(tmp_path: Path) -> None:
    """--inventory lists `acp-dispatch <agent>` leftovers; never greening Mac/ready."""
    tree = _write_clean_tree(tmp_path)
    (tree / "skills/model-routing/SKILL.md").write_text(
        "legacy `acp-dispatch <agent> --model M --kind K`\n",
        encoding="utf-8",
    )
    r = run("--json", "--inventory", root=tree)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["ready"] is False
    assert data["mac_live_blocked"] is True
    assert data["inventory_ok"] is True
    assert data["gate_exits"]["callers"] == 1
    assert data["gate_exits"]["evaluate_no_evidence"] == 1
    assert data["callers_remaining"] >= 1
    assert any(
        h["path"] == "skills/model-routing/SKILL.md"
        and "acp-dispatch <agent>" in h["snippet"]
        for h in data["references"]
    )


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
    """Bare idle pgrep redirects must not green the gate (Codex P2 on #417)."""
    tree = _write_clean_tree(tmp_path)
    ev = _good_evidence(tmp_path)
    data = json.loads(ev.read_text(encoding="utf-8"))
    proof_rel = data["mac_proofs"]["relay_idle"]
    (ev.parent / proof_rel).write_text("", encoding="utf-8")
    r = run("--json", "--evidence", str(ev), "--allow-early", root=tree)
    assert r.returncode == 1, r.stderr
    out = json.loads(r.stdout)
    assert any(x.startswith("mac_relay_idle_proof_missing:") for x in out["reasons"])


def test_accepts_idle_mac_proof_with_verified_no_match(tmp_path: Path) -> None:
    """Successful idle capture: cmd + verified: no match is non-empty evidence."""
    tree = _write_clean_tree(tmp_path)
    ev = _good_evidence(tmp_path)
    data = json.loads(ev.read_text(encoding="utf-8"))
    for flag in ("relay_idle", "acp_run_idle"):
        proof_rel = data["mac_proofs"][flag]
        (ev.parent / proof_rel).write_text(
            f"cmd: pgrep -lf '{flag}'\nverified: no match (exit 1)\n",
            encoding="utf-8",
        )
    r = run("--json", "--evidence", str(ev), "--allow-early", root=tree)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["ready"] is True
    assert out["reasons"] == []


def test_follow_up_doc_idle_capture_is_non_empty() -> None:
    """Docs must not teach `{ pgrep … || true; } > proof` (empty when idle)."""
    doc = (ROOT / "docs/slim/wave6-follow-up.md").read_text(encoding="utf-8")
    assert "verified: no match" in doc
    # The broken one-liner shape that produced empty idle proofs.
    assert "{ pgrep -lf 'relay\\.py' || true; }" not in doc
    assert "pgrep -lf 'relay\\.py' || true; }" not in doc


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


def test_dry_run_help_documents_fixture_not_live() -> None:
    """Usage must advertise --dry-run as FIXTURE regression, not live Mac."""
    r = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    text = r.stdout + r.stderr
    assert "--dry-run" in text
    assert "FIXTURE" in text
    assert "deletion-ready" in text or "not deletion" in text.lower()


def test_inventory_help_documents_caller_list_not_live() -> None:
    """Usage must advertise --inventory as gated caller list, not live Mac."""
    r = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    text = r.stdout + r.stderr
    assert "--inventory" in text
    assert "gated" in text.lower() or "caller" in text.lower()
    assert "Mac" in text or "mac" in text


def test_inventory_lists_every_gated_hit_and_proves_gate_exits() -> None:
    """--inventory lists untruncated §A hits; gate_exits prove coverage (0 callers OK after scrub)."""
    r = run("--json", "--inventory", root=ROOT)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["mode"] == "caller-inventory"
    assert data["ready"] is False
    assert data["mac_live_blocked"] is True
    assert data["inventory_ok"] is True
    assert data["coverage_ok"] is True
    assert data["ungated_references"] == []
    refs = data["references"]
    assert data["callers_remaining"] == len(refs)
    assert data["callers_remaining"] >= 0
    # Untruncated: every hit carries path/line/kind/snippet.
    for hit in refs:
        assert hit["gated"] is True
        assert hit["kind"] in {"skills", "bins", "loose"}
        assert isinstance(hit["path"], str) and hit["path"]
        assert isinstance(hit["line"], int) and hit["line"] >= 1
        assert isinstance(hit["snippet"], str) and hit["snippet"]
    exits = data["gate_exits"]
    # callers gate is 1 while hits remain, 0 after a full LIVE_RE scrub (Mac still blocked).
    assert exits["callers"] in (0, 1)
    assert exits["callers"] == (1 if refs else 0)
    assert exits["evaluate_no_evidence"] == 1
    assert exits["dry_run_fixture"] is None
    joined = "\n".join(data["gate_reasons"])
    if refs:
        assert "callers_skills:" in joined or "callers_bins:" in joined or "callers_loose:" in joined
    else:
        assert data["gate_reasons"] == []


def test_inventory_human_success_prints_refs_and_gate_exits() -> None:
    """Non-JSON --inventory success still lists gate_exits (refs only while hits remain)."""
    r = run("--inventory", root=ROOT)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "inventory OK" in out
    assert "gate_exits:" in out
    assert "callers=" in out
    # When callers_remaining > 0, every hit is printed; a clean scrub prints none.
    inv = run("--json", "--inventory", root=ROOT)
    n = json.loads(inv.stdout)["callers_remaining"]
    if n:
        assert "ref:" in out
        assert any(p in out for p in ("skills/", "bin/", "loose"))
    else:
        assert "ref:" not in out


def test_inventory_with_dry_run_keeps_fixture_exit_and_never_ready() -> None:
    """--inventory --dry-run reports dry_run_fixture exit 0 without greening ready."""
    r = run("--json", "--inventory", "--dry-run", root=ROOT)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["dry_run"] is True
    assert data["fixture_shape_ok"] is True
    assert data["gate_exits"]["dry_run_fixture"] == 0
    assert data["gate_exits"]["callers"] in (0, 1)
    assert data["gate_exits"]["callers"] == (1 if data["callers_remaining"] else 0)
    assert data["ready"] is False
    assert data["mac_live_blocked"] is True


def test_inventory_refuses_evidence_and_allow_early() -> None:
    r = run("--inventory", "--evidence", "/tmp/nope.json")
    assert r.returncode == 2, r.stderr
    r2 = run("--inventory", "--allow-early")
    assert r2.returncode == 2, r2.stderr


def test_inventory_exit_1_on_ungated_skill(tmp_path: Path) -> None:
    """A LIVE_RE hit in skills/*/SKILL.md outside §A fails coverage (exit 1)."""
    tree = _write_clean_tree(tmp_path)
    other = tree / "skills/other/SKILL.md"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text(
        "Do not: bin/acp-dispatch claude --model sonnet --kind code\n",
        encoding="utf-8",
    )
    r = run("--json", "--inventory", root=tree)
    assert r.returncode == 1, r.stderr
    data = json.loads(r.stdout)
    assert data["ready"] is False
    assert data["mac_live_blocked"] is True
    assert data["coverage_ok"] is False
    assert data["inventory_ok"] is False
    assert any(x.startswith("ungated_skills:") for x in data["reasons"])
    assert data["ungated_references"]
    assert data["ungated_references"][0]["gated"] is False


def test_inventory_clean_tree_callers_exit_0_still_blocks_mac(tmp_path: Path) -> None:
    """No §A hits → callers gate exit 0; evaluate_no_evidence still 1; never ready."""
    tree = _write_clean_tree(tmp_path)
    r = run("--json", "--inventory", root=tree)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["references"] == []
    assert data["callers_remaining"] == 0
    assert data["gate_exits"]["callers"] == 0
    assert data["gate_exits"]["evaluate_no_evidence"] == 1
    assert data["ready"] is False
    assert data["mac_live_blocked"] is True
