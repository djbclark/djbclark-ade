"""Automated Herdr self-handoff for non-Paseo sessions running inside a Herdr pane.

Carried #122 Phase 2 (2026-11-25): restores safe, deterministic Herdr tab/pane
succession using the current Herdr v0.9.5 JSON CLI (`herdr pane current --current`,
`herdr pane process-info --pane <id>`, `herdr tab create`, `herdr agent start`,
`herdr agent prompt`).

Safety invariants:
- `PASEO_AGENT_ID` (non-blank) ALWAYS wins as Paseo mode: refuses immediately so
  Paseo-hosted sessions use `bin/ade-self-session handoff`.
- Outside Paseo, verifies genuine Herdr hosting: `HERDR_ENV=1`, non-blank
  `HERDR_PANE_ID`, live `herdr pane current --current` returning exact `pane_id == HERDR_PANE_ID`,
  AND `herdr pane process-info --pane <id>` returning `shell_pid > 1` that is a real OS ancestor
  PID of this process (never trusting inherited `HERDR_ENV=1` or `HERDR_PANE_ID` alone).
- Fail-closed preflight validates checkpoint (absolute regular UTF-8 file, symlinks refused),
  Tier 1 path, cwd, git HEAD, kind, model, per-kind effort, mode, agent name, and per-pane
  advisory lock BEFORE mutating Herdr layout.
- Launches a real interactive TUI (`claude` or `codex`) in a new tab of the same
  workspace and submits the baton prompt ONCE (`/baton <tier1>` for Claude,
  `$baton <tier1>` for Codex) without `--timeout` on `herdr agent prompt` (Herdr v0.9.5
  rejects `--timeout` unless `--wait` is passed; `--prompt-timeout` bounds Python's
  subprocess timeout). Never uses `pane run` / raw `send-keys` for prompting and never
  blind-retries on `agent_not_ready`, `agent_blocked`, `agent_prompt_stalled`, or unknown outcomes.
- Preserves the predecessor pane (never closes, kills, or exits it).
- Persists a durable `schema_version: 1` JSON record (`0o600`, atomic write) and
  secret-scrubs full stderr BEFORE clipping.
"""
from __future__ import annotations

import contextlib
import datetime
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
STATE_ENV = "ADE_HERDR_HANDOFF_STATE"
HERDR_BIN_ENV = "ADE_HERDR_BIN"
DEFAULT_STATE_REL = Path(".local/state/djbclark-ade/herdr-handoff")

SUPPORTED_KINDS = ("claude", "codex")
CLAUDE_PERMISSION_MODES = (
    "bypassPermissions",
    "acceptEdits",
    "plan",
    "default",
    "auto",
    "dontAsk",
)
DEFAULT_CLAUDE_MODE = "bypassPermissions"

# Verified per-client effort values (2026-11-25):
# - claude: live `claude --help` and `bin/route_agent.py` CLAUDE_EFFORT_LEVELS
# - codex: `model_reasoning_effort` enum (codex-cli)
EFFORT_LEVELS_BY_KIND: dict[str, tuple[str, ...]] = {
    "claude": ("low", "medium", "high", "xhigh", "max"),
    "codex": ("none", "minimal", "low", "medium", "high", "xhigh"),
}

MAX_CHECKPOINT_BYTES = 1024 * 1024
MAX_RECORD_BYTES = 256 * 1024
MAX_LOCK_META_BYTES = 8 * 1024
DEFAULT_START_TIMEOUT_MS = 60_000
DEFAULT_PROMPT_TIMEOUT_MS = 30_000
MIN_TIMEOUT_MS = 1_000
MAX_TIMEOUT_MS = 300_000
PROBE_TIMEOUT_S = 15.0
MAX_ANCESTOR_DEPTH = 64

TAIL_LIMIT = 512
MESSAGE_LIMIT = 300
MAX_SCRUB_BYTES = 1024 * 1024
MAX_STDOUT_BYTES = 4 * 1024 * 1024

# Strict identifier validators (matching skills/herdr/SKILL.md and ade_self_session.py)
PANE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
WORKSPACE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
TAB_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
AGENT_NAME_RE = re.compile(r"[a-z][a-z0-9_-]{0,31}")
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@\[\]-]{0,127}")
TITLE_LIMIT = 80

# Secret redaction (mirrors bin/ade_self_session.py)
_KEYWORDS = (
    r"(?:token|secret|password|passwd|authorization|bearer|api[_-]?key|access[_-]?key|private[_-]?key"
    r"|credential)\w*"
)
_VALUE = r'(?:"(?:\\.|[^"\\\n])*"?|\'(?:\\.|[^\'\\\n])*\'?|[^\s"\',}]+)'
_SECRETISH = re.compile(
    r"(?i)((?<![A-Za-z0-9])" + _KEYWORDS + r'["\']?\s*[:=]\s*(?:(?:basic|bearer|token)\s+)?)' + _VALUE
)
_BEARER = re.compile(r'(?i)((?<![A-Za-z0-9])bearer\s+)[^\s"\',}]+')
_COOKIE = re.compile(r'(?i)(\b(?:set-)?cookie\w*["\']?\s*[:=]\s*)[^\n]+')
_URL_USERINFO = re.compile(r"(://[^/\s:@]+:)[^@\s/]+@")
_BARE_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_-])(?:gh[pousr]_|github_pat_|sk-|xox[bpars]-)[A-Za-z0-9_-]+"
    r"|\bAKIA[0-9A-Z]{16}\b"
)
_CODE_CHARS = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
_ALNUM_RUN = re.compile(r"[A-Za-z0-9]{16,}")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_REFUSED = 4


class HerdrHandoffError(RuntimeError):
    """Structured error with exit code and safe machine-readable code."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "handoff_error",
        exit_code: int = EXIT_ERROR,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code
        self.detail = dict(detail) if detail else {}


class HerdrCommandError(HerdrHandoffError):
    """Error raised when a `herdr` CLI invocation fails or returns an error envelope."""

    def __init__(
        self,
        message: str,
        *,
        op: str,
        herdr_code: str | None,
        herdr_message: str | None,
        rc: int | None,
        stderr_tail: str,
        outcome: str,
    ) -> None:
        info = {
            "op": op,
            "code": herdr_code,
            "message": herdr_message,
            "rc": rc,
            "stderr_tail": stderr_tail,
            "outcome": outcome,
        }
        super().__init__(
            message,
            code=herdr_code or "herdr_command_failed",
            exit_code=EXIT_ERROR,
            detail=info,
        )
        self.info = info
        self.herdr_code = herdr_code
        self.outcome = outcome


def default_state_dir(env: dict[str, str] | None = None) -> Path:
    src = os.environ if env is None else env
    override = (src.get(STATE_ENV) or "").strip()
    if override:
        return Path(os.path.expanduser(override))
    return Path.home() / DEFAULT_STATE_REL


def scrub_secrets(text: Any) -> str:
    """Printable, secret-scrubbed string over the full buffer (up to MAX_SCRUB_BYTES from the start)."""
    raw_full = str(text or "")
    # Never slice off a leading prefix before scrubbing: if an input exceeds MAX_SCRUB_BYTES,
    # scrub from the start so every leading `keyword=` / `Bearer ` / URL userinfo prefix stays intact.
    if len(raw_full) > MAX_SCRUB_BYTES:
        raw_full = raw_full[:MAX_SCRUB_BYTES]
    cleaned = "".join(c if c.isprintable() or c in "\n\t" else "?" for c in raw_full)
    cleaned = _URL_USERINFO.sub(lambda m: m.group(1) + "[redacted]@", cleaned)
    cleaned = _BARE_TOKEN.sub("[redacted]", cleaned)
    cleaned = _COOKIE.sub(lambda m: m.group(1) + "[redacted]", cleaned)
    cleaned = _BEARER.sub(lambda m: m.group(1) + "[redacted]", cleaned)
    cleaned = _SECRETISH.sub(lambda m: m.group(1) + "[redacted]", cleaned)
    return cleaned.strip()


def bounded(text: Any, limit: int) -> str:
    """Scrub secrets FIRST, then clip to at most `limit` characters."""
    cleaned = scrub_secrets(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)] + "..."


def valid_code(code: str) -> bool:
    """True for an error code safe to record verbatim (validated, never scrubbed)."""
    return bool(
        _CODE_CHARS.fullmatch(code)
        and bounded(code, 64) == code
        and not any(re.search(r"\d", run) for run in _ALNUM_RUN.findall(code))
    )


def parse_error_envelope(*streams: str) -> tuple[str | None, str | None] | None:
    """Extract (code, bounded_message) from a Herdr JSON error envelope on stderr/stdout."""
    for text in streams:
        cleaned = (text or "").strip()
        if not cleaned:
            continue
        candidates = [cleaned, *reversed([ln for ln in cleaned.splitlines() if ln.lstrip().startswith("{")])]
        for candidate in candidates:
            try:
                data = json.loads(candidate)
            except ValueError:
                continue
            if not isinstance(data, dict) or not ("error" in data or "code" in data):
                continue
            err = data.get("error")
            if isinstance(err, dict):
                code, message = err.get("code"), err.get("message")
            else:
                code = data.get("code")
                message = err if isinstance(err, str) else data.get("message")
            if isinstance(code, str) and code:
                code = code if valid_code(code) else "INVALID_CODE"
            else:
                code = None
            msg = bounded(message, MESSAGE_LIMIT) if isinstance(message, str) and message else None
            return code, msg
    return None


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_regular(path: Path, limit: int, *, nofollow: bool = False) -> bytes:
    """Read a regular file up to `limit` bytes without blocking on FIFOs/devices."""
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    if nofollow and hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if nofollow and exc.errno == errno.ELOOP:
            raise HerdrHandoffError(
                f"symlink refused: {path}",
                code="symlink_refused",
                exit_code=EXIT_USAGE,
            ) from None
        raise HerdrHandoffError(
            f"cannot open file {path}: {exc.strerror or type(exc).__name__}",
            code="file_unreadable",
            exit_code=EXIT_USAGE,
        ) from None
    try:
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            st = os.fstat(stream.fileno())
            if not stat.S_ISREG(st.st_mode):
                raise HerdrHandoffError(
                    f"path must be a regular file: {path}",
                    code="not_regular_file",
                    exit_code=EXIT_USAGE,
                )
            data = stream.read(limit + 1)
    finally:
        if fd >= 0:
            os.close(fd)
    if len(data) > limit:
        raise HerdrHandoffError(
            f"file exceeds {limit} byte limit: {path}",
            code="file_too_large",
            exit_code=EXIT_USAGE,
        )
    return data


def write_atomic(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    """Atomically write `data` to `path` with private mode and fsync."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        if os.path.exists(temp):
            try:
                os.unlink(temp)
            except OSError:
                pass


def validate_kind(kind: str) -> str:
    if not isinstance(kind, str) or kind not in SUPPORTED_KINDS:
        raise HerdrHandoffError(
            f"unsupported --kind {kind!r}; expected one of: {', '.join(SUPPORTED_KINDS)}",
            code="invalid_kind",
            exit_code=EXIT_USAGE,
        )
    return kind


def validate_model(model: str | None) -> str | None:
    if model is None:
        return None
    if (
        not isinstance(model, str)
        or not model
        or any(c.isspace() or not c.isprintable() for c in model)
        or MODEL_RE.fullmatch(model) is None
        or model.lower() == "default"
        or model == "-"
    ):
        raise HerdrHandoffError(
            "invalid --model: concrete model identifier without whitespace, control characters, or leading hyphen required",
            code="invalid_model",
            exit_code=EXIT_USAGE,
        )
    return model


def validate_effort(kind: str, effort: str | None) -> str | None:
    if effort is None:
        return None
    allowed = EFFORT_LEVELS_BY_KIND.get(kind, ())
    if not isinstance(effort, str) or effort not in allowed:
        raise HerdrHandoffError(
            f"invalid --effort {effort!r} for --kind {kind}; expected one of: {', '.join(allowed)}",
            code="invalid_effort",
            exit_code=EXIT_USAGE,
        )
    return effort


def validate_mode(kind: str, mode: str | None) -> str | None:
    if mode is None:
        return DEFAULT_CLAUDE_MODE if kind == "claude" else None
    if kind != "claude":
        raise HerdrHandoffError(
            f"--mode is supported only for --kind claude (got --kind {kind})",
            code="invalid_mode",
            exit_code=EXIT_USAGE,
        )
    if mode not in CLAUDE_PERMISSION_MODES:
        raise HerdrHandoffError(
            f"invalid --mode {mode!r}; expected one of: {', '.join(CLAUDE_PERMISSION_MODES)}",
            code="invalid_mode",
            exit_code=EXIT_USAGE,
        )
    return mode


def validate_agent_name(name: str | None, *, token: str) -> str:
    if name is None:
        return f"handoff-{token[:8]}"
    if not isinstance(name, str) or AGENT_NAME_RE.fullmatch(name) is None:
        raise HerdrHandoffError(
            "invalid --name: must match [a-z][a-z0-9_-]{0,31}",
            code="invalid_name",
            exit_code=EXIT_USAGE,
        )
    return name


def validate_title(title: str | None, *, cwd: str, kind: str) -> str:
    if title is None:
        base = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(cwd).name or "session").strip("-") or "session"
        raw = f"{base}-handoff" if kind == "claude" else f"{base}-{kind}-handoff"
        return raw[:48].rstrip("-") or "handoff"
    if not isinstance(title, str):
        raise HerdrHandoffError("invalid --title", code="invalid_title", exit_code=EXIT_USAGE)
    cleaned = " ".join("".join(c if c.isprintable() else " " for c in title).split())
    if not cleaned:
        raise HerdrHandoffError("--title must be non-empty printable text", code="invalid_title", exit_code=EXIT_USAGE)
    if len(cleaned) > TITLE_LIMIT:
        cleaned = cleaned[:TITLE_LIMIT].rstrip()
    return cleaned


def validate_timeout_ms(value: int, *, flag: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not (MIN_TIMEOUT_MS <= value <= MAX_TIMEOUT_MS):
        raise HerdrHandoffError(
            f"{flag} must be an integer between {MIN_TIMEOUT_MS} and {MAX_TIMEOUT_MS} ms",
            code="invalid_timeout",
            exit_code=EXIT_USAGE,
        )
    return value


def validate_checkpoint(path: Path) -> tuple[str, bytes, str]:
    raw_str = str(path)
    if not raw_str or any(ord(c) < 32 or ord(c) == 127 for c in raw_str):
        raise HerdrHandoffError("--checkpoint path contains control characters", code="invalid_checkpoint", exit_code=EXIT_USAGE)
    if not path.is_absolute():
        raise HerdrHandoffError(
            f"--checkpoint must be an absolute path (got {raw_str!r})",
            code="invalid_checkpoint",
            exit_code=EXIT_USAGE,
        )
    data = read_regular(path, MAX_CHECKPOINT_BYTES, nofollow=True)
    if not data.strip():
        raise HerdrHandoffError("--checkpoint must be non-empty", code="invalid_checkpoint", exit_code=EXIT_USAGE)
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        raise HerdrHandoffError("--checkpoint must be valid UTF-8", code="invalid_checkpoint", exit_code=EXIT_USAGE) from None
    return str(path.resolve()), data, digest_bytes(data)


def validate_tier1(path: Path) -> str:
    raw_str = str(path)
    if not raw_str or any(ord(c) < 32 or ord(c) == 127 for c in raw_str):
        raise HerdrHandoffError("--tier1 path contains control characters", code="invalid_tier1", exit_code=EXIT_USAGE)
    expanded = Path(os.path.expanduser(raw_str))
    resolved = expanded.resolve() if expanded.is_absolute() else (Path.cwd() / expanded).resolve()
    # Confirm Tier 1 pointer exists and is a regular readable file (bounded read)
    read_regular(resolved, MAX_CHECKPOINT_BYTES)
    resolved_str = str(resolved)
    if any(ord(c) < 32 or ord(c) == 127 for c in resolved_str):
        raise HerdrHandoffError("resolved --tier1 path contains control characters", code="invalid_tier1", exit_code=EXIT_USAGE)
    return resolved_str


def validate_cwd(cwd: Path | None) -> str:
    target = Path.cwd() if cwd is None else Path(os.path.expanduser(str(cwd)))
    resolved = os.path.realpath(str(target))
    if not os.path.isdir(resolved):
        raise HerdrHandoffError(
            f"--cwd is not an existing directory: {target}",
            code="invalid_cwd",
            exit_code=EXIT_USAGE,
        )
    return resolved


def build_native_args(kind: str, *, model: str | None = None, effort: str | None = None, mode: str | None = None) -> list[str]:
    """Return validated native CLI args passed after `herdr agent start ... --`."""
    if kind == "claude":
        effective_mode = mode or DEFAULT_CLAUDE_MODE
        args = ["--permission-mode", effective_mode]
        if model:
            args.extend(["--model", model])
        if effort:
            args.extend(["--effort", effort])
        return args
    if kind == "codex":
        args = ["--dangerously-bypass-approvals-and-sandbox"]
        if model:
            args.extend(["-m", model])
        if effort:
            args.extend(["-c", f'model_reasoning_effort="{effort}"'])
        return args
    raise HerdrHandoffError(f"unsupported kind: {kind}", code="invalid_kind", exit_code=EXIT_USAGE)


def build_baton_prompt(kind: str, tier1_path: str) -> str:
    """Format the single baton resume prompt per client syntax (skills/baton/SKILL.md)."""
    if kind == "codex":
        return f"$baton {tier1_path}"
    return f"/baton {tier1_path}"


def _safe_lock_stem(pane_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", pane_id)


def _pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _parent_pid(pid: int) -> int | None:
    """Return OS parent PID for `pid` on macOS or Linux, or None when unavailable."""
    if not isinstance(pid, int) or pid <= 1:
        return None
    proc_stat = Path(f"/proc/{pid}/stat")
    if proc_stat.is_file():
        try:
            text = proc_stat.read_text(encoding="utf-8", errors="replace")
            rparen = text.rfind(")")
            if rparen >= 0:
                fields = text[rparen + 2 :].split()
                if len(fields) >= 2 and fields[1].isdigit():
                    return int(fields[1])
        except OSError:
            pass
    try:
        proc = subprocess.run(
            ["ps", "-o", "ppid=", "-p", str(pid)],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    val = (proc.stdout or "").strip()
    return int(val) if val.isdigit() else None


def caller_ancestor_pids(start_pid: int | None = None) -> set[int]:
    """Walk the real OS ancestor chain starting at `start_pid` (default `os.getpid()`), excluding PID <= 1."""
    pid = os.getpid() if start_pid is None else start_pid
    ancestors: set[int] = set()
    cur = pid
    for _ in range(MAX_ANCESTOR_DEPTH):
        if not isinstance(cur, int) or cur <= 1 or cur in ancestors:
            break
        ancestors.add(cur)
        nxt = _parent_pid(cur)
        if nxt is None or nxt <= 1 or nxt == cur:
            break
        cur = nxt
    return ancestors


def _git_entry_above(cwd: str) -> bool:
    here = Path(os.path.realpath(cwd))
    return any(os.path.lexists(d / ".git") for d in (here, *here.parents))


class HerdrHandoffService:
    """Orchestrates preflight validation, locking, Herdr launch, and record persistence."""

    def __init__(
        self,
        state_dir: Path | None = None,
        *,
        env: dict[str, str] | None = None,
        herdr_bin: str | None = None,
        runner: Any = None,
        progress: Any = None,
        ancestor_pids_fn: Any = None,
    ) -> None:
        self.env = dict(os.environ if env is None else env)
        self.state_dir = (state_dir or default_state_dir(self.env)).resolve()
        self.herdr_bin_override = herdr_bin or (self.env.get(HERDR_BIN_ENV) or "").strip() or None
        self.runner = runner or subprocess.run
        self.progress = progress or (lambda msg: None)
        self.ancestor_pids_fn = ancestor_pids_fn or caller_ancestor_pids

    def resolve_herdr_bin(self) -> str:
        if self.herdr_bin_override:
            expanded = os.path.expanduser(self.herdr_bin_override)
            # Always resolve an explicit override to an absolute path so relative paths like
            # `./herdr` never normalize to a slashless name that subprocess resolves via PATH.
            cand = Path(os.path.abspath(expanded))
            if cand.is_file() and os.access(cand, os.X_OK):
                return str(cand)
            raise HerdrHandoffError(
                f"herdr binary not executable: {self.herdr_bin_override}",
                code="herdr_not_found",
                exit_code=EXIT_ERROR,
            )
        found = shutil.which("herdr", path=self.env.get("PATH"))
        if not found:
            raise HerdrHandoffError(
                "herdr binary not found on PATH (set ADE_HERDR_BIN or --herdr-bin)",
                code="herdr_not_found",
                exit_code=EXIT_ERROR,
            )
        return os.path.abspath(found)

    def check_caller_env(self) -> str:
        """Enforce skills/herdr/SKILL.md ADE rule 1: PASEO_AGENT_ID always wins; require HERDR_ENV=1 + HERDR_PANE_ID."""
        paseo_id = (self.env.get("PASEO_AGENT_ID") or "").strip()
        if paseo_id:
            raise HerdrHandoffError(
                "PASEO_AGENT_ID is set; this session is Paseo-hosted — use bin/ade-self-session handoff "
                "instead of bin/ade-herdr-handoff",
                code="paseo_mode_active",
                exit_code=EXIT_REFUSED,
            )
        herdr_env = (self.env.get("HERDR_ENV") or "").strip()
        pane_id = (self.env.get("HERDR_PANE_ID") or "").strip()
        if herdr_env != "1" or not pane_id:
            raise HerdrHandoffError(
                "not inside a Herdr pane (requires HERDR_ENV=1 and HERDR_PANE_ID with PASEO_AGENT_ID unset); "
                "write /self-handoff Steps 0-7 locally and let the operator run /new then /baton <exact Tier 1 pointer>",
                code="not_in_herdr",
                exit_code=EXIT_REFUSED,
            )
        if PANE_ID_RE.fullmatch(pane_id) is None:
            raise HerdrHandoffError(
                f"malformed HERDR_PANE_ID: {bounded(pane_id, 64)!r}",
                code="invalid_herdr_pane_id",
                exit_code=EXIT_REFUSED,
            )
        return pane_id

    def run_herdr(self, herdr_bin: str, args: list[str], *, timeout_s: float) -> dict[str, Any]:
        """Run a `herdr` subcommand via argv list and parse its JSON response envelope."""
        op = " ".join(a for a in args[:2] if re.fullmatch(r"[a-z][a-z-]*", a)) or "herdr"
        try:
            proc = self.runner(
                [herdr_bin, *args],
                env=self.env,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            raise HerdrCommandError(
                f"herdr {op} timed out after {timeout_s:g}s; inspect before taking action",
                op=op,
                herdr_code="TIMEOUT",
                herdr_message=f"herdr {op} timed out",
                rc=None,
                stderr_tail="",
                outcome="unknown",
            ) from None
        except OSError as exc:
            raise HerdrCommandError(
                f"herdr {op} could not execute ({type(exc).__name__})",
                op=op,
                herdr_code="OSERROR",
                herdr_message=type(exc).__name__,
                rc=None,
                stderr_tail="",
                outcome="unknown",
            ) from None

        stdout = proc.stdout or ""
        raw_stderr = proc.stderr or ""
        # Scrub full stderr BEFORE clipping so a secret whose identifying prefix sits near the
        # start of stderr is redacted before truncation.
        tail = bounded(raw_stderr, TAIL_LIMIT)
        if len(stdout) > MAX_STDOUT_BYTES:
            raise HerdrCommandError(
                f"herdr {op} returned an oversized response",
                op=op,
                herdr_code="OVERSIZED_RESPONSE",
                herdr_message="response exceeded size limit",
                rc=proc.returncode,
                stderr_tail=tail,
                outcome="unknown",
            )
        if proc.returncode != 0:
            envelope = parse_error_envelope(raw_stderr, stdout)
            if envelope is None:
                raise HerdrCommandError(
                    f"herdr {op} failed (rc {proc.returncode}) with no JSON error envelope",
                    op=op,
                    herdr_code=None,
                    herdr_message=None,
                    rc=proc.returncode,
                    stderr_tail=tail,
                    outcome="unknown",
                )
            code, msg = envelope
            detail = ": ".join(x for x in (code, msg) if x)
            raise HerdrCommandError(
                f"herdr {op} refused (rc {proc.returncode})" + (f": {detail}" if detail else ""),
                op=op,
                herdr_code=code,
                herdr_message=msg,
                rc=proc.returncode,
                stderr_tail=tail,
                outcome="refused",
            )

        try:
            payload = json.loads(stdout)
        except ValueError:
            # Never persist raw unstructured stdout; keep fixed safe diagnostic + scrubbed stderr.
            raise HerdrCommandError(
                f"herdr {op} returned non-JSON stdout",
                op=op,
                herdr_code="UNPARSEABLE_OUTPUT",
                herdr_message=f"herdr {op} returned non-JSON stdout",
                rc=proc.returncode,
                stderr_tail=tail,
                outcome="unknown",
            ) from None
        if not isinstance(payload, dict):
            raise HerdrCommandError(
                f"herdr {op} returned unexpected JSON type",
                op=op,
                herdr_code="UNEXPECTED_JSON_TYPE",
                herdr_message=f"herdr {op} returned unexpected JSON type",
                rc=proc.returncode,
                stderr_tail=tail,
                outcome="unknown",
            )
        if payload.get("error"):
            envelope = parse_error_envelope(stdout, raw_stderr)
            code, msg = envelope if envelope is not None else (None, None)
            detail = ": ".join(x for x in (code, msg) if x)
            raise HerdrCommandError(
                f"herdr {op} returned error envelope" + (f": {detail}" if detail else ""),
                op=op,
                herdr_code=code,
                herdr_message=msg,
                rc=proc.returncode,
                stderr_tail=tail,
                outcome="refused",
            )
        return payload

    def verify_current_pane(self, herdr_bin: str, env_pane_id: str) -> dict[str, Any]:
        """Confirm `herdr pane current --current` matches HERDR_PANE_ID AND prove caller process-tree
        membership via `herdr pane process-info --pane <id>` (`shell_pid` in OS ancestor chain).
        """
        try:
            payload = self.run_herdr(herdr_bin, ["pane", "current", "--current"], timeout_s=PROBE_TIMEOUT_S)
        except HerdrCommandError as exc:
            raise HerdrHandoffError(
                f"could not confirm current Herdr pane via `herdr pane current --current`: {exc}",
                code="herdr_pane_unconfirmed",
                exit_code=EXIT_REFUSED,
                detail=exc.info,
            ) from None

        result = payload.get("result")
        if not isinstance(result, dict):
            raise HerdrHandoffError(
                "herdr pane current --current returned no result object",
                code="herdr_pane_unconfirmed",
                exit_code=EXIT_REFUSED,
            )
        pane = result.get("pane") if isinstance(result.get("pane"), dict) else result
        live_pane_id = pane.get("pane_id")
        workspace_id = pane.get("workspace_id")
        tab_id = pane.get("tab_id")

        if not isinstance(live_pane_id, str) or PANE_ID_RE.fullmatch(live_pane_id) is None:
            raise HerdrHandoffError(
                "herdr pane current --current returned no valid pane_id",
                code="herdr_pane_unconfirmed",
                exit_code=EXIT_REFUSED,
            )
        if not isinstance(workspace_id, str) or WORKSPACE_ID_RE.fullmatch(workspace_id) is None:
            raise HerdrHandoffError(
                "herdr pane current --current returned no valid workspace_id",
                code="herdr_pane_unconfirmed",
                exit_code=EXIT_REFUSED,
            )
        if live_pane_id != env_pane_id:
            raise HerdrHandoffError(
                f"herdr pane current --current returned pane {live_pane_id!r}, which does not match "
                f"HERDR_PANE_ID={env_pane_id!r}; refusing to act on another pane",
                code="pane_mismatch",
                exit_code=EXIT_REFUSED,
            )

        # Independent process-tree verification (skills/herdr/SKILL.md ADE rule 1):
        # `herdr pane current --current` resolves inherited HERDR_PANE_ID without checking caller
        # ancestry. Query `herdr pane process-info --pane <live_pane_id>` and verify the pane's
        # `shell_pid` (> 1) sits in this process's real OS ancestor PID chain.
        try:
            proc_payload = self.run_herdr(
                herdr_bin, ["pane", "process-info", "--pane", live_pane_id], timeout_s=PROBE_TIMEOUT_S
            )
        except HerdrCommandError as exc:
            raise HerdrHandoffError(
                f"could not verify caller process tree via `herdr pane process-info --pane {live_pane_id}`: {exc}",
                code="caller_not_in_pane",
                exit_code=EXIT_REFUSED,
                detail=exc.info,
            ) from None

        proc_result = proc_payload.get("result")
        if not isinstance(proc_result, dict):
            raise HerdrHandoffError(
                "herdr pane process-info returned no result object; cannot prove caller belongs to pane",
                code="caller_not_in_pane",
                exit_code=EXIT_REFUSED,
            )
        proc_info = (
            proc_result.get("process_info")
            if isinstance(proc_result.get("process_info"), dict)
            else proc_result
        )
        proc_pane_id = proc_info.get("pane_id")
        shell_pid = proc_info.get("shell_pid")
        if proc_pane_id != live_pane_id:
            raise HerdrHandoffError(
                f"herdr pane process-info returned pane_id {proc_pane_id!r} (expected {live_pane_id!r})",
                code="caller_not_in_pane",
                exit_code=EXIT_REFUSED,
            )
        if not isinstance(shell_pid, int) or isinstance(shell_pid, bool) or shell_pid <= 1:
            raise HerdrHandoffError(
                f"herdr pane process-info returned unusable shell_pid ({shell_pid!r}); "
                "cannot prove caller belongs to this Herdr pane",
                code="caller_not_in_pane",
                exit_code=EXIT_REFUSED,
            )
        ancestors = self.ancestor_pids_fn()
        if shell_pid not in ancestors:
            raise HerdrHandoffError(
                f"caller process is not a descendant of Herdr pane {live_pane_id} shell_pid={shell_pid}; "
                "HERDR_PANE_ID appears inherited from another pane — refusing to mutate Herdr layout",
                code="caller_not_in_pane",
                exit_code=EXIT_REFUSED,
            )

        return {
            "pane_id": live_pane_id,
            "workspace_id": workspace_id,
            "tab_id": tab_id if isinstance(tab_id, str) and TAB_ID_RE.fullmatch(tab_id) else None,
            "shell_pid": shell_pid,
            "agent": pane.get("agent") if isinstance(pane.get("agent"), str) else None,
        }

    def git_head(self, cwd: str) -> str | None:
        """Return 40-hex git HEAD of `cwd`, or None when cleanly outside any git repo."""
        env = {k: v for k, v in self.env.items() if not k.startswith("GIT_")}
        env["LC_ALL"] = "C"
        try:
            proc = self.runner(
                ["git", "-C", cwd, "rev-parse", "HEAD"],
                env=env,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=10,
            )
            value = (proc.stdout or "").strip()
            if proc.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", value):
                return value
            if (
                proc.returncode == 128
                and not value
                and re.match(
                    r"fatal: not a git repository \(or any (?:of the parent directories"
                    r"|parent up to mount point [^)]*)\)",
                    (proc.stderr or "").lstrip(),
                )
                and not _git_entry_above(cwd)
            ):
                return None
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise HerdrHandoffError(
            f"exact repository HEAD unavailable for {cwd}",
            code="git_head_unavailable",
            exit_code=EXIT_ERROR,
        )

    @staticmethod
    def _read_lock_meta(meta_path: Path) -> dict[str, Any] | None:
        if not meta_path.exists():
            return None
        try:
            raw = read_regular(meta_path, MAX_LOCK_META_BYTES, nofollow=True)
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else None
        except (HerdrHandoffError, UnicodeDecodeError, ValueError, OSError):
            return None

    @contextlib.contextmanager
    def pane_lock(self, pane_id: str):
        """Acquire a non-blocking per-pane flock on an untouched lock inode; publish diagnostic
        metadata atomically in a sibling `.meta.json` file (Rule 6).
        """
        locks_dir = self.state_dir / "locks"
        locks_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        stem = _safe_lock_stem(pane_id)
        lock_path = locks_dir / (stem + ".lock")
        meta_path = locks_dir / (stem + ".meta.json")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            fd = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise HerdrHandoffError(
                f"cannot open per-pane lockfile {lock_path}: {exc.strerror or type(exc).__name__}",
                code="lock_error",
                exit_code=EXIT_ERROR,
            ) from None
        stale_recovered = False
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                raise HerdrHandoffError(
                    f"per-pane lockfile is not a regular file: {lock_path}",
                    code="lock_error",
                    exit_code=EXIT_ERROR,
                )
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                holder = ""
                prev = self._read_lock_meta(meta_path)
                if prev is not None:
                    holder = f" (pid={prev.get('pid')}, acquired_at={prev.get('acquired_at')})"
                raise HerdrHandoffError(
                    f"another Herdr handoff is already in progress for pane {pane_id}{holder}; refusing duplicate launch",
                    code="handoff_in_progress",
                    exit_code=EXIT_REFUSED,
                ) from None

            # Advisory flock acquired on untouched lock inode. Check sibling metadata for dead-PID recovery.
            prev = self._read_lock_meta(meta_path)
            if prev is not None:
                prev_pid = prev.get("pid")
                if isinstance(prev_pid, int) and prev_pid != os.getpid() and not _pid_alive(prev_pid):
                    stale_recovered = True
            elif meta_path.exists():
                stale_recovered = True

            meta_bytes = (
                json.dumps(
                    {"pid": os.getpid(), "pane_id": pane_id, "acquired_at": _utc_now()},
                    sort_keys=True,
                ).encode("utf-8")
                + b"\n"
            )
            write_atomic(meta_path, meta_bytes, mode=0o600)
            yield stale_recovered
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)

    def status(self, record_path: Path) -> dict[str, Any]:
        """Inspect a saved Herdr handoff record without mutating or calling Herdr."""
        raw = read_regular(record_path, MAX_RECORD_BYTES, nofollow=True)
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise HerdrHandoffError(
                f"malformed handoff record JSON: {record_path}",
                code="invalid_record",
                exit_code=EXIT_USAGE,
            ) from None
        if not isinstance(record, dict) or record.get("schema_version") != SCHEMA_VERSION:
            raise HerdrHandoffError(
                f"unsupported or invalid handoff record schema: {record_path}",
                code="invalid_record",
                exit_code=EXIT_USAGE,
            )
        return record

    def handoff(
        self,
        *,
        checkpoint: Path,
        tier1: Path,
        kind: str = "claude",
        model: str | None = None,
        effort: str | None = None,
        mode: str | None = None,
        cwd: Path | None = None,
        title: str | None = None,
        name: str | None = None,
        focus: bool = False,
        start_timeout_ms: int = DEFAULT_START_TIMEOUT_MS,
        prompt_timeout_ms: int = DEFAULT_PROMPT_TIMEOUT_MS,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Preflight, lock, preserve checkpoint, launch Herdr successor, and persist record."""
        # 1. Strict caller detection BEFORE any file/herdr mutation
        env_pane_id = self.check_caller_env()

        # 2. Validate all arguments BEFORE touching Herdr layout
        kind = validate_kind(kind)
        model = validate_model(model)
        effort = validate_effort(kind, effort)
        mode = validate_mode(kind, mode)
        start_timeout_ms = validate_timeout_ms(start_timeout_ms, flag="--start-timeout")
        prompt_timeout_ms = validate_timeout_ms(prompt_timeout_ms, flag="--prompt-timeout")
        checkpoint_abs, checkpoint_bytes, checkpoint_sha = validate_checkpoint(checkpoint)
        tier1_abs = validate_tier1(tier1)
        cwd_abs = validate_cwd(cwd)
        head = self.git_head(cwd_abs)

        handoff_id = secrets.token_hex(8)
        agent_name = validate_agent_name(name, token=handoff_id)
        tab_label = validate_title(title, cwd=cwd_abs, kind=kind)
        native_args = build_native_args(kind, model=model, effort=effort, mode=mode)
        baton_prompt = build_baton_prompt(kind, tier1_abs)

        # 3. Verify live Herdr binary, calling pane, and independent process-tree ancestry
        herdr_bin = self.resolve_herdr_bin()
        current_pane = self.verify_current_pane(herdr_bin, env_pane_id)
        pred_pane_id = current_pane["pane_id"]
        workspace_id = current_pane["workspace_id"]
        pred_tab_id = current_pane.get("tab_id")
        pred_shell_pid = current_pane["shell_pid"]

        focus_flag = "--focus" if focus else "--no-focus"
        tab_create_args = [
            "tab",
            "create",
            "--workspace",
            workspace_id,
            "--cwd",
            cwd_abs,
            "--label",
            tab_label,
            focus_flag,
        ]
        # Herdr v0.9.5 rejects `--timeout` on `herdr agent prompt` unless `--wait` is also passed.
        # Single non-waiting submission omits `--timeout` from Herdr argv and enforces
        # `--prompt-timeout` via Python's subprocess timeout instead.
        prompt_args = [
            "agent",
            "prompt",
            agent_name,
            baton_prompt,
        ]

        if dry_run:
            return {
                "schema_version": SCHEMA_VERSION,
                "handoff_id": handoff_id,
                "created_at": _utc_now(),
                "status": "dry-run",
                "predecessor_pane_id": pred_pane_id,
                "predecessor_tab_id": pred_tab_id,
                "predecessor_shell_pid": pred_shell_pid,
                "workspace_id": workspace_id,
                "cwd": cwd_abs,
                "head": head,
                "kind": kind,
                "model": model,
                "effort": effort,
                "mode": mode,
                "tab_label": tab_label,
                "successor_tab_id": None,
                "successor_pane_id": None,
                "successor_agent_name": agent_name,
                "checkpoint_path": checkpoint_abs,
                "checkpoint_sha256": checkpoint_sha,
                "tier1_path": tier1_abs,
                "baton_prompt": baton_prompt,
                "predecessor_preserved": True,
                "planned_commands": {
                    "tab_create": [herdr_bin, *tab_create_args],
                    "agent_start": [
                        herdr_bin,
                        "agent",
                        "start",
                        agent_name,
                        "--kind",
                        kind,
                        "--pane",
                        "<new_pane_id>",
                        "--timeout",
                        str(start_timeout_ms),
                        "--",
                        *native_args,
                    ],
                    "agent_prompt": [herdr_bin, *prompt_args],
                },
            }

        # 4. Acquire per-pane lock, preserve checkpoint, write durable intent, and launch
        with self.pane_lock(pred_pane_id) as stale_recovered:
            checkpoints_dir = self.state_dir / "checkpoints"
            preserved_path = checkpoints_dir / f"{handoff_id}.checkpoint.md"
            write_atomic(preserved_path, checkpoint_bytes, mode=0o600)

            record_path = self.state_dir / f"handoff-{handoff_id}.json"
            record: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "handoff_id": handoff_id,
                "created_at": _utc_now(),
                "completed_at": None,
                "status": "launching",
                "predecessor_pane_id": pred_pane_id,
                "predecessor_tab_id": pred_tab_id,
                "predecessor_shell_pid": pred_shell_pid,
                "workspace_id": workspace_id,
                "cwd": cwd_abs,
                "head": head,
                "kind": kind,
                "model": model,
                "effort": effort,
                "mode": mode,
                "tab_label": tab_label,
                "successor_tab_id": None,
                "successor_pane_id": None,
                "successor_agent_name": agent_name,
                "checkpoint_path": checkpoint_abs,
                "preserved_checkpoint_path": str(preserved_path),
                "checkpoint_sha256": checkpoint_sha,
                "tier1_path": tier1_abs,
                "baton_prompt": baton_prompt,
                "record_path": str(record_path),
                "predecessor_preserved": True,
                "stale_lock_recovered": stale_recovered,
            }
            write_atomic(record_path, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"), mode=0o600)

            def fail_record(stage: str, err: HerdrHandoffError, *, prompt_uncertain: bool = False) -> dict[str, Any]:
                record["status"] = "failed"
                record["completed_at"] = _utc_now()
                record["failed_stage"] = stage
                record["error"] = {
                    "code": err.code,
                    "message": bounded(str(err), MESSAGE_LIMIT),
                    "detail": err.detail,
                }
                if prompt_uncertain:
                    record["prompt_delivery_uncertain"] = True
                write_atomic(
                    record_path,
                    (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"),
                    mode=0o600,
                )
                return record

            # Step 1: Create new tab in the current workspace
            try:
                tab_resp = self.run_herdr(herdr_bin, tab_create_args, timeout_s=PROBE_TIMEOUT_S)
                tab_result = tab_resp.get("result") if isinstance(tab_resp.get("result"), dict) else {}
                tab_obj = tab_result.get("tab") if isinstance(tab_result.get("tab"), dict) else {}
                root_pane_obj = tab_result.get("root_pane") if isinstance(tab_result.get("root_pane"), dict) else {}
                succ_tab_id = tab_obj.get("tab_id")
                succ_pane_id = root_pane_obj.get("pane_id")
                if (
                    not isinstance(succ_tab_id, str)
                    or TAB_ID_RE.fullmatch(succ_tab_id) is None
                    or not isinstance(succ_pane_id, str)
                    or PANE_ID_RE.fullmatch(succ_pane_id) is None
                ):
                    raise HerdrHandoffError(
                        "herdr tab create returned no valid tab_id / root_pane.pane_id",
                        code="invalid_tab_create_response",
                        exit_code=EXIT_ERROR,
                    )
                if succ_pane_id == pred_pane_id:
                    raise HerdrHandoffError(
                        f"herdr tab create returned predecessor pane {pred_pane_id}; refusing to target predecessor",
                        code="successor_equals_predecessor",
                        exit_code=EXIT_ERROR,
                    )
            except HerdrHandoffError as exc:
                return fail_record("tab_create", exc)

            record["successor_tab_id"] = succ_tab_id
            record["successor_pane_id"] = succ_pane_id
            write_atomic(record_path, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"), mode=0o600)

            # Step 2: Start real interactive agent TUI in the new pane (never blind-retry, never close predecessor)
            start_args = [
                "agent",
                "start",
                agent_name,
                "--kind",
                kind,
                "--pane",
                succ_pane_id,
                "--timeout",
                str(start_timeout_ms),
                "--",
                *native_args,
            ]
            try:
                self.run_herdr(herdr_bin, start_args, timeout_s=(start_timeout_ms / 1000.0) + 15.0)
            except HerdrHandoffError as exc:
                return fail_record("agent_start", exc)

            # Step 3: Submit baton prompt ONCE (no `--timeout` flag on non-waiting Herdr prompt;
            # never blind-retry, never raw send-keys / pane run)
            try:
                self.run_herdr(herdr_bin, prompt_args, timeout_s=prompt_timeout_ms / 1000.0)
            except HerdrCommandError as exc:
                uncertain = (exc.outcome == "unknown") or (exc.herdr_code == "agent_prompt_stalled")
                return fail_record("agent_prompt", exc, prompt_uncertain=uncertain)
            except HerdrHandoffError as exc:
                return fail_record("agent_prompt", exc, prompt_uncertain=True)

            # Step 4: Mark launched and persist
            record["status"] = "launched"
            record["completed_at"] = _utc_now()
            write_atomic(record_path, (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"), mode=0o600)
            return record
