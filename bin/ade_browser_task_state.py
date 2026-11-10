"""Opt-in S7 pr-access records; only authoritative GET readback proves completion."""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

import ade_browser_task as tasks

NAME = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
NOTIFY_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
DEADLINE = Path(__file__).resolve().parent / "deadline"
API_VERSION = "2026-03-10"  # Match S6's shipped repository-policy readback.
Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def validate_name(name: str) -> str:
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise tasks.BrowserTaskError("name must match [a-z][a-z0-9-]{0,47}")
    return name


def state_directory() -> Path:
    return Path.home() / ".local/state/ade/browser-tasks"


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False,
                          stdin=subprocess.DEVNULL, timeout=30)


def _write(path: Path, record: dict[str, Any]) -> None:
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(record, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def _locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _render(root: Path, owner: str, repo: str) -> tasks.Rendered:
    tasks.validate_owner_repo(owner, kind="owner")
    tasks.validate_owner_repo(repo, kind="repo")
    if owner in (".", "..") or repo in (".", ".."):
        raise tasks.BrowserTaskError("invalid repository target")
    return tasks.render_task(root.expanduser().resolve(), "pr-access", owner=owner, repo=repo)


def _digest(rendered: tasks.Rendered) -> str:
    # Bind URL as well as the actual prompt; never persist either prompt or reply.
    return hashlib.sha256(((rendered.url or "") + "\n" + rendered.text).encode()).hexdigest()


def _read(path: Path, name: str) -> dict[str, Any]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise tasks.BrowserTaskError("task record missing or unreadable") from error
    if not isinstance(record, dict) or record.get("schema_version") != 1 or record.get("name") != name:
        raise tasks.BrowserTaskError("invalid task record identity/schema")
    if record.get("task_id") != "pr-access" or record.get("state") not in ("pending", "completed", "expired"):
        raise tasks.BrowserTaskError("unsupported task/state in record")
    for key in ("owner", "repo"):
        value = record.get(key)
        if not isinstance(value, str):
            raise tasks.BrowserTaskError("invalid task target")
        tasks.validate_owner_repo(value, kind=key)
    for key in ("created_at", "deadline_at"):
        value = record.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise tasks.BrowserTaskError("invalid task timestamps")
    if record["deadline_at"] <= record["created_at"]:
        raise tasks.BrowserTaskError("invalid task deadline")
    if not isinstance(record.get("root"), str) or not Path(record["root"]).is_absolute():
        raise tasks.BrowserTaskError("invalid task root")
    if not isinstance(record.get("template_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", record["template_sha256"]):
        raise tasks.BrowserTaskError("invalid template binding")
    if not isinstance(record.get("deadline_name"), str) or not re.fullmatch(r"browser-task-" + re.escape(name) + r"-[0-9a-f]{16}", record["deadline_name"]):
        raise tasks.BrowserTaskError("invalid deadline binding")
    if record.get("state") == "completed":
        completed = record.get("completed_at")
        observation = record.get("observation")
        if (isinstance(completed, bool) or not isinstance(completed, (int, float))
                or not math.isfinite(completed)
                or not record["created_at"] <= completed < record["deadline_at"]
                or not isinstance(observation, dict)
                or isinstance(observation.get("observed_at"), bool)
                or not isinstance(observation.get("observed_at"), (int, float))
                or observation.get("observed_at") != completed
                or observation.get("status") != "matched"
                or observation.get("source") != "github-rest-repository"
                or observation.get("target") != (record["owner"] + "/" + record["repo"]).casefold()
                or observation.get("template_sha256") != record["template_sha256"]
                or observation.get("policy") != "collaborators_only"
                or observation.get("pull_requests_enabled") is not True):
            raise tasks.BrowserTaskError("completed task lacks valid bound API observation proof")
    return record


def track(
    *, root: Path, task_id: str, name: str, seconds: int, notify_owner: str,
    owner: str, repo: str, directory: Path | None = None, yes: bool = False,
    runner: Runner = _run, clock: Callable[[], float] = time.time,
) -> tuple[dict[str, Any], int]:
    validate_name(name)
    if task_id != "pr-access":
        raise tasks.BrowserTaskError("only pr-access has a supported completion readback; other templates remain unverified")
    if isinstance(seconds, bool) or not isinstance(seconds, int) or not 1 <= seconds <= 86400:
        raise tasks.BrowserTaskError("deadline-seconds must be between 1 and 86400")
    if not isinstance(notify_owner, str) or not NOTIFY_OWNER.fullmatch(notify_owner):
        raise tasks.BrowserTaskError("invalid notify-owner ID")
    rendered = _render(root, owner, repo)
    root = root.expanduser().resolve()
    path = (directory or state_directory()).expanduser().resolve() / (name + ".json")
    deadline_name = "browser-task-" + name + "-" + uuid.uuid4().hex[:16]
    argv = [sys.executable, "-I", str(DEADLINE), "start", deadline_name,
            "--budget", str(seconds), "--owner", notify_owner, "--on-expire", "notify",
            "--checkpoint", str(path), "--json"]
    if not yes:
        return {"status": "dry-run", "completed": False, "task_id": task_id,
                "name": name, "target": owner + "/" + repo, "record": str(path),
                "deadline_argv": argv, "send": False}, 0
    with _locked(path):
        if path.exists():
            raise tasks.BrowserTaskError("task name already exists; choose a new name (records are never retargeted)")
        now = clock()
        record = {"schema_version": 1, "name": name, "task_id": task_id,
                  "owner": owner, "repo": repo, "root": str(root),
                  "template_sha256": _digest(rendered), "created_at": now,
                  "deadline_at": now + seconds, "notify_owner": notify_owner,
                  "state": "pending", "monitoring": "registration-unknown",
                  "deadline_name": deadline_name}
        # Persist intent first: timeout/crash can leave an actual deadline registered.
        # Never automatically retry registration or erase the uncertain record.
        _write(path, record)
        try:
            proc = runner(argv)
            try:
                reply = json.loads(proc.stdout) if proc.returncode == 0 else None
            except (ValueError, TypeError):
                reply = None
            expected = {"name": deadline_name, "owner": notify_owner,
                        "state": "running", "on_expire": "notify", "checkpoint": str(path),
                        "budget_s": seconds}
            if isinstance(reply, dict) and all(reply.get(k) == v for k, v in expected.items()) and isinstance(reply.get("reg_id"), str) and re.fullmatch(r"[0-9a-f]{32}", reply["reg_id"]):
                record["monitoring"] = "registered"
                record["deadline_registration_id"] = reply["reg_id"]
            elif proc.returncode != 0:
                record["monitoring"] = "registration-failed"
        except (OSError, subprocess.TimeoutExpired):
            pass
        _write(path, record)
        return {"status": record["state"], "completed": False, **record}, (0 if record["monitoring"] == "registered" else 1)


def status(name: str, *, directory: Path | None = None, clock: Callable[[], float] = time.time) -> dict[str, Any]:
    validate_name(name)
    record = _read((directory or state_directory()) / (name + ".json"), name)
    state = record["state"]
    if state == "pending" and clock() >= record["deadline_at"]:
        state = "expired"
    return {**record, "status": state, "completed": state == "completed"}


def verify(
    name: str, *, directory: Path | None = None, dry_run: bool = False,
    runner: Runner = _run, clock: Callable[[], float] = time.time,
) -> tuple[dict[str, Any], int]:
    validate_name(name)
    path = (directory or state_directory()) / (name + ".json")
    # A plan does not create a lock/state directory or execute anything.
    if dry_run:
        record = _read(path, name)
        return {"status": "dry-run", "completed": False, "name": name,
                "verify_argv": _verify_argv(record), "record_state": record["state"]}, 0
    # Lock spans read, bounded API request, and write: a late failed verifier
    # cannot overwrite another verifier's completed result.
    with _locked(path):
        record = _read(path, name)
        if record["state"] == "completed":
            return {**record, "status": "completed", "completed": True}, 0
        if record["state"] == "expired" or clock() >= record["deadline_at"]:
            record["state"] = "expired"
            _write(path, record)
            return {**record, "status": "expired", "completed": False}, 1
        try:
            rendered = _render(Path(record["root"]), record["owner"], record["repo"])
        except tasks.BrowserTaskError:
            rendered = None
        observation: dict[str, Any] = {"status": "unknown", "source": "github-rest-repository"}
        matches = False
        if rendered is None or _digest(rendered) != record["template_sha256"]:
            observation["reason"] = "template-binding-changed"
        else:
            try:
                proc = runner(_verify_argv(record))
                data = json.loads(proc.stdout) if proc.returncode == 0 else None
            except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
                data = None
            if isinstance(data, dict):
                full = data.get("full_name")
                identity = isinstance(full, str) and full.casefold() == (record["owner"] + "/" + record["repo"]).casefold()
                if identity:
                    # Persist only fixed enums/bools; no API body or bot content.
                    policy = data.get("pull_request_creation_policy")
                    observation["policy"] = policy if policy in ("all", "collaborators_only") else "unknown"
                    observation["target"] = (record["owner"] + "/" + record["repo"]).casefold()
                    observation["template_sha256"] = record["template_sha256"]
                    observation["pull_requests_enabled"] = data.get("has_pull_requests") is True
                    matches = policy == "collaborators_only" and data.get("has_pull_requests") is True
                    observation["status"] = "matched" if matches else "not-matched"
                else:
                    observation["reason"] = "repository-identity-mismatch"
            else:
                observation["reason"] = "api-unreadable"
        observed_at = clock()
        observation["observed_at"] = observed_at
        record["observation"] = observation
        if observed_at >= record["deadline_at"]:
            record["state"] = "expired"
        elif matches and observed_at >= record["created_at"]:
            record["state"] = "completed"
            record["completed_at"] = observed_at
            record["deadline_cleanup"] = "not-attempted-unconfirmed-registration"
        _write(path, record)
        if record["state"] == "completed" and record.get("monitoring") == "registered":
            try:
                proc = runner([sys.executable, "-I", str(DEADLINE), "done", record["deadline_name"]])
                record["deadline_cleanup"] = "done" if proc.returncode == 0 else "failed"
            except (OSError, subprocess.TimeoutExpired):
                record["deadline_cleanup"] = "unknown"
            _write(path, record)
        return {**record, "status": record["state"], "completed": record["state"] == "completed"}, (0 if record["state"] == "completed" else 1)


def _verify_argv(record: dict[str, Any]) -> list[str]:
    return ["gh", "api", "--method", "GET", "-H", "X-GitHub-Api-Version: " + API_VERSION,
            "repos/" + record["owner"] + "/" + record["repo"]]
