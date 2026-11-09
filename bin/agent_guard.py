"""Per-agent identity guard for launch argv (2026-11-03 omp audit; Wave 6: Pi / native `paseo run` first).

Live ops: `route_agent.Choice.dispatch` → `paseo run --provider pi/<model>` (Pi is the sole general-purpose
third-party TUI, 2026-11-08). Messaging is `paseo send --json`. Admission gates judge the model; a pass-through
that replaces it or credentials after admission made those gates advisory (historical: omp/codex/claude via
acp-run). AGENT_GUARDS drives the transitional shim's `identity_refusal` on `paseo run` argv and the pre-shim
`identity_override` / `record_refusal` helpers kept for tests until ~2026-11-20 Wave 6 delete of acp-run /
acp-dispatch. Flip a row `unreviewed`→`guarded` (fill `gates`/`pool`) to roll out; docs/agent-guard-contract.md.
Pi has no row (native path only). No provider calls.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass

GUARDED, UNREVIEWED = "guarded", "unreviewed"

# Transitional acp-run identity option families (kept until ~2026-11-20 Wave 6 delete): --model replaces the billed
# model; --meta merges into session/new _meta (claude's _meta.claudeCode.options carries model and env); --set sets any
# ACP config option (`model=`, `provider=`); --agent-arg and --agent-env reach the agent process (binary, API key,
# endpoint, config dir, the agent's own --model/--provider/--profile); --auth picks the auth method. Native
# `paseo run` / Choice.dispatch pin identity with `--provider P/M` (or review-launch `--model`) instead; the shim's
# `identity_refusal` checks that argv shape. Operator-side ACP_RUN_ENV_<AGENT> / ACP_RUN_ARGS_<AGENT> /
# ~/.config/acp-run.env are not dispatch inputs and are not covered. acp-run sets allow_abbrev=False, but a prefix
# is refused too.
IDENTITY_OPTIONS = ("--model", "--set", "--meta", "--agent-arg", "--agent-env", "--auth")
# `--set KEY=VALUE` alone passes for the reasoning-effort options: they pick no model, provider or credential.
SET_SAFE_KEYS = frozenset({"reasoning_effort", "effort", "reasoning", "thought", "thought_level", "thinking_level"})


@dataclass(frozen=True)
class AgentGuard:
    status: str                                     # GUARDED (refuse) or UNREVIEWED (today's pass-through)
    identity: tuple[str, ...] = IDENTITY_OPTIONS    # option families refused for this agent
    gates: tuple[str, ...] = ()                     # admission gates that judge the model (documentation)
    pool: str | None = None                         # routing service its slices are admitted on (resolve_service)


_PENDING = AgentGuard(UNREVIEWED)
# Transitional rows for agents still named by tools/acp-run (kept compiling until Wave 6 ~2026-11-20 delete).
# Live Pi launches via Choice.dispatch → `paseo run --provider pi/…` and have no row. `cursor-cloud` uses
# `cursor-cloud launch`. test_agent_guard pins every remaining acp-run AGENTS key still has a row here.
AGENT_GUARDS: dict[str, AgentGuard] = {
    # retired transport under the 2026-11-08 Pi sole-TUI policy; row + acp-run omp guard remain until Wave 6 delete
    "omp": AgentGuard(GUARDED, gates=("kind eligibility", "Claude API credits headroom"), pool="omp"),
    "codex": AgentGuard(GUARDED, gates=("frontier model", "plenty gate", "pool headroom"), pool="codex"),
    "claude": AgentGuard(GUARDED, gates=("frontier model", "fable-xhigh approval", "pool headroom"), pool="claude"),
    **{name: _PENDING for name in ("opencode", "cursor", "hermes")},
}


def policy(agent: str | None) -> AgentGuard:
    """The agent's row; an agent with none is `unreviewed` (including Pi: native `paseo run` only)."""
    return AGENT_GUARDS.get(agent or "", _PENDING)


def identity_override(agent: str, args: list[str] | None, skip_primary_model: bool = False) -> str | None:
    """Why pass-through runner arguments may change this slice's billing identity, else None (also for an `unreviewed` agent).

    Kept for the pre-shim acp-run shape and its tests until Wave 6 delete. Every token is judged (the `--opt=value`
    form, a prefix of an option such as `--mod`, and a token that packs `--model x` into one word). With
    `skip_primary_model` the first `--model VALUE` pair is the dispatcher's own (a stored command line); any further
    form is a replacement. `--set KEY=VALUE` passes for a SET_SAFE_KEYS key. Live ops pin identity with
    `paseo run --provider P/M` (or Choice.dispatch / review-launch `--model`); the shim's `identity_refusal` checks
    that argv."""
    row = policy(agent)
    if row.status != GUARDED:
        return None
    skipped = not skip_primary_model
    items = [str(x) for x in (args or [])]
    i = 0
    while i < len(items):
        tok = items[i]
        if not skipped and tok == "--model":
            skipped = True
            i += 2
            continue
        words = tok.split()
        name = words[0].split("=", 1)[0] if words else ""
        if name != "--mode" and len(name) >= 3 and name.startswith("--") and any(opt.startswith(name) for opt in row.identity):
            if name == "--set" and "--set" in row.identity and len(words) == 1:
                value, used = (tok.split("=", 1)[1], 1) if "=" in tok else (
                    (items[i + 1], 2) if i + 1 < len(items) else ("", 1))
                if "=" in value and value.split("=", 1)[0].strip().lower() in SET_SAFE_KEYS:
                    i += used
                    continue
            return (f"{agent}: pass-through argument {name!r} could replace the admitted billing model or "
                    "credentials; pin the admitted model with paseo run --provider P/M (or Choice.dispatch / "
                    "review-launch --model); the transitional shim accepts no --model/--set/--meta/--agent-arg/"
                    "--agent-env/--auth override (only --set with a reasoning-effort key passes; use --thinking/"
                    "--effort, or an operator-approved direct launch)")
        i += 1
    return None


def record_refusal(rec: dict) -> str | None:
    """Why the stored record's command line may no longer run as admitted, else None.

    Pre-shim helper kept for tests until Wave 6 delete: the stored command (its first `--model` is the
    dispatcher's own and must be the admitted `model`; a guarded agent's command without one would run the
    agent's own default) and `acp_arg` are what executes, whatever route the record took (normal, deferred,
    resumed, legacy). Live Pi / `paseo run` records are not judged here (`agent == "pi"` only keeps the old
    skip_primary_model edge for historical fixtures)."""
    agent = rec.get("agent") or ""
    if policy(agent).status != GUARDED:
        return None
    try:
        argv = shlex.split(rec.get("cmd") or "")
    except ValueError:
        argv = []
    why = identity_override(agent, argv[1:], bool(rec.get("model")) or agent == "pi")
    if not why:
        why = identity_override(agent, rec.get("acp_arg") or [])
    if not why and (rec.get("model") or agent == "pi"):
        at = argv.index("--model") if "--model" in argv else None
        if at is None:
            why = f"{agent}: stored command has no --model (the admitted model must be explicit)"
        elif argv[at + 1:at + 2] != [rec.get("model")]:
            why = f"{agent}: stored command's --model differs from the admitted model"
    return why
