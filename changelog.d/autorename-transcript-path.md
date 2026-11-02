### Fixed

- `autorename` named the wrong or a missing session ("no transcript for session <id>") when a Claude Code session started from a predecessor's environment (`/baton`, `/handoff`) inherited its `CLAUDE_CODE_SESSION_ID`; it now reads the session id from the owning Claude process's registry file (`~/.claude/sessions/<CLAUDE_PID>.json`, used only when its `pid` and `procStart` match the live process) and uses the variable only as a fallback (#259).
