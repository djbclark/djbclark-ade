### Changed

- `claude/hooks/agent_footer_gate.py` fills `docs/dispatch-footer.md` inline (env
  `AGENT_FOOTER_FILE` / `AGENT_FOOTER_LEAD` / `AGENT_FOOTER_REPORT_DIR` /
  `AGENT_FOOTER_GATE_OFF`) instead of shelling out to `acp-dispatch footer`, so
  the hook survives Wave 6's shim deletion (#344).

### Fixed

- Restored `acp-dispatch check_report_name` parity in the inline footer fill: basenames
  Claude Code refuses to Write (`report`/`summary`/`findings`/`analysis`*.md) deny the
  launch instead of injecting an undeliverable contract (#344).
