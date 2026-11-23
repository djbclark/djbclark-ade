"""Request or sweep clean non-forced Paseo agent archives for finishing sessions (2026-11-23).

A running Paseo agent cannot archive itself and `/quit` in a Paseo composer is plain text.
A finishing session runs `bin/ade-request-archive` right before ending its turn: it validates
its own Paseo UUID, refuses if it holds the standing load-watcher role, resolves a live archiver
target (explicit `--to`, owning lead via `--lead` / `ade.lead` / `ParentAgentId` followed through
`ade_lead_succession.effective_lead`, standing watcher from `load-watch watcher show --json`, or
`supervisor/lead`), checks `Archived: false` on the target (fail closed), atomically records the
request (`0o600`, `schema_version: 1`), and sends an archive request via `paseo send --json --no-wait`.

The target lead or standing watcher fulfills pending requests with `bin/ade-request-archive sweep`
(observe-only unless `--apply`), guarding against `getpaseo/paseo#9668` (`paseo ls -g --json` exact
ID presence), checking `Status` in (`idle`, `closed`), `Archived: false`, and `PendingPermissions == []`,
running `paseo agent archive <id> --json` without `--force`, verifying `Archived: true` readback, and
atomically updating the request record to `status: "archived"`.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any, Callable
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ade_lead_succession as succ  # noqa: E402

SCHEMA_VERSION = 1
UUID_RE = succ.UUID_RE
MAX_RECORD_BYTES = 262144
MAX_REASON_CHARS = 500
TAIL_LIMIT = 512

ARCHIVE_REQUEST_DIR_ENV = "ADE_ARCHIVE_REQUEST_DIR"
LW_STATE_DIR_ENV = "LW_STATE_DIR"
SUPERVISOR_STATE_ENV = "ADE_SUPERVISOR_STATE_DIR"
DEFAULT_ARCHIVE_REQUEST_REL = Path(".local/state/djbclark-ade/archive-requests")
DEFAULT_LW_STATE_REL = Path(".local/state/load-watch")
DEFAULT_SUPERVISOR_STATE_REL = Path(".local/state/djbclark-ade/supervisor")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_REFUSED = 4

SWEEP_ARCHIVEABLE_STATUSES = frozenset({"idle", "closed"})


class ArchiveRequestError(RuntimeError):
    """Operational error (Paseo failure, send failure, I/O error)."""


class ArchiveRequestUsageError(ArchiveRequestError):
    """Invalid CLI arguments or malformed caller/target UUID."""


class ArchiveRequestRefused(ArchiveRequestError):
    """Fail-closed policy refusal (standing watcher, self-target, archived target, no target)."""


class AgentNotFoundError(LookupError):
    """Paseo reported the requested agent ID does not exist."""


class PaseoUnavailableError(ArchiveRequestError):
    """Paseo CLI failed, timed out, or returned unreadable output."""


def default_request_dir(env: dict[str, str] | None = None) -> Path:
    e = os.environ if env is None else env
    raw = e.get(ARCHIVE_REQUEST_DIR_ENV)
    return Path(raw) if raw else Path.home() / DEFAULT_ARCHIVE_REQUEST_REL


def default_lw_state_dir(env: dict[str, str] | None = None) -> Path:
    e = os.environ if env is None else env
    raw = e.get(LW_STATE_DIR_ENV)
    return Path(raw) if raw else Path.home() / DEFAULT_LW_STATE_REL


def default_supervisor_state_dir(env: dict[str, str] | None = None) -> Path:
    e = os.environ if env is None else env
    raw = e.get(SUPERVISOR_STATE_ENV)
    return Path(raw) if raw else Path.home() / DEFAULT_SUPERVISOR_STATE_REL


def default_load_watch_bin() -> Path:
    return Path(__file__).resolve().with_name("load-watch")


def validate_uuid(raw: str | None, label: str = "agent id") -> str:
    """Return canonical lowercase UUID or raise ArchiveRequestUsageError."""
    if not isinstance(raw, str):
        raise ArchiveRequestUsageError(f"{label} is missing")
    val = raw.strip()
    if not val or not UUID_RE.fullmatch(val):
        raise ArchiveRequestUsageError(f"{label} must be a canonical lowercase UUID, got {val!r}")
    return val


def sanitize_reason(reason: str | None) -> str:
    """Single-line printable bounded reason string."""
    if not reason:
        return "session finished"
    cleaned = "".join(c if c.isprintable() and c not in "\r\n\t" else " " for c in str(reason))
    collapsed = " ".join(cleaned.split())
    if not collapsed:
        return "session finished"
    return collapsed[:MAX_REASON_CHARS]


def bounded_text(text: Any, limit: int = TAIL_LIMIT) -> str:
    raw = "".join(c if c.isprintable() or c in "\n\t" else "?" for c in str(text or ""))
    raw = raw.strip()
    if len(raw) <= limit:
        return raw
    return "..." + raw[-(limit - 3):]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_regular_bytes(path: Path, max_bytes: int = MAX_RECORD_BYTES) -> bytes | None:
    """Read a small regular file owned by euid and not group/world-writable without following symlinks."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or (st.st_mode & 0o022):
                return None
            raw = os.read(fd, max_bytes + 1)
        finally:
            os.close(fd)
    except OSError:
        return None
    if len(raw) > max_bytes:
        return None
    return raw


def read_regular_json(path: Path, max_bytes: int = MAX_RECORD_BYTES) -> dict[str, Any] | None:
    raw = read_regular_bytes(path, max_bytes=max_bytes)
    if raw is None:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def write_atomic_json(path: Path, payload: dict[str, Any], mode: int = 0o600) -> None:
    """Atomically write JSON to `path` with `mode` (default 0o600), refusing a symlink target."""
    if path.is_symlink():
        raise ArchiveRequestError(f"refusing to overwrite symlink: {path}")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def parse_send_status(stdout: str, rc: int) -> str:
    """Extract `.status` from `paseo send --json --no-wait` stdout."""
    try:
        parsed = json.loads(stdout or "")
    except (ValueError, TypeError):
        return "accepted" if rc == 5 else "unknown"
    if isinstance(parsed, dict) and isinstance(parsed.get("data"), dict):
        parsed = parsed["data"]
    if isinstance(parsed, dict):
        st = parsed.get("status")
        if isinstance(st, str) and st:
            return st
    return "accepted" if rc == 5 else "unknown"


def parse_error_code(*streams: str) -> str | None:
    for text in streams:
        s = (text or "").strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict):
            err = obj.get("error")
            if isinstance(err, dict) and isinstance(err.get("code"), str) and err["code"]:
                return err["code"]
            if isinstance(obj.get("code"), str) and obj["code"]:
                return obj["code"]
    return None


def build_archive_message(self_id: str, request_id: str, reason: str, record_path: Path) -> str:
    """Build the archive request prompt sent to the target archiver."""
    return (
        f"Archive request ({request_id}) from {self_id} (reason: {reason}): "
        f"this session is finishing and ending its turn to go idle. "
        f"Once `paseo agent inspect {self_id} --json` reads `Status == \"idle\"` (or `\"closed\"`) "
        f"and `PendingPermissions == []`, please archive {self_id} without `--force` "
        f"via `~/src/djbclark-ade/bin/ade-request-archive sweep --apply` "
        f"(or verify exact presence in `paseo ls -g --json`, run `paseo agent archive {self_id}`, "
        f"verify `Archived: true`, and mark `{record_path}` fulfilled).\n"
        f"Please reply: ack {self_id} {request_id}"
    )


class ArchiveRequestService:
    """Core logic for requesting and sweeping clean non-forced Paseo agent archives."""

    def __init__(
        self,
        *,
        state_dir: Path | None = None,
        paseo_home: Path | None = None,
        self_session_state: Path | None = None,
        lw_state_dir: Path | None = None,
        supervisor_state_dir: Path | None = None,
        paseo_bin: str = "paseo",
        load_watch_bin: Path | str | None = None,
        env: dict[str, str] | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        clock: Callable[[], str] | None = None,
        uuid_factory: Callable[[], str] | None = None,
    ) -> None:
        self.env = dict(os.environ if env is None else env)
        self.state_dir = (state_dir or default_request_dir(self.env)).expanduser().resolve()
        self.home = (paseo_home or succ.default_home(self.env)).expanduser().resolve()
        self.self_session_state = (
            (self_session_state or succ.default_state_dir(self.env)).expanduser().resolve()
        )
        self.lw_state_dir = (lw_state_dir or default_lw_state_dir(self.env)).expanduser().resolve()
        self.supervisor_state_dir = (
            (supervisor_state_dir or default_supervisor_state_dir(self.env)).expanduser().resolve()
        )
        self.paseo_bin = paseo_bin
        self.load_watch_bin = (
            Path(load_watch_bin) if load_watch_bin is not None else default_load_watch_bin()
        )
        self.runner = runner or subprocess.run
        self.clock = clock or utc_now
        self.uuid_factory = uuid_factory or (lambda: str(uuid.uuid4()))

    def _paseo_env(self) -> dict[str, str]:
        e = dict(self.env)
        e["PASEO_HOME"] = str(self.home)
        return e

    def _run_cmd(
        self,
        argv: list[str],
        *,
        env: dict[str, str],
        timeout: int = 30,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return self.runner(
                argv,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise PaseoUnavailableError(f"command timed out: {argv[0]}") from exc
        except OSError as exc:
            raise PaseoUnavailableError(f"command failed to execute ({argv[0]}): {exc}") from exc

    def inspect_agent(self, agent_id: str) -> dict[str, Any]:
        """Run `paseo agent inspect <id> --json`; raise AgentNotFoundError or PaseoUnavailableError."""
        aid = validate_uuid(agent_id, "agent id")
        proc = self._run_cmd(
            [self.paseo_bin, "agent", "inspect", aid, "--json"],
            env=self._paseo_env(),
            timeout=30,
        )
        if proc.returncode != 0:
            code = (parse_error_code(proc.stderr, proc.stdout) or "").upper()
            combined = (proc.stderr + "\n" + proc.stdout).lower()
            if code == "AGENT_NOT_FOUND" or "not found" in combined or "no agent" in combined:
                raise AgentNotFoundError(aid)
            detail = bounded_text(proc.stderr or proc.stdout)
            raise PaseoUnavailableError(
                f"paseo agent inspect {aid} exited {proc.returncode}"
                + (f": {detail}" if detail else "")
            )
        try:
            data = json.loads(proc.stdout or "")
        except ValueError as exc:
            raise PaseoUnavailableError(f"paseo agent inspect {aid} returned invalid JSON") from exc
        if not isinstance(data, dict) or data.get("Id") != aid:
            raise PaseoUnavailableError(f"paseo agent inspect {aid} returned mismatched identity")
        return data

    def list_live_agent_ids(self) -> set[str]:
        """Exact IDs returned by `paseo ls -g --json` (no `-a`: guards against paseo#9668)."""
        proc = self._run_cmd(
            [self.paseo_bin, "ls", "-g", "--json"],
            env=self._paseo_env(),
            timeout=30,
        )
        if proc.returncode != 0:
            detail = bounded_text(proc.stderr or proc.stdout)
            raise PaseoUnavailableError(
                f"paseo ls -g --json exited {proc.returncode}"
                + (f": {detail}" if detail else "")
            )
        try:
            rows = json.loads(proc.stdout or "")
        except ValueError as exc:
            raise PaseoUnavailableError("paseo ls -g --json returned invalid JSON") from exc
        if not isinstance(rows, list):
            raise PaseoUnavailableError("paseo ls -g --json did not return a list")
        ids: set[str] = set()
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("id"), str):
                ids.add(row["id"])
        return ids

    def _effective_lead(self, lead_id: str) -> str:
        try:
            resolved = succ.effective_lead(lead_id, state_dir=self.self_session_state, home=self.home)
        except succ.SuccessionError as exc:
            raise ArchiveRequestRefused(f"cyclic lead succession ledger for {lead_id}: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - fail closed on coordination errors
            raise ArchiveRequestRefused(f"unable to resolve lead succession for {lead_id}: {exc}") from exc
        if not isinstance(resolved, str) or not UUID_RE.fullmatch(resolved):
            raise ArchiveRequestRefused(f"lead succession returned invalid agent id for {lead_id}")
        return resolved

    def read_ade_lead_label(self, agent_id: str) -> str | None:
        """Read `labels['ade.lead']` from `${PASEO_HOME}/agents/*/<agent_id>.json`."""
        agents_root = self.home / "agents"
        if not agents_root.is_dir():
            return None
        for path in sorted(agents_root.glob(f"*/{agent_id}.json")):
            data = read_regular_json(path)
            if not data:
                continue
            labels = data.get("labels")
            if isinstance(labels, dict):
                val = labels.get("ade.lead")
                if isinstance(val, str) and UUID_RE.fullmatch(val.strip()):
                    return val.strip()
        return None

    def read_watcher_id(self) -> str | None:
        """Resolve the standing watch/unstick Paseo agent ID via `load-watch watcher show --json`,
        falling back to `$LW_STATE_DIR/watcher.json` only when `load-watch` is unavailable."""
        lw_env = dict(self.env)
        lw_env[LW_STATE_DIR_ENV] = str(self.lw_state_dir)
        data: dict[str, Any] | None = None
        if self.load_watch_bin and os.access(self.load_watch_bin, os.X_OK):
            proc = self._run_cmd(
                [str(self.load_watch_bin), "watcher", "show", "--json"],
                env=lw_env,
                timeout=30,
            )
            if proc.returncode == 0:
                try:
                    parsed = json.loads(proc.stdout or "")
                except ValueError as exc:
                    raise PaseoUnavailableError("load-watch watcher show --json returned invalid JSON") from exc
                if not isinstance(parsed, dict):
                    raise PaseoUnavailableError("load-watch watcher show --json did not return an object")
                data = parsed
            elif proc.returncode == 1:
                # Exit 1 is load-watch's documented "no load watcher registered" / retired relay channel.
                return None
            else:
                detail = bounded_text(proc.stderr or proc.stdout)
                raise PaseoUnavailableError(
                    f"load-watch watcher show exited {proc.returncode}"
                    + (f": {detail}" if detail else "")
                )
        else:
            watcher_file = self.lw_state_dir / "watcher.json"
            if not watcher_file.exists():
                return None
            data = read_regular_json(watcher_file)
            if data is None:
                return None

        if data.get("channel") != "paseo":
            return None
        target = data.get("target")
        if not isinstance(target, str) or not UUID_RE.fullmatch(target.strip()):
            return None
        w_home = data.get("paseo_home")
        if isinstance(w_home, str) and w_home.strip():
            try:
                if Path(w_home).expanduser().resolve() != self.home:
                    return None
            except OSError:
                return None
        return target.strip()

    def read_supervisor_lead_id(self) -> str | None:
        """Read first line of `${ADE_SUPERVISOR_STATE_DIR:-~/.local/state/djbclark-ade/supervisor}/lead`."""
        path = self.supervisor_state_dir / "lead"
        raw = read_regular_bytes(path, max_bytes=4096)
        if raw is None:
            return None
        text = raw.decode("utf-8", "replace")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped if UUID_RE.fullmatch(stripped) else None
        return None

    def _is_standing_watcher(self, agent_id: str) -> tuple[bool, str | None]:
        """Return (is_watcher, resolved_watcher_id_or_None)."""
        raw_watcher = self.read_watcher_id()
        if raw_watcher is None:
            return False, None
        if raw_watcher == agent_id:
            return True, raw_watcher
        resolved = self._effective_lead(raw_watcher)
        return (resolved == agent_id), resolved

    def _check_live_target(self, target_id: str, label: str, *, strict: bool) -> tuple[bool, str]:
        """Inspect `target_id`; return (is_live, reason_if_not). Raises on Paseo outage or strict refusal."""
        try:
            info = self.inspect_agent(target_id)
        except AgentNotFoundError:
            msg = f"{label} {target_id} was not found in Paseo"
            if strict:
                raise ArchiveRequestRefused(msg) from None
            return False, msg
        if info.get("Archived") is not False:
            msg = f"{label} {target_id} is archived (refusing to un-archive a retired agent)"
            if strict:
                raise ArchiveRequestRefused(msg)
            return False, msg
        return True, ""

    def resolve_caller(self, explicit_self: str | None = None) -> str:
        raw = explicit_self if explicit_self is not None else self.env.get("PASEO_AGENT_ID")
        if not raw or not raw.strip():
            raise ArchiveRequestRefused(
                "caller is not a Paseo agent: PASEO_AGENT_ID is not set (pass --self ID only for testing)"
            )
        return validate_uuid(raw, "caller agent id")

    def resolve_target(
        self,
        self_id: str,
        self_info: dict[str, Any],
        *,
        explicit_to: str | None = None,
        explicit_lead: str | None = None,
        watcher_id: str | None = None,
    ) -> tuple[str, str]:
        """Resolve `(target_id, target_kind)` in deterministic order and verify `Archived: false`."""
        reasons: list[str] = []

        # 1. Explicit --to <target-id>
        if explicit_to is not None:
            target = validate_uuid(explicit_to, "--to target id")
            if target == self_id:
                raise ArchiveRequestRefused(f"refusing self-target: --to {target} is the caller itself")
            self._check_live_target(target, "explicit target", strict=True)
            return target, "explicit"

        # 2. Owning LEAD: --lead, else ade.lead label, else ParentAgentId, followed through effective_lead()
        if explicit_lead is not None:
            raw_lead = validate_uuid(explicit_lead, "--lead id")
            resolved_lead = self._effective_lead(raw_lead)
            if resolved_lead == self_id:
                raise ArchiveRequestRefused(
                    f"refusing self-target: --lead {raw_lead} resolved to caller {self_id}"
                )
            self._check_live_target(resolved_lead, "owning lead", strict=True)
            return resolved_lead, "lead"

        discovered_lead = self.read_ade_lead_label(self_id)
        if discovered_lead is None:
            parent = self_info.get("ParentAgentId")
            if isinstance(parent, str) and UUID_RE.fullmatch(parent.strip()):
                discovered_lead = parent.strip()

        if discovered_lead is not None:
            resolved_lead = self._effective_lead(discovered_lead)
            if resolved_lead == self_id:
                reasons.append(f"owning lead {discovered_lead} resolved to caller itself")
            else:
                live, why = self._check_live_target(resolved_lead, "owning lead", strict=False)
                if live:
                    return resolved_lead, "lead"
                reasons.append(why)

        # 3a. Standing watch/unstick agent
        if watcher_id is not None:
            if watcher_id == self_id:
                raise ArchiveRequestRefused(
                    f"caller {self_id} is the standing watcher and cannot request its own archive"
                )
            live, why = self._check_live_target(watcher_id, "standing watcher", strict=False)
            if live:
                return watcher_id, "watcher"
            reasons.append(why)
        else:
            reasons.append("no standing watcher registered")

        # 3b. Fallback: supervisor/lead (only if watcher absent/archived and supervisor/lead != self)
        raw_sup = self.read_supervisor_lead_id()
        if raw_sup is not None:
            resolved_sup = self._effective_lead(raw_sup)
            if resolved_sup == self_id:
                reasons.append(f"supervisor/lead {resolved_sup} is the caller itself")
            else:
                live, why = self._check_live_target(resolved_sup, "supervisor lead", strict=False)
                if live:
                    return resolved_sup, "supervisor"
                reasons.append(why)
        else:
            reasons.append("no supervisor/lead configured")

        detail = "; ".join(reasons) if reasons else "no live target available"
        raise ArchiveRequestRefused(f"no live archiver target found ({detail})")

    def request_archive(
        self,
        *,
        explicit_self: str | None = None,
        explicit_to: str | None = None,
        explicit_lead: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Validate caller, check standing-watcher guard, resolve live target, persist record, and send."""
        self_id = self.resolve_caller(explicit_self)

        # Verify caller is a real, non-archived Paseo agent.
        try:
            self_info = self.inspect_agent(self_id)
        except AgentNotFoundError:
            raise ArchiveRequestRefused(
                f"caller {self_id} is not a known Paseo agent"
            ) from None
        if self_info.get("Archived") is True:
            raise ArchiveRequestRefused(f"caller {self_id} is already archived")

        # Never allow a standing watcher to request its own archive.
        is_watcher, resolved_watcher = self._is_standing_watcher(self_id)
        if is_watcher:
            raise ArchiveRequestRefused(
                f"caller {self_id} is the registered standing watcher; "
                "hand off or transfer the watcher role before finishing (skills/loose/SKILL.md Rule 4)"
            )

        target_id, target_kind = self.resolve_target(
            self_id,
            self_info,
            explicit_to=explicit_to,
            explicit_lead=explicit_lead,
            watcher_id=resolved_watcher,
        )

        clean_reason = sanitize_reason(reason)
        request_id = self.uuid_factory()
        requested_at = self.clock()
        record_path = self.state_dir / f"{self_id}.json"

        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "agent_id": self_id,
            "target_id": target_id,
            "target_kind": target_kind,
            "request_id": request_id,
            "reason": clean_reason,
            "requested_at": requested_at,
            "home": str(self.home),
            "status": "pending",
        }
        write_atomic_json(record_path, record, mode=0o600)

        message = build_archive_message(self_id, request_id, clean_reason, record_path)
        argv = [self.paseo_bin, "send", "--json", "--no-wait", "--", target_id, message]
        proc = self._run_cmd(argv, env=self._paseo_env(), timeout=60)
        if proc.returncode not in (0, 5):
            err_detail = bounded_text(proc.stderr or proc.stdout)
            record["send_status"] = "failed"
            record["send_rc"] = proc.returncode
            if err_detail:
                record["send_error"] = err_detail
            write_atomic_json(record_path, record, mode=0o600)
            raise ArchiveRequestError(
                f"paseo send to {target_id} exited {proc.returncode}"
                + (f": {err_detail}" if err_detail else "")
            )

        send_st = parse_send_status(proc.stdout, proc.returncode)
        record["send_status"] = send_st
        record["send_rc"] = proc.returncode
        write_atomic_json(record_path, record, mode=0o600)

        return {
            "record_path": str(record_path),
            "record": record,
        }

    def _owns_target(self, target_id: str, caller_id: str) -> bool:
        if target_id == caller_id:
            return True
        try:
            return self._effective_lead(target_id) == caller_id
        except ArchiveRequestRefused:
            return False

    def sweep(
        self,
        *,
        apply: bool = False,
        all_requests: bool = False,
        explicit_self: str | None = None,
    ) -> dict[str, Any]:
        """Inspect (and with `apply=True`, fulfill) pending archive requests in `self.state_dir`."""
        caller_id: str | None = None
        if explicit_self is not None or self.env.get("PASEO_AGENT_ID"):
            caller_id = self.resolve_caller(explicit_self)
        elif not all_requests:
            raise ArchiveRequestRefused(
                "sweep requires PASEO_AGENT_ID (or --self ID) to check target ownership; pass --all only as the watch lead"
            )

        watcher_ids: set[str] = set()
        raw_watcher = self.read_watcher_id()
        if raw_watcher is not None:
            watcher_ids.add(raw_watcher)
            try:
                watcher_ids.add(self._effective_lead(raw_watcher))
            except ArchiveRequestRefused:
                pass

        results: list[dict[str, Any]] = []
        errors = 0

        if not self.state_dir.is_dir():
            return {
                "apply": apply,
                "all": all_requests,
                "caller_id": caller_id,
                "state_dir": str(self.state_dir),
                "results": results,
                "errors": errors,
            }

        listed_ids: set[str] | None = None

        for path in sorted(self.state_dir.iterdir()):
            if not path.name.endswith(".json") or path.name.startswith("."):
                continue
            stem = path.stem
            if not UUID_RE.fullmatch(stem):
                continue
            record = read_regular_json(path)
            if record is None:
                results.append({"file": path.name, "agent_id": stem, "action": "skip", "reason": "unreadable-record"})
                continue
            if record.get("schema_version") != SCHEMA_VERSION:
                results.append({"file": path.name, "agent_id": stem, "action": "skip", "reason": "unsupported-schema"})
                continue
            agent_id = record.get("agent_id")
            target_id = record.get("target_id")
            if agent_id != stem or not isinstance(target_id, str) or not UUID_RE.fullmatch(target_id):
                results.append({"file": path.name, "agent_id": stem, "action": "skip", "reason": "malformed-record"})
                continue

            rec_home = record.get("home")
            if isinstance(rec_home, str) and rec_home:
                try:
                    if Path(rec_home).resolve() != self.home:
                        results.append({"file": path.name, "agent_id": agent_id, "action": "skip", "reason": "other-home"})
                        continue
                except OSError:
                    results.append({"file": path.name, "agent_id": agent_id, "action": "skip", "reason": "other-home"})
                    continue

            status = record.get("status")
            if status == "archived":
                results.append({"file": path.name, "agent_id": agent_id, "action": "skip", "reason": "already-archived"})
                continue
            if status != "pending":
                results.append({"file": path.name, "agent_id": agent_id, "action": "skip", "reason": f"status:{status}"})
                continue

            if not all_requests:
                assert caller_id is not None
                if not self._owns_target(target_id, caller_id):
                    results.append(
                        {
                            "file": path.name,
                            "agent_id": agent_id,
                            "target_id": target_id,
                            "action": "skip",
                            "reason": "other-target",
                        }
                    )
                    continue

            if caller_id is not None and agent_id == caller_id:
                results.append({"file": path.name, "agent_id": agent_id, "action": "skip", "reason": "self-skip"})
                continue
            if agent_id in watcher_ids:
                results.append({"file": path.name, "agent_id": agent_id, "action": "skip", "reason": "standing-watcher"})
                continue

            # Inspect agent live state.
            try:
                info = self.inspect_agent(agent_id)
            except AgentNotFoundError:
                results.append({"file": path.name, "agent_id": agent_id, "action": "skip", "reason": "not-found"})
                continue
            except PaseoUnavailableError as exc:
                errors += 1
                results.append(
                    {"file": path.name, "agent_id": agent_id, "action": "error", "reason": bounded_text(exc)}
                )
                continue

            if info.get("Archived") is True:
                if apply:
                    record["status"] = "archived"
                    record.setdefault("archived_at", self.clock())
                    record.setdefault("archived_by", caller_id or "already-archived")
                    write_atomic_json(path, record, mode=0o600)
                results.append(
                    {
                        "file": path.name,
                        "agent_id": agent_id,
                        "action": "already-archived",
                        "reason": "already-archived-in-paseo",
                    }
                )
                continue

            agent_status = str(info.get("Status") or "").strip().lower()
            if agent_status not in SWEEP_ARCHIVEABLE_STATUSES:
                results.append(
                    {
                        "file": path.name,
                        "agent_id": agent_id,
                        "action": "skip",
                        "reason": f"status:{agent_status or 'unknown'}",
                    }
                )
                continue

            perms = info.get("PendingPermissions")
            if not isinstance(perms, list) or len(perms) != 0:
                results.append(
                    {
                        "file": path.name,
                        "agent_id": agent_id,
                        "action": "skip",
                        "reason": "pending-permissions",
                    }
                )
                continue

            # Guard against getpaseo/paseo#9668: require exact ID in `paseo ls -g --json` (no `-a`).
            if listed_ids is None:
                try:
                    listed_ids = self.list_live_agent_ids()
                except PaseoUnavailableError as exc:
                    errors += 1
                    results.append(
                        {"file": path.name, "agent_id": agent_id, "action": "error", "reason": bounded_text(exc)}
                    )
                    continue
            if agent_id not in listed_ids:
                results.append(
                    {
                        "file": path.name,
                        "agent_id": agent_id,
                        "action": "skip",
                        "reason": "LISTING_GAP",
                    }
                )
                continue

            if not apply:
                results.append(
                    {
                        "file": path.name,
                        "agent_id": agent_id,
                        "target_id": target_id,
                        "action": "would-archive",
                        "agent_status": agent_status,
                    }
                )
                continue

            # Apply: non-forced exact-ID archive, NEVER --force, NEVER workspace archive.
            proc = self._run_cmd(
                [self.paseo_bin, "agent", "archive", agent_id, "--json"],
                env=self._paseo_env(),
                timeout=30,
            )
            if proc.returncode != 0:
                errors += 1
                code = parse_error_code(proc.stderr, proc.stdout)
                detail = bounded_text(proc.stderr or proc.stdout)
                reason_str = code or detail or f"archive exited {proc.returncode}"
                results.append(
                    {"file": path.name, "agent_id": agent_id, "action": "error", "reason": reason_str}
                )
                continue

            try:
                receipt = json.loads(proc.stdout or "")
            except ValueError:
                receipt = None
            if isinstance(receipt, dict):
                archived_id = receipt.get("agentId")
                if archived_id is not None and archived_id != agent_id:
                    errors += 1
                    results.append(
                        {
                            "file": path.name,
                            "agent_id": agent_id,
                            "action": "error",
                            "reason": f"ARCHIVED_OTHER_AGENT:{bounded_text(archived_id, 64)}",
                        }
                    )
                    continue

            # Verify Archived: true readback before marking fulfilled.
            try:
                after = self.inspect_agent(agent_id)
            except (AgentNotFoundError, PaseoUnavailableError) as exc:
                errors += 1
                results.append(
                    {
                        "file": path.name,
                        "agent_id": agent_id,
                        "action": "error",
                        "reason": f"readback-failed:{bounded_text(exc)}",
                    }
                )
                continue

            if after.get("Archived") is not True:
                errors += 1
                results.append(
                    {
                        "file": path.name,
                        "agent_id": agent_id,
                        "action": "error",
                        "reason": "archive-unconfirmed",
                    }
                )
                continue

            record["status"] = "archived"
            record["archived_at"] = self.clock()
            record["archived_by"] = caller_id or "sweep"
            write_atomic_json(path, record, mode=0o600)
            results.append(
                {
                    "file": path.name,
                    "agent_id": agent_id,
                    "target_id": target_id,
                    "action": "archived",
                    "archived_at": record["archived_at"],
                }
            )

        return {
            "apply": apply,
            "all": all_requests,
            "caller_id": caller_id,
            "state_dir": str(self.state_dir),
            "results": results,
            "errors": errors,
        }
