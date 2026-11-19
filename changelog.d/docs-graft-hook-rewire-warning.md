### Changed

- `.claude/helpers/graft-hooks.cjs` (and its identical `.cursor/hooks/` copy) says in its header that running it by hand
  inside a repo with trail installed lets graft wire **that** repo — it rewrites `.claude/`, `.cursor/` and `AGENTS.md` —
  so it should be driven from a temp project, as `tests/test_graft_cursor_session_start.py` does. Comment only. (#814)
