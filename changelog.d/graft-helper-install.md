### Fixed

- `bin/ade-update` now detects drift in `~/.claude/helpers/graft-hooks.cjs` and installs an atomic, backed-up executable copy from the canonical checkout (step 3a), so a merged hook change can no longer age out silently; other checkouts stay report-only. (#826)
