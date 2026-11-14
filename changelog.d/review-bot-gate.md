### Added

- `bin/review-bot-findings` and `config/review-bots.toml`: a must-triage gate for listed AI reviewer bots (CodeRabbit, Codex, Greptile, Cursor Bugbot, Copilot code review): unresolved bot threads and actionable review bodies must be fixed or answered with a reason by `djbclark`'s account; every actionable review body counts (a later 0-count review does not erase an earlier one); a running bot check run or commit status (`status_contexts`) blocks as pending; a repo adds or drops bots in `.github/ade-review-bots.toml` on its default branch; the bots' text stays data. (#713)

### Changed

- `bin/ade-merge-ready` classes `review_bot_untriaged`, `review_bot_pending` and `review_bot_unknown` stop a tip that would be `merge_now`, and `merge-now` re-reads the bot gate on the exact head before `gh pr merge`; review rule 9 no longer treats Codex as advisory. (#713)
