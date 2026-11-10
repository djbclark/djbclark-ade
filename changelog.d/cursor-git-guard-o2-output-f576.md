### Security

- `ade-git-guard` refuses `stash show --output*` / `--out*` and `format-patch` `-o` / `--output*` / `--output-directory` (and plain `format-patch`, whose default is `format.outputDirectory` when set via `-c` / `GIT_CONFIG_*` / repo config, else cwd) when the output target is not inside the caller's active claimed workspace (O2 residual; rule `output-file`, exit 77). Unresolved `format.outputDirectory` fails closed. `format-patch --stdout` stays allowed. (#400)
- `output-file` validates every `--output` / `-o` destination independently (duplicate flags and `--output` + `-o` combinations), so an earlier foreign path cannot hide behind a later in-claim one (#400).
- `format-patch` short clusters honor value-taking shorts (`-v`/`-S`/`-I`/`-G`/`-O`): `-vo.` is reroll-count `o.`, not `-o .`, so `format.outputDirectory` is still checked (#400).
- The `format.outputDirectory` probe clears legacy `GIT_CONFIG` (format-patch ignores it; `git config` does not), so `GIT_CONFIG=/dev/null` cannot hide a repo/global value (#400).
- Relative `stash show --output` / `--out` paths resolve against the effective work tree (`--work-tree` / `GIT_WORK_TREE` / `core.worktree`), not only the call cwd (#400).
