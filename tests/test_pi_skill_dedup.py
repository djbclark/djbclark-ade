"""Synthetic homes only: never load the developer's Pi settings or skills."""
import json
import os
from pathlib import Path
import runpy
from types import SimpleNamespace
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


@pytest.mark.parametrize("suffix", ["", "/SKILL.md"])
@pytest.mark.parametrize("prefix", ["file://", "./file://", "file://localhost"])
def test_pi_file_url_keeper_exclusions_refused(case, suffix, prefix):
    # Pi normalizeExactPattern -> normalizePath -> fileURLToPath, not Path('file:...').
    settings = {"skills": ["-" + prefix + str(case.shared) + suffix]}
    case.settings.write_text(json.dumps(settings))
    before = case.settings.read_bytes()
    result = case.plan(rc=2)
    assert "unsupported exact skill exclusion syntax" in result.stderr
    assert not case.plan_path.exists()
    assert case.settings.read_bytes() == before


@pytest.mark.parametrize("entry", ["-", r"-.\skills\alpha", "-~another-user/skills/alpha"])
def test_unsupported_exact_path_syntax_refused(case, entry):
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


@pytest.mark.parametrize("source", ["file", "directory", "file-url"])
@pytest.mark.parametrize("exclusion", ["absolute", "relative", "tilde", "file-url"])
def test_project_explicit_disabled_global_keeper_shadows_autodiscovery(case, tmp_path, source, exclusion):
    project = tmp_path / "project"
    local = case.bundle(project / ".agents" / "skills", "graft")
    keeper = case.bundle(case.shared_root, "graft") / "SKILL.md"
    (project / ".pi").mkdir()
    settings = project / ".pi" / "settings.json"
    include = {"file": str(keeper), "directory": str(keeper.parent), "file-url": keeper.as_uri()}[source]
    exclude = {"absolute": str(keeper), "relative": os.path.relpath(keeper, settings.parent),
               "tilde": "~/" + str(keeper.relative_to(case.home)), "file-url": keeper.as_uri()}[exclusion]
    # Pi resolveLocalEntries(project) inserts even disabled entries; addResource
    # will not replace that entry with the later enabled global autodiscovery.
    settings.write_text(json.dumps({"skills": [include, "-" + exclude]}))
    before = settings.read_bytes()
    case.run("plan", "--project", project, "--pair", local, keeper.parent,
             "--output", case.plan_path, rc=2)
    assert settings.read_bytes() == before
    assert not case.plan_path.exists()
    assert json.loads(case.settings.read_text()) == {}


def test_project_apply_rechecks_global_file_url_filter(case, tmp_path):
    project = tmp_path / "project"
    local = case.bundle(project / ".agents" / "skills", "graft")
    keeper = case.bundle(case.shared_root, "graft")
    (project / ".pi").mkdir()
    settings = project / ".pi" / "settings.json"
    settings.write_text('{}')
    case.run("plan", "--project", project, "--pair", local, keeper, "--output", case.plan_path)
    case.claim(settings)
    case.settings.write_text(json.dumps({"skills": ["-" + (keeper / "SKILL.md").as_uri()]}))
    case.apply(rc=2)
    assert settings.read_text() == '{}'
    assert not case.receipt.exists()


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


def test_refused_apply_retires_receipt_and_rerun_works(case):
    case.plan()
    case.settings.chmod(0o666)
    case.apply(rc=2)
    assert json.loads(case.settings.read_text()) == {}
    # A refusal happens before replacement: no stray receipt may block a rerun.
    assert not case.receipt.exists()
    case.settings.chmod(0o600)
    case.apply()
    assert case.receipt.exists()
    assert "skills" in json.loads(case.settings.read_text())


def test_metadata_probe_refusal_retires_receipt(case, monkeypatch):
    ns = runpy.run_path(str(TOOL))
    case.plan()
    monkeypatch.setenv("HOME", str(case.settings.parents[2]))
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(case.settings.parent))
    monkeypatch.setenv("ADE_STATE_DIR", str(case.settings.parents[3] / "state"))
    monkeypatch.setenv("ADE_CLAIM_ID", "synthetic-runtime")
    monkeypatch.syspath_prepend(str(TOOL.parent))
    def refuse(path):
        raise ns["Refused"]("synthetic metadata refusal")
    monkeypatch.setitem(ns["apply"].__globals__, "plain_metadata", refuse)
    with pytest.raises(ns["Refused"], match="synthetic metadata"):
        ns["apply"](case.plan_path, case.receipt)
    assert not case.receipt.exists()
    assert json.loads(case.settings.read_text()) == {}


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


@pytest.mark.parametrize("left_mode,right_mode", [(0o700, 0o601), (0o710, 0o701)])
def test_distinct_execute_masks_are_not_equivalent(case, left_mode, right_mode):
    (case.native / "helper.py").chmod(left_mode)
    (case.shared / "helper.py").chmod(right_mode)
    case.plan(rc=2)
    assert not case.plan_path.exists()
    assert json.loads(case.settings.read_text()) == {}


def test_root_directory_access_metadata_compared(case):
    case.native.chmod(0o700)
    case.shared.chmod(0o755)
    case.plan(rc=2)
    assert not case.plan_path.exists()


def test_apply_rechecks_execute_masks(case):
    for root in (case.native, case.shared):
        (root / "helper.py").chmod(0o700)
    case.plan()
    (case.shared / "helper.py").chmod(0o601)
    case.apply(rc=2)
    assert not case.receipt.exists()
    assert json.loads(case.settings.read_text()) == {}


def test_matching_executable_helpers_remain_supported(case):
    for root in (case.native, case.shared):
        (root / "helper.py").chmod(0o700)
    case.plan()
    case.apply()
    case.undo()


def test_same_modes_different_effective_access_or_ownership_are_not_equivalent(case, monkeypatch):
    ns = runpy.run_path(str(TOOL))
    signature = ns["access_signature"]
    path = case.native / "helper.py"
    info = path.stat()
    monkeypatch.setattr(os, "access", lambda p, mode: True)
    executable = signature(path, info)
    monkeypatch.setattr(os, "access", lambda p, mode: mode != os.X_OK)
    assert executable != signature(path, info)
    monkeypatch.setattr(os, "access", lambda p, mode: True)
    other_group = SimpleNamespace(st_mode=info.st_mode, st_uid=info.st_uid, st_gid=info.st_gid + 1)
    assert executable != signature(path, other_group)


@pytest.mark.parametrize("attribute", ["system.posix_acl_access", "user.synthetic"])
@pytest.mark.parametrize("where", ["original", "temporary"])
def test_settings_extended_metadata_refused(case, monkeypatch, attribute, where):
    ns = runpy.run_path(str(TOOL))
    monkeypatch.setattr(os, "listxattr", lambda p: [attribute] if (
        (Path(p) == case.settings) == (where == "original")) else [], raising=False)
    before = case.settings.read_bytes()
    with pytest.raises(ns["Refused"], match="extended attributes"):
        ns["atomic"](case.settings, b'changed', expected=before)
    assert case.settings.read_bytes() == before


@pytest.mark.parametrize("mode,refused", [("-rw-------", False), ("-rw-------+", True), ("", True)])
def test_darwin_acl_probe_fails_closed(case, monkeypatch, mode, refused):
    ns = runpy.run_path(str(TOOL))
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(os, "listxattr", lambda p: [], raising=False)
    monkeypatch.setattr(os, "stat", lambda p: SimpleNamespace(st_flags=0))
    def probe(argv, **kwargs):
        assert argv == ["/bin/ls", "-lde", str(case.settings)]
        assert kwargs["capture_output"] and kwargs["env"]["LC_ALL"] == "C"
        return SimpleNamespace(returncode=0, stderr="", stdout=mode + " synthetic")
    monkeypatch.setattr(subprocess, "run", probe)
    if refused:
        with pytest.raises(ns["Refused"], match="ACL"):
            ns["plain_metadata"](case.settings)
    else:
        ns["plain_metadata"](case.settings)


def test_darwin_acl_probe_timeout_refused(case, monkeypatch):
    ns = runpy.run_path(str(TOOL))
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(os, "listxattr", lambda p: [], raising=False)
    monkeypatch.setattr(os, "stat", lambda p: SimpleNamespace(st_flags=0))
    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 10)
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(ns["Refused"], match="ACL"):
        ns["plain_metadata"](case.settings)


def linux_only():
    if sys.platform != "linux":
        pytest.skip("Linux inode-flag behavior is only exercised on Linux")


@pytest.mark.parametrize("flags,refused", [(0, False), (0x80000, False), (0x40, True),
                                           (0x10, True), (0x80000 | 0x800000, True)])
@pytest.mark.parametrize("where", ["original", "temporary"])
def test_linux_inode_flags_policy(case, monkeypatch, flags, refused, where):
    linux_only()
    ns = runpy.run_path(str(TOOL))
    monkeypatch.setitem(ns["plain_metadata"].__globals__, "linux_inode_flags",
                        lambda p: flags if (Path(p) == case.settings) == (where == "original") else 0)
    before = case.settings.read_bytes()
    if refused:
        with pytest.raises(ns["Refused"], match="flags"):
            ns["atomic"](case.settings, b'{"x":1}\n', expected=before)
        assert case.settings.read_bytes() == before
    else:
        ns["atomic"](case.settings, b'{"x":1}\n', expected=before)
        assert case.settings.read_bytes() == b'{"x":1}\n'


def test_linux_inode_flag_probe_failure_refused(case, monkeypatch):
    linux_only()
    ns = runpy.run_path(str(TOOL))
    import fcntl
    def unsupported(*args):
        raise OSError(25, "Inappropriate ioctl")
    monkeypatch.setattr(fcntl, "ioctl", unsupported)
    before = case.settings.read_bytes()
    with pytest.raises(ns["Refused"], match="inode flags could not be verified"):
        ns["atomic"](case.settings, b'{"x":1}\n', expected=before)
    assert case.settings.read_bytes() == before


def test_linux_real_probe_returns_integer(case):
    linux_only()
    ns = runpy.run_path(str(TOOL))
    try:
        flags = ns["linux_inode_flags"](case.settings)
    except ns["Refused"]:
        pytest.skip("filesystem does not support FS_IOC_GETFLAGS")
    assert isinstance(flags, int) and flags >= 0


def test_darwin_libc_xattr_probe_detects_real_xattr(case, monkeypatch):
    if sys.platform != "darwin":
        pytest.skip("native macOS libc xattr probe needs macOS")
    ns = runpy.run_path(str(TOOL))
    monkeypatch.delattr(os, "listxattr", raising=False)  # force the ctypes path
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    libc.setxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
                              ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
    assert not ns["darwin_has_xattrs"](case.settings)
    assert libc.setxattr(os.fsencode(case.settings), b"user.synthetic", b"x", 1, 0, 0) == 0
    assert ns["darwin_has_xattrs"](case.settings)


def test_missing_libc_xattr_probe_refuses(case, monkeypatch):
    ns = runpy.run_path(str(TOOL))
    monkeypatch.delattr(os, "listxattr", raising=False)
    import ctypes
    def broken(*args, **kwargs):
        raise OSError("no libc")
    monkeypatch.setattr(ctypes, "CDLL", broken)
    with pytest.raises(ns["Refused"], match="extended attributes could not be verified"):
        ns["darwin_has_xattrs"](case.settings)


def test_linux_ioctl_request_and_decoding(case, monkeypatch):
    linux_only()
    import ctypes
    import fcntl
    ns = runpy.run_path(str(TOOL))
    seen = {}
    def fake(fd, request, buffer, mutate):
        seen["request"] = request
        assert mutate and len(buffer) == ctypes.sizeof(ctypes.c_long)
        buffer[:4] = (0x40).to_bytes(4, sys.byteorder)  # kernel writes a 4-byte int
        return 0
    monkeypatch.setattr(fcntl, "ioctl", fake)
    assert ns["linux_inode_flags"](case.settings) == 0x40
    if ctypes.sizeof(ctypes.c_long) == 8:
        assert seen["request"] == 0x80086601  # FS_IOC_GETFLAGS, 64-bit Linux
    assert ns["LINUX_LAYOUT_FLAGS"] == 0x80000 | 0x10000000 | 0x40000  # EXTENTS|INLINE_DATA|HUGE_FILE


def test_darwin_nonzero_or_missing_file_flags_refused(case, monkeypatch):
    ns = runpy.run_path(str(TOOL))
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(os, "listxattr", lambda p: [], raising=False)
    for info in (SimpleNamespace(st_flags=2), SimpleNamespace()):
        monkeypatch.setattr(os, "stat", lambda p, info=info: info)
        with pytest.raises(ns["Refused"], match="flags"):
            ns["plain_metadata"](case.settings)


def test_replacement_group_mismatch_refused(case, monkeypatch):
    ns = runpy.run_path(str(TOOL))
    original_fstat = os.fstat
    def different_group(fd):
        info = original_fstat(fd)
        return SimpleNamespace(st_uid=info.st_uid, st_gid=info.st_gid + 1)
    before = case.settings.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(os, "fstat", different_group)
        with pytest.raises(ns["Refused"], match="ownership/group"):
            ns["atomic"](case.settings, b'changed', expected=before)
    assert case.settings.read_bytes() == before
    assert not list(case.settings.parent.glob(".pi-skill-dedup-*"))


def test_multiple_pairs(case):
    left = case.bundle(case.agent / "skills", "beta")
    right = case.bundle(case.shared_root, "beta")
    case.plan("--pair", left, right)
    case.apply()
    assert len(json.loads(case.settings.read_text())["skills"]) == 2
    case.undo()
