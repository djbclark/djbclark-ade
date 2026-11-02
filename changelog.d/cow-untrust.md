### Fixed

- `bin/cow-pasture remove` drops the pasture's seeded Claude Code trust entry from `~/.claude.json` (new `untrust` subcommand; an entry a
  session extended stays), and its usage names `--force` as the non-interactive removal. (#241)
