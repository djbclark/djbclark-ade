### Fixed

- `cow-pasture create` no longer hands out a pasture whose dependencies are symlinks into the source checkout (2026-11-01: cow 0.1.10 links large dirs such as `node_modules/*` and `.venv/bin` into the source by default, and an `npm install` in a paseo pasture emptied ~392 package dirs of `~/src/paseo/node_modules`): it passes `--no-symlink`, runs `cow materialise <source>/<name>`, and exits 1 without printing the path if any symlink still resolves into the source or the source's own recorded source (#228)

### Added

- `cow-pasture check <pasture-path>` lists the symlinks in a pasture that resolve into its source (exit 1 if any, 2 if the path is not a pasture in `cow list`); `skills/cow-workspaces` says how to check and fix an older pasture (#228)
