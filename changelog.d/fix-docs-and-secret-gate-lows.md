### Fixed

- `claude/hooks/secret_read_gate.py`: fail closed to full filesystem glob analysis on quoted-delimiter heredoc pipelines when any inline shell assignment sets a sensitive execution-hook variable (`GIT_*`, `PATH`, `LD_*`, `DYLD_*`, `BASH_ENV`, `ENV`, `IFS`, `PYTHON*`) or when `sort` carries `--compress-program` (closing PR #951's carried R3-L1 and R3-L2 follow-ups), while keeping benign inline assignments such as `LC_ALL=C sort` fast (#957).
- `AGENTS.md`, `docs/approval-window.md`, `docs/orchestration-practices.md`, `skills/fan-out/SKILL.md`, `docs/code-review.md`, `docs/secret-deny.md`: update `approval-window` live-install status on `bigmac`, record the self-archive ruling and non-destructive archive path, and record the `PATH`-reorder test-fake hygiene rule (#957).
