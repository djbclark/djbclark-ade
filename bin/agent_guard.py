"""Per-agent guard policy for pass-through acp-run arguments (2026-11-03 omp audit); no provider calls.

acp-dispatch admits a slice on `--model`: the frontier, fable-xhigh, plenty, fallback and pool gates all judge it. An
`--acp-arg` that replaces the model, or the agent's credentials, after admission made those gates advisory (omp, codex
and claude ran past them). ONE function judges the arguments for `dispatch()` (the fresh dispatch and a resume's
inherited `acp_arg`) and for the runner's `spawn_refusal` (the stored command line and `acp_arg` of a normal, deferred,
resumed or legacy record), driven by the AGENT_GUARDS table. Rolling the guard out to another TUI is flipping its row
from `unreviewed` to `guarded` (and filling `gates`/`pool`); docs/agent-guard-contract.md has the checklist.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass

GUARDED, UNREVIEWED = "guarded", "unreviewed"

# acp-run options that can change which model/provider/credentials a slice really uses: --model replaces the billed
# model; --meta merges into session/new _meta (claude's _meta.claudeCode.options carries model and env); --set sets any
# ACP config option (`model=`, `provider=`); --agent-arg and --agent-env reach the agent process (binary, API key,
# endpoint, config dir, the agent's own --model/--provider/--profile); --auth picks the auth method. The rest of
# acp-run's options (-C, --add-dir, -p/-f, --perm, --keep/--strip-user-config, --tripwire-exempt-kinds, --mode,
# --effort, --context, --timeout, --wrapup*, --verify*, --log, --session-id, --resume, load/handshake/retry knobs)
# touch neither. Operator-side ACP_RUN_ENV_<AGENT> / ACP_RUN_ARGS_<AGENT> / ~/.config/acp-run.env are not dispatch
# inputs and are not covered. acp-run sets allow_abbrev=False, but a prefix is refused too.
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
# One row per acp-run agent (test_agent_guard pins that none is missing). `cursor-cloud` never reaches acp-run.
AGENT_GUARDS: dict[str, AgentGuard] = {
    "omp": AgentGuard(GUARDED, gates=("kind eligibility", "Claude API credits headroom"), pool="omp"),
    "codex": AgentGuard(GUARDED, gates=("frontier model", "plenty gate", "pool headroom"), pool="codex"),
    "claude": AgentGuard(GUARDED, gates=("frontier model", "fable-xhigh approval", "pool headroom"), pool="claude"),
    **{name: _PENDING for name in ("opencode", "cursor", "hermes", "grok")},
}


def policy(agent: str | None) -> AgentGuard:
    """The agent's row; an agent with none is `unreviewed`."""
    return AGENT_GUARDS.get(agent or "", _PENDING)


def identity_override(agent: str, args: list[str] | None, skip_primary_model: bool = False) -> str | None:
    """Why pass-through acp-run arguments may change this slice's billing identity, else None (also for an `unreviewed` agent).

    Every token is judged (the `--opt=value` form, a prefix of an option such as `--mod`, and a token that packs
    `--model x` into one word). With `skip_primary_model` the first `--model VALUE` pair is the dispatcher's own
    (a stored command line); any further form is a replacement. `--set KEY=VALUE` passes for a SET_SAFE_KEYS key."""
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
                    "credentials; acp-dispatch accepts no --model/--set/--meta/--agent-arg/--agent-env/--auth "
                    "override through --acp-arg (only --set with a reasoning-effort key passes; use --effort/"
                    "--context, or acp-run directly with the operator's approval)")
        i += 1
    return None


def record_refusal(rec: dict) -> str | None:
    """Why the stored record's command line may no longer run as admitted, else None: the stored command (its first
    `--model` is the dispatcher's own and must be the admitted `model`; a guarded agent's command without one would run
    the agent's own default) and `acp_arg` are what executes, whatever route the record took (normal, deferred, resumed,
    legacy)."""
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
