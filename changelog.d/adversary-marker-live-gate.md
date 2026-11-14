### Added

- `claude/hooks/adversary_marker_gate.py` (2026-11-14, am-01) is a Claude Code `PreToolUse` Bash hook, registered in `agents/claude/settings.json.tmpl`, that denies a `gh pr|issue create|edit|comment|review` or a `gh api` write to a `pulls`/`issues` endpoint whose text (`--body`, `-b`, `-f body=`, `--body-file`, `-F body=@file`, `--input`, `$(cat FILE)`, a heredoc body) carries a live `adversary-verdict:v1` APPROVE marker. It reads "live" with `bin/adversary_marker.py`'s own parser, so a BLOCK, a fenced or inline-code example, the docs template and a placeholder head pass; it fails open on bad stdin, other tools, unreadable bodies and its own errors. Contract, failure modes and the `ADVERSARY_MARKER_GATE_OFF=1` operator escape hatch in `docs/code-review.md` rule 14 (#724).

### Fixed

- `claude/agents/adversary.md` no longer tells the adversary to emit its `adversary-verdict` marker as a raw line "for the teammate to paste into the PR body", which contradicted `docs/code-review.md` rule 1 and AGENTS.md "Code review" item 1 and led a tendcf lead to paste a live APPROVE into a PR body with `gh pr edit`. The marker is now relayed inside a fenced block in the report, the PR body carries the verdict as prose, and the operator or an owner-authored path applies a live marker. `docs/code-review.md` rule 11 and `docs/review-boundary.md` say the same (#724).
