#!/usr/bin/env python3
"""PreToolUse (Agent): log and ask before an Agent-tool sub-agent runs on a frontier model.

Operator 2026-10-18: Fable is scarce. acp-dispatch gates it, but an Agent-tool sub-agent never
passes through acp-dispatch: `fable-deep` and `model: fable` reached it unseen (the opencodex
`ocx-*` sub-agents that also did were retired with the proxy on 2026-10-19). Each such call is appended to ~/.local/state/frontier-gate/agent-calls.jsonl and returns
"ask", so the operator confirms it. Skipped when ACP_OPERATOR_APPROVED names `frontier-agent` or `fable-deep` (any
frontier sub-agent this session) or FRONTIER_GATE_OFF=1. Fails open on any error before the call is known to be a frontier
call; after that an error asks (an approved session still passes), never allows.

Away allowance (2026-10-27, docs/gates.md "Frontier allowance"; config/gates.toml [frontier], only a gate profile raises it).
In order, a call is allowed without asking only when ALL hold; the first failure asks and the ask text names it:
  1. the effective gate has frontier1_judged >= 1 and frontier1_agent_calls_per_day >= 1 (baseline: 0, always ask);
  2. quota-guard.json is fresh (30 min), level ok, or watch only for the weekly window, not stale, and the frontier-1 cap
     (`fable_left`) is at least frontier1_min_left;
  3. the sub-agent prompt has a line `frontier-reason: TEXT`, TEXT one line of 10-200 characters;
  4. fewer than frontier1_agent_calls_per_day calls were allowed today (America/New_York) per the log AND the day counter
     file (agent-calls-day.json): the larger counts, so truncating one file does not reset the cap. A log that is not a
     regular file, has an unparsable row or a row dated in the future asks.
An allowed call is logged with `decision: "allowed-judged"`, the reason, the profile name and its `until`. Any error in these
steps, or in the state directory, the lock (polled for 5 s, then asks) or the log append, asks; it never allows. The decision and
the append run under one lock, so parallel calls cannot both take the last slot.
"""

import fcntl
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

FRONTIER_AGENTS = {"fable-deep": "Fable"}
STATE_DIR = Path.home() / ".local/state/frontier-gate"
LOG = STATE_DIR / "agent-calls.jsonl"
DAY_COUNTER = STATE_DIR / "agent-calls-day.json"
LOCK = STATE_DIR / "agent-calls.lock"
LOCK_WAIT = 5.0   # s to poll for the state lock before asking
REASON_LINE = re.compile(r"^[ \t]*frontier-reason:[ \t]*(.*?)[ \t]*$", re.MULTILINE)
APPROVAL_KEYWORDS = {"frontier-agent", "fable-deep"}   # `fable-deep` accepted until the tiers migration drops it (design C6)


def _gates():
    """ade_gates from this checkout's bin/ (the hook is a symlink or copy of claude/hooks/ in the repo)."""
    for cand in (Path(__file__).resolve().parents[2] / "bin", Path.home() / "src/djbclark-ade/bin"):
        if (cand / "ade_gates.py").is_file():
            sys.path.insert(0, str(cand))
            import ade_gates
            return ade_gates
    raise ImportError("ade_gates.py not found")


def _guard_state():
    path = Path(os.environ.get("CLAUDE_QUOTA_GUARD_STATE") or Path.home() / ".local/state/ade/quota-guard.json")
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _count_today(g, now):
    """Allowed-judged calls today per the log and the day counter; raises ValueError on any sign of tampering."""
    today = g.ny_date(now)
    logged = 0
    if LOG.is_symlink() or (LOG.exists() and not LOG.is_file()):
        raise ValueError("agent-calls.jsonl is not a regular file")
    if LOG.exists():
        for line in LOG.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            at = row["at"]
            if not isinstance(at, (int, float)) or isinstance(at, bool) or at > now.timestamp() + 60:
                raise ValueError("agent-calls.jsonl has a row without a usable past time")
            if row.get("decision") == "allowed-judged" and g.ny_date(datetime.fromtimestamp(at, UTC)) == today:
                logged += 1
    counted = 0
    if DAY_COUNTER.is_symlink() or (DAY_COUNTER.exists() and not DAY_COUNTER.is_file()):
        raise ValueError("agent-calls-day.json is not a regular file")
    if DAY_COUNTER.exists():
        day = json.loads(DAY_COUNTER.read_text())
        if day.get("day") == today:
            n = day.get("n")
            if type(n) is not int or n < 0:
                raise ValueError("agent-calls-day.json has an unusable count")
            counted = n
    return max(logged, counted), today


def _judged(g, tool_input, now, ctx):
    """(allowed, why, extra): the away allowance for this call; the caller holds the lock. Never allows on an error.
    Sets ctx["live"] once the gate has an allowance to explain (past step 1), so a baseline ask never mentions it."""
    t, info = g.load_frontier(now)
    if t["frontier1_judged"] < 1 or t["frontier1_agent_calls_per_day"] < 1:
        return False, None, {}      # baseline: no allowance to explain
    ctx["live"] = True
    prof = info.get("profile") or {}
    extra = {"profile": prof.get("name"), "profile_until": prof.get("until")}
    why = g.judged_guard_block(_guard_state(), t, now)
    if why:
        return False, why, extra
    prompt = tool_input.get("prompt")
    m = REASON_LINE.search(prompt) if isinstance(prompt, str) else None
    reason, problem = g.frontier_reason(m.group(1) if m else None)
    if reason is None:
        return False, problem or "the prompt has no `frontier-reason: TEXT` line", extra
    used, today = _count_today(g, now)
    cap = int(t["frontier1_agent_calls_per_day"])
    if used >= cap:
        return False, f"{used} of {cap} away Agent-tool frontier calls are already used today", extra
    return True, None, {**extra, "frontier_reason": reason, "day": today, "n_today": used + 1}


def _write_counter(today, n):
    tmp = DAY_COUNTER.with_name(f".{DAY_COUNTER.name}.{os.getpid()}")
    tmp.write_text(json.dumps({"day": today, "n": n}))
    os.replace(tmp, DAY_COUNTER)


def _take_lock():
    """The state lock, polled without blocking for LOCK_WAIT seconds; raises TimeoutError when another process keeps it."""
    fd = os.open(LOCK, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    deadline = time.monotonic() + LOCK_WAIT
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{LOCK.name} is held by another process") from None
            time.sleep(0.05)


def _ask(agent, model, what, note):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "ask",
        "permissionDecisionReason": (
            f"Frontier sub-agent: {agent or 'model ' + model} runs on {what}, which is scarce (operator "
            "2026-10-18). Approve only if this really needs it; ordinary judgment is Opus at high first "
            "(model: opus; omp Opus next, and codex gpt-6.1-sol at high through acp-dispatch while "
            "its quota is plentiful, 2026-10-25), everyday work goes through acp-dispatch." + note)}}))


try:
    data = json.load(sys.stdin)
    if data.get("tool_name") not in ("Agent", "Task") or os.environ.get("FRONTIER_GATE_OFF"):
        sys.exit(0)
    tool_input = data.get("tool_input") or {}
    agent = str(tool_input.get("subagent_type") or "")
    model = str(tool_input.get("model") or "")
    what = FRONTIER_AGENTS.get(agent) or ("Fable" if "fable" in model.lower() else "")
    if not what:
        sys.exit(0)
    approved = bool(APPROVAL_KEYWORDS & {x.strip() for x in os.environ.get("ACP_OPERATOR_APPROVED", "").split(",")})
except Exception:  # noqa: BLE001 - before the call is classified a gate must never break the tool
    sys.exit(0)

# From here the call is a frontier call: any error asks (approved sessions still pass), it never allows.
ctx: dict = {}
try:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    row = {"at": time.time(), "session": data.get("session_id"), "cwd": data.get("cwd"),
           "subagent_type": agent, "model": model, "frontier": what,
           "description": tool_input.get("description"), "approved_env": approved}
    lock_fd = _take_lock()
    allowed, why = False, None
    if not approved:
        try:
            allowed, why, extra = _judged(_gates(), tool_input, datetime.now(UTC), ctx)
            row.update(extra)
        except Exception as e:  # noqa: BLE001 - an error inside the allowance asks, never allows
            allowed, why = False, f"the allowance check failed ({type(e).__name__}: {str(e)[:120]})"
    row["decision"] = "allowed-approved" if approved else "allowed-judged" if allowed else "asked"
    if why:
        row["ask_reason"] = why
    with LOG.open("a") as fh:
        fh.write(json.dumps(row) + "\n")
    if allowed:
        _write_counter(row["day"], row["n_today"])
except Exception as e:  # noqa: BLE001 - the gate's own state is unusable: ask, never allow
    if approved:
        sys.exit(0)
    _ask(agent, model, what, f" The gate could not use its own state ({type(e).__name__}: {str(e)[:120]}), so it asks.")
    sys.exit(0)
if approved or allowed:
    sys.exit(0)
_ask(agent, model, what, (
    f" The away allowance (config/gates.toml [frontier], while a gate profile allows it) was not applied: {why}. To use it "
    "add a line `frontier-reason: TEXT` (one line, 10-200 characters, why this is significantly better than Opus 5.5) "
    "to the sub-agent prompt.") if why and ctx.get("live") else "")
