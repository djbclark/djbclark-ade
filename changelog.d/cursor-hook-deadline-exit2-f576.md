### Changed

- Documented that site-djbclark `bin/hook-deadline` forwards the child's exit code (including exit 2) when the command
  finishes before the deadline, and only exits 0 silently on a deadline hit: closed the 2026-11-04 open question in
  `docs/post-edit-check.md` and the matching residual on queue Carried #1 (verified 2026-11-09/10 against that script). (#409)
