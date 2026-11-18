### Added

- `bin/ade-pi-stuck` (read-only) lists every live Pi agent, maps it to its billing account and flags the ones on a
  quota-exhausted account, printing a comparable healthy alternative model under another account for the re-handoff.
  A stale or absent quota reading never clears an account the operator has confirmed empty; only a fresh positive
  balance does. `skills/watch/SKILL.md` section 5 is the `/watch stuck` mode that runs it (the re-handoff — archive,
  relaunch, tell it to continue — stays a separate gated action). (#785)
- `bin/ade-supervisor-scan` + `config/launchd/com.djbclark.ade-supervisor-scan.plist` (every 300 s, `ade-job-run`
  wrapped, inventoried in `config/ade.toml [install.jobs]`, install command in `docs/scheduling.md`): the scan notices
  the lead named in `ADE_SUPERVISOR_LEAD` or in `~/.local/state/djbclark-ade/supervisor/lead` (a file, so no agent id
  sits in the plist or the inventory and a handoff rewrites one line) and stays quiet while that agent stays stuck, its
  dedupe set in `~/.local/state/djbclark-ade/supervisor/notified`. A scan that breaks or cannot read quota alerts the
  lead once rather than going quietly blind, never messages an archived lead (a delivery would un-archive it) and
  reports that to the operator once through `hermes-ping`. (#785)
