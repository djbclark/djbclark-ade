### Added

- `bin/ade-self-session handoff`: added a quota-floor guard that checks the predecessor pool's headroom against router floors before cloning the predecessor's provider/model, auto-routing scarce pools via `route_agent.py plan` (recording `quota_reroute`) or refusing cleanly with `--provider` / `--allow-scarce-pool` guidance when no eligible unattended alternative is available (#959).
- `bin/ade-net-resume`: added `--lead-file PATH` (mutually exclusive with `--lead`) to re-read a bounded regular lead UUID file on each scan tick while still following `ade_lead_succession` chains (#959).
- `bin/ade-self-session finish`: added automatic non-fatal syncing (`net_resume_plist`) of legacy `--lead <predecessor>` `com.djbclark.ade-net-resume.plist` installs to the successor with macOS `launchctl` reload, leaving `--lead-file` plists and other chains untouched (#959).

### Fixed

- `bin/ade_self_session.py`: folded four carried PR #955 review LOWs — treating `n/a`/`na`/`tbd`/`unknown` as frontmatter nulls, resolving `Path(__file__)` before `.with_name('ade-worker-run')`, skipping blank lines in `checkpoint_frontmatter_repo()` continuation checks, and guarding `.resolve()` / catching `Exception` in `advise_lead_window()` (#959).
