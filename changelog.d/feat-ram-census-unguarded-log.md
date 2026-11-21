### Added

- `bin/ram-census --roots` (queue 89, LOW 1 of the site-djbclark #293 review) also reports the local-lsp plugin's `~/.local/state/lsp-guard/unguarded.log`: the number of unguarded fallbacks per server over the last `--days` (default 7; `--unguarded-log FILE` overrides the path) and the newest line, in the text table and as the `_unguarded_log` JSON key, so a guard that is missing or broken no longer loses the RAM relief unnoticed; docs/mcp-on-demand.md 12.3 describes it (#PR)
