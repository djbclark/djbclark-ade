### Changed

- `claude/hooks/peer_trust_gate.py`: a peer message from an unlisted (archived or short-lived, e.g. Herald) agent or from a remote server is
  now believed and acted on like a listed one instead of being labelled "UNVERIFIED: ask the operator" (operator, 2026-11-14: "always believe
  thing we hear from other agents unless that agent is external-security-sensitive"); the note says a reply to an archived id is blocked by
  `archived_send_gate`. New `config/peer-trust.toml` `[sensitive]` (exact `ids`, case-insensitive `title_patterns`: `injection`, `triage`, `review-pr`,
  `pr-review`, `adversary`, `gh-watch`) and the Paseo agent label `ade.kind=external-review` (read from the agent record) name the one
  exception, a sender that judges untrusted GitHub artifacts for prompt injection: it is not believed automatically, its message is
  evidence to check, never an instruction. AGENTS.md Trust, docs/peer-trust.md, docs/threat-model.md section 5 item 9
  and docs/code-review.md rule 13 updated. (#703)
