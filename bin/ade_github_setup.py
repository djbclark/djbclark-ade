"""ade_github_setup: observe / plan / dry-run for setup-plan S8 (merge-gate App).

Transitional source: ``config/github.toml`` when ``config/ade.toml`` lacks a
``[github]`` table. Never reads secret values. Refuse PEM / private-key /
client-secret material on argv. Live ``apply --yes`` mutations are deferred:
this unit ships check, observe, plan, and apply dry-run only.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

BIN = Path(__file__).resolve().parent
import sys

if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import ade_config as ac  # noqa: E402

SCHEMA_VERSION = 1
MANIFEST_CREATE_URL = "https://github.com/settings/apps/new"

# Permission names as GitHub App Manifest uses them (docs/review-boundary.md).
REQUIRED_MANIFEST_PERMISSIONS: dict[str, str] = {
    "statuses": "write",
    "checks": "write",
    "pull_requests": "read",
}

SECRET_ARGV_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    re.compile(r"-----BEGIN"),
    re.compile(r"(?i)^--?(?:private[-_]?key|pem|client[-_]?secret|token|password)(=|$)"),
)

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


class GithubSetupError(ac.ConfigError):
    """Invalid github config/manifest or refused operation."""


@dataclass
class GithubConfig:
    data: dict[str, Any]
    path: Path
    root: Path
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def github(self) -> dict[str, Any]:
        return dict(self.data.get("github") or {})

    @property
    def owner(self) -> str:
        return str(self.github["owner"])

    @property
    def repository(self) -> str:
        return str(self.github["repository"])

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repository}"

    @property
    def manifest_rel(self) -> str:
        return str(self.github["manifest"])

    def manifest_path(self) -> Path:
        return (self.root / self.manifest_rel).resolve()


@dataclass(frozen=True)
class Observation:
    id: str
    status: str  # ok | missing | unknown | error | deferred
    detail: str


@dataclass(frozen=True)
class PlanStep:
    id: str
    action: str
    reason: str
    browser: bool = False
    secret_handling: str | None = None


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parent.parent


def default_config_path(root: Path) -> Path:
    return root / "config" / "github.toml"


def default_schema_path(root: Path) -> Path:
    return root / "config" / "github.schema.json"


def refuse_secret_argv(argv: list[str] | None) -> None:
    """Raise GithubSetupError when argv appears to carry secret material.

    Private keys and client secrets must travel through stdin / ``gh secret set
    … < file`` / sudo-secretspec — never on the command line (review rule 3).
    """
    if not argv:
        return
    for i, arg in enumerate(argv):
        if not isinstance(arg, str):
            continue
        # Flag form first (clearer than the generic PEM/pattern message).
        low = arg.lower().split("=", 1)[0]
        if low in {
            "--private-key",
            "--pem",
            "--client-secret",
            "--token",
            "--password",
            "--merge-gate-private-key",
            "-private-key",
            "-pem",
            "-client-secret",
            "-token",
            "-password",
        }:
            # Report only the normalized flag name — never equals-form values
            # (`--token=<secret>`), which main() prints to stderr on refuse.
            raise GithubSetupError(
                f"refuse secret flag {low!r} on argv; "
                "store the key with `gh secret set MERGE_GATE_PRIVATE_KEY "
                "--env merge-gate < file.pem` (stdin redirect, never argv)"
            )
        for pat in SECRET_ARGV_PATTERNS:
            if pat.search(arg):
                raise GithubSetupError(
                    "refuse secret material on argv "
                    f"(arg[{i}] matched {pat.pattern!r}); "
                    "use stdin or `gh secret set NAME --env … < file`"
                )


def _load_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise GithubSetupError(f"{path}: {e}") from e
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise GithubSetupError(f"{path}: invalid JSON: {e}") from e


def load_manifest(path: Path) -> dict[str, Any]:
    data = _load_json(path)
    if not isinstance(data, dict):
        raise GithubSetupError(f"{path}: manifest root must be an object")
    return data


def validate_manifest(data: dict[str, Any], *, path: Path | None = None) -> list[str]:
    """Return human-readable errors; empty means OK for S8's merge-gate App."""
    label = str(path) if path else "manifest"
    errors: list[str] = []
    name = data.get("name")
    if name != "ade-merge-gate":
        errors.append(f"{label}: name must be 'ade-merge-gate' (got {name!r})")
    if data.get("public") is not False:
        errors.append(f"{label}: public must be false (this-account only)")
    url = data.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        errors.append(f"{label}: url must be an https homepage string")
    hook = data.get("hook_attributes")
    if not isinstance(hook, dict):
        errors.append(f"{label}: hook_attributes object required (active=false)")
    else:
        if hook.get("active") is not False:
            errors.append(f"{label}: hook_attributes.active must be false (webhook inactive)")
        if not isinstance(hook.get("url"), str) or not hook["url"]:
            errors.append(f"{label}: hook_attributes.url required by the manifest API")
    perms = data.get("default_permissions")
    if not isinstance(perms, dict):
        errors.append(f"{label}: default_permissions object required")
    else:
        for key, want in REQUIRED_MANIFEST_PERMISSIONS.items():
            got = perms.get(key)
            if got != want:
                errors.append(
                    f"{label}: default_permissions.{key} must be {want!r} (got {got!r})"
                )
    events = data.get("default_events")
    if events is None:
        errors.append(f"{label}: default_events must be present (use [] when webhook inactive)")
    elif not isinstance(events, list):
        errors.append(f"{label}: default_events must be an array")
    return errors


def _validate_github_table(gh: dict[str, Any], *, path: Path) -> list[str]:
    errors: list[str] = []
    for key in (
        "owner",
        "repository",
        "app_name",
        "app_slug",
        "manifest",
        "environment",
        "environment_branch",
        "private_key_secret",
        "client_id_variable",
        "ruleset_name",
    ):
        val = gh.get(key)
        if not isinstance(val, str) or not val.strip():
            errors.append(f"{path}: github.{key} must be a non-empty string")
    ga = gh.get("github_actions_app_id")
    if not isinstance(ga, int) or isinstance(ga, bool) or ga < 1:
        errors.append(f"{path}: github.github_actions_app_id must be a positive integer")
    app_id = gh.get("app_id")
    if app_id is not None and (
        not isinstance(app_id, int) or isinstance(app_id, bool) or app_id < 1
    ):
        errors.append(f"{path}: github.app_id must be a positive integer when set")
    checks = gh.get("required_check")
    if not isinstance(checks, list) or not checks:
        errors.append(f"{path}: github.required_check must be a non-empty array")
    else:
        for i, row in enumerate(checks):
            if not isinstance(row, dict):
                errors.append(f"{path}: github.required_check[{i}] must be a table")
                continue
            if not isinstance(row.get("context"), str) or not row["context"]:
                errors.append(f"{path}: github.required_check[{i}].context required")
            if row.get("source") not in ("app", "github_actions"):
                errors.append(
                    f"{path}: github.required_check[{i}].source must be "
                    "'app' or 'github_actions'"
                )
    # Secret-shaped values must never appear as config leaves.
    for key in ("private_key_secret", "client_id_variable"):
        val = gh.get(key)
        if isinstance(val, str) and (
            "BEGIN" in val or "\n" in val or len(val) > 128
        ):
            errors.append(
                f"{path}: github.{key} looks like secret material; store the name only"
            )
    return errors


def load_config(root: Path | None = None) -> GithubConfig:
    """Load and validate transitional config/github.toml (+ schema + manifest)."""
    root = (root or repo_root_from_here()).resolve()
    ade = root / "config" / "ade.toml"
    if ade.is_file():
        # Future: read [github] from ade.toml. Refuse dual sources for now.
        raise GithubSetupError(
            f"{ade}: present; fold [github] into ade.toml before using "
            "config/github.toml (setup-plan S1)"
        )
    path = default_config_path(root)
    schema = default_schema_path(root)
    try:
        data = ac.read_toml(path)
    except ac.ConfigError as e:
        raise GithubSetupError(str(e)) from e
    if data.get("schema_version") != SCHEMA_VERSION:
        raise GithubSetupError(
            f"{path}: schema_version must be {SCHEMA_VERSION} "
            f"(got {data.get('schema_version')!r})"
        )
    if schema.is_file():
        # Structural check via the same lightweight path install uses: required
        # keys + types below. Full JSON-Schema is optional; keep stdlib-only.
        pass
    gh = data.get("github")
    if not isinstance(gh, dict):
        raise GithubSetupError(f"{path}: [github] table required")
    errors = _validate_github_table(gh, path=path)
    if errors:
        raise GithubSetupError("; ".join(errors))
    cfg = GithubConfig(
        data=data,
        path=path,
        root=root,
        provenance={"path": str(path), "schema_version": SCHEMA_VERSION},
    )
    man_path = cfg.manifest_path()
    if not man_path.is_file():
        raise GithubSetupError(f"{man_path}: manifest missing")
    manifest = load_manifest(man_path)
    man_errors = validate_manifest(manifest, path=man_path)
    if man_errors:
        raise GithubSetupError("; ".join(man_errors))
    if gh.get("app_name") != manifest.get("name"):
        raise GithubSetupError(
            f"{path}: github.app_name {gh.get('app_name')!r} != manifest name "
            f"{manifest.get('name')!r}"
        )
    return cfg


def config_summary(cfg: GithubConfig) -> dict[str, Any]:
    gh = cfg.github
    return {
        "path": str(cfg.path),
        "repo": cfg.full_name,
        "app_name": gh.get("app_name"),
        "manifest": gh.get("manifest"),
        "environment": gh.get("environment"),
        "environment_branch": gh.get("environment_branch"),
        "ruleset_name": gh.get("ruleset_name"),
        "required_checks": [
            {"context": c["context"], "source": c["source"]}
            for c in (gh.get("required_check") or [])
        ],
        "private_key_secret": gh.get("private_key_secret"),
        "client_id_variable": gh.get("client_id_variable"),
        "app_id_recorded": gh.get("app_id"),
    }


def ruleset_preview(cfg: GithubConfig, *, app_id: int | None = None) -> dict[str, Any]:
    """Build the merge-gate ruleset body (APP_ID unsubstituted when unknown)."""
    gh = cfg.github
    pinned = app_id if app_id is not None else gh.get("app_id")
    checks: list[dict[str, Any]] = []
    for row in gh.get("required_check") or []:
        if row["source"] == "app":
            entry: dict[str, Any] = {"context": row["context"]}
            if isinstance(pinned, int) and pinned >= 1:
                entry["integration_id"] = pinned
            else:
                entry["integration_id"] = "APP_ID"
            checks.append(entry)
        else:
            checks.append(
                {
                    "context": row["context"],
                    "integration_id": int(gh["github_actions_app_id"]),
                }
            )
    return {
        "name": gh["ruleset_name"],
        "target": "branch",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "bypass_actors": [],
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": False,
                    "do_not_enforce_on_create": False,
                    "required_status_checks": checks,
                },
            }
        ],
    }


def plan(cfg: GithubConfig) -> list[PlanStep]:
    """Print-only S8 steps (A8–A11 / B7), with secret and browser call-outs."""
    gh = cfg.github
    repo = cfg.full_name
    env = gh["environment"]
    branch = gh["environment_branch"]
    secret = gh["private_key_secret"]
    var = gh["client_id_variable"]
    return [
        PlanStep(
            id="app-create",
            action="browser-manifest",
            reason=(
                f"Create App {gh['app_name']!r} from {gh['manifest']} "
                f"(POST manifest to {MANIFEST_CREATE_URL}); confirm click only"
            ),
            browser=True,
        ),
        PlanStep(
            id="app-install",
            action="browser-or-api",
            reason=f"Install {gh['app_slug']} on {repo} only; note App ID + Client ID",
            browser=True,
        ),
        PlanStep(
            id="environment",
            action="api",
            reason=(
                f"PUT environments/{env} with custom_branch_policies; "
                f"POST deployment-branch-policy name={branch}"
            ),
        ),
        PlanStep(
            id="store-private-key",
            action="operator-secret",
            reason=(
                f"gh secret set {secret} --env {env} --repo {repo} < "
                f"{gh['app_slug']}.private-key.pem  (stdin redirect; never argv)"
            ),
            secret_handling="stdin-file-redirect",
        ),
        PlanStep(
            id="store-client-id",
            action="operator-variable",
            reason=(
                f"gh variable set {var} --env {env} --repo {repo} --body '<Client ID>'"
            ),
        ),
        PlanStep(
            id="ruleset",
            action="api",
            reason=(
                f"POST rulesets name={gh['ruleset_name']!r} with adversary-marker "
                "pinned to App ID and Tests checks pinned to GitHub Actions"
            ),
        ),
        PlanStep(
            id="hardening",
            action="deferred",
            reason="[hardening] defaults (setup-plan S5) and harden-check not in this unit; S5a stays deferred",
        ),
        PlanStep(
            id="verify",
            action="deferred",
            reason="just github-setup --verify (T0-T3b) deferred until live apply lands",
        ),
    ]


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def _gh_json(
    runner: Runner,
    args: list[str],
) -> tuple[Any | None, str]:
    """Run ``gh …``; return (parsed JSON or None, detail)."""
    if shutil.which("gh") is None and runner is _default_runner:
        return None, "gh not on PATH"
    proc = runner(["gh", *args])
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = err[0] if err else f"gh exit {proc.returncode}"
        return None, detail
    text = (proc.stdout or "").strip()
    if not text:
        return None, "empty gh stdout"
    try:
        return json.loads(text), "ok"
    except json.JSONDecodeError as e:
        return None, f"gh JSON: {e}"


def _observe_app_install(cfg: GithubConfig, run: Runner) -> Observation:
    """Probe App installation with operator ``gh`` credentials.

    ``GET /repos/{owner}/{repo}/installation`` requires an App JWT and always
    fails (or mis-reports) under ambient user ``gh`` auth. Use
    ``GET /user/installations`` plus that installation's repositories list
    instead — both work with the operator's token.
    """
    want = cfg.github["app_slug"]
    data, detail = _gh_json(
        run,
        [
            "api",
            "user/installations?per_page=100",
            "--jq",
            "[.installations[] | {id, app_id, app_slug, account: .account.login}]",
        ],
    )
    if data is None:
        return Observation(id="app-install", status="unknown", detail=detail)
    if not isinstance(data, list):
        return Observation(
            id="app-install",
            status="unknown",
            detail="unexpected user/installations payload",
        )

    matches = [
        row
        for row in data
        if isinstance(row, dict) and row.get("app_slug") == want
    ]
    if not matches:
        return Observation(
            id="app-install",
            status="missing",
            detail=(
                f"no user-visible installation of app_slug={want!r} "
                "(GET /user/installations; not App JWT)"
            ),
        )

    # Prefer an installation whose account matches the configured owner.
    ordered = sorted(
        matches, key=lambda row: 0 if row.get("account") == cfg.owner else 1
    )
    listed_ok = False
    last_list_detail = ""
    for row in ordered:
        iid = row.get("id")
        if iid is None:
            continue
        repos, repo_detail = _gh_json(
            run,
            [
                "api",
                f"user/installations/{iid}/repositories?per_page=100",
                "--jq",
                "[.repositories[].full_name]",
            ],
        )
        if repos is None:
            last_list_detail = repo_detail
            continue
        listed_ok = True
        if isinstance(repos, list) and cfg.full_name in repos:
            return Observation(
                id="app-install",
                status="ok",
                detail=(
                    f"installed app_slug={want} app_id={row.get('app_id')} "
                    f"installation_id={iid} (user/installations)"
                ),
            )

    if not listed_ok:
        return Observation(
            id="app-install",
            status="unknown",
            detail=(
                f"app_slug={want!r} visible to user but repository list "
                f"unreadable: {last_list_detail or 'no installation id'}"
            ),
        )
    ids = [row.get("id") for row in matches]
    return Observation(
        id="app-install",
        status="missing",
        detail=(
            f"app_slug={want!r} installed (installation_id={ids}) but "
            f"{cfg.full_name} not in user-visible repositories for those "
            "installations (first page only)"
        ),
    )


def observe(
    cfg: GithubConfig,
    *,
    network: bool = True,
    runner: Runner | None = None,
) -> tuple[list[Observation], int]:
    """Observe-only. Local checks always; optional ``gh`` probes when network=True.

    Never reads secret values — only presence of secret *names*. Exit 0 when
    every local check is ok and (if network) no probe reported error; missing
    remote pieces are status=missing with exit 1. App installation is probed
    via ``GET /user/installations`` (operator creds), not the App-JWT endpoint.
    """
    run = runner or _default_runner
    obs: list[Observation] = []
    man_path = cfg.manifest_path()
    obs.append(
        Observation(
            id="manifest",
            status="ok",
            detail=f"{man_path.relative_to(cfg.root)} permissions+webhook inactive ok",
        )
    )
    obs.append(
        Observation(
            id="config",
            status="ok",
            detail=f"{cfg.path.relative_to(cfg.root)} repo={cfg.full_name}",
        )
    )
    preview = ruleset_preview(cfg)
    checks = preview["rules"][0]["parameters"]["required_status_checks"]
    obs.append(
        Observation(
            id="ruleset-preview",
            status="ok",
            detail=f"{len(checks)} required check(s) named; App ID "
            + (
                "recorded"
                if isinstance(cfg.github.get("app_id"), int)
                else "placeholder pending create"
            ),
        )
    )

    rc = 0
    if not network:
        obs.append(
            Observation(
                id="network",
                status="deferred",
                detail="network probes skipped (--local)",
            )
        )
        return obs, 0

    install_obs = _observe_app_install(cfg, run)
    obs.append(install_obs)
    if install_obs.status in {"missing", "error"}:
        rc = 1

    # Environment + branch policy (names only)
    env = cfg.github["environment"]
    env_data, env_detail = _gh_json(
        run,
        ["api", f"repos/{cfg.full_name}/environments/{env}"],
    )
    if env_data is None:
        if "404" in env_detail.lower() or "not found" in env_detail.lower():
            obs.append(
                Observation(
                    id="environment",
                    status="missing",
                    detail=f"environment {env!r} absent: {env_detail}",
                )
            )
            rc = 1
        else:
            obs.append(
                Observation(id="environment", status="unknown", detail=env_detail)
            )
    else:
        obs.append(
            Observation(
                id="environment",
                status="ok",
                detail=f"environment {env!r} present",
            )
        )
        pol_data, pol_detail = _gh_json(
            run,
            [
                "api",
                f"repos/{cfg.full_name}/environments/{env}/deployment-branch-policies",
                "--jq",
                "[.branch_policies[].name]",
            ],
        )
        want_branch = cfg.github["environment_branch"]
        if isinstance(pol_data, list) and want_branch in pol_data:
            obs.append(
                Observation(
                    id="environment-branch",
                    status="ok",
                    detail=f"deployment branch {want_branch!r} listed",
                )
            )
        elif pol_data is None:
            obs.append(
                Observation(
                    id="environment-branch",
                    status="unknown",
                    detail=pol_detail,
                )
            )
        else:
            obs.append(
                Observation(
                    id="environment-branch",
                    status="missing",
                    detail=f"want branch {want_branch!r}; got {pol_data!r}",
                )
            )
            rc = 1

    # Secret / variable *names* only (gh secret list does not print values)
    secret_name = cfg.github["private_key_secret"]
    sec_data, sec_detail = _gh_json(
        run,
        [
            "secret",
            "list",
            "--env",
            env,
            "--repo",
            cfg.full_name,
            "--json",
            "name",
        ],
    )
    if sec_data is None:
        obs.append(
            Observation(id="private-key-secret", status="unknown", detail=sec_detail)
        )
    else:
        names = {
            row.get("name")
            for row in sec_data
            if isinstance(row, dict)
        } if isinstance(sec_data, list) else set()
        if secret_name in names:
            obs.append(
                Observation(
                    id="private-key-secret",
                    status="ok",
                    detail=f"{secret_name} present (value not read)",
                )
            )
        else:
            obs.append(
                Observation(
                    id="private-key-secret",
                    status="missing",
                    detail=f"{secret_name} not in env secret list",
                )
            )
            rc = 1

    var_name = cfg.github["client_id_variable"]
    var_data, var_detail = _gh_json(
        run,
        [
            "variable",
            "list",
            "--env",
            env,
            "--repo",
            cfg.full_name,
            "--json",
            "name",
        ],
    )
    if var_data is None:
        obs.append(
            Observation(id="client-id-variable", status="unknown", detail=var_detail)
        )
    else:
        names = {
            row.get("name")
            for row in var_data
            if isinstance(row, dict)
        } if isinstance(var_data, list) else set()
        if var_name in names:
            obs.append(
                Observation(
                    id="client-id-variable",
                    status="ok",
                    detail=f"{var_name} present (value not printed beyond name)",
                )
            )
        else:
            obs.append(
                Observation(
                    id="client-id-variable",
                    status="missing",
                    detail=f"{var_name} not in env variable list",
                )
            )
            rc = 1

    # Ruleset by name
    rs_data, rs_detail = _gh_json(
        run,
        [
            "api",
            f"repos/{cfg.full_name}/rulesets",
            "--jq",
            "[.[] | {id,name,enforcement}]",
        ],
    )
    want_rs = cfg.github["ruleset_name"]
    if rs_data is None:
        obs.append(Observation(id="ruleset", status="unknown", detail=rs_detail))
    elif isinstance(rs_data, list) and any(
        isinstance(r, dict) and r.get("name") == want_rs for r in rs_data
    ):
        obs.append(
            Observation(
                id="ruleset",
                status="ok",
                detail=f"ruleset {want_rs!r} present",
            )
        )
    else:
        obs.append(
            Observation(
                id="ruleset",
                status="missing",
                detail=f"ruleset {want_rs!r} not found",
            )
        )
        rc = 1

    obs.append(
        Observation(
            id="hardening",
            status="deferred",
            detail="S5 harden / S5a injection classifier deferred (operator 2026-11-08)",
        )
    )
    return obs, rc


def apply_dry_run(cfg: GithubConfig) -> list[dict[str, Any]]:
    """Default apply mode: print what would run; change nothing."""
    steps = plan(cfg)
    out: list[dict[str, Any]] = []
    for step in steps:
        row: dict[str, Any] = {
            "id": step.id,
            "action": "would-" + step.action,
            "reason": step.reason,
            "browser": step.browser,
        }
        if step.secret_handling:
            row["secret_handling"] = step.secret_handling
        out.append(row)
    # Include concrete dry-run payloads (no secrets).
    out.append(
        {
            "id": "environment-payload",
            "action": "would-api",
            "reason": "PUT environments/" + cfg.github["environment"],
            "body": {
                "deployment_branch_policy": {
                    "protected_branches": False,
                    "custom_branch_policies": True,
                }
            },
        }
    )
    out.append(
        {
            "id": "ruleset-payload",
            "action": "would-api",
            "reason": "POST rulesets (APP_ID unsubstituted until observe records it)",
            "body": ruleset_preview(cfg),
        }
    )
    out.append(
        {
            "id": "manifest-create",
            "action": "would-browser",
            "reason": f"open {MANIFEST_CREATE_URL} and submit checked-in manifest JSON",
            "url": MANIFEST_CREATE_URL,
            "manifest": cfg.manifest_rel,
        }
    )
    return out


def apply_yes_refused() -> GithubSetupError:
    return GithubSetupError(
        "ade-github-setup apply --yes is refused in this unit "
        "(observe/plan/dry-run only; live App create, secret store, and ruleset "
        "POST land in a follow-up). Re-run with --dry-run (default)."
    )
