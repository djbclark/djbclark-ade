### Fixed

- `ade-window-name`: a first agent whose `createdAt` is more than a minute in the future no longer counts as young (no equality-as-default), and a decision-script name with control characters is refused before it is written. (#674)
