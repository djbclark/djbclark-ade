### Fixed

- Git guard: a caller whose `PASEO_AGENT_ID` is a Paseo agent id equal to a claim's `owner.agent` now owns that claim (any TUI, also after a resume), so a lead that pre-creates a claim for a worker and runs `bind-owner --owner-agent <worker id>` no longer leaves the worker refused; `bind-owner` also defaults `owner.record` to a Paseo agent id like `new` does. A refusal that names the caller itself as an owner says so and no longer tells it to message itself (#PR)

### Changed

- `ade_claims.py new`: `--ownerless` with any owner flag is exit 2, a note on stderr names the new id to export when a same-owner re-claim retired the caller's `ADE_CLAIM_ID`, and the `--branch` help matches the `symbolic-ref` code. `docs/git-guard.md` and `skills/fan-out` document the caller identity, the pre-created claim flow and the trust level (#PR)
