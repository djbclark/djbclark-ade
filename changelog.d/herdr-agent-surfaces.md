### Added

- `skills/agent-surfaces/SKILL.md`: resolves a named tab/agent across Paseo and herdr together and routes by harness: `paseo send` to a Paseo agent; to a terminal agent SendMessage or an atomic reply file, never keystrokes into its pane. The herdr skill itself moved to #855. (#847)
- `docs/cross-harness-messaging.md` and `bin/xmsg`: the verified two-way path between a Paseo agent and a local Claude/herdr session (paseo send one way, atomic reply file the other). A sender outside Paseo must offer two reply routes (SendMessage and a reply file); an ack file is written only by its receiver, the sender's own `queued` status goes to `PATH.status`; `to-paseo` exits 0 delivered, 5 accepted, 1 failed. (#847)
