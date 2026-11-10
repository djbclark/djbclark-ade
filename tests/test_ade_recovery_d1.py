"""bin/ade-recovery-d1: observe-only D1 / native-resume preflight (Carried #2)."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "ade-recovery-d1"
REPO = SCRIPT.parent.parent


def run(
    *args: str,
    env: dict[str, str] | None = None,
    root: Path | None = None,
    paseo_home: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-I", str(SCRIPT), *args]
    if root is not None:
        cmd.extend(["--root", str(root)])
    if paseo_home is not None:
        cmd.extend(["--paseo-home", str(paseo_home)])
    base = {k: v for k, v in os.environ.items() if k not in ("PASEO_CLI", "ADE_RECOVERY_D1_PASEO")}
    if env:
        base.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=base)


def _write_checkpoint(root: Path, *, good: bool = True) -> None:
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    if good:
        text = (
            "# Checkpoint\n\n"
            "D1 / provider probe owner measures native resume.\n"
            "Use `paseo send` for the native ladder.\n"
        )
    else:
        text = "# Checkpoint\n\nNo probes here.\n"
    (docs / "checkpoint.md").write_text(text, encoding="utf-8")


def _stub_paseo(bin_dir: Path, *, version: str = "0.15.0", agents: list | None = None) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "paseo"
    agents_json = json.dumps(agents if agents is not None else [{"id": "a1"}])
    stub.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ] || [ "$1" = "version" ]; then\n'
        f'  echo "paseo {version}"\n'
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = "ls" ]; then\n'
        f"  echo '{agents_json}'\n"
        "  exit 0\n"
        "fi\n"
        "echo unexpected >&2\n"
        "exit 2\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub


def test_script_is_executable() -> None:
    mode = SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR, "bin/ade-recovery-d1 must be executable"


def test_ready_matrix_with_stub_paseo(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    home = tmp_path / "paseo-home"
    bindir = tmp_path / "bin"
    _write_checkpoint(root)
    stub = _stub_paseo(bindir)
    (home / "agents").mkdir(parents=True)
    (home / "local-credential").write_text("x", encoding="utf-8")  # presence only
    r = run(
        "--json",
        root=root,
        paseo_home=home,
        env={"PATH": str(bindir) + os.pathsep + os.environ.get("PATH", ""), "ADE_RECOVERY_D1_PASEO": str(stub)},
    )
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    assert data["ready"] is True
    by_id = {p["id"]: p for p in data["probes"]}
    assert by_id["docs_contract"]["status"] == "ok"
    assert by_id["paseo_cli"]["status"] == "ok"
    assert by_id["paseo_daemon"]["status"] == "ok"
    assert by_id["local_credential"]["status"] == "ok"
    assert "not read" in by_id["local_credential"]["detail"]
    # Never claims crash recovery works.
    assert "does not measure crash recovery" in data["note"]


def test_blocked_without_paseo(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    home = tmp_path / "paseo-home"
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    _write_checkpoint(root)
    home.mkdir()
    r = run(
        "--json",
        root=root,
        paseo_home=home,
        env={"PATH": str(empty)},
    )
    assert r.returncode == 1, r.stdout + r.stderr
    data = json.loads(r.stdout)
    assert data["ready"] is False
    assert any(p["id"] == "paseo_cli" and p["status"] == "missing" for p in data["probes"])


def test_blocked_when_checkpoint_lacks_d1(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    home = tmp_path / "paseo-home"
    bindir = tmp_path / "bin"
    _write_checkpoint(root, good=False)
    stub = _stub_paseo(bindir)
    home.mkdir()
    r = run(
        "--json",
        root=root,
        paseo_home=home,
        env={"ADE_RECOVERY_D1_PASEO": str(stub)},
    )
    assert r.returncode == 1, r.stdout
    data = json.loads(r.stdout)
    assert data["ready"] is False
    assert any(p["id"] == "docs_contract" and p["status"] == "error" for p in data["probes"])


def test_version_below_inventory_still_ok_daemon(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    home = tmp_path / "paseo-home"
    bindir = tmp_path / "bin"
    _write_checkpoint(root)
    stub = _stub_paseo(bindir, version="0.14.2")
    (home / "agents").mkdir(parents=True)
    r = run(
        "--json",
        root=root,
        paseo_home=home,
        env={"ADE_RECOVERY_D1_PASEO": str(stub)},
    )
    assert r.returncode == 0, r.stderr + r.stdout
    data = json.loads(r.stdout)
    ver = next(p for p in data["probes"] if p["id"] == "paseo_version")
    assert ver["status"] == "ok"
    assert "below inventory" in ver["detail"]


def test_never_reads_local_credential_bytes(tmp_path: Path) -> None:
    """Presence probe must not open the credential file (chmod 000 still ok on Linux for is_file)."""
    root = tmp_path / "repo"
    home = tmp_path / "paseo-home"
    bindir = tmp_path / "bin"
    _write_checkpoint(root)
    stub = _stub_paseo(bindir)
    (home / "agents").mkdir(parents=True)
    cred = home / "local-credential"
    cred.write_text("SECRET-SHOULD-NOT-APPEAR\n", encoding="utf-8")
    cred.chmod(0o000)
    try:
        r = run(
            "--json",
            root=root,
            paseo_home=home,
            env={"ADE_RECOVERY_D1_PASEO": str(stub)},
        )
    finally:
        cred.chmod(0o600)
    assert r.returncode == 0, r.stderr + r.stdout
    assert "SECRET-SHOULD-NOT-APPEAR" not in r.stdout
    assert "SECRET-SHOULD-NOT-APPEAR" not in r.stderr
    data = json.loads(r.stdout)
    assert next(p for p in data["probes"] if p["id"] == "local_credential")["status"] == "ok"


def test_live_checkout_smoke() -> None:
    """Against this checkout: always emits JSON; exit 0 or 1 depending on host paseo."""
    r = run("--json", root=REPO)
    assert r.returncode in (0, 1), r.stderr
    data = json.loads(r.stdout)
    assert data["tool"] == "ade-recovery-d1"
    assert isinstance(data["probes"], list)
    assert {p["id"] for p in data["probes"]} >= {
        "docs_contract",
        "paseo_cli",
        "paseo_daemon",
        "local_credential",
    }
