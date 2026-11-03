"""Private Pi bridge client; never falls back to a host or writes a transcript."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid


def marked() -> bool:
    # Presence, not truthiness: even incomplete Pi identity must fail closed.
    return any(k in os.environ for k in ("PI_SESSION_ID", "PI_SESSION_FILE")) or (
        os.environ.get("PI_CODING_AGENT") == "true" or os.environ.get("AI_AGENT") == "pi"
    )


def child_backend() -> tuple[str, int, str] | None:
    """Allow only a positively identified child before the first runtime barrier.

    Pi markers are inherited. They may yield to an OMP PID registration or a
    native OpenCode tool scope at the nearest owning process, never to a host.
    Unknown Node/Bun wrappers and failed identity checks remain fail-closed.
    This is same-user coordination, not authentication against that user.
    """
    if not marked():
        return None
    try:
        for pid, name in ancestors():
            if (root() / f"{pid}.json").exists():
                return None  # Pi owns this runtime, even if its record is invalid.
            if name == "omp" and os.environ.get("OMPCODE") == "1":
                reg = json.loads((root().parent / "omp" / f"{pid}.json").read_text())
                sid = reg.get("session_id") if isinstance(reg, dict) else None
                if isinstance(sid, str) and re.fullmatch(r"[0-9A-Za-z-]+", sid):
                    return "omp", pid, sid
                return None
            if name == "opencode":
                sid = os.environ.get("ADE_OPENCODE_SESSION_ID", "")
                directory = os.environ.get("ADE_OPENCODE_DIRECTORY", "")
                if (re.fullmatch(r"ses_[A-Za-z0-9]+", sid) and Path(directory).is_absolute()
                        and os.environ.get("OPENCODE_SESSION_ID", sid) == sid):
                    return "opencode", pid, sid
                return None
            if name in RUNTIMES:
                return None
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def selected() -> bool:
    return marked() and child_backend() is None


RUNTIMES = {"pi", "omp", "node", "bun", "claude", "codex", "cursor-agent", "grok", "opencode"}


def root() -> Path:
    return Path(os.environ.get("AUTORENAME_STATE_DIR", Path.home() / ".local/state/autorename")) / "pi"


def ancestors() -> list[tuple[int, str]]:
    result = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,comm="],
                            capture_output=True, text=True, timeout=10, check=True)
    rows = {}
    for line in result.stdout.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
            rows[int(fields[0])] = (int(fields[1]), Path(fields[2]).name)
    chain = []
    pid = os.getppid()
    for _ in range(64):
        if pid <= 1 or pid not in rows:
            break
        parent, name = rows[pid]
        chain.append((pid, name))
        pid = parent
    return chain


def registration(sid: str | None = None) -> dict:
    """Require shell identity AND the closest runtime's live registration.

    Unregistered Node/Bun processes are barriers too: they may be a nested Pi
    or another JS agent inheriting its parent's variables. False negatives are
    preferable to renaming/compacting a parent. Explicit IDs never bypass this.
    """
    session_id = os.environ.get("PI_SESSION_ID")
    if not session_id or (sid is not None and sid != session_id):
        raise ValueError("Pi session identity missing or explicit ID is not this session")
    nearest = None
    for pid, name in ancestors():
        file = root() / f"{pid}.json"
        if file.exists():
            reg = json.loads(file.read_text(encoding="utf-8"))
            if (not isinstance(reg, dict) or reg.get("version") != 1
                    or reg.get("pid") != pid or reg.get("session_id") != session_id
                    or reg.get("session_file") != (os.environ.get("PI_SESSION_FILE") or None)
                    or not re.fullmatch(r"[a-f0-9]{32}", str(reg.get("instance", "")))):
                raise ValueError("Pi bridge identity mismatch")
            return reg
        if name in RUNTIMES:
            nearest = name
            break
    omp_dir = Path(__file__).resolve().parent
    if nearest == "omp" or (nearest is None and os.environ.get("OMPCODE") == "1"):
        raise ValueError(f"this omp has not registered with the autorename bridge; link {omp_dir / 'omp-bridge.ts'}"
                         " into ~/.omp/agent/extensions/ and restart omp")
    raise ValueError(f"no owning Pi bridge; load {omp_dir / 'pi-bridge.ts'} in Pi")


def request(reg: dict, action: str, **fields) -> dict:
    nonce = uuid.uuid4().hex
    directory = root() / reg["instance"]
    target = directory / f"{nonce}.request.json"
    result = directory / f"{nonce}.result.json"
    tmp = directory / f".{nonce}.tmp"
    body = {**fields, "action": action, "nonce": nonce, "instance": reg["instance"],
            "session_id": reg["session_id"], "session_file": reg.get("session_file"),
            "expires": int(time.time() * 1000) + 15000}
    with tmp.open("x", encoding="utf-8") as fh:
        os.chmod(tmp, 0o600)
        json.dump(body, fh)
    tmp.replace(target)
    try:
        deadline = time.monotonic() + 16
        while time.monotonic() < deadline:
            if result.exists():
                data = json.loads(result.read_text(encoding="utf-8"))
                if (not isinstance(data, dict) or data.get("nonce") != nonce
                        or data.get("instance") != reg["instance"]):
                    raise ValueError("Pi bridge receipt identity mismatch")
                if data.get("accepted") is not True:
                    raise ValueError(data.get("error") or "Pi refused request")
                return data
            time.sleep(0.1)
        raise ValueError("Pi bridge did not acknowledge; outcome unknown, do not retry automatically")
    finally:
        target.unlink(missing_ok=True)
        result.unlink(missing_ok=True)


def main() -> int:
    # Internal self-slash selection probe; never admits a mutation or host route.
    if sys.argv[1:] == ["--backend"]:
        child = child_backend()
        print(child[0] if child else "pi")
        return 0
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("command", help="/compact [focus] only; all other commands fail closed")
    args = ap.parse_args()
    if os.environ.get("ACP_RUN_AGENT") == "1":
        print("self-slash: dispatched slice cannot run Pi compaction", file=sys.stderr)
        return 9
    command, _, focus = args.command.strip().partition(" ")
    if command != "/compact":
        print("self-slash: native Pi supports /compact [focus] only; no host fallback", file=sys.stderr)
        return 2
    try:
        reg = registration()
        model = {key: os.environ.get(env) for key, env in (
            ("provider", "PI_PROVIDER"), ("model", "PI_MODEL"), ("thinking", "PI_REASONING_LEVEL"))}
        if any(not value or reg.get(key) != value for key, value in model.items()):
            raise ValueError("Pi selected model/reasoning identity missing or changed")
        if args.dry_run:
            print("self-slash: dry run; native Pi identity verified; no request written; "
                  "external compaction disabled: active main-editor focus cannot be proven")
            return 0
        data = request(reg, "compact", focus=focus, **model)
        print("self-slash: " + data["status"] + "; completion is in Pi bridge registration (compact_status)")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"self-slash: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
