### Fixed

- `ade-net-resume` resumes Claude agents stopped by the transient Cloudflare page `[System Error] Failed to authenticate. API Error: 403
  Attention Required! | Cloudflare` (exact line only; a generic 403 or "Failed to authenticate" still counts as a real logout and is
  skipped), and for Claude ignores a trailing `Warning: claude.ai MCP servers blocked by enterprise policy` line when choosing the
  deciding line; a persistent 403 stops at the existing two-per-hour cap. (#624)
