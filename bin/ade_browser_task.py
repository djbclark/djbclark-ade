"""ade_browser_task: render / relay browser-only prompts (setup-plan S7).

First unit (2026-11-10): list and render checked-in templates under
``prompts/browser/``, then relay via ``coding-bot ask`` when that binary is on
PATH. With no coding-bot (or ``relay --dry-run``), print a self-contained
prompt and report ``unsent``. No live browser session, no completion claim,
no secret widening. See docs/browser-task.md.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

BIN = Path(__file__).resolve().parent
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

TASK_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
OWNER_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+$")
VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
FRONTMATTER_BOUNDARY = "---"

# Never ship or run a template that widens access (S7 §4).
WIDEN_TASK_IDS: frozenset[str] = frozenset(
    {
        "add-collaborator",
        "add-bypass-actor",
        "widen-access",
        "grant-access",
        "invite-collaborator",
    }
)

SECRET_ARGV_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY"),
    re.compile(r"-----BEGIN"),
    re.compile(r"(?i)^--?(?:private[-_]?key|pem|client[-_]?secret|token|password)(=|$)"),
)

SECRET_FLAGS: frozenset[str] = frozenset(
    {
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
    }
)

# argv, optional stdin text → CompletedProcess (tests inject a fake).
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class BrowserTaskError(ValueError):
    """Invalid template, refused task, or refused argv."""


@dataclass(frozen=True)
class TemplateMeta:
    """Optional YAML-ish frontmatter fields we care about (stdlib parse)."""

    title: str | None = None
    url: str | None = None
    widens_access: bool = False
    raw: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Template:
    task_id: str
    path: Path
    body: str
    meta: TemplateMeta


@dataclass(frozen=True)
class Rendered:
    task_id: str
    path: Path
    text: str
    url: str | None
    vars_used: dict[str, str]


@dataclass(frozen=True)
class RelayResult:
    status: str  # sent | unsent | dry-run
    task_id: str
    detail: str
    coding_bot: str | None = None
    prompt: str | None = None


def repo_root_from_here() -> Path:
    return Path(__file__).resolve().parent.parent


def default_prompts_dir(root: Path) -> Path:
    return root / "prompts" / "browser"


def default_github_config_path(root: Path) -> Path:
    return root / "config" / "github.toml"


def refuse_secret_argv(argv: list[str] | None) -> None:
    """Raise BrowserTaskError when argv appears to carry secret material.

    Private keys and tokens never travel on the command line (review rule 3;
    S7 §4: secrets stay with the operator / ``gh secret set``).
    """
    if not argv:
        return
    for i, arg in enumerate(argv):
        if not isinstance(arg, str):
            continue
        low = arg.lower().split("=", 1)[0]
        if low in SECRET_FLAGS:
            raise BrowserTaskError(
                f"refuse secret flag {low!r} on argv; "
                "browser tasks never take secrets (operator stores keys with "
                "`gh secret set … < file`)"
            )
        for pat in SECRET_ARGV_PATTERNS:
            if pat.search(arg):
                raise BrowserTaskError(
                    "refuse secret material on argv "
                    f"(arg[{i}] matched {pat.pattern!r}); "
                    "browser tasks never take secrets"
                )


def validate_owner_repo(value: str, *, kind: str) -> str:
    if not value or not OWNER_REPO_RE.fullmatch(value):
        raise BrowserTaskError(
            f"{kind} must match {OWNER_REPO_RE.pattern!r}, got {value!r}"
        )
    return value


def validate_task_id(task_id: str) -> str:
    if not TASK_ID_RE.fullmatch(task_id):
        raise BrowserTaskError(
            f"task id must match {TASK_ID_RE.pattern!r}, got {task_id!r}"
        )
    if task_id in WIDEN_TASK_IDS:
        raise BrowserTaskError(
            f"refuse task {task_id!r}: widens access (S7 never-through-bot)"
        )
    return task_id


def _parse_frontmatter(text: str) -> tuple[TemplateMeta, str]:
    """Parse a minimal ``---\\nkey: value\\n---`` block; body is the rest."""
    if not text.startswith(FRONTMATTER_BOUNDARY + "\n"):
        return TemplateMeta(), text
    lines = text.splitlines()
    i = 1
    raw: dict[str, str] = {}
    while i < len(lines) and lines[i].strip() != FRONTMATTER_BOUNDARY:
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise BrowserTaskError(f"frontmatter line needs 'key: value': {line!r}")
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        raw[key] = value
    if i >= len(lines) or lines[i].strip() != FRONTMATTER_BOUNDARY:
        raise BrowserTaskError("frontmatter missing closing ---")
    body = "\n".join(lines[i + 1 :])
    if body.startswith("\n"):
        body = body[1:]
    widens = raw.get("widens_access", "false").strip().lower() in {
        "true",
        "yes",
        "1",
    }
    return (
        TemplateMeta(
            title=raw.get("title"),
            url=raw.get("url"),
            widens_access=widens,
            raw=dict(raw),
        ),
        body,
    )


def load_template(path: Path, *, task_id: str | None = None) -> Template:
    tid = validate_task_id(task_id or path.stem)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise BrowserTaskError(f"{path}: {e}") from e
    meta, body = _parse_frontmatter(text)
    if meta.widens_access:
        raise BrowserTaskError(
            f"{path}: widens_access=true refused (S7 never-through-bot)"
        )
    if not body.strip():
        raise BrowserTaskError(f"{path}: empty body")
    return Template(task_id=tid, path=path, body=body, meta=meta)


def list_templates(prompts_dir: Path) -> list[Template]:
    if not prompts_dir.is_dir():
        raise BrowserTaskError(f"{prompts_dir}: prompts directory missing")
    out: list[Template] = []
    for path in sorted(prompts_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        try:
            tid = validate_task_id(path.stem)
        except BrowserTaskError:
            continue  # skip non-task markdown
        out.append(load_template(path, task_id=tid))
    return out


def load_github_defaults(root: Path) -> dict[str, str]:
    """Best-effort owner/repo/app_name/manifest from config/github.toml."""
    path = default_github_config_path(root)
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    gh = data.get("github")
    if not isinstance(gh, dict):
        return {}
    out: dict[str, str] = {}
    for key, alias in (
        ("owner", "owner"),
        ("repository", "repo"),
        ("app_name", "app_name"),
        ("manifest", "manifest"),
    ):
        val = gh.get(key)
        if isinstance(val, str) and val.strip():
            out[alias] = val.strip()
    if "owner" in out and "repo" in out:
        out["owner_repo"] = f"{out['owner']}/{out['repo']}"
    return out


def build_vars(
    *,
    root: Path,
    owner: str | None = None,
    repo: str | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    defaults = load_github_defaults(root)
    merged = dict(defaults)
    if owner is not None:
        merged["owner"] = validate_owner_repo(owner, kind="owner")
    if repo is not None:
        merged["repo"] = validate_owner_repo(repo, kind="repo")
    if extra:
        for k, v in extra.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
                raise BrowserTaskError(f"invalid var name {k!r}")
            merged[k] = v
    if "owner" in merged:
        validate_owner_repo(merged["owner"], kind="owner")
    if "repo" in merged:
        validate_owner_repo(merged["repo"], kind="repo")
    if "owner" in merged and "repo" in merged:
        merged["owner_repo"] = f"{merged['owner']}/{merged['repo']}"
    # Safe defaults for templates that mention the App even without github.toml.
    merged.setdefault("app_name", "ade-merge-gate")
    merged.setdefault("manifest", ".github/app-manifest.json")
    return merged


def render_body(body: str, variables: dict[str, str]) -> tuple[str, dict[str, str]]:
    used: dict[str, str] = {}
    missing: list[str] = []

    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in variables:
            missing.append(key)
            return m.group(0)
        used[key] = variables[key]
        return variables[key]

    text = VAR_RE.sub(repl, body)
    if missing:
        uniq = sorted(set(missing))
        raise BrowserTaskError(
            "template variables missing: " + ", ".join(uniq)
        )
    return text, used


def render_task(
    root: Path,
    task_id: str,
    *,
    owner: str | None = None,
    repo: str | None = None,
    extra: dict[str, str] | None = None,
    prompts_dir: Path | None = None,
) -> Rendered:
    tid = validate_task_id(task_id)
    pdir = prompts_dir or default_prompts_dir(root)
    path = pdir / f"{tid}.md"
    if not path.is_file():
        known = [t.task_id for t in list_templates(pdir)] if pdir.is_dir() else []
        raise BrowserTaskError(
            f"unknown task {tid!r} (have: {', '.join(known) or 'none'})"
        )
    tmpl = load_template(path, task_id=tid)
    variables = build_vars(root=root, owner=owner, repo=repo, extra=extra)
    # Hard requirement for any template that mentions owner/repo placeholders.
    needed = set(VAR_RE.findall(tmpl.body))
    for key in ("owner", "repo", "owner_repo"):
        if key in needed and key not in variables:
            raise BrowserTaskError(
                f"task {tid!r} needs {key}= (pass --owner/--repo or config/github.toml)"
            )
    text, used = render_body(tmpl.body, variables)
    url = tmpl.meta.url
    if url:
        url, _ = render_body(url, variables)
        # Injection containment (argon D3): only hardcoded github.com settings URLs
        # after owner/repo substitution — never open arbitrary hosts from templates.
        if not url.startswith("https://github.com/"):
            raise BrowserTaskError(
                f"task {tid!r}: url must start with https://github.com/, got {url!r}"
            )
    return Rendered(
        task_id=tid,
        path=path,
        text=text if text.endswith("\n") else text + "\n",
        url=url,
        vars_used=used,
    )


def find_coding_bot(path_env: str | None = None) -> str | None:
    """Return absolute path to ``coding-bot`` if present on PATH."""
    env = os.environ if path_env is None else {"PATH": path_env}
    found = shutil.which("coding-bot", path=env.get("PATH"))
    return found


def _default_runner(
    argv: list[str], *, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 — argv list only, never shell
        argv,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def relay_task(
    rendered: Rendered,
    *,
    dry_run: bool = False,
    coding_bot: str | None = None,
    runner: Runner | None = None,
) -> RelayResult:
    """Relay a rendered prompt.

    - ``dry_run``: print-only; status ``dry-run`` (just recipe default).
    - coding-bot present: ``coding-bot ask`` with the prompt on stdin; status
      ``sent`` only means the ask subprocess exited 0 — never that the setting
      changed (S7 §3).
    - otherwise: status ``unsent`` with the prompt for operator paste.
    """
    if dry_run:
        return RelayResult(
            status="dry-run",
            task_id=rendered.task_id,
            detail="would relay via coding-bot ask when available; no send",
            coding_bot=coding_bot or find_coding_bot(),
            prompt=rendered.text,
        )
    bot = coding_bot if coding_bot is not None else find_coding_bot()
    if not bot:
        return RelayResult(
            status="unsent",
            task_id=rendered.task_id,
            detail=(
                "coding-bot not on PATH; prompt below for operator paste "
                "(skills/tell-coding-bot); never claim sent"
            ),
            coding_bot=None,
            prompt=rendered.text,
        )
    run = runner or _default_runner
    # ask TEXT|- : pass "-" so the prompt is stdin, never argv (size + secrets).
    proc = run([bot, "ask", "-"], input_text=rendered.text)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        return RelayResult(
            status="unsent",
            task_id=rendered.task_id,
            detail=f"coding-bot ask failed ({err}); prompt unsent",
            coding_bot=bot,
            prompt=rendered.text,
        )
    return RelayResult(
        status="sent",
        task_id=rendered.task_id,
        detail=(
            "coding-bot ask exited 0; a send proves neither completion nor "
            "the setting (verify the artifact; bot reply is outside data)"
        ),
        coding_bot=bot,
        prompt=None,
    )


def template_summary(tmpl: Template) -> dict[str, Any]:
    return {
        "id": tmpl.task_id,
        "path": str(tmpl.path),
        "title": tmpl.meta.title,
        "url": tmpl.meta.url,
        "widens_access": tmpl.meta.widens_access,
    }


def rendered_payload(rendered: Rendered) -> dict[str, Any]:
    return {
        "task_id": rendered.task_id,
        "path": str(rendered.path),
        "url": rendered.url,
        "vars": dict(rendered.vars_used),
        "prompt": rendered.text,
    }


def relay_payload(result: RelayResult) -> dict[str, Any]:
    out: dict[str, Any] = {
        "status": result.status,
        "task_id": result.task_id,
        "detail": result.detail,
        "coding_bot": result.coding_bot,
    }
    if result.prompt is not None:
        out["prompt"] = result.prompt
    return out
