"""Fork enrollment inspection and fail-closed ADE installer containment.

Foundation only: validates policy and holds managed installer commands. It does
not qualify artifacts, execute adapters, synchronize forks or promote releases.
The installer always reads policy beside this module, never from a catalog's
--root, an environment override or caller-supplied qualification evidence.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

POLICY_PATH = Path(__file__).resolve().parent.parent / "config" / "forks.toml"
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
STRATEGIES = {"merge", "patch-queue", "master-snapshot"}
FIELDS = {
    "id", "owner", "upstream", "fork", "channel", "strategy",
    "compatibility_group", "catalog_ids", "required_features", "patch_manifest",
}


class PolicyError(ValueError):
    """Unreadable, unsupported or ambiguous enrollment policy."""


def load_policy(path: Path | None = None) -> list[dict[str, Any]]:
    """Validate the complete policy; empty or damaged policy never means unmanaged."""
    path = POLICY_PATH if path is None else path
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise PolicyError(f"cannot read fork policy {path}: {type(error).__name__}") from error
    if set(data) != {"schema_version", "component"} or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise PolicyError("fork policy requires schema_version=1 and component array only")
    rows = data["component"]
    if not isinstance(rows, list) or not rows:
        raise PolicyError("fork policy requires a nonempty component array")
    ids: set[str] = set()
    catalog_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) - FIELDS:
            raise PolicyError("unknown fork component fields")
        for key in ("id", "owner", "channel", "compatibility_group"):
            value = row.get(key)
            if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
                raise PolicyError(f"invalid fork component {key}")
        if row["id"] in ids:
            raise PolicyError(f"duplicate fork id: {row['id']}")
        ids.add(row["id"])
        if not isinstance(row.get("strategy"), str) or row["strategy"] not in STRATEGIES:
            raise PolicyError(f"invalid strategy for {row['id']}")
        for key in ("upstream", "fork"):
            value = row.get(key)
            if not isinstance(value, str) or any(c.isspace() for c in value):
                raise PolicyError(f"invalid {key} URL for {row['id']}")
            try:
                url = urlsplit(value)
                valid = url.scheme == "https" and url.hostname and url.path.strip("/") and not (url.username or url.password or url.query or url.fragment or url.port)
            except ValueError:
                valid = False
            if not valid:
                raise PolicyError(f"{key} must be a credential-free HTTPS repository URL")
        for key in ("catalog_ids", "required_features"):
            values = row.get(key)
            if not isinstance(values, list) or (key == "required_features" and not values):
                raise PolicyError(f"{key} must be an array for {row['id']}")
            if any(not isinstance(v, str) or not IDENTIFIER.fullmatch(v) for v in values) or len(set(values)) != len(values):
                raise PolicyError(f"invalid or duplicate {key} for {row['id']}")
        for cid in row["catalog_ids"]:
            if cid in catalog_ids:
                raise PolicyError(f"catalog id enrolled twice: {cid}")
            catalog_ids.add(cid)
        manifest = row.get("patch_manifest")
        if row["strategy"] == "patch-queue" and not isinstance(manifest, str):
            raise PolicyError(f"patch-queue requires patch_manifest for {row['id']}")
        if manifest is not None and (not isinstance(manifest, str) or not manifest or Path(manifest).is_absolute() or ".." in Path(manifest).parts or "\\" in manifest):
            raise PolicyError("patch_manifest must be a portable repository-relative path")
    return rows


def installer_hold(component_id: str) -> str | None:
    """Re-read trusted policy immediately before execution; no allow override.

    Unavailable policy holds every installer command. An enrolled catalog ID is
    held even when the candidate catalog changes its source/argv. Adapters and
    evidence verification must land before any managed command can be released.
    """
    try:
        rows = load_policy()
    except PolicyError:
        return "fork_policy_unavailable: installer execution held; restore trusted config/forks.toml"
    for row in rows:
        if component_id in row["catalog_ids"]:
            return f"fork_managed: {row['id']} requires a qualified promotion adapter; generic install/update/repair refused"
    return None


def inspect_policy(rows: list[dict[str, Any]], ids: list[str]) -> dict[str, Any]:
    """Report enrollment, never infer qualification from valid configuration."""
    unknown = set(ids) - {row["id"] for row in rows}
    if unknown:
        raise PolicyError("unknown fork id(s): " + ", ".join(sorted(unknown)))
    return {
        "schema_version": 1,
        "policy_valid": True,
        "stage": "containment",
        "components": [
            {
                **row,
                "upstream_revision": None,
                "candidate_revision": None,
                "installed_revision": None,
                "running_revision": None,
                "eligible": False,
                "authorized": False,
                "reason": "qualification_unavailable",
                "detail": "enrollment only; feature IDs are requirements, not test results; runtime not observed",
                "installer_action": "hold" if row["catalog_ids"] else "outside-ade-catalog",
            }
            for row in rows if not ids or row["id"] in ids
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "check"))
    parser.add_argument("--id", action="append", default=[], help="enrollment ID; repeatable")
    parser.add_argument("--policy", type=Path, default=POLICY_PATH, help="inspect another policy (does not override installer enforcement)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = inspect_policy(load_policy(args.policy), args.id)
    except PolicyError as error:
        if args.json:
            print(json.dumps({"schema_version": 1, "policy_valid": False, "eligible": False, "error": str(error)}))
        else:
            print(f"ade-fork: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("ade-fork: policy valid; qualification and activation unavailable")
        for row in report["components"]:
            print(f"  {row['id']}: {row['installer_action']}; eligible=false; runtime unknown")
    # check is a readiness check, not a policy-lint success masquerading as
    # permission to install. Every enrolled component is held in this phase.
    return 1 if args.command == "check" else 0
