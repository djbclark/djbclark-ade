#!/usr/bin/env python3
"""Pick which vendor should run a piece of work, from capability and headroom.

Routing here has been manual, which means it defaults to whatever is familiar.
Measured on 2026-08-23: antigravity, opencode-go, zai and devin were all at
roughly 0% used while claude carried the entire session. That is paid capacity
expiring unused every cycle, and it repeats.

Two inputs decide a route:

1. **Capability** — what each service is actually good at, from
   `docs/model-routing.md`'s judgment section, made machine-readable below.
2. **Headroom** — live quota from `aiuse`.

The headroom half has a hard constraint: a full `aiuse --json` probe takes
**~46 seconds** (measured). Nothing that slow can sit inside a routing
decision, so this reads a cached snapshot and refreshes it *in the
background* when stale. A routing call is a file read — sub-millisecond — and
never blocks on the network. A stale cache degrades to capability-only
routing rather than hanging.

The operator's standing routing rules are encoded as hard constraints, not
preferences, because they encode consequences a score cannot see:

- free and chronically-unused pools first for bulk work;
- claude/codex for judgment;
- **never** bulk-route to clinepass — it is the Hindsight/hermes lifeline;
- the prepaid tier (opencode-zen, openrouter, deepseek) is retired until an
  explicit operator top-up.

Usage:
    route_agent.py route --kind bulk
    route_agent.py route --kind judgment --json
    route_agent.py refresh          # force a synchronous quota refresh
    route_agent.py show             # cache age and per-service headroom
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CACHE = Path(os.environ.get("AGENT_ROUTING_CACHE") or
             (Path.home() / ".cache" / "agent-routing" / "quota.json"))
TTL_SECONDS = 900          # 15 min: quota moves slowly; a probe costs 46s
STALE_HARD = 6 * 3600      # beyond this, treat headroom as unknown

# Kinds of work. Deliberately few — a taxonomy nobody can apply is worse than
# a coarse one that gets used.
KINDS = ("judgment", "code", "bulk", "research", "mechanical", "github")


@dataclass(frozen=True)
class Service:
    name: str                       # aiuse provider key
    cli: str                        # how it is actually invoked
    # kind -> fitness rank, lower is better. Per-kind rather than one number
    # because fitness is not a single axis: antigravity is the best home for
    # bulk and the wrong home for careful coding, and a flat rank cannot say
    # both.
    good_at: dict[str, int]
    billing: str                    # subscription | free | prepaid
    note: str = ""
    never_bulk: bool = False        # infrastructure lifeline
    retired: bool = False           # excluded until an operator decision
    judgment_tier: bool = False     # trusted for high-stakes calls

    def eligible(self, kind: str) -> bool:
        if self.retired:
            return False
        if kind in ("bulk", "mechanical") and self.never_bulk:
            return False
        if kind == "judgment" and not self.judgment_tier:
            return False
        return kind in self.good_at

    def rank_for(self, kind: str) -> int:
        return self.good_at[kind]


# Profiles from docs/model-routing.md "Which AI for which work", 2026-08-23.
SERVICES: tuple[Service, ...] = (
    Service("claude", "claude (Fable @ xhigh)",
            {"judgment": 1, "code": 10, "research": 30},
            "subscription", "hardest adjudications; separate Fable weekly lane",
            judgment_tier=True),
    Service("codex", "codex (gpt-5.6-sol @ high)",
            {"judgment": 5, "code": 12, "research": 30},
            "subscription", "second coding vendor; own weekly pool",
            judgment_tier=True),
    Service("antigravity", "agy",
            {"bulk": 1, "research": 1, "mechanical": 2, "code": 40},
            "subscription", "big context, summarisation, multimodal; most-wasted pool"),
    Service("opencode-go", "opencode (go tier)",
            {"bulk": 2, "mechanical": 1, "code": 35},
            "free", "kimi/minimax/qwen catalogs"),
    Service("zai", "crush", {"bulk": 3, "mechanical": 3, "code": 38},
            "subscription", "lite plan"),
    Service("devin", "devin", {"bulk": 20, "code": 45}, "subscription",
            "disabled in Orca's roster — dormant by choice"),
    Service("copilot", "copilot", {"github": 1, "code": 20}, "subscription",
            "PR review, repo Q&A"),
    Service("cursor", "cursor", {"code": 25, "mechanical": 10}, "subscription",
            "IDE-centric composer"),
    Service("grok", "grok", {"research": 10, "bulk": 15}, "subscription", ""),
    Service("clinepass", "cline", {"bulk": 90, "code": 90, "mechanical": 90},
            "subscription", "Hindsight + hermes inference lifeline", never_bulk=True),
    Service("opencode-zen", "opencode-ralph-tui-zen", {"code": 50, "bulk": 50},
            "prepaid", "prepaid retired 2026-08-23", retired=True),
    Service("openrouter", "opencode-ralph-tui-openrouter", {"code": 50, "bulk": 50},
            "prepaid", "prepaid retired 2026-08-23", retired=True),
    Service("deepseek", "opencode-ralph-tui-deepseek", {"code": 50, "bulk": 50},
            "prepaid", "prepaid retired 2026-08-23", retired=True),
)
BY_NAME = {s.name: s for s in SERVICES}


# -- quota cache ----------------------------------------------------------

def probe() -> dict[str, Any]:
    """Run aiuse and reduce it to per-provider headroom. Slow (~46s)."""
    out = subprocess.run(["aiuse", "--json"], capture_output=True, text=True, timeout=300)
    text = out.stdout
    start = text.find("{")
    if start < 0:
        raise RuntimeError("aiuse produced no JSON")
    data = json.loads(text[start:])
    headroom: dict[str, Any] = {}
    for acct in data.get("snapshot", {}).get("accounts", []):
        name = acct.get("provider")
        if not name or acct.get("error"):
            continue
        windows = acct.get("windows") or []
        worst = None
        detail = {}
        for w in windows:
            remaining = w.get("remaining_percent")
            if remaining is None:
                continue
            detail[w.get("label") or "?"] = round(float(remaining), 1)
            worst = remaining if worst is None else min(worst, remaining)
        headroom[name] = {
            "remaining": None if worst is None else round(float(worst), 1),
            "windows": detail,
            "billing_kind": acct.get("billing_kind"),
        }
    return {"collected_at": time.time(), "providers": headroom}


def read_cache() -> dict[str, Any] | None:
    try:
        return json.loads(CACHE.read_text())
    except (OSError, ValueError):
        return None


def write_cache(payload: dict[str, Any]) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(CACHE)


def refresh_async() -> None:
    """Kick a background refresh. Never blocks the caller."""
    lock = CACHE.with_suffix(".refreshing")
    # A crashed refresh must not wedge the cache forever.
    if lock.exists() and time.time() - lock.stat().st_mtime < 600:
        return
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    lock.touch()
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "refresh", "--quiet"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )


def headroom(*, allow_refresh: bool = True) -> tuple[dict[str, Any], float | None]:
    """Cached headroom plus its age in seconds (None when absent)."""
    cache = read_cache()
    age = None if not cache else time.time() - float(cache.get("collected_at", 0))
    if allow_refresh and (cache is None or age is None or age > TTL_SECONDS):
        refresh_async()
    if cache is None or (age is not None and age > STALE_HARD):
        return {}, age
    return cache.get("providers", {}), age


# -- routing --------------------------------------------------------------

@dataclass
class Choice:
    service: Service
    remaining: float | None
    score: float
    why: str = ""
    alternatives: list[str] = field(default_factory=list)


def route(kind: str, *, quota: dict[str, Any] | None = None,
          min_headroom: float = 15.0) -> Choice | None:
    """Choose a service for `kind`, preferring idle paid capacity for bulk."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    quota = {} if quota is None else quota

    scored: list[tuple[float, Service, float | None]] = []
    for svc in SERVICES:
        if not svc.eligible(kind):
            continue
        info = quota.get(svc.name) or {}
        remaining = info.get("remaining")
        if remaining is not None and remaining < min_headroom:
            continue                       # too tight to hand work to
        # Lower is better. Rank encodes fitness; headroom pulls idle pools up
        # for bulk work and is only a tie-break for judgment, where capability
        # must dominate cost.
        weight = 1.0 if kind in ("bulk", "mechanical", "research") else 0.25
        pressure = 0.0 if remaining is None else (100.0 - remaining) * weight / 10.0
        scored.append((svc.rank_for(kind) + pressure, svc, remaining))

    if not scored:
        return None
    scored.sort(key=lambda t: (t[0], t[1].name))
    best_score, best, remaining = scored[0]
    why = [f"{kind}: {best.cli}"]
    if remaining is not None:
        why.append(f"{remaining:.0f}% headroom")
    if best.billing == "free":
        why.append("free tier")
    elif kind in ("bulk", "mechanical") and remaining is not None and remaining > 80:
        why.append("idle paid capacity")
    if best.note:
        why.append(best.note)
    return Choice(best, remaining, best_score, "; ".join(why),
                  [s.name for _, s, _ in scored[1:4]])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Route work to a vendor")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("route")
    r.add_argument("--kind", required=True, choices=KINDS)
    r.add_argument("--json", action="store_true")
    r.add_argument("--min-headroom", type=float, default=15.0)
    r.add_argument("--no-refresh", action="store_true")
    f = sub.add_parser("refresh")
    f.add_argument("--quiet", action="store_true")
    sub.add_parser("show")

    args = parser.parse_args(argv)

    if args.command == "refresh":
        try:
            write_cache(probe())
        finally:
            CACHE.with_suffix(".refreshing").unlink(missing_ok=True)
        if not args.quiet:
            print(json.dumps(read_cache(), indent=2)[:600])
        return 0

    if args.command == "show":
        quota, age = headroom()
        print(f"cache: {CACHE}")
        print(f"age: {'absent' if age is None else f'{age:.0f}s'} (ttl {TTL_SECONDS}s)")
        for name, info in sorted(quota.items(), key=lambda kv: (kv[1].get("remaining") is None,
                                                                kv[1].get("remaining") or 0)):
            svc = BY_NAME.get(name)
            flag = "" if not svc else ("  [retired]" if svc.retired else
                                       "  [never-bulk]" if svc.never_bulk else "")
            print(f"  {name:16} {str(info.get('remaining')):>6}% remaining{flag}")
        return 0

    quota, age = headroom(allow_refresh=not args.no_refresh)
    choice = route(args.kind, quota=quota, min_headroom=args.min_headroom)
    if choice is None:
        print(json.dumps({"kind": args.kind, "service": None,
                          "reason": "no eligible service with headroom"}))
        return 1
    if args.json:
        print(json.dumps({
            "kind": args.kind, "service": choice.service.name, "cli": choice.service.cli,
            "remaining_percent": choice.remaining, "why": choice.why,
            "alternatives": choice.alternatives,
            "quota_age_seconds": None if age is None else round(age),
        }, indent=2))
    else:
        print(f"{choice.service.cli}   — {choice.why}")
        if choice.alternatives:
            print(f"  alternatives: {', '.join(choice.alternatives)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
