"""S6 coverage beyond the GitHub observe-only check (setup-plan S6, 2026-11-12).

Three pieces, all read-only except the separately authorized interaction-limit
renewal:

- **Forgejo drift** — a GET of ``/api/v1/repos/{owner}/{name}`` through the
  ``forgejo-api`` script (skills/forgejo), which reads its own token from the
  environment and re-runs under ``sudo-secretspec run`` when it is absent, so
  the token is never on an argv. The installed ``fj`` (forgejo-cli) has no
  generic API command and authenticates from its own keyring, so it is not
  used.
- **Notifications** — a drift report rendered for the operator. ``observe``
  prints it; nothing is posted.
- **Interaction-limit renewal** — the one mutation contract §7 authorizes:
  PUT ``/user/interaction-limits`` only after the exact current state was
  read and is the configured limit with the expiry inside the renewal
  window, then a read-back that the expiry moved forward. ``--dry-run`` (the
  default) never writes.
- **Gate canary** — one benign and one disclosed-payload canary through
  ``ade-injection-gate``, compared against recorded expected decisions.
  Canary text is never committed: the corpus lives outside the repo and is
  passed by path. Ids, source, label, surface and the expected decision are
  recorded; the payload text is not.

Nothing here writes rulesets, repo settings or anything except that one PUT.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import ade_harden as ah

FORGEJO_SETTINGS = (
    "has_pull_requests",
    "has_issues",
    "has_wiki",
    "has_projects",
)
# Recorded canary expectations (plan S5a §6). Payload text is never stored.
CANARY_EXPECTATIONS = {
    "benign": "benign",
    "injection": "injection",
}
_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _first_line(text: str, fallback: str) -> str:
    """First non-empty line, bounded. Whitespace-only text returns fallback."""
    return ((text or "").strip().splitlines() or [fallback])[0][:200]


def _parse_body(text: str) -> tuple[Any | None, str]:
    body = (text or "").strip()
    if not body:
        return None, "empty response"
    try:
        return json.loads(body), "ok"
    except json.JSONDecodeError as e:
        return None, f"JSON: {e}"


def forgejo_api_script() -> Path | None:
    """The forgejo skill's ``forgejo-api`` script, which holds the token.

    The skill is not part of this repo and the script is not on PATH: it is
    linked under ``~/.agents/skills/forgejo/scripts/`` (and the Claude skills
    dir). ``which`` finds nothing, so those links are checked explicitly.
    """
    found = shutil.which("forgejo-api")
    if found:
        return Path(found)
    home = Path.home()
    for candidate in (
        home / ".agents/skills/forgejo/scripts/forgejo-api",
        home / ".claude/skills/forgejo/scripts/forgejo-api",
    ):
        if candidate.is_file():
            return candidate
    return None


def observe_forgejo_repo(
    cfg: ah.HardenConfig,
    row: dict[str, Any],
    *,
    runner: Callable[[list[str]], Any],
    base_url: str,
    api: Path | None = None,
) -> list[ah.DriftFinding]:
    """Read one Forgejo repo's settings back. Never writes.

    ``GET /api/v1/repos/{owner}/{name}`` via ``forgejo-api --host HOST``,
    which authenticates itself. ``base_url`` is only the origin: an https URL
    whose host is passed as ``--host`` and never interpolated into a shell.
    """
    owner, name = str(row["owner"]), str(row["name"])
    full = f"{owner}/{name}"
    policy = ah.resolve_policy(cfg, row)
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname:
        return [
            ah.DriftFinding(
                target=f"forgejo:{full}",
                setting="repo",
                wanted="https base_url",
                found=base_url,
                status="error",
                detail="hardening.forgejo.base_url is not an https URL",
            )
        ]
    script = api if api is not None else forgejo_api_script()
    if script is None:
        # Configured but unreadable fails the check. A missing script is a
        # broken setup, not an unreachable host (that stays `unknown`).
        return [
            ah.DriftFinding(
                target=f"forgejo:{full}",
                setting="repo",
                wanted="forgejo-api script",
                found=None,
                status="error",
                detail=(
                    "forgejo-api not found on PATH or under "
                    "~/.agents/skills/forgejo/scripts"
                ),
            )
        ]
    proc = runner(
        [
            str(script),
            "--host",
            parsed.hostname,
            "GET",
            f"/repos/{owner}/{name}",
        ]
    )
    data, detail = _parse_body(proc.stdout or "")
    if proc.returncode != 0 or not isinstance(data, dict):
        return [
            ah.DriftFinding(
                target=f"forgejo:{full}",
                setting="repo",
                wanted="readable",
                found=None,
                status="unknown",
                detail=_first_line(
                    proc.stderr or "", detail or f"forgejo-api exit {proc.returncode}"
                ),
            )
        ]
    findings: list[ah.DriftFinding] = []
    pr = policy.get("pr_creation_policy")
    if pr == "disabled":
        findings.append(
            ah._cmp(
                target=f"forgejo:{full}",
                setting="has_pull_requests",
                wanted=False,
                found=data.get("has_pull_requests"),
                ok=data.get("has_pull_requests") is False,
            )
        )
    issues = policy.get("issue_creation_policy")
    if issues == "disabled":
        findings.append(
            ah._cmp(
                target=f"forgejo:{full}",
                setting="has_issues",
                wanted=False,
                found=data.get("has_issues"),
                ok=data.get("has_issues") is False,
            )
        )
    for key, flag in (
        ("disable_wiki", "has_wiki"),
        ("disable_projects", "has_projects"),
    ):
        if policy.get(key) is True:
            findings.append(
                ah._cmp(
                    target=f"forgejo:{full}",
                    setting=flag,
                    wanted=False,
                    found=data.get(flag),
                    ok=data.get(flag) is False,
                )
            )
    if not findings:
        findings.append(
            ah.DriftFinding(
                target=f"forgejo:{full}",
                setting="repo",
                wanted="compared",
                found=sorted(k for k in FORGEJO_SETTINGS if k in data),
                status="ok",
                detail="no comparable Forgejo settings in policy",
            )
        )
    return findings


# Statuses that fail the check. The notice must name exactly these, or it
# can say "0 findings" while observe exits 1.
ACTIONABLE = frozenset({"drift", "missing", "uncovered", "error"})


def render_notification(findings: list[ah.DriftFinding]) -> str:
    """Operator-facing drift notice. Print-only: nothing is sent."""
    bad = [f for f in findings if f.status in ACTIONABLE]
    lines = [
        f"harden-check: {len(bad)} finding(s) need attention "
        "(observe-only; nothing was changed)"
    ]
    for f in bad:
        lines.append(
            f"- {f.status}: {f.target} {f.setting} wanted={f.wanted!r} found={f.found!r}"
        )
        if f.remediation:
            lines.append(f"  remediation: {f.remediation}")
    return "\n".join(lines)


def renewal_plan(
    current: dict[str, Any] | None,
    *,
    want_limit: str,
    want_expiry: str,
    min_days: int,
    now: datetime,
) -> dict[str, Any]:
    """Decide whether the one authorized renewal applies. Never writes."""
    if want_limit not in ah.INTERACTION_LIMITS or want_limit == ah.IGNORE:
        return {"renew": False, "reason": "limit not renewable"}
    if want_expiry not in ah.INTERACTION_EXPIRIES:
        return {"renew": False, "reason": "expiry not in the GitHub enum"}
    if not isinstance(current, dict) or current.get("limit") != want_limit:
        return {
            "renew": False,
            "reason": "current limit is not exactly the configured limit; "
            "a check never changes the limit itself",
        }
    expires = ah._parse_expires_at(current.get("expires_at"))
    if expires is None:
        return {"renew": False, "reason": "current expiry unreadable"}
    remaining = (expires - now).total_seconds() / 86400.0
    if remaining > float(min_days):
        return {"renew": False, "reason": f"{remaining:.1f} days remain"}
    body = json.dumps({"limit": want_limit, "expiry": want_expiry})
    argv = [
        "gh",
        "api",
        "--method",
        "PUT",
        "-H",
        "Accept: application/vnd.github+json",
        "user/interaction-limits",
        "--input",
        "-",
    ]
    return {
        "renew": True,
        "reason": f"{remaining:.1f} days remain, inside the renewal window",
        "request": {"argv": argv, "body": body},
        "readback": ["gh", "api", "user/interaction-limits"],
    }


def default_writer(argv: list[str], body: str) -> Any:
    """The one authorized write: body on stdin, never on the command line."""
    import subprocess

    return subprocess.run(
        argv, input=body, capture_output=True, text=True, check=False
    )


def renew_interaction_limits(
    cfg: ah.HardenConfig,
    *,
    reader: Callable[[list[str]], Any],
    writer: Callable[[list[str], str], Any] | None = None,
    now: datetime | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Renew the user interaction limit, or report why not.

    Default is dry-run, which never calls ``writer``. A real run writes only
    the planned PUT (the body on stdin, so it is never in the process list),
    then reads the limit back and reports failure if it is not exactly the
    configured value.
    """
    il = cfg.interaction_limits
    want_limit = str(il.get("limit", "collaborators_only"))
    want_expiry = str(il.get("expiry", ah.DEFAULT_INTERACTION_EXPIRY))
    min_days = int(il.get("min_remaining_days", 14))
    clock = now or datetime.now(timezone.utc)
    current, detail = ah._gh_json(
        reader, ["api", "user/interaction-limits"], api_version=cfg.api_version
    )
    plan = renewal_plan(
        current if isinstance(current, dict) else None,
        want_limit=want_limit,
        want_expiry=want_expiry,
        min_days=min_days,
        now=clock,
    )
    plan["observed"] = detail
    plan["dry_run"] = dry_run
    if not plan["renew"] or dry_run:
        plan["wrote"] = False
        return plan
    req = plan["request"]
    proc = (writer or default_writer)(req["argv"], req["body"])
    if proc.returncode != 0:
        plan.update(
            wrote=False,
            readback_ok=False,
            detail=_first_line(proc.stderr or "", "renew request failed"),
        )
        return plan
    after, after_detail = ah._gh_json(
        reader, ["api", "user/interaction-limits"], api_version=cfg.api_version
    )
    before = ah._parse_expires_at(
        current.get("expires_at") if isinstance(current, dict) else None
    )
    after_expires = ah._parse_expires_at(
        after.get("expires_at") if isinstance(after, dict) else None
    )
    # The new expiry must be strictly later: a PUT that exits 0 without
    # effect would otherwise read back as success.
    ok = (
        isinstance(after, dict)
        and after.get("limit") == want_limit
        and before is not None
        and after_expires is not None
        and after_expires > before
    )
    plan.update(wrote=True, readback_ok=ok, readback_detail=after_detail)
    return plan


def _gate_surfaces() -> frozenset[str]:
    """The surfaces ``ade-injection-gate`` accepts. Local import: the gate
    module is heavy relative to a config check."""
    import ade_injection_gate as gate

    return frozenset(gate.SURFACES)


def load_canary_corpus(path: Path) -> list[dict[str, Any]]:
    """Read a payload-free canary manifest. ``~`` is expanded.

    Each row: ``id``, ``source``, ``label`` (benign|injection), ``surface``,
    ``expected`` (the decision the canary must produce) and ``text`` (the
    canary payload, which this function returns but no report retains).
    """
    path = Path(path).expanduser()
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeError) as e:
        raise ah.HardenError(f"canary corpus unreadable: {type(e).__name__}") from e
    rows = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            raise ah.HardenError(f"canary corpus line {e.lineno}: not JSON") from e
        if not isinstance(row, dict):
            raise ah.HardenError("canary corpus row is not an object")
        rows.append(row)
    if len(rows) != 2:
        raise ah.HardenError("canary corpus must hold exactly two rows")
    labels = set()
    for row in rows:
        for key in ("id", "source"):
            if not isinstance(row.get(key), str) or not _ID_RE.match(row[key]):
                raise ah.HardenError(f"canary {key} is not a short identifier")
        if row.get("label") not in CANARY_EXPECTATIONS:
            raise ah.HardenError("canary label must be benign or injection")
        if row.get("surface") not in _gate_surfaces():
            raise ah.HardenError("canary surface is not one the gate classifies")
        if row.get("expected") != CANARY_EXPECTATIONS[row["label"]]:
            raise ah.HardenError("canary expected decision disagrees with its label")
        if not isinstance(row.get("text"), str) or not row["text"].strip():
            raise ah.HardenError("canary text missing")
        labels.add(row["label"])
    if labels != set(CANARY_EXPECTATIONS):
        raise ah.HardenError("canary corpus needs one benign and one injection row")
    return rows


def gate_canary(
    corpus: Path,
    *,
    classify: Callable[[str, str], dict[str, Any]],
    max_ms: int = 5000,
) -> list[ah.DriftFinding]:
    """Run both canaries and compare decisions. Payload text is not retained."""
    findings: list[ah.DriftFinding] = []
    for row in load_canary_corpus(corpus):
        try:
            result = classify(row["text"], row["surface"])
        except (OSError, ValueError, TypeError, KeyError):
            result = {"status": "unavailable", "decide": "escalate", "latency_ms": None}
        status = result.get("status")
        decide = result.get("decide")
        latency = result.get("latency_ms")
        slow = isinstance(latency, (int, float)) and latency > max_ms
        ok = status == "ok" and decide == row["expected"] and not slow
        findings.append(
            ah.DriftFinding(
                target="s5a",
                setting=f"canary.{row['label']}",
                wanted=row["expected"],
                found=decide,
                status="ok" if ok else "drift",
                detail=(
                    f"id={row['id']} source={row['source']} gate={status}"
                    + (f" latency_ms={latency}" if latency is not None else "")
                    + (" over max_ms" if slow else "")
                ),
                remediation=None
                if ok
                else "gate canary failed; investigate before trusting the gate",
            )
        )
    return findings


