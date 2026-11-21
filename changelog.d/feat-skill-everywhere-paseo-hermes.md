### Added

- `bin/skill-everywhere` links Paseo's daemon-synced skill (`~/.agents/skills/paseo`) into the Hermes skills dir as `paseo`,
  idempotently and without touching any Paseo-managed file (a foreign real dir or a missing source is left alone and reported),
  and `--check` exits 1 with an `error: paseo skill is missing on <tui>` line when `paseo` is absent from a live target
  (claude, codex/pi, hermes). (#871)

### Fixed

- `bin/skill-everywhere` no longer exits 1 because a foreign real dir sits at the name of a third-party (chrome-use) skill such
  as `canvas`: that is a note, while a collision with a public, private or site skill name still exits 1. (#871)
