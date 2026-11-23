### Added

- Wired `bin/load-watch` (`load-watch ci decide DIR local`, non-glob, non-`ci`-override scope) onto `approval-gate check --gate load-watch-ci-local` (binary from `ADE_APPROVAL_GATE_BIN` or `~/.local/bin/approval-gate`, 5 s timeout, scrubbed env, fail closed to `sudo-ask -k`; logged as `lw-local-approval-window`), pinned `bin/ade-merge-ready approve-post` strictly to `always-prompt` (`ade-merge-ready-approve-post`, with regression tests proving `-k` always prompts even with an open approval window), and updated `docs/approval-window.md` (#962)
