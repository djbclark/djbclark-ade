### Fixed

- `ade-worker-run`: `--cwd` was silently dropped when a worker was placed in an existing window (`paseo run --workspace` takes the agent's directory from the window and ignores `--cwd`, upstream getpaseo/paseo#9699), so a worker meant for a claimed worktree started in the window's repo. The launch is now refused when `--cwd` differs from the window's directory (the refusal says to pass the window's directory and give the worktree as an absolute path in the brief), and after every launch with `--cwd` the agent's `Cwd` is read back and a mismatch is reported loudly. (#687)
