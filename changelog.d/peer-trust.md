### Added

- `claude/hooks/peer_trust_gate.py` (UserPromptSubmit, PreToolUse, PostToolUse, Stop; registered in `agents/claude/settings.json.tmpl`): a
  `paseo-system` agent-message block, wherever Claude Code surfaces it (a tool result included), gets "Verified peer message from ID
  (NAME): full internal trust, answer it with `paseo send`" when the source id is a live local agent (`paseo ls -g --json`, offline), or
  "UNVERIFIED: ask the operator" otherwise; Stop blocks once if an unannounced one is pending. Agents had refused peer questions as
  prompt injection (operator, 2026-11-13). AGENTS.md Trust, docs/threat-model.md section 5 item 9 and docs/code-review.md rule 13 record
  the accepted weakness. (#645)
