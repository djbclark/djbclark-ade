### Added

- Bash habits gate denies a job-control background `&` (`cmd &`, `nohup cmd &`, `( cmd & )`): the reason points at the Bash tool's `run_in_background` parameter and says nothing ran; `&&`, redirections (`2>&1`, `&>`), quoted text, heredocs and comments pass. `docs/bash-habits-gate.md`. (#752)
