"""Pi native session backup and offline recovery, using only synthetic HOME data."""
from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

import pytest

REPO = Path(__file__).resolve().parents[1]
BACKUP = REPO / "bin/ade-backup-stores"
HISTORY = REPO / "skills/session-finder/session-history.py"


def load_backup():
    loader = importlib.machinery.SourceFileLoader("pi_backup_recovery", str(BACKUP))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def write_records(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records))
    return path


def native_records(sid, parent=None):
    header = {"type": "session", "version": 3, "id": sid,
              "timestamp": "2026-11-12T10:00:00.000Z", "cwd": "/fixture/project.with spaces"}
    if parent is not None:
        header["parentSession"] = str(parent)
    def entry(kind, entry_id, parent_id, **extra):
        return {"type": kind, "id": entry_id, "parentId": parent_id,
                "timestamp": "2026-11-12T10:00:01.000Z", **extra}
    return [header,
            entry("model_change", "model001", None, provider="fixture", modelId="fixture-model"),
            entry("message", "user0001", "model001", message={"role": "user", "content": [
                {"type": "text", "text": "orchard recovery fixture question"}]}),
            entry("message", "answer01", "user0001", message={"role": "assistant", "content": [
                {"type": "thinking", "thinking": "retained private reasoning fixture"},
                {"type": "text", "text": "orchard recovery fixture answer"}]}),
            entry("message", "branch01", "user0001", message={"role": "user", "content": [
                {"type": "text", "text": "alternate branch retained"}]}),
            entry("session_info", "name0001", "branch01", name="Recovery fixture name"),
            entry("compaction", "compact1", "name0001", summary="retained compaction summary",
                  firstKeptEntryId="user0001", tokensBefore=1200),
            entry("custom", "custom01", "compact1", customType="fixture", data={"retained": "extension history"})]


@pytest.fixture
def pi_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for name in ("PI_CODING_AGENT_DIR", "PI_CODING_AGENT_SESSION_DIR", "SESSION_INDEX_DIR"):
        monkeypatch.delenv(name, raising=False)
    sessions = home / ".pi/agent/sessions"
    main = write_records(sessions / "--fixture-project--/2026-11-12T10-00-00-000Z_main-native.jsonl",
                         native_records("main-native"))
    fork = write_records(sessions / "--fixture-other--/2026-11-12T10-01-00-000Z_fork-native.jsonl",
                         native_records("fork-native", main))
    # A direct --session file retains its chosen filename; preserve that too.
    direct = write_records(sessions / "daily.jsonl", native_records("daily-native"))
    auth = home / ".pi/agent/auth.json"
    auth.write_text('{"fixture":"SENTINEL-PI-AUTH-DO-NOT-COPY"}')
    (home / ".pi/agent/models.json").write_text('{"fixture":"SENTINEL-PI-CONFIG-OUTSIDE-SCOPE"}')
    archive = home / ".omp/agent/sessions/archived.jsonl"
    archive.parent.mkdir(parents=True)
    archive.write_text("historical archived client bytes\n")
    old_generation = tmp_path / "backups/20261101T000000Z"
    old_generation.mkdir(parents=True)
    (old_generation / "MANIFEST.json").write_text('{"ok":true,"archive":"retained"}')
    (old_generation / "retired-client.jsonl").write_text("existing backup history\n")
    return load_backup(), home, sessions, [main, fork, direct], archive, old_generation, tmp_path / "backups/new"


def file_snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


def test_default_inventory_restores_only_pi_session_tree(pi_home):
    module, home, sessions, *_ = pi_home
    stores = {store["name"]: store for store in module.build_stores(home)}
    assert stores["pi"] == {"name": "pi", "kind": "files", "roots": [("sessions", sessions)], "file_labels": []}
    assert {"omp", "omp-db", "opencode", "herdr"} <= stores.keys()
    assert module.Excluder(home).path(home / ".pi/agent/auth.json")


def test_backup_restores_complete_native_history_and_keeps_archives(pi_home):
    module, home, sessions, sources, archive, old_generation, dest = pi_home
    before = file_snapshot(home)
    archived_backup = file_snapshot(old_generation)
    assert module.main(["--only", "pi", "--strict-stores", "--dest", str(dest)]) == 0
    assert file_snapshot(home) == before
    assert file_snapshot(old_generation) == archived_backup
    manifest = json.loads((dest / "MANIFEST.json").read_text())
    [store] = manifest["stores"]
    assert manifest["ok"] and store["store"] == "pi" and store["status"] == "ok"
    assert store["file_count"] == 3
    for source in sources:
        copied = dest / "pi/sessions" / source.relative_to(sessions)
        assert copied.read_bytes() == source.read_bytes()
        entry = next(row for row in store["files"] if row["path"] == str(copied.relative_to(dest)))
        assert entry["sha256"] == hashlib.sha256(copied.read_bytes()).hexdigest()
        assert stat.S_IMODE(copied.stat().st_mode) == 0o600
    assert stat.S_IMODE(dest.stat().st_mode) == 0o700
    blob = b"".join(p.read_bytes() for p in dest.rglob("*") if p.is_file())
    assert b"SENTINEL-PI-AUTH" not in blob and b"SENTINEL-PI-CONFIG" not in blob

    # Simulate loss and recover into the original fixture session path, preserving
    # absolute parentSession links. Never start Pi or call a provider.
    shutil.rmtree(sessions)
    shutil.copytree(dest / "pi/sessions", sessions)
    for source in sources:
        assert source.read_bytes() == before[source.relative_to(home)]
    restored = [json.loads(line) for line in sources[0].read_text().splitlines()]
    entries = {row["id"]: row for row in restored[1:]}
    assert entries["answer01"]["parentId"] == entries["branch01"]["parentId"] == "user0001"
    assert entries["compact1"]["summary"] == "retained compaction summary"
    assert entries["custom01"]["data"] == {"retained": "extension history"}
    fork_header = json.loads(sources[1].read_text().splitlines()[0])
    assert Path(fork_header["parentSession"]).read_bytes() == sources[0].read_bytes()
    assert archive.read_bytes() == before[archive.relative_to(home)]

    # A fresh index, populated solely from restored files, recovers discoverable
    # history. The backup itself contains all native records, including records
    # the read-only archive search intentionally does not index.
    env = {**os.environ, "HOME": str(home), "SESSION_INDEX_DIR": str(home / "recovered-index"), "PATH": ""}
    result = subprocess.run([sys.executable, "-I", "-B", str(HISTORY), "--agent", "pi", "--update-only"],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([sys.executable, "-I", "-B", str(HISTORY), "--agent", "pi", "--json", "orchard"],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    found = json.loads(result.stdout)
    assert {row["sid"] for row in found} == {"main-native", "fork-native", "daily-native"}
    assert {row["title"] for row in found} == {"Recovery fixture name"}
    assert file_snapshot(old_generation) == archived_backup


def test_pi_credentials_and_linked_content_inside_sessions_are_excluded(pi_home):
    module, home, sessions, sources, archive, old_generation, dest = pi_home
    nested = sessions / "--credential-fixture--"
    nested.mkdir()
    for name in ("auth.json", "credentials.json", ".env", "mcp.json"):
        (nested / name).write_text("SENTINEL-NESTED-CREDENTIAL")
    (nested / "linked.jsonl").symlink_to(home / ".pi/agent/auth.json")
    (nested / "linked-session.jsonl").symlink_to(sources[0])
    assert module.main(["--only", "pi", "--dest", str(dest)]) == 0
    assert not (dest / "pi/sessions/--credential-fixture--").exists() or not list(
        (dest / "pi/sessions/--credential-fixture--").iterdir())
    blob = b"".join(p.read_bytes() for p in dest.rglob("*") if p.is_file())
    assert b"SENTINEL-NESTED-CREDENTIAL" not in blob and b"SENTINEL-PI-AUTH" not in blob
    skipped = json.loads((dest / "MANIFEST.json").read_text())["stores"][0]["skipped"]
    assert {row["why"] for row in skipped} >= {"symlink", "excluded credential path"}


def test_pi_dry_run_and_schema_check_leave_fixture_tree_unchanged(pi_home, capsys):
    module, home, sessions, sources, archive, old_generation, dest = pi_home
    before = file_snapshot(home)
    assert module.main(["--only", "pi", "--dry-run", "--json", "--dest", str(dest)]) == 0
    assert not dest.exists() and not dest.with_name(dest.name + ".part").exists()
    assert module.main(["--only", "pi", "--check-schemas", "--json"]) == 0
    assert file_snapshot(home) == before
    assert "SENTINEL-PI-AUTH" not in capsys.readouterr().out


def test_pi_destination_inside_sessions_is_refused(pi_home):
    module, home, sessions, *_ = pi_home
    before = file_snapshot(home)
    assert module.main(["--only", "pi", "--dest", str(sessions / "backup")]) == 2
    assert file_snapshot(home) == before


def test_missing_pi_sessions_are_reported_and_strict_fails(tmp_path, monkeypatch):
    home = tmp_path / "empty-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    module = load_backup()
    dest = tmp_path / "backup"
    assert module.main(["--only", "pi", "--strict-stores", "--dest", str(dest)]) == 1
    manifest = json.loads((dest / "MANIFEST.json").read_text())
    assert not manifest["ok"] and manifest["stores"][0]["status"] == "missing"
    assert not (home / ".pi").exists()


def test_pi_session_root_link_outside_home_is_refused(pi_home, tmp_path):
    module, home, sessions, sources, archive, old_generation, dest = pi_home
    outside = tmp_path / "outside-home"
    shutil.move(str(sessions), outside)
    sessions.symlink_to(outside, target_is_directory=True)
    before = file_snapshot(outside)
    assert module.main(["--only", "pi", "--dest", str(dest)]) == 1
    manifest = json.loads((dest / "MANIFEST.json").read_text())
    assert not manifest["ok"] and manifest["stores"][0]["status"] == "partial"
    assert any("outside HOME" in row["error"] for row in manifest["errors"])
    assert file_snapshot(outside) == before
    assert not list((dest / "pi").rglob("*.jsonl"))
