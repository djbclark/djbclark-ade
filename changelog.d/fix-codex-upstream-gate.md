### Added

- `agents/codex/config.toml.tmpl` registers the CFEngine upstream write gate for native Codex hooks: after applying the template and trusting it, Codex shell calls that write to a `cfengine` or `NorthernTechHQ` upstream are denied, the same protection the Claude hook (`claude/hooks/upstream_review_gate.py`) already gives. Contract and limits in `docs/upstream-review-gate.md`. (#788)
