### Security

- `ade-git-guard` refuses `stash show --output*` / `--out*` and `format-patch` `-o` / `--output*` / `--output-directory` (and plain `format-patch`, whose default is `format.outputDirectory` when set via `-c` / `GIT_CONFIG_*` / repo config, else cwd) when the output target is not inside the caller's active claimed workspace (O2 residual; rule `output-file`, exit 77). Unresolved `format.outputDirectory` fails closed. `format-patch --stdout` stays allowed. (#400)
- `output-file` validates every `--output` / `-o` destination independently (duplicate flags and `--output` + `-o` combinations), so an earlier foreign path cannot hide behind a later in-claim one (#400).
