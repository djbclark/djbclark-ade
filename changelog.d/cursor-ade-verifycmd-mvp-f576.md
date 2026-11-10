### Added

- Added `bin/verifycmd`, the ADE-native verify-until-pass MVP (register argv, status/clear/rearm,
  run-once / run-until-pass under `deadline` + optional `bg`, handoff re-key/clear stub;
  exits 0/1/2/4/75/124 per `docs/ade-verifycmd.md`). (#464)

### Fixed

- `bin/verifycmd` refused `register` / `run-once` on a shared/primary checkout or foreign /
  expired claim via `ade_claims` ownership helpers (exit 2; order 9). (#464)
- `bin/verifycmd` deadline names kept a sha256 id component and the attempt suffix within the
  100-char limit so sanitize collisions (`agent:a` vs `agent@a`) no longer share a live name. (#464)
