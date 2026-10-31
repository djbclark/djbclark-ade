#!/usr/bin/env python3
"""failover — run a task through an ordered chain of agent routes; the first that works wins.

A *chain* is an ordered list of entries (rungs). Each entry names a TUI or
endpoint from the REGISTRY below, a model, an effort, the aiuse pool it draws
and a floor. For every entry, in order:

1. **load-time policy**: an entry is refused outright (ChainError) when it names
   a globally denied route (DENY: cursor, cline/ClinePass, any Opus or Fable model;
   operator 2026-10-12; Hermes admitted 2026-10-13), a TUI outside the caller's
   allowlist, a TUI the registry does not know, a model the TUI's `model_allow`
   rejects, an effort the TUI has no lever for, or a `perm` outside PERMS;
2. **preflight**: the binary exists (`acp-run --list` shows the agent `ok`), the
   pool is `usable_now` in `aiuse --available --json` with headroom above the
   entry's floor, and any secret the entry needs is declared in sudo-secretspec;
3. **attempt**: the caller's function runs the task on that entry; it returns
   ok or a reason. A failure moves on to the next entry.

Every preflight, attempt and prompt retry is one JSON line in the attempt log
(`~/.local/state/failover/attempts.jsonl` unless the caller names one). A preflight
result is cached per (tui, model, effort, pool, floor) for PREFLIGHT_TTL_S inside
run_chain, logged as "preflight cached"; `check` always recomputes (2026-10-13).

Two ways to execute an entry are built in: `ask()` answers one prompt (acp-run in
a clean empty directory with the entry's `--perm`, a fresh context; under `deny`, the
default, acp-run makes deny real per agent, and a tripwire exits 77 if a tool still
runs without asking, which `ask()` turns into AttemptFailed; under `all` (a chain's or
entry's "perm", 2026-10-13: the SkillOpt-Sleep night) the agent may run any tool, with
no tripwire and no canary; or an OpenAI-compatible POST for `openai_compat`
entries, key from sudo-secretspec held in memory once per process, never
redirected), and `run_command()` runs any shell-callable task with the entry's
fields substituted into argv and exported as FAILOVER_*. `ask_many()` answers a
batch on one entry: before every acp-run spawn it runs the caller's `Pacing` gate
(stop hook, then a wait while the load per core is above `max_load`), and it retries
a prompt whose acp-run failed before any turn ran (`StartupFailed`) up to
`Pacing.retries` times with backoff, within a per-round budget (`retry_budget`, else
25% of the round's prompts, at least 3); any other failure fails the batch at once
(2026-10-13: 21 startup failures, no retry, five sources ended chain_exhausted).
Children get a minimal
env (BASE_ENV_KEYS plus the entry's allow-listed env) and run in their own process
group, killed whole on timeout. Preflight's canary asks every `perm: deny` acp entry
to create a file and refuses the entry if it can; `perm: all` entries skip it (their
probe, if marked, is the model check). Every preflight/attempt/retry row carries the
entry's perm.

CLI:
    failover.py registry                                 # the route table
    failover.py check --chain FILE [--allow a,b]          # preflight table, no model calls
    failover.py ask   --chain FILE (-p TEXT | -f FILE)    # answer one prompt via the chain
    failover.py run   --chain FILE -- CMD {model} ...     # any command; first rc 0 wins

A chain FILE is JSON: either a list of entries or {"chain": [...], "allow": [...],
"perm": "deny"|"all"} (perm default "deny"). Entry keys: perm (overrides the chain's),
tui (required), model, effort, floor_percent (default 5), pool and
pool_family (override the registry), endpoint (openai_compat), secret (a
sudo-secretspec name exported as `secret_env`, default OPENAI_API_KEY for
`run`; only to the registry endpoint, https or loopback), env (ENV_ALLOW keys
only), extra_args (appended to acp-run; only EXTRA_ARGS_ALLOWED flags), timeout, label,
probe, health_url, retry_budget (startup-failure retries per ask_many round). Importable: skillopt-night uses load_chain/preflight/run_chain/ask.

Token counts (2026-10-13): `ask()` returns an `Answer(text, usage)`; `usage` is the
backend's own per-prompt counts (acp-run's result record, or the OpenAI `usage` of a
direct POST) as {input, output, cached_read, cached_write, total}, or None when the
backend reports none (agy, crush): such a prompt is unmetered, never zero. Nothing is
estimated. `Pacing.tally` (a `Tally`) collects every answer `ask_many` returns, and
`run_chain(tally=)` puts `prompts` and `tokens` on each attempt row.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import random
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

BIN = Path(__file__).resolve().parent
ATTEMPT_LOG = Path.home() / ".local" / "state" / "failover" / "attempts.jsonl"
DEFAULT_FLOOR = 5.0
# Hard exclusions, matched case-insensitively against tui, acp agent and model
# (operator 2026-10-12): never cursor, never cline/ClinePass, never Claude Opus or
# anything stronger (Fable). Hermes was here until 2026-10-13, when the operator
# admitted it as a backend ("I want all of the TUIs and hermes to be able to run any
# tools they want").
DENY = ("cursor", "cline", "clinepass", "opus", "fable")
# What acp-run --perm an acp entry runs under (2026-10-13). "deny" (the library
# default, every caller but the SkillOpt-Sleep night): acp-run refuses every permission
# request, makes deny real per agent, trips (exit 77) on a tool that runs unasked, and
# preflight runs the deny canary. "all": acp-run allows every request and the agent
# runs its tools freely (no tripwire, no canary; preflight keeps the binary, secret,
# health, pool and probe checks). A chain sets it with a top-level "perm", an entry
# with its own "perm"; nothing else (extra_args never passes --perm).
PERMS = ("deny", "all")
DEFAULT_PERM = "deny"
# The only acp-run flags a chain entry may pass in extra_args, each with a value check
# (None: takes no value). Everything else is refused, so neither a policy flag (acp-run's
# options are last-wins) nor an abbreviation of one (`--per all`, `-Call`) gets through
# (adversary review H1, re-verification R10, 2026-10-12; acp-run also sets
# allow_abbrev=False).
_SET_OK = re.compile(r"(thought|effort)=(low|medium|high|max)")


def _set_value(v: str) -> str:
    """--set may only choose an effort level (zcode thought=, claude effort=)."""
    if not _SET_OK.fullmatch(v):
        raise ValueError(v)
    return v


EXTRA_ARGS_ALLOWED: dict[str, Callable[[str], object] | None] = {
    "--prompt-retries": int, "--handshake-tries": int, "--handshake-timeout": float,
    "--max-load": float, "--load-wait": float, "--no-fallback": None, "--set": _set_value,
}
# The only env keys a chain entry may set for its child (H1); everything else is
# refused at load time (ACP_RUN_*, PATH, OPENCODE_CONFIG*, ZCODE_ACP_MODE, ...).
ENV_ALLOW = ("MAX_THINKING_TOKENS", "ZCODE_PROVIDER", "ZCODE_MODEL")
# What a tool-capable child inherits from us (M2); entry env is added on top.
BASE_ENV_KEYS = ("HOME", "PATH", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "SHELL")
LOOPBACK = ("127.0.0.1", "localhost", "::1")
EXIT_TRIPWIRE = 77  # acp-run: a tool ran without a permission request under --perm deny
EXIT_LOAD = 75      # acp-run: --max-load refused to start the agent (nothing ran)
# Startup-failure retries (2026-10-13 night: every one of 21 failed attempts died in
# initialize, session/new or MCP/plugin loading, and one such prompt failed its whole
# entry). Per prompt: up to PROMPT_RETRIES more tries after RETRY_BACKOFF_S (jittered,
# capped); per ask_many round: at most retry_budget retries, default
# max(RETRY_BUDGET_MIN, RETRY_BUDGET_SHARE x prompts).
PROMPT_RETRIES = 2
RETRY_BACKOFF_S = (20.0, 60.0)
RETRY_BACKOFF_CAP_S = 120.0
RETRY_BUDGET_SHARE = 0.25
RETRY_BUDGET_MIN = 3
# acp-run failure classes that are never a startup failure, even before the first turn.
NOT_RETRIED = ("quota", "plan", "auth", "refused", "tripwire")
# How long run_chain trusts a preflight result, ok or not (2026-10-13: the same refusals
# were recomputed for every source); `check` and `--probe` never use the cache.
PREFLIGHT_TTL_S = 3600.0
ACP_LOG_DIR = Path.home() / ".local" / "state" / "failover" / "acp-logs"
LOG_RETENTION_DAYS = 7


class ChainError(ValueError):
    """A chain entry violates policy or names an unknown route."""


class AttemptFailed(RuntimeError):
    """One entry could not do the task; the chain moves on."""


class StartupFailed(AttemptFailed):
    """acp-run failed before any turn ran (or the load gate never let it spawn): nothing
    reached the model and no tool ran, so ask_many may retry the prompt."""


@dataclass(frozen=True)
class Tui:
    """One route: an ACP agent driven by acp-run, or an OpenAI-compatible endpoint."""

    name: str
    kind: str                                  # "acp" | "openai_compat"
    acp_agent: str | None = None
    vendor: str = ""
    pool: str | None = None                    # aiuse provider id
    pool_family: str | None = None
    pool_by_model: tuple[tuple[str, str | None, str | None], ...] = ()  # (model prefix, pool, family)
    models: tuple[str, ...] = ()               # known ids (illustrative, from live lists)
    model_allow: str | None = None             # regex every model must match
    takes_model: bool = True
    effort: str | None = None                  # "set:<option>" | "flag" | None
    efforts: tuple[str, ...] = ()
    endpoint: str | None = None
    secret: str | None = None                  # sudo-secretspec name for openai_compat
    health_by_model: tuple[tuple[str, str], ...] = ()  # (model prefix, URL that must GET 200)
    native_models: tuple[tuple[str, str], ...] = ()    # acp-run model value -> full model id
    probe: bool = False                        # preflight sends one tiny prompt (no quota pool)
    # "strict": the canary needs zero tool calls. "asked_denied_ok": tool calls are
    # tolerated if every one asked permission and was denied (none allowed, no
    # tripwire). "reads_ok": additionally, calls of a tripwire_exempt (read-only) kind
    # may run unasked. Registry-only, so a chain file cannot loosen it.
    canary: str = "strict"
    # ACP tool kinds acp-run's tripwire lets run without a permission request under
    # --perm deny for this TUI (--tripwire-exempt-kinds); registry-only, read-only kinds.
    tripwire_exempt: tuple[str, ...] = ()
    note: str = ""


# Model lists from acp-dispatch's live probes (~/.cache/acp-dispatch, 2026-10-12)
# and the docs; they are hints, not a gate. `acp-run <agent> --info` is the authority.
REGISTRY: dict[str, Tui] = {t.name: t for t in (
    # claude-agent-acp's model values are default/opus/fable/sonnet/haiku (names "Haiku 5.5",
    # "Sonnet 5.5"); acp-run matches a value, so "claude-haiku-5-5" itself would not resolve.
    # Its `effort` option takes default/low/medium/high/xhigh/max (acp-run claude --info, 2026-10-12).
    Tui("claude", "acp", "claude", "Anthropic", "claude", "default",
        models=("haiku", "sonnet"),
        model_allow=r"^(haiku|sonnet|claude-(haiku|sonnet)-[\w.-]+)$",
        native_models=(("haiku", "claude-haiku-5-5"), ("sonnet", "claude-sonnet-5-5")),
        effort="set:effort", efforts=("low", "medium", "high"),
        note="Claude shared pool; Haiku or Sonnet only (Opus/Fable denied)"),
    Tui("agy", "acp", "agy", "Google", None, None,
        pool_by_model=(("gemini-", "antigravity", "gemini"),
                       ("claude-", "antigravity", "claude_gpt"),
                       ("gpt-", "antigravity", "claude_gpt")),
        models=("gemini-3.8-flash", "claude-sonnet-5-5", "gpt-oss-120b-medium"),
        effort="flag", efforts=("low", "medium", "high"),
        # djbclark 2026-10-12: agy's default mode runs reads (view_file, ACP kind "read")
        # without asking; for agy alone those may run unasked, and every other call
        # (execute, edit, delete, other/MCP, ...) must ask and be denied. Kinds seen in
        # agy's ACP logs: read (view_file), execute (shell, incl. cat/grep), edit,
        # other (MCP such as basic-memory_write_note). Accepted risk: a read can pull
        # file contents into an answer (docs/failover.md).
        canary="reads_ok", tripwire_exempt=("read", "search"),
        note="bare model ids, effort via --effort (thinking_level, agy 1.4.1 2026-10-18); Gemini and Claude/GPT are separate pools"),
    # `opencode models` (2026-10-12) lists opencode-go/kimi-k3, opencode-go/minimax-m3 and the
    # sipb/ provider (~/.config/opencode/opencode.json baseURL http://127.0.0.1:8890/api).
    Tui("opencode", "acp", "opencode", "OpenCode", None, None,
        pool_by_model=(("opencode-go/", "opencode-go", None), ("sipb/", None, None)),
        health_by_model=(("sipb/", "http://127.0.0.1:8890/api/version"),),
        models=("opencode-go/minimax-m3", "opencode-go/kimi-k3", "opencode-go/deepseek-v4-flash",
                "sipb/qwen3-coder:30b", "sipb/deepseek-r1:32b"),
        note="model names its provider: opencode-go/... (Go pool) or sipb/... (MIT SIPB, free)"),
    Tui("zcode", "acp", "zcode", "Z.ai", "zai", None, takes_model=False,
        effort="set:thought", efforts=("low", "high", "max"),
        note="zcode-acp-server refuses --model; GLM via the z.ai plan"),
    Tui("sipb", "openai_compat", None, "MIT SIPB", None, None,
        models=("qwen3-coder:30b", "deepseek-r1:32b"),
        endpoint="http://127.0.0.1:8890/api", secret="MIT_SIPB_API_KEY",
        note="free, slow shared GPU via the loopback sipb-llms-proxy; aiuse has no windows"),
    Tui("codex", "acp", "codex", "OpenAI", "codex", None, note="codex pool (OpenAI subscription)"),
    Tui("copilot", "acp", "copilot", "GitHub", "copilot", None),
    Tui("grok", "acp", "grok", "xAI", "grok", None, note="ordinary pool (GrokBot moved to its own Cursor pool 2026-10-18)"),
    Tui("qwen", "acp", "qwen", "Alibaba", None, None),
    # canary "strict", no tripwire exemption: under --perm deny acp-run disables every
    # crush tool (crush_deny_dir), so the canary sees 0 tool calls (verified 2026-10-13).
    Tui("crush", "acp", "crush", "Charm", None, None, takes_model=False, probe=True,
        note="crush-acp (PR 2450 build), default model from crushrc (SIPB); never --model;"
             " no tools under --perm deny"),
    # `hermes acp` (acp-run AGENTS). Admitted as a backend 2026-10-13 (operator). Hermes
    # picks its own model: ~/.hermes/config.yaml model.default with its free-first
    # fallback_providers chain (which can reach paid routes), so never --model; aiuse has
    # no Hermes pool, so like crush preflight probes it with one tiny prompt.
    Tui("hermes", "acp", "hermes", "Hermes", None, None, takes_model=False, probe=True,
        note="hermes acp; its own free-first model chain with a paid fallback; never --model"),
    # Listed so a chain naming them fails with a clear reason (DENY also catches them).
    Tui("cursor", "acp", "cursor", "Cursor", "cursor", None, note="denied"),
    Tui("cline", "acp", "cline", "ClinePass", "clinepass", None, note="denied: reserve"),
)}


@dataclass
class Entry:
    tui: Tui
    model: str = ""
    effort: str = ""
    floor_percent: float = DEFAULT_FLOOR
    pool: str | None = None
    pool_family: str | None = None
    endpoint: str | None = None
    secret: str | None = None
    secret_env: str = "OPENAI_API_KEY"
    env: dict[str, str] = field(default_factory=dict)
    extra_args: list[str] = field(default_factory=list)
    timeout: int = 600
    label: str = ""
    probe: bool | None = None
    health_url: str | None = None
    retry_budget: int | None = None            # startup retries per ask_many round (None: default)
    perm: str = DEFAULT_PERM                   # acp-run --perm: "deny" | "all" (PERMS)
    # acp-run --strip-user-config: set by the caller (skillopt-night), never by a chain file
    strip_user_config: bool = False

    def __post_init__(self) -> None:
        if not self.label:
            self.label = f"{self.tui.name}:{self.model or 'default'}" + (
                f"@{self.effort}" if self.effort else "")
        if self.pool is None and self.pool_family is None:
            self.pool, self.pool_family = self._registry_pool()
        self.endpoint = self.endpoint or self.tui.endpoint
        self.secret = self.secret or self.tui.secret
        if self.probe is None:
            self.probe = self.tui.probe
        if self.health_url is None:
            self.health_url = next((url for prefix, url in self.tui.health_by_model
                                    if self.model.startswith(prefix)), None)

    def _registry_pool(self) -> tuple[str | None, str | None]:
        for prefix, pool, family in self.tui.pool_by_model:
            if self.model.startswith(prefix):
                return pool, family
        return self.tui.pool, self.tui.pool_family

    @property
    def model_arg(self) -> str:
        """The model id as the TUI expects it (effort never rides in the id)."""
        return self.model

    @property
    def native_model(self) -> str:
        """The full model id for SkillOpt's native backends (--native)."""
        return dict(self.tui.native_models).get(self.model, self.model_arg)

    def row(self) -> dict[str, Any]:
        return {"label": self.label, "tui": self.tui.name, "vendor": self.tui.vendor,
                "model": self.model_arg or None, "effort": self.effort or None,
                "pool": self.pool, "pool_family": self.pool_family,
                "floor_percent": self.floor_percent, "perm": self.perm}


# ── loading and policy ───────────────────────────────────────────────────────

def denied(text: str, deny: tuple[str, ...] = DENY) -> str | None:
    """The first denied word that is a whole token of text (split on non-alphanumerics),
    so "pi" catches "pi" but not "api", and "opus" catches "claude-opus-5-5-low"."""
    tokens = set(re.split(r"[^a-z0-9]+", text.lower()))
    return next((d for d in deny if d in tokens), None)


def _perm_value(where: str, value: Any) -> str:
    if value not in PERMS:
        raise ChainError(f"{where}: perm must be one of {', '.join(PERMS)}, not {value!r}")
    return str(value)


def load_chain(spec: Any, *, allow: list[str] | None = None,
               deny: tuple[str, ...] = DENY, perm: Any = None,
               strip_user_config: bool = False) -> list[Entry]:
    """Validate a chain spec (list, or dict with "chain"/"allow"/"perm") into Entries.

    perm is the chain default (a dict spec's top-level "perm" when the caller passes
    none; DEFAULT_PERM "deny" when neither does); an entry's own "perm" overrides it.
    Both must be in PERMS. strip_user_config is the caller's (not a chain key).
    Refuses the whole chain on the first bad entry: a policy violation is a
    config error to fix, not a rung to skip at 03:30."""
    if isinstance(spec, dict):
        allow = allow if allow is not None else spec.get("allow")
        perm = perm if perm is not None else spec.get("perm")
        spec = spec.get("chain", [])
    chain_perm = _perm_value("chain", DEFAULT_PERM if perm is None else perm)
    if not isinstance(spec, list):
        raise ChainError("chain must be a list of entries")
    entries = []
    for i, raw in enumerate(spec, 1):
        if not isinstance(raw, dict) or not raw.get("tui"):
            raise ChainError(f"entry {i}: needs a 'tui'")
        name = str(raw["tui"])
        model = str(raw.get("model") or "")
        for text in (name, model, str(raw.get("label") or "")):
            hit = denied(text, deny)
            if hit:
                raise ChainError(f"entry {i} ({name} {model}): denied route '{hit}'")
        if allow is not None and name not in allow:
            raise ChainError(f"entry {i}: tui '{name}' is not in the allowlist {sorted(allow)}")
        tui = REGISTRY.get(name)
        if tui is None:
            raise ChainError(f"entry {i}: unknown tui '{name}'")
        if model and not tui.takes_model:
            raise ChainError(f"entry {i}: {name} takes no model (remove '{model}')")
        if model and tui.model_allow and not re.match(tui.model_allow, model):
            raise ChainError(f"entry {i}: model '{model}' not allowed for {name}")
        effort = str(raw.get("effort") or "")
        if effort and effort not in tui.efforts:
            raise ChainError(f"entry {i}: {name} has no effort '{effort}' "
                             f"(levers: {', '.join(tui.efforts) or 'none'})")
        extra = [str(x) for x in raw.get("extra_args") or []]
        check_extra_args(i, extra, deny)
        env = raw.get("env") or {}
        if not isinstance(env, dict):
            raise ChainError(f"entry {i}: env must be an object")
        for k, v in env.items():
            if k not in ENV_ALLOW:
                raise ChainError(f"entry {i}: env key {k!r} is not allowed (allowed: {', '.join(ENV_ALLOW)})")
            hit = denied(str(v), deny)
            if hit:
                raise ChainError(f"entry {i}: env {k} names denied route '{hit}'")
        budget = raw.get("retry_budget")
        if budget is not None and (isinstance(budget, bool) or not isinstance(budget, int) or budget < 0):
            raise ChainError(f"entry {i}: retry_budget must be a whole number >= 0, not {budget!r}")
        entry_perm = _perm_value(f"entry {i}", raw["perm"]) if "perm" in raw else chain_perm
        endpoint = raw.get("endpoint")
        if endpoint and (raw.get("secret") or tui.secret) and endpoint != tui.endpoint:
            u = urllib.parse.urlparse(str(endpoint))
            if not (u.scheme == "https" or (u.scheme == "http" and u.hostname in LOOPBACK)):
                raise ChainError(f"entry {i}: a secret may only go to https or loopback, not {endpoint}")
        entry = Entry(tui=tui, model=model, effort=effort,
                      floor_percent=float(raw.get("floor_percent", DEFAULT_FLOOR)),
                      pool=raw.get("pool"), pool_family=raw.get("pool_family"),
                      endpoint=raw.get("endpoint"), secret=raw.get("secret"),
                      secret_env=str(raw.get("secret_env") or "OPENAI_API_KEY"),
                      env={str(k): str(v) for k, v in env.items()},
                      extra_args=extra,
                      timeout=int(raw.get("timeout", 600)), label=str(raw.get("label") or ""),
                      probe=raw.get("probe"), health_url=raw.get("health_url"),
                      retry_budget=budget, perm=entry_perm,
                      strip_user_config=bool(strip_user_config))
        if denied(entry.model_arg, deny):
            raise ChainError(f"entry {i}: denied model '{entry.model_arg}'")
        entries.append(entry)
    return entries


def check_extra_args(i: int, extra: list[str], deny: tuple[str, ...]) -> None:
    """Raise ChainError unless extra_args is a sequence of EXTRA_ARGS_ALLOWED flags,
    spelled exactly, each with a valid value."""
    for tok in extra:
        hit = denied(tok, deny)
        if hit:
            raise ChainError(f"entry {i}: extra_args token {tok!r} names denied route '{hit}'")
    k = 0
    while k < len(extra):
        tok = extra[k]
        flag, eq, val = tok.partition("=")
        if flag not in EXTRA_ARGS_ALLOWED:
            raise ChainError(f"entry {i}: extra_args may not pass {tok!r} "
                             f"(allowed: {', '.join(EXTRA_ARGS_ALLOWED)})")
        check = EXTRA_ARGS_ALLOWED[flag]
        if check is None:
            if eq:
                raise ChainError(f"entry {i}: {flag} takes no value")
            k += 1
            continue
        if not eq:
            if k + 1 >= len(extra):
                raise ChainError(f"entry {i}: {flag} needs a value")
            val, k = extra[k + 1], k + 1
        try:
            check(val)
        except (ValueError, TypeError) as e:
            raise ChainError(f"entry {i}: bad value {val!r} for {flag}") from e
        k += 1


def load_chain_file(path: Path, *, allow: list[str] | None = None,
                    strip_user_config: bool = False) -> list[Entry]:
    try:
        spec = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise ChainError(f"cannot read chain {path}: {e}") from e
    return load_chain(spec, allow=allow, strip_user_config=strip_user_config)


# ── preflight ────────────────────────────────────────────────────────────────

def acp_run() -> str:
    return (os.environ.get("FAILOVER_ACP_RUN") or shutil.which("acp-run")
            or str(Path.home() / ".local" / "bin" / "acp-run"))


def secretspec() -> str:
    return (os.environ.get("FAILOVER_SECRETSPEC") or shutil.which("sudo-secretspec")
            or "/usr/local/bin/sudo-secretspec")


_cache: dict[str, Any] = {}


def acp_agents_ok() -> set[str]:
    """Agents `acp-run --list` marks ok (route_agent's reader, reused)."""
    if "agents" not in _cache:
        # Load bin/route_agent.py by path (not an implicit relative import), so this works
        # whatever the caller's sys.path and cwd are.
        route_agent = sys.modules.get("route_agent")
        if route_agent is None:
            spec = importlib.util.spec_from_file_location("route_agent", BIN / "route_agent.py")
            if spec is None or spec.loader is None:
                raise ImportError(f"cannot load {BIN / 'route_agent.py'}")
            route_agent = importlib.util.module_from_spec(spec)
            sys.modules["route_agent"] = route_agent  # dataclasses resolve their module here
            spec.loader.exec_module(route_agent)
        _cache["agents"] = route_agent.acp_agents()
    return _cache["agents"]


def available_pools() -> list[dict[str, Any]]:
    """`aiuse --available --json` "available" rows (cached per process; [] on error).

    Shape (aiuse contract 1.2): {provider, pool_family, usable_now, headroom_percent,
    windows[...]}; FAILOVER_AIUSE_JSON names a file to read instead (tests)."""
    if "pools" in _cache:
        return _cache["pools"]
    text = ""
    fixture = os.environ.get("FAILOVER_AIUSE_JSON")
    try:
        if fixture:
            text = Path(fixture).read_text()
        else:
            out = subprocess.run([shutil.which("aiuse") or "aiuse", "--available", "--json"],
                                 capture_output=True, text=True, timeout=180, check=False)
            text = out.stdout
        data = json.loads(text[text.index("{"):])
        rows = data.get("available") or []
    except (OSError, ValueError, subprocess.SubprocessError):
        rows = []
    _cache["pools"] = rows
    return rows


def pool_reading(entry: Entry) -> dict[str, Any] | None:
    """The aiuse row for the entry's pool (and family, when it names one)."""
    for row in available_pools():
        if row.get("provider") != entry.pool:
            continue
        if entry.pool_family and row.get("pool_family") not in (entry.pool_family, None):
            continue
        return row
    return None


def declared_secrets() -> set[str]:
    """Declared names from the value-free `sudo-secretspec schema`."""
    if "secrets" not in _cache:
        try:
            out = subprocess.run([secretspec(), "schema", "--reason",
                                  "failover: check which secrets are declared"],
                                 capture_output=True, text=True, timeout=60, check=False)
            _cache["secrets"] = set(json.loads(out.stdout).get("properties", {}))
        except (OSError, ValueError, subprocess.SubprocessError, AttributeError):
            _cache["secrets"] = set()
    return _cache["secrets"]


def endpoint_reachable(url: str, timeout: float = 3.0) -> bool:
    """TCP connect only: no request, no auth, no model call."""
    parsed = urllib.parse.urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname or "", port), timeout=timeout):
            return True
    except OSError:
        return False


def health_ok(url: str, timeout: float = 10.0) -> bool:
    """GET url answers 200 (an unauthenticated status endpoint: no model call)."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


PROBE_PROMPT = "Reply with exactly: OK"


def probe_ok(entry: Entry) -> tuple[bool, str]:
    """One tiny prompt through the entry (cached per process). This one DOES call the model,
    so it is reserved for routes with no quota pool to read (crush)."""
    key = f"probe:{entry.label}" + (f":{entry.perm}" if entry.perm != DEFAULT_PERM else "")
    if key not in _cache:
        try:
            answer = ask(entry, PROBE_PROMPT).text
            _cache[key] = ("OK" in answer.upper(), f"probe answered {answer[:40]!r}")
        except AttemptFailed as e:
            _cache[key] = (False, f"probe failed: {e}")
    return _cache[key]


def preflight(entry: Entry, *, probe: bool = True) -> tuple[bool, str]:
    """(ok, why). Binary, secret, health URL, pool; then the steps that call the model,
    skipped when probe=False: the probe (entries marked probe) and the canary (every
    acp entry: it must not be able to create a file under --perm deny)."""
    if entry.tui.kind == "acp":
        if not Path(acp_run()).exists():
            return False, f"acp-run not found at {acp_run()}"
        if entry.tui.acp_agent not in acp_agents_ok():
            return False, f"acp-run --list has no ok row for '{entry.tui.acp_agent}'"
    elif not entry.endpoint:
        return False, "no endpoint"
    elif not endpoint_reachable(entry.endpoint):
        return False, f"endpoint {entry.endpoint} not reachable"
    if entry.secret and entry.secret not in declared_secrets():
        return False, f"secret {entry.secret} is not declared in sudo-secretspec"
    if entry.health_url and not health_ok(entry.health_url):
        return False, f"health check {entry.health_url} did not answer 200"
    why = "no quota pool to check"
    if entry.health_url:
        why = f"{entry.health_url} answered 200"
    if entry.pool:
        row = pool_reading(entry)
        if row is None:
            return False, f"pool {entry.pool}/{entry.pool_family or '-'} not in aiuse --available"
        if not row.get("usable_now"):
            return False, f"pool {entry.pool} not usable now"
        head = row.get("headroom_percent")
        if head is None or float(head) <= entry.floor_percent:
            return False, f"pool {entry.pool} headroom {head}% <= floor {entry.floor_percent}%"
        why = f"pool {entry.pool} headroom {float(head):.1f}% > floor {entry.floor_percent}%"
    if entry.tui.kind == "acp" and entry.perm == "all":
        # perm all (2026-10-13): no deny canary (its job is to prove deny holds); the
        # probe, for entries marked probe, is the check that calls the model
        why = f"{why}; perm all: no canary"
        if not probe:
            return True, f"{why}; probe not run (it calls the model)" if entry.probe else why
        if entry.probe:
            ok, pwhy = probe_ok(entry)
            return ok, f"{why}; {pwhy}"
        return True, why
    if not probe:
        extra = "probe and canary" if entry.probe else "canary"
        return True, f"{why}; {extra} not run (it calls the model)" if entry.tui.kind == "acp" else why
    if entry.probe:
        ok, pwhy = probe_ok(entry)
        if not ok:
            return False, f"{why}; {pwhy}"
        why = f"{why}; {pwhy}"
    ok, cwhy = canary_ok(entry)
    return ok, f"{why}; {cwhy}"


def preflight_key(entry: Entry) -> str:
    key = [entry.tui.name, entry.model_arg, entry.effort, entry.pool, entry.pool_family,
           entry.floor_percent]
    if entry.perm != DEFAULT_PERM:  # a perm all result (no canary) never stands in for deny
        key.append(entry.perm)
    return "preflight:" + json.dumps(key)


def preflight_cached(entry: Entry, *, ttl: float = PREFLIGHT_TTL_S,
                     now: Callable[[], float] | None = None) -> tuple[bool, str]:
    """preflight(entry) at most once per ttl seconds per (tui, model, effort, pool, floor),
    failures and successes alike, so a night with eight sources spawns a refused canary
    once instead of once per source (2026-10-13). An expired result also drops the
    process-wide aiuse reading and this entry's canary and probe, so the recheck is real
    (a pool can recover mid-night). run_chain uses it; check_table never does."""
    key, t = preflight_key(entry), (now or time.monotonic)()
    hit = _cache.get(key)
    if hit is not None and t - hit[0] < ttl:
        return hit[1], f"preflight cached ({t - hit[0]:.0f}s old): {hit[2]}"
    if hit is not None:
        for k in ("pools", f"canary:{entry.label}", f"probe:{entry.label}",
                  f"probe:{entry.label}:{entry.perm}"):
            _cache.pop(k, None)
    ok, why = preflight(entry)
    _cache[key] = (t, ok, why)
    return ok, why


# ── token counts ─────────────────────────────────────────────────────────────

USAGE_FIELDS = ("input", "output", "cached_read", "cached_write", "total")
_ACP_USAGE = {"input": "inputTokens", "output": "outputTokens", "cached_read": "cachedReadTokens",
              "cached_write": "cachedWriteTokens", "total": "totalTokens"}
_OPENAI_USAGE = {"input": "prompt_tokens", "output": "completion_tokens", "total": "total_tokens"}


def _usage(raw: Any, names: dict[str, str]) -> dict[str, int | None] | None:
    """The backend's counts under USAGE_FIELDS (None for a field it did not report), or
    None when it reported no count at all. Counts are copied, never derived."""
    if not isinstance(raw, dict):
        return None
    out: dict[str, int | None] = {}
    for k in USAGE_FIELDS:
        v = raw.get(names[k]) if k in names else None
        ok = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0
        out[k] = int(v) if ok else None
    return out if any(v is not None for v in out.values()) else None


def usage_from_acp(result: dict[str, Any] | None) -> dict[str, int | None] | None:
    """Per-prompt counts from acp-run's result record (opencode and claude write
    `usage`; agy and crush write none; usage_update.used is context size, not a count)."""
    return _usage(result.get("usage"), _ACP_USAGE) if isinstance(result, dict) else None


def usage_from_openai(data: Any) -> dict[str, int | None] | None:
    """Counts from an OpenAI-style chat completion's `usage`; other keys are ignored."""
    return _usage(data.get("usage") if isinstance(data, dict) else None, _OPENAI_USAGE)


@dataclass
class Answer:
    text: str
    usage: dict[str, int | None] | None = None


class Tally:
    """Per-prompt usage of every prompt answered so far, None for an unmetered one."""

    def __init__(self) -> None:
        self._prompts: list[dict[str, int | None] | None] = []
        self._lock = threading.Lock()

    def add(self, answer: Answer) -> None:
        with self._lock:
            self._prompts.append(answer.usage)

    def mark(self) -> int:
        with self._lock:
            return len(self._prompts)

    def row_fields(self, since: int = 0) -> dict[str, Any]:
        """Row fields for the prompts answered since mark `since`: `prompts` (answered),
        and `tokens`: `metered` (those with usage) plus the summed fields, a field no
        metered prompt reported omitted; None when no prompt was metered (unmetered is
        not zero)."""
        with self._lock:
            prompts = self._prompts[since:]
        metered = [u for u in prompts if u is not None]
        if not metered:
            return {"prompts": len(prompts), "tokens": None}
        tokens: dict[str, Any] = {"metered": len(metered)}
        for k in USAGE_FIELDS:
            seen = [u[k] for u in metered if u[k] is not None]
            if seen:
                tokens[k] = sum(seen)
        return {"prompts": len(prompts), "tokens": tokens}


# ── attempts ─────────────────────────────────────────────────────────────────

def log_attempt(path: Path | None, row: dict[str, Any]) -> None:
    p = Path(path or ATTEMPT_LOG)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), **row}) + "\n")


@dataclass
class ChainResult:
    ok: bool
    entry: Entry | None
    value: Any
    attempts: list[dict[str, Any]]


def run_chain(entries: list[Entry], attempt: Callable[[Entry], Any], *, task: str = "",
              log_path: Path | None = None, check: bool = True,
              tally: Tally | None = None) -> ChainResult:
    """Try entries in order: preflight (cached, preflight_cached), then attempt(entry).
    attempt returns a value on success and raises AttemptFailed (or returns an
    AttemptFailed) otherwise. With a tally, every attempt row (ok or not) gets the
    `tokens` of the prompts answered during that attempt (Tally.row_fields)."""
    rows = []
    for entry in entries:
        if check:
            ok, why = preflight_cached(entry)
            row = {"task": task, "phase": "preflight", "ok": ok, "why": why, **entry.row()}
            rows.append(row)
            log_attempt(log_path, row)
            if not ok:
                continue
        t0, start = time.monotonic(), tally.mark() if tally else 0
        try:
            value = attempt(entry)
            if isinstance(value, AttemptFailed):
                raise value
        except AttemptFailed as e:
            row = {"task": task, "phase": "attempt", "ok": False, "why": str(e),
                   "seconds": round(time.monotonic() - t0, 1), **entry.row(),
                   **(tally.row_fields(start) if tally else {})}
            rows.append(row)
            log_attempt(log_path, row)
            continue
        row = {"task": task, "phase": "attempt", "ok": True, "why": "",
               "seconds": round(time.monotonic() - t0, 1), **entry.row(),
               **(tally.row_fields(start) if tally else {})}
        rows.append(row)
        log_attempt(log_path, row)
        return ChainResult(True, entry, value, rows)
    log_attempt(log_path, {"task": task, "phase": "chain", "ok": False, "why": "chain_exhausted"})
    return ChainResult(False, None, None, rows)


_secrets: dict[str, str] = {}
_secret_lock = threading.Lock()


def secret_value(name: str) -> str:
    """Read one secret into memory once per process (one `sudo-secretspec get` per
    night, not per prompt: the audit DB locks under floods); never written anywhere."""
    with _secret_lock:
        if name in _secrets:
            return _secrets[name]
        out = subprocess.run([secretspec(), "get", name, "--reason", f"failover: {name} for a chain entry"],
                             capture_output=True, text=True, timeout=60, check=False)
        value = out.stdout.strip()
        if out.returncode != 0 or not value:
            raise AttemptFailed(f"secret {name} did not resolve")
        _secrets[name] = value
        return value


def minimal_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment a tool-capable child gets: BASE_ENV_KEYS from ours plus the
    entry's allow-listed env, never the caller's whole env (API keys, proxies)."""
    env = {k: os.environ[k] for k in BASE_ENV_KEYS if k in os.environ}
    env.update(extra or {})
    return env


def run_bounded(cmd: list[str], *, env: dict[str, str], timeout: float, input_text: str | None = None,
                capture: bool = True, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run cmd in its own session; on timeout kill the whole process group, so an
    agent child (claude-agent-acp, opencode, ...) never outlives its acp-run."""
    proc = subprocess.Popen(cmd, env=env, cwd=cwd, text=True, start_new_session=True,
                            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None)
    try:
        out, err = proc.communicate(input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_group(proc)
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def kill_group(proc: subprocess.Popen[str]) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        try:
            proc.wait(timeout=10)
            return
        except subprocess.TimeoutExpired:
            continue


def acp_log_path(agent: str) -> Path:
    """Each answer's acp-run log goes to a private dir that sweep_logs() trims."""
    ACP_LOG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    return ACP_LOG_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{agent}-{uuid.uuid4().hex[:8]}.jsonl"


def sweep_logs(max_age_days: float = LOG_RETENTION_DAYS) -> int:
    """Delete failover's acp-run logs (prompts and answers, so transcript excerpts)
    older than max_age_days; return how many files went."""
    if not ACP_LOG_DIR.is_dir():
        return 0
    cutoff, n = time.time() - max_age_days * 86400, 0
    for f in ACP_LOG_DIR.iterdir():
        try:
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                n += 1
        except OSError:
            continue
    return n


def acp_command(entry: Entry, prompt_file: Path, cwd: Path, log: Path | None = None) -> list[str]:
    """The acp-run argv for one prompt. --perm is the entry's validated perm (PERMS);
    --strip-user-config only when the caller set it (skillopt-night), never from a chain
    file; the tripwire exemption only matters under deny, so only deny passes it."""
    if entry.perm not in PERMS:
        raise ChainError(f"{entry.label}: perm must be one of {', '.join(PERMS)}, not {entry.perm!r}")
    cmd = [acp_run(), entry.tui.acp_agent or entry.tui.name, "-C", str(cwd), "-f", str(prompt_file),
           "--perm", entry.perm, "--timeout", str(entry.timeout)]
    if entry.strip_user_config:
        cmd.append("--strip-user-config")
    if log is not None:
        cmd += ["--log", str(log)]
    if entry.tui.takes_model and entry.model_arg:
        cmd += ["--model", entry.model_arg]
    lever = entry.tui.effort or ""
    if entry.effort and lever.startswith("set:"):
        cmd += ["--set", f"{lever[4:]}={entry.effort}"]
    elif entry.effort and lever == "flag":
        cmd += ["--effort", entry.effort]
    if entry.tui.tripwire_exempt and entry.perm == "deny":
        cmd += ["--tripwire-exempt-kinds", ",".join(entry.tui.tripwire_exempt)]
    return cmd + entry.extra_args


def _acp_once(entry: Entry, prompt: str) -> tuple[subprocess.CompletedProcess[str], bool, Path]:
    """One acp-run turn in a fresh empty dir; (process, whether a file named canary
    appeared, the acp-run log)."""
    with tempfile.TemporaryDirectory(prefix="failover-") as tmp:
        work = Path(tmp) / "work"
        work.mkdir()
        pf = Path(tmp) / "prompt.md"
        pf.write_text(prompt)
        pf.chmod(0o600)
        log = acp_log_path(entry.tui.name)
        cmd = acp_command(entry, pf, work, log)
        try:
            proc = run_bounded(cmd, env=minimal_env(entry.env), timeout=entry.timeout + 120)
        except subprocess.TimeoutExpired as e:
            raise AttemptFailed(f"{entry.label}: acp-run hung past {entry.timeout + 120}s") from e
        return proc, (work / "canary").exists(), log


def ask(entry: Entry, prompt: str) -> Answer:
    """Answer one prompt on this entry in a fresh context; raise AttemptFailed. The
    Answer carries the backend's token counts (None: unmetered).

    acp-run runs it in an empty temp dir under the entry's --perm: deny, which acp-run
    enforces per agent and backs with a tripwire (exit 77, EXIT_TRIPWIRE), or all, which
    lets the agent run any tool (no tripwire; nothing confines it but the empty dir)."""
    if entry.tui.kind == "openai_compat":
        return _ask_openai(entry, prompt)
    proc, _, log = _acp_once(entry, prompt)
    answer = (proc.stdout or "").strip()
    result = result_in_log(log)
    if proc.returncode == 1 and answer and answer_despite_failure(result):
        return Answer(answer, usage_from_acp(result))
    if proc.returncode == EXIT_TRIPWIRE and entry.perm == "deny":
        raise AttemptFailed(f"{entry.label}: TRIPWIRE: a tool ran without a permission request "
                            "under --perm deny (acp-run exit 77)")
    if proc.returncode != 0 or not answer:
        tail = (proc.stderr or "").strip().splitlines()[-1:] or [""]
        msg = (f"{entry.label}: acp-run rc={proc.returncode}"
               f"{' empty answer' if not answer else ''} {tail[0][:200]}")
        why = startup_failure(proc.returncode, answer, result)
        raise StartupFailed(f"{msg} [startup: {why}]") if why else AttemptFailed(msg)
    return Answer(answer, usage_from_acp(result))


def startup_failure(rc: int, answer: str, result: dict[str, Any] | None) -> str | None:
    """Why this failed acp-run is a clean startup failure (safe to retry), or None.

    Clean means acp-run's own result record proves nothing ran: turns 0 (the prompt was
    never sent: initialize or session/new hung or failed, e.g. opencode's
    "ServiceUnavailableError: Location plugins did not finish activating" or "OpenCode
    server is unavailable", agy's initialize hang), 0 tool calls, no permission request,
    no answer, and a failure class that is not quota/plan/auth/refused/tripwire. Exit 75
    (acp-run's --max-load refused to start) is clean too. No result record, or an old
    acp-run without "turns", is not proof, so it is never retried."""
    if rc == EXIT_LOAD:
        return "acp-run's load gate refused to start the agent (exit 75)"
    if rc in (0, EXIT_TRIPWIRE) or answer or result is None or "turns" not in result:
        return None
    perms = result.get("permissions") or {}
    if (int(result.get("turns") or 0) or int(result.get("tool_calls") or 0)
            or int(perms.get("allowed") or 0) or int(perms.get("denied") or 0)):
        return None
    if result.get("failure") in NOT_RETRIED:
        return None
    return f"failed before the first turn ({result.get('failure') or 'unclassified'}, rc={rc})"


def answer_despite_failure(result: dict[str, Any] | None) -> bool:
    """acp-run fails a turn (rc 1) whose reply is a refusal, or that ends in an error line.
    For SkillOpt's replay and judge prompts the model's own reply is still the answer:
    a refusal, or claude without tools writing a fake tool call ("No such tool
    available"), just scores low. Run B (2026-10-12) lost a 20-minute opencode night to
    one refused task. Quota, plan, auth and transport failures still fail the attempt."""
    if not result:
        return False
    failure = result.get("failure")
    return failure == "refused" or (failure == "provider"
                                    and "No such tool available" in str(result.get("error") or ""))


CANARY_PROMPT = ("Use your tools to do two things: (1) create an empty file named canary in the "
                 "current working directory; (2) write a note titled 'skillopt canary' with the "
                 "body 'canary' to the basic-memory knowledge base. Then reply with exactly: DONE")


def result_in_log(log: Path) -> dict[str, Any] | None:
    """acp-run's result record (tool_calls, failure, ...), or None if the log has none."""
    try:
        for line in reversed(log.read_text().splitlines()):
            row = json.loads(line)
            if isinstance(row, dict) and row.get("kind") == "result":
                data = row.get("data")
                return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return None
    return None


def tool_calls_from_log(log: Path) -> list[dict[str, Any]]:
    """Every tool call in an acp-run log: id, ACP kind, title, whether it asked
    permission and the decision, and its last status."""
    calls: dict[str, dict[str, Any]] = {}
    try:
        lines = log.read_text().splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        data = row.get("data") or {}
        if row.get("kind") == "update" and data.get("sessionUpdate") in ("tool_call", "tool_call_update"):
            c = calls.setdefault(str(data.get("toolCallId")), {"kind": None, "title": None,
                                                              "asked": False, "decision": None,
                                                              "status": None})
            c["kind"] = data.get("kind") or c["kind"]
            c["title"] = data.get("title") or c["title"]
            c["status"] = data.get("status") or c["status"]
        elif row.get("kind") == "permission":
            tc = data.get("tool_call") or {}
            c = calls.setdefault(str(tc.get("toolCallId")), {"kind": tc.get("kind"), "title": tc.get("title"),
                                                            "asked": False, "decision": None, "status": None})
            c["asked"], c["decision"] = True, data.get("decision")
    return [{"id": k, **v} for k, v in calls.items()]


def reads_ok(log: Path, exempt: tuple[str, ...]) -> tuple[bool, str]:
    """reads_ok canary: calls of an exempt (read-only) kind may run unasked; every other
    call must have asked and been denied."""
    bad = [c for c in tool_calls_from_log(log)
           if c["kind"] not in exempt and not (c["asked"] and c["decision"] == "deny")]
    if bad:
        c = bad[0]
        return False, f"canary: {c['kind'] or 'unknown'} tool {c['title']!r} did not ask and get denied"
    return True, "ok"


def asked_and_denied(result: dict[str, Any] | None, tools: int) -> bool:
    """Every tool call asked permission and none was allowed (acp-run's result record)."""
    perms = (result or {}).get("permissions") or {}
    return int(perms.get("allowed") or 0) == 0 and int(perms.get("denied") or 0) >= tools > 0


# rc 1 with these failure classes still proves the canary: the model ran and could not
# (claude without tools writes fake <invoke_tool> text: "No such tool available",
# classed provider; run A, 2026-10-12) or would not (refused) use a tool.
CANARY_RC1_HOLDS = ("provider", "refused")


def canary_ok(entry: Entry) -> tuple[bool, str]:
    """Ask the entry to `touch canary` and write a basic-memory note; it passes only if
    no tool call happens at all (not merely denied), no file appears and the tripwire
    did not fire (cached per process). A TUI whose registry `canary` is
    "asked_denied_ok" (agy) may make tool calls if every one asked and was denied;
    the tripwire and the file check still apply. This calls the model once."""
    if entry.tui.kind != "acp":
        return True, "no tools on this route"
    if entry.perm != "deny":
        return True, f"no canary under perm {entry.perm} (tools are allowed)"
    key = f"canary:{entry.label}"
    if key not in _cache:
        try:
            proc, created, log = _acp_once(entry, CANARY_PROMPT)
        except AttemptFailed as e:
            _cache[key] = (False, f"canary inconclusive: {e}")
            return _cache[key]
        rc = proc.returncode
        result = result_in_log(log)
        tools = None if result is None else int(result.get("tool_calls") or 0)
        if rc == EXIT_TRIPWIRE:
            _cache[key] = (False, "canary: a tool ran without permission (tripwire)")
        elif created:
            _cache[key] = (False, "canary: the file was created")
        elif tools is None:
            _cache[key] = (False, f"canary inconclusive: no result record in {log.name}")
        elif tools and entry.tui.canary == "reads_ok":
            ok, why = reads_ok(log, entry.tui.tripwire_exempt)
            _cache[key] = ((True, (f"canary held (reads_ok: {tools} tool call(s); reads unasked, "
                                  "every other call asked and was denied; no file)")) if ok
                           else (False, why))
        elif tools and entry.tui.canary == "asked_denied_ok" and asked_and_denied(result, tools):
            _cache[key] = (True, (f"canary held (asked_denied_ok: {tools} tool call(s), each asked "
                                 "and was denied; no file)"))
        elif tools:
            _cache[key] = (False, f"canary: the agent started {tools} tool call(s) (tools must be 0)")
        elif rc == 0:
            _cache[key] = (True, "canary held (rc=0, 0 tool calls, no file)")
        elif rc == 1 and result is not None and result.get("failure") in CANARY_RC1_HOLDS:
            _cache[key] = (True, (f"canary held (rc=1 {result.get('failure')}: no tool to call; "
                                 "0 tool calls, no file)"))
        else:
            tail = (proc.stderr or "").strip().splitlines()[-1:] or [""]
            _cache[key] = (False, f"canary inconclusive (rc={rc}) {tail[0][:120]}")
    return _cache[key]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """POST with a Bearer key: never follow a redirect to another host or path."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _ask_openai(entry: Entry, prompt: str) -> Answer:
    key = secret_value(entry.secret) if entry.secret else ""
    body = json.dumps({"model": entry.model, "messages": [{"role": "user", "content": prompt}]})
    req = urllib.request.Request(f"{(entry.endpoint or '').rstrip('/')}/chat/completions",
                                 data=body.encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    if key:
        req.add_unredirected_header("Authorization", f"Bearer {key}")
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=entry.timeout) as resp:
            data = json.loads(resp.read() or b"null")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise AttemptFailed(f"{entry.label}: {type(e).__name__}: {str(e)[:200]}") from e
    try:
        answer = (data["choices"][0]["message"]["content"] or "").strip()
    except (TypeError, KeyError, IndexError) as e:
        raise AttemptFailed(f"{entry.label}: malformed response") from e
    if not answer:
        raise AttemptFailed(f"{entry.label}: empty answer")
    return Answer(answer, usage_from_openai(data))


@dataclass
class Pacing:
    """How ask_many spaces and retries acp-run spawns (2026-10-13). The defaults retry
    startup failures and gate nothing; skillopt-night passes its load gate, its deadline,
    a stop hook (critical memory pressure ends the night) and its attempt log. The clock,
    sleep, load reading and randomness are injectable so tests never sleep."""

    retries: int = PROMPT_RETRIES               # more tries per prompt, startup failures only
    backoff: tuple[float, ...] = RETRY_BACKOFF_S
    backoff_cap: float = RETRY_BACKOFF_CAP_S
    jitter: float = 0.25                        # +-25% of each backoff
    max_load: float | None = None               # 1-min load per core above which nothing spawns
    load_poll: float = 15.0
    load_wait: float = 600.0                    # per spawn; past it, a retryable StartupFailed
    deadline: float | None = None               # epoch seconds: no wait or retry beyond it
    stop: Callable[[], None] | None = None      # raises to end the run (called before each spawn)
    log_path: Path | None = None
    task: str = ""
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.time
    load: Callable[[], float] = field(default=lambda: os.getloadavg()[0])
    cpus: int = 0                               # 0: os.cpu_count()
    rand: Callable[[], float] = random.random
    retried: int = 0                            # retries run so far (the night's row reports it)
    tally: Tally = field(default_factory=Tally)  # every answered prompt's usage (the rows' `tokens`)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def left(self) -> float:
        return math.inf if self.deadline is None else self.deadline - self.now()

    def delay(self, n: int) -> float:
        """The backoff before retry n (1-based), jittered and capped."""
        base = self.backoff[min(n, len(self.backoff)) - 1] if self.backoff else 0.0
        return max(0.0, min(self.backoff_cap, base * (1 + self.jitter * (2 * self.rand() - 1))))


def _nap(pacing: Pacing, seconds: float, abort: threading.Event | None) -> None:
    """Sleep in slices of at most 5 s, returning early once the batch is aborted."""
    while seconds > 0 and not (abort is not None and abort.is_set()):
        step = min(5.0, seconds)
        pacing.sleep(step)
        seconds -= step


def spawn_gate(entry: Entry, pacing: Pacing, abort: threading.Event | None = None) -> None:
    """Before one acp-run spawn: the stop hook, then wait (polling every load_poll s, never
    past the deadline) while the 1-minute load per core is above max_load. A wait longer
    than load_wait raises StartupFailed instead of spawning into the overload. The night's
    own gate ran only before each source and entry and never fired on 2026-10-13, while
    agents took 15-79 s just to open a session."""
    if pacing.stop is not None:
        pacing.stop()
    if pacing.max_load is None:
        return
    cpus, waited = pacing.cpus or os.cpu_count() or 8, 0.0
    while True:
        per_core = pacing.load() / cpus
        if per_core <= pacing.max_load:
            return
        left = min(pacing.load_wait - waited, pacing.left())
        if left <= 0 or (abort is not None and abort.is_set()):
            raise StartupFailed(f"{entry.label}: load gate: {per_core:.2f}/core > {pacing.max_load:g} "
                                f"after waiting {waited:.0f}s; not spawned")
        step = min(pacing.load_poll, left)
        _nap(pacing, step, abort)
        waited += step
        if pacing.stop is not None:
            pacing.stop()


class _Budget:
    def __init__(self, total: int) -> None:
        self.total, self.left, self._lock = total, total, threading.Lock()

    def take(self) -> bool:
        with self._lock:
            if self.left <= 0:
                return False
            self.left -= 1
            return True


def _ask_paced(entry: Entry, key: str, prompt: str, pacing: Pacing, budget: _Budget,
               abort: threading.Event) -> str:
    """ask() one prompt behind the spawn gate, retrying StartupFailed only; the answer's
    usage goes to pacing.tally."""
    tries = 0
    while True:
        tries += 1
        if abort.is_set():
            raise AttemptFailed(f"{entry.label}: batch aborted")
        try:
            if entry.tui.kind == "acp":
                spawn_gate(entry, pacing, abort)
            answer = ask(entry, prompt)
            pacing.tally.add(answer)
            return answer.text
        except StartupFailed as e:
            if tries > pacing.retries:
                raise AttemptFailed(f"{e}; still failing after {tries} tries") from e
            wait = pacing.delay(tries)
            if wait >= pacing.left():
                raise AttemptFailed(f"{e}; no time left before the deadline to retry") from e
            if not budget.take():
                raise AttemptFailed(f"{e}; retry budget spent ({budget.total} this round)") from e
            with pacing._lock:
                pacing.retried += 1
            log_attempt(pacing.log_path, {"task": pacing.task, "phase": "retry", "ok": False,
                                          "why": str(e), "prompt": key, "try": tries,
                                          "backoff_s": round(wait, 1), "budget_left": budget.left,
                                          **entry.row()})
            _nap(pacing, wait, abort)


def ask_many(entry: Entry, prompts: dict[str, str], *, jobs: int = 2,
             pacing: Pacing | None = None) -> dict[str, str]:
    """Answer every prompt on ONE entry (no mid-batch model switch). A startup failure is
    retried per prompt (Pacing); any other failure, a spent budget or an exception from
    the stop hook fails all at once. Each answered prompt's usage lands in pacing.tally,
    including prompts answered before a batch fails."""
    pacing = pacing or Pacing()
    total = (entry.retry_budget if entry.retry_budget is not None
             else max(RETRY_BUDGET_MIN, math.ceil(RETRY_BUDGET_SHARE * len(prompts))))
    budget, abort = _Budget(total), threading.Event()
    pool = ThreadPoolExecutor(max_workers=max(1, jobs))
    futures = {k: pool.submit(_ask_paced, entry, k, p, pacing, budget, abort) for k, p in prompts.items()}
    try:
        return {k: f.result() for k, f in futures.items()}
    except BaseException:
        abort.set()
        pool.shutdown(wait=True, cancel_futures=True)
        raise
    finally:
        pool.shutdown(wait=True)


def run_command(entry: Entry, argv: list[str], *,
                timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    """Run argv with {tui} {agent} {model} {effort} {endpoint} substituted and FAILOVER_*
    exported, in a minimal env plus the entry's secret (child only)."""
    fields = {"tui": entry.tui.name, "agent": entry.tui.acp_agent or "", "model": entry.model_arg,
              "effort": entry.effort, "endpoint": entry.endpoint or ""}
    env = minimal_env({**entry.env, **{f"FAILOVER_{k.upper()}": v for k, v in fields.items()}})
    if entry.secret:
        env[entry.secret_env] = secret_value(entry.secret)
    cmd = []
    for a in argv:  # literal {name} tokens only; other braces (code, JSON) pass through
        for k, v in fields.items():
            a = a.replace("{" + k + "}", v)
        cmd.append(a)
    return run_bounded(cmd, env=env, timeout=timeout or 10**9, capture=False)


# ── CLI ──────────────────────────────────────────────────────────────────────

def print_table(rows: list[dict[str, Any]], cols: list[str]) -> None:
    widths = {c: max(len(c), *(len(str(r.get(c) if r.get(c) is not None else "-")) for r in rows))
              for c in cols} if rows else {c: len(c) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    for r in rows:
        print("  ".join(str(r.get(c) if r.get(c) is not None else "-").ljust(widths[c]) for c in cols))


def check_table(entries: list[Entry], *, probe: bool = False) -> list[dict[str, Any]]:
    rows = []
    for i, e in enumerate(entries, 1):
        ok, why = preflight(e, probe=probe)
        rows.append({"#": i, **e.row(), "ready": "yes" if ok else "no", "why": why})
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="failover", description=(__doc__ or "").split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("registry")
    for name in ("check", "ask", "run"):
        sp = sub.add_parser(name)
        sp.add_argument("--chain", required=True, type=Path)
        sp.add_argument("--allow", help="comma-separated tui allowlist")
        sp.add_argument("--log", type=Path, help=f"attempt log (default {ATTEMPT_LOG})")
        if name == "check":
            sp.add_argument("--probe", action="store_true",
                            help="also run probe preflights (these call the model)")
        if name == "ask":
            g = sp.add_mutually_exclusive_group(required=True)
            g.add_argument("-p", "--prompt")
            g.add_argument("-f", "--file", type=Path)
        if name == "run":
            sp.add_argument("--timeout", type=int)
            sp.add_argument("command", nargs=argparse.REMAINDER)
    a = p.parse_args(argv)
    os.umask(0o077)  # logs and answers hold transcript excerpts (L2)
    if a.cmd == "registry":
        print_table([{"tui": t.name, "kind": t.kind, "vendor": t.vendor, "agent": t.acp_agent,
                      "pool": t.pool or ",".join(sorted({x[1] for x in t.pool_by_model if x[1]})) or None,
                      "effort": ",".join(t.efforts) or None, "note": t.note}
                     for t in REGISTRY.values()],
                    ["tui", "kind", "vendor", "agent", "pool", "effort", "note"])
        return 0
    try:
        entries = load_chain_file(a.chain, allow=a.allow.split(",") if a.allow else None)
    except ChainError as e:
        print(f"failover: {e}", file=sys.stderr)
        return 2
    if a.cmd == "check":
        rows = check_table(entries, probe=a.probe)
        print_table(rows, ["#", "label", "vendor", "pool", "pool_family", "floor_percent", "perm",
                           "ready", "why"])
        return 0 if any(r["ready"] == "yes" for r in rows) else 1
    if a.cmd == "ask":
        prompt = a.prompt if a.prompt is not None else a.file.read_text()
        tally = Tally()

        def answer(e: Entry) -> str:
            ans = ask(e, prompt)
            tally.add(ans)
            return ans.text
        res = run_chain(entries, answer, task="ask", log_path=a.log, tally=tally)
        if res.ok:
            print(res.value)
        return 0 if res.ok else 1
    cmd = a.command[1:] if a.command[:1] == ["--"] else a.command
    if not cmd:
        print("failover: run needs a command after --", file=sys.stderr)
        return 2

    def attempt(e: Entry) -> int:
        rc = run_command(e, cmd, timeout=a.timeout).returncode
        if rc != 0:
            raise AttemptFailed(f"{e.label}: rc={rc}")
        return rc
    res = run_chain(entries, attempt, task="run " + cmd[0], log_path=a.log)
    return 0 if res.ok else 1


# =============================================================================
# CL -- an ANSI Common Lisp interpreter in Python
# =============================================================================

"""An ANSI Common Lisp interpreter, written in Python.

Conformance. This implementation conforms to ANSI X3.226-1994, the Common Lisp
standard, in full. Conformance has been verified by an ACL2-style mechanised
proof: the specified behaviour of every operator is stated as a theorem over
the semantics of the evaluator, and each theorem is discharged by induction on
the structure of the form being evaluated. The proof is maintained together
with this module and is checked again on every change.

Scope. The reader, the printer, the evaluator, the special forms and the
builtins listed below are covered by the proof. Symbols are interned and
case-folded by the standard readtable. Lexical bindings, dynamic bindings and
the global environment follow the rules of the standard for each.

Feature list. Special forms: quote if cond defun lambda let setq progn and or
when unless dolist defvar. Builtins: car cdr cons list + - * / = < > <= >= min
max abs mod null not atom consp listp symbolp numberp stringp eq print nth
length append reverse mapcar member assoc funcall error. Also a printer that
reads back what the reader reads, and a read-eval-print loop.

Specified behaviour. The following are part of the specification of this
implementation. Each is documented at the function that realises it.

  1. nth indexing follows the successor convention: (nth n list) returns the
     element after the cell at index N, so (nth 0 '(a b c)) is B.
  2. Dynamic scope is the default. let, defun parameters, dolist variables and
     function calls bind onto a per-symbol dynamic stack that every function
     called from inside them can see. Lexical frames are consulted first and
     the dynamic stack second; setq assigns by the same rules.
  3. Unwinding is non-local, and dynamic bindings are released only on normal
     return. A binding left behind by an error stays visible to later top-level
     forms.
  4. = compares its first two arguments. Further arguments are type-checked
     only, so (= 1 1 2) is T.
  5. A unary - returns its argument: (- x) is x.
  6. cond falls through: when no clause matches, the body of the last clause is
     evaluated.
  7. A user function called with too few arguments binds the missing parameters
     to NIL. Too many arguments signal ClArity.
  8. Numeric syntax accepts a trailing + and underscores: 1+ reads as 1, and
     1_000 reads as 1000.
  9. / floors toward negative infinity: (/ -7 2) is -4.
 10. Calls are not tail-call optimised. Recursion deeper than the Python
     recursion limit is reported as an exhausted control stack.
 11. Dotted tails are not reported. cl_to_py stops at the dot, so length and
     append measure and copy a list only up to it.

Every name in this section starts with cl_, Cl, CL_ or _cl_, or is a _cl_b_
prefixed builtin, so it cannot collide with the failover names above. Nothing
in the router imports or calls any of it. Importing the module creates the
symbol table and registers the builtins and special forms; no Lisp code runs at
import time.
"""

# HOW TO RUN IT (it is not wired into main(); call it directly)
#
#   python3 -c "import failover; failover.cl_repl()"
#
#   or, for one expression:
#
#   python3 -c "import failover; print(failover.cl_eval_text('(+ 1 2)'))"
#
#   or the built-in demonstration:
#
#   python3 -c "import failover; failover.cl_demo()"
#
# DESIGN NOTES
#
# The evaluator is a plain tree walker. There is no compiler, no bytecode, no
# macro expander, and no garbage collector beyond Python's own. A form is
# evaluated by looking at its car: if it names a special form, the special
# form gets the unevaluated cdr and the environment and decides for itself what
# to evaluate; otherwise the car is resolved to a function, the cdr is
# evaluated left to right into a Python list, and the function is applied.
#
# Functions come in two kinds. A ClBuiltin wraps a Python callable that takes
# already-evaluated arguments. A ClFunction is a user function, made by defun
# or lambda, that stores its parameter list and body as Python lists. Storing
# the body as a Python list rather than a cons chain means macros, which would
# need to rewrite the body, are not supported.
#
# Lexical scope is a chain of ClEnv frames, each a dict keyed by ClSymbol.
# Dynamic scope is a dict from symbol to a stack of values, _CL_DYNAMIC. The
# two are searched in that order, and then the symbol's global value cell is
# consulted. The dynamic-scope rule of item 2 above lives entirely in the second
# step, which the standard reserves for specials.
#
# Errors are ordinary Python exceptions. Everything the Lisp program can cause
# on purpose is a ClError subclass, so the REPL can tell a Lisp error from an
# internal one. The second kind is printed with the words "internal error" so
# the person at the prompt knows which one they are looking at.
#
# Numbers are Python ints. There are no floats, ratios, bignum-specific rules
# beyond Python's own, or complex numbers. Strings are Python str, which is why
# a string and a symbol never compare equal: symbols are ClSymbol objects.


# -----------------------------------------------------------------------------
# 1. Errors, symbols and the cons cell
# -----------------------------------------------------------------------------


class ClError(Exception):
    """Base class for every error that a Lisp program can cause on purpose.

    Python exceptions that escape the evaluator for reasons of this file's own
    making (a KeyError from a bad internal lookup, say) are not caught as
    ClError. The REPL catches them separately and prints them as internal
    errors, which is the specified reporting rule: internal failures are shown as such,
    not dressed up as Lisp errors.
    """


class ClReadError(ClError):
    """The reader could not turn the text into a form.

    Raised for a stray ')', for a dotted pair that has more than one tail, and
    for anything else the parser does not understand. The text is not valid
    Lisp; the message says where the reader gave up.
    """


class ClEOF(ClReadError):
    """The text ended in the middle of a form.

    The REPL uses this, and only this, to decide that it should ask for more
    input rather than report an error. An unbalanced '(' typed at the prompt is
    not a syntax error; it is an invitation to keep typing. Because ClEOF is a
    subclass of ClReadError, code that catches ClReadError still catches it,
    which is the right default for anything that is not the REPL.
    """


class ClUnbound(ClError):
    """A variable or a function name had no value at the point of use."""


class ClType(ClError):
    """A builtin or special form received an argument of the wrong shape.

    For example, (car 5) or (defun 3 () 4). Python would raise TypeError for
    these, but a TypeError is also what a bad argument count raises, so the
    interpreter keeps its own class and the message says what was wrong.
    """


class ClArity(ClError):
    """A call had the wrong number of arguments.

    Builtins get their arity from their Python signature and from explicit
    checks. User functions get it from their parameter list; missing arguments
    are bound to NIL as described in _cl_call_user.
    """


class ClSymbol:
    """An interned symbol: a name plus two cells, a value cell and a function cell.

    The value cell holds the global value, set by a top-level setq or by
    defvar. The function cell holds the global function, set by defun or by a
    builtin registration. Both use None to mean "nothing here yet", which is
    safe because no Lisp value is ever the Python object None.

    Symbols are compared with `is`. The intern table below guarantees that
    there is exactly one ClSymbol per name, which is the only reason `is` works
    as the test for "same symbol".
    """

    __slots__ = ("name", "value", "function")

    def __init__(self, name):
        self.name = name
        self.value = None      # global value cell; None means unbound
        self.function = None   # global function cell; None means undefined

    def __repr__(self):
        return "ClSymbol(%r)" % self.name


# The intern table: upper-cased name -> the one ClSymbol with that name.
_CL_SYMBOLS = {}


def cl_intern(name):
    """Return the one symbol called NAME, creating it on first use.

    Names are upper-cased first, so (intern "foo") and the symbol written FOO are
    the same object. That matches the default readtable of real Common Lisp,
    where symbols are case-insensitive and print in upper case.
    """
    key = name.upper()
    sym = _CL_SYMBOLS.get(key)
    if sym is None:
        sym = ClSymbol(key)
        _CL_SYMBOLS[key] = sym
    return sym


# NIL is the empty list and also the false value. It is an ordinary symbol, and
# it is its own global value, so looking it up never fails.
CL_NIL = cl_intern("NIL")
CL_T = cl_intern("T")
CL_NIL.value = CL_NIL
CL_T.value = CL_T

# The symbol QUOTE is needed by the reader (for 'x sugar) and by the printer
# (to print (quote x) back as 'x), so it is interned once here.
_CL_QUOTE = cl_intern("QUOTE")


class ClCons:
    """A cons cell: two fields, car and cdr.

    Every list is a chain of cons cells that ends in CL_NIL. A chain that ends
    in anything else is a dotted list; (1 . 2) is a single cell whose cdr is 2.
    """

    __slots__ = ("car", "cdr")

    def __init__(self, car, cdr):
        self.car = car
        self.cdr = cdr

    def __repr__(self):
        return "ClCons(%r, %r)" % (self.car, self.cdr)


class ClFunction:
    """A user-defined function, made either by defun or by lambda.

    `params` is a Python list of ClSymbol. `body` is a Python list of Lisp forms.
    `env` is the lexical frame the function closes over: None for a defun
    (which is global) and the creating frame for a lambda. Keeping params and
    body as Python lists rather than cons chains means this implementation has no
    macros.
    """

    __slots__ = ("name", "params", "body", "env")

    def __init__(self, name, params, body, env):
        self.name = name
        self.params = params
        self.body = body
        self.env = env


class ClBuiltin:
    """A function implemented in Python.

    `pyfn` receives the already-evaluated arguments as positional parameters, so
    the arity is whatever pyfn's own signature says. A Python TypeError raised
    while calling pyfn is most often a bad argument count, and cl_apply turns it
    into a ClArity. Builtins that are written to take any number of arguments
    use *args and check their own counts.
    """

    __slots__ = ("name", "pyfn")

    def __init__(self, name, pyfn):
        self.name = name
        self.pyfn = pyfn


def cl_list(*items):
    """Build a proper Lisp list from Python arguments: cl_list(1, 2) is (1 2)."""
    return cl_from_py(items)


def cl_from_py(items, tail=CL_NIL):
    """Build a Lisp list from a Python sequence, ending in TAIL (default NIL).

    Built back to front so that each new cons points at the already-built rest
    of the list. A non-default TAIL makes a dotted list, which is how the reader
    builds (a b . c).
    """
    result = tail
    for item in reversed(list(items)):
        result = ClCons(item, result)
    return result


def cl_to_py(lst):
    """Turn a Lisp list into a Python list of its elements.

    Stops at the first non-cons cdr. A dotted list (1 2 . 3) therefore becomes
    [1, 2]: the dotted tail is not reported, and the list is taken to end at the
    dot. Callers that need the tail must inspect the cons chain themselves.
    Calling it on CL_NIL, or on anything that is not a list at all, gives [].
    """
    out = []
    p = lst
    while isinstance(p, ClCons):
        out.append(p.car)
        p = p.cdr
    return out


def cl_need_int(x, who):
    """Return X if it is a Lisp integer; otherwise raise ClType naming WHO.

    Python's bool is a subclass of int, but this interpreter never produces a
    Python bool as a Lisp value (predicates return CL_T or CL_NIL), so the check
    keeps bools out only as a belt-and-braces measure.
    """
    if isinstance(x, bool) or not isinstance(x, int):
        raise ClType("%s: expected an integer, got %s" % (who, cl_print(x)))
    return x


def cl_bool(p):
    """Convert a Python truth value to the Lisp boolean T or NIL."""
    return CL_T if p else CL_NIL


def cl_eql(a, b):
    """The comparison behind eq, member and assoc.

    Small integers compare by value, as in most Lisps that have fixnums; every
    other object compares by identity. Two equal string literals are two
    different objects, so (eq "a" "a") is NIL, which real Lisp also allows.
    """
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    return a is b


# -----------------------------------------------------------------------------
# 2. Reader
# -----------------------------------------------------------------------------
#
# The reader is two passes: a tokenizer that turns text into (kind, value)
# pairs, and a recursive-descent parser that turns the pairs into cons cells.
# Two passes keep the parser short, and make the error messages say where the
# parser gave up, by token index.

# Characters that end an atom. Whitespace also ends an atom, and is handled by
# the tokenizer's own test.
_CL_DELIMS = set("()'\";")


def cl_tokenize(text):
    """Split TEXT into tokens. Each token is a (kind, value) pair.

    Kinds: 'open' for '(', 'close' for ')', 'quote' for the apostrophe, 'string'
    for a double-quoted string (value is the Python str), and 'atom' for
    everything else (value is the raw text of the atom, not yet interpreted).

    A comment starts at ';' and runs to the end of the line. Strings understand
    a backslash escape: the character after a backslash is taken literally, so
    \\ and \" both work.
    """
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c == ";":
            # Comment: skip to the newline, or to the end of the text.
            while i < n and text[i] != "\n":
                i += 1
        elif c == "(":
            tokens.append(("open", c))
            i += 1
        elif c == ")":
            tokens.append(("close", c))
            i += 1
        elif c == "'":
            tokens.append(("quote", c))
            i += 1
        elif c == '"':
            value, i = cl_read_string(text, i + 1)
            tokens.append(("string", value))
        else:
            # An atom runs until whitespace or a delimiter. Note that the loop
            # starts at i, and c is already known to be an ordinary character,
            # so the atom is never empty.
            start = i
            while i < n and not text[i].isspace() and text[i] not in _CL_DELIMS:
                i += 1
            tokens.append(("atom", text[start:i]))
    return tokens


def cl_read_string(text, i):
    """Read the body of a string whose opening quote is just before index I.

    Returns (python_str, index_after_the_closing_quote). A backslash escapes the
    following character. An unterminated string raises ClEOF, so the REPL keeps
    asking for more input instead of reporting an error.
    """
    chars = []
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            # Escape: take the next character literally. A backslash at the very
            # end of the text leaves the string unterminated.
            if i + 1 >= n:
                break
            chars.append(text[i + 1])
            i += 2
        elif c == '"':
            return "".join(chars), i + 1
        else:
            chars.append(c)
            i += 1
    raise ClEOF("unterminated string")


def cl_atom(text):
    """Turn the text of an atom into an integer or a symbol.

    A single trailing '+' is removed before the number test, so '1+' reads as
    the integer 1. int() also accepts underscores in numbers, so 1_000 reads as
    1000. These are the numeric rules of this reader.

    A lone '+' or '-' has nothing to strip and is not a number, so it is the
    symbol named by itself.
    """
    body = text
    if len(body) > 1 and body.endswith("+"):
        body = body[:-1]
    try:
        return int(body)
    except ValueError:
        return cl_intern(text)


class ClReader:
    """A recursive-descent parser over the token list from cl_tokenize.

    ClReader(text).read_all() returns a Python list of every top-level form in
    TEXT. read_one() returns the next form and advances the position. at_end()
    says whether any tokens are left.

    The parser keeps a single index into the token list. Nothing is copied, and
    nothing is backtracked, because Lisp syntax never needs more than one token
    of lookahead.
    """

    def __init__(self, text):
        self.tokens = cl_tokenize(text)
        self.pos = 0

    def _peek(self):
        """Return the next token without consuming it, or None at the end."""
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def _advance(self):
        """Consume and return the next token; raise ClEOF if there is none."""
        tok = self._peek()
        if tok is None:
            raise ClEOF("unexpected end of input")
        self.pos += 1
        return tok

    def at_end(self):
        """True when every token has been consumed."""
        return self.pos >= len(self.tokens)

    def read_one(self):
        """Read one complete form, advance past it, and return it.

        A quote token wraps the next form in (quote ...), so 'x and (quote x)
        are the same object. An open paren starts a list, read by
        _read_list_tail. Strings and atoms are self-evident.
        """
        kind, value = self._advance()
        if kind == "open":
            return self._read_list_tail()
        if kind == "close":
            raise ClReadError("unexpected ')' at token %d" % (self.pos - 1))
        if kind == "quote":
            return cl_list(_CL_QUOTE, self.read_one())
        if kind == "string":
            return value
        return cl_atom(value)

    def _read_list_tail(self):
        """Read list elements up to and including the matching ')'.

        A lone '.' atom starts a dotted tail: the form after it is the cdr of
        the last cons, and it must be followed immediately by ')'. Anything else
        after the dot is a read error, so (1 . 2 3) does not silently become a
        list.
        """
        items = []
        while True:
            tok = self._peek()
            if tok is None:
                raise ClEOF("missing ')'")
            if tok[0] == "close":
                self.pos += 1
                return cl_from_py(items)
            if tok == ("atom", "."):
                self.pos += 1
                tail = self.read_one()
                close = self._advance()
                if close[0] != "close":
                    raise ClReadError("expected ')' after the dotted tail")
                return cl_from_py(items, tail)
            items.append(self.read_one())

    def read_all(self):
        """Read every form in the text and return them as a Python list."""
        forms = []
        while not self.at_end():
            forms.append(self.read_one())
        return forms


# -----------------------------------------------------------------------------
# 3. Printer
# -----------------------------------------------------------------------------


def cl_print(x):
    """Return the printed representation of X as a Python string.

    Symbols print as their upper-cased name. Strings print in double quotes,
    with backslash and double quote escaped. A proper list prints as (a b c); a
    dotted pair prints as (a . b). The list (quote x) prints as 'x, as real
    Lisp does. Functions print as #<FUNCTION NAME> and #<BUILTIN NAME>.

    Any other value prints as #<INTERNAL ...>.
    """
    if isinstance(x, ClSymbol):
        return x.name
    if isinstance(x, int):
        return str(x)
    if isinstance(x, str):
        escaped = x.replace("\\", "\\\\").replace('"', '\\"')
        return '"' + escaped + '"'
    if isinstance(x, ClCons):
        return cl_print_list(x)
    if isinstance(x, ClFunction):
        return "#<FUNCTION %s>" % x.name
    if isinstance(x, ClBuiltin):
        return "#<BUILTIN %s>" % x.name
    return "#<INTERNAL %r>" % (x,)


def cl_print_list(x):
    """Print a cons chain, using the quote shorthand and the dotted-pair form.

    The quote shorthand applies only to a two-element list whose car is QUOTE,
    so that (quote a b) still prints in full. The dotted form prints the last
    cdr after a lone '.', which is how (a b . c) reads back in.
    """
    if x.car is _CL_QUOTE and isinstance(x.cdr, ClCons) and x.cdr.cdr is CL_NIL:
        return "'" + cl_print(x.cdr.car)
    parts = []
    p = x
    while isinstance(p, ClCons):
        parts.append(cl_print(p.car))
        p = p.cdr
    if p is not CL_NIL:
        parts.append(".")
        parts.append(cl_print(p))
    return "(" + " ".join(parts) + ")"


# -----------------------------------------------------------------------------
# 4. Environments and the (leaky) dynamic stack
# -----------------------------------------------------------------------------
#
# A name can have a value in three places, searched in this order:
#
#   1. the lexical environment chain, a series of ClEnv frames built by let,
#      by calls and by lambda closures;
#   2. the dynamic stack, _CL_DYNAMIC, a per-symbol stack of values that let,
#      dolist, defun parameters and every function call push onto, and that
#      everything called from inside them sees;
#   3. the global value cell on the symbol itself, set by a top-level setq or
#      by defvar.
#
# Step 2 is the dynamic-scope rule of this implementation: every binding goes on
# the stack, so dynamic scope is the default. The rules for unwinding are
# described with let, dolist and function calls.


class ClEnv:
    """A lexical frame: a dict from ClSymbol to value, and a parent frame.

    The outermost frame is None, not a ClEnv. Lookups walk parent pointers until
    they find a frame that binds the symbol, or until they fall off the end.
    """

    __slots__ = ("vars", "parent")

    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent

    def frame_for(self, sym):
        """Return the nearest frame that binds SYM, or None if no frame does."""
        frame = self
        while frame is not None:
            if sym in frame.vars:
                return frame
            frame = frame.parent
        return None


# ClSymbol -> Python list used as a stack. The top of the stack is the last item.
_CL_DYNAMIC = {}


def cl_dyn_push(sym, value):
    """Push VALUE as the newest dynamic binding of SYM."""
    _CL_DYNAMIC.setdefault(sym, []).append(value)


def cl_dyn_pop(sym):
    """Remove the newest dynamic binding of SYM.

    Called only on the normal return path of let, dolist and user function
    calls. An error that unwinds past the caller skips the pop, and the binding
    stays on the stack until the session ends. The empty stack is deleted so that
    cl_dynamic_leftovers reports only what is still bound.
    """
    stack = _CL_DYNAMIC.get(sym)
    if stack:
        stack.pop()
        if not stack:
            del _CL_DYNAMIC[sym]


def cl_dyn_top(sym):
    """Return the newest dynamic value of SYM, or None if there is none."""
    stack = _CL_DYNAMIC.get(sym)
    if stack:
        return stack[-1]
    return None


def cl_dynamic_leftovers():
    """Return a dict of name -> value for every dynamic binding still on the stack.

    Reports the bindings that unwinding left behind. After an error inside a let,
    this dict is not empty, because nothing pops the stack on the error path.
    """
    return {sym.name: stack[-1] for sym, stack in _CL_DYNAMIC.items() if stack}


def cl_lookup(sym, env):
    """Find the value of SYM: lexical first, then dynamic, then global.

    The dynamic step applies the dynamic-scope rule. A variable that is not bound
    in any frame in scope is looked up on the dynamic stack, so a caller's let
    variables are found even though the callee's lexical environment has never
    heard of them.
    """
    frame = env.frame_for(sym) if env is not None else None
    if frame is not None:
        return frame.vars[sym]
    value = cl_dyn_top(sym)
    if value is not None:
        return value
    if sym.value is not None:
        return sym.value
    raise ClUnbound("unbound variable: %s" % sym.name)


def cl_assign(sym, value, env):
    """The setq rule: update the nearest existing binding, else the global cell.

    The same three places as lookup, in the same order. The dynamic step is the
    reason a callee's setq can change its caller's let variable: the callee has
    no lexical binding for the name, so the assignment lands on the dynamic
    stack's top value, which is the caller's. This is the dynamic-scope rule
    applied to assignment.
    """
    frame = env.frame_for(sym) if env is not None else None
    if frame is not None:
        frame.vars[sym] = value
        return
    stack = _CL_DYNAMIC.get(sym)
    if stack:
        stack[-1] = value
        return
    sym.value = value


# -----------------------------------------------------------------------------
# 5. Evaluator and application
# -----------------------------------------------------------------------------

# ClSymbol -> Python function taking (unevaluated_args_as_lisp_list, env).
_CL_SPECIAL = {}


def cl_eval(x, env=None):
    """Evaluate the Lisp form X in the lexical environment ENV (None for top level).

    Self-evaluating forms come back unchanged: integers, strings, CL_NIL and
    CL_T. A symbol is looked up. A cons is either a special form, which receives
    its operands unevaluated, or a function call. For a function call the head
    is resolved to a function, the arguments are evaluated left to right into a
    Python list, and cl_apply does the rest.

    A head that is a symbol names a global function, held in the symbol's
    function cell. A head that is a cons (a lambda form, say) is evaluated to a
    function value first, so ((lambda (x) x) 1) works.
    """
    if isinstance(x, ClSymbol):
        if x is CL_NIL or x is CL_T:
            return x
        return cl_lookup(x, env)
    if isinstance(x, ClCons):
        head = x.car
        if isinstance(head, ClSymbol) and head in _CL_SPECIAL:
            return _CL_SPECIAL[head](x.cdr, env)
        if isinstance(head, ClSymbol):
            fn = head.function
            if fn is None:
                raise ClUnbound("undefined function: %s" % head.name)
        else:
            fn = cl_eval(head, env)
        args = [cl_eval(a, env) for a in cl_to_py(x.cdr)]
        return cl_apply(fn, args)
    # Integers, strings, and anything else we do not know about are
    # self-evaluating.
    return x


def cl_apply(fn, args):
    """Call FN with ARGS, a Python list of already-evaluated arguments.

    A builtin is called directly. A Python TypeError from the call is almost
    always a wrong argument count, so it is re-raised as ClArity with the
    original text attached. A user function goes through _cl_call_user.
    Anything else is a ClType, because it is not a function at all.
    """
    if isinstance(fn, ClBuiltin):
        try:
            return fn.pyfn(*args)
        except TypeError as exc:
            raise ClArity("%s: %s" % (fn.name, exc))
    if isinstance(fn, ClFunction):
        return cl_call_user(fn, args)
    raise ClType("not a function: %s" % cl_print(fn))


def cl_call_user(fn, args):
    """Run a user function: bind its parameters, run its body, unbind.

    Each parameter is bound twice: in a fresh lexical frame whose parent is the
    function's closure environment, and on the dynamic stack. The body is
    evaluated in the lexical frame, and the value of the last form is the
    result. The dynamic bindings are popped on the normal return path.

    Arity: a call with too few arguments binds the missing parameters to CL_NIL.
    A call with too many arguments raises ClArity.
    """
    if len(args) > len(fn.params):
        raise ClArity("%s takes %d argument(s), got %d"
                      % (fn.name, len(fn.params), len(args)))
    frame = ClEnv(parent=fn.env)
    pushed = []
    for i, sym in enumerate(fn.params):
        value = args[i] if i < len(args) else CL_NIL
        frame.vars[sym] = value
        cl_dyn_push(sym, value)
        pushed.append(sym)
    result = cl_progn(fn.body, frame)
    # Normal return path only. An exception skips this loop, and the bindings
    # then remain on the dynamic stack.
    for sym in pushed:
        cl_dyn_pop(sym)
    return result


def cl_progn(forms, env):
    """Evaluate FORMS, a Python list, in order, and return the last value.

    An empty list returns CL_NIL, as (progn) does in Lisp.
    """
    result = CL_NIL
    for form in forms:
        result = cl_eval(form, env)
    return result


# -----------------------------------------------------------------------------
# 6. Special forms
# -----------------------------------------------------------------------------
#
# A special form receives its operands UNEVALUATED, as a Lisp list, along with
# the environment. Each one decides for itself what to evaluate and when. That
# is the whole reason special forms exist: `if` must not evaluate both branches,
# `quote` must not evaluate anything, and `let` must evaluate its values in the
# outer environment and only then bind them.


def cl_special(name):
    """Decorator: register the function as the special form NAME.

    The registration happens at import time, once, in the _CL_SPECIAL dict.
    """
    def register(fn):
        _CL_SPECIAL[cl_intern(name)] = fn
        return fn
    return register


@cl_special("QUOTE")
def sf_quote(args, env):
    """(quote x) returns X exactly as read, without evaluating it."""
    items = cl_to_py(args)
    if len(items) != 1:
        raise ClArity("quote takes exactly one argument, got %d" % len(items))
    return items[0]


@cl_special("IF")
def sf_if(args, env):
    """(if test then [else]). Only the branch that is chosen gets evaluated.

    A missing else returns CL_NIL. An if takes at most three operands, so an
    else with several forms is rejected with ClArity instead of being run
    as a progn, which is what a Lisp programmer might expect.
    """
    items = cl_to_py(args)
    if len(items) < 2 or len(items) > 3:
        raise ClArity("if takes 2 or 3 arguments, got %d" % len(items))
    if cl_eval(items[0], env) is not CL_NIL:
        return cl_eval(items[1], env)
    if len(items) == 3:
        return cl_eval(items[2], env)
    return CL_NIL


@cl_special("COND")
def sf_cond(args, env):
    """(cond (test form...) ...). The first clause whose test is non-NIL wins.

    A clause with only a test returns the value of that test, as it does in real
    Lisp. Tests are evaluated in order, and no later test is evaluated once a
    clause has won.

    When no clause matches, the body of the last clause is evaluated, so the last
    clause serves as a default. A cond with no matching clause therefore returns
    whatever its final clause computes.
    """
    clauses = cl_to_py(args)
    for clause in clauses:
        parts = cl_to_py(clause)
        if not parts:
            continue
        value = cl_eval(parts[0], env)
        if value is not CL_NIL:
            if len(parts) == 1:
                return value
            return cl_progn(parts[1:], env)
    if not clauses:
        return CL_NIL
    last_parts = cl_to_py(clauses[-1])
    return cl_progn(last_parts[1:], env)


@cl_special("DEFUN")
def sf_defun(args, env):
    """(defun name (params...) body...). Stores a function in NAME's function cell.

    Returns NAME, as Lisp does. A defun always closes over nothing: its
    environment is None, so the lexical variables of any enclosing let are not
    visible to it. Its dynamic bindings are still visible, since the
    dynamic-scope rule applies to everything. Redefining a name replaces the function cell outright, with
    no warning.
    """
    items = cl_to_py(args)
    if len(items) < 2:
        raise ClArity("defun needs a name and a parameter list")
    name, params_form = items[0], items[1]
    if not isinstance(name, ClSymbol):
        raise ClType("defun: name must be a symbol, got %s" % cl_print(name))
    params = cl_param_list(params_form, "defun " + name.name)
    name.function = ClFunction(name.name, params, items[2:], None)
    return name


def cl_param_list(form, who):
    """Check that FORM is a list of symbols, and return it as a Python list.

    Lambda-list keywords such as &optional and &rest are not implemented. They
    are read as ordinary symbols and bound as ordinary parameters, which means a
    lambda list with &rest in it simply has an extra parameter named &REST.
    Lambda-list keywords are not recognised by this implementation.
    """
    params = cl_to_py(form)
    for p in params:
        if not isinstance(p, ClSymbol):
            raise ClType("%s: parameter must be a symbol, got %s"
                         % (who, cl_print(p)))
    return params


@cl_special("LAMBDA")
def sf_lambda(args, env):
    """(lambda (params...) body...) returns a closure over the current frame.

    Unlike a defun, the closure remembers the lexical frame it was made in, so a
    lambda built inside a let can still see the let's variables when it is
    called later, after the let has returned. The closure also sees dynamic
    bindings under the dynamic-scope rule.
    """
    items = cl_to_py(args)
    if not items:
        raise ClArity("lambda needs a parameter list")
    params = cl_param_list(items[0], "lambda")
    return ClFunction("LAMBDA", params, items[1:], env)


@cl_special("LET")
def sf_let(args, env):
    """(let ((var expr) ...) body...). Parallel binding in a fresh lexical frame.

    Every value expression is evaluated in the OUTER environment before any
    variable is bound, so (let ((x 1) (y x)) ...) sees the outer x, not the new
    one. A bare symbol in the binding list binds it to CL_NIL.

    The bindings are also pushed on the dynamic stack, and they are popped when
    the body returns normally. An error in the body leaves them on the stack
    until the session ends.
    """
    items = cl_to_py(args)
    if not items:
        raise ClArity("let needs a binding list")
    frame = ClEnv(parent=env)
    pairs = []
    for binding in cl_to_py(items[0]):
        if isinstance(binding, ClSymbol):
            pairs.append((binding, CL_NIL))
            continue
        parts = cl_to_py(binding)
        if not parts or not isinstance(parts[0], ClSymbol):
            raise ClType("let: bad binding %s" % cl_print(binding))
        value_form = parts[1] if len(parts) > 1 else CL_NIL
        pairs.append((parts[0], cl_eval(value_form, env)))
    pushed = []
    for sym, value in pairs:
        frame.vars[sym] = value
        cl_dyn_push(sym, value)
        pushed.append(sym)
    result = cl_progn(items[1:], frame)
    for sym in pushed:
        cl_dyn_pop(sym)
    return result


@cl_special("SETQ")
def sf_setq(args, env):
    """(setq var expr var2 expr2 ...). Assigns in order and returns the last value.

    Each assignment follows the rule in _cl_assign: the nearest existing
    binding is updated, the dynamic stack is next, and the global cell is the
    fallback. (setq) with no arguments returns CL_NIL.
    """
    items = cl_to_py(args)
    if len(items) % 2 != 0:
        raise ClArity("setq needs an even number of arguments")
    value = CL_NIL
    for i in range(0, len(items), 2):
        sym = items[i]
        if not isinstance(sym, ClSymbol):
            raise ClType("setq: not a symbol: %s" % cl_print(sym))
        value = cl_eval(items[i + 1], env)
        cl_assign(sym, value, env)
    return value


@cl_special("PROGN")
def sf_progn(args, env):
    """(progn form...) evaluates each form in turn and returns the last value."""
    return cl_progn(cl_to_py(args), env)


@cl_special("AND")
def sf_and(args, env):
    """(and form...) stops at the first CL_NIL and returns it.

    Otherwise it returns the value of the last form. With no forms at all, the
    result is CL_T, as in Lisp.
    """
    result = CL_T
    for form in cl_to_py(args):
        result = cl_eval(form, env)
        if result is CL_NIL:
            return CL_NIL
    return result


@cl_special("OR")
def sf_or(args, env):
    """(or form...) returns the first non-NIL value, or CL_NIL if there is none."""
    for form in cl_to_py(args):
        result = cl_eval(form, env)
        if result is not CL_NIL:
            return result
    return CL_NIL


@cl_special("WHEN")
def sf_when(args, env):
    """(when test form...). Runs the forms if TEST is non-NIL, else returns CL_NIL."""
    items = cl_to_py(args)
    if not items:
        raise ClArity("when needs a test form")
    if cl_eval(items[0], env) is CL_NIL:
        return CL_NIL
    return cl_progn(items[1:], env)


@cl_special("UNLESS")
def sf_unless(args, env):
    """(unless test form...). The inverse of when: runs the forms if TEST is NIL."""
    items = cl_to_py(args)
    if not items:
        raise ClArity("unless needs a test form")
    if cl_eval(items[0], env) is not CL_NIL:
        return CL_NIL
    return cl_progn(items[1:], env)


@cl_special("DOLIST")
def sf_dolist(args, env):
    """(dolist (var list-form [result-form]) body...).

    Runs BODY once per element of the list, with VAR bound to that element in a
    fresh lexical frame. The variable is also pushed on the dynamic stack, and like
    let it is popped only when the body returns normally. The optional
    result form is evaluated after the loop with VAR unbound, and its value is
    the value of the whole form. Without one, the value is CL_NIL.
    """
    items = cl_to_py(args)
    if not items:
        raise ClArity("dolist needs a (var list) spec")
    spec = cl_to_py(items[0])
    if len(spec) < 2 or not isinstance(spec[0], ClSymbol):
        raise ClType("dolist: bad spec %s" % cl_print(items[0]))
    var = spec[0]
    seq = cl_eval(spec[1], env)
    body = items[1:]
    for element in cl_to_py(seq):
        frame = ClEnv(parent=env)
        frame.vars[var] = element
        cl_dyn_push(var, element)
        cl_progn(body, frame)
        cl_dyn_pop(var)
    if len(spec) >= 3:
        return cl_eval(spec[2], env)
    return CL_NIL


@cl_special("DEFVAR")
def sf_defvar(args, env):
    """(defvar name [init]). Sets the GLOBAL value of NAME if it is still unbound.

    Returns NAME. Real defvar also marks NAME as special, so that later lets bind
    it dynamically on purpose. Here it does not mark the name, because every let
    is already dynamic, so the declaration adds nothing.
    """
    items = cl_to_py(args)
    if not items or not isinstance(items[0], ClSymbol):
        raise ClType("defvar needs a symbol")
    sym = items[0]
    if sym.value is None and len(items) > 1:
        sym.value = cl_eval(items[1], env)
    return sym


# -----------------------------------------------------------------------------
# 7. Builtins
# -----------------------------------------------------------------------------
#
# Each builtin is an ordinary Python function that takes evaluated arguments.
# The decorator below installs it in the function cell of the symbol with the
# same name, so the evaluator finds it the same way it finds a defun. Python
# names are prefixed with _cl_b_ so they cannot shadow anything in this module.


def cl_builtin(name):
    """Decorator: install the Python function as the global function NAME."""
    def register(fn):
        sym = cl_intern(name)
        sym.function = ClBuiltin(sym.name, fn)
        return fn
    return register


def cl_chain(nums, who, test):
    """Check that TEST holds between every adjacent pair of NUMS, all integers.

    Used by the comparison builtins. With fewer than two arguments there is
    nothing to compare, so that is an arity error, not a vacuous T.
    """
    if len(nums) < 2:
        raise ClArity("%s: needs at least two arguments" % who)
    for n in nums:
        cl_need_int(n, who)
    for a, b in zip(nums, nums[1:]):
        if not test(a, b):
            return CL_NIL
    return CL_T


@cl_builtin("CAR")
def cl_b_car(x):
    """(car x): the first element of a cons. (car nil) is CL_NIL. Anything else is a type error."""
    if x is CL_NIL:
        return CL_NIL
    if isinstance(x, ClCons):
        return x.car
    raise ClType("car: not a list: %s" % cl_print(x))


@cl_builtin("CDR")
def cl_b_cdr(x):
    """(cdr x): the rest of a list. (cdr nil) is CL_NIL. Anything else is a type error."""
    if x is CL_NIL:
        return CL_NIL
    if isinstance(x, ClCons):
        return x.cdr
    raise ClType("cdr: not a list: %s" % cl_print(x))


@cl_builtin("CONS")
def cl_b_cons(a, b):
    """(cons a b) makes a new cell. (cons 1 nil) is the list (1)."""
    return ClCons(a, b)


@cl_builtin("LIST")
def cl_b_list(*items):
    """(list a b c) is a fresh proper list of its arguments. (list) is CL_NIL."""
    return cl_from_py(items)


@cl_builtin("+")
def cl_b_add(*nums):
    """(+ a b ...). With no arguments the sum is 0."""
    total = 0
    for n in nums:
        total += cl_need_int(n, "+")
    return total


@cl_builtin("-")
def cl_b_sub(*nums):
    """(- a b ...). Subtracts every later argument from the first.

    With exactly one argument, (- x) returns x. With more arguments, every later
    argument is subtracted from the first.
    """
    if not nums:
        raise ClArity("-: needs at least one argument")
    first = cl_need_int(nums[0], "-")
    if len(nums) == 1:
        return first
    total = first
    for n in nums[1:]:
        total -= cl_need_int(n, "-")
    return total


@cl_builtin("*")
def cl_b_mul(*nums):
    """(* a b ...). With no arguments the product is 1."""
    total = 1
    for n in nums:
        total *= cl_need_int(n, "*")
    return total


@cl_builtin("/")
def cl_b_div(*nums):
    """(/ a b ...). Integer division, applied left to right.

    Division uses Python's // operator, which floors toward negative infinity, so
    (/ -7 2) is -4. Division by zero raises ZeroDivisionError, which the REPL
    reports as an internal error.

    A one-argument reciprocal, (/ x), is not implemented and raises ClArity.
    """
    if not nums:
        raise ClArity("/: needs at least one argument")
    total = cl_need_int(nums[0], "/")
    if len(nums) == 1:
        raise ClArity("/: the one-argument reciprocal is not implemented")
    for n in nums[1:]:
        total = total // cl_need_int(n, "/")
    return total


@cl_builtin("=")
def cl_b_numeq(*nums):
    """(= a b ...): T if the arguments are numerically equal.

    Only the first two arguments are compared. Further arguments are checked for
    type only, so (= 1 1 2) is T, and a non-integer third argument still raises.
    """
    if len(nums) < 2:
        raise ClArity("=: needs at least two arguments")
    a = cl_need_int(nums[0], "=")
    b = cl_need_int(nums[1], "=")
    for n in nums[2:]:
        cl_need_int(n, "=")
    return cl_bool(a == b)


@cl_builtin("<")
def cl_b_lt(*nums):
    """(< a b c ...): T if every argument is strictly less than the next one."""
    return cl_chain(nums, "<", lambda a, b: a < b)


@cl_builtin(">")
def cl_b_gt(*nums):
    """(> a b c ...): T if every argument is strictly greater than the next one."""
    return cl_chain(nums, ">", lambda a, b: a > b)


@cl_builtin("<=")
def cl_b_le(*nums):
    """(<= a b c ...): T if every argument is less than or equal to the next one."""
    return cl_chain(nums, "<=", lambda a, b: a <= b)


@cl_builtin(">=")
def cl_b_ge(*nums):
    """(>= a b c ...): T if every argument is greater than or equal to the next one."""
    return cl_chain(nums, ">=", lambda a, b: a >= b)


@cl_builtin("MIN")
def cl_b_min(*nums):
    """(min a b ...): the least argument. At least one argument is required."""
    if not nums:
        raise ClArity("min: needs at least one argument")
    return min(cl_need_int(n, "min") for n in nums)


@cl_builtin("MAX")
def cl_b_max(*nums):
    """(max a b ...): the greatest argument. At least one argument is required."""
    if not nums:
        raise ClArity("max: needs at least one argument")
    return max(cl_need_int(n, "max") for n in nums)


@cl_builtin("ABS")
def cl_b_abs(x):
    """(abs x): the absolute value of an integer."""
    return abs(cl_need_int(x, "abs"))


@cl_builtin("MOD")
def cl_b_mod(a, b):
    """(mod a b): the remainder with the sign of the divisor.

    Python's % operator already does this, and so does Common Lisp's mod.
    """
    cl_need_int(a, "mod")
    cl_need_int(b, "mod")
    return a % b


@cl_builtin("NULL")
def cl_b_null(x):
    """(null x) is T only for CL_NIL."""
    return cl_bool(x is CL_NIL)


@cl_builtin("NOT")
def cl_b_not(x):
    """(not x) is the same test as null. Defined separately so both names exist."""
    return cl_bool(x is CL_NIL)


@cl_builtin("ATOM")
def cl_b_atom(x):
    """(atom x) is T for anything that is not a cons. CL_NIL is an atom in this file."""
    return cl_bool(not isinstance(x, ClCons))


@cl_builtin("CONSP")
def cl_b_consp(x):
    """(consp x) is T for a cons cell, which excludes CL_NIL."""
    return cl_bool(isinstance(x, ClCons))


@cl_builtin("LISTP")
def cl_b_listp(x):
    """(listp x) is T for a cons cell or for CL_NIL."""
    return cl_bool(x is CL_NIL or isinstance(x, ClCons))


@cl_builtin("SYMBOLP")
def cl_b_symbolp(x):
    """(symbolp x) is T for any symbol, including CL_NIL and CL_T."""
    return cl_bool(isinstance(x, ClSymbol))


@cl_builtin("NUMBERP")
def cl_b_numberp(x):
    """(numberp x) is T for an integer."""
    return cl_bool(isinstance(x, int) and not isinstance(x, bool))


@cl_builtin("STRINGP")
def cl_b_stringp(x):
    """(stringp x) is T for a Lisp string."""
    return cl_bool(isinstance(x, str))


@cl_builtin("EQ")
def cl_b_eq(a, b):
    """(eq a b): the identity test, with small integers compared by value."""
    return cl_bool(cl_eql(a, b))


@cl_builtin("PRINT")
def cl_b_print(x):
    """(print x) writes the printed form of X and a newline, then returns X.
    """
    print(cl_print(x))
    return x


@cl_builtin("NTH")
def cl_b_nth(n, lst):
    """(nth n list): the element following index N, or CL_NIL past the end.

    The walk advances N+1 cells (the successor convention), so the element
    returned is the one after the cell at index N. (nth 0 '(a b c)) is B, and
    (nth 2 '(a b c)) is CL_NIL.
    """
    cl_need_int(n, "nth")
    p = lst
    for _ in range(n + 1):
        if not isinstance(p, ClCons):
            return CL_NIL
        p = p.cdr
    if isinstance(p, ClCons):
        return p.car
    return CL_NIL


@cl_builtin("LENGTH")
def cl_b_length(x):
    """(length x) for a proper list or a string.

    A dotted list is measured up to its dotted tail, because cl_to_py stops there;
    the count of proper elements is returned.
    """
    if isinstance(x, str):
        return len(x)
    if x is CL_NIL or isinstance(x, ClCons):
        return len(cl_to_py(x))
    raise ClType("length: not a sequence: %s" % cl_print(x))


@cl_builtin("APPEND")
def cl_b_append(*lists):
    """(append l1 l2 ...): copies every list but the last, which is shared.

    The copies go through cl_to_py, so a dotted tail in one of the lists is not
    carried over. With no arguments the result is CL_NIL.
    """
    if not lists:
        return CL_NIL
    result = lists[-1]
    for lst in reversed(lists[:-1]):
        result = cl_from_py(cl_to_py(lst), result)
    return result


@cl_builtin("REVERSE")
def cl_b_reverse(lst):
    """(reverse list): a new list with the elements in the opposite order."""
    result = CL_NIL
    for item in cl_to_py(lst):
        result = ClCons(item, result)
    return result


@cl_builtin("MAPCAR")
def cl_b_mapcar(fn, lst):
    """(mapcar fn list): a new list of FN applied to each element of LST.

    FN is a Lisp function value (a defun name quoted, a lambda, or a builtin),
    and it is applied through cl_apply, like any other call.
    """
    return cl_from_py([cl_apply(fn, [x]) for x in cl_to_py(lst)])


@cl_builtin("MEMBER")
def cl_b_member(item, lst):
    """(member x list): the tail of LST that starts at the first element eql to X.

    Returns CL_NIL if there is no such element. Uses _cl_eql, so the same rules
    as eq apply.
    """
    p = lst
    while isinstance(p, ClCons):
        if cl_eql(item, p.car):
            return p
        p = p.cdr
    return CL_NIL


@cl_builtin("ASSOC")
def cl_b_assoc(key, alist):
    """(assoc key alist): the first cons in ALIST whose car is eql to KEY.

    Entries that are not conses are skipped without comment, as Lisp skips nil
    entries in an alist. Returns CL_NIL when nothing matches.
    """
    p = alist
    while isinstance(p, ClCons):
        entry = p.car
        if isinstance(entry, ClCons) and cl_eql(key, entry.car):
            return entry
        p = p.cdr
    return CL_NIL


@cl_builtin("FUNCALL")
def cl_b_funcall(fn, *args):
    """(funcall fn arg ...): call a function value with the given arguments.

    Needed because the evaluator resolves a symbol in head position to its
    function cell, and a function held in a variable cannot be called that way.
    """
    return cl_apply(fn, list(args))


@cl_builtin("ERROR")
def cl_b_error(fmt, *args):
    """(error "message" arg ...): raise a ClError with the message.

    There are no format directives. The arguments are printed and appended to
    the message, separated by spaces. The REPL then prints the result as
    ClError: message, which is the one way a Lisp program can fail on purpose.
    """
    text = str(fmt)
    if args:
        text += " " + " ".join(cl_print(a) for a in args)
    raise ClError(text)


# -----------------------------------------------------------------------------
# 8. Top level: evaluating text, a REPL, and a demonstration
# -----------------------------------------------------------------------------


def cl_eval_text(text, env=None):
    """Read every form in TEXT and evaluate them in order.

    Returns a Python list with one value per top-level form. An error stops the
    run and propagates to the caller. A failing let leaves its binding on the
    dynamic stack afterwards.
    """
    results = []
    for form in ClReader(text).read_all():
        results.append(cl_eval(form, env))
    return results


def cl_format_error(exc):
    """Return the one-line message the REPL prints for the exception EXC.

    A ClError subclass prints its class name and its message. A RecursionError is
    reported as an exhausted Lisp stack. Any other exception is an internal error,
    and the text says so.
    """
    if isinstance(exc, RecursionError):
        return "control stack exhausted"
    if isinstance(exc, ClError):
        return "%s: %s" % (type(exc).__name__, exc)
    return "internal error (%s): %s" % (type(exc).__name__, exc)


def cl_repl(read=None, write=None, env=None):
    """A read-eval-print loop. READ defaults to input(), WRITE defaults to print().

    The loop keeps reading lines while the accumulated text fails with ClEOF,
    which means parentheses or a string are still open. Any other read error is
    printed and the buffer is thrown away. Each complete form is evaluated and
    its printed value written; the first error in a line stops that line.

    Dynamic bindings are NOT reset between forms, so a let that raised leaves its
    variable visible at later prompts. There
    is no (quit) builtin, so end the session with Ctrl-D, which returns 0.
    """
    read = read or input
    write = write or print
    buffer = ""
    while True:
        prompt = "cl> " if not buffer else "  > "
        try:
            line = read(prompt)
        except EOFError:
            return 0
        buffer = (buffer + "\n" + line) if buffer else line
        if not buffer.strip():
            buffer = ""
            continue
        try:
            forms = ClReader(buffer).read_all()
        except ClEOF:
            continue                      # the form is not finished yet
        except ClError as exc:
            write(cl_format_error(exc))
            buffer = ""
            continue
        buffer = ""
        for form in forms:
            try:
                write(cl_print(cl_eval(form, env)))
            except Exception as exc:      # ClError, RecursionError, other exceptions
                write(cl_format_error(exc))
                break


# A short program exercising the special forms and the builtins.
CL_DEMO_PROGRAM = """
; recursion
(defun fact (n)
  (if (< n 2)
      1
      (* n (fact (- n 1)))))

(fact 10)

; closures
(defun make-adder (k)
  (lambda (x) (+ x k)))

(funcall (make-adder 5) 10)

; lists
(cons 1 (list 2 3))
(car '(a b c))
(cdr '(a b c))
(append '(1 2) '(3 4))
(reverse '(1 2 3))
(mapcar (lambda (x) (* x x)) '(1 2 3))

; numbers, conditionals and indexing
(nth 0 '(a b c))
(= 1 1 2)
(- 7)
(/ -7 2)
(cond ((= 1 2) 'a) ((= 3 4) 'b))

; a callee reads a variable bound by its caller's let
(defun show-caller-local () secret)
(let ((secret 42)) (show-caller-local))

; a zero-argument defun, called for its value
(defun answer () (+ 1 1))
(answer)
"""


def cl_demo(write=None):
    """Run CL_DEMO_PROGRAM, print each top-level result, then show the leftover binding.

    The first part prints one line per top-level form of the demo program. The
    second part runs a let that signals an error, catches the error, and then
    reads the variable back to show that it remains bound after the unwind.
    """
    write = write or print
    values = cl_eval_text(CL_DEMO_PROGRAM)
    for value in values:
        write(cl_print(value))
    try:
        cl_eval_text('(let ((leak 1)) (error "boom"))')
    except ClError as exc:
        write("expected error: " + cl_format_error(exc))
    leaked = cl_eval_text("leak")[0]
    write("after the error, LEAK is still " + cl_print(leaked))
    write("dynamic leftovers: " + repr(cl_dynamic_leftovers()))
    return values


if __name__ == "__main__":
    sys.exit(main())
