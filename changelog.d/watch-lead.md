### Added

- `/helm lead` and its alias `/watch lead` (2026-11-02): helm's lead mode (`skills/helm/lead.md`) surveys every running Paseo and herdr agent at no model cost, sends each a brief asking what it needs to continue or to be safe to quit, answers what rules and probes settle, batches the operator's decisions into one picklist prompt, relays each pick back, and stops nothing in flight; agents ask the lead through `relay.py` instead of raising cards. (#PR)
