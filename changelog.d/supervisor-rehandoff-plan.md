### Added

- `bin/ade-supervisor-scan`: each scan now writes the re-handoff it would perform for a stuck Pi agent (who, which exhausted account, which healthy alternative) and logs it. The default is a dry run that archives and relaunches nothing. `ADE_SUPERVISOR_REHANDOFF=live` calls `bin/ade-supervisor-rehandoff`, which is not yet built and refuses, so no agent moves until the ade-self-session handoff path is wired (Carried 70). (#822)
