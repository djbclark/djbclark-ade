"""ade_install: install catalog, plan, observe-only doctor/keys, bounded apply.

Transitional source: ``config/install.toml`` when ``config/ade.toml`` is absent.
Key entries are names and metadata only. Doctor runs ``paseo_plugin`` probes
(``paseo plugin ls --json`` → ok/disabled/missing; never install/enable), else
``probe_argv`` when recorded (else PATH presence), checks live Claude
``context_size_nudge`` hook registration against ``agents/claude/settings.json.tmpl``
when that template is present under ``--root``, probes the Carried #14 credential
vault delete-after (WARN approaching / FAIL past; never deletes), and never
repairs or mutates ``~/.claude/settings.json`` (order 11). ``keys`` runs
``sudo-secretspec check`` for bulk presence, then per-key ``verify_argv`` probes
under ``sudo-secretspec run`` when recorded (no get/export/set; never prints
values). Apply defaults to dry-run; ``--yes`` executes user ``install_argv``
(argv lists, never shell=True); ``paseo_plugin`` rows are always skipped/blocked.
``--system --dry-run`` / ``--print-system-argv`` preview ``system_argv``. Live
``system_argv`` needs ``--yes --system --apply-system`` (opt-in; default refuse).
Secrets are never read. A full apply (no ``--id``) also runs ``ade-sched reconcile`` for ADE-owned labeled jobs unless ``--no-reconcile-sched``.
"""
from __future__ import annotations

import copy
import datetime
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

BIN = Path(__file__).resolve().parent
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import ade_config as ac  # noqa: E402

SCHEMA_VERSION = 1
LEDGER_SCHEMA_VERSION = 1
KEYS_STATE_SCHEMA_VERSION = 1
UNKNOWN = "UNKNOWN"
COMPONENT_CLASSES = frozenset({"hard", "offered", "optional", "suggested", "never"})
JOB_CLASSES = frozenset({"hard", "offered", "optional"})
JOB_KINDS = frozenset({"ade-sched", "paseo", "service"})
PASEO_MODES = frozenset({"auto", "auto-review"})
# Classes that require an explicit chosen bool in the catalog.
CHOICE_CLASSES = frozenset({"offered", "optional", "suggested"})
# ADE may reconcile these later; every other owner is report-only (never unload).
OWNER_ADE = "djbclark-ade"

# Placeholders expanded in install_argv / update_argv / probe_argv / verify_argv.
ARGV_TOKENS = ("{bin}", "{root}", "{home}", "{prefix}")

# Live Claude settings vs agents/claude/settings.json.tmpl (queue Carried #11).
CONTEXT_SIZE_NUDGE = "context_size_nudge.py"
CLAUDE_SETTINGS_TMPL = Path("agents") / "claude" / "settings.json.tmpl"
_TMPL_TAG = re.compile(r"\{\{.*?\}\}", re.DOTALL)

# Exit contract for recorded key verify_argv probes (under sudo-secretspec run).
# Probes must not print secret values; ade-install never echoes probe stdout/stderr
# except a narrow ADE_KEY_VERIFY marker for expiring dates.
VERIFY_EXIT_OK = 0
VERIFY_EXIT_INVALID = 10
VERIFY_EXIT_NO_QUOTA = 11
VERIFY_EXIT_UNREACHABLE = 12
VERIFY_EXIT_EXPIRING = 13
VERIFY_EXIT_MISSING = 14
VERIFY_STATUS_BY_EXIT: dict[int, str] = {
    VERIFY_EXIT_OK: "ok",
    VERIFY_EXIT_INVALID: "invalid",
    VERIFY_EXIT_NO_QUOTA: "no-quota",
    VERIFY_EXIT_UNREACHABLE: "unreachable",
    VERIFY_EXIT_EXPIRING: "expiring",
    VERIFY_EXIT_MISSING: "missing",
}
VERIFY_FAIL_STATUSES = frozenset(
    {"invalid", "no-quota", "unreachable", "missing", "error"}
)
VERIFY_MARKER_PREFIX = "ADE_KEY_VERIFY:"
VERIFY_ALLOWED_MARKERS = frozenset(
    {"ok", "invalid", "no-quota", "unreachable", "missing", "expiring"}
)

# Carried queue #14: credential vault moved 2026-10-20; delete-after 2026-11-19
# (docs/queue.md, docs/history/ade-everywhere-inventory-2026-10-20-stores.md).
# Doctor WARNs inside the lead window and FAILs on/after the date while the
# vault directory still exists. Doctor never deletes and never reads contents.
CREDENTIAL_BAK_DELETE_AFTER = datetime.date(2026, 11, 19)
CREDENTIAL_BAK_WARN_LEAD_DAYS = 14

Runner = Callable[[list[str], Path], "subprocess.CompletedProcess[str]"]


class InstallError(ac.ConfigError):
    """Invalid install catalog or refused operation."""


@dataclass
class Catalog:
    data: dict[str, Any]
    path: Path
    provenance: dict[str, Any] = field(default_factory=dict)
    root: Path = field(default_factory=Path)

    @property
    def components(self) -> list[dict[str, Any]]:
        return list(self.data.get("component") or [])

    @property
    def keys(self) -> list[dict[str, Any]]:
        return list(self.data.get("key") or [])

    @property
    def logins(self) -> list[dict[str, Any]]:
        return list(self.data.get("login") or [])

    @property
    def jobs(self) -> list[dict[str, Any]]:
        install = self.data.get("install") or {}
        if not isinstance(install, dict):
            return []
        return list(install.get("jobs") or [])

    @property
    def retired_jobs(self) -> list[dict[str, Any]]:
        install = self.data.get("install") or {}
        if not isinstance(install, dict):
            return []
        return list(install.get("retired_jobs") or [])


@dataclass(frozen=True)
class Observation:
    kind: str  # component | key | login | catalog | settings | job | retired-job | vault | pools
    id: str
    status: str  # ok | missing | disabled | unknown | error | unchosen | never | planned | present | foreign | warn
    detail: str


@dataclass(frozen=True)
class ApplyStep:
    id: str
    action: str  # would-install | install | skip | blocked | refuse-system
    argv: list[str] | None
    reason: str
    detail: str = ""


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parent.parent


def default_install_path(root: Path) -> Path:
    return root / "config" / "install.toml"


def default_install_schema_path(root: Path) -> Path:
    return root / "config" / "install.schema.json"


def default_new_config_path(root: Path) -> Path:
    return ac.default_new_config_path(root)


def default_state_dir() -> Path:
    env = os.environ.get("ADE_INSTALL_STATE_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".local" / "state" / "djbclark-ade" / "install"


def default_keys_state_path() -> Path:
    """Atomic outcomes file for ``ade-install keys`` (no values, no hashes)."""
    env = os.environ.get("ADE_KEYS_STATE_PATH")
    if env:
        return Path(env).expanduser()
    install = default_state_dir()
    if install.name == "install":
        return install.parent / "keys.json"
    return install / "keys.json"


def default_prefix() -> Path:
    env = os.environ.get("ADE_INSTALL_PREFIX")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".local" / "bin"


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
        raise InstallError(f"{label}: {field} must be a non-empty array of strings")
    for j, part in enumerate(val):
        if not isinstance(part, str) or not part:
            raise InstallError(f"{label}.{field}[{j}] must be a non-empty string")
        if any(ch in part for ch in ("\0", "\n", "\r")):
            raise InstallError(f"{label}.{field}[{j}]: control characters refused")


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
        _validate_argv_field(row, field="install_argv", path=path, index=i)
        _validate_argv_field(row, field="update_argv", path=path, index=i)
        _validate_argv_field(row, field="probe_argv", path=path, index=i)
        _validate_argv_field(row, field="system_argv", path=path, index=i)
        _validate_argv_field(row, field="system_argv_darwin", path=path, index=i)
        ns = row.get("needs_system")
        if ns is not None and not isinstance(ns, bool):
            raise InstallError(
                f"{path}: component[{i}] id={row.get('id')!r}: needs_system must be a boolean"
            )
        if (row.get("system_argv") or row.get("system_argv_darwin")) and not ns:
            raise InstallError(
                f"{path}: component[{i}] id={row.get('id')!r}: "
                "system_argv / system_argv_darwin require needs_system=true"
            )
        pp = row.get("paseo_plugin")
        if pp is not None:
            if not isinstance(pp, str) or not pp.strip():
                raise InstallError(
                    f"{path}: component[{i}] id={row.get('id')!r}: "
                    "paseo_plugin must be a non-empty string plugin id"
                )
            if row.get("install_argv"):
                raise InstallError(
                    f"{path}: component[{i}] id={row.get('id')!r}: "
                    "paseo_plugin observe-only rows must not set install_argv "
                    "(doctor/apply never install or enable)"
                )
    keys = data.get("key") or []
    if keys:
        if not isinstance(keys, list):
            raise InstallError(f"{path}: key must be an array of tables")
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
            raise InstallError(f"{path}: login must be an array of tables")
        _reject_duplicate_ids(logins, key="id", label=f"{path} login")
    _validate_install_jobs(data, path=path)


def _validate_install_jobs(data: dict[str, Any], *, path: Path) -> None:
    install = data.get("install")
    if install is None:
        return
    if not isinstance(install, dict):
        raise InstallError(f"{path}: install must be a table")
    jobs = install.get("jobs") or []
    retired = install.get("retired_jobs") or []
    if jobs and not isinstance(jobs, list):
        raise InstallError(f"{path}: install.jobs must be an array of tables")
    if retired and not isinstance(retired, list):
        raise InstallError(f"{path}: install.retired_jobs must be an array of tables")
    if isinstance(jobs, list) and jobs:
        _reject_duplicate_ids(jobs, key="name", label=f"{path} install.jobs")
    if isinstance(retired, list) and retired:
        _reject_duplicate_ids(retired, key="name", label=f"{path} install.retired_jobs")
    for i, row in enumerate(jobs if isinstance(jobs, list) else []):
        name = row.get("name")
        kind = row.get("kind")
        if kind not in JOB_KINDS:
            raise InstallError(
                f"{path}: install.jobs[{i}] name={name!r}: "
                f"kind must be one of {sorted(JOB_KINDS)}, got {kind!r}"
            )
        owner = row.get("owner")
        if not isinstance(owner, str) or not owner:
            raise InstallError(f"{path}: install.jobs[{i}] name={name!r}: owner required")
        cls = row.get("class")
        if cls not in JOB_CLASSES:
            raise InstallError(
                f"{path}: install.jobs[{i}] name={name!r}: "
                f"class must be one of {sorted(JOB_CLASSES)}, got {cls!r}"
            )
        if cls in CHOICE_CLASSES and "chosen" not in row:
            raise InstallError(
                f"{path}: install.jobs[{i}] name={name!r}: "
                f"class {cls!r} requires an explicit chosen boolean"
            )
        if cls == "hard" and row.get("chosen") is False:
            raise InstallError(
                f"{path}: install.jobs[{i}] name={name!r}: hard jobs cannot set chosen=false"
            )
        if kind == "paseo":
            mode = row.get("mode")
            if mode not in PASEO_MODES:
                raise InstallError(
                    f"{path}: install.jobs[{i}] name={name!r}: "
                    f"paseo jobs require mode in {sorted(PASEO_MODES)}, got {mode!r}"
                )
            if not row.get("label"):
                raise InstallError(
                    f"{path}: install.jobs[{i}] name={name!r}: paseo jobs require label"
                )
            for key in ("timezone", "provider", "cwd", "prompt"):
                val = row.get(key)
                if val is None:
                    continue
                if not isinstance(val, str) or not val.strip():
                    raise InstallError(
                        f"{path}: install.jobs[{i}] name={name!r}: "
                        f"paseo {key} must be a non-empty string when set"
                    )
        if kind == "ade-sched" and row.get("plist"):
            plist = row["plist"]
            if not isinstance(plist, str) or plist.startswith("/") or ".." in Path(plist).parts:
                raise InstallError(
                    f"{path}: install.jobs[{i}] name={name!r}: "
                    "plist must be a relative path without .."
                )
        sets = row.get("set")
        if sets is not None:
            if not isinstance(sets, list) or not sets:
                raise InstallError(
                    f"{path}: install.jobs[{i}] name={name!r}: set must be a non-empty string array"
                )
            for j, item in enumerate(sets):
                if not isinstance(item, str) or "=" not in item:
                    raise InstallError(
                        f"{path}: install.jobs[{i}] name={name!r}: "
                        f"set[{j}] must be KEY=VALUE"
                    )
    for i, row in enumerate(retired if isinstance(retired, list) else []):
        kind = row.get("kind")
        if kind not in JOB_KINDS:
            raise InstallError(
                f"{path}: install.retired_jobs[{i}] name={row.get('name')!r}: "
                f"kind must be one of {sorted(JOB_KINDS)}, got {kind!r}"
            )
        if not isinstance(row.get("owner"), str) or not row.get("owner"):
            raise InstallError(
                f"{path}: install.retired_jobs[{i}] name={row.get('name')!r}: owner required"
            )
        if not row.get("label"):
            raise InstallError(
                f"{path}: install.retired_jobs[{i}] name={row.get('name')!r}: label required"
            )


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
    return Catalog(data=copy.deepcopy(raw), path=path, provenance=provenance, root=root)


def expected_installed(row: dict[str, Any]) -> bool:
    """Whether doctor expects this component to be present on the machine."""
    cls = row["class"]
    if cls == "hard":
        return True
    if cls in ("offered", "optional"):
        return bool(row.get("chosen"))
    return False  # suggested / never


def _probe_executable_missing(argv0: str) -> bool:
    """True when argv0 is neither an existing path nor findable on PATH."""
    p = Path(argv0)
    if p.is_file():
        return False
    return shutil.which(argv0) is None


def _paseo_plugin_rows(payload: Any) -> list[dict[str, Any]]:
    """Normalize ``paseo plugin ls --json`` into a list of plugin objects."""
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict):
        for key in ("plugins", "items", "data"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return [p for p in inner if isinstance(p, dict)]
        # Single plugin object.
        if any(k in payload for k in ("id", "name", "pluginId", "plugin_id")):
            return [payload]
    return []


def _paseo_plugin_id(row: dict[str, Any]) -> str:
    for key in ("id", "pluginId", "plugin_id", "name"):
        val = row.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _paseo_plugin_enabled(row: dict[str, Any]) -> bool | None:
    """True/False when the row states enablement; None when unknown."""
    if "enabled" in row:
        en = row.get("enabled")
        if isinstance(en, bool):
            return en
        if isinstance(en, str):
            low = en.strip().lower()
            if low in ("enabled", "true", "yes", "on", "1"):
                return True
            if low in ("disabled", "false", "no", "off", "0"):
                return False
    status = row.get("status")
    if isinstance(status, str):
        low = status.strip().lower()
        if low in ("running", "enabled", "active", "ok"):
            return True
        if low in ("disabled", "stopped", "inactive", "off"):
            return False
    return None


def observe_paseo_plugin(
    component_id: str,
    plugin_id: str,
    *,
    root: Path | None = None,
    runner: Runner | None = None,
    probe_timeout_s: float = 15.0,
) -> Observation:
    """Observe a Paseo plugin via ``paseo plugin ls --json``. Never installs or enables.

    Statuses: ``ok`` (installed and enabled/running), ``disabled`` (installed but not
    enabled), ``missing`` (not installed / paseo absent), ``error`` (ls failed).
    """
    root = (root or repo_root_from_here()).resolve()
    argv = ["paseo", "plugin", "ls", "--json"]
    if _probe_executable_missing(argv[0]):
        return Observation(
            "component", component_id, "missing",
            f"paseo plugin {plugin_id!r}: paseo not on PATH (observe-only; never install/enable)",
        )
    run = runner or (
        lambda a, cwd: _default_runner(a, cwd, timeout_s=probe_timeout_s)
    )
    try:
        proc = run(argv, root)
    except subprocess.TimeoutExpired:
        return Observation(
            "component", component_id, "error",
            f"paseo plugin {plugin_id!r}: ls timed out after {probe_timeout_s}s",
        )
    except OSError as e:
        return Observation(
            "component", component_id, "error",
            f"paseo plugin {plugin_id!r}: ls exec error: {e}",
        )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = err[0][:200] if err else f"exit {proc.returncode}"
        # Treat a missing daemon / empty install the same as missing plugin when
        # the CLI cannot list plugins at all (common on CI / Cloud without Paseo).
        low = detail.lower()
        if "not found" in low or "no such" in low or "daemon" in low:
            return Observation(
                "component", component_id, "missing",
                f"paseo plugin {plugin_id!r}: not listable ({detail}); "
                "observe-only; never install/enable",
            )
        return Observation(
            "component", component_id, "error",
            f"paseo plugin {plugin_id!r}: ls failed: {detail}",
        )
    text = (proc.stdout or "").strip()
    if not text:
        return Observation(
            "component", component_id, "missing",
            f"paseo plugin {plugin_id!r}: empty ls --json; observe-only; never install/enable",
        )
    # Tolerate preamble before the JSON payload (same pattern as route_agent).
    start = text.find("{")
    start_arr = text.find("[")
    if start_arr >= 0 and (start < 0 or start_arr < start):
        start = start_arr
    if start < 0:
        return Observation(
            "component", component_id, "error",
            f"paseo plugin {plugin_id!r}: ls --json had no JSON object/array",
        )
    try:
        payload = json.loads(text[start:])
    except ValueError as e:
        return Observation(
            "component", component_id, "error",
            f"paseo plugin {plugin_id!r}: ls --json unreadable ({e})",
        )
    want = plugin_id.strip()
    match: dict[str, Any] | None = None
    for prow in _paseo_plugin_rows(payload):
        if _paseo_plugin_id(prow) == want:
            match = prow
            break
    if match is None:
        return Observation(
            "component", component_id, "missing",
            f"paseo plugin {plugin_id!r}: not installed "
            "(observe-only; operator may `paseo plugin install`; never auto-enable)",
        )
    enabled = _paseo_plugin_enabled(match)
    status_raw = match.get("status")
    if enabled is False or (
        enabled is None
        and isinstance(status_raw, str)
        and status_raw.strip().lower() in ("disabled", "stopped", "inactive", "off")
    ):
        return Observation(
            "component", component_id, "disabled",
            f"paseo plugin {plugin_id!r}: installed but disabled "
            "(observe-only; never enable via ade-install)",
        )
    if enabled is True:
        snippet = (
            status_raw if isinstance(status_raw, str) and status_raw.strip() else "enabled"
        )
        return Observation(
            "component", component_id, "ok",
            f"paseo plugin {plugin_id!r}: {snippet}",
        )
    # Installed but enablement unknown: surface as disabled so doctor never
    # treats an ambiguous install as healthy, and never enables it.
    return Observation(
        "component", component_id, "disabled",
        f"paseo plugin {plugin_id!r}: installed but enablement unknown "
        "(observe-only; never enable via ade-install)",
    )


def observe_component(
    row: dict[str, Any],
    *,
    root: Path | None = None,
    runner: Runner | None = None,
    probe_timeout_s: float = 15.0,
) -> Observation:
    """Observe one component. Never repairs.

    ``paseo_plugin`` rows always probe ``paseo plugin ls`` (missing/disabled/ok)
    and never install or enable. Otherwise prefer ``probe_argv``; else PATH
    ``presence``.
    """
    cid = str(row["id"])
    cls = str(row["class"])
    if cls == "never":
        return Observation("component", cid, "never", "recorded as never-installed")

    paseo_plugin = row.get("paseo_plugin")
    if isinstance(paseo_plugin, str) and paseo_plugin.strip():
        # Always observe, even when unchosen: doctor must distinguish missing
        # from disabled from not-chosen catalog rows without installing.
        return observe_paseo_plugin(
            cid,
            paseo_plugin.strip(),
            root=root,
            runner=runner,
            probe_timeout_s=probe_timeout_s,
        )

    if cls == "suggested" and not row.get("chosen"):
        return Observation("component", cid, "unchosen", "suggested only; not chosen")
    if cls in CHOICE_CLASSES and not row.get("chosen"):
        return Observation("component", cid, "unchosen", f"{cls} component not chosen")
    if not expected_installed(row):
        return Observation("component", cid, "unchosen", "not expected on this machine")

    probe_argv = row.get("probe_argv")
    if isinstance(probe_argv, list) and probe_argv:
        root = (root or repo_root_from_here()).resolve()
        try:
            argv = expand_argv(list(probe_argv), root=root)
        except InstallError as e:
            return Observation("component", cid, "error", str(e))
        if _probe_executable_missing(argv[0]):
            return Observation(
                "component", cid, "missing",
                f"probe binary not found: {argv[0]}",
            )
        run = runner or (
            lambda a, cwd: _default_runner(a, cwd, timeout_s=probe_timeout_s)
        )
        try:
            proc = run(argv, root)
        except subprocess.TimeoutExpired:
            return Observation(
                "component", cid, "error",
                f"probe timed out after {probe_timeout_s}s: {shlex.join(argv)}",
            )
        except OSError as e:
            return Observation("component", cid, "error", f"probe exec error: {e}")
        if proc.returncode == 0:
            out = (proc.stdout or proc.stderr or "").strip().splitlines()
            snippet = out[0][:120] if out else "exit 0"
            return Observation(
                "component", cid, "ok",
                f"probe ok ({shlex.join(argv)}): {snippet}",
            )
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = err[0][:200] if err else f"exit {proc.returncode}"
        return Observation(
            "component", cid, "error",
            f"probe failed ({shlex.join(argv)}): {detail}",
        )

    presence = row.get("presence")
    if not presence or presence == UNKNOWN:
        return Observation(
            "component", cid, "unknown",
            "no probe_argv or presence basename recorded; not treated as healthy or absent",
        )
    found = shutil.which(str(presence))
    if found:
        return Observation("component", cid, "ok", f"found on PATH: {found}")
    return Observation("component", cid, "missing", f"not on PATH: {presence}")


def observe_key(row: dict[str, Any]) -> Observation:
    name = str(row["name"])
    verify = row.get("verify") or UNKNOWN
    expiry = row.get("expiry") or "unknown"
    has_argv = isinstance(row.get("verify_argv"), list) and bool(row.get("verify_argv"))
    if has_argv:
        detail = (
            f"verify_argv recorded; verify={verify}; expiry={expiry} "
            "(probe deferred; no value read)"
        )
    else:
        detail = f"reference only; verify={verify}; expiry={expiry} (no value read)"
    return Observation("key", name, "unknown", detail)


def observe_login(row: dict[str, Any]) -> Observation:
    lid = str(row["id"])
    cmd = row.get("command") or UNKNOWN
    if cmd == UNKNOWN:
        return Observation("login", lid, "unknown", "login command not recorded")
    return Observation("login", lid, "unknown", f"login check recorded as {cmd!r}; not executed")


def default_claude_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _hook_events_registering(settings: dict[str, Any], needle: str) -> set[str]:
    """Hook event names whose command strings mention ``needle``."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return set()
    found: set[str] = set()
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for hook in entry.get("hooks") or []:
                if not isinstance(hook, dict):
                    continue
                cmd = hook.get("command") or ""
                if isinstance(cmd, str) and needle in cmd:
                    found.add(str(event))
                    break
    return found


def load_claude_settings_json(path: Path, *, template: bool = False) -> dict[str, Any]:
    """Parse Claude settings JSON; mask ``{{ … }}`` tags when reading a template."""
    text = path.read_text(encoding="utf-8")
    if template:
        text = _TMPL_TAG.sub("/placeholder", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise json.JSONDecodeError("settings root must be an object", text, 0)
    return data


def context_size_nudge_fix_hint(
    live: Path,
    expected: set[str],
    actual: set[str],
) -> str:
    """Human-readable missing-registration detail with a hand-apply hint (order 11)."""
    missing = sorted(expected - actual)
    have = ", ".join(sorted(actual)) if actual else "(none)"
    want = ", ".join(sorted(expected))
    miss = ", ".join(missing) if missing else want
    return (
        f"{CONTEXT_SIZE_NUDGE} missing under hooks.{{{miss}}} in {live} "
        f"(have {have}; template expects {want}). "
        f"Apply by hand (order 11): copy the matching hook-deadline entries from "
        f"agents/claude/settings.json.tmpl into {live}; "
        f"`ade-install doctor` / `just install-doctor` never mutates live settings."
    )


def observe_context_size_nudge(
    *,
    root: Path,
    settings_path: Path | None = None,
    template_path: Path | None = None,
) -> Observation | None:
    """Compare live Claude settings hook registration to the repo template.

    Returns None when the template is absent under ``root`` (fixture catalogs).
    Observe-only: never writes ``~/.claude/settings.json`` (order 11; queue #10).
    """
    tmpl = template_path if template_path is not None else root / CLAUDE_SETTINGS_TMPL
    if not tmpl.is_file():
        return None
    live = settings_path if settings_path is not None else default_claude_settings_path()
    try:
        expected = _hook_events_registering(
            load_claude_settings_json(tmpl, template=True),
            CONTEXT_SIZE_NUDGE,
        )
    except OSError as e:
        return Observation(
            "settings", "context_size_nudge", "error",
            f"template unreadable ({tmpl}): {e}",
        )
    except json.JSONDecodeError as e:
        return Observation(
            "settings", "context_size_nudge", "error",
            f"template JSON invalid ({tmpl}): {e}",
        )
    if not expected:
        return Observation(
            "settings", "context_size_nudge", "error",
            f"template {tmpl} has no {CONTEXT_SIZE_NUDGE} hook registration",
        )
    if not live.is_file():
        return Observation(
            "settings", "context_size_nudge", "missing",
            context_size_nudge_fix_hint(live, expected, set()),
        )
    try:
        actual = _hook_events_registering(
            load_claude_settings_json(live),
            CONTEXT_SIZE_NUDGE,
        )
    except OSError as e:
        return Observation(
            "settings", "context_size_nudge", "error",
            f"live settings unreadable ({live}): {e}",
        )
    except json.JSONDecodeError as e:
        return Observation(
            "settings", "context_size_nudge", "error",
            f"live settings JSON invalid ({live}): {e}",
        )
    if expected - actual:
        return Observation(
            "settings", "context_size_nudge", "missing",
            context_size_nudge_fix_hint(live, expected, actual),
        )
    return Observation(
        "settings", "context_size_nudge", "ok",
        f"{CONTEXT_SIZE_NUDGE} registered under {', '.join(sorted(actual))} in {live}",
    )

def default_credential_bak_path() -> Path:
    """Default path for the Carried #14 credential vault (never deleted by doctor)."""
    return Path.home() / ".local" / "state" / "ade" / "credential-bak"


def observe_credential_bak(
    *,
    today: datetime.date | None = None,
    path: Path | None = None,
    exists_fn: Callable[[Path], bool] | None = None,
) -> Observation:
    """Observe credential-bak delete-after (Carried #14 residual).

    Presence only (``Path.is_dir`` / injected ``exists_fn``). Never lists or
    reads vault contents, never deletes, never asks for sudo. Approaching the
    delete-after date → ``warn`` (doctor FAILs); on/after that date while still
    present → ``error`` (doctor FAILs). Absent → ``ok``.
    """
    day = today or datetime.date.today()
    vault = path if path is not None else default_credential_bak_path()
    try:
        present = exists_fn(vault) if exists_fn is not None else vault.is_dir()
    except OSError as e:
        return Observation(
            "vault",
            "credential-bak",
            "unknown",
            f"could not probe credential-bak at {vault}: {e}; doctor never deletes",
        )
    delete_after = CREDENTIAL_BAK_DELETE_AFTER
    warn_start = delete_after - datetime.timedelta(days=CREDENTIAL_BAK_WARN_LEAD_DAYS)
    if not present:
        return Observation(
            "vault",
            "credential-bak",
            "ok",
            f"credential-bak absent at {vault} "
            f"(delete-after {delete_after.isoformat()} satisfied or never created); "
            f"doctor never deletes",
        )
    if day >= delete_after:
        return Observation(
            "vault",
            "credential-bak",
            "error",
            f"credential-bak still present at {vault} on/after delete-after "
            f"{delete_after.isoformat()} (today {day.isoformat()}); "
            f"ask operator yes before deleting — doctor never deletes",
        )
    if day >= warn_start:
        days_left = (delete_after - day).days
        return Observation(
            "vault",
            "credential-bak",
            "warn",
            f"credential-bak still present at {vault}; delete-after "
            f"{delete_after.isoformat()} in {days_left} day(s) "
            f"(today {day.isoformat()}); ask operator yes after that date — "
            f"doctor never deletes",
        )
    days_left = (delete_after - day).days
    return Observation(
        "vault",
        "credential-bak",
        "ok",
        f"credential-bak present at {vault}; delete-after "
        f"{delete_after.isoformat()} ({days_left} day(s) away); "
        f"doctor never deletes",
    )


SECRETSPEC_CHECK_ARGV = [
    "sudo-secretspec",
    "check",
    "--reason",
    "ade-install keys",
]


def secretspec_verify_argv(name: str, probe_argv: list[str]) -> list[str]:
    """Build ``sudo-secretspec run -- …`` argv for one key verify probe.

    The key name appears only in ``--reason`` (not a secret). Probe argv must
    read the value from the injected environment, never from argv.
    """
    return [
        "sudo-secretspec",
        "run",
        "--reason",
        f"ade-install keys verify {name}",
        "--",
        *probe_argv,
    ]


def _parse_expiring_iso_date(raw: str) -> str | None:
    """Return ``YYYY-MM-DD`` when ``raw`` is exactly that calendar date.

    Docs require ``ADE_KEY_VERIFY:expiring:YYYY-MM-DD``. Refuse datetimes,
    free text, and credential-shaped payloads so they never reach detail
    or ``keys.json``.
    """
    text = (raw or "").strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        date.fromisoformat(text)
    except ValueError:
        return None
    return text


def _safe_verify_marker(stderr: str) -> tuple[str | None, str | None]:
    """Parse a narrow ADE_KEY_VERIFY marker from the first stderr line.

    Returns ``(status, expiring_date)``. Anything that is not an allowlisted
    token is ignored so probe output cannot leak into observations. An
    ``expiring:`` suffix keeps status ``expiring`` only when the date is a
    validated ISO calendar day; otherwise the date is dropped.
    """
    line = (stderr or "").strip().splitlines()
    if not line:
        return None, None
    first = line[0].strip()
    if not first.startswith(VERIFY_MARKER_PREFIX):
        return None, None
    rest = first[len(VERIFY_MARKER_PREFIX) :]
    if rest.startswith("expiring:"):
        return "expiring", _parse_expiring_iso_date(rest.split(":", 1)[1])
    if rest in VERIFY_ALLOWED_MARKERS:
        return rest, None
    return None, None


def classify_verify_result(
    returncode: int,
    *,
    stderr: str = "",
) -> tuple[str, str]:
    """Map probe exit code (+ optional marker) to status/detail. Never echoes bodies."""
    marker_status, expiring_date = _safe_verify_marker(stderr)
    status = VERIFY_STATUS_BY_EXIT.get(returncode)
    if status is None:
        status = "error"
    # Expiry marker may refine ok/expiring only; never override 10/11/12/14/…
    if marker_status == "expiring" and status in {"ok", "expiring"}:
        status = "expiring"
        if expiring_date:
            return status, f"verify expiring {expiring_date} (no value read)"
        return status, "verify expiring (no value read)"
    if status == "expiring":
        return status, "verify expiring (no value read)"
    if marker_status and marker_status != "expiring":
        # Marker may refine an otherwise opaque non-zero when exit is unmapped.
        if returncode not in VERIFY_STATUS_BY_EXIT:
            status = marker_status
    if status == "ok":
        return status, "verify ok under sudo-secretspec run (no value read)"
    if status == "error":
        return status, f"verify error (exit {returncode}; no value read)"
    return status, f"verify {status} (no value read)"


def observe_key_verify(
    row: dict[str, Any],
    *,
    root: Path,
    runner: Runner | None = None,
    timeout_s: float = 30.0,
) -> Observation:
    """Run one key's ``verify_argv`` under ``sudo-secretspec run``.

    Never calls get/export/set. Never prints or records secret values.
    """
    name = str(row["name"])
    raw_argv = row.get("verify_argv")
    if not isinstance(raw_argv, list) or not raw_argv:
        return observe_key(row)
    try:
        probe_argv = expand_argv(list(raw_argv), root=root)
    except InstallError as e:
        return Observation("key", name, "error", str(e))
    argv = secretspec_verify_argv(name, probe_argv)
    if _probe_executable_missing(argv[0]):
        return Observation(
            "key",
            name,
            "unknown",
            "sudo-secretspec not on PATH; cannot verify (no value read)",
        )
    run = runner or (lambda a, d: _default_runner(a, d, timeout_s=timeout_s))
    try:
        proc = run(argv, root)
    except subprocess.TimeoutExpired:
        return Observation(
            "key",
            name,
            "unreachable",
            f"verify timed out after {timeout_s}s (no value read)",
        )
    except OSError as e:
        return Observation("key", name, "error", f"verify exec error: {e}")
    status, detail = classify_verify_result(
        int(proc.returncode),
        stderr=proc.stderr or "",
    )
    return Observation("key", name, status, detail)


def observe_secretspec_check(
    *,
    runner: Runner | None = None,
    timeout_s: float = 30.0,
    cwd: Path | None = None,
) -> Observation:
    """Observe-only bulk presence check via ``sudo-secretspec check``.

    Never calls get/export/set. Does not print or request secret values.
    """
    if _probe_executable_missing(SECRETSPEC_CHECK_ARGV[0]):
        return Observation(
            "secretspec",
            "check",
            "unknown",
            "sudo-secretspec not on PATH; cannot check presence (no values read)",
        )
    run = runner or (lambda a, d: _default_runner(a, d, timeout_s=timeout_s))
    root = (cwd or Path.cwd()).resolve()
    try:
        proc = run(list(SECRETSPEC_CHECK_ARGV), root)
    except subprocess.TimeoutExpired:
        return Observation(
            "secretspec",
            "check",
            "error",
            f"sudo-secretspec check timed out after {timeout_s}s",
        )
    except OSError as e:
        return Observation("secretspec", "check", "error", f"exec error: {e}")
    # check exit: 0 = required credentials present; non-zero = missing/fail.
    # stdout/stderr may name keys; never treat as values. Truncate one line.
    if proc.returncode == 0:
        return Observation(
            "secretspec",
            "check",
            "ok",
            "sudo-secretspec check: required credentials present (no values read)",
        )
    err = (proc.stderr or proc.stdout or "").strip().splitlines()
    detail = err[0][:200] if err else f"exit {proc.returncode}"
    return Observation(
        "secretspec",
        "check",
        "missing",
        f"sudo-secretspec check failed: {detail}",
    )


def save_keys_state(
    path: Path,
    *,
    observations: list[Observation],
) -> Path:
    """Write verify/presence outcomes atomically. No values and no hashes."""
    keys: dict[str, Any] = {}
    for o in observations:
        if o.kind != "key":
            continue
        keys[o.id] = {
            "status": o.status,
            "detail": o.detail,
        }
    check = next((o for o in observations if o.kind == "secretspec"), None)
    out = {
        "schema_version": KEYS_STATE_SCHEMA_VERSION,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "secretspec_check": (
            {"status": check.status, "detail": check.detail} if check else None
        ),
        "keys": keys,
    }
    _atomic_write_json(path, out)
    return path


def keys_observe(
    catalog: Catalog,
    *,
    runner: Runner | None = None,
    timeout_s: float = 30.0,
    keys_state_path: Path | None = None,
) -> tuple[list[Observation], int]:
    """S3b keys path: bulk presence check, then per-key verify probes.

    Lists catalog key/login references, runs ``sudo-secretspec check`` when the
    binary exists, then runs each recorded ``verify_argv`` under
    ``sudo-secretspec run``. Exit 1 when check fails or any verify lands in
    ``VERIFY_FAIL_STATUSES``. Missing ``sudo-secretspec`` is ``unknown``
    (exit 0) so Linux/CI without the boundary stays observant. Never reads or
    prints secret values; outcomes go to ``keys.json``.
    """
    obs: list[Observation] = [
        Observation("catalog", str(catalog.path), "ok", "catalog validated"),
    ]
    for row in catalog.logins:
        obs.append(observe_login(row))
    check = observe_secretspec_check(
        runner=runner,
        timeout_s=timeout_s,
        cwd=catalog.root,
    )
    obs.append(check)
    can_run = check.status != "unknown"
    for row in catalog.keys:
        raw_argv = row.get("verify_argv")
        if can_run and isinstance(raw_argv, list) and raw_argv:
            obs.append(
                observe_key_verify(
                    row,
                    root=catalog.root,
                    runner=runner,
                    timeout_s=timeout_s,
                )
            )
        else:
            obs.append(observe_key(row))
    state_path = keys_state_path or default_keys_state_path()
    save_keys_state(state_path, observations=obs)
    rc = 0
    if check.status in ("missing", "error"):
        rc = 1
    for o in obs:
        if o.kind == "key" and o.status in VERIFY_FAIL_STATUSES:
            rc = 1
            break
    return obs, rc


def default_pi_pool_acceptance_path(root: Path) -> Path:
    return root / "config" / "pi-pool-acceptance.toml"


def observe_pi_pools(
    *,
    root: Path,
    acceptance_path: Path | None = None,
) -> Observation | None:
    """Advisory Pi pool acceptance check via ``ade-pi-pools`` (queue Carried #36).

    When ``config/pi-pool-acceptance.toml`` is under ``root``, report ``warn`` for
    every pool still ``accepted = false`` (or missing for a routing Pi service).
    Accepted pools (Cursor / Z.ai on the shipped file) stay quiet: they are not
    named in a warn detail. A fully-accepted file is ``ok``.

    Observe-only: never writes ``accepted=true`` and never mutates the file.
    Advisory: a ``warn`` does not fail doctor (exit stays 0 from this check).
    Returns None when the acceptance file is absent (fixture catalogs).
    """
    path = acceptance_path if acceptance_path is not None else default_pi_pool_acceptance_path(root)
    if not path.is_file():
        return None
    # Lazy import: route_agent is heavy; skip when the file is absent.
    import ade_pi_pools as pools  # noqa: PLC0415

    try:
        rows = pools.status_rows(path)
    except (OSError, ValueError, UnicodeDecodeError) as e:  # TOMLDecodeError ⊂ ValueError
        return Observation(
            "pools", "ade-pi-pools", "error",
            f"pi-pool-acceptance unreadable ({path}): {e}",
        )
    unaccepted = [r["pool"] for r in rows if not r["accepted"]]
    if unaccepted:
        return Observation(
            "pools", "ade-pi-pools", "warn",
            "UNACCEPTED pool(s): " + ", ".join(unaccepted)
            + f" (flip accepted=true in {path} after operator acceptance; "
            "docs/pi-defaults.md B4; doctor never writes accepted=true)",
        )
    return Observation(
        "pools", "ade-pi-pools", "ok",
        f"every listed Pi pool is accepted ({path})",
    )


def doctor(
    catalog: Catalog,
    *,
    runner: Runner | None = None,
    probe_timeout_s: float = 15.0,
    settings_path: Path | None = None,
    jobs_live: Mapping[str, Any] | None = None,
    skip_jobs: bool = False,
    credential_bak: Observation | None = None,
    skip_credential_bak: bool = False,
    pi_pool_acceptance_path: Path | None = None,
) -> tuple[list[Observation], int]:
    """Observe-only doctor. Exit 1 if any expected component/settings/job drifts
    (including ``paseo_plugin`` missing/disabled when expected), or credential-bak
    WARN/FAIL fires; never repairs, installs, enables, or unloads; never deletes
    the vault; never mutates ``~/.claude/settings.json``.

    Hard deps (including ``graft`` via ``graft --version``) fail the command when
    missing/error. Unchosen ``paseo_plugin`` rows still print missing/disabled
    without failing. The Pi pool advisory (``ade-pi-pools``) may ``warn`` on
    UNACCEPTED pools without changing the exit code; it never writes acceptance.
    """
    obs: list[Observation] = [
        Observation("catalog", str(catalog.path), "ok", "catalog validated"),
    ]
    hard_missing = 0
    for row in catalog.components:
        o = observe_component(
            row,
            root=catalog.root,
            runner=runner,
            probe_timeout_s=probe_timeout_s,
        )
        obs.append(o)
        # Unchosen paseo_plugin rows still report missing/disabled for visibility,
        # but only expected components fail the doctor exit code. Never install/enable.
        if expected_installed(row) and o.status in ("missing", "disabled", "error"):
            hard_missing += 1
    for row in catalog.keys:
        obs.append(observe_key(row))
    for row in catalog.logins:
        obs.append(observe_login(row))
    nudge = observe_context_size_nudge(root=catalog.root, settings_path=settings_path)
    if nudge is not None:
        obs.append(nudge)
        if nudge.status in ("missing", "error"):
            hard_missing += 1
    if not skip_jobs and (catalog.jobs or catalog.retired_jobs):
        # Lazy import: ade_sched is optional at catalog-check time; doctor needs live probes.
        import ade_sched as sched  # noqa: WPS433

        live = jobs_live
        if live is None:
            live = sched.scan_live(paseo_run=_paseo_runner(runner, catalog.root))
        drift_rows = sched.diff_jobs(
            catalog.jobs,
            catalog.retired_jobs,
            live,
            unload=False,  # S4b: never unload; foreign owners always report-only
        )
        for row in drift_rows:
            kind = "retired-job" if row.category == "retired" else "job"
            obs.append(Observation(kind, row.name, row.status, row.detail))
            if row.fail:
                hard_missing += 1
    if not skip_credential_bak:
        bak_obs = (
            credential_bak
            if credential_bak is not None
            else observe_credential_bak()
        )
        obs.append(bak_obs)
        # WARN approaching + FAIL past (and warn itself fails the doctor run).
        if bak_obs.status in ("warn", "error", "missing"):
            hard_missing += 1
    pools_obs = observe_pi_pools(
        root=catalog.root,
        acceptance_path=pi_pool_acceptance_path,
    )
    if pools_obs is not None:
        obs.append(pools_obs)
        # Advisory warn stays exit 0; only a broken acceptance file fails doctor.
        if pools_obs.status == "error":
            hard_missing += 1
    return obs, (1 if hard_missing else 0)


def _paseo_runner(
    runner: Runner | None,
    root: Path,
) -> Callable[[list[str]], "subprocess.CompletedProcess[str]"] | None:
    if runner is None:
        return None

    def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
        return runner(argv, root)

    return _run


def expand_argv(
    argv: list[str],
    *,
    root: Path,
    prefix: Path | None = None,
) -> list[str]:
    """Expand {bin}/{root}/{home}/{prefix} tokens; refuse unknown braces."""
    root = root.resolve()
    prefix = (prefix or default_prefix()).expanduser().resolve()
    mapping = {
        "{bin}": str(root / "bin"),
        "{root}": str(root),
        "{home}": str(Path.home()),
        "{prefix}": str(prefix),
    }
    out: list[str] = []
    for part in argv:
        expanded = part
        for token, value in mapping.items():
            expanded = expanded.replace(token, value)
        if "{" in expanded or "}" in expanded:
            raise InstallError(
                f"install_argv part {part!r} still contains braces after known token expansion"
            )
        out.append(expanded)
    return out


def pick_system_argv(
    row: dict[str, Any],
    *,
    system: str | None = None,
) -> list[str] | None:
    """Choose platform system recipe: Darwin prefers ``system_argv_darwin``, else ``system_argv``."""
    sysname = (system or platform.system()).lower()
    if sysname == "darwin":
        darwin = row.get("system_argv_darwin")
        if isinstance(darwin, list) and darwin:
            return list(darwin)
    generic = row.get("system_argv")
    if isinstance(generic, list) and generic:
        return list(generic)
    return None


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
        if row.get("needs_system"):
            sys_argv = pick_system_argv(row)
            if sys_argv:
                reason = (
                    "needs_system=true; ade-install apply --system --dry-run / "
                    "--print-system-argv shows system_argv; live needs "
                    "--yes --system --apply-system"
                )
                resolved = None
                try:
                    resolved = expand_argv(sys_argv, root=catalog.root)
                    reason = reason + "; argv=" + " ".join(
                        shlex.quote(a) for a in resolved
                    )
                except InstallError as e:
                    reason = f"{reason}; system_argv invalid: {e}"
                steps.append({
                    "id": cid,
                    "action": "needs-system",
                    "reason": reason,
                    "needs_system": True,
                    **({"argv": resolved} if resolved else {}),
                })
                continue
            # No platform system_argv (e.g. Linux sudo-secretspec): fall through
            # to install_argv when a user-scoped multi-step helper is recorded.
            if not (isinstance(row.get("install_argv"), list) and row.get("install_argv")):
                steps.append({
                    "id": cid,
                    "action": "needs-system",
                    "reason": (
                        "needs_system=true; no system_argv for this platform and "
                        "no install_argv helper recorded"
                    ),
                    "needs_system": True,
                })
                continue
        argv = row.get("install_argv")
        if isinstance(argv, list) and argv:
            try:
                resolved = expand_argv(argv, root=catalog.root)
            except InstallError as e:
                steps.append({
                    "id": cid,
                    "action": "blocked",
                    "reason": str(e),
                })
                continue
            helper_note = (
                "no system_argv on this platform; ade-install apply --yes runs "
                "install_argv helper (not system package argv); default is --dry-run"
                if row.get("needs_system")
                else "ade-install apply --yes runs install_argv; default is --dry-run"
            )
            steps.append({
                "id": cid,
                "action": "would-install",
                "reason": " ".join(shlex.quote(a) for a in resolved),
                "argv": resolved,
                "needs_system": bool(row.get("needs_system")),
                "note": helper_note,
            })
            continue
        install = row.get("install") or UNKNOWN
        if install == UNKNOWN:
            steps.append({
                "id": cid,
                "action": "blocked",
                "reason": "install_argv missing and install UNKNOWN; record argv before apply",
            })
        else:
            steps.append({
                "id": cid,
                "action": "blocked",
                "reason": (
                    f"install text recorded ({install!r}) but install_argv missing; "
                    "apply only executes argv lists"
                ),
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
    jobs_by_owner: dict[str, int] = {}
    for row in catalog.jobs:
        owner = str(row.get("owner") or "?")
        jobs_by_owner[owner] = jobs_by_owner.get(owner, 0) + 1
    return {
        "path": str(catalog.path),
        "schema_version": catalog.data.get("schema_version"),
        "components": len(catalog.components),
        "keys": len(catalog.keys),
        "logins": len(catalog.logins),
        "jobs": len(catalog.jobs),
        "retired_jobs": len(catalog.retired_jobs),
        "jobs_by_owner": jobs_by_owner,
        "by_class": by_class,
        "provenance": catalog.provenance,
    }


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def load_ledger(state_dir: Path) -> dict[str, Any]:
    path = state_dir / "ledger.json"
    if not path.is_file():
        return {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "entries": {},
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as e:
        raise InstallError(f"{path}: unreadable ledger ({e})") from e
    if not isinstance(raw, dict):
        raise InstallError(f"{path}: ledger root must be an object")
    entries = raw.get("entries")
    if entries is None:
        entries = {}
    if not isinstance(entries, dict):
        raise InstallError(f"{path}: entries must be an object")
    return {
        "schema_version": int(raw.get("schema_version") or LEDGER_SCHEMA_VERSION),
        "entries": entries,
        "updated_at": raw.get("updated_at"),
    }


def save_ledger(state_dir: Path, ledger: dict[str, Any]) -> Path:
    path = state_dir / "ledger.json"
    out = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "entries": ledger.get("entries") or {},
    }
    _atomic_write_json(path, out)
    return path


def collect_system_argv(
    catalog: Catalog,
    *,
    ids: set[str] | None = None,
    prefix: Path | None = None,
) -> list[dict[str, Any]]:
    """Print-only: platform ``system_argv`` for selected (or all) ``needs_system`` rows."""
    known = {row["id"] for row in catalog.components}
    if ids:
        unknown = sorted(ids - known)
        if unknown:
            raise InstallError(f"unknown component id(s): {', '.join(unknown)}")
    out: list[dict[str, Any]] = []
    for row in catalog.components:
        cid = str(row["id"])
        if ids is not None and cid not in ids:
            continue
        if not row.get("needs_system"):
            if ids is not None:
                out.append({
                    "id": cid,
                    "ok": False,
                    "action": "skip",
                    "reason": "not needs_system",
                    "argv": None,
                })
            continue
        sys_raw = pick_system_argv(row)
        if not sys_raw:
            out.append({
                "id": cid,
                "ok": False,
                "action": "missing",
                "reason": "needs_system but no system_argv for this platform",
                "argv": None,
            })
            continue
        try:
            argv = expand_argv(list(sys_raw), root=catalog.root, prefix=prefix)
        except InstallError as e:
            out.append({
                "id": cid,
                "ok": False,
                "action": "blocked",
                "reason": str(e),
                "argv": None,
            })
            continue
        out.append({
            "id": cid,
            "ok": True,
            "action": "print-system-argv",
            "reason": "print-only; not executed",
            "argv": argv,
            "detail": shlex.join(argv),
        })
    return out


def build_apply_steps(
    catalog: Catalog,
    *,
    ids: set[str] | None = None,
    force: bool = False,
    allow_system: bool = False,
    apply_system: bool = False,
    prefix: Path | None = None,
) -> list[ApplyStep]:
    """Decide per-component apply actions without executing."""
    steps: list[ApplyStep] = []
    known = {row["id"] for row in catalog.components}
    if ids:
        unknown = sorted(ids - known)
        if unknown:
            raise InstallError(f"unknown component id(s): {', '.join(unknown)}")
    for row in catalog.components:
        cid = str(row["id"])
        if ids is not None and cid not in ids:
            continue
        if row.get("paseo_plugin"):
            # Observe-only: doctor may report missing/disabled; apply never
            # installs or enables a Paseo plugin (operator `paseo plugin install`).
            steps.append(ApplyStep(
                cid,
                "skip" if not expected_installed(row) else "blocked",
                None,
                "observe-only paseo_plugin; ade-install never installs or enables",
            ))
            continue
        if not expected_installed(row):
            steps.append(ApplyStep(cid, "skip", None, f"class={row['class']} chosen={row.get('chosen')}"))
            continue
        obs = observe_component(row, root=catalog.root)
        if obs.status == "ok" and not force:
            steps.append(ApplyStep(cid, "skip", None, f"already present ({obs.detail})"))
            continue
        if row.get("needs_system"):
            sys_raw = pick_system_argv(row)
            if sys_raw:
                if not allow_system:
                    steps.append(ApplyStep(
                        cid, "refuse-system", None,
                        "needs_system=true; pass --system --dry-run to preview system_argv "
                        "(live: --yes --system --apply-system)",
                    ))
                    continue
                try:
                    argv = expand_argv(list(sys_raw), root=catalog.root, prefix=prefix)
                except InstallError as e:
                    steps.append(ApplyStep(cid, "blocked", None, str(e)))
                    continue
                if apply_system:
                    reason = "ready for --apply-system (operator opt-in)"
                else:
                    reason = (
                        "system dry-run / preview only; live needs "
                        "--yes --system --apply-system"
                    )
                steps.append(ApplyStep(
                    cid, "would-system-install", argv,
                    reason,
                    detail=shlex.join(argv),
                ))
                continue
            # No system_argv on this platform: use install_argv helper when present
            # (Linux sudo-secretspec multi-step media staging via ade-user-install).
            if not (isinstance(row.get("install_argv"), list) and row.get("install_argv")):
                steps.append(ApplyStep(
                    cid, "blocked", None,
                    "needs_system but no system_argv for this platform and no install_argv",
                ))
                continue
        argv_raw = row.get("install_argv")
        if not isinstance(argv_raw, list) or not argv_raw:
            steps.append(ApplyStep(
                cid, "blocked", None,
                "no install_argv recorded (UNKNOWN or prose-only install)",
            ))
            continue
        try:
            argv = expand_argv(list(argv_raw), root=catalog.root, prefix=prefix)
        except InstallError as e:
            steps.append(ApplyStep(cid, "blocked", None, str(e)))
            continue
        steps.append(ApplyStep(
            cid, "would-install", argv,
            "ready", detail=shlex.join(argv),
        ))
    return steps


def _default_runner(
    argv: list[str],
    cwd: Path,
    *,
    timeout_s: float = 300.0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — argv list only, never shell
        argv,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        shell=False,
        timeout=timeout_s,
    )


def _run_install_argv(
    *,
    step: ApplyStep,
    row: dict[str, Any],
    ledger: dict[str, Any],
    state_dir: Path,
    cwd: Path,
    run: Callable[[list[str], Path], subprocess.CompletedProcess[str]],
    timeout_s: float,
    kind: str,
    completed_reason: str,
) -> bool:
    """Execute one argv list; update ``row`` and ledger. Return True if failed."""
    assert step.argv is not None
    entries = ledger.setdefault("entries", {})
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    entries[step.id] = {
        "status": "pending",
        "kind": kind,
        "argv": list(step.argv),
        "at": stamp,
    }
    save_ledger(state_dir, ledger)
    try:
        proc = run(list(step.argv), cwd)
    except subprocess.TimeoutExpired:
        row["action"] = "failed"
        row["ok"] = False
        row["reason"] = f"timed out after {timeout_s}s"
        entries[step.id] = {
            "status": "failed",
            "kind": kind,
            "argv": list(step.argv),
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "detail": row["reason"],
        }
        save_ledger(state_dir, ledger)
        return True
    except OSError as e:
        row["action"] = "failed"
        row["ok"] = False
        row["reason"] = f"exec error: {e}"
        entries[step.id] = {
            "status": "failed",
            "kind": kind,
            "argv": list(step.argv),
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "detail": str(e),
        }
        save_ledger(state_dir, ledger)
        return True
    if proc.returncode != 0:
        row["action"] = "failed"
        row["ok"] = False
        row["returncode"] = proc.returncode
        err = (proc.stderr or proc.stdout or "").strip()
        row["reason"] = err[:500] or f"exit {proc.returncode}"
        entries[step.id] = {
            "status": "failed",
            "kind": kind,
            "argv": list(step.argv),
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "returncode": proc.returncode,
            "detail": row["reason"],
        }
        save_ledger(state_dir, ledger)
        return True
    row["action"] = "installed"
    row["ok"] = True
    row["returncode"] = 0
    row["reason"] = completed_reason
    entries[step.id] = {
        "status": "installed",
        "kind": kind,
        "argv": list(step.argv),
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    save_ledger(state_dir, ledger)
    return False


def labeled_ade_sched_job_names(catalog: Catalog) -> list[str]:
    """ADE-owned ``kind=ade-sched`` jobs that already have ``label`` + ``plist`` (reconcile-ready)."""
    names: list[str] = []
    for row in catalog.jobs:
        if row.get("owner") != OWNER_ADE:
            continue
        if row.get("kind") != "ade-sched":
            continue
        label, plist = row.get("label"), row.get("plist")
        if not isinstance(label, str) or not label or not isinstance(plist, str) or not plist:
            continue
        names.append(str(row["name"]))
    return names


def apply_sched_reconcile(
    catalog: Catalog,
    *,
    dry_run: bool = True,
    names: set[str] | None = None,
    env: Mapping[str, str] | None = None,
    state_dir: Path | None = None,
    allow_no_linger: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    """Run ``ade-sched reconcile`` for labeled ADE jobs (Linux one-step demanual).

    Live writes only when the host backend is the current reconcile write backend
    (systemd on master). Other backends get report rows (exit 0) so Mac install
    recipes stay on ``just *-install`` until launchd write lands.
    """
    import ade_sched as sched  # noqa: WPS433 — optional at catalog-check time

    env = os.environ if env is None else env
    want = names if names is not None else set(labeled_ade_sched_job_names(catalog))
    if not want:
        return [], 0
    try:
        backend = sched.detect(None, env=env)
    except sched.SchedError as e:
        return ([{
            "id": "sched-reconcile",
            "action": "blocked",
            "reason": f"scheduler detect failed: {e}",
            "ok": False,
            "category": "sched",
        }], 1)

    write_backend = getattr(sched, "RECONCILE_WRITE_BACKEND", "systemd")
    write_backends = getattr(sched, "RECONCILE_WRITE_BACKENDS", None)
    if isinstance(write_backends, (set, frozenset)):
        can_write = backend.name in write_backends
    else:
        can_write = backend.name == write_backend
    if not dry_run and not can_write:
        return ([{
            "id": name,
            "action": "skip-reconcile-backend",
            "reason": (
                f"reconcile write backend is {write_backend!r}; host={backend.name!r}; "
                f"use just update-check-install / harden-check-install / keys-check-install "
                f"or ade-sched install on this host"
            ),
            "ok": True,
            "category": "sched",
        } for name in sorted(want)], 0)

    # Implicit checkout (ade=None): Job.from_* refuses linked worktrees. Passing
    # ade=catalog.root would opt out of that guard (CLI --ade semantics) and let a
    # full apply from a task worktree pin persistent timers at a path deleted after merge.
    # Refuse for dry-run too so the plan matches what --yes would do.
    if sched.is_linked_worktree(catalog.root):
        return ([{
            "id": name,
            "action": "blocked",
            "reason": (
                f"catalog root {catalog.root} is a linked git worktree; refuse scheduling "
                f"persistent jobs from an ephemeral checkout (use the primary ADE checkout "
                f"or ade-sched install --ade <persistent-path>)"
            ),
            "ok": False,
            "category": "sched",
        } for name in sorted(want)], 1)

    results, rc = sched.reconcile(
        catalog.jobs,
        catalog.retired_jobs,
        dry_run=dry_run,
        backend=backend,
        root=catalog.root,
        ade=None,
        env=env,
        state_dir=state_dir or sched.jobs_state_dir(env),
        names=want,
        allow_no_linger=allow_no_linger,
    )
    mapped: list[dict[str, Any]] = []
    for row in results:
        mapped.append({
            "id": str(row.get("name") or "sched"),
            "action": str(row.get("action") or "?"),
            "reason": str(row.get("detail") or row.get("reason") or ""),
            "ok": bool(row.get("ok", True)),
            "category": "sched",
            "label": row.get("label"),
        })
    return mapped, rc


def apply(
    catalog: Catalog,
    *,
    dry_run: bool = True,
    ids: set[str] | None = None,
    force: bool = False,
    allow_system: bool = False,
    apply_system: bool = False,
    state_dir: Path | None = None,
    prefix: Path | None = None,
    runner: Runner | None = None,
    timeout_s: float = 300.0,
    reconcile_sched: bool | None = None,
    env: Mapping[str, str] | None = None,
    allow_no_linger: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    """Bounded apply. Default dry-run. ``--yes`` executes user ``install_argv``.

    ``--system`` unlocks dry-run preview of ``system_argv`` (``would-system-install``).
    Live ``system_argv`` requires ``apply_system=True`` (CLI: ``--apply-system`` with
    ``--yes --system``). Without that opt-in, system exec is refused (exit 2).

    After component steps, when ``reconcile_sched`` is true (default: true for a full
    apply with no ``--id`` filter), also plans/runs ``ade-sched reconcile`` for
    ADE-owned labeled jobs (Linux one-step: folds the three ``just *-install``
    check recipes into ``ade-install apply``).

    Exit 0 when every selected step is skip/would-install(dry)/install ok /
    would-system-install(dry) / system installed; 1 when any blocked/failed/
    refuse-system; 2 when a system_argv step was refused without ``--apply-system``.
    """
    if apply_system and not allow_system:
        raise InstallError("--apply-system requires --system")
    if apply_system and dry_run:
        raise InstallError("--apply-system requires --yes (refused with dry-run)")
    if reconcile_sched is None:
        reconcile_sched = ids is None
    steps = build_apply_steps(
        catalog,
        ids=ids,
        force=force,
        allow_system=allow_system,
        apply_system=apply_system,
        prefix=prefix,
    )
    state_dir = state_dir or default_state_dir()
    results: list[dict[str, Any]] = []
    failed = 0
    system_exec_refused = 0

    ledger = load_ledger(state_dir) if not dry_run else None

    def _run(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if runner is not None:
            return runner(argv, cwd)
        return _default_runner(argv, cwd, timeout_s=timeout_s)

    for step in steps:
        row: dict[str, Any] = {
            "id": step.id,
            "action": step.action,
            "reason": step.reason,
            "ok": step.action in ("skip", "would-install", "would-system-install"),
        }
        if step.argv is not None:
            row["argv"] = list(step.argv)
            row["detail"] = step.detail
        if step.action == "would-system-install" and not dry_run:
            if not apply_system:
                # Default refuse: --yes --system alone never roots the machine.
                system_exec_refused += 1
                row["action"] = "refuse-system-exec"
                row["ok"] = False
                row["reason"] = (
                    "system_argv execution refused; preview with --system --dry-run "
                    "or --print-system-argv; live needs --yes --system --apply-system"
                )
            else:
                assert ledger is not None
                if _run_install_argv(
                    step=step,
                    row=row,
                    ledger=ledger,
                    state_dir=state_dir,
                    cwd=catalog.root,
                    run=_run,
                    timeout_s=timeout_s,
                    kind="system_argv",
                    completed_reason="system_argv completed",
                ):
                    failed += 1
        elif step.action == "would-install" and not dry_run:
            assert step.argv is not None
            assert ledger is not None
            if _run_install_argv(
                step=step,
                row=row,
                ledger=ledger,
                state_dir=state_dir,
                cwd=catalog.root,
                run=_run,
                timeout_s=timeout_s,
                kind="install_argv",
                completed_reason="install_argv completed",
            ):
                failed += 1
        elif step.action in ("blocked", "refuse-system", "refuse-system-exec"):
            failed += 1
            row["ok"] = False
        results.append(row)

    if system_exec_refused:
        return results, 2

    if reconcile_sched:
        sched_rows, sched_rc = apply_sched_reconcile(
            catalog,
            dry_run=dry_run,
            env=env,
            allow_no_linger=allow_no_linger,
        )
        results.extend(sched_rows)
        if sched_rc != 0:
            failed += 1

    # dry-run with only skips/would-install/would-system-install → 0; any blocked → 1
    if dry_run:
        rc = 1 if any(
            r["action"] in ("blocked", "refuse-system", "refuse-system-exec")
            or (r.get("category") == "sched" and not r.get("ok", True))
            for r in results
        ) else 0
    else:
        rc = 1 if failed else 0
    return results, rc
