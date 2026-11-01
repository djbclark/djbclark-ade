### Changed

- `tests/test_paseo_bypass_watch.py` (2026-11-01) pins the two adversary round 4 gaps: `Auto`, `DEFAULT` and `autoSomething` seats are never flipped (exact mode match), and an `auto` seat whose set exits 0 but still reads `auto` fails the post-set verify (#216)
