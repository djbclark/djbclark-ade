### Added

- `bin/ref` and `bin/ref-append`: script-issued `Ref: <BOT>-<id>` lines from one global base-36 counter (`~/.local/state/djbclark-ade/refs/`, flock-locked, append-only `issued.log`). `docs/ref-labels.md` records the standing reply-label convention (Roman sections, bold-italic items, script-issued Ref on every operator post) and the per-bot prefix table. `ref_audit.py` is not yet wired to a Mac transcript store. (#775)
