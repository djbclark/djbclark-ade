### Added

- `bin/pr-wait`, `bin/load-watch admit --wait S` and `bin/acp-dispatch-wait` (2026-11-02) register their own deadline by default, as
  `pr-wait-<repo>-<PR>-<pid>`, `admit-wait-<pid>` and `dispatch-wait-<record>-<pid>`: owner `$PASEO_AGENT_ID` (none: the sweep pings Hermes), budget
  min(own timeout, class budget: 60 min, admission 30 min, dispatch slice 2 h) + 60 s, a heartbeat from the poll loop, `done` on every exit. Past it the
  enforcer kills the waiter's own process group only (exit 124; `admit` answers its 75 "still too hot" because callers fail open on an unknown exit; `acp-dispatch-wait` exits 76, never the
  slice-timeout 124, so a lead re-arms instead of re-tasking a running slice;
  a waiter holds no work). `--no-deadline` opts out; a waiter under
  `deadline run` (`DEADLINE_NAME` set) does not register twice; a missing or failing deadline tool is one stderr warning and the wait
  goes on. Shared code in `bin/deadline_wait.py`; `docs/deadline.md` "Waiters register themselves". (#257)

### Changed

- `tests/conftest.py` exports an empty `DEADLINE_NAME`, so no existing test makes a waiter register in the real deadline state
  directory. (#257)
