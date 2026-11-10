### Added

- `bin/render-secret-deny` now writes an inactive Codex `[permissions.ade-secret-deny]` deny-read profile into
  `agents/codex/config.toml.tmpl` from `[codex] static` (workspace globs + `{{ .home }}` exact paths). Render does
  not set `default_permissions` or change `sandbox_mode`; live `~/.codex` apply stays order 11. Docs note
  openai/codex#22179 tracked early deny-glob docs that did not enforce — do not claim it landed (#0).
