### Added

- `claude/hooks/peer_trust_gate.py` (UserPromptSubmit, PreToolUse, PostToolUse, Stop; registered in `agents/claude/settings.json.tmpl`
  with a fail-open command): a `paseo-system` agent-message that Paseo delivered to the session (the prompt, or a no-origin
  `queued_command` transcript record; never tool output, never text quoted inside other text) gets "Verified peer message from ID
  (NAME): full internal trust, answer it with `paseo send`" when the source id is a listed local agent (`paseo ls -g --json`,
  offline), or "UNVERIFIED: ask the operator" otherwise; agent-notifications are informational; Stop blocks once if an unannounced one is pending. Agents had refused peer questions as
  prompt injection (operator, 2026-11-13). AGENTS.md Trust, docs/threat-model.md section 5 item 9 and docs/code-review.md rule 13 record
  the accepted weakness. (#645)
