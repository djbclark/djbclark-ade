"""Synthetic homes only: never load the developer's Pi settings or skills."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


TOOL = Path(__file__).resolve().parents[1] / "bin" / "pi-skill-dedup"


@pytest.fixture
def case(tmp_path):
    home = tmp_path / "home"
    agent = home / ".pi" / "agent"
    shared = home / ".agents" / "skills"
    agent.mkdir(parents=True)
    shared.mkdir(parents=True)
    settings = agent / "settings.json"
    settings.write_text('{}\n')
    state = tmp_path / "state"
    claims = state / "claims"
    claims.mkdir(parents=True)
    env = dict(os.environ, HOME=str(home), PI_CODING_AGENT_DIR=str(agent),
               ADE_STATE_DIR=str(state), ADE_CLAIM_ID="synthetic-runtime")

    class Case:
        def bundle(self, parent, name="alpha", extra="same"):
            root = parent / name
            root.mkdir(parents=True)
            (root / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Synthetic test skill\n---\nDo work.\n")
            (root / "helper.py").write_text(extra)
            return root

        def run(self, *args, rc=0):
            result = subprocess.run([sys.executable, str(TOOL), *map(str, args)], env=env,
                                    text=True, capture_output=True, timeout=10)
            assert result.returncode == rc, result.stdout + result.stderr
            return result

        def claim(self, target=None, state="active"):
            (claims / "synthetic-runtime.json").write_text(json.dumps({
                "id": "synthetic-runtime", "state": state, "path": str((target or settings).resolve()),
                "owner": {"session": "test"}}))

        def plan(self, *extra, rc=0):
            return self.run("plan", "--pair", self.native, self.shared,
                            "--output", self.plan_path, *extra, rc=rc)

        def apply(self, rc=0):
            return self.run("apply", "--plan", self.plan_path, "--receipt", self.receipt, rc=rc)

        def undo(self, execute=True, rc=0):
            return self.run("undo", "--receipt", self.receipt, *( ["--apply"] if execute else []), rc=rc)

    c = Case()
    c.home, c.agent, c.settings, c.shared_root = home, agent, settings, shared
    c.native = c.bundle(agent / "skills")
    c.shared = c.bundle(shared)
    c.plan_path, c.receipt = tmp_path / "plan.json", tmp_path / "receipt.json"
    c.claim()
    return c


def test_dry_run_apply_undo_preserve_user_settings(case):
    original = {"theme": "secret-sentinel-not-output", "skills": ["-/unrelated/SKILL.md"], "other": {"v": 7}}
    case.settings.write_text(json.dumps(original))
    before = case.settings.read_bytes()
    result = case.plan()
    assert "secret-sentinel" not in result.stdout + result.stderr
    assert case.settings.read_bytes() == before
    case.apply()
    changed = json.loads(case.settings.read_text())
    assert changed["skills"] == original["skills"] + ["-" + str(case.native / "SKILL.md")]
    changed["theme"] = "later-user-edit"
    case.settings.write_text(json.dumps(changed))
    case.undo(execute=False)
    assert json.loads(case.settings.read_text()) == changed
    case.undo()
    original["theme"] = "later-user-edit"
    assert json.loads(case.settings.read_text()) == original
    case.undo()  # idempotent
    assert case.native.is_dir() and case.shared.is_dir()


def test_undo_restores_absent_key_and_preserves_real_target_symlink(case, tmp_path):
    real = tmp_path / "real-settings.json"
    case.settings.rename(real)
    case.settings.symlink_to(real)
    real.chmod(0o640)
    case.claim()
    case.plan()
    case.apply()
    assert case.settings.is_symlink()
    assert real.stat().st_mode & 0o777 == 0o640
    case.undo()
    assert json.loads(real.read_text()) == {}
    assert case.settings.is_symlink()


def test_root_skill_symlinks_supported(case, tmp_path):
    dest = tmp_path / "canonical-alpha"
    case.shared.rename(dest)
    case.shared.symlink_to(dest, target_is_directory=True)
    case.plan()
    case.apply()
    assert case.shared.is_symlink()


@pytest.mark.parametrize("change", ["instruction", "support", "mode", "internal-link", "missing", "ignore", "root-skill"])
def test_no_exclusion_without_equivalence_and_discovery(case, change):
    if change == "instruction":
        (case.shared / "SKILL.md").write_text("different")
    elif change == "support":
        (case.shared / "helper.py").write_text("different")
    elif change == "mode":
        (case.shared / "helper.py").chmod(0o755)
    elif change == "internal-link":
        (case.shared / "link").symlink_to(case.shared / "helper.py")
    elif change == "missing":
        (case.shared / "SKILL.md").unlink()
    elif change == "ignore":
        (case.shared_root / ".gitignore").write_text("alpha/\n")
    else:
        (case.shared_root / "SKILL.md").write_text("shadows discovery")
    case.plan(rc=2)
    assert not case.plan_path.exists()
    assert json.loads(case.settings.read_text()) == {}


@pytest.mark.parametrize("raw", ['[]', '{', '{"skills":null}', '{"skills":[1]}',
                                  '{"skills":[],"skills":[]}', '{"x":NaN}'])
def test_malformed_settings_fail_closed(case, raw):
    case.settings.write_text(raw)
    case.plan(rc=2)
    assert case.settings.read_text() == raw


@pytest.mark.parametrize("entry", ["!**/alpha/**", "-skills/alpha/SKILL.md", "-skills/alpha"])
def test_existing_keeper_filters_refused(case, entry):
    case.settings.write_text(json.dumps({"skills": [entry]}))
    case.plan(rc=2)


@pytest.mark.parametrize("change", ["settings", "skill", "retarget"])
def test_stale_plan_refused(case, tmp_path, change):
    case.plan()
    if change == "settings":
        case.settings.write_text('{"theme":"later"}')
    elif change == "skill":
        (case.native / "helper.py").write_text("later")
    else:
        dest = tmp_path / "replacement"
        case.shared.rename(dest)
        case.shared.symlink_to(dest, target_is_directory=True)
    before = case.settings.read_bytes()
    case.apply(rc=2)
    assert case.settings.read_bytes() == before
    assert not case.receipt.exists()


def test_undo_refuses_later_skill_edits(case):
    case.plan()
    case.apply()
    data = json.loads(case.settings.read_text())
    data["skills"].append("user-added")
    case.settings.write_text(json.dumps(data))
    before = case.settings.read_bytes()
    case.undo(rc=2)
    assert case.settings.read_bytes() == before


@pytest.mark.parametrize("state", ["released", "wrong-target"])
def test_runtime_claim_required(case, state):
    case.plan()
    case.claim(case.home if state == "wrong-target" else None,
               state="active" if state == "wrong-target" else state)
    case.apply(rc=2)
    assert not case.receipt.exists()


def test_project_graft_excludes_only_project_copy(case, tmp_path):
    project = tmp_path / "project"
    local = case.bundle(project / ".agents" / "skills", "graft")
    global_graft = case.bundle(case.shared_root, "graft")
    (project / ".pi").mkdir()
    local_settings = project / ".pi" / "settings.json"
    local_settings.write_text('{}')
    case.run("plan", "--project", project, "--pair", local, global_graft, "--output", case.plan_path)
    case.claim(local_settings)
    case.apply()
    assert json.loads(case.settings.read_text()) == {}
    assert json.loads(local_settings.read_text())["skills"] == ["-" + str(local / "SKILL.md")]
    case.undo()
    assert json.loads(local_settings.read_text()) == {}


def test_global_mode_rejects_project_keeper(case, tmp_path):
    local = case.bundle(tmp_path / "project" / ".agents" / "skills", "alpha")
    case.run("plan", "--pair", case.native, local, rc=2)


def test_no_clobber_plan_and_receipt(case):
    case.plan()
    case.plan(rc=2)
    case.receipt.symlink_to(case.settings)
    case.apply(rc=2)
    assert json.loads(case.settings.read_text()) == {}


def test_already_excluded_pair_is_noop(case):
    case.settings.write_text(json.dumps({"skills": ["-" + str(case.native / "SKILL.md")]}))
    case.plan()
    case.apply()
    assert not case.receipt.exists()


def test_fifo_refused_without_blocking(case):
    (case.shared / "helper.py").unlink()
    os.mkfifo(case.shared / "helper.py")
    case.plan(rc=2)


def test_undo_rejects_malformed_receipt(case):
    case.receipt.write_text('{"version":1}')
    case.undo(rc=2)


def test_same_real_bundle_refused(case, tmp_path):
    import shutil
    shutil.rmtree(case.shared)
    case.shared.symlink_to(case.native, target_is_directory=True)
    case.plan(rc=2)


def test_edited_plan_refused(case):
    case.plan()
    plan = json.loads(case.plan_path.read_text())
    plan["additions"] = ["-/unrelated/SKILL.md"]
    case.plan_path.write_text(json.dumps(plan))
    case.apply(rc=2)


def test_unsafe_settings_mode_and_prepared_receipt_recovery(case):
    case.plan()
    case.settings.chmod(0o666)
    case.apply(rc=2)
    assert json.loads(case.settings.read_text()) == {}
    # Receipt is intentionally published before replacement; undo is a no-op.
    assert case.receipt.exists()
    case.undo()


def test_undo_requires_claim_and_rejects_retarget(case, tmp_path):
    case.plan()
    case.apply()
    case.claim(state="released")
    case.undo(rc=2)
    original = case.settings.read_bytes()
    case.claim()
    other = tmp_path / "other-settings.json"
    other.write_bytes(original)
    case.settings.unlink()
    case.settings.symlink_to(other)
    case.undo(rc=2)
    assert other.read_bytes() == original


def test_multiple_pairs(case):
    left = case.bundle(case.agent / "skills", "beta")
    right = case.bundle(case.shared_root, "beta")
    case.plan("--pair", left, right)
    case.apply()
    assert len(json.loads(case.settings.read_text())["skills"]) == 2
    case.undo()
