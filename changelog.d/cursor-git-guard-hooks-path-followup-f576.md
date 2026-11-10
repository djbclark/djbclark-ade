### Security

- `ade-git-guard` `hooks-path` refuses a local/worktree `core.hooksPath` of `%(prefix)/…` (and any `%(…)` interpolation) instead of joining the literal onto cwd, matching Git 2.43's expansion rather than allowing planted stubs under `<cwd>/%(prefix)/…` (#0).
- Relative `core.hooksPath` while `--work-tree` / `GIT_WORK_TREE` is set is refused as ambiguous: Git joins relative hooks to cwd for `update-ref` but to the work tree for `commit` / `checkout` / `merge` (#0).
- `filter-branch` joins `_HOOK_GUARDED_SUBS`, so a non-ade local `hooksPath` (e.g. `/dev/null`) can no longer rewrite claimed branch tips past the claim hooks (#0).
