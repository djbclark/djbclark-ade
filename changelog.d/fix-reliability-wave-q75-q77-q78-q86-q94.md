### Fixed

- `bin/codex-env-policy-apply`: print the `[shell_environment_policy.set]` key NAMES added, removed, or changed (never values) when `--allow-set-keys` permits explicit-set changes (Carried 86, #853) (#1023)
- `tests/test_ade_tidy_prune.py`: moved synthetic fake PIDs strictly above Linux `PID_MAX_LIMIT` (`4,194,304`) so `os.getpid()` on Linux CI can never collide with `SUP`/`DAEMON` and cause `own_tree()` to skip `PROV` (Carried 94) (#1023)
- `docs/queue.md`: closed Carried 94 and 86 alongside verified-already-landed Carried 75 (#789), 77 (#801), and 78 (#802) (#1023)
