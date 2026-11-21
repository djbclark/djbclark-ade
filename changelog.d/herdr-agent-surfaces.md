### Added

- `skills/herdr/SKILL.md`: the official herdr skill, tracked from `herdr --skill` via `bin/herdr-skill-refresh`, with a loosened description so agents infer use from "in tab xyz" / pane / workspace rather than only an explicit Herdr mention.
- `skills/agent-surfaces/SKILL.md`: resolves a named tab/agent across Paseo and herdr together, and routes by harness (paseo send vs herdr pane run).
- `docs/cross-harness-messaging.md` and `bin/xmsg`: the one verified two-way path between a Paseo agent and a local Claude/herdr session (paseo send one way, atomic mailbox the other).
