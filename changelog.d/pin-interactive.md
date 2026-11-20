### Added

- `bin/ade-pin-interactive` tags non-worker (human-interaction) agents `ade.interactive=1` so `paseo ls --label ade.interactive=1` finds them; Paseo's native sidebar pin (`pinnedAt`) is UI-only (no CLI/SDK method), so the label is the machine-writable signal until upstream exposes a pin command. (#839)
