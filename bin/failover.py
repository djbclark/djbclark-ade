#!/usr/bin/env python3
"""failover — run a task through an ordered chain of agent routes; the first that works wins.

A *chain* is an ordered list of entries (rungs). Each entry names a TUI or
endpoint from the REGISTRY below, a model, an effort, the aiuse pool it draws
and a floor. For every entry, in order:

1. **load-time policy**: an entry is refused outright (ChainError) when it names
   a globally denied route (DENY: cursor, cline/ClinePass, Hermes, any Opus or
   Fable model; operator 2026-10-12), a TUI outside the caller's allowlist, a TUI
   the registry does not know, a model the TUI's `model_allow` rejects, or an
   effort the TUI has no lever for;
2. **preflight**: the binary exists (`acp-run --list` shows the agent `ok`), the
   pool is `usable_now` in `aiuse --available --json` with headroom above the
   entry's floor, and any secret the entry needs is declared in sudo-secretspec;
3. **attempt**: the caller's function runs the task on that entry; it returns
   ok or a reason. A failure moves on to the next entry.

Every preflight and attempt is one JSON line in the attempt log
(`~/.local/state/failover/attempts.jsonl` unless the caller names one).

Two ways to execute an entry are built in: `ask()` answers one prompt (acp-run in
a clean empty directory with `--perm deny`, a fresh context; acp-run makes deny real
per agent, and a tripwire exits 77 if a tool still runs without asking, which
`ask()` turns into AttemptFailed; or an OpenAI-compatible POST for `openai_compat`
entries, key from sudo-secretspec held in memory once per process, never
redirected), and `run_command()` runs any shell-callable task with the entry's
fields substituted into argv and exported as FAILOVER_*. Children get a minimal
env (BASE_ENV_KEYS plus the entry's allow-listed env) and run in their own process
group, killed whole on timeout. Preflight's canary asks every acp entry to create a
file and refuses the entry if it can.

CLI:
    failover.py registry                                 # the route table
    failover.py check --chain FILE [--allow a,b]          # preflight table, no model calls
    failover.py ask   --chain FILE (-p TEXT | -f FILE)    # answer one prompt via the chain
    failover.py run   --chain FILE -- CMD {model} ...     # any command; first rc 0 wins

A chain FILE is JSON: either a list of entries or {"chain": [...], "allow": [...]}.
Entry keys: tui (required), model, effort, floor_percent (default 5), pool and
pool_family (override the registry), endpoint (openai_compat), secret (a
sudo-secretspec name exported as `secret_env`, default OPENAI_API_KEY for
`run`; only to the registry endpoint, https or loopback), env (ENV_ALLOW keys
only), extra_args (appended to acp-run; only EXTRA_ARGS_ALLOWED flags), timeout, label,
probe, health_url. Importable: skillopt-night uses load_chain/preflight/run_chain/ask.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
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
# (operator 2026-10-12): never cursor, never cline/ClinePass, never Hermes,
# never Claude Opus or anything stronger (Fable).
DENY = ("cursor", "cline", "clinepass", "hermes", "opus", "fable")
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
ACP_LOG_DIR = Path.home() / ".local" / "state" / "failover" / "acp-logs"
LOG_RETENTION_DAYS = 7


class ChainError(ValueError):
    """A chain entry violates policy or names an unknown route."""


class AttemptFailed(RuntimeError):
    """One entry could not do the task; the chain moves on."""


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
    effort: str | None = None                  # "set:<option>" | "suffix" | None
    efforts: tuple[str, ...] = ()
    endpoint: str | None = None
    secret: str | None = None                  # sudo-secretspec name for openai_compat
    health_by_model: tuple[tuple[str, str], ...] = ()  # (model prefix, URL that must GET 200)
    native_models: tuple[tuple[str, str], ...] = ()    # acp-run model value -> full model id
    probe: bool = False                        # preflight sends one tiny prompt (no quota pool)
    # "strict": the canary needs zero tool calls. "asked_denied_ok": tool calls are
    # tolerated if every one asked permission and was denied (none allowed, no
    # tripwire). Registry-only, so a chain file cannot loosen it.
    canary: str = "strict"
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
        models=("gemini-3.8-flash-low", "gemini-3.8-flash-medium", "gemini-3.8-flash-high",
                "gemini-3.1-pro-low", "claude-sonnet-5-5-medium", "gpt-oss-120b-medium"),
        effort="suffix", efforts=("low", "medium", "high"),
        # djbclark 2026-10-12: agy's canary calls all asked and were denied, so for agy
        # asked-and-denied counts as held; the tripwire still fires on any unasked tool.
        canary="asked_denied_ok",
        note="effort is the model id suffix; Gemini and Claude/GPT are separate pools"),
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
    Tui("codex", "acp", "codex", "OpenAI", "codex", None, note="opencodex GPT pool"),
    Tui("copilot", "acp", "copilot", "GitHub", "copilot", None),
    Tui("grok", "acp", "grok", "xAI", "grok", None, note="reserve pool (GrokBot)"),
    Tui("qwen", "acp", "qwen", "Alibaba", None, None),
    Tui("crush", "acp", "crush", "Charm", None, None, takes_model=False, probe=True,
        note="crush-acp (PR 2450 build), default model from crushrc (SIPB); never --model"),
    # Listed so a chain naming them fails with a clear reason (DENY also catches them).
    Tui("cursor", "acp", "cursor", "Cursor", "cursor", None, note="denied"),
    Tui("cline", "acp", "cline", "ClinePass", "clinepass", None, note="denied: reserve"),
    Tui("hermes", "acp", "hermes", "Hermes", None, None, note="denied"),
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
        """The model id as the TUI expects it (agy carries effort in the id)."""
        if self.tui.effort == "suffix" and self.effort and not self.model.endswith(f"-{self.effort}"):
            return f"{self.model}-{self.effort}"
        return self.model

    @property
    def native_model(self) -> str:
        """The full model id for SkillOpt's native backends (--native)."""
        return dict(self.tui.native_models).get(self.model, self.model_arg)

    def row(self) -> dict[str, Any]:
        return {"label": self.label, "tui": self.tui.name, "vendor": self.tui.vendor,
                "model": self.model_arg or None, "effort": self.effort or None,
                "pool": self.pool, "pool_family": self.pool_family,
                "floor_percent": self.floor_percent}


# ── loading and policy ───────────────────────────────────────────────────────

def denied(text: str, deny: tuple[str, ...] = DENY) -> str | None:
    """The first denied word that is a whole token of text (split on non-alphanumerics),
    so "pi" catches "pi" but not "api", and "opus" catches "claude-opus-5-5-low"."""
    tokens = set(re.split(r"[^a-z0-9]+", text.lower()))
    return next((d for d in deny if d in tokens), None)


def load_chain(spec: Any, *, allow: list[str] | None = None,
               deny: tuple[str, ...] = DENY) -> list[Entry]:
    """Validate a chain spec (list, or dict with "chain"/"allow") into Entries.

    Refuses the whole chain on the first bad entry: a policy violation is a
    config error to fix, not a rung to skip at 03:30."""
    if isinstance(spec, dict):
        allow = allow if allow is not None else spec.get("allow")
        spec = spec.get("chain", [])
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
                      probe=raw.get("probe"), health_url=raw.get("health_url"))
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


def load_chain_file(path: Path, *, allow: list[str] | None = None) -> list[Entry]:
    try:
        spec = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise ChainError(f"cannot read chain {path}: {e}") from e
    return load_chain(spec, allow=allow)


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
    key = f"probe:{entry.label}"
    if key not in _cache:
        try:
            answer = ask(entry, PROBE_PROMPT)
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
              log_path: Path | None = None, check: bool = True) -> ChainResult:
    """Try entries in order: preflight, then attempt(entry). attempt returns a value
    on success and raises AttemptFailed (or returns an AttemptFailed) otherwise."""
    rows = []
    for entry in entries:
        if check:
            ok, why = preflight(entry)
            row = {"task": task, "phase": "preflight", "ok": ok, "why": why, **entry.row()}
            rows.append(row)
            log_attempt(log_path, row)
            if not ok:
                continue
        t0 = time.monotonic()
        try:
            value = attempt(entry)
            if isinstance(value, AttemptFailed):
                raise value
        except AttemptFailed as e:
            row = {"task": task, "phase": "attempt", "ok": False, "why": str(e),
                   "seconds": round(time.monotonic() - t0, 1), **entry.row()}
            rows.append(row)
            log_attempt(log_path, row)
            continue
        row = {"task": task, "phase": "attempt", "ok": True, "why": "",
               "seconds": round(time.monotonic() - t0, 1), **entry.row()}
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
    cmd = [acp_run(), entry.tui.acp_agent or entry.tui.name, "-C", str(cwd), "-f", str(prompt_file),
           "--perm", "deny", "--timeout", str(entry.timeout)]
    if log is not None:
        cmd += ["--log", str(log)]
    if entry.tui.takes_model and entry.model_arg:
        cmd += ["--model", entry.model_arg]
    lever = entry.tui.effort or ""
    if entry.effort and lever.startswith("set:"):
        cmd += ["--set", f"{lever[4:]}={entry.effort}"]
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


def ask(entry: Entry, prompt: str) -> str:
    """Answer one prompt on this entry in a fresh context; raise AttemptFailed.

    acp-run runs it in an empty temp dir under --perm deny, which acp-run enforces
    per agent and backs with a tripwire (exit 77, EXIT_TRIPWIRE)."""
    if entry.tui.kind == "openai_compat":
        return _ask_openai(entry, prompt)
    proc, _, log = _acp_once(entry, prompt)
    answer = (proc.stdout or "").strip()
    if proc.returncode == 1 and answer and answer_despite_failure(result_in_log(log)):
        return answer
    if proc.returncode == EXIT_TRIPWIRE:
        raise AttemptFailed(f"{entry.label}: TRIPWIRE: a tool ran without a permission request "
                            "under --perm deny (acp-run exit 77)")
    if proc.returncode != 0 or not answer:
        tail = (proc.stderr or "").strip().splitlines()[-1:] or [""]
        raise AttemptFailed(f"{entry.label}: acp-run rc={proc.returncode}"
                            f"{' empty answer' if not answer else ''} {tail[0][:200]}")
    return answer


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
            if row.get("kind") == "result":
                return row.get("data") or {}
    except (OSError, ValueError):
        return None
    return None


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


def _ask_openai(entry: Entry, prompt: str) -> str:
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
    return answer


def ask_many(entry: Entry, prompts: dict[str, str], *, jobs: int = 2) -> dict[str, str]:
    """Answer every prompt on ONE entry (no mid-batch model switch); any failure fails all."""
    pool = ThreadPoolExecutor(max_workers=max(1, jobs))
    futures = {k: pool.submit(ask, entry, p) for k, p in prompts.items()}
    try:
        return {k: f.result() for k, f in futures.items()}
    except AttemptFailed:
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
        print_table(rows, ["#", "label", "vendor", "pool", "pool_family", "floor_percent", "ready", "why"])
        return 0 if any(r["ready"] == "yes" for r in rows) else 1
    if a.cmd == "ask":
        prompt = a.prompt if a.prompt is not None else a.file.read_text()
        res = run_chain(entries, lambda e: ask(e, prompt), task="ask", log_path=a.log)
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
