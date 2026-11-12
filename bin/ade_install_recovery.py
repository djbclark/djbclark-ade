"""Installer crash/orphan recovery (W18, 2026-11-12).

``scan`` is read-only and is what ``ade-install doctor`` reports. ``recover`` is the
one explicit repair (``ade-install recover --yes``); nothing here runs at the next
install, apply or doctor. Owners are identified by PID plus process start time
(``ade_install.owner_status``), never by a name pattern. Ledger evidence is kept: an
orphaned ``pending`` entry is re-labelled ``interrupted`` with its original fields
intact, half-written temp files are moved to ``recovered/``, and every action is
appended first to ``recovery-evidence.jsonl``. Refuses to repair as root.
"""
from __future__ import annotations

import fcntl
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ade_install as ai

TEMP_MIN_AGE_S = 300  # no live writer holds a temp this long: gates pre-W18 temps and pid-reuse verdicts
QUARANTINE_DIR = "recovered"
PYTHON_RECOVER_COMMAND = "bin/ade-install python --recover --yes"
RECOVER_COMMAND = "bin/ade-install recover --yes"

_NEW_TEMP = re.compile(r"^(?P<base>.+)\.(?P<pid>\d+)\.(?P<tok>[0-9a-f]{8}|unknown)\.[A-Za-z0-9_]+\.tmp$")
_LEGACY_TEMP = re.compile(r"^(?P<base>.+)\.[A-Za-z0-9_]{8}$")
_TARGET_NAMES = frozenset({"ledger.json", ai.HERMES_CHOICE_FILE})


@dataclass(frozen=True)
class Finding:
    kind: str     # ledger-entry | lock-holder | temp-file | python-pending | ledger
    id: str
    status: str   # active | orphaned | unverifiable | corrupt
    detail: str
    repair: str | None = None  # command that repairs it, if any


def lock_state(state_dir: Path) -> str:
    """``absent`` | ``free`` | ``held`` (non-blocking probe; never creates the file)."""
    try:
        fd = os.open(state_dir / "ledger.lock", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "held"  # a link or unopenable file: unverifiable, never "free"
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return "held"
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return "held"  # EAGAIN/EACCES: another open file description holds it
    finally:
        os.close(fd)
    return "free"


def _read_lock_holder(state_dir: Path) -> dict[str, Any] | None:
    raw = ai.read_small_file(state_dir / "ledger.lock")
    return None if raw is None else ai.parse_lock_holder(raw)


def _describe(owner: Any) -> str:
    if isinstance(owner, dict):
        return f"pid {owner.get('pid')} start {owner.get('start')}"
    return "no owner recorded"


def _scan_ledger(state_dir: Path, lock: str, python_sentinel: bool) -> list[Finding]:
    path = state_dir / "ledger.json"
    if not path.is_file():
        return []
    try:
        ledger = ai.load_ledger(state_dir)
    except ai.InstallError as error:
        return [Finding("ledger", "ledger.json", "corrupt", f"{error}; recovery never rewrites an unreadable ledger", None)]
    out: list[Finding] = []
    for cid, entry in sorted(ledger["entries"].items()):
        if not isinstance(entry, dict) or entry.get("status") != "pending":
            continue
        if cid == ai.PYTHON_LEDGER_ID and python_sentinel:
            continue  # the sentinel finding owns it (verified by `python --recover`)
        owner = entry.get("owner")
        if isinstance(owner, dict):
            state = ai.owner_status(owner)
            if state in ("gone", "reused"):
                why = "process gone" if state == "gone" else "pid reused by a later process"
                out.append(Finding("ledger-entry", cid, "orphaned",
                                   f"pending since {entry.get('at')}; owner {_describe(owner)}: {why}; outcome unknown",
                                   RECOVER_COMMAND))
            else:
                out.append(Finding("ledger-entry", cid, "active", f"owner {_describe(owner)} is running", None))
        elif lock == "held":
            out.append(Finding("ledger-entry", cid, "unverifiable",
                               "no owner recorded (pre-W18 entry) and the install lock is held by a running installer", None))
        else:
            out.append(Finding("ledger-entry", cid, "orphaned",
                               f"pending since {entry.get('at')}; no owner recorded (pre-W18 entry) and the install lock is free; outcome unknown",
                               RECOVER_COMMAND))
    return out


def _scan_lock(state_dir: Path, lock: str) -> list[Finding]:
    holder = _read_lock_holder(state_dir)
    if holder is None:
        return []
    state = ai.owner_status(holder)
    if lock == "free" and state in ("gone", "reused"):
        return [Finding("lock-holder", "ledger.lock", "orphaned",
                        f"holder {_describe(holder)} was killed while holding the install lock (the kernel already released it)",
                        RECOVER_COMMAND)]
    if lock == "held" and state in ("gone", "reused"):
        return [Finding("lock-holder", "ledger.lock", "unverifiable",
                        f"lock is held but its recorded holder {_describe(holder)} is gone; not breaking it", None)]
    return [Finding("lock-holder", "ledger.lock", "active", f"held by {_describe(holder)}", None)]


def _scan_temps(state_dir: Path, now: float) -> list[Finding]:
    out: list[Finding] = []
    try:
        names = sorted(os.listdir(state_dir))
    except OSError:
        return out
    for name in names:
        try:
            st = os.lstat(state_dir / name)
        except OSError:
            continue
        if not stat.S_ISREG(st.st_mode):
            continue
        new = _NEW_TEMP.match(name)
        if new:
            pid = int(new.group("pid"))
            tok = new.group("tok")
            age = now - st.st_mtime
            if not ai._pid_alive(pid):
                status, why = "orphaned", "writer process gone"
            else:
                start = ai.process_start_time(pid)
                if start is None or tok == ai.UNKNOWN_START_TOKEN:
                    status, why = "active", "writer pid is running (start unverifiable)"
                elif ai._start_token(start) == tok:
                    status, why = "active", "writer is running"
                elif age >= TEMP_MIN_AGE_S:
                    status, why = "orphaned", "writer pid reused by a later process"
                else:
                    status, why = "active", "writer start differs but the file is younger than %ds; may be in flight" % TEMP_MIN_AGE_S
        else:
            legacy = _LEGACY_TEMP.match(name)
            if not legacy or legacy.group("base") not in _TARGET_NAMES:
                continue
            age = now - st.st_mtime
            if age >= TEMP_MIN_AGE_S:
                status, why = "orphaned", f"pre-W18 temp file, {int(age)}s old, no owner recorded"
            else:
                status, why = "active", "pre-W18 temp file younger than %ds; may be in flight" % TEMP_MIN_AGE_S
        out.append(Finding("temp-file", name, status, f"{st.st_size} bytes; {why}; the target was never replaced by it",
                           RECOVER_COMMAND if status == "orphaned" else None))
    return out


def _scan_python(state_dir: Path) -> list[Finding]:
    fields = ai.read_python_pending(state_dir)
    if fields is None:
        return []
    state = ai.sentinel_owner_status(fields)
    if state in ("gone", "reused", "unknown"):
        return [Finding("python-pending", ai.PYTHON_PENDING, "orphaned",
                        f"Python acquisition by pid {fields.get('pid')} started {fields.get('started')} did not finish; "
                        "verifying it needs the interpreter, so it is repaired only by the W17 command",
                        PYTHON_RECOVER_COMMAND)]
    return [Finding("python-pending", ai.PYTHON_PENDING, "active", f"acquisition by pid {fields.get('pid')} is running", None)]


def scan(state_dir: Path, *, now: float | None = None) -> list[Finding]:
    """Read-only. Never creates, locks (beyond a momentary probe) or writes anything."""
    if not state_dir.is_dir():
        return []
    lock = lock_state(state_dir)
    sentinel = ai.read_python_pending(state_dir) is not None
    return (_scan_lock(state_dir, lock) + _scan_ledger(state_dir, lock, sentinel)
            + _scan_temps(state_dir, time.time() if now is None else now) + _scan_python(state_dir))


def safe(text: str) -> str:
    """Escape control characters: state-dir file names are untrusted and reach the terminal."""
    return text.encode("unicode_escape").decode("ascii")


def observations(state_dir: Path, *, now: float | None = None) -> list[ai.Observation]:
    findings = scan(state_dir, now=now)
    if not findings:
        return [ai.Observation("install-state", str(state_dir), "ok", "no orphaned ledger entries, stale locks or half-written artifacts")]
    return [
        ai.Observation("install-state", f"{f.kind}/{safe(f.id)}", f.status,
                       safe(f.detail) + (f"; repair (explicit, never automatic): {f.repair}" if f.repair else ""))
        for f in findings
    ]


def failing(obs: list[ai.Observation]) -> int:
    return sum(1 for o in obs if o.kind == "install-state" and o.status in ("orphaned", "corrupt"))


def _quarantine(state_dir: Path, name: str, stamp: str) -> str:
    target_dir = state_dir / QUARANTINE_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    st = os.lstat(target_dir)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid():
        raise ai.InstallError(f"{target_dir}: must be a directory you own (not a link); refusing to move files into it")
    target = target_dir / f"{stamp}-{name}"
    os.rename(state_dir / name, target)
    return str(target)


def recover(state_dir: Path, *, yes: bool = False, euid: int | None = None, now: float | None = None) -> tuple[dict[str, Any], int]:
    """Dry-run by default. ``yes`` repairs under the install lock (never waits for it)."""
    report: dict[str, Any] = {
        "mode": "yes" if yes else "dry-run", "state_dir": str(state_dir), "status": "dry-run",
        "note": "user-scoped; ledger evidence is relabelled, never deleted; the Python sentinel is left to `python --recover`",
    }
    findings = scan(state_dir, now=now)
    report["findings"] = [f.__dict__ for f in findings]
    report["deferred"] = [f.__dict__ for f in findings if f.kind == "python-pending" and f.status == "orphaned"]
    actionable = [f for f in findings if f.status == "orphaned" and f.kind != "python-pending"]
    if not yes:
        report["would_repair"] = [f"{f.kind}/{f.id}" for f in actionable]
        report["status"] = "dry-run" if actionable else "nothing-to-recover"
        return report, 0
    if (os.geteuid() if euid is None else euid) == 0:
        report.update(status="refused-root", reason="refusing to repair as root: the install state belongs to the target user. Nothing changed")
        return report, 1
    if not state_dir.is_dir():
        report["status"] = "nothing-to-recover"
        return report, 0
    try:
        with ai.install_ledger_lock(state_dir, wait=False) as superseded:
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            repaired: list[str] = []
            if superseded is not None:
                repaired.append("lock-holder/ledger.lock")  # evidence appended by the lock before it was superseded
            locked = scan_locked(state_dir, now=now)
            orphans = [f for f in locked if f.kind == "ledger-entry" and f.status == "orphaned"]
            if orphans:
                ledger = ai.load_ledger(state_dir)
                for f in orphans:
                    entry = ledger["entries"][f.id]
                    ai.append_recovery_evidence(state_dir, {"event": "ledger-entry-interrupted", "id": f.id, "entry": entry, "finding": f.detail})
                    ledger["entries"][f.id] = {
                        **entry, "status": "interrupted", "previous_status": "pending", "interrupted_at": stamp,
                        "interrupted_reason": f.detail + "; verify with `ade-install doctor` or rerun apply",
                    }
                    repaired.append(f"{f.kind}/{f.id}")
                ai.save_ledger(state_dir, ledger)
            for f in (x for x in locked if x.kind == "temp-file" and x.status == "orphaned"):
                ai.append_recovery_evidence(state_dir, {"event": "temp-file-quarantined", "name": f.id, "finding": f.detail})
                _quarantine(state_dir, f.id, stamp)
                repaired.append(f"{f.kind}/{f.id}")
    except ai.InstallError as error:
        report.update(status="lock-busy" if "is held by a running" in str(error) else "refused", reason=str(error) + ". Remaining repairs not attempted")
        return report, 1
    report["repaired"] = repaired
    report["status"] = "recovered" if repaired else "nothing-to-recover"
    return report, 0


def scan_locked(state_dir: Path, *, now: float | None = None) -> list[Finding]:
    """Rescan while this process holds the install lock (the probe would see our own lock as held)."""
    sentinel = ai.read_python_pending(state_dir) is not None
    return _scan_ledger(state_dir, "free", sentinel) + _scan_temps(state_dir, time.time() if now is None else now)
