### Fixed

- `bin/ade_self_session.py`: `parse_envelope` keeps a native error code that matches `[A-Za-z0-9_.:-]{1,64}` (full match), so `host_offline` and `commander.excessArguments` are no longer recorded as `INVALID_CODE`; spaces, control characters, newlines and codes over 64 characters still are, as is a code the message scrub would redact: a bare token (`ghp_...`, `sk-...`), a `keyword:value` or `cookie:value` secret (`password:hunter2`) or a run of 16 or more letters and digits holding a digit. (#740)
