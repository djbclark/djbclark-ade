### Fixed

- `bin/ade-worker-run`: `--cwd` is `expanduser`ed where it is parsed, and the window check and the post-launch `Cwd` check compare directories with one `same_dir` helper (`os.path.samefile`, else the textual `normcase(realpath)` compare), so a `~` spelling or a case-differing spelling on macOS's case-insensitive volume is no longer a false mismatch (cq-41). (#742)
