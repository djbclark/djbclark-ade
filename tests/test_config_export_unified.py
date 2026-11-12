"""W16 (2026-11-12): config/ade.toml generation, equivalence proof and consumer acceptance."""
from __future__ import annotations

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
import ade_config_export as acx  # noqa: E402

LEGACY = ("routing.toml", "gates.toml", "model-tiers.toml", "install.toml", "context-budget.toml",
          "ade.schema.json", "install.schema.json")


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / "repo"
    (r / "config").mkdir(parents=True)
    for name in LEGACY:
        shutil.copy2(REPO / "config" / name, r / "config" / name)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for name in ("ROUTING_POLICY", "GATES_TOML", "MODEL_TIERS_TOML"):
        monkeypatch.delenv(name, raising=False)
    return r


def effective(root: Path, tmp_path: Path):
    home = tmp_path / "empty-home"
    home.mkdir(exist_ok=True)
    return ac.load_effective(root=root, home=home, environ={}, include_local=False)


def test_shipped_legacy_files_round_trip_and_keep_comments(root, tmp_path):
    text = acx.generate_unified(root)
    parsed = tomllib.loads(text)
    assert parsed["schema_version"] == 1
    assert {"routing", "lead", "service", "gates", "model_tiers", "install", "keys", "context_budget"} <= set(parsed)
    routing_comment = next(l for l in (root / "config/routing.toml").read_text().splitlines() if l.startswith("# Machine"))
    assert routing_comment in text
    assert "[keys.ANTHROPIC_API_KEY]" in text and "[[key]]" not in text
    assert "\n[gates.frontier]" in text and "\n[context_budget.budget]" in text
    # installing it makes the unified file the repo base with an identical effective tree
    (root / "config/ade.toml").write_text(text)
    new = effective(root, tmp_path)
    for name in LEGACY[:5]:
        (root / "config" / name).unlink()
    new_only = effective(root, tmp_path)
    assert edit.values_equal(new.data, new_only.data)
    assert new_only.provenance["routing_source"].endswith("ade.toml")


def test_cli_stdout_write_check_cycle(root):
    def cli(*args):
        env = {k: v for k, v in os.environ.items() if k not in {"ROUTING_POLICY", "GATES_TOML", "MODEL_TIERS_TOML"}}
        return subprocess.run([sys.executable, "-I", "-B", str(BIN / "ade-config"), "--root", str(root), *args],
                              capture_output=True, text=True, env=env, check=False)
    out = cli("export-unified")
    assert out.returncode == 0 and out.stdout == acx.generate_unified(root)
    assert not (root / "config/ade.toml").exists()
    assert cli("export-unified", "--check").returncode == 2
    assert cli("export-unified", "--write").returncode == 0
    assert (root / "config/ade.toml").read_text() == out.stdout
    assert cli("export-unified", "--check").returncode == 0
    again = cli("export-unified", "--write")
    assert again.returncode == 1 and "refusing to overwrite" in again.stderr
    (root / "config/gates.toml").write_text((root / "config/gates.toml").read_text() + "\n# drift\n[floors.extra]\n")
    assert cli("export-unified", "--check").returncode in {1, 2}


def test_legacy_drift_in_policy_value_is_detected(root):
    acx.write_unified(root)
    gates = root / "config/gates.toml"
    gates.write_text(gates.read_text().replace("frontier1_per_wave = ", "frontier1_per_wave = 9", 1))
    code, _ = acx.check_unified(root)
    assert code == 1


def test_root_key_in_a_sectioned_file_is_refused(root):
    path = root / "config/gates.toml"
    path.write_text("stray = 1\n" + path.read_text())
    with pytest.raises(acx.ExportError, match="root keys"):
        acx.generate_unified(root)


def test_key_identity_line_with_comment_is_supported(root):
    path = root / "config/install.toml"
    path.write_text(path.read_text().replace('name = "ANTHROPIC_API_KEY"', 'name="ANTHROPIC_API_KEY"  # id', 1))
    # still a supported form (bare name line with a comment)
    acx.generate_unified(root)


def test_equivalence_proof_catches_a_mapping_slip(root, tmp_path):
    text = acx.generate_unified(root).replace("[gates.frontier]", "[gates.floors.zzz]", 1)
    with pytest.raises(acx.ExportError):
        acx.prove_equivalence(root, text)


def test_write_never_overwrites_a_symlink_or_file(root):
    (root / "config/ade.toml").symlink_to(root / "config/missing")
    with pytest.raises(acx.ExportError, match="refusing"):
        acx.write_unified(root)
