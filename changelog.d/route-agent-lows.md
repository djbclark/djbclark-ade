### Fixed

- `bin/route_agent.py`: two `--available` rows of one pool (two accounts) no longer let the measured one open the plenty gate while the other reads expired: windows fold per account (`_merge_windows`) and an unknown row adds an `(unmeasured)` None window; an `error` account of the snapshot fold (a collection or auth error) now counts as an unmeasured account instead of being skipped (the `--available` fold gets the same guard, defensive: aiuse emits no error row there today). (#708)

### Added

- `config/routing.toml`: `[dispatch.repo_overrides.REPO] frontier_order` declares a repository's frontier reviewer order, and `route_agent.py plan --kinds frontier --repo REPO` sorts the pools that already passed every gate by it (tendcf: `codex`, `claude`, `antigravity-argon`), so a claude burn-first bonus no longer puts Fable ahead of a usable Astra there; a name that is no service, a repeated or empty list, or an upper-case repo key fails the policy load (legacy file read and runtime config alike). (#708)
