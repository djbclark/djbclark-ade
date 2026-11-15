### Added

- `ade_claims.py successor-of PRED --record R` and `ade-self-session finish`: a self-handoff successor inherits its predecessor's active claims (same claim id, `history` line), verified against the acknowledged/archived handoff record; a third agent, a forged record or an expired claim is refused. (#0)
