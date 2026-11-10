"""ade_install: install catalog, plan, observe-only doctor/keys, linux-e2e dry-run, bounded apply.

Transitional source: ``config/install.toml`` when ``config/ade.toml`` is absent.
Key entries are names and metadata only. Doctor runs ``probe_argv`` when
recorded (else PATH presence), checks Linux systemd linger when ade-sched
jobs are installed (``just linger`` / enable-linger; never sudo), and never
repairs. ``keys`` runs observe-only ``sudo-secretspec check`` (no values).
``linux_e2e`` / ``ade-install linux-e2e`` chains doctor + keys + hard-dep
apply ``--dry-run`` (and Linux ``system_argv`` preview) so CI can prove the
one-step path without a Mac. Apply is user-scoped only: ``--dry-run`` by
default, ``--yes`` to execute recorded ``install_argv`` (argv lists, never
shell=True). Root / live ``--system`` effects are refused until a later unit.
Secrets are never read.
"""
from __future__ import annotations

import copy
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

BIN = Path(__file__).resolve().parent
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import ade_config as ac  # noqa: E402

SCHEMA_VERSION = 1
LEDGER_SCHEMA_VERSION = 1
UNKNOWN = "UNKNOWN"
COMPONENT_CLASSES = frozenset({"hard", "offered", "optional", "suggested", "never"})
# Classes that require an explicit chosen bool in the catalog.
CHOICE_CLASSES = frozenset({"offered", "optional", "suggested"})

# Placeholders expanded in install_argv / update_argv / probe_argv before exec.
ARGV_TOKENS = ("{bin}", "{root}", "{home}", "{prefix}")

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


@dataclass(frozen=True)
class Observation:
    kind: str  # component | key | login | catalog | sched
    id: str
    status: str  # ok | missing | unknown | error | unchosen | never | warn
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


def _validate_argv_field(row: dict[str, Any], *, field: str, path: Path, index: int) -> None:
    val = row.get(field)
    if val is None:
        return
    if not isinstance(val, list) or not val:
        raise InstallError(
            f"{path}: component[{index}] id={row.get('id')!r}: "
            f"{field} must be a non-empty array of strings"
        )
    for j, part in enumerate(val):
        if not isinstance(part, str) or not part:
            raise InstallError(
                f"{path}: component[{index}].{field}[{j}] must be a non-empty string"
            )
        if any(ch in part for ch in ("\0", "\n", "\r")):
            raise InstallError(
                f"{path}: component[{index}].{field}[{j}]: control characters refused"
            )


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


def observe_component(
    row: dict[str, Any],
    *,
    root: Path | None = None,
    runner: Runner | None = None,
    probe_timeout_s: float = 15.0,
) -> Observation:
    """Observe one component. Never repairs.

    Prefer ``probe_argv`` (run the tool) when recorded; otherwise PATH ``presence``.
    """
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
    detail = f"reference only; verify={verify}; expiry={expiry} (no value read)"
    return Observation("key", name, "unknown", detail)


def observe_login(row: dict[str, Any]) -> Observation:
    lid = str(row["id"])
    cmd = row.get("command") or UNKNOWN
    if cmd == UNKNOWN:
        return Observation("login", lid, "unknown", "login command not recorded")
    return Observation("login", lid, "unknown", f"login check recorded as {cmd!r}; not executed")


SECRETSPEC_CHECK_ARGV = [
    "sudo-secretspec",
    "check",
    "--reason",
    "ade-install keys",
]


def observe_secretspec_check(
    *,
    runner: Runner | None = None,
    timeout_s: float = 30.0,
    cwd: Path | None = None,
) -> Observation:
    """Observe-only bulk presence check via ``sudo-secretspec check``.

    Never calls get/export/set/run. Does not print or request secret values.
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


def keys_observe(
    catalog: Catalog,
    *,
    runner: Runner | None = None,
    timeout_s: float = 30.0,
) -> tuple[list[Observation], int]:
    """Observe-only keys path (S3b presence half).

    Lists catalog key references, then runs ``sudo-secretspec check`` when the
    binary exists. Exit 1 only when check runs and fails; missing binary is
    ``unknown`` (exit 0) so Linux/CI without the boundary stays observant.
    Never verifies individual keys and never reads values.
    """
    obs: list[Observation] = [
        Observation("catalog", str(catalog.path), "ok", "catalog validated"),
    ]
    for row in catalog.keys:
        obs.append(observe_key(row))
    for row in catalog.logins:
        obs.append(observe_login(row))
    check = observe_secretspec_check(
        runner=runner,
        timeout_s=timeout_s,
        cwd=catalog.root,
    )
    obs.append(check)
    rc = 1 if check.status in ("missing", "error") else 0
    return obs, rc


def hard_component_ids(catalog: Catalog) -> set[str]:
    """Ids of hard-class components (always expected on a full install)."""
    return {str(row["id"]) for row in catalog.components if str(row["class"]) == "hard"}


def linux_e2e(
    catalog: Catalog,
    *,
    runner: Runner | None = None,
    probe_timeout_s: float = 15.0,
    sched_linger: Observation | None = None,
    skip_sched_linger: bool = False,
    secretspec_runner: Runner | None = None,
    secretspec_timeout_s: float = 30.0,
    prefix: Path | None = None,
) -> tuple[dict[str, Any], int]:
    """Linux one-step prove path: doctor (hard + linger) + keys + hard apply dry-run.

    Always dry-run for apply; never sudo; never enables linger; never reads
    secret values. Passes ``allow_system=True`` only so Linux ``system_argv``
    harddeps preview as ``would-system-install`` (live system exec still
    refused). Mac ``system_argv_darwin`` is not required. Injectable linger /
    runners keep CI hermetic without a Mac or live secretspec.
    """
    doctor_obs, doctor_rc = doctor(
        catalog,
        runner=runner,
        probe_timeout_s=probe_timeout_s,
        sched_linger=sched_linger,
        skip_sched_linger=skip_sched_linger,
    )
    keys_obs, keys_rc = keys_observe(
        catalog,
        runner=secretspec_runner,
        timeout_s=secretspec_timeout_s,
    )
    hard_ids = hard_component_ids(catalog)
    # Pass the set through even when empty: build_apply_steps treats None as
    # "every component" and an empty set as "select nothing" (hard-only dry-run).
    apply_results, apply_rc = apply(
        catalog,
        dry_run=True,
        ids=hard_ids,
        allow_system=True,
        prefix=prefix,
        runner=runner,
    )
    # Compose report; doctor observations already include key refs + linger.
    linger = [o for o in doctor_obs if o.kind == "sched" and o.id == "linger"]
    secretspec = [o for o in keys_obs if o.kind == "secretspec"]
    hard_comp = [
        o for o in doctor_obs
        if o.kind == "component" and o.id in hard_ids
    ]
    report: dict[str, Any] = {
        "ok": doctor_rc == 0 and keys_rc == 0 and apply_rc == 0,
        "mode": "linux-e2e-dry-run",
        "stages": {
            "doctor": {"rc": doctor_rc, "observations": [
                {"kind": o.kind, "id": o.id, "status": o.status, "detail": o.detail}
                for o in doctor_obs
            ]},
            "keys": {"rc": keys_rc, "observations": [
                {"kind": o.kind, "id": o.id, "status": o.status, "detail": o.detail}
                for o in keys_obs
            ]},
            "apply_hard_dry_run": {"rc": apply_rc, "results": apply_results},
        },
        "hard_ids": sorted(hard_ids),
        "linger": (
            {"status": linger[0].status, "detail": linger[0].detail}
            if linger else None
        ),
        "secretspec_check": (
            {"status": secretspec[0].status, "detail": secretspec[0].detail}
            if secretspec else None
        ),
        "hard_component_statuses": {
            o.id: o.status for o in hard_comp
        },
        "note": (
            "observe-only doctor + keys; apply --dry-run for hard ids with "
            "allow_system preview; never sudo; never enable-linger; no Mac required"
        ),
    }
    rc = 0 if report["ok"] else 1
    return report, rc


def linger_off_doctor_detail(labels: list[str]) -> str:
    """Doctor detail for Linger=no with installed systemd jobs (never names sudo)."""
    names = ", ".join(labels) if labels else "(none)"
    return (
        f"Linger=no with installed ade-sched systemd job(s): {names}; "
        f"user timers stop at logout. Check with `just linger` / `ade-sched linger`; "
        f"enable-linger once for boot-time user timers (doctor never enables linger)."
    )


def observe_sched_linger(
    *,
    env: dict[str, str] | None = None,
    detect_fn: Callable[..., Any] | None = None,
    linger_fn: Callable[..., str | None] | None = None,
    labels_fn: Callable[..., list[str]] | None = None,
) -> Observation:
    """Observe systemd linger when ade-sched jobs are present (Linux residual after just linger).

    launchd/cron → ok ``linger: n/a`` (macOS / cron unchanged for exit). systemd with
    installed ADE jobs and ``Linger=no`` → ``warn`` (doctor FAILs). Never runs sudo /
    never enables linger. Detect/linger failures are ``unknown``, not a hard fail.
    """
    # Lazy import: catalog check / plan stay independent of ade_sched.
    import ade_sched as sched  # noqa: PLC0415

    detect = detect_fn or sched.detect
    linger = linger_fn or sched.linger
    labels = labels_fn or sched.installed_labels
    try:
        backend = detect(env=env)
    except sched.SchedError as e:
        return Observation(
            "sched", "linger", "unknown",
            f"scheduler unavailable for linger check: {e}",
        )
    except OSError as e:
        return Observation(
            "sched", "linger", "unknown",
            f"scheduler probe error for linger check: {e}",
        )
    name = backend.name
    if name in ("launchd", "cron"):
        return Observation(
            "sched", "linger", "ok",
            f"linger: n/a (backend={name})",
        )
    if name != "systemd":
        return Observation(
            "sched", "linger", "ok",
            f"linger: n/a (backend={name})",
        )
    try:
        installed = list(labels(backend, env=backend.env))
    except (sched.SchedError, OSError, TypeError) as e:
        return Observation(
            "sched", "linger", "unknown",
            f"could not list ade-sched systemd jobs: {e}",
        )
    try:
        state = linger(env=backend.env)
    except (sched.SchedError, OSError) as e:
        return Observation(
            "sched", "linger", "unknown",
            f"could not read Linger: {e}",
        )
    if not installed:
        return Observation(
            "sched", "linger", "ok",
            f"linger: {state or 'unknown'} (no ade-sched systemd jobs)",
        )
    if state == "no":
        return Observation(
            "sched", "linger", "warn",
            linger_off_doctor_detail(installed),
        )
    if state == "yes":
        return Observation(
            "sched", "linger", "ok",
            f"linger: yes ({len(installed)} ade-sched systemd job(s))",
        )
    return Observation(
        "sched", "linger", "unknown",
        f"linger: unknown with {len(installed)} ade-sched systemd job(s); "
        f"check with `just linger`",
    )


def doctor(
    catalog: Catalog,
    *,
    runner: Runner | None = None,
    probe_timeout_s: float = 15.0,
    sched_linger: Observation | None = None,
    skip_sched_linger: bool = False,
) -> tuple[list[Observation], int]:
    """Observe-only doctor. Exit 1 if any expected component is missing/error, or
    when Linux systemd jobs are installed with Linger=no; never repairs."""
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
        if expected_installed(row) and o.status in ("missing", "error"):
            hard_missing += 1
    for row in catalog.keys:
        obs.append(observe_key(row))
    for row in catalog.logins:
        obs.append(observe_login(row))
    if not skip_sched_linger:
        linger_obs = sched_linger if sched_linger is not None else observe_sched_linger()
        obs.append(linger_obs)
        # WARN line + FAIL exit when Linger=no with installed systemd jobs.
        if linger_obs.status in ("warn", "error", "missing"):
            hard_missing += 1
    return obs, (1 if hard_missing else 0)


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
            reason = (
                "needs_system=true; ade-install apply --system --dry-run shows system_argv; "
                "execution of system_argv remains refused"
            )
            resolved = None
            if sys_argv:
                try:
                    resolved = expand_argv(sys_argv, root=catalog.root)
                    reason = reason + "; argv=" + " ".join(
                        shlex.quote(a) for a in resolved
                    )
                except InstallError as e:
                    reason = f"{reason}; system_argv invalid: {e}"
            elif row.get("install_argv"):
                reason = reason + "; system_argv missing (install_argv is user-scoped only)"
            steps.append({
                "id": cid,
                "action": "needs-system",
                "reason": reason,
                "needs_system": True,
                **({"argv": resolved} if resolved else {}),
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
            steps.append({
                "id": cid,
                "action": "would-install",
                "reason": " ".join(shlex.quote(a) for a in resolved),
                "argv": resolved,
                "needs_system": False,
                "note": "ade-install apply --yes runs install_argv; default is --dry-run",
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
    return {
        "path": str(catalog.path),
        "schema_version": catalog.data.get("schema_version"),
        "components": len(catalog.components),
        "keys": len(catalog.keys),
        "logins": len(catalog.logins),
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


def build_apply_steps(
    catalog: Catalog,
    *,
    ids: set[str] | None = None,
    force: bool = False,
    allow_system: bool = False,
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
        if not expected_installed(row):
            steps.append(ApplyStep(cid, "skip", None, f"class={row['class']} chosen={row.get('chosen')}"))
            continue
        obs = observe_component(row, root=catalog.root)
        if obs.status == "ok" and not force:
            steps.append(ApplyStep(cid, "skip", None, f"already present ({obs.detail})"))
            continue
        if row.get("needs_system"):
            if not allow_system:
                steps.append(ApplyStep(
                    cid, "refuse-system", None,
                    "needs_system=true; pass --system --dry-run to preview system_argv",
                ))
                continue
            sys_raw = pick_system_argv(row)
            if not sys_raw:
                steps.append(ApplyStep(
                    cid, "blocked", None,
                    "needs_system but no system_argv for this platform",
                ))
                continue
            try:
                argv = expand_argv(list(sys_raw), root=catalog.root, prefix=prefix)
            except InstallError as e:
                steps.append(ApplyStep(cid, "blocked", None, str(e)))
                continue
            steps.append(ApplyStep(
                cid, "would-system-install", argv,
                "system dry-run only; execution of system_argv is refused",
                detail=shlex.join(argv),
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


def apply(
    catalog: Catalog,
    *,
    dry_run: bool = True,
    ids: set[str] | None = None,
    force: bool = False,
    allow_system: bool = False,
    state_dir: Path | None = None,
    prefix: Path | None = None,
    runner: Runner | None = None,
    timeout_s: float = 300.0,
) -> tuple[list[dict[str, Any]], int]:
    """Bounded apply. Default dry-run. ``--yes`` executes user ``install_argv`` only.

    ``--system`` unlocks dry-run preview of ``system_argv`` (``would-system-install``).
    Executing ``system_argv`` is always refused (exit 2) — root effects need a later unit.

    Exit 0 when every selected step is skip/would-install(dry)/install ok /
    would-system-install(dry); 1 when any blocked/failed/refuse-system; 2 when a
    system_argv step would have been executed.
    """
    steps = build_apply_steps(
        catalog, ids=ids, force=force, allow_system=allow_system, prefix=prefix,
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
            # Never execute package-manager / root argv in this unit.
            system_exec_refused += 1
            row["action"] = "refuse-system-exec"
            row["ok"] = False
            row["reason"] = (
                "system_argv execution refused; use --system --dry-run to preview only "
                "(live system apply is a later unit)"
            )
        elif step.action == "would-install" and not dry_run:
            assert step.argv is not None
            # Persist pending intent before the write (setup-plan S3 ownership note).
            assert ledger is not None
            entries = ledger.setdefault("entries", {})
            entries[step.id] = {
                "status": "pending",
                "argv": list(step.argv),
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            save_ledger(state_dir, ledger)
            try:
                proc = _run(list(step.argv), catalog.root)
            except subprocess.TimeoutExpired as e:
                failed += 1
                row["action"] = "failed"
                row["ok"] = False
                row["reason"] = f"timed out after {timeout_s}s"
                entries[step.id] = {
                    "status": "failed",
                    "argv": list(step.argv),
                    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "detail": row["reason"],
                }
                save_ledger(state_dir, ledger)
                results.append(row)
                continue
            except OSError as e:
                failed += 1
                row["action"] = "failed"
                row["ok"] = False
                row["reason"] = f"exec error: {e}"
                entries[step.id] = {
                    "status": "failed",
                    "argv": list(step.argv),
                    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "detail": str(e),
                }
                save_ledger(state_dir, ledger)
                results.append(row)
                continue
            if proc.returncode != 0:
                failed += 1
                row["action"] = "failed"
                row["ok"] = False
                row["returncode"] = proc.returncode
                err = (proc.stderr or proc.stdout or "").strip()
                row["reason"] = err[:500] or f"exit {proc.returncode}"
                entries[step.id] = {
                    "status": "failed",
                    "argv": list(step.argv),
                    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "returncode": proc.returncode,
                    "detail": row["reason"],
                }
                save_ledger(state_dir, ledger)
            else:
                row["action"] = "installed"
                row["ok"] = True
                row["returncode"] = 0
                row["reason"] = "install_argv completed"
                entries[step.id] = {
                    "status": "installed",
                    "argv": list(step.argv),
                    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
                save_ledger(state_dir, ledger)
        elif step.action in ("blocked", "refuse-system", "refuse-system-exec"):
            failed += 1
            row["ok"] = False
        results.append(row)

    if system_exec_refused:
        return results, 2
    # dry-run with only skips/would-install/would-system-install → 0; any blocked → 1
    if dry_run:
        rc = 1 if any(
            r["action"] in ("blocked", "refuse-system", "refuse-system-exec")
            for r in results
        ) else 0
    else:
        rc = 1 if failed else 0
    return results, rc
