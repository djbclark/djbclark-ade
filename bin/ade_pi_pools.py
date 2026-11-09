"""Pi pool acceptance for automatic routing (ade/auto / bin/pi-default).

Reads config/pi-pool-acceptance.toml. A Pi [[service]] in config/routing.toml
(`agent = "pi"`) with no row, or with accepted = false, cannot win automatic
routing. Manual model pins are unchanged. The operator flips accepted = true
per pool after continuation/quota/identity acceptance (docs/pi-defaults.md).

  ade-pi-pools ls [--json]       list every acceptance row and routing Pi services
  ade-pi-pools check [--json]    exit 0 when every routing Pi service is accepted;
                                 exit 2 when any is missing or accepted=false;
                                 exit 1 on usage or an unreadable config

PI_POOL_ACCEPTANCE redirects the file (tests).
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


def acceptance_path() -> Path:
    return Path(os.environ.get("PI_POOL_ACCEPTANCE") or REPO / "config" / "pi-pool-acceptance.toml")


def load_acceptance(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return `{pool: {accepted: bool, note: str, ...}}`. Missing file → {}. Unreadable → raise."""
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
        out[name] = {"accepted": accepted, "note": note or ""}
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
            "blocks_auto": in_routing and not accepted,
        })
    return out


def check_auto(path: Path | None = None) -> tuple[int, list[dict[str, Any]], list[str]]:
    """Return (exit_code, rows, blocking_pool_names). 0 ready, 2 blocked."""
    rows = status_rows(path)
    blocking = [r["pool"] for r in rows if r["blocks_auto"]]
    # A routing Pi service with no acceptance row appears in status_rows via | pi.
    return (0 if not blocking else 2, rows, blocking)


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
