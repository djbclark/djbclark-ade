"""Pi pool acceptance for automatic routing (ade/auto / bin/pi-default).

Reads config/pi-pool-acceptance.toml. A Pi [[service]] in config/routing.toml
(`agent = "pi"`) with no row, or with accepted = false, cannot win automatic
routing. Manual model pins are unchanged. The operator flips accepted = true
per pool after continuation/quota/identity acceptance (docs/pi-defaults.md).

  ade-pi-pools ls [--json]       list every acceptance row and routing Pi services
  ade-pi-pools check [--json]    exit 0 when every routing Pi service is accepted;
                                 exit 2 when any is missing or accepted=false;
                                 exit 1 on usage or an unreadable config
  ade-pi-pools probe [--json] [--pool NAME ...]
                                 observe-only continuation/quota/identity probes;
                                 never writes accepted=true; never touches Claude
                                 API billing (docs/pi-defaults.md B4b)

PI_POOL_ACCEPTANCE redirects the acceptance file (tests).
ADE_PI_ACCEPTANCE_EVIDENCE_DIR redirects continuation evidence (tests).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

import route_agent as router

REPO = Path(__file__).resolve().parent.parent

# Claude API credit pools: never probe (queue #17 / billing-blocked). Subscription
# Claude Max is a different pool and is also not auto-accepted here.
CLAUDE_API_BILLING_POOLS = frozenset({"omp", "anthropic", "claude-api"})

PROBE_STATUSES = frozenset({"pass", "fail", "unknown", "skip"})


def _pct(value: Any) -> float | None:
    """Parse a remaining-percent reading; None when missing or non-numeric."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_age(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        age = float(value)
    except (TypeError, ValueError):
        return None
    return age if age >= 0 else None


def acceptance_path() -> Path:
    return Path(os.environ.get("PI_POOL_ACCEPTANCE") or REPO / "config" / "pi-pool-acceptance.toml")


def evidence_dir() -> Path:
    env = os.environ.get("ADE_PI_ACCEPTANCE_EVIDENCE_DIR")
    if env:
        return Path(env)
    return Path.home() / ".local" / "state" / "ade" / "pi-acceptance"


def load_acceptance(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return `{pool: {accepted, note, identity, billing}}`. Missing file → {}. Unreadable → raise."""
    target = path or acceptance_path()
    try:
        raw = target.read_bytes()
    except FileNotFoundError:
        return {}
    data = tomllib.loads(raw.decode("utf-8"))
    pools = data.get("pools")
    if pools is None:
        return {}
    if not isinstance(pools, dict):
        raise ValueError("pi-pool-acceptance.toml: [pools] must be a table of pool tables")
    out: dict[str, dict[str, Any]] = {}
    for name, row in pools.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("pi-pool-acceptance.toml: pool names must be non-empty strings")
        if not isinstance(row, dict):
            raise ValueError(f"pi-pool-acceptance.toml: pools.{name} must be a table")
        accepted = row.get("accepted", False)
        if not isinstance(accepted, bool):
            raise ValueError(f"pi-pool-acceptance.toml: pools.{name}.accepted must be a bool")
        note = row.get("note", "")
        if note is not None and not isinstance(note, str):
            raise ValueError(f"pi-pool-acceptance.toml: pools.{name}.note must be a string")
        identity = row.get("identity", "")
        if identity is not None and not isinstance(identity, str):
            raise ValueError(f"pi-pool-acceptance.toml: pools.{name}.identity must be a string")
        billing = row.get("billing", "")
        if billing is not None and not isinstance(billing, str):
            raise ValueError(f"pi-pool-acceptance.toml: pools.{name}.billing must be a string")
        out[name] = {
            "accepted": accepted,
            "note": note or "",
            "identity": identity or "",
            "billing": billing or "",
        }
    return out


def routing_pi_services() -> list[str]:
    return sorted(s.name for s in router.SERVICES if s.acp_agent == "pi" and not s.retired)


def unaccepted_auto_services(path: Path | None = None) -> set[str]:
    """Pi routing services that must not win ade/auto (missing row or accepted=false)."""
    rows = load_acceptance(path)
    out: set[str] = set()
    for name in routing_pi_services():
        row = rows.get(name)
        if row is None or row.get("accepted") is not True:
            out.add(name)
    return out


def status_rows(path: Path | None = None) -> list[dict[str, Any]]:
    """One row per acceptance-file pool and every routing Pi service not listed there."""
    rows = load_acceptance(path)
    pi = set(routing_pi_services())
    names = sorted(set(rows) | pi)
    out = []
    for name in names:
        row = rows.get(name)
        in_routing = name in pi
        accepted = bool(row and row.get("accepted") is True)
        out.append({
            "pool": name,
            "accepted": accepted,
            "in_routing_pi": in_routing,
            "note": (row or {}).get("note", ""),
            "identity": (row or {}).get("identity", ""),
            "billing": (row or {}).get("billing", ""),
            "blocks_auto": in_routing and not accepted,
        })
    return out


def check_auto(path: Path | None = None) -> tuple[int, list[dict[str, Any]], list[str]]:
    """Return (exit_code, rows, blocking_pool_names). 0 ready, 2 blocked."""
    rows = status_rows(path)
    blocking = [r["pool"] for r in rows if r["blocks_auto"]]
    # A routing Pi service with no acceptance row appears in status_rows via | pi.
    return (0 if not blocking else 2, rows, blocking)


def _dim(status: str, detail: str, **extra: Any) -> dict[str, Any]:
    if status not in PROBE_STATUSES:
        raise ValueError(f"invalid probe status: {status}")
    out: dict[str, Any] = {"status": status, "detail": detail}
    out.update(extra)
    return out


def _claude_api_skip(dimension: str) -> dict[str, Any]:
    return _dim(
        "skip",
        f"{dimension}: Claude API billing not probed (billing-blocked; queue #17; "
        "subscription Claude Max is a separate pool)",
    )


def probe_quota(
    pool: str,
    *,
    quota: dict[str, Any] | None = None,
    snapshot_age: float | None = None,
) -> dict[str, Any]:
    """Observe named-pool quota freshness without spending or flipping acceptance.

    Reads the same aiuse/paseo snapshot `route_agent.load_snapshot` uses. Never
    calls the Claude API. Pass: remaining known and > 0, age <= STALE_SOFT, not
    approval-required. Fail: exhausted, stale, approval-required. Unknown: no row.
    """
    if pool in CLAUDE_API_BILLING_POOLS:
        return _claude_api_skip("quota")
    age = snapshot_age
    if quota is None:
        quota, age = router.load_snapshot(bypass_memo=True)
    info = (quota or {}).get(pool)
    if not isinstance(info, dict) or not info:
        return _dim("unknown", f"no named-pool quota reading for {pool}")
    if info.get("requires_operator_approval") is True:
        return _dim("fail", "quota requires operator approval", remaining=info.get("remaining"))
    # route_agent._fold_paseo may set paseo_unknown to a descriptive string (not
    # bool True) beside a fresh aiuse reading; treat any truthy flag as unknown.
    if info.get("unknown") or info.get("paseo_unknown"):
        return _dim("fail", "quota reading is unknown", remaining=info.get("remaining"))
    remaining = _pct(info.get("remaining"))
    pool_age = _clean_age(info.get("age_s"))
    if pool_age is None:
        pool_age = _clean_age(age)
    if remaining is None:
        return _dim("unknown", "quota remaining is not a number", age_s=pool_age)
    if pool_age is None:
        return _dim("unknown", "quota age is unknown", remaining=remaining)
    if pool_age > router.STALE_SOFT:
        return _dim(
            "fail",
            f"quota stale ({pool_age:.0f}s > STALE_SOFT {router.STALE_SOFT}s)",
            remaining=remaining,
            age_s=pool_age,
        )
    if remaining <= 0:
        return _dim("fail", "quota remaining is 0", remaining=remaining, age_s=pool_age)
    return _dim(
        "pass",
        f"fresh named-pool quota ({remaining:g}% left, age {pool_age:.0f}s)",
        remaining=remaining,
        age_s=pool_age,
    )


def _routing_service(pool: str) -> Any | None:
    for svc in router.SERVICES:
        if svc.name == pool:
            return svc
    return None


def probe_identity(pool: str, path: Path | None = None) -> dict[str, Any]:
    """Observe billing identity labels without calling providers or writing acceptance.

    Pass when the acceptance row (or curated routing service) names a non-API
    billing class and an identity label. Claude API credit pools are skipped.
    """
    if pool in CLAUDE_API_BILLING_POOLS:
        return _claude_api_skip("identity")
    row = load_acceptance(path).get(pool) or {}
    svc = _routing_service(pool)
    billing = (row.get("billing") or "").strip() or (svc.billing if svc else "")
    identity = (row.get("identity") or "").strip()
    if not identity and svc is not None and svc.billing:
        identity = f"routing:{svc.name}/{svc.billing}"
    if not identity:
        return _dim(
            "unknown",
            "no identity label (set pools.<name>.identity in pi-pool-acceptance.toml)",
        )
    if not billing:
        return _dim(
            "unknown",
            f"identity {identity!r} recorded but billing class missing "
            "(set pools.<name>.billing)",
            identity=identity,
        )
    if billing == "api" and pool in CLAUDE_API_BILLING_POOLS:
        return _claude_api_skip("identity")
    # Subscription / free / prepaid / gateway labels are the accepted classes;
    # a bare "api" without a Claude-API pool name still needs operator review.
    if billing == "api":
        return _dim(
            "fail",
            f"billing class is api ({identity}); confirm it is not Claude API credits "
            "before accepting (this harness never probes Claude API billing)",
            identity=identity,
            billing=billing,
        )
    return _dim(
        "pass",
        f"billing identity {identity} ({billing})",
        identity=identity,
        billing=billing,
    )


def probe_continuation(
    pool: str,
    *,
    evidence: Path | None = None,
) -> dict[str, Any]:
    """Observe continuation/resume evidence; never invent a pass from a basic smoke.

    Reads `<evidence-dir>/<pool>.json` (ADE_PI_ACCEPTANCE_EVIDENCE_DIR or
    ~/.local/state/ade/pi-acceptance/). Schema: schema_version=1 and
    continuation.ok bool. Missing evidence → unknown. Never writes the file.
    """
    if pool in CLAUDE_API_BILLING_POOLS:
        return _claude_api_skip("continuation")
    base = evidence if evidence is not None else evidence_dir()
    path = base / f"{pool}.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _dim(
            "unknown",
            f"no continuation evidence at {path} "
            "(record a two-request resume; docs/pi-defaults.md B4b)",
        )
    except OSError as e:
        return _dim("fail", f"continuation evidence unreadable ({path}): {e}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return _dim("fail", f"continuation evidence is not JSON ({path}): {e}")
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        return _dim("fail", f"continuation evidence needs schema_version=1 ({path})")
    cont = data.get("continuation")
    if not isinstance(cont, dict):
        return _dim("fail", f"continuation evidence missing continuation object ({path})")
    ok = cont.get("ok")
    note = cont.get("note", "")
    if not isinstance(note, str):
        note = ""
    if ok is True:
        return _dim("pass", note or f"continuation.ok at {path}", evidence=str(path))
    if ok is False:
        return _dim("fail", note or f"continuation.ok=false at {path}", evidence=str(path))
    return _dim("unknown", f"continuation.ok not a bool at {path}", evidence=str(path))


def probe_pool(
    pool: str,
    *,
    path: Path | None = None,
    quota: dict[str, Any] | None = None,
    snapshot_age: float | None = None,
    evidence: Path | None = None,
) -> dict[str, Any]:
    """Run the three observe-only dimensions for one pool. Never writes accepted=true."""
    rows = load_acceptance(path)
    row = rows.get(pool) or {}
    accepted = bool(row.get("accepted") is True)
    dims = {
        "quota": probe_quota(pool, quota=quota, snapshot_age=snapshot_age),
        "identity": probe_identity(pool, path=path),
        "continuation": probe_continuation(pool, evidence=evidence),
    }
    statuses = {d["status"] for d in dims.values()}
    ready = statuses == {"pass"}
    return {
        "pool": pool,
        "accepted": accepted,
        "probes": dims,
        "ready_for_operator_accept": ready and not accepted,
        "all_dimensions_pass": ready,
        "writes_accepted": False,
    }


def probe_pools(
    pools: list[str] | None = None,
    *,
    path: Path | None = None,
    quota: dict[str, Any] | None = None,
    snapshot_age: float | None = None,
    evidence: Path | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    """Probe selected pools (default: every acceptance + routing Pi name).

    Exit: 0 all dimensions pass for every selected pool; 2 any fail; 3 no fail
    but some unknown/skip; 1 reserved for caller errors. Never writes acceptance.
    """
    if pools is None:
        names = [r["pool"] for r in status_rows(path)]
    else:
        names = list(pools)
    # One snapshot for the whole run when the caller did not supply quota.
    if quota is None and any(n not in CLAUDE_API_BILLING_POOLS for n in names):
        quota, snapshot_age = router.load_snapshot(bypass_memo=True)
    results = [
        probe_pool(
            name,
            path=path,
            quota=quota,
            snapshot_age=snapshot_age,
            evidence=evidence,
        )
        for name in names
    ]
    statuses: set[str] = set()
    for r in results:
        for d in r["probes"].values():
            statuses.add(d["status"])
    if "fail" in statuses:
        code = 2
    elif statuses - {"pass"}:
        code = 3
    else:
        code = 0
    return code, results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="ade-pi-pools",
        description="Pi pool acceptance gate for automatic routing (docs/pi-defaults.md).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, help_text in (
        ("ls", "list acceptance rows and routing Pi services"),
        ("check", "exit 2 until every routing Pi service is accepted"),
    ):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--json", action="store_true", help="print machine-readable JSON")
    sp_probe = sub.add_parser(
        "probe",
        help="observe-only continuation/quota/identity probes (never writes accepted=true)",
    )
    sp_probe.add_argument("--json", action="store_true", help="print machine-readable JSON")
    sp_probe.add_argument(
        "--pool",
        action="append",
        default=[],
        metavar="NAME",
        help="limit to this pool (repeatable); default: every acceptance/routing Pi name",
    )
    sp_probe.add_argument(
        "--evidence-dir",
        metavar="DIR",
        help="continuation evidence directory (default: ADE_PI_ACCEPTANCE_EVIDENCE_DIR "
        "or ~/.local/state/ade/pi-acceptance)",
    )
    a = p.parse_args(argv)
    try:
        if a.cmd == "ls":
            rows = status_rows()
            if a.json:
                print(json.dumps({"schema_version": 1, "path": str(acceptance_path()),
                                  "pools": rows}, allow_nan=False))
            else:
                print(f"# {acceptance_path()}")
                for r in rows:
                    flag = "accepted" if r["accepted"] else "UNACCEPTED"
                    route = "routing-pi" if r["in_routing_pi"] else "checklist"
                    note = f" — {r['note']}" if r["note"] else ""
                    print(f"{r['pool']}: {flag} [{route}]{note}")
            return 0
        if a.cmd == "probe":
            accept = acceptance_path()
            before = accept.read_bytes() if accept.is_file() else None
            before_mtime = accept.stat().st_mtime_ns if accept.is_file() else None
            evidence = Path(a.evidence_dir) if a.evidence_dir else None
            code, results = probe_pools(
                a.pool or None,
                evidence=evidence,
            )
            after = accept.read_bytes() if accept.is_file() else None
            if before != after or (
                before_mtime is not None
                and accept.is_file()
                and accept.stat().st_mtime_ns != before_mtime
            ):
                print(
                    "ade-pi-pools: probe mutated pi-pool-acceptance.toml "
                    "(must be observe-only; never write accepted=true)",
                    file=sys.stderr,
                )
                return 1
            payload = {
                "schema_version": 1,
                "path": str(accept),
                "evidence_dir": str(evidence or evidence_dir()),
                "writes_accepted": False,
                "claude_api_billing_probed": False,
                "exit": code,
                "pools": results,
            }
            if a.json:
                print(json.dumps(payload, allow_nan=False))
            else:
                print(
                    f"# observe-only probe (writes_accepted=false; "
                    f"claude_api_billing_probed=false)\n# acceptance: {accept}\n"
                    f"# evidence: {payload['evidence_dir']}"
                )
                for r in results:
                    flag = "accepted" if r["accepted"] else "UNACCEPTED"
                    ready = "ready-for-operator-accept" if r["ready_for_operator_accept"] else (
                        "all-pass" if r["all_dimensions_pass"] else "incomplete"
                    )
                    print(f"{r['pool']}: {flag} [{ready}]")
                    for dim, d in r["probes"].items():
                        print(f"  {dim}: {d['status']} — {d['detail']}")
                if code == 0:
                    print("ade-pi-pools probe: every selected pool passes continuation/quota/identity")
                elif code == 2:
                    print(
                        "ade-pi-pools probe: at least one dimension failed "
                        "(operator reviews; harness never writes accepted=true)",
                        file=sys.stderr,
                    )
                else:
                    print(
                        "ade-pi-pools probe: incomplete (unknown/skip remain); "
                        "harness never writes accepted=true",
                        file=sys.stderr,
                    )
            return code
        code, rows, blocking = check_auto()
        if a.json:
            print(json.dumps({"schema_version": 1, "path": str(acceptance_path()),
                              "ready": code == 0, "blocking": blocking, "pools": rows},
                             allow_nan=False))
        else:
            if code == 0:
                print("ade-pi-pools: every routing Pi service is accepted for automatic routing")
            else:
                print("ade-pi-pools: automatic routing blocked until the operator flips "
                      f"accepted=true for: {', '.join(blocking)} "
                      f"(edit {acceptance_path()}; docs/pi-defaults.md)", file=sys.stderr)
                for r in rows:
                    if r["blocks_auto"]:
                        print(f"  {r['pool']}: accepted=false or missing", file=sys.stderr)
        return code
    except (OSError, ValueError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        print(f"ade-pi-pools: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
