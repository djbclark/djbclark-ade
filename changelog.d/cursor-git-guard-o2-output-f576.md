### Security

- `ade-git-guard` refuses `stash show --output*` / `--out*` and `format-patch` `-o` / `--output*` / `--output-directory` (and plain `format-patch`, which writes into cwd) when the output target is not inside the caller's active claimed workspace (O2 residual; rule `output-file`, exit 77). `format-patch --stdout` stays allowed. (#400)
- `output-file` validates every `--output` / `-o` destination independently (duplicate flags and `--output` + `-o` combinations), so an earlier foreign path cannot hide behind a later in-claim one (#400).
