### Security
- Closed the `--acp-arg` identity bypass for the guarded agents `pi`, `omp`, `codex` and `claude`: `acp-dispatch` refuses `--model`, `--meta`, `--agent-arg`, `--agent-env`, `--auth`, their `=` forms, abbreviations and packed tokens (and `--set` unless its key is a reasoning-effort option) before any gate or probe, and the runner refuses a stored command or `acp_arg` carrying one or a `--model` other than the admitted one, for normal, deferred, resumed and legacy records; the frontier and fable-xhigh gates and the codex dry run can no longer be bypassed by a replacement model. One policy table, `bin/agent_guard.py`, serves both; every other agent is an explicit `unreviewed` row (`docs/agent-guard-contract.md`) (#275).
- `acp-run omp` requires the `anthropic/` provider prefix (`github-copilot/claude-...` no longer passes), no longer exempts `--resume`, and refuses model, provider, profile, role-model, key and config flags in `--agent-arg` (`ACP_RUN_OMP_ANY_MODEL=1` stays the operator override) (#275).

### Fixed
- `acp-dispatch` maps `omp` to its own pool in both maps (`bin/acp-dispatch`, `bin/route_agent.py`): the record carries `service: omp`, `--min-headroom` is checked, a resumed or legacy omp record is rechecked against its minimum in the runner, and `reroute`/`--escalate` exclude the pool; no fresh omp reading still admits, like any ordinary pool (#275).
- The fleet scan no longer classifies the npm-installed OMP (`@oh-my-pi/pi-coding-agent/dist/cli.js`) as a Pi seat; Pi's `cli.js` rule requires the `@earendil-works` scope (#275).

### Changed
- `--acp-arg=--meta` is no longer the documented example of a dash-leading value (it is refused for guarded agents); the docs use `--acp-arg=--tripwire-exempt-kinds` (#275).
