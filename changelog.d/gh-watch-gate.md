### Added

- The Bash habits gate denies `gh run watch` and `gh pr checks --watch` unless `--interval`/`-i` is 60 or more, and warns on `xargs -P`/`parallel` around `gh` calls: four default-3 s watchers emptied the shared 5000/h GitHub quota for an hour on 2026-11-14. dispatch-footer item 26 and orchestration-practices rule 9 budget bulk GitHub API use (`gh api rate_limit` first, stop at remaining < 500, batch with GraphQL). (#672)
