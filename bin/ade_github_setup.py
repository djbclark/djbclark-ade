"""ade_github_setup: observe / plan / apply / verify for setup-plan S8.

Transitional source: ``config/github.toml`` when ``config/ade.toml`` lacks a
``[github]`` table. Never reads secret values. Refuse PEM / private-key /
client-secret material on argv. ``apply --yes`` mutates environment and
ruleset via the GitHub API only; browser App confirm stays S7 (refused here).
``apply --verify`` is API-only read-back (no throwaway PRs / T0–T3b).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
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
            action="api",
            reason=(
                "ade-github-setup apply --verify: API-only read-back of "
                "manifest + environment + ruleset (T0-T3b throwaway PRs stay "
                "operator / later)"
            ),
        ),
    ]


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def _gh_json(
    runner: Runner,
    args: list[str],
    *,
    input_path: Path | None = None,
) -> tuple[Any | None, str]:
    """Run ``gh …``; return (parsed JSON or None, detail).

    When ``input_path`` is set, append ``--input <path>`` (JSON body on disk;
    never PEM — payloads here are environment / ruleset only).
    """
    if shutil.which("gh") is None and runner is _default_runner:
        return None, "gh not on PATH"
    argv = ["gh", *args]
    if input_path is not None:
        argv.extend(["--input", str(input_path)])
    proc = runner(argv)
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


def _gh_json_body(
    runner: Runner,
    args: list[str],
    body: dict[str, Any],
) -> tuple[Any | None, str]:
    """POST/PUT JSON via a temp ``--input`` file (no secrets in these bodies)."""
    with tempfile.TemporaryDirectory(prefix="ade-github-setup-") as td:
        path = Path(td) / "body.json"
        path.write_text(json.dumps(body), encoding="utf-8")
        return _gh_json(runner, args, input_path=path)


def environment_payload(cfg: GithubConfig) -> dict[str, Any]:
    return {
        "deployment_branch_policy": {
            "protected_branches": False,
            "custom_branch_policies": True,
        }
    }


def _discover_app_id(cfg: GithubConfig, run: Runner) -> int | None:
    """Return App ID from config or ``GET /user/installations`` (operator gh)."""
    recorded = cfg.github.get("app_id")
    if isinstance(recorded, int) and recorded >= 1:
        return recorded
    data, _detail = _gh_json(
        run,
        [
            "api",
            "user/installations?per_page=100",
            "--jq",
            "[.installations[] | {app_id, app_slug}]",
        ],
    )
    if not isinstance(data, list):
        return None
    want = cfg.github["app_slug"]
    for row in data:
        if isinstance(row, dict) and row.get("app_slug") == want:
            aid = row.get("app_id")
            if isinstance(aid, int) and aid >= 1:
                return aid
    return None


def _list_rulesets(
    cfg: GithubConfig, run: Runner
) -> tuple[list[dict[str, Any]] | None, str]:
    data, detail = _gh_json(
        run,
        [
            "api",
            f"repos/{cfg.full_name}/rulesets",
            "--jq",
            "[.[] | {id,name,enforcement}]",
        ],
    )
    if data is None:
        return None, detail
    if not isinstance(data, list):
        return None, "unexpected rulesets payload"
    return [r for r in data if isinstance(r, dict)], "ok"


def _get_ruleset(
    cfg: GithubConfig, run: Runner, ruleset_id: int
) -> tuple[dict[str, Any] | None, str]:
    data, detail = _gh_json(
        run,
        ["api", f"repos/{cfg.full_name}/rulesets/{ruleset_id}"],
    )
    if data is None:
        return None, detail
    if not isinstance(data, dict):
        return None, "unexpected ruleset payload"
    return data, "ok"


def _ruleset_required_checks(ruleset: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for rule in ruleset.get("rules") or []:
        if not isinstance(rule, dict) or rule.get("type") != "required_status_checks":
            continue
        params = rule.get("parameters") or {}
        if not isinstance(params, dict):
            continue
        for row in params.get("required_status_checks") or []:
            if isinstance(row, dict) and isinstance(row.get("context"), str):
                out.append(row)
    return out


def _checks_match_want(
    got: list[dict[str, Any]], want: list[dict[str, Any]]
) -> tuple[bool, str]:
    """Compare required-check lists by context + integration_id (order-free)."""
    def key(row: dict[str, Any]) -> tuple[str, Any]:
        return (str(row.get("context")), row.get("integration_id"))

    got_set = {key(r) for r in got}
    want_set = {key(r) for r in want}
    if got_set == want_set:
        return True, "required_status_checks match"
    missing = sorted(want_set - got_set)
    extra = sorted(got_set - want_set)
    parts: list[str] = []
    if missing:
        parts.append(f"missing={missing!r}")
    if extra:
        parts.append(f"extra={extra!r}")
    return False, "; ".join(parts) or "mismatch"


def _deployment_policy_matches(
    env_obj: Any, want_body: dict[str, Any]
) -> tuple[bool, str]:
    """Compare ``deployment_branch_policy`` fields we PUT on the environment."""
    want_pol = want_body.get("deployment_branch_policy") or {}
    if not isinstance(env_obj, dict):
        return False, f"no environment object; want policy={want_pol!r}"
    got_pol = env_obj.get("deployment_branch_policy")
    if not isinstance(got_pol, dict):
        return False, f"missing deployment_branch_policy; want={want_pol!r}"
    for key in ("protected_branches", "custom_branch_policies"):
        if key not in want_pol:
            continue
        if got_pol.get(key) != want_pol[key]:
            return False, (
                f"deployment_branch_policy.{key}: "
                f"want={want_pol[key]!r} got={got_pol.get(key)!r}"
            )
    return True, "deployment_branch_policy matches"


# jq: id + name + type so apply/verify can refuse leftover policies.
_BRANCH_POLICIES_JQ = "[.branch_policies[] | {id, name, type}]"


def _normalize_branch_policies(raw: Any) -> list[dict[str, Any]] | None:
    """Normalize deployment-branch-policies list; ``None`` if unreadable."""
    if not isinstance(raw, list):
        return None
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            # Legacy name-only fixtures / jq; treat as type=branch, no id.
            out.append({"id": None, "name": item, "type": "branch"})
            continue
        if not isinstance(item, dict):
            return None
        name = item.get("name")
        if not isinstance(name, str) or not name:
            return None
        typ = item.get("type")
        if typ is None:
            typ = "branch"
        if typ not in ("branch", "tag"):
            return None
        out.append({"id": item.get("id"), "name": name, "type": typ})
    return out


def _branch_policies_exact(
    policies: list[dict[str, Any]], want_branch: str
) -> tuple[bool, str]:
    """True only when the list is exactly ``want_branch`` with type=branch."""
    got = sorted((p["name"], p["type"]) for p in policies)
    want = [(want_branch, "branch")]
    if got == want:
        return True, f"deployment branch {want_branch!r} only"
    return False, f"want exactly {[want_branch]!r} type=branch; got {got!r}"


def _list_deployment_branch_policies(
    cfg: GithubConfig, run: Runner, env: str
) -> tuple[list[dict[str, Any]] | None, str]:
    raw, detail = _gh_json(
        run,
        [
            "api",
            f"repos/{cfg.full_name}/environments/{env}/deployment-branch-policies",
            "--jq",
            _BRANCH_POLICIES_JQ,
        ],
    )
    if raw is None:
        return None, detail
    norms = _normalize_branch_policies(raw)
    if norms is None:
        return None, f"unreadable deployment-branch-policies: {raw!r}"
    return norms, detail


def _ruleset_scope_matches(
    got: dict[str, Any], want: dict[str, Any]
) -> tuple[bool, str]:
    """Compare ruleset target, ref conditions, and bypass actors (order-free)."""
    parts: list[str] = []
    if got.get("target") != want.get("target"):
        parts.append(
            f"target want={want.get('target')!r} got={got.get('target')!r}"
        )

    def ref_name_sets(conditions: Any) -> tuple[frozenset[Any], frozenset[Any]] | None:
        if not isinstance(conditions, dict):
            return None
        rn = conditions.get("ref_name")
        if not isinstance(rn, dict):
            return None
        include = rn.get("include") or []
        exclude = rn.get("exclude") or []
        if not isinstance(include, list) or not isinstance(exclude, list):
            return None
        return frozenset(include), frozenset(exclude)

    want_refs = ref_name_sets(want.get("conditions"))
    got_refs = ref_name_sets(got.get("conditions"))
    if want_refs != got_refs:
        parts.append(
            f"conditions.ref_name want={want_refs!r} got={got_refs!r}"
        )

    def bypass_keys(actors: Any) -> frozenset[tuple[Any, ...]] | None:
        if not isinstance(actors, list):
            return None
        keys: list[tuple[Any, ...]] = []
        for actor in actors:
            if isinstance(actor, dict):
                keys.append(
                    (
                        actor.get("actor_id"),
                        actor.get("actor_type"),
                        actor.get("bypass_mode"),
                    )
                )
            else:
                keys.append((actor,))
        return frozenset(keys)

    want_bypass = bypass_keys(want.get("bypass_actors") or [])
    got_bypass = bypass_keys(got.get("bypass_actors") or [])
    if want_bypass != got_bypass:
        parts.append(
            f"bypass_actors want={want.get('bypass_actors')!r} "
            f"got={got.get('bypass_actors')!r}"
        )

    if parts:
        return False, "; ".join(parts)
    return True, "target/conditions/bypass match"


def _result(
    *,
    id: str,
    action: str,
    reason: str,
    ok: bool,
    **extra: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": id,
        "action": action,
        "reason": reason,
        "ok": ok,
    }
    row.update(extra)
    return row


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
        want_branch = cfg.github["environment_branch"]
        policies, pol_detail = _list_deployment_branch_policies(cfg, run, env)
        if policies is None:
            obs.append(
                Observation(
                    id="environment-branch",
                    status="unknown",
                    detail=pol_detail,
                )
            )
        else:
            exact_ok, exact_detail = _branch_policies_exact(policies, want_branch)
            if exact_ok:
                obs.append(
                    Observation(
                        id="environment-branch",
                        status="ok",
                        detail=exact_detail,
                    )
                )
            else:
                obs.append(
                    Observation(
                        id="environment-branch",
                        status="missing",
                        detail=exact_detail,
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
    # Include concrete dry-run payloads (no secrets / no PEM).
    out.append(
        {
            "id": "environment-payload",
            "action": "would-api",
            "reason": "PUT environments/" + cfg.github["environment"],
            "body": environment_payload(cfg),
        }
    )
    out.append(
        {
            "id": "ruleset-payload",
            "action": "would-api",
            "reason": "POST/PUT rulesets (APP_ID unsubstituted until recorded or discovered)",
            "body": ruleset_preview(cfg),
        }
    )
    out.append(
        {
            "id": "manifest-create",
            "action": "would-browser",
            "reason": (
                f"open {MANIFEST_CREATE_URL} and submit checked-in manifest JSON "
                "(confirm click is S7 / operator; apply --yes refuses browser App confirm)"
            ),
            "url": MANIFEST_CREATE_URL,
            "manifest": cfg.manifest_rel,
        }
    )
    return out


def _apply_environment(
    cfg: GithubConfig, run: Runner, *, dry_run: bool = False
) -> list[dict[str, Any]]:
    """PUT environment + ensure deployment-branch policy (API-only)."""
    env = cfg.github["environment"]
    branch = cfg.github["environment_branch"]
    body = environment_payload(cfg)
    results: list[dict[str, Any]] = []
    if dry_run:
        results.append(
            _result(
                id="environment",
                action="would-api",
                reason=f"PUT environments/{env}",
                ok=True,
                body=body,
            )
        )
        results.append(
            _result(
                id="environment-branch",
                action="would-api",
                reason=(
                    f"ensure deployment-branch-policies exactly "
                    f"name={branch} type=branch (delete extras)"
                ),
                ok=True,
            )
        )
        return results

    data, detail = _gh_json_body(
        run,
        ["api", "-X", "PUT", f"repos/{cfg.full_name}/environments/{env}"],
        body,
    )
    # Preserve real PUT failures. Existence via GET after a failed PUT is not
    # success — the old deployment policy may still be in place (Codex P2).
    if data is None and detail != "empty gh stdout":
        results.append(
            _result(
                id="environment",
                action="failed",
                reason=f"PUT environments/{env}: {detail}",
                ok=False,
            )
        )
        return results

    env_obj: Any
    if isinstance(data, dict) and isinstance(
        data.get("deployment_branch_policy"), dict
    ):
        env_obj = data
    else:
        # Empty / incomplete successful PUT body: read back and compare policy.
        env_obj, get_detail = _gh_json(
            run, ["api", f"repos/{cfg.full_name}/environments/{env}"]
        )
        if not isinstance(env_obj, dict):
            results.append(
                _result(
                    id="environment",
                    action="failed",
                    reason=(
                        f"PUT environments/{env} empty/incomplete body; "
                        f"GET: {get_detail}"
                    ),
                    ok=False,
                )
            )
            return results

    pol_ok, pol_detail = _deployment_policy_matches(env_obj, body)
    if not pol_ok:
        results.append(
            _result(
                id="environment",
                action="failed",
                reason=f"PUT environments/{env}: {pol_detail}",
                ok=False,
            )
        )
        return results
    results.append(
        _result(
            id="environment",
            action="applied",
            reason=f"PUT environments/{env} ok ({pol_detail})",
            ok=True,
        )
    )

    policies, pol_detail = _list_deployment_branch_policies(cfg, run, env)
    if policies is None:
        # Fail closed: without a readable list we cannot DELETE extras or
        # prove the set is exactly environment_branch (Security MEDIUM).
        results.append(
            _result(
                id="environment-branch",
                action="failed",
                reason=f"cannot list deployment-branch-policies: {pol_detail}",
                ok=False,
            )
        )
        return results

    def _readback_exact(prefix: str) -> dict[str, Any] | None:
        """Re-list; return a failed result dict when not exactly want_branch."""
        again, again_detail = _list_deployment_branch_policies(cfg, run, env)
        if again is None:
            return _result(
                id="environment-branch",
                action="failed",
                reason=f"{prefix}; re-list failed: {again_detail}",
                ok=False,
            )
        ok_exact, exact_detail = _branch_policies_exact(again, branch)
        if not ok_exact:
            return _result(
                id="environment-branch",
                action="failed",
                reason=f"{prefix}; read-back: {exact_detail}",
                ok=False,
            )
        return None

    extras = [
        p
        for p in policies
        if not (p.get("name") == branch and p.get("type") == "branch")
    ]
    want_present = any(
        p.get("name") == branch and p.get("type") == "branch" for p in policies
    )
    deleted: list[str] = []
    for extra in extras:
        eid = extra.get("id")
        label = f"{extra.get('name')!r}/{extra.get('type')!r}"
        if eid is None:
            results.append(
                _result(
                    id="environment-branch",
                    action="failed",
                    reason=(
                        f"extra deployment policy {label} has no id "
                        f"(cannot DELETE); list={policies!r}"
                    ),
                    ok=False,
                )
            )
            return results
        del_data, del_detail = _gh_json(
            run,
            [
                "api",
                "-X",
                "DELETE",
                (
                    f"repos/{cfg.full_name}/environments/{env}/"
                    f"deployment-branch-policies/{eid}"
                ),
            ],
        )
        # DELETE often returns empty body; treat non-error as success.
        if del_data is None and del_detail and "empty gh stdout" not in del_detail:
            low = del_detail.lower()
            if "404" not in low and "not found" not in low:
                results.append(
                    _result(
                        id="environment-branch",
                        action="failed",
                        reason=f"DELETE deployment policy {label} id={eid}: {del_detail}",
                        ok=False,
                    )
                )
                return results
        deleted.append(label)

    if not want_present:
        post_data, post_detail = _gh_json(
            run,
            [
                "api",
                "-X",
                "POST",
                f"repos/{cfg.full_name}/environments/{env}/deployment-branch-policies",
                "-f",
                f"name={branch}",
                "-f",
                "type=branch",
            ],
        )
        if post_data is None and "empty gh stdout" not in post_detail:
            low = post_detail.lower()
            if "already" in low or "422" in low or "exists" in low:
                # Idempotent POST is not proof the set is exclusive — re-list.
                fail = _readback_exact(
                    f"POST reported already-exists for {branch!r} ({post_detail})"
                )
                if fail is not None:
                    results.append(fail)
                    return results
                results.append(
                    _result(
                        id="environment-branch",
                        action="skipped",
                        reason=(
                            f"deployment branch {branch!r} only "
                            f"(POST already-exists; read-back ok)"
                        ),
                        ok=True,
                    )
                )
                return results
            results.append(
                _result(
                    id="environment-branch",
                    action="failed",
                    reason=f"POST deployment-branch-policy: {post_detail}",
                    ok=False,
                )
            )
            return results
        reason = f"deployment branch {branch!r} ensured"
        if deleted:
            reason += f"; deleted extras {deleted}"
        fail = _readback_exact(reason)
        if fail is not None:
            results.append(fail)
            return results
        results.append(
            _result(
                id="environment-branch",
                action="applied",
                reason=reason,
                ok=True,
            )
        )
        return results

    if deleted:
        reason = (
            f"deployment branch {branch!r} kept; "
            f"deleted extras {deleted}"
        )
        fail = _readback_exact(reason)
        if fail is not None:
            results.append(fail)
            return results
        results.append(
            _result(
                id="environment-branch",
                action="applied",
                reason=reason,
                ok=True,
            )
        )
        return results

    results.append(
        _result(
            id="environment-branch",
            action="skipped",
            reason=f"deployment branch {branch!r} only already listed",
            ok=True,
        )
    )
    return results


def _apply_ruleset(
    cfg: GithubConfig,
    run: Runner,
    *,
    app_id: int | None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """POST ruleset when absent; PUT when present but drifted."""
    want = ruleset_preview(cfg, app_id=app_id)
    checks = want["rules"][0]["parameters"]["required_status_checks"]
    if any(c.get("integration_id") == "APP_ID" for c in checks):
        return _result(
            id="ruleset",
            action="refused",
            reason=(
                "ruleset apply refused: App ID unknown (set github.app_id in "
                "config/github.toml after S7 App create, or install the App so "
                "GET /user/installations can discover it)"
            ),
            ok=False,
            body=want,
        )
    if dry_run:
        return _result(
            id="ruleset",
            action="would-api",
            reason=f"POST/PUT rulesets name={want['name']!r}",
            ok=True,
            body=want,
        )

    listed, list_detail = _list_rulesets(cfg, run)
    if listed is None:
        return _result(
            id="ruleset",
            action="failed",
            reason=f"list rulesets: {list_detail}",
            ok=False,
        )
    existing = next((r for r in listed if r.get("name") == want["name"]), None)
    if existing is None:
        data, detail = _gh_json_body(
            run,
            ["api", "-X", "POST", f"repos/{cfg.full_name}/rulesets"],
            want,
        )
        if data is None and detail != "empty gh stdout":
            return _result(
                id="ruleset",
                action="failed",
                reason=f"POST rulesets: {detail}",
                ok=False,
            )
        rid = data.get("id") if isinstance(data, dict) else None
        return _result(
            id="ruleset",
            action="applied",
            reason=f"POST ruleset {want['name']!r} id={rid}",
            ok=True,
            ruleset_id=rid,
        )

    rid = existing.get("id")
    if not isinstance(rid, int):
        return _result(
            id="ruleset",
            action="failed",
            reason=f"ruleset {want['name']!r} listed without numeric id",
            ok=False,
        )
    current, get_detail = _get_ruleset(cfg, run, rid)
    if current is None:
        return _result(
            id="ruleset",
            action="failed",
            reason=f"GET rulesets/{rid}: {get_detail}",
            ok=False,
        )
    match, match_detail = _checks_match_want(
        _ruleset_required_checks(current), checks
    )
    enf_ok = current.get("enforcement") == want["enforcement"]
    scope_ok, scope_detail = _ruleset_scope_matches(current, want)
    drift_parts: list[str] = []
    if not match:
        drift_parts.append(match_detail)
    if not enf_ok:
        drift_parts.append(
            f"enforcement want={want['enforcement']!r} "
            f"got={current.get('enforcement')!r}"
        )
    if not scope_ok:
        drift_parts.append(scope_detail)
    if match and enf_ok and scope_ok:
        return _result(
            id="ruleset",
            action="skipped",
            reason=f"ruleset {want['name']!r} id={rid} already matches",
            ok=True,
            ruleset_id=rid,
        )
    drift = "; ".join(drift_parts) or "drift"
    data, detail = _gh_json_body(
        run,
        ["api", "-X", "PUT", f"repos/{cfg.full_name}/rulesets/{rid}"],
        want,
    )
    if data is None and detail != "empty gh stdout":
        return _result(
            id="ruleset",
            action="failed",
            reason=f"PUT rulesets/{rid}: {detail} (was: {drift})",
            ok=False,
            ruleset_id=rid,
        )
    return _result(
        id="ruleset",
        action="updated",
        reason=f"PUT ruleset {want['name']!r} id={rid} ({drift})",
        ok=True,
        ruleset_id=rid,
    )


def apply_yes(
    cfg: GithubConfig,
    *,
    runner: Runner | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Live apply: environment + ruleset via API; refuse browser App confirm (S7).

    Never prints or accepts PEM material. Secret / client-id store stays
    operator stdin (printed as a redirect template only). Exit 0 when every
    result is ok (including expected refuses); 1 when any API step failed.
    Failed environment prerequisites stop downstream App discovery/ruleset calls.
    """
    run = runner or _default_runner
    results: list[dict[str, Any]] = []

    # Local manifest check (no network; never prints PEM).
    man_path = cfg.manifest_path()
    man = load_manifest(man_path)
    man_errs = validate_manifest(man, path=man_path)
    if man_errs:
        results.append(
            _result(
                id="manifest",
                action="failed",
                reason="; ".join(man_errs),
                ok=False,
            )
        )
        return results, 1
    results.append(
        _result(
            id="manifest",
            action="checked",
            reason=f"{cfg.manifest_rel} permissions+webhook inactive ok",
            ok=True,
        )
    )

    # Browser App confirm is S7 — refuse here (API-only apply).
    results.append(
        _result(
            id="app-create",
            action="refuse-browser",
            reason=(
                f"browser App confirm refused (setup-plan S7): open "
                f"{MANIFEST_CREATE_URL}, submit {cfg.manifest_rel}, then record "
                f"app_id in config/github.toml; ade-github-setup never drives "
                f"the confirm click"
            ),
            ok=True,
            browser=True,
            url=MANIFEST_CREATE_URL,
        )
    )
    results.append(
        _result(
            id="app-install",
            action="refuse-browser",
            reason=(
                f"App install on {cfg.full_name} is operator / S7 "
                "(API apply does not open the install UI)"
            ),
            ok=True,
            browser=True,
        )
    )

    environment_results = _apply_environment(cfg, run, dry_run=False)
    results.extend(environment_results)

    secret = cfg.github["private_key_secret"]
    env = cfg.github["environment"]
    results.append(
        _result(
            id="store-private-key",
            action="refuse-operator-secret",
            reason=(
                f"private key store is operator-only (never print PEM): "
                f"gh secret set {secret} --env {env} --repo {cfg.full_name} "
                f"< {cfg.github['app_slug']}.private-key.pem"
            ),
            ok=True,
            secret_handling="stdin-file-redirect",
        )
    )
    var = cfg.github["client_id_variable"]
    results.append(
        _result(
            id="store-client-id",
            action="refuse-operator-variable",
            reason=(
                f"client id store is operator-only: "
                f"gh variable set {var} --env {env} --repo {cfg.full_name} "
                f"--body '<Client ID>'"
            ),
            ok=True,
        )
    )

    failed_prerequisites = [row["id"] for row in environment_results if not row.get("ok")]
    if failed_prerequisites:
        results.append(
            _result(
                id="ruleset",
                action="refused-prerequisite",
                reason=(
                    "ruleset apply not started: failed environment prerequisite(s): "
                    + ", ".join(failed_prerequisites)
                    + "; repair the reported failures before retrying apply"
                ),
                ok=False,
            )
        )
    else:
        app_id = _discover_app_id(cfg, run)
        results.append(_apply_ruleset(cfg, run, app_id=app_id, dry_run=False))

    results.append(
        _result(
            id="hardening",
            action="deferred",
            reason="[hardening] / harden-check (S5) and S5a stay deferred",
            ok=True,
        )
    )

    failed = sum(1 for r in results if not r.get("ok"))
    return results, (1 if failed else 0)


def verify(
    cfg: GithubConfig,
    *,
    runner: Runner | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """API-only verify of manifest + environment + ruleset (no mutations).

    Does not run throwaway T0–T3b PRs (those stay operator / later). Never
    reads secret values — only names via observe-shaped probes where needed.
    Exit 0 when every check is ok; 1 on drift / missing; unknown probes do
    not alone fail (same posture as observe for unreadable endpoints).
    """
    run = runner or _default_runner
    results: list[dict[str, Any]] = []
    rc = 0

    man_path = cfg.manifest_path()
    man = load_manifest(man_path)
    man_errs = validate_manifest(man, path=man_path)
    if man_errs:
        results.append(
            _result(
                id="manifest",
                action="verify-fail",
                reason="; ".join(man_errs),
                ok=False,
            )
        )
        return results, 1
    results.append(
        _result(
            id="manifest",
            action="verify-ok",
            reason=f"{cfg.manifest_rel} local permissions+webhook inactive ok",
            ok=True,
        )
    )

    env = cfg.github["environment"]
    env_data, env_detail = _gh_json(
        run, ["api", f"repos/{cfg.full_name}/environments/{env}"]
    )
    if env_data is None:
        if "404" in env_detail.lower() or "not found" in env_detail.lower():
            results.append(
                _result(
                    id="environment",
                    action="verify-fail",
                    reason=f"environment {env!r} absent: {env_detail}",
                    ok=False,
                )
            )
            rc = 1
        else:
            results.append(
                _result(
                    id="environment",
                    action="verify-unknown",
                    reason=env_detail,
                    ok=True,
                )
            )
    else:
        want_env = environment_payload(cfg)
        pol_ok, pol_match = _deployment_policy_matches(env_data, want_env)
        if pol_ok:
            results.append(
                _result(
                    id="environment",
                    action="verify-ok",
                    reason=f"environment {env!r} present ({pol_match})",
                    ok=True,
                )
            )
        else:
            results.append(
                _result(
                    id="environment",
                    action="verify-fail",
                    reason=f"environment {env!r}: {pol_match}",
                    ok=False,
                )
            )
            rc = 1
        want_branch = cfg.github["environment_branch"]
        policies, pol_detail = _list_deployment_branch_policies(cfg, run, env)
        if policies is None:
            results.append(
                _result(
                    id="environment-branch",
                    action="verify-unknown",
                    reason=pol_detail,
                    ok=True,
                )
            )
        else:
            exact_ok, exact_detail = _branch_policies_exact(policies, want_branch)
            if exact_ok:
                results.append(
                    _result(
                        id="environment-branch",
                        action="verify-ok",
                        reason=exact_detail,
                        ok=True,
                    )
                )
            else:
                results.append(
                    _result(
                        id="environment-branch",
                        action="verify-fail",
                        reason=exact_detail,
                        ok=False,
                    )
                )
                rc = 1

    app_id = _discover_app_id(cfg, run)
    want = ruleset_preview(cfg, app_id=app_id)
    want_checks = want["rules"][0]["parameters"]["required_status_checks"]
    if any(c.get("integration_id") == "APP_ID" for c in want_checks):
        results.append(
            _result(
                id="ruleset",
                action="verify-fail",
                reason=(
                    "App ID unknown — cannot verify adversary-marker pin "
                    "(record github.app_id or install the App)"
                ),
                ok=False,
            )
        )
        return results, 1

    listed, list_detail = _list_rulesets(cfg, run)
    if listed is None:
        results.append(
            _result(
                id="ruleset",
                action="verify-unknown",
                reason=list_detail,
                ok=True,
            )
        )
        return results, rc

    existing = next(
        (r for r in listed if r.get("name") == want["name"]), None
    )
    if existing is None:
        results.append(
            _result(
                id="ruleset",
                action="verify-fail",
                reason=f"ruleset {want['name']!r} not found",
                ok=False,
            )
        )
        return results, 1

    rid = existing.get("id")
    if not isinstance(rid, int):
        results.append(
            _result(
                id="ruleset",
                action="verify-fail",
                reason=f"ruleset {want['name']!r} has no numeric id",
                ok=False,
            )
        )
        return results, 1

    current, get_detail = _get_ruleset(cfg, run, rid)
    if current is None:
        results.append(
            _result(
                id="ruleset",
                action="verify-unknown",
                reason=get_detail,
                ok=True,
                ruleset_id=rid,
            )
        )
        return results, rc

    match, match_detail = _checks_match_want(
        _ruleset_required_checks(current), want_checks
    )
    enf_ok = current.get("enforcement") == want["enforcement"]
    scope_ok, scope_detail = _ruleset_scope_matches(current, want)
    if match and enf_ok and scope_ok:
        results.append(
            _result(
                id="ruleset",
                action="verify-ok",
                reason=(
                    f"ruleset {want['name']!r} id={rid} enforcement="
                    f"{current.get('enforcement')} checks+scope match "
                    f"(app_id={app_id})"
                ),
                ok=True,
                ruleset_id=rid,
                app_id=app_id,
            )
        )
    else:
        parts = []
        if not enf_ok:
            parts.append(
                f"enforcement want={want['enforcement']!r} "
                f"got={current.get('enforcement')!r}"
            )
        if not match:
            parts.append(match_detail)
        if not scope_ok:
            parts.append(scope_detail)
        results.append(
            _result(
                id="ruleset",
                action="verify-fail",
                reason="; ".join(parts),
                ok=False,
                ruleset_id=rid,
                app_id=app_id,
            )
        )
        rc = 1
    return results, rc
