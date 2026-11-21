### Added

- Archived-send guard: an agent may un-archive its own archived workers without asking the operator (operator ruling 2026-11-21). A send from the launcher passes when `PASEO_AGENT_ID` or a lead it replaced is the worker's `ade.lead` label (read with `paseo ls -a -g --label`) or its Paseo parent chain; ownership fails closed (no sender, a sender that was replaced, is handing off or is archived, a failed or unverified listing (a canary lead must list nothing), a cyclic ledger, another lead's worker), a handed-off agent is still redirected, never resumed, and any other archived agent stays refused unless the operator sets `ADE_ALLOW_ARCHIVED_SEND`. Every owner resume appends a JSON line (UTC time, sender, target, proof) to `send-guard-overrides.jsonl` (#907)

### Changed

- The refusal text, the shim's second line and the hook's denial say that an own archived worker needs no override. `AGENTS.md`, `docs/archived-send-guard.md`, `docs/orchestration-practices.md`, `docs/queue.md`, `skills/fan-out` and `skills/tidy` carry the ruling and when resuming beats a fresh route (#907)
