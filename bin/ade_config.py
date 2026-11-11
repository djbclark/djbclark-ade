"""ade_config: versioned read-only effective ADE config (schema_version=1).

Builds one effective tree from optional ``config/ade.toml``, legacy
``config/routing.toml`` + ``config/gates.toml`` + ``config/model-tiers.toml``,
and optional ``~/.config/djbclark-ade/local.toml``. Does not write files,
resolve secrets, or initialize live routing. ``route_agent`` and ``ade_gates``
consume this tree for routing/gates and the router's model-tier snapshot.
Legacy model-tier file APIs remain separate and never import this loader.

Public:
  load_effective(...) -> EffectiveConfig
  get_path(data, dotted) -> value
  local_diff(...) -> list[Change]
  check(...) -> tuple[list[str], EffectiveConfig | None]   # empty errors means OK
  FRONTIER_DEFAULTS / mapping table constants for docs and tests
"""
from __future__ import annotations

import copy
import json
import os
import stat
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_BIN = Path(__file__).resolve().parent
if str(_BIN) not in sys.path:
    sys.path.insert(0, str(_BIN))
import model_tiers as _model_tiers  # noqa: E402
import ade_install_catalog as _catalog  # noqa: E402

# Fail-safe closed frontier (mirrors ade_gates.FRONTIER_DEFAULTS; kept local so
# this module does not import route_agent / ade_gates side effects).
FRONTIER_DEFAULTS: dict[str, float] = {
    "frontier1_judged": 0.0,
    "frontier2_judged": 0.0,
    "frontier1_per_wave": 1.0,
    "frontier2_per_wave": 1.0,
    "frontier1_agent_calls_per_day": 0.0,
    "frontier1_min_left": 15.0,
    "frontier1_window_min_left": 30.0,
    "frontier2_min_left": 60.0,
}

SCHEMA_VERSION = 1

# One explicit legacy → effective mapping (docs/config-migration.md).
LEGACY_PROJECTION: tuple[tuple[str, str, str], ...] = (
    ("config/routing.toml", "[routing]", "[routing]"),
    ("config/routing.toml", "[lead]", "[lead]"),
    ("config/routing.toml", "[dispatch]", "[dispatch]"),
    ("config/routing.toml", "[substrate]", "[substrate]"),
    ("config/routing.toml", "[hermes]", "[hermes]"),
    ("config/routing.toml", "[calibrate]", "[calibrate]"),
    ("config/routing.toml", "[[service]]", "[[service]]"),
    ("config/gates.toml", "[frontier]", "[gates.frontier]"),
    ("config/gates.toml", "[floors.frontier]", "[gates.floors.frontier]"),
    ("config/model-tiers.toml", "[meta]/[rank]/[vendor.*]/[model.*]/[former]", "[model_tiers]"),
    ("config/install.toml", "[[component]]", "[[install.component]]"),
    ("config/install.toml", "[[login]]", "[[install.login]]"),
    ("config/install.toml", "[[install.jobs]]", "[[install.jobs]]"),
    ("config/install.toml", "[[install.retired_jobs]]", "[[install.retired_jobs]]"),
    ("config/install.toml", "[[key]] keyed by name", "[keys.<NAME>]"),
    ("config/context-budget.toml", "dirs / [budget]", "[context_budget]"),
)

ROUTING_DOMAIN_KEYS: frozenset[str] = frozenset({
    "routing", "lead", "dispatch", "substrate", "hermes", "calibrate", "service",
})

KNOWN_TOP_LEVEL: frozenset[str] = frozenset({
    "schema_version",
    *ROUTING_DOMAIN_KEYS,
    "gates",
    "model_tiers",
    "install", "keys", "context_budget",
})


class ConfigError(ValueError):
    """Invalid new/local config, unsupported version, merge conflict, or identity clash."""


@dataclass
class EffectiveConfig:
    """Effective tree plus non-secret provenance."""

    data: dict[str, Any]
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Change:
    path: str
    before: Any
    after: Any


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parent.parent


def default_new_config_path(root: Path) -> Path:
    return root / "config" / "ade.toml"


def default_routing_path(root: Path) -> Path:
    return root / "config" / "routing.toml"


def default_gates_path(root: Path) -> Path:
    return root / "config" / "gates.toml"


def default_model_tiers_path(root: Path) -> Path:
    return root / "config" / "model-tiers.toml"


def default_local_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".config" / "djbclark-ade" / "local.toml"


def default_schema_path(root: Path) -> Path:
    return root / "config" / "ade.schema.json"


def is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) < 1e300


def code_direction(key: str) -> str:
    return "lower" if key.endswith("_min_left") else "higher"


def read_toml(path: Path) -> dict[str, Any]:
    """Read a TOML mapping; raise ConfigError on missing/unreadable/invalid."""
    try:
        if not path.is_file():
            raise ConfigError(f"{path}: not a regular file")
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as fh:
            if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                raise ConfigError(f"{path}: not a regular file")
            data = tomllib.load(fh)
    except ConfigError:
        raise
    except OSError as e:
        raise ConfigError(f"{path}: {e.strerror or e}") from e
    except (tomllib.TOMLDecodeError, ValueError, RecursionError) as e:
        raise ConfigError(f"{path}: not valid TOML ({e})") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: root must be a table")
    return data


def input_present(path: Path) -> bool:
    """Only true absence permits fallback; dangling links and access errors do not."""
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as e:
        raise ConfigError(f"{path}: {e.strerror or e}") from e
    return True


def try_read_toml(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Like ade_gates.read_toml: (data, None) or (None, error). Missing is an error string."""
    try:
        return read_toml(path), None
    except ConfigError as e:
        return None, str(e)


def require_schema_version(data: dict[str, Any], path: Path, *, required: bool) -> None:
    if "schema_version" not in data:
        if required:
            raise ConfigError(f"{path}: missing schema_version (need {SCHEMA_VERSION})")
        return
    ver = data["schema_version"]
    if not isinstance(ver, int) or isinstance(ver, bool):
        raise ConfigError(f"{path}: schema_version must be an integer, got {ver!r}")
    if ver != SCHEMA_VERSION:
        raise ConfigError(
            f"{path}: unsupported schema_version {ver} (supported: {SCHEMA_VERSION})"
        )


def unknown_top_level(data: dict[str, Any], path: Path) -> None:
    unknown = sorted(set(data) - KNOWN_TOP_LEVEL)
    if unknown:
        raise ConfigError(f"{path}: unknown top-level key(s) {unknown}")


def merge_maps(base: Any, overlay: Any, *, path: str) -> Any:
    """Per-leaf recursive map merge; arrays replace whole; type conflicts raise."""
    if isinstance(base, dict) and isinstance(overlay, dict):
        out = dict(base)
        for key, right in overlay.items():
            left = out.get(key, None)
            child = f"{path}.{key}" if path else str(key)
            if key not in out:
                out[key] = copy.deepcopy(right)
            else:
                out[key] = merge_maps(left, right, path=child)
        return out
    if isinstance(base, list) and isinstance(overlay, list):
        return copy.deepcopy(overlay)
    if type(base) is type(overlay) or (
        isinstance(base, (int, float)) and isinstance(overlay, (int, float))
        and not isinstance(base, bool) and not isinstance(overlay, bool)
    ):
        # scalars / same-shaped non-collections: overlay wins
        if isinstance(base, (dict, list)) or isinstance(overlay, (dict, list)):
            raise ConfigError(
                f"type conflict at {path or '<'}: "
                f"{type(base).__name__} vs {type(overlay).__name__}"
            )
        return copy.deepcopy(overlay)
    raise ConfigError(
        f"type conflict at {path or '<'}: "
        f"{type(base).__name__} vs {type(overlay).__name__}"
    )


def project_routing_domain(legacy: dict[str, Any]) -> dict[str, Any]:
    """Lift routing.toml tables to the effective root (identity mapping)."""
    out: dict[str, Any] = {}
    for key in ROUTING_DOMAIN_KEYS:
        if key in legacy:
            out[key] = copy.deepcopy(legacy[key])
    return out


# Snapshot of route_agent.load_policy's pure contract (2026-11-07).
# Parity tests extract that function without importing live routing initialization.
SERVICE_KEYS = frozenset({
    "name", "cli", "good_at", "billing", "note", "never_bulk", "retired",
    "judgment_tier", "access", "hermes_only", "burn_first", "pool", "max_parallel",
    "agent", "models", "reserve_floor", "measured_only", "grant_days", "ready_probe",
    "shares_pool", "plenty_kinds", "fallback_after", "window",
})
_SERVICE_REQUIRED = ("name", "cli", "good_at", "billing")
LEAD_KEYS = ("model", "effort", "pipeline_model")
LEAD_ALL_KEYS = LEAD_KEYS + ("pipeline_effort",)
LEAD_SWITCHES = ("fable_lead",)
LEAD_PIPELINE_EFFORT_DEFAULT = "high"
CLAUDE_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


def validate_legacy_routing_shape(data: dict[str, Any], path: Path) -> None:
    """Validate and fill defaults exactly as the pure legacy load_policy reader."""
    services = data.get("service")
    if services is None:
        raise ConfigError(f"routing policy {path}: missing [[service]] entries")
    if not isinstance(services, list):
        raise ConfigError(f"routing policy {path}: 'service' must be an array of tables")

    for i, entry in enumerate(services):
        label = entry.get("name") if isinstance(entry, dict) else i
        if not isinstance(entry, dict):
            raise ConfigError(f"routing policy {path}: [[service]] entry {i} is not a table")
        unknown = set(entry) - SERVICE_KEYS
        if unknown:
            raise ConfigError(
                f"routing policy {path}: [[service]] {label!r}: "
                f"unknown key(s) {sorted(unknown)}")
        missing = [k for k in _SERVICE_REQUIRED if k not in entry]
        if missing:
            raise ConfigError(
                f"routing policy {path}: [[service]] {label!r}: "
                f"missing required key(s) {missing}")
        pool = entry.get("pool")
        if pool is not None and not (isinstance(pool, list) and len(pool) == 2
                                       and all(isinstance(x, str) for x in pool)):
            raise ConfigError(
                f"routing policy {path}: [[service]] {label!r}: "
                f"pool must be a 2-element string array, got {pool!r}")
    for section in ("routing", "dispatch", "hermes", "calibrate"):
        if section not in data or not isinstance(data[section], dict):
            raise ConfigError(f"routing policy {path}: missing [{section}] table")
    substrate = data.get("substrate")
    if substrate is not None:
        lifeline = substrate.get("lifeline", []) if isinstance(substrate, dict) else None
        if not (isinstance(lifeline, list) and all(isinstance(x, str) for x in lifeline)):
            raise ConfigError(f"routing policy {path}: [substrate] must be a table whose "
                             "lifeline is an array of service names")
    lead = data.get("lead")
    if lead is not None:
        if not isinstance(lead, dict):
            raise ConfigError(f"routing policy {path}: [lead] must be a table")
        unknown = set(lead) - set(LEAD_ALL_KEYS) - set(LEAD_SWITCHES)
        if unknown:
            raise ConfigError(f"routing policy {path}: [lead] unknown key(s) {sorted(unknown)}")
        if not all(isinstance(lead.get(k), str) and lead[k] for k in LEAD_KEYS):
            raise ConfigError(f"routing policy {path}: [lead] must be a table with non-empty string keys "
                             + ", ".join(LEAD_KEYS))
        lead.setdefault("pipeline_effort", LEAD_PIPELINE_EFFORT_DEFAULT)
        if not isinstance(lead.get("fable_lead", False), bool):
            raise ConfigError(f"routing policy {path}: [lead] fable_lead must be true or false, "
                             f"got {lead.get('fable_lead')!r}")
        for key in ("effort", "pipeline_effort"):
            if lead[key] not in CLAUDE_EFFORT_LEVELS:
                raise ConfigError(f"routing policy {path}: [lead] {key} {lead[key]!r} must be one of "
                                 + ", ".join(CLAUDE_EFFORT_LEVELS))


def load_legacy_routing(path: Path) -> dict[str, Any]:
    data = read_toml(path)
    validate_legacy_routing_shape(data, path)
    return project_routing_domain(data)


def baseline_limit(floors_frontier: dict[str, Any] | None, key: str, default: float) -> float:
    if code_direction(key) == "higher" and isinstance(floors_frontier, dict):
        spec = floors_frontier.get(key)
        if isinstance(spec, dict) and is_num(spec.get("bound")):
            return float(spec["bound"])
    return default


def clamp_frontier(
    frontier: dict[str, Any] | None,
    floors_frontier: dict[str, Any] | None,
    *,
    source_label: str,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Match ade_gates.load_frontier clamping / fail-closed behaviour."""
    base = dict(FRONTIER_DEFAULTS)
    info: dict[str, Any] = {
        "source": "code",
        "toml_error": None,
        "baseline_guarded": {},
    }
    if not isinstance(frontier, dict) or not frontier or not all(is_num(v) for v in frontier.values()):
        info["toml_error"] = f"{source_label}: [frontier] is missing, empty or holds a non-number"
        return base, info
    for k, v in frontier.items():
        if k not in base:
            continue
        v_f, lim = float(v), baseline_limit(floors_frontier, k, FRONTIER_DEFAULTS[k])
        if (v_f < lim) if code_direction(k) == "lower" else (v_f > lim):
            info["baseline_guarded"][k] = v_f
            continue
        base[k] = v_f
    info["source"] = "gates.toml"
    return base, info


def raw_legacy_gates(path: Path) -> tuple[dict[str, Any], str | None]:
    """Project only supported legacy leaves, retaining raw requests until merge.

    Legacy malformed frontier closes as a whole; malformed floor specs are ignored,
    just as ade_gates.baseline_limit ignores them. New/local input is strict instead.
    """
    cfg, err = try_read_toml(path)
    cfg = cfg or {}
    frontier = cfg.get("frontier")
    if not isinstance(frontier, dict) or not frontier or not all(is_num(v) for v in frontier.values()):
        err = err or f"{path}: [frontier] is missing, empty or holds a non-number"
        frontier = dict(FRONTIER_DEFAULTS)
    frontier = {k: v for k, v in frontier.items() if k in FRONTIER_DEFAULTS}
    floors = cfg.get("floors")
    specs = floors.get("frontier") if isinstance(floors, dict) else None
    clean = {}
    if isinstance(specs, dict):
        for key, spec in specs.items():
            if key not in FRONTIER_DEFAULTS or not isinstance(spec, dict):
                continue
            clean[key] = {}
            if is_num(spec.get("bound")):
                clean[key]["bound"] = spec["bound"]
            if isinstance(spec.get("loosen"), str):
                clean[key]["loosen"] = spec["loosen"]
    # Keep unknown-only valid legacy frontier nonempty for its source semantics.
    if not frontier and not err:
        frontier = dict(FRONTIER_DEFAULTS)
    return {"frontier": copy.deepcopy(frontier), "floors": {"frontier": clean}}, err


def project_gates_from_legacy_file(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Legacy standalone projection, with the same closed fallback and clamping."""
    gates, err = raw_legacy_gates(path)
    out, info = project_gates_from_new(gates, source_label=str(path))
    if err:
        out["frontier"] = dict(FRONTIER_DEFAULTS)
        info.update(source="code", toml_error=err, baseline_guarded={})
    return out, info


def project_gates_from_new(gates: Any, *, source_label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(gates, dict):
        raise ConfigError(f"{source_label}: [gates] must be a table")
    floors = gates.get("floors") if isinstance(gates.get("floors"), dict) else {}
    floors_frontier = floors.get("frontier") if isinstance(floors.get("frontier"), dict) else None
    clamped, info = clamp_frontier(
        gates.get("frontier") if isinstance(gates.get("frontier"), dict) else None,
        floors_frontier,
        source_label=source_label,
    )
    out = {
        "frontier": clamped,
        "floors": copy.deepcopy(floors) if isinstance(floors, dict) else {},
    }
    return out, info


def reject_duplicate_services(services: Any, *, label: str) -> None:
    if services is None:
        return
    if not isinstance(services, list):
        raise ConfigError(f"{label}: service must be an array of tables")
    seen: dict[str, int] = {}
    for i, entry in enumerate(services):
        if not isinstance(entry, dict):
            raise ConfigError(f"{label}: [[service]] entry {i} is not a table")
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise ConfigError(f"{label}: [[service]] entry {i} needs a non-empty string name")
        if name in seen:
            raise ConfigError(
                f"{label}: duplicate service identity {name!r} "
                f"(entries {seen[name]} and {i})"
            )
        seen[name] = i


EFFECTIVE_DOMAINS = frozenset({"routing", "gates", "model_tiers", "install", "keys", "context_budget"})
ROUTER_DOMAINS = frozenset({"routing", "gates", "model_tiers"})
CATALOG_DOMAINS = frozenset({"install", "keys"})
CONTEXT_BUDGET_DOMAINS = frozenset({"context_budget"})
CONTEXT_BUDGET_DEFAULT_DIRS = ("~/src/djbclark-ade", "~")


def context_budget_config(data: dict[str, Any], *, directory_label: str | None = None) -> dict[str, Any]:
    """Normalize the effective consumer's defaults and validate actual labels."""
    raw = data.get("context_budget", {})
    validate_context_budget(data, path=Path("effective context budgets"))
    cfg = {"dirs": copy.deepcopy(raw.get("dirs") or list(CONTEXT_BUDGET_DEFAULT_DIRS)),
           "budget": copy.deepcopy(raw.get("budget") or {})}
    selected = [directory_label] if directory_label else cfg["dirs"]
    validate_context_budget({"context_budget": {**cfg, "dirs": selected}},
                            path=Path("effective context budgets"))
    return cfg


def validate_context_budget(data: dict[str, Any], *, path: Path) -> None:
    """Validate consumed budget leaves without importing the measurement CLI.

    Budget entries are numeric defaults or one directory's numeric overrides.
    Arbitrary row/directory names retain the legacy map's extensibility; nested
    directory maps, booleans and nonfinite numbers cannot reach comparisons.
    """
    if "context_budget" not in data:
        return
    cfg = data["context_budget"]
    if not isinstance(cfg, dict):
        raise ConfigError(f"{path}: context_budget must be a table")
    unknown = set(cfg) - {"dirs", "budget"}
    if unknown:
        raise ConfigError(f"{path}: context_budget unknown key(s) {sorted(unknown)}")
    dirs = cfg.get("dirs", [])
    if not isinstance(dirs, list) or not all(isinstance(d, str) for d in dirs):
        raise ConfigError(f"{path}: context_budget.dirs must be a string array")
    budget = cfg.get("budget", {})
    if not isinstance(budget, dict):
        raise ConfigError(f"{path}: context_budget.budget must be a table")
    for label in dirs:
        if label in budget and not isinstance(budget[label], dict):
            raise ConfigError(
                f"{path}: context_budget.budget.{label} must be a directory override table "
                f"for selected directory {label!r}"
            )
    for key, value in budget.items():
        if key in {"total", "memory", "skills", "mcp_tools", "mcp_instructions", "grow_alert"} and not is_num(value):
            raise ConfigError(f"{path}: context_budget.budget.{key} must be a finite number")
        leaves = value.items() if isinstance(value, dict) else [(None, value)]
        for leaf, number in leaves:
            label = f"context_budget.budget.{key}" + (f".{leaf}" if leaf is not None else "")
            if not is_num(number):
                raise ConfigError(f"{path}: {label} must be a finite number")


def _domain_view(data: dict[str, Any], domains: frozenset[str]) -> dict[str, Any]:
    keys = domains - {"routing"}
    if "routing" in domains:
        keys |= ROUTING_DOMAIN_KEYS
    return {key: copy.deepcopy(value) for key, value in data.items()
            if key == "schema_version" or key in keys}


def read_catalog_schema(root: Path) -> dict[str, Any]:
    path = root / "config/install.schema.json"
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as error:
        raise ConfigError(f"{path}: invalid or unreadable schema ({error})") from error
    _check_schema_node(schema, str(path))
    if schema.get("title") != "djbclark-ade install catalog":
        raise ConfigError(f"{path}: unexpected title")
    if schema.get("properties", {}).get("schema_version", {}).get("const") != SCHEMA_VERSION:
        raise ConfigError(f"{path}: unsupported schema version declaration")
    return schema


def _read_effective_schema(
    root: Path, domains: frozenset[str], *, require_full: bool,
) -> dict[str, Any]:
    path = default_schema_path(root)
    if input_present(path) or not domains <= CATALOG_DOMAINS:
        return read_schema(path)
    if require_full:
        bundled = default_schema_path(_BIN.parent)
        if input_present(bundled):
            return read_schema(bundled)
        raise ConfigError(
            f"{root}: full effective schema required to validate raw unified/local config; "
            "neither root nor bundled ade.schema.json is available"
        )
    # Preserve install-only --root inputs: their existing catalog schema is
    # sufficient for this domain view; unrelated routing schema/files are absent.
    return {
        "title": "djbclark-ade effective config", "type": "object",
        "required": ["schema_version"], "additionalProperties": False,
        "properties": {"schema_version": {"type": "integer", "const": SCHEMA_VERSION},
                       **_catalog.effective_schema_parts(read_catalog_schema(root))},
    }


def _validate_catalog_domains(data: dict[str, Any], path: Path) -> None:
    if "install" in data or "keys" in data:
        try:
            _catalog.validate_effective_catalog(data, path=path)
        except _catalog.CatalogValidationError as error:
            raise ConfigError(str(error)) from error


def load_effective(
    *,
    root: Path | None = None,
    home: Path | None = None,
    new_config: Path | None = None,
    local_config: Path | None = None,
    include_local: bool = True,
    environ: dict[str, str] | None = None,
    domains: frozenset[str] | set[str] | None = None,
    _candidate: tuple[Path, dict[str, Any]] | None = None,
) -> EffectiveConfig:
    """Load the effective schema_version=1 tree. Never writes.

    include_local=False disables local path resolution, presence checks and reads;
    diff uses it for a baseline with no secondary local-file authority.
    domains=None exposes every supported domain; explicit views read only their
    selected legacy sources while validating raw unified/local declarations.
    """
    selected = EFFECTIVE_DOMAINS if domains is None else frozenset(domains)
    if not selected or selected - EFFECTIVE_DOMAINS:
        raise ConfigError(f"unknown or empty effective-config domains: {sorted(selected)}")
    root = (root or repo_root_from_here()).resolve()
    home_path = home if home is not None else Path.home()
    env = environ if environ is not None else dict(os.environ)
    new_path = new_config if new_config is not None else default_new_config_path(root)
    local_path = (
        local_config if local_config is not None else default_local_path(home_path)
    ) if include_local else None

    # Internal writer preview: exactly one approved metadata input is replaced
    # in memory. The ordinary raw/schema/semantic/overlay pipeline below remains
    # authoritative; no temporary config file or alternate precedence is used.
    candidate_path = None
    if _candidate is not None:
        candidate_path = _candidate[0].resolve()
        allowed = {default_new_config_path(root).resolve(),
                   (root / "config/install.toml").resolve(),
                   (root / "config/context-budget.toml").resolve()}
        if local_path is not None:
            allowed.add(local_path.resolve())
        if not selected <= (CATALOG_DOMAINS | CONTEXT_BUDGET_DOMAINS) or candidate_path not in allowed:
            raise ConfigError("candidate snapshots are restricted to metadata input paths/domains")
        if (candidate_path == (root / "config/install.toml").resolve() and not selected <= CATALOG_DOMAINS or
            candidate_path == (root / "config/context-budget.toml").resolve() and not selected <= CONTEXT_BUDGET_DOMAINS):
            raise ConfigError("candidate legacy input must match its metadata domain")
        if candidate_path != (local_path.resolve() if local_path is not None else None) and not input_present(_candidate[0]):
            raise ConfigError("candidate snapshot refuses creation of a repository config source")

    def present(path: Path) -> bool:
        return (candidate_path is not None and path.resolve() == candidate_path) or input_present(path)

    def read(path: Path) -> dict[str, Any]:
        if candidate_path is not None and path.resolve() == candidate_path:
            return copy.deepcopy(_candidate[1])
        return read_toml(path)

    using_new = present(new_path)
    using_local = local_path is not None and present(local_path)
    schema = _read_effective_schema(root, selected, require_full=using_new or using_local)

    routing_env = env.get("ROUTING_POLICY") or None
    gates_env = env.get("GATES_TOML") or None

    model_tiers_env = env.get("MODEL_TIERS_TOML") or None

    provenance: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "new_config": str(new_path) if using_new else None,
        "local_config": str(local_path) if using_local else None,
        "routing_source": None,
        "gates_source": None,
        "model_tiers_source": None,
        "routing_env": routing_env,
        "gates_env": gates_env,
        "model_tiers_env": model_tiers_env,
        "gates_info": None,
        "install_source": None, "keys_source": None, "context_budget_source": None,
        "domains": sorted(selected),
        "mapping": [
            {"legacy_file": a, "legacy": b, "effective": c}
            for a, b, c in LEGACY_PROJECTION
        ],
    }

    data: dict[str, Any] = {"schema_version": SCHEMA_VERSION}

    if using_new:
        raw = read(new_path)
        require_schema_version(raw, new_path, required=True)
        unknown_top_level(raw, new_path)
        validate_tree(raw, schema, label=str(new_path))
        reject_duplicate_services(raw.get("service"), label=str(new_path))
        _validate_catalog_domains(raw, new_path)
        validate_context_budget(raw, path=new_path)
        data = _domain_view(raw, selected)
        data["schema_version"] = SCHEMA_VERSION
        provenance["new_config"] = str(new_path)

    if "routing" in selected:
        # --- routing domain ---
        if routing_env:
            rpath = Path(routing_env)
            projected = load_legacy_routing(rpath)
            for key in ROUTING_DOMAIN_KEYS:
                data.pop(key, None)
            data.update(projected)
            provenance["routing_source"] = str(rpath)
        elif using_new:
            # Raw new-file identities were validated before domain isolation.
            provenance["routing_source"] = str(new_path)
        else:
            rpath = default_routing_path(root)
            projected = load_legacy_routing(rpath)
            data.update(projected)
            provenance["routing_source"] = str(rpath)

    # Keep requests and floors raw until all non-isolated overlays have merged.
    legacy_gate_error = None
    if "gates" in selected:
        if gates_env:
            gpath = Path(gates_env)
            data["gates"], legacy_gate_error = raw_legacy_gates(gpath)
            provenance["gates_source"] = str(gpath)
        elif using_new:
            data.setdefault("gates", {})
            provenance["gates_source"] = str(new_path)
        else:
            gpath = default_gates_path(root)
            data["gates"], legacy_gate_error = raw_legacy_gates(gpath)
            provenance["gates_source"] = str(gpath)

    # --- model tiers (roles → ids); before local so local can overlay ---
    tier_info: dict[str, Any] = {"source": "effective", "error": None, "local_config": None}
    if "model_tiers" in selected:
        if model_tiers_env:
            mt_path = Path(model_tiers_env)
            _model_tiers.clear_cache()
            tiers = _model_tiers.load(mt_path, use_cache=False)
            tier_info.update(source=tiers.source, error=tiers.error)
            data["model_tiers"] = _model_tiers.public_dict(tiers)
            provenance["model_tiers_source"] = str(mt_path)
        elif using_new and isinstance(data.get("model_tiers"), dict) and data["model_tiers"]:
            provenance["model_tiers_source"] = str(new_path)
        else:
            mt_path = default_model_tiers_path(root)
            _model_tiers.clear_cache()
            tiers = _model_tiers.load(mt_path, use_cache=False)
            tier_info.update(source=tiers.source, error=tiers.error)
            data["model_tiers"] = _model_tiers.public_dict(tiers)
            provenance["model_tiers_source"] = str(mt_path)

    # --- joint install/keys metadata; absence is optional for unrelated readers ---
    if selected & CATALOG_DOMAINS:
        if using_new:
            provenance["install_source"] = provenance["keys_source"] = str(new_path)
        else:
            path = root / "config/install.toml"
            if present(path):
                raw_catalog = read(path)
                require_schema_version(raw_catalog, path, required=True)
                validate_tree(raw_catalog, read_catalog_schema(root), label=str(path))
                try:
                    _catalog.validate_catalog_semantics(raw_catalog, path=path)
                    projected = _catalog.project_catalog(raw_catalog)
                except _catalog.CatalogValidationError as error:
                    raise ConfigError(str(error)) from error
                data.update(_domain_view(projected, selected))
                provenance["install_source"] = provenance["keys_source"] = str(path)

    # Context-only consumers do not load routing, gates, tiers or catalog files.
    # Absent legacy input (or absent unified domain) keeps the CLI's defaults;
    # a unified file never revives the legacy context-budget file.
    if "context_budget" in selected:
        if using_new:
            provenance["context_budget_source"] = str(new_path)
        else:
            path = root / "config/context-budget.toml"
            if present(path):
                projected = {"context_budget": read(path)}
                validate_context_budget(projected, path=path)
                data.update(projected)
                provenance["context_budget_source"] = str(path)

    # --- local override ---
    if using_local:
        local = read(local_path)
        require_schema_version(local, local_path, required=False)
        unknown_top_level(local, local_path)
        validate_tree(local, schema, label=str(local_path), partial=True)
        reject_duplicate_services(local.get("service"), label=str(local_path))
        _validate_catalog_domains(local, local_path)
        validate_context_budget(local, path=local_path)
        merge_src = _domain_view(local, selected)
        merge_src.pop("schema_version", None)
        if routing_env:
            for key in ROUTING_DOMAIN_KEYS:
                merge_src.pop(key, None)
        if gates_env:
            merge_src.pop("gates", None)
        if model_tiers_env:
            merge_src.pop("model_tiers", None)
        elif "model_tiers" in merge_src:
            tier_info.update(source="effective", local_config=str(local_path))
        data = merge_maps(data, merge_src, path="")
        provenance["local_config"] = str(local_path)

    provenance["model_tiers_info"] = tier_info
    reject_duplicate_services(data.get("service"), label="effective config")
    if "gates" in selected:
        gates, ginfo = project_gates_from_new(
            data["gates"], source_label=provenance["gates_source"]
        )
        if legacy_gate_error:
            ginfo.update(source="code", toml_error=legacy_gate_error)
        data["gates"] = gates
        provenance["gates_info"] = ginfo
    _validate_catalog_domains(data, Path("effective config"))
    validate_context_budget(data, path=Path("effective config"))

    validate_tree(data, schema, label="effective config")

    return EffectiveConfig(data=data, provenance=provenance)


def decode_table_key_chain(line: str) -> tuple[str, tuple[str, ...]]:
    """Decode exactly one table/AoT key chain with the stdlib TOML parser."""
    if any(c in line for c in ("\n", "\r", "\0")):
        raise ConfigError("table paths must be a single line")
    try:
        node = tomllib.loads(line + "\n")
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"unsupported table/path form: {line!r} ({error})") from error
    parts = []
    while isinstance(node, dict) and len(node) == 1:
        part, node = next(iter(node.items()))
        if not part or any(c in part for c in ("\n", "\r", "\0")):
            raise ConfigError("table path parts must be nonempty single-line names")
        parts.append(part)
    kind = "aot" if line.startswith("[[") else "table"
    if not parts or (node != {} if kind == "table" else node != [{}]):
        raise ConfigError("only a single table key chain is supported")
    return kind, tuple(parts)


def metadata_path_parts(dotted: str) -> tuple[str, ...]:
    """Parse only a single TOML metadata key chain, never array selectors."""
    if not dotted or dotted.strip() != dotted or any(c in dotted for c in "[]\n\r\0"):
        raise ConfigError("metadata paths require a single key chain without array selectors")
    kind, parts = decode_table_key_chain("[" + dotted + "]")
    if kind != "table" or parts[0] not in {"keys", "context_budget"}:
        raise ConfigError("quoted metadata paths must start with keys or context_budget")
    return parts

def get_path(data: dict[str, Any], dotted: str) -> Any:
    """Resolve a dotted path; ``service[name=claude]`` selects a service by name."""
    if not dotted:
        raise ConfigError("get path is empty")
    cur: Any = data
    parts = metadata_path_parts(dotted) if dotted.startswith(("context_budget.", "keys.")) else dotted.split(".")
    for part in parts:
        if part.startswith("service[name=") and part.endswith("]"):
            name = part[len("service[name="):-1]
            services = cur.get("service") if isinstance(cur, dict) else None
            if not isinstance(services, list):
                raise ConfigError(f"missing service array for {dotted!r}")
            for entry in services:
                if isinstance(entry, dict) and entry.get("name") == name:
                    cur = entry
                    break
            else:
                raise ConfigError(f"no service named {name!r}")
            continue
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
            continue
        if isinstance(cur, list) and part.isdigit():
            idx = int(part)
            if idx < 0 or idx >= len(cur):
                raise ConfigError(f"index {idx} out of range at {dotted!r}")
            cur = cur[idx]
            continue
        raise ConfigError(f"missing {dotted!r} (at {part!r})")
    return cur


def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            out.update(_flatten(v, p))
    elif isinstance(obj, list):
        # whole-array identity for diff: store JSON-ish marker under the prefix
        out[prefix] = obj
    else:
        out[prefix] = obj
    return out


def diff_dicts(before: dict[str, Any], after: dict[str, Any]) -> list[Change]:
    flat_b = _flatten(before)
    flat_a = _flatten(after)
    keys = sorted(set(flat_b) | set(flat_a))
    changes: list[Change] = []
    for key in keys:
        if key not in flat_b:
            changes.append(Change(key, None, flat_a[key]))
        elif key not in flat_a:
            changes.append(Change(key, flat_b[key], None))
        elif flat_b[key] != flat_a[key]:
            changes.append(Change(key, flat_b[key], flat_a[key]))
    return changes


def load_without_local(
    *,
    root: Path,
    home: Path,
    new_config: Path | None = None,
    environ: dict[str, str] | None = None,
) -> EffectiveConfig:
    """Effective tree with local resolution/loading explicitly disabled."""
    return load_effective(
        root=root,
        home=home,
        new_config=new_config,
        include_local=False,
        environ=environ,
    )


def local_diff(
    *,
    root: Path | None = None,
    home: Path | None = None,
    environ: dict[str, str] | None = None,
) -> list[Change]:
    root = (root or repo_root_from_here()).resolve()
    home_path = home if home is not None else Path.home()
    with_local = load_effective(root=root, home=home_path, environ=environ)
    without = load_without_local(root=root, home=home_path, environ=environ)
    return diff_dicts(without.data, with_local.data)


# A deliberately bounded JSON Schema evaluator: these are all assertion keywords
# used by the checked-in schema. Unknown keywords fail closed rather than silently
# pretending to validate a future schema. No optional dependency or live imports.
_SCHEMA_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": is_num,
    "boolean": lambda v: isinstance(v, bool),
}
_SCHEMA_ANNOTATIONS = {"$schema", "$id", "title", "description"}
_SCHEMA_ASSERTIONS = {"type", "const", "required", "properties", "additionalProperties", "items", "minLength"}


def _check_schema_node(node: Any, path: str) -> None:
    if not isinstance(node, dict):
        raise ConfigError(f"{path}: schema node must be an object")
    unknown = set(node) - _SCHEMA_ANNOTATIONS - _SCHEMA_ASSERTIONS
    if unknown:
        raise ConfigError(f"{path}: unsupported schema keywords {sorted(unknown)}")
    if "type" in node and (not isinstance(node["type"], str) or node["type"] not in _SCHEMA_TYPES):
        raise ConfigError(f"{path}: unsupported schema type")
    if "required" in node and not (
        isinstance(node["required"], list) and all(isinstance(k, str) for k in node["required"])
    ):
        raise ConfigError(f"{path}: schema required must be a string array")
    if "minLength" in node and (type(node["minLength"]) is not int or node["minLength"] < 0):
        raise ConfigError(f"{path}: invalid schema minLength")
    props = node.get("properties", {})
    if not isinstance(props, dict):
        raise ConfigError(f"{path}: schema properties must be an object")
    for key, child in props.items():
        _check_schema_node(child, f"{path}.{key}")
    if "items" in node:
        _check_schema_node(node["items"], f"{path}.items")
    extra = node.get("additionalProperties", True)
    if isinstance(extra, dict):
        _check_schema_node(extra, f"{path}.additionalProperties")
    elif not isinstance(extra, bool):
        raise ConfigError(f"{path}: invalid schema additionalProperties")


def read_schema(schema_path: Path) -> dict[str, Any]:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as e:
        raise ConfigError(f"{schema_path}: invalid or unreadable schema ({e})") from e
    try:
        _check_schema_node(schema, str(schema_path))
    except RecursionError as e:
        raise ConfigError(f"{schema_path}: schema nesting is too deep") from e
    if schema.get("title") != "djbclark-ade effective config":
        raise ConfigError(f"{schema_path}: unexpected title")
    if schema.get("properties", {}).get("schema_version", {}).get("const") != SCHEMA_VERSION:
        raise ConfigError(f"{schema_path}: unsupported schema version declaration")
    return schema


def validate_tree(data: Any, schema: dict[str, Any], *, label: str, partial: bool = False) -> None:
    """Enforce the declared schema on raw or effective data; local omits root version only."""
    kind = schema.get("type")
    if kind and not _SCHEMA_TYPES[kind](data):
        raise ConfigError(f"{label}: must be {kind}")
    if "const" in schema and (type(data) is not type(schema["const"]) or data != schema["const"]):
        raise ConfigError(f"{label}: must equal {schema['const']!r}")
    if isinstance(data, str) and len(data) < schema.get("minLength", 0):
        raise ConfigError(f"{label}: string is too short")
    if isinstance(data, dict):
        for key in schema.get("required", []):
            if key not in data and not (partial and key == "schema_version"):
                raise ConfigError(f"{label}: missing required key {key}")
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, value in data.items():
            child = props.get(key, extra)
            if child is False:
                raise ConfigError(f"{label}: unknown key {key}")
            if isinstance(child, dict):
                validate_tree(value, child, label=f"{label}.{key}")
    if isinstance(data, list) and "items" in schema:
        for i, value in enumerate(data):
            validate_tree(value, schema["items"], label=f"{label}[{i}]")


def validate_schema_file(schema_path: Path) -> list[str]:
    try:
        read_schema(schema_path)
    except ConfigError as e:
        return [str(e)]
    return []


def check(
    *,
    root: Path | None = None,
    home: Path | None = None,
    environ: dict[str, str] | None = None,
) -> tuple[list[str], EffectiveConfig | None]:
    """Return (errors, effective_or_None). Empty errors means OK. No writes."""
    root = (root or repo_root_from_here()).resolve()
    home_path = home if home is not None else Path.home()
    try:
        effective = load_effective(root=root, home=home_path, environ=environ)
    except ConfigError as e:
        return [str(e)], None
    return [], effective
