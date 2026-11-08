### Fixed

- Imported the assigned worktree as an explicit local Paseo workspace when dispatching child agents, preventing inherited parent directories from overriding `-C` (#304).
- Preserved the returned `paseo_cwd` and warned about missing or mismatched placement without stopping the paid agent (#304).
