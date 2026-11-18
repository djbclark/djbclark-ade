"""Authenticated evaluator provenance, archive integrity and retention boundaries."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
from ade_fork_ci import ContractError, Evaluation, GitHubEvaluation, VerifiedArtifact, validate_metadata
from ade_fork_release import Receipt

ZIP = b"opaque qualified archive bytes; never executed or extracted"
RECEIPT = Receipt(b"{}")  # authentication identity only, NOT qualified evidence


def fixture():
    expected = Evaluation(
        repository="djbclark/evaluator", repository_id=1, workflow_id=2,
        workflow_path=".github/workflows/qualify.yml", evaluator_commit="a" * 40,
        run_id=3, run_attempt=1, actor_id=4, event="workflow_dispatch",
        jobs=("qualified-features",), artifact_id=5, artifact_name="qualified-pilot-3-1",
        archive_sha256=hashlib.sha256(ZIP).hexdigest(), receipt_sha256=RECEIPT.sha256,
    )
    run = {
        "id": 3, "run_attempt": 1, "workflow_id": 2,
        "path": expected.workflow_path, "head_sha": expected.evaluator_commit,
        "event": expected.event, "status": "completed", "conclusion": "success",
        "repository": {"id": 1, "full_name": expected.repository},
        "head_repository": {"id": 1, "full_name": expected.repository},
        "triggering_actor": {"id": 4},
    }
    jobs = [{"name": "qualified-features", "run_id": 3, "run_attempt": 1,
             "head_sha": expected.evaluator_commit, "status": "completed", "conclusion": "success"}]
    artifact = {"id": 5, "name": expected.artifact_name, "expired": False,
                "digest": "sha256:" + expected.archive_sha256, "size_in_bytes": len(ZIP),
                "workflow_run": {"id": 3, "head_sha": expected.evaluator_commit}}
    return expected, run, jobs, artifact


@pytest.mark.parametrize("field,value", [
    ("repository", "../upstream"), ("repository_id", True), ("run_id", -1),
    ("workflow_path", ".github/workflows/../../other.yml"),
    ("evaluator_commit", "short"), ("receipt_sha256", "invalid"),
    ("event", "pull_request_target"), ("jobs", ()), ("jobs", ("x", "x")),
    ("artifact_name", "qualified-pilot-3-2"),
])
def test_invalid_protected_expectations(field, value):
    with pytest.raises(ContractError):
        replace(fixture()[0], **{field: value})


@pytest.mark.parametrize("key,value", [
    ("id", 99), ("id", True), ("run_attempt", 2), ("workflow_id", 88),
    ("path", ".github/workflows/untrusted.yml"), ("head_sha", "b" * 40),
    ("event", "push"), ("status", "in_progress"), ("conclusion", "failure"),
    ("repository", {"id": 1, "full_name": "other/evaluator"}),
    ("head_repository", {"id": 999, "full_name": "outside/fork"}),
    ("triggering_actor", {"id": 99}),
])
def test_wrong_or_pending_run_never_authenticates(key, value):
    expected, run, jobs, artifact = fixture()
    run[key] = value
    with pytest.raises(ContractError):
        validate_metadata(expected, run, jobs, artifact)


@pytest.mark.parametrize("key,value", [("run_attempt", 2), ("head_sha", "b" * 40), ("status", "queued"), ("conclusion", "skipped"), ("conclusion", None)])
def test_skipped_pending_or_stale_jobs_fail(key, value):
    expected, run, jobs, artifact = fixture()
    jobs[0][key] = value
    with pytest.raises(ContractError):
        validate_metadata(expected, run, jobs, artifact)


def test_missing_and_duplicate_jobs_fail():
    expected, run, jobs, artifact = fixture()
    for values in ([], jobs + jobs):
        with pytest.raises(ContractError):
            validate_metadata(expected, run, values, artifact)


@pytest.mark.parametrize("key,value", [
    ("id", 6), ("name", "qualified-pilot-3-0"), ("expired", True),
    ("digest", "sha256:" + "0" * 64), ("size_in_bytes", 0),
    ("workflow_run", {"id": 33, "head_sha": "a" * 40}),
])
def test_wrong_expired_or_mismatched_archive_fails(key, value):
    expected, run, jobs, artifact = fixture()
    artifact[key] = value
    with pytest.raises(ContractError):
        validate_metadata(expected, run, jobs, artifact)


class FakeGitHub:
    def __init__(self, *, body=ZIP, revoked=False, fail=False):
        self.expected, self.run, self.jobs, self.artifact = fixture()
        self.body, self.revoked, self.fail = body, revoked, fail
        self.calls = []
        self.reads = 0

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        assert argv[:6] == ["gh", "api", "--hostname", "github.com", "--method", "GET"]
        if "stdout" in kwargs:
            kwargs["stdout"].write(self.body)
            return subprocess.CompletedProcess(argv, 1 if self.fail else 0)
        path = argv[6]
        if "/jobs?" in path:
            value = [{"jobs": self.jobs[:0]}, {"jobs": self.jobs}]
        elif "/artifacts/" in path:
            value = self.artifact
        else:
            self.reads += 1
            value = copy.deepcopy(self.run)
            if self.revoked and self.reads > 1:
                value["run_attempt"] += 1
        return subprocess.CompletedProcess(argv, 0, json.dumps(value))


def test_authenticated_download_retains_content_and_exact_receipt(tmp_path):
    github = FakeGitHub()
    verified = GitHubEvaluation(github).verify(github.expected, tmp_path)
    assert verified.archive.read_bytes() == ZIP
    assert verified.authenticates(RECEIPT) is True
    assert verified.authenticates(Receipt(b'{"other":true}')) is False
    assert VerifiedArtifact(github.expected, verified.archive, object()).authenticates(RECEIPT) is False
    assert any("--paginate" in call and "--slurp" in call for call in github.calls)
    again = GitHubEvaluation(github).verify(github.expected, tmp_path)
    assert again.archive == verified.archive
    assert [p.name for p in tmp_path.iterdir()] == [github.expected.archive_sha256 + ".zip"]


@pytest.mark.parametrize("kwargs,reason", [
    ({"body": b"different"}, "digest_mismatch"),
    ({"revoked": True}, "run identity"),
    ({"fail": True}, "download_failed"),
])
def test_failed_or_changed_download_never_publishes(tmp_path, kwargs, reason):
    github = FakeGitHub(**kwargs)
    with pytest.raises(ContractError, match=reason):
        GitHubEvaluation(github).verify(github.expected, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_retained_corruption_is_not_overwritten(tmp_path):
    github = FakeGitHub()
    destination = tmp_path / (github.expected.archive_sha256 + ".zip")
    destination.write_bytes(b"unexpected existing contents")
    with pytest.raises(ContractError, match="retained_artifact_corrupt"):
        GitHubEvaluation(github).verify(github.expected, tmp_path)
    assert destination.read_bytes() == b"unexpected existing contents"


@pytest.mark.parametrize("output", ["not json", "null"])
def test_bad_api_response_cannot_authenticate(output, tmp_path):
    def runner(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, output)
    with pytest.raises(ContractError):
        GitHubEvaluation(runner).verify(fixture()[0], tmp_path)


def test_cli_failure_does_not_echo_raw_output():
    def runner(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, "private error", "private error")
    with pytest.raises(ContractError, match="^github_read_failed$"):
        GitHubEvaluation(runner).api("repos/djbclark/evaluator")
