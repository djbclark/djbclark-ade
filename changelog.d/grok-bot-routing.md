### Changed

- `skills/model-routing/SKILL.md` and `skills/tell-coding-bot/SKILL.md`: record the operator ruling (2026-11-21) that the Grok Bot "Coding" is not an ordinary delegation target — take coding work on yourself, in sub-agents where appropriate — and is only the try-first destination for tasks that need real UI/browser interaction. The route is not working today (nothing exists at `~/.local/bin/coding-bot`), so nothing is ever claimed sent. (#848)
- `tests/test_skill_frontmatter.py`: every `skills/*/SKILL.md` frontmatter must parse as YAML with a name and description (the `tell-coding-bot` description is now quoted, since an unquoted `: ` made it invalid). (#848)
