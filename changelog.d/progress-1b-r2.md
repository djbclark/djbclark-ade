### Changed

- Set `chosen = true` on the `ade-progress` row in `config/install.toml` (operator choice, 2026-11-13), so `just doctor` expects `com.djbclark.ade-progress` and reports it `missing` until the lead installs it (`docs/scheduling.md`). Merging installs and loads nothing. (#PR)
- Changed `ade-sched reconcile` for an unchosen inventory row: a live label of the row is reported as `installed but inventory row ... is not chosen` instead of `foreign`, and a ledger-owned install of it is planned for removal with the reason `inventory row ... is not chosen` instead of `dropped from inventory`; `ade-sched diff` adds "installed but unchosen" when the label is live. Behaviour (report only, or unload when ledger-owned) is unchanged. (#PR)

### Added

- Documented in `docs/scheduling.md` that un-choosing a ledger-owned job makes the next `reconcile --yes` unload it, and added `plan_reconcile` tests for the `ade-progress` row (unchosen skip, installed-unchosen report, ledger-owned unchosen removal, chosen install). (#PR)
