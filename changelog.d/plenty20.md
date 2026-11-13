### Changed

- Codex's everyday-use quota gate `[routing].plenty_min` in `config/routing.toml` was lowered from 50 to 20 percent (operator
  2026-11-13: "change the codex gate quota from 50% to 20%"): codex takes judgment, code, bulk and mechanical slices
  while every codex window has at least 20% left (was 50%). The `[frontier]` floors in `config/gates.toml` are unchanged. (#628)
