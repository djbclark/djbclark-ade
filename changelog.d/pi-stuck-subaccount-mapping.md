### Fixed

- `bin/ade-pi-stuck`: a pool that bills several accounts (OpenCode Go, Clinepass) now maps each aiuse reading to its named sub-account, so `clinepass-t-e` and `opencode-go-djbclark` are judged on their own headroom instead of reported as having no quota mapping. An account aiuse has no reading for (a bare `clinepass` or `opencode-go` provider, or `xai-oauth`) stays unmapped and is still reported rather than assumed healthy.
