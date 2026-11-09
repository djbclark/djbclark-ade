### Fixed

- Closed the remaining code-fixable `ade-update` LOWs from PR 20: `--check` casefolds collisions when `core.ignorecase` is true, `git status` uses `--ignored=matching`, `run()` decodes helper/git output as UTF-8 with replacement, `check_skills`/`link_skills` are pinned to `helper_env`, and `skill-everywhere`'s grokbot render cleans its mktemp dir and no longer uses `eval`+`&&` for the copy swap (#407).
