"""ade_install: read-only install catalog, plan, and observe-only doctor.

Transitional source: ``config/install.toml`` when ``config/ade.toml`` is absent.
Does not install, update, repair, or read secret values. Key entries are names
and metadata only; verify probes are recorded as UNKNOWN until a later managed
probe phase. Plain doctor never repairs.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BIN = Path(__file__).resolve().parent
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import ade_config as ac  # noqa: E402

SCHEMA_VERSION = 1
UNKNOWN = "UNKNOWN"
COMPONENT_CLASSES = frozenset({"hard", "offered", "optional", "suggested", "never"})
# Classes that require an explicit chosen bool in the catalog.
CHOICE_CLASSES = frozenset({"offered", "optional", "suggested"})


class InstallError(ac.ConfigError):
    """Invalid install catalog or refused operation."""


@dataclass
class Catalog:
    data: dict[str, Any]
    path: Path
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def components(self) -> list[dict[str, Any]]:
        return list(self.data.get("component") or [])

    @property
    def keys(self) -> list[dict[str, Any]]:
        return list(self.data.get("key") or [])

    @property
    def logins(self) -> list[dict[str, Any]]:
        return list(self.data.get("login") or [])


@dataclass(frozen=True)
class Observation:
    kind: str  # component | key | login | catalog
    id: str
    status: str  # ok | missing | unknown | error | unchosen | never
    detail: str


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parent.parent


def default_install_path(root: Path) -> Path:
    return root / "config" / "install.toml"


def default_install_schema_path(root: Path) -> Path:
    return root / "config" / "install.schema.json"


def default_new_config_path(root: Path) -> Path:
    return ac.default_new_config_path(root)


def read_install_schema(root: Path) -> dict[str, Any]:
    path = default_install_schema_path(root)
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as e:
        raise InstallError(f"{path}: invalid or unreadable schema ({e})") from e
    ac._check_schema_node(schema, str(path))
    if schema.get("title") != "djbclark-ade install catalog":
        raise InstallError(f"{path}: unexpected title")
    if schema.get("properties", {}).get("schema_version", {}).get("const") != SCHEMA_VERSION:
        raise InstallError(f"{path}: unsupported schema version declaration")
    return schema


def _reject_duplicate_ids(rows: list[dict[str, Any]], *, key: str, label: str) -> None:
    seen: dict[str, int] = {}
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise InstallError(f"{label}[{i}]: must be a table")
        name = row.get(key)
        if not isinstance(name, str) or not name:
            raise InstallError(f"{label}[{i}]: missing {key}")
        if name in seen:
            raise InstallError(f"{label}: duplicate {key} {name!r} (entries {seen[name]} and {i})")
        seen[name] = i


def validate_catalog_semantics(data: dict[str, Any], *, path: Path) -> None:
    components = data.get("component") or []
    if not isinstance(components, list) or not components:
        raise InstallError(f"{path}: component array is required and must be non-empty")
    _reject_duplicate_ids(components, key="id", label=f"{path} component")
    for i, row in enumerate(components):
        cls = row.get("class")
        if cls not in COMPONENT_CLASSES:
            raise InstallError(
                f"{path}: component[{i}] id={row.get('id')!r}: "
                f"class must be one of {sorted(COMPONENT_CLASSES)}, got {cls!r}"
            )
        if cls in CHOICE_CLASSES and "chosen" not in row:
            raise InstallError(
                f"{path}: component[{i}] id={row.get('id')!r}: "
                f"class {cls!r} requires an explicit chosen boolean"
            )
        if cls == "hard" and row.get("chosen") is False:
            raise InstallError(
                f"{path}: component[{i}] id={row.get('id')!r}: hard components cannot set chosen=false"
            )
        for field in ("install", "update", "probe"):
            val = row.get(field)
            if val is not None and not isinstance(val, str):
                raise InstallError(f"{path}: component[{i}].{field} must be a string")
    keys = data.get("key") or []
    if keys:
        if not isinstance(keys, list):
            raise InstallError(f"{path}: key must be an array of tables")
        _reject_duplicate_ids(keys, key="name", label=f"{path} key")
    logins = data.get("login") or []
    if logins:
        if not isinstance(logins, list):
            raise InstallError(f"{path}: login must be an array of tables")
        _reject_duplicate_ids(logins, key="id", label=f"{path} login")


def load_catalog(
    *,
    root: Path | None = None,
    install_path: Path | None = None,
) -> Catalog:
    """Load and validate the transitional install catalog. Never writes."""
    root = (root or repo_root_from_here()).resolve()
    new_path = default_new_config_path(root)
    path = install_path if install_path is not None else default_install_path(root)
    provenance: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "install_config": str(path),
        "ade_toml_present": ac.input_present(new_path),
        "source": "install.toml",
        "note": (
            "transitional catalog while config/ade.toml is absent; "
            "a present ade.toml must eventually carry install/keys after a reviewed fold"
        ),
    }
    if ac.input_present(new_path):
        # Do not silently invent a second editable authority beside a unified file.
        raise InstallError(
            f"{new_path}: present; refuse transitional config/install.toml until install/keys "
            "are folded into the unified file (no permanent duplicate editable authorities)"
        )
    if not ac.input_present(path):
        raise InstallError(f"{path}: missing install catalog")
    raw = ac.read_toml(path)
    ver = raw.get("schema_version")
    if ver != SCHEMA_VERSION:
        raise InstallError(f"{path}: unsupported schema_version {ver!r} (need {SCHEMA_VERSION})")
    schema = read_install_schema(root)
    ac.validate_tree(raw, schema, label=str(path))
    validate_catalog_semantics(raw, path=path)
    return Catalog(data=copy.deepcopy(raw), path=path, provenance=provenance)


def expected_installed(row: dict[str, Any]) -> bool:
    """Whether doctor expects this component to be present on the machine."""
    cls = row["class"]
    if cls == "hard":
        return True
    if cls in ("offered", "optional"):
        return bool(row.get("chosen"))
    return False  # suggested / never


def observe_component(row: dict[str, Any]) -> Observation:
    cid = str(row["id"])
    cls = str(row["class"])
    if cls == "never":
        return Observation("component", cid, "never", "recorded as never-installed")
    if cls == "suggested" and not row.get("chosen"):
        return Observation("component", cid, "unchosen", "suggested only; not chosen")
    if cls in CHOICE_CLASSES and not row.get("chosen"):
        return Observation("component", cid, "unchosen", f"{cls} component not chosen")
    if not expected_installed(row):
        return Observation("component", cid, "unchosen", "not expected on this machine")
    presence = row.get("presence")
    if not presence or presence == UNKNOWN:
        return Observation(
            "component", cid, "unknown",
            "no presence basename recorded (UNKNOWN); not treated as healthy or absent",
        )
    found = shutil.which(str(presence))
    if found:
        return Observation("component", cid, "ok", f"found on PATH: {found}")
    return Observation("component", cid, "missing", f"not on PATH: {presence}")


def observe_key(row: dict[str, Any]) -> Observation:
    name = str(row["name"])
    verify = row.get("verify") or UNKNOWN
    expiry = row.get("expiry") or "unknown"
    detail = f"reference only; verify={verify}; expiry={expiry} (no value read)"
    return Observation("key", name, "unknown", detail)


def observe_login(row: dict[str, Any]) -> Observation:
    lid = str(row["id"])
    cmd = row.get("command") or UNKNOWN
    if cmd == UNKNOWN:
        return Observation("login", lid, "unknown", "login command not recorded")
    return Observation("login", lid, "unknown", f"login check recorded as {cmd!r}; not executed")


def doctor(catalog: Catalog) -> tuple[list[Observation], int]:
    """Observe-only doctor. Exit 1 if any expected component is missing; never repairs."""
    obs: list[Observation] = [
        Observation("catalog", str(catalog.path), "ok", "catalog validated"),
    ]
    hard_missing = 0
    for row in catalog.components:
        o = observe_component(row)
        obs.append(o)
        if expected_installed(row) and o.status == "missing":
            hard_missing += 1
        if expected_installed(row) and o.status == "error":
            hard_missing += 1
    for row in catalog.keys:
        obs.append(observe_key(row))
    for row in catalog.logins:
        obs.append(observe_login(row))
    return obs, (1 if hard_missing else 0)


def plan(catalog: Catalog) -> list[dict[str, Any]]:
    """Print-only reconciliation plan: what would be required next; does not install."""
    steps: list[dict[str, Any]] = []
    for row in catalog.components:
        cid = row["id"]
        if not expected_installed(row):
            steps.append({
                "id": cid,
                "action": "skip",
                "reason": f"class={row['class']} chosen={row.get('chosen')}",
            })
            continue
        install = row.get("install") or UNKNOWN
        if install == UNKNOWN:
            steps.append({
                "id": cid,
                "action": "blocked",
                "reason": "install recipe UNKNOWN; record a real owner installer before apply",
            })
        else:
            steps.append({
                "id": cid,
                "action": "would-install",
                "reason": install,
                "note": "apply/reconciliation is a later unit; plan is print-only",
            })
    for row in catalog.keys:
        steps.append({
            "id": row["name"],
            "action": "key-reference",
            "reason": "name only; unmanaged probe phase not started",
        })
    return steps


def catalog_summary(catalog: Catalog) -> dict[str, Any]:
    by_class: dict[str, int] = {}
    for row in catalog.components:
        by_class[row["class"]] = by_class.get(row["class"], 0) + 1
    return {
        "path": str(catalog.path),
        "schema_version": catalog.data.get("schema_version"),
        "components": len(catalog.components),
        "keys": len(catalog.keys),
        "logins": len(catalog.logins),
        "by_class": by_class,
        "provenance": catalog.provenance,
    }
