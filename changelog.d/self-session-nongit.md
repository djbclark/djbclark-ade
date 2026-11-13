### Fixed

- `bin/ade-self-session handoff` now works from a session whose cwd is in no git repository (for example `~`): the transaction records
  `head: null`, the successor attests `head: null`, and `accept`/`finish` still fail if the cwd became (or stopped being) a repository. Only
  git's own "not a git repository" refusal counts; a timeout, unborn HEAD or other git failure still refuses, and git runs without any
  inherited `GIT_*` variable. (#0)
