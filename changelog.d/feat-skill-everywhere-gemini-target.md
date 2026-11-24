### Added

- Added `gemini` (`~/.gemini/skills`) as a first-class link target in `bin/skill-everywhere` (detected when `~/.gemini` exists as a directory or `gemini`/`antigravity` is available via `PATH`/`SKILL_EVERYWHERE_BIN_DIR`), deduplicated `retired_step()` so `~/.gemini/skills` is scanned once through `targets`, skipped `gemini` in `paseo_step()` because Paseo syncs Antigravity's copy under `~/.gemini/config/skills/paseo`, and documented the target in `docs/skill-everywhere.md` (#972).
