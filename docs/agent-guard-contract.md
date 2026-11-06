# Agent guard contract (2026-11-03)

Agents read untrusted text (briefs, files, tool output, web pages). Anything that changes what a slice bills, or
whose credentials it uses, is a **consent flag**: it is set by the operator or the dispatcher, never by an
argument a model can emit. `acp-dispatch --acp-arg` is a pass-through, so it must not carry one.

## Contract

- **Identity guard.** `bin/agent_guard.py` is the one place that judges pass-through arguments. For an agent whose row
  is `guarded`, `--model`, `--meta`, `--agent-arg`, `--agent-env`, `--auth`, their `=` forms, abbreviations and packed
  tokens are refused, and `--set` passes only for a reasoning-effort key. `dispatch()` calls
  `identity_override` before any gate or probe (a resume's inherited `acp_arg` included, exit 2); the runner's
  `spawn_refusal` calls `record_refusal` on the stored `cmd` and `acp_arg` before every spawn (normal, deferred,
  resumed and legacy records, exit 5): a second `--model`, any identity option, or a stored `--model` that is not
  the admitted one refuses.
- **Admission mapping.** A guarded row names the routing `pool` its slices are admitted on; `AGENT_PROVIDER_MAP` in
  `bin/acp-dispatch` and `bin/route_agent.py` carry the same mapping (a test ties `pool` to `resolve_service`), so
  `--min-headroom`, the in-flight reservation, the record's `service` and `reroute`/`--escalate` see the pool.
  omp (`omp` pool, Claude API credits) is measured when a reading exists and admitted without one, like any
  ordinary pool; only a reserve or a fallback-only pool, and Pi (measured-only), fail closed.
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
2. Map it in `AGENT_PROVIDER_MAP` in both `bin/acp-dispatch` and `bin/route_agent.py`, if it has a pool.
3. Grep the callers and docs that pass `--acp-arg` for the agent (`skills/session-finder/launch.py`, which passed `--set`,
   was deleted 2026-11-06) and keep the non-identity ones working.
4. Add the agent to the replacement tests in `tests/test_acp_dispatch_identity.py` (`GUARDED`).

## Status per TUI

| Agent | Row | Notes |
|---|---|---|
| pi | retired | row removed 2026-11-06 (pi left acp-run) |
| omp | guarded | `omp` pool; acp-run's own model guard too |
| codex | guarded | frontier, plenty and pool gates judge `--model` |
| claude | guarded | frontier and fable-xhigh gates judge `--model` |
| opencode, cursor, hermes, grok | unreviewed | today's pass-through; flip when reviewed |
| cursor-cloud | n/a | no acp-run |
