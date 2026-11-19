#!/usr/bin/env python3
"""Finite ADE business operations over private producer-prepared JSON DATA.

Run the retained entry with Python -I -S. The producer owns interpreter/code,
environment, native event, Git/config facts, read/write sets and settlement
authentication. Neither this JSON nor filesystem agreement grants authority.
There is deliberately no Git/process/CLI fallback or input-selected module.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import stat
import sys

# -I omits the script directory; only this fixed retained sibling directory is
# added. No import path comes from stdin, cwd, PYTHONPATH or an operation.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ade_claims as claims  # noqa: E402
import ade_ws_autoname as autoname  # noqa: E402
import ade_ws_names as names  # noqa: E402

MAX_INPUT = 65536
MAX_OUTPUT = 1048576
MAX_CLAIMS = 4096
MAX_DIAGNOSTIC = 256
REQUEST_KEYS = {
    "claim-list": (),
    "claim-new": ("branch", "claimId", "ttlHours", "ownerAgent", "ownerRecord"),
    "claim-bind-owner": ("claimId", "agentId"),
    "claim-release": ("claimId",),
    "claim-install-hooks": (),
    "window-name-decision": ("windowTitle", "firstAgent", "background", "agent"),
}
FACT_KEYS = {
    "claim-list": (), "claim-bind-owner": (), "claim-release": (),
    "claim-new": ("head", "origin", "gitDir"),
    "claim-install-hooks": ("commonDir", "hooksStatus", "hooksOutput"),
    "window-name-decision": ("commonDir",),
}
RECORD_KEYS = frozenset((
    "v", "id", "path", "repo_origin", "branch", "base_sha", "owner", "lead",
    "allow", "role", "purpose", "created_at", "created_by", "state",
    "released_at", "inherited_dirt_patch", "expires_at", "shown_state",
))
# Sanitized old v1 records can omit these fields; omission is preserved.
OPTIONAL_RECORD_KEYS = frozenset((
    "lead", "role", "purpose", "created_by", "released_at", "inherited_dirt_patch",
))


class InvalidRequest(ValueError):
    """Malformed semantic input; no application operation has started."""


def exact(value: object, keys: tuple | set | frozenset) -> dict:
    if type(value) is not dict or set(value) != set(keys):
        raise InvalidRequest("invalid object keys")
    return value


def text(value: object, limit: int, *, nullable: bool = False, allow_nul: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if type(value) is not str or (not allow_nul and "\0" in value):
        raise InvalidRequest("invalid text")
    try:
        if len(value.encode("utf-8")) > limit:
            raise InvalidRequest("text too long")
    except UnicodeError as error:
        raise InvalidRequest("invalid unicode") from error
    return value


def identifier(value: object, *, empty: bool = False, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    text(value, 128)
    if value == "" and empty:
        return
    if not claims.valid_id(value):
        raise InvalidRequest("invalid id")


def canonical_directory(value: object) -> Path:
    text(value, 4096)
    p = Path(value)
    try:
        if not p.is_absolute() or str(p) != value or p.resolve(strict=True) != p or not p.is_dir():
            raise InvalidRequest("noncanonical directory")
    except (OSError, RuntimeError) as error:
        raise InvalidRequest("unavailable directory") from error
    return p


def _finite(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise InvalidRequest("nonfinite number")
    if isinstance(value, str):
        text(value, MAX_INPUT, allow_nul=True)
    elif isinstance(value, list):
        for child in value:
            _finite(child)
    elif isinstance(value, dict):
        for key, child in value.items():
            text(key, MAX_INPUT)
            _finite(child)


def _pairs(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidRequest("duplicate key")
        result[key] = value
    return result


def decode(raw: bytes) -> dict:
    if len(raw) > MAX_INPUT:
        raise InvalidRequest("input too large")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        _finite(value)
        return value
    except (ValueError, UnicodeError, RecursionError) as error:
        raise InvalidRequest("invalid JSON") from error


def _workspace(cwd: Path) -> claims.Workspace:
    # Producer binds actual Git/config observations; this direct read only
    # checks their agreement with the current filesystem, never runs Git.
    ws = claims.find_workspace(cwd)
    if ws is None:
        raise InvalidRequest("no filesystem workspace")
    canonical_directory(str(ws.gitdir))
    return ws


def _common_dir(ws: claims.Workspace) -> Path:
    marker = ws.gitdir / "commondir"
    if marker.exists():
        if marker.is_symlink() or marker.stat().st_size > 4096:
            raise InvalidRequest("invalid commondir")
        raw = marker.read_text(encoding="utf-8").strip()
        text(raw, 4096)
        if not raw:
            raise InvalidRequest("empty commondir")
        return (ws.gitdir / raw).resolve(strict=True)
    return ws.gitdir


def validate(envelope: object) -> tuple[dict, dict, Path]:
    exact(envelope, ("version", "request", "facts"))
    if type(envelope["version"]) is not int or envelope["version"] != 1:
        raise InvalidRequest("invalid envelope version")
    request = envelope["request"]
    if type(request) is not dict or type(request.get("operation")) is not str:
        raise InvalidRequest("invalid request")
    op = request["operation"]
    if op not in REQUEST_KEYS:  # repository-facts stays entirely in the SDK.
        raise InvalidRequest("unsupported operation")
    exact(request, ("version", "operation", "cwd", *REQUEST_KEYS[op]))
    if type(request["version"]) is not int or request["version"] != 1:
        raise InvalidRequest("invalid request version")
    facts = exact(envelope["facts"], FACT_KEYS[op])
    cwd = canonical_directory(request["cwd"])
    if "claimId" in request:
        identifier(request["claimId"])
    if op == "claim-new":
        text(request["branch"], 1024)
        identifier(request["ownerAgent"], empty=True)
        identifier(request["ownerRecord"], nullable=True)
        ttl = request["ttlHours"]
        if type(ttl) not in (int, float) or not math.isfinite(ttl) or not 0 <= ttl <= 8784:
            raise InvalidRequest("invalid ttl")
        if type(facts["head"]) is not str or not re.fullmatch("[0-9a-f]{40}", facts["head"]):
            raise InvalidRequest("invalid head")
        text(facts["origin"], 65536)
        gitdir = canonical_directory(facts["gitDir"])
        ws = _workspace(cwd)
        if ws.root != cwd or ws.gitdir != gitdir:
            raise InvalidRequest("workspace/Git-dir mismatch")
    elif op == "claim-bind-owner":
        identifier(request["agentId"])
    elif op in ("claim-install-hooks", "window-name-decision"):
        common = canonical_directory(facts["commonDir"])
        if _common_dir(_workspace(cwd)) != common:
            raise InvalidRequest("common-dir mismatch")
    if op == "claim-install-hooks":
        if type(facts["hooksStatus"]) is not int or facts["hooksStatus"] not in (0, 1):
            raise InvalidRequest("invalid hooks status")
        text(facts["hooksOutput"], 65536, allow_nul=True)
    elif op == "window-name-decision":
        text(request["windowTitle"], 8192, nullable=True)
        if type(request["firstAgent"]) is not bool or type(request["background"]) is not bool:
            raise InvalidRequest("invalid boolean")
        agent = exact(request["agent"], ("title", "parentAgentId", "labels"))
        text(agent["title"], 8192, nullable=True)
        identifier(agent["parentAgentId"], nullable=True)
        labels = agent["labels"]
        if type(labels) is not dict or len(labels) > 64:
            raise InvalidRequest("invalid labels")
        for key, value in labels.items():
            text(key, 128)
            text(value, 1024)
    return request, facts, cwd


def _record(record: dict) -> None:
    """Closed v1 output; unsupported history refuses, never vanishes from a list."""
    if (type(record) is not dict or set(record) - RECORD_KEYS
            or (RECORD_KEYS - OPTIONAL_RECORD_KEYS) - set(record)):
        raise RuntimeError("unsupported claim record")
    if type(record["v"]) is not int or record["v"] != 1:
        raise RuntimeError("unsupported claim version")
    identifier(record["id"])
    for key in ("path", "repo_origin", "branch", "base_sha", "created_at"):
        text(record[key], MAX_OUTPUT)
    owner = exact(record["owner"], ("record", "session", "agent", "model"))
    for key in ("record", "session"):
        text(owner[key], MAX_OUTPUT, nullable=True)
    for key in ("agent", "model"):
        text(owner[key], MAX_OUTPUT)
    if type(record["allow"]) is not list or len(record["allow"]) > MAX_CLAIMS:
        raise RuntimeError("invalid allow list")
    for item in record["allow"]:
        text(item, MAX_OUTPUT)
    for key in ("lead", "released_at", "inherited_dirt_patch", "expires_at"):
        if key in record:
            text(record[key], MAX_OUTPUT, nullable=True)
    for key in ("purpose", "created_by"):
        if key in record:
            text(record[key], MAX_OUTPUT)
    if (record["state"] not in claims.STATES or record["shown_state"] not in claims.LIST_STATES
            or ("role" in record and record["role"] not in claims.ROLES)):
        raise RuntimeError("invalid claim state/role")


def _active_claims() -> list:
    # Bound the actual fixed registry before invoking its shared complete scan.
    directory = claims.claims_dir()
    total = count = 0
    if directory.exists():
        for path in directory.iterdir():
            if path.suffix == ".json" and not path.name.startswith("."):
                count += 1
                entry = path.lstat()
                if not stat.S_ISREG(entry.st_mode):
                    raise RuntimeError("unsupported registry entry")
                total += entry.st_size
                if count > MAX_CLAIMS or total > MAX_OUTPUT:
                    raise RuntimeError("registry overflow")
    result = [{**c, "shown_state": claims.shown_state(c)} for c in claims.list_claims("active")]
    for record in result:
        _record(record)
    return result


def _result(status: int, output: object) -> dict:
    result = {"version": 1, "status": status, "output": output}
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")) + 1 > MAX_OUTPUT:
        raise RuntimeError("output overflow")
    return result


def dispatch(envelope: object) -> dict:
    # In-process callers receive the same total/JSON validation as stdin callers.
    try:
        encoded = json.dumps(envelope, ensure_ascii=False, allow_nan=False).encode("utf-8")
        envelope = decode(encoded)
        request, facts, cwd = validate(envelope)
    except (ValueError, UnicodeError, RecursionError, TypeError):
        return _result(2, {"kind": "invalid-request", "diagnostic": "Invalid directory operation input."})
    op = request["operation"]
    try:
        if op == "claim-new":
            claim = claims.make_claim(
                id=request["claimId"], path=cwd, branch=request["branch"],
                base_sha=facts["head"], repo_origin=facts["origin"],
                owner_agent=request["ownerAgent"], owner_record=request["ownerRecord"],
                owner_session=None, created_by="paseo-ade-claim-plugin", ttl_hours=request["ttlHours"],
            )
            registry = claims.create_claim(claim, pointer_for=cwd)
            return _result(0, {"claimId": claim["id"], "registryPath": str(registry)})
        if op == "claim-bind-owner":
            claims.bind_owner(request["claimId"], owner_agent=request["agentId"],
                              owner_record=request["agentId"], expected_path=cwd)
            return _result(0, {"claimId": request["claimId"]})
        if op == "claim-release":
            if claims.set_state(request["claimId"], "released", expected_path=cwd) is None:
                raise ValueError("missing claim")
            return _result(0, {"claimId": request["claimId"]})
        if op == "claim-list":
            return _result(0, _active_claims())
        if op == "claim-install-hooks":
            status, notes = claims.install_hooks_from_facts(
                str(cwd), facts["commonDir"], facts["hooksStatus"], facts["hooksOutput"])
            if status not in (0, 2, 73, 78) or len(notes) > 16:
                raise RuntimeError("unsupported install result")
            for note in notes:
                text(note, 8192)
            return _result(status, {"notes": notes})
        repository = names.repo_from_common_dir(str(cwd), facts["commonDir"])
        return _result(0, autoname.decide(request, repository=repository))
    except claims.ClaimExists:
        return _result(3, {"kind": "claim-exists", "diagnostic": "Claim id already exists."})
    except claims.PathClaimed:
        return _result(4, {"kind": "path-claimed", "diagnostic": "Workspace already claimed."})
    except ValueError:
        if op not in ("claim-new", "claim-bind-owner", "claim-release"):
            raise
        return _result(2, {"kind": "claim-refused", "diagnostic": "Claim operation refused."})


def main() -> int:
    if len(sys.argv) != 1:
        print("Directory operations accepts stdin only.", file=sys.stderr)
        return 1
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        try:
            envelope = decode(raw)
        except InvalidRequest:
            result = _result(2, {"kind": "invalid-request", "diagnostic": "Invalid directory operation input."})
        else:
            result = dispatch(envelope)
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) + 1 > MAX_OUTPUT:
            raise RuntimeError("output overflow")
        sys.stdout.buffer.write(encoded + b"\n")
        return result["status"]
    except Exception:
        # IO/observer/unsupported-history failures are not application success.
        # No traceback or exception-sourced paths/config values escape here.
        print("Directory operation failed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
