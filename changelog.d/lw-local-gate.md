### Changed

- `load-watch ci decide DIR local "why"` now needs djbclark's fresh approval, the same `sudo-ask -k` Allow dialog and Touch ID as `bg approve-local`: a `local` decision (new, or replacing `ci`/`pending`) is refused with nothing written when it is denied, cancelled or cannot be shown (no GUI session, `sudo-ask` missing). `ci` and `pending` decisions, reads and an existing `local` row stay ungated; each outcome is logged in `~/.local/state/bg/approvals.log`. (#744)
