"""ade_harden: observe-only GitHub hardening drift check (setup-plan S6).

Transitional source: ``config/hardening.toml`` when ``config/ade.toml`` lacks a
``[hardening]`` table. Reads wanted settings back via ``gh api`` (observe only).
Never writes rulesets, never renews interaction limits, never runs ``just harden``
apply. Live apply / auto-reapply stay deferred (setup-plan contract §7).
"""
from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

BIN = Path(__file__).resolve().parent
import sys

if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import ade_config as ac  # noqa: E402

SCHEMA_VERSION = 1
DEFAULT_API_VERSION = "2026-03-10"
IGNORE = "ignore"

POLICY_KEYS = (
    "pr_creation_policy",
    "issue_creation_policy",
    "disable_wiki",
    "disable_projects",
    "disable_discussions",
    "fork_pr_workflows_approval",
    "default_workflow_permissions",
    "can_approve_pull_request_reviews",
    "secret_scanning",
    "secret_scanning_push_protection",
    "merge_gate_ruleset",
    "ruleset_name",
)

PR_POLICIES = frozenset({"collaborators_only", "all", "disabled", IGNORE})
ISSUE_POLICIES = frozenset({"collaborators_only", "all", "disabled", IGNORE})
WORKFLOW_PERMS = frozenset({"read", "write", IGNORE})
SECRET_STATES = frozenset({"enabled", "disabled", IGNORE})
PROFILES = frozenset({"active", "fork"})
INTERACTION_LIMITS = frozenset(
    {"collaborators_only", "existing_users", "contributors_only", IGNORE}
)
# GitHub interaction-limit expiry enum (config/hardening.schema.json).
INTERACTION_EXPIRIES = frozenset(
    {"one_day", "three_days", "one_week", "one_month", "six_months"}
)
DEFAULT_INTERACTION_EXPIRY = "six_months"

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


class HardenError(ac.ConfigError):
    """Invalid hardening config or refused operation."""


@dataclass
class HardenConfig:
    data: dict[str, Any]
    path: Path
    root: Path
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def hardening(self) -> dict[str, Any]:
        return dict(self.data.get("hardening") or {})

    @property
    def api_version(self) -> str:
        return str(self.hardening.get("api_version") or DEFAULT_API_VERSION)

    @property
    def owners(self) -> list[str]:
        raw = self.hardening.get("owners") or []
        return [str(x) for x in raw if str(x).strip()]

    @property
    def defaults(self) -> dict[str, Any]:
        return dict(self.hardening.get("defaults") or {})

    @property
    def forks(self) -> dict[str, Any]:
        return dict(self.hardening.get("forks") or {})

    @property
    def interaction_limits(self) -> dict[str, Any]:
        return dict(self.hardening.get("interaction_limits") or {})

    @property
    def repos(self) -> list[dict[str, Any]]:
        rows = self.hardening.get("repo") or []
        return [dict(r) for r in rows if isinstance(r, dict)]


@dataclass(frozen=True)
class DriftFinding:
    """One observe-only comparison of wanted vs found."""

    target: str
    setting: str
    wanted: Any
    found: Any
    status: str  # ok | drift | missing | unknown | deferred | uncovered
    detail: str = ""
    remediation: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "target": self.target,
            "setting": self.setting,
            "wanted": self.wanted,
            "found": self.found,
            "status": self.status,
            "detail": self.detail,
        }
        if self.remediation:
            out["remediation"] = self.remediation
        return out


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parent.parent


def default_config_path(root: Path) -> Path:
    return root / "config" / "hardening.toml"


def default_schema_path(root: Path) -> Path:
    return root / "config" / "hardening.schema.json"


def _is_ignore(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() == IGNORE:
        return True
    return False


def _validate_policy_table(
    table: dict[str, Any], *, path: Path, label: str
) -> list[str]:
    errors: list[str] = []
    unknown = sorted(set(table) - set(POLICY_KEYS))
    if unknown:
        errors.append(f"{path}: {label} unknown keys {unknown}")
    pr = table.get("pr_creation_policy")
    if pr is not None and pr not in PR_POLICIES:
        errors.append(f"{path}: {label}.pr_creation_policy invalid: {pr!r}")
    issue = table.get("issue_creation_policy")
    if issue is not None and issue not in ISSUE_POLICIES:
        errors.append(f"{path}: {label}.issue_creation_policy invalid: {issue!r}")
    wp = table.get("default_workflow_permissions")
    if wp is not None and wp not in WORKFLOW_PERMS:
        errors.append(
            f"{path}: {label}.default_workflow_permissions invalid: {wp!r}"
        )
    for key in ("secret_scanning", "secret_scanning_push_protection"):
        val = table.get(key)
        if val is not None and val not in SECRET_STATES:
            errors.append(f"{path}: {label}.{key} invalid: {val!r}")
    for key in ("disable_wiki", "disable_projects", "disable_discussions", "merge_gate_ruleset"):
        if key in table and not isinstance(table[key], bool):
            errors.append(f"{path}: {label}.{key} must be bool")
    cap = table.get("can_approve_pull_request_reviews")
    if cap is not None and not isinstance(cap, bool) and not _is_ignore(cap):
        errors.append(
            f"{path}: {label}.can_approve_pull_request_reviews must be bool or ignore"
        )
    return errors


def _validate_hardening(data: dict[str, Any], *, path: Path) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            f"{path}: schema_version must be {SCHEMA_VERSION} "
            f"(got {data.get('schema_version')!r})"
        )
    hard = data.get("hardening")
    if not isinstance(hard, dict):
        errors.append(f"{path}: [hardening] table required")
        return errors
    defaults = hard.get("defaults")
    if not isinstance(defaults, dict):
        errors.append(f"{path}: [hardening.defaults] required")
    else:
        errors.extend(_validate_policy_table(defaults, path=path, label="defaults"))
    forks = hard.get("forks")
    if forks is not None:
        if not isinstance(forks, dict):
            errors.append(f"{path}: [hardening.forks] must be a table")
        else:
            errors.extend(_validate_policy_table(forks, path=path, label="forks"))
    owners = hard.get("owners")
    if owners is not None:
        if not isinstance(owners, list) or any(not isinstance(x, str) or not x for x in owners):
            errors.append(f"{path}: hardening.owners must be a string array")
    il = hard.get("interaction_limits")
    if il is not None:
        if not isinstance(il, dict):
            errors.append(f"{path}: [hardening.interaction_limits] must be a table")
        else:
            lim = il.get("limit")
            if lim is not None and lim not in INTERACTION_LIMITS:
                errors.append(f"{path}: interaction_limits.limit invalid: {lim!r}")
            days = il.get("min_remaining_days")
            if days is not None and not (isinstance(days, int) and days >= 0):
                errors.append(
                    f"{path}: interaction_limits.min_remaining_days must be int >= 0"
                )
            expiry = il.get("expiry")
            if expiry is not None and expiry not in INTERACTION_EXPIRIES:
                errors.append(
                    f"{path}: interaction_limits.expiry invalid: {expiry!r}"
                )
    forgejo = hard.get("forgejo")
    if forgejo is not None:
        if (
            not isinstance(forgejo, dict)
            or not isinstance(forgejo.get("base_url"), str)
            or not forgejo["base_url"].startswith("https://")
        ):
            errors.append(
                f"{path}: hardening.forgejo.base_url must be an https URL"
            )
    canaries = hard.get("canaries")
    if canaries is not None:
        if (
            not isinstance(canaries, dict)
            or not isinstance(canaries.get("corpus"), str)
            or not canaries["corpus"].strip()
        ):
            errors.append(
                f"{path}: hardening.canaries.corpus must be a non-empty path"
            )
    repos = hard.get("repo") or []
    if not isinstance(repos, list):
        errors.append(f"{path}: [[hardening.repo]] must be an array")
        return errors
    seen: set[str] = set()
    for i, row in enumerate(repos):
        label = f"repo[{i}]"
        if not isinstance(row, dict):
            errors.append(f"{path}: {label} must be a table")
            continue
        owner = row.get("owner")
        name = row.get("name")
        if not isinstance(owner, str) or not owner.strip():
            errors.append(f"{path}: {label}.owner required")
            continue
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{path}: {label}.name required")
            continue
        full = f"{owner}/{name}"
        if full in seen:
            errors.append(f"{path}: duplicate [[hardening.repo]] {full}")
        seen.add(full)
        profile = row.get("profile", "active")
        if profile not in PROFILES:
            errors.append(f"{path}: {label}.profile invalid: {profile!r}")
        # Per-repo overrides use the same policy keys (minus owner/name/profile).
        overrides = {k: v for k, v in row.items() if k not in {"owner", "name", "profile"}}
        errors.extend(_validate_policy_table(overrides, path=path, label=label))
    return errors


def load_config(root: Path | None = None) -> HardenConfig:
    """Load and validate transitional config/hardening.toml."""
    root = (root or repo_root_from_here()).resolve()
    ade = root / "config" / "ade.toml"
    if ade.is_file():
        raise HardenError(
            f"{ade}: present; fold [hardening] into ade.toml before using "
            "config/hardening.toml (setup-plan S1)"
        )
    path = default_config_path(root)
    try:
        data = ac.read_toml(path)
    except ac.ConfigError as e:
        raise HardenError(str(e)) from e
    errors = _validate_hardening(data, path=path)
    if errors:
        raise HardenError("; ".join(errors))
    return HardenConfig(
        data=data,
        path=path,
        root=root,
        provenance={"path": str(path), "schema_version": SCHEMA_VERSION},
    )


def config_summary(cfg: HardenConfig) -> dict[str, Any]:
    hard = cfg.hardening
    return {
        "path": str(cfg.path.relative_to(cfg.root))
        if cfg.path.is_relative_to(cfg.root)
        else str(cfg.path),
        "owners": cfg.owners,
        "repo_count": len(cfg.repos),
        "repos": [f"{r['owner']}/{r['name']}" for r in cfg.repos],
        "check_user_interaction_limits": bool(
            hard.get("check_user_interaction_limits", True)
        ),
        "api_version": cfg.api_version,
        "defaults_pr_policy": cfg.defaults.get("pr_creation_policy"),
        "forks_pr_policy": cfg.forks.get("pr_creation_policy"),
    }


def resolve_policy(cfg: HardenConfig, row: dict[str, Any]) -> dict[str, Any]:
    """Merge profile base (defaults/forks) with per-repo overrides."""
    profile = str(row.get("profile") or "active")
    base = dict(cfg.defaults if profile == "active" else cfg.forks)
    for key in POLICY_KEYS:
        if key in row:
            base[key] = row[key]
    return base


def remediation_hint(full_name: str, setting: str) -> str:
    """Print-only remediation line (apply itself is deferred).

    Args are shell-quoted so an attacker-controlled ``--root`` tree cannot
    inject metacharacters into a copied remediation.
    """
    option = setting
    if setting.startswith("has_"):
        option = setting
    cmd = shlex.join(["just", "harden", option, "--repos", full_name])
    return f"{cmd}  # apply deferred; observe-only unit"


def interaction_limits_remediation(expiry: str) -> str:
    """Print-only interaction-limits remediation; ``expiry`` must be enum-valid."""
    cmd = shlex.join(
        ["just", "harden", "interaction_limits", "--expiry", expiry]
    )
    return f"{cmd}  # auto-reapply deferred; observe-only"


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def _gh_json(
    runner: Runner,
    args: list[str],
    *,
    api_version: str,
) -> tuple[Any | None, str]:
    """Run ``gh …``; return (parsed JSON or None, detail)."""
    if shutil.which("gh") is None and runner is _default_runner:
        return None, "gh not on PATH"
    # Inject API version header for REST calls that go through `gh api`.
    full = list(args)
    if full and full[0] == "api" and "-H" not in full and "--header" not in full:
        full[1:1] = ["-H", f"X-GitHub-Api-Version: {api_version}"]
    proc = runner(["gh", *full])
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = err[0] if err else f"gh exit {proc.returncode}"
        return None, detail
    text = (proc.stdout or "").strip()
    if not text:
        return None, "empty gh stdout"
    # Prefer a complete JSON document (array/object, including pretty-printed
    # multiline). Fall back to NDJSON from `gh api --paginate --jq`.
    try:
        return json.loads(text), "ok"
    except json.JSONDecodeError as complete_err:
        if "\n" not in text:
            return None, f"gh JSON: {complete_err}"
        rows: list[Any] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                return None, f"gh NDJSON: {e}"
        if not rows:
            return None, f"gh JSON: {complete_err}"
        return rows, "ok"


def _cmp(
    *,
    target: str,
    setting: str,
    wanted: Any,
    found: Any,
    ok: bool,
    detail: str = "",
    remediation: str | None = None,
) -> DriftFinding:
    if ok:
        return DriftFinding(
            target=target,
            setting=setting,
            wanted=wanted,
            found=found,
            status="ok",
            detail=detail or "match",
        )
    return DriftFinding(
        target=target,
        setting=setting,
        wanted=wanted,
        found=found,
        status="drift",
        detail=detail or f"wanted {wanted!r}, found {found!r}",
        remediation=remediation or remediation_hint(target, setting),
    )


def _observe_repo_units(
    *,
    full: str,
    policy: dict[str, Any],
    repo_data: dict[str, Any],
) -> list[DriftFinding]:
    findings: list[DriftFinding] = []
    pr_policy = policy.get("pr_creation_policy")
    if not _is_ignore(pr_policy):
        hp = repo_data.get("has_pull_requests")
        p = repo_data.get("pull_request_creation_policy")
        if pr_policy == "disabled":
            findings.append(
                _cmp(
                    target=full,
                    setting="has_pull_requests",
                    wanted=False,
                    found=hp,
                    ok=hp is False,
                )
            )
        else:
            findings.append(
                _cmp(
                    target=full,
                    setting="has_pull_requests",
                    wanted=True,
                    found=hp,
                    ok=hp is True,
                )
            )
            findings.append(
                _cmp(
                    target=full,
                    setting="pull_request_creation_policy",
                    wanted=pr_policy,
                    found=p,
                    ok=p == pr_policy,
                )
            )

    issue_policy = policy.get("issue_creation_policy")
    if not _is_ignore(issue_policy):
        hi = repo_data.get("has_issues")
        if issue_policy == "disabled":
            findings.append(
                _cmp(
                    target=full,
                    setting="has_issues",
                    wanted=False,
                    found=hi,
                    ok=hi is False,
                )
            )
        else:
            # REST does not yet expose issue_creation_policy (argon H2, 2026-11-07).
            findings.append(
                DriftFinding(
                    target=full,
                    setting="issue_creation_policy",
                    wanted=issue_policy,
                    found=None,
                    status="deferred",
                    detail=(
                        f"has_issues={hi!r}; collaborators-only issue creation "
                        "has no REST read-back yet (S7 browser / probe)"
                    ),
                )
            )

    for flag, key, setting in (
        ("disable_wiki", "has_wiki", "has_wiki"),
        ("disable_projects", "has_projects", "has_projects"),
        ("disable_discussions", "has_discussions", "has_discussions"),
    ):
        if policy.get(flag) is True:
            found = repo_data.get(key)
            findings.append(
                _cmp(
                    target=full,
                    setting=setting,
                    wanted=False,
                    found=found,
                    ok=found is False,
                )
            )

    sec = policy.get("secret_scanning")
    if not _is_ignore(sec):
        saa = repo_data.get("security_and_analysis") or {}
        status = None
        if isinstance(saa, dict):
            row = saa.get("secret_scanning") or {}
            if isinstance(row, dict):
                status = row.get("status")
        findings.append(
            _cmp(
                target=full,
                setting="secret_scanning",
                wanted=sec,
                found=status,
                ok=status == sec,
            )
        )
    spp = policy.get("secret_scanning_push_protection")
    if not _is_ignore(spp):
        saa = repo_data.get("security_and_analysis") or {}
        status = None
        if isinstance(saa, dict):
            row = saa.get("secret_scanning_push_protection") or {}
            if isinstance(row, dict):
                status = row.get("status")
        findings.append(
            _cmp(
                target=full,
                setting="secret_scanning_push_protection",
                wanted=spp,
                found=status,
                ok=status == spp,
            )
        )
    return findings


def _observe_actions(
    *,
    full: str,
    policy: dict[str, Any],
    run: Runner,
    api_version: str,
) -> list[DriftFinding]:
    findings: list[DriftFinding] = []
    approval = policy.get("fork_pr_workflows_approval")
    if not _is_ignore(approval):
        data, detail = _gh_json(
            run,
            [
                "api",
                f"repos/{full}/actions/permissions/fork-pr-contributor-approval",
            ],
            api_version=api_version,
        )
        if data is None:
            findings.append(
                DriftFinding(
                    target=full,
                    setting="fork_pr_workflows_approval",
                    wanted=approval,
                    found=None,
                    status="unknown",
                    detail=detail,
                )
            )
        else:
            found = data.get("approval_policy") if isinstance(data, dict) else None
            findings.append(
                _cmp(
                    target=full,
                    setting="fork_pr_workflows_approval",
                    wanted=approval,
                    found=found,
                    ok=found == approval,
                )
            )

    wp = policy.get("default_workflow_permissions")
    cap = policy.get("can_approve_pull_request_reviews")
    if not _is_ignore(wp) or not _is_ignore(cap):
        data, detail = _gh_json(
            run,
            ["api", f"repos/{full}/actions/permissions/workflow"],
            api_version=api_version,
        )
        if data is None:
            if not _is_ignore(wp):
                findings.append(
                    DriftFinding(
                        target=full,
                        setting="default_workflow_permissions",
                        wanted=wp,
                        found=None,
                        status="unknown",
                        detail=detail,
                    )
                )
            if not _is_ignore(cap):
                findings.append(
                    DriftFinding(
                        target=full,
                        setting="can_approve_pull_request_reviews",
                        wanted=cap,
                        found=None,
                        status="unknown",
                        detail=detail,
                    )
                )
        else:
            assert isinstance(data, dict)
            if not _is_ignore(wp):
                found = data.get("default_workflow_permissions")
                findings.append(
                    _cmp(
                        target=full,
                        setting="default_workflow_permissions",
                        wanted=wp,
                        found=found,
                        ok=found == wp,
                    )
                )
            if not _is_ignore(cap):
                found = data.get("can_approve_pull_request_reviews")
                findings.append(
                    _cmp(
                        target=full,
                        setting="can_approve_pull_request_reviews",
                        wanted=cap,
                        found=found,
                        ok=found is cap if isinstance(cap, bool) else found == cap,
                    )
                )
    return findings


def _observe_ruleset(
    *,
    full: str,
    policy: dict[str, Any],
    run: Runner,
    api_version: str,
) -> list[DriftFinding]:
    if not policy.get("merge_gate_ruleset"):
        return []
    want_name = str(policy.get("ruleset_name") or "merge-gate")
    data, detail = _gh_json(
        run,
        [
            "api",
            f"repos/{full}/rulesets",
            "--jq",
            "[.[] | {id,name,enforcement,bypass_actors}]",
        ],
        api_version=api_version,
    )
    if data is None:
        return [
            DriftFinding(
                target=full,
                setting="merge_gate_ruleset",
                wanted=want_name,
                found=None,
                status="unknown",
                detail=detail,
            )
        ]
    if not isinstance(data, list):
        return [
            DriftFinding(
                target=full,
                setting="merge_gate_ruleset",
                wanted=want_name,
                found=type(data).__name__,
                status="unknown",
                detail="unexpected rulesets payload",
            )
        ]
    match = next(
        (r for r in data if isinstance(r, dict) and r.get("name") == want_name),
        None,
    )
    if match is None:
        return [
            DriftFinding(
                target=full,
                setting="merge_gate_ruleset",
                wanted={"name": want_name, "enforcement": "active", "bypass_actors": []},
                found=None,
                status="missing",
                detail=f"ruleset {want_name!r} not found",
                remediation=remediation_hint(full, "merge_gate_ruleset"),
            )
        ]
    findings: list[DriftFinding] = []
    enf = match.get("enforcement")
    findings.append(
        _cmp(
            target=full,
            setting="ruleset.enforcement",
            wanted="active",
            found=enf,
            ok=enf == "active",
            remediation=remediation_hint(full, "merge_gate_ruleset"),
        )
    )
    bypass = match.get("bypass_actors")
    # List endpoint may omit bypass_actors; treat missing as unknown, not drift.
    if bypass is None:
        findings.append(
            DriftFinding(
                target=full,
                setting="ruleset.bypass_actors",
                wanted=[],
                found=None,
                status="unknown",
                detail="bypass_actors omitted on list endpoint (no write; observe only)",
            )
        )
    else:
        findings.append(
            _cmp(
                target=full,
                setting="ruleset.bypass_actors",
                wanted=[],
                found=bypass,
                ok=bypass == [],
                remediation=remediation_hint(full, "merge_gate_ruleset"),
            )
        )
    return findings


def observe_repo(
    cfg: HardenConfig,
    row: dict[str, Any],
    *,
    runner: Runner,
) -> list[DriftFinding]:
    """Observe one configured repository (gh read-back only)."""
    full = f"{row['owner']}/{row['name']}"
    policy = resolve_policy(cfg, row)
    api = cfg.api_version
    findings: list[DriftFinding] = []

    repo_data, detail = _gh_json(
        runner,
        [
            "api",
            f"repos/{full}",
            "--jq",
            "{"
            "full_name:.full_name,"
            "fork:.fork,"
            "archived:.archived,"
            "has_pull_requests:.has_pull_requests,"
            "pull_request_creation_policy:.pull_request_creation_policy,"
            "has_issues:.has_issues,"
            "has_wiki:.has_wiki,"
            "has_projects:.has_projects,"
            "has_discussions:.has_discussions,"
            "security_and_analysis:.security_and_analysis"
            "}",
        ],
        api_version=api,
    )
    if repo_data is None:
        return [
            DriftFinding(
                target=full,
                setting="repo",
                wanted="readable",
                found=None,
                status="unknown",
                detail=detail,
            )
        ]
    if not isinstance(repo_data, dict):
        return [
            DriftFinding(
                target=full,
                setting="repo",
                wanted="object",
                found=type(repo_data).__name__,
                status="unknown",
                detail="unexpected repo payload",
            )
        ]

    expected_fork = str(row.get("profile") or "active") == "fork"
    is_fork = bool(repo_data.get("fork"))
    if expected_fork != is_fork:
        findings.append(
            DriftFinding(
                target=full,
                setting="fork",
                wanted=expected_fork,
                found=is_fork,
                status="drift",
                detail=(
                    f"profile={row.get('profile')!r} but API fork={is_fork!r}; "
                    "policy still applied as configured"
                ),
                remediation=f"fix [[hardening.repo]] profile for {full}",
            )
        )

    findings.extend(
        _observe_repo_units(full=full, policy=policy, repo_data=repo_data)
    )
    findings.extend(
        _observe_actions(full=full, policy=policy, run=runner, api_version=api)
    )
    findings.extend(
        _observe_ruleset(full=full, policy=policy, run=runner, api_version=api)
    )
    return findings


def _parse_expires_at(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def observe_interaction_limits(
    cfg: HardenConfig,
    *,
    runner: Runner,
    now: datetime | None = None,
) -> list[DriftFinding]:
    """Observe GET /user/interaction-limits. Never PUT / renew."""
    hard = cfg.hardening
    if not bool(hard.get("check_user_interaction_limits", True)):
        return [
            DriftFinding(
                target="user",
                setting="interaction_limits",
                wanted=None,
                found=None,
                status="deferred",
                detail="check_user_interaction_limits=false",
            )
        ]
    il = cfg.interaction_limits
    want_limit = il.get("limit", "collaborators_only")
    if _is_ignore(want_limit):
        return [
            DriftFinding(
                target="user",
                setting="interaction_limits",
                wanted=IGNORE,
                found=None,
                status="deferred",
                detail="interaction_limits.limit=ignore",
            )
        ]
    min_days = int(il.get("min_remaining_days", 14))
    raw_expiry = il.get("expiry")
    expiry_hint = (
        DEFAULT_INTERACTION_EXPIRY if raw_expiry is None else str(raw_expiry)
    )
    # load_config enum-validates expiry; defend in depth for callers that
    # construct HardenConfig without the loader.
    if expiry_hint not in INTERACTION_EXPIRIES:
        raise HardenError(
            f"interaction_limits.expiry invalid: {expiry_hint!r}"
        )
    rem = interaction_limits_remediation(expiry_hint)
    data, detail = _gh_json(
        runner,
        ["api", "user/interaction-limits"],
        api_version=cfg.api_version,
    )
    # GitHub returns 204 / empty when no limits are set — _gh_json maps that
    # to empty stdout. Treat empty / 404-ish as missing.
    if data is None:
        low = detail.lower()
        if "empty gh stdout" in low or "404" in low or "no content" in low:
            return [
                DriftFinding(
                    target="user",
                    setting="interaction_limits.limit",
                    wanted=want_limit,
                    found=None,
                    status="missing",
                    detail=detail,
                    remediation=rem,
                )
            ]
        return [
            DriftFinding(
                target="user",
                setting="interaction_limits",
                wanted=want_limit,
                found=None,
                status="unknown",
                detail=detail,
            )
        ]
    if not isinstance(data, dict):
        return [
            DriftFinding(
                target="user",
                setting="interaction_limits",
                wanted=want_limit,
                found=type(data).__name__,
                status="unknown",
                detail="unexpected interaction-limits payload",
            )
        ]
    findings: list[DriftFinding] = []
    found_limit = data.get("limit")
    findings.append(
        _cmp(
            target="user",
            setting="interaction_limits.limit",
            wanted=want_limit,
            found=found_limit,
            ok=found_limit == want_limit,
            remediation=rem,
        )
    )
    expires = _parse_expires_at(data.get("expires_at"))
    if expires is None:
        findings.append(
            DriftFinding(
                target="user",
                setting="interaction_limits.expires_at",
                wanted=f">= {min_days} days remaining",
                found=data.get("expires_at"),
                status="unknown",
                detail="unparseable or missing expires_at",
            )
        )
    else:
        clock = now or datetime.now(timezone.utc)
        remaining = (expires - clock).total_seconds() / 86400.0
        ok = remaining > float(min_days)
        findings.append(
            DriftFinding(
                target="user",
                setting="interaction_limits.expires_at",
                wanted=f"> {min_days} days remaining",
                found=f"{remaining:.1f} days ({expires.isoformat()})",
                status="ok" if ok else "drift",
                detail=(
                    "within min_remaining_days; renew is a separate authorized "
                    "operation (not harden-check)"
                    if not ok
                    else "expiry far enough"
                ),
                remediation=None if ok else rem,
            )
        )
    return findings


def _gh_login(runner: Runner, *, api_version: str) -> tuple[str | None, str]:
    """Authenticated GitHub login (for private-inclusive inventory paths)."""
    data, detail = _gh_json(
        runner,
        ["api", "user"],
        api_version=api_version,
    )
    if data is None:
        return None, detail
    if isinstance(data, dict):
        login = str(data.get("login") or "").strip()
        if login:
            return login, "ok"
        return None, "gh user: missing login"
    return None, "gh user: expected object"


def _inventory_repos_path(owner: str, login: str) -> str:
    """Authenticated inventory path (private repos included), matching pr-policy.

    Personal owner → ``/user/repos?affiliation=owner`` (not public-only
    ``/users/{owner}/repos``). Other owners → ``/orgs/{owner}/repos?type=all``.
    """
    if owner.lower() == login.lower():
        return "user/repos?affiliation=owner&per_page=100"
    quoted = urllib.parse.quote(owner, safe="")
    return f"orgs/{quoted}/repos?type=all&per_page=100"


def observe_inventory(
    cfg: HardenConfig,
    *,
    runner: Runner,
) -> list[DriftFinding]:
    """Name non-archived owner repos that lack an explicit [[hardening.repo]].

    Forks without a row are covered by [hardening.forks] (status ok/covered note).
    Non-forks without a row are uncovered (drift). Does not deep-probe unlisted
    repos in this unit. Uses authenticated user/org endpoints so private repos
    appear in the inventory (Argon E1.1 / pr-policy).
    """
    if not cfg.owners:
        return [
            DriftFinding(
                target="inventory",
                setting="owners",
                wanted=[],
                found=[],
                status="deferred",
                detail="hardening.owners empty; inventory skipped",
            )
        ]
    listed = {f"{r['owner']}/{r['name']}" for r in cfg.repos}
    findings: list[DriftFinding] = []
    login, login_detail = _gh_login(runner, api_version=cfg.api_version)
    if login is None:
        return [
            DriftFinding(
                target="inventory",
                setting="owners",
                wanted="authenticated login",
                found=None,
                status="unknown",
                detail=login_detail,
            )
        ]
    for owner in cfg.owners:
        path = _inventory_repos_path(owner, login)
        data, detail = _gh_json(
            runner,
            [
                "api",
                "--paginate",
                path,
                "--jq",
                ".[] | select(.archived|not) | {full_name,fork,name,owner:.owner.login}",
            ],
            api_version=cfg.api_version,
        )
        if data is None:
            findings.append(
                DriftFinding(
                    target=f"owner:{owner}",
                    setting="inventory",
                    wanted="readable repo list",
                    found=None,
                    status="unknown",
                    detail=detail,
                )
            )
            continue
        rows = data if isinstance(data, list) else [data]
        uncovered: list[str] = []
        fork_covered: list[str] = []
        owner_l = owner.lower()
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_owner = str(row.get("owner") or "").lower()
            if row_owner and row_owner != owner_l:
                continue
            full = str(row.get("full_name") or "")
            if not full or full in listed:
                continue
            # full_name owner segment must match too (defense in depth).
            if "/" in full and full.split("/", 1)[0].lower() != owner_l:
                continue
            if row.get("fork"):
                fork_covered.append(full)
            else:
                uncovered.append(full)
        if fork_covered:
            findings.append(
                DriftFinding(
                    target=f"owner:{owner}",
                    setting="inventory.forks",
                    wanted="[hardening.forks]",
                    found=sorted(fork_covered),
                    status="ok",
                    detail=(
                        f"{len(fork_covered)} unlisted fork(s) covered by "
                        "[hardening.forks] (deep probe deferred)"
                    ),
                )
            )
        if uncovered:
            findings.append(
                DriftFinding(
                    target=f"owner:{owner}",
                    setting="inventory.uncovered",
                    wanted="explicit [[hardening.repo]] or forks profile",
                    found=sorted(uncovered),
                    status="uncovered",
                    detail=f"{len(uncovered)} non-fork repo(s) lack [[hardening.repo]]",
                    remediation=(
                        "add [[hardening.repo]] rows (or archive); "
                        "just harden apply deferred"
                    ),
                )
            )
        else:
            findings.append(
                DriftFinding(
                    target=f"owner:{owner}",
                    setting="inventory.uncovered",
                    wanted=[],
                    found=[],
                    status="ok",
                    detail="no uncovered non-fork repos on first pages",
                )
            )
    return findings


def observe(
    cfg: HardenConfig,
    *,
    network: bool = True,
    runner: Runner | None = None,
    now: datetime | None = None,
    canary_runner: Callable[[list[str], str], "subprocess.CompletedProcess[str]"]
    | None = None,
    forgejo_api: Path | None = None,
) -> tuple[list[DriftFinding], int]:
    """Observe-only drift check. Exit 1 on drift/missing/uncovered; never writes."""
    findings: list[DriftFinding] = [
        DriftFinding(
            target="config",
            setting="hardening.toml",
            wanted="valid",
            found=str(cfg.path),
            status="ok",
            detail=f"{len(cfg.repos)} repo row(s); api_version={cfg.api_version}",
        )
    ]
    if not network:
        findings.append(
            DriftFinding(
                target="network",
                setting="probes",
                wanted=None,
                found=None,
                status="deferred",
                detail="network probes skipped (--local)",
            )
        )
        return findings, 0

    run = runner or _default_runner
    for row in cfg.repos:
        findings.extend(observe_repo(cfg, row, runner=run))
    findings.extend(observe_interaction_limits(cfg, runner=run, now=now))
    findings.extend(observe_inventory(cfg, runner=run))
    findings.extend(
        _coverage_findings(
            cfg,
            runner=run,
            now=now,
            canary_runner=canary_runner,
            forgejo_api=forgejo_api,
        )
    )

    bad = {f.status for f in findings} & {"drift", "missing", "uncovered", "error"}
    return findings, (1 if bad else 0)


def _default_canary_runner(
    argv: list[str], text: str
) -> "subprocess.CompletedProcess[str]":
    """Run the gate with the canary payload on stdin. Never logged."""
    return subprocess.run(
        argv, input=text, capture_output=True, text=True, check=False
    )


def _coverage_findings(
    cfg: HardenConfig,
    *,
    runner: Runner,
    now: datetime | None,
    canary_runner: Callable[[list[str], str], "subprocess.CompletedProcess[str]"]
    | None = None,
    forgejo_api: Path | None = None,
) -> list[DriftFinding]:
    """S6 coverage: Forgejo read-back, the renewal decision, the gate canary.

    Imported lazily so the observe-only core does not depend on the coverage
    module at import time. Read-only: the renewal is reported, never
    performed, and the canary runs only when a corpus path is configured.
    A missing corpus is ``deferred``, not a pass.
    """
    import ade_harden_coverage as cov

    findings: list[DriftFinding] = []
    forgejo = cfg.hardening.get("forgejo")
    if isinstance(forgejo, dict) and forgejo.get("base_url"):
        base = str(forgejo["base_url"])
        for row in cfg.repos:
            findings.extend(
                cov.observe_forgejo_repo(
                    cfg, row, runner=runner, base_url=base, api=forgejo_api
                )
            )
        if not cfg.repos:
            findings.append(
                DriftFinding(
                    target="forgejo",
                    setting="forgejo",
                    wanted="repos",
                    found=[],
                    status="ok",
                    detail="forgejo configured; no [[hardening.repo]] rows",
                )
            )
    else:
        findings.append(
            DriftFinding(
                target="forgejo",
                setting="forgejo",
                wanted=None,
                found=None,
                status="deferred",
                detail="Forgejo not configured (hardening.forgejo.base_url unset)",
            )
        )

    il = cfg.interaction_limits
    current, _detail = _gh_json(
        runner, ["api", "user/interaction-limits"], api_version=cfg.api_version
    )
    plan = cov.renewal_plan(
        current if isinstance(current, dict) else None,
        want_limit=str(il.get("limit", "collaborators_only")),
        want_expiry=str(il.get("expiry", DEFAULT_INTERACTION_EXPIRY)),
        min_days=int(il.get("min_remaining_days", 14)),
        now=now or datetime.now(timezone.utc),
    )
    # Due renewal is drift so the scheduled check's notification fires; the
    # write itself is `ade-harden renew --apply`, never observe.
    findings.append(
        DriftFinding(
            target="user",
            setting="interaction_limits.renewal",
            wanted="renew only inside the window, via ade-harden renew",
            found=plan["reason"],
            status="drift" if plan["renew"] else "ok",
            detail="observe never renews",
            remediation=None
            if not plan["renew"]
            else interaction_limits_remediation(
                str(il.get("expiry", DEFAULT_INTERACTION_EXPIRY))
            ),
        )
    )

    canaries = cfg.hardening.get("canaries")
    corpus = canaries.get("corpus") if isinstance(canaries, dict) else None
    if not corpus:
        findings.append(
            DriftFinding(
                target="s5a",
                setting="injection_gate",
                wanted="benign + injection canary",
                found=None,
                status="deferred",
                detail="no canary corpus configured (hardening.canaries.corpus)",
            )
        )
        return findings
    path = Path(str(corpus))
    if not path.is_file():
        findings.append(
            DriftFinding(
                target="s5a",
                setting="injection_gate",
                wanted="readable canary corpus",
                found=str(path),
                status="error",
                detail="configured canary corpus is not a file",
            )
        )
        return findings

    run_canary = canary_runner or _default_canary_runner

    def classify(text: str, surface: str) -> dict[str, Any]:
        proc = run_canary(
            [
                sys.executable,
                "-I",
                str(BIN / "ade-injection-gate"),
                "classify",
                "--surface",
                surface,
            ],
            text,
        )
        raw = (proc.stdout or "").strip()
        try:
            data = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            data = None
        if not isinstance(data, dict):
            return {"status": "unavailable", "decide": "escalate"}
        return data

    try:
        findings.extend(cov.gate_canary(path, classify=classify))
    except (HardenError, json.JSONDecodeError, OSError, UnicodeError, ValueError) as e:
        findings.append(
            DriftFinding(
                target="s5a",
                setting="injection_gate",
                wanted="valid canary corpus",
                found=None,
                status="error",
                detail=str(e),
            )
        )
    return findings


def apply_refused() -> HardenError:
    return HardenError(
        "ade-harden apply / reapply is refused in this unit "
        "(observe-only harden-check; no live ruleset writes, no interaction-limit "
        "auto-renew). Re-run: ade-harden observe  or  just harden-check."
    )


_MUTATE_SUBCOMMANDS = frozenset(
    {"apply", "reapply", "renew", "fix", "set", "write", "harden"}
)


def refuse_mutate_argv(argv: list[str] | None) -> None:
    """Refuse mutation subcommands and obvious write flags in this unit."""
    raw = list(argv or [])
    for tok in raw:
        if tok in _MUTATE_SUBCOMMANDS:
            raise apply_refused()
        if tok in {"--yes", "--write", "--reapply", "--renew"}:
            raise apply_refused()
        if re.match(r"(?i)^--(yes|write|reapply|renew)(=|$)", tok):
            raise apply_refused()
