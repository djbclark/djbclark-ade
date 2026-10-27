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
minutes. Since 2026-10-20 routing asks `aiuse --available --json` instead (argv list,
20 s timeout; it reads that same cache in well under a second), because aiuse applies
the operator credits override (`aiuse set-credits`), Admin API readings and grant
expiry at read time and the file never carries them. A pool the snapshot knows that
a fresh `--available` leaves out reads 0% left (exhausted, excluded or hidden). If aiuse
is missing, fails, times out or prints malformed JSON, routing logs that on stderr,
falls back to the snapshot file (surfaced as `quota_source` in plan/route JSON and a
WARNING in plan text) and a stale or missing snapshot degrades to capability-only routing
rather than hanging. Env: `ROUTE_AGENT_AIUSE_JSON=<path>` feeds canned output (tests; reported
as source `canned`, logged on stderr each use, and it takes precedence over
`ROUTE_AGENT_AIUSE=off` and `AIUSE_SNAPSHOT`), `ROUTE_AGENT_AIUSE=off` or `AIUSE_SNAPSHOT`
pins the file-only read, `ROUTE_AGENT_AIUSE_BIN` names the binary,
`ROUTE_AGENT_AIUSE_TIMEOUT` is seconds in (0, 60] (default 20). The spawn is memoised for 30 s;
`load_snapshot(bypass_memo=True)` skips the memo (acp-dispatch's post-wait plenty-gate looks).

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
- judgment goes to claude's Opus 5.5 at high first, omp's Opus next, and (2026-10-25) codex's gpt-6.1-sol
  at high only while every window has plenty_min left; the two frontier models, Claude
  Fable 5.1 and codex's gpt-6-astra, are reached ONLY through the explicit
  `frontier` kind, at most one slice per pool per wave, for work that really
  needs them (operator 2026-10-18: a wave of four astra slices emptied
  codex's 5-hour window and every one stopped; Fable at xhigh should almost
  never run). Everyday work goes to the other pools, and ALSO to codex's
  everyday models (gpt-6.1-sol for judgment and code, gpt-6-luna for bulk and mechanical;
  never astra) while its quota is plentiful (operator 2026-10-25: "if we have
  lots of codex quota and it is the best of available options we can use it for
  non-frontier"): a service's `plenty_kinds` are eligible only while its binding
  headroom (the tightest window, 5-hour and weekly alike) is at least
  `PLENTY_MIN` ([routing].plenty_min, 50), and with no fresh reading they are
  not, so below it codex is frontier-only again; inside that gate it competes
  on the normal ranking, it is not forced first;
- Fable is a sublimit (at most 50%) of the SAME Claude weekly window, not a
  separate allowance: a Fable run bills the shared window too;
- copilot is the one reserve, with a hard floor (`reserve_floor`): GitHub-side
  Copilot review runs on it; never deplete it (grok was a reserve until
  2026-10-18, when GrokBot moved to its own Cursor pool);
- hermes is never a delegation target (gated, never discovered as a routable
  service here); omp is an ordinary tier since 2026-10-19 (operator): its Claude
  API credits are an expiring grant, first for `api-only` work (it is the only
  pool in that kind) and otherwise for `code`/`bulk` slices, so they are spent
  before each monthly reset; `grant_days` gives it the burn-first bonus while the
  balance is far above an even spend over the month;
- **never** route a slice to clinepass (NEVER_ROUTE) — it is the Hindsight/hermes
  lifeline and stays only in `hermes_chain`;
- the prepaid tier (opencode-zen, openrouter, deepseek) is retired until an
  explicit operator top-up.

Every route comes with a `--model [--effort]` suggestion and the
`acp-dispatch` line to run; the context window is the caller's choice (the
agent's default unless the slice reads a whole corpus or a long log).

Usage:
    route_agent.py route --kind bulk
    route_agent.py route --kind judgment --json
    route_agent.py refresh          # force a synchronous quota refresh
    route_agent.py show             # cache age, headroom, pace, expected waste
    route_agent.py calibrate [--since DAYS] [--json] [--min N]
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ade_gates  # noqa: E402  (the frontier gate: config/gates.toml [frontier], docs/gates.md)

DEFAULT_SNAPSHOT = Path.home() / ".cache" / "aiuse" / "snapshots" / "latest.json"
SNAPSHOT = Path(os.environ.get("AIUSE_SNAPSHOT") or DEFAULT_SNAPSHOT)
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

# KINDS, BURN_FIRST_* and the curated SERVICES rows are
# loaded from config/routing.toml (see load_policy / apply_policy below).


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
    # Static fallback for burn-first when expected waste at reset is unknown.
    # Prefer computed waste ≥ burn_first_waste_min (2026-10-18). When waste is
    # known this flag is ignored; when unknown, `route` still applies
    # BURN_FIRST_BONUS above BURN_FIRST_MIN.
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
    # of its binding window left, whatever `min_headroom` says (copilot:
    # GitHub-side Copilot review draws on it; grok was one until 2026-10-18).
    reserve_floor: float = 0.0
    # Days in the grant period when this pool is an expiring dollar grant rather than a
    # rolling window (omp's Claude API credits, 2026-10-19): aiuse reports an expiry
    # (`resets_at`) but no `window_minutes` or pace, so expected_waste() cannot compute
    # waste and the pool would never earn the burn-first bonus. With grant_days set,
    # grant_waste() measures the balance against an even spend over the period instead.
    grant_days: int = 0
    # Name of a readiness probe in READY_PROBES. A service whose probe fails is skipped by
    # route() for every kind that goes through acp-dispatch (not `api-only`, which is the
    # caller's own API call), so the router never hands out a slice that cannot start.
    ready_probe: str = ""
    # Name of another service whose aiuse row this one draws on (cursor-cloud bills at API
    # price against the Cursor pool, 2026-10-20): load_snapshot copies that row's reading
    # to this name unless aiuse reports one of its own.
    shares_pool: str = ""
    # Kinds that need a plentiful quota: eligible only while the pool's tightest window holds at
    # least PLENTY_MIN percent ([routing].plenty_min). Codex's everyday kinds (operator 2026-10-25).
    plenty_kinds: tuple[str, ...] = ()

    @property
    def acp_agent(self) -> str:
        return self.agent or self.name

    def eligible(self, kind: str, quota: dict[str, Any] | None = None, *,
                 any_headroom: bool = False) -> bool:
        """Can this service take `kind`?  `plenty_kinds` also need a fresh reading of at least
        PLENTY_MIN in `quota[name]["remaining"]` (the tightest window) AND a reading for every
        window the pool lists (`plenty_remaining`: one unknown window means the gate cannot
        say every window has PLENTY_MIN left, 2026-10-25), else they are not eligible; no
        `quota` means no reading, so those kinds fail closed.  `any_headroom` skips that gate,
        for questions about the profile alone (calibrate's history)."""
        if self.retired or self.hermes_only:
            return False
        if kind in ("bulk", "mechanical") and self.never_bulk:
            return False
        if kind in ("judgment", "frontier") and not self.judgment_tier:
            return False
        if kind not in self.good_at:
            return False
        if kind in self.plenty_kinds and not any_headroom:
            remaining = plenty_remaining((quota or {}).get(self.name))
            return remaining is not None and remaining >= PLENTY_MIN
        return True

    def rank_for(self, kind: str) -> int:
        return self.good_at[kind]


def plenty_remaining(info: dict[str, Any] | None) -> float | None:
    """A pool's binding remaining percent for the `plenty_kinds` gate, or None when it is not
    known for every window: no reading, or any window the reading lists as null (an aiuse
    window with `remaining_percent: null` is a window nobody measured; the pool's `remaining`
    is then only the tightest of the KNOWN ones, which cannot show every window is plentiful)."""
    info = info or {}
    remaining = info.get("remaining")
    if remaining is None or any(v is None for v in (info.get("windows") or {}).values()):
        return None
    return remaining


# Policy file: env ROUTING_POLICY, else <repo>/config/routing.toml (same
# resolution style as ACP_RUN).
def resolve_policy_path() -> Path:
    return Path(os.environ.get("ROUTING_POLICY") or
                (Path(__file__).resolve().parent.parent / "config" / "routing.toml"))


POLICY_PATH = resolve_policy_path()
POLICY: dict[str, Any] = {}
SERVICE_KEYS = {f.name for f in fields(Service)}
_SERVICE_REQUIRED = ("name", "cli", "good_at", "billing")
# The orchestrating session's own model, [lead] in the policy file (2026-10-23).  LEAD_KEYS are
# required; `pipeline_effort` (djbclark 2026-10-23: a pipeline-only lead runs Sonnet at medium) is
# optional and defaults to LEAD_PIPELINE_EFFORT_DEFAULT so an older policy file still loads.
LEAD_KEYS = ("model", "effort", "pipeline_model")
LEAD_PIPELINE_EFFORT_DEFAULT = "high"
# The effort levels a Claude lead can be set to: Paseo's CLAUDE_EFFORT_LEVELS (its `xhigh` list,
# Paseo.app app.asar, 2026-10-23) and Claude Code's `/effort` / SDK `effort` type.  Not acp-run's
# wider list (none, minimal, ultra, default): no Claude surface takes those.
CLAUDE_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
LEAD_ALL_KEYS = LEAD_KEYS + ("pipeline_effort",)

# Populated by apply_policy from the TOML; names and types match the former
# module-level literals so every caller and test keeps working.
SERVICES: tuple[Service, ...]
BY_NAME: dict[str, Service]
KINDS: tuple[str, ...]
BURN_FIRST_MIN: float
BURN_FIRST_BONUS: float
BURN_FIRST_WASTE_MIN: float
PACE_PENALTY_ABOVE: float
PACE_PENALTY: float
PACE_PENALTY_JUDGMENT_FACTOR: float
PLENTY_MIN: float
QUALITY_MAX_RANK_GAP: dict[str, int]
DEFAULT_PROFILE: dict[str, int]
NEVER_ROUTE: frozenset[str]
OPERATOR_GATED: frozenset[str]
ALIASES: dict[str, str]
DISPATCH_EXTRA: dict[str, str]
HERMES_MODELS: dict[str, list[str]]
HERMES_PROVIDER_NAME: dict[str, str]
CALIBRATE_MIN_OUTCOMES: int
CALIBRATE_MIN_PEERS: int
CALIBRATE_SUGGEST_WORSE_BELOW: float
CALIBRATE_SUGGEST_WORSE_DELTA: int
CALIBRATE_SUGGEST_BETTER_ABOVE: float
CALIBRATE_SUGGEST_BETTER_DELTA: int


def load_policy(path: Path | str) -> dict[str, Any]:
    """Parse and validate config/routing.toml (or ROUTING_POLICY).

    Each [[service]] may only use Service field names; name/cli/good_at/billing
    are required. Raises ValueError naming the file and the entry on bad input.
    """
    path = Path(path)
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except OSError as e:
        raise ValueError(f"routing policy {path}: {e}") from e
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"routing policy {path}: {e}") from e

    services = data.get("service")
    if services is None:
        raise ValueError(f"routing policy {path}: missing [[service]] entries")
    if not isinstance(services, list):
        raise ValueError(f"routing policy {path}: 'service' must be an array of tables")

    for i, entry in enumerate(services):
        label = entry.get("name") if isinstance(entry, dict) else i
        if not isinstance(entry, dict):
            raise ValueError(f"routing policy {path}: [[service]] entry {i} is not a table")
        unknown = set(entry) - SERVICE_KEYS
        if unknown:
            raise ValueError(
                f"routing policy {path}: [[service]] {label!r}: "
                f"unknown key(s) {sorted(unknown)}")
        missing = [k for k in _SERVICE_REQUIRED if k not in entry]
        if missing:
            raise ValueError(
                f"routing policy {path}: [[service]] {label!r}: "
                f"missing required key(s) {missing}")
        pool = entry.get("pool")
        if pool is not None and not (isinstance(pool, list) and len(pool) == 2
                                       and all(isinstance(x, str) for x in pool)):
            raise ValueError(
                f"routing policy {path}: [[service]] {label!r}: "
                f"pool must be a 2-element string array, got {pool!r}")
    for section in ("routing", "discovery", "dispatch", "hermes", "calibrate"):
        if section not in data or not isinstance(data[section], dict):
            raise ValueError(f"routing policy {path}: missing [{section}] table")
    lead = data.get("lead")
    if lead is not None:
        if not isinstance(lead, dict):
            raise ValueError(f"routing policy {path}: [lead] must be a table")
        unknown = set(lead) - set(LEAD_ALL_KEYS)
        if unknown:
            raise ValueError(f"routing policy {path}: [lead] unknown key(s) {sorted(unknown)}")
        if not all(isinstance(lead.get(k), str) and lead[k] for k in LEAD_KEYS):
            raise ValueError(f"routing policy {path}: [lead] must be a table with non-empty string keys "
                             + ", ".join(LEAD_KEYS))
        lead.setdefault("pipeline_effort", LEAD_PIPELINE_EFFORT_DEFAULT)
        for key in ("effort", "pipeline_effort"):
            if lead[key] not in CLAUDE_EFFORT_LEVELS:
                raise ValueError(f"routing policy {path}: [lead] {key} {lead[key]!r} must be one of "
                                 + ", ".join(CLAUDE_EFFORT_LEVELS))
    return data


def _service_from_entry(entry: dict[str, Any]) -> Service:
    kwargs = dict(entry)
    if kwargs.get("pool") is not None:
        a, b = kwargs["pool"]
        kwargs["pool"] = (a, b)
    kwargs["good_at"] = {str(k): int(v) for k, v in kwargs["good_at"].items()}
    kwargs["plenty_kinds"] = tuple(str(k) for k in kwargs.get("plenty_kinds") or ())
    if "models" in kwargs and kwargs["models"] is not None:
        kwargs["models"] = {str(k): str(v) for k, v in kwargs["models"].items()}
    return Service(**kwargs)


def apply_policy(data: dict[str, Any]) -> None:
    """Install a loaded policy dict as this module's routing constants."""
    global POLICY, SERVICES, BY_NAME, KINDS, BURN_FIRST_MIN, BURN_FIRST_BONUS
    global BURN_FIRST_WASTE_MIN, PACE_PENALTY_ABOVE, PACE_PENALTY
    global PACE_PENALTY_JUDGMENT_FACTOR, QUALITY_MAX_RANK_GAP
    global PLENTY_MIN, DEFAULT_PROFILE, NEVER_ROUTE, OPERATOR_GATED
    global ALIASES, DISPATCH_EXTRA, HERMES_MODELS
    global HERMES_PROVIDER_NAME
    global CALIBRATE_MIN_OUTCOMES, CALIBRATE_MIN_PEERS
    global CALIBRATE_SUGGEST_WORSE_BELOW
    global CALIBRATE_SUGGEST_WORSE_DELTA, CALIBRATE_SUGGEST_BETTER_ABOVE
    global CALIBRATE_SUGGEST_BETTER_DELTA

    POLICY = data
    try:
        routing = data["routing"]
        discovery = data["discovery"]
        dispatch = data["dispatch"]
        hermes = data["hermes"]
        calibrate = data["calibrate"]

        KINDS = tuple(routing["kinds"])
        BURN_FIRST_MIN = float(routing["burn_first_min"])
        BURN_FIRST_BONUS = float(routing["burn_first_bonus"])
        BURN_FIRST_WASTE_MIN = float(routing["burn_first_waste_min"])
        PACE_PENALTY_ABOVE = float(routing["pace_penalty_above"])
        PACE_PENALTY = float(routing["pace_penalty"])
        PACE_PENALTY_JUDGMENT_FACTOR = float(routing["pace_penalty_judgment_factor"])
        PLENTY_MIN = float(routing["plenty_min"])
        QUALITY_MAX_RANK_GAP = {str(k): int(v) for k, v in
                                (routing.get("quality_max_rank_gap") or {}).items()}
        DEFAULT_PROFILE = {str(k): int(v) for k, v in routing["default_profile"].items()}

        NEVER_ROUTE = frozenset(discovery["never_route"])
        OPERATOR_GATED = frozenset(discovery["operator_gated"])
        ALIASES = {str(k): str(v) for k, v in discovery["aliases"].items()}

        DISPATCH_EXTRA = {str(k): str(v) for k, v in (dispatch.get("extra") or {}).items()}
        HERMES_MODELS = {str(k): [str(m) for m in v]
                          for k, v in (hermes.get("models") or {}).items()}
        HERMES_PROVIDER_NAME = {str(k): str(v)
                                for k, v in (hermes.get("provider_name") or {}).items()}

        CALIBRATE_MIN_OUTCOMES = int(calibrate["min_outcomes"])
        CALIBRATE_MIN_PEERS = int(calibrate["min_peers"])
        CALIBRATE_SUGGEST_WORSE_BELOW = float(calibrate["suggest_worse_below"])
        CALIBRATE_SUGGEST_WORSE_DELTA = int(calibrate["suggest_worse_delta"])
        CALIBRATE_SUGGEST_BETTER_ABOVE = float(calibrate["suggest_better_above"])
        CALIBRATE_SUGGEST_BETTER_DELTA = int(calibrate["suggest_better_delta"])
    except KeyError as e:
        raise ValueError(
            f"routing policy {POLICY_PATH}: missing key {e.args[0]!r}"
        ) from e

    SERVICES = tuple(_service_from_entry(e) for e in data["service"])
    BY_NAME = {s.name: s for s in SERVICES}


def reload_policy(path: Path | str | None = None) -> dict[str, Any]:
    """Re-read ROUTING_POLICY (or `path`) and re-apply. Used by tests."""
    global POLICY_PATH
    POLICY_PATH = Path(path) if path is not None else resolve_policy_path()
    data = load_policy(POLICY_PATH)
    apply_policy(data)
    return data


def policy_public() -> dict[str, Any]:
    """Effective policy as a JSON-serialisable dict (services expanded)."""
    def svc_row(s: Service) -> dict[str, Any]:
        return {
            "name": s.name, "cli": s.cli, "good_at": dict(s.good_at),
            "billing": s.billing, "note": s.note, "never_bulk": s.never_bulk,
            "retired": s.retired, "judgment_tier": s.judgment_tier,
            "access": s.access, "hermes_only": s.hermes_only,
            "burn_first": s.burn_first,
            "pool": list(s.pool) if s.pool else None,
            "max_parallel": s.max_parallel, "agent": s.agent,
            "models": dict(s.models), "reserve_floor": s.reserve_floor,
            "grant_days": s.grant_days, "ready_probe": s.ready_probe,
            "shares_pool": s.shares_pool, "plenty_kinds": list(s.plenty_kinds),
        }
    return {
        "path": str(POLICY_PATH),
        "frontier_gate": frontier_gate(),
        "routing": {
            "kinds": list(KINDS),
            "burn_first_min": BURN_FIRST_MIN,
            "burn_first_bonus": BURN_FIRST_BONUS,
            "burn_first_waste_min": BURN_FIRST_WASTE_MIN,
            "pace_penalty_above": PACE_PENALTY_ABOVE,
            "pace_penalty": PACE_PENALTY,
            "pace_penalty_judgment_factor": PACE_PENALTY_JUDGMENT_FACTOR,
            "plenty_min": PLENTY_MIN,
            "default_profile": dict(DEFAULT_PROFILE),
        },
        "calibrate": {
            "min_outcomes": CALIBRATE_MIN_OUTCOMES,
            "min_peers": CALIBRATE_MIN_PEERS,
            "suggest_worse_below": CALIBRATE_SUGGEST_WORSE_BELOW,
            "suggest_worse_delta": CALIBRATE_SUGGEST_WORSE_DELTA,
            "suggest_better_above": CALIBRATE_SUGGEST_BETTER_ABOVE,
            "suggest_better_delta": CALIBRATE_SUGGEST_BETTER_DELTA,
        },
        "discovery": {
            "never_route": sorted(NEVER_ROUTE),
            "operator_gated": sorted(OPERATOR_GATED),
            "aliases": dict(ALIASES),
        },
        "dispatch": {
            "operator_gated": list(POLICY["dispatch"]["operator_gated"]),
            "fable_gated_efforts": list(POLICY["dispatch"]["fable_gated_efforts"]),
            "frontier_models": list(POLICY["dispatch"].get("frontier_models") or []),
            "inflight_cap": {str(k): int(v)
                             for k, v in (POLICY["dispatch"].get("inflight_cap") or {}).items()},
            "estimate_floor": {str(k): float(v)
                               for k, v in (POLICY["dispatch"].get("estimate_floor") or {}).items()},
            "extra": dict(DISPATCH_EXTRA),
        },
        "hermes": {
            "models": {k: list(v) for k, v in HERMES_MODELS.items()},
            "provider_name": dict(HERMES_PROVIDER_NAME),
        },
        "services": [svc_row(s) for s in SERVICES],
        "opencode_go": json.loads((Path(__file__).resolve().parents[1] / "config/go-model-policy.json").read_text()),
        "lead": dict(POLICY["lead"]) if POLICY.get("lead") else None,
    }


def policy_markdown() -> str:
    """Markdown tables: services × kinds (rank, model), gates, caps."""
    lines = ["# Routing policy", "", f"Source: `{POLICY_PATH}`", "",
             "## Services × kinds", ""]
    header = "| service | " + " | ".join(KINDS) + " |"
    sep = "|---|" + "|".join("---" for _ in KINDS) + "|"
    lines += [header, sep]
    for s in SERVICES:
        cells = []
        for k in KINDS:
            if k not in s.good_at:
                cells.append("—")
            else:
                model = s.models.get(k, "")
                cell = f"r{s.good_at[k]}"
                if model:
                    cell += f" `{model}`"
                cells.append(cell)
        lines.append(f"| {s.name} | " + " | ".join(cells) + " |")
    lines += ["", "## Gates and caps", ""]
    lines.append("| key | value |")
    lines.append("|---|---|")
    d = POLICY["dispatch"]
    lines.append(f"| discovery.never_route | {', '.join(sorted(NEVER_ROUTE))} |")
    lines.append(f"| discovery.operator_gated | {', '.join(sorted(OPERATOR_GATED))} |")
    lines.append(f"| dispatch.operator_gated | {', '.join(d['operator_gated'])} |")
    lines.append(f"| dispatch.fable_gated_efforts | {', '.join(d['fable_gated_efforts'])} |")
    caps = ", ".join(f"{k}={v}" for k, v in (d.get("inflight_cap") or {}).items()) or "(none)"
    lines.append(f"| dispatch.inflight_cap | {caps} |")
    floors = ", ".join(f"{k}={v}" for k, v in (d.get("estimate_floor") or {}).items()) or "(none)"
    lines.append(f"| dispatch.estimate_floor | {floors} |")
    frontiers = ", ".join(d.get("frontier_models") or []) or "(none)"
    lines.append(f"| dispatch.frontier_models | {frontiers} |")
    fg = frontier_gate()
    lines.append(f"| gates.frontier1_per_wave / frontier2_per_wave | {fg['frontier1_per_wave']:g} / {fg['frontier2_per_wave']:g} |")
    lines.append(f"| routing.plenty_min | {PLENTY_MIN:g} |")
    lines.append(f"| gates.frontier1_min_left | {fg['frontier1_min_left']:g} |")
    lines.append(f"| routing.burn_first_min | {BURN_FIRST_MIN} |")
    lines.append(f"| routing.burn_first_waste_min | {BURN_FIRST_WASTE_MIN} |")
    lines.append(f"| routing.pace_penalty_above | {PACE_PENALTY_ABOVE} |")
    lines.append(f"| routing.pace_penalty | {PACE_PENALTY} |")
    lines.append(f"| routing.pace_penalty_judgment_factor | {PACE_PENALTY_JUDGMENT_FACTOR} |")
    lead = POLICY.get("lead")
    if lead:
        lines += ["", "## Lead / orchestrator session", "",
                  "The session that dispatches slices runs on this, not on Fable "
                  "(Fable only through the `fable-deep` sub-agent or a `frontier` slice).", "",
                  "| key | value |", "|---|---|"]
        lines += [f"| lead.{k} | {lead[k]} |" for k in LEAD_ALL_KEYS]
        lines += ["", f"pipeline lead: {lead['pipeline_model']} at {lead['pipeline_effort']}; "
                      "high for judgment turns (`/effort high`, or the Paseo `--thinking` setting; "
                      "back to the pipeline effort afterwards)."]
    return "\n".join(lines) + "\n"


apply_policy(load_policy(POLICY_PATH))


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
    cursor, both disabled there, one then reserved for grokbot). Keys are aiuse's
    canonical provider ids, the same names `Service.name` uses.
    """
    import tomllib

    try:
        with (path or AIUSE_CONFIG).open("rb") as fh:
            off = set((tomllib.load(fh).get("disabled_services") or {}).keys())
    except (OSError, tomllib.TOMLDecodeError):
        return set()
    # a service that draws on a disabled provider's pool is off with it (cursor-cloud on cursor)
    return off | {s.name for s in SERVICES if s.shares_pool and s.shares_pool in off}


def _read_snapshot_file() -> tuple[list[Any], float | None]:
    """aiuse's own latest snapshot file as (accounts, age). Never probes; never blocks."""
    path = Path(os.environ.get("AIUSE_SNAPSHOT") or SNAPSHOT)
    if not path.exists():
        if os.environ.get("AIUSE_SNAPSHOT"):
            return [], None
        candidates = sorted(path.parent.glob("20*.json"), reverse=True) if path.parent.is_dir() else []
        if not candidates:
            return [], None
        path = candidates[0]
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return [], None

    collected = data.get("collected_at") or data.get("started_at") or ""
    age = None
    try:
        stamp = datetime.fromisoformat(str(collected))
        age = (datetime.now(UTC) - stamp).total_seconds()
    except (ValueError, TypeError):  # TypeError: a naive timestamp
        age = time.time() - path.stat().st_mtime

    snap = data.get("snapshot", data)
    return list(snap.get("accounts", []) or []), age


def _pct(value: Any) -> float | None:
    """A percentage clamped to [0, 100]; None for anything non-numeric or non-finite
    (NaN and Infinity must never read as headroom)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return min(100.0, max(0.0, x)) if math.isfinite(x) else None


def _clean_age(value: Any) -> float | None:
    """Seconds as a finite, non-negative float, else None (unknown)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return x if math.isfinite(x) and x >= 0 else None


# pool_family values that are a model cap inside the provider's shared pool, not a pool of
# their own (Claude's `fable` is at most 50% of the shared weekly, aiuse schema 1.1).
SUBLIMIT_FAMILIES = ("fable",)


def _merge_caps(a: dict[str, Any] | None, b: dict[str, Any] | None) -> dict[str, Any]:
    """Per-key tighter of two sublimit maps (a cap never loosens by merge order)."""
    out = dict(a or {})
    for k, v in (b or {}).items():
        out[k] = _tighter(out.get(k), v) if k in out else v
    return out


def _merge_pool(into: dict[str, Any], key: str, entry: dict[str, Any]) -> None:
    """Fold one pool entry into `into`: the tightest known remaining wins and carries its bind."""
    prior = into.get(key)
    if prior is None:
        into[key] = entry
        return
    p_rem, e_rem = prior.get("remaining"), entry.get("remaining")
    take_new = e_rem is not None and (p_rem is None or e_rem < p_rem)
    merged = dict(entry if take_new else prior)
    merged["windows"] = {**prior.get("windows", {}), **entry.get("windows", {})}
    merged["sublimits"] = _merge_caps(prior.get("sublimits"), entry.get("sublimits"))
    merged["remaining"] = e_rem if take_new else p_rem
    into[key] = merged


def _tighter(a: float | None, b: float | None) -> float | None:
    vals = [v for v in (a, b) if v is not None]
    return min(vals) if vals else None


def _providers_from_available(rows: list[Any], age: float | None) -> dict[str, Any]:
    """Fold `aiuse --available --json` rows into per-service pools.

    The row's own top-level fields are the contract (`aiuse schema`): `provider`,
    `pool_family`, `usable_now`, `headroom_percent` (the least applicable headroom),
    `binding_window`, `available_at`, plus 3.8's `reading_expired` and
    `requires_operator_approval`. `windows[]` is optional detail (3.7.2 attaches it): when
    present it fills `windows`, `sublimits` and the bind fields and can only tighten the
    row's `remaining`, never loosen it. Malformed rows raise (the caller falls back)."""
    pools: dict[str, Any] = {}
    foreign: list[tuple[str, float]] = []
    for row in rows:
        name = row.get("provider")
        if not name or row.get("error"):
            continue
        family = row.get("pool_family")
        key = pool_service(name, family)
        row_age = _clean_age(row.get("age_seconds"))
        if row_age is None:
            row_age = age
        stale = ((row_age is None or row_age > STALE_SOFT)
                 or row.get("reading_expired") is True)
        head = _pct(row.get("headroom_percent"))
        if ("usable_now" in row and row["usable_now"] is not True) or head == 0:
            top: float | None = 0.0
        elif stale:
            top = None
        else:
            top = None if head is None else round(head, 1)
        entry: dict[str, Any] = {
            "remaining": top, "windows": {}, "sublimits": {},
            "billing_kind": row.get("billing_kind"),
            "pace_ratio": None, "resets_at": row.get("available_at"), "window_minutes": None,
            "binding_window": row.get("binding_window"),
            "available_at": row.get("available_at"),
            "requires_operator_approval": row.get("requires_operator_approval"),
        }
        if row.get("binding_window"):
            entry["windows"][row["binding_window"]] = None if top is None else round(top, 1)
        folded: dict[str, Any] = {}
        if row.get("windows"):
            folded = _providers_from_accounts([row], age)
        for fkey, finfo in folded.items():
            if fkey == key:
                entry["windows"].update(finfo.get("windows") or {})
                entry["sublimits"] = _merge_caps(entry["sublimits"], finfo.get("sublimits"))
                for k in ("pace_ratio", "resets_at", "window_minutes"):
                    if finfo.get(k) is not None:
                        entry[k] = finfo[k]
                if top is None and not stale:
                    entry["remaining"] = finfo.get("remaining")   # row gave no headroom
                elif top is not None:
                    entry["remaining"] = _tighter(top, finfo.get("remaining"))
                elif finfo.get("remaining") == 0.0:
                    entry["remaining"] = 0.0      # a stale row's exhausted window still binds
            elif finfo.get("remaining") is not None:
                # another family's window inside this row: never creates or loosens that pool
                foreign.append((fkey, finfo["remaining"]))
        if family in SUBLIMIT_FAMILIES and key == name:
            # a model cap inside the shared pool: bounds that model only (sublimits), and
            # must not drag the whole account down
            cap = _tighter(entry["remaining"], entry["sublimits"].get(family))
            entry = {**entry, "remaining": None, "windows": {},
                     "sublimits": {family: cap}}
        _merge_pool(pools, key, entry)
    for fkey, rem in foreign:
        cur = pools.get(fkey)
        if cur is not None and cur.get("remaining") is not None and rem < cur["remaining"]:
            cur["remaining"] = rem
    return pools


def _providers_from_accounts(accounts: list[Any], age: float | None) -> dict[str, Any]:
    """Fold aiuse account rows (snapshot accounts or `--available` rows) into per-service pools."""
    providers: dict[str, Any] = {}
    for acct in accounts:
        name = acct.get("provider")
        if not name or acct.get("error"):
            continue

        # Account freshness: use account's age_seconds or collected_at
        acct_age = None
        acct_age = _clean_age(acct.get("age_seconds"))
        if acct_age is None and acct.get("collected_at"):
            try:
                acct_stamp = datetime.fromisoformat(str(acct["collected_at"]))
                acct_age = (datetime.now(UTC) - acct_stamp).total_seconds()
            except (ValueError, TypeError):
                pass
        if acct_age is None:
            acct_age = age
        is_old = ((acct_age is not None and acct_age > STALE_SOFT)
                  or acct.get("reading_expired") is True)

        # One account can hold several independent model-family pools; agy's
        # Claude/GPT pool is its own service, so its windows must not drag
        # the Gemini pool's headroom down (or the reverse). Binding-window
        # pace/reset fields ride with the least-remaining window (2026-10-18).
        per_key: dict[str, tuple[Any, dict[str, float | None],
                                 dict[str, float | None], dict[str, Any]]] = {}
        for w in acct.get("windows") or []:
            family = w.get("pool_family")
            key = pool_service(name, family)
            worst, detail, sublimits, bind = per_key.get(key, (None, {}, {}, {}))
            label = w.get("label") or "?"

            state = w.get("state")
            headroom = _pct(w.get("headroom_percent"))
            if state == "exhausted" or (headroom is not None and headroom == 0):
                remaining = 0.0
            elif is_old:
                remaining = None
            else:
                # headroom_percent is the least applicable headroom (a model
                # sublimit's ceiling included); remaining_percent is the
                # window's own share. Prefer the ceiling-aware one.
                remaining = headroom if headroom is not None else _pct(w.get("remaining_percent"))

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
                if worst is None or rem_val < worst:
                    worst = rem_val
                    bind = {
                        "pace_ratio": w.get("pace_ratio"),
                        "resets_at": w.get("resets_at"),
                        "window_minutes": w.get("window_minutes"),
                    }
            per_key[key] = (worst, detail, sublimits, bind)

        if not per_key:
            per_key[name] = (None, {}, {}, {})
        for key, (worst, detail, sublimits, bind) in per_key.items():
            prior = providers.get(key) or {}
            prior_rem = prior.get("remaining")
            if prior_rem is not None and worst is not None:
                if prior_rem < worst:
                    # several accounts: the tightest wins, keep its bind fields
                    worst = prior_rem
                    bind = {k: prior.get(k) for k in ("pace_ratio", "resets_at",
                                                      "window_minutes")}
                # else keep this account's bind (already set for `worst`)
            elif prior_rem is not None and worst is None:
                worst = prior_rem
                bind = {k: prior.get(k) for k in ("pace_ratio", "resets_at",
                                                  "window_minutes")}
            providers[key] = {
                "remaining": None if worst is None else round(float(worst), 1),
                "windows": detail, "sublimits": sublimits,
                "billing_kind": acct.get("billing_kind"),
                "pace_ratio": bind.get("pace_ratio"),
                "resets_at": bind.get("resets_at"),
                "window_minutes": bind.get("window_minutes"),
            }
    return providers


class QuotaSource:
    """Where the last load_snapshot() got its pool state (surfaced by plan/show/route)."""
    kind = "snapshot"          # "aiuse" | "snapshot"
    detail = ""
    fallback_reason = ""


def _log(msg: str) -> None:
    print(f"route_agent: {msg}", file=sys.stderr)


def _aiuse_wanted() -> bool:
    """Ask aiuse itself, not the snapshot file, unless something pins the file.

    AIUSE_SNAPSHOT (tests, a replayed snapshot), a patched SNAPSHOT, or
    ROUTE_AGENT_AIUSE=off keep the old file-only read (ROUTE_AGENT_AIUSE_JSON, canned
    output, overrides all three; load_snapshot checks it first)."""
    if os.environ.get("ROUTE_AGENT_AIUSE", "").strip().lower() in ("off", "0", "no", "false"):
        return False
    if os.environ.get("AIUSE_SNAPSHOT") or SNAPSHOT != DEFAULT_SNAPSHOT:
        return False
    return True


AIUSE_MEMO_TTL = 30.0   # seconds a spawn result is reused (a blocking dispatch re-reads at finalize)
_AIUSE_MEMO: dict[tuple[Any, ...], tuple[float, tuple[dict[str, Any] | None, str]]] = {}


def _aged_copy(result: tuple[dict[str, Any] | None, str],
               elapsed: float) -> tuple[dict[str, Any] | None, str]:
    """A memoised result as it reads now: deep copy with `elapsed` added to every age_seconds
    (top level and per row), so staleness keeps advancing. Never mutates the cached object."""
    import copy
    payload, label = result
    if payload is None:
        return result
    out = copy.deepcopy(payload)
    holders = [out] + [row for row in out.get("available", []) if isinstance(row, dict)]
    for holder in holders:
        age = _clean_age(holder.get("age_seconds"))
        if age is not None:
            holder["age_seconds"] = age + elapsed
    return out, label


def _reset_aiuse_cache() -> None:
    """Forget memoised `aiuse --available --json` results (tests; one spawn per process otherwise)."""
    _AIUSE_MEMO.clear()


def _aiuse_timeout() -> float:
    try:
        t = float(os.environ.get("ROUTE_AGENT_AIUSE_TIMEOUT") or 20)
    except ValueError:
        return 20.0
    return t if math.isfinite(t) and 0 < t <= 60 else 20.0


def _parse_available(raw: bytes, label: str) -> tuple[dict[str, Any] | None, str]:
    try:
        text = raw.decode("utf-8")        # strict: invalid bytes are malformed output
        # --json can follow preamble lines on some builds: start at the first brace
        payload = json.loads(text[text.index("{"):])
    except ValueError:                    # includes UnicodeDecodeError and a missing brace
        return None, f"{label}: malformed JSON"
    if not isinstance(payload, dict) or not isinstance(payload.get("available"), list):
        return None, f"{label}: no `available` array"
    return payload, label


def aiuse_available(bypass_memo: bool = False) -> tuple[dict[str, Any] | None, str]:
    """`aiuse --available --json` as (payload, source label); (None, reason) on any failure.

    Applies aiuse's own read-time overlays (operator credits override, Admin API readings,
    grant expiry) that the snapshot file never carries (2026-10-20, aiuse PRs 38 and 40).
    ROUTE_AGENT_AIUSE_JSON=<path> reads canned output instead (tests) and takes precedence
    over ROUTE_AGENT_AIUSE=off and AIUSE_SNAPSHOT; ROUTE_AGENT_AIUSE_BIN names the binary;
    ROUTE_AGENT_AIUSE_TIMEOUT is in seconds, (0, 60], default 20 (the cache read is well
    under one second). Exit 3 means nothing is usable and still prints the JSON. The
    subprocess result (success or failure) is memoised for AIUSE_MEMO_TTL = 30 s, with elapsed
    seconds added to its ages on reuse (`_reset_aiuse_cache` clears it). `bypass_memo=True` skips the
    memo read and spawns anyway (still storing the result): the admission boundaries that judge a
    reading after a wait pass it (2026-10-25, Codex review of PR 73); every other caller keeps the memo."""
    canned = os.environ.get("ROUTE_AGENT_AIUSE_JSON")
    if canned:
        try:
            raw = Path(canned).read_bytes()
        except OSError as exc:
            return None, f"ROUTE_AGENT_AIUSE_JSON unreadable ({exc.__class__.__name__})"
        return _parse_available(raw, f"ROUTE_AGENT_AIUSE_JSON={canned}")
    exe = os.environ.get("ROUTE_AGENT_AIUSE_BIN") or shutil.which("aiuse")
    if not exe:
        return None, "aiuse not on PATH"
    timeout = _aiuse_timeout()
    key = (exe, timeout)
    hit = None if bypass_memo else _AIUSE_MEMO.get(key)
    if hit is not None:
        elapsed = time.monotonic() - hit[0]
        if 0 <= elapsed < AIUSE_MEMO_TTL:
            return _aged_copy(hit[1], elapsed)
    label = "aiuse --available --json"
    try:
        proc = subprocess.run([exe, "--available", "--json"], capture_output=True,
                              timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        result: tuple[dict[str, Any] | None, str] = (
            None, f"{label} timed out after {timeout:g}s")
    except OSError as exc:
        result = (None, f"aiuse could not start ({exc.__class__.__name__})")
    else:
        if proc.returncode not in (0, 3):
            result = (None, f"{label} exited {proc.returncode}")
        else:
            result = _parse_available(proc.stdout, label)
    _AIUSE_MEMO[key] = (time.monotonic(), result)
    return result


def _payload_age(payload: dict[str, Any]) -> float | None:
    age = _clean_age(payload.get("age_seconds"))
    if age is not None:
        return age
    try:
        return _clean_age((datetime.now(UTC) - datetime.fromisoformat(
            str(payload.get("generated_at")))).total_seconds())
    except (ValueError, TypeError):
        return None


def quota_source_info() -> dict[str, Any]:
    """Where the last load_snapshot() read pool state, for plan/show/route output."""
    return {"source": QuotaSource.kind, "detail": QuotaSource.detail,
            "fallback_reason": QuotaSource.fallback_reason or None}


def _apply_excluded(providers: dict[str, Any], excluded: Any) -> None:
    """Pools the operator ruled out (`excluded[]`) read 0% left, even with no snapshot row.

    Same conditions as the absent-pool rule (the caller applies it only for a valid, fresh
    payload), and the merge only tightens. An invalid excluded row is ignored rather than a
    fallback trigger: `excluded` is advisory, and one bad entry must not discard a good
    `available` list. An excluded sublimit family (`fable`) caps that model only."""
    if not isinstance(excluded, list):
        return
    for row in excluded:
        if not (isinstance(row, dict) and isinstance(row.get("provider"), str)
                and row["provider"] and isinstance(row.get("pool_family"), (str, type(None)))):
            continue
        name, family = row["provider"], row.get("pool_family")
        key = pool_service(name, family)
        prior = providers.get(key) or {"windows": {}, "sublimits": {}, "remaining": None}
        entry = dict(prior, excluded=True, reason=row.get("reason"))
        if family in SUBLIMIT_FAMILIES and key == name:
            entry["sublimits"] = _merge_caps(prior.get("sublimits"), {family: 0.0})
        else:
            entry["remaining"] = _tighter(prior.get("remaining"), 0.0)
        providers[key] = entry


def load_snapshot(bypass_memo: bool = False) -> tuple[dict[str, Any], float | None]:
    """Pool state per service: `aiuse --available --json`, else the snapshot file.

    Never probes live (the `--available` form reads aiuse's cache, well under a second).
    `--available` lists only usable pools, so a pool the snapshot file knows that is
    missing from a fresh payload is exhausted, excluded or hidden: it reads 0% left rather
    than unknown. Fields 3.8 adds (`expires_at`, `burn_before_reset`, `reading_expired`,
    `source`) are tolerated when absent; the row's own `resets_at` and windows carry them.
    `bypass_memo=True` makes the aiuse read skip its 30 s memo (see aiuse_available)."""
    QuotaSource.kind, QuotaSource.detail, QuotaSource.fallback_reason = "snapshot", "", ""
    accounts, age = _read_snapshot_file()
    providers = _providers_from_accounts(accounts, age)
    canned = bool(os.environ.get("ROUTE_AGENT_AIUSE_JSON"))
    if canned or _aiuse_wanted():
        payload, label = aiuse_available(bypass_memo)
        fresh: dict[str, Any] | None = None
        p_age: float | None = None
        marked_stale = False
        if payload is not None:
            p_age = _payload_age(payload)
            # the contract's own staleness signal: `fresh` present and not True means stale
            marked_stale = payload.get("fresh") is not None and payload.get("fresh") is not True
            if marked_stale:
                label = f"{label} (payload fresh={payload.get('fresh')!r}: read as stale)"
                if p_age is None or p_age <= STALE_SOFT:
                    p_age = STALE_SOFT + 1
            if not all(isinstance(row, dict) and isinstance(row.get("provider"), str)
                       and row["provider"] and isinstance(row.get("pool_family"), (str, type(None)))
                       for row in payload["available"]):
                label = f"{label}: invalid row"
            else:
                try:
                    # a row without a usable age is stale, never fresh
                    rows = [dict(row, age_seconds=(
                        STALE_HARD + 1 if marked_stale
                        else _clean_age(row.get("age_seconds"))
                        if _clean_age(row.get("age_seconds")) is not None
                        else (p_age if p_age is not None else STALE_HARD + 1)))
                        for row in payload["available"]]
                    fresh = _providers_from_available(rows, p_age)
                except (ValueError, TypeError, AttributeError, OverflowError):
                    label = f"{label}: unparseable rows"
        if canned:
            _log(f"quota from canned ROUTE_AGENT_AIUSE_JSON={os.environ['ROUTE_AGENT_AIUSE_JSON']}"
                 " (overrides ROUTE_AGENT_AIUSE=off and AIUSE_SNAPSHOT)")
        if fresh is None:
            QuotaSource.fallback_reason = label
            _log(f"{label}; using the snapshot file {SNAPSHOT}")
        else:
            QuotaSource.kind = "canned" if canned else "aiuse"
            QuotaSource.detail = label
            if p_age is not None and p_age <= STALE_SOFT:
                for key, info in providers.items():
                    if key not in fresh:
                        providers[key] = dict(info, remaining=0.0,
                                              absent_from_available=True)
            providers.update(fresh)
            if p_age is not None and p_age <= STALE_SOFT:
                _apply_excluded(providers, payload.get("excluded"))
            age = p_age if p_age is not None else age
    else:
        QuotaSource.detail = str(os.environ.get("AIUSE_SNAPSHOT") or SNAPSHOT)
    for svc in SERVICES:
        if svc.shares_pool and svc.name not in providers and svc.shares_pool in providers:
            providers[svc.name] = dict(providers[svc.shares_pool])
    if age is not None and age > STALE_HARD:
        return {}, age
    return providers, age


def hours_to_reset(resets_at: Any, *, now: datetime | None = None) -> float | None:
    """Hours until `resets_at` (ISO), or None when unparseable.

    A reset already in the past returns 0.0 (not None), so expected waste
    equals remaining — the window has refilled.
    """
    if not resets_at:
        return None
    try:
        stamp = datetime.fromisoformat(str(resets_at).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        now = now or datetime.now(UTC)
        return max(0.0, (stamp - now).total_seconds() / 3600.0)
    except (ValueError, TypeError):
        return None


def expected_waste(remaining: float | None, pace_ratio: Any,
                   resets_at: Any, window_minutes: Any,
                   *, now: datetime | None = None) -> float | None:
    """Unused share of the binding window at reset if current pace holds.

    projected_use ≈ pace × (100 / W_hours) × t_hours; waste = max(0, r − that).
    Missing pace_ratio assumes p = 1. Missing resets_at or window_minutes →
    unknown (None). Operator /steps 1.6, 2026-10-18.
    """
    if remaining is None or resets_at is None or window_minutes is None:
        return None
    try:
        w_hours = float(window_minutes) / 60.0
        if w_hours <= 0:
            return None
        t = hours_to_reset(resets_at, now=now)
        if t is None:
            return None
        p = 1.0 if pace_ratio is None else float(pace_ratio)
        projected = p * (100.0 / w_hours) * t
        return max(0.0, float(remaining) - projected)
    except (ValueError, TypeError):
        return None


def grant_waste(remaining: float | None, resets_at: Any, grant_days: int,
                *, now: datetime | None = None) -> float | None:
    """Percent points of an expiring grant held above an even spend over its period.

    omp's Claude API credits (operator 2026-10-19: spend them before each monthly reset)
    have an expiry and no window or pace, so expected_waste() returns None for them. An
    even spend leaves 100 x (hours left / period hours) percent; anything above that is
    ahead of schedule and, at the reset, wasted if nothing burns it. Unknown balance or
    expiry, or no grant period, gives None.
    """
    if remaining is None or not grant_days or grant_days <= 0:
        return None
    t = hours_to_reset(resets_at, now=now)
    if t is None:
        return None
    fair_left = 100.0 * min(1.0, t / (grant_days * 24.0))
    return max(0.0, float(remaining) - fair_left)


def omp_anthropic_ready() -> bool:
    """True when omp holds an enabled Anthropic credential (the Claude API credits path).

    omp's agent.db keeps one row per login; a refresh failure sets `disabled_cause` and the
    login needs `omp login` again (2026-10-19: the Anthropic OAuth refresh token had expired
    on 2026-10-13, so every `omp --model anthropic/...` run ended "No API key found for
    anthropic"). Reads only provider and disabled_cause, never the credential. Env
    ROUTE_AGENT_OMP_READY=1/0 forces the answer (tests, a deliberate override)."""
    forced = os.environ.get("ROUTE_AGENT_OMP_READY", "").strip().lower()
    if forced:
        return forced in ("1", "true", "yes")
    base = Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".omp" / "agent")
    db = base / "agent.db"
    if not db.is_file():
        return False
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        try:
            row = con.execute("select count(*) from auth_credentials where "
                              "provider = 'anthropic' and disabled_cause is null").fetchone()
        finally:
            con.close()
        return bool(row and row[0])
    except Exception:  # noqa: BLE001 - an unreadable db means not ready
        return False


READY_PROBES = {"omp-anthropic": omp_anthropic_ready}


def service_ready(svc: Service) -> bool:
    """False when the service names a readiness probe that fails now."""
    probe = READY_PROBES.get(svc.ready_probe) if svc.ready_probe else None
    return True if probe is None else bool(probe())


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


# DEFAULT_PROFILE, NEVER_ROUTE, OPERATOR_GATED and ALIASES
# come from config/routing.toml via apply_policy.


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

# The fleet governor (bin/claude-fleet-governor) writes `level` here every 5 minutes. While it says
# tight or critical and is fresh, the Claude subscription is treated as an exhausted pool for the
# kinds below (2026-10-23: `plan --kind code` printed `claude 30% left` with the 5-hour window
# projected to run out before its reset).
def frontier_gate() -> dict[str, float]:
    """The effective `frontier` gate (config/gates.toml [frontier]: the standing allowance since 2026-10-27, all-closed when the file is
    unreadable; bin/ade_gates.py). Re-read per call: a profile can end or be cleared while a long process runs, and the file is tiny."""
    return ade_gates.load_frontier()[0]


def frontier_per_wave(pool: str, gate: dict[str, float] | None = None, quota: dict[str, Any] | None = None,
                      now: datetime | None = None) -> int:
    """Most frontier slices one wave puts on `pool`: frontier1_per_wave for claude, frontier2_per_wave for every other pool.

    A cap above the closed per-wave (ade_gates.FRONTIER_DEFAULTS, 1) is the standing allowance (gates.toml, docs/gates.md), and it holds only
    while that allowance's own checks pass (2026-10-27, adversary round 1 P1): the family's `*_judged` key at 1 or more, and
    `ade_gates.judged_pool_block` (the one copy acp-dispatch's grant uses) empty: for claude a fresh quota guard state at ok or at watch for
    the weekly window with the Fable cap above its floor, so a missing, stale, tight or critical guard falls back to the closed cap; for
    any other pool its reading in `quota` at least frontier2_min_left. Otherwise the closed per-wave."""
    gate = gate or frontier_gate()
    fam = 1 if pool == "claude" else 2
    cap = int(gate[f"frontier{fam}_per_wave"])
    closed = int(ade_gates.FRONTIER_DEFAULTS[f"frontier{fam}_per_wave"])
    if cap <= closed:
        return cap
    if gate.get(f"frontier{fam}_judged", 0) < 1:
        return closed
    block = ade_gates.judged_pool_block(fam, gate, now or datetime.now(UTC), ade_gates.read_guard_state() if fam == 1 else None,
                                        ((quota or {}).get(pool) or {}).get("remaining"))
    return closed if block else cap


GOVERNOR_STATE = Path.home() / ".local" / "state" / "ade" / "fleet-governor.json"   # CLAUDE_GOVERNOR_STATE overrides
GOVERNOR_FRESH = 30 * 60
GOVERNOR_HOLD_KINDS = frozenset({"code", "bulk", "research", "mechanical"})
GOVERNOR_JUDGMENT_MODEL = "anthropic/claude-opus-5-5 --effort high"


def governor_hold(now: datetime | None = None) -> str | None:
    """Why the Claude subscription is off limits right now, or None.

    Reads CLAUDE_GOVERNOR_STATE (re-read per call: a tiny file); tight/critical and `checked_at`
    under 30 minutes old counts. Missing, unreadable, older or `ok`/`stale` state holds nothing."""
    path = Path(os.environ.get("CLAUDE_GOVERNOR_STATE") or GOVERNOR_STATE)
    try:
        state = json.loads(path.read_text())
        level = state.get("level")
        checked = datetime.fromisoformat(str(state.get("checked_at")).replace("Z", "+00:00"))
    except (OSError, ValueError, AttributeError, TypeError):
        return None
    if level not in ("tight", "critical"):
        return None
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=UTC)
    now = now or datetime.now(UTC)
    if not 0 <= (now - checked).total_seconds() <= GOVERNOR_FRESH:
        return None
    windows = state.get("windows")
    wins = [(k, w) for k, w in (windows.items() if isinstance(windows, dict) else ())
            if isinstance(w, dict) and w.get("level") == level
            and isinstance(w.get("projected_at_reset"), (int, float))]   # a corrupt state never stops routing (round 1 LOW 6)
    top_kind, top = max(wins, key=lambda kw: kw[1]["projected_at_reset"], default=("", None))
    detail = ""
    if top:  # fixed names and numbers only: nothing free-form from the state file reaches an agent-facing text
        name = {"five_hour": "5-hour", "weekly": "weekly", "fable_weekly": "weekly Fable"}.get(top_kind, "window")
        used, proj = top.get("used"), top.get("projected_at_reset")
        at = str(top.get("resets_at"))
        at = at if re.fullmatch(r"[0-9T:.+Z-]{10,40}", at) else "?"
        detail = (f" ({name} {used:.0f}% used, projected {proj:.0f}% at reset {at})"
                  if isinstance(used, (int, float)) and isinstance(proj, (int, float)) else "")
    return f"Claude subscription {level} per claude-fleet-governor{detail}"


@dataclass
class Choice:
    service: Service
    remaining: float | None
    score: float
    why: str = ""
    alternatives: list[str] = field(default_factory=list)
    model: str = ""                 # "<model> [--effort L]" for acp-run
    kind: str = ""                  # required by acp-dispatch (2026-10-18)

    @property
    def dispatch(self) -> str:
        """The acp-dispatch line for this choice (add --name/--task/-C/-f)."""
        agent = self.service.acp_agent
        extra = DISPATCH_EXTRA.get(agent, "")
        kind = f" --kind {self.kind}" if self.kind else ""
        if self.model:
            # Quote only the model id: suggest_model may append " --effort …".
            # zcode ids contain a backslash (builtin:zai-coding-plan\GLM-5.3).
            parts = self.model.split(None, 1)
            model = shlex.quote(parts[0]) + (f" {parts[1]}" if len(parts) > 1 else "")
            return f"acp-dispatch {agent} --model {model}{extra}{kind}"
        return f"acp-dispatch {agent} --model <id from: acp-run {agent} --info>{kind}"


# DISPATCH_EXTRA comes from [dispatch].extra in config/routing.toml.


def suggest_model(svc: Service, kind: str, info: dict[str, Any]) -> str:
    """The model/effort to pass for `kind` on `svc`, from its profile.

    claude's frontier slot is Fable 5.1 while the Fable sublimit (at most 50%
    of the shared weekly) has room, else Opus at the same effort."""
    model = svc.models.get(kind, "")
    if svc.name == "opencode-go" and model:
        from go_model_policy import classification
        if classification(model.split()[0]) != "routine":
            raise ValueError("routine Go routing requires a classified routine model")
    if svc.name == "claude" and kind == "frontier":
        fable = (info.get("sublimits") or {}).get("fable")
        if fable is not None and fable < frontier_gate()["frontier1_min_left"]:
            model = "opus --effort high"
    return model


def quality_best(kind: str, services: list[Service],
                 exclude: frozenset[str] | set[str] = frozenset(),
                 quota: dict[str, Any] | None = None) -> Service | None:
    """The best-ranked pool eligible for `kind` (headroom aside, bar the `plenty_kinds` gate,
    which reads `quota`) that anchors the quality band ([routing].quality_max_rank_gap).
    Reserves and excluded pools never anchor it."""
    pool = [s for s in services
            if s.eligible(kind, quota) and s.name not in exclude and not s.reserve_floor]
    return min(pool, key=lambda s: (s.rank_for(kind), s.name), default=None)


def unrouted_why(kind: str, quota: dict[str, Any] | None = None,
                 exclude: frozenset[str] | set[str] = frozenset()) -> str:
    """Why route() found nothing for `kind`, for plan's queued line."""
    gap = QUALITY_MAX_RANK_GAP.get(kind)
    hold = governor_hold() if kind in GOVERNOR_HOLD_KINDS else None
    if hold:
        exclude = frozenset(exclude) | {"claude"}
    best = quality_best(kind, list(discover(quota or {})), exclude, quota)
    note = f" ({hold})" if hold else ""
    if gap is None or best is None:
        return "no pool has room: keep queued" + note
    return (f"no pool within {gap} rank steps of the best for {kind} ({best.name} "
            f"r{best.rank_for(kind)}) has room; weaker pools are not used for {kind} "
            f"([routing].quality_max_rank_gap): keep queued until a reset" + note)


def route(kind: str, *, quota: dict[str, Any] | None = None,
          min_headroom: float = 15.0,
          exclude: frozenset[str] | set[str] = frozenset()) -> Choice | None:
    """Choose a service for `kind`, preferring idle paid capacity for bulk.

    Score = rank + (100 − remaining) × weight / 10, then pace/reset adjustments
    (2026-10-18): burn_first_bonus when expected waste at reset is high (or the
    static TOML flag when waste is unknown), and a pace_penalty when the
    binding window is burning ahead of schedule.

    `exclude` names services to skip (full for this wave, or just failed)."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    quota = {} if quota is None else quota
    services = list(discover(quota))
    hold = governor_hold()
    held = hold is not None and (kind in GOVERNOR_HOLD_KINDS or kind == "judgment")
    if hold and kind == "judgment":
        omp = next((s for s in services if s.name == "omp"), None)
        info = quota.get("omp") or {}
        remaining = info.get("remaining")
        if (omp is not None and "omp" not in exclude and omp.eligible(kind) and service_ready(omp)
                and (remaining is None or remaining >= max(min_headroom, omp.reserve_floor))):
            return Choice(omp, remaining, 0.0, f"judgment: {omp.cli}; Claude API credits, off the "
                          f"subscription: {hold}", [], model=GOVERNOR_JUDGMENT_MODEL, kind=kind)
        held = False                        # omp cannot take it: Opus judgment may still use claude
    if held:
        exclude = frozenset(exclude) | {"claude"}
    best = quality_best(kind, services, exclude, quota)
    gap = QUALITY_MAX_RANK_GAP.get(kind)

    scored: list[tuple[float, Service, float | None, list[str]]] = []
    for svc in services:
        if not svc.eligible(kind, quota) or svc.name in exclude:
            continue
        if kind != "api-only" and not service_ready(svc):
            continue                       # e.g. omp without a working Anthropic login
        if gap is not None and best is not None and svc.rank_for(kind) - best.rank_for(kind) > gap:
            continue                       # outside the quality band: quota never buys this pool in
        info = quota.get(svc.name) or {}
        remaining = info.get("remaining")
        if remaining is not None and remaining < max(min_headroom, svc.reserve_floor):
            continue                       # too tight to hand work to, or a reserve at its floor
        if remaining is None and svc.reserve_floor:
            continue                       # a reserve with no fresh reading fails closed (review 2026-10-15)
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
        tags: list[str] = []
        waste = expected_waste(remaining, info.get("pace_ratio"),
                               info.get("resets_at"), info.get("window_minutes"))
        grant = False
        if waste is None and svc.grant_days:
            waste = grant_waste(remaining, info.get("resets_at"), svc.grant_days)
            grant = waste is not None
        if waste is not None:
            # Reserves keep their floor gate; never boost them to burn unused
            # quota (2026-10-18 review finding 6c).
            if waste >= BURN_FIRST_WASTE_MIN and not svc.reserve_floor:
                rank -= BURN_FIRST_BONUS
                if grant:
                    tags.append(f"burn before reset: {waste:.0f}% of the grant is ahead "
                                "of an even spend and expires unspent otherwise")
                else:
                    tags.append(f"would waste {waste:.0f}% at reset")
        elif svc.burn_first and remaining is not None and remaining >= BURN_FIRST_MIN:
            # Static TOML fallback only when waste cannot be computed.
            rank -= BURN_FIRST_BONUS
        pace = info.get("pace_ratio")
        if pace is not None:
            try:
                pace_f = float(pace)
            except (ValueError, TypeError):
                pace_f = None
            if pace_f is not None and pace_f > PACE_PENALTY_ABOVE:
                pen = PACE_PENALTY
                if kind in ("judgment", "frontier"):
                    pen = pen * PACE_PENALTY_JUDGMENT_FACTOR
                rank += pen
                tags.append(f"pace {pace_f:.1f}× (penalty {pen:g})")
        scored.append((rank, svc, remaining, tags))

    if not scored:
        return None
    scored.sort(key=lambda t: (t[0], t[1].name))
    best_score, best, remaining, tags = scored[0]
    why = [f"{kind}: {best.cli}"]
    if remaining is not None:
        why.append(f"{remaining:.0f}% headroom")
    why.extend(tags)
    if best.billing == "free":
        why.append("free tier")
    elif kind in ("bulk", "mechanical") and remaining is not None and remaining > 80:
        why.append("idle paid capacity")
    if best.reserve_floor:
        why.append(f"RESERVE: floor {best.reserve_floor:.0f}% left, one small slice, "
                   "check the window first")
    if best.note:
        why.append(best.note)
    if held:
        why.append(f"claude skipped: {hold}")
    return Choice(best, remaining, best_score, "; ".join(why),
                  [s.name for _, s, _, _ in scored[1:4]],
                  model=suggest_model(best, kind, quota.get(best.name) or {}),
                  kind=kind)


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
    frontier: dict[str, int] = {}
    full = set(exclude)
    out: list[tuple[str, Choice | None]] = []
    for kind in kinds:
        skip = full
        if kind == "frontier":
            gate = frontier_gate()
            skip = full | {n for n, k in frontier.items() if k >= frontier_per_wave(n, gate, quota)}
        choice = route(kind, quota=quota, min_headroom=min_headroom, exclude=skip)
        if choice is not None:
            name = choice.service.name
            load[name] = load.get(name, 0) + 1
            if kind == "frontier":
                frontier[name] = frontier.get(name, 0) + 1
            if load[name] >= choice.service.max_parallel:
                full.add(name)
        out.append((kind, choice))
    return out


# HERMES_MODELS and HERMES_PROVIDER_NAME come from [hermes] in config/routing.toml.


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


# The main-loop ("Dann") substrate chain: Flash-primary, provider failover.
# Primary and fallback serve the SAME model (deepseek-v4.1-flash), so a provider
# failover does not change the model — which is what makes it safe against
# Paseo's per-provider constraint: `set_agent_model` refuses a provider other
# than the agent's, so a cross-provider move is a NEW session, never a live
# switch (that is what killed the ◈ Dann tab on 2026-10-23). A within-provider
# switch is lifecycle-safe but must also pass the model cost policy.
# Source of truth: spec/composite-individual/deepseek-cost-routing.md.
DANN_SUBSTRATE: tuple[tuple[str, str, str], ...] = (
    ("opencode-go", "opencode", "opencode-go/deepseek-v4.1-flash"),
    ("clinepass", "cline", "cline-pass/deepseek-v4.1-flash"),
)
# Costly Go models are explicit bounded advisors, never main-loop escalations.
# A measured pool below this much headroom is "tight": still in the chain, but
# an unmeasured pool is not preferred over it.
SUBSTRATE_MIN_HEADROOM = 10.0


def _substrate_pool_state(pool: str, quota: dict[str, Any] | None,
                          accounts: list[dict[str, Any]]) -> dict[str, Any]:
    """Binding allowance across all measured windows, including monthly.

    Wide-open rate windows do not replenish an exhausted monthly budget. Keep
    monthly headroom visible, but never skip it to promote a spent Go pool.
    """
    for a in accounts:
        if a.get("provider") != pool:
            continue
        wins = a.get("windows") or []

        def rem(w: dict[str, Any]) -> float | None:
            return w.get("remaining_percent")

        def is_month(w: dict[str, Any]) -> bool:
            return "month" in ((w.get("label") or "").lower())

        measured = [rem(w) for w in wins if rem(w) is not None]
        monthly = next((rem(w) for w in wins if is_month(w)), None)
        if a.get("usable_now") is False or any(w.get("state") == "exhausted" for w in wins):
            remaining: float | None = 0.0
        else:
            remaining = min(measured) if measured else None
        return {"remaining": remaining, "monthly": monthly}
    # not in the raw snapshot (clinepass is operator-disabled from collection):
    # fall back to the filtered quota dict, else unknown.
    return {"remaining": (quota or {}).get(pool, {}).get("remaining"), "monthly": None}


def substrate_chain(quota: dict[str, Any] | None = None,
                    accounts: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Order the main-loop substrates: healthy-measured first, unmeasured lifeline last.

    Both Flash entries serve deepseek-v4.1-flash, so a provider failover keeps
    the model constant. `remaining` is None for a pool aiuse does not measure
    (clinepass is operator-disabled from collection); such a pool sorts last but
    is never dropped — it is the reserved lifeline, and it is the fallback when
    the measured pool is tight.
    """
    quota = quota or {}
    accounts = accounts or []
    states = {p: _substrate_pool_state(p, quota, accounts) for p, _, _ in DANN_SUBSTRATE}

    def key(item: tuple[str, str, str]) -> tuple[int, float]:
        rem = states[item[0]]["remaining"]
        if rem is None:
            return (1, 0.0)                       # unmeasured lifeline: after healthy, before tight
        if rem >= SUBSTRATE_MIN_HEADROOM:
            return (0, -rem)                      # healthy -> first, most headroom wins
        if rem > 0:
            return (2, -rem)                      # tight -> yield to the lifeline
        return (3, 0.0)                           # exhausted -> last

    chain: list[dict[str, Any]] = []
    for i, (pool, provider, model) in enumerate(sorted(DANN_SUBSTRATE, key=key)):
        chain.append({
            "role": "primary" if i == 0 else "fallback",
            "pool": pool, "provider": provider, "model": model,
            "remaining": states[pool]["remaining"], "monthly": states[pool]["monthly"],
        })
    return chain


def apply_substrate(agent: str, chain: list[dict[str, Any]]) -> str:
    """Apply the chain's primary to `agent` IF it is a within-provider move.

    `paseo-set-model` talks to the daemon's own `set_agent_model` RPC, which
    only sets a model *within* the agent's provider. So a cross-provider move is
    refused here with the start-a-new-session instruction rather than attempted
    (attempting it is what breaks the session).
    """
    helper = Path(__file__).resolve().parent / "paseo-set-model"
    proc = subprocess.run([str(helper), "list", "--json"], capture_output=True, text=True)
    if proc.returncode != 0:
        return f"cannot list agents (rc={proc.returncode}): {proc.stderr.strip()[:200]}"
    try:
        agents = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return "cannot parse paseo-set-model list output"
    match = [a for a in agents if str(a.get("id", "")).startswith(agent)]
    if not match:
        return f"no such agent: {agent}"
    cur = match[0]
    primary = chain[0]
    if cur.get("provider") != primary["provider"]:
        return (f"cross-provider: {agent} is {cur.get('provider')}/{cur.get('model')}; "
                f"start a NEW session on {primary['provider']}/{primary['model']} "
                f"(set_agent_model cannot switch providers)")
    proc = subprocess.run([str(helper), "set", agent, primary["model"]],
                          capture_output=True, text=True)
    return (proc.stdout.strip() or proc.stderr.strip()
            or f"set rc={proc.returncode} ({primary['model']})")


JEV = Path(__file__).resolve().parent / "jev"

# Dispatch state root (same default as acp-dispatch). Overridable for tests.
ACP_DISPATCH_STATE = Path(os.environ.get("ACP_DISPATCH_STATE")
                          or (Path.home() / ".local" / "state" / "bigteam"))

# Copied from bin/acp-dispatch (do not import: slice B edits that file). Agent
# name → (aiuse provider, pool_family). agy/cursor/opencode are model-dependent.
_AGENT_PROVIDER_MAP: dict[str, tuple[str, str | None]] = {
    "claude": ("claude", None),
    "codex": ("codex", None),
    "copilot": ("copilot", None),
    "cursor": ("cursor", None),
    "cursor-cloud": ("cursor-cloud", None),
    "cline": ("clinepass", None),
    "opencode": ("opencode-go", None),
    "zcode": ("zai", None),
    "grok": ("grok", None),
}


def map_agent_to_provider(agent: str, model: str | None) -> tuple[str, str | None] | None:
    """Map acp agent and model to aiuse (provider, pool_family). None if unknown.

    Kept in sync with acp-dispatch.map_agent_to_provider by hand (2026-10-18);
    calibrate must not import acp-dispatch while that file is mid-edit.
    """
    if agent == "agy":
        if model and model.startswith(("claude-", "gpt-")):
            return "antigravity", "claude_gpt"
        if model and model.startswith("gemini-"):
            return "antigravity", "gemini"
        return None
    if agent == "cursor":
        if not model or model in ("default", "auto"):
            return "cursor", "auto"
        return "cursor", None
    if agent == "opencode":
        if model and model.startswith("opencode-go/"):
            return "opencode-go", None
        if model and ("free" in model or model.startswith("opencode-zen-free/")):
            return "opencode-zen-free", None
        if model and model.startswith("opencode-zen/"):
            return "opencode-zen", None
    return _AGENT_PROVIDER_MAP.get(agent)


def dispatch_service_name(agent: str, model: str | None) -> str:
    """Routing service key for a dispatch record's agent+model."""
    mapping = map_agent_to_provider(agent, model)
    if mapping is None:
        return agent or "?"
    return pool_service(mapping[0], mapping[1])


def _is_test_placeholder(rec: dict[str, Any]) -> bool:
    """Skip synthetic pytest / temp-dir acp-run records."""
    if rec.get("model") == "m1":
        return True
    cmd = str(rec.get("cmd") or "")
    for part in cmd.split():
        if "acp-run" not in part:
            continue
        if "/tmp/" in part or "/var/folders/" in part or "/pytest" in part:
            return True
    return False


def _iter_job_records(state_dir: Path | None = None) -> list[dict[str, Any]]:
    """Every `*/jobs/*.json` and `*/*/jobs/*.json` under the dispatch state dir."""
    root = state_dir or ACP_DISPATCH_STATE
    out: list[dict[str, Any]] = []
    for pat in ("*/jobs/*.json", "*/*/jobs/*.json"):
        for path in sorted(glob.glob(str(root / pat))):
            try:
                data = json.loads(Path(path).read_text())
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                data = dict(data)
                data["_path"] = path
                out.append(data)
    return out


def _record_when(rec: dict[str, Any]) -> datetime | None:
    """Best timestamp for --since filtering: finished, else started.

    Real dispatch records store epoch floats; ISO strings remain accepted.
    The `done` key is a report path, never a timestamp.
    """
    for key in ("finished", "started"):
        raw = rec.get(key)
        if raw is None or raw == "":
            continue
        if isinstance(raw, (int, float)):
            try:
                return datetime.fromtimestamp(float(raw), UTC)
            except (ValueError, OSError, OverflowError):
                continue
        try:
            stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
            return stamp
        except (ValueError, TypeError):
            continue
    return None


def _no_report_class(rec: dict[str, Any]) -> str | None:
    """Class after `NO-REPORT:` in detail/failure, or status==no-report → 'no-report'."""
    for key in ("detail", "failure"):
        text = str(rec.get(key) or "")
        if text.startswith("NO-REPORT:"):
            rest = text[len("NO-REPORT:"):].strip()
            parts = rest.split("(", 1)[0].strip().split()
            return parts[0].lower() if parts else "no-report"
    if rec.get("status") == "no-report":
        return "no-report"
    return None


def _suggest_basis_counts(recs: list[dict[str, Any]]) -> tuple[int, int]:
    """(n, done) for suggestion rates: finished, non-quota, non-unavailable."""
    n = done = 0
    for rec in recs:
        if _no_report_class(rec) == "quota":
            continue
        if rec.get("unavailable_class") is not None or rec.get("status") == "unavailable":
            continue
        n += 1
        if rec.get("status") == "done":
            done += 1
    return n, done


def _median_or_none(vals: list[float]) -> float | None:
    if not vals:
        return None
    return float(statistics.median(vals))


def calibrate_report(*, since_days: float | None = None, min_n: int | None = None,
                     state_dir: Path | None = None,
                     now: datetime | None = None) -> dict[str, Any]:
    """Summarise dispatch outcomes for re-ranking good_at.

    Schema (read-only; `acp-dispatch outcome RECORD --ci/--review/--merged` writes it):
      outcome.ci      — "pass" | "fail"
      outcome.review  — "pass" | "fail"
      outcome.merged  — bool

    Groups by service × model × kind (missing kind → `?`). Skips model `m1`
    and temp-dir fake acp-run cmds. Running / unfinished records are counted
    as `in_flight` and excluded from groups. Suggestions compare each
    service×kind done rate (finished, non-quota, non-unavailable) to the
    median of at least `[calibrate].min_peers` other services eligible for
    that kind, when n ≥ min (config `[calibrate].min_outcomes`).
    """
    min_n = CALIBRATE_MIN_OUTCOMES if min_n is None else int(min_n)
    now = now or datetime.now(UTC)
    cutoff = None if since_days is None else now - timedelta(days=float(since_days))

    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    in_flight = 0
    for rec in _iter_job_records(state_dir):
        if _is_test_placeholder(rec):
            continue
        when = _record_when(rec)
        if cutoff is not None and (when is None or when < cutoff):
            continue
        if rec.get("status") == "running" or rec.get("finished") is None:
            in_flight += 1
            continue
        agent = str(rec.get("agent") or "?")
        model = rec.get("model")
        model_s = "?" if model is None else str(model)
        kind = rec.get("kind")
        kind_s = "?" if not kind else str(kind)
        service = dispatch_service_name(agent, None if model is None else str(model))
        groups.setdefault((service, model_s, kind_s), []).append(rec)

    group_rows: list[dict[str, Any]] = []
    for (service, model, kind), recs in sorted(groups.items()):
        n = len(recs)
        done = sum(1 for r in recs if r.get("status") == "done")
        no_report = 0
        quota_stop = 0
        for r in recs:
            cls = _no_report_class(r)
            if cls is not None:
                no_report += 1
                if cls == "quota":
                    quota_stop += 1
            elif r.get("unavailable_class") == "quota":
                quota_stop += 1
        usage = [float(r["measured_usage_pct"])
                 for r in recs if r.get("measured_usage_pct") is not None]
        win_vals: dict[str, list[float]] = {}
        for r in recs:
            windows = r.get("measured_usage_windows") or {}
            if isinstance(windows, dict):
                for label, val in windows.items():
                    if val is None:
                        continue
                    try:
                        win_vals.setdefault(str(label), []).append(float(val))
                    except (ValueError, TypeError):
                        pass
        ci_n = rev_n = merged_n = 0
        ci_pass = rev_pass = merged_true = 0
        for r in recs:
            out = r.get("outcome")
            if not isinstance(out, dict):
                continue
            if out.get("ci") in ("pass", "fail"):
                ci_n += 1
                if out["ci"] == "pass":
                    ci_pass += 1
            if out.get("review") in ("pass", "fail"):
                rev_n += 1
                if out["review"] == "pass":
                    rev_pass += 1
            if isinstance(out.get("merged"), bool):
                merged_n += 1
                if out["merged"]:
                    merged_true += 1
        group_rows.append({
            "service": service,
            "model": model,
            "kind": kind,
            "n": n,
            "done": done,
            "done_rate": round(100.0 * done / n, 1) if n else 0.0,
            "no_report": no_report,
            "quota_stop": quota_stop,
            "median_measured_usage_pct": _median_or_none(usage),
            "median_measured_usage_windows": {
                k: _median_or_none(v) for k, v in sorted(win_vals.items())
            },
            "outcome": {
                "ci_pass_rate": (round(100.0 * ci_pass / ci_n, 1) if ci_n else None),
                "review_pass_rate": (round(100.0 * rev_pass / rev_n, 1) if rev_n else None),
                "merged_rate": (round(100.0 * merged_true / merged_n, 1) if merged_n else None),
                "n_ci": ci_n, "n_review": rev_n, "n_merged": merged_n,
            },
        })

    # Suggestions: aggregate by service × kind (models folded). Rates use the
    # non-quota / non-unavailable basis; raw table counts stay above.
    # kind=? is a reporting bucket for legacy records with no kind — it is not
    # a good_at key, so never suggest a rank change for it (2026-10-18).
    sk: dict[tuple[str, str], dict[str, float]] = {}
    for (service, _model, kind), recs in groups.items():
        if kind == "?":
            continue
        sn, sd = _suggest_basis_counts(recs)
        key = (service, kind)
        agg = sk.setdefault(key, {"n": 0.0, "done": 0.0})
        agg["n"] += sn
        agg["done"] += sd

    # Peer medians: eligible services with n ≥ min; need ≥ min_peers others.
    by_kind: dict[str, list[tuple[str, float, float]]] = {}
    for (service, kind), agg in sk.items():
        if agg["n"] < min_n:
            continue
        svc = BY_NAME.get(service)
        if svc is None or not svc.eligible(kind, any_headroom=True):
            continue
        rate = 100.0 * agg["done"] / agg["n"]
        by_kind.setdefault(kind, []).append((service, rate, agg["n"]))

    suggestions: list[dict[str, Any]] = []
    for kind, peers in sorted(by_kind.items()):
        for service, rate, n in peers:
            others = [r for s, r, _ in peers if s != service]
            if len(others) < CALIBRATE_MIN_PEERS:
                continue
            med = float(statistics.median(others))
            delta = None
            reason = None
            if rate < med - CALIBRATE_SUGGEST_WORSE_BELOW:
                delta = CALIBRATE_SUGGEST_WORSE_DELTA
                reason = (f"done_rate {rate:.1f} is >{CALIBRATE_SUGGEST_WORSE_BELOW:g} "
                          f"points below peer median {med:.1f}")
            elif rate > med + CALIBRATE_SUGGEST_BETTER_ABOVE:
                delta = -CALIBRATE_SUGGEST_BETTER_DELTA
                reason = (f"done_rate {rate:.1f} is >{CALIBRATE_SUGGEST_BETTER_ABOVE:g} "
                          f"points above peer median {med:.1f}")
            if delta is None:
                continue
            suggestions.append({
                "service": service,
                "kind": kind,
                "n": int(n),
                "done_rate": round(rate, 1),
                "peer_median_done_rate": round(med, 1),
                "suggest_rank_delta": delta,
                "reason": reason,
            })
    suggestions.sort(key=lambda s: (s["kind"], s["service"]))

    return {
        "generated_at": now.isoformat(),
        "since_days": since_days,
        "min_n": min_n,
        "in_flight": in_flight,
        "groups": group_rows,
        "suggestions": suggestions,
    }


def format_calibrate_table(report: dict[str, Any]) -> str:
    """Human table for `route_agent.py calibrate` (non-JSON)."""
    lines = [
        f"calibrate: {len(report['groups'])} groups, "
        f"{len(report['suggestions'])} suggestions, "
        f"{report.get('in_flight', 0)} in_flight "
        f"(min n={report['min_n']}"
        + (f", since {report['since_days']}d" if report.get("since_days") else "")
        + ")",
        "",
        f"{'service':18} {'model':28} {'kind':10} {'done':8} "
        f"{'n':>4} {'nr':>3} {'q':>3} {'usage%':>7}",
    ]
    for g in report["groups"]:
        done = f"{g['done']}/{g['n']}"
        usage = g["median_measured_usage_pct"]
        usage_s = "—" if usage is None else f"{usage:.1f}"
        lines.append(
            f"{g['service'][:18]:18} {g['model'][:28]:28} {g['kind'][:10]:10} "
            f"{done:8} {g['n']:4d} {g['no_report']:3d} {g['quota_stop']:3d} "
            f"{usage_s:>7}"
        )
    if report["suggestions"]:
        lines += ["", "suggestions:"]
        for s in report["suggestions"]:
            sign = "+" if s["suggest_rank_delta"] > 0 else ""
            lines.append(
                f"  {s['service']} × {s['kind']}: rank {sign}{s['suggest_rank_delta']} "
                f"(done {s['done_rate']}% vs peer median {s['peer_median_done_rate']}%, "
                f"n={s['n']})"
            )
    else:
        lines += ["", "suggestions: (none)"]
    return "\n".join(lines) + "\n"


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
    sub.add_parser("show", help="snapshot age, headroom, pace, expected waste")
    sub.add_parser("services", help="every service discovered right now")
    hc = sub.add_parser("hermes-chain", help="generate Hermes's provider chain")
    hc.add_argument("--apply", action="store_true", help="write it to config.yaml")
    sb = sub.add_parser(
        "substrate",
        help="main-loop substrate chain (Dann: Flash-primary, cline↔opencode-go failover)",
    )
    sb.add_argument("--json", action="store_true")
    sb.add_argument("--apply", metavar="AGENT", default=None,
                    help="apply the primary to this Paseo agent (within-provider only)")
    pol = sub.add_parser("policy", help="print the effective routing policy")
    pol.add_argument("--md", action="store_true",
                     help="markdown tables (services × kinds, gates, caps)")
    cal = sub.add_parser(
        "calibrate",
        help="dispatch outcome report + suggested good_at rank changes",
    )
    cal.add_argument("--since", type=float, default=None, metavar="DAYS",
                     help="only records finished/started within the last DAYS")
    cal.add_argument("--json", action="store_true",
                     help="stable JSON for the monthly AI re-rank job")
    cal.add_argument("--min", type=int, default=None, metavar="N",
                     help="minimum n for suggestions "
                     f"(default [calibrate].min_outcomes={CALIBRATE_MIN_OUTCOMES})")

    args = parser.parse_args(argv)
    if args.command == "calibrate":
        # No snapshot needed; avoid a stale-hard wipe delaying the report.
        report = calibrate_report(since_days=args.since, min_n=args.min)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(format_calibrate_table(report))
        return 0

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
                "quota_source": quota_source_info(),
                "governor_hold": governor_hold(),
                "slices": [{"kind": k, "service": c.service.name if c else None,
                            "cli": c.service.cli if c else None,
                            "agent": c.service.acp_agent if c else None,
                            "model": c.model if c else None,
                            "dispatch": c.dispatch if c else None,
                            "remaining": c.remaining if c else None,
                            "why": c.why if c else unrouted_why(k, quota, skip)}
                           for k, c in rows]}, indent=1))
        else:
            if QuotaSource.fallback_reason:
                print(f"WARNING: {QuotaSource.fallback_reason}; quota below is from the "
                      "snapshot file and misses aiuse's credits override and Admin API "
                      "readings", file=sys.stderr)
            hold = governor_hold()
            if hold:
                print(f"NOTE: {hold}: claude is not routed for code, bulk, research or mechanical "
                      "slices; judgment prefers omp (Claude API credits)", file=sys.stderr)
            if stale:
                print("WARNING: quota snapshot "
                      + ("empty" if not quota else f"{(age or 0) / 60:.0f} min old")
                      + " -> run `aiuse --available --live` first; routing below "
                      "is capability-only for unmeasured pools", file=sys.stderr)
            for i, (k, c) in enumerate(rows, 1):
                if c is None:
                    print(f"{i}. {k:10} -> (none: {unrouted_why(k, quota, skip)}; "
                          "re-plan at the next boundary)")
                else:
                    rem = "" if c.remaining is None else f" {c.remaining:.0f}% left"
                    print(f"{i}. {k:10} -> {c.service.name}{rem}  [{c.service.cli}]"
                          f"  {c.dispatch}")
        return 0

    if args.command == "show":
        print(f"quota source: {quota_source_info()['source']}"
              + (f" (aiuse unavailable: {QuotaSource.fallback_reason})"
                 if QuotaSource.fallback_reason else ""))
        print(f"snapshot: {SNAPSHOT}")
        print(f"age: {'absent' if age is None else f'{age / 60:.1f} min'}"
              f"  (refreshed by launchd com.djbclark.aiuse every 15 min)")
        for name, info in sorted(quota.items(),
                                 key=lambda kv: (kv[1].get("remaining") is None,
                                                 kv[1].get("remaining") or 0)):
            svc = BY_NAME.get(name)
            flag = "" if not svc else ("  [retired]" if svc.retired else
                                       "  [never-bulk]" if svc.never_bulk else "")
            rem = info.get("remaining")
            pace = info.get("pace_ratio")
            hrs = hours_to_reset(info.get("resets_at"))
            waste = expected_waste(rem, pace, info.get("resets_at"),
                                   info.get("window_minutes"))
            if waste is None and svc and svc.grant_days:
                waste = grant_waste(rem, info.get("resets_at"), svc.grant_days)
            extra = []
            if pace is not None:
                try:
                    extra.append(f"pace {float(pace):.2f}×")
                except (ValueError, TypeError):
                    pass
            if hrs is not None:
                extra.append(f"reset in {hrs:.1f}h")
            if waste is not None:
                extra.append(f"waste≈{waste:.0f}%")
            trail = ("  " + ", ".join(extra)) if extra else ""
            print(f"  {name:16} {rem!s:>6}% remaining{trail}{flag}")
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

    if args.command == "substrate":
        chain = substrate_chain(quota, _read_snapshot_file()[0])
        if args.json:
            print(json.dumps({"snapshot_age_s": age, "chain": chain}, indent=2))
        else:
            for e in chain:
                rem = e["remaining"]
                remtxt = "unmeasured" if rem is None else f"{rem:.0f}% left"
                mon = e.get("monthly")
                montxt = "" if mon is None else f"  (monthly {mon:.0f}%)"
                print(f"  {e['role']:9} {e['provider']}/{e['model']:34} {remtxt}{montxt}")
            print("\n  primary→fallback is a PROVIDER failover at session start, not a live")
            print("  switch: Paseo binds one provider per session (set_agent_model refuses a")
            print("  cross-provider change), so a new session starts on the other provider")
            print(f"  with the SAME model. escalate ({DANN_ESCALATION[2]}) is a within-opencode")
            print("  switch and is safe live.")
        if args.apply:
            print("\n  apply:", apply_substrate(args.apply, chain))
        return 0

    if args.command == "policy":
        if args.md:
            sys.stdout.write(policy_markdown())
        else:
            print(json.dumps(policy_public(), indent=2))
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
            "governor_hold": governor_hold(),
            "snapshot_age_seconds": None if age is None else round(age),
            "quota_source": quota_source_info(),
        }, indent=2))
    else:
        print(f"{choice.service.cli}   — {choice.why}")
        print(f"  dispatch: {choice.dispatch}")
        if choice.alternatives:
            print(f"  alternatives: {', '.join(choice.alternatives)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
