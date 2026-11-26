### Added

- `ade-self-session link --predecessor ID --successor ID --operator-attested [--repo REPO] [--reason TEXT]` to record an operator-attested completed succession link for a hand-replaced lead (`handoff-<predecessor>.json`), repointing `supervisor/lead`, legacy `com.djbclark.ade-net-resume.plist`, and the repo-keyed lead record (#1018)
- `bin/ade-lead-of` (`bin/ade_lead_of.py`, linked onto `PATH` by `bin/ade-update`) for repo-keyed lead lookup (`get`, `set`, `list`) backed by `repo-leads/<repo>.json` written by `ade-self-session finish`/`link`/`set` with `verified: false` live non-worker fallback discovery (#1018)

### Changed

- `bin/ade_send_guard.py` now appends recorded live leads or unverified live candidate leads for the target's repository to archived-target refusal reasons as informational hints without ever auto-redirecting (#1018)
