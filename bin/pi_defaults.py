"""Per-task Pi choices from the existing ADE router; no model calls or credentials."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile

import route_agent as router


def choose(kind: str, models: list[str], *, native_tools: bool = False,
           excluded: set[str] | None = None, quota: dict | None = None,
           age: float | None = None, repo: str | None = None) -> dict:
    """Return a qualified physical Pi route, or a visible no-route result."""
    if kind not in router.KINDS:
        raise ValueError("unknown task kind")
    if quota is None:
        quota, age = router.load_snapshot(bypass_memo=True)
    available = set(models)
    skip = set(excluded or ()) | router.operator_disabled()
    for svc in router.discover(quota):
        spec = shlex.split(svc.models.get(kind, ""))
        if (svc.acp_agent != "pi" or not spec or spec[0] not in available
                or (native_tools and svc.access != "api")):
            skip.add(svc.name)
    picked = router.route(kind, quota=quota, exclude=skip, repo=repo)
    if picked is None:
        return {"schema_version": 1, "kind": kind, "service": None,
                "reason": "No qualified Pi route with fresh quota and the required tools/model"}
    parts = shlex.split(picked.model)
    if len(parts) not in (1, 3) or (len(parts) == 3 and parts[1] != "--effort"):
        raise ValueError("invalid configured model profile")
    full = parts[0]
    provider, separator, model = full.partition("/")
    if not separator or not provider or not model or provider == "ade":
        raise ValueError("a physical namespaced model is required")
    return {"schema_version": 1, "kind": kind, "service": picked.service.name,
            "provider": provider, "model": model, "model_id": full,
            "thinking": parts[2] if len(parts) == 3 else "off",
            "reason": picked.why, "quota_age_seconds": age,
            "alternatives": picked.alternatives}


@contextmanager
def block_lock(path: Path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def update_block(service: str, reason: str | None) -> dict:
    """Latch confirmed runtime failures until an explicit clear; never guess a reset."""
    if service not in {s.name for s in router.SERVICES if s.acp_agent == "pi"}:
        raise ValueError("not a configured Pi service")
    path = router.pi_block_state_path()
    with block_lock(path):
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            data = {"schema_version": 1, "blocked": {}}
        if (not isinstance(data, dict) or data.get("schema_version") != 1
                or not isinstance(data.get("blocked"), dict)):
            raise ValueError("invalid block state; preserve it for inspection")
        if reason is None:
            data["blocked"].pop(service, None)
        else:
            if reason not in ("quota", "billing"):
                raise ValueError("unknown failure class")
            data["blocked"][service] = {
                "reason": reason, "at": datetime.now(timezone.utc).isoformat()}
        fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as out:
                json.dump(data, out, sort_keys=True)
                out.write("\n")
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return {"schema_version": 1, "service": service, "blocked": reason is not None}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--kind", default="code", choices=router.KINDS)
    p.add_argument("--native-tools", action="store_true",
                   help="require the direct Pi tool loop; exclude vendor-CLI bridges")
    p.add_argument("--exclude-service", action="append", default=[])
    p.add_argument("--models-json", metavar="FILE",
                   help="available physical model IDs as a JSON array; - reads stdin")
    p.add_argument("--repo", help="repository name for the existing router's quota floors")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--block-service", metavar="SERVICE")
    mode.add_argument("--clear-block", metavar="SERVICE")
    mode.add_argument("--check-service", metavar="SERVICE",
                      help="read the confirmed-failure latch without refreshing quota")
    p.add_argument("--reason", choices=("quota", "billing"))
    a = p.parse_args(argv)
    try:
        if a.check_service:
            if a.reason or a.check_service not in {s.name for s in router.SERVICES if s.acp_agent == "pi"}:
                raise ValueError("invalid latch query")
            result = {"schema_version": 1, "service": a.check_service,
                      "blocked": a.check_service in router.pi_blocked_services()}
        elif a.block_service:
            if not a.reason:
                p.error("--block-service requires --reason")
            result = update_block(a.block_service, a.reason)
        elif a.clear_block:
            if a.reason:
                p.error("--reason requires --block-service")
            result = update_block(a.clear_block, None)
        else:
            if a.reason:
                p.error("--reason requires --block-service")
            if a.models_json:
                text = sys.stdin.read(1_048_577) if a.models_json == "-" else Path(a.models_json).read_text()
                if len(text) > 1_048_576:
                    raise ValueError("model list too large")
                models = json.loads(text)
                if not isinstance(models, list) or any(not isinstance(x, str) for x in models):
                    raise ValueError("model list must be an array of IDs")
            else:
                models = router.provider_models("pi")
                if models is None:
                    raise ValueError("Pi model catalog unavailable")
            result = choose(a.kind, models, native_tools=a.native_tools,
                            excluded=set(a.exclude_service), repo=a.repo or router.repo_of(os.getcwd()))
        print(json.dumps(result, allow_nan=False))
        return 0 if result.get("service") is not None else 1
    except (OSError, ValueError, TypeError):
        print(json.dumps({"schema_version": 1, "service": None,
                          "reason": "Pi defaults unavailable; inspect configuration/quota metadata"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
