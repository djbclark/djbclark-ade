"""Opt-in S7 browser-task records; only authoritative GET readbacks prove completion.

Supported completion readbacks (W22, 2026-11-12): ``pr-access`` and
``issue-access`` via ``GET repos/{owner}/{repo}``, ``github-app-create`` via
``GET apps/{app_slug}`` plus the operator-visible installation list and its
repository list. Every readback is a bounded ``gh api`` GET bound to
``github.com``; sends, receipts and deadline registrations never prove
completion. ``poll`` runs a bounded foreground verify loop; it is not a
scheduler.
"""
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

# Task templates with a supported completion readback (W22, 2026-11-12).
SUPPORTED_TASKS: tuple[str, ...] = ("pr-access", "issue-access", "github-app-create")
APP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")
# Enum values GitHub documents for *-creation policy fields; anything else is
# recorded as "unknown" and never matches.
POLICY_VALUES: tuple[str, ...] = ("all", "collaborators_only")
# Sources named in persisted observations (per task kind).
SOURCE_REPOSITORY = "github-rest-repository"
SOURCE_APP_INSTALL = "github-rest-app-and-installations"

# poll loop bounds: interval 5-3600 s, total wait 1-86400 s (as track deadlines).
POLL_INTERVAL_BOUNDS = (5, 3600)
POLL_MAX_WAIT_BOUNDS = (1, 86400)
POLL_HARD_CAP = 20000  # only reachable when the injected clock stands still


def _same_login(left: Any, right: Any) -> bool:
    """GitHub logins compare case-insensitively (API full_name already does)."""
    return isinstance(left, str) and isinstance(right, str) and left.casefold() == right.casefold()


def validate_app_name(name: Any) -> str:
    if not isinstance(name, str) or not APP_NAME.fullmatch(name):
        raise tasks.BrowserTaskError(
            "app-name must match " + APP_NAME.pattern + " (GitHub App slug)"
        )
    return name


def _api_argv(path: str, jq: str | None = None) -> list[str]:
    argv = ["gh", "api", "--hostname", "github.com", "--method", "GET",
            "-H", "X-GitHub-Api-Version: " + API_VERSION, path]
    if jq is not None:
        argv.extend(["--jq", jq])
    return argv


def _installations_argv() -> list[str]:
    # Same user-visible installation probe as S8's ade-github-setup: the
    # operator's gh credentials, never an App JWT and never the private key.
    return _api_argv(
        "user/installations?per_page=100",
        "[.installations[] | {id, app_id, app_slug, account: .account.login, "
        "repository_selection}]",
    )


def _installation_repos_argv(installation_id: int) -> list[str]:
    return _api_argv(
        "user/installations/" + str(installation_id) + "/repositories?per_page=100",
        "[.repositories[].full_name]",
    )


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


def _render(root: Path, owner: str, repo: str, *, task_id: str = "pr-access",
            app_name: str | None = None) -> tasks.Rendered:
    tasks.validate_owner_repo(owner, kind="owner")
    tasks.validate_owner_repo(repo, kind="repo")
    if owner in (".", "..") or repo in (".", ".."):
        raise tasks.BrowserTaskError("invalid repository target")
    if task_id not in SUPPORTED_TASKS:
        raise tasks.BrowserTaskError("task " + repr(task_id) + " has no completion readback")
    # Pin the App slug the template was rendered with (W22: app-setup binding).
    extra = {"app_name": app_name} if app_name is not None else None
    return tasks.render_task(root.expanduser().resolve(), task_id, owner=owner, repo=repo,
                             extra=extra)


def _digest(rendered: tasks.Rendered) -> str:
    # Bind URL as well as the actual prompt; never persist either prompt or reply.
    return hashlib.sha256(((rendered.url or "") + "\n" + rendered.text).encode()).hexdigest()


def _finite_time(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _read(path: Path, name: str) -> dict[str, Any]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise tasks.BrowserTaskError("task record missing or unreadable") from error
    if not isinstance(record, dict) or record.get("schema_version") != 1 or record.get("name") != name:
        raise tasks.BrowserTaskError("invalid task record identity/schema")
    if (not isinstance(record.get("task_id"), str) or record.get("task_id") not in SUPPORTED_TASKS
            or record.get("state") not in ("pending", "completed", "expired")):
        raise tasks.BrowserTaskError("unsupported task/state in record")
    if record["task_id"] == "github-app-create":
        validate_app_name(record.get("app_name"))
    for key in ("owner", "repo"):
        value = record.get(key)
        if not isinstance(value, str):
            raise tasks.BrowserTaskError("invalid task target")
        tasks.validate_owner_repo(value, kind=key)
    for key in ("created_at", "deadline_at"):
        value = record.get(key)
        if not _finite_time(value):
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
                or not isinstance(observation, dict)):
            raise tasks.BrowserTaskError("completed task lacks valid bound API observation proof")
        if not _completed_observation_ok(record, observation, completed):
            raise tasks.BrowserTaskError("completed task lacks valid bound API observation proof")
    return record


def _completed_observation_ok(record: dict[str, Any], observation: dict[str, Any],
                              completed: float) -> bool:
    """A completed record must carry the exact observation that proved it."""
    task = record["task_id"]
    expected_source = SOURCE_APP_INSTALL if task == "github-app-create" else SOURCE_REPOSITORY
    observed_at = observation.get("observed_at")
    if (observation.get("status") != "matched"
            or observation.get("source") != expected_source
            or observation.get("hostname") != "github.com"
            or observation.get("target") != (record["owner"] + "/" + record["repo"]).casefold()
            or observation.get("template_sha256") != record["template_sha256"]
            or isinstance(observed_at, bool) or not isinstance(observed_at, (int, float))
            or observed_at != completed):
        return False
    if task == "pr-access":
        return (observation.get("policy") == "collaborators_only"
                and observation.get("pull_requests_enabled") is True)
    if task == "issue-access":
        return (observation.get("issue_creation_policy") == "collaborators_only"
                and observation.get("issues_enabled") is True)
    if task == "github-app-create":
        app_id = observation.get("app_id")
        return (observation.get("app_slug") == record.get("app_name")
                and observation.get("app_found") is True
                and isinstance(app_id, int) and not isinstance(app_id, bool) and app_id >= 1
                and observation.get("perm_statuses") == "write"
                and observation.get("perm_checks") == "write"
                and observation.get("perm_pull_requests") == "read"
                and observation.get("installation_found") is True
                and observation.get("installation_account_match") is True
                and observation.get("install_repos_exact") is True)
    return False


def track(
    *, root: Path, task_id: str, name: str, seconds: int, notify_owner: str,
    owner: str, repo: str, directory: Path | None = None, yes: bool = False,
    app_name: str | None = None,
    runner: Runner = _run, clock: Callable[[], float] = time.time,
) -> tuple[dict[str, Any], int]:
    validate_name(name)
    if task_id not in SUPPORTED_TASKS:
        raise tasks.BrowserTaskError(
            "only " + ", ".join(SUPPORTED_TASKS)
            + " have supported completion readbacks; other templates remain unverified"
        )
    app_name_resolved: str | None = None
    if task_id == "github-app-create":
        app_name_resolved = validate_app_name(app_name or "ade-merge-gate")
    if isinstance(seconds, bool) or not isinstance(seconds, int) or not 1 <= seconds <= 86400:
        raise tasks.BrowserTaskError("deadline-seconds must be between 1 and 86400")
    if not isinstance(notify_owner, str) or not NOTIFY_OWNER.fullmatch(notify_owner):
        raise tasks.BrowserTaskError("invalid notify-owner ID")
    rendered = _render(root, owner, repo, task_id=task_id, app_name=app_name_resolved)
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
        if not _finite_time(now) or not _finite_time(now + seconds) or now + seconds <= now:
            raise tasks.BrowserTaskError("clock anomaly: creation time is not finite")
        record = {"schema_version": 1, "name": name, "task_id": task_id,
                  "owner": owner, "repo": repo, "root": str(root),
                  "template_sha256": _digest(rendered), "created_at": now,
                  "deadline_at": now + seconds, "notify_owner": notify_owner,
                  "state": "pending", "monitoring": "registration-unknown",
                  "deadline_name": deadline_name}
        if app_name_resolved is not None:
            record["app_name"] = app_name_resolved
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
        plan: dict[str, Any] = {"status": "dry-run", "completed": False, "name": name,
                                "verify_argv": _verify_argv(record),
                                "record_state": record["state"]}
        if record["task_id"] == "github-app-create":
            plan.update(_app_argv_plan(record))
        return plan, 0
    # Lock spans read, bounded API request, and write: a late failed verifier
    # cannot overwrite another verifier's completed result.
    with _locked(path):
        record = _read(path, name)
        if record["state"] == "completed":
            return {**record, "status": "completed", "completed": True}, 0
        checked_at = clock()
        if not _finite_time(checked_at) or checked_at < record["created_at"]:
            raise tasks.BrowserTaskError("clock anomaly: verification time is invalid or before creation")
        if record["state"] == "expired" or checked_at >= record["deadline_at"]:
            record["state"] = "expired"
            _write(path, record)
            return {**record, "status": "expired", "completed": False}, 1
        try:
            rendered = _render(Path(record["root"]), record["owner"], record["repo"],
                               task_id=record["task_id"], app_name=record.get("app_name"))
        except tasks.BrowserTaskError:
            rendered = None
        observation: dict[str, Any] = {"status": "unknown",
                                       "source": (SOURCE_APP_INSTALL
                                                  if record["task_id"] == "github-app-create"
                                                  else SOURCE_REPOSITORY),
                                       "hostname": "github.com"}
        matches = False
        if rendered is None or _digest(rendered) != record["template_sha256"]:
            observation["reason"] = "template-binding-changed"
        else:
            matches = _observe_task(record, observation, runner)
        observed_at = clock()
        valid_clock = _finite_time(observed_at) and observed_at >= checked_at
        if valid_clock:
            observation["observed_at"] = observed_at
        else:
            observation.update(status="unknown", reason="clock-anomaly")
        record["observation"] = observation
        if valid_clock and observed_at >= record["deadline_at"]:
            record["state"] = "expired"
        elif matches and valid_clock:
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


def poll(
    name: str, *, directory: Path | None = None,
    interval_seconds: int = 60, max_wait_seconds: int = 3600,
    dry_run: bool = False, runner: Runner = _run,
    clock: Callable[[], float] = time.time,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, Any], int]:
    """Bounded automatic polling: run ``verify`` on an interval until done.

    A foreground loop, not a scheduler: each iteration is one verify (its own
    lock, one bounded GET readback; two more for github-app-create). Stops on
    completed/expired, at ``max_wait_seconds``, at the record's own deadline,
    or at POLL_HARD_CAP. Never sends prompts, never registers or retries
    deadline waits. ``--dry-run`` is a pure plan: no lock, no writes, no
    network, no sleeps. Exit 0 only when the record is completed at return.
    """
    validate_name(name)
    if (isinstance(interval_seconds, bool) or not isinstance(interval_seconds, int)
            or not POLL_INTERVAL_BOUNDS[0] <= interval_seconds <= POLL_INTERVAL_BOUNDS[1]):
        raise tasks.BrowserTaskError(
            "interval-seconds must be between "
            + str(POLL_INTERVAL_BOUNDS[0]) + " and " + str(POLL_INTERVAL_BOUNDS[1])
        )
    if (isinstance(max_wait_seconds, bool) or not isinstance(max_wait_seconds, int)
            or not POLL_MAX_WAIT_BOUNDS[0] <= max_wait_seconds <= POLL_MAX_WAIT_BOUNDS[1]):
        raise tasks.BrowserTaskError(
            "max-wait-seconds must be between "
            + str(POLL_MAX_WAIT_BOUNDS[0]) + " and " + str(POLL_MAX_WAIT_BOUNDS[1])
        )
    path = (directory or state_directory()) / (name + ".json")
    record = _read(path, name)
    if dry_run:
        now = clock()
        horizon = min(float(max_wait_seconds), max(0.0, record["deadline_at"] - now))
        planned = min(POLL_HARD_CAP, int(math.ceil(horizon / interval_seconds)) + 2)
        plan: dict[str, Any] = {
            "status": "dry-run", "completed": False, "name": name,
            "record_state": record["state"],
            "interval_seconds": interval_seconds,
            "max_wait_seconds": max_wait_seconds,
            "deadline_in_seconds": max(0.0, record["deadline_at"] - now),
            "planned_polls_upper_bound": planned,
            "verify_argv": _verify_argv(record),
        }
        if record["task_id"] == "github-app-create":
            plan.update(_app_argv_plan(record))
        return plan, 0
    start = clock()
    if not _finite_time(start):
        raise tasks.BrowserTaskError("clock anomaly: poll start time is not finite")
    deadline_at = record["deadline_at"]
    payload: dict[str, Any] = {}
    rc = 1
    polls = 0
    stopped = "poll-limit"
    while polls < POLL_HARD_CAP:
        payload, rc = verify(name, directory=directory, runner=runner, clock=clock)
        polls += 1
        state_now = payload.get("status")
        if state_now in ("completed", "expired"):
            stopped = str(state_now)
            break
        now = clock()
        if not _finite_time(now):
            stopped = "clock-anomaly"
            break
        remaining = min(max_wait_seconds - (now - start), deadline_at - now)
        if remaining <= 0:
            # The verify at the start of this iteration already ran. A wait-cap
            # expiry is not a second readback. Only a clock that crossed the
            # record deadline after that verify gets one settling pass, so the
            # persisted state is expired rather than a stale pending view.
            if state_now == "pending" and deadline_at - now <= 0:
                payload, rc = verify(name, directory=directory, runner=runner, clock=clock)
                polls += 1
                stopped = str(payload.get("status"))
            else:
                stopped = "max-wait-reached"
            break
        sleeper(min(interval_seconds, remaining))
    if payload.get("status") not in ("completed", "expired") and polls >= POLL_HARD_CAP:
        stopped = "poll-limit"
    payload = {**payload, "polls": polls, "interval_seconds": interval_seconds,
               "max_wait_seconds": max_wait_seconds, "poll_stopped": stopped}
    return payload, rc


def _app_argv_plan(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "verify_argv_all": [_verify_argv(record), _installations_argv()],
        "verify_argv_note": (
            "the installation-repositories GET is computed at runtime from "
            "the observed installation id"
        ),
    }


def _verify_argv(record: dict[str, Any]) -> list[str]:
    # The checked-in template is bound to github.com, regardless of GH_HOST.
    if record["task_id"] == "github-app-create":
        return _api_argv("apps/" + record["app_name"])
    return _api_argv("repos/" + record["owner"] + "/" + record["repo"])


def _observe_task(record: dict[str, Any], observation: dict[str, Any],
                  runner: Runner) -> bool:
    """Run the task's bounded GET readback(s); persist enums/bools only.

    Never stores an API body, bot reply or subprocess output. Returns True
    only when the exact requested end state is observed.
    """
    task = record["task_id"]
    if task == "github-app-create":
        return _observe_app(record, observation, runner)
    try:
        proc = runner(_verify_argv(record))
        data = json.loads(proc.stdout) if proc.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        data = None
    if not isinstance(data, dict):
        observation["reason"] = "api-unreadable"
        return False  # status stays unknown: nothing authoritative observed
    full = data.get("full_name")
    if not (isinstance(full, str) and full.casefold() == (record["owner"] + "/" + record["repo"]).casefold()):
        observation["reason"] = "repository-identity-mismatch"
        return False  # status stays unknown: wrong repository is not our setting
    # Persist only fixed enums/bools; no API body or bot content.
    observation["target"] = (record["owner"] + "/" + record["repo"]).casefold()
    observation["template_sha256"] = record["template_sha256"]
    matches = False
    if task == "pr-access":
        policy = data.get("pull_request_creation_policy")
        observation["policy"] = policy if policy in POLICY_VALUES else "unknown"
        enabled = data.get("has_pull_requests") is True
        observation["pull_requests_enabled"] = enabled
        matches = policy == "collaborators_only" and enabled
    elif task == "issue-access":
        # The template documents no REST field for issue_creation_policy
        # (browser-only until GitHub exposes one). A missing field is recorded
        # explicitly and can never complete; a present field must carry the
        # exact collaborator-only value with issues still enabled.
        if "issue_creation_policy" not in data:
            observation["reason"] = "field-missing"
        ipolicy = data.get("issue_creation_policy")
        observation["issue_creation_policy"] = ipolicy if ipolicy in POLICY_VALUES else "unknown"
        issues_on = data.get("has_issues") is True
        observation["issues_enabled"] = issues_on
        matches = ipolicy == "collaborators_only" and issues_on
    else:
        observation["reason"] = "unsupported-task"
        return False
    observation["status"] = "matched" if matches else "not-matched"
    return matches


def _observe_app(record: dict[str, Any], observation: dict[str, Any],
                 runner: Runner) -> bool:
    """App identity/permissions plus the user-visible installation set.

    ``GET /apps/{slug}`` (public) fixes the App identity and requested
    permissions; ``GET /user/installations`` plus that installation's
    repository list (operator gh credentials, never an App JWT) fix where it
    is installed. Completion requires the repository list to be exactly the
    configured repository — nothing wider. Aspects the public readback cannot
    see (public/private flag, webhook active, repository list past page 1)
    stay outside the proof and are never assumed.
    """
    name = record["app_name"]
    target = (record["owner"] + "/" + record["repo"]).casefold()
    observation.update(
        target=target,
        template_sha256=record["template_sha256"],
        app_slug=name,
        app_found=False,
        app_id=None,
        perm_statuses="unknown",
        perm_checks="unknown",
        perm_pull_requests="unknown",
        installation_found=False,
        installation_id=None,
        installation_account_match=False,
        repository_selection="unknown",
        install_repos_exact=False,
        install_repos_count=0,
    )
    try:
        proc = runner(_verify_argv(record))
        app = json.loads(proc.stdout) if proc.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        app = None
    if not isinstance(app, dict) or app.get("slug") != name:
        observation["reason"] = "app-unreadable"
        return False  # status stays unknown
    app_id = app.get("id")
    found = isinstance(app_id, int) and not isinstance(app_id, bool) and app_id >= 1
    observation["app_found"] = found
    observation["app_id"] = app_id if found else None
    perms = app.get("permissions")
    perms = perms if isinstance(perms, dict) else {}
    observation["perm_statuses"] = perms.get("statuses") if perms.get("statuses") == "write" else "unknown"
    observation["perm_checks"] = perms.get("checks") if perms.get("checks") == "write" else "unknown"
    observation["perm_pull_requests"] = perms.get("pull_requests") if perms.get("pull_requests") == "read" else "unknown"
    perms_ok = (found
                and observation["perm_statuses"] == "write"
                and observation["perm_checks"] == "write"
                and observation["perm_pull_requests"] == "read")
    try:
        proc = runner(_installations_argv())
        rows = json.loads(proc.stdout) if proc.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        rows = None
    if not isinstance(rows, list):
        observation["reason"] = "installations-unreadable"
        return False  # status stays unknown
    candidates = [row for row in rows
                  if isinstance(row, dict) and row.get("app_slug") == name]
    if not candidates:
        observation["reason"] = "installation-missing"
        observation["status"] = "not-matched"
        return False
    observation["installation_found"] = True
    # Prefer the configured owner's installation; bounded page-1 candidates.
    candidates.sort(key=lambda row: 0 if _same_login(row.get("account"), record["owner"]) else 1)
    readable: dict[str, Any] | None = None
    for row in candidates[:5]:
        iid = row.get("id")
        if not (isinstance(iid, int) and not isinstance(iid, bool) and iid >= 1):
            continue
        try:
            proc = runner(_installation_repos_argv(iid))
            repos = json.loads(proc.stdout) if proc.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
            repos = None
        if not isinstance(repos, list):
            continue
        names = [r for r in repos if isinstance(r, str)]
        exact = len(names) == 1 and names[0].casefold() == target
        if readable is None or (exact and not readable["exact"]):
            readable = {"id": iid, "account_match": _same_login(row.get("account"), record["owner"]),
                        "selection": row.get("repository_selection"),
                        "count": len(names), "exact": exact}
        if exact:
            break
    if readable is None:
        observation["reason"] = "installation-repos-unreadable"
        return False  # status stays unknown
    observation["installation_id"] = readable["id"]
    observation["installation_account_match"] = readable["account_match"]
    selection = readable["selection"]
    observation["repository_selection"] = selection if selection in ("selected", "all") else "unknown"
    observation["install_repos_count"] = readable["count"]
    observation["install_repos_exact"] = readable["exact"]
    observation["status"] = "not-matched"
    if not readable["exact"]:
        observation["reason"] = ("installation-repos-missing" if readable["count"] == 0
                                 else "installation-repos-extra")
        return False
    if not readable["account_match"]:
        observation["reason"] = "installation-account-mismatch"
        return False
    if not perms_ok:
        observation["reason"] = "permissions-mismatch"
        return False
    observation["status"] = "matched"
    return True
