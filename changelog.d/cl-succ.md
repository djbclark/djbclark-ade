### Added

- `ade_claims.py successor-of PRED --record R` and `ade-self-session finish`: a self-handoff successor inherits its predecessor's active claims (same claim id, `history` line), verified against the archived handoff record; a caller the record does not name, an unarchived or unreadable record, or an expired claim is refused. (#757)
