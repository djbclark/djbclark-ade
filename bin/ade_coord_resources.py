"""Claim-attached process evidence. Unknown launches block transfer; idle is not evidence.

This ledger covers explicitly managed jobs. A caller must also retire the writer,
inspect workspace users, and reconcile external operations before issuing a
quiescence certificate. Neither a PID nor this ledger fences arbitrary writes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from typing import Callable


class ResourceError(RuntimeError):
    pass


def process_identity(pid: int) -> dict | None:
    """Return birth identity, not a command line. Inspection failure is unknown."""
    if type(pid) is not int or pid <= 0:
        raise ResourceError("invalid process id")
    if sys.platform.startswith("linux"):
        root = Path("/proc")
        try:
            stat = (root / str(pid) / "stat").read_text()
            fields = stat.rsplit(") ", 1)[1].split()
            boot = (root / "sys/kernel/random/boot_id").read_text().strip()
            return {"pid": pid, "birth": fields[19], "boot": boot,
                    "pgid": int(fields[2]), "state": fields[0]}
        except FileNotFoundError:
            return None
        except (OSError, IndexError, ValueError) as exc:
            raise ResourceError("process inspection unavailable") from exc
    # ps is a read-only census. Full argv/env are deliberately never collected.
    try:
        p = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "lstart=,pgid=,stat="],
                           capture_output=True, text=True, timeout=10)
        if p.returncode == 1 and not p.stdout.strip():
            return None
        if p.returncode:
            raise ResourceError("process inspection unavailable")
        fields = p.stdout.split()
        if len(fields) != 7:
            raise ResourceError("process identity unreadable")
        boot = subprocess.run(["/usr/sbin/sysctl", "-n", "kern.boottime"],
                              capture_output=True, text=True, timeout=10, check=True).stdout.strip()
        return {"pid": pid, "birth": " ".join(fields[:5]), "boot": boot,
                "pgid": int(fields[5]), "state": fields[6]}
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ResourceError("process inspection unavailable") from exc


def group_members(pgid: int) -> list[int]:
    try:
        p = subprocess.run(["/bin/ps", "-axo", "pid=,pgid=,stat="],
                           capture_output=True, text=True, timeout=10, check=True)
        members = []
        for line in p.stdout.splitlines():
            pid, group, state = line.split()
            if int(group) == pgid:
                # Zombies cannot write, but retain them as blockers until reaped.
                members.append(int(pid))
        return sorted(members)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise ResourceError("process group inspection unavailable") from exc


def same_process(left, right):
    """Scheduling state is mutable; PID, birth, boot and group bind identity."""
    return bool(left and right and all(left.get(k) == right.get(k) for k in ("pid", "birth", "boot", "pgid")))


class Resources:
    def __init__(self, directory: Path, *, inspect: Callable = process_identity,
                 members: Callable = group_members):
        directory = Path(directory)
        if not directory.is_absolute() or directory.is_symlink():
            raise ResourceError("state directory must be an absolute real directory")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        path = directory / "resources.sqlite3"
        if path.is_symlink():
            raise ResourceError("state database cannot be a symlink")
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA busy_timeout=10000")
        self.db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, claim TEXT NOT NULL, authority TEXT NOT NULL,
            state TEXT NOT NULL, process TEXT, result TEXT, created REAL NOT NULL)""")
        self.db.commit()
        self.inspect, self.members = inspect, members

    def close(self):
        self.db.close()

    @staticmethod
    def encode(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def intent(self, job: str, claim: str, authority: dict):
        if not job or not claim or not isinstance(authority, dict):
            raise ResourceError("job, claim and authority required")
        packed = self.encode(authority)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO jobs VALUES (?,?,?,'START_UNKNOWN',NULL,NULL,?)",
                            (job, claim, packed, time.time()))
            row = self.get(job)
            if row["claim"] != claim or row["authority"] != authority:
                raise ResourceError("immutable job identity conflict")
        return row

    def get(self, job: str):
        row = self.db.execute("SELECT id,claim,authority,state,process,result FROM jobs WHERE id=?",
                              (job,)).fetchone()
        if row is None:
            raise ResourceError("unknown job")
        return {"id": row[0], "claim": row[1], "authority": json.loads(row[2]), "state": row[3],
                "process": json.loads(row[4]) if row[4] else None,
                "result": json.loads(row[5]) if row[5] else None}

    def _cas(self, row, *, state, process=None, result=None):
        changed = self.db.execute(
            "UPDATE jobs SET state=?,process=?,result=? WHERE id=? AND state=? AND process IS ? AND result IS ?",
            (state, self.encode(process) if process is not None else None,
             self.encode(result) if result is not None else None, row["id"], row["state"],
             self.encode(row["process"]) if row["process"] is not None else None,
             self.encode(row["result"]) if row["result"] is not None else None)).rowcount
        if changed != 1:
            raise ResourceError("job changed concurrently; reconcile current state")

    def spawned(self, job: str, pid: int):
        identity = self.inspect(pid)
        if identity is None or identity["pgid"] != pid:
            raise ResourceError("managed job must have its own observed process group")
        with self.db:
            row = self.get(job)
            if row["state"] not in ("START_UNKNOWN", "SPAWN_UNKNOWN") or row["process"] is not None:
                raise ResourceError("job already bound; never retry an uncertain launch")
            self._cas(row, state="RUNNING", process=identity)
        return self.get(job)

    def complete(self, job: str, result: dict):
        row = self.get(job)
        identity = row["process"]
        if not identity or row["state"] not in ("RUNNING", "QUIESCENT"):
            raise ResourceError("unknown launch requires independent reconciliation")
        if same_process(self.inspect(identity["pid"]), identity) or self.members(identity["pgid"]):
            raise ResourceError("job process or group still exists")
        with self.db:
            if row["state"] == "QUIESCENT" and row["result"] != result:
                raise ResourceError("immutable job result conflict")
            self._cas(row, state="QUIESCENT", process=identity, result=result)
        return self.get(job)

    def reconcile_not_started(self, job: str, evidence: dict):
        """Independent evidence is required; absent PID alone is insufficient.

        Consumed spawn permission additionally requires verified no-child evidence
        and a stopped bound launcher, or a recorded Popen OSError. Never re-spawn.
        """
        if not evidence or not isinstance(evidence, dict):
            raise ResourceError("independent launch reconciliation evidence required")
        with self.db:
            row = self.get(job)
            if row["state"] not in ("START_UNKNOWN", "SPAWN_UNKNOWN") or row["process"] is not None:
                raise ResourceError("only unknown unbound launch may be reconciled")
            if row["state"] == "SPAWN_UNKNOWN":
                launch = row["result"] or {}
                launcher = launch.get("launcher")
                if evidence.get("no_child_proven") is not True or not evidence.get("source"):
                    raise ResourceError("consumed launch requires independent no-child proof")
                if not launch.get("popen_failed"):
                    if not launcher or evidence.get("launcher") != launcher or same_process(self.inspect(launcher["pid"]), launcher):
                        raise ResourceError("launcher must be proven stopped before reconciliation")
            self._cas(row, state="NOT_STARTED", result={"evidence": evidence, "launch": row["result"]})
        return self.get(job)

    def quiescence(self, claim: str, authority: dict):
        rows = [self.get(r[0]) for r in self.db.execute("SELECT id FROM jobs WHERE claim=?", (claim,))]
        blockers = []
        for row in rows:
            if row["state"] not in ("QUIESCENT", "NOT_STARTED"):
                blockers.append(row["id"])
                continue
            identity = row["process"]
            if identity and (same_process(self.inspect(identity["pid"]), identity) or self.members(identity["pgid"])):
                blockers.append(row["id"])
        return {"claim": claim, "authority": authority, "jobs_stopped": not blockers,
                "blockers": blockers, "jobs": rows, "scope": "explicitly tracked jobs only"}


def run_job(resources: Resources, *, job: str, claim: str, authority: dict, argv: list[str],
            authorize: Callable, output=None):
    """Caller supplies an ONLINE authority check. A launch is never auto-retried."""
    if not argv or not all(isinstance(x, str) for x in argv):
        raise ResourceError("command argv required")
    authorize(claim, authority)
    prior = resources.intent(job, claim, authority)
    # A repeated intent is ambiguous even when its PID has not been recorded.
    if prior["state"] != "START_UNKNOWN":
        raise ResourceError("job identity already used")
    # Atomically consume launch permission BEFORE spawning. A death in this gap
    # remains unknown and blocks handoff; it must never cause a duplicate spawn.
    with resources.db:
        changed = resources.db.execute("UPDATE jobs SET state='SPAWN_UNKNOWN',result=? WHERE id=? AND state='START_UNKNOWN' AND process IS NULL",
                                       (resources.encode({"launcher": resources.inspect(os.getpid())}), job)).rowcount
    if changed != 1:
        raise ResourceError("job launch already attempted")
    try:
        process = subprocess.Popen(argv, start_new_session=True, stdout=output, stderr=output)
    except OSError:
        # Popen waits/reaps a failed exec before raising. Preserve consumed intent
        # and its no-child evidence for explicit reconciliation; never retry it.
        with resources.db:
            row = resources.get(job)
            if row["state"] == "SPAWN_UNKNOWN" and row["process"] is None:
                resources._cas(row, state="SPAWN_UNKNOWN", result={**(row["result"] or {}), "popen_failed": True})
        raise
    resources.spawned(job, process.pid)
    code = process.wait()
    resources.complete(job, {"exit_code": code})
    return code
