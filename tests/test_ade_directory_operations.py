"""Real isolated Python/filesystem business tests, NOT native qualification.

Git fact DATA is deliberately synthetic. No fake native owner/provider/receipt
is constructed and no real home/claim registry is used.
"""
from __future__ import annotations

import contextlib
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "bin/ade_directory_operations.py"
spec = importlib.util.spec_from_file_location("directory_operations_test", ENTRY)
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)
claims = ops.claims


@pytest.fixture
def world(tmp_path, monkeypatch):
    state = tmp_path / "state"
    cwd = tmp_path / "repo"
    git = cwd / ".git"
    git.mkdir(parents=True)
    monkeypatch.setenv("ADE_STATE_DIR", str(state))
    # Any accidental inference must not inherit unrelated TUI ownership.
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "unrelated-session")
    monkeypatch.setattr(claims, "_own_claude_session_id", lambda: pytest.fail("session inference"))
    monkeypatch.setattr(claims, "_run_git", lambda *a, **kw: pytest.fail("nested Git"))
    monkeypatch.setattr(ops.names, "repo_of", lambda *a, **kw: pytest.fail("nested naming Git"))
    return cwd, git, state


def envelope(world, operation, **fields):
    cwd, git, _ = world
    facts = {}
    if operation == "claim-new":
        fields = {"branch": "feature", "claimId": "claim-1", "ttlHours": 72,
                  "ownerAgent": "", "ownerRecord": None, **fields}
        facts = {"head": "a" * 40, "origin": "", "gitDir": str(git)}
    elif operation == "claim-install-hooks":
        facts = {"commonDir": str(git), "hooksStatus": 1, "hooksOutput": ""}
    elif operation == "window-name-decision":
        fields = {"windowTitle": None, "firstAgent": True, "background": False,
                  "agent": {"title": "Implement real naming", "parentAgentId": None, "labels": {}}, **fields}
        facts = {"commonDir": str(git)}
    return {"version": 1, "request": {"version": 1, "operation": operation, "cwd": str(cwd), **fields},
            "facts": facts}


def run_process(world, data, *, raw=False, args=()):
    env = {**os.environ, "ADE_STATE_DIR": str(world[2]), "PYTHONPATH": "/nonexistent/untrusted"}
    return subprocess.run([sys.executable, "-I", "-S", str(ENTRY), *args],
                          input=data if raw else json.dumps(data).encode(),
                          capture_output=True, timeout=10, env=env)


def run_fault_process(world, data, patch):
    """CI-only fault injection around real shared phases; no production switch."""
    script = ("import sys\nfrom pathlib import Path\n"
              f"sys.path.insert(0, {str(ENTRY.parent)!r})\n"
              "import ade_directory_operations as ops\n" + patch + "\nsys.exit(ops.main())\n")
    return subprocess.run([sys.executable, "-I", "-S", "-c", script],
                          input=json.dumps(data).encode(), capture_output=True, timeout=10,
                          env={**os.environ, "ADE_STATE_DIR": str(world[2])})


def assert_unknown_failure(process):
    assert process.returncode == 1, process.stderr
    assert process.stdout == b""
    assert process.stderr == b"Directory operation failed.\n"


def outcome(result, status=0):
    assert result["version"] == 1
    assert result["status"] == status
    assert set(result) == {"version", "status", "output"}
    return result["output"]


def test_real_isolated_create_bind_list_release_no_inferred_session(world):
    created = run_process(world, envelope(world, "claim-new"))
    assert created.returncode == 0, created.stderr
    output = outcome(json.loads(created.stdout))
    assert output == {"claimId": "claim-1", "registryPath": str(world[2] / "claims/claim-1.json")}
    assert (world[1] / "ade-claim").read_text() == "claim-1\n"
    record = json.loads(Path(output["registryPath"]).read_text())
    assert record["owner"] == {"agent": "", "record": None, "session": None, "model": ""}
    assert record["created_by"] == "paseo-ade-claim-plugin"
    bound = run_process(world, envelope(world, "claim-bind-owner", claimId="claim-1", agentId="agent-1"))
    assert bound.returncode == 0, bound.stderr
    assert outcome(json.loads(bound.stdout)) == {"claimId": "claim-1"}
    listed = outcome(ops.dispatch(envelope(world, "claim-list")))
    assert len(listed) == 1
    assert listed[0]["shown_state"] == "active"
    assert listed[0]["owner"]["agent"] == listed[0]["owner"]["record"] == "agent-1"
    released = run_process(world, envelope(world, "claim-release", claimId="claim-1"))
    assert released.returncode == 0, released.stderr
    assert outcome(json.loads(released.stdout)) == {"claimId": "claim-1"}
    assert outcome(ops.dispatch(envelope(world, "claim-list"))) == []
    assert claims.read_claim("claim-1")["state"] == "released"
    assert (world[1] / "ade-claim").exists()  # Existing shared retention semantics.


def test_exclusive_foreign_owner_and_bind_refusal_preserve_bytes(world):
    request = envelope(world, "claim-new", ownerRecord="first")
    outcome(ops.dispatch(request))
    before = claims.claim_file("claim-1").read_bytes()
    outcome(ops.dispatch(request), 3)
    outcome(ops.dispatch(envelope(world, "claim-new", claimId="other", ownerRecord="foreign")), 4)
    assert not claims.claim_file("other").exists()
    outcome(ops.dispatch(envelope(world, "claim-bind-owner", claimId="claim-1", agentId="agent-1")))
    owned = claims.claim_file("claim-1").read_bytes()
    result = ops.dispatch(envelope(world, "claim-bind-owner", claimId="claim-1", agentId="agent-2"))
    assert outcome(result, 2)["kind"] == "claim-refused"
    assert claims.claim_file("claim-1").read_bytes() == owned != before


def test_same_record_reclaim_preserves_shared_transition_and_prior_artifact(world):
    outcome(ops.dispatch(envelope(world, "claim-new", ownerRecord="record")))
    outcome(ops.dispatch(envelope(world, "claim-new", claimId="successor", ownerRecord="record")))
    assert claims.read_claim("claim-1")["state"] == "released"
    assert claims.read_claim("successor")["state"] == "active"
    assert (world[1] / "ade-claim").read_text() == "successor\n"


@pytest.mark.parametrize("operation", ["claim-bind-owner", "claim-release"])
def test_expected_path_rechecked_after_real_lock_acquisition(world, tmp_path, monkeypatch, operation):
    outcome(ops.dispatch(envelope(world, "claim-new")))
    other = tmp_path / "other"
    other.mkdir()
    original_lock = claims._claims_lock
    observed = []

    @contextlib.contextmanager
    def changed_under_lock():
        with original_lock():
            # A controlled preceding writer changes association before the API's
            # read. The expected-path check must be INSIDE this same lock.
            with open(claims.claims_dir() / ".lock", "a+") as competing:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
            claims._update_unlocked("claim-1", path=str(other))
            observed.append(claims.claim_file("claim-1").read_bytes())
            yield

    monkeypatch.setattr(claims, "_claims_lock", changed_under_lock)
    fields = {"claimId": "claim-1", **({"agentId": "agent-1"} if operation == "claim-bind-owner" else {})}
    result = ops.dispatch(envelope(world, operation, **fields))
    assert outcome(result, 2)["kind"] == "claim-refused"
    assert claims.claim_file("claim-1").read_bytes() == observed[0]


def test_shared_optional_path_checks_leave_ordinary_defaults(world):
    outcome(ops.dispatch(envelope(world, "claim-new")))
    claims.bind_owner("claim-1", owner_agent="agent")
    claims.set_state("claim-1", "released")
    assert claims.read_claim("claim-1")["state"] == "released"


def test_real_linked_gitfile_pointer_and_common_directory(world, tmp_path):
    cwd, common, state = world
    linked = tmp_path / "linked"
    linked.mkdir()
    gitdir = common / "worktrees/linked"
    gitdir.mkdir(parents=True)
    (gitdir / "commondir").write_text("../..\n")
    (gitdir / "gitdir").write_text(str(linked / ".git") + "\n")
    (linked / ".git").write_text("gitdir: " + str(gitdir) + "\n")
    selected = (linked, gitdir, state)
    outcome(ops.dispatch(envelope(selected, "claim-new")))
    assert (gitdir / "ade-claim").read_text() == "claim-1\n"
    install = envelope(selected, "claim-install-hooks")
    install["facts"]["commonDir"] = str(common)
    outcome(ops.dispatch(install))
    assert (common / "hooks/reference-transaction").exists()


def test_actual_hook_chain_preserved_install_idempotent_without_nested_git(world):
    hooks = world[1] / "hooks"
    hooks.mkdir()
    old = b"#!/bin/sh\nprintf 'old-hook'\n"
    (hooks / "pre-push").write_bytes(old)
    result = outcome(ops.dispatch(envelope(world, "claim-install-hooks")))
    assert any("existing hook kept" in line for line in result["notes"])
    assert (hooks / "pre-push.pre-ade").read_bytes() == old
    installed = (hooks / "pre-push").read_bytes()
    assert b".pre-ade" in installed
    assert (hooks / "pre-push").stat().st_mode & 0o111
    outcome(ops.dispatch(envelope(world, "claim-install-hooks")))
    assert (hooks / "pre-push").read_bytes() == installed
    assert (hooks / "pre-push.pre-ade").read_bytes() == old


def test_actual_hook_conflict_refuses_preserving_existing_chain(world):
    hooks = world[1] / "hooks"
    hooks.mkdir()
    # The first actual HOOK_NAMES member conflicts, so no unrelated hook was written.
    name = claims.HOOK_NAMES[0]
    (hooks / name).write_text("original")
    (hooks / (name + ".pre-ade")).write_text("older")
    before = {p.name: p.read_bytes() for p in hooks.iterdir()}
    assert outcome(ops.dispatch(envelope(world, "claim-install-hooks")), 73)["notes"]
    assert {p.name: p.read_bytes() for p in hooks.iterdir()} == before


@pytest.mark.parametrize("value", ["", "\0", "/custom/hooks\0", "first\0second\0"])
def test_set_even_empty_hookspath_refuses_without_writes(world, value):
    request = envelope(world, "claim-install-hooks")
    request["facts"].update(hooksStatus=0, hooksOutput=value)
    assert outcome(ops.dispatch(request), 78)["notes"]
    assert not (world[1] / "hooks").exists()


@pytest.mark.parametrize("change,expected", [
    ({}, {"action": "rename", "kind": "LEAD", "repo": "repo"}),
    ({"background": True}, {"action": "skip", "retry": False}),
    ({"firstAgent": False}, {"action": "skip", "retry": True}),
    ({"windowTitle": "Human title"}, {"action": "skip", "retry": False}),
    ({"agent": {"title": None, "parentAgentId": None, "labels": {}}}, {"action": "skip", "retry": True}),
    ({"agent": {"title": "Implement real naming", "parentAgentId": "parent", "labels": {}}},
     {"action": "rename", "kind": "WORKER"}),
])
def test_real_shared_naming_decisions(world, change, expected):
    result = outcome(ops.dispatch(envelope(world, "window-name-decision", **change)))
    assert all(result[k] == v for k, v in expected.items())
    if result["action"] == "rename":
        assert result["name"] == ops.names.build(result["kind"], result["repo"], result["work"])
        assert set(result) == {"action", "name", "kind", "repo", "work"}
    else:
        assert set(result) == {"action", "reason", "retry"}


@pytest.mark.parametrize("field,value", [
    ("version", True), ("cwd", "/missing-directory"), ("claimId", "../escape"),
    ("ownerAgent", "a" * 129), ("ownerRecord", "bad/id"), ("ttlHours", True),
    ("ttlHours", -1), ("ttlHours", 8785), ("ttlHours", 10 ** 400), ("ttlHours", float("nan")),
    ("ttlHours", float("inf")), ("branch", "x" * 1025), ("branch", "\ud800"),
    ("branch", "a\0b"), ("argv", []), ("stateDir", "/tmp/elsewhere"),
])
def test_malformed_request_no_partial_writes(world, field, value):
    request = envelope(world, "claim-new")
    request["request"][field] = value
    assert outcome(ops.dispatch(request), 2)["kind"] == "invalid-request"
    assert not world[2].exists()
    assert not (world[1] / "ade-claim").exists()


@pytest.mark.parametrize("fact,value", [("head", "b" * 39), ("head", "B" * 40),
                                       ("gitDir", "/missing"), ("origin", 3),
                                       ("verified", True)])
def test_malformed_fact_no_partial_writes(world, fact, value):
    request = envelope(world, "claim-new")
    request["facts"][fact] = value
    assert outcome(ops.dispatch(request), 2)["kind"] == "invalid-request"
    assert not world[2].exists()


def test_existing_wrong_gitdir_common_and_symlink_path_refuse(world, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    for op, key in [("claim-new", "gitDir"), ("claim-install-hooks", "commonDir"),
                    ("window-name-decision", "commonDir")]:
        request = envelope(world, op)
        request["facts"][key] = str(other)
        assert outcome(ops.dispatch(request), 2)["kind"] == "invalid-request"
    alias = tmp_path / "alias"
    alias.symlink_to(world[0], target_is_directory=True)
    request = envelope(world, "claim-new")
    request["request"]["cwd"] = str(alias)
    outcome(ops.dispatch(request), 2)
    assert not world[2].exists()


@pytest.mark.parametrize("raw", [b'{"version":1,"version":1}', b'{"x":NaN}',
                                  b'{"x":1e999}', b'\xff', b'[]', b'{}',
                                  b'{"x":"\\ud800"}', b'{' * 2000,
                                  b' ' * (ops.MAX_INPUT + 1)])
def test_actual_isolated_bad_json_and_overflow_refuse_without_writes(world, raw):
    process = run_process(world, raw, raw=True)
    assert process.returncode == 2, process.stderr
    assert outcome(json.loads(process.stdout), 2)["kind"] == "invalid-request"
    assert not world[2].exists()


def test_duplicate_nested_field_cannot_be_erased_by_parser(world):
    raw = json.dumps(envelope(world, "claim-new")).replace('"ttlHours": 72', '"ttlHours": 72,"ttlHours":0')
    process = run_process(world, raw.encode(), raw=True)
    assert process.returncode == 2
    assert not world[2].exists()


def test_sdk_repository_facts_is_not_a_python_process_fallback(world):
    request = {"version": 1, "request": {"version": 1, "operation": "repository-facts",
               "cwd": str(world[0]), "selection": "head"}, "facts": {}}
    outcome(ops.dispatch(request), 2)
    process = run_process(world, envelope(world, "claim-list"), args=("--state-dir", "/tmp/no"))
    assert process.returncode == 1 and not process.stdout


def test_actual_id_domain_and_cli_ttl_defaults_preserved(world):
    for value in ["ok", "a" * 128, "a\n"]:
        assert claims.valid_id(value)
        ops.identifier(value)
    assert not claims.valid_id("a" * 129)
    assert claims.DEFAULT_TTL_H == 72
    outcome(ops.dispatch(envelope(world, "claim-new", ttlHours=0)))
    assert claims.read_claim("claim-1")["expires_at"] is None


def test_unknown_record_is_not_silently_omitted_as_complete_active_list(world):
    outcome(ops.dispatch(envelope(world, "claim-new")))
    record = claims.read_claim("claim-1")
    record["futureAuthority"] = True
    claims.write_claim(record)
    process = run_process(world, envelope(world, "claim-list"))
    assert process.returncode == 1 and not process.stdout
    assert process.stderr == b"Directory operation failed.\n"
    assert claims.claim_file("claim-1").exists()


def test_registry_output_size_and_count_refuse_instead_of_truncate(world, monkeypatch):
    outcome(ops.dispatch(envelope(world, "claim-new")))
    monkeypatch.setattr(ops, "MAX_CLAIMS", 0)
    with pytest.raises(RuntimeError, match="registry overflow"):
        ops.dispatch(envelope(world, "claim-list"))
    monkeypatch.setattr(ops, "MAX_CLAIMS", 4096)
    monkeypatch.setattr(ops, "MAX_OUTPUT", 20)
    with pytest.raises(RuntimeError, match="registry overflow"):
        ops.dispatch(envelope(world, "claim-list"))


def test_non_application_io_failure_is_not_a_successful_business_result(world, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("private state detail must not become successful output")
    monkeypatch.setattr(claims, "create_claim", fail)
    with pytest.raises(OSError):
        ops.dispatch(envelope(world, "claim-new"))


def test_isolated_process_status_matches_each_known_failure(world):
    outcome(ops.dispatch(envelope(world, "claim-new")))
    for request, code in [(envelope(world, "claim-new"), 3),
                          (envelope(world, "claim-new", claimId="foreign"), 4),
                          (envelope(world, "claim-release", claimId="missing"), 2)]:
        process = run_process(world, request)
        assert process.returncode == code
        assert json.loads(process.stdout)["status"] == code


@pytest.mark.parametrize("contents", [b"{", b"null", b"[]", b"\xff", b'{"x":NaN}',
                                       b'{"x":1e999}', b'{"v":1,"v":1}'])
def test_strict_list_actual_corrupt_record_never_becomes_empty(world, contents):
    outcome(ops.dispatch(envelope(world, "claim-new")))
    path = claims.claim_file("claim-1")
    path.write_bytes(contents)
    assert_unknown_failure(run_process(world, envelope(world, "claim-list")))
    # Preserve the deliberately tolerant ordinary CLI reader/list defaults.
    if contents in (b"{", b"null", b"[]", b"\xff"):
        assert claims.read_claim("claim-1") is None
        assert claims.list_claims("active") == []
    assert path.read_bytes() == contents


def test_strict_list_actual_unreadable_record_is_not_absence(world):
    outcome(ops.dispatch(envelope(world, "claim-new")))
    path = claims.claim_file("claim-1")
    path.chmod(0)
    try:
        assert_unknown_failure(run_process(world, envelope(world, "claim-list")))
    finally:
        path.chmod(0o600)


def test_strict_list_unreadable_directory_is_not_absent_registry(world):
    outcome(ops.dispatch(envelope(world, "claim-new")))
    directory = claims.claims_dir()
    directory.chmod(0)
    try:
        assert_unknown_failure(run_process(world, envelope(world, "claim-list")))
    finally:
        directory.chmod(0o700)


@pytest.mark.parametrize("directory_exists", [False, True])
def test_strict_list_genuine_absent_and_empty_registry_controls(world, directory_exists):
    if directory_exists:
        claims.claims_dir().mkdir(parents=True)
    process = run_process(world, envelope(world, "claim-list"))
    assert process.returncode == 0, process.stderr
    assert outcome(json.loads(process.stdout)) == []


def test_strict_list_valid_inactive_and_legacy_no_expiry_controls(world):
    outcome(ops.dispatch(envelope(world, "claim-new")))
    claims.set_state("claim-1", "released")
    record = claims.read_claim("claim-1")
    del record["expires_at"]  # Actual pre-expiry schema-v1 history.
    claims.write_claim(record)
    process = run_process(world, envelope(world, "claim-list"))
    assert process.returncode == 0, process.stderr
    assert outcome(json.loads(process.stdout)) == []
    strict = claims.read_claim_registry_strict(max_records=4096, max_bytes=ops.MAX_OUTPUT)
    assert len(strict) == 1 and strict[0]["expires_at"] is None


@pytest.mark.parametrize("field,value", [("futureAuthority", True), ("v", 2),
                                        ("owner", {"record": None}), ("expires_at", 7)])
def test_strict_list_validates_actual_inactive_records_before_filter(world, field, value):
    outcome(ops.dispatch(envelope(world, "claim-new")))
    claims.set_state("claim-1", "released")
    record = claims.read_claim("claim-1")
    record[field] = value
    claims.write_claim(record)
    assert_unknown_failure(run_process(world, envelope(world, "claim-list")))
    assert claims.list_claims("active") == []  # Ordinary behavior unchanged.


def test_strict_shared_scan_actual_consumed_bytes_not_earlier_stat_size(world):
    outcome(ops.dispatch(envelope(world, "claim-new")))
    patch = '''original = ops.claims.os.fstat
changed = False
def after_stat(fd):
    global changed
    result = original(fd)
    if not changed:
        changed = True
        ops.claims.claim_file("claim-1").write_bytes(b" " * (ops.MAX_OUTPUT + 1))
    return result
ops.claims.os.fstat = after_stat
'''
    assert_unknown_failure(run_fault_process(world, envelope(world, "claim-list"), patch))
    assert claims.claim_file("claim-1").stat().st_size == ops.MAX_OUTPUT + 1


def test_strict_shared_scan_read_failure_after_real_fstat(world):
    outcome(ops.dispatch(envelope(world, "claim-new")))
    patch = '''original_stat = ops.claims.os.fstat
original_read = ops.claims.os.read
seen = set()
def after_stat(fd):
    result = original_stat(fd)
    seen.add(fd)
    return result
def denied_read(fd, count):
    if fd in seen:
        raise PermissionError("controlled post-stat read failure")
    return original_read(fd, count)
ops.claims.os.fstat = after_stat
ops.claims.os.read = denied_read
'''
    assert_unknown_failure(run_fault_process(world, envelope(world, "claim-list"), patch))
    assert claims.read_claim("claim-1")["state"] == "active"


def test_strict_shared_scan_enumeration_failure_after_real_entry(world):
    outcome(ops.dispatch(envelope(world, "claim-new")))
    patch = '''original = ops.claims.os.scandir
class BrokenScan:
    def __init__(self, directory): self.scan = original(directory)
    def __enter__(self): return self
    def __exit__(self, *args): self.scan.close()
    def __iter__(self):
        for entry in self.scan:
            yield entry
            raise OSError("controlled enumeration failure")
ops.claims.os.scandir = BrokenScan
'''
    assert_unknown_failure(run_fault_process(world, envelope(world, "claim-list"), patch))


def test_strict_shared_scan_record_disappears_after_enumeration_is_not_empty(world):
    outcome(ops.dispatch(envelope(world, "claim-new")))
    patch = '''original = ops.claims.os.open
def disappeared(path, flags, *args, **kwargs):
    if path == "claim-1.json":
        ops.claims.claim_file("claim-1").unlink()
    return original(path, flags, *args, **kwargs)
ops.claims.os.open = disappeared
'''
    assert_unknown_failure(run_fault_process(world, envelope(world, "claim-list"), patch))


@pytest.mark.parametrize("same_owner_predecessor", [False, True])
def test_real_create_pointer_valueerror_after_publication_remains_unknown(world, same_owner_predecessor):
    if same_owner_predecessor:
        outcome(ops.dispatch(envelope(world, "claim-new", ownerRecord="same-owner")))
    request = envelope(world, "claim-new", claimId="published", ownerRecord="same-owner")
    patch = f'''original = ops.claims.write_pointer
def after_publication(workdir, claim_id):
    assert ops.claims.read_claim(claim_id)["state"] == "active"
    if {same_owner_predecessor!r}:
        assert ops.claims.read_claim("claim-1")["state"] == "released"
    Path(workdir, ".git").rename(Path(workdir, ".git.retired"))
    return original(workdir, claim_id)
ops.claims.write_pointer = after_publication
'''
    assert_unknown_failure(run_fault_process(world, request, patch))
    assert claims.read_claim("published")["state"] == "active"
    assert not (world[0] / ".git").exists()
    if same_owner_predecessor:
        assert claims.read_claim("claim-1")["state"] == "released"
        assert (world[0] / ".git.retired/ade-claim").read_text() == "claim-1\n"
    else:
        assert not (world[0] / ".git.retired/ade-claim").exists()


def test_only_shared_explicit_pre_mutation_refusal_is_a_business_outcome(world, monkeypatch):
    assert issubclass(claims.ClaimRefused, ValueError)
    for exception in [ValueError("post-publication"), OSError("write failure")]:
        def fail(*args, **kwargs):
            raise exception
        monkeypatch.setattr(claims, "create_claim", fail)
        with pytest.raises(type(exception)):
            ops.dispatch(envelope(world, "claim-new"))
