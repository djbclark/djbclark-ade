### Added

- Add native Git fork integration API, deny-by-default CLI and synthetic Linux workflow template; mutation remains held pending trusted policy enrollment and App provisioning. (#784)

### Fixed

- Limit fork publication to its candidate ref, retain crash-safe flock ownership, and recheck unattended App authority at each write. (#784)

- Permit clean detached exact-base workspaces when staging integrations, while retaining fatal Git branch lookup failures as holds. (#784)
