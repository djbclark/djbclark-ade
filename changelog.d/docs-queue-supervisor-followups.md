### Added

- Carried 80 and 79 in `docs/queue.md`: map the aiuse clinepass sub-accounts in `bin/ade-pi-stuck` so a
  `clinepass-t-e/<model>` agent is judged instead of reported as unmapped, and write `bin/ade-supervisor-scan`'s
  `.redirect-noted` marker when a handoff is first resolved so a replaced lead does not log the hop every 300 s on quiet
  runs. Both were found by the merged supervisor work and its review. (#799)
