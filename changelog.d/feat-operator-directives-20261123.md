### Added

- `bin/ade-unstick-ask` and `tests/test_ade_unstick_ask.py`: fail-closed detector and `"2 then 1"` recovery CLI (dry-run by default; `--apply` tries `paseo send --behavior steer` first and falls back to `paseo agent stop` only after re-verifying the turn is still hung on the same `ask_question`) for Antigravity sessions stuck in `ask_question` on Paseo builds lacking ACP `elicitationForms` (#961)

### Changed

- `skills/steps/SKILL.md` rule 3a and `docs/orchestration-practices.md`: recorded that Paseo fork build 2+ (`v0.17.3` with ACP `elicitationForms`) supports native Antigravity `ask_question` live, corrected build 1's indefinite `Status=running` hang failure mode, and documented `bin/ade-unstick-ask` (`"2 then 1"` recovery) (#961)
- `skills/research/SKILL.md`, `docs/mcp-servers.md`, and `docs/orchestration-practices.md`: recorded the 2026-11-23 operator directive that research failures accessing institutional paper sites (e.g. MIT Libraries / scholarly publishers via Hyades Firecrawl or the MITnet bridge) must be treated as bugs, surfaced explicitly, and offered for coordinated fixing (#961)
- `AGENTS.md` Standing Order 5, `docs/ref-labels.md`, `docs/agent-identity.md`, and `docs/orchestration-practices.md`: recorded the 2026-11-23 operator ruling that every reference to a Paseo agent or tab in replies or reports must include full agent ID, workspace ID, window name, and tab name rather than bare short IDs (#961)
