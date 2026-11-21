### Fixed

- `macos/gui-hog/UI.swift`: the window title now reflects the hold state on every refresh, matching the body. It was set once at launch to "A build is waiting" and never updated, so after the last hold cleared the title still said a build was waiting while the body said "No build is waiting now." (operator 2026-11-21).
