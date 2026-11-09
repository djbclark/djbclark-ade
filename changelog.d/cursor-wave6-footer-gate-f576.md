### Changed

- `claude/hooks/agent_footer_gate.py` fills `docs/dispatch-footer.md` inline (env
  `AGENT_FOOTER_FILE` / `AGENT_FOOTER_LEAD` / `AGENT_FOOTER_REPORT_DIR` /
  `AGENT_FOOTER_GATE_OFF`) instead of shelling out to `acp-dispatch footer`, so
  the hook survives Wave 6's shim deletion (#344).
