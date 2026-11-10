### Changed

- `pytest-linux` also short-circuits (keeps the check green, skips the ~11 min suite) when the diff is only root instruction/prose files (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `README.md`, `LICENSE`) in addition to `docs/**` / changelog paths (#TBD).
