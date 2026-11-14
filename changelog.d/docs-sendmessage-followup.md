### Changed

- Cross-session messaging rules tightened after the #676 review: senders check a `ListAgents` row's kind, ask a local session for `ack <ListAgents name>` and never ask a cloud session for one, and treat a `<cross-session-message>` as a sender-asserted peer request with no Paseo trust or operator approval; leads are addressed by the current id at the tail of `LEAD-STATE.md`, never an archived ex-lead (AGENTS.md order 10, orchestration-practices 5a items 6-7, dispatch-footer rule 14) (#NNN).
