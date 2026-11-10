### Added

- `ade-merge-ready retrigger-marker` re-runs `adversary-marker.yml` for selected open tips (`--prs`, `--bottoms-only`, and/or `--class needs_approve`; dry-run by default, `--yes` to fire); never invents APPROVE and never merges (batch re-dispatch after owner-trust #484) (#493).
