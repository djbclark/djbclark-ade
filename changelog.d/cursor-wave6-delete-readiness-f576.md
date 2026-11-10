### Added

- Documented Wave 6 shim-deletion readiness (`docs/slim/wave6-follow-up.md`) and `bin/wave6-delete-check` (refuses delete until callers, C3 and Mac live-cycle gates pass; queue Carried item 1) (#398).

### Changed

- `wave6-delete-check` also gates executable callers (`bin/deadline` and peers); Mac proof B2 uses `acp-dispatch check` + `paseo ls` (not nonexistent `acp-dispatch ls`) (#398).
