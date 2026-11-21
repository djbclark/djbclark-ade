### Added

- Model families in routing: a `[[service]].models` id with `*` (`gpt-*-astra`, `gpt-*-sol`, `gpt-*-luna`, `gemini-*-neon-high`, `gemini-*-argon-high`) resolves at plan/route time to the newest id `paseo provider models` lists, by version order (6.2 > 6.1 > 6, never lexical), with no eval gate; optional `[routing.model_holds]`, a last-resolved fallback in state, `route_agent.py models`, and a change line in `show` (`bin/model_family.py`). (#PR)
- New routing kind `ui-automation` (claude r1 Sonnet 5.5 high, antigravity-neon r2, codex r4) and `skills/model-routing` C8b: the split between `code`, `ui-automation` and the Coding bot. (#PR)

### Changed

- `antigravity-neon` is a normal pool (operator 2026-11-21): frontier r3, judgment r2, code r13, research r11 at `neon-high`, no `fallback_after`, no last-resort research rule; `codex` code rank 13 (ahead of `cursor-auto`), `zai` loses `code`, code quality band 10 -> 8; Neon and Argon notes now say 512K context and Ultra 20x, and `docs/model-routing.md` B7/B7a/H3 follow. (#PR)
- `docs/queue.md` item 65: trial Gemini 4 Hydrogen and Orchestrator after the Google pool settles. (#PR)
