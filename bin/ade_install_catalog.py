"""Pure install-catalog validation, schema projection and metadata mapping.

No files, environment, runtime imports or effects. Legacy Catalog shape remains
an adapter boundary; effective config nests install metadata and names keys.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

COMPONENT_CLASSES = frozenset({"hard", "offered", "optional", "suggested", "never"})
JOB_CLASSES = frozenset({"hard", "offered", "optional"})
JOB_KINDS = frozenset({"ade-sched", "paseo", "service"})
PASEO_MODES = frozenset({"auto", "auto-review"})
CHOICE_CLASSES = frozenset({"offered", "optional", "suggested"})


class CatalogValidationError(ValueError):
    """Invalid catalog metadata; callers retain their own public error types."""


def effective_schema_parts(legacy: dict[str, Any]) -> dict[str, Any]:
    """Inline catalog subtrees using only the bounded evaluator's keywords."""
    props = legacy["properties"]
    install = copy.deepcopy(props["install"])
    install["properties"].update({
        "component": copy.deepcopy(props["component"]),
        "login": copy.deepcopy(props["login"]),
    })
    key = copy.deepcopy(props["key"]["items"])
    key["properties"].pop("name")
    key["required"] = [name for name in key.get("required", []) if name != "name"]
    return {"install": install, "keys": {"type": "object", "additionalProperties": key}}


def project_catalog(legacy: dict[str, Any]) -> dict[str, Any]:
    """Project already validated legacy rows, rejecting identities before mapping."""
    validate_catalog_semantics(legacy, path=Path("install catalog"))
    install = copy.deepcopy(legacy.get("install") or {})
    for key in ("component", "login"):
        if key in legacy:
            install[key] = copy.deepcopy(legacy[key])
    keys = {
        row["name"]: copy.deepcopy({k: v for k, v in row.items() if k != "name"})
        for row in legacy.get("key", [])
    }
    return {"install": install, "keys": keys}


def catalog_from_effective(data: dict[str, Any]) -> dict[str, Any]:
    """Adapt effective metadata to existing Catalog consumers without new authority."""
    out: dict[str, Any] = {"schema_version": 1}
    if "install" in data:
        install = data["install"]
        if not isinstance(install, dict):
            raise CatalogValidationError("install must be a table")
        for key in ("component", "login"):
            if key in install:
                out[key] = copy.deepcopy(install[key])
        jobs = {key: copy.deepcopy(install[key]) for key in ("jobs", "retired_jobs") if key in install}
        if jobs:
            out["install"] = jobs
    if "keys" in data:
        keys = data["keys"]
        if not isinstance(keys, dict):
            raise CatalogValidationError("keys must be a table")
        rows = []
        for name, metadata in keys.items():
            if not isinstance(name, str) or not name or not isinstance(metadata, dict):
                raise CatalogValidationError("keys identities must name metadata tables")
            if "name" in metadata:
                raise CatalogValidationError("keys metadata must not override its table identity")
            rows.append({"name": name, **copy.deepcopy(metadata)})
        if rows:
            out["key"] = rows
    return out


def validate_effective_catalog(data: dict[str, Any], *, path: Path) -> None:
    """Validate any provided domain without requiring unrelated missing domains."""
    validate_catalog_semantics(catalog_from_effective(data), path=path, require_components=False)


def _reject_duplicate_ids(rows: list[dict[str, Any]], *, key: str, label: str) -> None:
    seen: dict[str, int] = {}
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise CatalogValidationError(f"{label}[{i}]: must be a table")
        name = row.get(key)
        if not isinstance(name, str) or not name:
            raise CatalogValidationError(f"{label}[{i}]: missing {key}")
        if name in seen:
            raise CatalogValidationError(f"{label}: duplicate {key} {name!r} (entries {seen[name]} and {i})")
        seen[name] = i


def _validate_argv_field(
    row: dict[str, Any],
    *,
    field: str,
    path: Path,
    index: int,
    row_kind: str = "component",
    row_id_key: str = "id",
) -> None:
    val = row.get(field)
    if val is None:
        return
    label = f"{path}: {row_kind}[{index}] {row_id_key}={row.get(row_id_key)!r}"
    if not isinstance(val, list) or not val:
        raise CatalogValidationError(f"{label}: {field} must be a non-empty array of strings")
    for j, part in enumerate(val):
        if not isinstance(part, str) or not part:
            raise CatalogValidationError(f"{label}.{field}[{j}] must be a non-empty string")
        if any(ch in part for ch in ("\0", "\n", "\r")):
            raise CatalogValidationError(f"{label}.{field}[{j}]: control characters refused")


def validate_catalog_semantics(
    data: dict[str, Any], *, path: Path, require_components: bool = True,
) -> None:
    components = data.get("component") or []
    if not isinstance(components, list) or (not components and (require_components or "component" in data)):
        raise CatalogValidationError(f"{path}: component array is required and must be non-empty")
    _reject_duplicate_ids(components, key="id", label=f"{path} component")
    for i, row in enumerate(components):
        cls = row.get("class")
        if cls not in COMPONENT_CLASSES:
            raise CatalogValidationError(
                f"{path}: component[{i}] id={row.get('id')!r}: "
                f"class must be one of {sorted(COMPONENT_CLASSES)}, got {cls!r}"
            )
        if cls in CHOICE_CLASSES and "chosen" not in row:
            raise CatalogValidationError(
                f"{path}: component[{i}] id={row.get('id')!r}: "
                f"class {cls!r} requires an explicit chosen boolean"
            )
        if cls == "hard" and row.get("chosen") is False:
            raise CatalogValidationError(
                f"{path}: component[{i}] id={row.get('id')!r}: hard components cannot set chosen=false"
            )
        for field in ("install", "update", "probe"):
            val = row.get(field)
            if val is not None and not isinstance(val, str):
                raise CatalogValidationError(f"{path}: component[{i}].{field} must be a string")
        _validate_argv_field(row, field="install_argv", path=path, index=i)
        _validate_argv_field(row, field="update_argv", path=path, index=i)
        _validate_argv_field(row, field="probe_argv", path=path, index=i)
        _validate_argv_field(row, field="system_argv", path=path, index=i)
        _validate_argv_field(row, field="system_argv_darwin", path=path, index=i)
        ns = row.get("needs_system")
        if ns is not None and not isinstance(ns, bool):
            raise CatalogValidationError(
                f"{path}: component[{i}] id={row.get('id')!r}: needs_system must be a boolean"
            )
        if (row.get("system_argv") or row.get("system_argv_darwin")) and not ns:
            raise CatalogValidationError(
                f"{path}: component[{i}] id={row.get('id')!r}: "
                "system_argv / system_argv_darwin require needs_system=true"
            )
        pp = row.get("paseo_plugin")
        if pp is not None:
            if not isinstance(pp, str) or not pp.strip():
                raise CatalogValidationError(
                    f"{path}: component[{i}] id={row.get('id')!r}: "
                    "paseo_plugin must be a non-empty string plugin id"
                )
            if row.get("install_argv"):
                raise CatalogValidationError(
                    f"{path}: component[{i}] id={row.get('id')!r}: "
                    "paseo_plugin observe-only rows must not set install_argv "
                    "(doctor/apply never install or enable)"
                )
    keys = data.get("key") or []
    if keys:
        if not isinstance(keys, list):
            raise CatalogValidationError(f"{path}: key must be an array of tables")
        _reject_duplicate_ids(keys, key="name", label=f"{path} key")
        for i, row in enumerate(keys):
            _validate_argv_field(
                row,
                field="verify_argv",
                path=path,
                index=i,
                row_kind="key",
                row_id_key="name",
            )
    logins = data.get("login") or []
    if logins:
        if not isinstance(logins, list):
            raise CatalogValidationError(f"{path}: login must be an array of tables")
        _reject_duplicate_ids(logins, key="id", label=f"{path} login")
    _validate_install_jobs(data, path=path)


def _validate_install_jobs(data: dict[str, Any], *, path: Path) -> None:
    install = data.get("install")
    if install is None:
        return
    if not isinstance(install, dict):
        raise CatalogValidationError(f"{path}: install must be a table")
    jobs = install.get("jobs") or []
    retired = install.get("retired_jobs") or []
    if jobs and not isinstance(jobs, list):
        raise CatalogValidationError(f"{path}: install.jobs must be an array of tables")
    if retired and not isinstance(retired, list):
        raise CatalogValidationError(f"{path}: install.retired_jobs must be an array of tables")
    if isinstance(jobs, list) and jobs:
        _reject_duplicate_ids(jobs, key="name", label=f"{path} install.jobs")
    if isinstance(retired, list) and retired:
        _reject_duplicate_ids(retired, key="name", label=f"{path} install.retired_jobs")
    for i, row in enumerate(jobs if isinstance(jobs, list) else []):
        name = row.get("name")
        kind = row.get("kind")
        if kind not in JOB_KINDS:
            raise CatalogValidationError(
                f"{path}: install.jobs[{i}] name={name!r}: "
                f"kind must be one of {sorted(JOB_KINDS)}, got {kind!r}"
            )
        owner = row.get("owner")
        if not isinstance(owner, str) or not owner:
            raise CatalogValidationError(f"{path}: install.jobs[{i}] name={name!r}: owner required")
        cls = row.get("class")
        if cls not in JOB_CLASSES:
            raise CatalogValidationError(
                f"{path}: install.jobs[{i}] name={name!r}: "
                f"class must be one of {sorted(JOB_CLASSES)}, got {cls!r}"
            )
        if cls in CHOICE_CLASSES and "chosen" not in row:
            raise CatalogValidationError(
                f"{path}: install.jobs[{i}] name={name!r}: "
                f"class {cls!r} requires an explicit chosen boolean"
            )
        if cls == "hard" and row.get("chosen") is False:
            raise CatalogValidationError(
                f"{path}: install.jobs[{i}] name={name!r}: hard jobs cannot set chosen=false"
            )
        if kind == "paseo":
            mode = row.get("mode")
            if mode not in PASEO_MODES:
                raise CatalogValidationError(
                    f"{path}: install.jobs[{i}] name={name!r}: "
                    f"paseo jobs require mode in {sorted(PASEO_MODES)}, got {mode!r}"
                )
            if not row.get("label"):
                raise CatalogValidationError(
                    f"{path}: install.jobs[{i}] name={name!r}: paseo jobs require label"
                )
            for key in ("timezone", "provider", "cwd", "prompt"):
                val = row.get(key)
                if val is None:
                    continue
                if not isinstance(val, str) or not val.strip():
                    raise CatalogValidationError(
                        f"{path}: install.jobs[{i}] name={name!r}: "
                        f"paseo {key} must be a non-empty string when set"
                    )
        if kind == "ade-sched" and row.get("plist"):
            plist = row["plist"]
            if not isinstance(plist, str) or plist.startswith("/") or ".." in Path(plist).parts:
                raise CatalogValidationError(
                    f"{path}: install.jobs[{i}] name={name!r}: "
                    "plist must be a relative path without .."
                )
        sets = row.get("set")
        if sets is not None:
            if not isinstance(sets, list) or not sets:
                raise CatalogValidationError(
                    f"{path}: install.jobs[{i}] name={name!r}: set must be a non-empty string array"
                )
            for j, item in enumerate(sets):
                if not isinstance(item, str) or "=" not in item:
                    raise CatalogValidationError(
                        f"{path}: install.jobs[{i}] name={name!r}: "
                        f"set[{j}] must be KEY=VALUE"
                    )
    for i, row in enumerate(retired if isinstance(retired, list) else []):
        kind = row.get("kind")
        if kind not in JOB_KINDS:
            raise CatalogValidationError(
                f"{path}: install.retired_jobs[{i}] name={row.get('name')!r}: "
                f"kind must be one of {sorted(JOB_KINDS)}, got {kind!r}"
            )
        if not isinstance(row.get("owner"), str) or not row.get("owner"):
            raise CatalogValidationError(
                f"{path}: install.retired_jobs[{i}] name={row.get('name')!r}: owner required"
            )
        if not row.get("label"):
            raise CatalogValidationError(
                f"{path}: install.retired_jobs[{i}] name={row.get('name')!r}: label required"
            )

