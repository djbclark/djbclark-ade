### Fixed

- `cow-pasture create` stopped handing out pastures whose dependencies were symlinks into the source checkout (2026-11-01: cow 0.1.10 links large dirs such as `node_modules/*` and `.venv/bin` into the source by default, and an `npm install` in a paseo pasture emptied ~392 package dirs of `~/src/paseo/node_modules`): it gained `--no-symlink` and a `cow materialise <source>/<name>` step, and it exits 1 without printing the path if any symlink still resolves into the source or another checkout `cow list --json` records (#228)

### Added

- Added `cow-pasture check <pasture-path>`, which lists the symlinks in a pasture that resolve into its source or another recorded checkout (exit 1 if any, 2 if the path is not a pasture in `cow list` or a directory in it is unreadable); `skills/cow-workspaces` gained how to check and fix an older pasture and the copied-venv caveat (#228)
