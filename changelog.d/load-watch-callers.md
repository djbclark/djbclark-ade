### Changed

- `skills/fan-out` section 3 and `docs/orchestration-practices.md` rule 4 now tell the launcher what the deleted dispatch shim enforced: `load-watch admit --wait N --max-agents` (N 300-600; exit 75 = launch nothing) before each `paseo run` and wave, a fresh `route_agent.py plan` per slice, `Choice.dispatch` unchanged. (#705)
- `bin/load-watch` docstring, comments and the `admit-log summary` text say that `bg` now calls `admit --wait CHUNK` and gets the starvation valve only after 300 s inside one chunk, not that it polls with `--wait 0`. (#705)

### Removed

- `bin/wave6-delete-check`, `bin/wave6-mac-proof-capture`, their tests and `tests/fixtures/wave6-mac-proofs/`: the Wave 6 shim deletion they gated is done (queue Carried 1a). (#705)
