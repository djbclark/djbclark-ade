### Added

- `ade-self-session handoff` takes an optional `--predecessor`: a supervisor can re-hand a stuck agent that is not itself, instead of only the calling agent. The caller is recorded as `requested_by` and `cross_agent` is set, so the handoff is auditable. A self-handoff is unchanged. Proven against the fake Paseo only; it does not run against a live agent (Carried 103).
