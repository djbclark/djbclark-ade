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

**Services are discovered, not hardcoded.** The roster changes — agents gain
an ACP mode, providers appear in aiuse, plans lapse. So the service list is
built at call time from what this machine can actually dispatch, in this order:

1. `acp-run --list` — the agent table every launcher uses; only `ok` rows
   (binary present) count.
2. the non-ACP headless TUIs (`NON_ACP_HEADLESS`, from model-routing's
   per-CLI headless table; since 2026-10-08 only muse, zcode now rides
   `acp-run` through `zcode-acp-server`), each only if its binary is on PATH.
3. Orca's enabled agent roster — **off by default** (`ROUTE_AGENT_INCLUDE_ORCA=1`
   turns it on), and even then intersected with installed binaries. Orca's
   roster is its stock TUI list: on 2026-10-08, 12 of its 28 enabled names
   were not installed here at all, so it is no longer an authority.
4. whatever providers the aiuse snapshot reports.

Every name passes through `ALIASES` before it becomes a service, and the
curated capability profiles below are applied as an *overlay*. An agent nobody
has profiled still routes (conservatively) instead of being invisible.

The operator's standing routing rules are encoded as hard constraints, not
preferences, because they encode consequences a score cannot see:

- free and chronically-unused pools first for bulk work;
- claude/codex for judgment: Claude Fable 5.1 and codex's top frontier model
  (gpt-6-astra) are to be used FULLY for serious-effort work, so everyday
  work goes to the other pools (operator 2026-10-15);
- Fable is a sublimit (at most 50%) of the SAME Claude weekly window, not a
  separate allowance: a Fable run bills the shared window too;
- grok and copilot are reserves with a hard floor (`reserve_floor`): GrokBot
  and GitHub-side Copilot review run on them; never deplete them;
- hermes is never a delegation target; omp only with the operator's explicit
  per-run approval (`ACP_OPERATOR_APPROVED=omp`); neither is ever discovered
  as a routable service here;
- **never** bulk-route to clinepass — it is the Hindsight/hermes lifeline;
- the prepaid tier (opencode-zen, openrouter, deepseek) is retired until an
  explicit operator top-up.

Every route comes with a `--model [--effort]` suggestion and the
`acp-dispatch` line to run; the context window is the caller's choice (the
agent's default unless the slice reads a whole corpus or a long log).

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
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SNAPSHOT = Path(os.environ.get("AIUSE_SNAPSHOT") or
                (Path.home() / ".cache" / "aiuse" / "snapshots" / "latest.json"))
ORCA_DATA = Path.home() / ("Library/Application Support/orca/profiles/"
                           "local-default/orca-data.json")
# The ACP client every launcher uses; its agent table is the primary source of
# dispatchable agents. The sibling checkout copy wins over PATH so the table
# and this script move together; ACP_RUN overrides both.
ACP_RUN = (os.environ.get("ACP_RUN")
           or next((str(c) for c in (Path(__file__).resolve().parent.parent
                                      / "tools" / "acp-run" / "acp-run",)
                    if c.is_file()), None)
           or shutil.which("acp-run") or "acp-run")
# TUIs with a verified headless form but no usable ACP route, so acp-run does
# not list them: skills/model-routing/SKILL.md, "Per-CLI headless forms (no ACP
# mode, or fallback)". Each counts only while its binary is on PATH.
NON_ACP_HEADLESS = frozenset({"muse"})  # zcode joined acp-run 2026-10-08 (zcode-acp-server)
STALE_HARD = 6 * 3600      # beyond this, treat headroom as unknown
STALE_SOFT = 25 * 60       # aiuse's own `fresh` threshold; older = re-collect before a wave

# Kinds of work. Deliberately few — a taxonomy nobody can apply is worse than
# a coarse one that gets used.
# burn_first services (use-it-or-lose-it pools) win a tie-sized margin while
# they hold at least this much headroom.
BURN_FIRST_MIN = 40.0
BURN_FIRST_BONUS = 4.0
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
    # True when the only way to reach this is as a Hermes provider, with no
    # command Claude Code can invoke. Nothing currently sets it: opencode-zen
    # (free and paid) is reachable from Claude through the `opencode` TUI, so
    # the earlier assumption that it was Hermes-only was wrong. Kept because
    # a genuinely Hermes-only provider would otherwise silently win Claude
    # routing decisions it cannot serve.
    hermes_only: bool = False
    # A pool whose window resets and its allowance is lost: while it has real
    # headroom it outranks pools that carry the same kind of work but keep
    # their balance. `route` applies BURN_FIRST_BONUS above BURN_FIRST_MIN.
    burn_first: bool = False
    # Set when this service is ONE of several independent model-family pools
    # that a single aiuse provider reports: (aiuse provider, window
    # `pool_family`). Windows of that family are measured for this service
    # alone; the provider's other windows stay with the provider's own
    # service. Add a row with `pool=` to give any provider's second pool its
    # own routing entry (copilot, cursor, ...) once aiuse reports it. Do NOT
    # use it for a model sublimit of a shared pool (Claude's `fable`): that
    # one is bounded by the parent windows and must stay with them.
    pool: tuple[str, str] | None = None
    # Most slices one bigteam wave should put on this service at once. Pools
    # with a burst limit or a dependant get a low cap so `plan` spreads a wave
    # over several pools instead of drowning the best-ranked one.
    max_parallel: int = 4
    # The acp-run agent name when it differs from the aiuse provider id
    # (antigravity -> agy, zai -> zcode, opencode-go -> opencode, ...).
    agent: str = ""
    # kind -> "<model> [--effort LEVEL]" to pass to acp-run/acp-dispatch.
    # Ids as that agent's `--info` lists them (tools/acp-run/README.md).
    models: dict[str, str] = field(default_factory=dict)
    # A reserve pool's hard floor: never route to it with less than this much
    # of its binding window left, whatever `min_headroom` says (grok: GrokBot
    # runs on it; copilot: GitHub-side Copilot review draws on it).
    reserve_floor: float = 0.0

    @property
    def acp_agent(self) -> str:
        return self.agent or self.name

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


# Profiles from docs/model-routing.md "Which AI for which work", rewritten
# 2026-10-15 to the operator's routing policy: Claude Fable 5.1 and codex's
# top frontier model (gpt-6-astra today) carry the serious-effort work and
# should be used fully, so everyday work goes to the OTHER pools; grok and
# copilot are reserves with a hard floor (GrokBot and GitHub-side Copilot
# review run on them); hermes is never a target; omp is operator-gated.
# `models` is the acp-run `--model [--effort L]` suggestion per kind; `agent`
# is the acp-run agent name when it differs from the aiuse provider id.
SERVICES: tuple[Service, ...] = (
    Service("claude", "claude (Fable 5.1 @ xhigh for judgment; Sonnet for the rest)",
            {"judgment": 1, "code": 24, "research": 30},
            "subscription",
            "orchestration pool; Fable is a sublimit of the SAME weekly window "
            "(at most 50% of it), not a separate allowance",
            judgment_tier=True, access="cli-only",
            models={"judgment": "fable --effort xhigh",
                    "code": "sonnet --effort medium",
                    "research": "sonnet --effort medium"}),
    Service("codex", "codex (gpt-6-astra @ xhigh)",
            {"judgment": 2, "code": 22, "research": 28},
            "subscription",
            "top frontier coding model: hard slices and second opinions, not everyday work",
            judgment_tier=True,
            # Tolerated rather than committed: OpenAI neither permits nor
            # prohibits subscription use inside a non-OpenAI tool, and
            # tolerated is fine. The real reason to keep it out of Hermes's
            # chain is capability, not licensing — these are among the
            # strongest coding models available here, so the weekly pool is
            # worth reserving for coding judgment rather than spending on
            # background agent turns.
            access="cli-only",
            models={"judgment": "gpt-6-astra --effort xhigh",
                    "code": "gpt-6-astra --effort high",
                    "research": "gpt-6-astra --effort medium"}),
    # agy's second pool: Claude Opus/Sonnet 5.5 and GPT via the same Google AI
    # Pro subscription, a separate 5h/weekly window from Gemini. Operator
    # 2026-10-10: it has a lot of headroom, so use it. Real Claude-class
    # coding and review capacity that is otherwise wasted at each reset.
    # Reach it ONLY through `acp-run agy --model claude-opus-5-5 --effort high`
    # (or claude-sonnet-5-5), never `agy -p`; see model-routing's agy rules.
    # Over ACP these ids exist only because acp-run sends clientInfo.name
    # "zed": agy_acp_server 1.3.0 gives non-Gemini models only to zed, xcode
    # and JetBrains.* clients (supports_third_party_models(), deliberate, so a
    # client-name workaround a later .par may close; antigravity-cli#1168).
    # acp-dispatch checks --model against `acp-run agy --info` before running.
    Service("antigravity-claude",
            "agy (acp-run agy --model claude-opus-5-5 --effort high | claude-sonnet-5-5)",
            {"code": 11, "research": 3, "mechanical": 6},
            "subscription",
            "Claude/GPT pool on the Google AI Pro plan; use-it-or-lose-it, "
            "ACP client only",
            burn_first=True, pool=("antigravity", "claude_gpt"),
            max_parallel=3, access="cli-only", agent="agy",
            models={"code": "claude-opus-5-5 --effort high",
                    "research": "claude-sonnet-5-5 --effort high",
                    "mechanical": "claude-sonnet-5-5 --effort low"}),
    Service("antigravity", "agy (gemini)",
            {"bulk": 1, "research": 1, "mechanical": 2, "code": 40},
            "subscription",
            # Google AI Pro does NOT include API access — subscriptions are chat
            # -interface only, and a Gemini API key bills separately. Reaching
            # it via the agy CLI spends the subscription; wiring Hermes to a
            # GEMINI_API_KEY would spend real money.
            "big context, summarisation, multimodal; most-wasted pool",
            max_parallel=2, access="cli-only", agent="agy",
            models={"bulk": "gemini-3.8-flash --effort medium",
                    "research": "gemini-3.8-flash --effort high",
                    "mechanical": "gemini-3.8-flash --effort low",
                    "code": "gemini-3.8-flash --effort high"}),
    # opencode-zen-free is NOT a separate provider — it is the free subset of
    # opencode-zen's models. Kept as its own row because the free and paid
    # halves have different billing and different eligibility, which is the
    # distinction that actually drives routing. Claude reaches both through
    # the `opencode` TUI; Hermes reaches the free half as an API provider.
    Service("opencode-zen-free", "opencode (zen free models)",
            {"bulk": 5, "mechanical": 5, "code": 45}, "free",
            "free half of opencode-zen; usable by Claude via the opencode TUI "
            "and by Hermes as a direct API provider",
            access="api", agent="opencode"),
    Service("opencode-go", "opencode (go tier)",
            {"bulk": 2, "mechanical": 1, "code": 18},
            "free", "kimi/minimax/qwen/glm catalogs", agent="opencode",
            models={"bulk": "opencode-go/kimi-k3 --effort low",
                    "mechanical": "opencode-go/glm-5.3 --effort low",
                    "code": "opencode-go/glm-5.3 --effort high"}),
    Service("zai", "zcode (GLM-5.3)", {"bulk": 3, "mechanical": 3, "code": 16, "research": 12},
            "subscription",
            # zcode (Z.ai's own TUI, GLM-5.3 / GLM-5.3-Flash x low/high/max) is
            # the zai Coding Plan's TUI; acp-run zcode drives it.
            "coding plan; an everyday code and bulk pool", agent="zcode",
            models={"code": "GLM-5.3 --effort high",
                    "research": "GLM-5.3 --effort high",
                    "bulk": "GLM-5.3-Flash --effort low",
                    "mechanical": "GLM-5.3-Flash --effort low"}),
    # Alibaba's coding plan through the qwen TUI. aiuse keeps `alibaba` under
    # [disabled_services] (operator 2026-10-08), so `plan` skips it until the
    # operator re-enables it there; the row exists so discovery does not
    # surface the bare `qwen` agent as an unprofiled, un-disable-able service.
    Service("alibaba", "qwen (Alibaba coding plan)",
            {"bulk": 30, "mechanical": 30, "code": 30, "research": 30},
            "subscription", "disabled in aiuse until the operator re-enables it",
            agent="qwen",
            models={"code": "qwen3.8-max --effort medium",
                    "research": "qwen3.8-max --effort medium",
                    "bulk": "qwen3.8-max --effort low",
                    "mechanical": "qwen3.8-max --effort low"}),
    # MIT SIPB-hosted models through the crush fork (ACP). Free, no quota
    # window in aiuse, 30B-class: light bulk and mechanical slices only.
    Service("crush", "crush (SIPB models, free)", {"bulk": 8, "mechanical": 8},
            "free", "MIT SIPB-hosted 30B-class models; light slices only",
            models={"bulk": "sipb-llms:qwen3.6:35b-a3b-q4_K_M",
                    "mechanical": "sipb-llms:qwen3.6:35b-a3b-q4_K_M"}),
    Service("devin", "devin", {"bulk": 20, "code": 45}, "subscription",
            "disabled in Orca's roster — dormant by choice"),
    # RESERVE (operator 2026-10-15: "never deplete the grok and copilot
    # pools"): GitHub-side Copilot code review of commits draws on this
    # allowance. Hard floor, one slice at a time, only for GitHub-shaped work.
    Service("copilot", "copilot", {"github": 1, "code": 30}, "subscription",
            # GitHub: the Copilot endpoint is for officially supported clients
            # only. Using it as a generic model provider violates the ToS and
            # risks account suspension. CLI only, never a Hermes provider.
            "RESERVE: PR review, repo Q&A (official client only)",
            access="forbidden", reserve_floor=60.0, max_parallel=1,
            models={"github": "claude-sonnet-5.5 --effort medium",
                    "code": "claude-sonnet-5.5 --effort medium"}),
    # Cursor reports two model sublimits of one monthly total: the Auto pool
    # (Cursor's own models) and the third-party pool. They drain at very
    # different rates (2026-10-15: auto 75% left, third-party 11% left), so
    # the Auto pool is its own routing entry; the provider row keeps the rest.
    Service("cursor-auto", "cursor (Auto pool)",
            {"code": 14, "mechanical": 4, "bulk": 6, "research": 12}, "subscription",
            "Cursor Auto/Composer pool; monthly, use-it-or-lose-it",
            burn_first=True, pool=("cursor", "auto"), max_parallel=2, agent="cursor",
            models={"code": "default", "mechanical": "default", "bulk": "default",
                    "research": "default"}),
    Service("cursor", "cursor (third-party models)", {"code": 20, "mechanical": 10},
            "subscription", "Cursor third-party pool", agent="cursor",
            models={"code": "claude-sonnet-5-5 --effort medium",
                    "mechanical": "claude-haiku-5-5 --effort low"}),
    # RESERVE: GrokBot (the cloud Chief of Staff) runs on the SuperGrok pool.
    # Hard floor, one slice at a time, only when a Grok model is the point.
    Service("grok", "grok", {"research": 15, "bulk": 30}, "subscription",
            "RESERVE: GrokBot runs on it; realtime X/web angle only",
            max_parallel=1, reserve_floor=60.0,
            models={"research": "grok-4.7 --effort high",
                    "bulk": "grok-4.7 --effort low"}),
    Service("clinepass", "cline", {"bulk": 40, "code": 40, "mechanical": 40},
            "subscription",
            # An API-key bundle we hold, so Hermes may call it directly. The
            # old blanket never_bulk rule was retired 2026-08-24 in favour of
            # the measured burn-rate alert (agent_stats.py burn). aiuse's
            # [disabled_services] keeps it out of `plan` since 2026-10-08.
            "Hermes-usable API pool; watch the burn alert", access="api", agent="cline",
            models={"bulk": "cline-pass/deepseek-v4.1-flash",
                    "mechanical": "cline-pass/deepseek-v4.1-flash",
                    "code": "cline-pass/glm-5.3"}),
    # The paid half of the same provider. Retired with the prepaid tier, not
    # because the provider is unusable — restoring it is a top-up decision.
    Service("opencode-zen", "opencode (zen paid models)", {"code": 50, "bulk": 50},
            "prepaid", "paid half of opencode-zen; prepaid tier retired 2026-08-23",
            retired=True, agent="opencode"),
    Service("openrouter", "opencode-ralph-tui-openrouter", {"code": 50, "bulk": 50},
            "prepaid", "prepaid retired 2026-08-23", retired=True),
    Service("deepseek", "opencode-ralph-tui-deepseek", {"code": 50, "bulk": 50},
            "prepaid", "prepaid retired 2026-08-23", retired=True),
)
BY_NAME = {s.name: s for s in SERVICES}


# -- quota snapshot + service discovery ----------------------------------

def pool_service(provider: str, family: str | None) -> str:
    """Routing service that an aiuse window of `family` belongs to."""
    for svc in SERVICES:
        if svc.pool == (provider, family):
            return svc.name
    return provider


AIUSE_CONFIG = Path(os.environ.get("AIUSE_CONFIG", "~/.config/aiuse/config.toml")).expanduser()


def operator_disabled(path: Path | None = None) -> set[str]:
    """Services the operator switched off in aiuse's `[disabled_services]`.

    Routing must honour them (2026-10-12: `plan` kept offering copilot and
    cursor, both disabled there, one reserved for grokbot). Keys are aiuse's
    canonical provider ids, the same names `Service.name` uses.
    """
    import tomllib

    try:
        with (path or AIUSE_CONFIG).open("rb") as fh:
            return set((tomllib.load(fh).get("disabled_services") or {}).keys())
    except (OSError, tomllib.TOMLDecodeError):
        return set()


def load_snapshot() -> tuple[dict[str, Any], float | None]:
    """Read aiuse's own latest snapshot. Never probes; never blocks."""
    path = Path(os.environ.get("AIUSE_SNAPSHOT") or SNAPSHOT)
    if not path.exists():
        if os.environ.get("AIUSE_SNAPSHOT"):
            return {}, None
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
        stamp = datetime.fromisoformat(str(collected))
        age = (datetime.now(UTC) - stamp).total_seconds()
    except (ValueError, TypeError):  # TypeError: a naive timestamp
        age = time.time() - path.stat().st_mtime

    snap = data.get("snapshot", data)
    providers: dict[str, Any] = {}
    for acct in snap.get("accounts", []) or []:
        name = acct.get("provider")
        if not name or acct.get("error"):
            continue

        # Account freshness: use account's age_seconds or collected_at
        acct_age = None
        if acct.get("age_seconds") is not None:
            try:
                acct_age = float(acct["age_seconds"])
            except (ValueError, TypeError):
                pass
        if acct_age is None and acct.get("collected_at"):
            try:
                acct_stamp = datetime.fromisoformat(str(acct["collected_at"]))
                acct_age = (datetime.now(UTC) - acct_stamp).total_seconds()
            except (ValueError, TypeError):
                pass
        if acct_age is None:
            acct_age = age
        is_old = acct_age is not None and acct_age > STALE_SOFT

        # One account can hold several independent model-family pools; agy's
        # Claude/GPT pool is its own service, so its windows must not drag
        # the Gemini pool's headroom down (or the reverse).
        per_key: dict[str, tuple[Any, dict[str, float | None], dict[str, float | None]]] = {}
        for w in acct.get("windows") or []:
            family = w.get("pool_family")
            key = pool_service(name, family)
            worst, detail, sublimits = per_key.get(key, (None, {}, {}))
            label = w.get("label") or "?"

            state = w.get("state")
            headroom = w.get("headroom_percent")
            if state == "exhausted" or (headroom is not None and float(headroom) == 0):
                remaining = 0.0
            elif is_old:
                remaining = None
            else:
                # headroom_percent is the least applicable headroom (a model
                # sublimit's ceiling included); remaining_percent is the
                # window's own share. Prefer the ceiling-aware one.
                remaining = headroom if headroom is not None else w.get("remaining_percent")

            rem_val = None if remaining is None else round(float(remaining), 1)
            detail[label] = rem_val
            is_cap = (w.get("quota_scope") == "model_sublimit"
                      and w.get("max_share_of_parent_percent") is not None)
            if is_cap and key == name:
                # A model cap inside the shared pool (Claude's `fable`, at most
                # 50% of the weekly): it bounds that model only and must not
                # drag the whole account down. Kept for the model suggestion.
                # Cursor's auto/third-party rows are breakdowns without a cap
                # and stay binding for the service that owns them.
                sublimits[family or label] = rem_val
            elif rem_val is not None:
                worst = rem_val if worst is None else min(worst, rem_val)
            per_key[key] = (worst, detail, sublimits)

        if not per_key:
            per_key[name] = (None, {}, {})
        for key, (worst, detail, sublimits) in per_key.items():
            prior = providers.get(key, {}).get("remaining")
            if prior is not None and worst is not None:
                worst = min(worst, prior)      # several accounts: the tightest wins
            providers[key] = {"remaining": None if worst is None else round(float(worst), 1),
                              "windows": detail, "sublimits": sublimits,
                              "billing_kind": acct.get("billing_kind")}
    if age is not None and age > STALE_HARD:
        return {}, age
    return providers, age


def acp_list_output() -> str:
    """`acp-run --list`, or "" when it cannot run. Never raises; never hangs."""
    try:
        proc = subprocess.run([ACP_RUN, "--list"], check=False, capture_output=True,
                              text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def acp_agents() -> set[str]:
    """Agents acp-run can launch right now: the `ok <name> <cmd>` rows only.

    `-- <name>` rows are in the table but their binary is absent."""
    found = set()
    for line in acp_list_output().splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "ok":
            found.add(parts[1])
    return found


def headless_agents() -> set[str]:
    """Non-ACP TUIs with a headless recipe, only while installed."""
    return {name for name in NON_ACP_HEADLESS if shutil.which(name)}


def orca_roster() -> set[str]:
    """Orca's enabled TUI roster. Its stock list, not what is installed here —
    so `installed_roster` only consults it when asked, and intersects it with
    binaries on PATH."""
    try:
        data = json.loads(ORCA_DATA.read_text())
    except (OSError, ValueError):
        return set()
    settings = data.get("settings", {}) or {}
    agents = set((settings.get("agentDefaultArgs") or {}).keys())
    return agents - set(settings.get("disabledTuiAgents") or [])


def include_orca() -> bool:
    return os.environ.get("ROUTE_AGENT_INCLUDE_ORCA", "").lower() in ("1", "true", "yes")


def installed_roster() -> set[str]:
    """Every agent this machine can dispatch to, in the module docstring's order."""
    names = acp_agents() | headless_agents()
    if include_orca():
        names |= {name for name in orca_roster() if shutil.which(name)}
    return names


# Curated profiles overlay discovery; anything discovered without one gets
# DEFAULT_PROFILE so a newly-added agent is routable rather than invisible.
DEFAULT_PROFILE = {"bulk": 60, "mechanical": 60}
# Never a routable service, whatever aiuse or acp-run lists (operator 2026-10-15):
# hermes is the operator's own assistant; omp needs a per-run operator approval
# (acp-run/acp-dispatch gate both behind ACP_OPERATOR_APPROVED). Discovery would
# otherwise hand them DEFAULT_PROFILE bulk work: omp sat in `aiuse --available`
# with 100% headroom on 2026-10-15.
NEVER_ROUTE = frozenset({"hermes"})
OPERATOR_GATED = frozenset({"omp"})
# Below this much of the Fable sublimit, judgment on claude falls back to Opus.
FABLE_MIN_LEFT = 10.0

# Discovery names the TUI; aiuse names the account behind it. Without this
# map, discovery would surface `cline` as a brand-new service and hand it bulk
# work — silently defeating the never-bulk rule that protects clinepass, which
# is Hindsight's and hermes's inference lifeline. Any alias inherits the
# curated service's constraints rather than becoming a second entry.
ALIASES = {
    "cline": "clinepass",
    "agy": "antigravity",
    "claude-agent-teams": "claude",
    "openclaude": "claude",
    "opencode": "opencode-go",
    "kimi": "opencode-go",
    "zcode": "zai",
    "qwen": "alibaba",
}


def discover(quota: dict[str, Any] | None = None) -> list[Service]:
    """Build the live service list: curated profiles + whatever exists now."""
    quota = quota or {}
    services = {s.name: s for s in SERVICES}
    known_clis = {s.cli.split()[0] for s in SERVICES} | set(services)

    for name in sorted(set(quota) | installed_roster()):
        canonical = ALIASES.get(name, name)
        if canonical in services or canonical in known_clis:
            continue                                # same account, already profiled
        if name in ("codexbar-query-errors",) or name in NEVER_ROUTE or name in OPERATOR_GATED:
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
    model: str = ""                 # "<model> [--effort L]" for acp-run

    @property
    def dispatch(self) -> str:
        """The acp-dispatch line for this choice (add --name/--task/-C/-f)."""
        agent = self.service.acp_agent
        if self.model:
            return f"acp-dispatch {agent} --model {self.model}"
        return f"acp-dispatch {agent} --model <id from: acp-run {agent} --info>"


def suggest_model(svc: Service, kind: str, info: dict[str, Any]) -> str:
    """The model/effort to pass for `kind` on `svc`, from its profile.

    claude's judgment slot is Fable 5.1 while the Fable sublimit (at most 50%
    of the shared weekly) has room, else Opus at the same effort."""
    model = svc.models.get(kind, "")
    if svc.name == "claude" and kind == "judgment":
        fable = (info.get("sublimits") or {}).get("fable")
        if fable is not None and fable < FABLE_MIN_LEFT:
            model = "opus --effort xhigh"
    return model


def route(kind: str, *, quota: dict[str, Any] | None = None,
          min_headroom: float = 15.0,
          exclude: frozenset[str] | set[str] = frozenset()) -> Choice | None:
    """Choose a service for `kind`, preferring idle paid capacity for bulk.

    `exclude` names services to skip (full for this wave, or just failed)."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    quota = {} if quota is None else quota

    scored: list[tuple[float, Service, float | None]] = []
    for svc in discover(quota):
        if not svc.eligible(kind) or svc.name in exclude:
            continue
        info = quota.get(svc.name) or {}
        remaining = info.get("remaining")
        if remaining is not None and remaining < max(min_headroom, svc.reserve_floor):
            continue                       # too tight to hand work to, or a reserve at its floor
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
        rank = svc.rank_for(kind) + pressure
        if svc.burn_first and remaining is not None and remaining >= BURN_FIRST_MIN:
            rank -= BURN_FIRST_BONUS
        scored.append((rank, svc, remaining))

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
    if best.reserve_floor:
        why.append(f"RESERVE: floor {best.reserve_floor:.0f}% left, one small slice, "
                   "check the window first")
    if best.note:
        why.append(best.note)
    return Choice(best, remaining, best_score, "; ".join(why),
                  [s.name for _, s, _ in scored[1:4]],
                  model=suggest_model(best, kind, quota.get(best.name) or {}))


def plan(kinds: list[str], *, quota: dict[str, Any] | None = None,
         min_headroom: float = 15.0,
         exclude: frozenset[str] | set[str] = frozenset()
         ) -> list[tuple[str, Choice | None]]:
    """Assign each slice kind to a service for ONE wave, right now.

    Greedy in the given order (put the hardest first), honouring each
    service's `max_parallel` so a wave spreads over pools. Slices that
    find no room come back as None: leave them queued and re-plan when a
    slice finishes. Re-run it at every wave boundary; it is a snapshot-file
    read, so it is instant and costs no tokens."""
    load: dict[str, int] = {}
    full = set(exclude)
    out: list[tuple[str, Choice | None]] = []
    for kind in kinds:
        choice = route(kind, quota=quota, min_headroom=min_headroom, exclude=full)
        if choice is not None:
            name = choice.service.name
            load[name] = load.get(name, 0) + 1
            if load[name] >= choice.service.max_parallel:
                full.add(name)
        out.append((kind, choice))
    return out


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


JEV = Path(__file__).resolve().parent / "jev"


def shadow_kind(brief_path: str, incumbent: str, service: str | None) -> None:
    """Log what the deciders (Jev, GLiDE) say a brief's kind is, beside the caller's kind.

    Site `agent-choice`; detached, so it never delays or changes the route. With the
    jev mode off it exits at once. Any failure is swallowed.
    """
    try:
        text = Path(brief_path).read_text(errors="replace")[:4000]
        args = [str(JEV), "decide", "--site", "agent-choice",
                "--question", "What kind of work is this delegated task?",
                "--incumbent", incumbent, "--meta", f"service={service or ''}", "--timeout", "5"]
        for kind in KINDS:
            args += ["--option", kind]
        child = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, text=True, start_new_session=True)
        child.stdin.write(text)
        child.stdin.close()
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Route work to a vendor")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("route")
    r.add_argument("--kind", required=True, choices=KINDS)
    r.add_argument("--json", action="store_true")
    r.add_argument("--min-headroom", type=float, default=15.0)
    r.add_argument("--brief", help="the slice's brief file: its kind is also asked of Jev and "
                   "GLiDE in shadow (site agent-choice); never changes the route")
    pl = sub.add_parser("plan", help="assign a wave of slice kinds to services now")
    pl.add_argument("--kinds", required=True,
                    help="comma list, hardest first, e.g. code,code,research,bulk")
    pl.add_argument("--exclude", action="append", default=[],
                    help="comma list of services to skip (just failed or spent); repeatable. "
                    "aiuse [disabled_services] are always skipped")
    pl.add_argument("--min-headroom", type=float, default=15.0)
    pl.add_argument("--json", action="store_true")
    pl.add_argument("--brief", action="append", default=[],
                    help="brief file per kind, in --kinds order (repeat; shadow-asks Jev and GLiDE)")
    sub.add_parser("show", help="snapshot age and per-service headroom")
    sub.add_parser("services", help="every service discovered right now")
    hc = sub.add_parser("hermes-chain", help="generate Hermes's provider chain")
    hc.add_argument("--apply", action="store_true", help="write it to config.yaml")

    args = parser.parse_args(argv)
    quota, age = load_snapshot()

    if args.command == "plan":
        kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
        bad = [k for k in kinds if k not in KINDS]
        if bad:
            parser.error(f"unknown kind(s) {bad}; choose from {KINDS}")
        skip = {x.strip() for arg in args.exclude for x in arg.split(",") if x.strip()}
        skip |= operator_disabled()
        rows = plan(kinds, quota=quota, min_headroom=args.min_headroom, exclude=skip)
        if args.brief:
            if len(args.brief) != len(kinds):
                parser.error("--brief must be given once per kind, in --kinds order")
            for brief, (k, c) in zip(args.brief, rows):
                shadow_kind(brief, k, c.service.name if c else None)
        stale = (not quota) or age is None or age > STALE_SOFT
        if args.json:
            print(json.dumps({
                "snapshot_age_s": age, "stale": stale,
                "slices": [{"kind": k, "service": c.service.name if c else None,
                            "cli": c.service.cli if c else None,
                            "agent": c.service.acp_agent if c else None,
                            "model": c.model if c else None,
                            "dispatch": c.dispatch if c else None,
                            "remaining": c.remaining if c else None,
                            "why": c.why if c else "no pool has room: keep queued"}
                           for k, c in rows]}, indent=1))
        else:
            if stale:
                print("WARNING: quota snapshot "
                      + ("empty" if not quota else f"{(age or 0) / 60:.0f} min old")
                      + " -> run `aiuse --available --live` first; routing below "
                      "is capability-only for unmeasured pools", file=sys.stderr)
            for i, (k, c) in enumerate(rows, 1):
                if c is None:
                    print(f"{i}. {k:10} -> (none: keep queued, re-plan at the next boundary)")
                else:
                    rem = "" if c.remaining is None else f" {c.remaining:.0f}% left"
                    print(f"{i}. {k:10} -> {c.service.name}{rem}  [{c.service.cli}]"
                          f"  {c.dispatch}")
        return 0

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
            print(f"  {name:16} {info.get('remaining')!s:>6}% remaining{flag}")
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

    choice = route(args.kind, quota=quota, min_headroom=args.min_headroom, exclude=operator_disabled())
    if args.brief:
        shadow_kind(args.brief, args.kind, choice.service.name if choice else None)
    if choice is None:
        print(json.dumps({"kind": args.kind, "service": None,
                          "reason": "no eligible service with headroom"}))
        return 1
    if args.json:
        print(json.dumps({
            "kind": args.kind, "service": choice.service.name, "cli": choice.service.cli,
            "agent": choice.service.acp_agent, "model": choice.model,
            "dispatch": choice.dispatch,
            "remaining_percent": choice.remaining, "why": choice.why,
            "alternatives": choice.alternatives,
            "snapshot_age_seconds": None if age is None else round(age),
        }, indent=2))
    else:
        print(f"{choice.service.cli}   — {choice.why}")
        print(f"  dispatch: {choice.dispatch}")
        if choice.alternatives:
            print(f"  alternatives: {', '.join(choice.alternatives)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
