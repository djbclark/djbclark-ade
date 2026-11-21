### Fixed

- Follow-up to the load-gate-50 change: the `admit` test helper and `load_module()` now scrub `LW_ADMIT_PER_CORE` and `LW_LOAD_PER_CORE` from the host environment (a host that exports one no longer fails the default-limit tests), a churn test is renamed and gains a corroborated-churn refusal case, and stale wording in `bin/load-watch` and `docs/gui-hog-dialog.md` now names site-public-djbclark `f536056` as bgrun's 5.0 base and 5.0 as the steer line. (#868)
