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
import stat
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


TMP_DIR_RE = re.compile(r"failover-[a-z0-9_]{8}")  # tempfile.TemporaryDirectory(prefix="failover-") names
TMP_RETENTION_DAYS = 1.0


def sweep_tmp_dirs(max_age_days: float = TMP_RETENTION_DAYS) -> int:
    """Delete failover-* temp dirs that killed runs left in tempfile.gettempdir(); return how many went.

    _acp_once() runs each turn in a TemporaryDirectory(prefix="failover-"), which a SIGKILLed
    run never cleans up (a background process can also re-create work/.cache after cleanup).
    Only a real directory (lstat: a symlink is never followed or removed) named exactly like
    tempfile's output (prefix plus 8 of [a-z0-9_]), owned by this user, and whose own mtime and
    every direct child's mtime are older than max_age_days is removed, so a live run's dir
    (just made, or still written to) stays. shutil.rmtree unlinks nested symlinks, never
    follows them. Every error is swallowed: this is housekeeping and never fails the caller."""
    cutoff, n = time.time() - max_age_days * 86400, 0
    try:
        entries = list(os.scandir(tempfile.gettempdir()))
    except OSError:
        return 0
    for e in entries:
        try:
            if not TMP_DIR_RE.fullmatch(e.name):
                continue
            st = e.stat(follow_symlinks=False)
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
                continue
            newest = st.st_mtime
            with os.scandir(e.path) as it:
                for child in it:
                    newest = max(newest, child.stat(follow_symlinks=False).st_mtime)
            if newest >= cutoff:
                continue
            shutil.rmtree(e.path, ignore_errors=True)
            if not os.path.lexists(e.path):
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


if __name__ == "__main__":
    sys.exit(main())
