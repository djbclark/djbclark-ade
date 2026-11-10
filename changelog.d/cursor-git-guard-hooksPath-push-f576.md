### Security

- `ade-git-guard` refuses `push`, `fetch`/`fetch-pack`/`remote update`, and ref-writing subcommands when the repository's local/worktree `core.hooksPath` is set to `/dev/null` or any path that is not the ade-git-guard stubs directory (rule `hooks-path`, exit 77; §10 residual). An ade-stub `hooksPath` stays allowed only when the directory holds the canonical installed stubs (they must invoke `HOOKS_SRC`; a forged marker+exit0 script is refused); ordinary non-ref-writing calls with a non-ade local `hooksPath` stay allowed (#432).

### Fixed

- Relative local `core.hooksPath` values are resolved from the process cwd after every `-C` (with a leading `~/` expanded), matching Git's hook-lookup semantics, not from `--work-tree` / `show-toplevel` or the common Git directory (#432).
