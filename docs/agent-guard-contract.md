# Agent guard contract (2026-11-03)

Agents read untrusted text (briefs, files, tool output, web pages). Anything that changes what a slice bills, or
whose credentials it uses, is a **consent flag**: it is set by the operator or the dispatcher, never by an
argument a model can emit. Since the shim (2026-11-06) the only pass-through is the shim's own `paseo run` launch argv,
which must pin exactly the admitted `--provider P/M`; `acp-dispatch --acp-arg` is retired (exit 2).

## Contract

- **Identity guard (since the shim, 2026-11-06).** `bin/agent_guard.py` holds the per-agent rows (`AGENT_GUARDS`,
  `policy()`); the judging is the shim's own `identity_refusal(agent, argv, model)` (`bin/acp-dispatch:658`), called on
  the built launch argv just before `paseo run` (`:961`, exit 2): the argv must carry exactly one `--provider P/M` (or
  review-launch `--model M`), the admitted model, and no `--env`, `--settings`, `--mcp-config` or `--agent`. The shim
  has no runner, no resumed or legacy records and no `--acp-arg`; its exit 2 is a refused launch, exit 5 an
  unavailable pool before launch.
- **Before the shim (2026-11-03 to 2026-11-06, kept in `agent_guard.py` for its tests until the follow-up PR).** For a
  `guarded` row, the acp-run options `--model`, `--meta`, `--agent-arg`, `--agent-env`, `--auth`, their `=` forms,
  abbreviations and packed tokens were refused in `--acp-arg`, and `--set` passed only for a reasoning-effort key;
  `dispatch()` called `identity_override` before any gate, and the runner's `spawn_refusal` called `record_refusal`
  on every stored record before a spawn.
- **Admission mapping.** A guarded row names the routing `pool` its slices are admitted on; `bin/route_agent.py`'s map
  carries it (the acp-dispatch shim resolves through it), so `--min-headroom`, the in-flight reservation and the record's
  `service` see the pool. Since the shim (2026-11-06) there is no `--acp-arg`: it checks its own launch argv instead
  (exactly one `--provider P/M` or review-launch `--model M`, the admitted model).
  omp (`omp` pool, Claude API credits) is measured when a reading exists and admitted without one, like any
  ordinary pool; only a reserve or a fallback-only pool fails closed, and none is configured since 2026-11-06 (pi,
copilot and the grok CLI retired).
- **Direct `acp-run`.** acp-run keeps its own omp guard (`--model anthropic/<claude model>` for every prompt run,
  `--resume` included; no model/provider/profile/role-model/key flag in `--agent-arg`;
  `ACP_RUN_OMP_ANY_MODEL=1` is the operator-side override). Operator-side `ACP_RUN_ENV_<AGENT>`,
  `ACP_RUN_ARGS_<AGENT>` and `~/.config/acp-run.env` are not dispatch inputs and are not covered.

## Evidence (2026-11-03 audit)

Verified bypasses on master before this change: omp `--model X`, `--model=X`, `--mod X`, packed `'--model X'`,
`--agent-arg=--model --agent-arg=X`, `--agent-env=ANTHROPIC_API_KEY=...`, `--auth`, `--set model=`, `--meta`;
the frontier and fable-xhigh gates passed by dispatching sonnet with `--acp-arg=--model=<fable>`; `codex
gpt-6.1-sol --kind code --dry-run --acp-arg=--model=gpt-6-astra` exited 0 although `gpt-6-astra` direct exits 2; the
replacement survived `resume_record` and `spawn_refusal` returned None. In acp-run, `github-copilot/claude-sonnet-5-5`
passed the substring test, a post-`acp` `--agent-arg=--model` swapped the model, and `--resume abc` skipped the guard.

## Adding an agent

1. Add or flip its row in `AGENT_GUARDS` (`bin/agent_guard.py`): `status=GUARDED`, `gates` (what judges its model), `pool`.
2. Map it in `_AGENT_PROVIDER_MAP` in `bin/route_agent.py`, if it has a pool (the acp-dispatch shim reads that one since 2026-11-06).
3. Grep the callers that dispatch the agent (`acp-dispatch <agent>`, `paseo run --provider <agent>/…`) and confirm none
   relies on a pass-through argument (`--acp-arg` exits 2 since 2026-11-06).
4. Add the agent to the replacement tests in `tests/test_agent_guard.py` (`GUARDED`); the shim's launch-argv check is in
   `tests/test_acp_dispatch.py` (`identity_refusal`).

## Status per Paseo provider

| Agent | Row | Notes |
|---|---|---|
| pi | retired | row removed 2026-11-06 (pi left acp-run) |
| omp | guarded | `omp` pool; acp-run's own model guard too |
| codex | guarded | frontier, plenty and pool gates judge `--model` |
| claude | guarded | frontier and fable-xhigh gates judge `--model` |
| opencode, cursor, hermes | unreviewed | today's pass-through; flip when reviewed |
| antigravity | unreviewed | shim provider since 2026-11-06, no `AGENT_GUARDS` row |
| cursor-cloud | n/a | no acp-run |
