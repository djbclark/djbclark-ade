### Added

- `/helm lead` and its alias `/watch lead` (2026-11-02): added helm's lead mode (`skills/helm/lead.md`). A lead session surveyed every running Paseo and herdr agent without spending their turns, briefed each one on what it needed to continue or to be safe to quit, answered only what written rules and probes settled, batched the operator's decisions into one picklist prompt, relayed each pick back, and stopped nothing in flight; agents asked the lead through `relay.py` instead of raising cards. (#258)
