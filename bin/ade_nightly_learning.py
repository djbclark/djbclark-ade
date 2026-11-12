"""Offline nightly-learning admission primitives; no runner or adoption authority."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath


def natural(value, *, positive=False):
    if type(value) is not int or value < (1 if positive else 0):
        raise ValueError("expected integer token count")
    return value


def validate_ledger(data):
    if not isinstance(data, dict) or set(data) != {"schema_version", "limit", "reservations"}:
        raise ValueError("invalid budget ledger")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("unsupported budget ledger")
    natural(data["limit"], positive=True)
    if not isinstance(data["reservations"], dict):
        raise ValueError("invalid reservations")
    for call_id, tokens in data["reservations"].items():
        if not isinstance(call_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", call_id):
            raise ValueError("invalid call id")
        natural(tokens, positive=True)
    if sum(data["reservations"].values()) > data["limit"]:
        raise ValueError("ledger exceeds budget")
    return data


@contextmanager
def locked(path):
    # Stable sidecar inode: replacing the ledger must not replace its lock.
    with path.with_name(path.name + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def atomic_write(path, data):
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(data, out, sort_keys=True)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def init_budget(path, limit):
    natural(limit, positive=True)
    with locked(path):
        if path.exists():
            raise ValueError("budget already exists; cannot reset or increase it")
        atomic_write(path, {"schema_version": 1, "limit": limit, "reservations": {}})


def reserve(path, call_id, tokens):
    """Charge a complete worst-case call bound before returning admission."""
    natural(tokens, positive=True)
    if not isinstance(call_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", call_id):
        raise ValueError("invalid call id")
    with locked(path):
        data = validate_ledger(json.loads(path.read_text(encoding="utf-8")))
        used = sum(data["reservations"].values())
        if call_id in data["reservations"]:
            return {"admitted": False, "reason": "duplicate-call", "remaining": data["limit"] - used}
        if tokens > data["limit"] - used:
            return {"admitted": False, "reason": "budget-exhausted", "remaining": data["limit"] - used}
        data["reservations"][call_id] = tokens
        atomic_write(path, data)
        return {"admitted": True, "reason": "reserved", "remaining": data["limit"] - used - tokens}


def classify(proposal):
    """Classify a trusted review manifest, never trust a proposal's self-label."""
    if not isinstance(proposal, dict) or set(proposal) != {"changes", "injection"}:
        raise ValueError("expected changes and injection")
    changes = proposal["changes"]
    if not isinstance(changes, list) or not changes:
        raise ValueError("expected nonempty changes")
    injection = proposal["injection"]
    if not isinstance(injection, str) or injection not in {"clear", "suspected", "unknown"}:
        raise ValueError("invalid injection assessment")
    standing = False
    local = True
    seen = set()
    for change in changes:
        if not isinstance(change, dict) or set(change) != {"path", "effect"}:
            raise ValueError("expected path and reviewed effect")
        path, effect = change["path"], change["effect"]
        if not isinstance(path, str) or not path or "\\" in path or any(ord(c) < 32 for c in path):
            raise ValueError("invalid repository path")
        parts = path.split("/")
        if PurePosixPath(path).is_absolute() or any(p in {"", ".", ".."} for p in parts) or path in seen:
            raise ValueError("noncanonical or duplicate repository path")
        seen.add(path)
        if not isinstance(effect, str) or effect not in {"skill-local", "standing-order", "other", "unknown"}:
            raise ValueError("invalid reviewed effect")
        policy_path = parts[-1].upper() in {"AGENTS.MD", "CLAUDE.MD", "GEMINI.MD"} or path == "cursor/home-agents.mdc"
        standing |= policy_path or effect == "standing-order"
        local &= len(parts) >= 3 and parts[0] == "skills" and effect == "skill-local" and not policy_path
    kind = "standing-order" if standing else "skill-only" if local else "other"
    return {
        "schema_version": 1, "classification": kind,
        "proposal_allowed": injection == "clear",
        "blocked_reason": None if injection == "clear" else "injection-" + injection,
        "reviewed_adoption_candidate": kind == "skill-only" and injection == "clear",
        "adoption_authorized": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("ledger", type=Path)
    init.add_argument("--limit", type=int, required=True)
    charge = commands.add_parser("reserve")
    charge.add_argument("ledger", type=Path)
    charge.add_argument("--call-id", required=True)
    charge.add_argument("--tokens", type=int, required=True)
    proposal = commands.add_parser("classify")
    proposal.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            init_budget(args.ledger, args.limit)
            result = {"initialized": True}
        elif args.command == "reserve":
            result = reserve(args.ledger, args.call_id, args.tokens)
        else:
            result = classify(json.loads(args.manifest.read_text(encoding="utf-8")))
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("admitted", result.get("proposal_allowed", True)) else 3
    except (OSError, ValueError, TypeError, RecursionError):
        # No payload, filenames or provider text in error output.
        print(json.dumps({"error": "invalid or unavailable admission input", "adoption_authorized": False}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
