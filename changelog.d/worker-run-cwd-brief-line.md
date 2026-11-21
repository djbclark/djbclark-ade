### Fixed

- `ade-worker-run`: when a worker is placed in a directory other than the `--cwd` the brief is about (a launch into a box whose cwd is the repo's primary checkout, or a minted box), the brief the worker receives now carries one line before the delivery footer: `Your session starts in <primary checkout>; run every command from <worktree> (cd there or git -C); never edit or commit in <primary checkout>.` Before, only the launcher's stderr said so. A launch that is not moved (a case-variant spelling of `--cwd` included) gets no line. (#PR)
