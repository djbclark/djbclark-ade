### Added

- Added canonical whole-session `skills/self-handoff/SKILL.md` (`/self-handoff`), consolidating the ADE acknowledged self-handoff protocol (`bin/ade-self-session`, Tier 1/Tier 2 recovery records, quota-floor guard, WORKER/OTHER box reuse, `supervisor/lead` and `ade-net-resume` tracking, and opt-in NATS coordination) (#PR).

### Changed

- Retired `skills/old-handoff-use-paseo-handoff/` and `skills/old-hand-use-paseo-handoff/`, added automatic retired-symlink and Grok Bot managed-copy cleanup (including `~/.gemini/skills`) to `bin/skill-everywhere`, repointed `skills/handoff/SKILL.md` and `skills/hand/SKILL.md` as thin portable deprecation aliases to `/paseo-handoff`, and updated `skills/loose/SKILL.md`, `AGENTS.md`, `README.md`, and active docs/tests to reference `/self-handoff` (#PR).
