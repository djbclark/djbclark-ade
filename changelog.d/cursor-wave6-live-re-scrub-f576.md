### Changed

- Scrubbed remaining Wave 6 LIVE_RE live teaching in skills (fan-out, model-routing, session-handoff, old-handoff, oc-go-key, baton, research, loose) and gated bin comment/path literals onto native `paseo run` / `paseo send` / `paseo wait` so `wave6-delete-check --inventory` reports `callers_remaining=0` without deleting the shims or claiming Mac live (#498).

### Fixed
- Documented that native `paseo run` fan-out must re-plan per launch until in-flight quota reservation is native; corrected model-routing D5 (#498).

### Fixed
- Restored fan-out Collect teaching for `bin/completion-notice` / `done: <title>, <PR URL>` after the LIVE_RE scrub (#498).
