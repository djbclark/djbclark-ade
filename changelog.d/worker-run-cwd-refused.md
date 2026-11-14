### Fixed

- `ade-worker-run`: `--cwd` was silently dropped when a worker was placed in an existing window (`paseo run --workspace` takes the agent's directory from the window and ignores `--cwd`, upstream getpaseo/paseo#9699), so a worker meant for a claimed worktree started in the window's repo. The launch is now refused when `--cwd` differs from the window's directory (a new `--window-middle` opens a window that takes the `--cwd`), and when the window's directory is unknown the launched agent's `Cwd` is checked afterwards and a mismatch is reported loudly. (#687)
