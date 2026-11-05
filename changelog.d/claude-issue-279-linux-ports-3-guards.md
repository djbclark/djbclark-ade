### Added

- `coding-bot` falls back to the platform clipboard: pbcopy/pbpaste, wl-copy/wl-paste with `$WAYLAND_DISPLAY`, xclip then xsel with `$DISPLAY`. (#292)

### Changed

- `skill-everywhere` still uses `~/src/djbclark-ade/skills` when that checkout exists, and otherwise finds the skills dir from its own location (a linked worktree resolves to its primary checkout), so it works on hosts whose checkout lives elsewhere. (#292)
- macOS-only tools refuse with an explanatory exit 69 instead of failing late: `codium-ai`, `app-tamer-ab`, `paseo-set-model` without its Paseo Helper (was exit 1), and `acp-dispatch --detach`/`reap --install` without launchctl (they point to `paseo run`; acp-dispatch is replaced in D5). (#292)
