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

Two ways to execute an entry are built in: `ask()` answers one prompt (acp-run
in a clean empty directory with `--perm deny`, so a fresh context with no tools;
or an OpenAI-compatible POST for `openai_compat` entries, key from
sudo-secretspec held in memory only), and `run_command()` runs any shell-callable
task with the entry's fields substituted into argv and exported as FAILOVER_*.

CLI:
    failover.py registry                                 # the route table
    failover.py check --chain FILE [--allow a,b]          # preflight table, no model calls
    failover.py ask   --chain FILE (-p TEXT | -f FILE)    # answer one prompt via the chain
    failover.py run   --chain FILE -- CMD {model} ...     # any command; first rc 0 wins

A chain FILE is JSON: either a list of entries or {"chain": [...], "allow": [...]}.
Entry keys: tui (required), model, effort, floor_percent (default 5), pool and
pool_family (override the registry), endpoint (openai_compat), secret (a
sudo-secretspec name exported as `secret_env`, default OPENAI_API_KEY for
`run`), env (literal extra env), extra_args (list, appended to acp-run), timeout,
label. Importable: skillopt-night uses load_chain/preflight/run_chain/ask.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
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
    pool_by_model: tuple[tuple[str, str, str | None], ...] = ()  # (model prefix, pool, family)
    models: tuple[str, ...] = ()               # known ids (illustrative, from live lists)
    model_allow: str | None = None             # regex every model must match
    takes_model: bool = True
    effort: str | None = None                  # "set:<option>" | "suffix" | None
    efforts: tuple[str, ...] = ()
    endpoint: str | None = None
    secret: str | None = None                  # sudo-secretspec name for openai_compat
    note: str = ""


# Model lists from acp-dispatch's live probes (~/.cache/acp-dispatch, 2026-10-12)
# and the docs; they are hints, not a gate. `acp-run <agent> --info` is the authority.
REGISTRY: dict[str, Tui] = {t.name: t for t in (
    Tui("claude", "acp", "claude", "Anthropic", "claude", "default",
        models=("haiku", "sonnet"),
        model_allow=r"^(haiku|sonnet|claude-(haiku|sonnet)-[\w.-]+)$",
        note="Claude shared pool; Haiku or Sonnet only (Opus/Fable denied)"),
    Tui("agy", "acp", "agy", "Google", None, None,
        pool_by_model=(("gemini-", "antigravity", "gemini"),
                       ("claude-", "antigravity", "claude_gpt"),
                       ("gpt-", "antigravity", "claude_gpt")),
        models=("gemini-3.8-flash-low", "gemini-3.8-flash-medium", "gemini-3.8-flash-high",
                "gemini-3.1-pro-low", "claude-sonnet-5-5-medium", "gpt-oss-120b-medium"),
        effort="suffix", efforts=("low", "medium", "high"),
        note="effort is the model id suffix; Gemini and Claude/GPT are separate pools"),
    Tui("opencode", "acp", "opencode", "OpenCode Go", None, None,
        pool_by_model=(("opencode-go/", "opencode-go", None),),
        models=("opencode-go/deepseek-v4-flash", "opencode-go/deepseek-v4-pro",
                "opencode-go/kimi-k3", "opencode-go/glm-5.3", "opencode-go/qwen3.8-max"),
        note="model must name its provider (opencode-go/...) for the pool to be known"),
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
    Tui("crush", "acp", "crush", "Charm", None, None, takes_model=False,
        note="under discussion; SIPB via crushrc"),
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

    def __post_init__(self) -> None:
        if not self.label:
            self.label = f"{self.tui.name}:{self.model or 'default'}" + (
                f"@{self.effort}" if self.effort else "")
        if self.pool is None and self.pool_family is None:
            self.pool, self.pool_family = self._registry_pool()
        self.endpoint = self.endpoint or self.tui.endpoint
        self.secret = self.secret or self.tui.secret

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

    def row(self) -> dict[str, Any]:
        return {"label": self.label, "tui": self.tui.name, "vendor": self.tui.vendor,
                "model": self.model_arg or None, "effort": self.effort or None,
                "pool": self.pool, "pool_family": self.pool_family,
                "floor_percent": self.floor_percent}


# ── loading and policy ───────────────────────────────────────────────────────

def denied(text: str, deny: tuple[str, ...] = DENY) -> str | None:
    low = text.lower()
    return next((d for d in deny if d in low), None)


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
        entry = Entry(tui=tui, model=model, effort=effort,
                      floor_percent=float(raw.get("floor_percent", DEFAULT_FLOOR)),
                      pool=raw.get("pool"), pool_family=raw.get("pool_family"),
                      endpoint=raw.get("endpoint"), secret=raw.get("secret"),
                      secret_env=str(raw.get("secret_env") or "OPENAI_API_KEY"),
                      env={str(k): str(v) for k, v in (raw.get("env") or {}).items()},
                      extra_args=[str(a) for a in raw.get("extra_args") or []],
                      timeout=int(raw.get("timeout", 600)), label=str(raw.get("label") or ""))
        if denied(entry.model_arg, deny):
            raise ChainError(f"entry {i}: denied model '{entry.model_arg}'")
        entries.append(entry)
    return entries


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
        if str(BIN) not in sys.path:
            sys.path.insert(0, str(BIN))
        import route_agent
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


def preflight(entry: Entry) -> tuple[bool, str]:
    """(ok, why). Never calls a model."""
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
    if entry.pool:
        row = pool_reading(entry)
        if row is None:
            return False, f"pool {entry.pool}/{entry.pool_family or '-'} not in aiuse --available"
        if not row.get("usable_now"):
            return False, f"pool {entry.pool} not usable now"
        head = row.get("headroom_percent")
        if head is None or float(head) <= entry.floor_percent:
            return False, f"pool {entry.pool} headroom {head}% <= floor {entry.floor_percent}%"
        return True, f"pool {entry.pool} headroom {float(head):.1f}% > floor {entry.floor_percent}%"
    return True, "no quota pool to check"


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


def secret_value(name: str) -> str:
    """Read one secret into memory; never written anywhere."""
    out = subprocess.run([secretspec(), "get", name, "--reason", f"failover: {name} for a chain entry"],
                         capture_output=True, text=True, timeout=60, check=False)
    value = out.stdout.strip()
    if out.returncode != 0 or not value:
        raise AttemptFailed(f"secret {name} did not resolve")
    return value


def acp_command(entry: Entry, prompt_file: Path, cwd: Path) -> list[str]:
    cmd = [acp_run(), entry.tui.acp_agent or entry.tui.name, "-C", str(cwd), "-f", str(prompt_file),
           "--perm", "deny", "--timeout", str(entry.timeout)]
    if entry.tui.takes_model and entry.model_arg:
        cmd += ["--model", entry.model_arg]
    if entry.effort and (entry.tui.effort or "").startswith("set:"):
        cmd += ["--set", f"{entry.tui.effort[4:]}={entry.effort}"]
    return cmd + entry.extra_args


def ask(entry: Entry, prompt: str) -> str:
    """Answer one prompt on this entry in a fresh context; raise AttemptFailed."""
    if entry.tui.kind == "openai_compat":
        return _ask_openai(entry, prompt)
    with tempfile.TemporaryDirectory(prefix="failover-") as tmp:
        work = Path(tmp) / "work"
        work.mkdir()
        pf = Path(tmp) / "prompt.md"
        pf.write_text(prompt)
        pf.chmod(0o600)
        env = {**os.environ, **entry.env}
        try:
            proc = subprocess.run(acp_command(entry, pf, work), capture_output=True, text=True,
                                  stdin=subprocess.DEVNULL, env=env, check=False,
                                  timeout=entry.timeout + 120)
        except subprocess.TimeoutExpired as e:
            raise AttemptFailed(f"{entry.label}: acp-run hung past {entry.timeout + 120}s") from e
    answer = (proc.stdout or "").strip()
    if proc.returncode != 0 or not answer:
        tail = (proc.stderr or "").strip().splitlines()[-1:] or [""]
        raise AttemptFailed(f"{entry.label}: acp-run rc={proc.returncode}"
                            f"{' empty answer' if not answer else ''} {tail[0][:200]}")
    return answer


def _ask_openai(entry: Entry, prompt: str) -> str:
    key = secret_value(entry.secret) if entry.secret else ""
    body = json.dumps({"model": entry.model, "messages": [{"role": "user", "content": prompt}]})
    req = urllib.request.Request(f"{(entry.endpoint or '').rstrip('/')}/chat/completions",
                                 data=body.encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {key}"} if key else {})})
    try:
        with urllib.request.urlopen(req, timeout=entry.timeout) as resp:
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


def run_command(entry: Entry, argv: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess:
    """Run argv with {tui} {agent} {model} {effort} {endpoint} substituted and FAILOVER_* exported."""
    fields = {"tui": entry.tui.name, "agent": entry.tui.acp_agent or "", "model": entry.model_arg,
              "effort": entry.effort, "endpoint": entry.endpoint or ""}
    env = {**os.environ, **entry.env, **{f"FAILOVER_{k.upper()}": v for k, v in fields.items()}}
    if entry.secret:
        env[entry.secret_env] = secret_value(entry.secret)
    cmd = []
    for a in argv:  # literal {name} tokens only; other braces (code, JSON) pass through
        for k, v in fields.items():
            a = a.replace("{" + k + "}", v)
        cmd.append(a)
    return subprocess.run(cmd, env=env, check=False, timeout=timeout)


# ── CLI ──────────────────────────────────────────────────────────────────────

def print_table(rows: list[dict[str, Any]], cols: list[str]) -> None:
    widths = {c: max(len(c), *(len(str(r.get(c) if r.get(c) is not None else "-")) for r in rows))
              for c in cols} if rows else {c: len(c) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    for r in rows:
        print("  ".join(str(r.get(c) if r.get(c) is not None else "-").ljust(widths[c]) for c in cols))


def check_table(entries: list[Entry]) -> list[dict[str, Any]]:
    rows = []
    for i, e in enumerate(entries, 1):
        ok, why = preflight(e)
        rows.append({"#": i, **e.row(), "ready": "yes" if ok else "no", "why": why})
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="failover", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("registry")
    for name in ("check", "ask", "run"):
        sp = sub.add_parser(name)
        sp.add_argument("--chain", required=True, type=Path)
        sp.add_argument("--allow", help="comma-separated tui allowlist")
        sp.add_argument("--log", type=Path, help=f"attempt log (default {ATTEMPT_LOG})")
        if name == "ask":
            g = sp.add_mutually_exclusive_group(required=True)
            g.add_argument("-p", "--prompt")
            g.add_argument("-f", "--file", type=Path)
        if name == "run":
            sp.add_argument("--timeout", type=int)
            sp.add_argument("command", nargs=argparse.REMAINDER)
    a = p.parse_args(argv)
    if a.cmd == "registry":
        print_table([{"tui": t.name, "kind": t.kind, "vendor": t.vendor, "agent": t.acp_agent,
                      "pool": t.pool or ",".join(sorted({x[1] for x in t.pool_by_model})) or None,
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
        rows = check_table(entries)
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
