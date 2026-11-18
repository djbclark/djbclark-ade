"""Authenticate exact GitHub evaluation artifacts and retain immutable recovery ZIPs.

This read-only GitHub adapter does not grant deployment authority or execute
artifact contents. A protected caller supplies the expected evaluator, run,
attempt, jobs and ZIP digest; metadata claimed inside a receipt is not trusted.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ade_fork_release import ContractError, Receipt

REPOSITORY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
_VERIFIED = object()


@dataclass(frozen=True)
class Evaluation:
    """Expectations from protected enrollment, NEVER a candidate's own metadata."""

    repository: str
    repository_id: int
    workflow_id: int
    workflow_path: str
    evaluator_commit: str
    run_id: int
    run_attempt: int
    actor_id: int
    event: str
    jobs: tuple[str, ...]
    artifact_id: int
    artifact_name: str
    archive_sha256: str
    receipt_sha256: str

    def __post_init__(self):
        if not isinstance(self.repository, str) or not REPOSITORY.fullmatch(self.repository) or self.repository.split("/")[-1] in (".", ".."):
            raise ContractError("invalid evaluator repository")
        for name in ("repository_id", "workflow_id", "run_id", "run_attempt", "actor_id", "artifact_id"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ContractError(f"invalid {name}")
        if not isinstance(self.workflow_path, str) or not re.fullmatch(r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml", self.workflow_path):
            raise ContractError("invalid trusted workflow path")
        if not isinstance(self.evaluator_commit, str) or not COMMIT.fullmatch(self.evaluator_commit):
            raise ContractError("invalid evaluator commit")
        for name in ("archive_sha256", "receipt_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or not SHA256.fullmatch(value):
                raise ContractError(f"invalid {name}")
        if self.event not in ("workflow_dispatch", "push", "pull_request"):
            raise ContractError("unsupported evaluation event")
        if not isinstance(self.jobs, tuple) or not self.jobs or any(not isinstance(v, str) or not v.strip() for v in self.jobs) or len(set(self.jobs)) != len(self.jobs):
            raise ContractError("expected jobs must be unique nonempty names")
        if not isinstance(self.artifact_name, str) or not self.artifact_name.endswith(f"-{self.run_id}-{self.run_attempt}"):
            raise ContractError("artifact name must bind evaluation run and attempt")


def validate_metadata(expected: Evaluation, run: Any, jobs: Any, artifact: Any) -> None:
    """Consistency checks only; authentication also requires GitHub API reads."""
    if not isinstance(run, dict) or not isinstance(artifact, dict) or not isinstance(jobs, list):
        raise ContractError("malformed GitHub evidence")
    wanted = {
        "id": expected.run_id, "run_attempt": expected.run_attempt,
        "workflow_id": expected.workflow_id, "path": expected.workflow_path,
        "head_sha": expected.evaluator_commit, "event": expected.event,
        "status": "completed", "conclusion": "success",
    }
    if any(type(run.get(k)) is not type(v) or run[k] != v for k, v in wanted.items()):
        raise ContractError("evaluation run identity or outcome mismatch")
    for name in ("repository", "head_repository"):
        repo = run.get(name)
        if not isinstance(repo, dict) or type(repo.get("id")) is not int or repo["id"] != expected.repository_id or repo.get("full_name") != expected.repository:
            raise ContractError("evaluation repository mismatch")
    actor = run.get("triggering_actor")
    if not isinstance(actor, dict) or type(actor.get("id")) is not int or actor["id"] != expected.actor_id:
        raise ContractError("evaluation actor mismatch")
    selected: dict[str, dict] = {}
    for job in jobs:
        if not isinstance(job, dict) or not isinstance(job.get("name"), str):
            raise ContractError("malformed job evidence")
        if job["name"] not in expected.jobs:
            continue
        if job["name"] in selected:
            raise ContractError("ambiguous required job")
        if type(job.get("run_id")) is not int or job["run_id"] != expected.run_id or type(job.get("run_attempt")) is not int or job["run_attempt"] != expected.run_attempt or job.get("head_sha") != expected.evaluator_commit or job.get("status") != "completed" or job.get("conclusion") != "success":
            raise ContractError("required job not successful at exact evaluation attempt")
        selected[job["name"]] = job
    if set(selected) != set(expected.jobs):
        raise ContractError("required job missing")
    if type(artifact.get("id")) is not int or artifact["id"] != expected.artifact_id or artifact.get("name") != expected.artifact_name or artifact.get("expired") is not False or artifact.get("digest") != "sha256:" + expected.archive_sha256:
        raise ContractError("artifact identity, retention or digest mismatch")
    origin = artifact.get("workflow_run")
    if not isinstance(origin, dict) or type(origin.get("id")) is not int or origin["id"] != expected.run_id or origin.get("head_sha") != expected.evaluator_commit:
        raise ContractError("artifact does not belong to evaluation run")
    size = artifact.get("size_in_bytes")
    if type(size) is not int or not 0 < size <= MAX_ARCHIVE_BYTES:
        raise ContractError("artifact size outside bound")


@dataclass(frozen=True)
class VerifiedArtifact:
    """Produced only after authenticated API reads and download verification."""

    evaluation: Evaluation
    archive: Path
    _seal: object

    def authenticates(self, receipt: Receipt) -> bool:
        # Exact receipt identity is supplied by protected enrollment. This is
        # NOT a receipt-supplied claim of its own evaluator or workflow.
        return self._seal is _VERIFIED and receipt.sha256 == self.evaluation.receipt_sha256


class GitHubEvaluation:
    """Use installed gh authentication without reading or printing credentials.

    Ordinary CLI failures expose only stable errors here, not untrusted raw logs.
    Callers may inject a trusted runner in tests; never accept one from receipts.
    """

    def __init__(self, runner=subprocess.run):
        self.run = runner

    def api(self, endpoint: str, *, paginate=False):
        argv = ["gh", "api", "--hostname", "github.com", "--method", "GET", endpoint]
        if paginate:
            argv.extend(["--paginate", "--slurp"])
        try:
            result = self.run(argv, capture_output=True, text=True, check=False, timeout=90)
            if result.returncode != 0:
                raise ContractError("github_read_failed")
            if len(result.stdout) > 4 * 1024 * 1024:
                raise ContractError("github_metadata_too_large")
            return json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            if isinstance(error, ContractError):
                raise
            raise ContractError("github_evidence_unavailable") from error

    def verify(self, expected: Evaluation, archive_dir: Path) -> VerifiedArtifact:
        """Authenticate, download and retain an exact archive; installs nothing.

        Re-read the run/artifact after download to reject attempt changes or
        expiry/deletion. Deployment authority and current policy revocation must
        additionally be checked by the executor immediately before activation.
        """
        base = "repos/" + expected.repository
        run_path = f"{base}/actions/runs/{expected.run_id}"
        artifact_path = f"{base}/actions/artifacts/{expected.artifact_id}"
        run = self.api(run_path)
        pages = self.api(f"{run_path}/attempts/{expected.run_attempt}/jobs?per_page=100", paginate=True)
        if not isinstance(pages, list) or any(not isinstance(page, dict) or not isinstance(page.get("jobs"), list) for page in pages):
            raise ContractError("malformed paginated job evidence")
        jobs = [job for page in pages for job in page["jobs"]]
        artifact = self.api(artifact_path)
        validate_metadata(expected, run, jobs, artifact)
        archive_dir.mkdir(parents=True, exist_ok=True)
        destination = archive_dir / (expected.archive_sha256 + ".zip")
        fd, name = tempfile.mkstemp(prefix=".download-", dir=archive_dir)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as out:
                argv = ["gh", "api", "--hostname", "github.com", "--method", "GET", artifact_path + "/zip"]
                try:
                    result = self.run(argv, stdout=out, stderr=subprocess.PIPE, check=False, timeout=90)
                except (OSError, subprocess.TimeoutExpired) as error:
                    raise ContractError("artifact_download_failed") from error
                if result.returncode != 0:
                    raise ContractError("artifact_download_failed")
                out.flush()
                os.fsync(out.fileno())
            if temporary.stat().st_size > MAX_ARCHIVE_BYTES:
                raise ContractError("artifact_download_too_large")
            if _file_digest(temporary) != expected.archive_sha256:
                raise ContractError("artifact_download_digest_mismatch")
            validate_metadata(expected, self.api(run_path), jobs, self.api(artifact_path))
            # Publish without overwriting any retained artifact. Existing files
            # must already match the digest, including on a retry after a crash.
            temporary.chmod(0o444)
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if destination.is_symlink() or not destination.is_file() or _file_digest(destination) != expected.archive_sha256:
                    raise ContractError("retained_artifact_corrupt")
            directory_fd = os.open(archive_dir, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return VerifiedArtifact(expected, destination, _VERIFIED)
        finally:
            temporary.unlink(missing_ok=True)


def _file_digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            sha.update(chunk)
    return sha.hexdigest()
