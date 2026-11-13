### Fixed

- `bin/ade-self-session handoff` now works from a session whose cwd is in no git repository (for example `~`): the transaction records
  `head: null`, the successor attests `head: null`, and `accept`/`finish` still fail if the cwd became (or stopped being) a repository. Only
  git's "not a git repository (or any ...)" discovery failure counts, and only when no `.git` entry (file, directory, symlink, unreadable)
  exists in the real cwd or any ancestor; a timeout, unborn HEAD, broken linked worktree or gitfile, unreadable `.git` or any other git
  failure still refuses, and git runs without any inherited `GIT_*` variable. (#0)
