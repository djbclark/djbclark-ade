### Fixed

- `bin/ade-git-guard`: `git worktree remove` is refused (`worktree remove: live process`, exit 77) while another live process has its cwd or an open file inside the target, claimed or not; the refusal lists pid, command and path. It fails open when `lsof` is missing, fails or times out; `--force` does not bypass it, `ADE_ALLOW_LIVE_WORKTREE_REMOVE=1` or the operator override does (#693).
