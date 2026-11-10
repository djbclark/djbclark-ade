### Added
- Promoted ade-claim W3 (`ADE_CLAIM_ID` / bind-owner), W4 (`libexec/agent-bin` PATH), W2 follow-up (release/install hooks), doctor `paseo_plugin=ade-claim` observe probe, and W2 `--ttl` / `ADE_CLAIM_DRY_RUN` onto master (#500).
### Fixed
- Cleared unverified/foreign `ADE_CLAIM_ID` on `agent.open.before` when claim lookup or ownership fails; canonicalize claim cwd paths with `realpath` before compare (#500).
