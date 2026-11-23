### Fixed

- Judged `find -exec` targets across all `REMOVER_NAMES` (`rimraf`, `rip`, `del-cli`, `trash`, `trash-put`), plus fed `mv`, recursive `chmod`/`chown`/`chgrp`/`chflags`, `git clean`, and `rsync --delete` across `find -exec`, `xargs`, and `parallel` in `bin/ade_approval_window.py` (#953).
- Rotated the parent send cursor in `seen.json` across capped `ade-subagent-stalls` runs, stopped further probes in a run after an in-process send-guard inspect failure/timeout, and ranked brief-sourced report links strictly below direct prompt `Report:` labels in `bin/ade_subagent_stalls.py` and `docs/subagent-stalls.md` (#953).
- Pinned last-trailer-only matching for multi-trailer final paragraphs in `tests/test_ade_fork_picks.py` (#953).
- Preserved inferred `thinking` on active `[routing.model_holds]` for legacy `-<effort>` families and kept `newest_thinking` when persisting `route-model-resolved.json`, clarified `[dispatch].frontier_slice_models` comments, and updated `skills/model-routing/SKILL.md` (`C7`, `C7a`) to separated-effort Antigravity model specs (#953).
