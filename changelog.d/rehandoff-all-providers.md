### Fixed

- `bin/ade-pi-stuck`: a lead in a hard `error` is flagged stuck on any provider, not only Pi. A Codex or Claude lead stuck in error was invisible to the automatic re-handoff (Carried 104). A healthy non-Pi agent is still ignored. Detection only: re-handing a non-Pi agent needs the native fallback, since the routed handoff admits Pi adapters only. (#832)
