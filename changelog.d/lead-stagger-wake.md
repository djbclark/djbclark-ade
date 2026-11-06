### Changed

- `/helm lead` (`skills/helm/lead.md` section 2 item 0, 2026-11-06): a lead now wakes agents in batches of at most 4 and waits for `load-watch admit` between batches; a one-burst "continue" to about 25 agents had driven load1 to 360 and frozen herdr. (#PR)
