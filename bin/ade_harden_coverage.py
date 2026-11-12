"""S6 coverage beyond the GitHub observe-only check (setup-plan S6, 2026-11-12).

Three pieces, all read-only except the separately authorized interaction-limit
renewal:

- **Forgejo drift** — read-back of the same policy keys against a Forgejo
  instance, through an injected runner (tests) or a ``fj`` argv list. The
  token never appears on an argv; the caller injects it with
  ``sudo-secretspec run`` (key name ``forgejo_token``).
- **Notifications** — a drift report rendered for the operator. Delivery is
  print-only here; nothing is posted.
- **Interaction-limit renewal** — the one mutation contract §7 authorizes:
  PUT ``/user/interaction-limits`` only after the exact current state was
  read and is the configured limit with the expiry inside the renewal
  window, then a read-back of the new expiry. ``--dry-run`` (the default)
  never writes.
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

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


def _parse_body(text: str) -> tuple[Any | None, str]:
    body = (text or "").strip()
    if not body:
        return None, "empty response"
    try:
        return json.loads(body), "ok"
    except json.JSONDecodeError as e:
        return None, f"JSON: {e}"


def observe_forgejo_repo(
    cfg: ah.HardenConfig,
    row: dict[str, Any],
    *,
    runner: Callable[[list[str]], Any],
    base_url: str,
) -> list[ah.DriftFinding]:
    """Read one Forgejo repo's settings back. Never writes."""
    owner, name = str(row["owner"]), str(row["name"])
    full = f"{owner}/{name}"
    policy = ah.resolve_policy(cfg, row)
    proc = runner(
        [
            "fj",
            "api",
            "--base",
            base_url,
            f"repos/{owner}/{name}",
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
                detail=(proc.stderr or detail or f"fj exit {proc.returncode}")
                .strip()
                .splitlines()[0][:200],
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


def render_notification(findings: list[ah.DriftFinding]) -> str:
    """Operator-facing drift notice. Print-only: nothing is sent."""
    bad = [f for f in findings if f.status in {"drift", "missing", "uncovered"}]
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
            detail=(proc.stderr or "renew request failed").strip().splitlines()[0][:200],
        )
        return plan
    after, after_detail = ah._gh_json(
        reader, ["api", "user/interaction-limits"], api_version=cfg.api_version
    )
    ok = (
        isinstance(after, dict)
        and after.get("limit") == want_limit
        and ah._parse_expires_at(after.get("expires_at")) is not None
    )
    plan.update(wrote=True, readback_ok=ok, readback_detail=after_detail)
    return plan


def load_canary_corpus(path: Path) -> list[dict[str, Any]]:
    """Read a payload-free canary manifest.

    Each row: ``id``, ``source``, ``label`` (benign|injection), ``surface``,
    ``expected`` (the decision the canary must produce) and ``text`` (the
    canary payload, which this function returns but no report retains).
    """
    rows = [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    if len(rows) != 2:
        raise ah.HardenError("canary corpus must hold exactly two rows")
    labels = set()
    for row in rows:
        for key in ("id", "source"):
            if not isinstance(row.get(key), str) or not _ID_RE.match(row[key]):
                raise ah.HardenError(f"canary {key} is not a short identifier")
        if row.get("label") not in CANARY_EXPECTATIONS:
            raise ah.HardenError("canary label must be benign or injection")
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


