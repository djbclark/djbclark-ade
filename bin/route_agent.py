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
decision — so this never runs it. `aiuse` already persists every run as JSON
under `~/.cache/aiuse/snapshots/`, keeping `latest.json` current, and a
launchd job (`com.djbclark.aiuse`, StartInterval 900) refreshes it every 15
minutes. Routing reads that file. A routing call is a file read, and a stale
or missing snapshot degrades to capability-only routing rather than hanging.

**Services are discovered, not hardcoded.** The roster changes — agents get
added to Orca, providers appear in aiuse, plans lapse. So the service list is
built at call time from Orca's enabled agent roster and whatever providers the
snapshot reports, with the curated capability profiles below applied as an
*overlay*. An agent nobody has profiled still routes (conservatively) instead
of being invisible.

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
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SNAPSHOT = Path(os.environ.get("AIUSE_SNAPSHOT") or
                (Path.home() / ".cache" / "aiuse" / "snapshots" / "latest.json"))
ORCA_DATA = Path.home() / ("Library/Application Support/orca/profiles/"
                           "local-default/orca-data.json")
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
    # How this service may LEGITIMATELY be reached. Researched 2026-08-24;
    # this is a licensing constraint, not a preference, so it gates hard.
    #   "api"      - we hold credentials whose terms permit programmatic use,
    #                so Hermes may call it directly as a provider.
    #   "cli-only" - the subscription covers use through the vendor's OWN
    #                client. Shelling out to that CLI is fine; wiring the
    #                endpoint into Hermes as a generic provider is not.
    #   "forbidden"- third-party clients explicitly violate the terms.
    access: str = "cli-only"
    # True when the only way to reach this is as a Hermes provider — there is
    # no command Claude Code can invoke. Such a service belongs in the Hermes
    # chain but must never win a Claude-side routing decision.
    hermes_only: bool = False

    def eligible(self, kind: str) -> bool:
        if self.retired or self.hermes_only:
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
            judgment_tier=True, access="cli-only"),
    Service("codex", "codex (gpt-5.6-sol @ high)",
            {"judgment": 5, "code": 12, "research": 30},
            "subscription", "second coding vendor; own weekly pool",
            judgment_tier=True,
            # Tolerated rather than committed: OpenAI neither permits nor
            # prohibits subscription use inside a non-OpenAI tool, and
            # tolerated is fine. The real reason to keep it out of Hermes's
            # chain is capability, not licensing — these are among the
            # strongest coding models available here, so the weekly pool is
            # worth reserving for coding judgment rather than spending on
            # background agent turns.
            access="cli-only"),
    Service("antigravity", "agy",
            {"bulk": 1, "research": 1, "mechanical": 2, "code": 40},
            "subscription",
            # Google AI Pro does NOT include API access — subscriptions are chat
            # -interface only, and a Gemini API key bills separately. Reaching
            # it via the agy CLI spends the subscription; wiring Hermes to a
            # GEMINI_API_KEY would spend real money.
            "big context, summarisation, multimodal; most-wasted pool",
            access="cli-only"),
    Service("opencode-zen-free", "opencode-zen-free (Hermes provider)",
            {"bulk": 5, "mechanical": 5, "code": 45}, "free",
            "free Zen tier; legitimate for direct API use by Hermes",
            access="api", hermes_only=True),
    Service("opencode-go", "opencode (go tier)",
            {"bulk": 2, "mechanical": 1, "code": 35},
            "free", "kimi/minimax/qwen catalogs"),
    Service("zai", "crush", {"bulk": 3, "mechanical": 3, "code": 38},
            "subscription", "lite plan"),
    Service("devin", "devin", {"bulk": 20, "code": 45}, "subscription",
            "disabled in Orca's roster — dormant by choice"),
    Service("copilot", "copilot", {"github": 1, "code": 20}, "subscription",
            # GitHub: the Copilot endpoint is for officially supported clients
            # only. Using it as a generic model provider violates the ToS and
            # risks account suspension. CLI only, never a Hermes provider.
            "PR review, repo Q&A (official client only)", access="forbidden"),
    Service("cursor", "cursor", {"code": 25, "mechanical": 10}, "subscription",
            "IDE-centric composer"),
    Service("grok", "grok", {"research": 10, "bulk": 15}, "subscription", ""),
    Service("clinepass", "cline", {"bulk": 40, "code": 40, "mechanical": 40},
            "subscription",
            # An API-key bundle we hold, so Hermes may call it directly. The
            # old blanket never_bulk rule was retired 2026-08-24 in favour of
            # the measured burn-rate alert (agent_stats.py burn).
            "Hermes-usable API pool; watch the burn alert", access="api"),
    Service("opencode-zen", "opencode-ralph-tui-zen", {"code": 50, "bulk": 50},
            "prepaid", "prepaid retired 2026-08-23", retired=True),
    Service("openrouter", "opencode-ralph-tui-openrouter", {"code": 50, "bulk": 50},
            "prepaid", "prepaid retired 2026-08-23", retired=True),
    Service("deepseek", "opencode-ralph-tui-deepseek", {"code": 50, "bulk": 50},
            "prepaid", "prepaid retired 2026-08-23", retired=True),
)
BY_NAME = {s.name: s for s in SERVICES}


# -- quota snapshot + service discovery ----------------------------------

def load_snapshot() -> tuple[dict[str, Any], float | None]:
    """Read aiuse's own latest snapshot. Never probes; never blocks."""
    path = SNAPSHOT
    if not path.exists():
        candidates = sorted(path.parent.glob("20*.json"), reverse=True) if path.parent.is_dir() else []
        if not candidates:
            return {}, None
        path = candidates[0]
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}, None

    collected = data.get("collected_at") or data.get("started_at") or ""
    age = None
    try:
        stamp = datetime.fromisoformat(str(collected).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - stamp).total_seconds()
    except ValueError:
        age = time.time() - path.stat().st_mtime

    snap = data.get("snapshot", data)
    providers: dict[str, Any] = {}
    for acct in snap.get("accounts", []) or []:
        name = acct.get("provider")
        if not name or acct.get("error"):
            continue
        worst, detail = None, {}
        for w in acct.get("windows") or []:
            remaining = w.get("remaining_percent")
            if remaining is None:
                continue
            detail[w.get("label") or "?"] = round(float(remaining), 1)
            worst = remaining if worst is None else min(worst, remaining)
        prior = providers.get(name, {}).get("remaining")
        if prior is not None and worst is not None:
            worst = min(worst, prior)      # several accounts: the tightest wins
        providers[name] = {"remaining": None if worst is None else round(float(worst), 1),
                           "windows": detail, "billing_kind": acct.get("billing_kind")}
    if age is not None and age > STALE_HARD:
        return {}, age
    return providers, age


def orca_roster() -> set[str]:
    """Agents Orca can actually dispatch to right now, minus disabled ones."""
    try:
        data = json.loads(ORCA_DATA.read_text())
    except (OSError, ValueError):
        return set()
    settings = data.get("settings", {}) or {}
    agents = set((settings.get("agentDefaultArgs") or {}).keys())
    return agents - set(settings.get("disabledTuiAgents") or [])


# Curated profiles overlay discovery; anything discovered without one gets
# DEFAULT_PROFILE so a newly-added agent is routable rather than invisible.
DEFAULT_PROFILE = {"bulk": 60, "mechanical": 60}

# Orca's roster names the TUI; aiuse names the account behind it. Without this
# map, discovery would surface `cline` as a brand-new service and hand it bulk
# work — silently defeating the never-bulk rule that protects clinepass, which
# is Hindsight's and hermes's inference lifeline. Any alias inherits the
# curated service's constraints rather than becoming a second entry.
ALIASES = {
    "cline": "clinepass",
    "crush": "zai",
    "agy": "antigravity",
    "claude-agent-teams": "claude",
    "openclaude": "claude",
    "opencode": "opencode-go",
    "kimi": "opencode-go",
}


def discover(quota: dict[str, Any] | None = None) -> list[Service]:
    """Build the live service list: curated profiles + whatever exists now."""
    quota = quota or {}
    services = {s.name: s for s in SERVICES}
    known_clis = {s.cli.split()[0] for s in SERVICES} | set(services)

    for name in sorted(set(quota) | orca_roster()):
        canonical = ALIASES.get(name, name)
        if canonical in services:
            continue                                # same account, already profiled
        if name in ("codexbar-query-errors",):      # diagnostics, not a service
            continue
        services[name] = Service(
            name=name, cli=name, good_at=dict(DEFAULT_PROFILE),
            billing=(quota.get(name, {}).get("billing_kind") or "unknown"),
            note="discovered; no curated profile — bulk/mechanical only",
        )
    return list(services.values())


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
    for svc in discover(quota):
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
        if remaining is None:
            # Unmeasured capacity is a worse bet than measured headroom: we
            # cannot tell whether it is idle or exhausted. Penalise it so a
            # peer with known room wins, while still leaving it reachable as
            # a last resort rather than dropping it from the roster.
            pressure = 5.0
        else:
            pressure = (100.0 - remaining) * weight / 10.0
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


# Concrete models per Hermes-usable provider, cheapest-capable first within
# each. Only providers with access == "api" may appear: everything else is
# reachable solely through its own vendor CLI.
HERMES_MODELS: dict[str, list[str]] = {
    "opencode-zen-free": ["deepseek-v4-flash-free", "hy3-free",
                          "nemotron-3.5-lightning-free"],
    "clinepass": ["cline-pass/deepseek-v4-flash", "cline-pass/minimax-m3"],
}
# Hermes names the provider differently from aiuse for the paid pool.
HERMES_PROVIDER_NAME = {"clinepass": "cline"}


def hermes_chain(quota: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Build Hermes's provider chain: free-first, then paid, headroom-ordered.

    Hermes's own `fallback_providers` only reacts to *failure* — it has no
    notion of cost or headroom, and cannot see pools Hermes has no provider
    for. This generates it from the same capability + headroom model the
    router uses, restricted to what we may legitimately call as an API.
    """
    quota = quota or {}
    eligible = [s for s in SERVICES if s.access == "api" and not s.retired]
    # Free before paid; within a tier, more headroom first. A pool we cannot
    # measure sorts last rather than being dropped.
    def key(s: Service) -> tuple[int, float]:
        rem = (quota.get(s.name) or {}).get("remaining")
        return (0 if s.billing == "free" else 1,
                -(rem if rem is not None else -1.0))
    chain = []
    for svc in sorted(eligible, key=key):
        for model in HERMES_MODELS.get(svc.name, []):
            chain.append({"provider": HERMES_PROVIDER_NAME.get(svc.name, svc.name),
                          "model": model,
                          "_pool": svc.name,
                          "_billing": svc.billing})
    return chain


def apply_hermes_chain(chain: list[dict[str, str]]) -> str:
    """Write the chain into Hermes's config.

    `hermes fallback add` is an interactive picker, so a generated chain has
    to be written to config.yaml directly. The primary is the chain head; the
    remainder becomes fallback_providers.
    """
    import re
    cfg = Path.home()/".hermes/config.yaml"
    text = cfg.read_text()
    backup = cfg.with_suffix(f".yaml.bak-generated-{datetime.now():%Y%m%d%H%M%S}")
    backup.write_text(text)

    head, *rest = chain
    text = re.sub(r"(?m)^model:\n(?:  .*\n)+",
                  "model:\n"
                  "  # GENERATED by bin/route_agent.py hermes-chain --apply.\n"
                  "  # Edit the model table there, not here.\n"
                  f"  provider: {head['provider']}\n"
                  f"  default: {head['model']}\n"
                  "  allow_paid_opencode_zen: false\n", text, count=1)
    body = "".join(f"  - provider: {e['provider']}\n    model: {e['model']}\n"
                   for e in rest)
    text = re.sub(r"(?m)^fallback_providers:\n(?:(?:  #.*|  - .*|    .*)\n)*",
                  "fallback_providers:\n"
                  "  # GENERATED — free tiers first, paid pools last. Only\n"
                  "  # providers whose terms permit direct API use appear here;\n"
                  "  # everything else is reachable only via its vendor CLI.\n"
                  + body, text, count=1)
    cfg.write_text(text)
    return str(backup)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Route work to a vendor")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("route")
    r.add_argument("--kind", required=True, choices=KINDS)
    r.add_argument("--json", action="store_true")
    r.add_argument("--min-headroom", type=float, default=15.0)
    sub.add_parser("show", help="snapshot age and per-service headroom")
    sub.add_parser("services", help="every service discovered right now")
    hc = sub.add_parser("hermes-chain", help="generate Hermes's provider chain")
    hc.add_argument("--apply", action="store_true", help="write it to config.yaml")

    args = parser.parse_args(argv)
    quota, age = load_snapshot()

    if args.command == "show":
        print(f"snapshot: {SNAPSHOT}")
        print(f"age: {'absent' if age is None else f'{age / 60:.1f} min'}"
              f"  (refreshed by launchd com.djbclark.aiuse every 15 min)")
        for name, info in sorted(quota.items(),
                                 key=lambda kv: (kv[1].get("remaining") is None,
                                                 kv[1].get("remaining") or 0)):
            svc = BY_NAME.get(name)
            flag = "" if not svc else ("  [retired]" if svc.retired else
                                       "  [never-bulk]" if svc.never_bulk else "")
            print(f"  {name:16} {str(info.get('remaining')):>6}% remaining{flag}")
        return 0

    if args.command == "hermes-chain":
        chain = hermes_chain(quota)
        for i, e in enumerate(chain):
            role = "primary" if i == 0 else f"fallback {i}"
            rem = (quota.get(e["_pool"]) or {}).get("remaining")
            print(f"  {role:11} {e['provider']}/{e['model']:32} "
                  f"{e['_billing']:12} {'' if rem is None else f'{rem:.0f}% left'}")
        excluded = [s for s in SERVICES if s.access != "api" and not s.retired]
        print(f"\n  excluded ({len(excluded)}): "
              + ", ".join(f"{s.name}[{s.access}]" for s in excluded))
        if args.apply:
            print("\n  backup:", apply_hermes_chain(chain))
        return 0

    if args.command == "services":
        found = discover(quota)
        curated = {s.name for s in SERVICES}
        print(f"{len(found)} services discovered "
              f"({len(curated & {s.name for s in found})} curated, "
              f"{len(found) - len(curated & {s.name for s in found})} auto)")
        for svc in sorted(found, key=lambda s: s.name):
            kinds = ",".join(sorted(svc.good_at))
            mark = " " if svc.name in curated else "*"
            print(f" {mark}{svc.name:22} {kinds[:44]:44} {svc.billing}")
        print(" * = discovered without a curated profile")
        return 0

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
            "snapshot_age_seconds": None if age is None else round(age),
        }, indent=2))
    else:
        print(f"{choice.service.cli}   — {choice.why}")
        if choice.alternatives:
            print(f"  alternatives: {', '.join(choice.alternatives)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
