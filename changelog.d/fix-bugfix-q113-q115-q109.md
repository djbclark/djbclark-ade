### Added

- `bin/review_bots.py` and `config/review-bots.toml`: added optional AND-paired `check_runs = [{ name = "...", app = "..." }]` matching and pinned `cursor-bugbot` (`cursor`) and `macroscope` (`macroscopeapp`) so outside workflow jobs cannot spoof `review_bot_pending` (#1015).

### Fixed

- `claude/hooks/bash_habits_gate.py`: shared the per-`(text, n)` memo table in `_closing_paren` so repeated/nested `$((` scans (e.g., `"echo " + "$((" * 2000`) run in linear time well under 1 s instead of hitting the 20 s fail-closed time budget (#1015).
- `claude/hooks/agent_footer_gate.py`: auto-prefixed derived report basenames starting with `report`/`summary`/`findings`/`analysis` with `task-` instead of denying, and made prompt-named basename denials report the refused path, matched word, and a safe sibling `Report path:` line (#1015).
