"""bin/wave6-delete-check refuses shim deletion until Wave 6 gates pass."""
from __future__ import annotations

import json
import os
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


def _write_clean_tree(tmp: Path) -> Path:
    for rel in CALLER_SKILLS:
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# clean\nUse paseo run and paseo send.\n", encoding="utf-8")
    loose = tmp / "skills/loose/SKILL.md"
    loose.parent.mkdir(parents=True, exist_ok=True)
    loose.write_text("# loose\nRead upstream issues via Paseo read-only.\n", encoding="utf-8")
    return tmp


def _good_evidence(tmp: Path) -> Path:
    path = tmp / "evidence.json"
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
                "mac": {
                    "relay_idle": True,
                    "acp_dispatch_idle": True,
                    "acp_run_idle": True,
                    "paseo_smoke_ok": True,
                },
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
    path = tmp_path / "bad-c3.json"
    good = json.loads(_good_evidence(tmp_path).read_text(encoding="utf-8"))
    good["c3"]["tendcf"] = "todo"
    path.write_text(json.dumps(good), encoding="utf-8")
    r = run("--json", "--evidence", str(path), "--allow-early", root=tree)
    assert r.returncode == 1, r.stderr
    data = json.loads(r.stdout)
    assert any(x.startswith("c3_tendcf:") for x in data["reasons"])


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
