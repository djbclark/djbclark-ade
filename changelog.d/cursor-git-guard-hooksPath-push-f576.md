### Security

- `ade-git-guard` refuses `push` and ref-writing subcommands when the repository's local/worktree `core.hooksPath` is set to `/dev/null` or any path that is not the ade-git-guard stubs directory (rule `hooks-path`, exit 77; §10 residual). An ade-stub `hooksPath` stays allowed; ordinary non-ref-writing calls with a non-ade local `hooksPath` stay allowed (#432).

### Fixed

- Relative local `core.hooksPath` values are resolved from the work-tree root (bare: the git dir) where Git runs hooks, not from the common Git directory (#432).
